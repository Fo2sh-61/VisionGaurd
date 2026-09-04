"""A camera's feature list decides what analyses that camera - and only that.

Two bugs and one gap:

- `_start_weapons` and `_start_zones` both took every enabled camera, so knife
  detection and restricted-area watching ran on cameras that never asked for
  them. `BagWatch` took no camera list at all. The `features:` list was
  decorative for three features of seven.
- `FeatureWorker.start()` took its camera list once, at construction, so a
  camera added at runtime streamed and was analysed by nothing until the
  engine restarted.

And the race this must not reintroduce: `ZonesWorker.set_restricted`'s
docstring records that closing a scene from the API thread, while the camera's
own thread was mid-`analyse`, made that thread open a *second* scene whose clip
replaced the first one's. Switching a camera off destroyed the recording of the
scene that was running. `unwatch` has the same shape, so it sets a flag and
returns; the closing happens on the camera's own thread.
"""

from __future__ import annotations

import threading
import time

from vg.config import CameraConfig


def camera(camera_id: str, features: list[str], **kw) -> CameraConfig:
    """One camera config, valid, with everything else defaulted."""
    return CameraConfig.parse(
        {"id": camera_id, "name": camera_id, "source": "webcam:0",
         "features": features, **kw},
        camera_id,
    )


