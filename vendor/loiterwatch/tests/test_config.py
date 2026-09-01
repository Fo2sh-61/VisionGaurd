from __future__ import annotations

from pathlib import Path

import pytest
from conftest import T0, stay

from loiterwatch import load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "atm.yaml"


def test_example_config_loads():
    config = load_config(str(EXAMPLE))
    assert [r.rule_id for r in config.rules] == [
        "atm_dwell", "atm_dwell_overnight", "atm_casing", "atm_no_card"
    ]
    assert config.exit_grace_s == 5


def test_defaults_are_merged_into_each_rule():
    config = parse_config({
        "defaults": {"cooldown_s": 42},
        "rules": [{"id": "d", "type": "dwell", "threshold_s": 10}],
    })
    assert config.rules[0].cooldown_s == 42


def test_rule_override_beats_default():
    config = parse_config({
        "defaults": {"severity": "info"},
        "rules": [{"id": "d", "type": "dwell", "threshold_s": 10,
                   "severity": "critical"}],
    })
    assert config.rules[0].severity.value == "critical"


def test_unknown_rule_type_is_rejected():
    with pytest.raises(ValueError, match="unknown rule type"):
        parse_config({"rules": [{"id": "x", "type": "telepathy"}]})


def test_unknown_zone_is_rejected():
    with pytest.raises(ValueError, match="unknown zone"):
        parse_config({
            "zones": {"atm": {}},
            "rules": [{"id": "d", "type": "dwell", "threshold_s": 5,
                       "zones": ["parking_lot"]}],
        })


def test_duplicate_rule_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate rule id"):
        parse_config({"rules": [
            {"id": "d", "type": "dwell", "threshold_s": 5},
            {"id": "d", "type": "dwell", "threshold_s": 9},
        ]})


def test_dwell_without_threshold_is_rejected():
    with pytest.raises(ValueError, match="threshold"):
        parse_config({"rules": [{"id": "d", "type": "dwell"}]})


def test_empty_config_is_rejected():
    with pytest.raises(ValueError, match="no rules"):
        parse_config({})


def test_active_hours_gating_overnight_window():
    config = parse_config({"rules": [{
        "id": "night", "type": "dwell", "threshold_s": 10,
        "active_hours": {"start": "23:00", "end": "05:00"},
    }]})
    rule = config.rules[0]
    import datetime as dt
    def ts(hour):
        return dt.datetime(2026, 8, 9, hour, 30, tzinfo=dt.timezone.utc).timestamp()
    assert rule.in_schedule(ts(23))
    assert rule.in_schedule(ts(2))
    assert not rule.in_schedule(ts(13))


def test_cumulative_dwell_sums_across_visits():
    from conftest import T0, exit_event, stay
    from loiterwatch import CumulativeDwellRule, Engine

    rule = CumulativeDwellRule("total", zones=["atm"], threshold_s=60, window_s=600)
    eng = Engine([rule], exit_grace=2.0, tick_s=1.0)
    for i in range(3):                       # three 25s visits == 75s total
        start = T0 + i * 120
        stay(eng, "t1", "atm", start, start + 25)
        eng.ingest(exit_event("t1", "atm", start + 26))
    assert len(eng.alerts) == 1
    assert eng.alerts[0].evidence["visits"] == 3
    assert eng.alerts[0].evidence["total_dwell_s"] >= 60


def test_cumulative_dwell_ignores_visits_outside_the_window():
    from conftest import T0, exit_event, stay
    from loiterwatch import CumulativeDwellRule, Engine

    rule = CumulativeDwellRule("total", zones=["atm"], threshold_s=60, window_s=100)
    eng = Engine([rule], exit_grace=2.0, tick_s=1.0)
    for i in range(3):
        start = T0 + i * 200                 # spaced beyond the window
        stay(eng, "t1", "atm", start, start + 40)
        eng.ingest(exit_event("t1", "atm", start + 41))
    assert eng.alerts == []
