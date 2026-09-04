"""System Health's bars are readings, and the projection sits beside them.

The capacity card was first built as arithmetic - a configured rate times a
cost - and drawn as a bar. It read 100% over a graphics card the driver had
at 18%, and the operator said so. A bar is a claim about *now*; only a
measurement gets to make it. Found 3 Sep 2026.

Three things are pinned here:

  **A worker keeps a window of what it actually did.** Milliseconds really
  spent over the last few seconds, divided by the seconds covered. Idle for
  the whole window reads 0.0, which is then a true statement.

  **The shared pass keeps the same window**, so the pass and its readers are
  measured over the same seconds.

  **The processor figure is a reading, not a first-call zero.** psutil
  reports the change since the last call on the same object; a fresh
  `Process()` every poll meant the engine's share read 0.0 for as long as
  the product existed.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import schemas as S  # noqa: E402
from vg.features.base import FeatureWorker  # noqa: E402
from vg.infer.shared import SharedDetection  # noqa: E402
from test_shared_pass import OneFrameBus, SlowDetector, _frame  # noqa: E402


class BusyWorker(FeatureWorker[int]):
    def __init__(self, bus, ms: float) -> None:
        super().__init__("busy", bus, ["cam-a"], rate_hz=100.0)
        self.ms = ms

    def analyse(self, frame) -> int:
        time.sleep(self.ms / 1000)
        return 1


def _run_one_frame(worker):
    """Start, wait for the frame, read stats BEFORE stop (see `_closing`)."""
    worker.start()
    stats = None
    deadline = time.monotonic() + 3.0
    while stats is None and time.monotonic() < deadline:
        if worker.result("cam-a") is not None:
            stats = worker.stats
        time.sleep(0.01)
    worker.stop()
    assert stats is not None, "the worker never analysed the frame"
    return stats


class TestAWorkerReportsWhatItDid:
    def test_busy_time_is_milliseconds_over_seconds_covered(self):
        """One 40 ms frame, a worker a fraction of a second old: the span
        floors at one second, so it reads ~40 ms/s - not 40/5 = 8, which
        would be spreading one second's work over five."""
        stats = _run_one_frame(BusyWorker(OneFrameBus(_frame()), ms=40))

        assert stats["busy_ms_per_second"] >= 30
        assert stats["analysed_per_second"] >= 0.9
        assert stats["window_seconds"] == FeatureWorker.WINDOW_SECONDS

    def test_borrowed_time_is_not_busy_time(self):
        """The shared pass is charged once, on its own row. A worker's
        measured figure is its OWN work, exactly as its per-frame one is."""
        from test_shared_pass import RidingWorker

        shared = SharedDetection(SlowDetector(ms=40))
        stats = _run_one_frame(RidingWorker(OneFrameBus(_frame()), shared))

        assert stats["busy_ms_per_second"] < 30
        assert stats["last_shared_ms"] >= 30

    def test_idle_reads_zero_and_zero_is_true(self):
        worker = BusyWorker(bus=None, ms=1)
        assert worker.stats["busy_ms_per_second"] == 0.0
        assert worker.stats["analysed_per_second"] == 0.0


class TestThePassReportsWhatItDid:
    def test_load_is_passes_and_milliseconds_over_the_window(self):
        shared = SharedDetection(SlowDetector(ms=20))
        shared.raw_boxes(_frame(sequence=1))
        shared.raw_boxes(_frame(sequence=2))

        load = shared.load()
        assert load["passes_per_second"] >= 1.9
        assert load["busy_ms_per_second"] >= 30

    def test_a_cache_hit_adds_nothing_to_the_load(self):
        shared = SharedDetection(SlowDetector(ms=20))
        frame = _frame()
        shared.raw_boxes(frame)
        before = shared.load()
        shared.raw_boxes(frame)

        assert shared.load()["passes_per_second"] == before["passes_per_second"]


