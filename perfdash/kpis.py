"""Central KPI definitions. The dashboard, the README table and the tests all
read from KPI_DEFINITIONS, so a KPI means the same thing everywhere."""
from __future__ import annotations

import numpy as np
import pandas as pd

ADDITIVE = ["sessions", "units", "net_revenue", "cogs", "referral_fee", "fba_fee", "cm1",
            "bb_weighted", "ad_spend", "ad_sales", "impressions", "clicks", "ad_orders",
            "storage_cost", "cm2", "cm3"]

# key: (label, unit, formula in words, why it is on the dashboard)
KPI_DEFINITIONS = {
    "net_revenue": ("Net revenue", "EUR", "Customer price in EUR (UK at monthly rate) ÷ (1 + VAT of the country)",
                    "Size of the business without VAT"),
    "cogs": ("Landed cost", "EUR", "Units × landed cost (purchase + freight & customs)",
             "Product cost"),
    "amazon_fees": ("Amazon fees", "EUR", "15 % commission on the gross price + FBA fee per unit",
                    "What Amazon keeps"),
    "cm1": ("Contribution margin 1 (CM1)", "EUR", "Net revenue − landed cost − Amazon fees",
            "What the product earns before marketing"),
    "ad_spend": ("Ad spend", "EUR", "Sponsored Products spend in EUR (already net)",
                 "Marketing investment"),
    "cm2": ("Contribution margin 2 (CM2)", "EUR", "CM1 − ad spend", "Headline: what is left after ads"),
    "storage_cost": ("Storage (est.)", "EUR",
                     "Storage fee per unit and month × average stock, EU pool split by units sold",
                     "Cost of holding stock; real billing not in data"),
    "cm3": ("Contribution margin 3 (CM3)", "EUR", "CM2 − storage (estimated)", "Shows the cost of slow movers"),
    "cm1_pct": ("Contribution margin 1 %", "%", "CM1 ÷ net revenue", "Product margin before marketing"),
    "cm2_pct": ("Contribution margin 2 %", "%", "CM2 ÷ net revenue", "Margin quality"),
    "cm3_pct": ("Contribution margin 3 %", "%", "CM3 ÷ net revenue", "Margin after holding stock"),
    "cost_ratios": ("Cost ratios", "%", "Landed cost, Amazon fees, ads and storage each ÷ net revenue",
                    "Explain why a margin % moved (CM2 % bridge)"),
    "per_week": ("€ per week", "EUR", "Period total ÷ number of weeks",
                 "Makes periods of different length comparable"),
    "cm2_unit": ("Contribution margin 2 per unit", "EUR", "CM2 ÷ units", "Comparable across countries"),
    "tacos": ("TACoS", "%", "Ad spend ÷ total net revenue", "How much the business leans on ads"),
    "acos": ("ACoS (net)", "%", "Ad spend ÷ net ad sales. ≈ Amazon console figure × (1 + VAT)",
             "Ad efficiency"),
    "be_acos": ("Break-even ACoS", "%", "Contribution margin 1 ÷ net revenue: above this every ad-driven sale loses money",
                "The line ACoS must stay under"),
    "ad_sales": ("Ad sales (net)", "EUR", "Sales Amazon credits to an ad click within 7 days, net of VAT",
                 "What the ads bring in"),
    "roas": ("ROAS", "×", "Net ad sales ÷ ad spend", "EUR of sales per EUR of ads"),
    "ad_profit": ("Ad profit", "EUR",
                  "Net ad sales × contribution margin 1 % of the product − ad spend: what ad-driven sales earn minus what the ads cost",
                  "Positive = the ads pay for themselves"),
    "ad_share": ("Ad share of sales", "%", "Net ad sales ÷ net revenue", "How much of the business comes through ads"),
    "cpc": ("Cost per click", "EUR", "Ad spend ÷ clicks", "Price of traffic"),
    "ad_cvr": ("Ad conversion", "%", "Ad orders ÷ clicks", "Do ad visitors buy?"),
    "cvr": ("Conversion", "%", "Units ÷ sessions", "Does the listing convince visitors?"),
    "buy_box": ("Buy box", "%", "Session-weighted share of page views with our offer in the basket box",
                "Below 100 % someone else takes our sales"),
    "asp": ("Net price", "EUR", "Net revenue ÷ units", "Actual price after VAT"),
    "cover_weeks": ("Weeks of cover", "weeks", "Available stock ÷ average units per week (last 4 weeks), per stock region",
                    "When do we run out?"),
    "lead_weeks": ("Reorder time", "weeks", "Lead time from product master ÷ 7", "How early we must reorder"),
}


