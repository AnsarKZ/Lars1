"""End-to-end: replay the whole week and pin the expected incidents."""
from datetime import datetime, timezone

import pytest

from stockrecon.config import Settings
from stockrecon.engine import Engine
from stockrecon.sources.csv_replay import CsvReplaySource


class Silent:
    def send(self, e): pass
    def digest(self, text): pass


@pytest.fixture(scope="module")
def alerts():
    src = CsvReplaySource("data")
    first, last = src.time_bounds()
    result = Engine(src, Settings(), Silent()).run(first, last)
    return {(a.type, a.channel, a.channel_sku, a.key[-1]): a for a in result.manager.history}


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def find(alerts, type_, channel=None, sku=None):
    hits = [a for (t, c, s, _), a in alerts.items()
            if t == type_ and (channel is None or c == channel) and (sku is None or s == sku)]
    assert hits, f"expected {type_} {channel} {sku}"
    return hits[0]


def test_problem_1_amazon_de_rejections_caught_long_before_overselling(alerts):
    rejected = find(alerts, "LISTING_REJECTED", "AMZ-DE", "LN-IF750-ANT")
    negative = find(alerts, "STOCK_NEGATIVE")
    assert rejected.opened_at <= utc("2026-09-25T11:00")
    assert negative.opened_at - rejected.opened_at > (utc("2026-09-27") - utc("2026-09-25"))
    assert find(alerts, "SHOWN_TOO_HIGH", "AMZ-DE", "LN-IF750-ANT").max_severity.name == "CRITICAL"


def test_problem_2_inactive_listing_in_italy(alerts):
    a = find(alerts, "LISTING_INACTIVE", "AMZ-IT", "LN-SPM-SET")
    assert a.opened_at <= utc("2026-09-25T08:00")


def test_problem_3_amazon_fr_missing_weight(alerts):
    a = find(alerts, "LISTING_REJECTED", "AMZ-FR", "LN-BK-BAM-L")
    assert a.opened_at <= utc("2026-09-24T07:00")
    assert a.team == "Content / PIM"


def test_infrastructure_incidents(alerts):
    assert find(alerts, "PUSH_JOB_DOWN").opened_at <= utc("2026-09-27T00:00")
    uk = find(alerts, "CHANNEL_PUSH_FAILING", "AMZ-UK")
    assert uk.opened_at == utc("2026-09-28T06:20") and uk.resolved_at is not None
    find(alerts, "UNMAPPED_LISTING", "AMZ-DE", "LN-TB-350-ALT")


def test_no_alert_floods_or_noise(alerts):
    assert len(alerts) <= 15
    types = {t for t, *_ in alerts}
    assert "SHOWN_TOO_LOW" not in types          # timing noise is absorbed
    assert "PUSH_FAILED" not in types            # 429s were all retried successfully
    assert not any(s == "LN-GK-18" for _, _, s, _ in alerts)   # one-off zero readings ignored
