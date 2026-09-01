from __future__ import annotations

import pytest
from conftest import T0, obs, stay

from loiterwatch import DwellRule, Engine, Event, EventKind


def test_cooldown_suppresses_duplicate_alerts():
    rule = DwellRule("dwell", zones=["atm"], threshold_s=30, repeat_every_s=1,
                     cooldown_s=100)
    eng = Engine([rule], exit_grace=5.0, tick_s=1.0)
    stay(eng, "t1", "atm", T0, T0 + 250)
    # without the cooldown this would fire ~220 times
    assert 2 <= len(eng.alerts) <= 3


def test_replay_is_deterministic():
    events = [obs("t1", "atm", T0 + i) for i in range(0, 400, 2)]
    runs = []
    for _ in range(2):
        eng = Engine([DwellRule("dwell", zones=["atm"], threshold_s=180)],
                     exit_grace=5.0, tick_s=1.0)
        eng.ingest_all(events)
        runs.append([(a.ts, a.rule_id, a.track_id) for a in eng.alerts])
    assert runs[0] == runs[1]


def test_alert_fires_between_events_not_on_the_next_one():
    """Threshold crossing must not wait for the next observation to arrive."""
    rule = DwellRule("dwell", zones=["atm"], threshold_s=60, min_observations=2)
    eng = Engine([rule], exit_grace=600.0, tick_s=1.0)
    eng.ingest(obs("t1", "atm", T0))
    eng.ingest(obs("t1", "atm", T0 + 5))
    eng.ingest(obs("t1", "atm", T0 + 300))  # 295s gap in the log
    assert eng.alerts[0].ts == pytest.approx(T0 + 60)


def test_explicit_enter_resets_the_visit():
    rule = DwellRule("dwell", zones=["atm"], threshold_s=100)
    eng = Engine([rule], exit_grace=600.0, tick_s=1.0)
    stay(eng, "t1", "atm", T0, T0 + 90)
    eng.ingest(Event(ts=T0 + 91, kind=EventKind.ENTER, zone="atm", track_id="t1"))
    eng.ingest(obs("t1", "atm", T0 + 150))
    assert eng.alerts == []


def test_occupancy_reflects_current_state():
    eng = Engine([DwellRule("d", threshold_s=9999)], exit_grace=5.0, tick_s=1.0)
    eng.ingest(obs("t1", "atm", T0))
    eng.ingest(obs("t2", "door", T0))
    assert eng.occupancy() == {"atm": ["t1"], "door": ["t2"]}
    eng.advance(T0 + 60)
    assert eng.occupancy() == {"atm": [], "door": []}


def test_out_of_order_timestamps_do_not_rewind_the_clock():
    eng = Engine([DwellRule("d", threshold_s=30)], exit_grace=5.0, tick_s=1.0)
    eng.ingest(obs("t1", "atm", T0 + 100))
    eng.ingest(obs("t1", "atm", T0 + 50))  # late arrival
    assert eng.world.now >= T0 + 100
