"""What every feature worker has in common.

A worker subscribes to the frame bus for the cameras it serves, runs at its own
rate, and keeps its latest result per camera. Nothing else in the system knows
or cares what a worker does with a frame.

The rule that this file exists to enforce: **a feature must not depend on
another feature being switched on.** The first version of this system ran
person detection inside the recognition worker, so a camera configured for
counting alone was processed by nothing at all — counting silently required
face recognition. Features share *models*, never *workers*.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar

from vg.ingest.framebus import FrameBus
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

R = TypeVar("R")


@dataclass
class Result(Generic[R]):
    """One worker's latest output for one camera."""

    camera_id: str
    at: datetime
    payload: R
    inference_ms: float = 0.0

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(timezone.utc)) - self.at).total_seconds()


class FeatureWorker(ABC, Generic[R]):
    """A feature running over the live frame bus.

    Subclasses implement `analyse(frame)`. Everything else — threading, rate
    limiting, on-demand boost, result freshness — is handled here so each
    feature is one small file with no concurrency code in it.
    """

    # Results older than this are treated as absent. A box or a count from
    # four seconds ago is not a description of what the camera sees now, and
    # serving it as though it were is the same lie as a stale frame.
    RESULT_TTL_SECONDS = 3.0

    # How long a camera stays boosted after someone shows interest in it.
    BOOST_TTL_SECONDS = 2.0

    def __init__(
        self,
        name: str,
        bus: FrameBus,
        cameras: list[str],
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
    ) -> None:
        self.name = name
        self.bus = bus
        self.cameras = list(cameras)
        self.interval = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self.boost_interval = 1.0 / boost_hz if boost_hz > 0 else 0.0

        self._results: dict[str, Result[R]] = {}
        self._boost_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

        self.frames_processed = 0

    # -- what a feature implements -----------------------------------------

    @abstractmethod
    def analyse(self, frame: Frame) -> R:
        """Do the work for one frame and return this feature's result."""

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._threads or not self.cameras:
            if not self.cameras:
                log.info("%s: no cameras assigned, not starting", self.name)
            return

        self._stop.clear()
        for camera_id in self.cameras:
            thread = threading.Thread(
                target=self._run, args=(camera_id,),
                name=f"{self.name}-{camera_id}", daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        log.info("%s running on %s", self.name, self.cameras)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3.0)
        self._threads.clear()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- the loop -----------------------------------------------------------

    def _run(self, camera_id: str) -> None:
        subscription = self.bus.subscribe(camera_id, maxsize=1)
        next_due = 0.0
        try:
            while not self._stop.is_set():
                frame = subscription.get(timeout=0.5)
                if frame is None:
                    continue

                now = time.monotonic()
                if now < next_due:
                    continue
                # Read the interval every frame so a boost takes effect on the
                # next one rather than at the next restart.
                next_due = now + self._interval_for(camera_id)

                started = time.perf_counter()
                try:
                    payload = self.analyse(frame)
                except Exception:
                    # One bad frame must not kill the feature for that camera.
                    log.exception("%s failed on %s", self.name, camera_id)
                    continue

                result = Result(
                    camera_id=frame.camera_id,
                    at=frame.captured_at,
                    payload=payload,
                    inference_ms=(time.perf_counter() - started) * 1000,
                )
                with self._lock:
                    self._results[frame.camera_id] = result
                self.frames_processed += 1
        finally:
            self.bus.unsubscribe(subscription)

    # -- demand-driven rate -------------------------------------------------

    def note_interest(self, camera_id: str) -> None:
        """Somebody is watching; run this camera faster for a moment.

        Expires on its own, so there is nothing to release and no way to leak
        a boost if the viewer closes the page mid-poll.
        """
        with self._lock:
            self._boost_until[camera_id] = time.monotonic() + self.BOOST_TTL_SECONDS

    def _interval_for(self, camera_id: str) -> float:
        with self._lock:
            until = self._boost_until.get(camera_id, 0.0)
        return self.boost_interval if time.monotonic() < until else self.interval

    # -- reads --------------------------------------------------------------

    def result(self, camera_id: str) -> Result[R] | None:
        """Latest result, or None if it is stale or the camera is not served."""
        with self._lock:
            result = self._results.get(camera_id)
        if result is None:
            return None
        return None if result.age_seconds() > self.RESULT_TTL_SECONDS else result

    def payload(self, camera_id: str) -> R | None:
        result = self.result(camera_id)
        return result.payload if result else None

    def serves(self, camera_id: str) -> bool:
        return camera_id in self.cameras

    @property
    def stats(self) -> dict:
        with self._lock:
            latest = [r.inference_ms for r in self._results.values()]
        return {
            "name": self.name,
            "cameras": len(self.cameras),
            "frames_processed": self.frames_processed,
            "last_inference_ms": round(max(latest), 1) if latest else 0.0,
        }
