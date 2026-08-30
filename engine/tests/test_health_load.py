"""System Health tells the truth about load, including when it cannot measure it.

The failure this exists to prevent is not a crash. It is a page that reads
"all good" over a machine that is dropping frames — which is what the console
did before, because every counter needed to say otherwise was already being
kept and nothing read it.

Two rules are under test, and they pull in opposite directions on purpose:

  **Say it when it is bad.** A worker that is behind must be named, and the
  summary severity must rise with it. Degradation is payload, never a 5xx.

  **Do not say it when you do not know.** A figure that cannot be measured is
  `null` and renders as unavailable. Never `0`, because a machine at 90% and
  a machine nobody can measure would then look identical, and the second one
  is the dangerous case.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import schemas as S  # noqa: E402


def _stage(health: S.SystemHealth, key: str) -> S.PipelineStage | None:
    return next((s for s in health.pipeline if s.key == key), None)


class FakeSubscription:
    """The two counters `FeatureWorker.stats` reads off a subscription."""

    def __init__(self, depth: int, maxsize: int, dropped: int) -> None:
        self._frames = [None] * depth
        self.maxsize = maxsize
        self.dropped = dropped


class FakeWorker:
    """Enough of a FeatureWorker to be described on the health page."""

    def __init__(self, name: str, *, depth: int = 0, maxsize: int = 1,
                 dropped: int = 0, cameras: int = 2) -> None:
        self.name = name
        self._stats = {
            "name": name,
            "cameras": cameras,
            "frames_processed": 100,
            "last_inference_ms": 21.5,
            "queue_depth": depth,
            "queue_max": maxsize,
            "frames_dropped": dropped,
            "behind": bool(maxsize and depth >= maxsize and dropped > 0),
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)


class BrokenWorker:
    """A worker whose own bookkeeping raises.

    It must not take the health page down with it - the page's whole job is
    to keep answering when things are broken.
    """

    name = "broken"

    @property
    def stats(self) -> dict:
        raise RuntimeError("counters unavailable")


# ---------------------------------------------------------------------------
# nothing running
# ---------------------------------------------------------------------------

class TestNothingRunning:
    def test_health_is_still_two_hundred(self, bare_live_store):
        """Rule 7. Degradation is payload, never a 5xx.

        Every subsystem absent is the state the page exists FOR, so it is
        also the state most likely to be reached by an exception nobody
        wrote a branch for.
        """
        health = bare_live_store.health()
        assert isinstance(health, S.SystemHealth)

    def test_the_workers_stage_says_nothing_is_running(self, bare_live_store):
        stage = _stage(bare_live_store.health(), "workers")
        assert stage is not None
        assert stage.workers == []
        assert stage.healthy is False
        assert "nothing" in stage.detail.lower()


# ---------------------------------------------------------------------------
# a worker that is behind
# ---------------------------------------------------------------------------

class TestSaturationIsVisible:
    def test_a_behind_worker_is_named(self, bare_live_store):
        """Named, not just counted.

        "One worker is behind" sends an operator through seven pages. The
        page knows which one; it should say so.
        """
        bare_live_store.recogniser = FakeWorker(
            "recognition", depth=1, maxsize=1, dropped=42)
        bare_live_store.people_worker = FakeWorker("people")

        stage = _stage(bare_live_store.health(), "workers")
        assert stage is not None
        assert "recognition" in stage.detail
        assert stage.healthy is False
        assert stage.severity is S.Severity.WARN

    def test_the_summary_severity_rises_with_it(self, bare_live_store):
        """The bug this whole stage exists to remove.

        A healthy-looking summary over a saturated machine is worse than no
        page at all, because it is actively reassuring.
        """
        bare_live_store.recogniser = FakeWorker(
            "recognition", depth=1, maxsize=1, dropped=42)
        assert bare_live_store.health().severity is S.Severity.WARN

    def test_busy_is_not_the_same_as_behind(self, bare_live_store):
        """A full queue alone is a worker that happened to be mid-frame.

        Drops are what say it did not catch up. Flagging every momentarily
        full queue would train an operator to ignore the warning.
        """
        bare_live_store.people_worker = FakeWorker(
            "people", depth=1, maxsize=1, dropped=0)

        stage = _stage(bare_live_store.health(), "workers")
        assert stage.workers[0].behind is False
        assert stage.healthy is True

    def test_the_counters_reach_the_wire(self, bare_live_store):
        bare_live_store.people_worker = FakeWorker(
            "people", depth=1, maxsize=2, dropped=7, cameras=3)

        load = _stage(bare_live_store.health(), "workers").workers[0]
        assert load.name == "people"
        assert load.cameras == 3
        assert load.queue_depth == 1
        assert load.queue_max == 2
        assert load.frames_dropped == 7
        assert load.frames_processed == 100

    def test_camel_case_on_the_wire(self, bare_live_store):
        """The console is TypeScript; snake_case would force a translator."""
        bare_live_store.people_worker = FakeWorker("people")

        wire = _stage(bare_live_store.health(), "workers").workers[0].model_dump(
            by_alias=True)
        for key in ("framesProcessed", "lastInferenceMs", "queueDepth",
                    "queueMax", "framesDropped"):
            assert key in wire, f"{key} missing from the wire"
        assert "frames_processed" not in wire


# ---------------------------------------------------------------------------
# a worker that is not running, and one that is broken
# ---------------------------------------------------------------------------

class TestAbsentIsNotZero:
    def test_a_stopped_worker_is_absent_not_zeroed(self, bare_live_store):
        """"Stopped" and "idle" are different answers.

        A row of zeros reads as the second one, and an operator looking for
        why attendance is empty would conclude the worker is running fine.
        """
        bare_live_store.people_worker = FakeWorker("people")
        bare_live_store.recogniser = None

        names = [w.name for w in _stage(
            bare_live_store.health(), "workers").workers]
        assert names == ["people"]

    def test_a_broken_worker_does_not_take_the_page_down(self, bare_live_store):
        bare_live_store.recogniser = BrokenWorker()
        bare_live_store.people_worker = FakeWorker("people")

        stage = _stage(bare_live_store.health(), "workers")
        assert [w.name for w in stage.workers] == ["people"]


# ---------------------------------------------------------------------------
# what cannot be measured
# ---------------------------------------------------------------------------

class TestUnmeasurableIsNotZero:
    def test_processor_load_is_a_number_or_nothing(self, bare_live_store):
        cpu = bare_live_store.health().cpu_percent
        assert cpu is None or isinstance(cpu, float)

    def test_gpu_share_is_absent_rather_than_invented(self, bare_live_store):
        """Nothing in this engine measures per-process GPU share.

        Until something does, the honest value is None. A plausible number
        here would be read as measured, which is the specific lie Principle
        III names.
        """
        assert bare_live_store.health().gpu_percent is None

    def test_there_is_no_per_worker_processor_field(self):
        """Deliberately absent, and asserted so nobody adds it back.

        Feature workers are threads in one process. The operating system
        attributes processor time to the process, so a per-worker percentage
        could only ever be this engine's guess at a split.
        """
        assert "cpu_percent" not in S.WorkerLoad.model_fields
        assert "gpu_percent" not in S.WorkerLoad.model_fields


# ---------------------------------------------------------------------------
# the saving, made checkable
# ---------------------------------------------------------------------------

class TestSkippedFramesAreNotDrops:
    def test_they_are_reported_separately(self, bare_live_store):
        """A skipped frame is the feature working; a dropped one is not.

        Adding them together would make a healthy saving look like an
        overload, and the change that produced it look like a regression.
        """
        metrics = {m.key: m for m in bare_live_store.health().metrics}
        assert "dropped" in metrics
        assert "skipped" in metrics
        assert metrics["dropped"].label != metrics["skipped"].label
