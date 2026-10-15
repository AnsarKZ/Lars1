"""Human-readable outputs: the daily digest and the end-of-replay summary."""
from __future__ import annotations

from datetime import datetime

from .checks import local
from .models import MasterData, Severity


def days_of_cover(state, master: MasterData, now: datetime) -> list[tuple[str, int, float, float | None]]:
    """(sku, stock, units/day, days left) — low stock is where overselling starts."""
    rows = []
    for sku in sorted(state.stock):
        keys = [k for k, l in master.by_channel_sku.items() if l.sku == sku]
        per_day = state.daily_sales(keys, now)
        stock = state.stock[sku]
        days = stock / per_day if per_day > 0 else None
        rows.append((sku, stock, per_day, days))
    return rows


def digest_text(now: datetime, manager, state, master: MasterData) -> str:
    lines = [f"\n──── Daily digest {local(now)} Vienna ────"]
    open_alerts = sorted(manager.open_alerts, key=lambda a: (-a.severity, a.opened_at))
    if open_alerts:
        lines.append(f"Open alerts ({len(open_alerts)}):")
        for a in open_alerts:
            lines.append(f"  #{a.id:<3} {a.severity.name:8} since {local(a.first_seen)}  {a.title}")
    else:
        lines.append("No open alerts.")
    low = [(s, q, d) for s, q, _, d in days_of_cover(state, master, now) if d is not None and d < 2]
    if low:
        lines.append("Low stock (< 2 days of cover):")
        for sku, q, d in low:
            lines.append(f"  {sku:14} {q:>4} units  ≈ {max(d, 0):.1f} days")
    lines.append("──────────────────────────────────────\n")
    return "\n".join(lines)


def summary_markdown(result, master: MasterData, end: datetime) -> str:
    alerts = sorted(result.manager.history, key=lambda a: a.opened_at)
    out = ["# Replay summary", "",
           f"Rounds: {result.rounds} · alerts opened: {len(alerts)} · "
           f"still open at end: {sum(a.resolved_at is None for a in alerts)}", "",
           "| # | Severity (max) | Type | Scope | First seen (Vienna) | Alert opened | Resolved | Team |",
           "|---|---|---|---|---|---|---|---|"]
    for a in alerts:
        scope = " ".join(x for x in (a.channel, a.channel_sku) if x) or "global"
        if a.type == "STOCK_NEGATIVE":
            scope = a.key[1]
        out.append(f"| {a.id} | {a.max_severity.name} | {a.type} | {scope} | {local(a.first_seen)} | "
                   f"{local(a.opened_at)} | {local(a.resolved_at) if a.resolved_at else 'open'} | {a.team} |")
    out += ["", "## Days of cover at end of replay", "",
            "| SKU | Stock | Units/day | Days left |", "|---|---|---|---|"]
    for sku, q, per_day, d in days_of_cover(result.state, master, end):
        out.append(f"| {sku} | {q} | {per_day:.1f} | {'-' if d is None else f'{max(d, 0):.1f}'} |")
    by_sev = {s.name: sum(a.max_severity == s for a in alerts) for s in Severity}
    out += ["", "## Alerts by severity", "", ", ".join(f"{k}: {v}" for k, v in by_sev.items()), ""]
    return "\n".join(out)
