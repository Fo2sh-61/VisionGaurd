"""Cameras whose frames are sent to the engine instead of fetched by it.

The cloud trial's engine runs on a Kaggle notebook with no inbound port and
no way to reach a camera on Mohamed's laptop or site. So the laptop pushes:
`tools/cloud/webcam_sender.py` signs in and POSTs each webcam frame as a JPEG
to `/cameras/{id}/push` through the engine's own tunnel (specs/021-cloud-trial,
owner's choice, 31 Oct 2026).

A camera opts in with `source: push:<its own id>`. Everything downstream of
capture is untouched: `PushCapture` stands in for `cv2.VideoCapture`, and its
`grab()` waits for the next pushed frame the way an RTSP grab waits for the
next packet. No frame within the read timeout is a failed read, so the camera
goes stale and then NO SIGNAL exactly as a dropped network camera does. An old
picture is never served as live.

Only the newest frame is kept. A sender faster than the engine reads is not a
queue that grows; the extra frames are simply replaced.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

#: Bigger than any sane webcam JPEG, small enough that a mistaken upload of a
#: file cannot tie up memory.
MAX_BYTES = 4 * 1024 * 1024

_JPEG_START = b"\xff\xd8"


class NotAJpeg(ValueError):
    """The body was not a JPEG picture."""


@dataclass
class _Slot:
    lock: threading.Lock = field(default_factory=threading.Lock)
    arrived: threading.Condition = field(init=False)
    jpeg: bytes = b""
    sequence: int = 0
    received_at: float = 0.0

    def __post_init__(self) -> None:
        self.arrived = threading.Condition(self.lock)


_slots: dict[str, _Slot] = {}
_slots_lock = threading.Lock()


def _slot(camera_id: str) -> _Slot:
    with _slots_lock:
        found = _slots.get(camera_id)
        if found is None:
            found = _slots[camera_id] = _Slot()
        return found


def put(camera_id: str, data: bytes) -> int:
    """Store the newest frame for a camera. Returns its sequence number.

    Checked for size and the JPEG start marker only: decoding happens on the
    camera's own thread, never on the request that delivered it.
    """
    if len(data) > MAX_BYTES:
        raise NotAJpeg(f"{len(data)} bytes is more than a webcam frame ({MAX_BYTES})")
    if not data.startswith(_JPEG_START):
        raise NotAJpeg("the body is not a JPEG picture")
    slot = _slot(camera_id)
    with slot.arrived:
        slot.jpeg = data
        slot.sequence += 1
        slot.received_at = time.monotonic()
        slot.arrived.notify_all()
        return slot.sequence


def last_received(camera_id: str) -> float | None:
    """`time.monotonic()` of the newest frame, or None if none ever arrived."""
    slot = _slot(camera_id)
    with slot.lock:
        return slot.received_at or None


def _reset_for_tests() -> None:
    with _slots_lock:
        _slots.clear()


class PushCapture:
    """The slice of `cv2.VideoCapture` that `CameraSource` uses, fed by `put`."""

    def __init__(self, camera_id: str, timeout_seconds: float = 5.0):
        self.camera_id = camera_id
        self.timeout_seconds = timeout_seconds
        self._slot = _slot(camera_id)
        # Start from what is there now: a frame pushed before this capture
        # opened is old news, not the next frame.
        with self._slot.lock:
            self._seen = self._slot.sequence
        self._pending: bytes = b""
        self._open = True

    def isOpened(self) -> bool:  # noqa: N802 - cv2's name
        return self._open

    def grab(self) -> bool:
        """Wait for a frame newer than the last one. False on timeout."""
        deadline = time.monotonic() + self.timeout_seconds
        with self._slot.arrived:
            while self._open and self._slot.sequence == self._seen:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._slot.arrived.wait(left)
            if not self._open:
                return False
            self._seen = self._slot.sequence
            self._pending = self._slot.jpeg
        return True

    def retrieve(self) -> tuple[bool, np.ndarray | None]:
        if not self._pending:
            return False, None
        image = cv2.imdecode(np.frombuffer(self._pending, np.uint8), cv2.IMREAD_COLOR)
        self._pending = b""
        return image is not None, image

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.grab():
            return False, None
        return self.retrieve()

    def set(self, prop: int, value: float) -> bool:
        return False

    def get(self, prop: int) -> float:
        return 0.0

    def release(self) -> None:
        self._open = False
        with self._slot.arrived:
            self._slot.arrived.notify_all()
