"""A closed camera view lets go of its stream; a recorded clip plays in real time.

Two bugs, found together on 12 Sep 2026 while measuring camera tiles.

**Closing the enlarged view left its live stream running.** A browser keeps
loading an image after its element leaves the page - the HTML spec says so -
and an MJPEG response never finishes, so the connection stayed open until the
whole page was left. The engine counts an open stream as somebody watching,
so the camera kept reading and converting every frame for nobody: 822 a
second on the recorded clip with the view closed. The Track page's big view and enrolment's
live view did the same. Measured in the browser: removing the element leaves
the stream open; `removeAttribute('src')` closes it and fires no event;
`src = ''` closes it but fires `error`.

**A recorded-clip camera ran about thirty times too fast.** A live camera's
`grab()` waits for the device's next frame; a file's does not, so the engine
pulled 495 frames a second from the 15 fps clip.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from vg.ingest import source as vgsource
from vg.ingest.source import CameraSource

ROOT = Path(__file__).resolve().parents[2]
#: Both apps' copies. The phone had this leak too; checking only the console
#: left the phone's copy free to regress unnoticed.
CAMERA_FRAMES = {
    app: ROOT / app / "src" / "components" / "CameraFrame.tsx"
    for app in ("web", "mobile")
}


# ---------------------------------------------------------------------------
# the console lets go of a stream it has stopped showing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("app", sorted(CAMERA_FRAMES))
class TestTheConsoleLetsGoOfTheStream:
    """A source check, because there is no runtime state that reveals it.

    The repo has no browser test runner, and the leak is invisible from
    inside the page: the element is gone, the connection is not. What this
    pins is the one shape measured to work - an element that owns its `src`
    and removes it - so a tidy-up cannot quietly put back the plain
    `<img src={camera.streamUrl}>` that leaked.
    """

    @staticmethod
    def _source(app: str) -> str:
        return CAMERA_FRAMES[app].read_text(encoding="utf-8")

    def _stream_image(self, app: str) -> str:
        source = self._source(app)
        start = source.index("function StreamImage(")
        return source[start:source.index("export function CameraFrame(", start)]

    def test_the_stream_element_removes_its_address_when_it_stops(self, app):
        body = self._stream_image(app)
        assert "useLayoutEffect(" in body
        assert "img.src = src;" in body, (
            "the stream element must set its own src, so React never owns it")
        assert "removeAttribute('src')" in body, (
            "removing the element does not close an MJPEG connection; "
            "removing its src does")

    def test_the_live_view_draws_the_stream_through_it(self, app):
        source = self._source(app)
        assert re.search(r"useStream\s*\?\s*\(\s*<StreamImage src=\{frameSrc\}", source), (
            "the stream must be drawn by StreamImage, not a plain <img>")
        assert "src={camera.streamUrl}" not in source

    def test_letting_go_never_reads_as_a_failed_camera(self, app):
        """`src = ''` closes the stream too, but fires `error`, and
        CameraFrame's error handler marks the camera's picture as failed."""
        source = self._source(app)
        assert not re.search(r"""\.src\s*=\s*(''|"")""", source)
        assert not re.search(r"""setAttribute\(\s*['"]src['"]\s*,\s*(''|"")""", source)


# ---------------------------------------------------------------------------
# a recorded file plays at the rate it was recorded at
# ---------------------------------------------------------------------------

RECORDED_FPS = 10.0


@pytest.fixture
def clip(tmp_path) -> Path:
    """A two-second 10 fps clip, so pacing is visible in a fraction of a second."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"),
                             RECORDED_FPS, (64, 48))
    if not writer.isOpened():
        pytest.skip("this OpenCV build cannot write an MJPG .avi")
    for i in range(20):
        writer.write(np.full((48, 64, 3), i * 12, np.uint8))
    writer.release()
    return path


def grabs(cam: CameraSource) -> int:
    return cam.health.frames_read + cam.health.frames_skipped


class TestAFileCameraPlaysInRealTime:
    def test_the_recorded_rate_is_read_from_the_file(self, clip):
        cam = CameraSource("c1", str(clip))
        try:
            assert cam.open()
            assert cam._file_interval == pytest.approx(1 / RECORDED_FPS)
        finally:
            cam.close()

    def test_a_file_with_no_usable_rate_plays_at_the_fallback(self, clip, monkeypatch):
        real = cv2.VideoCapture

        class NoRate:
            def __init__(self, *args):
                self._cap = real(*args)

            def get(self, prop):
                return 0.0 if prop == cv2.CAP_PROP_FPS else self._cap.get(prop)

            def __getattr__(self, name):
                return getattr(self._cap, name)

        monkeypatch.setattr(vgsource.cv2, "VideoCapture", NoRate)
        cam = CameraSource("c1", str(clip))
        try:
            assert cam.open()
            assert cam._file_interval == pytest.approx(1 / vgsource._FILE_FPS_FALLBACK)
        finally:
            cam.close()

    def test_an_open_view_decodes_at_the_recorded_rate_not_flat_out(self, clip):
        """Every frame decoded, as while somebody has the camera open: 6
        frames of a 10 fps clip take half a second, not a few milliseconds."""
        cam = CameraSource("c1", str(clip), live_capture="always")
        try:
            assert cam.open()
            started = time.monotonic()
            for _ in range(6):
                assert cam.read() is not None
            # The first frame is due at once, the next five a tenth apart.
            assert time.monotonic() - started >= 0.4
        finally:
            cam.close()

    def test_nobody_watching_still_grabs_at_the_recorded_rate(self, clip):
        """Unwatched, most frames are grabbed and skipped. Before this they
        were grabbed as fast as the loop could turn."""
        cam = CameraSource("c1", str(clip), target_fps=5.0)
        try:
            assert cam.open()
            started = time.monotonic()
            for _ in range(3):
                assert cam.read() is not None
            elapsed = time.monotonic() - started
            # Pacing can only make this slower, never faster, so the bound
            # holds on a loaded machine.
            assert grabs(cam) <= elapsed * RECORDED_FPS + 2
        finally:
            cam.close()

    def test_stopping_while_it_waits_ends_the_read(self, clip):
        """Stop used to send a file straight into rewind-and-read-again, and
        with the stop flag set that repeats until the stack runs out. The
        wait for the next frame made that the usual way for a file camera to
        be stopped."""
        cam = CameraSource("c1", str(clip))
        assert cam.open()
        cam._file_due = time.monotonic() + 30  # the next frame is a long way off
        outcome: list = []

        def read():
            try:
                outcome.append(cam.read())
            except BaseException as exc:  # noqa: BLE001 - the thing under test
                outcome.append(exc)

        reader = threading.Thread(target=read)
        reader.start()
        time.sleep(0.1)
        cam.stop()
        reader.join(timeout=2.0)
        try:
            assert not reader.is_alive(), "stop must end a read waiting on the file's pace"
            assert outcome and not isinstance(outcome[0], BaseException), outcome
        finally:
            cam.close()

    def test_looping_round_does_not_cost_an_extra_frame(self, clip):
        """Coming round to the start must not cost a frame's wait.

        The grab that finds the end of the file spends a slot of its own
        before failing, so the first frame of the next loop was due two
        intervals out instead of one - a hitch every time the clip came
        round, measured at 217 ms against 108 ms on a 10 fps file.

        The deadline is asserted directly rather than timed: how long a read
        takes depends on the machine, where the deadline the rewind leaves
        behind does not.
        """
        cam = CameraSource("c1", str(clip))
        try:
            assert cam.open()
            cam._file_due = time.monotonic() + 5 * cam._file_interval
            assert cam._rewind()
            assert cam._file_due - time.monotonic() <= cam._file_interval * 0.5, (
                "a rewind must put the next frame due now, not keep the slot "
                "the end-of-file grab had already taken")
        finally:
            cam.close()

    def test_a_looped_file_keeps_playing_at_its_rate(self, clip):
        """And the loop itself still works: 25 frames off a 20-frame clip,
        without reopening it, at about the rate it was recorded."""
        cam = CameraSource("c1", str(clip), live_capture="always")
        try:
            assert cam.open()
            started = time.monotonic()
            for _ in range(25):
                assert cam.read() is not None
            assert cam.health.reconnects == 0, "it looped rather than reopening"
            assert time.monotonic() - started >= 24 * cam._file_interval * 0.8
        finally:
            cam.close()

    def test_a_stopped_file_camera_does_not_rewind_for_ever(self, clip):
        """The loop that grabs does not run once stop is set, so a read after
        stop found no frame, took it for the end of the file, rewound and
        read again - recursion until the stack ran out."""
        cam = CameraSource("c1", str(clip))
        try:
            assert cam.open()
            cam.stop()
            assert cam.read() is None  # nothing captured yet, and no RecursionError
        finally:
            cam.close()

    def test_a_live_camera_is_never_paced_by_the_engine(self):
        """The device paces a webcam or an RTSP stream; adding a wait would
        only put the picture behind."""
        for spec in ("webcam:99", "rtsp://127.0.0.1:1/none"):
            assert CameraSource("c1", spec)._file_interval == 0.0
