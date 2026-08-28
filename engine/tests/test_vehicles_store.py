"""The vehicle register and the pass log.

Four rules carry this file, and each one describes a way a gate log can
quietly stop being true:

**One car is one row.** `plate` is canonical and `UNIQUE`. A plate typed on an
English keyboard, imported from a spreadsheet in Arabic digits, and read off a
camera must collide — or a school ends up with three records per car and finds
out at the barrier.

**Removing a car keeps its passes.** `ON DELETE SET NULL`, never `CASCADE`.
The history is what a removal exists to preserve.

**A pass never changes after it is written.** Blacklisting a car today must
not rewrite what happened yesterday.

**Visits are derived.** No table, no `open` flag, no orphan sweep — so the
answer cannot drift from the passes it is computed from.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.events.vehicles import (  # noqa: E402
    CATEGORIES,
    PlateTaken,
    VehicleStore,
    read_csv,
    status_for,
    template_csv,
)

TODAY = date(2026, 8, 24)
NOON = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

PLATE_ARABIC = "ب ج د ١٢٣٤"
PLATE_ASCII = "ب ج د 1234"
CANONICAL = "بجد 1234"
OTHER = "سصط 9876"


@pytest.fixture
def store():
    """A real store on a throwaway database.

    Closed before the tempdir, or Windows fails the teardown with the file
    still open.
    """
    with tempfile.TemporaryDirectory() as tmp:
        vehicles = VehicleStore(Path(tmp) / "vehicles.db")
        try:
            yield vehicles
        finally:
            vehicles.close_db()


def a_pass(store, plate=PLATE_ARABIC, at=NOON, direction="entry", gate=1,
           camera="gate1_entry", confidence=0.9, votes=3, review=False):
    return store.record_pass(
        at=at, camera_id=camera, gate=gate, direction=direction, plate=plate,
        confidence=confidence, votes=votes, needs_review=review, today=TODAY)


# ---------------------------------------------------------------------------
# one car, one row
# ---------------------------------------------------------------------------

class TestOneCarIsOneRow:
    @pytest.mark.parametrize("typed", [PLATE_ARABIC, PLATE_ASCII, "بجد١٢٣٤"])
    def test_however_it_is_typed_it_finds_the_same_car(self, store, typed):
        store.add(PLATE_ARABIC, owner_name="Tarek")

        assert store.by_plate(typed).owner_name == "Tarek"

    def test_a_duplicate_is_refused_with_a_message_a_person_can_read(self, store):
        store.add(PLATE_ARABIC)

        with pytest.raises(PlateTaken, match="already registered"):
            store.add(PLATE_ASCII)

    def test_the_constraint_decides_the_race_not_a_lookup(self, store):
        """Checking first and inserting second still races two simultaneous
        imports of the same list. `UNIQUE` cannot be interleaved."""
        store.add(PLATE_ARABIC)

        with pytest.raises(PlateTaken):
            store.add(CANONICAL)

        assert store.count() == 1

    def test_a_plate_with_nothing_in_it_is_refused(self, store):
        with pytest.raises(ValueError, match="needs a plate"):
            store.add("!!!")


class TestCategories:
    @pytest.mark.parametrize("category", CATEGORIES)
    def test_the_four_categories_are_accepted(self, store, category):
        assert store.add(f"بجد {hash(category) % 9000 + 1000}",
                         category=category).category == category

    def test_resident_is_gone(self, store):
        """The gate-anpr project's fifth category. It means nothing at a
        school — a parent is a Visitor, with their child's class in `unit`."""
        assert "resident" not in CATEGORIES

        with pytest.raises(ValueError, match="unknown category"):
            store.add(PLATE_ARABIC, category="resident")

    def test_an_invented_category_never_reaches_the_database(self, store):
        with pytest.raises(ValueError):
            store.add(PLATE_ARABIC, category="honoured guest")

        assert store.count() == 0


# ---------------------------------------------------------------------------
# what a pass reads as
# ---------------------------------------------------------------------------

