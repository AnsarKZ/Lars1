"""The robot: wakes every 30 minutes, pulls what is new, asks the five
questions, and passes findings to the alert manager."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .alerting import AlertEvent, AlertManager
from .checks import VIENNA, Context, run_all
from .config import Settings
from .models import Severity
from .notify import Notifier
from .report import digest_text
from .sources.base import DataSource
from .state import State


def floor_slot(ts: datetime, interval: timedelta) -> datetime:
    epoch = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return epoch + ((ts - epoch) // interval) * interval


@dataclass
class RunResult:
    rounds: int = 0
    events: list[AlertEvent] = field(default_factory=list)
    manager: AlertManager | None = None
    state: State | None = None


class Engine:
    def __init__(self, source: DataSource, settings: Settings, notifier: Notifier,
                 run_log: Path | None = None, pause_s: float = 0.0):
        self.source = source
        self.settings = settings
        self.notifier = notifier
        self.manager = AlertManager(settings)
        self.run_log = run_log.open("w", encoding="utf-8") if run_log else None
        self.pause_s = pause_s

    def ticks(self, first: datetime, last: datetime):
        s = self.settings
        tick = floor_slot(first, s.round_interval) + s.round_offset
        while tick <= first:
            tick += s.round_interval
        while tick <= last + s.round_interval:
            yield tick
            tick += s.round_interval

    def run(self, first: datetime, last: datetime, until: datetime | None = None) -> RunResult:
        master = self.source.master_data()
        state = State(start=first)
        result = RunResult(manager=self.manager, state=state)
        prev = first
        for tick in self.ticks(first, last):
            if until and tick > until:
                break
            t0 = time.perf_counter()
            state.ingest(self.source.fetch(prev, tick),
                         lambda ts: floor_slot(ts, self.settings.round_interval))
            ctx = Context(now=tick, slot=tick - self.settings.round_offset,
                          state=state, master=master, settings=self.settings)
            checked = run_all(ctx)
            events = self.manager.process(tick, checked.findings, checked.holds)
            for e in events:
                self.notifier.send(e)
            result.events += events
            result.rounds += 1

            local = tick.astimezone(VIENNA)
            if local.hour == self.settings.digest_local_hour and local.minute < 30:
                self.notifier.digest(digest_text(tick, self.manager, state, master))

            if self.run_log:   # structured per-round log: what production ships to App Insights
                self.run_log.write(json.dumps({
                    "round_utc": tick.isoformat(), "findings": len(checked.findings),
                    "events": len(events), "open_alerts": len(self.manager.open_alerts),
                    "open_critical": sum(a.severity == Severity.CRITICAL
                                         for a in self.manager.open_alerts),
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}) + "\n")
            state.prune(tick)
            prev = tick
            if self.pause_s:
                time.sleep(self.pause_s)
        if self.run_log:
            self.run_log.close()
        return result
