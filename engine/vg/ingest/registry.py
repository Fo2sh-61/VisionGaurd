"""Every camera, running.

One capture thread per camera, each publishing to the shared `FrameBus`.
Threads (not asyncio) because OpenCV's `read()` is a blocking C call that
releases the GIL — the thread sits in native code while others run, which is
exactly the shape we want. At 208 cameras this becomes a process pool, but the
interface below does not have to change for that.

The registry is also what the API asks for camera state, so the honesty rules
about NO SIGNAL live here too: a camera that has dropped keeps returning its
last good frame, clearly marked, and never pretends to be current.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Iterable

import cv2

from vg.config import CameraConfig
from vg.ingest.framebus import FrameBus
from vg.ingest.source import CameraSource, Frame, SourceStatus

log = logging.getLogger(__name__)

# How long after the last real frame a camera is considered dark. Generous
# enough that a 5 fps camera missing a couple of frames is not an incident.
STALE_AFTER_SECONDS = 10.0


class CameraWorker:
    """One camera, one thread."""

    def __init__(self, config: CameraConfig, bus: FrameBus) -> None:
        self.config = config
        self.bus = bus
        self.source = CameraSource(
            config.id, config.source, target_fps=config.fps, rotate=config.rotate,
            live_capture=config.live_capture,
        )
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._jpeg_lock = threading.Lock()
        self._jpeg_key: tuple | None = None
        self._jpeg_cache: bytes | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"camera-{self.config.id}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        log.info("camera %s starting (%s)", self.config.id, self.source.redacted)
        try:
            # Unthrottled: the bus carries the camera's native rate and each
            # consumer samples it down to what it needs. Rate-limiting here
            # would cap every feature at one rate and make the enlarged view's
            # on-demand speed-up impossible — the frames simply would not exist.
            for frame in self.source.all_frames():
                if self._stop.is_set():
                    break
                # Stale frames are NOT published. Downstream features must not
                # re-detect the same person every second off a frozen frame and
                # raise an alert storm. The API still serves the stale frame for
                # display — that is a rendering concern, not a detection one.
                if not frame.is_stale:
                    self.bus.publish(frame)
        except Exception:
            log.exception("camera %s worker died", self.config.id)
        finally:
            self.source.close()
            log.info("camera %s stopped", self.config.id)

    def stop(self, timeout: float = 3.0) -> None:
        """Signal and wait. Convenience for callers stopping one camera."""
        self.request_stop()
        self.join(timeout)

    def request_stop(self) -> None:
        """Signal only — returns immediately.

        Split out from `stop()` so the registry can signal every camera at once
        and then wait on all of them against a single deadline. Signalling and
        joining in the same loop makes shutdown cost 3s *per camera*.
        """
        self._stop.set()
        self.source.stop()

    def join(self, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> SourceStatus:
        """`ok` | `down` | `auth`, matching the front end's SourceStatus.

        A camera whose last frame is older than the stale threshold is reported
        down even if the source has not noticed yet — a stream that silently
        stops delivering is indistinguishable from one that dropped, and the
        operator needs to know either way.
        """
        health = self.source.health
        if health.status != "ok":
            return health.status
        if health.last_frame_at is None:
            return "down"
        age = (datetime.now(timezone.utc) - health.last_frame_at).total_seconds()
        return "ok" if age <= STALE_AFTER_SECONDS else "down"

    def last_frame(self) -> Frame | None:
        return self.source.last_good_frame()

    def snapshot_jpeg(self, quality: int = 80, max_width: int = 1280) -> bytes | None:
        """Encode the last good frame as JPEG for the API.

        Cached per frame. Several tiles, a modal and a polling grid can all ask
        for the same camera within one frame interval, and JPEG encoding a
        1280px image is not free — at 208 cameras being polled once a second it
        is the difference between idle and saturated. The cache key is the
        frame sequence number, so a new frame invalidates it automatically.

        Returns None when nothing has ever been captured — the caller sends a
        404 and the UI draws an offline tile, rather than showing a black
        rectangle that looks like a working camera pointed at a wall.
        """
        frame = self.last_frame()
        if frame is None:
            return None

        key = (frame.sequence, quality, max_width)
        with self._jpeg_lock:
            if self._jpeg_key == key:
                return self._jpeg_cache

        encoded = self.encode_jpeg(frame, quality, max_width)
        with self._jpeg_lock:
            self._jpeg_key = key
            self._jpeg_cache = encoded
        return encoded

    @staticmethod
    def encode_jpeg(frame: Frame, quality: int = 80, max_width: int = 1280) -> bytes | None:
        """Encode a specific frame, so a streaming caller can encode the exact
        frame it waited for instead of re-reading whatever is current."""
        image = frame.image
        if image.shape[1] > max_width:
            scale = max_width / image.shape[1]
            image = cv2.resize(
                image,
                (max_width, int(image.shape[0] * scale)),
                interpolation=cv2.INTER_AREA,
            )

        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buffer.tobytes() if ok else None


class CameraRegistry:
    """All the cameras, and the single place the API asks about them."""

    def __init__(self, cameras: Iterable[CameraConfig], bus: FrameBus | None = None) -> None:
        self.bus = bus or FrameBus()
        self.workers: dict[str, CameraWorker] = {
            c.id: CameraWorker(c, self.bus) for c in cameras if c.enabled
        }
        # Disabled cameras are kept so the UI can show them as configured but
        # off, rather than having them vanish from the list.
        self.disabled: dict[str, CameraConfig] = {
            c.id: c for c in cameras if not c.enabled
        }
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        for worker in self.workers.values():
            worker.start()
        self._started = True
        log.info("registry started with %d camera(s)", len(self.workers))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every camera within one total time budget.

        Signalling and joining are separate passes. Doing both in one loop
        meant each camera got its own 3s join while stuck in a blocking cv2
        read — two cameras took 6s, ten took 30s, and it looked like a hang.
        Now `timeout` is the budget for all of them together, regardless of
        count. Capture threads are daemons, so any straggler dies with the
        process rather than keeping it alive.
        """
        for worker in self.workers.values():
            worker.request_stop()

        deadline = time.monotonic() + timeout
        for worker in self.workers.values():
            worker.join(max(0.0, deadline - time.monotonic()))

        self.bus.close()
        self._started = False

    def __enter__(self) -> "CameraRegistry":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def worker(self, camera_id: str) -> CameraWorker | None:
        return self.workers.get(camera_id)

    # -- runtime changes ----------------------------------------------------

    def add(self, config: CameraConfig) -> CameraWorker | None:
        """Start watching a camera without restarting the engine.

        Adding a camera should not interrupt the other 207. Replacing an
        existing id stops the old worker first so two threads never hold the
        same device.
        """
        self.remove(config.id)

        if not config.enabled:
            self.disabled[config.id] = config
            return None

        worker = CameraWorker(config, self.bus)
        self.workers[config.id] = worker
        if self._started:
            worker.start()
        log.info("camera %s added to the registry", config.id)
        return worker

    def remove(self, camera_id: str) -> bool:
        """Stop watching a camera and release its device."""
        removed = False

        worker = self.workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()
            removed = True

        if self.disabled.pop(camera_id, None) is not None:
            removed = True

        if removed:
            log.info("camera %s removed from the registry", camera_id)
        return removed

    def configs(self) -> list[CameraConfig]:
        """Every camera currently known, enabled or not."""
        return [w.config for w in self.workers.values()] + list(self.disabled.values())

    def wait_for_first_frame(self, timeout: float = 10.0) -> int:
        """Block until every camera has produced a frame, or the timeout.

        Startup convenience: without it, the first request after boot gets
        404s from every snapshot endpoint and the console looks broken when it
        is merely young. Returns how many cameras came up.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = sum(1 for w in self.workers.values() if w.last_frame() is not None)
            if ready == len(self.workers):
                return ready
            time.sleep(0.1)
        return sum(1 for w in self.workers.values() if w.last_frame() is not None)

    @property
    def online(self) -> int:
        return sum(1 for w in self.workers.values() if w.status == "ok")

    @property
    def total(self) -> int:
        return len(self.workers) + len(self.disabled)
