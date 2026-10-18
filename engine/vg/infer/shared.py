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

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from vg.infer.persons import DetectedPerson, PersonDetector

log = logging.getLogger(__name__)

#: How far back `SharedDetection.load()` looks. Matches
#: `FeatureWorker.WINDOW_SECONDS` so the pass and its readers are measured
#: over the same seconds.
WINDOW_SECONDS = 5.0

#: What `weights_to_load` reports back, and what System Health prints.
TENSORRT = "TensorRT"
UNACCELERATED = "PyTorch CUDA"

# ---------------------------------------------------------------------------
# Who pays for the shared pass
#
# Several workers call `raw_boxes` for the same frame and the model runs once.
# Each of them still SPENDS the time: the first computes, the others block on
# the per-camera lock until it has, then take the cached answer. Measured from
# inside a worker, all of them look like they ran a 13 ms model - and a page
# that adds their rows up charges one pass three times.
#
# So the time a thread spends inside `raw_boxes` - waiting, computing or
# hitting the cache - is recorded against THAT thread, and a worker subtracts
# it from its own timing. What is left is what the worker itself did: ByteTrack
# for tracking, the knife model for weapons, bookkeeping for zones. The pass is
# then charged exactly once, on its own row, from `last_pass_ms`.
# ---------------------------------------------------------------------------

_borrowed = threading.local()


def _borrow(ms: float) -> None:
    _borrowed.ms = getattr(_borrowed, "ms", 0.0) + ms


def take_borrowed_ms() -> float:
    """Milliseconds this thread has spent in the shared pass since last asked.

    Reading resets it, so a worker calls it once before `analyse` to clear
    anything stale and once after to learn what that frame borrowed.
    """
    ms = getattr(_borrowed, "ms", 0.0)
    _borrowed.ms = 0.0
    return ms


def tensorrt_available() -> bool:
    """Can this machine load a TensorRT engine at all?

    **Importing `tensorrt` is not enough and the difference is not academic.**
    On the cu13 build against a cu128 torch, `import tensorrt` succeeds,
    `trt.Logger()` succeeds, and `trt.Builder()` segfaults - taking the whole
    interpreter with it, so an export reports exit code 0 and produces no
    file. The import is the cheap check that ultralytics itself performs; this
    one only claims what it can see, and the build tool does the real probe.
    """
    try:
        import tensorrt
    except Exception:
        return False
    # Touch an attribute rather than bare-importing: an install whose native
    # half is missing imports and then fails on first use.
    return bool(getattr(tensorrt, "__version__", ""))


def engine_path_for(weights: Path, imgsz: int) -> Path:
    """Where the accelerated build for these weights and this size lives.

    The size is **in the filename**, which is the whole trick. A TensorRT plan
    has static shapes, so an engine built at 480 cannot serve a model
    configured at 640 - and because the name carries the size, a 640 config
    simply never names the 480 file. The rule that a wrong-size build must be
    rejected needs no comparison logic; it enforces itself.

    This is also the convention already on disk: `yolov8s-480.engine`,
    `yolov8s-pose-640.engine`.
    """
    return weights.with_name(f"{weights.stem}-{imgsz}.engine")


def weights_to_load(weights: Path, imgsz: int) -> tuple[Path, str]:
    """The file a runner should actually open, and what to call that choice.

    Prefers the accelerated build, falls back to the supplied weights **on the
    GPU** - never to the processor. A missing engine is a slower product, not
    a broken one, and P6-FR-033 requires the console to say which it is
    running rather than leaving it to be discovered by timing a frame.

    That is not hypothetical. This repo carried five engines that no
    configuration referenced, loaded by a library that was not importable, one
    of them built for the wrong input size - and nothing on any screen said
    so. The product ran unaccelerated for months.
    """
    if os.getenv("VG_NO_TENSORRT") == "1":
        # The lever for answering "is the engine costing accuracy?" without
        # deleting a file that took ten minutes to build. A TensorRT plan is
        # built at FP16 and its input size is fixed, so it is not bit-identical
        # to the .pt it came from - and on a model that classifies single
        # characters, "not identical" is a thing to be able to measure rather
        # than argue about. `tools/compare_plates.py` sets this.
        return weights, UNACCELERATED

    engine = engine_path_for(weights, imgsz)
    if not engine.exists():
        return weights, UNACCELERATED
    if not tensorrt_available():
        log.warning(
            "%s exists but tensorrt is not importable - running %s unaccelerated",
            engine.name, weights.name,
        )
        return weights, UNACCELERATED
    return engine, TENSORRT


def _open_now(model, imgsz: int) -> None:
    """Make ultralytics actually open the plan, here, inside the caller's try.

    `YOLO("x.engine")` only remembers the path. The plan is deserialised on
    the first predict, so a plan from another TensorRT version used to pass
    the try in `load_model` and fail later, in a runner's warm-up, where
    nothing falls back. On the first site install that stopped the engine:
    plans built by TensorRT 11.2 were read by 11.4 and deserialised to None.
    """
    import numpy as np

    model.predict(np.zeros((imgsz, imgsz, 3), dtype=np.uint8),
                  imgsz=imgsz, verbose=False)


