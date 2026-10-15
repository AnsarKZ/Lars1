"""Status rules: which product in which marketplace needs attention, and why.

Rules run on fixed windows (independent of the period selector) so a status
does not flip when someone clicks 1W vs 13W. Every rule has a minimum volume
so thin data never turns a cell red.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import RULES as R
from .kpis import summarize, window
from .model import Model

LEVEL_RANK = {"ok": 0, "watch": 1, "critical": 2}


@dataclass
class Signal:
    marketplace: str
    sku: str
    rule: str
    level: str      # watch | critical
    kpi: str
    text: str


def stock_status(m: Model) -> pd.DataFrame:
    """Latest count per stock region and SKU, with cover and lead time."""
    last = m.fact_stock_week.count_date.max()
    st = m.fact_stock_week[m.fact_stock_week.count_date == last].copy()
    region_of = dict(zip(m.dim_marketplace.marketplace, m.dim_marketplace.region))
    fw = m.fact_week.assign(region=m.fact_week.marketplace.map(region_of))
    end = len(m.weeks) - 1
    recent = window(fw, m.weeks, end, R["rate_weeks"])
    rate = recent.groupby(["region", "sku"]).units.sum() / R["rate_weeks"]
    cm2_unit = summarize(recent, ["region", "sku"]).cm2_unit
    p = m.dim_product.set_index("sku")
    st["rate_week"] = [rate.get((r, s), 0.0) for r, s in zip(st.region, st.sku)]
    st["cm2_unit"] = [cm2_unit.get((r, s), np.nan) for r, s in zip(st.region, st.sku)]
    st["lead_weeks"] = st.sku.map(p.lead_time_days) / 7
    st["storage_month"] = st.available * st.sku.map(p.storage_eur_month)
    with np.errstate(divide="ignore"):
        st["cover_weeks"] = np.where(st.rate_week > 0, st.available / st.rate_week, np.inf)
        st["cover_incl_inbound"] = np.where(st.rate_week > 0,
                                            (st.available + st.inbound) / st.rate_week, np.inf)
    st["stock_level"] = "ok"
    crit = (st.cover_weeks < st.lead_weeks) & (st.inbound == 0)
    watch = st.cover_incl_inbound < st.lead_weeks + R["cover_watch_buffer_weeks"]
    over = st.cover_weeks > R["overstock_weeks"]
    st.loc[watch | over, "stock_level"] = "watch"
    st.loc[crit, "stock_level"] = "critical"
    st["stock_issue"] = np.select([crit, watch, over], ["stock-out", "low cover", "overstock"], "")
    # Units we cannot sell between running out and the next delivery (ordered today)
    st["weeks_short"] = np.where(crit, st.lead_weeks - st.cover_weeks, 0.0)
    st["units_at_risk"] = st.weeks_short * st.rate_week
    st["cm2_at_risk"] = st.units_at_risk * st.cm2_unit
    return st.reset_index(drop=True)


def evaluate(m: Model) -> tuple[list[Signal], pd.DataFrame]:
    fw, weeks = m.fact_week, m.weeks
    end = len(weeks) - 1
    signals: list[Signal] = []
    region_of = dict(zip(m.dim_marketplace.marketplace, m.dim_marketplace.region))
    stock = stock_status(m).set_index(["region", "sku"])

    this_w = summarize(window(fw, weeks, end, 1), ["marketplace", "sku"])
    prev_w = summarize(window(fw, weeks, end - 1, 1), ["marketplace", "sku"])
    base4 = summarize(window(fw, weeks, end - 1, 4), ["marketplace", "sku"])   # 4 weeks before
    last4 = summarize(window(fw, weeks, end, R["cm2_window_weeks"]), ["marketplace", "sku"])
    ads4 = summarize(window(fw, weeks, end - 1, R["acos_window_weeks"]), ["marketplace", "sku"])

    for (mp, sku), row in last4.iterrows():
        # --- stock (region level, shown on every marketplace of the region)
        s = stock.loc[(region_of[mp], sku)]
        if s.stock_level != "ok":
            if s.stock_issue == "stock-out":
                text = (f"{s.available:,} units left in {region_of[mp]} ≈ {s.cover_weeks:.1f} weeks; "
                        f"reorder takes {s.lead_weeks:.1f} weeks, nothing inbound")
            elif s.stock_issue == "overstock":
                text = (f"{s.cover_weeks:.0f} weeks of stock in {region_of[mp]} "
                        f"(EUR {s.stock_value_eur:,.0f} tied up)")
            else:
                text = (f"Cover incl. inbound {s.cover_incl_inbound:.1f} weeks vs reorder time "
                        f"{s.lead_weeks:.1f} weeks")
            signals.append(Signal(mp, sku, "stock", s.stock_level, "cover_weeks", text))

        # --- buy box: last two weeks
        if (mp, sku) in this_w.index and (mp, sku) in prev_w.index:
            t, p = this_w.loc[(mp, sku)], prev_w.loc[(mp, sku)]
            if t.sessions >= R["min_sessions_week"] and p.sessions >= R["min_sessions_week"]:
                if t.buy_box < R["buybox_critical"] and p.buy_box < R["buybox_critical"]:
                    signals.append(Signal(mp, sku, "buy_box", "critical", "buy_box",
                                          f"Buy box {t.buy_box:.0f} % (prev. week {p.buy_box:.0f} %): "
                                          "another seller gets most of our sales"))
                elif t.buy_box < R["buybox_watch"]:
                    signals.append(Signal(mp, sku, "buy_box", "watch", "buy_box",
                                          f"Buy box {t.buy_box:.0f} %"))

        # --- CM2 over the last 4 weeks
        if row.net_revenue >= R["min_net_revenue_4w"] and row.cm2 < 0:
            signals.append(Signal(mp, sku, "cm2", "critical", "cm2",
                                  f"CM2 EUR {row.cm2:,.0f} in 4 weeks ({row.cm2_pct:.0f} % of net revenue)"))

        # --- ACoS vs break-even, 4 weeks ending the week before (attribution complete)
        if (mp, sku) in ads4.index:
            a = ads4.loc[(mp, sku)]
            if a.ad_spend >= R["min_ad_spend_4w"] and a.acos > a.be_acos * R["acos_margin"]:
                signals.append(Signal(mp, sku, "acos", "watch", "acos",
                                      f"ACoS {a.acos:.0f} % above break-even {a.be_acos:.0f} %: "
                                      f"ad-driven sales lose money"))

        # --- conversion and revenue vs own 4-week baseline
        if (mp, sku) in this_w.index and (mp, sku) in base4.index:
            t, b = this_w.loc[(mp, sku)], base4.loc[(mp, sku)]
            if t.sessions >= R["min_sessions_cvr"] and b.cvr > 0 and t.cvr < (1 - R["cvr_drop"]) * b.cvr:
                signals.append(Signal(mp, sku, "cvr", "watch", "cvr",
                                      f"Conversion {t.cvr:.1f} % vs {b.cvr:.1f} % (4-week avg.)"))
            avg = b.net_revenue / 4
            if avg >= R["min_revenue_week_avg"] and t.net_revenue < (1 - R["revenue_drop"]) * avg:
                signals.append(Signal(mp, sku, "revenue", "watch", "net_revenue",
                                      f"Net revenue EUR {t.net_revenue:,.0f} vs EUR {avg:,.0f}/week (4-week avg.)"))

    status = (pd.DataFrame([s.__dict__ for s in signals])
              if signals else pd.DataFrame(columns=["marketplace", "sku", "rule", "level", "kpi", "text"]))
    return signals, status


def cell_level(status: pd.DataFrame, mp: str, sku: str) -> str:
    s = status[(status.marketplace == mp) & (status.sku == sku)]
    if s.empty:
        return "ok"
    return max(s.level, key=LEVEL_RANK.get)
