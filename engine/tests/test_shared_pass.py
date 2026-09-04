"""The shared person pass is costed once, and waiting for it is not inference.

Counting, intrusion, track and knife detection all read one `SharedDetection`,
cached per (camera, frame): the model runs once however many of them ask.
But each of them still SPENDS the time - the first computes, the rest block on
the per-camera lock until it has - and measured from inside a worker they all
looked like they had run a 13 ms model. System Health added the rows up and
drew a graphics-card bar at 100% over a card the driver had at 18%.

Found 3 Sep 2026, on the first real look at the capacity card.

Two mechanisms are pinned here:

  **Borrowed time.** Every millisecond a thread spends inside `raw_boxes` -
  computing, waiting, or reading the cache - is charged to that thread, and
  a worker subtracts it from its own figure. What is left is what the worker
  itself did.

  **One row for the pass.** `last_pass_ms` is timed around the model call
  alone, and the capacity projection charges it once, at the fastest rate
  any reader runs each camera - never per reader.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import schemas as S  # noqa: E402
from vg.features.base import FeatureWorker  # noqa: E402
from vg.infer.shared import SharedDetection, take_borrowed_ms  # noqa: E402


class SlowDetector:
    """A model that takes a known time and returns nothing."""

    device = "cuda:0"
    version = "fake"
    weights = Path("fake.pt")

    def __init__(self, ms: float) -> None:
        self.ms = ms
        self.calls = 0

    def raw_boxes(self, image):
        self.calls += 1
        time.sleep(self.ms / 1000)
        return None

    def raw_boxes_many(self, images):
        return [self.raw_boxes(i) for i in images]


def _frame(camera_id="cam-a", sequence=1):
    return SimpleNamespace(camera_id=camera_id, sequence=sequence, image=None,
                           width=640, height=480,
                           captured_at=datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# the pass, and who pays for it
# ---------------------------------------------------------------------------

class TestBorrowedTime:
    def test_the_pass_is_timed_around_the_model_alone(self):
        shared = SharedDetection(SlowDetector(ms=20))
        shared.raw_boxes(_frame())

        assert shared.last_pass_ms >= 15
        assert shared.passes == 1

    def test_time_in_the_pass_is_charged_to_the_thread_that_spent_it(self):
        shared = SharedDetection(SlowDetector(ms=20))
        take_borrowed_ms()  # clear anything a previous test left

        shared.raw_boxes(_frame())

        borrowed = take_borrowed_ms()
        assert borrowed >= 15
        # Reading resets it. A worker reads once before `analyse` and once
        # after, and the second read must be about THAT frame only.
        assert take_borrowed_ms() == 0.0

    def test_a_cache_hit_is_borrowed_time_but_not_a_pass(self):
        """The second reader of one frame waits or reads the cache. Either
        way it spent time it did not compute, and that time is borrowed -
        never counted as a second model run."""
        detector = SlowDetector(ms=20)
        shared = SharedDetection(detector)
        frame = _frame()

        shared.raw_boxes(frame)
        first_pass = shared.last_pass_ms
        take_borrowed_ms()

        shared.raw_boxes(frame)

        assert detector.calls == 1
        assert shared.passes == 1
        assert shared.last_pass_ms == first_pass
        # Charged for the trip, cheap as it was.
        assert take_borrowed_ms() < 15

    def test_a_worker_blocked_behind_another_is_charged_the_wait(self):
        """The bug's exact shape: worker B arrives while A is mid-pass, waits
        on the per-camera lock, gets A's answer. B spent ~20 ms and ran no
        model. That 20 ms is borrowed, so B's own figure stays near zero."""
        shared = SharedDetection(SlowDetector(ms=40))
        frame = _frame()
        seen: dict[str, float] = {}

        def reader(name: str, delay: float) -> None:
            time.sleep(delay)
            take_borrowed_ms()
            shared.raw_boxes(frame)
            seen[name] = take_borrowed_ms()

        a = threading.Thread(target=reader, args=("a", 0.0))
        b = threading.Thread(target=reader, args=("b", 0.01))
        a.start(); b.start(); a.join(); b.join()

        assert shared.passes == 1
        assert seen["a"] >= 30
        # B waited most of A's pass. Without borrowed accounting this wait
        # was B's "inference time".
        assert seen["b"] >= 20


