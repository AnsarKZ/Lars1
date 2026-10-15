"""Turns per-round findings into alerts with a lifecycle.

  finding seen N rounds in a row  -> OPEN      (N = finding.persistence)
  severity rises while open       -> ESCALATED
  still open after reminder time  -> REMINDER  (critical/high only)
  absent for M rounds             -> RESOLVED  (M = settings.resolve_after_rounds)
  held (could not judge)          -> nothing changes

One alert per problem, not one per round: this is the flood protection.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime

from .config import Settings
from .models import Finding, Severity


@dataclass
class Alert:
    id: int
    key: tuple
    type: str
    severity: Severity
    title: str
    detail: str
    team: str
    opened_at: datetime
    first_seen: datetime
    channel: str | None = None
    channel_sku: str | None = None
    eur_at_risk: float = 0.0
    max_severity: Severity = Severity.INFO
    last_notified: datetime | None = None
    resolved_at: datetime | None = None


@dataclass
class AlertEvent:
    kind: str                 # OPEN / ESCALATED / REMINDER / RESOLVED
    at: datetime
    alert: Alert
    routes: list[str]


@dataclass
class _Track:
    streak: int = 0
    absent: int = 0
    first_seen: datetime | None = None
    alert: Alert | None = None


def _held(key: tuple, holds: set[tuple]) -> bool:
    return any(key[:len(h)] == h for h in holds)


@dataclass
class AlertManager:
    settings: Settings
    tracks: dict[tuple, _Track] = field(default_factory=dict)
    history: list[Alert] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    @property
    def open_alerts(self) -> list[Alert]:
        return [t.alert for t in self.tracks.values() if t.alert]

    def process(self, now: datetime, findings: list[Finding], holds: set[tuple]) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        present = {f.key: f for f in findings}

        for key, f in present.items():
            t = self.tracks.setdefault(key, _Track())
            t.streak += 1
            t.absent = 0
            t.first_seen = t.first_seen or now
            a = t.alert
            if a is None:
                if t.streak >= f.persistence:
                    a = Alert(next(self._ids), key, f.type, f.severity, f.title, f.detail, f.team,
                              opened_at=now, first_seen=t.first_seen, channel=f.channel,
                              channel_sku=f.channel_sku, eur_at_risk=f.eur_at_risk,
                              max_severity=f.severity, last_notified=now)
                    t.alert = a
                    self.history.append(a)
                    events.append(self._event("OPEN", now, a))
                continue
            escalated = f.severity > a.max_severity
            a.severity, a.title, a.detail, a.team = f.severity, f.title, f.detail, f.team
            a.eur_at_risk = max(a.eur_at_risk, f.eur_at_risk)
            if escalated:
                a.max_severity = f.severity
                a.last_notified = now
                events.append(self._event("ESCALATED", now, a))
            else:
                every = self.settings.reminder_every.get(a.severity)
                if every and now - a.last_notified >= every:
                    a.last_notified = now
                    events.append(self._event("REMINDER", now, a))

        for key in [k for k in self.tracks if k not in present]:
            if _held(key, holds):
                continue
            t = self.tracks[key]
            if t.alert is None:
                del self.tracks[key]          # never became an alert: just forget the streak
                continue
            t.absent += 1
            if t.absent >= self.settings.resolve_after_rounds:
                t.alert.resolved_at = now
                events.append(self._event("RESOLVED", now, t.alert))
                del self.tracks[key]
        return events

    def _event(self, kind: str, now: datetime, a: Alert) -> AlertEvent:
        sev = Severity.INFO if kind == "RESOLVED" else a.severity
        routes = self.settings.routes[sev] if kind != "RESOLVED" else ["Teams"]
        return AlertEvent(kind, now, a, routes)
