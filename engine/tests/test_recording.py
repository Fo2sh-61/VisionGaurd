"""Recording a camera, started and stopped by a person.

This replaced three "Save clip" buttons that did nothing at all. The rule they
broke is constitution rule 4 — never show anything untrue — and the way a
recorder breaks the same rule is subtler than a dead button: it tells somebody
a file was saved. They go and look for it during an incident, and it is not
there, or it is empty, or it will not play.

So the tests below are mostly about the ways a recording can fail while
looking like it worked:

- a camera that sends no frames must not produce a "saved" recording of nothing
- a file must actually play back, with the frames that went in
- one camera cannot have two writers on it
- a recording nobody stopped must end by itself, and say that is why it ended
- and when recording is not running at all, pressing the button gets an honest
  refusal with a reason, never a plausible-looking result

There is no rolling buffer, deliberately. Recording starts when the button is
pressed and not a second earlier, which the UI has to say where it matters.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from vg.api import schemas as S
from vg.ingest import encoder
from vg.ingest.framebus import FrameBus
from vg.ingest.recorder import AlreadyRecording, Recorder
from vg.ingest.source import Frame

CAMERA = "cam-clip"


@pytest.fixture
def bus() -> FrameBus:
    return FrameBus()


@pytest.fixture
def recorder(bus):
    with tempfile.TemporaryDirectory() as tmp:
        yield Recorder(bus, Path(tmp), clock=180)


def publish(
    bus: FrameBus, n: int, camera: str = CAMERA, shade: int = 40, fps: float = 25.0
) -> None:
    """Publish `n` frames at a real rate, timestamped as a camera would."""
    gap = 1.0 / fps
    for i in range(n):
        image = np.full((240, 320, 3), (shade + i * 4) % 255, dtype=np.uint8)
        bus.publish(Frame(camera, image, datetime.now(timezone.utc), i))
        time.sleep(gap)


def playback_seconds(path) -> float:
    """How long the saved file lasts when somebody presses play."""
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    capture.release()
    return frames / fps if fps > 0 else 0.0


def settle(seconds: float = 0.4) -> None:
    """Let the recorder thread drain what was just published."""
    time.sleep(seconds)


class TestItWritesARealFile:
    def test_the_frames_that_went_in_come_back_out(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 25)
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        assert done.state == "saved"
        assert done.frames == 25
        assert done.path.exists() and done.path.stat().st_size > 0

        capture = cv2.VideoCapture(str(done.path))
        played = 0
        while capture.read()[0]:
            played += 1
        capture.release()
        assert played > 0, "the file plays back nothing at all"


class TestItPlaysBackAtRealSpeed:
    """The slow-motion bug.

    Two seconds of webcam came out as a twenty-five second file. An mp4 has one
    fixed frame rate, so the length of the file is decided entirely by how many
    frames went in against the rate written in its header. The header was being
    written from `fps` in engine.yaml — which is the ANALYTICS rate, how often
    the models run, and engine.yaml says exactly that on the line above it. A
    webcam delivering 25 frames a second into a file stamped "5 per second" is
    five times too long, and every movement in it is five times too slow.

    So the rule these defend: **the file lasts as long as the recording did.**
    """

    def test_a_two_second_recording_is_a_two_second_file(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 50, fps=25.0)  # two seconds of a 25 fps camera
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        # Generous bounds: this is wall-clock timing on a shared machine. The
        # bug it guards against was 5x, not 20%.
        assert 1.4 <= playback_seconds(done.path) <= 3.0, (
            "the file does not last as long as the recording did"
        )

    def test_the_analytics_rate_cannot_reach_the_file(self, bus, recorder):
        """engine.yaml says 5 fps for analytics. A 25 fps camera stamped at 5
        would play back five times too long."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 50, fps=25.0)
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        assert done.fps > 10.0, (
            f"the file was written at {done.fps} fps, close to the analytics "
            f"rate rather than what the camera delivered"
        )

    def test_a_slow_camera_is_not_sped_up_either(self, bus, recorder):
        """The mirror image. Five frames a second must not become a file that
        plays in a fifth of the time."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 10, fps=5.0)  # two seconds of a 5 fps camera
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        assert 1.2 <= playback_seconds(done.path) <= 3.0

    def test_a_recording_too_short_to_measure_still_saves(self, bus, recorder):
        """Press record, press stop. Two frames is still a real recording."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 2, fps=25.0)
        done = recorder.stop(CAMERA, actor="mohamed")

        assert done.state == "saved"
        assert done.path.exists() and done.path.stat().st_size > 0

    def test_the_name_says_which_camera_and_when(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 5)
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        assert done.path.name.startswith(f"{CAMERA}_")
        assert done.path.suffix == ".mp4"

    def test_stop_waits_for_the_file_to_be_closed(self, bus, recorder):
        """Returning early hands back a path nobody can open yet."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 10)
        done = recorder.stop(CAMERA, actor="mohamed")

        assert cv2.VideoCapture(str(done.path)).isOpened()


class TestTheWaysItCanLie:
    def test_a_camera_that_sent_nothing_is_a_failure_not_a_save(self, recorder):
        """The worst outcome: "saved" next to a file that is not there.

        Somebody looks for it during an incident and finds nothing.
        """
        recorder.max_seconds = 0.2
        recorder.start(CAMERA, actor="mohamed")
        settle(1.6)

        done = recorder.current(CAMERA)
        assert done.state == "failed"
        assert done.frames == 0
        assert done.path is None, "a path was reported for a file never written"
        assert done.reason

    def test_one_camera_cannot_have_two_writers(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        with pytest.raises(AlreadyRecording):
            recorder.start(CAMERA, actor="someone else")
        recorder.stop(CAMERA, actor="mohamed")

    def test_a_forgotten_recording_stops_itself_and_says_why(self, bus, recorder):
        """Overnight it is about 10 GB a camera. It has to end on its own,
        and ending has to be distinguishable from somebody pressing stop."""
        recorder.max_seconds = 0.3
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 10)
        settle(1.2)

        current = recorder.current(CAMERA)
        assert current.running is False
        assert current.reason and "automatically" in current.reason

    def test_a_plain_stop_gives_no_reason(self, bus, recorder):
        """A reason means something unexpected happened. A normal stop is not
        something to explain, and explaining it would make every recording
        look like it went wrong."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 5)
        settle()
        assert recorder.stop(CAMERA, actor="mohamed").reason is None

    def test_stopping_a_camera_that_is_not_recording_is_not_an_error(self, recorder):
        assert recorder.stop(CAMERA, actor="mohamed") is None

    def test_frames_from_another_camera_are_not_in_this_recording(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 8, camera="cam-other")
        publish(bus, 4, camera=CAMERA)
        settle()

        assert recorder.stop(CAMERA, actor="mohamed").frames == 4

    def test_shutdown_closes_every_open_file(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed")
        recorder.start("cam-two", actor="mohamed")
        publish(bus, 4)
        publish(bus, 4, camera="cam-two")
        settle()

        recorder.stop_all()
        assert recorder.running() == []


class TestWhatTheConsoleIsTold:
    def test_pressing_stop_after_it_already_stopped_still_says_where_it_went(
        self, bare_live_store, bus
    ):
        """The ten-minute limit fires, then the operator presses stop.

        A bare "this camera is not recording" would hide a file that was
        written seconds earlier.
        """
        with tempfile.TemporaryDirectory() as tmp:
            recorder = Recorder(bus, Path(tmp), clock=180, max_seconds=0.3)
            bare_live_store.recorder = recorder
            recorder.start(CAMERA, actor="mohamed")
            publish(bus, 6)
            # Wait for the limit to have actually fired and the file to be
            # closed, not a fixed nap: closing an H.264 file takes real time,
            # and this test is about the *already stopped* path, which only
            # exists once the recording has genuinely finished.
            deadline = time.monotonic() + 10.0
            while recorder.running() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not recorder.running(), "the limit never fired"

            result = bare_live_store.stop_recording(CAMERA, "mohamed")

        assert result.ok is False
        assert result.recording is not None and result.recording.file
        assert "automatically" in result.reason

    def test_the_last_recording_is_still_reportable_after_it_ends(self, bus, recorder):
        """The operator pressed stop and wants to know where the file went."""
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 5)
        settle()
        recorder.stop(CAMERA, actor="mohamed")

        assert recorder.current(CAMERA).state == "saved"

    def test_demo_mode_refuses_rather_than_pretending(self):
        """A fake save is worse than a dead button: it sends somebody looking
        for a file during an incident."""
        from vg.api.store import MockStore

        store = MockStore()
        for result in (store.start_recording(CAMERA, "mohamed"),
                       store.stop_recording(CAMERA, "mohamed"),
                       store.recording(CAMERA)):
            assert result.ok is False
            assert result.recording is None
            assert result.reason and len(result.reason) > 10

    def test_without_a_recorder_the_reason_is_stated(self, bare_live_store):
        result = bare_live_store.start_recording(CAMERA, "mohamed")
        assert result.ok is False
        assert "not running" in result.reason

    def test_the_capability_list_says_recording_is_unavailable(self, bare_live_store):
        cap = next(c for c in bare_live_store.capabilities() if c.key == "recording")
        assert cap.state == S.DataState.UNAVAILABLE
        assert cap.reason

    def test_an_unknown_camera_is_refused_by_name(self, bare_live_store, bus):
        with tempfile.TemporaryDirectory() as tmp:
            bare_live_store.recorder = Recorder(bus, Path(tmp), clock=180)
            result = bare_live_store.start_recording("cam-nope", "mohamed")

        assert result.ok is False and "cam-nope" in result.reason

    def test_a_dark_camera_is_refused_before_it_wastes_fifteen_seconds(
        self, bare_live_store, bus
    ):
        """Starting anyway gives a recording indicator and then an empty
        failure. Saying so now is kinder and just as true."""
        camera = bare_live_store.config.cameras[0]
        with tempfile.TemporaryDirectory() as tmp:
            bare_live_store.recorder = Recorder(bus, Path(tmp), clock=180)
            result = bare_live_store.start_recording(camera.id, "mohamed")

        assert result.ok is False
        assert "not sending frames" in result.reason


