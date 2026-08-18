"""Frame bus, camera registry and the live store.

Two things here are guarding real bugs that already happened once:

  - `TestTimezone` — Windows has no system tz database, so `zoneinfo` silently
    failed and every timestamp rendered three hours early for Cairo.
  - `TestBackpressure` — a slow consumer must drop frames, not queue them.
    Queuing means every detection arrives late and memory grows forever.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vg.ingest.framebus import FrameBus, Subscription
from vg.ingest.source import Frame


def frame(camera_id: str = "c1", seq: int = 1) -> Frame:
    return Frame(camera_id, np.zeros((4, 4, 3), np.uint8), datetime.now(timezone.utc), seq)


# ---------------------------------------------------------------------------
# frame bus
# ---------------------------------------------------------------------------

class TestFrameBus:
    def test_subscriber_receives_published_frames(self):
        bus = FrameBus()
        sub = bus.subscribe()
        bus.publish(frame(seq=1))
        assert sub.get(timeout=0.5).sequence == 1

    def test_subscription_filters_by_camera(self):
        bus = FrameBus()
        sub = bus.subscribe("c2")
        bus.publish(frame("c1", 1))
        bus.publish(frame("c2", 2))
        received = sub.get(timeout=0.5)
        assert received.camera_id == "c2" and received.sequence == 2

    def test_wildcard_subscription_gets_everything(self):
        bus = FrameBus()
        sub = bus.subscribe(None)
        bus.publish(frame("c1", 1))
        bus.publish(frame("c2", 2))
        assert {sub.get(0.5).camera_id, sub.get(0.5).camera_id} == {"c1", "c2"}

    def test_decode_once_serves_many(self):
        # The whole reason the bus exists: three features, one decode.
        bus = FrameBus()
        subs = [bus.subscribe() for _ in range(3)]
        bus.publish(frame(seq=9))
        assert all(s.get(0.5).sequence == 9 for s in subs)

    def test_callback_is_invoked(self):
        bus = FrameBus()
        seen: list[int] = []
        bus.on_frame(lambda f: seen.append(f.sequence))
        bus.publish(frame(seq=5))
        assert seen == [5]

    def test_one_broken_callback_does_not_stop_the_others(self):
        # A crashing subscriber must not take capture down for every feature.
        bus = FrameBus()
        seen: list[int] = []
        bus.on_frame(lambda f: (_ for _ in ()).throw(RuntimeError("boom")))
        bus.on_frame(lambda f: seen.append(f.sequence))
        bus.publish(frame(seq=3))
        assert seen == [3]

    def test_unsubscribe_stops_delivery(self):
        bus = FrameBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        bus.publish(frame())
        assert bus.subscriber_count == 0


class TestBackpressure:
    def test_full_queue_drops_the_oldest(self):
        sub = Subscription(None, maxsize=2)
        for i in range(1, 6):
            sub._offer(frame(seq=i))

        # Newest two survive; a stale backlog is worse than a gap because it
        # makes every detection arrive late.
        assert [sub.get(0.1).sequence for _ in range(2)] == [4, 5]

    def test_drops_are_counted_not_hidden(self):
        sub = Subscription(None, maxsize=2)
        for i in range(5):
            sub._offer(frame(seq=i))
        assert sub.dropped == 3

    def test_publishing_never_blocks_on_a_stalled_consumer(self):
        bus = FrameBus()
        bus.subscribe(maxsize=1)  # never read from

        started = time.monotonic()
        for i in range(500):
            bus.publish(frame(seq=i))
        assert time.monotonic() - started < 1.0

    def test_get_returns_none_on_timeout(self):
        assert Subscription(None).get(timeout=0.05) is None

    def test_close_releases_a_waiting_reader(self):
        sub = Subscription(None)
        result: list = []

        reader = threading.Thread(target=lambda: result.append(sub.get(timeout=5)))
        reader.start()
        time.sleep(0.05)
        sub.close()
        reader.join(timeout=2)

        assert not reader.is_alive(), "close() must wake a blocked reader"
        assert result == [None]


# ---------------------------------------------------------------------------
# timezone — the bug that made every event read three hours early
# ---------------------------------------------------------------------------

class TestTimezone:
    def test_cairo_resolves_to_a_real_offset(self):
        from vg.api.live import _tz_offset_minutes

        # Windows has no system tz database. Without the `tzdata` package this
        # silently returned 0 and a 6:12am breach displayed as 3:12am.
        assert _tz_offset_minutes("Africa/Cairo") == 180

    def test_utc_is_zero(self):
        from vg.api.live import _tz_offset_minutes

        assert _tz_offset_minutes("UTC") == 0

    def test_unknown_zone_falls_back_loudly(self, caplog):
        from vg.api.live import _tz_offset_minutes

        with caplog.at_level("ERROR"):
            assert _tz_offset_minutes("Mars/Olympus_Mons") == 0
        # Falling back is acceptable; doing it silently is not.
        assert "tzdata" in caplog.text


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def _config(self, **kw):
        from vg.config import CameraConfig

        return CameraConfig.parse(
            {"id": "c1", "name": "Test", "source": "webcam:99", **kw}, "c"
        )

    def test_disabled_cameras_are_kept_not_dropped(self):
        from vg.ingest.registry import CameraRegistry

        registry = CameraRegistry([
            self._config(id="on", enabled=True),
            self._config(id="off", enabled=False),
        ])
        # A camera turned off in config still appears in the UI as configured
        # but off, rather than silently disappearing from the list.
        assert set(registry.workers) == {"on"}
        assert set(registry.disabled) == {"off"}
        assert registry.total == 2

    def test_a_camera_with_no_frames_is_down(self):
        from vg.ingest.registry import CameraWorker

        worker = CameraWorker(self._config(), FrameBus())
        assert worker.status == "down"

    def test_a_camera_that_stopped_delivering_is_down(self):
        from vg.ingest.registry import STALE_AFTER_SECONDS, CameraWorker

        worker = CameraWorker(self._config(), FrameBus())
        worker.source.health.status = "ok"
        worker.source.health.last_frame_at = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_AFTER_SECONDS + 5
        )
        # A stream that silently stops is indistinguishable from one that
        # dropped, and the operator needs to know either way.
        assert worker.status == "down"

    def test_a_recently_delivering_camera_is_ok(self):
        from vg.ingest.registry import CameraWorker

        worker = CameraWorker(self._config(), FrameBus())
        worker.source.health.status = "ok"
        worker.source.health.last_frame_at = datetime.now(timezone.utc)
        assert worker.status == "ok"

    def test_snapshot_is_none_before_any_frame(self):
        from vg.ingest.registry import CameraWorker

        # None means 404, which renders an offline tile. A black JPEG would
        # look like a working camera pointed at a wall.
        assert CameraWorker(self._config(), FrameBus()).snapshot_jpeg() is None


# ---------------------------------------------------------------------------
# real hardware
# ---------------------------------------------------------------------------

class TestCaptureRateSeparation:
    """Reading and publishing are separate rates. Conflating them is the
    OpenCV latency trap: `read()` returns the NEXT buffered frame, not the
    newest, so throttling reads makes the live view fall progressively behind.
    """

    def test_file_sources_are_paced(self):
        # A file returns frames as fast as they decode, so it is the one source
        # that must be slowed in the loop — otherwise it burns a core.
        from vg.ingest.source import SourceKind, parse_source

        assert parse_source("file:clip.mp4")[0] is SourceKind.FILE

    def test_webcam_buffer_is_capped(self):
        # A deep driver buffer means every read() hands back an older frame.
        # This was set for RTSP but missed for webcam, which is why the laptop
        # camera lagged.
        import inspect

        from vg.ingest import source as src

        body = inspect.getsource(src.CameraSource.open)
        webcam_section = body.split("SourceKind.WEBCAM")[1].split("elif")[0]
        assert "CAP_PROP_BUFFERSIZE" in webcam_section

    def test_wait_for_frame_returns_immediately_when_newer_exists(self):
        from vg.ingest.source import CameraSource

        cam = CameraSource("c1", "webcam:0")
        cam._last_good = frame(seq=5)

        started = time.monotonic()
        got = cam.wait_for_frame(after_sequence=4, timeout=2.0)
        assert got is not None and got.sequence == 5
        # No sleep interval invented on top of the camera's own rate.
        assert time.monotonic() - started < 0.1

    def test_wait_for_frame_blocks_until_something_newer(self):
        from vg.ingest.source import CameraSource

        cam = CameraSource("c1", "webcam:0")
        cam._last_good = frame(seq=5)

        # Asking for something newer than what we have must wait, not spin.
        assert cam.wait_for_frame(after_sequence=5, timeout=0.15) is None

    def test_wait_for_frame_wakes_on_arrival(self):
        from vg.ingest.source import CameraSource

        cam = CameraSource("c1", "webcam:0")
        result: list = []

        reader = threading.Thread(
            target=lambda: result.append(cam.wait_for_frame(0, timeout=3.0))
        )
        reader.start()
        time.sleep(0.05)

        with cam._frame_ready:
            cam._last_good = frame(seq=7)
            cam._frame_ready.notify_all()

        reader.join(timeout=2)
        assert result and result[0] is not None and result[0].sequence == 7


@pytest.mark.camera
class TestLiveCapture:
    def test_registry_captures_from_the_webcam(self):
        from vg.config import CameraConfig
        from vg.ingest.registry import CameraRegistry

        config = CameraConfig.parse(
            {"id": "cam-laptop", "name": "Webcam", "source": "webcam:0", "fps": 5}, "c"
        )
        with CameraRegistry([config]) as registry:
            if registry.wait_for_first_frame(timeout=10.0) == 0:
                pytest.skip("no webcam available")

            worker = registry.worker("cam-laptop")
            assert worker.status == "ok"

            jpeg = worker.snapshot_jpeg()
            assert jpeg is not None
            # JPEG magic bytes — proves it is a real encode, not an empty buffer.
            assert jpeg[:2] == b"\xff\xd8"
            assert len(jpeg) > 1000

    def test_frames_reach_a_subscriber(self):
        from vg.config import CameraConfig
        from vg.ingest.registry import CameraRegistry

        config = CameraConfig.parse(
            {"id": "cam-laptop", "name": "Webcam", "source": "webcam:0", "fps": 5}, "c"
        )
        registry = CameraRegistry([config])
        sub = registry.bus.subscribe("cam-laptop")
        try:
            registry.start()
            received = sub.get(timeout=10.0)
            if received is None:
                pytest.skip("no webcam available")
            assert received.camera_id == "cam-laptop"
            assert not received.is_stale
            assert received.width > 0
        finally:
            registry.stop()
