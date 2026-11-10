"""Spec 023: attendance read as it was recorded, excused, the week, the groups.

What these pin, in the order a head teacher would ask:

* **A past day is the day as it was.** Somebody enrolled after it is not on it,
  somebody removed since still is (by name), a day nothing was recorded on is
  "no record" rather than a school of absentees, and the cut-off that applied
  that day decides who was late.
* **Excused is neither here nor absent**, and an arrival always beats it.
* **The week strip and the table cannot disagree** about the same morning.
* **Groups carry a 30-day figure** that is "no data" rather than 0%.
* **Removal keeps the past readable** and stops recognition at once.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace as dc_replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg import config as vgconfig
from vg.api import app as app_module
from vg.api import schemas as S
from vg.api.live import LiveStore
from vg.api.store import AlreadyBusy, NothingThere, SubsystemUnavailable
from vg.config import CameraConfig, HoursConfig
from vg.events.attendance import AttendanceLedger
from vg.events.sightings import Sighting, SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry

CAIRO = 180
MODEL = "sface-2021dec"
ENROLLED = datetime(2026, 1, 1, tzinfo=timezone.utc)

DOORWAY = CameraConfig(id="cam-door", name="Main entrance", source="0",
                       enabled=True, features=("attendance",), faces=True)
DOORWAY_OFF = CameraConfig(id="cam-gate", name="Side gate", source="0",
                           enabled=False, features=("attendance",), faces=True)
HALL = CameraConfig(id="cam-hall", name="Hall", source="0",
                    enabled=True, features=("counting",), faces=True)


def at(day: str, hour: int, minute: int = 0) -> datetime:
    """A UTC instant that is `hour:minute` in Cairo on `day`."""
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hour, minute, tzinfo=timezone.utc) - timedelta(minutes=CAIRO)


def unit(seed: str) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.standard_normal(128).astype("float32")
    return v / float(np.linalg.norm(v))


def seen(person: str, when: datetime, camera: str = "cam-door") -> Sighting:
    return Sighting(person, camera, when, confidence=0.8, model=MODEL)


# A Monday long past, and the days around it.
D = "2026-08-17"
CUTOFF = time(8, 0)


@dataclass
class World:
    store: LiveStore
    gallery: FaceGallery
    sightings: SightingStore
    tmp: tempfile.TemporaryDirectory

    def person(self, pid, name, group=None, type="Student", created=ENROLLED,
               photo=True):
        self.gallery.add_person(pid, name, type=type, group=group, created_at=created)
        if photo:
            self.gallery.add_embedding(pid, unit(pid), MODEL)

    def arrive(self, pid, day, hour, minute=0, camera="cam-door"):
        self.sightings.record(seen(pid, at(day, hour, minute), camera), force=True)


def build(cameras=()):
    tmp = tempfile.TemporaryDirectory()
    gallery = FaceGallery(Path(tmp.name) / "g.db", model=MODEL, threshold=0.363)
    sightings = SightingStore(Path(tmp.name) / "s.db", clock=CAIRO)
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry(list(cameras)),
                      gallery=gallery, sightings=sightings)
    return World(store, gallery, sightings, tmp)


@pytest.fixture
def world():
    w = build([DOORWAY, DOORWAY_OFF, HALL])
    w.person("p-layla", "Layla Ahmed", "Grade 8")
    w.person("p-omar", "Omar Khaled", "Grade 8")
    w.person("p-youssef", "Youssef Ali", "Grade 9")
    yield w
    # The gallery before the temp directory, or Windows fails the teardown.
    w.sightings.close()
    w.gallery.close()
    w.tmp.cleanup()


def statuses(result: S.AttendanceResult) -> dict[str, str]:
    return {r.person.name: r.status.value for r in result.records}


def working_days(store: LiveStore, count: int) -> list[str]:
    """The most recent `count` working days before today, newest first."""
    today = date.fromisoformat(store._today_str())
    days, back = [], 1
    while len(days) < count:
        d = today - timedelta(days=back)
        if d.weekday() in store.hours().working_days:
            days.append(d.isoformat())
        back += 1
    return days


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

class TestLedger:
    @pytest.fixture
    def ledger(self, tmp_path):
        return AttendanceLedger(tmp_path / "s.db", CAIRO)

    def test_two_excusals_for_one_day_are_one_person(self, ledger):
        now = datetime.now(timezone.utc)
        ledger.excuse("p-a", D, "Admin One", now)
        ledger.excuse("p-a", D, "Admin Two", now)
        assert ledger.excused_on(D) == {"p-a"}
        with ledger._open() as conn:
            rows = conn.execute("SELECT COUNT(*) AS n FROM excusal").fetchone()["n"]
        assert rows == 2  # each administrator's act is kept

    def test_an_excusal_is_for_its_own_day(self, ledger):
        ledger.excuse("p-a", D, "Admin", datetime.now(timezone.utc))
        assert ledger.excused_on("2026-08-18") == set()
        assert ledger.excused_among("p-a", [D, "2026-08-18"]) == {D}

    def test_a_removed_person_belongs_on_the_days_before_the_removal(self, ledger):
        person = type("P", (), dict(
            id="p-gone", name="Gone Person", type="Student", group="Grade 8",
            created_at=ENROLLED, photo_on_file=True))()
        ledger.note_removed(person, at("2026-08-20", 10), "Admin")

        assert [r.name for r in ledger.removed_expected_on("2026-08-19")] == ["Gone Person"]
        assert ledger.removed_expected_on("2026-08-20") == []  # the removal day
        assert ledger.removed_expected_on("2026-08-25") == []
        # Removed after arriving the same day: seen, so still on that day.
        assert [r.name for r in ledger.removed_expected_on(
            "2026-08-20", seen={"p-gone"})] == ["Gone Person"]
        # Not yet enrolled on that day.
        assert ledger.removed_expected_on("2025-12-31", seen={"p-gone"}) == []

    def test_somebody_without_a_photo_was_never_expected(self, ledger):
        person = type("P", (), dict(
            id="p-x", name="No Photo", type="Student", group=None,
            created_at=ENROLLED, photo_on_file=False))()
        ledger.note_removed(person, at("2026-08-20", 10), "Admin")
        assert ledger.removed_expected_on("2026-08-10", seen={"p-x"}) == []

    def test_hours_are_noted_only_when_they_change(self, ledger):
        base = HoursConfig()
        ledger.note_hours(base, "2026-09-01")
        ledger.note_hours(base, "2026-09-02")  # nothing changed: no new row
        later = HoursConfig(late_cutoff=time(8, 15))
        ledger.note_hours(later, "2026-09-10")

        assert ledger.hours_on("2026-08-31") is None
        assert ledger.hours_on("2026-09-05").late_cutoff == time(8, 0)
        assert ledger.hours_on("2026-09-10").late_cutoff == time(8, 15)
        with ledger._open() as conn:
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM hours_snapshot").fetchone()["n"] == 2

    def test_rows_survive_close_and_reopen(self, tmp_path):
        one = AttendanceLedger(tmp_path / "s.db", CAIRO)
        one.excuse("p-a", D, "Admin", datetime.now(timezone.utc))
        one.note_hours(HoursConfig(), "2026-09-01")
        one.close()

        two = AttendanceLedger(tmp_path / "s.db", CAIRO)
        assert two.excused_on(D) == {"p-a"}
        assert two.hours_on("2026-09-01").day_start == time(7, 30)


# ---------------------------------------------------------------------------
# the register store
# ---------------------------------------------------------------------------

class TestRegisterStore:
    @pytest.fixture
    def sightings(self, tmp_path):
        s = SightingStore(tmp_path / "s.db", clock=CAIRO)
        yield s
        s.close()

    def test_excused_is_for_the_absent_only(self, sightings):
        sightings.record(seen("p-a", at(D, 7, 40)), force=True)
        reg = sightings.register(D, ["p-a", "p-b", "p-c"], CUTOFF,
                                 excused={"p-a", "p-b"})
        by = {e.person_id: e.status for e in reg.entries}
        # Arrival wins: p-a came, so the excusal changes nothing.
        assert by == {"p-a": "on_time", "p-b": "excused", "p-c": "absent"}
        assert (reg.present, reg.excused, reg.absent, reg.expected) == (1, 1, 1, 3)

    def test_present_counts_only_arrivals(self, sightings):
        sightings.record(seen("p-a", at(D, 8, 30)), force=True)
        reg = sightings.register(D, ["p-a", "p-b"], CUTOFF, excused={"p-b"})
        assert reg.present == 1 and reg.late == 1

    def test_has_day_is_about_sightings_not_dates(self, sightings):
        assert not sightings.has_day(D)
        sightings.record(seen("p-a", at(D, 7, 40)), force=True)
        assert sightings.has_day(D) and not sightings.has_day("2026-08-18")

    def test_person_days_agrees_with_history_and_the_register(self, sightings):
        for day, minute in ((D, 40), ("2026-08-16", 55), ("2026-08-15", 59)):
            sightings.record(seen("p-a", at(day, 8 if minute > 50 else 7, minute % 60
                                            if minute > 50 else minute)), force=True)
        sightings.record(seen("p-a", at("2026-08-14", 1, 14)), force=True)  # night walk

        dates = [D, "2026-08-16", "2026-08-15", "2026-08-14"]
        got = sightings.person_days("p-a", dates, cutoffs={d: CUTOFF for d in dates},
                                    day_start=time(7, 30), day_end=time(15, 0))
        hist = sightings.history("p-a", cutoff=CUTOFF, day_start=time(7, 30),
                                 day_end=time(15, 0))
        assert {d: (e.status, e.minutes_late) for d, e in got.items()} == {
            d: (e.status, e.minutes_late) for d, e in hist.items()}
        assert "2026-08-14" not in got  # outside school hours: not an arrival
        reg = sightings.register("2026-08-16", ["p-a"], CUTOFF,
                                 time(7, 30), time(15, 0))
        assert reg.entries[0].status == got["2026-08-16"].status


# ---------------------------------------------------------------------------
# a past day, as it was
# ---------------------------------------------------------------------------

class TestPastDays:
    def test_somebody_enrolled_after_the_day_is_not_on_it(self, world):
        world.person("p-new", "New Arrival", created=at("2026-09-01", 9))
        world.arrive("p-layla", D, 7, 40)

        assert "New Arrival" not in statuses(world.store.attendance("group", "Everyone", D))
        later = world.store.attendance("group", "Everyone", "2026-09-02")
        assert later.recorded is False  # nothing seen that day
        world.arrive("p-layla", "2026-09-02", 7, 40)
        assert statuses(world.store.attendance(
            "group", "Everyone", "2026-09-02"))["New Arrival"] == "absent"

    def test_somebody_removed_since_is_still_on_the_days_they_belonged_to(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.arrive("p-omar", D, 7, 41)
        assert world.store.remove_person("p-omar", "Admin") is True

        past = world.store.attendance("group", "Everyone", D)
        assert statuses(past)["Omar Khaled"] == "on_time"  # by name, as recorded
        today = world.store._today_str()
        assert "p-omar" not in [e.person_id for e in world.store._register(today).entries]
        assert "p-omar" not in [p.id for p in world.store.people()]

    def test_a_removed_person_with_no_photo_is_never_expected(self, world):
        world.person("p-nophoto", "No Photo", photo=False)
        world.arrive("p-layla", D, 7, 40)
        world.store.remove_person("p-nophoto", "Admin")
        assert "No Photo" not in statuses(world.store.attendance("group", "Everyone", D))

    def test_a_tombstone_for_somebody_still_enrolled_is_ignored(self, world):
        """A delete that failed after the tombstone was written."""
        world.arrive("p-layla", D, 7, 40)
        world.store.ledger.note_removed(
            world.gallery.person("p-omar"), datetime.now(timezone.utc) + timedelta(days=1),
            "Admin")
        names = [r.person.name for r in world.store.attendance("group", "Everyone", D).records]
        assert names.count("Omar Khaled") == 1

    def test_a_day_with_no_sightings_is_no_record_not_everyone_absent(self, world):
        r = world.store.attendance("group", "Everyone", "2026-08-10")
        assert r.recorded is False
        assert r.records == [] and r.expected == 0 and r.absent == 0

    def test_today_with_nobody_yet_is_a_normal_morning(self, world):
        r = world.store.attendance("group", "Everyone", world.store._today_str())
        assert r.recorded is True
        assert r.expected == 3 and r.absent == 3 and r.present == 0

    def test_a_day_is_judged_by_the_cutoff_that_applied_on_it(self, world):
        world.arrive("p-layla", D, 7, 50)
        world.store.hours()
        # Before anything was noted, the current 08:00 applies: on time.
        assert statuses(world.store.attendance("group", "Everyone", D))["Layla Ahmed"] == "on_time"

        # Hours that were in force from the start of August: 07:45.
        world.store.ledger.note_hours(
            dc_hours(world.store.hours(), late_cutoff=time(7, 45)), "2026-08-01")
        world.store._past_registers.clear()
        assert statuses(world.store.attendance("group", "Everyone", D))["Layla Ahmed"] == "late"

        # Today's hours were noted afterwards and do not rewrite it.
        world.store.hours_on(world.store._today_str())
        assert statuses(world.store.attendance("group", "Everyone", D))["Layla Ahmed"] == "late"

    def test_hours_history_survives_a_ledger_that_cannot_be_read(self, world):
        world.store.ledger = None
        assert world.store.hours_on(D) == world.store.hours()


def dc_hours(hours: HoursConfig, **changes) -> HoursConfig:
    from dataclasses import replace
    return replace(hours, **changes)


# ---------------------------------------------------------------------------
# the group register
# ---------------------------------------------------------------------------

class TestGroupRegister:
    def test_excused_is_its_own_count(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.arrive("p-omar", D, 8, 20)
        world.store.excuse("p-youssef", D, "Admin")

        r = world.store.attendance("group", "Everyone", D)
        assert (r.present, r.late, r.absent, r.excused, r.expected) == (2, 1, 0, 1, 3)
        assert r.expected == r.present + r.absent + r.excused
        assert {m.key: m.value for m in r.metrics}["excused"] == 1

    def test_a_face_only_names_somebody_who_arrived(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.arrive("p-omar", D, 8, 20)
        world.store.excuse("p-youssef", D, "Admin")
        world.person("p-nour", "Nour Hassan", "Grade 8")
        world.store._past_registers.clear()

        by = {r.person.name: r.person.match for r in
              world.store.attendance("group", "Everyone", D).records}
        assert by["Layla Ahmed"] == by["Omar Khaled"] == S.MatchKind.FACE
        assert by["Youssef Ali"] == S.MatchKind.NONE

    def test_records_carry_group_and_the_last_sighting(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.arrive("p-layla", D, 13, 5)
        rec = next(r for r in world.store.attendance("group", "Everyone", D).records
                   if r.person.name == "Layla Ahmed")
        assert rec.group == "Grade 8"
        assert rec.last_seen_at.utc > rec.seen_at.utc

    def test_a_group_counts_only_its_own(self, world):
        world.arrive("p-youssef", D, 7, 40)
        r = world.store.attendance("group", "Grade 8", D)
        assert r.expected == 2 and r.present == 0 and r.absent == 2

    def test_the_strip_is_the_doorways_and_keeps_offline_ones(self, world):
        r = world.store.attendance("group", "Everyone", world.store._today_str())
        assert {c.id for c in r.cameras} == {"cam-door", "cam-gate"}
        gate = next(c for c in r.cameras if c.id == "cam-gate")
        assert gate.offline is True and gate.offline_reason == "disabled"

    def test_recognition_elsewhere_counts_other_cameras_that_identify(self, world):
        r = world.store.attendance("group", "Everyone", world.store._today_str())
        assert r.recognition_elsewhere == 1  # the hall

    def test_groups_here_does_not_count_the_excused(self, world):
        today = world.store._today_str()
        world.arrive("p-layla", today, 12, 0)  # inside school hours, whenever it runs
        world.store.excuse("p-omar", today, "Admin")
        by = {g.name: g.here for g in world.store.groups()}
        assert by["Grade 8"] == 1 and by["Everyone"] == 1


# ---------------------------------------------------------------------------
# the doorway overlay and the camera's reason
# ---------------------------------------------------------------------------

class TestCameraPictures:
    @dataclass
    class Face:
        x: float = 0.1
        y: float = 0.1
        w: float = 0.2
        h: float = 0.2
        label: str = "Layla"
        score: float = 0.9
        identified: bool = True

    class Recogniser:
        def __init__(self, faces):
            self.faces = faces

        def faces_on(self, camera_id):
            return self.faces

    def test_an_unrecognised_face_is_amber_a_recognised_one_is_unchanged(self, world):
        world.store.recogniser = self.Recogniser([
            self.Face(identified=True), self.Face(label="Unknown", identified=False)])
        known, unknown = world.store._face_boxes("cam-door")
        assert known.severity == S.Severity.INFO and known.match == S.MatchKind.FACE
        assert unknown.severity == S.Severity.WARN and unknown.match == S.MatchKind.NONE

    def test_offline_reasons(self, world):
        store = world.store
        assert store.camera_view("cam-gate").offline_reason == "disabled"

        worker = store.registry.worker("cam-door")
        # Never started: the source says it is down.
        assert store.camera_view("cam-door").offline_reason == "down"
        worker.source.health.status = "auth"
        assert store.camera_view("cam-door").offline_reason == "auth"

    def test_an_online_camera_has_no_reason(self, world, monkeypatch):
        worker = world.store.registry.worker("cam-door")
        monkeypatch.setattr(type(worker), "status", property(lambda self: "ok"))
        view = world.store.camera_view("cam-door")
        assert view.offline is False and view.offline_reason is None


# ---------------------------------------------------------------------------
# excusing
# ---------------------------------------------------------------------------

class TestExcuse:
    def test_it_returns_the_persons_row_as_excused(self, world):
        world.arrive("p-layla", D, 7, 40)
        row = world.store.excuse("p-omar", D, "Admin")
        assert row.person.name == "Omar Khaled" and row.status == S.AttendanceStatus.EXCUSED

    def test_the_audit_entry_comes_before_the_row(self, world, monkeypatch):
        world.arrive("p-layla", D, 7, 40)

        def boom(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(world.store.ledger, "excuse", boom)
        with pytest.raises(RuntimeError):
            world.store.excuse("p-omar", D, "Admin One")

        entry = [e for e in world.store._audit if e.action == "attendance.excuse"]
        assert len(entry) == 1
        assert (entry[0].subject, entry[0].detail, entry[0].actor) == (
            "Omar Khaled", D, "Admin One")
        assert world.store.ledger.excused_on(D) == set()

    def test_a_future_day_is_refused(self, world):
        tomorrow = (date.fromisoformat(world.store._today_str())
                    + timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="not happened"):
            world.store.excuse("p-omar", tomorrow, "Admin")
        with pytest.raises(ValueError):
            world.store.excuse("p-omar", "not-a-date", "Admin")

    def test_somebody_not_on_that_day_is_a_404(self, world):
        world.arrive("p-layla", D, 7, 40)
        with pytest.raises(NothingThere):
            world.store.excuse("p-nobody", D, "Admin")
        world.person("p-new", "New Arrival", created=at("2026-09-01", 9))
        with pytest.raises(NothingThere):  # not yet enrolled on D
            world.store.excuse("p-new", D, "Admin")

    def test_somebody_who_arrived_is_refused_with_the_time(self, world):
        world.arrive("p-layla", D, 7, 42)
        with pytest.raises(AlreadyBusy, match="07:42"):
            world.store.excuse("p-layla", D, "Admin")
        assert world.store.ledger.excused_on(D) == set()
        assert not [e for e in world.store._audit if e.action == "attendance.excuse"]

    def test_a_day_nothing_was_recorded_is_refused(self, world):
        with pytest.raises(AlreadyBusy, match="nothing was recorded"):
            world.store.excuse("p-omar", "2026-08-10", "Admin")

    def test_a_second_excuse_succeeds_and_is_audited_again(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.store.excuse("p-omar", D, "Admin One")
        row = world.store.excuse("p-omar", D, "Admin Two")
        assert row.status == S.AttendanceStatus.EXCUSED
        assert len([e for e in world.store._audit
                    if e.action == "attendance.excuse"]) == 2
        assert world.store.attendance("group", "Everyone", D).excused == 1

    def test_a_late_excuse_drops_that_day_from_the_memo(self, world):
        world.arrive("p-layla", D, 7, 40)
        before = world.store._everyone_register(D)
        assert world.store._everyone_register(D) is before  # memoised
        world.store.excuse("p-omar", D, "Admin")
        assert world.store._everyone_register(D) is not before

    def test_today_is_never_memoised(self, world):
        today = world.store._today_str()
        world.store._everyone_register(today)
        assert all(key[0] != today for key in world.store._past_registers)

    def test_nothing_to_save_into_is_a_503(self, bare_live_store):
        with pytest.raises(SubsystemUnavailable):
            bare_live_store.excuse("p-a", D, "Admin")

    def test_a_ledger_that_would_not_open_says_why(self, world):
        world.store.ledger = None
        world.store.ledger_error = "OperationalError: unable to open"
        with pytest.raises(SubsystemUnavailable, match="unable to open"):
            world.store.excuse("p-omar", D, "Admin")


# ---------------------------------------------------------------------------
# the week
# ---------------------------------------------------------------------------

class TestWeek:
    def test_seven_working_days_newest_first_skipping_friday(self, world):
        for day in ("2026-08-17", "2026-08-16", "2026-08-15", "2026-08-13",
                    "2026-08-12", "2026-08-11", "2026-08-10"):
            world.arrive("p-layla", day, 7, 40)
        days = world.store.week("p-layla", D)
        assert [d.date for d in days] == [
            "2026-08-17", "2026-08-16", "2026-08-15", "2026-08-13",
            "2026-08-12", "2026-08-11", "2026-08-10"]  # Friday the 14th is skipped

    def test_each_kind_of_day(self, world):
        world.arrive("p-layla", "2026-08-17", 7, 40)            # on time
        world.arrive("p-layla", "2026-08-16", 8, 20)            # late
        world.arrive("p-omar", "2026-08-15", 7, 40)             # a recorded day, not her
        world.arrive("p-omar", "2026-08-13", 7, 40)
        world.store.excuse("p-layla", "2026-08-13", "Admin")    # excused
        # 2026-08-12: nothing recorded at all.
        days = {d.date: d for d in world.store.week("p-layla", D)}

        assert days["2026-08-17"].status == S.AttendanceStatus.ON_TIME
        assert days["2026-08-17"].location == "cam-door"  # as the table names it
        assert days["2026-08-17"].seen_at is not None
        assert days["2026-08-16"].status == S.AttendanceStatus.LATE
        assert days["2026-08-16"].minutes_late == 20
        assert days["2026-08-15"].status == S.AttendanceStatus.ABSENT
        assert days["2026-08-13"].status == S.AttendanceStatus.EXCUSED
        assert days["2026-08-12"].status == S.AttendanceStatus.UNKNOWN

    def test_before_enrolment_is_no_record(self, world):
        world.person("p-new", "New Arrival", created=at("2026-08-16", 9))
        world.arrive("p-layla", "2026-08-15", 7, 40)
        world.arrive("p-layla", "2026-08-16", 7, 40)
        days = {d.date: d for d in world.store.week("p-new", "2026-08-16")}
        assert days["2026-08-15"].status == S.AttendanceStatus.UNKNOWN
        assert days["2026-08-16"].status == S.AttendanceStatus.ABSENT

    def test_the_strip_and_the_table_agree(self, world):
        world.arrive("p-layla", D, 8, 1)
        world.arrive("p-omar", D, 7, 59)
        table = statuses(world.store.attendance("group", "Everyone", D))
        for pid, name in (("p-layla", "Layla Ahmed"), ("p-omar", "Omar Khaled")):
            assert world.store.week(pid, D)[0].status.value == table[name]

    def test_arrival_beats_an_excusal_in_the_strip_too(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.store.ledger.excuse("p-layla", D, "Admin", datetime.now(timezone.utc))
        assert world.store.week("p-layla", D)[0].status == S.AttendanceStatus.ON_TIME

    def test_it_asks_for_the_person_once_not_a_register_a_day(self, world, monkeypatch):
        world.arrive("p-layla", D, 7, 40)
        calls = []
        monkeypatch.setattr(world.sightings, "register",
                            lambda *a, **k: calls.append(1))
        world.store.week("p-layla", D)
        assert calls == []

    def test_a_removed_person_still_has_a_week(self, world):
        world.arrive("p-omar", D, 7, 40)
        world.store.remove_person("p-omar", "Admin")
        assert world.store.week("p-omar", D)[0].status == S.AttendanceStatus.ON_TIME

    def test_the_days_after_a_removal_are_no_record_not_absent(self, world):
        person = world.gallery.person("p-omar")
        world.arrive("p-omar", "2026-08-18", 7, 40)
        world.arrive("p-layla", "2026-08-24", 7, 40)  # a recorded day, not his
        world.arrive("p-layla", "2026-08-19", 7, 40)
        world.store.ledger.note_removed(person, at("2026-08-20", 10), "Admin")
        world.gallery.remove_person("p-omar")

        days = {d.date: d.status for d in world.store.week("p-omar", "2026-08-24")}
        assert days["2026-08-24"] == S.AttendanceStatus.UNKNOWN
        assert days["2026-08-20"] == S.AttendanceStatus.UNKNOWN
        assert days["2026-08-19"] == S.AttendanceStatus.ABSENT  # still on the roll
        assert days["2026-08-18"] == S.AttendanceStatus.ON_TIME

    def test_nothing_with_recognition_off_or_for_nobody(self, bare_live_store, world):
        assert bare_live_store.week("p-a", D) == []
        assert world.store.week("p-nobody", D) == []
        assert world.store.week("p-layla", "garbage") == []


# ---------------------------------------------------------------------------
# removal
# ---------------------------------------------------------------------------

class TestRemoval:
    def test_audit_then_tombstone_then_delete(self, world, monkeypatch):
        order = []
        real_log = world.store._log
        monkeypatch.setattr(world.store, "_log", lambda *a, **k: (
            order.append("audit"), real_log(*a, **k))[1])
        real_note = world.store.ledger.note_removed
        monkeypatch.setattr(world.store.ledger, "note_removed", lambda *a, **k: (
            order.append("tombstone"), real_note(*a, **k))[1])
        real_remove = world.gallery.remove_person
        monkeypatch.setattr(world.gallery, "remove_person", lambda *a, **k: (
            order.append("delete"), real_remove(*a, **k))[1])

        assert world.store.remove_person("p-omar", "Admin") is True
        assert order == ["audit", "tombstone", "delete"]

    def test_a_failing_delete_leaves_the_audit_entry_and_the_person(self, world, monkeypatch):
        world.arrive("p-omar", D, 7, 40)

        def boom(*a, **k):
            raise RuntimeError("locked")

        monkeypatch.setattr(world.gallery, "remove_person", boom)
        with pytest.raises(RuntimeError):
            world.store.remove_person("p-omar", "Admin")

        assert [e.action for e in world.store._audit] == ["person.remove"]
        assert world.gallery.person("p-omar") is not None
        names = [r.person.name for r in world.store.attendance("group", "Everyone", D).records]
        assert names.count("Omar Khaled") == 1  # the tombstone is ignored

    def test_recognition_cannot_name_them_afterwards(self, world):
        vector = unit("p-omar")
        assert world.gallery.match(vector).person is not None
        world.store.remove_person("p-omar", "Admin")
        assert world.gallery.match(vector).person is None or \
            world.gallery.match(vector).person.id != "p-omar"

    def test_yesterday_keeps_them_and_today_does_not(self, world):
        world.arrive("p-layla", D, 7, 40)
        world.arrive("p-omar", D, 7, 41)
        world.store.remove_person("p-omar", "Admin")
        assert "Omar Khaled" in statuses(world.store.attendance("group", "Everyone", D))
        assert "Omar Khaled" not in [
            r.person.name for r in world.store.attendance(
                "group", "Everyone", world.store._today_str()).records]

    def test_the_directory_may_say_excused(self, world):
        today = world.store._today_str()
        world.arrive("p-layla", today, 12, 0)
        world.store.excuse("p-omar", today, "Admin")
        by = {p.name: p.attendance_today for p in world.store.people()}
        assert by["Omar Khaled"] == S.AttendanceStatus.EXCUSED


# ---------------------------------------------------------------------------
# groups: the 30-day figure
# ---------------------------------------------------------------------------

class TestThirtyDays:
    def figures(self, store):
        return {g.name: (g.attendance_30d, g.recorded_days) for g in store.groups()}

    def test_no_data_is_none_not_zero(self, world):
        assert self.figures(world.store)["Grade 8"] == (None, 0)

    def test_recognition_off_is_none(self):
        w = build()
        try:
            w.person("p-a", "A One", "Grade 8")
            w.store.sightings = None
            assert {g.name: g.attendance_30d for g in w.store.groups()}["Grade 8"] is None
        finally:
            w.sightings.close()
            w.gallery.close()
            w.tmp.cleanup()

    def test_arrived_over_expected_with_the_excused_taken_out(self, world):
        d1, d2 = working_days(world.store, 2)
        for pid in ("p-layla", "p-youssef"):
            world.arrive(pid, d1, 7, 40)           # omar absent on d1
        world.arrive("p-layla", d2, 7, 40)
        world.arrive("p-omar", d2, 7, 45)
        world.store.excuse("p-youssef", d2, "Admin")

        f = self.figures(world.store)
        assert f["Grade 8"] == (0.75, 2)           # 3 of 4
        assert f["Grade 9"] == (1.0, 1)            # d2 excused: neither for nor against
        assert f["Everyone"][1] == 2
        assert f["Everyone"][0] == pytest.approx(4 / 5)
        # They overlap and are not slices of a pie.
        assert 0.0 <= f["Everyone"][0] <= 1.0

    def _with_hours(self, world, monkeypatch, cutoff):
        real = world.store.hours_on
        monkeypatch.setattr(world.store, "hours_on", lambda on: dc_replace(
            real(on), late_cutoff=cutoff, working_days=frozenset(range(7))))

    def test_today_is_left_out_until_its_cutoff_has_passed(self, world, monkeypatch):
        world.sightings.record(seen("p-layla", datetime.now(timezone.utc)), force=True)
        self._with_hours(world, monkeypatch, time(23, 59, 59))
        assert self.figures(world.store)["Grade 8"] == (None, 0)

    def test_today_counts_once_its_cutoff_has_passed(self, world, monkeypatch):
        world.sightings.record(seen("p-layla", datetime.now(timezone.utc)), force=True)
        self._with_hours(world, monkeypatch, time(0, 0))
        assert self.figures(world.store)["Grade 8"][1] == 1

    def test_a_day_nothing_was_recorded_on_is_skipped(self, world):
        d1, d2 = working_days(world.store, 2)
        world.arrive("p-layla", d1, 7, 40)
        assert self.figures(world.store)["Grade 8"][1] == 1  # d2 has no sightings

    def test_a_non_working_day_is_skipped(self, world):
        today = date.fromisoformat(world.store._today_str())
        friday = next(today - timedelta(days=b) for b in range(1, 8)
                      if (today - timedelta(days=b)).weekday() == 4)
        world.arrive("p-layla", friday.isoformat(), 7, 40)
        assert self.figures(world.store)["Grade 8"] == (None, 0)

    def test_one_pass_serves_every_group_and_the_past_is_remembered(
            self, world, monkeypatch):
        d1, d2 = working_days(world.store, 2)
        world.arrive("p-layla", d1, 7, 40)
        world.arrive("p-layla", d2, 7, 40)
        calls = []
        real = world.sightings.register
        monkeypatch.setattr(world.sightings, "register",
                            lambda *a, **k: (calls.append(a[0]), real(*a, **k))[1])

        world.store.groups()
        assert sorted(calls) == sorted([d1, d2, world.store._today_str()])
        calls.clear()
        world.store.groups()
        assert calls == [world.store._today_str()]  # only today is read again

    def test_a_late_excuse_changes_the_figure(self, world):
        d1, = working_days(world.store, 1)
        world.arrive("p-layla", d1, 7, 40)
        assert self.figures(world.store)["Grade 8"] == (0.5, 1)
        world.store.excuse("p-omar", d1, "Admin")
        assert self.figures(world.store)["Grade 8"] == (1.0, 1)

    def test_somebody_in_two_groups_counts_in_both(self, world):
        d1, = working_days(world.store, 1)
        world.arrive("p-layla", d1, 7, 40)
        f = self.figures(world.store)
        assert f["Everyone"][0] == pytest.approx(1 / 3)
        assert f["Grade 8"][0] == 0.5 and f["Grade 9"][0] == 0.0


# ---------------------------------------------------------------------------
# the export
# ---------------------------------------------------------------------------

@pytest.fixture
def api(world, user_store, authed):
    app_module.set_store(world.store)
    application = app_module.create_app()
    application.state.users = user_store
    application.state.registry = world.store.registry
    return application, world


class TestExport:
    def lines(self, client, day):
        r = client.get("/attendance/export", params={"subject": "Everyone", "date": day})
        assert r.status_code == 200
        return r.text.splitlines()

    def test_excused_group_and_the_summary(self, api, authed):
        application, world = api
        world.arrive("p-layla", D, 7, 40)
        world.store.excuse("p-omar", D, "Admin")
        lines = self.lines(authed(application), D)

        assert lines[0].split(",")[:6] == [
            "date", "name", "person_id", "type", "group", "status"]
        omar = next(l for l in lines if "Omar Khaled" in l).split(",")
        assert omar[4:6] == ["Grade 8", "excused"]
        assert "excused,1" in lines and "absent,1" in lines

    def test_a_day_nothing_was_recorded_on_is_the_header_and_the_summary(self, api, authed):
        application, _ = api
        lines = [l for l in self.lines(authed(application), "2026-08-10") if l]
        assert lines[0].startswith("date,name")
        assert not any("Layla" in l for l in lines)
        assert "expected,0" in lines


# ---------------------------------------------------------------------------
# permissions and the HTTP seam
# ---------------------------------------------------------------------------

class TestEndpoints:
    PATHS = [("GET", "/attendance"), ("GET", "/attendance/export"),
             ("GET", "/attendance/week?person=p-layla&date=" + D),
             ("GET", "/groups"), ("GET", "/people"),
             ("POST", "/enrolment/sessions"),
             ("POST", "/attendance/excused")]

    def test_it_is_refused_everywhere(self, api, authed):
        application, _ = api
        it = authed(application, "it")
        for method, path in self.PATHS:
            r = it.request(method, path, json={"personId": "p-omar", "date": D}
                           if method == "POST" else None)
            assert r.status_code == 403, (method, path)

    def test_an_admin_is_not_refused(self, api, authed):
        application, _ = api
        admin = authed(application, "admin")
        for method, path in self.PATHS:
            r = admin.request(method, path, json={"personId": "p-omar", "date": D}
                              if method == "POST" else None)
            assert r.status_code != 403, (method, path)

    def test_excuse_over_http(self, api, authed):
        application, world = api
        world.arrive("p-layla", D, 7, 42)
        client = authed(application)
        body = {"personId": "p-omar", "date": D}

        ok = client.post("/attendance/excused", json=body)
        assert ok.status_code == 200 and ok.json()["status"] == "excused"
        entry = [e for e in world.store._audit if e.action == "attendance.excuse"][0]
        assert entry.actor == "Test Admin"

        assert client.post("/attendance/excused",
                           json={"personId": "p-layla", "date": D}).status_code == 409
        assert client.post("/attendance/excused",
                           json={"personId": "p-nobody", "date": D}).status_code == 404
        assert client.post("/attendance/excused",
                           json={"personId": "p-omar", "date": "2999-01-01"}).status_code == 422
        assert client.post("/attendance/excused",
                           json={"personId": "p-omar", "date": "2026-08-10"}).status_code == 409
        # The body takes no actor: extra fields are refused.
        assert client.post("/attendance/excused",
                           json={**body, "actor": "someone"}).status_code == 422

    def test_week_over_http(self, api, authed):
        application, world = api
        world.arrive("p-layla", D, 7, 40)
        r = authed(application).get("/attendance/week",
                                    params={"person": "p-layla", "date": D})
        assert r.status_code == 200
        assert r.json()[0]["status"] == "on_time" and r.json()[0]["date"] == D

    def test_the_group_figure_is_camel_cased(self, api, authed):
        application, _ = api
        row = authed(application).get("/groups").json()[0]
        assert "attendance30d" in row and "recordedDays" in row
        assert row["attendance30d"] is None

    def test_the_week_route_is_not_swallowed_by_a_parameter(self, api, authed):
        application, _ = api
        # No person given: the route itself answers (422), so nothing earlier
        # with a path parameter caught it.
        assert authed(application).get("/attendance/week").status_code == 422


# ---------------------------------------------------------------------------
# The sentences the console shows about what the engine really does
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def _en(key: str) -> str:
    """One English wording out of the console's catalogue, unescaped."""
    text = (REPO / "web" / "src" / "i18n" / "en.ts").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(f"'{key}':"):
            value = line.split(":", 1)[1].strip().rstrip(",")
            return value[1:-1].replace("\\'", "'")
    raise AssertionError(f"{key} is missing from en.ts")


class TestWhatTheConsoleSays:
    def test_the_removal_sentence_says_what_removal_really_does(self):
        """P14-FR-222: the three true things, and nothing the engine does not do.

        The engine deletes the face measurements and stops recognising at once
        (tested above), and keeps past attendance as recorded (tested above).
        If this wording drifts, one of those tests no longer backs it.
        """
        text = _en("people.removeSentence")
        assert "face measurements are deleted" in text
        assert "recognition stops at once, without a restart" in text
        assert "Past attendance stays as it was recorded" in text
        assert "{name}" in text

    def test_the_photo_note_says_only_measurements_are_kept(self):
        """P14-FR-237: true because the gallery holds vectors and no images
        (`test_a_committed_session_leaves_rows_only_in_person_and_face_embedding`)."""
        text = _en("enrol.photoNote")
        assert "Only the face measurements are kept" in text
        assert "never the photographs" in text
