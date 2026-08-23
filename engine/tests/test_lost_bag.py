"""Lost bag search, end to end, without a camera or a model.

A search is the one feature here that runs *only* while somebody is watching
it, so most of what is worth proving is about what it does **not** do:

  * a camera the operator did not tick is never handed to the detector
  * a frame already seen is not analysed twice, so "seen 40 times" means 40 looks
  * one frame is not a result - a false hit is exactly one frame (D1)
  * a box covering the whole picture is not a result either (D10)
  * the overlay carries a bag, never a name, and drops when the hit goes stale
  * a `lost` poll does not wake face recognition
  * nothing runs when nobody is searching, and no other feature has to be on

The job takes its clock as a callable, so a sixty-second limit is proved in
microseconds. No test here sleeps on the clock it is measuring, and none of
them touch the real weights.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.api import schemas as S
from vg.infer.bags import DetectedBag
from vg.ingest.source import Frame

# Relative to the clock, for the reason `test_weapons_live.py` gives: a date
# typed on the day this was written stops sitting inside its own window as
# soon as it is more than a day old.
START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)

REPO_DIR = Path(__file__).resolve().parents[2]
BAG_WEIGHTS = REPO_DIR / "models" / "bagbest.pt"


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

def frame(camera_id: str = "cam-a", *, at: float = 0.0, sequence: int = 0,
          mark: int = 0) -> Frame:
    """One frame, `at` seconds after START.

    `mark` is written into pixel (0, 0) so `FakeBags` can tell which camera the
    pixels came from. The real detector cannot - `detect(image)` is handed bare
    pixels and never learns the camera - and the rule that matters most here,
    that only ticked cameras are ever analysed, can only be proved by recording
    which camera each call was about.
    """
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    image[0, 0, 0] = mark
    return Frame(
        camera_id=camera_id,
        image=image,
        captured_at=START + timedelta(seconds=at),
        sequence=sequence,
    )


def bag(x: float = 0.4, y: float = 0.4, w: float = 0.2, h: float = 0.2,
        confidence: float = 0.7, label: str = "backpack") -> DetectedBag:
    """A bag box. The default sits well inside both size limits."""
    return DetectedBag(x=x, y=y, w=w, h=h, confidence=confidence, label=label)


class FakeBags:
    """Stands in for `BagDetector`. Records every call, resolved to a camera.

    `boxes_by_camera` is what to return for a camera on every call. `script`
    overrides it with a per-call list, so a test can make a bag appear once and
    then stop - which is how a false positive behaves and how a real one does
    not.
    """

    def __init__(self, boxes_by_camera: dict[str, list[DetectedBag]] | None = None,
                 marks: dict[int, str] | None = None,
                 script: dict[str, list[list[DetectedBag]]] | None = None) -> None:
        self.boxes_by_camera = boxes_by_camera or {}
        self.script = script or {}
        self.marks = marks or {}
        self.asked: list[str] = []
        self.version = "bagbest"
        self.device = "cpu"
        self._lock = threading.Lock()

    def detect(self, image, min_confidence=None):
        with self._lock:
            camera_id = self.marks.get(int(image[0, 0, 0]), "?")
            n = self.asked.count(camera_id)
            self.asked.append(camera_id)
        if camera_id in self.script:
            steps = self.script[camera_id]
            return list(steps[n]) if n < len(steps) else []
        return list(self.boxes_by_camera.get(camera_id, []))


class FakeConfig:
    def __init__(self, camera_id: str, name: str, area: str | None = None) -> None:
        self.id = camera_id
        self.name = name
        self.area = area
        self.enabled = True


class FakeWorker:
    """Hands out scripted frames, then repeats the last one forever.

    Repeating is the real behaviour: `last_frame()` returns the same frame
    until the camera delivers a new one, which is exactly why the job has to
    skip on an unchanged `sequence`.
    """

    def __init__(self, config: FakeConfig, frames: list[Frame],
                 status: str = "ok") -> None:
        self.config = config
        self.frames = list(frames)
        self._status = status
        self._i = 0
        self._lock = threading.Lock()

    @property
    def status(self) -> str:
        return self._status

    def last_frame(self) -> Frame | None:
        with self._lock:
            if not self.frames:
                return None
            i = min(self._i, len(self.frames) - 1)
            self._i += 1
            return self.frames[i]


class FakeRegistry:
    def __init__(self, workers: dict[str, FakeWorker],
                 disabled: dict[str, FakeConfig] | None = None) -> None:
        self.workers = dict(workers)
        self.disabled = dict(disabled or {})

    def worker(self, camera_id: str) -> FakeWorker | None:
        return self.workers.get(camera_id)

    def configs(self) -> list[FakeConfig]:
        return [w.config for w in self.workers.values()] + list(self.disabled.values())

    @property
    def online(self) -> int:
        return sum(1 for w in self.workers.values() if w.status == "ok")

    @property
    def total(self) -> int:
        return len(self.workers) + len(self.disabled)


class FixedNow:
    """A clock the test moves by hand. Never sleeps, never drifts."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or START
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now = self._now + timedelta(seconds=seconds)


