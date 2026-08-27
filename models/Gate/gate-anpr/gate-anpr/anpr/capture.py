"""
Opening camera streams without hanging.

`cv2.VideoCapture` on a dead RTSP address blocks for a very long time — long
enough that `run.py check` looks frozen and a camera worker stops retrying its
healthy siblings. Everything that opens a stream goes through here instead.
"""

from __future__ import annotations

import os
import threading

# FFmpeg options must be set before the first VideoCapture is constructed.
# stimeout is in microseconds; TCP is far more reliable than UDP for RTSP.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000|reorder_queue_size;0",
)

import cv2  # noqa: E402  (must follow the env var)

DEFAULT_TIMEOUT_MS = 6000


import sys

# A USB webcam opens at whatever its driver calls the default, which is very
# often 640x480 even on a camera that does 1080p. That default is the single
# hardest limit on range: a 35cm Egyptian plate at 3m through a ~65 degree lens
# lands on about 59px at 640 wide, which is under what any reader can resolve,
# and about 117px at 1280 wide, which is comfortable. Asking for a size costs
# nothing and is the difference between working at 3m and not.
#
# Not applied to RTSP: an IP camera streams whatever its own configuration
# says, and setting these properties on a network stream is at best ignored.
DEFAULT_CAPTURE_SIZE = (1280, 720)


def normalise_source(source: str | int):
    """'0' -> 0 (webcam index); anything else stays a string."""
    s = str(source)
    return int(s) if s.isdigit() else s


def _is_local_device(source: str | int) -> bool:
    """True for a webcam index — the only kind whose resolution we may set."""
    return isinstance(normalise_source(source), int)


def open_capture(source: str | int, timeout_ms: int = DEFAULT_TIMEOUT_MS,
                 width: int = 0, height: int = 0):
    """
    Open a stream, or return None within roughly `timeout_ms`.

    The open runs on a worker thread as a hard backstop: some FFmpeg builds
    ignore the timeout options, and a stuck thread is far better than a stuck
    process.

    `width`/`height` request a capture size on local webcams. Zero means use
    DEFAULT_CAPTURE_SIZE; the driver may return something smaller, which is
    fine — whatever it gives is what the pipeline works with.
    """
    result: dict[str, object] = {}

    def _open() -> None:
        try:
            src = normalise_source(source)
            local = isinstance(src, int)
            # DirectShow honours resolution requests on Windows webcams and
            # opens far quicker; the default MSMF backend frequently ignores
            # them and silently stays at 640x480.
            if local and sys.platform == "win32":
                cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(src)
            else:
                cap = cv2.VideoCapture(src)
            for prop, val in ((cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms),
                              (cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms),
                              (cv2.CAP_PROP_BUFFERSIZE, 1)):
                try:
                    cap.set(prop, val)
                except Exception:
                    pass
            if local:
                w = width or DEFAULT_CAPTURE_SIZE[0]
                h = height or DEFAULT_CAPTURE_SIZE[1]
                try:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                except Exception:
                    pass
            result["cap"] = cap
        except Exception as exc:
            result["error"] = str(exc)

    t = threading.Thread(target=_open, daemon=True)
    t.start()
    t.join(timeout_ms / 1000.0 + 2.0)

    cap = result.get("cap")
    if cap is None or not cap.isOpened():
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        return None
    return cap


def probe(source: str | int, timeout_ms: int = DEFAULT_TIMEOUT_MS
          ) -> tuple[bool, str]:
    """Try to grab one frame. Returns (ok, 'WxH' or reason)."""
    cap = open_capture(source, timeout_ms)
    if cap is None:
        return False, "لا يمكن الاتصال / cannot connect"
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            return False, "اتصل بدون صورة / connected but no frame"
        return True, f"{frame.shape[1]}x{frame.shape[0]}"
    finally:
        cap.release()