def _div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, a / b, np.nan)
    return out


def summarize(fw: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Aggregate the weekly fact over any grouping and derive every ratio KPI."""
    g = fw.groupby(by)[ADDITIVE].sum() if by else fw[ADDITIVE].sum().to_frame().T
    g["amazon_fees"] = g.referral_fee + g.fba_fee
    g["cm1_pct"] = _div(g.cm1, g.net_revenue) * 100
    g["cm2_pct"] = _div(g.cm2, g.net_revenue) * 100
    g["cm3_pct"] = _div(g.cm3, g.net_revenue) * 100
    g["cogs_pct"] = _div(g.cogs, g.net_revenue) * 100
    g["fees_pct"] = _div(g.amazon_fees, g.net_revenue) * 100
    g["storage_pct"] = _div(g.storage_cost, g.net_revenue) * 100
    g["cm2_unit"] = _div(g.cm2, g.units)
    g["tacos"] = _div(g.ad_spend, g.net_revenue) * 100
    g["acos"] = _div(g.ad_spend, g.ad_sales) * 100
    g["be_acos"] = _div(g.cm1, g.net_revenue) * 100
    g["cvr"] = _div(g.units, g.sessions) * 100
    g["buy_box"] = _div(g.bb_weighted, g.sessions)
    g["asp"] = _div(g.net_revenue, g.units)
    g["roas"] = _div(g.ad_sales, g.ad_spend)
    g["ad_share"] = _div(g.ad_sales, g.net_revenue) * 100
    g["cpc"] = _div(g.ad_spend, g.clicks)
    g["ctr"] = _div(g.clicks, g.impressions) * 100
    g["ad_cvr"] = _div(g.ad_orders, g.clicks) * 100
    # Contribution margin 1 earned on ad-driven sales minus what the ads cost. Each sale is valued
    # at its own product's CM1 % in its own market, then summed, so totals equal the sum of rows.
    fine = fw.groupby(list(dict.fromkeys(by + ["marketplace", "sku"])))[
        ["ad_sales", "cm1", "net_revenue", "ad_spend"]].sum()
    fine_profit = np.nan_to_num(fine.ad_sales * _div(fine.cm1, fine.net_revenue)) - fine.ad_spend
    g["ad_profit"] = fine_profit.groupby(level=by).sum() if by else float(fine_profit.sum())
    return g


PER_WEEK = ["sessions", "units", "net_revenue", "cogs", "amazon_fees", "cm1", "ad_spend", "cm2",
            "storage_cost", "cm3", "ad_sales", "ad_profit", "clicks", "ad_orders"]


def per_week(g: pd.DataFrame, n_weeks: int) -> pd.DataFrame:
    """Add <measure>_wk columns: totals ÷ weeks, so unequal periods compare fairly."""
    g = g.copy()
    for f in PER_WEEK:
        g[f + "_wk"] = g[f] / n_weeks
    return g


def comparison_weeks(end: int, n: int) -> int:
    """Weeks available for the comparison period before a window of n weeks ending at `end`."""
    return max(0, min(n, end - n + 1))


def window(fw: pd.DataFrame, weeks: list[pd.Timestamp], end: int, n: int) -> pd.DataFrame:
    """Rows of the n weeks ending at index `end` (inclusive)."""
    if end - n + 1 < 0:
        return fw.iloc[0:0]
    sel = weeks[end - n + 1:end + 1]
    return fw[fw.week.isin(sel)]