class TestStatus:
    def test_a_car_nobody_registered_is_not_registered(self, store):
        assert a_pass(store).status == "unknown"

    def test_a_registered_car_is_known(self, store):
        store.add(PLATE_ARABIC, owner_name="Tarek", category="staff")

        record = a_pass(store)

        assert record.status == "known"
        assert record.owner_name == "Tarek"

    def test_a_withdrawn_car_is_blacklisted(self, store):
        store.add(PLATE_ARABIC, category="blacklist")

        assert a_pass(store).status == "blacklist"

    def test_a_lapsed_permit_is_expired(self, store):
        store.add(PLATE_ARABIC, category="visitor", valid_until="2026-08-01")

        assert a_pass(store).status == "expired"

    def test_a_permit_valid_today_is_not_expired(self, store):
        store.add(PLATE_ARABIC, category="visitor", valid_until="2026-08-24")

        assert a_pass(store).status == "known"

    def test_no_expiry_never_expires(self, store):
        store.add(PLATE_ARABIC, category="staff")

        assert a_pass(store).status == "known"

    def test_blacklist_outranks_expiry(self, store):
        """A withdrawn contractor whose permit also lapsed is a security
        event, not a quiet amber row."""
        store.add(PLATE_ARABIC, category="blacklist", valid_until="2020-01-01")

        assert a_pass(store).status == "blacklist"

    def test_an_unreadable_expiry_date_does_not_crash_the_gate(self, store):
        """A spreadsheet full of "31/02/2026" must not take the camera down."""
        store.add(PLATE_ARABIC, category="visitor", valid_until="not a date")

        assert a_pass(store).status == "known"

    def test_status_for_is_pure(self):
        assert status_for(None, TODAY) == "unknown"


# ---------------------------------------------------------------------------
# history is not rewritten
# ---------------------------------------------------------------------------

class TestThePastIsNotEdited:
    def test_blacklisting_a_car_does_not_change_yesterdays_pass(self, store):
        vehicle = store.add(PLATE_ARABIC, category="staff")
        yesterday = a_pass(store, at=NOON - timedelta(days=1))
        assert yesterday.status == "known"

        store.update(vehicle.id, category="blacklist")

        assert store.pass_by_id(yesterday.id).status == "known"

    def test_the_change_applies_from_the_next_pass(self, store):
        vehicle = store.add(PLATE_ARABIC, category="staff")
        a_pass(store, at=NOON - timedelta(hours=2))
        store.update(vehicle.id, category="blacklist")

        assert a_pass(store, at=NOON).status == "blacklist"

    def test_removing_a_vehicle_keeps_every_pass_it_made(self, store):
        """`SET NULL`, never `CASCADE`. The history is what a removal exists
        to preserve — a car whose access is withdrawn is exactly the one whose
        past visits somebody will want to look at."""
        vehicle = store.add(PLATE_ARABIC, owner_name="Tarek")
        a_pass(store)
        a_pass(store, at=NOON + timedelta(minutes=5), direction="exit")

        assert store.remove(vehicle.id) is True

        passes = store.passes()
        assert len(passes) == 2
        assert all(p.vehicle_id is None for p in passes)
        assert all(p.plate == CANONICAL for p in passes), (
            "the plate is denormalised onto the pass so the history stays "
            "searchable after the register entry goes")

    def test_the_car_reads_as_unregistered_from_its_next_pass(self, store):
        vehicle = store.add(PLATE_ARABIC)
        store.remove(vehicle.id)

        assert a_pass(store).status == "unknown"


