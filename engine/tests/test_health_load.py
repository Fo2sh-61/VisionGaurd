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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import schemas as S  # noqa: E402
from vg.features.base import FeatureWorker  # noqa: E402
from vg.ingest.framebus import FrameBus  # noqa: E402
from vg.ingest.source import Frame  # noqa: E402


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

    def test_gpu_load_is_a_reading_or_nothing(self, bare_live_store):
        """Whole-device utilisation from the driver, or None. Never invented.

        This used to assert None outright, because nothing measured it. It
        is measured now (NVML, since 3 Sep 2026) - and it had to be, because
        the capacity projection once drew a GPU bar at 100% over a card the
        driver had at 18%, with nothing on the page to contradict it. On a
        machine with no NVIDIA driver the honest value is still None, and a
        plausible number there would be the lie Principle III names.
        """
        gpu = bare_live_store.health().gpu_percent
        assert gpu is None or (isinstance(gpu, float) and 0.0 <= gpu <= 100.0)

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

    def test_they_are_not_called_undecoded(self, bare_live_store):
        """They were decoded. `grab()` is the decode on OpenCV's FFmpeg backend.

        What an unwatched camera skips is `retrieve()`, the conversion to
        pixels. The page said "Frames not decoded" until 12 Sep 2026, which
        told an operator the expensive part was being saved when it was not.
        """
        label = {m.key: m for m in bare_live_store.health().metrics}["skipped"].label
        assert "not decoded" not in label.lower()


# ---------------------------------------------------------------------------
# a worker that cannot count itself
# ---------------------------------------------------------------------------

class TestCountersThatCannotBeRead:
    """Rule 7, on the four stages that used to break it.

    The workers stage always skipped a worker whose bookkeeping raised. The
    four per-feature stages read `worker.stats` unguarded, so one broken
    counter took the whole of System Health down with a 500 — the page an
    operator opens to find out what is wrong, refusing to answer *because*
    something was wrong. Found on 2 Sep 2026 while adding the capacity
    projection, which had to read the same counters.
    """

    @staticmethod
    def _stages(store):
        return {s.key: s for s in store.health().pipeline}

    def test_person_detection_says_so_instead_of_five_hundreding(
            self, bare_live_store):
        bare_live_store.people_worker = BrokenWorker()

        stage = self._stages(bare_live_store)["detect"]
        assert stage.healthy is False
        assert "counters" in stage.detail.lower()

    def test_the_rest_of_the_page_still_answers(self, bare_live_store):
        """The point of the guard. One broken counter must cost one row,
        never the page."""
        bare_live_store.people_worker = BrokenWorker()

        health = bare_live_store.health()
        assert isinstance(health, S.SystemHealth)
        assert len(health.pipeline) > 1


# ---------------------------------------------------------------------------
# off is not down
# ---------------------------------------------------------------------------

class TestOffIsNotDown:
    """A camera an operator switched off is not a fault.

    `registry.total` counts disabled cameras - rightly, for the setup list,
    where a camera somebody turned off must not vanish. System Health used
    the same number as "how many should be online", so two cameras disabled
    on purpose read as "1 of 3 online", the ingest stage went amber, the
    summary said two cameras were not being analysed, and the top bar
    carried the same untruth onto every page. Found 3 Sep 2026.
    """

    @staticmethod
    def _store(*configs):
        from vg import config as vgconfig
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        return LiveStore(config=vgconfig.load(),
                         registry=CameraRegistry(list(configs)))

    @staticmethod
    def _camera(cid, enabled):
        from vg.config import CameraConfig

        return CameraConfig.parse(
            {"id": cid, "name": cid, "source": "webcam:99", "enabled": enabled},
            "c")

    def test_a_disabled_camera_is_counted_as_off_not_offline(self):
        store = self._store(self._camera("on", True), self._camera("off", False))
        health = store.health()

        assert health.cameras_total == 1
        assert health.cameras_disabled == 1
        # Not "1 of 2". The disabled one is neither online nor missing.
        assert health.cameras_online <= health.cameras_total

    def test_the_ingest_stage_says_switched_off_in_words(self):
        store = self._store(self._camera("on", True), self._camera("off", False))
        stage = _stage(store.health(), "ingest")

        assert stage is not None
        assert "switched off" in stage.detail
        assert "of 1" in stage.detail

    def test_a_disabled_source_is_not_a_recorder_that_is_down(self):
        store = self._store(self._camera("off", False))
        health = store.health()

        assert health.recorders_total == 0
        assert health.cameras_disabled == 1

    def test_the_top_bar_agrees(self):
        """`site()` feeds the chrome on every page. It has to count the same
        way, or the top bar contradicts System Health."""
        store = self._store(self._camera("on", True), self._camera("off", False))
        assert store.site().cameras_total == 1


