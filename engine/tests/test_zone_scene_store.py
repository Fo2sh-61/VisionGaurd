"""The scene log, keyed by zone (spec 025, T024).

What can lie here: an old database losing its history when the table gains
columns, an alert that goes twice or never, and a count that mixes two zones
on one camera.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vg.events import zones as zone_events
from vg.events.zones import SceneStore

START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)


@pytest.fixture
def scenes(tmp_path):
    store = SceneStore(tmp_path / "scenes.db")
    yield store
    store.close_db()


class Hook:
    def __init__(self):
        self.calls = []

    def __call__(self, scene_id, camera_id, started_at, continues, zone_id):
        self.calls.append((scene_id, camera_id, continues, zone_id))


class TestMigration:
    def test_an_old_table_gains_the_columns_and_keeps_its_rows(self, tmp_path):
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE zone_scene (
                id TEXT PRIMARY KEY, camera_id TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT,
                peak_people INTEGER NOT NULL DEFAULT 1, clip_path TEXT,
                clip_state TEXT NOT NULL DEFAULT 'none', clip_reason TEXT,
                end_reason TEXT);
            INSERT INTO zone_scene (id, camera_id, started_at)
                VALUES ('s1', 'cam-a', '2026-11-01T08:00:00+00:00');
        """)
        conn.commit()
        conn.close()

        store = SceneStore(path)
        try:
            scene = store.get("s1")
            assert scene.zone_id == "cam-a"          # backfilled to the camera
            assert scene.alerted is False
            cols = {r["name"] for r in store._conn.execute(
                "PRAGMA table_info(zone_scene)")}
            assert {"zone_id", "alerted"} <= cols
            indexes = {r["name"] for r in store._conn.execute(
                "PRAGMA index_list(zone_scene)")}
            assert "idx_zone_scene_zone" in indexes
        finally:
            store.close_db()

    def test_opening_twice_does_not_fail_or_duplicate(self, tmp_path):
        SceneStore(tmp_path / "a.db").close_db()
        again = SceneStore(tmp_path / "a.db")
        again.close_db()


class TestOpenAndAlert:
    def test_open_with_alert_now_calls_the_hook_and_marks_alerted(self, scenes):
        hook = Hook()
        scenes.on_open = hook
        sid = scenes.open("cam-a", START, zone_id="z1", alert_now=True)
        assert hook.calls == [(sid, "cam-a", False, "z1")]
        assert scenes.get(sid).alerted is True

    def test_open_without_alert_now_is_quiet(self, scenes):
        hook = Hook()
        scenes.on_open = hook
        sid = scenes.open("cam-a", START, zone_id="z1", alert_now=False)
        assert hook.calls == []
        assert scenes.get(sid).alerted is False

    def test_a_continuation_is_logged_but_never_marked_alerted(self, scenes):
        sid = scenes.open("cam-a", START, continues=True, zone_id="z1")
        assert scenes.get(sid).alerted is False

    def test_alert_marks_and_calls_the_hook_once_as_a_new_incident(self, scenes):
        hook = Hook()
        scenes.on_open = hook
        sid = scenes.open("cam-a", START, zone_id="z1", alert_now=False)
        assert scenes.alert(sid) is True
        assert scenes.alert(sid) is False             # second call: nothing
        assert hook.calls == [(sid, "cam-a", False, "z1")]
        assert scenes.get(sid).alerted is True

    def test_alert_on_an_unknown_scene_does_nothing(self, scenes):
        hook = Hook()
        scenes.on_open = hook
        assert scenes.alert("nope") is False
        assert hook.calls == []

    def test_a_failing_hook_does_not_lose_the_row(self, scenes):
        def boom(*a):
            raise RuntimeError("mail is down")
        scenes.on_open = boom
        sid = scenes.open("cam-a", START, zone_id="z1")
        assert scenes.get(sid) is not None

    def test_zone_id_defaults_to_the_camera(self, scenes):
        sid = scenes.open("cam-a", START)
        assert scenes.get(sid).zone_id == "cam-a"


class TestReading:
    def test_recent_filters_by_zone(self, scenes):
        a = scenes.open("cam-a", START, zone_id="z1")
        scenes.open("cam-a", START + timedelta(minutes=1), zone_id="z2")
        assert [s.id for s in scenes.recent(1, zone_id="z1")] == [a]
        assert len(scenes.recent(1)) == 2

    def test_counts_by_zone_separates_two_zones_on_one_camera(self, scenes):
        scenes.open("cam-a", START, zone_id="z1")
        scenes.open("cam-a", START + timedelta(minutes=1), zone_id="z1")
        scenes.open("cam-a", START + timedelta(minutes=2), zone_id="z2")
        counts = scenes.counts_since_by_zone(START - timedelta(hours=1))
        assert counts == {"z1": 2, "z2": 1}
        # The per-camera count still adds them up.
        assert scenes.counts_since(START - timedelta(hours=1)) == {"cam-a": 3}

    def test_hours_is_an_end_reason(self, scenes):
        assert "hours" in zone_events.END_REASONS
        sid = scenes.open("cam-a", START, zone_id="z1")
        scenes.close(sid, START + timedelta(seconds=30), "hours")
        assert scenes.get(sid).end_reason == "hours"

    def test_clips_are_still_kept_per_camera_across_zones(self, scenes, tmp_path):
        paths = []
        for i, zone in enumerate(["z1", "z2", "z1", "z2"]):
            sid = scenes.open("cam-a", START + timedelta(minutes=i), zone_id=zone)
            scenes.start_clip(sid)
            clip = tmp_path / f"{i}.mp4"
            clip.write_bytes(b"x")
            scenes.attach_clip(sid, clip)
            paths.append((sid, clip))
        kept = [s for s in scenes.recent(1) if s.clip_state == "saved"]
        assert len(kept) == zone_events.CLIPS_KEPT_PER_CAMERA
        # The oldest, whichever zone it was in, is the one replaced.
        assert scenes.get(paths[0][0]).clip_state == "replaced"
        assert not paths[0][1].exists()