# ---------------------------------------------------------------------------
# a worker reports what IT did
# ---------------------------------------------------------------------------

class OneFrameBus:
    """A bus that hands out one frame and then nothing."""

    def __init__(self, frame) -> None:
        self.frame = frame

    def subscribe(self, camera_id, maxsize=1):
        bus = self

        class Sub:
            _frames: list = []
            maxsize = 1
            dropped = 0
            given = False

            def get(self, timeout=0.5):
                if self.given:
                    time.sleep(0.01)
                    return None
                self.given = True
                return bus.frame

        return Sub()

    def unsubscribe(self, subscription) -> None:
        pass


class RidingWorker(FeatureWorker[int]):
    """Reads the shared pass, then does 10 ms of its own work."""

    def __init__(self, bus, shared) -> None:
        super().__init__("riding", bus, ["cam-a"], rate_hz=100.0)
        self.shared = shared

    def analyse(self, frame) -> int:
        self.shared.raw_boxes(frame)
        time.sleep(0.010)
        return 1


class TestAWorkerReportsItsOwnTime:
    def test_the_shared_pass_is_subtracted_from_inference(self):
        shared = SharedDetection(SlowDetector(ms=40))
        worker = RidingWorker(OneFrameBus(_frame()), shared)

        worker.start()
        # Read BEFORE stop: a camera thread drops its result in `_closing`
        # on the way out, so anything read after `stop()` is None by design.
        result = None
        stats = None
        deadline = time.monotonic() + 3.0
        while result is None and time.monotonic() < deadline:
            result = worker.result("cam-a")
            if result is not None:
                stats = worker.stats
            time.sleep(0.01)
        worker.stop()

        assert result is not None, "the worker never analysed the frame"
        # ~40 ms borrowed, ~10 ms own. Before this, inference_ms was ~50.
        assert result.shared_ms >= 30
        assert result.inference_ms < 30
        assert stats["last_shared_ms"] >= 30
        assert stats["last_inference_ms"] < 30


# ---------------------------------------------------------------------------
# the capacity card charges the pass once
# ---------------------------------------------------------------------------

class Reader:
    """A person-pass reader as the capacity projection sees it."""

    def __init__(self, name, cameras, rates, *, own_ms=2.0, device="cpu",
                 detector=None, restricted=None):
        self.name = name
        self.cameras = list(cameras)
        self._rates = dict(rates)
        self.detector = detector
        # Only a zones worker has `restricted()`. Giving every reader one
        # would make the projection think counting and track also skip
        # unrestricted cameras, which they do not.
        if restricted is not None:
            self.restricted = lambda: set(restricted)
        self._stats = {
            "name": name, "cameras": len(cameras),
            "frames_per_second": sum(rates.values()),
            "last_inference_ms": own_ms, "last_shared_ms": 13.0,
            "device": device, "queue_depth": 0, "queue_max": 1,
            "frames_dropped": 0, "frames_processed": 5,
        }

    def rate_for(self, camera_id):
        return self._rates[camera_id]

    @property
    def stats(self):
        return dict(self._stats)


def _detector(last_pass_ms=13.0, device="cuda:0"):
    return SimpleNamespace(last_pass_ms=last_pass_ms, device=device)


def _row(capacity, name):
    return next((r for r in capacity.rows if r.name == name), None)