def wait_until(predicate, *, timeout: float = 5.0) -> None:
    """Wait on the worker, never on the clock under test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


# ---------------------------------------------------------------------------
# a worker can gain and lose one camera while it runs
# ---------------------------------------------------------------------------

from vg.features.base import FeatureWorker          # noqa: E402
from vg.ingest.framebus import FrameBus             # noqa: E402
from vg.ingest.source import Frame                  # noqa: E402

import numpy as np                                  # noqa: E402
from datetime import datetime, timezone             # noqa: E402


class Counter(FeatureWorker[int]):
    """Counts frames per camera, and records which cameras it closed."""

    def __init__(self, bus, cameras):
        super().__init__("counter", bus, cameras, rate_hz=0)
        self.seen: dict[str, int] = {}
        self.closed: list[tuple[str, str]] = []
        self._seen_lock = threading.Lock()

    def analyse(self, frame) -> int:
        with self._seen_lock:
            self.seen[frame.camera_id] = self.seen.get(frame.camera_id, 0) + 1
            return self.seen[frame.camera_id]

    def _closing(self, camera_id: str) -> None:
        # The thread that ran `analyse` is the thread that runs this. Recorded
        # so a test can prove it, because closing from the API thread is what
        # once destroyed the recording of a scene that was still running.
        self.closed.append((camera_id, threading.current_thread().name))
        super()._closing(camera_id)


def publish(bus, camera_id: str, n: int = 3) -> None:
    for i in range(n):
        bus.publish(Frame(camera_id, np.zeros((4, 4, 3), np.uint8),
                          datetime.now(timezone.utc), i))
        time.sleep(0.01)


class TestWatchAndUnwatch:
    def test_a_worker_gains_a_camera_while_running(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            worker.watch("cam-b")
            publish(bus, "cam-b")

            wait_until(lambda: worker.seen.get("cam-b", 0) > 0)
            assert worker.serves("cam-b")
            assert worker.stats["cameras"] == 2
        finally:
            worker.stop()
            bus.close()

    def test_watching_a_camera_twice_is_harmless(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            worker.watch("cam-a")
            assert worker.stats["cameras"] == 1
        finally:
            worker.stop()
            bus.close()

    def test_a_worker_can_be_given_a_camera_before_it_starts(self):
        """`start()` returns early on an empty camera list, so a worker built
        with none must still come alive when one is assigned."""
        bus = FrameBus()
        worker = Counter(bus, [])
        worker.start()
        try:
            worker.watch("cam-a")
            publish(bus, "cam-a")

            wait_until(lambda: worker.seen.get("cam-a", 0) > 0)
        finally:
            worker.stop()
            bus.close()

    def test_unwatching_stops_that_camera(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            publish(bus, "cam-a")
            wait_until(lambda: worker.seen.get("cam-a", 0) > 0)

            worker.unwatch("cam-a")
            # Wait for the THREAD to let go, not merely for the list to lose
            # the camera. `unwatch` sets a flag and returns, so the two are
            # not the same instant.
            wait_until(lambda: worker.closed)
            before = worker.seen["cam-a"]

            publish(bus, "cam-a", 5)
            time.sleep(0.2)
            assert worker.seen["cam-a"] == before
        finally:
            worker.stop()
            bus.close()

    def test_unwatching_one_camera_leaves_the_others_running(self):
        """The isolation assertion. Rule 9 in one test."""
        bus = FrameBus()
        worker = Counter(bus, ["cam-a", "cam-b"])
        worker.start()
        try:
            publish(bus, "cam-a")
            publish(bus, "cam-b")
            wait_until(lambda: worker.seen.get("cam-b", 0) > 0)

            worker.unwatch("cam-a")
            wait_until(lambda: not worker.serves("cam-a"))

            before = worker.seen["cam-b"]
            publish(bus, "cam-b", 5)
            wait_until(lambda: worker.seen["cam-b"] > before)
        finally:
            worker.stop()
            bus.close()

    def test_the_close_hook_runs_on_the_cameras_own_thread(self):
        """Not on the caller's.

        `ZonesWorker.set_restricted` documents why: closing a scene from the
        API thread, while the camera's thread was mid-`analyse`, made that
        thread open a second scene whose clip replaced the first one's.
        """
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            publish(bus, "cam-a")
            wait_until(lambda: worker.seen.get("cam-a", 0) > 0)

            worker.unwatch("cam-a")
            wait_until(lambda: worker.closed)

            camera_id, thread_name = worker.closed[0]
            assert camera_id == "cam-a"
            assert thread_name == "counter-cam-a"
            assert thread_name != threading.current_thread().name
        finally:
            worker.stop()
            bus.close()

    def test_unwatching_forgets_that_cameras_result(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            publish(bus, "cam-a")
            wait_until(lambda: worker.result("cam-a") is not None)

            worker.unwatch("cam-a")
            wait_until(lambda: worker.result("cam-a") is None)
        finally:
            worker.stop()
            bus.close()

    def test_a_rewatched_camera_works_again(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a"])
        worker.start()
        try:
            worker.unwatch("cam-a")
            wait_until(lambda: not worker.serves("cam-a"))

            worker.watch("cam-a")
            publish(bus, "cam-a")
            wait_until(lambda: worker.seen.get("cam-a", 0) > 0)
        finally:
            worker.stop()
            bus.close()

    def test_stop_still_stops_everything(self):
        bus = FrameBus()
        worker = Counter(bus, ["cam-a", "cam-b"])
        worker.start()
        try:
            worker.watch("cam-c")
            worker.stop()

            assert not worker._threads
        finally:
            bus.close()


# ---------------------------------------------------------------------------
# the feature list governs — for all seven, not four
# ---------------------------------------------------------------------------

class TestTheFeatureListGoverns:
    """Three features used to ignore the camera's `features:` list entirely.

    `_start_weapons` and `_start_zones` both took `[c.id for c in roster if
    c.enabled]`, so knife detection and restricted-area watching ran on every
    camera whether or not anybody asked. `BagWatch` took no camera list at
    all. For those three the list was decoration.

    These tests read the camera list the worker was actually constructed with,
    which is the thing that decides what gets analysed.
    """

    def roster(self):
        return [
            camera("cam-knife", ["counting", "weapons"]),
            camera("cam-plain", ["counting"]),
            camera("cam-zone", ["intrusion"]),
            camera("cam-bag", ["lostitems"]),
            camera("cam-off", ["weapons", "intrusion"], enabled=False),
        ]

    def test_knives_only_on_cameras_that_asked(self):
        from vg.api.app import _weapons_cameras

        assert _weapons_cameras(self.roster()) == ["cam-knife"]

    def test_restricted_areas_only_on_cameras_that_asked(self):
        from vg.api.app import _zone_cameras

        assert _zone_cameras(self.roster()) == ["cam-zone"]

    def test_bag_search_only_on_cameras_that_asked(self):
        from vg.api.app import _lost_cameras

        assert _lost_cameras(self.roster()) == ["cam-bag"]

    def test_a_disabled_camera_is_never_included(self):
        from vg.api.app import _lost_cameras, _weapons_cameras, _zone_cameras

        roster = self.roster()
        for select in (_weapons_cameras, _zone_cameras, _lost_cameras):
            assert "cam-off" not in select(roster)

    def test_bag_search_refuses_interest_on_an_unassigned_camera(self):
        """The overlay poll is what starts bag work, so this is the real gate."""
        from vg.features.lostbag import BagWatch

        watch = BagWatch(registry=None, detector=None, clock=None,
                         cameras={"cam-bag"})

        watch.note_interest("cam-plain")
        assert watch.watching == []

        watch.note_interest("cam-bag")
        assert watch.watching == ["cam-bag"]

    def test_unwatching_bag_search_drops_its_boxes_too(self):
        from vg.features.lostbag import BagWatch

        watch = BagWatch(registry=None, detector=None, clock=None,
                         cameras={"cam-bag"})
        watch.note_interest("cam-bag")

        watch.unwatch("cam-bag")

        assert not watch.serves("cam-bag")
        assert watch.watching == []


# ---------------------------------------------------------------------------
# a camera added through the API is analysed by a RUNNING worker
# ---------------------------------------------------------------------------
#
# The unit tests above prove `watch`/`unwatch` move one camera on one worker.
# This proves the wiring in between: that `LiveStore._apply_features` reads the
# camera's feature list and reaches the workers `LiveStore` actually holds.
# Without it, every piece could pass on its own while a camera added from the
# console was still analysed by nothing until a restart - which is the bug the
# whole slice exists to remove.

class Recorder(FeatureWorker[int]):
    """A worker that only records which cameras it was told to serve."""

    def __init__(self, bus, cameras):
        super().__init__("recorder", bus, cameras, rate_hz=0)

    def analyse(self, frame) -> int:
        return 0


def store_with_workers(tmp_path, **workers):
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.ingest.registry import CameraRegistry
    from vg.ingest.store import CameraStore

    registry = CameraRegistry([])
    return LiveStore(
        vgconfig.load(), registry,
        cameras=CameraStore(tmp_path / "roster.db"), **workers)


class TestAddingACameraReachesTheWorkers:
    def test_a_new_camera_is_picked_up_without_a_restart(self, tmp_path):
        """P13-FR-014, at the level that actually matters."""
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives = Recorder(bus, [])
        knives.start()
        store = store_with_workers(tmp_path, weapons=knives)
        try:
            assert not knives.serves("cam-new")

            store.add_camera(S.AddCameraRequest(
                name="New", source="webcam:9", features=["weapons"]))

            assert knives.serves("cam-new"), (
                "the camera was saved but no worker was told about it")
        finally:
            knives.stop()
            store.cameras.close()
            bus.close()

    def test_a_feature_not_chosen_is_not_wired_up(self, tmp_path):
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives = Recorder(bus, [])
        knives.start()
        store = store_with_workers(tmp_path, weapons=knives)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Plain", source="webcam:9", features=["counting"]))

            assert not knives.serves("cam-plain")
        finally:
            knives.stop()
            store.cameras.close()
            bus.close()

    def test_taking_a_feature_away_unwires_it(self, tmp_path):
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives = Recorder(bus, [])
        knives.start()
        store = store_with_workers(tmp_path, weapons=knives)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Both", source="webcam:9",
                features=["counting", "weapons"]))
            assert knives.serves("cam-both")

            store.edit_camera("cam-both", S.EditCameraRequest(
                features=["counting"]))

            assert not knives.serves("cam-both")
        finally:
            knives.stop()
            store.cameras.close()
            bus.close()

    def test_removing_a_camera_unwires_every_feature(self, tmp_path):
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives, zones = Recorder(bus, []), Recorder(bus, [])
        knives.start()
        zones.start()
        store = store_with_workers(tmp_path, weapons=knives, zones=zones)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Doomed", source="webcam:9",
                features=["weapons", "intrusion"]))
            assert knives.serves("cam-doomed") and zones.serves("cam-doomed")

            store.remove_camera("cam-doomed")

            assert not knives.serves("cam-doomed")
            assert not zones.serves("cam-doomed")
        finally:
            knives.stop()
            zones.stop()
            store.cameras.close()
            bus.close()

    def test_one_cameras_change_leaves_another_camera_alone(self, tmp_path):
        """Rule 9, across cameras rather than across features."""
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives = Recorder(bus, [])
        knives.start()
        store = store_with_workers(tmp_path, weapons=knives)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Keep", source="webcam:8", features=["weapons"]))
            store.add_camera(S.AddCameraRequest(
                name="Drop", source="webcam:9", features=["weapons"]))

            store.remove_camera("cam-drop")

            assert knives.serves("cam-keep"), "the other camera was collateral"
        finally:
            knives.stop()
            store.cameras.close()
            bus.close()

    def test_the_identity_tier_is_a_move_not_a_gap(self, tmp_path):
        """A camera must always be served by exactly one recognition tier.

        `_start_recognition` puts a camera in the identity tier when
        `c.faces or "attendance" in c.features`, and patrol takes every other
        enabled camera. So the move is exercised from a camera that has
        NEITHER - `counting` only, which patrol serves - to one marked
        `faces`, which the identity tier takes over.

        The order matters: watch the new tier before unwatching the old, or
        there is an instant where neither is looking at this camera.
        """
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        identity, patrol = Recorder(bus, []), Recorder(bus, [])
        identity.start()
        patrol.start()
        store = store_with_workers(tmp_path, recogniser=identity, patrol=patrol)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Hall", source="webcam:9", features=["counting"]))
            assert patrol.serves("cam-hall")
            assert not identity.serves("cam-hall")

            store.edit_camera("cam-hall", S.EditCameraRequest(faces=True))

            assert identity.serves("cam-hall")
            assert not patrol.serves("cam-hall")

            # And back again, so the move works in both directions.
            store.edit_camera("cam-hall", S.EditCameraRequest(faces=False))

            assert patrol.serves("cam-hall")
            assert not identity.serves("cam-hall")
        finally:
            identity.stop()
            patrol.stop()
            store.cameras.close()
            bus.close()

    def test_attendance_alone_is_enough_for_the_identity_tier(self, tmp_path):
        """`faces` and `attendance` both select it, as `_start_recognition` does.

        Pinned because the two look like they might mean different things, and
        a camera silently landing in the patrol tier would be recognised at a
        lower rate against an easier bar with nothing to say so.
        """
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        identity, patrol = Recorder(bus, []), Recorder(bus, [])
        identity.start()
        patrol.start()
        store = store_with_workers(tmp_path, recogniser=identity, patrol=patrol)
        try:
            store.add_camera(S.AddCameraRequest(
                name="Door", source="webcam:9", features=["attendance"]))

            assert identity.serves("cam-door")
            assert not patrol.serves("cam-door")
        finally:
            identity.stop()
            patrol.stop()
            store.cameras.close()
            bus.close()

    def test_a_feature_whose_worker_is_absent_still_adds_the_camera(self, tmp_path):
        """Rule 8 at the moment of assignment, and rule 9 alongside it."""
        from vg.api import schemas as S
        from vg.ingest.framebus import FrameBus

        bus = FrameBus()
        knives = Recorder(bus, [])
        knives.start()
        store = store_with_workers(tmp_path, weapons=knives)
        # Bag search did not start on this engine.
        store.lost_error = "The bag model file is missing."
        try:
            added = store.add_camera(S.AddCameraRequest(
                name="Mixed", source="webcam:9",
                features=["weapons", "lostitems"]))

            assert added.id == "cam-mixed", "the camera is still added"
            assert knives.serves("cam-mixed"), "the feature that CAN run does"
        finally:
            knives.stop()
            store.cameras.close()
            bus.close()
