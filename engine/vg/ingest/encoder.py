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

import logging
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

    def __str__(self) -> str:
        return self.label


#: Media Foundation, named explicitly. The fourcc is along for the ride — the
#: mp4 sink encodes H.264 whatever tag it is handed — but `avc1` is what the
#: file ends up containing, so that is what it says here.
MSMF_H264 = Encoder(cv2.CAP_MSMF, "avc1", "Media Foundation H.264", True)

#: FFmpeg with a real OpenH264 alongside it. Not this machine, but it is how a
#: Linux box with the library installed gets browser-playable clips.
FFMPEG_H264 = Encoder(cv2.CAP_FFMPEG, "avc1", "FFmpeg H.264", True)

#: The last resort. A real recording that a desktop player opens and the
#: console cannot — worth having, and worth saying out loud.
FFMPEG_MP4V = Encoder(cv2.CAP_FFMPEG, "mp4v", "FFmpeg MPEG-4 Part 2", False)


def candidates() -> tuple[Encoder, ...]:
    """Every encoder worth trying, best first.

    Media Foundation goes first on Windows and is absent everywhere else, so
    the FFmpeg path — and the OpenH264 error it prints — is only reached on a
    machine where it is the only option left.
    """
    if sys.platform == "win32":
        return (MSMF_H264, FFMPEG_H264, FFMPEG_MP4V)
    return (FFMPEG_H264, FFMPEG_MP4V)


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
