"""Rolling knowledge the robot builds up round by round.

Everything here is derived only from data already seen, so the replay never
looks into the future.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Batch, Order, PushAttempt, Readback

Key = tuple[str, str]   # (channel, channel_sku)


@dataclass
class ListingState:
    last_submission: str | None = None
    last_sent_qty: int | None = None
    last_success_ts: datetime | None = None
    consecutive_errors: int = 0
    first_error_ts: datetime | None = None
    last_error_msg: str | None = None
    last_readback: Readback | None = None


@dataclass
class State:
    start: datetime
    stock: dict[str, int] = field(default_factory=dict)            # sku -> available
    stock_ts: datetime | None = None
    last_push_ts: datetime | None = None
    pushes_by_slot: dict[datetime, list[PushAttempt]] = field(default_factory=lambda: defaultdict(list))
    submissions: dict[str, tuple[Key, datetime]] = field(default_factory=dict)   # id -> (key, sent)
    pending: dict[str, datetime] = field(default_factory=dict)                  # id -> sent
    results_ts: dict[str, datetime] = field(default_factory=dict)               # id -> processed
    listings: dict[Key, ListingState] = field(default_factory=lambda: defaultdict(ListingState))
    orders: deque[Order] = field(default_factory=deque)                          # last 7 days
    readbacks: list[Readback] = field(default_factory=list)                     # this round only
    seen_unmapped: dict[Key, datetime] = field(default_factory=dict)
    unmapped_orders: dict[Key, int] = field(default_factory=lambda: defaultdict(int))
    quality_notes: list = field(default_factory=list)                            # this round only

    def ingest(self, batch: Batch, slot_of) -> None:
        for s in batch.stock:
            self.stock[s.sku] = s.available
            self.stock_ts = s.ts

        for p in sorted(batch.pushes, key=lambda p: p.ts):
            self.pushes_by_slot[slot_of(p.ts)].append(p)
            self.last_push_ts = max(self.last_push_ts or p.ts, p.ts)
            if p.submission_id:
                key = (p.channel, p.channel_sku)
                self.submissions[p.submission_id] = (key, p.ts)
                self.pending[p.submission_id] = p.ts
                st = self.listings[key]
                st.last_submission = p.submission_id
                st.last_sent_qty = p.qty

        for r in sorted(batch.processing, key=lambda r: r.ts):
            self.pending.pop(r.submission_id, None)
            self.results_ts[r.submission_id] = r.ts
            st = self.listings[(r.channel, r.channel_sku)]
            if r.success:
                st.last_success_ts = r.ts
                st.consecutive_errors = 0
                st.first_error_ts = None
                st.last_error_msg = None
            else:
                st.consecutive_errors += 1
                st.first_error_ts = st.first_error_ts or r.ts
                st.last_error_msg = r.message

        self.orders.extend(sorted(batch.orders, key=lambda o: o.ts))

        self.readbacks = list(batch.readbacks)
        for rb in self.readbacks:
            self.listings[(rb.channel, rb.channel_sku)].last_readback = rb
        self.quality_notes = list(batch.quality)

    def prune(self, now: datetime) -> None:
        """Forget old history so memory stays flat in production."""
        for slot in [s for s in self.pushes_by_slot if s < now - timedelta(days=1)]:
            del self.pushes_by_slot[slot]
        while self.orders and self.orders[0].ts < now - timedelta(days=7):
            self.orders.popleft()

    def orders_since(self, key: Key, since: datetime, until: datetime) -> int:
        return sum(o.qty for o in self.orders
                   if (o.channel, o.channel_sku) == key and since < o.ts <= until)

    def daily_sales(self, keys: list[Key], now: datetime) -> float:
        """Average units/day over the observed window (max 7 days)."""
        days = max((now - self.start) / timedelta(days=1), 0.5)
        days = min(days, 7)
        ks = set(keys)
        return sum(o.qty for o in self.orders if (o.channel, o.channel_sku) in ks) / days