# ---------------------------------------------------------------------------
# searching
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.fixture
    def filled(self, store):
        store.add(PLATE_ARABIC, owner_name="Tarek Nassar", phone="01012345678",
                  unit="IT", category="staff")
        store.add(OTHER, owner_name="Nadia Salem", unit="Grade 8 parent",
                  category="visitor")
        store.add("مثم 5555", owner_name="Former contractor",
                  category="blacklist")
        return store

    @pytest.mark.parametrize("query", ["Tarek", "IT", "01012345678"])
    def test_it_matches_owner_unit_and_phone(self, filled, query):
        assert [v.owner_name for v in filled.search(query)] == ["Tarek Nassar"]

    def test_it_matches_a_plate_typed_in_either_digit_system(self, filled):
        assert len(filled.search("1234")) == 1
        assert len(filled.search("١٢٣٤")) == 1

    def test_a_category_filter_narrows_it(self, filled):
        assert len(filled.search(category="blacklist")) == 1
        assert len(filled.search(category="staff")) == 1

    def test_all_means_all(self, filled):
        assert len(filled.search(category="all")) == 3

    def test_nothing_matching_is_an_empty_list_not_an_error(self, filled):
        assert filled.search("nobody by that name") == []


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

class TestImport:
    def test_a_plain_list_loads(self, store):
        result = store.import_rows([
            {"plate": PLATE_ARABIC, "owner_name": "Tarek", "category": "staff"},
            {"plate": OTHER, "owner_name": "Nadia", "category": "visitor"},
        ])

        assert result["added"] == 2
        assert result["problems"] == []
        assert store.count() == 2

    def test_arabic_column_headings_work(self, store):
        """A school's list arrives however the previous system exported it."""
        result = store.import_rows([
            {"رقم اللوحة": PLATE_ARABIC, "اسم المالك": "Tarek", "الفئة": "staff"},
        ])

        assert result["added"] == 1
        assert store.by_plate(PLATE_ASCII).owner_name == "Tarek"

    def test_a_duplicate_row_updates_rather_than_failing(self, store):
        store.add(PLATE_ARABIC, owner_name="Old name", category="staff")

        result = store.import_rows([
            {"plate": PLATE_ASCII, "owner_name": "New name", "category": "staff"},
        ])

        assert result["skipped_duplicates"] == 1
        assert store.count() == 1
        assert store.by_plate(CANONICAL).owner_name == "New name"

    def test_every_rejected_row_is_reported_with_its_number_and_reason(self, store):
        """A silent partial import is the worst outcome: the office believes
        the list is loaded and finds out at the gate."""
        result = store.import_rows([
            {"plate": PLATE_ARABIC, "category": "staff"},
            {"plate": "", "owner_name": "No plate"},
            {"plate": OTHER, "category": "resident"},
        ])

        assert result["added"] == 1
        assert len(result["problems"]) == 2
        assert any("row 3" in p for p in result["problems"])
        assert any("no readable plate" in p for p in result["problems"])
        assert any("resident" in p for p in result["problems"])

    def test_a_row_with_no_category_defaults_to_visitor(self, store):
        store.import_rows([{"plate": PLATE_ARABIC}])

        assert store.by_plate(CANONICAL).category == "visitor"

    def test_the_template_round_trips_through_the_reader(self, store):
        """The blank template must itself import, or the first thing a school
        does with it fails."""
        rows = read_csv(template_csv())

        result = store.import_rows(rows)

        assert result["added"] == 1, result["problems"]

    def test_an_empty_file_is_not_an_error(self, store):
        assert store.import_rows([]) == {
            "added": 0, "updated": 0, "skipped_duplicates": 0, "problems": []}


# ---------------------------------------------------------------------------
# derived visits
# ---------------------------------------------------------------------------

