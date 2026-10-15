"""All thresholds and routing in one place, so they can be tuned without
touching check logic. Values are justified in the README."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .models import Severity


@dataclass(frozen=True)
class ChannelProfile:
    asynchronous: bool                       # result arrives later (file 04)
    max_processing: timedelta = timedelta(minutes=60)


TEAM_IT = "IT / Data"
TEAM_MARKETPLACE = "Marketplace management"
TEAM_CONTENT = "Content / PIM"
TEAM_OPS = "Operations / Customer service"
TEAM_MASTER = "Master data"


@dataclass
class Settings:
    # --- robot clock
    round_interval: timedelta = timedelta(minutes=30)
    round_offset: timedelta = timedelta(minutes=20)   # runs at :20 / :50, after readback at :15 / :45

    # --- ① push job alive
    push_heartbeat_max_age: timedelta = timedelta(minutes=65)   # > 2 runs missed

    # --- ③ processing
    rejections_before_alert: int = 2                 # consecutive ERRORs per listing
    stale_after: timedelta = timedelta(hours=2)      # no successful update for this long

    # --- ⑤ shown vs. target
    tolerance_units: int = 2                         # |gap| <= 2 is timing noise
    gap_persistence: int = 3                         # rounds (= 1.5 h)
    inactive_persistence: int = 2

    # --- alert lifecycle
    resolve_after_rounds: int = 2                    # finding absent this often -> resolved
    reminder_every: dict = field(default_factory=lambda: {
        Severity.CRITICAL: timedelta(hours=4),
        Severity.HIGH: timedelta(hours=24),        # the daily digest covers the rest
    })
    digest_local_hour: int = 8                       # daily digest at 08:00 Vienna

    # --- channels
    profiles: dict = field(default_factory=lambda: {
        "AMZ-DE": ChannelProfile(asynchronous=True),
        "AMZ-FR": ChannelProfile(asynchronous=True),
        "AMZ-IT": ChannelProfile(asynchronous=True),
        "AMZ-UK": ChannelProfile(asynchronous=True),
        "SHOPIFY": ChannelProfile(asynchronous=False),
    })
    channel_group_min_skus: int = 3                  # >= 3 SKUs failing alike -> one channel alert

    # Listings we know about and deliberately do not track (e.g. retired offers).
    ignored_listings: set = field(default_factory=set)

    # --- notification channels by severity
    routes: dict = field(default_factory=lambda: {
        Severity.CRITICAL: ["phone (on-call)", "Teams", "e-mail"],
        Severity.HIGH: ["Teams", "e-mail"],
        Severity.WARNING: ["Teams"],
        Severity.INFO: ["daily digest"],
    })


def rejection_team(message: str | None) -> tuple[str, str]:
    """Map a channel error message to (category, responsible team)."""
    msg = (message or "").lower()
    if "pflichtattribut" in msg or "fehlt" in msg or "missing" in msg:
        return "required attribute missing (master data)", TEAM_CONTENT
    if "ungültig" in msg or "invalid" in msg:
        return "invalid attribute value (listing settings)", TEAM_MARKETPLACE
    return "unknown rejection", TEAM_IT
