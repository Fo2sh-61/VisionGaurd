"""Knife scenes: a knife was seen on a camera, from when to when.

A scene is one incident, not one detection. A knife held in a corridor at 2 Hz
is dozens of detections and exactly one thing that happened, so the row here
opens at the **first** sighting of the run that confirmed it and closes when the
knife has been gone for a couple of seconds. `features/weapons.py` owns
that rule; this file only stores it.

Four decisions worth stating:

**Rows are never deleted.** Not by retention, not by a dismissal, not ever. A
knife that was seen and turned out to be a phone is still something the school
looked at, and the record of the looking is the point. Only files go, and only
with age: `expire()` marks a row `expired` and then unlinks its video. There is
no per-camera cap here — `zone_scene` keeps three clips per camera because a
busy doorway would otherwise bury a quiet one, but the second knife of the day
matters exactly as much as the first.

**Mark, then unlink.** `expire` writes `expired` and clears `clip_path` before
deleting the file it named. A crash between the two leaves a row that honestly
says the video is gone; the other order leaves a row offering a file that is not
there, which is the same lie as a fake save.

**Peak, not last.** An entry says the highest confidence seen during the scene.
The final frame's confidence is 0 for every scene that ended, which would read
as "the model was never sure".

**A verdict never moves back.** `pending` becomes `confirmed` or `dismissed`
once, by one person, and stays. `review()` returns False on a second attempt so
the endpoint can say so rather than silently overwriting the first reviewer.

Nothing here knows who anybody is. This feature sees a knife on a body; naming
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
CREATE TABLE IF NOT EXISTS weapon_scene (
    id              TEXT PRIMARY KEY,
    camera_id       TEXT NOT NULL,
    started_at      TEXT NOT NULL,          -- ISO-8601 UTC, the FIRST sighting
    ended_at        TEXT,                   -- NULL while the knife is in view
    peak_confidence REAL NOT NULL DEFAULT 0.0,
    model_version   TEXT NOT NULL DEFAULT '',
    clip_path       TEXT,
    clip_state      TEXT NOT NULL DEFAULT 'none',
    clip_reason     TEXT,
    end_reason      TEXT,
    verdict         TEXT NOT NULL DEFAULT 'pending',
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    review_reason   TEXT
);

CREATE INDEX IF NOT EXISTS idx_weapon_scene_camera
    ON weapon_scene(camera_id, started_at DESC);
"""

#: Why a scene ended. Stored so an entry cut at the two-minute limit does not
#: read like a knife that was put away.
END_REASONS = ("gone", "limit", "shutdown")

#: What happened to the video. `saved` is the only one with a playable file.
CLIP_STATES = ("none", "recording", "saved", "expired", "failed")

#: What an entry says once its video has been removed by age. One sentence,
#: in the operator's words, because it is rendered where the button was and
#: has to explain itself with nothing around it. The number is deliberately
#: absent: this store is not told the retention period, the caller is.
EXPIRED_REASON = "Video no longer kept."

#: What a verdict can be. Nothing moves back out of the last two.
VERDICTS = ("pending", "confirmed", "dismissed")


@dataclass(frozen=True)
class WeaponScene:
    """One knife incident on one camera."""

    id: str
    camera_id: str
    started_at: datetime
    ended_at: datetime | None = None
    peak_confidence: float = 0.0
    model_version: str = ""
    clip_path: Path | None = None
    clip_state: str = "none"
    clip_reason: str | None = None
    end_reason: str | None = None
    verdict: str = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None

    @property
    def running(self) -> bool:
        return self.ended_at is None

    @property
    def seconds(self) -> float:
        """How long the scene lasted, so far or in total.

        A running scene is measured against now, which is what the page shows
        while the knife is still in view.
        """
        end = self.ended_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def playable(self) -> bool:
        return self.clip_state == "saved" and self.clip_path is not None