class TestTheFilePlaysInABrowser:
    """The console plays clips in a <video> tag, and browsers cannot decode
    MPEG-4 Part 2. A recording saved as mp4v looked perfectly healthy — real
    file, real frames, plays in a desktop player — and rendered in the console
    as a player with no picture. That is rule 4 through a codec: the button
    said Watch clip and the watching never happened.

    OpenCV's pip build ships no H.264 encoder (licensing), but on Windows it
    encodes through the OS's own Media Foundation, so asking costs nothing:
    a machine that can produce a browser-playable file does, and one that
    cannot still gets mp4v — a real recording, watchable in a desktop player,
    which beats no recording at all.
    """

    class _FakeWriter:
        """Stands in for cv2.VideoWriter; records what it was asked for."""

        opened_for: set[tuple[int, int]] = set()
        asked: list[tuple[int, int]] = []

        def __init__(self, path, backend, fourcc, fps, size) -> None:
            type(self).asked.append((backend, fourcc))
            self._ok = (backend, fourcc) in type(self).opened_for

        def isOpened(self) -> bool:
            return self._ok

        def write(self, image) -> None:
            pass

        def release(self) -> None:
            pass

    @pytest.fixture
    def fake_writer(self, monkeypatch):
        fake = self._FakeWriter
        fake.asked = []
        fake.opened_for = set()
        # The chooser remembers what worked last. An earlier test in this
        # session picking the real encoder would otherwise reorder the list
        # under this one.
        encoder._reset_for_tests()
        monkeypatch.setattr(cv2, "VideoWriter", fake)
        return fake

    @pytest.mark.skipif(sys.platform != "win32", reason="Media Foundation is Windows")
    def test_the_windows_h264_encoder_is_asked_for_by_name(self):
        """The bug this class is named for, in one line.

        `cv2.VideoWriter(path, fourcc, ...)` with no backend picks FFmpeg for
        an .mp4 and stops there. OpenCV's pip build has no H.264 encoder, so
        that ask always failed here and every recording fell through to mp4v —
        while the comment above it said Media Foundation would be used. It
        never was, because nothing named it.
        """
        first = encoder.candidates()[0]
        assert first.backend == cv2.CAP_MSMF, (
            "on Windows the OS encoder must be named explicitly, or OpenCV "
            "silently uses FFmpeg and writes a file the console cannot play"
        )
        assert first.plays_in_browser

    def test_h264_is_asked_for_before_mp4v(self, bus, recorder, fake_writer):
        playable = [c.plays_in_browser for c in encoder.candidates()]
        assert playable[0] is True, (
            "the browser-playable codec must be the first choice"
        )
        assert playable[-1] is False, (
            "and mp4v the last resort, so a recording always exists"
        )
        assert playable == sorted(playable, reverse=True), (
            "every playable encoder is tried before the one that is not"
        )

        best = encoder.candidates()[0]
        fake_writer.opened_for = {
            (best.backend, cv2.VideoWriter_fourcc(*best.fourcc))}
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 15)
        settle()
        recording = recorder.stop(CAMERA, actor="mohamed")

        assert fake_writer.asked[0] == (
            best.backend, cv2.VideoWriter_fourcc(*best.fourcc))
        assert recording.state == "saved"

    def test_a_machine_without_h264_falls_back_to_mp4v(
            self, bus, recorder, fake_writer):
        # Every H.264 route refuses; the recording must still happen rather
        # than fail on a machine with a lean OS install.
        last = encoder.candidates()[-1]
        assert not last.plays_in_browser
        fake_writer.opened_for = {
            (last.backend, cv2.VideoWriter_fourcc(*last.fourcc))}
        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 15)
        settle()
        recording = recorder.stop(CAMERA, actor="mohamed")

        assert fake_writer.asked == [
            (c.backend, cv2.VideoWriter_fourcc(*c.fourcc))
            for c in encoder.candidates()
        ], "tried in preference order, every one of them"
        assert recording.state == "saved"

    def test_this_machine_writes_a_file_the_browser_can_decode(self, bus, recorder):
        # End to end with the real writer. This used to skip on Windows —
        # it probed the default backend, which has no H.264, and so never
        # ran on the machine whose recordings were broken. It probes the
        # real chooser now, and therefore runs here.
        encoder._reset_for_tests()
        probe_path = recorder.directory / "probe.mp4"
        writer, chosen = encoder.open_writer(probe_path, 15.0, 320, 240)
        if writer is not None:
            writer.release()
        probe_path.unlink(missing_ok=True)
        if chosen is None or not chosen.plays_in_browser:
            pytest.skip(f"no H.264 encoder on this machine (best: {chosen})")

        recorder.start(CAMERA, actor="mohamed")
        publish(bus, 20)
        settle()
        recording = recorder.stop(CAMERA, actor="mohamed")

        assert recording.state == "saved"
        capture = cv2.VideoCapture(str(recording.path))
        raw = int(capture.get(cv2.CAP_PROP_FOURCC))
        capture.release()
        tag = "".join(chr((raw >> 8 * i) & 0xFF) for i in range(4)).lower()
        assert tag in ("avc1", "h264"), (
            f"the file is {tag!r} — a browser cannot decode that"
        )