def engine_opens(engine: Path, imgsz: int, task: str = "detect") -> str | None:
    """None when this plan opens with the TensorRT installed here, else why not.

    `build_engines.py` asks this before calling a plan "already built": a file
    that exists but will not open is stale, and gets rebuilt.
    """
    from ultralytics import YOLO

    try:
        _open_now(YOLO(str(engine), task=task), imgsz)
    except Exception as exc:  # noqa: BLE001 - any failure means "rebuild it"
        return f"{type(exc).__name__}: {exc}"
    return None


def load_model(weights: Path, imgsz: int, task: str = "detect",
               accelerate: bool = True):
    """Open the fastest form of these weights that actually loads.

    Returns `(model, path, form)`. Tries the accelerated build first and falls
    back to the supplied weights **on the GPU** if it will not open — which is
    the third of the three states P6-FR-033 names, and the one a file-exists
    check alone cannot catch. A plan built by a different library version, or
    for a different GPU, exists and is still useless.

    A failed engine load must never take the product down with it. Knife
    detection going dark because somebody upgraded a driver would be a far
    worse outcome than running six milliseconds slower.
    """
    from ultralytics import YOLO

    if not accelerate:
        # This model has asked to run as it was trained. `models/README.md`
        # says why for the two that do.
        return YOLO(str(weights)), weights, UNACCELERATED

    chosen, form = weights_to_load(weights, imgsz)
    if form is UNACCELERATED or chosen == weights:
        return YOLO(str(weights)), weights, UNACCELERATED

    try:
        model = YOLO(str(chosen), task=task)
        _open_now(model, imgsz)
        return model, chosen, TENSORRT
    except Exception as exc:
        # Stale plan, wrong GPU, wrong library version. Say it once, loudly,
        # and keep working - the console reports the form either way.
        log.warning(
            "%s exists but would not load (%s) - running %s unaccelerated. "
            "Rebuild it with: python engine/tools/build_engines.py",
            chosen.name, exc, weights.name,
        )
        return YOLO(str(weights)), weights, UNACCELERATED


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

    def __init__(self, detector: PersonDetector, batch: bool = False) -> None:
        self.detector = detector
        # Run frames that are ALREADY waiting as one model call.
        #
        # Throughput only, and deliberately not a scheduler: nothing is ever
        # held back hoping a second frame turns up. A caller that finds the
        # model free runs alone, immediately, exactly as before. A caller that
        # finds it busy joins whoever else is queued and they go in together.
        # So there is no window to tune and no latency to trade away.
        self.batch = batch
        # Set once, if the loaded model turns out to refuse a batch.
        #
        # A TensorRT plan is compiled at a FIXED batch size - 1, as
        # `build_engines.py` builds them - and handed three images it raises
        # rather than adapting. That exception would be caught per frame by
        # FeatureWorker and logged, so the visible symptom would be detection
        # quietly stopping on a camera. Falling back to one-at-a-time keeps
        # the answers and loses only the speed-up that was never available.
        self.batch_unavailable: str | None = None
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
        # pass per frame; System Health reports it.
        self.passes = 0
        # What the model itself took for the most recent frame, on this
        # machine. Timed around the model call alone - no lock wait, no cache
        # - so it is the one figure a capacity projection can multiply by a
        # rate without counting anybody's queueing as inference.
        self.last_pass_ms = 0.0
        # (when, ms) per real model call, for WINDOW_SECONDS. Its own lock:
        # appended from inside `_model_lock` and read from the API thread,
        # and it must never be tempted into `_cache_lock`'s ordering.
        self._recent_passes: deque[tuple[float, float]] = deque()
        self._recent_lock = threading.Lock()
        self._started_at = time.monotonic()
        # Frames whose thread is blocked on `_model_lock` right now, and the
        # answers left for them. Guarded by `_cache_lock`, which is only ever
        # held for a dict operation and never across a model call.
        self._waiting: dict[str, object] = {}
        self._batched: dict[str, object] = {}
        # How many frames the last batched call carried. System Health reads
        # it; a value of 1 means batching is on and finding nothing to batch,
        # which is the honest answer for a single-camera site.
        self.last_batch = 0

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

        Every millisecond spent in here - computing, waiting for another
        worker's computation, or reading the cache - is charged to the calling
        thread via `take_borrowed_ms`, so the worker can report what it did
        ITSELF and the pass is costed once. See the note at the top.
        """
        started = time.perf_counter()
        try:
            return self._raw_boxes(frame)
        finally:
            _borrow((time.perf_counter() - started) * 1000)

    def _raw_boxes(self, frame):
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

            boxes = self._run(frame)

            with self._cache_lock:
                self._cache[frame.camera_id] = _Cached(frame.sequence, boxes)
            return boxes

    def _run(self, frame):
        """One frame through the model, batched with whoever else is waiting.

        Adds no scheduling. A caller announces the frame it is holding, takes
        the model lock, and sweeps up every OTHER frame announced meanwhile.
        Those threads are already blocked, so running their work costs nothing
        extra and saves them a call each.

        Everything here is keyed by the FRAME, never by the camera. That is
        not a detail. Keyed by camera, two frames from one camera collide: the
        second thread pops the first one's answer, throws it away because it
        does not match the frame it is holding, and the first thread wakes to
        find nothing waiting for it. `--batch-check` caught exactly that -
        frames coming back empty - and an empty answer means "nobody in this
        picture", which is a wrong detection, not a slow one.
        """
        if not self.batch:
            with self._model_lock:
                started = time.perf_counter()
                boxes = self.detector.raw_boxes(frame.image)
                self.last_pass_ms = (time.perf_counter() - started) * 1000
                self.passes += 1
                self._note_pass(self.last_pass_ms)
            return boxes

        token = id(frame)
        with self._cache_lock:
            self._waiting[token] = frame

        with self._model_lock:
            with self._cache_lock:
                # Only ever our own answer. Popping somebody else's is the
                # bug described above.
                if token in self._batched:
                    self._waiting.pop(token, None)
                    return self._batched.pop(token)

                mine_pending = self._waiting.pop(token, None)
                others = list(self._waiting.items())
                for other_token, _ in others:
                    self._waiting.pop(other_token, None)

            batch = [frame] if mine_pending is None else [mine_pending]
            tokens = [token]
            for other_token, other in others:
                batch.append(other)
                tokens.append(other_token)

            started = time.perf_counter()
            if len(batch) == 1 or self.batch_unavailable:
                answers = [self.detector.raw_boxes(f.image) for f in batch]
            else:
                try:
                    answers = self.detector.raw_boxes_many(
                        [f.image for f in batch])
                except Exception as exc:
                    # Once, loudly, then never again. Every frame in this
                    # batch still gets its own answer - the fallback runs
                    # them singly rather than dropping them.
                    self.batch_unavailable = str(exc)
                    log.warning(
                        "batched detection is not available on this model "
                        "(%s) - running one frame at a time. A TensorRT plan "
                        "is compiled at a fixed batch size; rebuild it with a "
                        "dynamic batch, or set models.person.batch: false to "
                        "stop asking.", exc,
                    )
                    answers = [self.detector.raw_boxes(f.image) for f in batch]
            # Real model invocations, not trips through the lock. One batched
            # call is one; a fallback that ran three images singly is three.
            # This number reaches System Health, and a saving that did not
            # happen must not be reported as one.
            single = len(batch) == 1 or bool(self.batch_unavailable)
            self.passes += len(batch) if single else 1
            self.last_batch = 1 if single else len(batch)
            # Per frame, whichever way it ran: a batch of three that took
            # 30 ms cost each frame 10.
            self.last_pass_ms = (time.perf_counter() - started) * 1000 / len(batch)
            for _ in batch:
                self._note_pass(self.last_pass_ms)

            mine = None
            with self._cache_lock:
                for other_token, other, result in zip(tokens, batch, answers):
                    if other_token == token:
                        mine = result
                    else:
                        # Left for its own thread, which is still blocked
                        # behind us on the model lock. Keyed by frame, so it
                        # can only ever be collected by the thread that asked.
                        self._batched[other_token] = result
                        self._cache[other.camera_id] = _Cached(
                            other.sequence, result)
            return mine

    def _note_pass(self, ms: float) -> None:
        with self._recent_lock:
            self._recent_passes.append((time.monotonic(), ms))

    def load(self) -> dict:
        """What the pass is really costing, per second, over the window.

        Measured - passes that happened and the milliseconds they took -
        as opposed to the projection System Health also shows, which is a
        configured rate times a cost. Idle for the whole window reads 0.
        """
        now = time.monotonic()
        with self._recent_lock:
            cutoff = now - WINDOW_SECONDS
            while self._recent_passes and self._recent_passes[0][0] < cutoff:
                self._recent_passes.popleft()
            span = max(1.0, min(WINDOW_SECONDS, now - self._started_at))
            return {
                "passes_per_second": round(len(self._recent_passes) / span, 2),
                "busy_ms_per_second": round(
                    sum(ms for _, ms in self._recent_passes) / span, 1),
                "window_seconds": WINDOW_SECONDS,
            }

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

    @property
    def form(self) -> str:
        """TensorRT or PyTorch CUDA, from the detector actually loaded.

        Forwarded like `device` and `version` for the same reason: a feature
        must be able to say what it is running on without holding the model.
        """
        return getattr(self.detector, "form", UNACCELERATED)
