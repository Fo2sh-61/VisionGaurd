"""Bag detection on the cameras somebody is currently looking at.

**There is no search and no job.** An operator ticks the cameras they care
about and picks a colour; those cameras appear on screen and a box is drawn
round any bag of that colour, live, for as long as they keep looking. Nothing is
started, nothing is stopped, nothing finishes. It is the attendance page's
shape, applied to bags.

**What starts the work: somebody looking.** Each tile polls
`/cameras/{id}/detections?feature=lost` for its overlay, and that poll is the
only thing that registers interest. One background thread runs the bag model
over the cameras with live interest and keeps their most recent boxes. When the
last tile stops polling, interest lapses within `INTEREST_SECONDS` and the
thread goes back to having nothing to do.

So idle cost is still zero - no page open, no interest, no model call - without
anybody having to press Stop and without a time limit to run out. This is the
same idea as `recogniser.note_interest()`: the act of watching is what pays for
the work.

**No person gate**, unlike knives: the bag worth finding is precisely the one
with nobody near it, so the whole frame goes to the model.

**Nothing is recorded.** No clip, no still, no row in any table, no history.

**What a box means, and what it does not.** Measured on footage with no bag in
it (research D10), this model puts a `suitcase` box on a black office chair at
up to 0.88 and holds it there. A box is therefore *a possible bag*, drawn in
amber over a live picture the operator is already looking at, so they can see
for themselves that it is a chair. It is never a claim that a bag is there.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# How long a camera stays interesting after the last poll for its overlay.
# Comfortably longer than the slowest tile refresh (1.5 s on a big grid) so a
# tile still on screen never flickers out, and short enough that leaving the
# page stops the work almost at once.
INTEREST_SECONDS = 6.0

# How long a box stays on screen after the frame that produced it. A box drawn
# over a live picture of where a bag *was* is a stale frame wearing a rectangle.
OVERLAY_HOLD_SECONDS = 3.0

# Do not spin when no camera is being looked at, or when every watched camera's
# frame is unchanged.
IDLE_PAUSE_SECONDS = 0.25

# Ignore a bag box under 1 % of the frame - a distant smudge, not a bag somebody
# can go and pick up.
MIN_BOX_FRACTION = 0.01

# ...and over 60 % of it. Measured (research D10): a motion-blurred frame comes
# back as one `suitcase` box covering 99.7 % of the picture. No bag anybody can
# walk over and collect fills the frame.
MAX_BOX_FRACTION = 0.6


@dataclass(frozen=True)
class Hit:
    """One box, on one camera, in one frame."""

    at: datetime
    x: float
    y: float
    w: float
    h: float
    label: str
    confidence: float
    sequence: int = 0
    colour: str | None = None
    colours: frozenset[str] = frozenset()

    @property
    def area(self) -> float:
        return self.w * self.h


def matches_colour(hit: Hit, wanted: str | None) -> bool:
    """Does this hit answer to `wanted`? No colour asked for means every bag.

    Matched against the **lenient** set, never the single best name: a dark blue
    bag looks black in poor light and has to answer to both.

    A hit whose colour could not be named at all matches everything. An unnamed
    colour means "we could not narrow this down", which is a different answer
    from "this is not the one". Treating it as a mismatch would hide the bag
    somebody is looking for because a crop came back one pixel wide.
    """
    if not wanted:
        return True
    return not hit.colours or wanted in hit.colours


class BagWatch:
    """Looks for bags on whichever cameras are on somebody's screen.

    One thread, started with the engine and idle until a tile asks for a `lost`
    overlay. Holds only the most recent boxes per camera; there is no job, no
    result and no history to keep.
    """

    def __init__(self, registry, detector, clock, *, now=None) -> None:
        self.registry = registry
        self.detector = detector
        self.clock = clock
        # Wall clock, injectable so a test can age a box without sleeping.
        self._now = now or (lambda: datetime.now(timezone.utc))

        self._lock = threading.Lock()
        # camera id -> when it was last asked about
        self._interest: dict[str, datetime] = {}
        # camera id -> the boxes from the newest frame that had any
        self._boxes: dict[str, list[Hit]] = {}
        self._seen: dict[str, int] = {}

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_inference_ms = 0
        self._colour_warned = False

    # -- the public surface -------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="bag-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def note_interest(self, camera_id: str) -> None:
        """Somebody is looking at this camera. The only thing that starts work."""
        with self._lock:
            self._interest[camera_id] = self._now()

    def boxes_on(self, camera_id: str, colour: str | None = None) -> list[Hit]:
        """The newest boxes for one camera, of the colour asked for."""
        with self._lock:
            hits = list(self._boxes.get(camera_id, []))
        cutoff = self._now() - timedelta(seconds=OVERLAY_HOLD_SECONDS)
        return [h for h in hits if h.at >= cutoff and matches_colour(h, colour)]

    @property
    def watching(self) -> list[str]:
        """Cameras being looked at right now."""
        cutoff = self._now() - timedelta(seconds=INTEREST_SECONDS)
        with self._lock:
            return [c for c, at in self._interest.items() if at >= cutoff]

    @property
    def stats(self) -> dict:
        """The keys `FeatureWorker.stats` uses, so System Health reads alike."""
        watching = self.watching
        return {
            "cameras": len(watching),
            "last_inference_ms": self._last_inference_ms,
            "state": "watching" if watching else "idle",
        }

    # -- the loop -----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            watching = self.watching
            if not watching:
                # Nobody is looking. This is the whole of the idle cost: one
                # sleeping thread and no model call.
                self._forget_stale()
                time.sleep(IDLE_PAUSE_SECONDS)
                continue

            fresh = False
            for camera_id in watching:
                if self._stop.is_set():
                    break
                try:
                    if self._look_at(camera_id):
                        fresh = True
                except Exception:  # noqa: BLE001 - reported, never raised
                    log.exception("bag watch failed on %s", camera_id)

            if not fresh:
                time.sleep(IDLE_PAUSE_SECONDS)

    def _look_at(self, camera_id: str) -> bool:
        """One look at one camera. True if there was a new frame to look at."""
        worker = self.registry.worker(camera_id)
        if worker is None or worker.status != "ok":
            return False

        frame = worker.last_frame()
        if frame is None:
            return False
        # `last_frame()` returns the same frame until the camera delivers a new
        # one; running the model on it again would cost a pass and change
        # nothing on screen.
        if self._seen.get(camera_id) == frame.sequence:
            return False
        self._seen[camera_id] = frame.sequence

        started = time.perf_counter()
        boxes = self.detector.detect(frame.image)
        self._last_inference_ms = int((time.perf_counter() - started) * 1000)

        hits = [
            self._hit(box, frame)
            for box in boxes
            if MIN_BOX_FRACTION <= box.w * box.h <= MAX_BOX_FRACTION
        ]
        # Replace, never accumulate: the overlay shows what is in view now, and
        # the previous frame's boxes were the previous frame's answer.
        with self._lock:
            self._boxes[camera_id] = hits
        return True

    def _forget_stale(self) -> None:
        """Drop cameras nobody is looking at, so nothing grows without bound."""
        cutoff = self._now() - timedelta(seconds=INTEREST_SECONDS)
        with self._lock:
            gone = [c for c, at in self._interest.items() if at < cutoff]
            for camera_id in gone:
                self._interest.pop(camera_id, None)
                self._boxes.pop(camera_id, None)
                self._seen.pop(camera_id, None)

    def _hit(self, box, frame) -> Hit:
        colour, colours = self._colour_of(box, frame)
        return Hit(
            at=frame.captured_at,
            x=box.x, y=box.y, w=box.w, h=box.h,
            label=box.label,
            confidence=box.confidence,
            sequence=frame.sequence,
            colour=colour,
            colours=colours,
        )

    def _colour_of(self, box, frame) -> tuple[str | None, frozenset[str]]:
        """Name the bag's colour, or lose the colour rather than the box.

        A degenerate crop - a box one pixel wide at the frame edge - must not
        cost somebody the box on their bag. Logged once so a systematic failure
        is visible, then the hit goes on without a colour, which the filter
        reads as "cannot be narrowed" rather than "does not match".
        """
        from vg.infer.colour import crop_for, name_colour

        try:
            guess = name_colour(crop_for(frame.image, box), frame.image)
            return guess.best, guess.lenient
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            if not self._colour_warned:
                self._colour_warned = True
                log.warning("could not name a bag's colour: %s", exc)
            return None, frozenset()
