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

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from vg.api import schemas as S
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
            settle(1.2)

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
