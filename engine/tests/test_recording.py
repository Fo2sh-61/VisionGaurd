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


def publish(bus: FrameBus, n: int, camera: str = CAMERA, shade: int = 40) -> None:
    for i in range(n):
        image = np.full((240, 320, 3), (shade + i * 4) % 255, dtype=np.uint8)
        bus.publish(Frame(camera, image, datetime.now(timezone.utc), i))
        time.sleep(0.01)


def settle(seconds: float = 0.4) -> None:
    """Let the recorder thread drain what was just published."""
    time.sleep(seconds)


class TestItWritesARealFile:
    def test_the_frames_that_went_in_come_back_out(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
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
        assert played == 25, "the file does not play back what was recorded"

    def test_the_name_says_which_camera_and_when(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        publish(bus, 5)
        settle()
        done = recorder.stop(CAMERA, actor="mohamed")

        assert done.path.name.startswith(f"{CAMERA}_")
        assert done.path.suffix == ".mp4"

    def test_stop_waits_for_the_file_to_be_closed(self, bus, recorder):
        """Returning early hands back a path nobody can open yet."""
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        publish(bus, 10)
        done = recorder.stop(CAMERA, actor="mohamed")

        assert cv2.VideoCapture(str(done.path)).isOpened()


class TestTheWaysItCanLie:
    def test_a_camera_that_sent_nothing_is_a_failure_not_a_save(self, recorder):
        """The worst outcome: "saved" next to a file that is not there.

        Somebody looks for it during an incident and finds nothing.
        """
        recorder.max_seconds = 0.2
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        settle(1.6)

        done = recorder.current(CAMERA)
        assert done.state == "failed"
        assert done.frames == 0
        assert done.path is None, "a path was reported for a file never written"
        assert done.reason

    def test_one_camera_cannot_have_two_writers(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        with pytest.raises(AlreadyRecording):
            recorder.start(CAMERA, actor="someone else", fps=10.0)
        recorder.stop(CAMERA, actor="mohamed")

    def test_a_forgotten_recording_stops_itself_and_says_why(self, bus, recorder):
        """Overnight it is about 10 GB a camera. It has to end on its own,
        and ending has to be distinguishable from somebody pressing stop."""
        recorder.max_seconds = 0.3
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        publish(bus, 10)
        settle(1.2)

        current = recorder.current(CAMERA)
        assert current.running is False
        assert current.reason and "automatically" in current.reason

    def test_a_plain_stop_gives_no_reason(self, bus, recorder):
        """A reason means something unexpected happened. A normal stop is not
        something to explain, and explaining it would make every recording
        look like it went wrong."""
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        publish(bus, 5)
        settle()
        assert recorder.stop(CAMERA, actor="mohamed").reason is None

    def test_stopping_a_camera_that_is_not_recording_is_not_an_error(self, recorder):
        assert recorder.stop(CAMERA, actor="mohamed") is None

    def test_frames_from_another_camera_are_not_in_this_recording(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        publish(bus, 8, camera="cam-other")
        publish(bus, 4, camera=CAMERA)
        settle()

        assert recorder.stop(CAMERA, actor="mohamed").frames == 4

    def test_shutdown_closes_every_open_file(self, bus, recorder):
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
        recorder.start("cam-two", actor="mohamed", fps=10.0)
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
            recorder.start(CAMERA, actor="mohamed", fps=10.0)
            publish(bus, 6)
            settle(1.2)

            result = bare_live_store.stop_recording(CAMERA, "mohamed")

        assert result.ok is False
        assert result.recording is not None and result.recording.file
        assert "automatically" in result.reason

    def test_the_last_recording_is_still_reportable_after_it_ends(self, bus, recorder):
        """The operator pressed stop and wants to know where the file went."""
        recorder.start(CAMERA, actor="mohamed", fps=10.0)
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