class TestThePassIsChargedOnce:
    def test_one_row_for_the_pass_however_many_read_it(self, bare_live_store):
        det = _detector()
        bare_live_store.people_worker = Reader(
            "people", ["cam-a"], {"cam-a": 5.0}, own_ms=1.0, detector=det)
        bare_live_store.tracking = Reader(
            "tracking", ["cam-a"], {"cam-a": 5.0}, own_ms=2.0, detector=det)

        capacity = bare_live_store.health().capacity
        shared = [r for r in capacity.rows if r.shared]
        assert len(shared) == 1
        row = shared[0]
        assert row.name == "person detection"
        assert row.ms_per_frame == pytest.approx(13.0)
        assert row.measured is True
        # 5/sec on one camera, once - not 10.
        assert row.frames_per_second == pytest.approx(5.0)
        assert row.ms_per_second == pytest.approx(65.0)

    def test_readers_rows_are_their_own_work_only(self, bare_live_store):
        det = _detector()
        bare_live_store.people_worker = Reader(
            "people", ["cam-a"], {"cam-a": 5.0}, own_ms=1.0, detector=det)
        bare_live_store.tracking = Reader(
            "tracking", ["cam-a"], {"cam-a": 5.0}, own_ms=2.0, detector=det)

        capacity = bare_live_store.health().capacity
        assert _row(capacity, "people").ms_per_frame == pytest.approx(1.0)
        assert _row(capacity, "tracking").ms_per_frame == pytest.approx(2.0)
        # The pass is on the GPU; ByteTrack is not. Neither reader's own
        # work lands on the graphics-card budget.
        assert capacity.gpu_ms_per_second == pytest.approx(65.0)
        assert capacity.cpu_ms_per_second == pytest.approx(15.0)

    def test_the_pass_runs_at_the_fastest_reader_per_camera(self, bare_live_store):
        """Two cameras. On cam-a people runs at 2 and tracking at 5; the pass
        runs at 5 there, because tracking's frames are a superset. On cam-b
        only people reads, at 2. Total 7 - not 9, not 4."""
        det = _detector()
        bare_live_store.people_worker = Reader(
            "people", ["cam-a", "cam-b"], {"cam-a": 2.0, "cam-b": 2.0},
            detector=det)
        bare_live_store.tracking = Reader(
            "tracking", ["cam-a"], {"cam-a": 5.0}, detector=det)

        row = [r for r in bare_live_store.health().capacity.rows if r.shared][0]
        assert row.cameras == 2
        assert row.frames_per_second == pytest.approx(7.0)

    def test_zones_only_charges_cameras_that_are_restricted(self, bare_live_store):
        """A zones worker returns before any detection call on a camera
        nobody restricted. Those cameras are not charged for the pass."""
        det = _detector()
        bare_live_store.zones_worker = Reader(
            "zones", ["cam-a", "cam-b"], {"cam-a": 5.0, "cam-b": 5.0},
            detector=det, restricted={"cam-a"})

        row = [r for r in bare_live_store.health().capacity.rows if r.shared][0]
        assert row.cameras == 1
        assert row.frames_per_second == pytest.approx(5.0)

    def test_an_untimed_pass_is_an_estimate_and_says_so(self, bare_live_store):
        bare_live_store.people_worker = Reader(
            "people", ["cam-a"], {"cam-a": 5.0}, detector=_detector(0.0))

        row = [r for r in bare_live_store.health().capacity.rows if r.shared][0]
        assert row.measured is False
        assert row.ms_per_frame == pytest.approx(
            bare_live_store.ASSUMED_MS_PER_FRAME["person detection"])

    def test_no_reader_means_no_pass_row(self, bare_live_store):
        from test_capacity import FakeWorker

        bare_live_store.recogniser = FakeWorker("recognition", device="cpu")
        capacity = bare_live_store.health().capacity
        assert not any(r.shared for r in capacity.rows)

    def test_the_old_flag_is_gone(self):
        """There is nothing left to warn about, so the warning must not
        linger as a field that quietly reads false."""
        assert "shares_person_pass" not in S.Capacity.model_fields
