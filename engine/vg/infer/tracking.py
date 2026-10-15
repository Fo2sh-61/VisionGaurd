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

#: How long a lost track stays alive before its ID is retired. Long enough to
#: survive someone passing behind a pillar, short enough that a different
#: person arriving later does not inherit the ID — which would put one
#: person's history onto another and is the worst failure this file has.
LOST_TRACK_SECONDS = 6.0

def track_buffer_for(frame_rate: float) -> int:
    """`track_buffer` in real frames, for a feed arriving at `frame_rate`.

    **This changed under us, and the seconds are what must not change.**

    Until ultralytics 8.4.127, `BYTETracker.__init__` took a `frame_rate` and
    computed `max_time_lost = int(frame_rate / 30 * track_buffer)` — so
    `track_buffer` was quoted against an implied 30 fps whatever the real rate
    was, and this module pre-multiplied by 30 to cancel it. 8.4.127 dropped the
    `frame_rate` argument and now uses the value raw:

        self.max_frames_lost = args.track_buffer

    The old pre-multiplied 180 therefore became 180 *frames*: 36 seconds at
    5 Hz and 180 at 1 Hz, against the 6 intended. An ID held half a minute
    after somebody leaves is exactly how the next person through the door
    inherits it, which is the failure this file exists to prevent. Seven tests
    in `test_tracker_config.py` caught it on the upgrade.

    Now that the unit is honestly frames, the conversion is the obvious one and
    there is no implied rate left to cancel.

    **Requires ultralytics >= 8.4.127.** Older versions would scale this a
    second time and give back a window `frame_rate / 30` of what was asked for.
    """
    return max(1, int(round(frame_rate * LOST_TRACK_SECONDS)))


#: The buffer for a 30 fps feed, kept as a named reference point. Real
#: trackers get `track_buffer_for(their own rate)`; this is only what that
#: returns at 30 Hz, and exists so the number in the config below is not bare.
TRACK_BUFFER = track_buffer_for(30.0)

# ByteTrack's own defaults, restated here so they are visible and tunable
# without reaching into the ultralytics package. Names match its config file.
#
# `track_buffer` here is a placeholder: `PersonTracker.__init__` overwrites it
# with the value for its own frame rate, because a buffer in frames cannot be
# a constant across feeds running at different rates.
TRACKER_DEFAULTS = dict(
    tracker_type="bytetrack",
    track_high_thresh=0.25,
    track_low_thresh=0.10,
    new_track_thresh=0.25,
    track_buffer=TRACK_BUFFER,
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
    #: Which of the detections handed to `update` this track was matched to
    #: on this frame, or -1 when ByteTrack did not say. Fall detection reads
    #: it to keep each body's keypoints with that body: a pose model returns
    #: keypoints in detection order, and ByteTrack returns tracks in its own.
    index: int = -1

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

        # Tell it the rate it is fed at its SLOWEST. The tracking worker boosts
        # from its idle rate to 12 Hz while someone is watching the Track page,
        # and the window scales with whatever is passed here: quoting the boost
        # rate would stretch the idle window to fourteen seconds, which is long
        # enough for the next person through the door to inherit an ID. Erring
        # short costs a fragmented path; erring long costs the wrong name.
        settings = {**TRACKER_DEFAULTS, **overrides}
        # The buffer is in real frames now, so it belongs to this feed's rate
        # and not to the module. An explicit `track_buffer` override still
        # wins — a caller asking for a specific frame count means it.
        if "track_buffer" not in overrides:
            settings["track_buffer"] = track_buffer_for(frame_rate)
        args = SimpleNamespace(**settings)
        # No `frame_rate=` argument: ultralytics 8.4.127 removed it. Passing it
        # raises TypeError rather than being ignored, which is the good
        # outcome — a silently ignored rate would have left the window wrong
        # with nothing to notice.
        self._tracker = BYTETracker(args)
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
                # ultralytics' rows are x1 y1 x2 y2 id score cls idx.
                index=int(row[7]) if len(row) >= 8 else -1,
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