class NamingRecogniser:
    """A recogniser that always sees Mohamed, and records every boost.

    Its whole job here is to be available and to stay untouched: if a `lost`
    poll ever wakes it, `boosted` says so.
    """

    def __init__(self) -> None:
        self.boosted: list[str] = []

    def faces_on(self, camera_id: str):
        return [_Face()]

    def result(self, camera_id: str):
        return _Result()

    def note_interest(self, camera_id: str) -> None:
        self.boosted.append(camera_id)


class _Result:
    inference_ms = 12.0


class _Face:
    x, y, w, h = 0.1, 0.1, 0.1, 0.1
    label = "Mohamed Fouad"
    score = 0.97
    identified = True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_registry(*specs) -> tuple[FakeRegistry, dict[int, str]]:
    """`specs` are `(camera_id, frames)` or `(camera_id, frames, status)`.

    Returns the registry and the mark -> camera id map `FakeBags` needs.
    """
    workers, marks = {}, {}
    for i, spec in enumerate(specs, start=1):
        camera_id, frames = spec[0], spec[1]
        status = spec[2] if len(spec) > 2 else "ok"
        marks[i] = camera_id
        workers[camera_id] = FakeWorker(
            FakeConfig(camera_id, camera_id.replace("cam-", "Camera ")),
            frames, status)
    return FakeRegistry(workers), marks


def marked(camera_id: str, mark: int, count: int, *,
           repeat_sequence: bool = False, at_step: float = 0.5) -> list[Frame]:
    """`count` frames for one camera, each with a fresh sequence by default."""
    return [
        frame(camera_id, at=i * at_step, mark=mark,
              sequence=0 if repeat_sequence else i)
        for i in range(count)
    ]


def _clock():
    from vg.clock import clock_for

    return clock_for("UTC")


def new_search(registry, detector, now: FixedNow, *, limit_seconds: float = 60.0):
    from vg.features.lostbag import BagSearch

    return BagSearch(registry, detector, _clock(), limit_seconds=limit_seconds,
                     now=now)


def run_to_end(search, now: FixedNow, *, seconds: float = 61.0) -> None:
    """Move the clock past the limit and wait for the thread to notice."""
    now.advance(seconds)
    search.join(timeout=5.0)
    assert not search.alive(), "the search thread outlived its own limit"


