"""Plain data records shared by data sources, checks and alerting.

All timestamps are timezone-aware UTC datetimes. Conversion from local time
happens once, inside the data source, never in the checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


# ---------------------------------------------------------------- raw events

@dataclass(frozen=True)
class StockLevel:
    ts: datetime          # slot start (UTC)
    sku: str
    available: int        # may be negative (oversold)


@dataclass(frozen=True)
class Order:
    ts: datetime
    channel: str
    channel_sku: str
    qty: int
    order_id: str


@dataclass(frozen=True)
class PushAttempt:
    run_id: str
    ts: datetime
    channel: str
    channel_sku: str
    qty: int
    attempt: int
    http_status: int
    response: str
    submission_id: str | None   # None when the API refused the request


@dataclass(frozen=True)
class ProcessingResult:
    submission_id: str
    channel: str
    channel_sku: str
    ts: datetime
    success: bool
    message: str | None


@dataclass(frozen=True)
class Readback:
    ts: datetime
    channel: str
    channel_sku: str
    fulfillment: str           # DEFAULT = shipped by us, AMAZON_* = FBA
    qty: int | None            # None if the query failed
    listing_status: str | None # ACTIVE / INACTIVE / None
    query_status: str          # OK / TIMEOUT / ...


@dataclass(frozen=True)
class DataQualityNote:
    ts: datetime
    source: str
    message: str


@dataclass
class Batch:
    """Everything that became visible in the window (start, end]."""
    stock: list[StockLevel] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    pushes: list[PushAttempt] = field(default_factory=list)
    processing: list[ProcessingResult] = field(default_factory=list)
    readbacks: list[Readback] = field(default_factory=list)
    quality: list[DataQualityNote] = field(default_factory=list)


# --------------------------------------------------------------- master data

@dataclass(frozen=True)
class Listing:
    sku: str
    product: str
    price_eur: float
    channel: str
    channel_sku: str


@dataclass(frozen=True)
class ChannelRule:
    channel: str
    buffer: int
    max_qty: int | None   # None = no cap

    def target(self, available: int) -> int:
        """Stock the channel should show: available - buffer, >= 0, <= max."""
        qty = max(available - self.buffer, 0)
        return qty if self.max_qty is None else min(qty, self.max_qty)


@dataclass
class MasterData:
    listings: list[Listing]
    rules: dict[str, ChannelRule]

    def __post_init__(self) -> None:
        # Exact match on (channel, channel_sku). No case folding on purpose:
        # unknown spellings must surface as alerts, not be guessed.
        self.by_channel_sku = {(l.channel, l.channel_sku): l for l in self.listings}

    def listing(self, channel: str, channel_sku: str) -> Listing | None:
        return self.by_channel_sku.get((channel, channel_sku))

    @property
    def keys(self) -> list[tuple[str, str]]:
        return list(self.by_channel_sku)

    def channel_keys(self, channel: str) -> list[tuple[str, str]]:
        return [k for k in self.by_channel_sku if k[0] == channel]


# ------------------------------------------------------------------ findings

class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Finding:
    """One problem observed in one robot round (not yet an alert)."""
    key: tuple                 # stable identity, e.g. ("LISTING_REJECTED", "AMZ-DE", "LN-IF750-ANT")
    type: str
    severity: Severity
    title: str
    detail: str
    team: str
    persistence: int = 1       # consecutive rounds before an alert is opened
    channel: str | None = None
    channel_sku: str | None = None
    eur_at_risk: float = 0.0
