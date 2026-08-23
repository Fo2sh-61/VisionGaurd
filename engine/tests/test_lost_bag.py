"""Bag detection on the cameras somebody is looking at, without a camera or a model.

There is no search and no job here, so what is worth proving is narrow:

  * nothing runs until a tile asks for a bag overlay, and it stops when they stop
  * a camera nobody is looking at is never handed to the detector
  * a frame already seen is not analysed twice
  * the overlay shows the newest frame's boxes, not a stack of every recent one
  * the box carries a bag, never a name, and goes stale rather than lingering
  * the colour filter narrows, and never hides a bag whose colour is unknown
  * a `lost` poll does not wake face recognition
  * it works with every other feature switched off

The watch takes its clock as a callable, so ageing a box out takes microseconds
and no test sleeps on the clock it is measuring.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from vg.api import schemas as S
from vg.infer.bags import DetectedBag
from vg.ingest.source import Frame

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
    that only watched cameras are analysed, can only be proved by recording it.
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
    """Stands in for `BagDetector`. Records every call, resolved to a camera."""

    def __init__(self, boxes_by_camera: dict[str, list[DetectedBag]] | None = None,
                 marks: dict[int, str] | None = None) -> None:
        self.boxes_by_camera = boxes_by_camera or {}
        self.marks = marks or {}
        self.asked: list[str] = []
        self.version = "bagbest"
        self.device = "cpu"
        self._lock = threading.Lock()

    def detect(self, image, min_confidence=None):
        with self._lock:
            camera_id = self.marks.get(int(image[0, 0, 0]), "?")
            self.asked.append(camera_id)
        return list(self.boxes_by_camera.get(camera_id, []))


class FakeConfig:
    def __init__(self, camera_id: str, name: str, area: str | None = None) -> None:
        self.id = camera_id
        self.name = name
        self.area = area
        self.enabled = True


class FakeWorker:
    """Hands out scripted frames, then repeats the last one forever.

    Repeating is the real behaviour: `last_frame()` returns the same frame until
    the camera delivers a new one, which is why the watch skips an unchanged
    `sequence`.
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
    """Always sees Mohamed, and records every boost.

    Its whole job is to be available and stay untouched: if a `lost` poll ever
    wakes it, `boosted` says so.
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
    """`specs` are `(camera_id, frames)` or `(camera_id, frames, status)`."""
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
           repeat_sequence: bool = False) -> list[Frame]:
    """`count` frames for one camera, all stamped at START.

    One timestamp for every frame so that "how old is this box" is decided by
    the clock the test moves and nothing else.
    """
    return [
        frame(camera_id, at=0.0, mark=mark, sequence=0 if repeat_sequence else i)
        for i in range(count)
    ]


def _clock():
    from vg.clock import clock_for

    return clock_for("UTC")


def new_watch(registry, detector, now: FixedNow):
    from vg.features.lostbag import BagWatch

    watch = BagWatch(registry, detector, _clock(), now=now)
    watch.start()
    return watch


def wait_until(predicate, *, timeout: float = 5.0) -> None:
    """Wait on the watch, never on the clock under test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def live_store(tmp_path, registry=None, **kw):
    """A LiveStore over a roster and a throwaway database.

    Pass `registry` to use the fakes. Without one the cameras are real
    `CameraWorker`s that were never started, so they read **offline** - and
    `camera_detections` returns no boxes for an offline camera, which quietly
    turns an endpoint assertion into one that passes for the wrong reason.
    """
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    if registry is None:
        roster = [
            CameraConfig.parse(
                {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
                 "features": ["counting"]}, "cam-a"),
            CameraConfig.parse(
                {"id": "cam-b", "name": "Back door", "source": "webcam:1",
                 "features": ["counting"]}, "cam-b"),
        ]
        registry = CameraRegistry(roster)
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


# ---------------------------------------------------------------------------
# nothing runs until somebody looks
# ---------------------------------------------------------------------------

