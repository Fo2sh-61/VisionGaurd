"""Scenes: somebody was on a restricted camera, from when to when.

A scene is one visit, not one detection. A person standing in a doorway at 5 fps
is hundreds of detections and exactly one thing that happened, so the row here
opens when they arrive and closes when they have been gone for a full second.
The worker in `features/zones.py` owns that rule; this file only stores it.

Three decisions worth stating:

**Rows are never deleted.** Only files are. Each camera keeps its newest few
clips (`CLIPS_KEPT_PER_CAMERA`); a new one pushes the oldest past the cap, its
file is removed and its row is marked `replaced`.

A replaced row stops being *listed* — the console's log is a list of what can
be watched, and an entry with nothing behind it is clutter. It does not stop
*existing*: the time, the peak count and the duration stay here, because a
detection that happened is evidence even once the video of it is gone, and
`recent()` still returns it when asked. Deleting the row would be the thing
that turns this from a log into a rumour.

**Mark, then unlink.** `attach_clip` writes `replaced` before deleting the file
it names. A crash between the two leaves a row that honestly says the clip is
gone; the other order leaves a row pointing at a file that is not there, which
is the same lie as a fake save.

**Peak, not last.** An entry says how many people were seen at the busiest
moment of the scene. The final frame's count is 0 for every scene that ended,
which would read as "nobody was there".

Nothing here knows who anybody is. This feature sees bodies; naming them is
recognition's job and deliberately not wired to it.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from vg import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS zone_scene (
    id           TEXT PRIMARY KEY,
    camera_id    TEXT NOT NULL,
    started_at   TEXT NOT NULL,          -- ISO-8601 UTC, from the frame
    ended_at     TEXT,                   -- NULL while the scene is running
    peak_people  INTEGER NOT NULL DEFAULT 1,
    clip_path    TEXT,
    clip_state   TEXT NOT NULL DEFAULT 'none',
    clip_reason  TEXT,
    end_reason   TEXT,
    zone_id      TEXT,                   -- the area it happened in (spec 025)
    alerted      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_zone_scene_camera
    ON zone_scene(camera_id, started_at DESC);
"""

#: Columns spec 025 added. An existing database gets them by ALTER, then every
#: old row is given the zone it always was: the camera. The index on them can
#: only be made once they exist, so it is made here and not in `SCHEMA`.
_ADDED_COLUMNS = (
    ("zone_id", "TEXT"),
    ("alerted", "INTEGER NOT NULL DEFAULT 0"),
)

#: Why a scene ended. Stored so an entry cut at the limit does not read like a
#: person who left. `hours` is the watched hours ending while somebody was
#: still there.
END_REASONS = ("nobody", "limit", "switched_off", "shutdown", "hours")

#: What happened to the clip. `saved` is the only one with a playable file.
CLIP_STATES = ("none", "recording", "saved", "replaced", "failed")

#: How many saved clips each camera keeps. When a new one saves, whatever
#: this leaves over is replaced, oldest first. Per camera, so a busy doorway
#: never costs a quiet corridor its evidence. Owner decision 2026-08-21 (was
#: one); the real target — roughly a working day of clips, sized to the
#: deployment machine — stays an installation decision.
CLIPS_KEPT_PER_CAMERA = 3

#: What a replaced entry says. One sentence, in the operator's words, because
#: it is rendered next to a disabled button and has to explain it on its own.
REPLACED_REASON = (
    "The clip is no longer kept — a newer scene on this camera replaced it."
)


@dataclass(frozen=True)
class Scene:
    """One visit to a restricted camera."""

    id: str
    camera_id: str
    started_at: datetime
    ended_at: datetime | None = None
    peak_people: int = 1
    clip_path: Path | None = None
    clip_state: str = "none"
    clip_reason: str | None = None
    end_reason: str | None = None
    #: The area this happened in. An old row's zone is its camera.
    zone_id: str | None = None
    #: Whether this entry's alert was raised (spec 025 alert-after-N).
    alerted: bool = False

    @property
    def running(self) -> bool:
        return self.ended_at is None

    @property
    def seconds(self) -> float:
        """How long the scene lasted, so far or in total.

        A running scene is measured against now, which is what the page shows
        while somebody is still standing there.
        """
        end = self.ended_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def playable(self) -> bool:
        return self.clip_state == "saved" and self.clip_path is not None


