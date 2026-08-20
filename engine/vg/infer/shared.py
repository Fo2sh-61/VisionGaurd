"""One person-detection pass per camera per frame, shared by every feature.

This is finding F2 in `docs/PLAN.md`, and it is two bugs wearing one coat.

A camera configured with both `counting` and `track` gets two workers. Both
want people in the frame, and both used to ask the model themselves:

    PeopleWorker.analyse    -> detector.detect(frame.image)
    TrackingWorker.analyse  -> detector.raw_boxes(frame.image)

`app.py` hands both workers **the same `PersonDetector` instance**, and
`features/base.py` gives every feature its own thread per camera. So:

1. **The model runs twice on the same frame.** Half the GPU spent on that
   camera produces a number the engine already had.

2. **Two threads enter one model at once.** Ultralytics/torch predict is not
   documented as thread-safe, and the failure mode is not a crash — it is
   boxes from one camera's frame coming back for another's. Silently wrong
   detections are the worst possible outcome for a system whose whole promise
   is that what it shows is true.

`SharedDetection` fixes both. Features no longer hold a detector; they hold
this, and ask for a frame's detections. The first asker runs the model, the
second gets the same answer back.

**What is and is not deduplicated.** The key is `(camera_id, frame.sequence)`
— one exact frame. Two features analysing the same frame share one pass. Two
features that happen to pick up different frames each get their own, because
the alternative is handing back boxes that do not match the image they will be
drawn on, and a box in the wrong place is worse than a box computed twice.

The workers rate-limit independently (`base.py`), so alignment is common but
not guaranteed. Bug 2 is fixed unconditionally: the model lock means no two
threads are ever inside it, aligned or not.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from vg.infer.persons import DetectedPerson, PersonDetector


@dataclass
class _Cached:
    sequence: int
    boxes: object  # ultralytics Boxes, or None when the frame had none


class SharedDetection:
    """The one place a person detector is called.

    Wraps a `PersonDetector` so that no feature holds one directly. Every body
    feature goes through here, which is what makes "detect once" enforceable
    rather than a convention somebody remembers.
    """

    def __init__(self, detector: PersonDetector) -> None:
        self.detector = detector
        # Guards the model itself. Global rather than per-camera because there
        # is one model shared by every camera, so two cameras calling at once
        # is the same hazard as two features on one camera.
        self._model_lock = threading.Lock()
        # Guards the cache dict only. Held briefly, never across a model call.
        self._cache_lock = threading.Lock()
        self._cache: dict[str, _Cached] = {}
        # Per-camera, so the second feature to arrive waits for the first
        # instead of starting a duplicate pass. A camera never blocks another.
        self._compute_locks: dict[str, threading.Lock] = {}
        # Counts real model calls. The call-count test reads this to prove one
        # pass per frame; System Health can report it later.
        self.passes = 0

    # -- internals ----------------------------------------------------------

    def _compute_lock(self, camera_id: str) -> threading.Lock:
        with self._cache_lock:
            lock = self._compute_locks.get(camera_id)
            if lock is None:
                lock = self._compute_locks[camera_id] = threading.Lock()
            return lock

    def _cached(self, camera_id: str, sequence: int):
        """(hit, boxes) for this exact frame."""
        with self._cache_lock:
            entry = self._cache.get(camera_id)
        if entry is not None and entry.sequence == sequence:
            return True, entry.boxes
        return False, None

    # -- what features call -------------------------------------------------

    def raw_boxes(self, frame):
        """Ultralytics boxes for this frame, computed at most once.

        Returns whatever `PersonDetector.raw_boxes` returns, including None.
        `None` is cached like any other answer: "the model found nothing" is a
        result, and recomputing it is the same waste as recomputing a hit.
        """
        hit, boxes = self._cached(frame.camera_id, frame.sequence)
        if hit:
            return boxes

        with self._compute_lock(frame.camera_id):
            # Checked again inside the lock: while we waited, the feature we
            # were queued behind may have computed exactly what we wanted.
            # Without this the wait would be pointless and the pass would run
            # twice anyway.
            hit, boxes = self._cached(frame.camera_id, frame.sequence)
            if hit:
                return boxes

            with self._model_lock:
                boxes = self.detector.raw_boxes(frame.image)
                self.passes += 1

            with self._cache_lock:
                self._cache[frame.camera_id] = _Cached(frame.sequence, boxes)
            return boxes

    def detect(self, frame, min_area: float = 0.0) -> list[DetectedPerson]:
        """People in this frame as fractions, from the shared pass."""
        boxes = self.raw_boxes(frame)
        return PersonDetector.people_from(boxes, frame.width, frame.height, min_area)

    # -- passthrough --------------------------------------------------------
    #
    # Features and System Health ask the detector what it is and where it is
    # running. Forwarding these means a worker never needs the real detector,
    # which is the point: if a feature can reach the model it can call it.

    @property
    def device(self) -> str:
        return self.detector.device

    @property
    def version(self) -> str:
        return self.detector.version

    @property
    def weights(self):
        return self.detector.weights
