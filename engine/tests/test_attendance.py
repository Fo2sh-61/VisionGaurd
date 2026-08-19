"""Sighting store and the attendance register.

The register is what a head teacher acts on, so the tests are about the ways it
could quietly lie: marking someone present who was not there, marking someone
absent the system never actually looked for, or counting a 1am corridor walk as
arriving for school.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from vg.events.sightings import Sighting, SightingStore

CAIRO = 180  # UTC+3, in minutes


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = SightingStore(Path(tmp) / "s.db", clock=CAIRO)
        yield s
        s.close()


def local(hour: int, minute: int = 0, day: int = 7) -> datetime:
    """A UTC instant that is `hour:minute` in Cairo on 2026-08-`day`."""
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc) - timedelta(
        minutes=CAIRO
    )


def seen(person: str, at: datetime, camera: str = "cam-entrance") -> Sighting:
    return Sighting(person, camera, at, confidence=0.8, model="sface-2021dec")


class TestLocalDate:
    def test_uses_the_site_timezone_not_utc(self, store):
        # 00:30 in Cairo is still the previous day in UTC. Filing an arrival
        # under the wrong date silently corrupts the register.
        just_after_midnight = local(0, 30, day=7)
        assert just_after_midnight.date().isoformat() == "2026-08-06"
        assert store.local_date(just_after_midnight) == "2026-08-07"


class TestDebounce:
    def test_first_sighting_is_always_written(self, store):
        assert store.record(seen("p1", local(7, 42)), force=True) is True

    def test_a_repeat_moments_later_is_dropped(self, store):
        # Standing at an entrance at 5 fps is fifty recognitions of one arrival.
        store.record(seen("p1", local(7, 42)), force=True)
        assert store.record(seen("p1", local(7, 42, day=7))) is False

    def test_a_repeat_much_later_is_kept(self, store):
        store.record(seen("p1", local(7, 42)), force=True)
        later = local(7, 42) + timedelta(seconds=SightingStore.DEBOUNCE_SECONDS + 5)
        assert store.record(seen("p1", later)) is True

    def test_different_cameras_debounce_independently(self, store):
        store.record(seen("p1", local(7, 42), camera="a"), force=True)
        # Moving between cameras is real movement, not a duplicate.
        assert store.record(seen("p1", local(7, 42), camera="b")) is True


class TestRegister:
    def test_arrival_before_cutoff_is_on_time(self, store):
        store.record(seen("p1", local(7, 42)), force=True)
        register = store.register("2026-08-07", ["p1"], cutoff=time(8, 0))

        entry = register.entry("p1")
        assert entry.status == "on_time"
        assert register.present == 1 and register.absent == 0

    def test_arrival_after_cutoff_is_late_with_the_minutes(self, store):
        store.record(seen("p1", local(8, 27)), force=True)
        register = store.register("2026-08-07", ["p1"], cutoff=time(8, 0))

        entry = register.entry("p1")
        assert entry.status == "late"
        assert entry.minutes_late == 27

    def test_nobody_seen_is_absent(self, store):
        register = store.register("2026-08-07", ["p1", "p2"], cutoff=time(8, 0))
        assert register.absent == 2
        assert all(e.first_seen is None for e in register.entries)

    def test_absence_is_derived_not_stored(self, store):
        # Absence is the absence of evidence. Recording a sighting later must
        # change the register with no "absent" row to undo.
        assert store.register("2026-08-07", ["p1"], cutoff=time(8, 0)).absent == 1
        store.record(seen("p1", local(7, 30)), force=True)
        assert store.register("2026-08-07", ["p1"], cutoff=time(8, 0)).absent == 0

    def test_only_expected_people_appear(self, store):
        # Someone with no photo on file cannot be recognised, so they must not
        # be reported absent as though the system had looked for them.
        store.record(seen("p1", local(7, 30)), force=True)
        register = store.register("2026-08-07", ["p1"], cutoff=time(8, 0))
        assert [e.person_id for e in register.entries] == ["p1"]

    def test_first_camera_is_recorded(self, store):
        store.record(seen("p1", local(7, 30), camera="gate"), force=True)
        store.record(seen("p1", local(9, 0), camera="library"))
        assert store.register("2026-08-07", ["p1"], cutoff=time(8, 0)).entry(
            "p1"
        ).camera_id == "gate"

    def test_a_different_day_is_a_different_register(self, store):
        store.record(seen("p1", local(7, 30, day=6)), force=True)
        assert store.register("2026-08-07", ["p1"], cutoff=time(8, 0)).absent == 1
        assert store.register("2026-08-06", ["p1"], cutoff=time(8, 0)).present == 1


class TestSchoolHours:
    """The bug that marked a 01:14 sighting as an on-time arrival."""

    def test_a_sighting_before_school_is_not_an_arrival(self, store):
        store.record(seen("p1", local(1, 14)), force=True)
        register = store.register(
            "2026-08-07", ["p1"], cutoff=time(8, 0),
            day_start=time(7, 30), day_end=time(15, 0),
        )
        # 01:14 precedes the 08:00 cutoff, so without the school-hours window
        # this read as "on time". A night caretaker would be marked present.
        assert register.entry("p1").status == "absent"

    def test_a_sighting_after_school_is_not_an_arrival(self, store):
        store.record(seen("p1", local(19, 30)), force=True)
        register = store.register(
            "2026-08-07", ["p1"], cutoff=time(8, 0),
            day_start=time(7, 30), day_end=time(15, 0),
        )
        assert register.entry("p1").status == "absent"

    def test_a_sighting_inside_school_hours_still_counts(self, store):
        store.record(seen("p1", local(7, 42)), force=True)
        register = store.register(
            "2026-08-07", ["p1"], cutoff=time(8, 0),
            day_start=time(7, 30), day_end=time(15, 0),
        )
        assert register.entry("p1").status == "on_time"

    def test_out_of_hours_sightings_are_still_stored(self, store):
        # They are real and they matter for tracking a person. They just are
        # not arrivals, so the data must survive even though the register
        # ignores it.
        store.record(seen("p1", local(1, 14)), force=True)
        assert len(store.sightings_on("2026-08-07")) == 1

    def test_the_first_in_hours_sighting_sets_the_arrival(self, store):
        store.record(seen("p1", local(2, 0)), force=True)  # night, ignored
        store.record(seen("p1", local(8, 15)), force=True)  # the real arrival
        register = store.register(
            "2026-08-07", ["p1"], cutoff=time(8, 0),
            day_start=time(7, 30), day_end=time(15, 0),
        )
        entry = register.entry("p1")
        assert entry.status == "late" and entry.minutes_late == 15


class TestHistory:
    def test_groups_by_day(self, store):
        for day in (5, 6, 7):
            store.record(seen("p1", local(7, 40, day=day)), force=True)
        history = store.history("p1", days=30)
        assert set(history) == {"2026-08-05", "2026-08-06", "2026-08-07"}

    def test_counts_sightings_per_day(self, store):
        store.record(seen("p1", local(7, 40)), force=True)
        store.record(seen("p1", local(9, 40)), force=True)
        assert store.history("p1")["2026-08-07"].sightings == 2


class TestSeenToday:
    def test_false_before_any_sighting(self, store):
        assert store.seen_today("p1", local(9, 0)) is False

    def test_true_after_one(self, store):
        store.record(seen("p1", local(7, 42)), force=True)
        assert store.seen_today("p1", local(9, 0)) is True
