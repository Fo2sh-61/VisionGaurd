"""Falls: somebody went down on a camera, from when to when, and what happened.

An entry is one fall, not one detection. The model decides a person fell once;
the entry then stays open for as long as that person stays down, and closes
when they get up or leave the camera. `features/falls.py` owns those rules;
this file only stores them.

Five decisions worth stating:

**Rows are never deleted.** Not by retention, not by "not a fall", not ever.
Somebody who went down and got up again is still something that happened on
the site, and a page that hides its own false alarms cannot be audited. Only
videos go, and only with age: `expire()` marks a row `expired` and then
unlinks its file — mark, then unlink, the order `events/weapons.py` gives the
reason for.

**Down is not the same as alerted.** `started_at` is when the person went
down. `alerted_at` is when they had been down long enough to count — set by
the worker, once, and only if they were still down then. An entry with no
`alerted_at` is a fall the person got up from by themselves, and it is listed
as exactly that: it never raised anything.

**Nothing is sent to anyone.** There is no alert hook here, unlike knives and
zones. The owner's design is explicit: a fall shows on the console at once,
and pressing a button is optional. That is a decision about this feature, not
an omission.

**Two buttons, both optional, both signed.** "I'm on my way" records who is
going, and can be taken back — the same person may press it by mistake, and
an undo that leaves the name behind would claim somebody went who did not.
"Not a fall" is recorded once, by one person, and never moves back, for the
reason `WeaponSceneStore.review` gives.

**Peak, not last.** The confidence an entry shows is the highest the model
gave while the person was down.

Nothing here knows who anybody is. The model sees a body on the floor; naming
the body is recognition's job and deliberately not wired to it.
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
CREATE TABLE IF NOT EXISTS fall_scene (
    id              TEXT PRIMARY KEY,
    camera_id       TEXT NOT NULL,
    started_at      TEXT NOT NULL,          -- ISO-8601 UTC: went down
    detected_at     TEXT NOT NULL,          -- the model decided it was a fall
    alerted_at      TEXT,                   -- down long enough to count; NULL = never
    ended_at        TEXT,                   -- NULL while still down
    end_reason      TEXT,
    peak_confidence REAL NOT NULL DEFAULT 0.0,
    model_version   TEXT NOT NULL DEFAULT '',
    box_x           REAL,                   -- where, as fractions of the frame
    box_y           REAL,
    box_w           REAL,
    box_h           REAL,
    clip_path       TEXT,
    clip_state      TEXT NOT NULL DEFAULT 'none',
    clip_reason     TEXT,
    responder       TEXT,                   -- "I'm on my way"
    responded_at    TEXT,
    verdict         TEXT NOT NULL DEFAULT 'none',
    reviewed_by     TEXT,
    reviewed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_fall_scene_camera
    ON fall_scene(camera_id, started_at DESC);
"""

#: Why an entry ended. Stored so "left the camera" never reads as "got up".
END_REASONS = ("got_up", "left_view", "switched_off", "shutdown")

#: What happened to the video. `saved` is the only one with a playable file.
CLIP_STATES = ("none", "recording", "saved", "expired", "failed")

#: What an entry says once its video has been removed by age.
EXPIRED_REASON = "Video no longer kept."

#: What a verdict can be. `not_a_fall` never moves back.
VERDICTS = ("none", "not_a_fall")


@dataclass(frozen=True)
class FallScene:
    """One fall on one camera."""

    id: str
    camera_id: str
    started_at: datetime
    detected_at: datetime
    alerted_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None
    peak_confidence: float = 0.0
    model_version: str = ""
    box: tuple[float, float, float, float] | None = None
    clip_path: Path | None = None
    clip_state: str = "none"
    clip_reason: str | None = None
    responder: str | None = None
    responded_at: datetime | None = None
    verdict: str = "none"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self.ended_at is None

    @property
    def alerted(self) -> bool:
        return self.alerted_at is not None

    @property
    def seconds(self) -> float:
        """How long the person was down, so far or in total."""
        end = self.ended_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def playable(self) -> bool:
        return self.clip_state == "saved" and self.clip_path is not None


