"""Overlay + live loop, driven by synthetic frames instead of a camera."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch import DwellRule, Engine, IntrusionRule, parse_config
from loiterwatch.live import Detection, Overlay, fmt_clock, next_threshold, run


class FakeDetector:
    """Reports one person, always, in a fixed box."""

    def __init__(self, track_id: str = "1", conf: float = 0.9) -> None:
        self.track_id, self.conf = track_id, conf
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return [Detection(self.track_id, (100, 80, 220, 400), self.conf)]


def blank_frames(n: int, w: int = 640, h: int = 480):
    for _ in range(n):
        yield np.zeros((h, w, 3), dtype=np.uint8)


def fake_clock(step: float = 0.1, start: float = 1_770_000_000.0):
    """Deterministic clock: each call advances by one frame interval."""
    state = {"t": start}

    def tick() -> float:
        state["t"] += step
        return state["t"]

    return tick


@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00"), (9, "0:09"), (65, "1:05"), (600, "10:00"), (3725, "1:02:05"),
])
def test_clock_formatting(seconds, expected):
    assert fmt_clock(seconds) == expected


def test_next_threshold_picks_the_soonest_upcoming_level():
    rules = [IntrusionRule("i", confirm_s=3,
                           escalate=[{"after_s": 15, "severity": "critical"},
                                     {"after_s": 60, "severity": "critical"}])]
    assert next_threshold(rules, "cam", dwell=0, now=0) == 3
    assert next_threshold(rules, "cam", dwell=4, now=0) == 15
    assert next_threshold(rules, "cam", dwell=20, now=0) == 60
    assert next_threshold(rules, "cam", dwell=99, now=0) is None


def test_next_threshold_ignores_rules_scoped_to_other_zones():
    rules = [DwellRule("d", zones=["other_cam"], threshold_s=10)]
    assert next_threshold(rules, "cam", dwell=0, now=0) is None


def test_overlay_draws_without_a_camera():
    engine = Engine([IntrusionRule("i", confirm_s=3)], exit_grace=3.0, tick_s=0.5)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = [Detection("1", (100, 80, 220, 400), 0.9)]
    out = Overlay("cam").draw(frame, dets, engine, {}, 1000.0, [], 30.0)
    assert out.shape == (480, 640, 3)
    assert out.any(), "overlay drew nothing onto the frame"


def test_label_is_drawn_above_the_box_not_over_it():
    engine = Engine([IntrusionRule("i", confirm_s=3)], exit_grace=3.0, tick_s=0.5)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    Overlay("cam").draw(frame, [Detection("1", (100, 200, 220, 400), 0.9)],
                        engine, {}, 1000.0, [], 30.0)
    band = frame[160:198, 100:220]          # strip just above the box top edge
    assert band.any(), "nothing rendered above the person"


def test_box_at_the_top_edge_does_not_crash():
    engine = Engine([IntrusionRule("i", confirm_s=3)], exit_grace=3.0, tick_s=0.5)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    Overlay("cam").draw(frame, [Detection("1", (0, 0, 120, 300), 0.9)],
                        engine, {}, 1000.0, [], 30.0)


def test_live_loop_runs_headless_and_raises_an_alert():
    config = parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "intrusion", "confirm_s": 0.2,
                   "min_observations": 2, "min_confidence": 0.5}],
    })
    detector = FakeDetector()
    engine = run(config, detector, window=False, camera="cam",
                 frame_source=blank_frames(40), clock=fake_clock())
    assert detector.calls == 40
    assert any(a.rule_id == "i" for a in engine.alerts)


def test_live_loop_ignores_low_confidence_detections():
    config = parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "intrusion", "confirm_s": 0.2,
                   "min_observations": 2, "min_confidence": 0.8}],
    })
    engine = run(config, FakeDetector(conf=0.35), window=False, camera="cam",
                 frame_source=blank_frames(40), clock=fake_clock())
    assert engine.alerts == []


def test_alarm_fires_once_per_alert(monkeypatch):
    from loiterwatch import live as live_mod

    calls = []
    monkeypatch.setattr(live_mod.alarm, "play", lambda severity: calls.append(severity))

    config = parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "intrusion", "confirm_s": 0.2,
                   "min_observations": 2}],
    })
    engine = run(config, FakeDetector(), window=False, camera="cam",
                 frame_source=blank_frames(40), clock=fake_clock())
    assert len(calls) == len(engine.alerts) > 0


def test_alarm_can_be_disabled(monkeypatch):
    from loiterwatch import live as live_mod

    calls = []
    monkeypatch.setattr(live_mod.alarm, "play", lambda severity: calls.append(severity))

    config = parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "intrusion", "confirm_s": 0.2,
                   "min_observations": 2}],
    })
    run(config, FakeDetector(), window=False, camera="cam",
        frame_source=blank_frames(40), clock=fake_clock(), play_alarm=False)
    assert calls == []


def test_alerts_are_logged_to_jsonl(tmp_path):
    import json
    log = tmp_path / "alerts.jsonl"
    config = parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "intrusion", "confirm_s": 0.2,
                   "min_observations": 2}],
    })
    run(config, FakeDetector(), window=False, camera="cam",
        log_path=str(log), frame_source=blank_frames(40), clock=fake_clock())
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows and rows[0]["rule_id"] == "i" and rows[0]["zone"] == "cam"
