"""The five questions the robot asks every round, in root-cause order.

① Is the push job alive?        push_job_alive
② Did the pushes get through?    push_delivery
③ Were they accepted?            channel_processing (+ freshness safety net)
④ Is the product buyable?        listing_visibility
⑤ Does the shop show the truth?  shown_vs_target, negative_stock
+  Catalog drift and data quality

Each check returns findings and "holds". A hold says "I could not judge this
key this round" (e.g. Amazon still processing, readback timed out) so the
alert manager neither counts it as present nor as resolved.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import (TEAM_IT, TEAM_MARKETPLACE, TEAM_MASTER, TEAM_OPS,
                     Settings, rejection_team)
from .models import Finding, MasterData, Severity
from .state import State

VIENNA = ZoneInfo("Europe/Vienna")


def local(ts: datetime | None) -> str:
    return "-" if ts is None else ts.astimezone(VIENNA).strftime("%d.%m. %H:%M")


@dataclass
class Context:
    now: datetime
    slot: datetime            # push slot this round judges (now - 20 min)
    state: State
    master: MasterData
    settings: Settings


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)
    holds: set[tuple] = field(default_factory=set)      # key prefixes not judgeable this round

    def extend(self, other: "CheckResult") -> None:
        self.findings += other.findings
        self.holds |= other.holds


# ------------------------------------------------------------- ① push alive

def push_job_alive(ctx: Context) -> CheckResult:
    out = CheckResult()
    last = ctx.state.last_push_ts or ctx.state.start
    age = ctx.now - last
    if age > ctx.settings.push_heartbeat_max_age:
        missed = int(age / ctx.settings.round_interval)
        out.findings.append(Finding(
            key=("PUSH_JOB_DOWN",), type="PUSH_JOB_DOWN", severity=Severity.CRITICAL,
            title="Push job is not running",
            detail=f"No stock push since {local(last)} (~{missed} runs missed). "
                   "No channel receives stock updates; buffers are the only protection.",
            team=TEAM_IT))
        return out

    attempts = ctx.state.pushes_by_slot.get(ctx.slot, [])
    expected = len(ctx.master.keys)
    sent = {(p.channel, p.channel_sku) for p in attempts}
    if attempts and len(sent & set(ctx.master.keys)) < expected:
        out.findings.append(Finding(
            key=("PUSH_RUN_INCOMPLETE",), type="PUSH_RUN_INCOMPLETE", severity=Severity.HIGH,
            title="Push run incomplete",
            detail=f"Run at {local(ctx.slot)} covered {len(sent)} of {expected} listings.",
            team=TEAM_IT))
    return out


# ---------------------------------------------------------- ② push delivery

def push_delivery(ctx: Context) -> CheckResult:
    """A push counts as failed if its LAST attempt failed, whatever the code.
    429 followed by a successful retry is therefore silent by design."""
    out = CheckResult()
    attempts = ctx.state.pushes_by_slot.get(ctx.slot, [])
    if not attempts:
        # No run this slot: question ① owns that. Keep open delivery alerts as they are.
        out.holds |= {("PUSH_FAILED",), ("CHANNEL_PUSH_FAILING",)}
        return out

    final: dict[tuple, object] = {}
    for p in sorted(attempts, key=lambda p: (p.attempt, p.ts)):
        final[(p.channel, p.channel_sku)] = p
    failed = {k: p for k, p in final.items()
              if p.http_status >= 400 or not p.submission_id}

    by_channel: dict[str, list] = defaultdict(list)
    for (channel, _), p in failed.items():
        by_channel[channel].append(p)

    for channel, ps in by_channel.items():
        auth = any(p.http_status in (401, 403) for p in ps)
        reasons = sorted({f"{p.http_status} {p.response}" for p in ps})
        total = len(ctx.master.channel_keys(channel))
        if len(ps) >= min(ctx.settings.channel_group_min_skus, total):
            out.findings.append(Finding(
                key=("CHANNEL_PUSH_FAILING", channel), type="CHANNEL_PUSH_FAILING",
                severity=Severity.CRITICAL if auth else Severity.HIGH,
                title=f"{channel} unreachable" + (" (access denied)" if auth else ""),
                detail=f"{len(ps)}/{total} listings failed in run {local(ctx.slot)}: "
                       f"{'; '.join(reasons)}."
                       + (" Retrying will not help: renew the API token." if auth else ""),
                team=TEAM_IT, persistence=1 if auth else 2, channel=channel))
        else:
            for p in ps:
                out.findings.append(Finding(
                    key=("PUSH_FAILED", channel, p.channel_sku), type="PUSH_FAILED",
                    severity=Severity.HIGH,
                    title=f"Push to {channel} {p.channel_sku} failed",
                    detail=f"Final attempt {p.attempt} answered {p.http_status} {p.response}.",
                    team=TEAM_IT, persistence=1 if auth else 2,
                    channel=channel, channel_sku=p.channel_sku))
    return out


# ------------------------------------------------- ③ processing / freshness

def channel_processing(ctx: Context) -> CheckResult:
    out = CheckResult()
    s = ctx.settings
    for key in ctx.master.keys:
        channel, channel_sku = key
        st = ctx.state.listings[key]
        listing = ctx.master.listing(*key)
        if st.consecutive_errors >= s.rejections_before_alert:
            category, team = rejection_team(st.last_error_msg)
            stock = ctx.state.stock.get(listing.sku)
            out.findings.append(Finding(
                key=("LISTING_REJECTED", channel, channel_sku), type="LISTING_REJECTED",
                severity=Severity.HIGH,
                title=f"{channel} rejects every update for {channel_sku} ({listing.product})",
                detail=f"{st.consecutive_errors} rejections in a row since {local(st.first_error_ts)}: "
                       f"\"{st.last_error_msg}\". Category: {category}. "
                       f"Channel keeps its old stock and counts down on its own; "
                       f"warehouse now has {stock}. HTTP said 'accepted', only the "
                       f"processing report shows the error.",
                team=team, channel=channel, channel_sku=channel_sku))

    overdue = defaultdict(list)
    for sid, sent in ctx.state.pending.items():
        (channel, channel_sku), _ = ctx.state.submissions[sid]
        profile = s.profiles.get(channel)
        if profile and profile.asynchronous and ctx.now - sent > profile.max_processing:
            overdue[channel].append(channel_sku)
    for channel, skus in overdue.items():
        out.findings.append(Finding(
            key=("PROCESSING_OVERDUE", channel), type="PROCESSING_OVERDUE",
            severity=Severity.WARNING,
            title=f"{channel} is not processing submissions",
            detail=f"{len(skus)} submissions without result for > "
                   f"{int(s.profiles[channel].max_processing.total_seconds() // 60)} min.",
            team=TEAM_IT, channel=channel))
    return out


def freshness(ctx: Context, explained: set[tuple]) -> CheckResult:
    """Safety net: a listing that has not been successfully updated for too
    long, for a reason no other check explains."""
    out = CheckResult()
    if ("PUSH_JOB_DOWN",) in explained:
        return out
    for key in ctx.master.keys:
        channel, channel_sku = key
        if (channel,) in explained or key in explained:
            continue
        st = ctx.state.listings[key]
        if st.last_submission in ctx.state.pending:
            continue                       # an update is on its way (e.g. right after an outage)
        last = st.last_success_ts or ctx.state.start
        if ctx.now - last > ctx.settings.stale_after:
            out.findings.append(Finding(
                key=("STALE_LISTING", channel, channel_sku), type="STALE_LISTING",
                severity=Severity.WARNING,
                title=f"{channel} {channel_sku} not updated since {local(last)}",
                detail="No successful stock update for "
                       f"{(ctx.now - last).total_seconds() / 3600:.1f} h, cause unknown.",
                team=TEAM_IT, channel=channel, channel_sku=channel_sku))
    return out


# --------------------------------------------------- readback-based checks

def _round_readbacks(ctx: Context):
    """Own-shipped readbacks of this round, plus per-channel timeout info."""
    own, timeouts = {}, defaultdict(list)
    for rb in ctx.state.readbacks:
        if rb.fulfillment != "DEFAULT":
            continue                       # FBA: Amazon's stock, not ours
        if rb.query_status != "OK":
            timeouts[rb.channel].append(rb.channel_sku)
            continue
        own[(rb.channel, rb.channel_sku)] = rb
    return own, timeouts


def readback_health(ctx: Context) -> CheckResult:
    out = CheckResult()
    if not ctx.state.readbacks:
        out.findings.append(Finding(
            key=("READBACK_JOB_DOWN",), type="READBACK_JOB_DOWN", severity=Severity.HIGH,
            title="Readback job delivered no data",
            detail="Cannot see what any channel shows. Shown-vs-target checks paused.",
            team=TEAM_IT, persistence=2))
        out.holds |= {("SHOWN_TOO_HIGH",), ("SHOWN_TOO_LOW",), ("LISTING_INACTIVE",),
                      ("READBACK_MISSING",), ("UNMAPPED_LISTING",)}
        return out
    _, timeouts = _round_readbacks(ctx)
    for channel, skus in timeouts.items():
        out.findings.append(Finding(
            key=("READBACK_FAILED", channel), type="READBACK_FAILED", severity=Severity.WARNING,
            title=f"Readback for {channel} failing",
            detail=f"{len(skus)} queries returned no stock (e.g. TIMEOUT). "
                   "Treated as 'unknown', not as 0.",
            team=TEAM_IT, persistence=2, channel=channel))
        for sku in skus:
            for t in ("SHOWN_TOO_HIGH", "SHOWN_TOO_LOW", "LISTING_INACTIVE", "READBACK_MISSING"):
                out.holds.add((t, channel, sku))
    return out


def listing_visibility(ctx: Context) -> CheckResult:
    out = CheckResult()
    own, _ = _round_readbacks(ctx)
    for key, rb in own.items():
        listing = ctx.master.listing(*key)
        if listing is None or rb.listing_status != "INACTIVE":
            continue
        rule = ctx.master.rules[key[0]]
        target = rule.target(ctx.state.stock.get(listing.sku, 0))
        if target <= 0:
            continue                       # nothing to sell, inactive is fine
        per_day = ctx.state.daily_sales([key], ctx.now)
        out.findings.append(Finding(
            key=("LISTING_INACTIVE", *key), type="LISTING_INACTIVE", severity=Severity.WARNING,
            title=f"{key[0]} {key[1]} ({listing.product}) is INACTIVE although in stock",
            detail=f"Should show {target}, shows {rb.qty}. Customers cannot buy it. "
                   f"Typical sales here ~{per_day:.1f}/day (~EUR {per_day * listing.price_eur:.0f}/day lost).",
            team=TEAM_MARKETPLACE, persistence=ctx.settings.inactive_persistence,
            channel=key[0], channel_sku=key[1], eur_at_risk=per_day * listing.price_eur))
    return out


def shown_vs_target(ctx: Context) -> CheckResult:
    """Target = rule(warehouse stock at push time) - own orders since then.
    Gap   = shown - target. Direction decides severity."""
    out = CheckResult()
    s = ctx.settings
    own, _ = _round_readbacks(ctx)
    for key, rb in own.items():
        listing = ctx.master.listing(*key)
        if listing is None or rb.listing_status != "ACTIVE" or key in s.ignored_listings:
            continue
        channel, channel_sku = key
        st = ctx.state.listings[key]

        # Amazon has not processed our latest push before the readback:
        # the channel may legitimately still show the previous value.
        sid = st.last_submission
        processed = ctx.state.results_ts.get(sid) if sid else None
        if sid and (processed is None or processed > rb.ts):
            out.holds |= {("SHOWN_TOO_HIGH", *key), ("SHOWN_TOO_LOW", *key)}
            continue

        available = ctx.state.stock.get(listing.sku, 0)
        target = ctx.master.rules[channel].target(available)
        target = max(target - ctx.state.orders_since(key, ctx.slot, rb.ts), 0)
        gap = rb.qty - target
        if abs(gap) <= s.tolerance_units:
            continue

        cause = ""
        if st.consecutive_errors:
            cause = (f" Likely cause: updates rejected since {local(st.first_error_ts)} "
                     f"(\"{st.last_error_msg}\").")

        if gap > 0:
            # Critical only when the gap can become real cancellations soon:
            # stock gone, or the channel promises more than exists and the
            # rest would sell out within a day.
            sku_keys = [k for k, l in ctx.master.by_channel_sku.items() if l.sku == listing.sku]
            per_day = ctx.state.daily_sales(sku_keys, ctx.now)
            imminent = rb.qty > available and available < per_day
            if available <= 0 or imminent:
                sev, persistence = Severity.CRITICAL, 1
                what = (f"OVERSELLING: shows {rb.qty}, warehouse has only {available} "
                        f"(~{per_day:.0f} sold/day across channels). "
                        "Orders beyond stock cannot be fulfilled.")
            elif rb.qty > available:
                sev, persistence = Severity.HIGH, s.gap_persistence
                what = (f"Shows {rb.qty}, more than the {available} in the warehouse "
                        f"(should show {target}). Safety buffer is gone.")
            else:
                sev, persistence = Severity.HIGH, s.gap_persistence
                what = (f"Shows {rb.qty}, should show {target} (warehouse {available}). "
                        "Safety buffer is being used up.")
            out.findings.append(Finding(
                key=("SHOWN_TOO_HIGH", *key), type="SHOWN_TOO_HIGH", severity=sev,
                title=f"{channel} {channel_sku} ({listing.product}) shows too much stock",
                detail=what + cause, team=TEAM_MARKETPLACE, persistence=persistence,
                channel=channel, channel_sku=channel_sku, eur_at_risk=gap * listing.price_eur))
        else:
            out.findings.append(Finding(
                key=("SHOWN_TOO_LOW", *key), type="SHOWN_TOO_LOW", severity=Severity.WARNING,
                title=f"{channel} {channel_sku} ({listing.product}) shows too little stock",
                detail=f"Shows {rb.qty}, should show {target}. Possible lost sales." + cause,
                team=TEAM_MARKETPLACE, persistence=s.gap_persistence,
                channel=channel, channel_sku=channel_sku, eur_at_risk=-gap * listing.price_eur))
    return out


def negative_stock(ctx: Context) -> CheckResult:
    out = CheckResult()
    for sku, available in ctx.state.stock.items():
        if available >= 0:
            continue
        showing = [f"{rb.channel} {rb.qty}" for rb in ctx.state.readbacks
                   if rb.fulfillment == "DEFAULT" and rb.qty
                   and (l := ctx.master.listing(rb.channel, rb.channel_sku)) and l.sku == sku]
        out.findings.append(Finding(
            key=("STOCK_NEGATIVE", sku), type="STOCK_NEGATIVE", severity=Severity.CRITICAL,
            title=f"{sku} oversold: warehouse at {available}",
            detail=f"{-available} units sold that do not exist. Still offered on: "
                   f"{', '.join(showing) or 'none'}. Prepare customer communication.",
            team=TEAM_OPS))
    return out


# --------------------------------------------------------------- catalog

def catalog_drift(ctx: Context) -> CheckResult:
    """Listings that appear but are not in the mapping, and mapped listings
    that are missing from the readback."""
    out = CheckResult()
    st = ctx.state
    seen = set()
    for rb in st.readbacks:
        if rb.fulfillment != "DEFAULT":
            continue
        key = (rb.channel, rb.channel_sku)
        seen.add(key)
        if ctx.master.listing(*key) is None and key not in ctx.settings.ignored_listings:
            st.seen_unmapped.setdefault(key, rb.ts)
    for o in st.orders:
        key = (o.channel, o.channel_sku)
        if ctx.master.listing(*key) is None and key not in ctx.settings.ignored_listings:
            st.seen_unmapped.setdefault(key, o.ts)
    for key, first in st.seen_unmapped.items():
        rb = st.listings[key].last_readback
        orders = sum(o.qty for o in st.orders if (o.channel, o.channel_sku) == key)
        out.findings.append(Finding(
            key=("UNMAPPED_LISTING", *key), type="UNMAPPED_LISTING", severity=Severity.WARNING,
            title=f"Unknown listing {key[0]} {key[1]}",
            detail=f"Not in SKU mapping (first seen {local(first)}). "
                   f"Status {rb.listing_status if rb else '?'}, shows {rb.qty if rb else '?'}, "
                   f"{orders} units ordered in the last 7 days. Orders on unmapped listings "
                   "may never be deducted from warehouse stock.",
            team=TEAM_MASTER, channel=key[0], channel_sku=key[1]))

    _, timeouts = _round_readbacks(ctx)
    timed_out = {(c, s) for c, skus in timeouts.items() for s in skus}
    for key in ctx.master.keys:
        if key not in seen and key not in timed_out:
            out.findings.append(Finding(
                key=("READBACK_MISSING", *key), type="READBACK_MISSING", severity=Severity.INFO,
                title=f"No readback for {key[0]} {key[1]}",
                detail="Mapped listing missing from the readback (deleted or not returned by the API?).",
                team=TEAM_MASTER, persistence=2, channel=key[0], channel_sku=key[1]))
    return out


def data_quality(ctx: Context) -> CheckResult:
    out = CheckResult()
    for note in ctx.state.quality_notes:
        out.findings.append(Finding(
            key=("DATA_QUALITY", note.source), type="DATA_QUALITY", severity=Severity.INFO,
            title=f"Data quality issue in {note.source}",
            detail=note.message, team=TEAM_IT))
    return out


# --------------------------------------------------------------- pipeline

def run_all(ctx: Context) -> CheckResult:
    result = CheckResult()
    for check in (push_job_alive, push_delivery, channel_processing, readback_health,
                  listing_visibility, shown_vs_target, negative_stock, catalog_drift,
                  data_quality):
        result.extend(check(ctx))

    # Root cause first: staleness is only reported when nothing above explains it.
    explained: set[tuple] = set()
    for f in result.findings:
        if f.type == "PUSH_JOB_DOWN":
            explained.add(("PUSH_JOB_DOWN",))
        elif f.type == "CHANNEL_PUSH_FAILING":
            explained.add((f.channel,))
        elif f.type in ("PUSH_FAILED", "LISTING_REJECTED"):
            explained.add((f.channel, f.channel_sku))
    for key in ctx.master.keys:
        st = ctx.state.listings[key]
        if st.consecutive_errors:               # rejected, but not yet alert-worthy
            explained.add(key)
    result.extend(freshness(ctx, explained))
    return result