def wait_until(predicate, *, timeout: float = 5.0) -> None:
    """Wait on the *job*, never on the clock under test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def live_store(tmp_path, **kw):
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
    registry = CameraRegistry(roster)

    # Keep every clip write inside the test's own directory, as
    # `test_weapons_live.py` does - the real folder holds an operator's own
    # recordings and the retention sweep.
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


# ---------------------------------------------------------------------------
# the honest states, before anything runs
# ---------------------------------------------------------------------------

class TestHonestStates:
    def test_bare_live_store_search_is_failed_not_done(self, bare_live_store):
        """"We searched and found nothing" and "we never searched" differ.

        Only one of them should stop somebody looking for a child's bag.
        """
        result = bare_live_store.search_lost(S.LostQuery())

        assert result.job.state == "failed"
        assert result.hits == []
        assert result.cameras == []
        assert result.job.error

        cap = {c.key: c for c in bare_live_store.capabilities()}["search_lost"]
        assert cap.state is S.DataState.UNAVAILABLE
        assert cap.reason

    def test_demo_mode_still_searches(self):
        """Demo mode stays a working demo - and stays honest about clips."""
        from vg.api.store import MockStore

        store = MockStore()
        result = store.search_lost(S.LostQuery(cameras=["x"]))

        assert result.job.state == "done"
        assert result.hits
        assert result.cameras_checked == 1
        # There are no clips, in demo mode or out of it.
        assert result.job.clips_searched == 0
        assert result.job.clips_total == 0
        assert store.lost_search() is result
        store.stop_lost_search()


# ---------------------------------------------------------------------------
# what the job looks at, and what it refuses to call a result
# ---------------------------------------------------------------------------

class TestWhatTheJobLooksAt:
    def test_only_chosen_cameras_are_ever_analysed(self):
        """SC-004 / P7-FR-003. The rule the recording double exists to prove."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 4)),
            ("cam-b", marked("cam-b", 2, 4)),
            ("cam-c", marked("cam-c", 3, 4)),
        )
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a", "cam-c"]))
        # The loop checks the clock between cameras, so jumping it straight
        # away can end the search after the first one. Wait for the work, then
        # end it - what is under test is who was asked, not how fast.
        wait_until(lambda: set(detector.asked) >= {"cam-a", "cam-c"})
        run_to_end(search, now)

        assert set(detector.asked) == {"cam-a", "cam-c"}
        assert "cam-b" not in detector.asked

    def test_a_single_frame_is_not_a_result(self):
        """One frame is exactly what a false hit looks like (D1)."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 8)))
        detector = FakeBags(marks=marks, script={"cam-a": [[bag()]]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: search.current().frames_checked >= 3)
        run_to_end(search, now)

        job = search.current()
        assert job.confirmed() == []
        assert job.frames_checked >= 3

    def test_a_bag_seen_twice_pins_its_camera_with_a_box(self, tmp_path):
        """P7-FR-008, 009, 015 - the happy path, in one block."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 3)))
        detector = FakeBags(marks=marks, script={"cam-a": [
            [bag(confidence=0.5)], [bag(confidence=0.9)], [bag(confidence=0.6)],
        ]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: detector.asked.count("cam-a") == 3)
        run_to_end(search, now)

        store = live_store(tmp_path, lost=search)
        result = store.lost_search()

        assert len(result.hits) == 1
        hit = result.hits[0]
        assert hit.camera_id == "cam-a"
        assert hit.box.kind == "object"
        assert hit.box.severity is S.Severity.WARN
        assert hit.box.label == "Backpack"
        assert hit.box.match is S.MatchKind.NONE
        assert hit.box.track_id is None
        # The best of the three, and the time of the last - not the first.
        assert hit.confidence == pytest.approx(0.9)
        assert "3 times" in hit.note
        assert len(result.cameras) == 1
        assert result.cameras[0].id == "cam-a"
        assert result.cameras[0].boxes

    def test_an_unchanged_frame_is_not_analysed_twice(self):
        """Otherwise "seen 40 times" describes one look, forty times over."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 5, repeat_sequence=True)))
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: detector.asked)
        run_to_end(search, now)

        assert detector.asked.count("cam-a") == 1

    def test_the_search_ends_at_the_limit(self):
        """SC-002 / P7-FR-010. It stops itself; nobody has to."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now, limit_seconds=60.0)
        job = search.start(S.LostQuery(cameras=["cam-a"]))
        assert job.state == "running"
        run_to_end(search, now)

        job = search.current()
        assert job.state == "done"
        assert not search.alive()
        assert job.seconds_elapsed(now()) >= 60.0

    def test_a_new_search_replaces_the_running_one(self):
        """P7-FR-011. Replace, never queue - and never mix the results."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 500)),
            ("cam-b", marked("cam-b", 2, 500)),
        )
        detector = FakeBags(marks=marks,
                            boxes_by_camera={"cam-a": [bag()], "cam-b": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        first = search.start(S.LostQuery(cameras=["cam-a"]))
        second = search.start(S.LostQuery(cameras=["cam-b"]))

        assert first.state == "stopped"
        assert second.id != first.id
        assert search.current() is second
        run_to_end(search, now)
        assert "cam-a" not in search.current().hits

    def test_stop_keeps_the_hits(self):
        """Stopping is not undoing. The operator asked it to end, not to forget."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: len(search.current().hits.get("cam-a", [])) >= 2)
        search.stop()

        job = search.current()
        assert job.state == "stopped"
        assert job.confirmed() == ["cam-a"]
        assert not search.alive()

    def test_a_tiny_box_is_ignored(self):
        """A distant smudge is not a bag somebody can go and pick up."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 8)))
        detector = FakeBags(marks=marks,
                            boxes_by_camera={"cam-a": [bag(w=0.02, h=0.02)]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: search.current().frames_checked >= 3)
        run_to_end(search, now)

        assert search.current().confirmed() == []

    def test_a_whole_frame_box_is_ignored(self):
        """Research D10: a motion-blurred frame reads as one 99.7 % `suitcase`.

        Measured on `baseline-empty` at the configured confidence, four times
        over 706 sampled frames. A box covering the whole picture is a blur
        artefact, never a bag anybody can walk over and collect - and unlike a
        one-frame flicker it recurs, so the two-frame rule does not catch it.
        """
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 8)))
        detector = FakeBags(marks=marks, boxes_by_camera={
            "cam-a": [bag(x=0.0, y=0.0, w=1.0, h=1.0, label="suitcase")]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: search.current().frames_checked >= 3)
        run_to_end(search, now)

        assert search.current().confirmed() == []


# ---------------------------------------------------------------------------
# cameras that could not be looked at
# ---------------------------------------------------------------------------

class TestCamerasThatCannotBeLookedAt:
    def test_an_offline_camera_is_named_not_dropped(self):
        """P7-FR-013. Ticking a box earns an answer, even a disappointing one."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 4)),
            ("cam-b", marked("cam-b", 2, 4), "offline"),
        )
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a", "cam-b"]))
        wait_until(lambda: "cam-a" in search.current().checked
                   and search.current().unavailable)
        run_to_end(search, now)

        job = search.current()
        named = {u.camera_id: u.reason for u in job.unavailable}
        assert "cam-b" in named
        assert "offline" in named["cam-b"].lower()
        assert "cam-a" in job.checked
        assert job.state == "done"

    def test_an_unknown_camera_is_named_not_404(self, tmp_path):
        """A bad id in a list of ten must not lose the other nine."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 4)))
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a", "cam-nope"]))
        run_to_end(search, now)

        store = live_store(tmp_path, lost=search)
        result = store.lost_search()
        named = {u.camera_id: u.reason for u in result.cameras_unavailable}
        assert named.get("cam-nope") == "Not a camera on this engine."
        assert result.job.state == "done"

    def test_a_search_of_nothing_fails_with_a_sentence(self):
        """Payload, not a 422 - an error code helps nobody tick a box."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 4)))
        detector = FakeBags(marks=marks)
        search = new_search(registry, detector, FixedNow())
        job = search.start(S.LostQuery(cameras=[]))

        assert job.state == "failed"
        assert job.error == "No camera was chosen."
        assert not search.alive()
        assert detector.asked == []


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

