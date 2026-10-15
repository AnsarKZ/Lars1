"""The data model.

  dim_product      one row per SKU (costs, fees, lead time) from file 04
  dim_marketplace  VAT, currency and stock region per marketplace
  fact_sales_day   day x marketplace x SKU, all money in net EUR (files 01 + 05)
  fact_ads_day     day x campaign, spend and ad sales in net EUR (files 02 + 05)
  fact_stock_week  count date x region x SKU (file 03)
  fact_week        week x marketplace x SKU: the one table all KPIs come from

Money rules (agreed): everything in net EUR. UK first converted with the
monthly average rate of the transaction month, then VAT removed. Amazon's
commission is charged on the gross price, so it is computed on gross and then
carried as a net cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ATTRIBUTION_DAYS, DATA_DIR, MARKETPLACES, WEEKS_PER_MONTH
from .load import (DataQuality, load_ads, load_fx, load_products, load_sales,
                   load_stock)


@dataclass
class Model:
    dim_product: pd.DataFrame
    dim_marketplace: pd.DataFrame
    fact_sales_day: pd.DataFrame
    fact_ads_day: pd.DataFrame
    fact_stock_week: pd.DataFrame
    fact_week: pd.DataFrame
    weeks: list[pd.Timestamp]          # Monday of every complete week, ascending
    dq: DataQuality

    @property
    def reporting_week(self) -> pd.Timestamp:
        return self.weeks[-1]


def _monday(d: pd.Series) -> pd.Series:
    return d - pd.to_timedelta(d.dt.weekday, unit="D")


def _fx_factor(currency: pd.Series, dates: pd.Series, fx: dict[str, float]) -> np.ndarray:
    month = dates.dt.strftime("%Y-%m")
    return np.where(currency == "GBP", month.map(fx).astype(float), 1.0)


def build(data_dir: Path = DATA_DIR) -> Model:
    dq = DataQuality()
    products = load_products(dq, data_dir)
    sales = load_sales(dq, data_dir)
    ads = load_ads(dq, products, data_dir)
    stock = load_stock(dq, data_dir)
    months = set(sales.date.dt.strftime("%Y-%m")) | set(ads.date.dt.strftime("%Y-%m"))
    fx = load_fx(dq, months, data_dir)

    mp = pd.DataFrame([{"marketplace": k, "vat": v[0], "currency": v[1], "region": v[2]}
                       for k, v in MARKETPLACES.items()])
    vat = dict(zip(mp.marketplace, mp.vat))
    cost = products.set_index("sku")

    # ---------------------------------------------------------- sales, net EUR
    s = sales.copy()
    s["week"] = _monday(s.date)
    gross_eur = s.ordered_product_sales * _fx_factor(s.currency, s.date, fx)
    s["net_revenue"] = gross_eur / (1 + s.marketplace.map(vat))
    s["cogs"] = s.units_ordered * s.sku.map(cost.landed_eur)                 # incl. freight & customs
    s["referral_fee"] = gross_eur * s.sku.map(cost.referral_rate)            # 15 % of the GROSS price
    s["fba_fee"] = s.units_ordered * s.sku.map(cost.fba_fee_eur)
    s["cm1"] = s.net_revenue - s.cogs - s.referral_fee - s.fba_fee
    s["bb_weighted"] = s.buy_box_pct * s.sessions
    fact_sales_day = s[["date", "week", "marketplace", "sku", "sessions", "units_ordered",
                        "net_revenue", "cogs", "referral_fee", "fba_fee", "cm1", "bb_weighted",
                        "buy_box_pct"]].rename(columns={"units_ordered": "units"})

    # ------------------------------------------------------------ ads, net EUR
    a = ads.copy()
    a["week"] = _monday(a.date)
    f = _fx_factor(a.currency, a.date, fx)
    a["ad_spend"] = a.spend * f                                              # spend is already net
    a["ad_sales"] = a.sales_7d * f / (1 + a.marketplace.map(vat))            # ad sales are gross
    fact_ads_day = a[["date", "week", "marketplace", "sku", "campaign_name", "targeting_type",
                      "daily_budget", "impressions", "clicks", "ad_spend", "ad_sales", "orders_7d"]
                     ].rename(columns={"orders_7d": "ad_orders"})

    # ------------------------------------------------------------------ weekly
    keys = ["week", "marketplace", "sku"]
    w = fact_sales_day.groupby(keys)[["sessions", "units", "net_revenue", "cogs", "referral_fee",
                                      "fba_fee", "cm1", "bb_weighted"]].sum()
    w = w.join(fact_ads_day.groupby(keys)[["ad_spend", "ad_sales", "impressions", "clicks", "ad_orders"]].sum(),
               how="left").fillna(0.0)
    w = w.reset_index()
    weeks = sorted(w.week.unique())
    # only complete Monday-Sunday weeks
    days = fact_sales_day.groupby("week").date.nunique()
    weeks = [x for x in weeks if days[x] == 7]
    w = w[w.week.isin(weeks)]

    # ---------------------------------------------------------- storage (CM3)
    # Count on Monday = stock after Sunday. Week W is bracketed by the counts on W and W+7.
    rows = []
    for (region, sku), g in stock.groupby(["region", "sku"]):
        g = g.set_index("count_date").available
        for wk in weeks:
            start, end = g.get(wk), g.get(wk + pd.Timedelta(days=7))
            if start is None or end is None:
                continue
            avg = (start + end) / 2
            rows.append({"week": wk, "region": region, "sku": sku,
                         "storage_cost": avg * cost.storage_eur_month[sku] / WEEKS_PER_MONTH})
    storage = pd.DataFrame(rows)
    w["region"] = w.marketplace.map(dict(zip(mp.marketplace, mp.region)))
    share_base = w.groupby(["week", "region", "sku"]).units.transform("sum")
    n_mp = w.groupby(["week", "region", "sku"]).units.transform("size")
    # EU pool cost is split across DE/FR/IT by units sold that week (equal split if none sold)
    w["storage_share"] = np.where(share_base > 0, w.units / share_base.replace(0, np.nan), 1 / n_mp)
    w = w.merge(storage, on=["week", "region", "sku"], how="left")
    w["storage_cost"] = (w.storage_cost.fillna(0.0) * w.storage_share)
    w["cm2"] = w.cm1 - w.ad_spend
    w["cm3"] = w.cm2 - w.storage_cost
    w = w.drop(columns="storage_share")
    dq.add("model", "Storage cost (CM3) is an estimate", "info",
           "Monthly fee x average of the two weekly counts; EU pool split by units sold. "
           "Real storage billing is not in the data.")

    # -------------------------------------------- stock reconciliation check
    sold = (fact_sales_day.assign(region=fact_sales_day.marketplace.map(dict(zip(mp.marketplace, mp.region))))
            .groupby(["region", "sku", "week"]).units.sum())
    stk = stock.sort_values("count_date").copy()
    stk["prev"] = stk.groupby(["region", "sku"]).available.shift()
    stk["prev_inbound"] = stk.groupby(["region", "sku"]).inbound.shift()
    stk["sold"] = [sold.get((r, k, d - pd.Timedelta(days=7)), np.nan)
                   for r, k, d in zip(stk.region, stk.sku, stk.count_date)]
    received = stk.available - stk.prev + stk.sold
    quiet = (stk.prev_inbound == 0) & stk.sold.notna()
    resid = received[quiet].abs()
    worst = stk.loc[resid.idxmax()]
    arrived = stk.prev_inbound.gt(0) & stk.inbound.eq(0) & stk.sold.notna()
    delivery_gap = ((received[arrived] - stk.prev_inbound[arrived]).abs()
                    / stk.prev_inbound[arrived]).max()
    dq.add("03 FBA stock", "Stock change = sales + deliveries", "ok",
           f"Weekly stock moves match units sold (median gap {resid.median():.0f} units). "
           f"Largest gap: {resid.max():.0f} units unannounced for {worst.sku} {worst.region} "
           f"(count {worst.count_date:%d.%m.}). Deliveries match 'inbound' within "
           f"{delivery_gap:.0%}.")

    attr_open = fact_ads_day.date.max() - pd.Timedelta(days=ATTRIBUTION_DAYS - 1)
    dq.add("02 ads", "Ad sales still being credited", "info",
           f"Clicks from {attr_open:%d.%m.} on can still turn into credited sales (7-day window, "
           "export on 28.09.). ACoS for the reporting week reads too high; ad status uses the "
           "4 weeks before it.")

    return Model(products, mp, fact_sales_day, fact_ads_day, stock, w.reset_index(drop=True),
                 [pd.Timestamp(x) for x in weeks], dq)

