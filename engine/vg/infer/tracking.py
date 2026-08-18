"""Layer 3 — giving each person a stable ID across frames.

DEV_PLAN §3.2 puts this between person detection and everything that needs to
know "is this the same person as last frame": dwell time, paths, and the
appearance matching that carries a name from one camera to the next.

**One shared detector, one tracker per camera.** That split matters. The model
is the expensive thing and §3.4 is emphatic that it must run once per frame and
fan out — but a tracker is *stateful about motion*, and feeding it frames from
two cameras in turn corrupts every track in both. Ultralytics' `model.track()`
hides a single tracker inside the model object, which is exactly the wrong shape
here, so this module drives `BYTETracker` directly and keeps one per camera.

Cost is roughly 2 ms of CPU per frame. The GPU is untouched.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

log = logging.getLogger(__name__)

# ByteTrack's own defaults, restated here so they are visible and tunable
# without reaching into the ultralytics package. Names match its config file.
TRACKER_DEFAULTS = dict(
    tracker_type="bytetrack",
    track_high_thresh=0.25,
    track_low_thresh=0.10,
    new_track_thresh=0.25,
    # Frames a lost track stays alive. At 5 Hz analytics, 30 frames is six
    # seconds — long enough to survive someone passing behind a pillar, short
    # enough that a different person arriving later does not inherit the ID.
    track_buffer=30,
    match_thresh=0.80,
    fuse_score=True,
)


@dataclass(frozen=True)
class Track:
    """One person, this frame, in PIXELS.

    Pixels, not fractions, because everything downstream of here crops the
    frame: appearance matching reads the clothing inside the box. Conversion to
    fractions happens at the API boundary and nowhere earlier, per the geometry
    rule in schemas.py.
    """

    track_id: int
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The tuple shape loiterwatch's Detection expects."""
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def to_fractions(self, frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
        return (
            max(0.0, self.x1 / frame_w),
            max(0.0, self.y1 / frame_h),
            min(1.0, self.width / frame_w),
            min(1.0, self.height / frame_h),
        )


class PersonTracker:
    """ByteTrack for one camera.

    Takes the ultralytics `Boxes` the shared detector already produced, so no
    second inference pass happens here.
    """

    def __init__(self, frame_rate: float = 5.0, **overrides) -> None:
        from ultralytics.trackers import BYTETracker

        args = SimpleNamespace(**{**TRACKER_DEFAULTS, **overrides})
        # frame_rate feeds the motion model's expectations about how far a
        # person moves between frames. Passing 30 for a 5 Hz feed makes it
        # expect small steps and lose people who cross the frame quickly.
        self._tracker = BYTETracker(args, frame_rate=max(1, int(round(frame_rate))))
        self.frames = 0

    def update(self, boxes, image: np.ndarray | None = None) -> list[Track]:
        """Tracks for this frame, or [] when nobody is present.

        A tracker must be called on *every* analysed frame, including empty
        ones — that is how lost tracks age out. Skipping empty frames makes a
        track survive an arbitrarily long absence and hand its ID to whoever
        walks in next.
        """
        self.frames += 1
        try:
            rows = self._tracker.update(boxes, image)
        except Exception:
            # A tracker fault must not take the camera down with it.
            log.exception("tracker update failed; dropping this frame's tracks")
            return []

        out: list[Track] = []
        for row in np.asarray(rows):
            if len(row) < 6:
                continue
            x1, y1, x2, y2, track_id, score = row[:6]
            out.append(Track(
                track_id=int(track_id),
                x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2),
                confidence=float(score),
            ))
        return out


class TrackerPool:
    """One `PersonTracker` per camera, created on first sight.

    Thread-safe: feature workers run a thread per camera, and two cameras can
    genuinely ask for their tracker at the same moment.
    """

    def __init__(self, frame_rate: float = 5.0, **overrides) -> None:
        self.frame_rate = frame_rate
        self.overrides = overrides
        self._trackers: dict[str, PersonTracker] = {}
        self._lock = threading.Lock()

    def for_camera(self, camera_id: str) -> PersonTracker:
        with self._lock:
            tracker = self._trackers.get(camera_id)
            if tracker is None:
                tracker = PersonTracker(self.frame_rate, **self.overrides)
                self._trackers[camera_id] = tracker
                log.info("tracking started for %s", camera_id)
            return tracker

    def forget(self, camera_id: str) -> None:
        """Drop a camera's tracker, so a removed camera leaves no state."""
        with self._lock:
            self._trackers.pop(camera_id, None)

    @property
    def cameras(self) -> list[str]:
        with self._lock:
            return sorted(self._trackers)
