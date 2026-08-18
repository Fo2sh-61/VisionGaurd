from __future__ import annotations

import pytest
from conftest import T0, obs, signal, stay

from loiterwatch import DwellRule, Engine


def engine(**kw):
    rule = DwellRule("dwell", zones=["atm"], threshold_s=180, cooldown_s=60, **kw)
    return Engine([rule], exit_grace=5.0, tick_s=1.0)


def test_fires_exactly_at_threshold():
    eng = engine()
    stay(eng, "t1", "atm", T0, T0 + 179)
    assert eng.alerts == []
    stay(eng, "t1", "atm", T0 + 180, T0 + 180)
    assert len(eng.alerts) == 1
    assert eng.alerts[0].ts == pytest.approx(T0 + 180)
    assert eng.alerts[0].evidence["dwell_s"] == pytest.approx(180.0)


def test_no_alert_when_person_leaves_early():
    eng = engine()
    stay(eng, "t1", "atm", T0, T0 + 120)
    eng.advance(T0 + 400)  # long gone
    assert eng.alerts == []


def test_grace_period_bridges_detector_dropout():
    """A 4s tracking gap must not reset the dwell clock (grace is 5s)."""
    eng = engine()
    stay(eng, "t1", "atm", T0, T0 + 100)
    stay(eng, "t1", "atm", T0 + 104, T0 + 200)  # 4s hole
    assert len(eng.alerts) == 1
    assert eng.alerts[0].evidence["entered_at"] == pytest.approx(T0)


def test_gap_beyond_grace_restarts_the_clock():
    eng = engine()
    stay(eng, "t1", "atm", T0, T0 + 100)
    stay(eng, "t1", "atm", T0 + 130, T0 + 250)  # 30s hole > 5s grace
    assert eng.alerts == []  # second visit only reaches 120s


def test_escalation_fires_each_level_once():
    rule = DwellRule(
        "dwell", zones=["atm"], cooldown_s=1,
        thresholds=[{"after_s": 180, "severity": "warning"},
                    {"after_s": 600, "severity": "critical"}],
    )
    eng = Engine([rule], exit_grace=5.0, tick_s=1.0)
    stay(eng, "t1", "atm", T0, T0 + 700)
    sevs = [a.severity.value for a in eng.alerts]
    assert sevs == ["warning", "critical"]


def test_min_observations_guards_against_single_spurious_detection():
    rule = DwellRule("dwell", zones=["atm"], threshold_s=10, min_observations=5)
    eng = Engine([rule], exit_grace=600.0, tick_s=1.0)
    eng.ingest(obs("ghost", "atm", T0))
    eng.advance(T0 + 300)
    assert eng.alerts == []


def test_min_confidence_filters_weak_detections():
    rule = DwellRule("dwell", zones=["atm"], threshold_s=60, min_confidence=0.8)
    eng = Engine([rule], exit_grace=5.0, tick_s=1.0)
    stay(eng, "t1", "atm", T0, T0 + 120, conf=0.4)
    assert eng.alerts == []


def test_zone_scoping():
    eng = engine()
    stay(eng, "t1", "sidewalk", T0, T0 + 400)
    assert eng.alerts == []


def test_repeat_every_re_alerts_while_still_present():
    rule = DwellRule("dwell", zones=["atm"], threshold_s=60,
                     repeat_every_s=120, cooldown_s=0)
    eng = Engine([rule], exit_grace=5.0, tick_s=1.0)
    stay(eng, "t1", "atm", T0, T0 + 400)
    assert len(eng.alerts) >= 3
