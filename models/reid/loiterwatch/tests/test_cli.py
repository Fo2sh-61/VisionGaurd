from __future__ import annotations

import json
from pathlib import Path

from loiterwatch.cli import main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = str(ROOT / "examples" / "atm.yaml")
EVENTS = str(ROOT / "examples" / "atm_events.jsonl")


def test_validate_ok(capsys):
    assert main(["validate", "-c", CONFIG]) == 0
    assert "4 rule(s)" in capsys.readouterr().out


def test_types_lists_all_rules(capsys):
    assert main(["types"]) == 0
    out = capsys.readouterr().out
    for name in ("dwell", "repeat_entry", "no_transaction"):
        assert name in out


def test_replay_reproduces_the_atm_scenario(capsys):
    assert main(["replay", EVENTS, "-c", CONFIG, "--json"]) == 0
    alerts = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]
    by_rule = {a["rule_id"] for a in alerts}
    assert by_rule == {"atm_no_card", "atm_dwell", "atm_casing"}

    dwell = [a for a in alerts if a["rule_id"] == "atm_dwell"]
    assert [a["severity"] for a in dwell] == ["warning", "critical"]
    assert dwell[0]["time"].endswith("10:45:31+00:00")   # entered 10:42:31 + 3min
    assert all(a["track_id"] == "track-B" for a in dwell)

    # the customer who actually used the ATM is never alerted on
    assert all(a["track_id"] != "track-A" for a in alerts)


R_CONFIG = str(ROOT / "examples" / "restricted_area.yaml")
R_EVENTS = str(ROOT / "examples" / "restricted_events.jsonl")


def test_restricted_area_scenario(capsys):
    assert main(["replay", R_EVENTS, "-c", R_CONFIG, "--json"]) == 0
    alerts = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]

    # every alert lands on the camera-derived zone, no polygons configured
    assert {a["zone"] for a in alerts} == {"cam_07"}

    # the intruder escalates three times
    intruder = [a for a in alerts if a["track_id"] == "track-A"]
    assert [round(a["evidence"]["threshold_s"]) for a in intruder] == [3, 30, 300]

    # the badged engineer and the one-frame reflection are silent
    assert all(a["track_id"] not in ("track-B", "noise-1") for a in alerts)

    # the prober trips the repeat-entry rule
    assert any(a["rule_id"] == "perimeter_probing" for a in alerts)


def test_restricted_config_validates(capsys):
    assert main(["validate", "-c", R_CONFIG]) == 0
    out = capsys.readouterr().out
    assert "3 rule(s)" in out and "all zones" in out