# ---------------------------------------------------------------------------
# a thread that died
# ---------------------------------------------------------------------------

class _ThreadKilled(BaseException):
    """Not an `Exception`, so the loop's one-bad-frame guard lets it past.

    The thread then dies through the same `finally` the vehicles worker's
    threads went through on 4-5 Sep 2026, when an ordinary AttributeError in
    the loop's own bookkeeping - outside that guard - killed each of them on
    its first frame.
    """


class Mortal(FeatureWorker[int]):
    """A real worker whose thread dies on each of its first `deaths` frames."""

    def __init__(self, bus, cameras, *, deaths: int = 0) -> None:
        super().__init__("mortal", bus, cameras, rate_hz=0)
        self.deaths_to_come = deaths

    def analyse(self, frame) -> int:
        if self.deaths_to_come > 0:
            self.deaths_to_come -= 1
            raise _ThreadKilled()
        return 0


def _feed_until(bus, camera_id: str, predicate, *, timeout: float = 5.0) -> None:
    """Publish frames until `predicate()` holds.

    Waits on the worker, never on a fixed sleep, so a slow machine makes the
    test slower rather than wrong.
    """
    deadline = time.monotonic() + timeout
    sequence = 0
    while time.monotonic() < deadline:
        if predicate():
            return
        bus.publish(Frame(camera_id, np.zeros((4, 4, 3), np.uint8),
                          datetime.now(timezone.utc), sequence))
        sequence += 1
        time.sleep(0.02)
    raise AssertionError("condition never became true")


def _thread_alive(name: str) -> bool:
    return any(t.name == name and t.is_alive() for t in threading.enumerate())


