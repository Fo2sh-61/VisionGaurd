"""Falls, end to end, without a camera or a model.

The model's half is proven against the owner's own code in
`test_falls_model.py`. What is under test here is the half that decides what a
fall means on the site, and the part that can lie:

  * a fall shorter than the down rule is listed and never alerts
  * somebody who stays down alerts once, stamped when the rule was met
  * getting up and leaving the camera are different endings, and say so
  * a person the pose model loses on the floor is not a person who left
  * rows are never deleted; a video that is gone says why
  * the two buttons are signed, "not a fall" never moves back, and the
    audit entry is written before the change it records

Driven with readings and a clock the test controls, so a ten-second rule
takes microseconds to prove.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vg.events.falls import FallSceneStore
from vg.features.falls import DOWN_SECONDS, GOT_UP_SECONDS, LOST_SECONDS
from vg.infer.falls import FallAlert, FallingPerson, FallReading

START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def person(pid: int = 1, state: str = "fallen", seconds: float = 0.0,
           x: float = 0.3, y: float = 0.6, w: float = 0.4, h: float = 0.2,
           confidence: float = 0.9) -> FallingPerson:
    return FallingPerson(person_id=pid, x=x, y=y, w=w, h=h, state=state,
                         confidence=confidence, seen_at=at(seconds))


def fell(pid: int = 1, seconds: float = 2.0, fell_at: float = 1.0,
         confidence: float = 0.85, x: float = 0.3, y: float = 0.6) -> FallAlert:
    return FallAlert(person_id=pid, at=at(seconds), fell_at=at(fell_at),
                     confidence=confidence, x=x, y=y, w=0.4, h=0.2)


def reading(*people, alerts=()) -> FallReading:
    return FallReading(people=tuple(people), alerts=tuple(alerts),
                       known={p.person_id: p for p in people})


class FakeRecording:
    def __init__(self, camera_id: str, path: Path | None) -> None:
        self.camera_id = camera_id
        self.path = path
        self.state = "recording"
        self.reason = None


class FakeRecorder:
    def __init__(self, directory: Path, *, already: bool = False) -> None:
        self.directory = Path(directory)
        self.already = already
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._running: dict[str, FakeRecording] = {}

    def start(self, camera_id: str, actor: str):
        from vg.ingest.recorder import AlreadyRecording

        if self.already or camera_id in self._running:
            raise AlreadyRecording(camera_id)
        self.started.append(camera_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{camera_id}_{len(self.started)}.mp4"
        self._running[camera_id] = FakeRecording(camera_id, path)
        return self._running[camera_id]

    def stop(self, camera_id: str, actor: str):
        recording = self._running.pop(camera_id, None)
        if recording is None:
            return None
        self.stopped.append(camera_id)
        recording.state = "saved"
        recording.path.write_bytes(b"not really an mp4")
        return recording


class FakeDetector:
    version = "lstm_cctv"
    device = "cpu"

    def __init__(self) -> None:
        self.forgotten: list[str] = []

    def forget(self, camera_id: str) -> None:
        self.forgotten.append(camera_id)


@pytest.fixture
def scenes(tmp_path) -> FallSceneStore:
    store = FallSceneStore(tmp_path / "falls.db")
    yield store
    store.close_db()


def worker(scenes, recorder=None, cameras=("cam-a", "cam-b")):
    from vg.features.falls import FallsWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("the worker must not be started in these tests")

    return FallsWorker(NoBus(), FakeDetector(), list(cameras), scenes, recorder=recorder)


def play(w, script, camera_id="cam-a"):
    """`(seconds, reading)` pairs, in order."""
    for seconds, r in script:
        w.apply(camera_id, at(seconds), r)


def down_for(seconds: float, step: float = 0.2, start: float = 2.0, pid: int = 1):
    """A person who fell at 1 s, alerted at 2 s, lying there `seconds` more."""
    script = [(start, reading(person(pid, seconds=start), alerts=[fell(pid, start)]))]
    t = start
    while t < start + seconds:
        t = round(t + step, 6)
        script.append((t, reading(person(pid, seconds=t))))
    return script


def stands_up(from_s: float, for_s: float = 2.0, pid: int = 1, step: float = 0.2):
    script, t = [], from_s
    while t < from_s + for_s:
        script.append((t, reading(person(pid, "normal", seconds=t))))
        t = round(t + step, 6)
    return script


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

class TestStorage:
    def test_an_open_fall_is_closed_on_next_start(self, tmp_path):
        database = tmp_path / "falls.db"
        store = FallSceneStore(database)
        scene_id = store.open("cam-a", at(0), at(1), 0.8, "lstm_cctv")
        store.start_clip(scene_id)
        store.close_db()

        restarted = FallSceneStore(database)
        assert restarted.close_orphans() == 1
        scene = restarted.get(scene_id)
        assert scene.running is False and scene.end_reason == "shutdown"
        assert scene.clip_state == "failed"
        assert "engine stopped" in scene.clip_reason
        restarted.close_db()

    def test_a_row_is_never_removed(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        scenes.mark_not_a_fall(scene_id, "mona", at(3))
        scenes.close(scene_id, at(12), "got_up")
        assert [s.id for s in scenes.recent(None, None)] == [scene_id]

    def test_not_a_fall_is_recorded_once_and_never_moves(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        assert scenes.mark_not_a_fall(scene_id, "mona", at(3)) is True
        assert scenes.mark_not_a_fall(scene_id, "karim", at(4)) is False
        scene = scenes.get(scene_id)
        assert scene.verdict == "not_a_fall" and scene.reviewed_by == "mona"

    def test_on_my_way_names_one_person_and_can_be_taken_back(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        assert scenes.respond(scene_id, "karim", at(5)) is True
        assert scenes.respond(scene_id, "mona", at(6)) is False, \
            "a second press must not replace the first person's name"
        assert scenes.get(scene_id).responder == "karim"
        assert scenes.undo_response(scene_id) == "karim"
        scene = scenes.get(scene_id)
        assert scene.responder is None and scene.responded_at is None

    def test_nobody_goes_to_a_person_who_already_got_up(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        scenes.close(scene_id, at(4), "got_up")
        assert scenes.respond(scene_id, "karim", at(5)) is False

    def test_an_alert_is_stamped_once(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        assert scenes.alert(scene_id, at(10)) is True
        assert scenes.alert(scene_id, at(11)) is False
        assert scenes.get(scene_id).alerted_at == at(10)

    def test_expired_video_says_why_and_the_row_stays(self, scenes, tmp_path):
        clip = tmp_path / "old.mp4"
        clip.write_bytes(b"x")
        scene_id = scenes.open("cam-a", at(0), at(1), 0.9, "lstm_cctv")
        scenes.attach_clip(scene_id, clip)
        assert scenes.expire(at(10)) == 1
        scene = scenes.get(scene_id)
        assert scene.clip_state == "expired" and scene.clip_path is None
        assert scene.clip_reason == "Video no longer kept."
        assert not clip.exists()

    def test_peak_confidence_never_drops(self, scenes):
        scene_id = scenes.open("cam-a", at(0), at(1), 0.6, "lstm_cctv")
        scenes.note_confidence(scene_id, 0.9)
        scenes.note_confidence(scene_id, 0.7)
        assert scenes.get(scene_id).peak_confidence == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

class TestDown:
    def test_a_fall_opens_an_entry_stamped_when_they_went_down(self, scenes):
        w = worker(scenes)
        play(w, [(2.0, reading(person(seconds=2.0), alerts=[fell()]))])
        [scene] = scenes.recent(None)
        assert scene.started_at == at(1.0), "when they went down, not when it was sure"
        assert scene.detected_at == at(2.0)
        assert scene.running and not scene.alerted

    def test_staying_down_alerts_once_when_the_rule_is_met(self, scenes):
        w = worker(scenes)
        play(w, down_for(DOWN_SECONDS + 3))
        [scene] = scenes.recent(None)
        assert scene.alerted_at == at(1.0 + DOWN_SECONDS)
        assert scene.running

    def test_getting_up_inside_the_rule_never_alerts(self, scenes):
        w = worker(scenes)
        play(w, down_for(3.0) + stands_up(5.2))
        [scene] = scenes.recent(None)
        assert scene.end_reason == "got_up"
        assert scene.alerted_at is None, "down shorter than the rule never alerts"
        # Ended when they stood, not when it was certain they had.
        assert scene.ended_at == at(5.2)

    def test_getting_up_after_the_alert_closes_it(self, scenes):
        w = worker(scenes)
        play(w, down_for(DOWN_SECONDS + 2) + stands_up(DOWN_SECONDS + 4.2))
        [scene] = scenes.recent(None)
        assert scene.alerted and scene.end_reason == "got_up"

    def test_one_upright_frame_is_not_getting_up(self, scenes):
        """A glitchy frame must not close the entry of somebody on the floor."""
        w = worker(scenes)
        script = down_for(2.0)
        script.append((4.2, reading(person(state="normal", seconds=4.2))))
        script += down_for(DOWN_SECONDS, start=4.4)[1:]
        play(w, script)
        [scene] = scenes.recent(None)
        assert scene.running and scene.alerted

    def test_leaving_the_camera_is_not_getting_up(self, scenes):
        w = worker(scenes)
        play(w, down_for(2.0) + [(4.0 + LOST_SECONDS + 0.2, reading())])
        [scene] = scenes.recent(None)
        assert scene.end_reason == "left_view"
        assert scene.ended_at == at(4.0), "ended when last seen"

    def test_lost_on_the_floor_for_a_moment_stays_one_entry(self, scenes):
        """Pose models lose people lying down. That is not them leaving."""
        w = worker(scenes)
        script = down_for(2.0)
        script += [(4.0 + i * 0.2, reading()) for i in range(1, 10)]   # 1.8 s unseen
        script += down_for(DOWN_SECONDS, start=6.0)[1:]
        play(w, script)
        [scene] = scenes.recent(None)
        assert scene.running and scene.alerted

    def test_a_new_number_in_the_same_place_is_the_same_person(self, scenes):
        """ByteTrack renamed the person lying there: one fall, one entry."""
        w = worker(scenes)
        script = down_for(2.0)
        script += [(4.2 + i * 0.2, reading(person(pid=7, seconds=4.2 + i * 0.2)))
                   for i in range(int(DOWN_SECONDS / 0.2) + 5)]
        play(w, script)
        [scene] = scenes.recent(None)
        assert scene.running and scene.alerted

    def test_somebody_else_standing_nearby_is_not_the_person_down(self, scenes):
        w = worker(scenes)
        script = down_for(2.0)
        script += [(4.0 + i * 0.2, reading(person(pid=7, state="normal",
                                                  seconds=4.0 + i * 0.2)))
                   for i in range(1, int(LOST_SECONDS / 0.2) + 3)]
        play(w, script)
        [scene] = scenes.recent(None)
        assert scene.end_reason == "left_view"

    def test_two_people_down_are_two_entries(self, scenes):
        w = worker(scenes)
        play(w, [(2.0, reading(person(1, seconds=2.0), person(2, x=0.0, y=0.0, seconds=2.0),
                               alerts=[fell(1), fell(2, x=0.0, y=0.0)]))])
        assert len(scenes.recent(None)) == 2

    def test_cameras_do_not_share_falls(self, scenes):
        w = worker(scenes)
        play(w, down_for(2.0), camera_id="cam-a")
        play(w, [(5.0, reading(person(seconds=5.0)))], camera_id="cam-b")
        assert [s.camera_id for s in scenes.recent(None)] == ["cam-a"]
        assert w.down_on("cam-b") == []

    def test_the_overlay_draws_the_person_down_and_for_how_long(self, scenes):
        w = worker(scenes)
        play(w, down_for(DOWN_SECONDS + 1))
        [box] = w.down_on("cam-a")
        assert box.alerted
        assert box.seconds == pytest.approx(DOWN_SECONDS + 2.0)
        for value in (box.x, box.y, box.w, box.h, box.confidence):
            assert 0.0 <= value <= 1.0

    def test_switching_a_camera_off_closes_its_falls_and_forgets_it(self, scenes):
        w = worker(scenes)
        play(w, down_for(2.0))
        w._closing("cam-a")
        [scene] = scenes.recent(None)
        assert scene.end_reason == "switched_off"
        assert w.detector.forgotten == ["cam-a"]

    def test_shutdown_leaves_nobody_on_the_floor(self, scenes):
        w = worker(scenes)
        play(w, down_for(2.0))
        w.close_all()
        assert scenes.running() == []

    def test_got_up_is_the_models_own_one_second(self):
        assert GOT_UP_SECONDS == pytest.approx(1.0)


class TestRecording:
    def test_a_fall_is_recorded_and_the_clip_attached(self, scenes, tmp_path):
        recorder = FakeRecorder(tmp_path / "clips")
        w = worker(scenes, recorder)
        play(w, down_for(2.0) + stands_up(4.2))
        [scene] = scenes.recent(None)
        assert scene.playable and scene.clip_path.is_file()
        assert recorder.started == recorder.stopped == ["cam-a"]

    def test_no_recorder_is_said_not_faked(self, scenes):
        w = worker(scenes)
        play(w, down_for(2.0))
        [scene] = scenes.recent(None)
        assert scene.clip_state == "failed"
        assert "not running" in scene.clip_reason

    def test_a_second_fall_on_a_busy_camera_says_why(self, scenes, tmp_path):
        recorder = FakeRecorder(tmp_path / "clips")
        w = worker(scenes, recorder)
        play(w, [(2.0, reading(person(1, seconds=2.0), person(2, x=0.0, y=0.0, seconds=2.0),
                               alerts=[fell(1), fell(2, x=0.0, y=0.0)]))])
        states = sorted(s.clip_state for s in scenes.recent(None))
        assert states == ["failed", "recording"]
        failed = next(s for s in scenes.recent(None) if s.clip_state == "failed")
        assert "already recording" in failed.clip_reason


# ---------------------------------------------------------------------------
# the console's side: LiveStore and the endpoints
# ---------------------------------------------------------------------------

from vg.api import schemas as S  # noqa: E402


class FakeWorker:
    """Stands in for a running FallsWorker: cameras, a rule, an overlay."""

    def __init__(self, cameras=("cam-a",), down=()) -> None:
        self.cameras = list(cameras)
        self.down_seconds = DOWN_SECONDS
        self._down = list(down)
        self.detector = FakeDetector()
        self.device = "cpu"

    def serves(self, camera_id: str) -> bool:
        return camera_id in self.cameras

    def down_on(self, camera_id: str):
        return list(self._down) if camera_id == "cam-a" else []

    def watch(self, camera_id):
        if camera_id not in self.cameras:
            self.cameras.append(camera_id)

    def unwatch(self, camera_id):
        if camera_id in self.cameras:
            self.cameras.remove(camera_id)

    def set_rate(self, camera_id, rate):
        pass

    @property
    def stats(self):
        return {"name": "falls", "cameras": len(self.cameras), "frames_per_second": 5.0,
                "device": "cpu", "frames_processed": 10, "last_inference_ms": 21.0,
                "last_shared_ms": 0.0, "busy_ms_per_second": 1.0,
                "analysed_per_second": 5.0, "window_seconds": 5.0, "queue_depth": 0,
                "queue_max": 1, "frames_dropped": 0, "behind": False, "died_on": []}


def live_store(tmp_path, scenes=None, worker=None, alerts_store=None):
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    roster = [
        CameraConfig.parse({"id": "cam-a", "name": "Playground", "source": "webcam:0",
                            "area": "Outside", "features": ["falls"]}, "cam-a"),
        CameraConfig.parse({"id": "cam-b", "name": "Library", "source": "webcam:1",
                            "features": ["counting"]}, "cam-b"),
    ]
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, CameraRegistry(roster), falls=worker, fall_scenes=scenes,
                     alerts_store=alerts_store)


@pytest.fixture
def down_now(scenes):
    """Somebody who went down 40 seconds ago and is still down, alerted."""
    went = datetime.now(timezone.utc) - timedelta(seconds=40)
    scene_id = scenes.open("cam-a", went, went + timedelta(seconds=1), 0.82,
                           "lstm_cctv", box=(0.3, 0.6, 0.4, 0.2))
    scenes.alert(scene_id, went + timedelta(seconds=DOWN_SECONDS))
    return scene_id


class TestTheHistory:
    def test_an_entry_reads_as_the_page_needs_it(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        [entry] = store.falls(None)
        assert entry.camera_name == "Playground" and entry.location == "Outside"
        assert entry.alerted_at is not None and entry.ended_at is None
        assert entry.verdict == "none" and entry.confidence == pytest.approx(0.82)
        assert entry.seconds >= 39

    def test_nothing_is_hidden_not_a_fall_included(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        store.mark_not_a_fall(down_now, "Mona Adel")
        scenes.close(down_now, datetime.now(timezone.utc), "got_up")
        [entry] = store.falls(None)
        assert entry.verdict == "not_a_fall" and entry.reviewed_by == "Mona Adel"

    def test_no_history_without_a_store(self, bare_live_store):
        assert bare_live_store.falls(None) == []
        assert bare_live_store.fall_cameras() == []

    def test_the_rule_quoted_is_the_rule_applied(self, tmp_path, scenes):
        worker = FakeWorker()
        worker.down_seconds = 7.0
        status = live_store(tmp_path, scenes, worker).falls_status()
        assert status.down_seconds == 7.0 and status.cameras_checked == 1


class TestTheButtons:
    def test_on_my_way_is_signed_and_can_be_undone(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        assert store.respond_to_fall(down_now, "Mona Adel").responder == "Mona Adel"
        assert store.undo_fall_response(down_now, "Mona Adel").responder is None
        actions = [e.action for e in store.audit(50) if e.subject == down_now]
        assert "fall.respond" in actions and "fall.respond.undo" in actions

    def test_a_second_person_going_is_told_who_already_is(self, tmp_path, scenes, down_now):
        from vg.api.store import FallRefused

        store = live_store(tmp_path, scenes, FakeWorker())
        store.respond_to_fall(down_now, "Mona Adel")
        with pytest.raises(FallRefused, match="Mona Adel"):
            store.respond_to_fall(down_now, "Karim S.")

    def test_not_a_fall_never_moves_back(self, tmp_path, scenes, down_now):
        from vg.api.store import FallRefused

        store = live_store(tmp_path, scenes, FakeWorker())
        store.mark_not_a_fall(down_now, "Mona Adel")
        with pytest.raises(FallRefused, match="Mona Adel"):
            store.mark_not_a_fall(down_now, "Karim S.")
        assert scenes.get(down_now).reviewed_by == "Mona Adel"

    def test_the_audit_entry_is_written_before_the_change(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())

        def explode(*a, **kw):
            raise RuntimeError("the disk is full")

        scenes.mark_not_a_fall = explode
        with pytest.raises(RuntimeError):
            store.mark_not_a_fall(down_now, "Mona Adel")
        entries = [e for e in store.audit(50) if e.subject == down_now]
        assert entries and entries[0].action == "fall.not_a_fall"
        assert entries[0].actor == "Mona Adel"

    def test_an_unknown_id_is_none(self, tmp_path, scenes):
        store = live_store(tmp_path, scenes, FakeWorker())
        assert store.respond_to_fall("nope", "Mona Adel") is None
        assert store.mark_not_a_fall("nope", "Mona Adel") is None


class TestTheEndpoints:
    @pytest.fixture
    def app_and_store(self, user_store, tmp_path, scenes):
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.store import MockStore

        store = live_store(tmp_path, scenes, FakeWorker())
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        yield application, store
        app_module.set_store(MockStore())

    def test_the_buttons_are_signed_with_the_session(self, app_and_store, authed, down_now):
        app, _ = app_and_store
        client = authed(app, role="it")   # not admin-only: anybody on duty
        answer = client.post(f"/falls/{down_now}/respond")
        assert answer.status_code == 200
        assert answer.json()["responder"] == "Test It"
        assert client.delete(f"/falls/{down_now}/respond").json()["responder"] is None
        answer = client.post(f"/falls/{down_now}/not-a-fall")
        assert answer.json()["verdict"] == "not_a_fall"
        assert answer.json()["reviewedBy"] == "Test It"

    def test_a_refusal_is_a_409_with_the_reason(self, app_and_store, authed, scenes, down_now):
        app, _ = app_and_store
        client = authed(app)
        scenes.close(down_now, datetime.now(timezone.utc), "got_up")
        answer = client.post(f"/falls/{down_now}/respond")
        assert answer.status_code == 409
        assert "no longer down" in answer.json()["detail"]

    def test_an_unknown_fall_is_a_404(self, app_and_store, authed):
        app, _ = app_and_store
        assert authed(app).post("/falls/nope/not-a-fall").status_code == 404

    def test_the_lists_answer(self, app_and_store, authed, down_now):
        app, _ = app_and_store
        client = authed(app)
        entries = client.get("/falls/entries?window=all")
        assert entries.status_code == 200 and entries.json()[0]["id"] == down_now
        assert client.get("/falls/status").json()["downSeconds"] == DOWN_SECONDS
        assert client.get("/falls/cameras").status_code == 200
        assert client.get("/falls/entries?window=forever").status_code == 422

    def test_nothing_without_signing_in(self, app_and_store, down_now):
        from fastapi.testclient import TestClient

        app, _ = app_and_store
        assert TestClient(app).get("/falls/entries").status_code == 401


class TestTheClip:
    def test_a_saved_clip_inside_the_folder_is_served(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        folder = store.config.storage.fall_clips_dir
        folder.mkdir(parents=True)
        clip = folder / "cam-a_1.mp4"
        clip.write_bytes(b"x")
        scenes.attach_clip(down_now, clip)
        path, reason = store.clip_for_fall(down_now)
        assert path == clip.resolve() and reason == ""
        assert store.falls(None)[0].clip.url == f"/falls/{down_now}/clip"

    def test_a_path_outside_the_folder_is_never_served(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        outside = tmp_path / "secret.mp4"
        outside.write_bytes(b"x")
        scenes.attach_clip(down_now, outside)
        path, reason = store.clip_for_fall(down_now)
        assert path is None and "not where it should be" in reason

    def test_no_clip_says_why(self, tmp_path, scenes, down_now):
        store = live_store(tmp_path, scenes, FakeWorker())
        scenes.fail_clip(down_now, "No clip: recording is not running on this engine.")
        path, reason = store.clip_for_fall(down_now)
        assert path is None and "not running" in reason


class TestOnTheConsole:
    def test_the_overlay_draws_only_people_down_and_names_nobody(self, tmp_path, scenes):
        from vg.features.falls import DownBox

        worker = FakeWorker(down=[DownBox(0.3, 0.6, 0.4, 0.2, 12.0, True, 0.9),
                                  DownBox(0.0, 0.0, 0.2, 0.2, 3.0, False, 0.7)])
        store = live_store(tmp_path, scenes, worker)
        boxes = store._boxes("cam-a", "falls")
        assert [b.severity for b in boxes] == [S.Severity.CRITICAL, S.Severity.WARN]
        assert all(b.track_id is None and b.match == S.MatchKind.NONE for b in boxes)
        assert store._boxes("cam-b", "falls") == []

    def test_somebody_down_is_on_home_until_they_get_up(self, tmp_path, scenes, down_now):
        from vg.alerts.store import AlertStore

        alerts = AlertStore(tmp_path / "alerts.db")
        try:
            store = live_store(tmp_path, scenes, FakeWorker(), alerts_store=alerts)
            items = [i for i in store.attention() if i.kind == "fall"]
            assert [i.target_id for i in items] == [down_now]
            assert items[0].severity == S.Severity.CRITICAL
            assert items[0].note.code == "attention.fall"
            scenes.close(down_now, datetime.now(timezone.utc), "got_up")
            assert [i for i in store.attention() if i.kind == "fall"] == []
        finally:
            alerts.close_db()

    def test_down_but_not_yet_counted_is_not_on_home(self, tmp_path, scenes):
        from vg.alerts.store import AlertStore

        went = datetime.now(timezone.utc) - timedelta(seconds=3)
        scenes.open("cam-a", went, went, 0.7, "lstm_cctv")
        alerts = AlertStore(tmp_path / "alerts.db")
        try:
            store = live_store(tmp_path, scenes, FakeWorker(), alerts_store=alerts)
            assert [i for i in store.attention() if i.kind == "fall"] == []
        finally:
            alerts.close_db()

    def test_capability_and_health_say_why_when_off(self, bare_live_store):
        states = {c.key: c for c in bare_live_store.capabilities()}
        assert states["falls"].state.value == "unavailable"
        assert states["falls"].reason
        stage = next(s for s in bare_live_store.health().pipeline if s.key == "falls")
        assert stage.healthy is False and stage.detail == states["falls"].reason

    def test_no_camera_checked_is_said_not_shown_as_running(self, tmp_path, scenes):
        store = live_store(tmp_path, scenes, FakeWorker(cameras=()))
        state, reason = store._falls_state()
        assert state.value == "unavailable" and "System health" in reason

    def test_running_is_live_with_no_excuse(self, tmp_path, scenes):
        store = live_store(tmp_path, scenes, FakeWorker())
        states = {c.key: c for c in store.capabilities()}
        assert states["falls"].state.value == "live" and states["falls"].reason is None
        stage = next(s for s in store.health().pipeline if s.key == "falls")
        assert stage.healthy and "1 camera(s)" in stage.detail

    def test_ticking_falls_on_a_camera_watches_it(self, tmp_path, scenes):
        from vg.config import CameraConfig

        worker = FakeWorker(cameras=())
        store = live_store(tmp_path, scenes, worker)
        camera = CameraConfig.parse({"id": "cam-b", "name": "Library",
                                     "source": "webcam:1", "features": ["falls"]}, "cam-b")
        notes = store._apply_features(camera)
        assert worker.cameras == ["cam-b"]
        assert any(n.feature == "falls" and n.running for n in notes)
        store._apply_features(CameraConfig.parse(
            {"id": "cam-b", "name": "Library", "source": "webcam:1"}, "cam-b"))
        assert worker.cameras == []


class TestTheRateFloor:
    def test_the_floor_leaves_room_inside_the_interpolation_window(self):
        """A copied number is only safe while something checks it."""
        from vg import config as cfg
        from vg.infer.falls import MAX_INTERPOLATE_SECONDS

        assert 1.0 / cfg.MIN_ANALYTICS_HZ["falls"] < MAX_INTERPOLATE_SECONDS

    def test_falls_below_the_floor_is_refused_with_what_to_do(self):
        from vg import config as cfg

        with pytest.raises(cfg.ConfigError) as raised:
            cfg.CameraConfig.parse({"id": "c", "name": "c", "source": "webcam:0",
                                    "fps": 2, "features": ["falls"]}, "c")
        assert "falls" in str(raised.value) and "raise the rate" in str(raised.value).lower()