class TestVisitsAreDerived:
    def test_an_entry_with_no_exit_is_a_car_still_inside(self, store):
        a_pass(store, direction="entry")

        inside = store.inside()

        assert len(inside) == 1
        assert inside[0].inside is True
        assert inside[0].left_at is None

    def test_an_entry_then_an_exit_is_a_completed_visit(self, store):
        a_pass(store, at=NOON, direction="entry")
        a_pass(store, at=NOON + timedelta(minutes=30), direction="exit", gate=1)

        visits = store.visits()

        assert len(visits) == 1
        assert visits[0].inside is False
        assert visits[0].minutes(NOON) == 30.0
        assert visits[0].inferred is False

    def test_two_entries_in_a_row_close_the_first_as_inferred(self, store):
        """The car left through a gate nobody is watching. That is reported as
        inferred, never presented as an observed exit."""
        a_pass(store, at=NOON, direction="entry")
        a_pass(store, at=NOON + timedelta(hours=3), direction="entry")

        visits = store.visits()
        closed = [v for v in visits if not v.inside]

        assert len(closed) == 1
        assert closed[0].inferred is True
        assert closed[0].exit_gate is None, (
            "an inferred close has no exit gate - there was no exit")

    def test_two_cars_do_not_pair_with_each_other(self, store):
        a_pass(store, plate=PLATE_ARABIC, direction="entry")
        a_pass(store, plate=OTHER, at=NOON + timedelta(minutes=5),
               direction="exit")

        inside = store.inside()

        assert [v.plate for v in inside] == [CANONICAL]

    def test_a_visit_carries_the_owner_when_the_car_is_registered(self, store):
        store.add(PLATE_ARABIC, owner_name="Tarek", unit="IT")
        a_pass(store)

        assert store.inside()[0].owner_name == "Tarek"

    def test_gate_totals_count_both_directions_and_who_is_inside(self, store):
        a_pass(store, at=NOON, direction="entry", gate=1)
        a_pass(store, plate=OTHER, at=NOON, direction="entry", gate=1)
        a_pass(store, at=NOON + timedelta(minutes=10), direction="exit", gate=1)

        totals = store.gates(NOON - timedelta(hours=1))

        assert totals == [{"gate": 1, "entered": 2, "left": 1, "inside": 1}]


# ---------------------------------------------------------------------------
# counts and retention
# ---------------------------------------------------------------------------

class TestCountsAndRetention:
    def test_counts_are_measurements_of_what_was_recorded(self, store):
        store.add(PLATE_ARABIC, category="blacklist")
        a_pass(store)
        a_pass(store, plate=OTHER, at=NOON + timedelta(minutes=1))
        a_pass(store, plate="مثم 5555", at=NOON + timedelta(minutes=2),
               confidence=0.3, review=True)

        counts = store.counts_since(NOON - timedelta(hours=1))

        assert counts["entered"] == 3
        assert counts["blacklist"] == 1
        assert counts["unknown"] == 2
        assert counts["needs_review"] == 1

    def test_an_old_pass_loses_its_images_but_not_its_row(self, store, tmp_path):
        """A pass whose photographs have aged out is still a pass. The time,
        the gate, the plate and the status are the record."""
        snapshot = tmp_path / "old.jpg"
        snapshot.write_bytes(b"jpeg")
        old = store.record_pass(
            at=NOON - timedelta(days=60), camera_id="gate1_entry", gate=1,
            direction="entry", plate=PLATE_ARABIC, confidence=0.9, votes=3,
            needs_review=False, today=TODAY, snapshot=str(snapshot))

        cleared = store.expire(NOON - timedelta(days=30))

        assert cleared == 1
        assert not snapshot.exists()
        kept = store.pass_by_id(old.id)
        assert kept is not None, "the row must outlive its photograph"
        assert kept.snapshot is None
        assert kept.status == "unknown"

    def test_a_recent_pass_keeps_its_images(self, store, tmp_path):
        snapshot = tmp_path / "new.jpg"
        snapshot.write_bytes(b"jpeg")
        store.record_pass(
            at=NOON, camera_id="gate1_entry", gate=1, direction="entry",
            plate=PLATE_ARABIC, confidence=0.9, votes=3, needs_review=False,
            today=TODAY, snapshot=str(snapshot))

        store.expire(NOON - timedelta(days=30))

        assert snapshot.exists()

    def test_has_snapshot_is_false_when_the_file_is_gone(self, store):
        """The path is text in a row and the file may not be there. Any reader
        must check rather than assume."""
        record = store.record_pass(
            at=NOON, camera_id="gate1_entry", gate=1, direction="entry",
            plate=PLATE_ARABIC, confidence=0.9, votes=3, needs_review=False,
            today=TODAY, snapshot="/no/such/file.jpg")

        assert record.has_snapshot is False


