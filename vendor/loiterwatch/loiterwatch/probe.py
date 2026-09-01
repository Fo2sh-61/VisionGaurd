"""Find the stream URL of an IP camera by trying the paths vendors actually use.

There is no standard. ONVIF discovery exists but plenty of cheap cameras
implement it badly or not at all, while nearly all of them answer RTSP on 554
with *some* vendor-specific path. Trying a list is unglamorous and works.

Two failure modes are worth telling apart, and the RTSP status code does it:
  401 Unauthorized -- the path may be fine, the credentials are wrong
  404 Not Found    -- credentials accepted, this path does not exist
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from urllib.parse import quote

# ordered roughly by how often they turn up on generic ONVIF/Chinese cameras,
# which is what most unbranded "Camera" web UIs are
RTSP_PATHS = [
    "/11",
    "/12",
    "/live/ch0",
    "/live/ch00_0",
    "/live/ch1",
    "/onvif1",
    "/onvif2",
    "/stream1",
    "/stream2",
    "/h264/ch1/main/av_stream",
    "/cam/realmonitor?channel=1&subtype=0",
    "/Streaming/Channels/101",
    "/live.sdp",
    "/video1",
    "/media/video1",
    "/ch0_0.264",
    "/1/h264major",
    "/axis-media/media.amp",
    "/",
]

HTTP_PATHS = [
    "/video",
    "/videostream.cgi",
    "/mjpg/video.mjpg",
    "/video.mjpg",
]


@dataclass
class ProbeResult:
    url: str
    ok: bool
    detail: str = ""
    width: int = 0
    height: int = 0

    @property
    def display(self) -> str:
        size = f"{self.width}x{self.height}" if self.width else "?"
        return f"{'OK ' if self.ok else '-- '} {self.url}" + (
            f"   [{size}]" if self.ok else "")


def build_urls(host: str, user: str = "", password: str = "",
               port: int = 554, http_port: int = 80,
               include_http: bool = True) -> list[str]:
    """Candidate URLs. Credentials are percent-encoded, which is the thing
    people most often get wrong by hand -- a `@` or `/` in a password silently
    breaks URL parsing and comes back looking like an auth failure."""
    if user or password:
        credentials = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    else:
        credentials = ""
    urls = [f"rtsp://{credentials}{host}:{port}{path}" for path in RTSP_PATHS]
    if include_http:
        urls += [f"http://{credentials}{host}:{http_port}{path}"
                 for path in HTTP_PATHS]
    return urls


def try_url(url: str, timeout: float = 6.0) -> ProbeResult:
    """Open a stream and read one frame, giving up after `timeout`.

    The read runs on a worker thread because a wrong RTSP path can leave
    OpenCV's ffmpeg backend blocking well past its own timeout, and a prober
    that hangs on candidate three is useless.
    """
    import cv2

    outcome: dict = {"ok": False, "detail": "timed out", "w": 0, "h": 0}

    def attempt() -> None:
        capture = None
        try:
            capture = cv2.VideoCapture(url)
            if not capture.isOpened():
                outcome["detail"] = "could not open"
                return
            ok, frame = capture.read()
            if not ok or frame is None:
                outcome["detail"] = "opened but sent no frame"
                return
            outcome.update(ok=True, detail="", w=frame.shape[1], h=frame.shape[0])
        except Exception as exc:  # noqa: BLE001
            outcome["detail"] = str(exc)[:80]
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(timeout)
    return ProbeResult(url, outcome["ok"], outcome["detail"],
                       outcome["w"], outcome["h"])


def set_ffmpeg_timeouts(seconds: float = 4.0) -> None:
    """Force TCP and a socket timeout, so dead paths fail fast.

    Must be set before the first capture is created -- OpenCV reads this
    environment variable when it initialises the ffmpeg backend.

    TCP rather than the default UDP is also what you want for a real run: UDP
    drops packets under load and produces smeared, half-decoded frames, which a
    detector happily reports as low-confidence people.
    """
    micros = int(seconds * 1_000_000)
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        f"rtsp_transport;tcp|stimeout;{micros}|timeout;{micros}",
    )


def quiet_ffmpeg() -> None:
    """Silence ffmpeg's decoder chatter.

    H.265 cameras emit `VPS 0 does not exist` on essentially every keyframe
    boundary -- harmless, but it repeats forever and buries the alert output
    that the console is actually there to show.
    """
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")  # AV_LOG_QUIET


def probe(host: str, user: str = "", password: str = "", port: int = 554,
          http_port: int = 80, timeout: float = 6.0, include_http: bool = True,
          on_result=None) -> list[ProbeResult]:
    set_ffmpeg_timeouts(min(timeout, 4.0))
    results: list[ProbeResult] = []
    for url in build_urls(host, user, password, port, http_port, include_http):
        result = try_url(url, timeout)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results
