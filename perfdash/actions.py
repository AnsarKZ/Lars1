"""Turn critical signals into ranked actions: number, cause, expected effect.

Very different problems (a stock-out, a loss-making campaign, a lost buy box)
are ranked on one scale: the CM2 lost for every week the action is postponed.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import RULES as R
from .kpis import summarize, window
from .model import Model
from .rules import stock_status



@dataclass
class Action:
    title: str
    scope: str
    number: str
    cause: str
    action: str
    effect: str
    cost_of_delay_week: float   # CM2 lost per week of waiting
    kind: str


def _name(m: Model, sku: str) -> str:
    return m.dim_product.set_index("sku")["product"][sku]


def stock_actions(m: Model) -> list[Action]:
    out = []
    p = m.dim_product.set_index("sku")
    for _, s in stock_status(m).query("stock_issue == 'stock-out'").iterrows():
        out.append(Action(
            title=f"Reorder {_name(m, s.sku)} for {s.region} today",
            scope=f"{s.sku} · {s.region} pool",
            number=(f"{s.available:,} units left, selling {s.rate_week:.0f}/week → out of stock in "
                    f"~{s.cover_weeks * 7:.0f} days. Nothing inbound; reorder time {p.lead_time_days[s.sku]} days."),
            cause="No purchase order placed after the last delivery; cover fell below the reorder time.",
            action=(f"Order now (MOQ {p.moq[s.sku]:,}; last orders were 3,000) and expedite part of it. "
                    "Cut ads on this SKU in the region to stretch stock, and shift that budget to the "
                    "overstocked colour variant as a substitute."),
            effect=(f"Without action ~{s.weeks_short:.1f} weeks out of stock: ~{s.units_at_risk:,.0f} units "
                    f"and EUR {s.cm2_at_risk:,.0f} contribution margin (CM2) lost, plus lost ranking before Q4. Each week of "
                    f"delay adds ~EUR {s.rate_week * s.cm2_unit:,.0f}."),
            cost_of_delay_week=s.rate_week * s.cm2_unit, kind="stock"))
    return out


def loss_actions(m: Model) -> list[Action]:
    end = len(m.weeks) - 1
    last4 = summarize(window(m.fact_week, m.weeks, end, R["cm2_window_weeks"]), ["sku", "marketplace"])
    ads4 = summarize(window(m.fact_week, m.weeks, end - 1, R["acos_window_weeks"]), ["sku", "marketplace"])
    out = []
    for sku, g in last4.groupby(level="sku"):
        losing = g[(g.cm2 < 0) & (g.net_revenue >= R["min_net_revenue_4w"])]
        if losing.empty:
            continue
        loss_week = -losing.cm2.sum() / R["cm2_window_weeks"]
        a = ads4.loc[losing.index]
        spend_week = a.ad_spend.sum() / R["acos_window_weeks"]
        target_spend = (a.ad_sales * a.be_acos / 100).sum() / R["acos_window_weeks"]
        worst = losing.cm2_pct.idxmin()[1]
        mps = ", ".join(f"{mp} {a.loc[(sku, mp)].acos:.0f} %" for mp in losing.index.get_level_values(1))
        out.append(Action(
            title=f"Cut ad budgets for {_name(m, sku)}",
            scope=f"{sku} · {', '.join(losing.index.get_level_values(1))}",
            number=(f"Contribution margin 2 (CM2) −EUR {loss_week:,.0f}/week; ads EUR {spend_week:,.0f}/week. "
                    f"ACoS (net) {mps} vs break-even ~{a.be_acos.mean():.0f} %."),
            cause="Budgets run at ~8× the other products since launch and efficiency is not improving; "
                  "every ad-driven sale costs more than it earns.",
            action=(f"Lower bids/budgets to bring ACoS under break-even, starting with {worst} (worst margin). "
                    "Keep the exact-match campaigns that convert; pause the weakest auto campaigns."),
            effect=(f"Spend at break-even ACoS ≈ EUR {target_spend:,.0f}/week, so ≈ EUR "
                    f"{spend_week - target_spend:,.0f}/week less ad cost. Stops most of the "
                    f"EUR {loss_week:,.0f}/week loss."),
            cost_of_delay_week=loss_week, kind="ads"))
    return out


def buybox_actions(m: Model) -> list[Action]:
    fw, weeks = m.fact_week, m.weeks
    by_week = summarize(fw, ["marketplace", "sku", "week"])
    out = []
    for (mp, sku), g in by_week.groupby(level=["marketplace", "sku"]):
        g = g.droplevel([0, 1]).sort_index()
        low = g.buy_box < R["buybox_critical"]
        if not (low.iloc[-1] and low.iloc[-2]):
            continue
        # first week of the current low streak
        start = low[::-1].cumprod()[::-1]
        first = start[start == 1].index.min()
        before = g[g.index < first].tail(8)
        after = g[g.index >= first]
        lost_units = before.units.mean() - after.units.mean()
        cm2_unit = before.cm2.sum() / before.units.sum()
        out.append(Action(
            title=f"Win back the buy box for {_name(m, sku)} in {mp}",
            scope=f"{sku} · {mp}",
            number=(f"Buy box {before.buy_box.mean():.0f} % → {after.buy_box.mean():.0f} % since "
                    f"{first:%d.%m.} Visitors unchanged ({before.sessions.mean():.0f} → "
                    f"{after.sessions.mean():.0f}/week) but units {before.units.mean():.0f} → "
                    f"{after.units.mean():.0f}/week."),
            cause="Another seller wins the basket button on our listing (only this marketplace, "
                  "our price is unchanged): reseller, competitor offer or hijacker.",
            action="Check the offer list in Seller Central, report unauthorised sellers via Brand Registry, "
                   "and pause ads on this listing until the buy box is back (we pay for clicks that "
                   "sell someone else's offer).",
            effect=(f"≈ {lost_units:.0f} units/week back, ≈ EUR {lost_units * after.asp.mean():,.0f}/week "
                    f"net revenue and EUR {lost_units * cm2_unit:,.0f}/week contribution margin (CM2)."),
            cost_of_delay_week=lost_units * cm2_unit, kind="buy_box"))
    return out


def top_actions(m: Model, n: int = 3) -> list[Action]:
    acts = stock_actions(m) + loss_actions(m) + buybox_actions(m)
    return sorted(acts, key=lambda a: -a.cost_of_delay_week)[:n]
