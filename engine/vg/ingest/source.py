"""Camera capture with reconnect, health tracking and a last-good-frame cache.

The health model is the important part, and it comes straight from a promise the
front end already makes. `CameraFrame.tsx` renders "NO SIGNAL - showing last
received frame" when `Camera.offline` is true. So the contract is:

  - while a stream is up, callers get fresh frames and `offline` is false
  - when it drops, callers keep getting the LAST GOOD frame, and `offline`
    flips to true within one poll interval
  - a stale frame is never served with `offline` false

Getting that backwards means the console shows a five-minute-old empty corridor
and claims it is live, which is worse than showing nothing.

Status maps onto the existing `SourceStatus` type in web/src/types.ts:
`ok` | `down` | `auth`.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Literal

import cv2
import numpy as np

log = logging.getLogger(__name__)

SourceStatus = Literal["ok", "down", "auth"]

# OpenCV cannot distinguish "wrong password" from "host unreachable" — both are
# just a failed open. We infer auth failure from the URL having credentials:
# if a stream with a username never opens, a bad password is the likeliest cause
# and it is the one the operator can actually fix.
_CREDENTIALS = re.compile(r"://([^:/@]+):([^@]*)@")


class SourceKind(str, Enum):
    WEBCAM = "webcam"
    RTSP = "rtsp"
    FILE = "file"


@dataclass(frozen=True)
class Frame:
    """One decoded frame plus the provenance the event layer needs.

    `image` is BGR uint8, as OpenCV produces. `captured_at` is UTC and
    server-authoritative — the UI is forbidden from computing "11 min ago" off
    its own clock, so the time a frame was grabbed has to travel with it.
    """

    camera_id: str
    image: np.ndarray
    captured_at: datetime
    sequence: int
    is_stale: bool = False

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def to_normalised(self, x: float, y: float) -> tuple[float, float]:
        """Pixel coords -> fractions of the frame, the units everything above uses."""
        return x / self.width, y / self.height


@dataclass
class SourceHealth:
    """Current state of one camera, shaped for the System Health page."""

    status: SourceStatus = "down"
    last_frame_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    reconnects: int = 0
    frames_read: int = 0
    frames_dropped: int = 0
    opened_at: datetime | None = None

    @property
    def online(self) -> bool:
        return self.status == "ok"

    def to_wire(self) -> dict:
        return {
            "status": self.status,
            "lastFrameAt": self.last_frame_at.isoformat() if self.last_frame_at else None,
            "lastError": self.last_error,
            "reconnects": self.reconnects,
            "framesRead": self.frames_read,
            "framesDropped": self.frames_dropped,
        }


def parse_source(spec: str) -> tuple[SourceKind, str | int]:
    """Turn an engine.yaml `source` string into something cv2.VideoCapture takes.

    Accepted forms:
        webcam:0                  local capture device by index
        0                         bare index, same thing
        rtsp://user:pass@host/…   network stream
        http://… , https://…      MJPEG or HLS
        file:clips/walk.mp4       recorded video, path relative to the repo
        C:\\path\\to\\clip.mp4      absolute path
    """
    spec = spec.strip()

    if spec.startswith("webcam:"):
        index = spec.split(":", 1)[1]
        if not index.isdigit():
            raise ValueError(f"webcam source needs a numeric index, got {spec!r}")
        return SourceKind.WEBCAM, int(index)

    if spec.isdigit():
        return SourceKind.WEBCAM, int(spec)

    if spec.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return SourceKind.RTSP, spec

    if spec.startswith("file:"):
        return SourceKind.FILE, spec.split(":", 1)[1]

    return SourceKind.FILE, spec


class CameraSource:
    """A camera that keeps trying.

    Not a thread — `read()` is synchronous and reconnects inline. The registry
    above this owns threading, so this stays testable without one.

    Typical use::

        with CameraSource("cam-1", "webcam:0", target_fps=5) as cam:
            for frame in cam.frames():
                if frame.is_stale:
                    continue          # NO SIGNAL; the API still serves it
                detect(frame.image)
    """

    # Reconnect backoff, seconds. Caps out rather than growing forever: a camera
    # that comes back after an hour should be picked up within ~10s, not another hour.
    BACKOFF = (0.5, 1.0, 2.0, 5.0, 10.0)

    # Consecutive read failures tolerated before declaring the source down.
    # RTSP drops the odd frame in normal operation; one failure is not an outage.
    FAILURES_BEFORE_DOWN = 3

    def __init__(
        self,
        camera_id: str,
        source: str,
        *,
        target_fps: float = 5.0,
        rotate: int = 0,
        loop_files: bool = True,
        open_timeout_ms: int = 5000,
        read_timeout_ms: int = 5000,
    ) -> None:
        self.camera_id = camera_id
        self.source_spec = source
        self.kind, self.handle = parse_source(source)
        self.target_fps = target_fps
        self.rotate = rotate
        self.loop_files = loop_files
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms

        self.health = SourceHealth()
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        # Signals "a new frame landed". The MJPEG endpoint waits on this rather
        # than polling on a timer, so display latency is the camera's, not a
        # sleep interval we invented.
        self._frame_ready = threading.Condition(self._lock)
        self._last_good: Frame | None = None
        self._sequence = 0
        self._next_frame_due = 0.0
        self._backoff_index = 0
        self._stop = threading.Event()

        self._has_credentials = bool(
            isinstance(self.handle, str) and _CREDENTIALS.search(self.handle)
        )

    # -- lifecycle ----------------------------------------------------------

    def __enter__(self) -> "CameraSource":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def redacted(self) -> str:
        """The source string with the password masked. Safe to log."""
        if isinstance(self.handle, int):
            return f"webcam:{self.handle}"
        return _CREDENTIALS.sub(r"://\1:****@", str(self.handle))

    def open(self) -> bool:
        """Try to open the stream. Returns success; never raises on failure."""
        self.close()

        try:
            if self.kind is SourceKind.WEBCAM:
                cap = cv2.VideoCapture(self.handle, cv2.CAP_DSHOW)
                if not cap.isOpened():  # DirectShow is Windows-only; fall back
                    cap.release()
                    cap = cv2.VideoCapture(self.handle)
                # Same reason as RTSP below: a deep driver buffer means every
                # read() hands back an older frame and the live view lags.
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            elif self.kind is SourceKind.RTSP:
                cap = cv2.VideoCapture(str(self.handle), cv2.CAP_FFMPEG)
                # Keep the buffer at one frame. Without this, OpenCV hands back
                # whatever queued up while we were busy inferring, and detections
                # drift seconds behind reality — fatal for a <2s weapons budget.
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms)
            else:
                path = Path(str(self.handle))
                if not path.is_absolute():
                    path = Path(__file__).resolve().parents[3] / path
                if not path.is_file():
                    self._fail(f"no such file: {path}")
                    return False
                cap = cv2.VideoCapture(str(path))
        except Exception as exc:  # cv2 can throw on malformed URLs
            self._fail(f"{type(exc).__name__}: {exc}")
            return False

        if not cap.isOpened():
            cap.release()
            self._fail("could not open stream")
            return False

        self._cap = cap
        self.health.status = "ok"
        self.health.opened_at = datetime.now(timezone.utc)
        self.health.last_error = None
        self.health.consecutive_failures = 0
        self._backoff_index = 0
        log.info("camera %s opened (%s)", self.camera_id, self.redacted)
        return True

    def close(self) -> None:
        with self._lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None

    def stop(self) -> None:
        """Break out of `frames()` at the next iteration."""
        self._stop.set()

    # -- reading ------------------------------------------------------------

    def read(self) -> Frame | None:
        """Read one frame.

        Returns a fresh Frame, or the last good frame marked `is_stale=True`
        when the stream is down, or None if nothing has ever been captured.
        Reconnection happens inline and is not the caller's problem.
        """
        if self._cap is None and not self._reconnect():
            return self._stale()

        assert self._cap is not None
        try:
            ok, image = self._cap.read()
        except Exception as exc:
            ok, image = False, None
            self.health.last_error = f"{type(exc).__name__}: {exc}"

        if not ok or image is None or image.size == 0:
            # A file that ran out is not a failure — loop it and carry on.
            if self.kind is SourceKind.FILE and self.loop_files and self._rewind():
                return self.read()
            self._note_failure("read returned no frame")
            return self._stale()

        if self.rotate:
            image = _rotate(image, self.rotate)

        self._sequence += 1
        self.health.frames_read += 1
        self.health.consecutive_failures = 0
        if self.health.status != "ok":
            log.info("camera %s recovered", self.camera_id)
            self.health.status = "ok"
            self.health.last_error = None

        frame = Frame(
            camera_id=self.camera_id,
            image=image,
            captured_at=datetime.now(timezone.utc),
            sequence=self._sequence,
        )
        self.health.last_frame_at = frame.captured_at
        with self._frame_ready:
            self._last_good = frame
            self._frame_ready.notify_all()
        return frame

    def all_frames(self) -> Iterator[Frame]:
        """Yield every frame the device produces, unthrottled.

        This is what the frame bus carries. Rate limiting belongs in the
        consumer, not here: recognition wants 2 Hz when nobody is watching and
        12 Hz when somebody is, and it cannot have the second if ingest has
        already thrown those frames away.

        `read()` blocks in native code at the device's own pace, so this does
        not spin. Subscribers are drop-oldest, so a slow consumer costs nothing
        beyond the frames it misses.
        """
        while not self._stop.is_set():
            frame = self.read()

            if frame is None:
                time.sleep(self._backoff())
                continue

            yield frame

            if frame.is_stale:
                time.sleep(self._backoff())

    def frames(self) -> Iterator[Frame]:
        """Read at the device's rate; yield at `target_fps`.

        The distinction is the whole point, and getting it wrong is the classic
        OpenCV latency trap.

        `cap.read()` does not return the *newest* frame — it returns the *next*
        one from the driver's buffer. So a loop that sleeps between reads to hit
        5 fps against a 30 fps camera consumes one frame in six and falls
        further behind every second, until the display is running seconds
        late. Dropping frames requires actually pulling them off the device.

        So: read every frame the camera produces, which keeps `last_good_frame`
        genuinely current for the live view, and yield only at the analytics
        rate. `read()` blocks in native code at the device's own pace, so this
        does not spin.

        The cost is decoding every frame rather than one in six. That is the
        right trade at this scale; at 208 cameras the answer is sub-streams and
        a lower device rate, not re-introducing the lag.
        """
        interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.0
        next_due = time.monotonic()

        while not self._stop.is_set():
            frame = self.read()

            if frame is None:
                # Nothing captured yet and the source will not open. Back off
                # rather than spinning the CPU against a dead camera.
                time.sleep(self._backoff())
                continue

            if frame.is_stale:
                yield frame
                time.sleep(self._backoff())
                continue

            # A file has no natural pace — it returns frames as fast as they
            # decode — so it is the one source that must be slowed down here.
            if self.kind is SourceKind.FILE and interval:
                sleep_for = next_due - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)

            now = time.monotonic()
            if now >= next_due:
                next_due = max(now, next_due + interval)
                yield frame
            # Otherwise the frame is still recorded as `last_good_frame` — the
            # live view gets it, the analytics pipeline does not.

    def last_good_frame(self) -> Frame | None:
        """The most recent real frame, for the snapshot endpoint. Thread-safe."""
        with self._lock:
            return self._last_good

    def wait_for_frame(
        self, after_sequence: int = -1, timeout: float = 2.0
    ) -> Frame | None:
        """Block until a frame newer than `after_sequence` arrives.

        Lets the live view push at the camera's real rate instead of polling on
        a fixed interval — a `sleep(0.1)` loop both adds up to 100 ms of lag and
        caps the stream at 10 fps no matter what the camera can do.
        """
        with self._frame_ready:
            if self._last_good is not None and self._last_good.sequence > after_sequence:
                return self._last_good
            self._frame_ready.wait(timeout)
            if self._last_good is not None and self._last_good.sequence > after_sequence:
                return self._last_good
            return None

    # -- internals ----------------------------------------------------------

    def _stale(self) -> Frame | None:
        """Re-serve the last good frame, honestly labelled."""
        with self._lock:
            last = self._last_good
        if last is None:
            return None
        self.health.frames_dropped += 1
        return Frame(
            camera_id=last.camera_id,
            image=last.image,
            captured_at=last.captured_at,
            sequence=last.sequence,
            is_stale=True,
        )

    def _note_failure(self, reason: str) -> None:
        self.health.consecutive_failures += 1
        self.health.last_error = reason
        if self.health.consecutive_failures >= self.FAILURES_BEFORE_DOWN:
            if self.health.status == "ok":
                log.warning(
                    "camera %s went down after %d failures: %s",
                    self.camera_id,
                    self.health.consecutive_failures,
                    reason,
                )
            self.health.status = "auth" if self._has_credentials else "down"
            self.close()

    def _fail(self, reason: str) -> None:
        self.health.last_error = reason
        self.health.consecutive_failures += 1
        # A stream whose URL carries a username that will not open is reported
        # as `auth` — it is the actionable diagnosis, and the UI has a state for it.
        self.health.status = "auth" if self._has_credentials else "down"
        log.warning("camera %s: %s (%s)", self.camera_id, reason, self.redacted)

    def _reconnect(self) -> bool:
        self.health.reconnects += 1
        return self.open()

    def _rewind(self) -> bool:
        if self._cap is None:
            return False
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return True

    def _backoff(self) -> float:
        delay = self.BACKOFF[min(self._backoff_index, len(self.BACKOFF) - 1)]
        self._backoff_index += 1
        return delay


def _rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    if degrees == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def open_source(camera, **overrides) -> CameraSource:
    """Build a CameraSource from a `config.CameraConfig`."""
    params = {
        "target_fps": camera.fps,
        "rotate": camera.rotate,
    }
    params.update(overrides)
    return CameraSource(camera.id, camera.source, **params)
