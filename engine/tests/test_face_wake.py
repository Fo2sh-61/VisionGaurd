"""Face recognition that wakes on motion (`face_wake: motion`).

An attendance camera is empty most of the day and the face models are the
costliest thing it runs on the processor. These tests pin the two halves of
the bargain: a still, empty picture is not looked at, and nobody who is
actually in front of the camera is missed because of it - including a person
who walks up and then stands still.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vg.config import CameraConfig, ConfigError
from vg.features.recognition import (
    WAKE_HEARTBEAT_SECONDS,
    WAKE_HOLD_SECONDS,
    MotionWake,
    RecognitionWorker,
)
from vg.ingest.source import Frame

MODEL = "sface-2021dec"
START = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)

EMPTY = np.full((120, 160, 3), 90, dtype=np.uint8)
SOMEONE = EMPTY.copy()
SOMEONE[30:100, 60:110] = 220  # a bright figure where the empty hall was


def frame(image, seconds, camera_id="cam-door", sequence=0):
    return Frame(camera_id=camera_id, image=image,
                 captured_at=START + timedelta(seconds=seconds), sequence=sequence)


# -- fakes, after test_track_page.py ----------------------------------------

class FakeFace:
    def __init__(self):
        self.x, self.y, self.w, self.h = 10, 10, 120, 120
        self.confidence = 0.99

    def to_fractions(self, fw, fh):
        return 0.1, 0.1, 0.2, 0.4


class FakeObservation:
    model = MODEL

    def __init__(self):
        self.face = FakeFace()
        self.embedding = np.zeros(128, dtype="float32")


class CountingPipeline:
    """Says whether the face models ran, and finds a face only when told to."""

    model_name = MODEL

    def __init__(self, faces=False):
        self.faces = faces
        self.calls = 0

    def observe(self, image, **kw):
        self.calls += 1
        return [FakeObservation()] if self.faces else []


class NoMatch:
    person, score, runner_up, reason = None, 0.1, 0.0, "below threshold"


class FakeGallery:
    def match(self, embedding, model=None):
        return NoMatch()


class FakeSightings:
    def seen_today(self, person_id, when=None):
        return True

    def record(self, sighting, force=False):
        return True


class NoBus:
    def subscribe(self, *a, **kw):
        raise AssertionError("not started in these tests")


def worker(pipeline, wake=("cam-door",)):
    return RecognitionWorker(NoBus(), FakeGallery(), FakeSightings(),
                             pipeline=pipeline, cameras=["cam-door"], wake=wake)


# -- the picture comparison --------------------------------------------------

class TestMotionWake:
    def test_the_first_frame_is_always_looked_at(self):
        assert MotionWake().should_look("cam-door", EMPTY, START)

    def test_a_still_picture_sleeps_once_the_hold_runs_out(self):
        wake = MotionWake()
        wake.should_look("cam-door", EMPTY, START)

        assert wake.should_look("cam-door", EMPTY, START + timedelta(seconds=1))
        assert not wake.should_look(
            "cam-door", EMPTY, START + timedelta(seconds=WAKE_HOLD_SECONDS + 1))

    def test_somebody_walking_in_wakes_it(self):
        wake = MotionWake()
        late = START + timedelta(seconds=WAKE_HOLD_SECONDS + 1)
        wake.should_look("cam-door", EMPTY, START)
        assert not wake.should_look("cam-door", EMPTY, late)

        assert wake.should_look("cam-door", SOMEONE, late + timedelta(seconds=0.5))

    def test_a_still_picture_is_still_looked_at_now_and_then(self):
        """A face that turns towards the camera without moving much is found."""
        wake = MotionWake()
        wake.should_look("cam-door", EMPTY, START)
        looks = [s for s in range(1, 41)
                 if wake.should_look("cam-door", EMPTY, START + timedelta(seconds=s))]

        # The hold, then one look per heartbeat.
        hold = [s for s in looks if s < WAKE_HOLD_SECONDS]
        assert looks[len(hold):] == [
            int(hold[-1] + WAKE_HEARTBEAT_SECONDS * n) for n in (1, 2, 3)]

    def test_sensor_noise_is_not_movement(self):
        rng = np.random.default_rng(0)
        noisy = np.clip(EMPTY.astype(int) + rng.integers(-6, 7, EMPTY.shape),
                        0, 255).astype(np.uint8)
        wake = MotionWake()
        wake.should_look("cam-door", EMPTY, START)

        assert not wake.moved("cam-door", noisy)

    def test_a_picture_that_changes_size_counts_as_movement(self):
        """A reconnect at another resolution must not be compared, or crash."""
        wake = MotionWake()
        wake.moved("cam-door", EMPTY)

        assert wake.moved("cam-door", np.zeros((480, 640, 3), dtype=np.uint8))

    def test_cameras_are_judged_separately(self):
        wake = MotionWake()
        wake.should_look("cam-a", EMPTY, START)
        wake.should_look("cam-b", EMPTY, START)
        later = START + timedelta(seconds=WAKE_HOLD_SECONDS + 1)

        assert wake.should_look("cam-a", SOMEONE, later)
        assert not wake.should_look("cam-b", EMPTY, later)


# -- the worker ---------------------------------------------------------------

class TestRecognitionWakesOnMotion:
    def test_an_empty_still_hall_does_not_run_the_face_models(self):
        pipeline = CountingPipeline()
        w = worker(pipeline)

        for i in range(40):  # 20 s at 2 checks a second
            w.analyse(frame(EMPTY, i * 0.5, sequence=i))

        # Looked while the hold from the first frame lasted, then once more
        # when the heartbeat came round, and otherwise not at all.
        assert pipeline.calls == int(WAKE_HOLD_SECONDS / 0.5) + 1
        assert w.frames_still == 40 - pipeline.calls
        assert w.analyse(frame(EMPTY, 30.0)).faces == ()

    def test_somebody_arriving_is_looked_at_on_the_first_check(self):
        pipeline = CountingPipeline()
        w = worker(pipeline)
        for i in range(30):
            w.analyse(frame(EMPTY, i * 0.5, sequence=i))
        before = pipeline.calls

        w.analyse(frame(SOMEONE, 15.0, sequence=30))

        assert pipeline.calls == before + 1

    def test_a_person_standing_still_is_looked_at_for_as_long_as_their_face_is_there(self):
        """The anchor gate needs several looks over 1.5 s; a still person must get them."""
        pipeline = CountingPipeline(faces=True)
        w = worker(pipeline)

        checks = int(4 * WAKE_HOLD_SECONDS / 0.5)
        for i in range(checks):  # walks in once, then does not move at all
            w.analyse(frame(SOMEONE, i * 0.5, sequence=i))

        assert pipeline.calls == checks
        assert w.frames_still == 0

    def test_a_camera_somebody_is_watching_is_always_looked_at(self):
        pipeline = CountingPipeline()
        w = worker(pipeline)
        for i in range(30):
            w.analyse(frame(EMPTY, i * 0.5, sequence=i))
        before = pipeline.calls

        w.note_interest("cam-door")
        w.analyse(frame(EMPTY, 15.0, sequence=30))

        assert pipeline.calls == before + 1

    def test_a_camera_not_asked_for_it_looks_every_time(self):
        """The default is what this did before: unproven means off."""
        pipeline = CountingPipeline()
        w = worker(pipeline, wake=())

        for i in range(40):
            w.analyse(frame(EMPTY, i * 0.5, sequence=i))

        assert pipeline.calls == 40
        assert w.frames_still == 0


# -- the setting -------------------------------------------------------------

def parse(**extra):
    return CameraConfig.parse(
        {"id": "cam-door", "name": "Door", "source": "webcam:0",
         "features": ["attendance"], **extra},
        "camera 'cam-door'",
    )


class TestTheSetting:
    def test_the_default_is_always(self):
        assert parse().face_wake == "always"

    def test_motion_is_accepted(self):
        assert parse(face_wake="Motion").face_wake == "motion"

    def test_an_unknown_value_stops_startup(self):
        with pytest.raises(ConfigError, match="face_wake"):
            parse(face_wake="sometimes")

    def test_it_survives_the_camera_store(self, tmp_path):
        from vg.ingest.store import CameraStore

        store = CameraStore(tmp_path / "roster.db")
        try:
            store.add(camera_id="cam-door", name="Door", source="webcam:0",
                      features=("attendance",), face_wake="motion")
            assert store.all()[0].face_wake == "motion"

            store.add(camera_id="cam-hall", name="Hall", source="webcam:0")
            hall = next(c for c in store.all() if c.id == "cam-hall")
            assert hall.face_wake == "always"
        finally:
            store.close()

    def test_a_roster_from_before_the_setting_still_opens(self, tmp_path):
        """A deployed roster.db has no face_wake column until it is migrated."""
        import sqlite3

        from vg.ingest.store import CameraStore

        path = tmp_path / "roster.db"
        store = CameraStore(path)
        store.add(camera_id="cam-door", name="Door", source="webcam:0")
        store.close()
        conn = sqlite3.connect(path)
        conn.execute("ALTER TABLE camera DROP COLUMN face_wake")
        conn.commit()
        conn.close()

        store = CameraStore(path)
        try:
            assert store.all()[0].face_wake == "always"
        finally:
            store.close()