class TestTheOverlay:
    def test_the_overlay_carries_no_name_and_drops_after_the_hold(self, tmp_path):
        """Rules 1 and 3, D5. The knife trap, checked before it can be sprung."""
        from vg.features.lostbag import OVERLAY_HOLD_SECONDS

        # Every frame carries the same timestamp, so "how old is this hit" is
        # decided by the clock the test moves and nothing else.
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 500, at_step=0.0)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: search.boxes_on("cam-a"))
        search.stop()

        store = live_store(tmp_path, lost=search, recogniser=NamingRecogniser())

        boxes = store.overlay("cam-a", "lost")
        # One bag in view is one box, however many times it was seen.
        assert len(boxes) == 1
        assert all(b.kind == "object" for b in boxes)
        assert all(b.label == "Backpack" for b in boxes)
        assert all(b.match is S.MatchKind.NONE for b in boxes)
        assert all(b.severity is S.Severity.WARN for b in boxes)

        # The same camera on the attendance page still names the face. The bag
        # overlay hides nothing; it simply is not the one that names people.
        named = store.overlay("cam-a", "attendance")
        assert any(b.label == "Mohamed Fouad" for b in named)

        # A box over where a bag *was* is a stale frame wearing a rectangle.
        now.advance(OVERLAY_HOLD_SECONDS + 5)
        assert store.overlay("cam-a", "lost") == []

    def test_a_lost_poll_does_not_wake_face_recognition(self, tmp_path, authed):
        """The knife-page lesson, kept. `lost` is not in `FACE_OVERLAYS`."""
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 4)))
        detector = FakeBags(marks=marks)
        recogniser = NamingRecogniser()
        search = new_search(registry, detector, FixedNow())
        store = live_store(tmp_path, lost=search, recogniser=recogniser)

        app_module.set_store(store)
        try:
            app = app_module.create_app()
            app.state.recogniser = recogniser
            client = authed(app)

            assert client.get("/cameras/cam-a/detections?feature=lost").status_code == 200
            assert recogniser.boosted == []

            client.get("/cameras/cam-a/detections?feature=attendance")
            assert recogniser.boosted == ["cam-a"]
        finally:
            app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# start-up, capabilities and the endpoints