class WeaponSceneStore:
    """Every knife scene, running or finished, reviewed or not."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- writing ------------------------------------------------------------

    def open(
        self,
        camera_id: str,
        started_at: datetime,
        confidence: float,
        model_version: str,
    ) -> str:
        """Start a scene. Returns its id.

        `started_at` is the first sighting of the confirming run, not the
        moment the third sighting tipped it over. An operator watching the
        clip should see the knife arrive, not already be there.
        """
        scene_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO weapon_scene (id, camera_id, started_at, "
                "peak_confidence, model_version, clip_state, verdict) "
                "VALUES (?, ?, ?, ?, ?, 'none', 'pending')",
                (
                    scene_id,
                    camera_id,
                    _iso(started_at),
                    float(confidence),
                    model_version,
                ),
            )
            self._conn.commit()
        return scene_id

    def note_confidence(self, scene_id: str, confidence: float) -> None:
        """Raise the peak if this frame was surer. Never lowers it."""
        with self._lock:
            self._conn.execute(
                "UPDATE weapon_scene SET peak_confidence = ? "
                "WHERE id = ? AND peak_confidence < ?",
                (float(confidence), scene_id, float(confidence)),
            )
            self._conn.commit()

    def close(self, scene_id: str, ended_at: datetime, end_reason: str) -> None:
        """End a scene. Closing an already-closed one changes nothing."""
        with self._lock:
            self._conn.execute(
                "UPDATE weapon_scene SET ended_at = ?, end_reason = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (_iso(ended_at), end_reason, scene_id),
            )
            self._conn.commit()

    def start_clip(self, scene_id: str) -> None:
        """The recorder accepted; a file is being written."""
        with self._lock:
            self._conn.execute(
                "UPDATE weapon_scene SET clip_state = 'recording', "
                "clip_reason = NULL WHERE id = ?",
                (scene_id,),
            )
            self._conn.commit()

    def attach_clip(self, scene_id: str, path: Path | str) -> None:
        """This scene has a saved file.

        Nothing is superseded. `zone_scene` deletes a camera's oldest clip when
        a new one saves, because a doorway that triggers all day would otherwise
        push every other camera's evidence off the disk. Knives are rare and
        each one is its own incident, so the only thing that removes a knife
        video is age — `expire()`, called by the caller that knows the retention
        period.
        """
        path = Path(path)
        with self._lock:
            self._conn.execute(
                "UPDATE weapon_scene SET clip_state = 'saved', clip_path = ?, "
                "clip_reason = NULL WHERE id = ?",
                (str(path), scene_id),
            )
            self._conn.commit()

    def fail_clip(self, scene_id: str, reason: str) -> None:
        """No playable file, and why — in words an operator can act on."""
        with self._lock:
            self._conn.execute(
                "UPDATE weapon_scene SET clip_state = 'failed', clip_path = NULL, "
                "clip_reason = ? WHERE id = ?",
                (reason, scene_id),
            )
            self._conn.commit()

    def review(self, scene_id: str, verdict: str, reviewer: str,
               at: datetime, reason: str | None = None) -> bool:
        """Record a person's decision. True only if this call made it.

        `WHERE verdict = 'pending'` is the whole guarantee: a verdict is
        recorded once, by one person, and never moves. A second reviewer
        gets False and the endpoint tells them so, rather than their name
        silently replacing the first one's on a safety decision.

        It is also the race: two operators pressing Confirm at the same
        moment both reach here, and exactly one row is changed, because
        SQLite decides it rather than a read-then-write in Python.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE weapon_scene SET verdict = ?, reviewed_by = ?, "
                "reviewed_at = ?, review_reason = ? "
                "WHERE id = ? AND verdict = 'pending'",
                (verdict, reviewer, _iso(at), reason, scene_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def close_orphans(self, reason: str = "shutdown") -> int:
        """Close scenes a crash left open. Returns how many.

        Called on start. Without it a scene from a killed process shows as
        still running forever, and the page reports a knife in view that was
        put away days ago.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE weapon_scene SET ended_at = COALESCE(ended_at, started_at), "
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
            log.info(
                "closed %d knife scene(s) left open by a previous run", cursor.rowcount
            )
        return cursor.rowcount

    def expire(self, older_than: datetime) -> int:
        """Remove videos that started before `older_than`. Returns how many.

        **Rows are never touched beyond their clip state.** The entry, its
        time, its confidence, its verdict and its reviewer all stay for
        ever; only the file goes. A school that can no longer watch the
        video still has the record that it looked, which is most of what
        the log is for.

        **Mark, then unlink.** The rows are updated and committed *before*
        a single file is deleted. A crash in between leaves entries that
        honestly say the video is gone; the other order leaves entries
        offering files that are not there, which is the same lie as a fake
        save. It also means a locked file — Windows, an open player, a
        network share — costs disk space rather than honesty.

        The period itself is the caller's: this store does not know what
        `clip_retention_days` is, and should not have to be edited when a
        site changes it.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, clip_path FROM weapon_scene "
                "WHERE clip_state = 'saved' AND started_at < ? "
                "ORDER BY started_at ASC",
                (_iso(older_than),),
            ).fetchall()
            if not rows:
                return 0
            marks = ",".join("?" * len(rows))
            self._conn.execute(
                "UPDATE weapon_scene SET clip_state = 'expired', "
                f"clip_path = NULL, clip_reason = ? WHERE id IN ({marks})",
                (EXPIRED_REASON, *[row["id"] for row in rows]),
            )
            self._conn.commit()

        # Outside the lock and after the commit: the rows already tell the
        # truth, so a failure to delete costs disk, not honesty.
        for row in rows:
            _unlink(row["clip_path"])
        log.info("expired %d knife clip(s) older than %s", len(rows), older_than)
        return len(rows)

    # -- reading ------------------------------------------------------------

    def get(self, scene_id: str) -> WeaponScene | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM weapon_scene WHERE id = ?", (scene_id,)
            ).fetchone()
        return _to_scene(row) if row else None

    def recent(
        self,
        since: datetime | None,
        until: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[WeaponScene]:
        """Scenes that started within the window, newest first.

        Either bound may be `None`, meaning open-ended: `recent(None, None)` is
        every row ever written, which is what the page's "All" period asks for
        and what makes "rows are never deleted" checkable.

        There is no `include_replaced` equivalent. Nothing here stops being
        listed — a dismissed entry stays on the page, because the list of what
        was looked at is the record, and a page that hides its own false alarms
        cannot be audited.
        """
        query = "SELECT * FROM weapon_scene WHERE 1 = 1"
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
        log.warning("could not delete expired knife clip %s: %s", path, exc)


def _to_scene(row: sqlite3.Row) -> WeaponScene:
    return WeaponScene(
        id=row["id"],
        camera_id=row["camera_id"],
        started_at=_parse(row["started_at"]),
        ended_at=_parse(row["ended_at"]),
        peak_confidence=float(row["peak_confidence"]),
        model_version=row["model_version"],
        clip_path=Path(row["clip_path"]) if row["clip_path"] else None,
        clip_state=row["clip_state"],
        clip_reason=row["clip_reason"],
        end_reason=row["end_reason"],
        verdict=row["verdict"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=_parse(row["reviewed_at"]),
        review_reason=row["review_reason"],
    )
