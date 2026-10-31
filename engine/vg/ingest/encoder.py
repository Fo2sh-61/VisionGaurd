"""Pick a video encoder this machine actually has.

The console plays saved clips in a `<video>` tag, and browsers decode H.264
(`avc1`) but not MPEG-4 Part 2 (`mp4v`). An mp4v clip looks perfectly healthy
on disk and renders as a player with no picture — a dead button with extra
steps.

OpenCV's pip build ships no H.264 encoder, for licensing reasons. Asking its
FFmpeg backend for `avc1` on Windows therefore fails, loudly, in native code
that Python cannot catch:

    Failed to load OpenH264 library: openh264-2.5.0-win64.dll
    [ERROR] VIDEOIO/FFMPEG: Failed to initialize VideoWriter

Windows already has an H.264 encoder — Media Foundation — and OpenCV can use
it, but only when it is *asked for by name*. `cv2.VideoWriter(path, fourcc,
...)` with no backend picks FFmpeg for an `.mp4` and never tries anything
else, so every recording on this machine fell through to mp4v and would not
play. Naming `CAP_MSMF` is the whole fix: it writes real H.264 at every frame
size, needs no download, and never reaches the FFmpeg path that prints the
error above.

So this module exists to hold the ordered list in **one** place. The recorder
and the archive exporter both write mp4s, both used to carry their own copy of
"try avc1, then mp4v", and both were wrong in the same way.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Encoder:
    """One way of writing an mp4, and whether the console can play the result."""

    backend: int
    fourcc: str
    label: str
    plays_in_browser: bool
    #: Frames go to a separate `ffmpeg` process instead of an OpenCV writer.
    pipe: bool = False

    def __str__(self) -> str:
        return self.label


#: Media Foundation, named explicitly. The fourcc is along for the ride — the
#: mp4 sink encodes H.264 whatever tag it is handed — but `avc1` is what the
#: file ends up containing, so that is what it says here.
MSMF_H264 = Encoder(cv2.CAP_MSMF, "avc1", "Media Foundation H.264", True)

#: FFmpeg with a real OpenH264 alongside it. Not this machine, but it is how a
#: Linux box with the library installed gets browser-playable clips.
FFMPEG_H264 = Encoder(cv2.CAP_FFMPEG, "avc1", "FFmpeg H.264", True)

#: The system's own `ffmpeg` program with `libx264`, frames piped to it raw.
#: Linux has no Media Foundation, and OpenCV's pip wheel has no H.264 there
#: either, so without this a Linux machine (the cloud trial) saves clips the
#: console cannot play. `ffmpeg` with x264 is a standard package.
PIPE_X264 = Encoder(-1, "avc1", "ffmpeg program, libx264", True, pipe=True)

#: The last resort. A real recording that a desktop player opens and the
#: console cannot — worth having, and worth saying out loud.
FFMPEG_MP4V = Encoder(cv2.CAP_FFMPEG, "mp4v", "FFmpeg MPEG-4 Part 2", False)


def candidates() -> tuple[Encoder, ...]:
    """Every encoder worth trying, best first.

    Media Foundation goes first on Windows and is absent everywhere else, so
    the FFmpeg path — and the OpenH264 error it prints — is only reached on a
    machine where it is the only option left. Windows never reaches for the
    `ffmpeg` program: Media Foundation is always there.
    """
    if sys.platform == "win32":
        return (MSMF_H264, FFMPEG_H264, FFMPEG_MP4V)
    return (FFMPEG_H264, PIPE_X264, FFMPEG_MP4V)


def _ffmpeg_candidates() -> list[str]:
    """Every `ffmpeg` worth asking, in order: `VG_FFMPEG`, PATH, the system's.

    The first one on PATH is not always the useful one. On Kaggle it is a
    build with no libx264 that shadows the distribution's `/usr/bin/ffmpeg`,
    which has it - the cloud trial's first run stopped on exactly that.
    """
    found = [os.environ.get("VG_FFMPEG", "").strip(), shutil.which("ffmpeg") or "",
             "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    seen: list[str] = []
    for exe in found:
        if exe and exe not in seen and Path(exe).is_file():
            seen.append(exe)
    return seen


@functools.lru_cache(maxsize=1)
def _ffmpeg_with_x264() -> str | None:
    """The first `ffmpeg` program that has libx264, or None. Asked once.

    Checked up front because ffmpeg only opens its encoder once frames
    arrive: without this, a build with no x264 would look open, take a
    whole recording, and leave a broken file.
    """
    for exe in _ffmpeg_candidates():
        try:
            listed = subprocess.run(
                [exe, "-hide_banner", "-encoders"], capture_output=True,
                timeout=15, check=False).stdout.decode(errors="replace")
        except (OSError, subprocess.SubprocessError):
            continue
        if " libx264 " in listed:
            return exe
    return None


class PipeWriter:
    """`cv2.VideoWriter`'s three methods, over an `ffmpeg` process.

    `-movflags +faststart` puts the index at the front, so a browser can start
    playing before it has the whole file. `yuv420p` because browsers decode
    nothing else from H.264. stderr goes to a temporary file, not a pipe: an
    unread pipe fills and stalls ffmpeg, and with it the recorder.
    """

    def __init__(self, path: Path | str, fps: float, width: int, height: int):
        self._path = Path(path)
        self._size = (width, height)
        self._log = tempfile.TemporaryFile()
        self._proc: subprocess.Popen | None = None
        exe = _ffmpeg_with_x264()
        if exe is None:
            return
        try:
            self._proc = subprocess.Popen(
                [exe, "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "rawvideo", "-pix_fmt", "bgr24",
                 "-s", f"{width}x{height}", "-r", f"{max(1.0, fps):g}", "-i", "-",
                 "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 str(self._path)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._log,
            )
        except OSError:
            self._proc = None

    def isOpened(self) -> bool:  # noqa: N802 - cv2.VideoWriter's name
        return self._proc is not None and self._proc.poll() is None

    def write(self, frame) -> None:
        if not self.isOpened() or self._proc.stdin is None:
            return
        if (frame.shape[1], frame.shape[0]) != self._size:
            frame = cv2.resize(frame, self._size)
        try:
            self._proc.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError):
            pass

    def release(self) -> None:
        if self._proc is None:
            self._log.close()
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            code = self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            code = -1
        if code != 0:
            self._log.seek(0)
            log.warning("ffmpeg exited %s writing %s: %s", code, self._path,
                        self._log.read().decode(errors="replace").strip()[-500:])
        self._log.close()
        self._proc = None


_lock = threading.Lock()
_chosen: Encoder | None = None
_warmed = False


def chosen() -> Encoder | None:
    """The encoder that last opened a file, or None if none has yet."""
    with _lock:
        return _chosen


def _ordered() -> tuple[Encoder, ...]:
    """Candidates with the one already known to work moved to the front.

    Still the full list, never just the winner: a size or a frame rate one
    backend refuses is a reason to fall back, not a reason to fail.
    """
    with _lock:
        first = _chosen
    if first is None:
        return candidates()
    return (first,) + tuple(c for c in candidates() if c != first)


def open_writer(
    path: Path | str, fps: float, width: int, height: int
) -> tuple[cv2.VideoWriter | None, Encoder | None]:
    """Open an mp4 writer with the best encoder this machine has.

    Returns the writer and the encoder that opened it, or `(None, None)` when
    nothing worked. The caller decides what a missing encoder means — the
    recorder fails that recording, the exporter refuses the export — because
    "no encoder" is not the same answer as "the file would not open".
    """
    if width <= 0 or height <= 0:
        return None, None

    global _chosen
    for encoder in _ordered():
        if encoder.pipe:
            writer = PipeWriter(path, fps, width, height)
        else:
            writer = cv2.VideoWriter(
                str(path), encoder.backend, cv2.VideoWriter_fourcc(*encoder.fourcc),
                max(1.0, fps), (width, height),
            )
        if writer.isOpened():
            with _lock:
                if _chosen != encoder:
                    _chosen = encoder
                    log.info("encoding video with %s", encoder.label)
            return writer, encoder
        writer.release()

    return None, None


def warm() -> None:
    """Pay the encoder's one-time start-up cost now, off-thread.

    The first open in a process costs an extra second while OpenCV loads the
    backend. Paid lazily, that second lands inside somebody's first recording,
    right at the start of whatever made them press the button. Paid here, it
    lands while the engine is still starting and nobody is watching.

    It also settles `chosen()` before anything asks, so the log says which
    encoder this machine has at start-up rather than at the first recording.
    """
    global _warmed
    with _lock:
        if _warmed:
            return
        _warmed = True

    def run() -> None:
        path = Path(tempfile.gettempdir()) / "vg-encoder-warmup.mp4"
        try:
            writer, encoder = open_writer(path, 15.0, 64, 64)
            if writer is not None:
                writer.release()
            if encoder is None:
                log.warning(
                    "no video encoder on this machine - recording and clip "
                    "export will fail with that reason")
            elif not encoder.plays_in_browser:
                log.warning(
                    "no H.264 encoder on this machine - clips will be written "
                    "with %s, which saves and plays in a desktop player but "
                    "shows no picture in the console", encoder.label)
        except Exception:  # noqa: BLE001 - a warm-up may not break anything
            log.debug("encoder warm-up failed", exc_info=True)
        finally:
            path.unlink(missing_ok=True)

    threading.Thread(target=run, name="encoder-warmup", daemon=True).start()


def _reset_for_tests() -> None:
    """Forget the remembered encoder, and do not warm. Tests only.

    Warming is left marked done on purpose. A test that swaps `cv2.VideoWriter`
    for a fake does not want a background thread opening a real one behind it,
    and every `Recorder` built by a test would start one.
    """
    global _chosen, _warmed
    with _lock:
        _chosen = None
        _warmed = True