class TestOnlyWhenSomebodyIsLooking:
    def test_no_interest_means_no_model_call(self):
        """The whole of the idle cost: one sleeping thread and nothing else."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 50)))
        detector = FakeBags(marks=marks)
        watch = new_watch(registry, detector, FixedNow())
        try:
            time.sleep(0.5)
            assert detector.asked == []
            assert watch.watching == []
            assert watch.stats["state"] == "idle"
        finally:
            watch.stop()

    def test_a_poll_is_what_starts_the_work(self):
        """Noting interest, and only that, puts a camera in front of the model."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 50)))
        detector = FakeBags(marks=marks)
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: detector.asked)
            assert set(detector.asked) == {"cam-a"}
            assert watch.stats["state"] == "watching"
        finally:
            watch.stop()

    def test_a_camera_nobody_is_watching_is_never_analysed(self):
        """Ticking one camera must not cost a pass on the one beside it."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 50)),
            ("cam-b", marked("cam-b", 2, 50)),
        )
        detector = FakeBags(marks=marks)
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: len(detector.asked) >= 3)
            assert set(detector.asked) == {"cam-a"}
        finally:
            watch.stop()

    def test_interest_lapses_when_the_page_stops_polling(self):
        """Leaving the page stops the work. Nobody has to press anything."""
        from vg.features.lostbag import INTEREST_SECONDS

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks)
        now = FixedNow()
        watch = new_watch(registry, detector, now)
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: detector.asked)

            now.advance(INTEREST_SECONDS + 1)
            wait_until(lambda: watch.watching == [])
            settled = len(detector.asked)
            time.sleep(0.5)
            assert len(detector.asked) == settled, "still working with nobody looking"
            assert watch.boxes_on("cam-a") == []
        finally:
            watch.stop()

    def test_an_unchanged_frame_is_not_analysed_twice(self):
        """A stalled camera must not cost a model pass per poll."""
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 50, repeat_sequence=True)))
        detector = FakeBags(marks=marks)
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: detector.asked)
            time.sleep(0.4)
            assert detector.asked.count("cam-a") == 1
        finally:
            watch.stop()

    def test_an_offline_camera_is_not_handed_to_the_model(self):
        registry, marks = make_registry(
            ("cam-a", marked("cam-a", 1, 50), "offline"))
        detector = FakeBags(marks=marks)
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            time.sleep(0.4)
            assert detector.asked == []
            assert watch.boxes_on("cam-a") == []
        finally:
            watch.stop()

    def test_an_unknown_camera_is_ignored_not_a_crash(self):
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 50)))
        watch = new_watch(registry, FakeBags(marks=marks), FixedNow())
        try:
            watch.note_interest("cam-nope")
            time.sleep(0.4)
            assert watch.boxes_on("cam-nope") == []
        finally:
            watch.stop()


# ---------------------------------------------------------------------------
# the boxes
# ---------------------------------------------------------------------------

class TestTheBoxes:
    def test_a_bag_in_view_is_outlined_at_once(self, tmp_path):
        """One frame is enough. There is no confirmation to wait for - the
        operator is looking at the picture and can judge it themselves."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            store = live_store(tmp_path, lost=watch, recogniser=NamingRecogniser())
            store.note_lost_interest("cam-a")
            wait_until(lambda: store.overlay("cam-a", "lost"))

            boxes = store.overlay("cam-a", "lost")
            assert len(boxes) == 1
            assert boxes[0].kind == "object"
            assert boxes[0].label == "Backpack"
            assert boxes[0].match is S.MatchKind.NONE
            assert boxes[0].severity is S.Severity.WARN
            assert boxes[0].track_id is None
        finally:
            watch.stop()

    def test_the_overlay_carries_no_name_even_when_a_face_is_matched(self, tmp_path):
        """Rules 1 and 3, and the knife trap: `_boxes` falls through to faces."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            store = live_store(tmp_path, lost=watch, recogniser=NamingRecogniser())
            store.note_lost_interest("cam-a")
            wait_until(lambda: store.overlay("cam-a", "lost"))

            assert all(b.label == "Backpack" for b in store.overlay("cam-a", "lost"))
            # The same camera on attendance still names the face. The bag
            # overlay hides nothing; it is simply not the one that names people.
            assert any(b.label == "Mohamed Fouad"
                       for b in store.overlay("cam-a", "attendance"))
        finally:
            watch.stop()

    def test_a_box_goes_stale_rather_than_lingering(self, tmp_path):
        """A box over a live picture of where a bag *was* is a stale frame
        wearing a rectangle."""
        from vg.features.lostbag import OVERLAY_HOLD_SECONDS

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        now = FixedNow()
        watch = new_watch(registry, detector, now)
        try:
            store = live_store(tmp_path, lost=watch)
            store.note_lost_interest("cam-a")
            wait_until(lambda: store.overlay("cam-a", "lost"))

            now.advance(OVERLAY_HOLD_SECONDS + 1)
            assert store.overlay("cam-a", "lost") == []
        finally:
            watch.stop()

    def test_one_bag_is_one_box_however_many_frames_saw_it(self):
        """Holding every recent hit would stack a hundred rectangles on one
        rucksack, which reads as a smear rather than a box."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: len(detector.asked) >= 20)
            assert len(watch.boxes_on("cam-a")) == 1
        finally:
            watch.stop()

    def test_a_tiny_box_is_ignored(self):
        """A distant smudge is not a bag somebody can go and pick up."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks,
                            boxes_by_camera={"cam-a": [bag(w=0.02, h=0.02)]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: len(detector.asked) >= 3)
            assert watch.boxes_on("cam-a") == []
        finally:
            watch.stop()

    def test_a_whole_frame_box_is_ignored(self):
        """Research D10: a motion-blurred frame reads as one 99.7 % `suitcase`,
        four times over 706 sampled frames of footage with no bag in it."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={
            "cam-a": [bag(x=0.0, y=0.0, w=1.0, h=1.0, label="suitcase")]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            watch.note_interest("cam-a")
            wait_until(lambda: len(detector.asked) >= 3)
            assert watch.boxes_on("cam-a") == []
        finally:
            watch.stop()


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
    """A bag-sized patch: flat colour, texture noise, and a dark strap."""
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
    frame_ = np.zeros((size, size, 3), dtype=np.float32)
    frame_[:, :] = _lit((128, 128, 128), gain)
    return np.clip(frame_, 0, 255).astype(np.uint8)


