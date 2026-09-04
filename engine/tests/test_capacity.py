"""The analytics rate is real, and the machine says how full it is.

Two bugs are pinned here, and they are the same bug seen from two ends.

**The rate was a stored number, not a setting.** Every worker was built with
one rate — `min(fps)` across its cameras, fixed at construction — so turning
one camera down to 2/sec quietly turned every other camera on that worker
down with it, and editing the rate in the console changed the *decode* rate
and nothing else. The models carried on at the old rate until somebody
restarted the engine, and nothing anywhere said so.

**Nothing said what the configuration cost.** The wall was found by hitting
it: the engine fell behind and System Health reported that afterwards. A
projection is what lets somebody see it coming — and a projection is exactly
the kind of number that turns into a confident fiction if it is not built
carefully, which is what most of the tests below are about.

The rules the projection has to keep:

  **Say which figures were measured.** A cost timed on this machine and one
  carried in from an earlier run must never look alike (Principle III).

  **Never add GPU and CPU.** Face recognition is OpenCV with no CUDA path.
  Its milliseconds and the person detector's are not the same milliseconds,
  and one combined percentage would be a percentage of nothing.

  **A worker that did not say which processor it uses is placed in neither
  budget.** Guessing makes both totals wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import schemas as S  # noqa: E402
from vg.features.base import FeatureWorker  # noqa: E402


class CountingWorker(FeatureWorker[int]):
    """The smallest real worker. Never started, so no bus is touched."""

    def analyse(self, frame):  # pragma: no cover - never runs in these tests
        return 1


def _worker(cameras, rate_hz=5.0) -> CountingWorker:
    return CountingWorker("people", bus=None, cameras=list(cameras),
                          rate_hz=rate_hz)


# ---------------------------------------------------------------------------
# the rate belongs to the camera
# ---------------------------------------------------------------------------

class TestPerCameraRate:
    def test_one_camera_turned_down_leaves_the_others_alone(self):
        """The regression. `min(fps)` used to apply to every camera.

        An operator turning the corridor camera down to 2/sec had no way to
        know they had just turned the entrance down too.
        """
        worker = _worker(["cam-a", "cam-b"], rate_hz=5.0)
        worker.set_rate("cam-a", 2.0)

        assert worker.rate_for("cam-a") == 2.0
        assert worker.rate_for("cam-b") == 5.0

    def test_a_camera_nobody_set_falls_back_to_the_workers_rate(self):
        """Absence is not zero. A camera with no rate of its own keeps the
        one the worker was constructed with, which is what happened before
        per-camera rates existed."""
        worker = _worker(["cam-a"], rate_hz=4.0)
        assert worker.rate_for("cam-a") == pytest.approx(4.0)

    def test_the_interval_the_loop_uses_follows_the_camera(self):
        """`rate_for` reporting one number while the loop used another would
        be worse than no setting at all — the page would be honest about a
        rate nothing ran at."""
        worker = _worker(["cam-a", "cam-b"], rate_hz=5.0)
        worker.set_rate("cam-a", 2.0)

        assert worker._interval_for("cam-a") == pytest.approx(0.5)
        assert worker._interval_for("cam-b") == pytest.approx(0.2)

    def test_a_boost_still_wins_while_somebody_is_watching(self):
        """The per-camera rate must not break the demand boost. A tile
        somebody has open runs faster than its configured rate, and that is
        the one case where the configured number is deliberately ignored."""
        worker = _worker(["cam-a"], rate_hz=5.0)
        worker.set_rate("cam-a", 1.0)
        worker.note_interest("cam-a")

        assert worker._interval_for("cam-a") == pytest.approx(worker.boost_interval)

    def test_zero_is_refused_rather_than_meaning_every_frame(self):
        """Filling a machine is a decision, never an accident. A rate of 0
        read as "as fast as possible" is how one camera eats a whole GPU."""
        worker = _worker(["cam-a"])
        with pytest.raises(ValueError):
            worker.set_rate("cam-a", 0)

    def test_the_load_a_worker_asks_for_is_the_sum_of_its_cameras(self):
        """Two cameras at 2/sec beside one at 5 is nine frames a second.

        An average would report three and understate the busy one, which is
        the camera that decides whether the machine copes.
        """
        worker = _worker(["cam-a", "cam-b", "cam-c"], rate_hz=5.0)
        worker.set_rate("cam-a", 2.0)
        worker.set_rate("cam-b", 2.0)

        assert worker.stats["frames_per_second"] == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# editing a camera changes what actually runs
# ---------------------------------------------------------------------------

class RecordingWorker:
    """Enough of a worker to record what the store asked of it."""

    def __init__(self, name="people"):
        self.name = name
        self.rates: dict[str, float] = {}
        self.watching: set[str] = set()

    def set_rate(self, camera_id: str, rate_hz: float) -> None:
        self.rates[camera_id] = rate_hz

    def watch(self, camera_id: str) -> None:
        self.watching.add(camera_id)

    def unwatch(self, camera_id: str) -> None:
        self.watching.discard(camera_id)


class TestEditingTheRateTakesEffect:
    def test_applying_a_camera_pushes_its_rate_into_every_worker(
            self, bare_live_store):
        """The regression, from the store's end.

        `_apply_features` re-watched cameras and never touched the rate, so
        an edit was persisted, audited, echoed back to the console — and
        ignored by the thing it was supposed to change.
        """
        from vg.config import CameraConfig

        worker = RecordingWorker()
        bare_live_store.people_worker = worker
        bare_live_store.tracking = RecordingWorker("tracking")

        camera = CameraConfig.parse(
            {"id": "cam-a", "name": "A", "source": "webcam:0",
             "features": ["counting"], "fps": 2.0},
            where="test")
        bare_live_store._apply_features(camera)

        assert worker.rates == {"cam-a": 2.0}
        assert bare_live_store.tracking.rates == {"cam-a": 2.0}

    def test_a_worker_that_cannot_take_a_rate_does_not_fail_the_edit(
            self, bare_live_store):
        """Rule 9, and the reason `_set_rate` swallows AttributeError.

        A worker predating per-camera rates must not stop an operator saving
        a camera; it keeps the rate it was built with and carries on.
        """
        from vg.config import CameraConfig

        class OldWorker:
            def watch(self, camera_id): pass
            def unwatch(self, camera_id): pass

        bare_live_store.people_worker = OldWorker()
        camera = CameraConfig.parse(
            {"id": "cam-a", "name": "A", "source": "webcam:0",
             "features": ["counting"], "fps": 2.0},
            where="test")

        bare_live_store._apply_features(camera)  # must not raise


# ---------------------------------------------------------------------------
# what the configuration asks of the machine
# ---------------------------------------------------------------------------

class FakeWorker:
    """A worker that reports whatever the test needs it to."""

    def __init__(self, name, *, cameras=2, hz=5.0, ms=20.0, device="cuda:0",
                 on_demand=False):
        self._stats = {
            "name": name,
            "cameras": cameras,
            "frames_per_second": hz,
            "last_inference_ms": ms,
            "device": device,
            "on_demand": on_demand,
            "queue_depth": 0,
            "queue_max": 1,
            "frames_dropped": 0,
            "frames_processed": 10,
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)


def _row(capacity: S.Capacity, name: str) -> S.CapacityRow | None:
    return next((r for r in capacity.rows if r.name == name), None)


class TestCapacityProjection:
    def test_nothing_running_reports_no_capacity_at_all(self, bare_live_store):
        """Absent, not zero. "No workers" and "workers costing nothing" are
        different answers, and zeros would read as a machine with room."""
        assert bare_live_store.health().capacity is None

    def test_it_is_the_rate_times_the_cost(self, bare_live_store):
        """The whole arithmetic, and the thing an operator is being asked to
        trust: 10 frames a second at 20 ms each is 200 ms of every second."""
        bare_live_store.people_worker = FakeWorker("people", hz=10.0, ms=20.0)

        capacity = bare_live_store.health().capacity
        assert capacity is not None
        assert _row(capacity, "people").ms_per_second == pytest.approx(200.0)
        assert capacity.gpu_ms_per_second == pytest.approx(200.0)

    def test_faces_and_the_person_pass_are_counted_separately(
            self, bare_live_store):
        """The reason there are two budgets.

        SFace has no CUDA path, so attendance never competes with counting
        for the same milliseconds. One combined figure would be a percentage
        of nothing.
        """
        bare_live_store.people_worker = FakeWorker(
            "people", hz=10.0, ms=20.0, device="cuda:0")
        bare_live_store.recogniser = FakeWorker(
            "recognition", hz=5.0, ms=44.0, device="cpu")

        capacity = bare_live_store.health().capacity
        assert capacity.gpu_ms_per_second == pytest.approx(200.0)
        assert capacity.cpu_ms_per_second == pytest.approx(220.0)
        assert capacity.gpu_budget_ms == 1000.0
        assert capacity.cpu_budget_ms == capacity.cores * 1000.0

    def test_a_worker_that_did_not_say_is_in_neither_budget(
            self, bare_live_store):
        """Guessing a pool makes BOTH totals wrong. It is carried on its own
        line instead, so the page can name it."""
        bare_live_store.people_worker = FakeWorker(
            "people", hz=5.0, ms=20.0, device=None)

        capacity = bare_live_store.health().capacity
        assert capacity.gpu_ms_per_second == 0.0
        assert capacity.cpu_ms_per_second == 0.0
        assert capacity.unplaced_ms_per_second == pytest.approx(100.0)
        assert _row(capacity, "people").pool is None

    def test_a_timed_cost_is_marked_measured(self, bare_live_store):
        bare_live_store.people_worker = FakeWorker("people", ms=18.4)

        capacity = bare_live_store.health().capacity
        assert _row(capacity, "people").measured is True
        assert _row(capacity, "people").ms_per_frame == pytest.approx(18.4)
        assert capacity.all_measured is True

    def test_a_worker_that_has_not_run_yet_is_marked_an_estimate(
            self, bare_live_store):
        """Principle III. A figure carried in from an earlier machine is not
        a measurement, and a page that presents it as one is the confident
        fiction the constitution forbids."""
        bare_live_store.people_worker = FakeWorker("people", ms=0.0)

        capacity = bare_live_store.health().capacity
        row = _row(capacity, "people")
        assert row.measured is False
        assert row.ms_per_frame == pytest.approx(
            bare_live_store.ASSUMED_MS_PER_FRAME["people"])
        assert capacity.all_measured is False

    def test_a_worker_serving_no_camera_gets_no_row(self, bare_live_store):
        """Absent rather than present with zeros, exactly like the workers
        stage. "Not running" and "running for free" are different answers."""
        bare_live_store.people_worker = FakeWorker("people", cameras=0)
        assert bare_live_store.health().capacity is None

    def test_bag_search_is_shown_but_never_counted(self, bare_live_store):
        """Its idle cost is zero and its watched cost is not fixed by any
        setting, so a number for it would be invented. The row says what it
        is instead."""
        bare_live_store.lost_watch = FakeWorker(
            "lostitems", hz=None, ms=29.0, on_demand=True)

        capacity = bare_live_store.health().capacity
        row = _row(capacity, "lostitems")
        assert row.on_demand is True
        assert row.frames_per_second is None
        assert row.ms_per_second is None
        assert capacity.gpu_ms_per_second == 0.0

    def test_a_worker_whose_counters_raise_does_not_take_the_page_down(
            self, bare_live_store):
        """Rule 7. The health page's whole job is to keep answering while
        things are broken."""
        class Broken:
            @property
            def stats(self):
                raise RuntimeError("counters unavailable")

        bare_live_store.people_worker = Broken()
        bare_live_store.recogniser = FakeWorker("recognition", device="cpu")

        capacity = bare_live_store.health().capacity
        assert capacity is not None
        assert _row(capacity, "people") is None
        assert _row(capacity, "recognition") is not None

    def test_health_is_still_two_hundred_with_a_full_machine(
            self, bare_live_store):
        """Overload is payload. A machine asked for more than it has must
        report that, not refuse to answer."""
        bare_live_store.people_worker = FakeWorker(
            "people", cameras=40, hz=200.0, ms=20.0)

        health = bare_live_store.health()
        assert isinstance(health, S.SystemHealth)
        assert health.capacity.gpu_ms_per_second > health.capacity.gpu_budget_ms
