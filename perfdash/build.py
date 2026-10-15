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
from .kpis import KPI_DEFINITIONS, summarize, window
from .model import Model, build
from .rules import LEVEL_RANK, evaluate, stock_status

TEMPLATE = Path(__file__).with_name("template.html")
FIELDS = ["sessions", "units", "net_revenue", "cogs", "amazon_fees", "cm1", "ad_spend", "cm2",
          "storage_cost", "cm3", "cm1_pct", "cm2_pct", "cm3_pct", "cm2_unit", "tacos", "acos",
          "be_acos", "cvr", "buy_box", "asp"]


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

    periods, totals, by_mp, grid = {}, {}, {}, {}
    for key, n in PERIODS.items():
        cur = window(fw, weeks, end, n)
        prev = window(fw, weeks, end - n, n)
        periods[key] = {
            "weeks": n,
            "cur": f"{weeks[end - n + 1]:%d.%m.}–{weeks[end] + pd.Timedelta(days=6):%d.%m.%Y}",
            "prev": (f"{weeks[end - 2 * n + 1]:%d.%m.}–{weeks[end - n] + pd.Timedelta(days=6):%d.%m.%Y}"
                     if not prev.empty else None),
            "acos_incomplete": True,   # every window ends with the reporting week
        }
        totals[key] = {"cur": _row(summarize(cur, []).iloc[0]),
                       "prev": _row(summarize(prev, []).iloc[0]) if not prev.empty else None}
        mc, mpv = summarize(cur, ["marketplace"]), (summarize(prev, ["marketplace"]) if not prev.empty else None)
        by_mp[key] = {mp: {"cur": _row(mc.loc[mp]),
                           "prev": _row(mpv.loc[mp]) if mpv is not None and mp in mpv.index else None}
                      for mp in mc.index}
        gc = summarize(cur, ["marketplace", "sku"])
        gp = summarize(prev, ["marketplace", "sku"]) if not prev.empty else None
        grid[key] = {f"{mp}|{sku}": {"cur": _row(gc.loc[(mp, sku)]),
                                     "prev": _row(gp.loc[(mp, sku)]) if gp is not None and (mp, sku) in gp.index else None}
                     for mp, sku in gc.index}

    trend = summarize(fw, ["week"])
    trend_rows = [{"week": f"{w:%d.%m.}", "label": _week_label(w), **_row(r)} for w, r in trend.iterrows()]

    _, status = evaluate(m)
    cells = []
    for mp in m.dim_marketplace.marketplace:
        for sku in m.dim_product.sku:
            s = status[(status.marketplace == mp) & (status.sku == sku)]
            level = max(s.level, key=LEVEL_RANK.get) if not s.empty else "ok"
            sig = sorted(s.to_dict("records"), key=lambda r: -LEVEL_RANK[r["level"]])
            live = f"{mp}|{sku}" in grid["26W"]
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