class TestColour:
    def test_colour_under_seven_lights(self):
        """D3's acceptance bar: the lenient set must hold the true name.

        The strict guess is measured and printed but not asserted on - what the
        filter uses is the lenient set, and that is what must never drop the
        right answer, because hiding the bag somebody is looking for is the
        expensive error.
        """
        from vg.infer.colour import name_colour

        strict = rows = 0
        missed: list[str] = []
        for light, gain in LIGHTING:
            reference = scene(gain)
            for i, (expected, bgr) in enumerate(SWATCHES):
                rows += 1
                guess = name_colour(swatch(bgr, gain, seed=i), reference)
                if guess.best == expected:
                    strict += 1
                if expected not in guess.lenient:
                    missed.append(f"{expected} under {light}: best={guess.best} "
                                  f"lenient={sorted(guess.lenient)}")

        print(f"\nstrict nearest colour: {strict}/{rows} = {strict / rows:.0%}")
        assert not missed, (
            "the lenient set dropped the true colour, which is the one error "
            "this design cannot absorb:\n  " + "\n  ".join(missed))

    def test_every_name_is_one_the_wire_knows(self):
        from vg.infer.colour import KNOWN_COLOURS, name_colour

        for _, gain in LIGHTING:
            reference = scene(gain)
            for i, (_, bgr) in enumerate(SWATCHES):
                guess = name_colour(swatch(bgr, gain, seed=i), reference)
                assert guess.best in KNOWN_COLOURS
                assert guess.lenient <= set(KNOWN_COLOURS)

    def test_a_degenerate_crop_does_not_raise(self):
        """An empty or one-pixel crop is a bad box, not a reason to lose one."""
        from vg.infer.colour import name_colour

        reference = scene((1.0, 1.0, 1.0))
        assert name_colour(np.zeros((0, 0, 3), dtype=np.uint8), reference).best
        assert name_colour(np.zeros((1, 1, 3), dtype=np.uint8), reference).best

    def test_crop_for_clamps_to_the_frame(self):
        from vg.infer.colour import crop_for

        image = np.zeros((100, 200, 3), dtype=np.uint8)
        crop = crop_for(image, bag(x=0.95, y=0.95, w=0.5, h=0.5))
        assert crop.size > 0

    def test_matches_colour_is_the_one_rule_the_overlay_uses(self):
        from vg.features.lostbag import Hit, matches_colour

        def hit(colours):
            return Hit(at=START, x=0.1, y=0.1, w=0.2, h=0.2, label="backpack",
                       confidence=0.8, colours=frozenset(colours))

        assert matches_colour(hit({"blue", "black"}), "blue")
        assert matches_colour(hit({"blue", "black"}), "black")
        assert not matches_colour(hit({"red"}), "blue")
        # No colour asked for means every bag.
        assert matches_colour(hit({"red"}), None)
        # An unnamed colour means "could not narrow this down", which is a
        # different answer from "not the one" - it must never hide a bag.
        assert matches_colour(hit(set()), "blue")

    def test_the_overlay_only_draws_the_colour_that_was_asked_for(self, tmp_path):
        """An amber box round a black bag, for somebody who asked for blue, is a
        detection they did not ask for on the tile they are staring at."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        watch = new_watch(registry, detector, FixedNow())
        try:
            store = live_store(tmp_path, lost=watch)
            store.note_lost_interest("cam-a")
            wait_until(lambda: watch.boxes_on("cam-a"))

            named = {c for h in watch.boxes_on("cam-a") for c in h.colours}
            assert named, "the watch must name a colour on every box"

            # A colour the bag is not.
            wrong = next(c for c in ("red", "green", "yellow", "blue")
                         if c not in named)
            assert store.overlay("cam-a", "lost", wrong) == []
            # ...and one it is.
            assert store.overlay("cam-a", "lost", sorted(named)[0])
            # No colour asked for shows everything.
            assert store.overlay("cam-a", "lost")
        finally:
            watch.stop()


# ---------------------------------------------------------------------------
# start-up, capability and the endpoint
# ---------------------------------------------------------------------------

class TestHonestStates:
    def test_a_bare_engine_says_why_there_are_no_boxes(self, bare_live_store):
        cap = {c.key: c for c in bare_live_store.capabilities()}["search_lost"]
        assert cap.name == "Bag detection"
        assert cap.state is S.DataState.UNAVAILABLE
        assert cap.reason
        assert bare_live_store.overlay("cam-a", "lost") == []

    def test_capabilities_and_health_say_what_is_happening(self, tmp_path):
        """P7-FR-016 / D6. Never a bare label."""
        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        watch = new_watch(registry, FakeBags(marks=marks), FixedNow())
        try:
            store = live_store(tmp_path, lost=watch)
            cap = {c.key: c for c in store.capabilities()}["search_lost"]
            assert cap.state is S.DataState.LIVE
            assert cap.reason is None

            stage = {s.key: s for s in store.health().pipeline}["search_lost"]
            assert stage.healthy
            assert "idle" in stage.detail
            assert "bagbest" in stage.detail

            store.note_lost_interest("cam-a")
            stage = {s.key: s for s in store.health().pipeline}["search_lost"]
            assert "watching 1 camera" in stage.detail
        finally:
            watch.stop()

    def test_a_failed_start_is_a_sentence_not_a_crash(self, bare_live_store):
        bare_live_store.lost_error = "weights not found"
        cap = {c.key: c for c in bare_live_store.capabilities()}["search_lost"]
        assert cap.state is S.DataState.UNAVAILABLE
        assert "weights not found" in cap.reason


class TestStandsAlone:
    def test_works_with_every_other_feature_off(self, monkeypatch):
        """Rule 9 / P7-FR-014. No feature may require another to be on."""
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.config import CameraConfig
        from vg.infer import bags as bags_module
        from vg.infer import persons as persons_module

        built: list[str] = []

        class StubDetector:
            version, device = "bagbest", "cpu"

            def __init__(self, **kw):
                built.append("bags")

            def detect(self, image, min_confidence=None):
                return []

        monkeypatch.setattr(bags_module, "BagDetector", StubDetector)

        def boom(*a, **kw):  # pragma: no cover - only runs if the gate breaks
            raise AssertionError("bag detection must not build a person detector")

        monkeypatch.setattr(persons_module, "PersonDetector", boom)

        roster = [CameraConfig.parse(
            {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
             "features": []}, "cam-a")]
        registry = FakeRegistry({"cam-a": FakeWorker(
            FakeConfig("cam-a", "Main entrance"), marked("cam-a", 1, 2))})

        watch, error = app_module._start_lost(vgconfig.load(), registry, roster)
        try:
            assert error is None
            assert watch is not None
            assert built == ["bags"]
        finally:
            if watch is not None:
                watch.stop()


class TestTheEndpoint:
    def test_a_lost_poll_draws_a_bag_and_leaves_faces_alone(self, tmp_path, authed):
        """The poll is what starts the work - and it must not wake the face
        model, which is the lesson the knife page paid for."""
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        recogniser = NamingRecogniser()
        watch = new_watch(registry, detector, FixedNow())
        store = live_store(tmp_path, registry, lost=watch, recogniser=recogniser)

        app_module.set_store(store)
        try:
            app = app_module.create_app()
            app.state.recogniser = recogniser
            client = authed(app)

            first = client.get("/cameras/cam-a/detections?feature=lost")
            assert first.status_code == 200
            # The poll registered interest, so the model starts looking.
            wait_until(lambda: watch.boxes_on("cam-a"))
            assert recogniser.boosted == []

            client.get("/cameras/cam-a/detections?feature=attendance")
            assert recogniser.boosted == ["cam-a"]
        finally:
            watch.stop()
            app_module.set_store(MockStore())

    def test_the_colour_query_narrows_the_overlay(self, tmp_path, authed):
        from vg.api import app as app_module
        from vg.api.store import MockStore

        registry, marks = make_registry(("cam-a", marked("cam-a", 1, 500)))
        detector = FakeBags(marks=marks, boxes_by_camera={"cam-a": [bag()]})
        watch = new_watch(registry, detector, FixedNow())
        store = live_store(tmp_path, registry, lost=watch)

        app_module.set_store(store)
        try:
            app = app_module.create_app()
            app.state.recogniser = None
            client = authed(app)
            client.get("/cameras/cam-a/detections?feature=lost")
            wait_until(lambda: watch.boxes_on("cam-a"))

            named = {c for h in watch.boxes_on("cam-a") for c in h.colours}
            wrong = next(c for c in ("red", "green", "yellow", "blue")
                         if c not in named)

            asked = client.get(f"/cameras/cam-a/detections?feature=lost&colour={wrong}")
            assert asked.status_code == 200
            assert asked.json()["boxes"] == []

            right = sorted(named)[0]
            kept = client.get(f"/cameras/cam-a/detections?feature=lost&colour={right}")
            assert kept.json()["boxes"]
        finally:
            watch.stop()
            app_module.set_store(MockStore())

    def test_demo_mode_does_not_pretend_to_detect(self):
        """`MockStore` has no model to point at a camera, and says nothing."""
        from vg.api.store import MockStore

        store = MockStore()
        store.note_lost_interest("cam-a")
