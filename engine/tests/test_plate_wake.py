"""Plate reading that wakes on motion (`plate_wake: motion`).

The plate pair is the heaviest thing VisionGuard runs, and a gate is empty most
of the day. These tests pin both halves: an empty, still gate is not read, and
no car is lost because of it - including one that stops at the barrier, and
one whose pass has to be finished after it drives off.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vg.config import CameraConfig, ConfigError
from vg.features.vehicles import LOST_FRAMES, VehiclesWorker
from vg.features.wake import WAKE_HEARTBEAT_SECONDS, WAKE_HOLD_SECONDS
from vg.infer.plates import PlateBox, PlateRead
from vg.ingest.source import Frame

PLATE = "بجد 1234"
START = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
STEP = 0.25  # the vehicle worker's idle rate is 4 reads a second

EMPTY = np.full((120, 160, 3), 90, dtype=np.uint8)
CAR = EMPTY.copy()
CAR[40:110, 20:140] = 200  # a car where the empty gate was


class CountingReader:
    """Reads the plate whenever the car is in the picture, and counts reads."""

    form = version = "test"
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def read_frame(self, image):
        self.calls += 1
        if image[60, 80, 0] != 200:
            return []
        box = PlateBox(x1=50, y1=90, x2=170, y2=130, confidence=0.9)
        return [PlateRead(box=box, text=PLATE, confidence=0.95)]


def frame(image, seconds, sequence=0):
    return Frame(camera_id="gate1", image=image,
                 captured_at=START + timedelta(seconds=seconds), sequence=sequence)


def worker(reader, wake=("gate1",), finals=None):
    finals = finals if finals is not None else []

    def on_pass(camera_id, record):
        return record.amends or "pass-1"

    def on_final(camera_id, row_id):
        finals.append(row_id)

    return VehiclesWorker(bus=None, reader=reader, cameras=["gate1"],
                          on_pass=on_pass, on_final=on_final, wake=wake)


def feed(w, images, start=0):
    for i, image in enumerate(images):
        w.analyse(frame(image, (start + i) * STEP, sequence=start + i))


class TestPlateReadingWakesOnMotion:
    def test_an_empty_still_gate_is_not_read(self):
        reader = CountingReader()
        w = worker(reader)

        checks = int(30 / STEP)  # thirty seconds of nothing
        feed(w, [EMPTY] * checks)

        hold = int(WAKE_HOLD_SECONDS / STEP)
        heartbeats = int((30 - WAKE_HOLD_SECONDS) // WAKE_HEARTBEAT_SECONDS)
        assert reader.calls <= hold + heartbeats + 1
        assert w.frames_still == checks - reader.calls

    def test_a_car_arriving_is_read_on_the_first_check(self):
        reader = CountingReader()
        w = worker(reader)
        feed(w, [EMPTY] * int(20 / STEP))
        before = reader.calls

        result = w.analyse(frame(CAR, 20.0, sequence=999))

        assert reader.calls == before + 1
        assert [r.text for r in result.reads] == [PLATE]

    def test_a_car_waiting_at_the_barrier_is_read_the_whole_time(self):
        reader = CountingReader()
        w = worker(reader)

        checks = int(4 * WAKE_HOLD_SECONDS / STEP)  # drives up, then stands still
        feed(w, [CAR] * checks)

        assert reader.calls == checks
        assert w.frames_still == 0

    def test_a_car_that_drives_off_still_gets_its_pass_finished(self):
        """The track ends only on frames that were read; sleep must not strand it."""
        reader = CountingReader()
        finals: list = []
        w = worker(reader, finals=finals)

        feed(w, [CAR] * 8)
        feed(w, [EMPTY] * (LOST_FRAMES + 40), start=8)

        assert finals == ["pass-1"]
        assert not w._tracks.get("gate1")

    def test_a_car_the_reader_loses_while_it_stands_still_is_still_finished(self):
        """An open track keeps the gate awake even after the hold runs out.

        At one read a second the track needs LOST_FRAMES + 1 seconds of misses
        to finish - longer than the hold. Without the open-track rule the gate
        would fall asleep with the car's pass still open.
        """
        reader = CountingReader()
        finals: list = []
        w = VehiclesWorker(bus=None, reader=reader, cameras=["gate1"],
                           on_pass=lambda c, r: r.amends or "pass-1",
                           on_final=lambda c, row: finals.append(row),
                           wake=("gate1",))
        for second in range(3):  # three reads that agree make the pass
            w.analyse(frame(CAR, float(second), sequence=second))
        reader.read_frame = lambda image: []  # plate hidden, car still there

        for second in range(3, 3 + LOST_FRAMES + 1):
            w.analyse(frame(CAR, float(second), sequence=second))

        assert LOST_FRAMES + 1 > WAKE_HOLD_SECONDS
        assert finals == ["pass-1"]
        assert w.frames_still == 0

    def test_a_plate_too_small_to_read_keeps_the_gate_awake(self):
        """No track opens for an unreadable plate; the read itself must keep it awake."""
        reader = CountingReader()
        small = PlateRead(box=PlateBox(x1=60, y1=90, x2=90, y2=100, confidence=0.9),
                          text="", confidence=0.0)
        assert not small.readable
        reader.read_frame = lambda image: (setattr(reader, "calls", reader.calls + 1)
                                           or [small])
        w = worker(reader)

        checks = int(3 * WAKE_HOLD_SECONDS / STEP)  # a car parked too far away
        feed(w, [CAR] * checks)

        assert reader.calls == checks
        assert w.frames_still == 0

    def test_a_gate_somebody_is_watching_is_always_read(self):
        reader = CountingReader()
        w = worker(reader)
        feed(w, [EMPTY] * int(20 / STEP))
        before = reader.calls

        w.note_interest("gate1")
        w.analyse(frame(EMPTY, 20.0, sequence=999))

        assert reader.calls == before + 1

    def test_a_gate_not_asked_for_it_reads_every_time(self):
        """The default is what this did before: unproven means off."""
        reader = CountingReader()
        w = worker(reader, wake=())

        feed(w, [EMPTY] * 80)

        assert reader.calls == 80
        assert w.frames_still == 0


def parse(**extra):
    return CameraConfig.parse(
        {"id": "gate1", "name": "Gate", "source": "webcam:0",
         "features": ["vehicles"], "gate": 1, "direction": "entry", **extra},
        "camera 'gate1'",
    )


class TestTheSetting:
    def test_the_default_is_always(self):
        assert parse().plate_wake == "always"

    def test_motion_is_accepted(self):
        assert parse(plate_wake="MOTION").plate_wake == "motion"

    def test_an_unknown_value_stops_startup(self):
        with pytest.raises(ConfigError, match="plate_wake"):
            parse(plate_wake="never")

    def test_it_survives_the_camera_store(self, tmp_path):
        from vg.ingest.store import CameraStore

        store = CameraStore(tmp_path / "roster.db")
        try:
            store.add(camera_id="gate1", name="Gate", source="webcam:0",
                      features=("vehicles",), gate=1, direction="entry",
                      plate_wake="motion")
            stored = store.all()[0]
            assert stored.plate_wake == "motion"
            assert stored.face_wake == "always"
        finally:
            store.close()

    def test_a_roster_from_before_the_setting_still_opens(self, tmp_path):
        import sqlite3

        from vg.ingest.store import CameraStore

        path = tmp_path / "roster.db"
        store = CameraStore(path)
        store.add(camera_id="gate1", name="Gate", source="webcam:0")
        store.close()
        conn = sqlite3.connect(path)
        conn.execute("ALTER TABLE camera DROP COLUMN plate_wake")
        conn.commit()
        conn.close()

        store = CameraStore(path)
        try:
            assert store.all()[0].plate_wake == "always"
        finally:
            store.close()
