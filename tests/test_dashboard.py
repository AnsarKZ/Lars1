import math

import pandas as pd
import pytest

from perfdash.actions import top_actions
from perfdash.build import payload
from perfdash.kpis import summarize, window
from perfdash.model import build
from perfdash.rules import evaluate, stock_status


@pytest.fixture(scope="module")
def m():
    return build()


def test_cleaning(m):
    notes = {n["check"]: n for n in m.dq.notes}
    assert "56 rows removed" in notes["Exact duplicate rows"]["detail"]
    assert notes["Landed cost = purchase + freight & customs"]["status"] == "ok"
    assert set(m.fact_ads_day.sku) == set(m.dim_product.sku)          # lower-case IT SKUs mapped
    assert m.fact_stock_week.count_date.min() == pd.Timestamp("2026-03-30")
    assert len(m.weeks) == 26 and m.reporting_week == pd.Timestamp("2026-09-21")


def test_net_money_rules_for_one_known_unit(m):
    """One anthracite bottle in DE at EUR 29.99 gross: net 25.20, CM1 9.60."""
    d = m.fact_sales_day
    row = d[(d.marketplace == "DE") & (d.sku == "LN-ISO-750-ANT") & (d.units > 0)].iloc[0]
    assert row.net_revenue / row.units == pytest.approx(29.99 / 1.19, abs=0.01)
    assert row.referral_fee / row.units == pytest.approx(0.15 * 29.99, abs=0.01)   # on gross
    assert row.cm1 / row.units == pytest.approx(29.99 / 1.19 - 7.5 - 0.15 * 29.99 - 3.6, abs=0.01)


def test_uk_converted_then_vat_removed(m):
    d = m.fact_sales_day
    row = d[(d.marketplace == "UK") & (d.sku == "LN-ISO-750-ANT") & (d.units > 0)
            & (d.date.dt.month == 9)].iloc[0]
    assert row.net_revenue / row.units == pytest.approx(25.99 * 1.149 / 1.20, abs=0.01)


def test_margin_ladder_adds_up(m):
    t = summarize(m.fact_week, []).iloc[0]
    assert t.cm1 == pytest.approx(t.net_revenue - t.cogs - t.amazon_fees)
    assert t.cm2 == pytest.approx(t.cm1 - t.ad_spend)
    assert t.cm3 == pytest.approx(t.cm2 - t.storage_cost)
    assert round(t.cm2) == 232761


def test_storage_split_keeps_region_total(m):
    w = m.fact_week[m.fact_week.week == m.reporting_week]
    eu = w[w.marketplace.isin(["DE", "FR", "IT"]) & (w.sku == "LN-ISO-750-KOR")].storage_cost.sum()
    s = m.fact_stock_week.set_index(["region", "sku", "count_date"]).available
    avg = (s[("EU", "LN-ISO-750-KOR", pd.Timestamp("2026-09-21"))]
           + s[("EU", "LN-ISO-750-KOR", pd.Timestamp("2026-09-28"))]) / 2
    assert eu == pytest.approx(avg * 0.18 * 12 / 52)


def test_expected_criticals_and_no_red_sea(m):
    _, st = evaluate(m)
    crit = st[st.level == "critical"]
    assert set(map(tuple, crit[["marketplace", "sku", "rule"]].values)) == {
        ("DE", "LN-ISO-750-ANT", "stock"), ("FR", "LN-ISO-750-ANT", "stock"), ("IT", "LN-ISO-750-ANT", "stock"),
        ("DE", "LN-KAR-1800", "cm2"), ("FR", "LN-KAR-1800", "cm2"), ("IT", "LN-KAR-1800", "cm2"),
        ("UK", "LN-KAR-1800", "cm2"), ("FR", "LN-BRK-L", "buy_box")}
    assert len(st[st.level == "watch"]) <= 25          # signals; 10 of 32 cells end up amber


def test_stock_cover(m):
    s = stock_status(m).set_index(["region", "sku"])
    ant = s.loc[("EU", "LN-ISO-750-ANT")]
    assert ant.available == 511 and ant.inbound == 0
    assert ant.cover_weeks == pytest.approx(511 / 378.5)
    assert s.loc[("UK", "LN-ISO-750-ANT")].stock_level == "ok"


def test_top_actions_ranked_by_cost_of_waiting(m):
    acts = top_actions(m)
    assert [a.kind for a in acts] == ["stock", "ads", "buy_box"]
    assert acts[0].cost_of_delay_week > acts[1].cost_of_delay_week > acts[2].cost_of_delay_week


def test_payload_is_complete_and_json_safe(m):
    d = payload(m)
    assert set(d["periods"]) == {"1W", "4W", "13W", "26W"} and d["periods"]["26W"]["prev"] is None
    assert len(d["cells"]) == 32 and len(d["trend"]) == 26
    for period in d["grid"].values():
        for row in period.values():
            assert all(v is None or not (isinstance(v, float) and math.isnan(v)) for v in row["cur"].values())


def test_period_windows_do_not_overlap(m):
    cur = window(m.fact_week, m.weeks, len(m.weeks) - 1, 13)
    prev = window(m.fact_week, m.weeks, len(m.weeks) - 14, 13)
    assert set(cur.week).isdisjoint(prev.week) and len(set(cur.week) | set(prev.week)) == 26