class Reader:
    """A person-pass reader with a measured load, as the card sees it."""

    def __init__(self, name, *, busy=0.0, analysed=0.0, device="cpu",
                 detector=None):
        self.name = name
        self.cameras = ["cam-a"]
        self.detector = detector
        self._stats = {
            "name": name, "cameras": 1, "frames_per_second": 5.0,
            "last_inference_ms": 2.0, "last_shared_ms": 13.0, "device": device,
            "busy_ms_per_second": busy, "analysed_per_second": analysed,
            "window_seconds": 5.0, "queue_depth": 0, "queue_max": 1,
            "frames_dropped": 0, "frames_processed": 5,
        }

    def rate_for(self, camera_id):
        return 5.0

    @property
    def stats(self):
        return dict(self._stats)


class TestTheCardKeepsReadingAndProjectionApart:
    def test_busy_totals_come_from_measurements_not_rates(self, bare_live_store):
        """A worker configured at 5/sec that only managed 1 frame in the
        window is charged for the frame, not for the five."""
        det = SimpleNamespace(
            last_pass_ms=13.0, device="cuda:0",
            load=lambda: {"passes_per_second": 1.0, "busy_ms_per_second": 13.0,
                          "window_seconds": 5.0})
        bare_live_store.people_worker = Reader(
            "people", busy=0.5, analysed=1.0, device="cuda:0", detector=det)
        bare_live_store.tracking = Reader(
            "tracking", busy=3.0, analysed=1.0, device="cpu", detector=det)

        capacity = bare_live_store.health().capacity
        # Reading: the pass (13) plus people's own (0.5) on the GPU.
        assert capacity.gpu_busy_ms_per_second == pytest.approx(13.5)
        assert capacity.cpu_busy_ms_per_second == pytest.approx(3.0)
        # Projection, still there, still separate: 5/sec x 13 for the pass.
        assert capacity.gpu_ms_per_second == pytest.approx(65.0 + 10.0)
        assert capacity.window_seconds == 5.0

    def test_the_shared_row_reads_from_the_detector(self, bare_live_store):
        det = SimpleNamespace(
            last_pass_ms=13.0, device="cuda:0",
            load=lambda: {"passes_per_second": 4.8, "busy_ms_per_second": 62.0,
                          "window_seconds": 5.0})
        bare_live_store.people_worker = Reader("people", detector=det)

        row = [r for r in bare_live_store.health().capacity.rows if r.shared][0]
        assert row.busy_ms_per_second == pytest.approx(62.0)
        assert row.analysed_per_second == pytest.approx(4.8)

    def test_a_detector_with_no_load_method_is_a_zero_reading_not_a_crash(
            self, bare_live_store):
        bare_live_store.people_worker = Reader(
            "people", detector=SimpleNamespace(last_pass_ms=13.0, device="cuda:0"))

        row = [r for r in bare_live_store.health().capacity.rows if r.shared][0]
        assert row.busy_ms_per_second == 0.0


class TestTheProcessorFigureIsAReading:
    def test_the_first_call_is_none_not_zero(self):
        """psutil hands back 0.0 before it has a baseline. Passing that on
        would say "idle" about a machine nobody has measured yet."""
        from vg.api import live

        live._PROCESS = None
        live._PRIMED = False
        first = live._cpu_readings()
        # BOTH withheld on the priming poll. Taking them separately once
        # handed back a machine figure of 0.0 a microsecond after the
        # process figure was honest enough to say None.
        assert first == {"process": None, "machine": None}

    def test_later_calls_are_numbers_from_one_held_process(self):
        from vg.api import live

        live._PROCESS = None
        live._PRIMED = False
        live._cpu_readings()
        time.sleep(0.05)
        readings = live._cpu_readings()

        assert isinstance(readings["process"], float) and readings["process"] >= 0.0
        assert isinstance(readings["machine"], float)
        assert 0.0 <= readings["machine"] <= 100.0
        assert live._PROCESS is not None

    def test_health_carries_both_readings(self, bare_live_store):
        health = bare_live_store.health()
        for value in (health.cpu_percent, health.cpu_machine_percent):
            assert value is None or isinstance(value, float)
        assert "cpu_machine_percent" in S.SystemHealth.model_fields
        assert "gpu_memory_total_mb" in S.SystemHealth.model_fields


class TestTheWindowIsShared:
    def test_pass_and_readers_use_the_same_seconds(self):
        from vg.infer import shared

        assert shared.WINDOW_SECONDS == FeatureWorker.WINDOW_SECONDS


def _now():
    return datetime.now(timezone.utc)
