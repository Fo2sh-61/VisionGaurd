"""Everyone means everyone, and a grade is something extra on top.

The bug this file exists to stop. `Everyone` used to be the bucket for people
with **no** group set — so it held the leftovers, shrank as people were sorted
into grades, and vanished entirely once everybody had one. The word on the
screen said "the whole school" and the list underneath was whoever nobody had
got round to filing.

It was worse than a label, because the same word already meant the opposite
elsewhere: `attendance("group", "")` builds a register of the whole school and
labels it "Everyone". So the Attendance dropdown offered "Everyone", sent it as
a filter, and got back the ungrouped leftovers under a heading claiming to be
the school. Two meanings, one word, and the wrong one was the clickable one.

The rule now: **every enrolled person is in Everyone.** A specific group is
optional and additional — being in Grade 8 does not take you out of Everyone.
Group counts therefore overlap on purpose and do not sum to the roll.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg import config as vgconfig
from vg.api.live import LiveStore
from vg.events.sightings import Sighting, SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry

CAIRO = 180
MODEL = "sface-2021dec"


def local(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc) - timedelta(
        minutes=CAIRO
    )


def unit(seed: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.standard_normal(128).astype("float32")
    return v / float(np.linalg.norm(v))


def build(roll):
    """A LiveStore over a throwaway gallery holding `(id, name, group)` rows.

    Everybody gets a face, because nobody without one can be enrolled — a
    person with no photo cannot be marked present and would read as a
    permanent absence in every register they appear in.
    """
    tmp = tempfile.TemporaryDirectory()
    gallery = FaceGallery(Path(tmp.name) / "g.db", model=MODEL, threshold=0.363)
    sightings = SightingStore(Path(tmp.name) / "s.db", clock=CAIRO)

    for pid, name, group in roll:
        gallery.add_person(pid, name, group=group)
        gallery.add_embedding(pid, unit(pid), MODEL)

    store = LiveStore(
        config=vgconfig.load(), registry=CameraRegistry([]),
        gallery=gallery, sightings=sightings,
    )
    return store, tmp, gallery, sightings


@pytest.fixture
def store():
    """Two in Grade 8, one in Grade 9, one with no group at all."""
    store, tmp, gallery, sightings = build([
        ("p-layla", "Layla Ahmed", "Grade 8"),
        ("p-omar", "Omar Khaled", "Grade 8"),
        ("p-youssef", "Youssef Ali", "Grade 9"),
        ("p-nadia", "Nadia Fouad", None),
    ])
    yield store
    sightings.close()
    gallery.close()
    tmp.cleanup()


def named(store) -> list[str]:
    return [g.name for g in store.groups()]


def sized(store) -> dict[str, int]:
    return {g.name: g.people for g in store.groups()}


class TestEveryoneHoldsEveryone:
    def test_everyone_holds_every_enrolled_person(self, store):
        """Four enrolled, four in Everyone — including the three with a grade."""
        assert sized(store)["Everyone"] == 4

    def test_a_person_in_a_grade_is_still_in_everyone(self, store):
        """A specific group is additional, never instead of.

        This is the whole correction: being filed into Grade 8 must not take
        somebody out of the school.
        """
        everyone = store.group("Everyone")
        assert everyone is not None

        listed = {r.person.name for r in everyone.roster} if everyone.roster else set()
        # With nothing recording attendance there is no roster to read, so the
        # count is the claim that has to hold either way.
        assert everyone.summary.people == 4
        if listed:
            assert "Layla Ahmed" in listed

    def test_everyone_survives_when_all_have_a_group(self):
        """The old bucket disappeared here. Everyone must not.

        This is the exact case that made the bug invisible in testing and
        obvious in use: file the last person into a grade and the row claiming
        to be the whole school silently left the page.
        """
        store, tmp, gallery, sightings = build([
            ("p-layla", "Layla Ahmed", "Grade 8"),
            ("p-omar", "Omar Khaled", "Grade 9"),
        ])
        try:
            assert sized(store)["Everyone"] == 2
        finally:
            sightings.close()
            gallery.close()
            tmp.cleanup()

    def test_someone_with_no_group_appears_only_in_everyone(self, store):
        """No leftovers bucket. An optional field left blank is not a group."""
        assert named(store) == ["Everyone", "Grade 8", "Grade 9"]

    def test_everyone_is_first(self, store):
        """It is the whole school, so it reads as the parent of the rest."""
        assert named(store)[0] == "Everyone"

    def test_specific_groups_are_alphabetical_after_everyone(self):
        store, tmp, gallery, sightings = build([
            ("p-a", "A", "Grade 9"),
            ("p-b", "B", "All staff"),
            ("p-c", "C", "Bus riders"),
        ])
        try:
            assert named(store) == ["Everyone", "All staff", "Bus riders", "Grade 9"]
        finally:
            sightings.close()
            gallery.close()
            tmp.cleanup()

    def test_counts_overlap_on_purpose(self, store):
        """Group sizes no longer sum to the roll, and must not be read as if
        they did. Everyone contains the members of every other group."""
        counts = sized(store)
        assert counts["Everyone"] == 4
        assert counts["Grade 8"] == 2
        assert counts["Grade 9"] == 1
        assert sum(v for k, v in counts.items() if k != "Everyone") < counts["Everyone"]

    def test_an_empty_directory_has_no_groups_at_all(self):
        """Not an Everyone of nobody. Nothing is enrolled, so there is nothing
        to group, and a row reading "Everyone · 0 people" invites the question
        of whose school this is."""
        store, tmp, gallery, sightings = build([])
        try:
            assert store.groups() == []
        finally:
            sightings.close()
            gallery.close()
            tmp.cleanup()

    def test_a_group_literally_named_everyone_does_not_split_the_row(self):
        """Somebody types "Everyone" into the optional group box.

        They are in Everyone regardless, so it folds in rather than producing
        two rows with the same name and different counts.
        """
        store, tmp, gallery, sightings = build([
            ("p-a", "A", "Everyone"),
            ("p-b", "B", "Grade 8"),
        ])
        try:
            assert named(store) == ["Everyone", "Grade 8"]
            assert sized(store)["Everyone"] == 2
        finally:
            sightings.close()
            gallery.close()
            tmp.cleanup()


class TestTheEveryoneRegister:
    """Picking Everyone in the Attendance dropdown must mean the school."""

    def test_everyone_is_the_whole_school_not_the_ungrouped(self, store):
        store.sightings.record(
            Sighting("p-layla", "cam-entrance", local(7, 40), 0.8, MODEL), force=True,
        )

        register = store._register("2026-08-17", group="Everyone")

        assert {e.person_id for e in register.entries} == {
            "p-layla", "p-omar", "p-youssef", "p-nadia",
        }

    def test_everyone_and_a_blank_subject_agree(self, store):
        """They were different answers under the same heading. Now they are
        the same answer, because they are the same question."""
        everyone = store._register("2026-08-17", group="Everyone")
        whole = store._register("2026-08-17", group=None)

        assert {e.person_id for e in everyone.entries} == {
            e.person_id for e in whole.entries
        }

    def test_a_specific_group_is_still_only_that_group(self, store):
        """The other half of the rule. A page headed Grade 8 that listed the
        school would be read as a Grade 8 register."""
        register = store._register("2026-08-17", group="Grade 8")

        assert {e.person_id for e in register.entries} == {"p-layla", "p-omar"}

    def test_a_group_nobody_is_in_is_empty_not_everybody(self, store):
        """Matching nobody is the honest answer for an empty group."""
        register = store._register("2026-08-17", group="Grade 11")

        assert register.entries == []