# ---------------------------------------------------------------------------

class TestStandsAlone:
    def test_works_with_every_other_feature_off(self, monkeypatch):
        """Rule 9 / P7-FR-014. No feature may require another to be switched on."""
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.config import CameraConfig
        from vg.infer import bags as bags_module

        built: list[str] = []

        class StubDetector:
            version, device = "bagbest", "cpu"

            def __init__(self, **kw):
                built.append("bags")

            def detect(self, image, min_confidence=None):
                return []

        monkeypatch.setattr(bags_module, "BagDetector", StubDetector)

        def boom(*a, **kw):  # pragma: no cover - only runs if the gate breaks
            raise AssertionError("lost bag search must not build a person detector")

        from vg.infer import persons as persons_module

        monkeypatch.setattr(persons_module, "PersonDetector", boom)

        roster = [CameraConfig.parse(
            {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
             "features": []}, "cam-a")]
        registry = FakeRegistry({"cam-a": FakeWorker(
            FakeConfig("cam-a", "Main entrance"), marked("cam-a", 1, 2))})

        search, error = app_module._start_lost(vgconfig.load(), registry, roster)

        assert error is None
        assert search is not None
        assert built == ["bags"]


class TestCapabilities:
    def test_capabilities_say_why(self, tmp_path, bare_live_store):
        """P7-FR-016 / D6. Four failures, four sentences - never a bare label."""
        cap = {c.key: c for c in bare_live_store.capabilities()}["search_lost"]
        assert cap.name == "Lost bag search"
        assert cap.state is S.DataState.UNAVAILABLE
        assert cap.reason

        bare_live_store.lost_error = "weights not found"
        cap = {c.key: c for c in bare_live_store.capabilities()}["search_lost"]
        assert cap.state is S.DataState.UNAVAILABLE
        assert "weights not found" in cap.reason

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 4)))
        search = new_search(registry, FakeBags(marks=marks), FixedNow())
        store = live_store(tmp_path, lost=search)

        cap = {c.key: c for c in store.capabilities()}["search_lost"]
        assert cap.state is S.DataState.LIVE
        assert cap.reason is None

        stage = {s.key: s for s in store.health().pipeline}["search_lost"]
        assert stage.healthy
        assert "idle" in stage.detail

        store.search_lost(S.LostQuery(cameras=["cam-a"]))
        stage = {s.key: s for s in store.health().pipeline}["search_lost"]
        assert "searching 1 camera" in stage.detail
        search.stop()


class TestEndpoints:
    def test_endpoints_through_the_app(self, tmp_path, authed):
        """POST starts, GET describes, DELETE stops. 404 before any of it."""
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks)
        now = FixedNow()
        search = new_search(registry, detector, now)
        store = live_store(tmp_path, lost=search)

        app_module.set_store(store)
        try:
            client = authed(app_module.create_app())

            assert client.get("/lost-items/search").status_code == 404

            started = client.post("/lost-items/search",
                                  json={"cameras": ["cam-a"]})
            assert started.status_code == 200
            job_id = started.json()["job"]["id"]
            assert started.json()["job"]["state"] == "running"
            assert started.json()["secondsLimit"] == 60.0

            polled = client.get("/lost-items/search")
            assert polled.status_code == 200
            assert polled.json()["job"]["id"] == job_id

            assert client.delete("/lost-items/search").status_code == 204
            assert client.get("/lost-items/search").json()["job"]["state"] == "stopped"

            # Stopping nothing is not a failure.
            assert client.delete("/lost-items/search").status_code == 204
        finally:
            search.stop()
            app_module.set_store(MockStore())

    def test_any_signed_in_user_may_search(self, tmp_path, authed):
        """`/lost-items` is in neither admin prefix list, and must stay out.

        A search reveals nothing the live camera pages do not already show.
        """
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        search = new_search(registry, FakeBags(marks=marks), FixedNow())
        store = live_store(tmp_path, lost=search)

        app_module.set_store(store)
        try:
            client = authed(app_module.create_app(), role="it")
            assert client.post("/lost-items/search",
                               json={"cameras": ["cam-a"]}).status_code == 200
        finally:
            search.stop()
            app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# colour
