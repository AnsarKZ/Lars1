"""Alert sinks. The prototype prints to the console and writes JSON lines;
production would add Teams webhooks, e-mail and an on-call pager behind the
same interface."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .alerting import AlertEvent
from .checks import local
from .models import Severity

ICON = {Severity.CRITICAL: "🔴", Severity.HIGH: "🟠", Severity.WARNING: "🟡", Severity.INFO: "🔵"}
KIND = {"OPEN": "NEW", "ESCALATED": "WORSE", "REMINDER": "STILL", "RESOLVED": "FIXED"}


class Notifier(Protocol):
    def send(self, event: AlertEvent) -> None: ...
    def digest(self, text: str) -> None: ...


class ConsoleNotifier:
    def __init__(self, min_severity: Severity = Severity.WARNING, color: bool = True):
        self.min_severity = min_severity
        self.color = color

    def send(self, e: AlertEvent) -> None:
        a = e.alert
        if a.max_severity < self.min_severity:
            return
        when = f"{local(e.at)} Vienna | {e.at:%H:%M} UTC"
        if e.kind == "RESOLVED":
            took = e.at - a.first_seen
            print(f"[{when}] ✅ {KIND[e.kind]:5} #{a.id} {a.title}  (lasted {took})")
            return
        icon = ICON[a.severity]
        print(f"[{when}] {icon} {KIND[e.kind]:5} #{a.id} {a.severity.name:8} {a.title}")
        print(f"{'':28}{a.detail}")
        print(f"{'':28}→ {a.team} via {', '.join(e.routes)}")

    def digest(self, text: str) -> None:
        print(text)


class JsonlNotifier:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("w", encoding="utf-8")

    def send(self, e: AlertEvent) -> None:
        a = e.alert
        self.fh.write(json.dumps({
            "event": e.kind, "at_utc": e.at.isoformat(), "alert_id": a.id, "type": a.type,
            "severity": a.severity.name, "title": a.title, "detail": a.detail, "team": a.team,
            "routes": e.routes, "channel": a.channel, "channel_sku": a.channel_sku,
            "eur_at_risk": round(a.eur_at_risk, 2)}, ensure_ascii=False) + "\n")
        self.fh.flush()

    def digest(self, text: str) -> None:
        pass


class FanOut:
    def __init__(self, *sinks: Notifier):
        self.sinks = sinks

    def send(self, e: AlertEvent) -> None:
        for s in self.sinks:
            s.send(e)

    def digest(self, text: str) -> None:
        for s in self.sinks:
            s.digest(text)
