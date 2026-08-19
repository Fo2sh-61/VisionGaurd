"""A person's history page, and a group's register.

These were the last two screens serving fixtures. Both are about a named
child, which is what makes an invented number here worse than an invented
number on a dashboard: somebody rings a parent about it.

Three things could quietly lie and each has a test below.

**The denominator.** "27 of 30 days present" is a sentence about a child, and
the 30 decides whether it reads as good or bad. A calendar month counts
weekends, holidays and every hour the engine was switched off, so a child with
perfect attendance comes out at 27/30. Only days the system actually recorded
somebody can honestly be counted.

**The group filter.** The register was built from every enrolled person and
then shown under a group's name, so "Grade 8 - 380 of 400 arrived" was the
whole school wearing Grade 8's heading.

**Late.** `SightingStore.history` returned "on_time" for every day and left a
comment saying the caller would fix it. No caller did.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg import config as vgconfig
from vg.api import schemas as S
from vg.api.live import LiveStore
from vg.events.sightings import Sighting, SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry

CAIRO = 180  # UTC+3, in minutes
MODEL = "sface-2021dec"


def local(hour: int, minute: int = 0, day: int = 17) -> datetime:
    """A UTC instant that is `hour:minute` in Cairo on 2026-08-`day`."""
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc) - timedelta(
        minutes=CAIRO
    )


def seen(person: str, at: datetime, camera: str = "cam-entrance") -> Sighting:
    return Sighting(person, camera, at, confidence=0.8, model=MODEL)


def unit(seed: str):
    """Any vector will do; nothing here matches faces, it only enrols them."""
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.standard_normal(128).astype("float32")
    return v / float(np.linalg.norm(v))


@pytest.fixture
def store():
    """A LiveStore with a real gallery and a real sighting database.

    Three students in two groups. All three have a face on file, so all three
    are expected in the register - `photo_on_file` is what makes someone
    recognisable, and only recognisable people can be marked absent.
    """
    with tempfile.TemporaryDirectory() as tmp:
        gallery = FaceGallery(Path(tmp) / "g.db", model=MODEL, threshold=0.363)
        sightings = SightingStore(Path(tmp) / "s.db", clock=CAIRO)

        for pid, name, group in [
            ("p-layla", "Layla Ahmed", "Grade 8"),
            ("p-omar", "Omar Khaled", "Grade 8"),
            ("p-youssef", "Youssef Ali", "Grade 9"),
        ]:
            gallery.add_person(pid, name, group=group)
            gallery.add_embedding(pid, unit(pid), MODEL)

        live = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([]),
            gallery=gallery, sightings=sightings,
        )
        yield live
        sightings.close()
        gallery.close()


# -- the denominator -------------------------------------------------------


class TestDaysCounted:
    def test_a_day_nobody_was_recorded_is_not_an_absence(self, store):
        """The engine being off is not the child being away.

        Two days recorded, Layla seen on both. If the window were the calendar
        she would show 2 of 30 and read as a truant.
        """
        store.sightings.record(seen("p-layla", local(7, 40, day=17)), force=True)
        store.sightings.record(seen("p-layla", local(7, 45, day=18)), force=True)

        history = store.history("Layla Ahmed")
        assert history.total_days == 2
        assert history.present_days == 2

    def test_a_day_someone_else_was_recorded_counts_against_her(self, store):
        """The system was up and looking, and she was not there. That is real.

        This is the other half of the rule above: only counting days *she* was
        seen would make every history 100% and the page pointless.
        """
        store.sightings.record(seen("p-layla", local(7, 40, day=17)), force=True)
        store.sightings.record(seen("p-omar", local(7, 41, day=18)), force=True)

        history = store.history("Layla Ahmed")
        assert history.total_days == 2
        assert history.present_days == 1
        assert [f.kind for f in history.flags] == ["absence"]

    def test_attendance_is_not_a_percentage_of_nothing(self, store):
        """0% would be acted on. "No days recorded" is the truth."""
        history = store.history("Layla Ahmed")
        assert history.total_days == 0
        assert [m.key for m in history.metrics] == ["present", "late"]
        assert history.period_label == "No days recorded"


# -- late ------------------------------------------------------------------


class TestLate:
    def test_an_arrival_after_the_cutoff_is_late_not_on_time(self, store):
        # 08:27 Cairo, against the 08:00 cutoff in engine.yaml.
        store.sightings.record(seen("p-layla", local(8, 27, day=17)), force=True)

        history = store.history("Layla Ahmed")
        late = next(m for m in history.metrics if m.key == "late")
        assert late.value == 1
        assert history.trend[0].status == S.AttendanceStatus.LATE
        assert "27 minutes" in history.flags[0].detail

    def test_a_late_day_still_counts_as_present(self, store):
        store.sightings.record(seen("p-layla", local(8, 27, day=17)), force=True)
        assert store.history("Layla Ahmed").present_days == 1

    def test_the_register_and_the_history_agree_about_the_same_morning(self, store):
        """Two code paths, one morning. They must not disagree.

        They used to: the register applied the cutoff and the history
        hardcoded "on_time", so the same arrival was late on one screen and
        fine on another.
        """
        store.sightings.record(seen("p-layla", local(8, 27, day=17)), force=True)

        register = store._register("2026-08-17")
        history = store.sightings.history(
            "p-layla", cutoff=time(8, 0),
            day_start=store.config.hours.start, day_end=store.config.hours.end,
        )
        assert register.entry("p-layla").status == "late"
        assert history["2026-08-17"].status == "late"

    def test_person_mode_attendance_applies_the_cutoff(self, store):
        """P0-04. Every past day was reported on time, `late` was always 0.

        The day register applied the cutoff and this branch did not, so the
        same morning was late on one screen and fine on another.
        """
        store.sightings.record(seen("p-layla", local(8, 27, day=17)), force=True)
        store.sightings.record(seen("p-layla", local(7, 50, day=18)), force=True)

        result = store.attendance("person", "Layla Ahmed", "2026-08-18")
        assert result.late == 1
        assert {d.date: d.status.value for d in result.days} == {
            "2026-08-17": "late", "2026-08-18": "on_time"}

    def test_the_two_screens_agree_about_the_same_morning(self, store):
        """The history page and the attendance page, one child, one day."""
        store.sightings.record(seen("p-layla", local(8, 27, day=17)), force=True)

        page = store.history("Layla Ahmed")
        register = store.attendance("person", "Layla Ahmed", "2026-08-17")
        assert page.trend[0].status == register.days[0].status
        assert register.days[0].minutes_late == 27

    def test_a_person_day_says_where_they_were_first_seen(self, store):
        """`location` was hardcoded None even though the camera was known."""
        store.sightings.record(seen("p-layla", local(7, 50, day=17)), force=True)

        result = store.attendance("person", "Layla Ahmed", "2026-08-17")
        assert result.days[0].location is not None

    def test_a_sighting_outside_school_hours_is_not_an_arrival(self, store):
        """01:14 is before the 08:00 cutoff, and is not arriving for school.

        Bounded the same way the register is, or the night caretaker's rounds
        would mark half the school present at 1am.
        """
        store.sightings.record(seen("p-layla", local(1, 14, day=17)), force=True)
        store.sightings.record(seen("p-omar", local(7, 50, day=17)), force=True)

        history = store.history("Layla Ahmed")
        assert history.total_days == 1
        assert history.present_days == 0


# -- the group filter ------------------------------------------------------


class TestGroup:
    def test_a_group_shows_that_group_and_not_the_school(self, store):
        detail = store.group("Grade 8")
        assert sorted(r.person.name for r in detail.roster) == [
            "Layla Ahmed", "Omar Khaled"]

    def test_the_header_and_the_list_are_the_same_group(self, store):
        """A count of 3 above a list of 2 is the bug this catches."""
        detail = store.group("Grade 8")
        assert detail.summary.people == len(detail.roster) == 2

    def test_asking_for_a_group_register_narrows_it(self, store):
        result = store.attendance("group", "Grade 9", "2026-08-17")
        assert result.expected == 1
        assert [r.person.name for r in result.records] == ["Youssef Ali"]

    def test_a_group_that_does_not_exist_is_not_the_whole_school(self, store):
        assert store.group("Grade 11") is None


# -- honest emptiness ------------------------------------------------------


class TestWhenNothingIsRunning:
    def test_history_without_recognition_names_her_and_explains(self, store):
        """She is enrolled. Nothing was watching. Both are true at once.

        "No such person" would deny the first, and inventing 27 of 30 days
        would deny the second.
        """
        store.sightings = None  # the model failed to load

        history = store.history("Layla Ahmed")
        assert history.person.name == "Layla Ahmed"
        assert history.present_days == 0 and history.total_days == 0
        assert history.trend == [] and history.flags == []
        assert "not running" in history.metrics[0].text

    def test_a_group_without_recognition_keeps_its_roll_and_drops_the_register(
        self, store
    ):
        """How many are in Grade 8 is enrolment, not recognition.

        The roll is still known and still true. Who turned up is not, so the
        roster is empty rather than a list of children marked absent by a
        system that was not looking.
        """
        store.sightings = None

        detail = store.group("Grade 8")
        assert detail.summary.people == 2
        assert detail.roster == []

    def test_history_of_someone_not_enrolled_is_not_found(self, store):
        assert store.history("Somebody Else") is None

    def test_history_without_a_gallery_is_not_found(self, bare_live_store):
        """No gallery means no way to know the name is a person at all."""
        assert bare_live_store.history("Layla Ahmed") is None
        assert bare_live_store.group("Grade 8") is None