class SceneStore:
    """Every scene, running or finished."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()
        #: Called after a scene's row is committed, with
        #: `(scene_id, camera_id, started_at, continues, zone_id)`. Alert
        #: delivery (spec 013) sets it; it must only hand the event over.
        self.on_open = None

    def _migrate(self) -> None:
        """Bring a database written before spec 025 up to date, once."""
        have = {row["name"] for row in
                self._conn.execute("PRAGMA table_info(zone_scene)").fetchall()}
        for name, kind in _ADDED_COLUMNS:
            if name not in have:
                self._conn.execute(
                    f"ALTER TABLE zone_scene ADD COLUMN {name} {kind}")
        # Every scene before areas existed happened in "the camera", and an
        # imported whole-camera zone takes the camera's id, so history and
        # clips follow with no copying.
        self._conn.execute(
            "UPDATE zone_scene SET zone_id = camera_id WHERE zone_id IS NULL")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_zone_scene_zone "
            "ON zone_scene(zone_id, started_at DESC)")

    # -- writing ------------------------------------------------------------

    def open(self, camera_id: str, started_at: datetime,
             continues: bool = False, zone_id: str | None = None,
             alert_now: bool = True) -> str:
        """Start a scene. Returns its id.

        `continues` marks the scene the worker opens at once when it cuts a
        long visit at the two-minute limit: the same person, still there. A
        new row, not a new alert.

        `zone_id` is the area it happened in; left out, it is the camera's id,
        which is exactly what an imported whole-camera zone is called.

        `alert_now` is whether the hook runs at all. A zone told to alert only
        after N seconds opens its scene quietly and calls `alert()` later, if
        the visit lasts. `alerted` is set here only for an alert that really
        goes: a continuation is logged but never alerted.
        """
        scene_id = uuid.uuid4().hex
        zone_id = zone_id or camera_id
        alerts = 1 if (alert_now and not continues) else 0
        with self._lock:
            self._conn.execute(
                "INSERT INTO zone_scene (id, camera_id, started_at, peak_people, "
                "clip_state, zone_id, alerted) VALUES (?, ?, ?, 1, 'none', ?, ?)",
                (scene_id, camera_id, _iso(started_at), zone_id, alerts),
            )
            self._conn.commit()
        if alert_now:
            self._hand_over(scene_id, camera_id, started_at, continues, zone_id)
        return scene_id

    def alert(self, scene_id: str) -> bool:
        """The visit has lasted long enough: raise its alert, once.

        Marks the entry `alerted` and runs the same hook `open` would have, as
        a new incident. Returns False, doing nothing, when the scene is
        unknown or was already alerted, so a worker may call it on every frame
        without sending twice.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT camera_id, started_at, zone_id FROM zone_scene "
                "WHERE id = ? AND alerted = 0", (scene_id,)).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "UPDATE zone_scene SET alerted = 1 WHERE id = ?", (scene_id,))
            self._conn.commit()
        self._hand_over(scene_id, row["camera_id"], _parse(row["started_at"]),
                        False, row["zone_id"] or row["camera_id"])
        return True

    def _hand_over(self, scene_id: str, camera_id: str, started_at: datetime,
                   continues: bool, zone_id: str) -> None:
        # After the commit: the row is the event, and a failing hook costs a
        # message, never the record that somebody was there.
        if self.on_open is None:
            return
        try:
            self.on_open(scene_id, camera_id, started_at, continues, zone_id)
        except Exception:
            log.exception("zone scene %s: the alert hook failed", scene_id[:8])

    def note_people(self, scene_id: str, count: int) -> None:
        """Raise the peak if this frame was busier. Never lowers it."""
        with self._lock:
            self._conn.execute(
                "UPDATE zone_scene SET peak_people = ? "
                "WHERE id = ? AND peak_people < ?",
                (count, scene_id, count),
            )
            self._conn.commit()

    def close(self, scene_id: str, ended_at: datetime, end_reason: str) -> None:
        """End a scene. Closing an already-closed one changes nothing."""
        with self._lock:
            self._conn.execute(
                "UPDATE zone_scene SET ended_at = ?, end_reason = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (_iso(ended_at), end_reason, scene_id),
            )
            self._conn.commit()

    def start_clip(self, scene_id: str) -> None:
        """The recorder accepted; a file is being written."""
        with self._lock:
            self._conn.execute(
                "UPDATE zone_scene SET clip_state = 'recording', clip_reason = NULL "
                "WHERE id = ?",
                (scene_id,),
            )
            self._conn.commit()

    def attach_clip(self, scene_id: str, path: Path | str) -> None:
        """This scene has a saved file; the camera's oldest beyond the cap goes.

        Each camera keeps its `CLIPS_KEPT_PER_CAMERA` newest saved clips —
        this one plus the two before it. Whatever that pushes past the cap is
        marked `replaced` **before** its file is unlinked: a crash in between
        then leaves a row that says the clip is gone, which is true, rather
        than one that offers a file that is not there.
        """
        path = Path(path)
        with self._lock:
            row = self._conn.execute(
                "SELECT camera_id FROM zone_scene WHERE id = ?", (scene_id,)
            ).fetchone()
            if row is None:
                log.warning("attach_clip for unknown scene %s", scene_id)
                return
            camera_id = row["camera_id"]

            # The other saved rows for this camera, newest first. The first
            # (cap - 1) stay; this scene fills the last slot.
            superseded = self._conn.execute(
                "SELECT id, clip_path FROM zone_scene "
                "WHERE camera_id = ? AND clip_state = 'saved' AND id != ? "
                "ORDER BY started_at DESC LIMIT -1 OFFSET ?",
                (camera_id, scene_id, CLIPS_KEPT_PER_CAMERA - 1),
            ).fetchall()

            if superseded:
                marks = ",".join("?" * len(superseded))
                self._conn.execute(
                    "UPDATE zone_scene SET clip_state = 'replaced', "
                    f"clip_path = NULL, clip_reason = ? WHERE id IN ({marks})",
                    (REPLACED_REASON, *[old["id"] for old in superseded]),
                )
            self._conn.execute(
                "UPDATE zone_scene SET clip_state = 'saved', clip_path = ?, "
                "clip_reason = NULL WHERE id = ?",
                (str(path), scene_id),
            )
            self._conn.commit()

        # Outside the lock and after the commit: the rows already tell the
        # truth, so a failure to delete costs disk, not honesty.
        for old in superseded:
            _unlink(old["clip_path"])

    def fail_clip(self, scene_id: str, reason: str) -> None:
        """No playable file, and why — in words an operator can act on."""
        with self._lock:
            self._conn.execute(
                "UPDATE zone_scene SET clip_state = 'failed', clip_path = NULL, "
                "clip_reason = ? WHERE id = ?",
                (reason, scene_id),
            )
            self._conn.commit()

    def close_orphans(self, reason: str = "shutdown") -> int:
        """Close scenes a crash left open. Returns how many.

        Called on start. Without it a scene from a killed process shows as
        still running forever, and the page reports somebody standing in a
        restricted area who left days ago.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE zone_scene SET ended_at = COALESCE(ended_at, started_at), "
                "end_reason = ?, "
                "clip_state = CASE WHEN clip_state = 'recording' THEN 'failed' "
                "                  ELSE clip_state END, "
                "clip_reason = CASE WHEN clip_state = 'recording' "
                "                   THEN 'The engine stopped while this was recording, "
                "so no clip was saved.' ELSE clip_reason END "
                "WHERE ended_at IS NULL",
                (reason,),
            )
            self._conn.commit()
        if cursor.rowcount:
            log.info("closed %d scene(s) left open by a previous run", cursor.rowcount)
        return cursor.rowcount

    # -- reading ------------------------------------------------------------

    def get(self, scene_id: str) -> Scene | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM zone_scene WHERE id = ?", (scene_id,)
            ).fetchone()
        return _to_scene(row) if row else None

    def recent(
        self,
        since_days: int,
        camera_id: str | None = None,
        include_replaced: bool = True,
        zone_id: str | None = None,
    ) -> list[Scene]:
        """Scenes that started within the window, newest first.

        `include_replaced=False` leaves out the ones whose clip a newer scene
        has already pushed out. The console's log no longer asks for that
        (spec 025: the log is complete and says "No clip kept"), but the filter
        stays for anyone who wants only what can be watched.

        It is a filter and never a delete: the default returns everything, so
        the rows are still here to be read, counted and audited. Losing the
        record that somebody entered a restricted area is a different and much
        worse thing than not listing it.
        """
        query = "SELECT * FROM zone_scene WHERE started_at >= ?"
        params: list = [_iso(_days_ago(since_days))]
        if camera_id:
            query += " AND camera_id = ?"
            params.append(camera_id)
        if zone_id:
            query += " AND zone_id = ?"
            params.append(zone_id)
        if not include_replaced:
            query += " AND clip_state != 'replaced'"
        query += " ORDER BY started_at DESC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_to_scene(r) for r in rows]

    def counts_since(self, since: datetime) -> dict[str, int]:
        """Scenes per camera since an instant — the page's "today" numbers.

        One query for the whole roster rather than one per camera. The camera
        list is polled continuously and a site has 208 of them; asking 208
        times for a number the index can group in one pass is how a cheap page
        becomes an expensive one.

        Cameras with no scenes are absent, so callers default to 0.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT camera_id, COUNT(*) AS n FROM zone_scene "
                "WHERE started_at >= ? GROUP BY camera_id",
                (_iso(since),),
            ).fetchall()
        return {row["camera_id"]: int(row["n"]) for row in rows}

    def counts_since_by_zone(self, since: datetime) -> dict[str, int]:
        """Scenes per area since an instant. Areas with none are absent."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT zone_id, COUNT(*) AS n FROM zone_scene "
                "WHERE started_at >= ? GROUP BY zone_id",
                (_iso(since),),
            ).fetchall()
        return {row["zone_id"]: int(row["n"]) for row in rows}

    def camera_ids(self) -> list[str]:
        """Every camera with a legacy (pre-025) scene: the import reads this.

        Legacy rows are the whole-camera ones: no zone, or a zone named after
        the camera. A drawn zone's scenes carry its own id and must not make
        the import invent a zone for their camera.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT camera_id FROM zone_scene "
                "WHERE zone_id IS NULL OR zone_id = camera_id "
                "ORDER BY camera_id"
            ).fetchall()
        return [row["camera_id"] for row in rows]

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _days_ago(days: int) -> datetime:
    from datetime import timedelta

    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        # The row already says the clip is gone. A locked file costs disk
        # space, which is not worth failing a scene close over.
        log.warning("could not delete replaced clip %s: %s", path, exc)


def _to_scene(row: sqlite3.Row) -> Scene:
    return Scene(
        id=row["id"],
        camera_id=row["camera_id"],
        started_at=_parse(row["started_at"]),
        ended_at=_parse(row["ended_at"]),
        peak_people=row["peak_people"],
        clip_path=Path(row["clip_path"]) if row["clip_path"] else None,
        clip_state=row["clip_state"],
        clip_reason=row["clip_reason"],
        end_reason=row["end_reason"],
        zone_id=row["zone_id"] or row["camera_id"],
        alerted=bool(row["alerted"]),
    )
