"""Run a camera's models only while something is happening in front of it.

Shared by face recognition (`face_wake`) and plate reading (`plate_wake`). It is
a helper, not a worker: each feature holds its own `MotionWake`, so neither
depends on the other being switched on.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import cv2
import numpy as np

#: Two checks are compared on a small grey copy of the picture, blurred so
#: sensor noise does not count as movement. A pixel has moved when it changed by more than WAKE_PIXEL_DELTA
#: grey levels; the picture has moved when at least WAKE_AREA of it did.
WAKE_SIZE = (160, 120)
WAKE_PIXEL_DELTA = 25
WAKE_AREA = 0.005

#: How long a camera keeps being looked at after the last movement or the last
#: thing its worker found.
#: Longer than the anchor gate's span (1.5 s identity, 2.0 s patrol), so
#: somebody who walks up and then stands still is still looked at long enough
#: to be named. A worker that keeps finding something (a face, a plate) calls
#: `keep_awake`, so it never lapses while that thing is in view.
WAKE_HOLD_SECONDS = 5.0

#: Look at least this often even when nothing moves. A person who stood still
#: with their face turned away until the hold ran out, then lifted their head -
#: a change too small to count as movement - is still found within this long.
#: At 2 checks a second it costs one check in twenty.
WAKE_HEARTBEAT_SECONDS = 10.0


class MotionWake:
    """Whether a camera has anything worth running its models on.

    An entrance or a gate is empty most of the day, and the models are the most
    expensive work its camera costs. This decides, per camera, whether to look:

      - something moved since the last check  -> look
      - the worker found something in the hold -> look (a still person or car)
      - something moved within the hold        -> look
      - no look for WAKE_HEARTBEAT_SECONDS     -> look (something still, turned)
      - otherwise                              -> skip, and count it

    It errs towards looking. A first frame, a picture of a new size, or any
    failure in the comparison all count as movement: a skipped check is a face
    or a plate nobody looked for, while an extra one only costs time.
    """

    def __init__(self, hold_seconds: float = WAKE_HOLD_SECONDS,
                 heartbeat_seconds: float = WAKE_HEARTBEAT_SECONDS) -> None:
        self.hold = timedelta(seconds=hold_seconds)
        self.heartbeat = timedelta(seconds=heartbeat_seconds)
        self._last: dict[str, np.ndarray] = {}
        self._awake_until: dict[str, datetime] = {}
        self._looked_at: dict[str, datetime] = {}

    def moved(self, camera_id: str, image: np.ndarray) -> bool:
        try:
            small = cv2.resize(image, WAKE_SIZE, interpolation=cv2.INTER_AREA)
            if small.ndim == 3:
                small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            small = cv2.GaussianBlur(small, (5, 5), 0)
        except cv2.error:
            self._last.pop(camera_id, None)
            return True
        previous = self._last.get(camera_id)
        self._last[camera_id] = small
        if previous is None or previous.shape != small.shape:
            return True
        changed = np.count_nonzero(cv2.absdiff(small, previous) > WAKE_PIXEL_DELTA)
        return changed >= WAKE_AREA * small.size

    def should_look(self, camera_id: str, image: np.ndarray, now: datetime) -> bool:
        if self.moved(camera_id, image):
            self.keep_awake(camera_id, now)
            look = True
        else:
            until = self._awake_until.get(camera_id)
            looked = self._looked_at.get(camera_id)
            look = ((until is not None and now < until)
                    or looked is None or now - looked >= self.heartbeat)
        if look:
            self._looked_at[camera_id] = now
        return look

    def keep_awake(self, camera_id: str, now: datetime) -> None:
        self._awake_until[camera_id] = now + self.hold

    def forget(self, camera_id: str) -> None:
        self._last.pop(camera_id, None)
        self._awake_until.pop(camera_id, None)
        self._looked_at.pop(camera_id, None)
