"""Restricted zones, end to end, without a camera or a model.

A zone here IS a camera: a toggled-on camera's whole frame is the restricted
area. There is no polygon to draw, so nothing in this file tests geometry —
`test_zones.py` still owns that for the polygon zones in engine.yaml.

What is under test is the part that can lie:

  * the camera list is the real roster, never a fixture ("Server room" is the
    name of a bug here, not a room)
  * one walk is one entry, even when detection flickers
  * an entry whose clip is gone says so, and its button is disabled
  * nothing is recorded on a camera nobody switched on

The scene state machine is fed fake frames with fake detections and a clock the
test controls, so a two-minute limit takes microseconds to prove and a 0.9
second flicker is exactly 0.9 seconds every run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.api import schemas as S
from vg.api.store import MockStore
from vg.events.zones import SceneStore
from vg.infer.persons import DetectedPerson
from vg.ingest.source import Frame
from vg.ingest.store import CameraStore

START = datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

def frame(camera_id: str = "cam-a", *, at: float = 0.0, sequence: int = 0) -> Frame:
    """One frame, `at` seconds after START. The image is never looked at."""
    return Frame(
        camera_id=camera_id,
        image=np.zeros((4, 4, 3), dtype=np.uint8),
        captured_at=START + timedelta(seconds=at),
        sequence=sequence,
    )


def person() -> DetectedPerson:
    return DetectedPerson(x=0.4, y=0.2, w=0.2, h=0.6, confidence=0.9)


class FakeDetector:
    """Stands in for SharedDetection. Records every camera it was asked about.

    The recording is the point: SC-005 says a camera nobody restricted must
    never reach the model at all, and only this can prove it.
    """

    def __init__(self, people: int = 0) -> None:
        self.people = people
        self.asked: list[str] = []

    def detect(self, frame):
        self.asked.append(frame.camera_id)
        return [person() for _ in range(self.people)]


class FakeRecording:
    def __init__(self, camera_id: str, path: Path | None, state: str = "recording",
                 reason: str | None = None) -> None:
        self.id = f"rec-{camera_id}"
        self.camera_id = camera_id
        self.path = path
        self.state = state
        self.reason = reason


class FakeRecorder:
    """A recorder that writes a real (empty) file and no video.

    Enough to prove the wiring — started, stopped, one file per scene — without
    OpenCV, a camera or a second of wall clock.
    """

    def __init__(self, directory: Path, *, fails: bool = False,
                 already: bool = False) -> None:
        self.directory = Path(directory)
        self.fails = fails
        self.already = already
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._running: dict[str, FakeRecording] = {}
        self._n = 0

    def start(self, camera_id: str, actor: str):
        from vg.ingest.recorder import AlreadyRecording

        if self.already:
            raise AlreadyRecording(camera_id)
        self.started.append(camera_id)
        self._n += 1
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{camera_id}_{self._n}.mp4"
        recording = FakeRecording(camera_id, path)
        self._running[camera_id] = recording
        return recording

    def stop(self, camera_id: str, actor: str):
        recording = self._running.pop(camera_id, None)
        if recording is None:
            return None
        self.stopped.append(camera_id)
        if self.fails:
            recording.state = "failed"
            recording.reason = "The camera sent no frames, so there was nothing to record."
            recording.path = None
        else:
            recording.state = "saved"
            recording.path.write_bytes(b"not really an mp4")
        return recording


@pytest.fixture
def scenes(tmp_path) -> SceneStore:
    store = SceneStore(tmp_path / "scenes.db")
    yield store
    store.close_db()


@pytest.fixture
def cameras(tmp_path) -> CameraStore:
    store = CameraStore(tmp_path / "cameras.db")
    store.add("cam-a", "Main entrance", "webcam:0", features=("counting",))
    store.add("cam-b", "Back door", "webcam:1", features=("counting",))
    yield store
    store.close()


def worker(scenes, *, detector=None, recorder=None, restricted=("cam-a",),
           cameras=("cam-a", "cam-b")):
    """A ZonesWorker with no thread started — `analyse` is called directly."""
    from vg.features.zones import ZonesWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("the worker must not be started in these tests")

    return ZonesWorker(
        NoBus(), detector or FakeDetector(), list(cameras), scenes,
        recorder=recorder, restricted=set(restricted),
    )


# ---------------------------------------------------------------------------
# storage — the toggle and the scene rows
# ---------------------------------------------------------------------------

class TestStorage:
    def test_toggle_persists_across_restart(self, tmp_path):
        # P4-FR-003. A setting that dies with the process is not a setting.
        database = tmp_path / "cameras.db"
        store = CameraStore(database)
        store.add("cam-a", "Main entrance", "webcam:0")
        assert store.set_restricted("cam-a", True) is True
        store.close()

        reopened = CameraStore(database)
        assert reopened.restricted_ids() == {"cam-a"}
        reopened.close()

    def test_toggling_an_unknown_camera_reports_failure(self, cameras):
        # So the endpoint can 404 instead of reporting a change it never made.
        assert cameras.set_restricted("nope", True) is False

    def test_a_removed_camera_is_not_restricted(self, cameras):
        cameras.set_restricted("cam-a", True)
        cameras.remove("cam-a")
        assert cameras.restricted_ids() == set()

    def test_an_existing_database_gains_the_column(self, tmp_path):
        # The upgrade path: a database written before this feature existed.
        import sqlite3

        database = tmp_path / "old.db"
        old = sqlite3.connect(database)
        old.execute(
            "CREATE TABLE camera (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "source TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'RTSP', "
            "area TEXT NOT NULL DEFAULT 'Unassigned', fps REAL NOT NULL DEFAULT 5.0, "
            "rotate INTEGER NOT NULL DEFAULT 0, features TEXT NOT NULL DEFAULT '', "
            "enabled INTEGER NOT NULL DEFAULT 1, removed_at TEXT, created_at TEXT NOT NULL)"
        )
        old.execute(
            "INSERT INTO camera (id, name, source, created_at) "
            "VALUES ('cam-old', 'Old camera', 'webcam:0', '2026-01-01T00:00:00+00:00')"
        )
        old.commit()
        old.close()

        store = CameraStore(database)
        assert [c.id for c in store.all()] == ["cam-old"], "the row must survive"
        assert store.set_restricted("cam-old", True) is True
        assert store.restricted_ids() == {"cam-old"}
        store.close()

    def test_new_clip_replaces_the_previous_one_for_that_camera_only(
            self, scenes, tmp_path):
        # P4-FR-008. A busy camera must never delete a quiet camera's clip.
        a_old = tmp_path / "a-old.mp4"
        a_new = tmp_path / "a-new.mp4"
        b_clip = tmp_path / "b.mp4"
        for path in (a_old, a_new, b_clip):
            path.write_bytes(b"clip")

        first = scenes.open("cam-a", START)
        scenes.attach_clip(first, a_old)
        other = scenes.open("cam-b", START)
        scenes.attach_clip(other, b_clip)

        second = scenes.open("cam-a", START + timedelta(minutes=5))
        scenes.attach_clip(second, a_new)

        assert scenes.get(first).clip_state == "replaced"
        assert not a_old.exists()
        assert scenes.get(second).clip_state == "saved"
        assert a_new.exists()
        assert scenes.get(other).clip_state == "saved", "camera B is untouched"
        assert b_clip.exists()

    def test_replaced_entry_stays_listed_with_a_reason(self, scenes, tmp_path):
        old = tmp_path / "old.mp4"
        old.write_bytes(b"clip")
        first = scenes.open("cam-a", START)
        scenes.note_people(first, 3)
        scenes.close(first, START + timedelta(seconds=12), "nobody")
        scenes.attach_clip(first, old)

        new = tmp_path / "new.mp4"
        new.write_bytes(b"clip")
        second = scenes.open("cam-a", START + timedelta(minutes=1))
        scenes.attach_clip(second, new)

        kept = scenes.get(first)
        assert kept.clip_state == "replaced"
        assert kept.clip_reason and "no longer kept" in kept.clip_reason
        assert kept.peak_people == 3, "the entry keeps everything but the file"
        assert kept.seconds == pytest.approx(12.0)

    def test_scene_row_is_never_deleted(self, scenes, tmp_path):
        # The constitution's no-delete rule. There must be no way to remove a
        # row, and replacing a clip must not take one with it.
        clip = tmp_path / "a.mp4"
        clip.write_bytes(b"clip")
        first = scenes.open("cam-a", START)
        scenes.attach_clip(first, clip)
        for i in range(3):
            later = scenes.open("cam-a", START + timedelta(minutes=i + 1))
            path = tmp_path / f"later-{i}.mp4"
            path.write_bytes(b"clip")
            scenes.attach_clip(later, path)

        assert len(scenes.recent(since_days=1, camera_id="cam-a")) == 4
        assert scenes.get(first) is not None
        assert not hasattr(scenes, "delete")

    def test_open_scene_is_closed_on_next_start(self, tmp_path):
        # Invariant 4: nothing shows as recording forever after a crash.
        database = tmp_path / "scenes.db"
        store = SceneStore(database)
        scene_id = store.open("cam-a", START)
        store.start_clip(scene_id)
        store.close_db()

        reopened = SceneStore(database)
        assert reopened.close_orphans() == 1
        stranded = reopened.get(scene_id)
        assert stranded.running is False
        assert stranded.end_reason == "shutdown"
        assert stranded.clip_state == "failed"
        assert stranded.clip_reason
        reopened.close_db()

    def test_peak_people_never_goes_down(self, scenes):
        scene_id = scenes.open("cam-a", START)
        scenes.note_people(scene_id, 3)
        scenes.note_people(scene_id, 1)
        assert scenes.get(scene_id).peak_people == 3


# ---------------------------------------------------------------------------
# US1 — the camera list is real
# ---------------------------------------------------------------------------

def live_store(tmp_path, camera_store=None, scene_store=None, **kw):
    """A LiveStore over a small real roster and a throwaway database."""
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    roster = [
        CameraConfig.parse(
            {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
             "features": ["counting"]}, "cam-a"),
        CameraConfig.parse(
            {"id": "cam-b", "name": "Back door", "source": "webcam:1",
             "features": ["counting"]}, "cam-b"),
    ]
    # Not started: nothing opens a device, so nothing is online. That is the
    # honest state for a list test — the roster is not the same question as
    # whether a camera is delivering frames.
    registry = CameraRegistry(roster)
    store = LiveStore(vgconfig.load(), registry, cameras=camera_store, **kw)
    store.scenes = scene_store
    return store


@pytest.fixture
def store_and_cameras(tmp_path, scenes):
    cameras = CameraStore(tmp_path / "cameras.db")
    cameras.add("cam-a", "Main entrance", "webcam:0", features=("counting",))
    cameras.add("cam-b", "Back door", "webcam:1", features=("counting",))
    store = live_store(tmp_path, camera_store=cameras, scene_store=scenes)
    yield store, cameras
    cameras.close()


class TestCameraList:
    def test_zones_lists_every_configured_camera(self, store_and_cameras):
        # P4-FR-001. The list IS the roster: every camera, restricted or not,
        # and nothing that is not a camera.
        store, _ = store_and_cameras
        zones = store.zones()

        assert [z.id for z in zones] == ["cam-a", "cam-b"]
        assert [z.name for z in zones] == ["Main entrance", "Back door"]
        assert all(z.camera_id == z.id for z in zones), (
            "a zone IS a camera, so the ids must be the same"
        )
        assert all(z.enabled is False for z in zones), "default is off"

    def test_no_invented_zone_names_from_live_store(self, store_and_cameras):
        # The P0-01 bug class, with its own guard. "Server room" is the name of
        # a MockStore fixture, and it has no business on a live screen.
        from vg.api.store import MockStore

        store, _ = store_and_cameras
        invented = {z.name for z in MockStore().zones()}
        assert invented, "the fixtures must still exist for demo mode"

        live_names = {z.name for z in store.zones()}
        assert not (live_names & invented), (
            f"a fixture zone reached the live store: {live_names & invented}"
        )
        live_breach_zones = {b.zone_name for b in store.breaches(30)}
        assert not (live_breach_zones & invented)

    def test_an_empty_roster_lists_nothing_not_demo_cameras(self, tmp_path, scenes):
        store = live_store(tmp_path, scene_store=scenes)
        store.registry.workers.clear()
        store.registry.disabled.clear()
        assert store.zones() == []

    def test_zone_polygon_is_the_whole_frame(self, store_and_cameras):
        # The wire still carries a polygon, so it carries the truth: the four
        # corners. Nothing draws it, but nothing has to change to say it.
        store, _ = store_and_cameras
        corners = [(p.x, p.y) for p in store.zones()[0].polygon]
        assert corners == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    def test_every_zone_is_always_on_no_schedules(self, store_and_cameras):
        store, _ = store_and_cameras
        assert all(z.schedule.mode is S.ScheduleMode.ALWAYS for z in store.zones())

    def test_toggle_writes_through_and_comes_back(self, store_and_cameras):
        store, cameras = store_and_cameras
        updated = store.set_zone_enabled("cam-a", True)

        assert updated is not None and updated.enabled is True
        assert cameras.restricted_ids() == {"cam-a"}, "written to the database"
        assert [z.enabled for z in store.zones()] == [True, False]

    def test_toggling_an_unknown_camera_returns_none_so_the_api_404s(
            self, store_and_cameras):
        store, _ = store_and_cameras
        assert store.set_zone_enabled("no-such-camera", True) is None

    def test_breaches_today_counts_that_cameras_scenes(self, store_and_cameras, scenes):
        store, _ = store_and_cameras
        scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.open("cam-b", datetime.now(timezone.utc))

        counts = {z.id: z.breaches_today for z in store.zones()}
        assert counts == {"cam-a": 2, "cam-b": 1}

    def test_intrusion_cameras_have_no_zone_overlay(self, store_and_cameras):
        # P4-FR-002. The zone is the frame, so there is no rectangle to draw.
        store, _ = store_and_cameras
        store.set_zone_enabled("cam-a", True)
        for view in store.intrusion_cameras():
            assert view.zone is None, "no orange rectangle — the frame IS the zone"

    def test_intrusion_cameras_are_the_restricted_ones(self, store_and_cameras):
        store, _ = store_and_cameras
        store.set_zone_enabled("cam-a", True)
        assert [v.id for v in store.intrusion_cameras()] == ["cam-a"]


class TestToggleAuthorisation:
    """P4-FR-004. Viewing is for everyone signed in; changing is admin only.

    Enforced by path in `auth/deps.py`, not by a decorator here. This pins the
    rule so nobody loosens it by accident — a `/zones` PATCH that an IT account
    can make is a configuration change made by somebody who should not.
    """

    @pytest.fixture
    def app(self, user_store, store_and_cameras):
        from vg.api import app as app_module
        from vg.api.app import create_app

        store, _ = store_and_cameras
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        yield application
        app_module.set_store(MockStore())

    def test_toggle_requires_admin(self, app, authed):
        it = authed(app, role="it")
        assert it.get("/zones").status_code == 200, "any signed-in role may look"
        assert it.patch("/zones/cam-a", json={"enabled": True}).status_code == 403

        admin = authed(app, role="admin")
        assert admin.patch("/zones/cam-a", json={"enabled": True}).status_code == 200

    def test_an_unknown_camera_404s(self, app, authed):
        admin = authed(app, role="admin")
        assert admin.patch("/zones/nope", json={"enabled": True}).status_code == 404


# ---------------------------------------------------------------------------
# US2 — the scene state machine
#
# Every test here drives `analyse(frame)` directly with fake detections and a
# clock the test controls through `frame.captured_at`. No camera, no model, no
# server, no wall clock — so a two-minute limit takes microseconds and a 0.9
# second flicker is exactly 0.9 seconds on every machine.
# ---------------------------------------------------------------------------

def walk(zones_worker, detector, script, camera_id="cam-a"):
    """Feed a scripted walk: `(seconds, people)` pairs, in order."""
    for i, (at, people) in enumerate(script):
        detector.people = people
        zones_worker.analyse(frame(camera_id, at=at, sequence=i))


class TestSceneMachine:
    def test_person_opens_a_scene(self, scenes):
        # P4-FR-005. The first frame with a body in it is a scene.
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1)])

        logged = scenes.recent(since_days=1)
        assert len(logged) == 1
        assert logged[0].camera_id == "cam-a"
        assert logged[0].started_at == START
        assert logged[0].running is True, "still there until they leave"

    def test_flicker_under_one_second_does_not_split_the_scene(self, scenes):
        # P4-FR-006 and SC-003 — the single most important test in the feature.
        # A detector losing somebody for nine tenths of a second is a detector
        # blinking, not a person leaving and coming back.
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [
            (0.0, 1),
            (0.5, 0),
            (0.9, 0),   # 0.9 s since the last sighting — still one scene
            (1.2, 1),   # found again
            (1.6, 1),
        ])

        logged = scenes.recent(since_days=1)
        assert len(logged) == 1, "a blink must not become a second entry"
        assert logged[0].running is True

    def test_one_full_second_of_nobody_closes_the_scene(self, scenes):
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (0.5, 0), (1.6, 0)])

        logged = scenes.recent(since_days=1)
        assert len(logged) == 1
        assert logged[0].running is False
        assert logged[0].end_reason == "nobody"

    def test_the_gap_is_measured_from_the_last_person_not_the_frame_count(
            self, scenes):
        # The rule is wall-clock, so a 2 Hz camera and a 12 Hz boosted one
        # behave identically. Four empty frames close nothing if they are close
        # together; one closes the scene if it is far enough away.
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (0.1, 0), (0.2, 0), (0.3, 0), (0.4, 0)])
        assert scenes.recent(since_days=1)[0].running is True

        walk(zw, detector, [(1.5, 0)])
        assert scenes.recent(since_days=1)[0].running is False

    def test_a_new_person_after_the_gap_starts_a_second_scene(self, scenes):
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (2.0, 0), (5.0, 1)])

        logged = scenes.recent(since_days=1)
        assert len(logged) == 2
        assert logged[0].started_at == START + timedelta(seconds=5)
        assert logged[1].end_reason == "nobody"

    def test_scene_is_cut_at_the_two_minute_limit(self, scenes):
        # P4-FR-009. Somebody standing in a doorway all afternoon is not a
        # two-hour clip, and the entry has to say it was cut rather than look
        # like they left.
        from vg.features.zones import MAX_SCENE_SECONDS

        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (60.0, 1), (MAX_SCENE_SECONDS + 0.5, 1)])

        cut = [s for s in scenes.recent(since_days=1) if s.end_reason == "limit"]
        assert len(cut) == 1, "the scene must end at the limit, with that reason"
        assert cut[0].seconds <= MAX_SCENE_SECONDS + 1.0

    def test_a_person_still_there_after_the_limit_starts_a_fresh_scene(self, scenes):
        # Cutting must not blind the camera: they are still standing there.
        from vg.features.zones import MAX_SCENE_SECONDS

        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (MAX_SCENE_SECONDS + 0.5, 1)])

        logged = scenes.recent(since_days=1)
        assert len(logged) == 2
        assert logged[0].running is True

    def test_camera_not_restricted_never_opens_a_scene(self, scenes):
        # SC-005, and the second half matters more than the first: a camera
        # nobody switched on must never reach the model at all, or switching
        # the feature on would cost every site a detection pass per camera.
        detector = FakeDetector()
        zw = worker(scenes, detector=detector, restricted=("cam-a",))
        walk(zw, detector, [(0.0, 1), (1.0, 1)], camera_id="cam-b")

        assert scenes.recent(since_days=1) == []
        assert "cam-b" not in detector.asked, (
            "a camera nobody restricted must not be sent to the detector"
        )

    def test_scene_records_peak_people_not_last_count(self, scenes):
        # P4-FR-012. The last frame of every scene has nobody in it, so the
        # last count would report 0 for every entry.
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1), (0.4, 3), (0.8, 1), (2.0, 0)])

        assert scenes.recent(since_days=1)[0].peak_people == 3

    def test_toggling_off_mid_scene_closes_the_scene(self, scenes):
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1)])
        assert scenes.recent(since_days=1)[0].running is True

        zw.set_restricted(set())

        logged = scenes.recent(since_days=1)[0]
        assert logged.running is False
        assert logged.end_reason == "switched_off"

    def test_toggling_a_camera_on_starts_watching_it(self, scenes):
        detector = FakeDetector()
        zw = worker(scenes, detector=detector, restricted=())
        walk(zw, detector, [(0.0, 1)])
        assert scenes.recent(since_days=1) == []

        zw.set_restricted({"cam-a"})
        walk(zw, detector, [(1.0, 1)])
        assert len(scenes.recent(since_days=1)) == 1

    def test_shutdown_closes_the_open_scene(self, scenes):
        detector = FakeDetector()
        zw = worker(scenes, detector=detector)
        walk(zw, detector, [(0.0, 1)])
        zw.close_all("shutdown")

        logged = scenes.recent(since_days=1)[0]
        assert logged.running is False
        assert logged.end_reason == "shutdown"


class TestFeatureIndependence:
    def test_restricted_zones_do_not_change_counting(self, scenes):
        # Rule 9 and P4-FR-011. The zones worker consumes the shared detection
        # results; it must not touch the people worker's own answers.
        from vg.features.people import PeopleWorker

        detector = FakeDetector(people=2)

        class NoBus:
            def subscribe(self, *a, **kw):
                raise AssertionError("not started")

        people = PeopleWorker(NoBus(), detector, ["cam-a"])
        before = people.analyse(frame("cam-a", at=0.0))

        zw = worker(scenes, detector=detector)
        zw.analyse(frame("cam-a", at=0.5, sequence=1))

        after = people.analyse(frame("cam-a", at=1.0, sequence=2))
        assert before.count == after.count == 2
        assert before.zones == after.zones

    def test_the_worker_writes_no_concurrency_code(self):
        # `FeatureWorker` owns threading. A feature file that starts a thread
        # is a feature file that will deadlock something at 3am.
        import inspect

        from vg.features import zones

        source = inspect.getsource(zones)
        assert "threading.Thread" not in source
        assert "import threading" not in source

    def test_zones_is_a_feature_worker(self):
        from vg.features.base import FeatureWorker
        from vg.features.zones import ZonesWorker

        assert issubclass(ZonesWorker, FeatureWorker)


# ---------------------------------------------------------------------------
# US2 — the log on the wire
# ---------------------------------------------------------------------------

def capability(store, key: str):
    return next(c for c in store.capabilities() if c.key == key)


class TestBreachLog:
    def test_a_scene_becomes_a_log_entry(self, store_and_cameras, scenes):
        store, _ = store_and_cameras
        started = datetime.now(timezone.utc) - timedelta(seconds=12)
        scene_id = scenes.open("cam-a", started)
        scenes.note_people(scene_id, 3)
        scenes.close(scene_id, started + timedelta(seconds=12), "nobody")

        entry = store.breaches(1)[0]
        assert entry.id == scene_id
        assert entry.camera_name == "Main entrance"
        assert entry.zone_name == "Main entrance"
        assert entry.people == 3
        assert entry.dwell_seconds == pytest.approx(12.0, abs=0.2)
        assert entry.status is S.BreachStatus.RESOLVED

    def test_nobody_is_ever_named_on_a_breach(self, store_and_cameras, scenes):
        # Rule 1. This feature detects bodies; it never runs a face against
        # them, so a name here would be a claim nothing in the pipeline made.
        store, _ = store_and_cameras
        scenes.open("cam-a", datetime.now(timezone.utc))

        entry = store.breaches(1)[0]
        assert entry.subject.match is S.MatchKind.NONE
        assert entry.subject.name == "Unidentified"
        assert entry.subject.id is None

    def test_a_running_scene_is_open_with_no_clip(self, store_and_cameras, scenes):
        store, _ = store_and_cameras
        scenes.open("cam-a", datetime.now(timezone.utc))

        entry = store.breaches(1)[0]
        assert entry.status is S.BreachStatus.OPEN
        assert entry.clip is None

    def test_an_absent_log_is_empty_not_fixtures(self, tmp_path):
        store = live_store(tmp_path)
        store.scenes = None
        assert store.breaches(30) == []

    def test_a_replaced_entry_has_no_clip_and_says_why(
            self, store_and_cameras, scenes, tmp_path):
        store, _ = store_and_cameras
        old, new = tmp_path / "old.mp4", tmp_path / "new.mp4"
        old.write_bytes(b"clip")
        new.write_bytes(b"clip")

        first = scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.attach_clip(first, old)
        second = scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.attach_clip(second, new)

        entries = {b.id: b for b in store.breaches(1)}
        assert entries[first].clip is None
        assert entries[first].clip_state == "replaced"
        assert "no longer kept" in entries[first].clip_reason
        assert entries[second].clip is not None

    def test_every_entry_without_a_clip_carries_a_reason(
            self, store_and_cameras, scenes):
        # No bare disabled controls. Every state that has no file explains
        # itself, because the UI renders `clipReason` next to the button.
        store, _ = store_and_cameras
        running = scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.start_clip(running)
        failed = scenes.open("cam-b", datetime.now(timezone.utc))
        scenes.fail_clip(failed, "No clip: the camera sent no frames.")

        for entry in store.breaches(1):
            if entry.clip is None:
                assert entry.clip_reason, f"{entry.clip_state} has no reason"

    def test_the_clip_url_is_same_origin_and_relative(
            self, store_and_cameras, scenes, tmp_path):
        # A <video src> cannot send an Authorization header, so an absolute
        # engine URL plays for nobody. This is the trap that blacked out every
        # camera stream last cycle.
        store, _ = store_and_cameras
        clip = tmp_path / "a.mp4"
        clip.write_bytes(b"clip")
        scene_id = scenes.open("cam-a", datetime.now(timezone.utc))
        scenes.attach_clip(scene_id, clip)

        url = store.breaches(1)[0].clip.url
        assert url == f"/breaches/{scene_id}/clip"
        assert not url.startswith("http"), "must be same-origin"


class TestCapabilities:
    def test_capabilities_says_why_when_the_worker_is_not_running(
            self, store_and_cameras):
        # Rules 4, 7, 8. An empty log on a dead watcher must never read as
        # "all clear", and "unavailable" alone does not tell anybody what to fix.
        store, _ = store_and_cameras
        store.zones_worker = None
        store.people_worker = None

        state = capability(store, "breaches")
        assert state.state is S.DataState.UNAVAILABLE
        assert "Person detection is not running" in state.reason

    def test_a_startup_failure_is_reported_in_its_own_words(
            self, store_and_cameras):
        store, _ = store_and_cameras
        store.zones_worker = None
        store.zones_error = "weights not found: yolov8s.pt"

        state = capability(store, "breaches")
        assert state.state is S.DataState.UNAVAILABLE
        assert "yolov8s.pt" in state.reason

    def test_a_live_capability_offers_no_excuse(self, store_and_cameras):
        # A reason attached to a working feature reads as a fault.
        store, cameras = store_and_cameras
        store.zones_worker = worker(store.scenes)

        state = capability(store, "breaches")
        assert state.state is S.DataState.LIVE
        assert state.reason is None
