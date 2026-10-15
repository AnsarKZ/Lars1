"""Assemble everything the dashboard shows into one JSON payload and render
the self-contained HTML page. All numbers are computed here, in Python, from
the central KPI definitions; the page only displays and filters them."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .actions import top_actions
from .config import ATTRIBUTION_DAYS, PERIODS, RULES
from .kpis import KPI_DEFINITIONS, PER_WEEK, comparison_weeks, per_week, summarize, window
from .model import Model, build
from .rules import LEVEL_RANK, evaluate, stock_status

TEMPLATE = Path(__file__).with_name("template.html")
FIELDS = ["sessions", "units", "net_revenue", "cogs", "amazon_fees", "cm1", "ad_spend", "cm2",
          "storage_cost", "cm3", "cm1_pct", "cm2_pct", "cm3_pct", "cogs_pct", "fees_pct",
          "storage_pct", "cm2_unit", "tacos", "acos", "be_acos", "cvr", "buy_box", "asp"]
FIELDS += [f + "_wk" for f in PER_WEEK]


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, float):
        return round(v, 2)
    return v


def _row(s: pd.Series) -> dict:
    return {f: _clean(float(s[f])) for f in FIELDS}


def _week_label(w: pd.Timestamp) -> str:
    return f"{w:%d.%m.}–{w + pd.Timedelta(days=6):%d.%m.%Y}"


def payload(m: Model) -> dict:
    fw, weeks = m.fact_week, m.weeks
    end = len(weeks) - 1
    names = m.dim_product.set_index("sku")["product"]
    life = m.dim_product.set_index("sku")["lifecycle"]

    def label(i0: int, i1: int) -> str:
        return f"{weeks[i0]:%d.%m.}–{weeks[i1] + pd.Timedelta(days=6):%d.%m.%Y}"

    def table(frame: pd.DataFrame, by: list[str], n: int):
        return per_week(summarize(frame, by), n) if not frame.empty else None

    periods, totals, by_mp, grid = {}, {}, {}, {}
    for key, n in PERIODS.items():
        k = comparison_weeks(end, n)                      # weeks available before the window
        cur, prev = window(fw, weeks, end, n), window(fw, weeks, end - n, k)
        periods[key] = {
            "weeks": n, "prev_weeks": k, "prev_full": k == n,
            "cur": label(end - n + 1, end),
            "prev": label(end - n - k + 1, end - n) if k else None,
        }
        tc, tp = table(cur, [], n), table(prev, [], k)
        c, p = tc.iloc[0], (tp.iloc[0] if tp is not None else None)
        bridge = None
        if p is not None:   # why CM2 % moved, in percentage points; the steps add up exactly
            bridge = [{"k": "CM2 % before", "v": float(p.cm2_pct), "total": True},
                      {"k": "Landed cost", "v": float(p.cogs_pct - c.cogs_pct)},
                      {"k": "Amazon fees", "v": float(p.fees_pct - c.fees_pct)},
                      {"k": "Ad spend", "v": float(p.tacos - c.tacos)},
                      {"k": "CM2 % now", "v": float(c.cm2_pct), "total": True}]
        totals[key] = {"cur": _row(c), "prev": _row(p) if p is not None else None, "bridge": bridge}
        mc, mpv = table(cur, ["marketplace"], n), table(prev, ["marketplace"], k)
        by_mp[key] = {mp: {"cur": _row(mc.loc[mp]),
                           "prev": _row(mpv.loc[mp]) if mpv is not None and mp in mpv.index else None}
                      for mp in mc.index}
        gc, gp = table(cur, ["marketplace", "sku"], n), table(prev, ["marketplace", "sku"], k)
        grid[key] = {f"{mp}|{sku}": {"cur": _row(gc.loc[(mp, sku)]),
                                     "prev": _row(gp.loc[(mp, sku)]) if gp is not None and (mp, sku) in gp.index else None}
                     for mp, sku in gc.index}

    trend = per_week(summarize(fw, ["week"]), 1)
    trend_rows = [{"week": f"{w:%d.%m.}", "label": _week_label(w), **_row(r)} for w, r in trend.iterrows()]

    _, status = evaluate(m)
    cells = []
    for mp in m.dim_marketplace.marketplace:
        for sku in m.dim_product.sku:
            s = status[(status.marketplace == mp) & (status.sku == sku)]
            level = max(s.level, key=LEVEL_RANK.get) if not s.empty else "ok"
            sig = sorted(s.to_dict("records"), key=lambda r: -LEVEL_RANK[r["level"]])
            live = f"{mp}|{sku}" in grid[max(PERIODS, key=PERIODS.get)]
            cells.append({"marketplace": mp, "sku": sku, "level": level if live else "none",
                          "signals": [{"rule": r["rule"], "level": r["level"], "text": r["text"]} for r in sig]})

    st = stock_status(m)
    stock_rows = [{
        "region": r.region, "sku": r.sku, "product": names[r.sku], "available": int(r.available),
        "inbound": int(r.inbound), "reserved": int(r.reserved), "rate_week": round(r.rate_week, 1),
        "cover_weeks": _clean(float(r.cover_weeks)), "cover_incl_inbound": _clean(float(r.cover_incl_inbound)),
        "lead_weeks": round(r.lead_weeks, 1), "level": r.stock_level, "issue": r.stock_issue,
        "value_eur": round(r.stock_value_eur, 0), "cm2_at_risk": round(r.cm2_at_risk, 0),
    } for r in st.itertuples()]

    last4 = summarize(window(fw, weeks, end, RULES["cm2_window_weeks"]), ["marketplace", "sku"])
    losing = last4[(last4.cm2 < 0) & (last4.net_revenue >= RULES["min_net_revenue_4w"])]
    risks = {
        "stockout_count": int((st.stock_issue == "stock-out").sum()),
        "stockout_cm2": round(float(st.cm2_at_risk.sum()), 0),
        "stockout_items": [f"{r.sku} {r.region}" for r in st.itertuples() if r.stock_issue == "stock-out"],
        "overstock_value": round(float(st.loc[st.stock_issue == "overstock", "stock_value_eur"].sum()), 0),
        "overstock_storage_month": round(float(st.loc[st.stock_issue == "overstock", "storage_month"].sum()), 0),
        "overstock_items": [f"{r.sku} {r.region}" for r in st.itertuples() if r.stock_issue == "overstock"],
        "loss_ad_spend_week": round(float(losing.ad_spend.sum()) / RULES["cm2_window_weeks"], 0),
        "loss_cm2_week": round(float(losing.cm2.sum()) / RULES["cm2_window_weeks"], 0),
        "loss_items": sorted({f"{sku}" for _, sku in losing.index}),
    }

    return {
        "meta": {
            "reporting_week": _week_label(weeks[end]),
            "first_week": _week_label(weeks[0]),
            "export_date": "28.09.2026",
            "attribution_days": ATTRIBUTION_DAYS,
        },
        "periods": periods,
        "totals": totals,
        "by_marketplace": by_mp,
        "grid": grid,
        "trend": trend_rows,
        "cells": cells,
        "stock": stock_rows,
        "risks": risks,
        "actions": [a.__dict__ for a in top_actions(m)],
        "products": [{"sku": s, "product": names[s], "lifecycle": life[s]} for s in m.dim_product.sku],
        "marketplaces": list(m.dim_marketplace.marketplace),
        "kpi_definitions": [{"key": k, "label": v[0], "unit": v[1], "formula": v[2], "why": v[3]}
                            for k, v in KPI_DEFINITIONS.items()],
        "rules": RULES,
        "data_quality": m.dq.notes,
    }


def render(data: dict, out: Path, fragment: Path | None = None) -> Path:
    """Write a standalone HTML document to `out`. Optionally also the bare page
    fragment (no doctype/head), which is what the claude.ai artifact viewer wraps."""
    html = TEMPLATE.read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = html.replace("/*__DATA__*/null", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                   + page.replace("<style>", "<style>\n[hidden] { display: none !important; }\n", 1)
                   .replace("<div class=\"wrap\">", "</head>\n<body>\n<div class=\"wrap\">", 1)
                   + "\n</body>\n</html>\n", encoding="utf-8")
    if fragment:
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_text(page, encoding="utf-8")
    return out


def export_model(m: Model, folder: Path) -> None:
    """Write the model tables as CSV: the shape the warehouse tables would have."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("dim_product", "dim_marketplace", "fact_sales_day", "fact_ads_day",
                 "fact_stock_week", "fact_week"):
        getattr(m, name).to_csv(folder / f"{name}.csv", index=False)


def main(out: Path = Path("site/index.html"), model_dir: Path | None = Path("out/model"),
         fragment: Path | None = Path("out/artifact.html")) -> Path:
    m = build()
    if model_dir:
        export_model(m, model_dir)
    return render(payload(m), out, fragment)