# ---------------------------------------------------------------------------

# The seven lighting conditions from research D3, as (name, gain-per-channel).
# BGR order, as OpenCV produces. Warm lamps lift red and drop blue; cool
# daylight does the opposite.
LIGHTING = [
    ("normal", (1.00, 1.00, 1.00)),
    ("dim", (0.45, 0.45, 0.45)),
    ("very dim", (0.25, 0.25, 0.25)),
    ("bright", (1.60, 1.60, 1.60)),
    ("warm lamps", (0.80, 0.98, 1.20)),
    ("cool daylight", (1.20, 1.02, 0.84)),
    ("dim and warm", (0.36, 0.44, 0.54)),
]

# The true colour of each patch, in BGR, and the palette name it must answer to.
SWATCHES = [
    ("black", (34, 36, 32)),
    ("light", (232, 236, 234)),
    ("light", (150, 155, 152)),   # mid grey - the same band as white, by design
    ("red", (48, 44, 186)),
    ("blue", (178, 96, 52)),
    ("green", (78, 140, 62)),
    ("yellow", (58, 196, 214)),
]


def _lit(bgr, gain):
    return tuple(min(255.0, channel * g) for channel, g in zip(bgr, gain))


def swatch(bgr, gain, *, size: int = 64, seed: int = 0) -> np.ndarray:
    """A bag-sized patch: flat colour, texture noise, and a dark strap.

    The strap crosses 10 % of the patch and is what the central-60 % crop and
    the median are there to survive.
    """
    rng = np.random.default_rng(seed)
    lit = _lit(bgr, gain)
    patch = np.zeros((size, size, 3), dtype=np.float32)
    patch[:, :] = lit
    patch += rng.normal(0.0, 6.0, patch.shape)
    strap = slice(int(size * 0.45), int(size * 0.55))
    patch[strap, :] = [c * 0.35 for c in lit]
    return np.clip(patch, 0, 255).astype(np.uint8)


def scene(gain, *, size: int = 240) -> np.ndarray:
    """A mid-grey frame under the same light, for the grey-world reference."""
    frame = np.zeros((size, size, 3), dtype=np.float32)
    frame[:, :] = _lit((128, 128, 128), gain)
    return np.clip(frame, 0, 255).astype(np.uint8)


class TestColour:
    def test_colour_under_seven_lights(self):
        """D3's acceptance bar: the lenient set must hold the true name.

        The strict guess is measured and printed but not asserted on - it is
        86 % on this table and the design does not depend on it. What the
        filter uses is the lenient set, and that is what must never drop the
        right answer, because hiding the bag somebody is looking for is the
        expensive error.
        """
        from vg.infer.colour import name_colour

        strict = 0
        rows = 0
        missed: list[str] = []
        for light, gain in LIGHTING:
            frame = scene(gain)
            for i, (expected, bgr) in enumerate(SWATCHES):
                rows += 1
                guess = name_colour(swatch(bgr, gain, seed=i), frame)
                if guess.best == expected:
                    strict += 1
                if expected not in guess.lenient:
                    missed.append(
                        f"{expected} under {light}: best={guess.best} "
                        f"lenient={sorted(guess.lenient)}")

        print(f"\nstrict nearest colour: {strict}/{rows} = {strict / rows:.0%}")
        assert not missed, (
            "the lenient set dropped the true colour, which is the one error "
            "this design cannot absorb:\n  " + "\n  ".join(missed))

    def test_every_name_is_one_the_wire_knows(self):
        """A name the palette does not contain could never be filtered on."""
        from vg.infer.colour import KNOWN_COLOURS, name_colour

        for light, gain in LIGHTING:
            frame = scene(gain)
            for i, (_, bgr) in enumerate(SWATCHES):
                guess = name_colour(swatch(bgr, gain, seed=i), frame)
                assert guess.best in KNOWN_COLOURS
                assert guess.lenient <= set(KNOWN_COLOURS)

    def test_a_degenerate_crop_does_not_raise(self):
        """An empty or one-pixel crop is a bad box, not a reason to lose a hit."""
        from vg.infer.colour import name_colour

        frame = scene((1.0, 1.0, 1.0))
        assert name_colour(np.zeros((0, 0, 3), dtype=np.uint8), frame).best
        assert name_colour(np.zeros((1, 1, 3), dtype=np.uint8), frame).best

    def test_crop_for_clamps_to_the_frame(self):
        """A box running off the edge must come back with pixels, not nothing."""
        from vg.infer.bags import DetectedBag
        from vg.infer.colour import crop_for

        image = np.zeros((100, 200, 3), dtype=np.uint8)
        crop = crop_for(image, DetectedBag(x=0.95, y=0.95, w=0.5, h=0.5,
                                           confidence=0.9, label="backpack"))
        assert crop.size > 0


