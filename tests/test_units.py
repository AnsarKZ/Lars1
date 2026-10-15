from datetime import datetime, timedelta, timezone

from stockrecon.alerting import AlertManager
from stockrecon.checks import Context, push_delivery
from stockrecon.config import Settings
from stockrecon.models import ChannelRule, Finding, Listing, MasterData, PushAttempt, Severity
from stockrecon.sources.csv_replay import CsvReplaySource
from stockrecon.state import State

UTC = timezone.utc
T0 = datetime(2026, 9, 22, 6, 20, tzinfo=UTC)


def test_local_time_converted_to_utc():
    src = CsvReplaySource("data")
    first = src.fetch(datetime(2026, 9, 21, tzinfo=UTC), datetime(2026, 9, 21, 22, 0, tzinfo=UTC))
    # 01_lagerbestand "2026-09-22 00:00" Vienna (MESZ) == 21.09. 22:00 UTC
    assert first.stock and all(s.ts == datetime(2026, 9, 21, 22, 0, tzinfo=UTC) for s in first.stock)


def test_duplicate_readbacks_are_dropped_and_reported():
    src = CsvReplaySource("data")
    b = src.fetch(datetime(2026, 9, 25, 10, 0, tzinfo=UTC), datetime(2026, 9, 25, 10, 20, tzinfo=UTC))
    keys = [(r.channel, r.channel_sku, r.fulfillment) for r in b.readbacks]
    assert len(keys) == len(set(keys))
    assert b.quality and "duplicate" in b.quality[0].message


def test_target_rule_buffer_floor_and_cap():
    amazon, shopify = ChannelRule("AMZ-DE", 2, None), ChannelRule("SHOPIFY", 0, 50)
    assert amazon.target(125) == 123
    assert amazon.target(1) == 0 and amazon.target(-5) == 0
    assert shopify.target(125) == 50 and shopify.target(12) == 12


def test_mapping_is_exact_not_case_insensitive():
    md = CsvReplaySource("data").master_data()
    assert md.listing("SHOPIFY", "ln-if750-ant") is not None
    assert md.listing("SHOPIFY", "LN-IF750-ANT") is None
    assert md.listing("AMZ-DE", "LN-TB-350-ALT") is None


def _ctx(attempts, keys):
    md = MasterData([Listing(s, s, 10.0, c, s) for c, s in keys],
                    {c: ChannelRule(c, 2, None) for c, _ in keys})
    st = State(start=T0 - timedelta(hours=1))
    slot = T0 - timedelta(minutes=20)
    for p in attempts:
        st.pushes_by_slot[slot].append(p)
    return Context(now=T0, slot=slot, state=st, master=md, settings=Settings())


def _push(sku, attempt, status, sid, channel="AMZ-DE"):
    return PushAttempt("L1", T0 - timedelta(minutes=20 - attempt), channel, sku, 5, attempt,
                       status, "x", sid)


def test_429_with_successful_retry_is_silent():
    ctx = _ctx([_push("A", 1, 429, None), _push("A", 2, 202, "S1")], [("AMZ-DE", "A")])
    assert push_delivery(ctx).findings == []


def test_final_failure_alerts_and_channel_wide_failures_are_grouped():
    keys = [("AMZ-UK", s) for s in "ABCD"]
    ctx = _ctx([_push(s, 1, 403, None, "AMZ-UK") for s in "ABCD"], keys)
    findings = push_delivery(ctx).findings
    assert len(findings) == 1 and findings[0].type == "CHANNEL_PUSH_FAILING"
    assert findings[0].severity == Severity.CRITICAL and findings[0].persistence == 1


def _finding(persistence=2):
    return Finding(("X", "k"), "X", Severity.HIGH, "t", "d", "team", persistence=persistence)


def test_alert_lifecycle_persistence_hold_and_resolve():
    m = AlertManager(Settings())
    t = T0
    step = timedelta(minutes=30)
    assert m.process(t, [_finding()], set()) == []                     # 1st round: not yet
    assert [e.kind for e in m.process(t + step, [_finding()], set())] == ["OPEN"]
    assert m.process(t + 2 * step, [_finding()], set()) == []          # no duplicate alert
    assert m.process(t + 3 * step, [], {("X",)}) == []                 # held: unchanged
    assert m.process(t + 4 * step, [], set()) == []                    # absent once
    assert [e.kind for e in m.process(t + 5 * step, [], set())] == ["RESOLVED"]


def test_single_blip_never_becomes_an_alert():
    m = AlertManager(Settings())
    assert m.process(T0, [_finding(persistence=3)], set()) == []
    assert m.process(T0 + timedelta(minutes=30), [], set()) == []
    assert m.history == []