class TestFiltering:
    def test_the_log_filters_narrow_correctly(self, store):
        store.add(PLATE_ARABIC, category="blacklist")
        a_pass(store, at=NOON, direction="entry", gate=1)
        a_pass(store, plate=OTHER, at=NOON + timedelta(minutes=1),
               direction="exit", gate=2)

        assert len(store.passes(gate=1)) == 1
        assert len(store.passes(direction="exit")) == 1
        assert len(store.passes(status="blacklist")) == 1
        assert len(store.passes(plate="1234")) == 1

    def test_the_newest_pass_comes_first(self, store):
        a_pass(store, at=NOON)
        a_pass(store, plate=OTHER, at=NOON + timedelta(hours=1))

        assert store.passes()[0].plate == "سصط 9876"


class TestVisitPairingHolds:
    """The window query, at its edges.

    Every one of these is a way `LEAD` can pair the wrong two rows, and each
    would show up as a car reported inside a building it left hours ago.
    """

    def test_an_exit_with_no_entry_before_it_is_not_a_visit(self, store):
        """A car that was already inside when the engine started. There is no
        entry to pair with, and inventing one would put a made-up arrival time
        on the page."""
        a_pass(store, at=NOON, direction="exit")

        assert store.visits() == []
        assert store.inside() == []

    def test_the_exit_after_the_entry_is_the_one_that_pairs(self, store):
        """Not the last exit of the day, not the first of the log — the next
        pass in time order for that plate."""
        a_pass(store, at=NOON, direction="entry")
        a_pass(store, at=NOON + timedelta(minutes=20), direction="exit")
        a_pass(store, at=NOON + timedelta(hours=2), direction="entry")
        a_pass(store, at=NOON + timedelta(hours=4), direction="exit")

        visits = sorted(store.visits(), key=lambda v: v.entered)

        assert [v.minutes(NOON) for v in visits] == [20.0, 120.0]
        assert not any(v.inferred for v in visits)

    def test_a_car_that_came_back_is_two_visits_not_one(self, store):
        a_pass(store, at=NOON, direction="entry")
        a_pass(store, at=NOON + timedelta(minutes=30), direction="exit")
        a_pass(store, at=NOON + timedelta(hours=3), direction="entry")

        visits = store.visits()

        assert len(visits) == 2
        assert len([v for v in visits if v.inside]) == 1

    def test_an_exit_at_another_gate_still_closes_the_visit(self, store):
        """In at the front, out at the back. Pairing is by plate and time, not
        by gate — a visit that only closed at the gate it opened at would
        leave half the school permanently "inside"."""
        a_pass(store, at=NOON, direction="entry", gate=1)
        a_pass(store, at=NOON + timedelta(minutes=45), direction="exit", gate=2)

        visits = store.visits()

        assert len(visits) == 1
        assert visits[0].entry_gate == 1
        assert visits[0].exit_gate == 2
        assert visits[0].inside is False

    def test_the_window_narrows_the_entries_without_breaking_the_pairing(
            self, store):
        """`since` filters which entries are reported. It must not filter the
        passes the pairing is computed from, or an entry just inside the
        window pairs with nothing and reads as still inside."""
        yesterday = NOON - timedelta(days=1)
        a_pass(store, at=yesterday, direction="entry")
        a_pass(store, at=yesterday + timedelta(minutes=30), direction="exit")
        a_pass(store, at=NOON, direction="entry")
        a_pass(store, at=NOON + timedelta(minutes=15), direction="exit")

        today_only = store.visits(since=NOON - timedelta(hours=1))

        assert len(today_only) == 1
        assert today_only[0].minutes(NOON) == 15.0

    def test_an_entry_from_yesterday_is_still_inside_today(self, store):
        """It is not in today's list, because it did not happen today — but
        the car is still in the grounds, and the unfiltered answer says so."""
        a_pass(store, at=NOON - timedelta(days=1), direction="entry")

        assert store.inside(since=NOON - timedelta(hours=1)) == []
        assert len(store.inside()) == 1

    def test_gates_counts_a_gate_that_only_has_an_entry_camera(self, store):
        """One direction is all this gate can see. Entries are real, exits are
        zero because none were recorded — the flag that says pairing is
        impossible lives on the camera configuration, not here."""
        a_pass(store, at=NOON, direction="entry", gate=1)
        a_pass(store, plate=OTHER, at=NOON, direction="entry", gate=1)

        totals = store.gates(NOON - timedelta(hours=1))

        assert totals == [{"gate": 1, "entered": 2, "left": 0, "inside": 2}]

    def test_each_gate_is_counted_separately(self, store):
        a_pass(store, at=NOON, direction="entry", gate=1)
        a_pass(store, plate=OTHER, at=NOON, direction="entry", gate=2)

        totals = store.gates(NOON - timedelta(hours=1))

        assert [row["gate"] for row in totals] == [1, 2]
        assert all(row["entered"] == 1 for row in totals)