class FallSceneStore:
    """Every fall, running or finished."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- writing: the worker ------------------------------------------------

    def open(
        self,
        camera_id: str,
        started_at: datetime,
        detected_at: datetime,
        confidence: float,
        model_version: str,
        box: tuple[float, float, float, float] | None = None,
    ) -> str:
        """Start an entry. Returns its id.

        `started_at` is when the person went down — the first frame the model
        stopped calling them upright — not the moment it was sure. Somebody
        watching the page wants to know how long they have been on the floor.
        """
        scene_id = uuid.uuid4().hex
        x, y, w, h = box if box is not None else (None, None, None, None)
        with self._lock:
            self._conn.execute(
                "INSERT INTO fall_scene (id, camera_id, started_at, detected_at, "
                "peak_confidence, model_version, box_x, box_y, box_w, box_h, "
                "clip_state, verdict) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', 'none')",
                (scene_id, camera_id, _iso(started_at), _iso(detected_at),
                 float(confidence), model_version, x, y, w, h),
            )
            self._conn.commit()
        return scene_id

    def note_confidence(self, scene_id: str, confidence: float) -> None:
        """Raise the peak if this frame was surer. Never lowers it."""
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET peak_confidence = ? "
                "WHERE id = ? AND peak_confidence < ?",
                (float(confidence), scene_id, float(confidence)),
            )
            self._conn.commit()

    def note_box(self, scene_id: str, box: tuple[float, float, float, float]) -> None:
        """Where the person is lying now. Fractions of the frame."""
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET box_x = ?, box_y = ?, box_w = ?, box_h = ? "
                "WHERE id = ?",
                (*[float(v) for v in box], scene_id),
            )
            self._conn.commit()

    def alert(self, scene_id: str, at: datetime) -> bool:
        """The person has been down long enough to count. Once only."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE fall_scene SET alerted_at = ? "
                "WHERE id = ? AND alerted_at IS NULL AND ended_at IS NULL",
                (_iso(at), scene_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def close(self, scene_id: str, ended_at: datetime, end_reason: str) -> None:
        """End an entry. Closing an already-closed one changes nothing."""
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET ended_at = ?, end_reason = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (_iso(ended_at), end_reason, scene_id),
            )
            self._conn.commit()

    def start_clip(self, scene_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET clip_state = 'recording', clip_reason = NULL "
                "WHERE id = ?",
                (scene_id,),
            )
            self._conn.commit()

    def attach_clip(self, scene_id: str, path: Path | str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET clip_state = 'saved', clip_path = ?, "
                "clip_reason = NULL WHERE id = ?",
                (str(Path(path)), scene_id),
            )
            self._conn.commit()

    def fail_clip(self, scene_id: str, reason: str) -> None:
        """No playable file, and why — in words an operator can act on."""
        with self._lock:
            self._conn.execute(
                "UPDATE fall_scene SET clip_state = 'failed', clip_path = NULL, "
                "clip_reason = ? WHERE id = ?",
                (reason, scene_id),
            )
            self._conn.commit()

    # -- writing: a person at the console -----------------------------------

    def respond(self, scene_id: str, responder: str, at: datetime) -> bool:
        """"I'm on my way". True only if this call recorded it.

        Only while the person is still down — going to somebody who already
        got up is not something the history should be able to say — and only
        if nobody else is already going, so a second press cannot quietly
        replace the first person's name.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE fall_scene SET responder = ?, responded_at = ? "
                "WHERE id = ? AND ended_at IS NULL AND responder IS NULL",
                (responder, _iso(at), scene_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def undo_response(self, scene_id: str) -> str | None:
        """Take back "I'm on my way". Returns whose name was removed, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT responder FROM fall_scene WHERE id = ?", (scene_id,)
            ).fetchone()
            if row is None or row["responder"] is None:
                return None
            self._conn.execute(
                "UPDATE fall_scene SET responder = NULL, responded_at = NULL "
                "WHERE id = ?",
                (scene_id,),
            )
            self._conn.commit()
        return row["responder"]

    def mark_not_a_fall(self, scene_id: str, reviewer: str, at: datetime) -> bool:
        """"Not a fall". True only if this call made it; it never moves back.

        `WHERE verdict = 'none'` is the whole guarantee, decided by SQLite
        rather than a read-then-write here, so two people pressing at once
        change one row once.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE fall_scene SET verdict = 'not_a_fall', reviewed_by = ?, "
                "reviewed_at = ? WHERE id = ? AND verdict = 'none'",
                (reviewer, _iso(at), scene_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    # -- upkeep -------------------------------------------------------------

    def close_orphans(self, reason: str = "shutdown") -> int:
        """Close entries a crash left open. Returns how many.

        Without it a fall from a killed process shows as somebody still on
        the floor, for ever.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE fall_scene SET ended_at = COALESCE(ended_at, started_at), "
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
            log.info("closed %d fall(s) left open by a previous run", cursor.rowcount)
        return cursor.rowcount

    def expire(self, older_than: datetime) -> int:
        """Remove videos of falls that started before `older_than`.

        Rows are never touched beyond their clip state; mark, then unlink.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, clip_path FROM fall_scene "
                "WHERE clip_state = 'saved' AND started_at < ? "
                "ORDER BY started_at ASC",
                (_iso(older_than),),
            ).fetchall()
            if not rows:
                return 0
            marks = ",".join("?" * len(rows))
            self._conn.execute(
                "UPDATE fall_scene SET clip_state = 'expired', "
                f"clip_path = NULL, clip_reason = ? WHERE id IN ({marks})",
                (EXPIRED_REASON, *[row["id"] for row in rows]),
            )
            self._conn.commit()

        for row in rows:
            _unlink(row["clip_path"])
        log.info("expired %d fall clip(s) older than %s", len(rows), older_than)
        return len(rows)

    # -- reading ------------------------------------------------------------

    def get(self, scene_id: str) -> FallScene | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fall_scene WHERE id = ?", (scene_id,)
            ).fetchone()
        return _to_scene(row) if row else None

    def recent(
        self,
        since: datetime | None,
        until: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[FallScene]:
        """Falls that started within the window, newest first.

        Either bound may be `None`, meaning open-ended. Nothing is filtered
        out: an entry marked "not a fall" is listed, and says so.
        """
        query = "SELECT * FROM fall_scene WHERE 1 = 1"
        params: list = []
        if since is not None:
            query += " AND started_at >= ?"
            params.append(_iso(since))
        if until is not None:
            query += " AND started_at < ?"
            params.append(_iso(until))
        if camera_id:
            query += " AND camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY started_at DESC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_to_scene(r) for r in rows]

    def running(self) -> list[FallScene]:
        """Everybody down right now, on any camera, longest down first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fall_scene WHERE ended_at IS NULL "
                "ORDER BY started_at ASC").fetchall()
        return [_to_scene(r) for r in rows]

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


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
        # The row already says the video is gone. A locked file costs disk
        # space, which is not worth failing the sweep over.
        log.warning("could not delete expired fall clip %s: %s", path, exc)


def _to_scene(row: sqlite3.Row) -> FallScene:
    box = None
    if row["box_x"] is not None:
        box = (float(row["box_x"]), float(row["box_y"]),
               float(row["box_w"]), float(row["box_h"]))
    return FallScene(
        id=row["id"],
        camera_id=row["camera_id"],
        started_at=_parse(row["started_at"]),
        detected_at=_parse(row["detected_at"]),
        alerted_at=_parse(row["alerted_at"]),
        ended_at=_parse(row["ended_at"]),
        end_reason=row["end_reason"],
        peak_confidence=float(row["peak_confidence"]),
        model_version=row["model_version"],
        box=box,
        clip_path=Path(row["clip_path"]) if row["clip_path"] else None,
        clip_state=row["clip_state"],
        clip_reason=row["clip_reason"],
        responder=row["responder"],
        responded_at=_parse(row["responded_at"]),
        verdict=row["verdict"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=_parse(row["reviewed_at"]),
    )
