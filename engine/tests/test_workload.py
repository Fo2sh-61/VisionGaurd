"""Workload placement — removing work nothing reads, changing no answer.

Five changes, and one rule over all of them: **no detection result may
change**. These tests are the part of that rule a machine can check. The other
part is `engine/tools/compare_detections.py`, which replays the labelled clip
and diffs it, because a unit test cannot tell you a face moved four pixels.

What each class here is defending:

  TestPatrolOff        the tier is off by default, and off is not broken
  TestBatching         several waiting frames cost one call, one frame does
                       not wait for company, and nobody gets somebody else's
                       boxes
  TestFaceGating       a face found inside a person crop lands in exactly the
                       same place as one found in the whole frame
  TestIsolation        gating faces behind person detection did not make
                       attendance depend on counting being switched on
  TestReversal         every change comes back by editing config

The batching tests use a fake detector rather than a real model, for the same
reason `test_shared_detection.py` does: what is under test is the sharing
logic, not the weights.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as vgconfig  # noqa: E402
from vg.infer.shared import SharedDetection  # noqa: E402


@dataclass
class FakeFrame:
    """Enough of `ingest.source.Frame` for the sharing logic."""

    camera_id: str
    sequence: int
    image: np.ndarray

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


def frame(camera: str = "cam-1", sequence: int = 1) -> FakeFrame:
    # A distinct fill per camera and sequence, so a batched answer can be
    # traced back to the image it was actually computed from. If a frame ever
    # receives its neighbour's boxes, that is the assertion that catches it.
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:] = (hash((camera, sequence)) % 200) + 1
    return FakeFrame(camera, sequence, image)


class BatchingDetector:
    """Counts calls and records how many images each one carried."""

    device = "cpu"
    version = "fake"
    weights = Path("fake.pt")
    form = "PyTorch CUDA"

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.delay = delay
        self._lock = threading.Lock()

    @staticmethod
    def _answer(image) -> str:
        """A result that names the image it came from.

        The whole batching risk is a frame receiving another frame's boxes.
        Returning something derived from the pixels makes that visible instead
        of plausible.
        """
        return f"boxes-for-{int(image[0][0][0])}"

    def raw_boxes(self, image):
        with self._lock:
            self.calls += 1
            self.batch_sizes.append(1)
        if self.delay:
            time.sleep(self.delay)
        return self._answer(image)

    def raw_boxes_many(self, images):
        with self._lock:
            self.calls += 1
            self.batch_sizes.append(len(images))
        if self.delay:
            time.sleep(self.delay)
        return [self._answer(i) for i in images]


# ---------------------------------------------------------------------------
# change 1 — patrol face recognition off by default
# ---------------------------------------------------------------------------

class TestPatrolOff:
    def test_the_shipped_default_is_off(self):
        """Off is the DEFAULT, not merely a setting the shipped file uses.

        A config with no `tracking:` block at all must also be off, or a fresh
        install quietly pays for the tier this change exists to remove.
        """
        assert vgconfig.TrackingConfig().patrol_hz == 0
        assert vgconfig.TrackingConfig.parse({}, "tracking").patrol_hz == 0

    def test_the_shipped_config_is_off(self):
        assert vgconfig.load().tracking.patrol_hz == 0

    def test_it_still_turns_back_on(self):
        """The reversal. One number, and the tier is back."""
        assert vgconfig.TrackingConfig.parse(
            {"patrol_hz": 0.5}, "tracking").patrol_hz == 0.5

    def test_off_is_not_broken(self):
        """0 is a valid value, not a rejected one.

        The distinction this protects: a validator that refused 0 would turn
        "switched off" into a startup error, which is the opposite of what
        honest degradation means.
        """
        assert vgconfig.TrackingConfig.parse(
            {"patrol_hz": 0}, "tracking").patrol_hz == 0
        with pytest.raises(vgconfig.ConfigError):
            vgconfig.TrackingConfig.parse({"patrol_hz": -1}, "tracking")


# ---------------------------------------------------------------------------
# change 3 — batch the shared person pass
# ---------------------------------------------------------------------------

class TestBatching:
    def test_off_by_default_and_unchanged(self):
        """Batching absent means the old path, exactly."""
        detector = BatchingDetector()
        shared = SharedDetection(detector)
        shared.raw_boxes(frame("cam-1", 1))
        shared.raw_boxes(frame("cam-2", 1))
        assert detector.calls == 2
        assert detector.batch_sizes == [1, 1]

    def test_a_lone_frame_never_waits_for_company(self):
        """P8-FR-011, and the reason there is no batching window.

        Nothing is held back hoping a second frame arrives. One caller, one
        call, no delay - a single-camera site must not pay for a feature that
        only helps a busy one.
        """
        detector = BatchingDetector()
        shared = SharedDetection(detector, batch=True)

        started = time.perf_counter()
        result = shared.raw_boxes(frame("cam-1", 1))
        elapsed = time.perf_counter() - started

        assert detector.calls == 1
        assert detector.batch_sizes == [1]
        assert result is not None
        # Generous, because it is asserting the absence of a wait rather than
        # timing anything: a 50 ms window would show up here as 50 ms.
        assert elapsed < 0.25

    def test_frames_already_waiting_go_together(self):
        """The saving. Several cameras queued behind the model, one call."""
        detector = BatchingDetector(delay=0.15)
        shared = SharedDetection(detector, batch=True)

        results: dict[str, object] = {}
        errors: list[BaseException] = []

        def ask(camera: str) -> None:
            try:
                results[camera] = shared.raw_boxes(frame(camera, 1))
            except BaseException as exc:      # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=ask, args=(f"cam-{i}",))
                   for i in range(1, 5)]
        threads[0].start()
        # Let the first thread take the model lock, so the rest genuinely
        # queue behind it rather than racing to be first.
        time.sleep(0.05)
        for t in threads[1:]:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, errors
        assert len(results) == 4
        # First call carries cam-1 alone; the three that queued behind it are
        # swept into one. Four frames, two calls.
        assert detector.calls == 2
        assert max(detector.batch_sizes) > 1

    def test_every_frame_gets_its_own_boxes(self):
        """The thing that must never break.

        Batching returns results positionally. Get that wrong and one camera
        is drawn with another camera's people - silently, and looking entirely
        plausible. Each fake answer names the image it came from, so a
        crossed wire is an assertion failure rather than a mystery.
        """
        detector = BatchingDetector(delay=0.15)
        shared = SharedDetection(detector, batch=True)

        frames = {f"cam-{i}": frame(f"cam-{i}", 1) for i in range(1, 5)}
        results: dict[str, object] = {}

        def ask(camera: str) -> None:
            results[camera] = shared.raw_boxes(frames[camera])

        threads = [threading.Thread(target=ask, args=(c,)) for c in frames]
        threads[0].start()
        time.sleep(0.05)
        for t in threads[1:]:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        for camera, f in frames.items():
            expected = BatchingDetector._answer(f.image)
            assert results[camera] == expected, (
                f"{camera} received {results[camera]!r}, expected {expected!r} "
                "- a batched result was filed against the wrong frame"
            )

    def test_the_cache_key_is_unchanged(self):
        """Batching is throughput only.

        Two features on one frame still cost one pass, and a second frame from
        the same camera still costs another. That is the `(camera, sequence)`
        contract `SharedDetection` was built on, and batching must not move it.
        """
        detector = BatchingDetector()
        shared = SharedDetection(detector, batch=True)

        f = frame("cam-1", 1)
        first = shared.raw_boxes(f)
        second = shared.raw_boxes(f)          # same frame, another feature
        assert detector.calls == 1
        assert first == second

        shared.raw_boxes(frame("cam-1", 2))   # next frame
        assert detector.calls == 2

    def test_a_model_that_refuses_a_batch_falls_back(self):
        """The one that matters on this machine.

        A TensorRT plan is compiled at a FIXED batch size - 1, as
        `build_engines.py` builds them - and raises when handed three images.
        That exception would be caught per frame by `FeatureWorker` and
        logged, so the visible symptom would be detection quietly stopping on
        a camera. Every frame must still get its own answer.
        """
        class RefusesBatches(BatchingDetector):
            def raw_boxes_many(self, images):
                raise AssertionError(
                    "input size torch.Size([3, 3, 640, 640]) not equal to "
                    "max model size (1, 3, 640, 640)")

        detector = RefusesBatches(delay=0.15)
        shared = SharedDetection(detector, batch=True)

        frames = {f"cam-{i}": frame(f"cam-{i}", 1) for i in range(1, 5)}
        results: dict[str, object] = {}

        def ask(camera: str) -> None:
            results[camera] = shared.raw_boxes(frames[camera])

        threads = [threading.Thread(target=ask, args=(c,)) for c in frames]
        threads[0].start()
        time.sleep(0.05)
        for th in threads[1:]:
            th.start()
        for th in threads:
            th.join(timeout=5.0)

        assert len(results) == 4, "a frame was lost when the batch was refused"
        for camera, f in frames.items():
            assert results[camera] == BatchingDetector._answer(f.image)
        assert shared.batch_unavailable

    def test_a_saving_that_did_not_happen_is_not_reported(self):
        """`passes` reaches System Health.

        Counting trips through the lock rather than model calls would show a
        halved workload on a machine where the model ran just as often - a
        number that looks like a win and is not one.
        """
        class RefusesBatches(BatchingDetector):
            def raw_boxes_many(self, images):
                raise AssertionError("fixed batch size")

        detector = RefusesBatches()
        shared = SharedDetection(detector, batch=True)
        for i in range(1, 5):
            shared.raw_boxes(frame(f"cam-{i}", 1))

        assert shared.passes == detector.calls

    def test_it_reverses_by_config(self):
        """P8-FR-004 for change 3."""
        spec = vgconfig.ModelConfig.parse(
            "person", {"weights": "models/yolov8s.pt", "batch": True}, "models.person")
        assert spec.batch is True
        off = vgconfig.ModelConfig.parse(
            "person", {"weights": "models/yolov8s.pt"}, "models.person")
        assert off.batch is False


# ---------------------------------------------------------------------------
# change 2 — face detection gated to person crops
# ---------------------------------------------------------------------------

class TestFaceGating:
    """The only change in this feature that can move a result.

    Everything here is about one arithmetic mistake: YuNet run on a crop
    returns coordinates relative to THE CROP. Convert those against the full
    frame and every face box lands somewhere wrong - and wrong in a way that
    looks plausible, which is how it would reach a school.
    """

    def test_a_crop_offset_is_added_back(self):
        from vg.infer.faces import DetectedFace

        # A face at (110, 130) in a crop whose top-left is (100, 120) is at
        # (210, 250) in the frame. Not at (110, 130).
        face = DetectedFace(x=110, y=130, w=40, h=50, confidence=0.9,
                            landmarks=np.zeros((5, 2), dtype=np.float32),
                            raw=np.zeros(15, dtype=np.float32))
        moved = face.offset(100, 120)

        assert (moved.x, moved.y) == (210, 250)
        assert (moved.w, moved.h) == (40, 50), "offsetting must not resize"
        assert moved.confidence == face.confidence

    def test_offset_then_fractions_matches_the_ungated_path(self):
        """The equivalence the whole change rests on.

        A face found inside a crop and a face found in the whole frame must
        produce the SAME fractions. If they do not, gating changed a result
        and P8-FR-002 says reject the change.
        """
        from vg.infer.faces import DetectedFace

        raw = np.zeros(15, dtype=np.float32)
        marks = np.zeros((5, 2), dtype=np.float32)
        whole = DetectedFace(x=210, y=250, w=40, h=50, confidence=0.9,
                             landmarks=marks, raw=raw)
        cropped = DetectedFace(x=110, y=130, w=40, h=50, confidence=0.9,
                               landmarks=marks, raw=raw).offset(100, 120)

        assert cropped.to_fractions(640, 480) == whole.to_fractions(640, 480)

    def test_the_landmarks_move_with_the_box(self):
        """`raw` carries the five landmarks SFace aligns on.

        Offsetting the box and leaving the landmarks behind would align every
        crop against points from the wrong part of the picture - which does
        not fail loudly, it just identifies the wrong person.
        """
        from vg.infer.faces import DetectedFace

        raw = np.arange(15, dtype=np.float32)
        moved = DetectedFace(
            x=10, y=20, w=30, h=40, confidence=0.9,
            landmarks=raw[4:14].reshape(5, 2).copy(), raw=raw,
        ).offset(100, 200)

        assert moved.raw[0] == pytest.approx(raw[0] + 100)   # box x
        assert moved.raw[1] == pytest.approx(raw[1] + 200)   # box y
        # Landmarks are (x, y) pairs from index 4 onward.
        assert moved.raw[4] == pytest.approx(raw[4] + 100)
        assert moved.raw[5] == pytest.approx(raw[5] + 200)
        # Width, height and score are not coordinates and must not move.
        assert moved.raw[2] == pytest.approx(raw[2])
        assert moved.raw[3] == pytest.approx(raw[3])
        assert moved.raw[14] == pytest.approx(raw[14])
        # The landmarks field is what the overlay draws the five points from,
        # and it has to move with `raw` or the two disagree.
        assert moved.landmarks[0][0] == pytest.approx(raw[4] + 100)
        assert moved.landmarks[0][1] == pytest.approx(raw[5] + 200)

    def test_a_crop_is_never_resized(self):
        """`tracking.identity.face_px: 80` is a MEASURED pixel floor.

        engine.yaml records why: at 40px the same person scores 0.23-0.48
        against themselves. Scaling a crop silently changes what that floor
        means, and identities change with it.
        """
        from vg.features.recognition import person_crops

        image = np.zeros((480, 640, 3), dtype=np.uint8)
        crops = person_crops(image, [(0.1, 0.2, 0.25, 0.5)], pad=0.0)

        assert len(crops) == 1
        crop, (ox, oy) = crops[0]
        assert (ox, oy) == (64, 96)
        assert crop.shape[:2] == (240, 160), "the crop must be native pixels"

    def test_a_crop_is_padded_so_a_face_is_not_clipped(self):
        """A person box is a BODY box; the head sits at its very top edge.

        Cropping tight to it hands YuNet a face cut off at the eyebrows.
        Padding is not a nicety here - without it the gated path finds fewer
        faces than the ungated one and P8-FR-001 fails.
        """
        from vg.features.recognition import person_crops

        image = np.zeros((480, 640, 3), dtype=np.uint8)
        (_, (ox, oy)), = person_crops(image, [(0.5, 0.5, 0.2, 0.4)], pad=0.1)

        assert ox < int(0.5 * 640)
        assert oy < int(0.5 * 480)

    def test_crops_stay_inside_the_frame(self):
        """A box at the edge must not produce a negative origin.

        Numpy would happily slice from the far side of the image, so this is
        the difference between an edge case and a face box on the wrong wall.
        """
        from vg.features.recognition import person_crops

        image = np.zeros((480, 640, 3), dtype=np.uint8)
        for box in [(0.0, 0.0, 0.2, 0.2), (0.85, 0.85, 0.2, 0.2)]:
            (crop, (ox, oy)), = person_crops(image, [box], pad=0.2)
            assert ox >= 0 and oy >= 0
            assert oy + crop.shape[0] <= 480
            assert ox + crop.shape[1] <= 640
            assert crop.size > 0

    def test_no_people_means_no_face_work(self):
        """The saving itself: an empty frame costs nothing."""
        from vg.features.recognition import person_crops

        image = np.zeros((480, 640, 3), dtype=np.uint8)
        assert person_crops(image, []) == []


# ---------------------------------------------------------------------------
# the rule change 2 must not break
# ---------------------------------------------------------------------------

class TestIsolation:
    """`features/base.py` exists because of the bug this change resembles.

    Its docstring: the first version of this system ran person detection
    inside the recognition worker, so a camera configured for counting alone
    was processed by nothing at all. Features share MODELS, never WORKERS.
    """

    def test_gating_is_off_unless_asked_for(self):
        """Measured, not cautious.

        `--gate-check` finds every face either way, but the boxes land up to
        11 pixels apart because YuNet on a crop is a different computation
        from YuNet on a frame. That moves the landmarks, and the landmarks
        decide which patch gets embedded - so it could move an identity.
        P8-FR-002: unproven means off, not on-by-default.
        """
        camera = vgconfig.CameraConfig.parse({
            "id": "c", "name": "C", "source": "webcam:0",
            "features": ["attendance", "counting"],
        }, "cameras[0]")
        assert camera.gates_faces is False

    def test_attendance_alone_is_not_gated(self):
        """The trap that would have made this change a LOSS.

        engine.yaml records that `[attendance]` alone runs two small models
        and no GPU. Gating there would ADD the person model and a GPU
        dependency to the one camera shape that does not have them - costing
        time rather than saving it.
        """
        camera = vgconfig.CameraConfig.parse({
            "id": "c", "name": "C", "source": "webcam:0",
            "features": ["attendance"],
        }, "cameras[0]")
        assert camera.gates_faces is False

    def test_it_can_still_be_switched_on(self):
        for value, expected in (("person", True), ("frame", False)):
            camera = vgconfig.CameraConfig.parse({
                "id": "c", "name": "C", "source": "webcam:0",
                "features": ["attendance"], "face_gate": value,
            }, "cameras[0]")
            assert camera.gates_faces is expected

    def test_recognition_holds_a_model_not_a_worker(self):
        """The structural guarantee, asserted rather than assumed.

        A `SharedDetection` runs the model itself. A `PeopleWorker` only has
        boxes if somebody switched counting on. Holding the first is sharing
        a model; holding the second is depending on a feature.
        """
        import inspect

        from vg.features.recognition import RecognitionWorker

        parameters = inspect.signature(RecognitionWorker.__init__).parameters
        assert "shared" in parameters
        assert parameters["shared"].default is None, (
            "recognition must start without a detector - a camera with no "
            "person pass still has to recognise faces"
        )

    def test_an_unknown_gate_is_refused_at_startup(self):
        """Not a silent fallback.

        A typo that quietly means "whole frame" is a performance regression
        nobody notices; a typo that stops the engine is one somebody fixes.
        """
        with pytest.raises(vgconfig.ConfigError):
            vgconfig.CameraConfig.parse({
                "id": "c", "name": "C", "source": "webcam:0",
                "face_gate": "peron",
            }, "cameras[0]")


# ---------------------------------------------------------------------------
# what switching patrol off has to admit to
# ---------------------------------------------------------------------------

class TestPatrolOffIsVisible:
    """P8-FR-008. A thinner answer must not pass for a fuller one.

    Patrol off means corridor cameras run no recogniser, so a path comes back
    with fewer NAMED stops. The failure mode is not an error - it is a
    perfectly well-formed answer that is quietly incomplete, and reads
    exactly like a person who was not there. An operator has no way to tell
    the two apart unless the engine says which it is.

    The fact travels; the sentence is built in the console, so it is
    translatable rather than 66 English strings in Python.
    """

    def test_the_answer_says_only_doorways_were_looking(self, bare_live_store):
        from vg.api import schemas as S

        bare_live_store.patrol = None
        assert bare_live_store._name_source() is S.NameSource.IDENTITY

    def test_with_patrol_running_it_says_everywhere(self, bare_live_store):
        from vg.api import schemas as S

        bare_live_store.patrol = object()
        assert bare_live_store._name_source() is S.NameSource.ALL

    def test_the_fact_is_on_the_endpoint_the_console_uses(self):
        """`/track` is RETIRED - the console reads the path skeleton.

        Putting this on TrackResult alone would have been a field nothing
        renders: honest in the engine, invisible on the screen, and the exact
        shape of bug this whole feature is about.
        """
        from vg.api import schemas as S

        assert "names_from" in S.PathSkeleton.model_fields
        assert "names_from" in S.TrackResult.model_fields

    def test_it_is_a_fact_not_a_sentence(self):
        """An enum, so the console can say it in Arabic.

        The engine already ships 65 English sentences to the screen and
        `specs/008-arabic-console` exists to undo that. Adding a 66th would
        be building the debt that spec is being written to pay off.
        """
        from vg.api import schemas as S

        assert set(S.NameSource) == {S.NameSource.ALL, S.NameSource.IDENTITY}
        for member in S.NameSource:
            assert " " not in member.value


# ---------------------------------------------------------------------------
# change 4 — capture rate
# ---------------------------------------------------------------------------

class TestCaptureRate:
    def test_watched_is_the_default_and_always_reverses_it(self):
        camera = vgconfig.CameraConfig.parse(
            {"id": "c", "name": "C", "source": "webcam:0"}, "cameras[0]")
        assert camera.live_capture == "watched"

        always = vgconfig.CameraConfig.parse({
            "id": "c", "name": "C", "source": "webcam:0",
            "live_capture": "always",
        }, "cameras[0]")
        assert always.live_capture == "always"

    def test_an_unknown_value_is_refused_at_startup(self):
        with pytest.raises(vgconfig.ConfigError):
            vgconfig.CameraConfig.parse({
                "id": "c", "name": "C", "source": "webcam:0",
                "live_capture": "sometimes",
            }, "cameras[0]")

    def test_a_watcher_is_counted_and_released(self):
        from vg.ingest.source import CameraSource

        cam = CameraSource("cam-1", "file:nothing.mp4")
        assert cam.watchers == 0
        with cam.watched():
            assert cam.watchers == 1
            with cam.watched():
                assert cam.watchers == 2
            assert cam.watchers == 1
        assert cam.watchers == 0

    def test_a_watcher_is_released_even_when_the_viewer_drops(self):
        """An MJPEG response usually ends by the client disappearing.

        If that path leaked a watcher, one closed browser tab would pin a
        camera at full decode for the life of the process - and the leak
        would be invisible, because nothing is obviously broken.
        """
        from vg.ingest.source import CameraSource

        cam = CameraSource("cam-1", "file:nothing.mp4")
        with pytest.raises(RuntimeError):
            with cam.watched():
                raise RuntimeError("client went away")
        assert cam.watchers == 0

    def test_unwatched_decodes_at_the_analytics_rate(self):
        """The saving, stated as a rule rather than a timing.

        Unwatched: decode at `fps`. Watched: decode everything. Either way
        every frame is GRABBED, which is what keeps the buffer drained.
        """
        from vg.ingest.source import CameraSource

        cam = CameraSource("cam-1", "file:nothing.mp4", target_fps=5.0)
        assert cam.wants_decode(now=0.0) is True       # first frame always
        assert cam.wants_decode(now=0.05) is False     # 20 ms later, skip
        assert cam.wants_decode(now=0.30) is True      # past the interval

    def test_watched_decodes_every_frame(self):
        from vg.ingest.source import CameraSource

        cam = CameraSource("cam-1", "file:nothing.mp4", target_fps=5.0)
        with cam.watched():
            assert cam.wants_decode(now=0.0) is True
            assert cam.wants_decode(now=0.01) is True
            assert cam.wants_decode(now=0.02) is True

    def test_the_grab_loop_does_not_spin(self):
        """The bug that would have made this change a LOSS.

        Grabbing without decoding is only cheap if `grab()` waits for a frame.
        On an RTSP stream it does, so the loop paces itself and the buffer is
        genuinely drained - which is the whole reason for grabbing rather than
        sleeping. On a webcam it can return instantly, and then this loop
        burns a whole core: measured at 658,000 grabs a second on this
        machine, which costs far more than the decodes it saves.

        A hundred cameras each spinning a core is worse than the waste this
        feature exists to remove, and it would not look like a bug - just a
        busy machine.
        """
        from vg.ingest import source as vgsource

        assert vgsource._NONBLOCKING_GRAB_SECONDS > 0
        assert vgsource._IDLE_GRAB_SLEEP > 0
        # Under one frame at 120 fps, so a backend that genuinely blocks for
        # a frame never reaches the sleep.
        assert vgsource._NONBLOCKING_GRAB_SECONDS < 1 / 120

        text = Path(vgsource.__file__).read_text(encoding="utf-8")
        assert "_IDLE_GRAB_SLEEP" in text and "_NONBLOCKING_GRAB_SECONDS" in text, (
            "the grab loop must pace itself when the backend does not"
        )

    def test_always_decodes_every_frame_even_unwatched(self):
        """The reversal for change 4."""
        from vg.ingest.source import CameraSource

        cam = CameraSource("cam-1", "file:nothing.mp4",
                           target_fps=5.0, live_capture="always")
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.01) is True


# ---------------------------------------------------------------------------
# SC-004 — every change comes back by editing config
# ---------------------------------------------------------------------------

class TestReversal:
    """Each change reverses on its own, and reversing one leaves the rest.

    This is the promise that makes the whole feature safe to deploy: if
    something misbehaves on site, an operator edits a file and restarts
    rather than waiting for a build. A reversal that only works when the
    others are also reverted is not a reversal.
    """

    @staticmethod
    def _camera(**extra):
        raw = {"id": "c", "name": "C", "source": "webcam:0",
               "features": ["attendance", "counting"]}
        raw.update(extra)
        return vgconfig.CameraConfig.parse(raw, "cameras[0]")

    def test_all_four_keys_reverse_independently(self):
        # Everything switched on.
        on_camera = self._camera(face_gate="person", live_capture="watched")
        on_person = vgconfig.ModelConfig.parse(
            "person", {"weights": "models/yolov8s.pt", "batch": True},
            "models.person")
        on_patrol = vgconfig.TrackingConfig.parse({"patrol_hz": 0.5}, "tracking")

        assert on_camera.gates_faces is True
        assert on_camera.live_capture == "watched"
        assert on_person.batch is True
        assert on_patrol.patrol_hz == 0.5

        # Reverse ONE - face gating - and check the other three are untouched.
        off_gate = self._camera(face_gate="frame", live_capture="watched")
        assert off_gate.gates_faces is False
        assert off_gate.live_capture == "watched", (
            "reversing face gating disturbed capture"
        )
        assert on_person.batch is True
        assert on_patrol.patrol_hz == 0.5

        # Reverse capture only.
        off_capture = self._camera(face_gate="person", live_capture="always")
        assert off_capture.live_capture == "always"
        assert off_capture.gates_faces is True, (
            "reversing capture disturbed face gating"
        )

    def test_an_untouched_config_reproduces_todays_behaviour(self):
        """An existing engine.yaml must upgrade without being edited.

        The one intended exception is patrol, which this feature deliberately
        changes the default of. Everything else must be as it was.
        """
        plain = self._camera()
        assert plain.gates_faces is False      # whole frame, as before
        assert plain.live_capture == "watched"

        model = vgconfig.ModelConfig.parse(
            "person", {"weights": "models/yolov8s.pt"}, "models.person")
        assert model.batch is False            # one frame at a time, as before
        assert model.accelerate is True        # TensorRT still preferred

    def test_the_shipped_config_is_valid(self):
        """The file that actually ships, parsed."""
        cfg = vgconfig.load()
        assert cfg.tracking.patrol_hz == 0
        assert cfg.models["bags"].accelerate is True, (
            "the bag TensorRT engine measured FASTER on p95 - 23.3 ms against "
            "29.0 - so the spec's 'free 31%' was wrong and this stays on"
        )
        for camera in cfg.cameras:
            assert camera.live_capture in vgconfig.LIVE_CAPTURE
            assert camera.face_gate in vgconfig.FACE_GATES