class TestThePassIsPhotographed:
    """P6-FR-003: a pass carries a photograph of the frame and a crop of the
    plate. P6-FR-026: both are deleted at thirty days and **the row stays**.

    The rule underneath both: a picture is evidence attached to a record, not
    a precondition for one. Nothing here may cost a pass.
    """

    def test_both_images_are_written(self, tmp_path):
        import numpy as np

        from vg.events.vehicles import save_pass_images
        from vg.infer.plates import PlateBox

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        box = PlateBox(x1=100, y1=200, x2=260, y2=250, confidence=0.9)

        snapshot, crop = save_pass_images(
            tmp_path / "gate", "cam-laptop", NOON, PLATE_ARABIC, frame, box)

        assert snapshot and Path(snapshot).is_file()
        assert crop and Path(crop).is_file()

    def test_the_filename_is_ascii_whatever_the_plate_is(self, tmp_path):
        """Arabic in a filename survives NTFS and dies in the first tool that
        copies it over a share. The plate is in the database anyway."""
        import numpy as np

        from vg.events.vehicles import save_pass_images

        snapshot, _ = save_pass_images(
            tmp_path / "gate", "cam-laptop", NOON, PLATE_ARABIC,
            np.zeros((60, 120, 3), dtype=np.uint8))

        assert snapshot is not None
        assert Path(snapshot).name.isascii()

    def test_no_frame_means_no_picture_and_no_error(self, tmp_path):
        from vg.events.vehicles import save_pass_images

        assert save_pass_images(tmp_path / "gate", "cam", NOON,
                                PLATE_ARABIC, None) == (None, None)

    def test_a_write_that_fails_costs_the_picture_not_the_pass(
            self, store, tmp_path, monkeypatch):
        """The whole reason this returns paths instead of raising."""
        import numpy as np

        from vg.events import vehicles as ve

        monkeypatch.setattr(
            ve.Path, "mkdir",
            lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))

        snapshot, crop = ve.save_pass_images(
            tmp_path / "gate", "cam", NOON, PLATE_ARABIC,
            np.zeros((60, 120, 3), dtype=np.uint8))

        assert (snapshot, crop) == (None, None)
        # And the pass still writes, which is the part that is kept for good.
        assert a_pass(store).plate == CANONICAL

    def test_expiry_deletes_the_crop_as_well_as_the_photograph(
            self, store, tmp_path):
        snapshot = tmp_path / "old.jpg"
        crop = tmp_path / "old-plate.jpg"
        snapshot.write_bytes(b"jpeg")
        crop.write_bytes(b"jpeg")
        record = store.record_pass(
            at=NOON - timedelta(days=31), camera_id="gate1_entry", gate=1,
            direction="entry", plate=PLATE_ARABIC, confidence=0.9, votes=3,
            needs_review=False, today=TODAY, snapshot=str(snapshot),
            plate_crop=str(crop))

        store.expire(NOON - timedelta(days=30))

        assert not snapshot.exists()
        assert not crop.exists()
        kept = store.pass_by_id(record.id)
        assert kept is not None, "the row outlives its images, always"
        assert kept.has_snapshot is False


# ---------------------------------------------------------------------------
# any recorded day, not just today
# ---------------------------------------------------------------------------

