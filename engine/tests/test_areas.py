"""Areas: the one table zones and stations share (spec 025, P14-FR-401..415).

What can lie here is the shape (a bow-tie has no honest "inside"), the hours
(one rule decides whether anything is watched) and the import (nothing the
owner already set up may disappear, and nothing may come back after a delete).
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timezone

import pytest

from vg import areas
from vg.areas import (
    Area, AreaError, AreaStore, FULL_FRAME, import_legacy, validate_polygon,
    watching_at,
)
from vg.config import HoursConfig, Schedule, ZoneConfig

SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

#: Saturday to Thursday, 07:30 to 15:00 - the shipped default.
WORKING = HoursConfig()


@pytest.fixture
def store(tmp_path):
    s = AreaStore(tmp_path / "areas.db")
    yield s
    s.close_db()


def make(store, **kw):
    base = dict(kind="zone", name="Server room", camera_id="cam-a",
                polygon=SQUARE, hours_mode="always", actor="mona", now=NOW)
    base.update(kw)
    return store.create(**base)


def at(weekday_date: str, hhmm: str) -> datetime:
    day = datetime.fromisoformat(weekday_date)
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m))


# 2026-11-07 is a Saturday, 2026-11-06 a Friday, 2026-11-09 a Monday.
SAT, FRI, MON = "2026-11-07", "2026-11-06", "2026-11-09"


# ---------------------------------------------------------------------------
# the shape
# ---------------------------------------------------------------------------

class TestPolygon:
    def test_a_valid_quad_and_the_full_frame_pass(self):
        assert validate_polygon(SQUARE) == tuple(SQUARE)
        assert validate_polygon(FULL_FRAME) == FULL_FRAME

    def test_fewer_than_three_points_is_refused(self):
        with pytest.raises(AreaError, match="at least 3 points"):
            validate_polygon([(0.1, 0.1), (0.9, 0.9)])

    @pytest.mark.parametrize("bad", [(1.2, 0.5), (-0.1, 0.5), (0.5, 1.0001),
                                      (float("nan"), 0.5)])
    def test_a_point_outside_the_frame_is_refused(self, bad):
        with pytest.raises(AreaError, match="outside the picture"):
            validate_polygon([(0.1, 0.1), (0.9, 0.1), bad])

    def test_a_bow_tie_is_refused_as_crossing_not_as_a_line(self):
        # Its signed area is zero, so a careless order of checks would call it
        # "almost a line" and send the operator after the wrong fault.
        with pytest.raises(AreaError, match="cross"):
            validate_polygon([(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])

    def test_a_sliver_is_refused_as_almost_a_line(self):
        with pytest.raises(AreaError, match="almost a line"):
            validate_polygon([(0.1, 0.5), (0.9, 0.5), (0.9, 0.5005)])

    def test_three_points_on_a_line_are_almost_a_line(self):
        with pytest.raises(AreaError, match="almost a line"):
            validate_polygon([(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)])

    def test_the_smallest_acceptable_area_is_a_named_constant(self):
        assert areas.MIN_AREA_FRACTION == 0.002

    def test_a_concave_shape_is_fine(self):
        l_shape = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.9, 0.5),
                   (0.9, 0.9), (0.1, 0.9)]
        assert validate_polygon(l_shape)


# ---------------------------------------------------------------------------
# the hours
# ---------------------------------------------------------------------------

def area(**kw) -> Area:
    base = dict(id="a", kind="zone", name="x", camera_id="cam-a",
                polygon=tuple(SQUARE), hours_mode="always")
    base.update(kw)
    return Area(**base)


class TestWatching:
    def test_always_watches_any_time(self):
        assert watching_at(area(), at(SAT, "03:00"), WORKING)

    def test_paused_and_deleted_never_watch(self):
        assert not watching_at(area(paused=True), at(SAT, "09:00"), WORKING)
        assert not watching_at(area(deleted_at=NOW), at(SAT, "09:00"), WORKING)

    def test_outside_working_is_the_complement_of_the_working_window(self):
        zone = area(hours_mode="outside_working")
        assert not watching_at(zone, at(SAT, "09:00"), WORKING), "a working day, in hours"
        assert watching_at(zone, at(SAT, "16:00"), WORKING), "after closing"
        assert watching_at(zone, at(SAT, "07:00"), WORKING), "before opening"
        # Friday is not a working day in the default Saturday-to-Thursday week.
        assert watching_at(zone, at(FRI, "09:00"), WORKING), "a day off"

    def test_outside_working_follows_a_settings_change_at_once(self):
        zone = area(hours_mode="outside_working")
        friday_week = HoursConfig(working_days=frozenset({4}))
        assert not watching_at(zone, at(FRI, "09:00"), friday_week)
        assert watching_at(zone, at(SAT, "09:00"), friday_week)

    def test_custom_zone_hours_may_cross_midnight(self):
        zone = area(hours_mode="custom", hours_from="16:00", hours_to="08:00")
        assert watching_at(zone, at(MON, "23:00"), WORKING)
        assert watching_at(zone, at(MON, "02:00"), WORKING)
        assert not watching_at(zone, at(MON, "12:00"), WORKING)

    def test_the_end_of_a_window_is_not_inside_it(self):
        zone = area(hours_mode="custom", hours_from="09:00", hours_to="10:00")
        assert watching_at(zone, at(MON, "09:00"), WORKING)
        assert not watching_at(zone, at(MON, "10:00"), WORKING)

    def test_a_station_is_watched_in_the_working_day_only(self):
        station = area(kind="station", hours_mode="working", limit_minutes=5)
        assert watching_at(station, at(SAT, "09:00"), WORKING)
        assert not watching_at(station, at(SAT, "16:00"), WORKING)
        assert not watching_at(station, at(FRI, "09:00"), WORKING)

    def test_a_custom_station_window(self):
        station = area(kind="station", hours_mode="custom", hours_from="10:00",
                       hours_to="12:00", limit_minutes=5)
        assert watching_at(station, at(MON, "11:00"), WORKING)
        assert not watching_at(station, at(MON, "12:30"), WORKING)


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

class TestStore:
    def test_create_list_get_roundtrip_in_fractions(self, store):
        zone = make(store)
        got = store.get(zone.id)
        assert got.polygon == tuple(SQUARE)
        assert got.created_by == "mona"
        assert [a.id for a in store.list()] == [zone.id]
        assert got.alert_after_seconds == 0.0, "a zone defaults to alert at once"

    def test_the_shape_rules_apply_on_save(self, store):
        with pytest.raises(AreaError):
            make(store, polygon=[(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])
        assert store.list() == [], "a refused area writes nothing"

    def test_empty_name_and_no_camera_are_refused(self, store):
        with pytest.raises(AreaError, match="name"):
            make(store, name="   ")
        with pytest.raises(AreaError, match="camera"):
            make(store, camera_id="")

    def test_custom_hours_need_both_times(self, store):
        with pytest.raises(AreaError, match="both"):
            make(store, hours_mode="custom", hours_from="16:00")

    def test_a_station_needs_a_limit_between_1_and_480(self, store):
        for bad in (None, 0, 481):
            with pytest.raises(AreaError, match="minutes"):
                make(store, kind="station", hours_mode="working",
                     limit_minutes=bad)
        ok = make(store, kind="station", hours_mode="working", limit_minutes=480)
        assert ok.limit_minutes == 480

    def test_a_station_custom_window_must_start_before_it_ends(self, store):
        with pytest.raises(AreaError, match="before they end"):
            make(store, kind="station", hours_mode="custom", hours_from="22:00",
                 hours_to="06:00", limit_minutes=5)

    def test_a_zone_cannot_carry_station_fields(self, store):
        zone = make(store, limit_minutes=5, assignee_id="p1")
        assert zone.limit_minutes is None and zone.assignee_id is None

    def test_update_rechecks_the_whole_area(self, store):
        zone = make(store)
        with pytest.raises(AreaError):
            store.update(zone.id, polygon=[(0.1, 0.1), (0.2, 0.2)])
        assert store.get(zone.id).polygon == tuple(SQUARE), "unchanged on refusal"
        changed = store.update(zone.id, name="Lab", alert_after_seconds=10)
        assert (changed.name, changed.alert_after_seconds) == ("Lab", 10)

    def test_update_cannot_move_the_kind_or_the_id(self, store):
        zone = make(store)
        with pytest.raises(ValueError):
            store.update(zone.id, kind="station")

    def test_pause_keeps_who_and_when_and_resume_clears_them(self, store):
        zone = make(store)
        paused = store.set_paused(zone.id, True, "omar", NOW)
        assert (paused.paused, paused.paused_by, paused.paused_at) == (
            True, "omar", NOW)
        resumed = store.set_paused(zone.id, False, "mona", NOW)
        assert (resumed.paused, resumed.paused_by, resumed.paused_at) == (
            False, None, None)

    def test_soft_delete_keeps_the_row_the_name_and_the_import_key(self, store):
        zone = make(store, import_key="camera:cam-a")
        store.soft_delete(zone.id, "mona", NOW)
        assert store.list() == []
        gone = store.list(include_deleted=True)[0]
        assert gone.deleted and gone.deleted_by == "mona"
        assert gone.name == "Server room"
        assert "camera:cam-a" in store.import_keys()

    def test_an_unknown_id_is_a_clear_error(self, store):
        with pytest.raises(areas.NoSuchArea):
            store.set_paused("nope", True, "mona")

    def test_list_filters_by_kind_and_camera(self, store):
        z = make(store)
        s = make(store, kind="station", name="Desk", hours_mode="working",
                 limit_minutes=5, camera_id="cam-b")
        assert [a.id for a in store.list(kind="zone")] == [z.id]
        assert [a.id for a in store.list(camera_id="cam-b")] == [s.id]

    def test_a_row_survives_reopening(self, tmp_path):
        first = AreaStore(tmp_path / "a.db")
        zone = make(first)
        first.close_db()
        second = AreaStore(tmp_path / "a.db")
        assert second.get(zone.id).name == "Server room"
        second.close_db()


# ---------------------------------------------------------------------------
# the one-time import (P14-FR-415, SC-405)
# ---------------------------------------------------------------------------

def yaml_zone(zone_id, schedule, *, dwell=2.0, enabled=True, camera="cam-laptop"):
    return ZoneConfig(
        id=zone_id, name=f"name of {zone_id}", camera_id=camera,
        polygon=((0.1, 0.18), (0.62, 0.18), (0.62, 0.8), (0.1, 0.8)),
        schedule=schedule, enabled=enabled, min_dwell_seconds=dwell)


DESK = yaml_zone("zone-desk", Schedule(mode="always"))
CHEM = yaml_zone("zone-chem", Schedule(
    mode="outside", days=("mon", "tue", "wed", "thu", "fri"),
    start=dtime(8, 0), end=dtime(16, 0)), dwell=3.0, camera="cam-rtsp-1")


def run_import(store, **kw):
    args = dict(
        cameras_restricted={"cam-a": True, "cam-b": False},
        scene_camera_ids=["cam-c"],
        camera_names={"cam-a": "Main entrance", "cam-b": "Back door",
                      "cam-c": "Car park", "cam-d": "Never used"},
        yaml_zones=[], hours=WORKING, now=NOW)
    args.update(kw)
    return import_legacy(store, **args)


class TestImport:
    def test_cameras_with_a_row_or_history_become_whole_frame_zones(self, store):
        assert run_import(store) == 3
        by_id = {a.id: a for a in store.list()}
        assert set(by_id) == {"cam-a", "cam-b", "cam-c"}, "cam-d was never used"
        a = by_id["cam-a"]
        assert (a.name, a.polygon, a.camera_id) == (
            "Main entrance", FULL_FRAME, "cam-a")
        assert a.hours_mode == "always" and a.paused is False
        assert by_id["cam-b"].paused is True, "the row said not restricted"
        assert by_id["cam-c"].paused is True, "history only: it was never on"

    def test_the_old_scene_rows_already_match_by_id(self, store):
        run_import(store)
        assert store.get("cam-a").id == "cam-a"

    def test_a_desk_polygon_imports_as_always(self, store):
        run_import(store, yaml_zones=[DESK])
        desk = store.get("zone-desk")
        assert desk.hours_mode == "always" and desk.import_note is None
        assert desk.polygon == DESK.polygon

    def test_a_weekday_lab_becomes_custom_and_says_what_changed(self, store):
        run_import(store, yaml_zones=[CHEM])
        chem = store.get("zone-chem")
        assert (chem.hours_mode, chem.hours_from, chem.hours_to) == (
            "custom", "16:00", "08:00")
        assert "Weekend" in chem.import_note
        assert "3 s" in chem.import_note and "2 s" in chem.import_note

    def test_outside_the_settings_hours_is_outside_working(self, store):
        same = yaml_zone("z", Schedule(
            mode="outside", days=("sat", "sun", "mon", "tue", "wed", "thu"),
            start=WORKING.start, end=WORKING.end))
        run_import(store, yaml_zones=[same])
        assert store.get("z").hours_mode == "outside_working"
        assert store.get("z").import_note is None

    def test_an_inside_window_becomes_custom(self, store):
        exam = yaml_zone("exam", Schedule(
            mode="inside", days=("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
            start=dtime(9, 0), end=dtime(12, 0)))
        run_import(store, yaml_zones=[exam])
        got = store.get("exam")
        assert (got.hours_mode, got.hours_from, got.hours_to) == (
            "custom", "09:00", "12:00")

    def test_a_disabled_yaml_zone_imports_paused(self, store):
        run_import(store, yaml_zones=[yaml_zone("off", Schedule(), enabled=False)])
        assert store.get("off").paused is True

    def test_the_import_is_idempotent(self, store):
        run_import(store, yaml_zones=[DESK, CHEM])
        before = len(store.list())
        assert run_import(store, yaml_zones=[DESK, CHEM]) == 0
        assert len(store.list()) == before

    def test_a_deleted_imported_zone_does_not_come_back(self, store):
        run_import(store, yaml_zones=[DESK])
        store.soft_delete("zone-desk", "mona", NOW)
        store.soft_delete("cam-a", "mona", NOW)
        assert run_import(store, yaml_zones=[DESK]) == 0
        assert store.list() == [] or all(a.id not in ("zone-desk", "cam-a")
                                         for a in store.list())

    def test_the_notify_defaults_are_what_the_rule_said(self, store):
        run_import(store, notify=(True, True))
        assert all(a.notify_in_app and a.notify_email for a in store.list())
