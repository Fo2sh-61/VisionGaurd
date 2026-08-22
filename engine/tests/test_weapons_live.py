"""Knife detection, end to end, without a camera or a model.

The whole feature is a state machine over two detectors, so almost everything
here is driven with fake frames, fake people, fake knives and a clock the test
controls. A two-minute cut takes microseconds to prove and a 9.5 second flicker
is exactly 9.5 seconds every run.

What is under test is the part that can lie:

  * the knife model is never asked about a frame with nobody in it
  * a knife with nobody near it is not a detection
  * one incident is one entry, even when the detector blinks
  * an entry whose video is gone says why, and offers no button
  * the overlay carries no name, ever, even when a face is matched
  * a verdict records the signed-in account, is written to the audit first,
    and cannot be changed afterwards

Only `test_model_loads_and_finds_nothing_on_grey_and_noise` touches the real
weights, and it skips without them so CI stays green on a machine with no
models folder.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.api import schemas as S
from vg.events.weapons import WeaponSceneStore
from vg.features.weapons import OVERLAY_HOLD_SECONDS
from vg.infer.persons import DetectedPerson
from vg.infer.weapons import DetectedWeapon
from vg.ingest.source import Frame
from vg.ingest.store import CameraStore

# Relative to the clock, never a date typed on the day this was written — the
# reason `test_zones_live.py` gives: a fixed date stops matching its own window
# as soon as it is more than a day old. An hour ago sits inside every window
# used here and stays in the past after a scene adds its two minutes.
START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)

REPO_DIR = Path(__file__).resolve().parents[2]
KNIFE_WEIGHTS = REPO_DIR / "models" / "knifebest.pt"


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


def person(x: float = 0.4, y: float = 0.2, w: float = 0.2,
           h: float = 0.6) -> DetectedPerson:
    return DetectedPerson(x=x, y=y, w=w, h=h, confidence=0.9)


def knife(x: float = 0.45, y: float = 0.4, w: float = 0.05, h: float = 0.05,
          confidence: float = 0.7) -> DetectedWeapon:
    """A knife box. The default sits inside the default person box."""
    return DetectedWeapon(x=x, y=y, w=w, h=h, confidence=confidence, label="knife")


class FakeDetector:
    """Stands in for SharedDetection. Records every camera it was asked about."""

    def __init__(self, people: int = 0) -> None:
        self.people = people
        # Overrides `people` when set: an explicit list of boxes to return.
        self.boxes: list[DetectedPerson] | None = None
        self.asked: list[str] = []

    def detect(self, frame):
        self.asked.append(frame.camera_id)
        if self.boxes is not None:
            return list(self.boxes)
        return [person() for _ in range(self.people)]


class FakeKnives:
    """Stands in for WeaponDetector. Records every call.

    The recording is the point: P6-FR-002 says the knife model must not run on
    a frame with nobody in it, and only this can prove it. The claim that the
    feature is affordable on 208 cameras rests entirely on that gate.

    `asked` holds one entry per call, not a camera id — the real detector's
    `detect(image)` is handed `frame.image` and never learns which camera the
    pixels came from. What matters here is whether it ran at all.
    """

    def __init__(self, hits: int = 0) -> None:
        self.hits = hits
        # Overrides `hits` when set: explicit boxes to return.
        self.boxes: list[DetectedWeapon] | None = None
        self.asked: list[int] = []
        self.version = "knifebest"
        self.device = "cpu"

    def detect(self, image, min_confidence=None):
        self.asked.append(len(self.asked))
        if self.boxes is not None:
            return list(self.boxes)
        return [knife() for _ in range(self.hits)]


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
def scenes(tmp_path) -> WeaponSceneStore:
    store = WeaponSceneStore(tmp_path / "weapons.db")
    yield store
    store.close_db()


def worker(scenes, *, people=None, knives=None, recorder=None,
           cameras=("cam-a", "cam-b")):
    """A WeaponsWorker with no thread started — `analyse` is called directly."""
    from vg.features.weapons import WeaponsWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("the worker must not be started in these tests")

    return WeaponsWorker(
        NoBus(),
        people or FakeDetector(),
        knives or FakeKnives(),
        list(cameras),
        scenes,
        recorder=recorder,
    )


def walk(weapons_worker, people, knives, script, camera_id="cam-a"):
    """Feed a scripted incident: `(seconds, n_people, n_knives)` triples."""
    for i, (at, n_people, n_knives) in enumerate(script):
        people.people = n_people
        people.boxes = None
        knives.hits = n_knives
        knives.boxes = None
        weapons_worker.analyse(frame(camera_id, at=at, sequence=i))


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
    # honest state for a list test.
    registry = CameraRegistry(roster)

    # Point the clip folder at the test's own directory before anything can
    # write to it. `vgconfig.load()` returns a fresh frozen config each call,
    # so this leaks nowhere — and without it the clip tests write real files
    # into `engine/data/clips/weapons/`, where the retention sweep and an
    # operator's own recordings live. A test must never touch that.
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")

    store = LiveStore(config, registry, cameras=camera_store,
                      weapon_scenes=scene_store, **kw)
    return store


@pytest.fixture
def store_and_cameras(tmp_path, scenes):
    cameras = CameraStore(tmp_path / "cameras.db")
    cameras.add("cam-a", "Main entrance", "webcam:0", features=("counting",))
    cameras.add("cam-b", "Back door", "webcam:1", features=("counting",))
    store = live_store(tmp_path, camera_store=cameras, scene_store=scenes)
    yield store, cameras
    cameras.close()


# ---------------------------------------------------------------------------
# storage — the rows a crash leaves behind
# ---------------------------------------------------------------------------

class TestStorage:
    def test_open_scene_is_closed_on_next_start(self, tmp_path):
        # A killed process leaves a row that says a knife is still in view.
        # Without this the page reports a knife on a camera for ever, and the
        # `recording` clip state promises a video that was never finished.
        database = tmp_path / "weapons.db"
        store = WeaponSceneStore(database)
        scene_id = store.open("cam-a", START, 0.8, "knifebest")
        store.start_clip(scene_id)
        store.close_db()

        restarted = WeaponSceneStore(database)
        assert restarted.close_orphans() == 1

        scene = restarted.get(scene_id)
        assert scene.running is False
        assert scene.end_reason == "shutdown"
        assert scene.clip_state == "failed", "a half-written file is not a clip"
        assert "engine stopped" in scene.clip_reason
        restarted.close_db()

    def test_a_row_is_never_removed(self, scenes):
        # P6-FR-008. The one storage promise the whole feature rests on.
        scene_id = scenes.open("cam-a", START, 0.9, "knifebest")
        scenes.close(scene_id, START + timedelta(seconds=12), "gone")
        assert [s.id for s in scenes.recent(None, None)] == [scene_id]

    def test_peak_confidence_never_drops(self, scenes):
        scene_id = scenes.open("cam-a", START, 0.6, "knifebest")
        scenes.note_confidence(scene_id, 0.9)
        scenes.note_confidence(scene_id, 0.7)
        assert scenes.get(scene_id).peak_confidence == pytest.approx(0.9)


class TestBareStore:
    def test_bare_live_store_returns_no_weapons(self, bare_live_store):
        # Rule 4. Nothing is running, so there is nothing to list — and the
        # capability says why rather than leaving an empty page to imply
        # "no knives seen".
        assert bare_live_store.weapons(None, None) == []

        states = {c.key: c for c in bare_live_store.capabilities()}
        weapons = states["weapons"]
        assert weapons.state.value == "unavailable"
        assert weapons.reason, "an unavailable capability must say why"


# ---------------------------------------------------------------------------
# the model itself — the only test that touches the real weights
# ---------------------------------------------------------------------------

class TestModel:
    @pytest.mark.skipif(
        not KNIFE_WEIGHTS.is_file(),
        reason="models/knifebest.pt is not on this machine",
    )
    def test_model_loads_and_finds_nothing_on_grey_and_noise(self):
        # A model that fires on flat grey or on static would make every camera
        # in the school a permanent alarm. Neither image contains a knife, and
        # neither contains a person either — this is the floor, not accuracy.
        from vg.infer.weapons import WeaponDetector

        detector = WeaponDetector()
        grey = np.full((480, 640, 3), 128, dtype=np.uint8)
        noise = np.random.default_rng(0).integers(
            0, 256, (480, 640, 3), dtype=np.uint8)

        assert detector.detect(grey) == []
        assert detector.detect(noise) == []
        assert detector.version == "knifebest"
        assert detector.device in {"cuda", "cpu"}


# ---------------------------------------------------------------------------
# the person gate — what makes this affordable and what removes the furniture
# ---------------------------------------------------------------------------

class TestPersonGate:
    def test_knife_model_is_never_called_with_nobody_in_view(self, scenes):
        # P6-FR-002. The whole cost claim is this line: 208 cameras can carry
        # knife detection only because an empty corridor never reaches the
        # second model. A FakeKnives full of hits proves the gate is the reason
        # nothing was found, not the absence of knives.
        people = FakeDetector(people=0)
        knives = FakeKnives(hits=3)
        ww = worker(scenes, people=people, knives=knives)

        walk(ww, people, knives, [(t / 2, 0, 3) for t in range(5)])

        assert knives.asked == [], "the knife model ran on a frame with nobody in it"
        assert scenes.recent(None, None) == []
        assert people.asked, "the person model must still have run"

    def test_a_knife_outside_every_person_box_is_ignored(self, scenes, tmp_path):
        # Research D2's static corner object: a desk edge in the bottom-right
        # that scored over 0.5 in 9 of 120 frames, with somebody sitting at the
        # desk the whole time. "Only when a person is in view" would not have
        # saved it; "on the person" does.
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        for i, at in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]):
            people.boxes = [person(x=0.4, y=0.2, w=0.2, h=0.6)]
            knives.boxes = [knife(x=0.78, y=0.88, w=0.05, h=0.05, confidence=0.9)]
            ww.analyse(frame("cam-a", at=at, sequence=i))

        assert knives.asked, "the knife model should have run — a person was there"
        assert scenes.recent(None, None) == []
        assert recorder.started == []


# ---------------------------------------------------------------------------
# the scene machine — candidate, open, extend, close
# ---------------------------------------------------------------------------

class TestSceneMachine:
    def test_one_sighting_opens_nothing(self, scenes, tmp_path):
        # P6-FR-003. A single frame is how the corner object and a phone in a
        # hand both look. Three sightings over a second is the bar.
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        walk(ww, people, knives, [
            (0.0, 1, 1),
            (0.5, 1, 0),
            (1.0, 1, 0),
            (2.0, 1, 0),
            (5.0, 1, 0),
        ])

        assert scenes.recent(None, None) == []
        assert recorder.started == []

    def test_three_sightings_over_a_second_open_a_scene_and_start_recording(
            self, scenes, tmp_path):
        # P6-FR-003, P6-FR-004, SC-001.
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        for i, (at, conf) in enumerate([(0.0, 0.6), (0.5, 0.9), (1.0, 0.7)]):
            people.boxes = [person()]
            knives.boxes = [knife(confidence=conf)]
            ww.analyse(frame("cam-a", at=at, sequence=i))

        logged = scenes.recent(None, None)
        assert len(logged) == 1
        scene = logged[0]
        assert scene.camera_id == "cam-a"
        assert scene.running is True
        assert scene.clip_state == "recording"
        assert scene.peak_confidence == pytest.approx(0.9), "peak, not last"
        assert scene.model_version == "knifebest"
        assert recorder.started == ["cam-a"]

    def test_entry_time_is_the_first_sighting_not_the_third(self, scenes, tmp_path):
        # P6-FR-003. An operator opening the clip should watch the knife
        # arrive, not find it already in shot.
        people = FakeDetector()
        knives = FakeKnives()
        ww = worker(scenes, people=people, knives=knives,
                    recorder=FakeRecorder(tmp_path / "clips"))

        walk(ww, people, knives, [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)])

        scene = scenes.recent(None, None)[0]
        assert scene.started_at == START
        assert scene.started_at != START + timedelta(seconds=1.0)

    def test_flicker_under_ten_seconds_is_one_scene(self, scenes, tmp_path):
        # P6-FR-004 and SC-002 — the test that decides whether this feels
        # solid. A knife is lost by the detector far more often than a body is:
        # a hand turns, a sleeve covers it. Ten seconds of nothing is the bar,
        # and 9.5 s must not split one incident into two entries.
        people = FakeDetector()
        knives = FakeKnives()
        ww = worker(scenes, people=people, knives=knives,
                    recorder=FakeRecorder(tmp_path / "clips"))

        script = [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)]
        # Nothing at all from 1.0 s to 10.5 s — a 9.5 second gap.
        script += [(t / 2, 1, 0) for t in range(3, 21)]
        script += [(10.5, 1, 1)]
        walk(ww, people, knives, script)

        logged = scenes.recent(None, None)
        assert len(logged) == 1, "a blink must not become a second entry"
        assert logged[0].running is True

    def test_ten_seconds_without_a_knife_closes_and_saves(self, scenes, tmp_path):
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        script = [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)]
        script += [(1.0 + t / 2, 1, 0) for t in range(1, 22)]  # out to 11.5 s
        walk(ww, people, knives, script)

        scene = scenes.recent(None, None)[0]
        assert scene.running is False
        assert scene.end_reason == "gone"
        assert scene.clip_state == "saved"
        assert recorder.stopped == ["cam-a"]
        assert scene.clip_path.is_file()

    def test_scene_is_cut_at_two_minutes_and_a_knife_still_there_reopens(
            self, scenes, tmp_path):
        people = FakeDetector()
        knives = FakeKnives()
        ww = worker(scenes, people=people, knives=knives,
                    recorder=FakeRecorder(tmp_path / "clips"))

        walk(ww, people, knives, [(t / 2, 1, 1) for t in range(251)])  # 125 s

        logged = scenes.recent(None, None)
        assert len(logged) == 2, "cut at the limit, and still holding it"
        newest, oldest = logged
        assert oldest.end_reason == "limit"
        assert oldest.started_at == START
        assert newest.running is True
        assert newest.started_at == oldest.ended_at, "the second starts where the first was cut"

    def test_the_measured_false_hit_sequences_never_form_a_scene(
            self, scenes, tmp_path):
        # SC-003. Research D2, replayed at 5 Hz: the runs actually measured on
        # the two recorded clips, which contain no knife at all. The long runs
        # are the corner object, outside the person's box; the two singles are
        # the only hits that landed on a person, four seconds apart.
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        outside = knife(x=0.78, y=0.88, w=0.05, h=0.05, confidence=0.9)
        step = 0.2  # 5 Hz
        at = 0.0
        sequence = 0

        for run in (1, 5, 1, 1, 1):
            for _ in range(run):
                people.boxes = [person()]
                knives.boxes = [outside]
                ww.analyse(frame("cam-a", at=at, sequence=sequence))
                at += step
                sequence += 1
            # a quiet second between runs
            for _ in range(5):
                people.boxes = [person()]
                knives.boxes = []
                ww.analyse(frame("cam-a", at=at, sequence=sequence))
                at += step
                sequence += 1

        # The two hits that were genuinely on a person, four seconds apart.
        for gap in (0.0, 4.0):
            people.boxes = [person()]
            knives.boxes = [knife(confidence=0.9)]
            ww.analyse(frame("cam-a", at=at + gap, sequence=sequence))
            sequence += 1

        assert scenes.recent(None, None) == [], "neither recorded clip may raise a knife"
        assert recorder.started == []


# ---------------------------------------------------------------------------
# recording failures — a scene without a video still says what happened
# ---------------------------------------------------------------------------

class TestRecording:
    def test_recorder_busy_logs_the_scene_without_a_video(
            self, scenes, tmp_path, store_and_cameras):
        # Rule 4. The incident happened whether or not a file was written, and
        # the entry says why there is nothing to watch rather than offering a
        # button that does nothing.
        from vg.features.weapons import BUSY_REASON

        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips", already=True)
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        walk(ww, people, knives, [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)])

        scene = scenes.recent(None, None)[0]
        assert scene.clip_state == "failed"
        assert scene.clip_reason == BUSY_REASON

        store, _ = store_and_cameras
        entry = store.weapons(None, None)[0]
        assert entry.clip is None, "no file, no clip on the wire"
        assert entry.clip_reason == BUSY_REASON

    def test_the_box_survives_a_blink_so_it_can_actually_be_seen(
            self, scenes, tmp_path):
        # The overlay is read from the LAST ANALYSED FRAME. The knife model is
        # intermittent by nature — that is the whole reason GAP_SECONDS is ten
        # seconds and not one — so on most analysed frames it finds nothing
        # even while somebody is plainly holding a knife.
        #
        # Reading the instantaneous frame therefore draws a box for one 200 ms
        # analysis tick and nothing in between, which at 5 Hz is invisible to a
        # person: the entry appears in the list and the picture stays bare.
        # Reported by the owner, 22 Aug 2026.
        people = FakeDetector()
        knives = FakeKnives()
        ww = worker(scenes, people=people, knives=knives,
                    recorder=FakeRecorder(tmp_path / "clips"))

        # Three hits open a scene. The model fires on the third frame.
        walk(ww, people, knives, [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)])
        assert ww.knives_on("cam-a"), "a box on the frame the model fired"

        # The very next frame: person still there, model blinks. The scene is
        # still open and the list still shows the entry — so the picture must
        # not go blank.
        walk(ww, people, knives, [(1.2, 1, 0)])
        assert ww.knives_on("cam-a"), "the box vanished on the next frame"

        # It must not be held for ever, though. A box a person can no longer
        # justify is worse than no box.
        walk(ww, people, knives, [(1.2 + OVERLAY_HOLD_SECONDS + 0.1, 1, 0)])
        assert ww.knives_on("cam-a") == [], "a stale box is a false claim"

    def test_shutdown_closes_the_open_scene(self, scenes, tmp_path):
        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(tmp_path / "clips")
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)

        walk(ww, people, knives, [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)])
        ww.close_all("shutdown")

        scene = scenes.recent(None, None)[0]
        assert scene.running is False
        assert scene.end_reason == "shutdown"
        assert recorder.stopped == ["cam-a"]


# ---------------------------------------------------------------------------
# the overlay — rule 1 and rule 3, on the page most likely to break them
# ---------------------------------------------------------------------------

class TestOverlay:
    def test_weapons_overlay_carries_no_name_even_when_a_face_is_matched(
            self, tmp_path, scenes):
        # P6-FR-012, rules 1 and 3. `_boxes` sent everything it did not
        # recognise to the face overlay, weapons included — so this page would
        # have drawn somebody's name next to a knife the recogniser never
        # associated with them. The worst possible sentence to put on a screen.
        class FakeWeaponsWorker:
            def knives_on(self, camera_id):
                return [knife(confidence=0.82)] if camera_id == "cam-a" else []

            def serves(self, camera_id):
                return True

        class NamedFace:
            """What `_face_boxes` actually reads — a matched, named face."""

            x, y, w, h = 0.42, 0.22, 0.1, 0.12
            label = "Mohamed Fouad"
            score = 0.91
            identified = True

        class FakeRecogniser:
            def faces_on(self, camera_id):
                return [NamedFace()]

        store = live_store(tmp_path, scene_store=scenes,
                           weapons=FakeWeaponsWorker(),
                           recogniser=FakeRecogniser())

        boxes = store.overlay("cam-a", "weapons")
        assert len(boxes) == 1
        box = boxes[0]
        assert box.kind == "weapon"
        assert box.label == "Knife"
        assert box.match == S.MatchKind.NONE, "a knife is not an identity"
        assert box.severity == S.Severity.CRITICAL
        assert box.track_id is None
        assert box.confidence == pytest.approx(0.82)

        # No name reached the knife overlay, even though the recogniser is
        # naming a face on this very camera in this very frame.
        assert all("Mohamed" not in (b.label or "") for b in boxes)

        # The attendance overlay is untouched — each feature draws its own,
        # and that page still gets the name it is asking for (rule 3).
        faces = store.overlay("cam-a", "attendance")
        assert [f.label for f in faces] == ["Mohamed Fouad"]
        assert faces[0].match is S.MatchKind.FACE


    def test_a_real_worker_puts_a_red_knife_box_on_the_page(
            self, tmp_path, scenes):
        # The end-to-end overlay test, and the one that was missing.
        #
        # `test_weapons_overlay_carries_no_name_even_when_a_face_is_matched`
        # proves _knife_boxes maps correctly, but it hands LiveStore a FAKE
        # worker whose knives_on always returns a knife. Every link between the
        # real worker and the page was therefore untested, and the overlay
        # shipped invisible: the model blinks, knives_on read only the current
        # frame, and the box existed for one analysis tick at a time.
        #
        # This drives a REAL WeaponsWorker and asks the store what it would
        # draw, one frame after the model last fired.
        people = FakeDetector()
        knives = FakeKnives()
        ww = worker(scenes, people=people, knives=knives,
                    recorder=FakeRecorder(tmp_path / "clips"))

        walk(ww, people, knives, [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)])
        # ...and now a frame the model found nothing on, which is the common
        # case while somebody is holding a knife.
        walk(ww, people, knives, [(1.2, 1, 0)])

        store = live_store(tmp_path, scene_store=scenes, weapons=ww)
        boxes = store.overlay("cam-a", "weapons")

        assert len(boxes) == 1, "the page would have shown a bare picture"
        assert boxes[0].kind == "weapon"
        assert boxes[0].label == "Knife"
        assert boxes[0].severity is S.Severity.CRITICAL
        # A camera the worker never saw draws nothing, not another camera's box.
        assert store.overlay("cam-b", "weapons") == []


# ---------------------------------------------------------------------------
# honest states
# ---------------------------------------------------------------------------

class TestHonestStates:
    def _weapons_capability(self, store):
        return {c.key: c for c in store.capabilities()}["weapons"]

    def test_capabilities_says_why_when_knife_detection_is_not_running(
            self, bare_live_store, tmp_path, scenes):
        # P6-FR-011, P6-FR-015. Three failures, three sentences: an operator
        # has to be able to tell "the model would not load" from "nobody
        # switched a camera on", because only one of them is theirs to fix.
        cap = self._weapons_capability(bare_live_store)
        assert cap.state is S.DataState.UNAVAILABLE
        assert "erson detection" in cap.reason

        bare_live_store.weapons_error = "weights not found"
        cap = self._weapons_capability(bare_live_store)
        assert cap.state is S.DataState.UNAVAILABLE
        assert "weights not found" in cap.reason

        class FakeWeaponsWorker:
            cameras = ["cam-a"]
            stats = {"cameras": 1, "last_inference_ms": 14}

            def knives_on(self, camera_id):
                return []

            def serves(self, camera_id):
                return True

        store = live_store(tmp_path, scene_store=scenes,
                           weapons=FakeWeaponsWorker())
        store.weapons_worker.knives = FakeKnives()
        cap = self._weapons_capability(store)
        assert cap.state is S.DataState.LIVE
        assert cap.reason is None

        # And System Health agrees with the capability, on both stores.
        broken = {s.key: s for s in bare_live_store.health().pipeline}["weapons"]
        assert broken.healthy is False
        working = {s.key: s for s in store.health().pipeline}["weapons"]
        assert working.healthy is True

    def test_knife_detection_does_not_change_counting(self, scenes, tmp_path):
        # P6-FR-013, rule 9. The knife worker reads the SAME SharedDetection
        # the people worker holds. If it ran its own pass, or perturbed that
        # cache, switching knife detection on would quietly change the
        # headcount on the Counting page — a feature requiring another feature
        # to behave, which is exactly what rule 9 forbids.
        from vg.infer.shared import SharedDetection

        class _Values(list):
            def tolist(self):
                return list(self)

        class FakeBox:
            """The shape `PersonDetector.people_from` actually reads."""

            def __init__(self, x1, y1, x2, y2, confidence):
                self.xyxy = [_Values([x1, y1, x2, y2])]
                self.conf = [confidence]

        class OneFrameDetector:
            """A PersonDetector stand-in that counts real model calls."""

            device = "cpu"
            version = "fake"

            def __init__(self):
                self.runs = 0

            def raw_boxes(self, image):
                self.runs += 1
                # Two people, in the 4x4 pixel frame the doubles produce.
                return [FakeBox(0, 0, 2, 3, 0.9), FakeBox(2, 0, 4, 3, 0.8)]

        detector = OneFrameDetector()
        shared = SharedDetection(detector)
        f = frame("cam-a", at=0.0, sequence=7)

        # What Counting would report for this frame, with no knife worker.
        without = len(shared.detect(f))

        knives = FakeKnives(hits=0)
        ww = worker(scenes, people=shared, knives=knives)
        ww.analyse(f)

        with_worker = len(shared.detect(f))
        assert without == 2
        assert with_worker == without, "the headcount must not move"
        assert detector.runs == 1, "one frame, one person pass — the cache held"
        assert shared.passes == 1


# ---------------------------------------------------------------------------
# serving the video
# ---------------------------------------------------------------------------

class TestClipEndpoint:
    def test_clip_endpoint_404s_with_a_reason_and_refuses_paths_outside_the_folder(
            self, tmp_path, scenes, authed, monkeypatch):
        # P6-FR-006, rule 4. Every refusal says what happened in words, and
        # none of them is a 500. A row is data like any other: a wrong one must
        # not become a way to read the disk.
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.store import MockStore

        store = live_store(tmp_path, scene_store=scenes)
        root = store.config.storage.weapon_clips_dir
        root.mkdir(parents=True, exist_ok=True)

        app_module.set_store(store)
        app = create_app()
        client = authed(app)

        assert client.get("/weapons/unknown-id/clip").status_code == 404

        failed = scenes.open("cam-a", START, 0.9, "knifebest")
        scenes.fail_clip(failed, "No clip: a recording was already running.")
        response = client.get(f"/weapons/{failed}/clip")
        assert response.status_code == 404
        assert "already running" in response.json()["detail"]

        outside = scenes.open("cam-a", START, 0.9, "knifebest")
        scenes.attach_clip(outside, tmp_path / "elsewhere.mp4")
        (tmp_path / "elsewhere.mp4").write_bytes(b"not really an mp4")
        response = client.get(f"/weapons/{outside}/clip")
        assert response.status_code == 404
        assert "not where it should be" in response.json()["detail"]

        missing = scenes.open("cam-a", START, 0.9, "knifebest")
        scenes.attach_clip(missing, root / "gone.mp4")
        response = client.get(f"/weapons/{missing}/clip")
        assert response.status_code == 404
        assert "no longer on disk" in response.json()["detail"]

        good = scenes.open("cam-a", START, 0.9, "knifebest")
        (root / "there.mp4").write_bytes(b"not really an mp4")
        scenes.attach_clip(good, root / "there.mp4")
        response = client.get(f"/weapons/{good}/clip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"

        app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# the human gate — who decided, recorded before the deciding
# ---------------------------------------------------------------------------

class TestReview:
    @pytest.fixture
    def pending(self, scenes):
        """One finished, unreviewed scene with a video."""
        scene_id = scenes.open("cam-a", START, 0.88, "knifebest")
        scenes.close(scene_id, START + timedelta(seconds=14), "gone")
        return scene_id

    @pytest.fixture
    def app_and_store(self, user_store, tmp_path, scenes):
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.store import MockStore

        store = live_store(tmp_path, scene_store=scenes)
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        yield application, store
        app_module.set_store(MockStore())

    def test_review_records_the_signed_in_user_not_the_body(
            self, scenes, pending, app_and_store, authed):
        # P6-FR-007. The reviewer is the account that pressed the button, not
        # whatever the request body claims. Otherwise anybody with the endpoint
        # can put somebody else's name against a verdict on a knife.
        app, store = app_and_store

        result = store.review_weapon(
            pending,
            S.WeaponReview(verdict=S.ReviewVerdict.CONFIRMED, actor="Mallory"),
            reviewer="Mohamed Fouad",
        )
        assert result is not None
        assert result.reviewed_by == "Mohamed Fouad"
        assert result.reviewed_at is not None
        assert scenes.get(pending).reviewed_by == "Mohamed Fouad"

    def test_the_endpoint_uses_the_session_user(
            self, scenes, pending, app_and_store, authed):
        app, _ = app_and_store
        client = authed(app, role="admin")

        response = client.post(
            f"/weapons/{pending}/review",
            json={"verdict": "confirmed", "actor": "Mallory"},
        )
        assert response.status_code == 200
        assert response.json()["reviewedBy"] == "Test Admin"
        assert scenes.get(pending).reviewed_by == "Test Admin"

    def test_a_review_body_without_an_actor_is_accepted(
            self, scenes, pending, app_and_store, authed):
        # The console stopped sending `actor`. `Wire` forbids unknown fields
        # and `actor` was required, so if the wire had not been widened first
        # every single review would 422.
        app, _ = app_and_store
        client = authed(app)

        response = client.post(
            f"/weapons/{pending}/review",
            json={"verdict": "dismissed", "reason": "a phone"},
        )
        assert response.status_code == 200
        assert response.json()["verdict"] == "dismissed"

    def test_audit_entry_is_written_before_the_verdict(
            self, tmp_path, scenes, pending):
        # Rule 11. The audit entry records that somebody pressed the button,
        # which is true whether or not the write behind it succeeded. Writing
        # it afterwards means a failed write leaves no trace that anybody ever
        # looked at this detection.
        store = live_store(tmp_path, scene_store=scenes)

        def explode(*a, **kw):
            raise RuntimeError("the disk is full")

        store.weapon_scenes.review = explode

        with pytest.raises(RuntimeError):
            store.review_weapon(
                pending,
                S.WeaponReview(verdict=S.ReviewVerdict.CONFIRMED),
                reviewer="Mohamed Fouad",
            )

        entries = [e for e in store.audit(50) if e.subject == pending]
        assert entries, "the attempt left no audit trail at all"
        assert entries[0].action == "weapon.confirmed"
        assert entries[0].actor == "Mohamed Fouad"

    def test_a_second_review_is_refused_with_404(
            self, scenes, pending, app_and_store, authed):
        # A verdict never moves back and is never overwritten. The second
        # caller is told plainly rather than silently replacing the first
        # reviewer's name on a safety decision.
        app, _ = app_and_store
        client = authed(app)

        assert client.post(
            f"/weapons/{pending}/review", json={"verdict": "confirmed"},
        ).status_code == 200

        second = client.post(
            f"/weapons/{pending}/review", json={"verdict": "dismissed"})
        assert second.status_code == 404
        assert "awaiting review" in second.json()["detail"]

        scene = scenes.get(pending)
        assert scene.verdict == "confirmed"
        assert scene.reviewed_by == "Test Admin"

    def test_an_it_support_account_can_review(
            self, scenes, pending, app_and_store, authed):
        # Reviewing is an operator action, not a configuration change. This
        # pins `/weapons` OUT of `ADMIN_WRITE_PREFIXES`: an IT account watching
        # the cameras at night must be able to clear a false alarm.
        app, _ = app_and_store
        response = authed(app, role="it").post(
            f"/weapons/{pending}/review", json={"verdict": "dismissed"})
        assert response.status_code != 403
        assert response.status_code == 200

    def test_dismissed_entries_stay_listed_and_there_is_no_delete_route(
            self, scenes, pending, app_and_store, authed):
        # P6-FR-008. False alarms stay in the history. A page that quietly
        # drops what it got wrong cannot be audited, and there is deliberately
        # no way to remove one.
        app, store = app_and_store
        client = authed(app)

        client.post(f"/weapons/{pending}/review",
                    json={"verdict": "dismissed", "reason": "a phone"})

        listed = store.weapons(None, None)
        assert [w.id for w in listed] == [pending]
        assert listed[0].verdict is S.ReviewVerdict.DISMISSED
        assert listed[0].severity is S.Severity.INFO, "cleared, so no longer red"
        assert listed[0].dismissal_reason == "a phone"

        assert client.delete(f"/weapons/{pending}").status_code in (404, 405)


# ---------------------------------------------------------------------------
# periods and retention
# ---------------------------------------------------------------------------

class TestWindows:
    def test_windows_today_yesterday_and_all_use_site_local_days(self):
        # P6-FR-010. "Today" is the SITE's today. A school in Cairo at 00:30
        # local is still on the previous UTC day, so a server-midnight boundary
        # would file last night's entries under this morning.
        from vg.api.app import weapon_window
        from vg.clock import FixedClock

        clock = FixedClock(180)  # UTC+3
        now = datetime.now(timezone.utc)
        midnight = (clock.local(now).replace(hour=0, minute=0, second=0,
                                             microsecond=0)
                    .replace(tzinfo=timezone.utc) - timedelta(minutes=180))

        since, until = weapon_window("Today", clock, "")
        assert since == midnight
        assert until is None

        since, until = weapon_window("Yesterday", clock, "")
        assert since == midnight - timedelta(days=1)
        assert until == midnight

        since, until = weapon_window("Last 7 days", clock, "")
        assert until is None
        assert abs((now - since).total_seconds() - 7 * 86400) < 5

        since, until = weapon_window("All", clock, "")
        assert (since, until) == (None, None)

    def test_this_school_year_uses_the_configured_term_start(self):
        from vg.api.app import weapon_window
        from vg.clock import FixedClock

        clock = FixedClock(180)
        since, until = weapon_window("This school year", clock, "2025-09-01")
        assert until is None
        # Local midnight on 1 September, expressed as an instant.
        assert since == datetime(2025, 8, 31, 21, 0, tzinfo=timezone.utc)

        # Unset falls back to a rolling year rather than to the epoch: a site
        # that never filled in the term date should see a plausible year, not
        # every row there has ever been under a label that says "this year".
        now = datetime.now(timezone.utc)
        since, until = weapon_window("This school year", clock, "")
        assert until is None
        assert abs((now - since).total_seconds() - 365 * 86400) < 5

    def test_unknown_window_is_422_naming_the_allowed_ones(
            self, tmp_path, scenes, user_store, authed):
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.store import MockStore

        store = live_store(tmp_path, scene_store=scenes)
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        client = authed(application)

        response = client.get("/weapons/detections", params={"window": "Last century"})
        assert response.status_code == 422
        detail = str(response.json()["detail"])
        for label in ("Today", "Yesterday", "Last 7 days", "Last 30 days",
                      "Last 90 days", "This school year", "All"):
            assert label in detail

        app_module.set_store(MockStore())

    def test_a_window_actually_narrows_the_list(self, tmp_path, scenes):
        # The bounds are not decoration: an entry outside them is not returned.
        store = live_store(tmp_path, scene_store=scenes)
        old = scenes.open("cam-a", START - timedelta(days=40), 0.9, "knifebest")
        recent = scenes.open("cam-a", START, 0.9, "knifebest")

        everything = [w.id for w in store.weapons(None, None)]
        assert set(everything) == {old, recent}

        narrowed = [w.id for w in store.weapons(
            datetime.now(timezone.utc) - timedelta(days=30), None)]
        assert narrowed == [recent]


class TestRetention:
    def test_videos_older_than_retention_expire_but_rows_stay(
            self, scenes, tmp_path):
        # P6-FR-009, SC-007. The video goes; the entry never does. A school
        # keeping the record of what it looked at, long after the footage is
        # gone, is the whole difference between a log and a rumour.
        clips = tmp_path / "clips"
        clips.mkdir()

        old_file = clips / "old.mp4"
        old_file.write_bytes(b"not really an mp4")
        old = scenes.open("cam-a", START - timedelta(days=31), 0.9, "knifebest")
        scenes.close(old, START - timedelta(days=31) + timedelta(seconds=10), "gone")
        scenes.attach_clip(old, old_file)

        young_file = clips / "young.mp4"
        young_file.write_bytes(b"not really an mp4")
        young = scenes.open("cam-a", START - timedelta(days=29), 0.9, "knifebest")
        scenes.close(young, START - timedelta(days=29) + timedelta(seconds=10), "gone")
        scenes.attach_clip(young, young_file)

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        assert scenes.expire(cutoff) == 1

        assert not old_file.exists(), "the video should be gone"
        assert young_file.exists(), "the young one is untouched"

        rows = {s.id: s for s in scenes.recent(None, None)}
        assert set(rows) == {old, young}, "no row is ever removed"
        assert rows[old].clip_state == "expired"
        assert rows[old].clip_path is None
        assert "no longer kept" in rows[old].clip_reason
        assert rows[young].clip_state == "saved"

        # Running it again finds nothing new to do.
        assert scenes.expire(cutoff) == 0

    def test_the_row_says_expired_even_when_the_file_cannot_be_deleted(
            self, scenes, tmp_path, monkeypatch):
        # Mark, then unlink. A locked file — Windows, an open player, a
        # network share — must not leave a row promising a video that the
        # sweep has already decided to remove.
        from vg.events import weapons as weapons_events

        clips = tmp_path / "clips"
        clips.mkdir()
        path = clips / "stuck.mp4"
        path.write_bytes(b"not really an mp4")

        scene_id = scenes.open("cam-a", START - timedelta(days=31), 0.9, "knifebest")
        scenes.attach_clip(scene_id, path)

        def refuse(_path, missing_ok=False):
            raise OSError("the file is locked")

        monkeypatch.setattr(Path, "unlink", refuse)

        assert scenes.expire(datetime.now(timezone.utc) - timedelta(days=30)) == 1
        scene = scenes.get(scene_id)
        assert scene.clip_state == "expired", "marked before the unlink was tried"
        assert scene.clip_path is None
        assert weapons_events.EXPIRED_REASON in scene.clip_reason

    def test_a_new_video_saving_sweeps_the_old_ones(self, scenes, tmp_path):
        # The only sweep that needs nobody to be looking. An engine running for
        # months with the console shut would otherwise keep every video it ever
        # wrote — and the retention period is a promise to the people on
        # camera, not a feature of the page.
        clips = tmp_path / "clips"
        clips.mkdir()
        stale = clips / "stale.mp4"
        stale.write_bytes(b"not really an mp4")
        old = scenes.open("cam-a", START - timedelta(days=31), 0.9, "knifebest")
        scenes.attach_clip(old, stale)

        people = FakeDetector()
        knives = FakeKnives()
        recorder = FakeRecorder(clips)
        ww = worker(scenes, people=people, knives=knives, recorder=recorder)
        ww.retention_days = 30

        script = [(0.0, 1, 1), (0.5, 1, 1), (1.0, 1, 1)]
        script += [(1.0 + t / 2, 1, 0) for t in range(1, 22)]
        walk(ww, people, knives, script)

        assert not stale.exists(), "the old video should have gone with the new save"
        rows = {s.id: s for s in scenes.recent(None, None)}
        assert rows[old].clip_state == "expired", "the row stays, the file goes"

    def test_an_expired_entry_offers_no_video_and_says_why(
            self, tmp_path, scenes):
        # Rule 4: no dead button. The wire carries no clip and a sentence in
        # its place, and the endpoint refuses with the same words.
        store = live_store(tmp_path, scene_store=scenes)
        root = store.config.storage.weapon_clips_dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / "expired.mp4"
        path.write_bytes(b"not really an mp4")

        scene_id = scenes.open("cam-a", START - timedelta(days=31), 0.9, "knifebest")
        scenes.close(scene_id, START - timedelta(days=31) + timedelta(seconds=9), "gone")
        scenes.attach_clip(scene_id, path)
        scenes.expire(datetime.now(timezone.utc) - timedelta(days=30))

        entry = [w for w in store.weapons(None, None) if w.id == scene_id][0]
        assert entry.clip is None
        assert entry.clip_state == "expired"
        assert "no longer kept" in entry.clip_reason

        _path, reason = store.clip_for_weapon(scene_id)
        assert _path is None
        assert "no longer kept" in reason