class TestColourFilter:
    def test_colour_filter_hides_with_a_count(self, tmp_path):
        """P7-FR-006, 007. Hidden is not the same as not found, and says so."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 3)),
            ("cam-b", marked("cam-b", 2, 3)),
        )
        detector = FakeBags(marks=marks, boxes_by_camera={
            "cam-a": [bag()], "cam-b": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a", "cam-b"]))
        wait_until(lambda: sorted(search.current().confirmed()) == ["cam-a", "cam-b"])
        run_to_end(search, now)

        job = search.current()
        _paint(job, "cam-a", "blue", {"blue", "black"})
        _paint(job, "cam-b", "red", {"red"})

        store = live_store(tmp_path, lost=search)

        job.query = S.LostQuery(cameras=["cam-a", "cam-b"], colour="blue")
        narrowed = store.lost_search()
        assert [h.camera_id for h in narrowed.hits] == ["cam-a"]
        assert narrowed.hidden_by_colour == 1
        assert [c.id for c in narrowed.cameras] == ["cam-a"]

        job.query = S.LostQuery(cameras=["cam-a", "cam-b"])
        everything = store.lost_search()
        assert len(everything.hits) == 2
        assert everything.hidden_by_colour == 0

    def test_a_hit_carries_its_colour_on_the_wire(self, tmp_path):
        """The page says "looked blue or black", so both have to travel."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 3)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        wait_until(lambda: search.current().confirmed() == ["cam-a"])
        run_to_end(search, now)
        _paint(search.current(), "cam-a", "blue", {"blue", "black"})

        hit = live_store(tmp_path, lost=search).lost_search().hits[0]
        assert hit.colour == "blue"
        assert sorted(hit.colours) == ["black", "blue"]

    def test_an_unknown_colour_is_422_naming_the_palette(self, tmp_path, authed):
        """"purple" is not a refusal to answer - it is a list of what to pick."""
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 4)))
        search = new_search(registry, FakeBags(marks=marks), FixedNow())
        store = live_store(tmp_path, lost=search)

        app_module.set_store(store)
        try:
            client = authed(app_module.create_app())
            refused = client.post("/lost-items/search",
                                  json={"cameras": ["cam-a"], "colour": "purple"})
            assert refused.status_code == 422
            detail = str(refused.json())
            for name in ("black", "light", "red", "blue", "green", "yellow"):
                assert name in detail
        finally:
            search.stop()
            app_module.set_store(MockStore())

    def test_the_real_detector_names_a_colour_on_every_hit(self):
        """The job must fill the colour fields, not leave the filter blind.

        Without this the chips on the page would hide every bag: an empty
        lenient set contains nothing, so every colour filters everything out.
        """
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 3)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        now = FixedNow()
        search = new_search(registry, detector, now)
        search.start(S.LostQuery(cameras=["cam-a"]))
        run_to_end(search, now)

        hits = search.current().hits["cam-a"]
        assert hits
        assert all(h.colour for h in hits)
        assert all(h.colours for h in hits)


def _paint(job, camera_id: str, colour: str, colours: set[str]) -> None:
    """Restamp a camera's hits with a known colour.

    The colour a 16x16 black test frame produces is not the point of these
    tests; what the filter does with a colour is.
    """
    import dataclasses

    job.hits[camera_id] = [
        dataclasses.replace(h, colour=colour, colours=frozenset(colours))
        for h in job.hits[camera_id]
    ]
