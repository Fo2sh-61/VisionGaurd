"""Whole-camera-view restricted area: presence itself is the event."""
from __future__ import annotations

import pytest
from conftest import T0, obs, signal, stay

from loiterwatch import DEFAULT_ZONE, Engine, Event, IntrusionRule


def engine(**kw):
    return Engine([IntrusionRule("intrusion", **kw)], exit_grace=5.0, tick_s=1.0)


def frame_obs(track: str, ts: float, conf: float = 0.9) -> Event:
    return Event.from_dict({"ts": ts, "track_id": track, "confidence": conf})


def test_zone_defaults_to_frame_when_events_carry_none():
    ev = Event.from_dict({"ts": T0, "track_id": "t1"})
    assert ev.zone == DEFAULT_ZONE


def test_camera_id_becomes_the_zone():
    ev = Event.from_dict({"ts": T0, "track_id": "t1", "camera": "cam_07"})
    assert ev.zone == "cam_07"
    assert ev.camera == "cam_07"


def test_explicit_zone_still_wins_over_camera():
    ev = Event.from_dict({"ts": T0, "track_id": "t1", "camera": "cam_07",
                          "zone": "loading_bay"})
    assert ev.zone == "loading_bay"


def test_cameras_are_tracked_independently():
    eng = engine(confirm_s=3, min_observations=2)
    eng.ingest_all([
        Event.from_dict({"ts": T0 + i, "track_id": "t1", "camera": cam})
        for i in range(6) for cam in ("cam_01", "cam_02")
    ])
    zones = {a.zone for a in eng.alerts}
    assert zones == {"cam_01", "cam_02"}


def test_fires_after_the_confirmation_delay_not_before():
    eng = engine(confirm_s=3, min_observations=3)
    eng.ingest_all([frame_obs("t1", T0 + i) for i in range(3)])
    assert eng.alerts == []          # 2s of presence is not yet confirmed
    eng.ingest(frame_obs("t1", T0 + 3))
    assert len(eng.alerts) == 1
    assert eng.alerts[0].ts == pytest.approx(T0 + 3)
    assert eng.alerts[0].severity.value == "critical"


def test_single_frame_detector_noise_never_alerts():
    """A reflection or a blowing bag appears once; it must not page anyone."""
    eng = engine(confirm_s=3, min_observations=3)
    eng.ingest(frame_obs("noise", T0))
    eng.advance(T0 + 600)
    assert eng.alerts == []


def test_low_confidence_detections_are_ignored():
    eng = engine(confirm_s=3, min_observations=2, min_confidence=0.6)
    eng.ingest_all([frame_obs("t1", T0 + i, conf=0.35) for i in range(10)])
    assert eng.alerts == []


def test_authorized_presence_is_cleared_by_signal():
    eng = engine(confirm_s=3, min_observations=2, cleared_by=["badge_granted"])
    events = [frame_obs("t1", T0 + i) for i in range(30)]
    events.append(signal(DEFAULT_ZONE, "badge_granted", T0 + 1))
    eng.ingest_all(sorted(events, key=lambda e: e.ts))
    assert eng.alerts == []


def test_badge_after_the_alert_does_not_retroactively_clear_it():
    eng = engine(confirm_s=3, min_observations=2, cleared_by=["badge_granted"])
    events = [frame_obs("t1", T0 + i) for i in range(30)]
    events.append(signal(DEFAULT_ZONE, "badge_granted", T0 + 20))
    eng.ingest_all(sorted(events, key=lambda e: e.ts))
    assert len(eng.alerts) == 1


def test_escalation_on_continued_presence():
    eng = engine(confirm_s=3, min_observations=2, cooldown_s=1,
                 escalate=[{"after_s": 30, "severity": "critical"},
                           {"after_s": 120, "severity": "critical"}])
    eng.ingest_all([frame_obs("t1", T0 + i) for i in range(0, 150, 2)])
    assert [round(a.evidence["threshold_s"]) for a in eng.alerts] == [3, 30, 120]


def test_leaving_and_returning_alerts_again():
    eng = engine(confirm_s=3, min_observations=2, cooldown_s=1)
    eng.ingest_all([frame_obs("t1", T0 + i) for i in range(6)])
    eng.advance(T0 + 100)                       # gone, visit closes
    eng.ingest_all([frame_obs("t1", T0 + 100 + i) for i in range(6)])
    assert len(eng.alerts) == 2
