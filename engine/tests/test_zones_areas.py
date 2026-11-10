"""Zones as drawn areas, scripted frame by frame (spec 025, T023 and T048).

A zone is a polygon on a camera and a person is inside when their FEET are.
The scene machine itself is the old one, re-keyed to the zone; the checks here
are the parts spec 025 added (feet, several zones on a camera, alert after N,
closing on pause/delete/hours) and the three traps that once shipped as bugs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_zones_live import (
    ARRIVES, FakeDetector, FakeRecorder, START, frame,
    walk, worker,
)
from vg.areas import Area, FULL_FRAME
from vg.config import HoursConfig
from vg.events.zones import SceneStore
from vg.features import zones as zones_feature
from vg.infer.persons import DetectedPerson

LEFT_HALF = ((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0))
RIGHT_HALF = ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0))
DESK = ((0.1, 0.5), (0.4, 0.5), (0.4, 0.9), (0.1, 0.9))


def zone(zone_id="z1", polygon=DESK, camera="cam-a", **kw):
    base = dict(id=zone_id, kind="zone", name=zone_id.upper(), camera_id=camera,
                polygon=polygon, hours_mode="always", alert_after_seconds=0.0)
    base.update(kw)
    return Area(**base)


class Standing:
    """A detector whose people stand where the test says (box, not feet)."""

    def __init__(self):
        self.boxes: list[tuple[float, float, float, float]] = []
        self.asked: list[str] = []

    def detect(self, frame):
        self.asked.append(frame.camera_id)
        return [DetectedPerson(x=x, y=y, w=w, h=h, confidence=0.9)
                for x, y, w, h in self.boxes]


def feed(zw, detector, boxes, seconds, start=0.0, step=1.0):
    """The same people on every frame for `seconds`."""
    detector.boxes = boxes
    at = start
    n = int(start * 10)
    while at <= start + seconds + 1e-9:
        zw.analyse(frame("cam-a", at=at, sequence=n))
        at += step
        n += 1


@pytest.fixture
def scenes(tmp_path):
    store = SceneStore(tmp_path / "scenes.db")
    yield store
    store.close_db()


# a person whose feet are at (0.25, 0.8): inside DESK
FEET_IN = (0.2, 0.2, 0.1, 0.6)
# body spans the desk from above but feet at (0.25, 0.3): outside DESK
BODY_ONLY = (0.2, -0.2, 0.1, 0.5)


class TestFeetNotBodies:
    def test_feet_inside_opens_a_scene(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d, areas=[zone()])
        feed(zw, d, [FEET_IN], 3)
        scene = scenes.recent(1)[0]
        assert scene.zone_id == "z1" and scene.camera_id == "cam-a"

    def test_a_body_overlapping_from_above_logs_nothing(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d, areas=[zone()])
        feed(zw, d, [BODY_ONLY], 10)
        assert scenes.recent(1) == []

    def test_the_result_counts_people_per_zone(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d,
                    areas=[zone("l", LEFT_HALF), zone("r", RIGHT_HALF)])
        d.boxes = [FEET_IN, (0.7, 0.2, 0.1, 0.6), (0.75, 0.2, 0.1, 0.6)]
        result = zw.analyse(frame("cam-a", at=0.0))
        counts = {r.zone_id: r.people for r in result.zones}
        assert counts == {"l": 1, "r": 2}
        assert result.people == 3 and result.restricted is True


class TestFullFrameIsTheOldBehaviour:
    """SC-404 stood in for by the scripted walks: the same scenes as before."""

    SCRIPT = ARRIVES + [(2.5, 0), (6.5, 0), (6.8, 1), (7.2, 1), (14.0, 0),
                        (30.0, 1), (32.0, 1)]

    def test_a_full_frame_polygon_logs_what_a_whole_camera_zone_did(self, scenes):
        d = FakeDetector()                       # one person, feet at (0.5, 0.8)
        zw = worker(scenes, detector=d, areas=[zone("cam-a", FULL_FRAME)])
        walk(zw, d, self.SCRIPT)
        logged = list(reversed(scenes.recent(1)))
        assert [(s.started_at - START).total_seconds() for s in logged] \
            == [0.0, 30.0]
        assert logged[0].end_reason == "nobody" and logged[1].running

    def test_a_person_on_the_bottom_edge_is_inside_the_whole_frame(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d, areas=[zone("cam-a", FULL_FRAME)])
        feed(zw, d, [(0.4, 0.4, 0.2, 0.6)], 3)      # feet at y == 1.0
        assert len(scenes.recent(1)) == 1


class TestTwoZonesOnOneCamera:
    def test_one_person_in_both_is_two_entries_and_one_clip(self, scenes, tmp_path):
        class OnePerCamera(FakeRecorder):
            """Like the real recorder: a second start on a camera refuses."""

            def start(self, camera_id, actor):
                from vg.ingest.recorder import AlreadyRecording

                if camera_id in self._running:
                    raise AlreadyRecording(camera_id)
                return super().start(camera_id, actor)

        recorder = OnePerCamera(tmp_path / "clips")
        d = Standing()
        both = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        zw = worker(scenes, detector=d, recorder=recorder,
                    areas=[zone("a", both), zone("b", both)])
        feed(zw, d, [FEET_IN], 3)
        logged = scenes.recent(1)
        assert {s.zone_id for s in logged} == {"a", "b"}
        assert recorder.started == ["cam-a"], "one recorder per camera"
        quiet = [s for s in logged if s.clip_state != "recording"]
        assert len(quiet) == 1
        assert quiet[0].clip_reason == (
            "No clip - recorded under the other zone's entry")

    def test_a_person_in_one_zone_does_not_open_the_other(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d,
                    areas=[zone("l", LEFT_HALF), zone("r", RIGHT_HALF)])
        feed(zw, d, [FEET_IN], 3)
        assert [s.zone_id for s in scenes.recent(1)] == ["l"]


class TestAlertAfterN:
    def hook(self, scenes):
        calls = []
        scenes.on_open = lambda sid, cam, at, cont, zid: calls.append((sid, cont, zid))
        return calls

    def test_zero_alerts_at_confirmation(self, scenes):
        calls = self.hook(scenes)
        d = FakeDetector()
        zw = worker(scenes, detector=d, areas=[zone("z", FULL_FRAME)])
        walk(zw, d, ARRIVES)
        assert len(calls) == 1

    def test_ten_seconds_inside_four_seconds_logs_but_never_alerts(self, scenes):
        calls = self.hook(scenes)
        d = FakeDetector()
        zw = worker(scenes, detector=d,
                    areas=[zone("z", FULL_FRAME, alert_after_seconds=10.0)])
        walk(zw, d, [(0.0, 1), (2.0, 1), (4.0, 1), (4.5, 0), (10.5, 0)])
        scene = scenes.recent(1)[0]
        assert calls == [] and scene.alerted is False
        assert scene.running is False

    def test_fifteen_seconds_alerts_once(self, scenes):
        calls = self.hook(scenes)
        d = FakeDetector()
        zw = worker(scenes, detector=d,
                    areas=[zone("z", FULL_FRAME, alert_after_seconds=10.0)])
        walk(zw, d, [(float(t), 1) for t in range(0, 16)])
        assert len(calls) == 1 and calls[0][1] is False
        assert scenes.recent(1)[0].alerted is True

    def test_a_short_visit_that_never_alerted_does_not_silence_the_next(
            self, scenes):
        """Trap: `_announced` means "an alert was raised", not "a scene opened"."""
        calls = self.hook(scenes)
        d = FakeDetector()
        zw = worker(scenes, detector=d,
                    areas=[zone("z", FULL_FRAME, alert_after_seconds=10.0)])
        # four seconds, gone, back 20 s later and stay the full delay
        walk(zw, d, [(0.0, 1), (2.0, 1), (4.0, 1), (4.5, 0), (10.0, 0)]
             + [(30.0 + t, 1) for t in range(0, 16)])
        assert len(calls) == 1
        assert scenes.recent(1)[0].alerted is True

    def test_leaving_and_returning_inside_a_minute_is_one_incident(self, scenes):
        calls = self.hook(scenes)
        d = FakeDetector()
        zw = worker(scenes, detector=d, areas=[zone("z", FULL_FRAME)])
        walk(zw, d, ARRIVES + [(3.0, 0), (9.0, 0), (40.0, 1), (42.0, 1)])
        assert len(scenes.recent(1)) == 2
        assert len(calls) == 2 and [c[1] for c in calls] == [False, True]


class TestStandingDown:
    def make(self, scenes, **kw):
        d = FakeDetector()
        zw = worker(scenes, detector=d, areas=[zone("z", FULL_FRAME, **kw)])
        walk(zw, d, ARRIVES)
        assert scenes.recent(1)[0].running
        return zw, d

    def test_pause_closes_on_the_next_frame_as_switched_off(self, scenes):
        zw, d = self.make(scenes)
        zw.set_areas([zone("z", FULL_FRAME, paused=True)])
        assert scenes.recent(1)[0].running, "not closed from the API thread"
        walk(zw, d, [(3.0, 1)])
        assert scenes.recent(1)[0].end_reason == "switched_off"

    def test_delete_closes_on_the_next_frame_as_switched_off(self, scenes):
        zw, d = self.make(scenes)
        zw.set_areas([])
        assert scenes.recent(1)[0].running
        walk(zw, d, [(3.0, 1)])
        assert scenes.recent(1)[0].end_reason == "switched_off"

    def test_hours_ending_closes_as_hours(self, scenes):
        d = FakeDetector()
        window = zone("z", FULL_FRAME, hours_mode="custom",
                      hours_from="23:00", hours_to="23:59")

        class Clock:
            def local(self, when):
                return when
        zw = worker(scenes, detector=d, areas=[window], clock=Clock(),
                    hours=lambda: HoursConfig())
        base = datetime(2026, 11, 10, 23, 58, tzinfo=timezone.utc)
        from vg.ingest.source import Frame
        import numpy as np

        def at(sec, n):
            return Frame(camera_id="cam-a",
                         image=np.zeros((4, 4, 3), dtype=np.uint8),
                         captured_at=base + timedelta(seconds=sec), sequence=n)

        d.people = 1
        zw.analyse(at(0, 0))
        zw.analyse(at(2, 1))
        assert scenes.recent(2)[0].running
        zw.analyse(at(100, 2))                    # 23:59:40, past the end: closed
        assert scenes.recent(2)[0].end_reason == "hours"


class TestNothingWatchingCostsNothing:
    def test_a_paused_zone_never_reaches_the_detector(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d, areas=[zone("z", FULL_FRAME, paused=True)])
        feed(zw, d, [FEET_IN], 3)
        assert d.asked == []

    def test_a_camera_with_no_zone_never_reaches_the_detector(self, scenes):
        d = Standing()
        zw = worker(scenes, detector=d, areas=[zone("z", FULL_FRAME, camera="cam-b")])
        feed(zw, d, [FEET_IN], 3)
        assert d.asked == []

    def test_restricted_lists_cameras_with_a_watching_zone(self, scenes):
        zw = worker(scenes, areas=[zone("a", FULL_FRAME),
                                   zone("b", FULL_FRAME, camera="cam-b", paused=True)])
        assert zw.restricted() == {"cam-a"}


class TestScenesCarryTheirZone:
    def test_a_scene_names_its_zone(self, scenes):
        d = FakeDetector()
        zw = worker(scenes, detector=d, areas=[zone("desk", FULL_FRAME)])
        walk(zw, d, ARRIVES)
        assert scenes.recent(1)[0].zone_id == "desk"


class TestTraps:
    """T048: one test for each bug the plan named."""

    def test_the_busy_sentence_does_not_blame_a_person(self):
        assert zones_feature.BUSY_REASON == (
            "No clip - recorded under the other zone's entry")

    def test_the_replaced_entry_is_listed_without_a_clip(self, tmp_path):
        from test_zones_live import live_store, with_areas
        scenes = SceneStore(tmp_path / "s.db")
        try:
            for i in range(4):
                sid = scenes.open("cam-a", START + timedelta(minutes=i),
                                  zone_id="cam-a")
                scenes.start_clip(sid)
                clip = tmp_path / f"{i}.mp4"
                clip.write_bytes(b"x")
                scenes.attach_clip(sid, clip)
            store = live_store(tmp_path, scene_store=scenes)
            areas = with_areas(store, tmp_path)
            try:
                rows = store.breaches(1)
            finally:
                areas.close_db()
            assert len(rows) == 4
            replaced = [b for b in rows if b.clip_state == "replaced"]
            assert len(replaced) == 1 and replaced[0].clip is None
        finally:
            scenes.close_db()

    def test_import_key_survives_a_soft_delete(self, tmp_path):
        from vg.areas import AreaStore, import_legacy
        store = AreaStore(tmp_path / "a.db")
        try:
            kwargs = dict(cameras_restricted={"cam-a": True},
                          scene_camera_ids=[], camera_names={"cam-a": "A"},
                          yaml_zones=[], hours=HoursConfig())
            import_legacy(store, **kwargs)
            only = store.list(kind="zone")[0]
            store.soft_delete(only.id, "mona")
            import_legacy(store, **kwargs)
            assert store.list(kind="zone") == []
            assert store.get(only.id).import_key is not None
        finally:
            store.close_db()