class TestADayIsAWindow:
    """Movements can be asked about any day that has passes in it.

    Every one of these queries took a `since` and ran to the end of time,
    which is right for "today" and wrong for "Tuesday" — a day picker over an
    unbounded query shows Tuesday *and everything after it*.
    """

    def test_a_later_day_is_outside_the_window(self, store):
        a_pass(store, at=NOON)
        a_pass(store, plate=OTHER, at=NOON + timedelta(days=1))

        day = store.passes(since=NOON - timedelta(hours=12),
                           until=NOON + timedelta(hours=12))

        assert len(day) == 1

    def test_an_earlier_day_is_outside_the_window(self, store):
        a_pass(store, at=NOON - timedelta(days=1))
        a_pass(store, plate=OTHER, at=NOON)

        day = store.passes(since=NOON - timedelta(hours=1),
                           until=NOON + timedelta(hours=1))

        assert len(day) == 1

    def test_the_window_excludes_its_upper_bound(self, store):
        """Midnight belongs to the day that is starting, not the one ending —
        otherwise two consecutive days both claim the same pass."""
        a_pass(store, at=NOON)

        assert store.passes(since=NOON - timedelta(hours=1), until=NOON) == []
        assert len(store.passes(since=NOON,
                                until=NOON + timedelta(hours=1))) == 1

    def test_visits_are_bounded_by_when_the_car_came_in(self, store):
        """A visit that ran past midnight belongs to the day it started, which
        is what somebody asking "what happened on Tuesday" means."""
        a_pass(store, at=NOON)
        a_pass(store, at=NOON + timedelta(hours=14), direction="exit")

        visits = store.visits(since=NOON - timedelta(hours=12),
                              until=NOON + timedelta(hours=12))

        assert len(visits) == 1
        assert visits[0].left_at is not None

    def test_gates_are_bounded_too(self, store):
        a_pass(store, at=NOON)
        a_pass(store, plate=OTHER, at=NOON + timedelta(days=2))

        rows = store.gates(NOON - timedelta(hours=1),
                           NOON + timedelta(hours=1))

        assert sum(r["entered"] for r in rows) == 1


class TestTheTrafficChart:
    def test_entries_and_exits_are_counted_separately(self, store):
        a_pass(store, at=NOON)
        a_pass(store, at=NOON + timedelta(minutes=20), direction="exit")

        hours = store.hourly(NOON - timedelta(hours=1),
                             NOON + timedelta(hours=2))

        assert sum(h["entered"] for h in hours) == 1
        assert sum(h["left"] for h in hours) == 1

    def test_an_hour_with_nothing_in_it_is_absent_not_zero(self, store):
        """A flat bar at 3am is a drawing of data that does not exist."""
        a_pass(store, at=NOON)

        hours = store.hourly(NOON - timedelta(hours=6),
                             NOON + timedelta(hours=6))

        assert len(hours) == 1

    def test_a_quiet_day_is_an_empty_list(self, store):
        assert store.hourly(NOON, NOON + timedelta(hours=1)) == []

    def test_hours_come_back_in_order(self, store):
        a_pass(store, at=NOON + timedelta(hours=3))
        a_pass(store, plate=OTHER, at=NOON)

        hours = store.hourly(NOON - timedelta(hours=1),
                             NOON + timedelta(hours=6))

        assert [h["hour"] for h in hours] == sorted(h["hour"] for h in hours)


class TestAVisitCarriesItsEvidence:
    """Each row can show the photograph that proves it — by pointing at the
    pass that holds it, never by copying the image anywhere."""

    def test_the_entry_pass_id_comes_through(self, store):
        entry = a_pass(store, at=NOON)

        assert store.visits()[0].entry_pass_id == entry.id

    def test_the_exit_pass_id_comes_through(self, store):
        a_pass(store, at=NOON)
        exit_pass = a_pass(store, at=NOON + timedelta(hours=1),
                           direction="exit")

        assert store.visits()[0].exit_pass_id == exit_pass.id

    def test_an_inferred_exit_offers_no_exit_photograph(self, store):
        """A visit closed because the car was seen entering AGAIN has no exit
        picture — nobody watched it leave. Handing over the re-entry's
        photograph would present an inference as an observation."""
        a_pass(store, at=NOON)
        a_pass(store, at=NOON + timedelta(hours=2))

        visit = next(v for v in store.visits() if v.inferred)
        assert visit.exit_pass_id is None
        assert visit.exit_has_snapshot is False

    def test_no_photograph_means_no_thumbnail_not_a_broken_one(self, store):
        """These passes were recorded without images, which is the normal
        state after thirty days — the row is kept, the picture is not."""
        a_pass(store, at=NOON)

        assert store.visits()[0].entry_has_snapshot is False


