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
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

from vg.infer.shared import take_borrowed_ms
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
    #: What THIS worker did for this frame, excluding time spent in the shared
    #: person pass. A worker that waited 13 ms for another worker's detection
    #: and then read the cache did not run a 13 ms model.
    inference_ms: float = 0.0
    #: What it borrowed from the shared pass - waiting, computing or reading
    #: the cache. Kept beside `inference_ms` rather than folded in, so the
    #: pass can be charged once, on its own row, and never per worker.
    shared_ms: float = 0.0

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

    # How far back "what is this worker doing" looks. Short enough to be a
    # reading of now rather than an average of the afternoon; long enough
    # that a 2/sec camera has several frames in it.
    WINDOW_SECONDS = 5.0

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

        # Per camera, because the rate belongs to the camera and not to the
        # worker. Until 2 Sep 2026 there was ONE rate for the whole worker —
        # `min(fps)` across its cameras, fixed at construction — with two
        # consequences nobody could see: turning one camera down to 2/sec
        # quietly turned every other camera on that worker down with it, and
        # editing the rate in the console changed the *decode* rate and
        # nothing else, so the models kept running at the old rate until
        # somebody restarted the engine. `self.interval` remains the fallback
        # for a camera nobody has set a rate for.
        self._rates: dict[str, float] = {}

        # Which processor this worker's model actually loaded onto — "cpu",
        # "cuda:0". Set by the subclass FROM THE MODEL, never guessed here:
        # System Health costs GPU and CPU against separate budgets, and a
        # worker charged to the wrong pool is worse than one the page admits
        # it cannot place. None means "did not say", and is rendered as that.
        self.device: str | None = None

        self._results: dict[str, Result[R]] = {}
        self._boost_until: dict[str, float] = {}
        self._lock = threading.Lock()
        # Keyed by camera, not a list, because `unwatch` has to find the one
        # thread for one camera.
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        # Per camera, because `self._stop` is worker-wide and cannot say
        # "stop this one". `stop()` still sets the worker-wide event.
        self._drop: dict[str, threading.Event] = {}
        # Whether `start()` has been called. `watch()` needs it: before start
        # it only records the camera, after start it also spawns the thread.
        self._started = False
        # The live subscriptions, per camera. Kept so System Health can read
        # how deep this worker's queue is and how many frames the bus threw
        # away while it was busy. Both counters already existed on the
        # subscription; nothing was reachable to ask.
        self._subs: dict[str, object] = {}

        self.frames_processed = 0

        # What this worker actually did lately: (when, own ms, borrowed ms)
        # per analysed frame, kept for WINDOW_SECONDS. A projection
        # multiplies a configured rate by a cost; this is the reading it is
        # checked against - milliseconds really spent, per second of wall
        # clock, across every camera this worker serves.
        #
        # Double underscore, so Python mangles it to _FeatureWorker__load_window
        # and a subclass CANNOT reach it by accident. This was `_recent`, and
        # `vehicles.py` used the same obvious name for its own dict of plates
        # seen lately. The subclass won, `_run` called .append() on a dict, and
        # every vehicles thread died on its first frame - number plates were
        # never read, and nothing on screen said so. A feature is written by
        # copying another feature, so a name a subclass might reasonably pick
        # must be one it cannot take.
        self.__load_window: deque[tuple[float, float, float]] = deque()
        self._started_at = time.monotonic()

        # Cameras whose thread ended without anybody asking it to - no
        # `stop()`, no `unwatch()`. A dying thread takes itself out of
        # `_threads`, but its camera stays in `self.cameras`, and every other
        # counter then reads zero - exactly what an idle worker looks like.
        # That is how the vehicles worker sat dead for a whole day on 4-5 Sep
        # 2026 while System Health said "all keeping up". Double underscore
        # for the same reason as `__load_window`: a subclass cannot take it.
        self.__died_on: set[str] = set()

    # -- what a feature implements -----------------------------------------

    @abstractmethod
    def analyse(self, frame: Frame) -> R:
        """Do the work for one frame and return this feature's result."""

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._threads:
            return
        self._started = True
        self._stop.clear()
        if not self.cameras:
            # Not an error, and no longer final: `watch()` can bring this
            # worker to life later, when an operator assigns it a camera.
            log.info("%s: no cameras assigned, not starting a thread yet",
                     self.name)
            return

        for camera_id in list(self.cameras):
            self._spawn(camera_id)
        log.info("%s running on %s", self.name, self.cameras)

    def _spawn(self, camera_id: str) -> None:
        """One camera, one thread. Caller holds no lock."""
        thread = threading.Thread(
            target=self._run, args=(camera_id,),
            name=f"{self.name}-{camera_id}", daemon=True,
        )
        with self._lock:
            self._drop[camera_id] = threading.Event()
            self._threads[camera_id] = thread
            # A fresh thread for this camera. The last one dying is history.
            self.__died_on.discard(camera_id)
        thread.start()

    def watch(self, camera_id: str) -> None:
        """Serve a camera that was assigned after this worker started.

        Without this a camera added from the console streamed, appeared in the
        grid, and was analysed by nothing at all until somebody restarted the
        engine — which at site scale means interrupting every other camera to
        add one.
        """
        with self._lock:
            if camera_id in self.cameras:
                return
            self.cameras.append(camera_id)

        if self._started:
            self._spawn(camera_id)
        log.info("%s now watching %s", self.name, camera_id)

    def unwatch(self, camera_id: str) -> None:
        """Stop serving one camera. Every other camera is untouched.

        **Sets a flag and returns.** It does not close anything itself, and
        that is the whole point: `ZonesWorker.set_restricted` records what
        happens otherwise — closing a scene from the calling thread, while the
        camera's own thread was mid-`analyse` holding that scene, made it open
        a second one whose clip replaced the first. Switching a camera off
        destroyed the recording of the scene that was running.

        So the camera's own thread notices, runs `_closing`, and exits.
        """
        with self._lock:
            if camera_id not in self.cameras:
                return
            self.cameras.remove(camera_id)
            drop = self._drop.get(camera_id)
        if drop is not None:
            drop.set()
        log.info("%s no longer watching %s", self.name, camera_id)

    def _closing(self, camera_id: str) -> None:
        """Called on the camera's OWN thread, just before it lets go.

        Subclasses override this to close whatever they were holding for that
        camera — an open scene, a recording, a tracker. Never call it from
        anywhere else; see `unwatch`.
        """
        with self._lock:
            self._results.pop(camera_id, None)
            self._boost_until.pop(camera_id, None)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=3.0)
        with self._lock:
            self._threads.clear()
            self._drop.clear()
        self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- the loop -----------------------------------------------------------

    def _run(self, camera_id: str) -> None:
        subscription = self.bus.subscribe(camera_id, maxsize=1)
        with self._lock:
            self._subs[camera_id] = subscription
            dropped = self._drop.setdefault(camera_id, threading.Event())
        next_due = 0.0
        try:
            while not self._stop.is_set() and not dropped.is_set():
                frame = subscription.get(timeout=0.5)
                if frame is None:
                    continue
                # Checked again after the wait, not only at the top of the
                # loop: `get` blocks for half a second, so a camera unwatched
                # during that wait would otherwise get one more analysed
                # frame after it was switched off.
                if dropped.is_set() or self._stop.is_set():
                    break

                now = time.monotonic()
                if now < next_due:
                    continue
                # Read the interval every frame so a boost takes effect on the
                # next one rather than at the next restart.
                next_due = now + self._interval_for(camera_id)

                # Cleared first, so a frame that raised mid-pass cannot leave
                # its borrowed time to be blamed on the next one.
                take_borrowed_ms()
                started = time.perf_counter()
                try:
                    payload = self.analyse(frame)
                except Exception:
                    # One bad frame must not kill the feature for that camera.
                    log.exception("%s failed on %s", self.name, camera_id)
                    continue
                total_ms = (time.perf_counter() - started) * 1000
                shared_ms = take_borrowed_ms()

                result = Result(
                    camera_id=frame.camera_id,
                    at=frame.captured_at,
                    payload=payload,
                    # Own work only. Three workers reading one shared pass
                    # used to each report the pass, and the page added them.
                    inference_ms=max(0.0, total_ms - shared_ms),
                    shared_ms=shared_ms,
                )
                with self._lock:
                    self._results[frame.camera_id] = result
                    self.__load_window.append(
                        (time.monotonic(), result.inference_ms, result.shared_ms))
                self.frames_processed += 1
        finally:
            # On this camera's own thread, before it lets the subscription
            # go. Anything this worker was holding for this camera closes
            # here or not at all - see `unwatch`.
            try:
                self._closing(camera_id)
            except Exception:
                log.exception("%s failed closing %s", self.name, camera_id)
            with self._lock:
                self._subs.pop(camera_id, None)
                if self._drop.get(camera_id) is dropped:
                    self._drop.pop(camera_id, None)
                if self._threads.get(camera_id) is threading.current_thread():
                    self._threads.pop(camera_id, None)
                    # The loop only ends on its own when `stop()` or
                    # `unwatch()` asked it to. Neither did, so an exception
                    # killed it. Recorded under the same lock that took it
                    # out of `_threads`, so no read sees it gone but unsaid.
                    if not self._stop.is_set() and not dropped.is_set():
                        self.__died_on.add(camera_id)
            self.bus.unsubscribe(subscription)

    # -- demand-driven rate -------------------------------------------------

    def note_interest(self, camera_id: str) -> None:
        """Somebody is watching; run this camera faster for a moment.

        Expires on its own, so there is nothing to release and no way to leak
        a boost if the viewer closes the page mid-poll.
        """
        with self._lock:
            self._boost_until[camera_id] = time.monotonic() + self.BOOST_TTL_SECONDS

    def set_rate(self, camera_id: str, rate_hz: float) -> None:
        """How often this worker analyses one camera, from now on.

        Takes effect on the **next frame**, not at the next restart: the loop
        asks `_interval_for` every time round, so there is no thread to
        replace and nothing to reload. This is what makes the analytics rate
        on the camera form a real setting rather than a stored number.

        A rate of zero or less is refused rather than quietly meaning "every
        frame". Filling a machine is a decision, never an accident.
        """
        if rate_hz <= 0:
            raise ValueError(
                f"{self.name}: analytics rate must be greater than 0, "
                f"got {rate_hz}")
        with self._lock:
            self._rates[camera_id] = float(rate_hz)

    def rate_for(self, camera_id: str) -> float:
        """This camera's analytics rate, in frames per second."""
        with self._lock:
            return self._rate_locked(camera_id)

    def _rate_locked(self, camera_id: str) -> float:
        """Caller holds `self._lock`."""
        rate = self._rates.get(camera_id)
        if rate:
            return rate
        return 1.0 / self.interval if self.interval else 0.0

    def _interval_for(self, camera_id: str) -> float:
        with self._lock:
            until = self._boost_until.get(camera_id, 0.0)
            rate = self._rates.get(camera_id)
        if time.monotonic() < until:
            return self.boost_interval
        return (1.0 / rate) if rate else self.interval

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
        # Under the lock since `watch`/`unwatch` mutate the list. It was safe
        # to read unlocked only while the list never changed.
        with self._lock:
            return camera_id in self.cameras

    @property
    def stats(self) -> dict:
        with self._lock:
            latest = [r.inference_ms for r in self._results.values()]
            borrowed = [r.shared_ms for r in self._results.values()]
            subs = list(self._subs.values())

            # The reading. Own milliseconds over the last WINDOW_SECONDS,
            # divided by the seconds actually covered - a worker two seconds
            # old is not spread over five. Idle for the whole window reads
            # 0.0, which is then a true statement.
            now = time.monotonic()
            cutoff = now - self.WINDOW_SECONDS
            while self.__load_window and self.__load_window[0][0] < cutoff:
                self.__load_window.popleft()
            span = max(1.0, min(self.WINDOW_SECONDS, now - self._started_at))
            busy_ms = sum(own for _, own, _ in self.__load_window) / span
            analysed = len(self.__load_window) / span
            served = len(self.cameras)
            # What this worker asks of the machine every second: the sum of
            # its cameras' OWN rates, not one rate multiplied by a count.
            # Two cameras at 2/sec beside one at 5 is nine analysed frames a
            # second, and an average would understate the busy one.
            per_second = sum(self._rate_locked(c) for c in self.cameras)
            # Only cameras still served: one switched off since is not dead,
            # just no longer this worker's.
            died_on = sorted(c for c in self.__died_on if c in self.cameras)

        # Deepest queue and total drops across this worker's cameras. The
        # worst camera is the one worth naming: an average would hide a
        # single saturated stream behind nine idle ones.
        depth = max((len(s._frames) for s in subs), default=0)
        capacity = max((s.maxsize for s in subs), default=0)
        dropped = sum(s.dropped for s in subs)

        return {
            "name": self.name,
            "cameras": served,
            # The two figures a capacity projection is arithmetic over: how
            # many frames a second this worker is asked for, and what one of
            # them costs. Both are read here rather than re-derived anywhere
            # else, so the page and the loop can never disagree.
            "frames_per_second": round(per_second, 2),
            "device": self.device,
            "frames_processed": self.frames_processed,
            "last_inference_ms": round(max(latest), 1) if latest else 0.0,
            # What this worker borrowed from the shared person pass on its
            # last frame. Reported so it is visible, never added to the
            # figure above - the pass is charged once, elsewhere.
            "last_shared_ms": round(max(borrowed), 1) if borrowed else 0.0,
            # Measured, not projected: what this worker spent and how many
            # frames it got through, per second, over the window.
            "busy_ms_per_second": round(busy_ms, 1),
            "analysed_per_second": round(analysed, 2),
            "window_seconds": self.WINDOW_SECONDS,
            "queue_depth": depth,
            "queue_max": capacity,
            "frames_dropped": dropped,
            # Full AND dropping. A full queue on its own is a worker that
            # happened to be mid-frame; drops are what say it did not catch up.
            "behind": bool(capacity and depth >= capacity and dropped > 0),
            # Cameras whose thread has died. Always present, and empty when
            # none has, so a reader can tell "none died" from a worker that
            # cannot say at all (the key is missing).
            "died_on": died_on,
        }
