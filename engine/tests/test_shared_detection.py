"""One detection pass per camera per frame, and one thread inside the model.

P1-01, closing finding F2. A camera with both `counting` and `track` used to
run the person model twice on the same frame, from two threads, against one
shared model instance. Two separate faults:

  - half the GPU spent on that camera recomputing a number already in hand
  - two threads inside a model that is not documented as thread-safe, whose
    failure mode is not a crash but boxes from the wrong frame

`docs/PLAN.md` says P1 is done when "a call-count test proves one detection
pass; no two threads enter the model at once". Both are here.

The detector is a fake that counts calls and, for the concurrency test,
deliberately sleeps inside the call so overlapping threads would be caught. A
real model would make these tests slow, GPU-dependent, and no more convincing:
what is being checked is the sharing logic, not the weights.
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
    return FakeFrame(camera, sequence, np.zeros((48, 64, 3), dtype=np.uint8))


class FakeBox:
    """The two attributes `PersonDetector.people_from` reads off a box.

    Ultralytics returns tensors; these are the same shape in numpy, which is
    all the conversion touches.
    """

    def __init__(self, call: int) -> None:
        self.call = call
        self.xyxy = np.array([[8.0, 8.0, 24.0, 40.0]])
        self.conf = np.array([0.9])


class CountingDetector:
    """Counts model calls, and notices if two threads are ever inside one."""

    device = "cpu"
    version = "fake"
    weights = Path("fake.pt")

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.max_concurrent = 0
        self._inside = 0
        self._lock = threading.Lock()

    def raw_boxes(self, image):
        with self._lock:
            self._inside += 1
            self.max_concurrent = max(self.max_concurrent, self._inside)
            self.calls += 1
            call = self.calls
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self._inside -= 1
        # A distinct list per call, so a test can tell a shared answer from a
        # recomputed one by identity rather than by equality.
        return [FakeBox(call)]


# ---------------------------------------------------------------------------
# one pass per frame
# ---------------------------------------------------------------------------

class TestOnePassPerFrame:
    def test_two_features_on_one_frame_cost_one_pass(self):
        """The whole point. Counting and tracking, same frame, one call."""
        detector = CountingDetector()
        shared = SharedDetection(detector)
        f = frame()

        shared.raw_boxes(f)   # tracking
        shared.detect(f)      # counting

        assert detector.calls == 1
        assert shared.passes == 1

    def test_the_second_feature_gets_the_same_answer(self):
        """Shared, not merely deduplicated by count.

        Identity, not equality: an equal-but-recomputed result would pass an
        equality check while still having cost a second pass.
        """
        shared = SharedDetection(CountingDetector())
        f = frame()

        first = shared.raw_boxes(f)
        second = shared.raw_boxes(f)

        assert first is second

    def test_a_new_frame_runs_again(self):
        """Caching must not outlive its frame.

        Serving frame 1's boxes for frame 2 would draw people where they were,
        not where they are — a wrong box is worse than a recomputed one.
        """
        detector = CountingDetector()
        shared = SharedDetection(detector)

        shared.raw_boxes(frame(sequence=1))
        shared.raw_boxes(frame(sequence=2))

        assert detector.calls == 2

    def test_cameras_do_not_share_with_each_other(self):
        """Two cameras are two images. Same sequence number means nothing."""
        detector = CountingDetector()
        shared = SharedDetection(detector)

        shared.raw_boxes(frame(camera="cam-1", sequence=7))
        shared.raw_boxes(frame(camera="cam-2", sequence=7))

        assert detector.calls == 2

    def test_an_empty_result_is_cached_too(self):
        """"Nothing here" is an answer, and recomputing it costs the same."""
        class EmptyDetector(CountingDetector):
            def raw_boxes(self, image):
                super().raw_boxes(image)
                return None

        detector = EmptyDetector()
        shared = SharedDetection(detector)
        f = frame()

        assert shared.raw_boxes(f) is None
        assert shared.raw_boxes(f) is None
        assert detector.calls == 1

    def test_detect_returns_people_without_a_second_pass(self):
        """`detect` is `raw_boxes` plus arithmetic, never another call."""
        detector = CountingDetector()
        shared = SharedDetection(detector)
        f = frame()

        shared.detect(f)
        shared.detect(f)
        shared.raw_boxes(f)

        assert detector.calls == 1


# ---------------------------------------------------------------------------
# one thread inside the model
# ---------------------------------------------------------------------------

class TestNoTwoThreadsInTheModel:
    def test_concurrent_features_never_overlap_in_the_model(self):
        """The corruption half of F2.

        The fake sleeps inside the call, so any overlap is observed rather
        than hoped against. Without the model lock this fails reliably.
        """
        detector = CountingDetector(delay=0.02)
        shared = SharedDetection(detector)
        frames = [frame(camera=f"cam-{i}", sequence=1) for i in range(6)]

        threads = [
            threading.Thread(target=shared.raw_boxes, args=(f,)) for f in frames
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert detector.max_concurrent == 1, (
            f"{detector.max_concurrent} threads were inside the model at once"
        )

    def test_racing_features_on_one_frame_still_cost_one_pass(self):
        """Two threads, same frame, arriving together.

        This is the real shape of the bug: counting and tracking on one camera
        waking within milliseconds of each other. The double-check inside the
        per-camera lock is what makes the loser reuse rather than recompute.
        """
        detector = CountingDetector(delay=0.05)
        shared = SharedDetection(detector)
        f = frame()
        results = []
        start = threading.Barrier(2)

        def ask():
            start.wait(timeout=5)
            results.append(shared.raw_boxes(f))

        threads = [threading.Thread(target=ask) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert detector.calls == 1, f"{detector.calls} passes for one frame"
        assert results[0] is results[1]

    def test_one_camera_does_not_block_another(self):
        """Per-camera compute locks, not one global queue.

        A slow camera holding every other camera's detection would turn one
        bad stream into a site-wide stall.
        """
        detector = CountingDetector(delay=0.05)
        shared = SharedDetection(detector)
        order: list[str] = []

        def ask(camera: str):
            shared.raw_boxes(frame(camera=camera))
            order.append(camera)

        threads = [threading.Thread(target=ask, args=(f"cam-{i}",)) for i in range(4)]
        started = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        elapsed = time.perf_counter() - started

        assert len(order) == 4
        # Serialised by the model lock, so ~4 x 50ms is expected; the check is
        # that nothing deadlocked or waited far longer than the work took.
        assert elapsed < 2.0, f"took {elapsed:.2f}s - something is over-locking"


# ---------------------------------------------------------------------------
# no feature holds a model
# ---------------------------------------------------------------------------

class TestFeaturesCannotReachTheModel:
    """"No feature calls the model directly" is the rule P1-01 sets.

    Enforced by reading the source: both workers must go through the frame,
    not the image. `detector.detect(frame.image)` is the old signature and is
    exactly what has to not come back.
    """

    @pytest.mark.parametrize("module", ["people", "tracking"])
    def test_the_worker_asks_with_a_frame_not_an_image(self, module: str):
        source = (Path(__file__).resolve().parents[1] / "vg" / "features"
                  / f"{module}.py").read_text(encoding="utf-8")

        assert "detector.detect(frame.image)" not in source
        assert "detector.raw_boxes(frame.image)" not in source

    def test_app_wraps_the_detector_before_any_worker_sees_it(self):
        """The wrap has to happen at construction.

        If `PersonDetector` is handed to a worker anywhere, that worker can
        call it directly and the guarantee is gone.
        """
        source = (Path(__file__).resolve().parents[1] / "vg" / "api"
                  / "app.py").read_text(encoding="utf-8")

        assert "SharedDetection(PersonDetector(" in source, (
            "app.py must wrap the person detector where it is built"
        )