class TestTheLastImportLine:
    """The register tab draws "Last import: 2,140 rows · 6 skipped · 12 Aug".

    That line is either a fact or it is absent. The audit log cannot be the
    source — it still lives in RAM until P3 and would forget at the next
    restart — so the importer records its own run.
    """

    def test_a_fresh_register_has_never_imported_anything(self, store):
        """None, not a row of zeros. "0 rows imported" reads as a failed
        import rather than as an import that never happened."""
        assert store.last_import_run() is None

    def test_an_import_records_what_it_did(self, store):
        store.import_rows([
            {"plate": "ب ج د 1234", "owner_name": "Mohamed Fouad"},
            {"plate": "س ص ط 9876", "owner_name": "Sara Ibrahim"},
        ], by_who="Mohamed Fouad")

        run = store.last_import_run()
        assert run["added"] == 2
        assert run["by_who"] == "Mohamed Fouad"

    def test_the_numbers_match_what_the_importer_reported(self, store):
        result = store.import_rows([
            {"plate": "ب ج د 1234"},
            {"plate": "ب ج د 1234"},          # the same car twice
            {"plate": "not a plate at all"},   # rejected
        ], by_who="Sara Ibrahim")

        run = store.last_import_run()
        assert run["added"] == result["added"]
        assert run["skipped"] == result["skipped_duplicates"]
        assert run["rejected"] == len(result["problems"])

    def test_the_latest_run_is_the_one_reported(self, store):
        store.import_rows([{"plate": "ب ج د 1234"}], by_who="First")
        store.import_rows([{"plate": "س ص ط 9876"}], by_who="Second")

        assert store.last_import_run()["by_who"] == "Second"


class TestTheChartIsInTheSitesHours:
    """The hour buckets are the site's, and the shift is done in minutes.

    **The obvious version of this is wrong and looks right.** Group on the
    stored UTC hour, let the caller add `offset // 60`, and it is exact for
    Cairo, London and New York — and an hour out for half of every day in
    India (+5:30) or Iran (+3:30). The bug would never show up at this school
    and would be waiting for the next one.
    """

    def test_utc_is_unshifted(self, store):
        a_pass(store, at=NOON)                      # 12:00 UTC

        assert store.hourly(NOON - timedelta(hours=1),
                            NOON + timedelta(hours=1), 0)[0]["hour"] == 12

    def test_a_whole_hour_offset_shifts_the_bucket(self, store):
        a_pass(store, at=NOON)                      # 12:00 UTC = 15:00 Cairo

        rows = store.hourly(NOON - timedelta(hours=1),
                            NOON + timedelta(hours=1), 180)

        assert rows[0]["hour"] == 15

    def test_a_half_hour_offset_lands_in_the_right_hour(self, store):
        """12:45 UTC is 18:15 in India — hour 18, not hour 17."""
        quarter_to = NOON + timedelta(minutes=45)
        a_pass(store, at=quarter_to)

        rows = store.hourly(NOON, NOON + timedelta(hours=1), 330)

        assert rows[0]["hour"] == 18

    def test_a_negative_offset_wraps_backwards(self, store):
        """02:00 UTC is 21:00 the previous evening in New York."""
        early = NOON.replace(hour=2)
        a_pass(store, at=early)

        rows = store.hourly(early - timedelta(hours=1),
                            early + timedelta(hours=1), -300)

        assert rows[0]["hour"] == 21