@pytest.fixture
def dead_worker():
    """A worker whose only thread has died. Nothing asked it to stop."""
    bus = FrameBus()
    worker = Mortal(bus, ["gate-1"], deaths=1)
    worker.start()
    try:
        _feed_until(bus, "gate-1", lambda: not _thread_alive("mortal-gate-1"))
        yield worker
    finally:
        worker.stop()
        bus.close()


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning")
class TestADeadThreadIsNotIdle:
    """Rule 8: a worker whose thread has died must not read as running.

    A dying thread takes itself out of `_threads`, but its camera stays in
    `cameras`. Every other counter then reads zero, which is exactly what an
    idle worker looks like - so System Health said "all keeping up" over the
    dead vehicles worker for a whole day, 4-5 Sep 2026.
    """

    def test_the_workers_stage_stops_saying_running(
            self, bare_live_store, dead_worker):
        bare_live_store.vehicles_worker = dead_worker

        stage = _stage(bare_live_store.health(), "workers")
        assert stage.healthy is False
        assert stage.severity is S.Severity.CRITICAL
        assert "mortal" in stage.detail
        assert "gate-1" in stage.detail, "named, not just counted"
        assert "running" not in stage.detail.lower()
        # Its own row would read "keeping up" under a "stopped" headline:
        # the counters of a dead thread look exactly like an idle one's.
        assert "mortal" not in [w.name for w in stage.workers]

    def test_the_features_own_row_says_it_stopped(
            self, bare_live_store, dead_worker):
        bare_live_store.people_worker = dead_worker

        stage = _stage(bare_live_store.health(), "detect")
        assert stage.healthy is False
        assert stage.severity is S.Severity.CRITICAL
        assert "stopped" in stage.detail.lower()
        assert "gate-1" in stage.detail
        assert stage.restartable is False, "the Restart button does nothing"

    def test_a_worker_that_cannot_say_reads_exactly_as_today(
            self, bare_live_store):
        """Additive. No `died_on` in its counters, no change on the page."""
        bare_live_store.people_worker = FakeWorker("people")

        health = bare_live_store.health()
        workers = _stage(health, "workers")
        assert workers.healthy is True
        assert workers.detail == "1 running, all keeping up"
        assert _stage(health, "detect").healthy is True

    def test_stopping_is_not_a_death(self):
        bus = FrameBus()
        worker = Mortal(bus, ["gate-1"])
        worker.start()
        try:
            _feed_until(bus, "gate-1", lambda: worker.frames_processed > 0)
        finally:
            worker.stop()
            bus.close()
        assert worker.stats["died_on"] == []

    def test_a_fresh_thread_clears_the_death(self):
        bus = FrameBus()
        worker = Mortal(bus, ["gate-1"], deaths=1)
        worker.start()
        try:
            _feed_until(bus, "gate-1",
                        lambda: worker.stats.get("died_on") == ["gate-1"])
            worker.unwatch("gate-1")
            worker.watch("gate-1")
            _feed_until(bus, "gate-1", lambda: worker.frames_processed > 0)
            assert worker.stats["died_on"] == []
        finally:
            worker.stop()
            bus.close()

    def test_a_dead_camera_switched_off_is_no_longer_reported(self, dead_worker):
        """Off is not down, here as on the ingest row. `unwatch` alone - no
        fresh thread to clear the record - must still end the alarm."""
        dead_worker.unwatch("gate-1")

        assert dead_worker.stats["died_on"] == []

    def test_several_dead_cameras_are_each_named(self, bare_live_store):
        bus = FrameBus()
        worker = Mortal(bus, ["gate-1", "gate-2"], deaths=2)
        worker.start()
        try:
            for camera_id in ("gate-1", "gate-2"):
                _feed_until(bus, camera_id,
                            lambda c=camera_id: not _thread_alive(f"mortal-{c}"))
            bare_live_store.people_worker = worker

            health = bare_live_store.health()
            detect = _stage(health, "detect")
            assert '"gate-1", "gate-2"' in detect.detail
            assert "threads died" in detect.detail
            assert "threads died" in _stage(health, "workers").detail
        finally:
            worker.stop()
            bus.close()

    def test_knife_detection_says_it_stopped(self, bare_live_store, dead_worker):
        """On this feature above all others, an empty log must never read
        as an all-clear."""
        # Only ever compared with None on the way to this row.
        bare_live_store.weapon_scenes = object()
        bare_live_store.weapons_worker = dead_worker

        stage = _stage(bare_live_store.health(), "weapons")
        assert stage.healthy is False
        assert stage.severity is S.Severity.CRITICAL
        assert '"gate-1"' in stage.detail
        assert stage.restartable is False

    def test_plate_reading_names_the_camera_as_the_operator_typed_it(
            self, dead_worker):
        """The typed name, quoted - so the comma inside this one cannot read
        as a second camera."""
        from vg import config as vgconfig
        from vg.api.live import LiveStore
        from vg.config import CameraConfig
        from vg.ingest.registry import CameraRegistry

        gate = CameraConfig.parse(
            {"id": "gate-1", "name": "Gate, north", "source": "webcam:99",
             "features": ["vehicles"], "gate": 1, "direction": "entry"},
            "c")
        store = LiveStore(config=vgconfig.load(),
                          registry=CameraRegistry([gate]))
        # Only ever compared with None on the way to this row.
        store.vehicle_store = object()
        store.vehicles_worker = dead_worker

        stage = _stage(store.health(), "vehicles")
        assert stage.healthy is False
        assert stage.severity is S.Severity.CRITICAL
        assert '"Gate, north"' in stage.detail
        assert "gate-1" not in stage.detail, "a database key, not a name"

    def test_face_recognition_says_it_stopped_before_nobody_is_enrolled(
            self, dead_worker):
        """A dead thread recognises nobody, however many are enrolled, so
        it outranks the empty-gallery warning on the same row."""
        import tempfile

        from vg import config as vgconfig
        from vg.api.live import LiveStore
        from vg.events.sightings import SightingStore
        from vg.identity.gallery import FaceGallery
        from vg.ingest.registry import CameraRegistry

        tmp = tempfile.TemporaryDirectory()
        gallery = FaceGallery(Path(tmp.name) / "g.db", model="sface-2021dec",
                              threshold=0.363)
        sightings = SightingStore(Path(tmp.name) / "s.db", clock=180)
        try:
            store = LiveStore(config=vgconfig.load(),
                              registry=CameraRegistry([]),
                              gallery=gallery, sightings=sightings)
            store.recogniser = dead_worker

            stage = _stage(store.health(), "recognition")
            assert stage.healthy is False
            assert stage.severity is S.Severity.CRITICAL
            assert "nobody is recognised" in stage.detail
        finally:
            sightings.close()
            # Before the directory, or Windows fails the teardown.
            gallery.close()
            tmp.cleanup()
