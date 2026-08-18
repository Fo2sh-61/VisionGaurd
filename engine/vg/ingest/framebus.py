"""Fan one camera's frames out to everything that wants them.

Decode once, use many times. At 208 cameras this is not an optimisation — a
frame decoded separately for person detection, weapons and counting is three
times the decode cost for identical pixels, and decode is the first wall we hit.

The rule that matters here: **a slow consumer must never stall ingest.** If the
weapons model takes 300 ms on a frame while the camera delivers every 200 ms,
the queue must drop old frames rather than grow. Analytics want the most recent
frame, not every frame — a backlog is worse than a gap, because it means every
detection is reported late.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable, Iterator

from vg.ingest.source import Frame

log = logging.getLogger(__name__)


class Subscription:
    """A bounded, drop-oldest view of one camera's frames.

    Not a `queue.Queue`: when full, that either blocks the producer or raises.
    Both are wrong here. This drops the oldest frame instead and counts it, so
    the cost of a slow consumer is visible rather than silent.
    """

    def __init__(self, camera_id: str | None, maxsize: int = 2) -> None:
        self.camera_id = camera_id
        self.maxsize = maxsize
        self.dropped = 0
        self._frames: deque[Frame] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._closed = False

    def _offer(self, frame: Frame) -> None:
        with self._ready:
            if self._closed:
                return
            if len(self._frames) == self.maxsize:
                self.dropped += 1
            self._frames.append(frame)
            self._ready.notify()

    def get(self, timeout: float | None = 1.0) -> Frame | None:
        """Next frame, or None on timeout or close."""
        with self._ready:
            if not self._frames and not self._closed:
                self._ready.wait(timeout)
            if self._frames:
                return self._frames.popleft()
            return None

    def frames(self) -> Iterator[Frame]:
        while not self._closed:
            frame = self.get()
            if frame is not None:
                yield frame

    def close(self) -> None:
        with self._ready:
            self._closed = True
            self._ready.notify_all()

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FrameBus:
    """In-process pub/sub for frames.

    Subscribers filtered by camera, or `None` for every camera. Publishing is
    non-blocking regardless of how many subscribers there are or how slow they
    happen to be.
    """

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._callbacks: list[tuple[str | None, Callable[[Frame], None]]] = []
        self._lock = threading.Lock()

    def subscribe(self, camera_id: str | None = None, maxsize: int = 2) -> Subscription:
        sub = Subscription(camera_id, maxsize)
        with self._lock:
            self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with self._lock:
            if sub in self._subscriptions:
                self._subscriptions.remove(sub)

    def on_frame(
        self, callback: Callable[[Frame], None], camera_id: str | None = None
    ) -> None:
        """Register a synchronous callback.

        Runs on the capture thread, so it must be fast. Anything doing real work
        — inference, disk writes — belongs on a `Subscription` with its own
        thread instead.
        """
        with self._lock:
            self._callbacks.append((camera_id, callback))

    def publish(self, frame: Frame) -> None:
        with self._lock:
            subs = [
                s for s in self._subscriptions
                if s.camera_id is None or s.camera_id == frame.camera_id
            ]
            callbacks = [
                cb for cam, cb in self._callbacks
                if cam is None or cam == frame.camera_id
            ]

        for sub in subs:
            sub._offer(frame)

        for callback in callbacks:
            try:
                callback(frame)
            except Exception:
                # One bad subscriber must not take down capture for everyone.
                log.exception("frame callback failed for %s", frame.camera_id)

    def close(self) -> None:
        with self._lock:
            for sub in self._subscriptions:
                sub.close()
            self._subscriptions.clear()
            self._callbacks.clear()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)
