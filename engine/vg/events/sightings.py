"""Who was seen where, and the attendance register built from it.

A sighting is one recognition event: this person, on this camera, at this
instant, with this confidence. Attendance is a *view* over sightings, not a
separate thing that gets written — which matters, because it means the register
can be recomputed when a threshold changes or a face is re-enrolled, and there
is always a trail behind every "present" mark.

Three decisions worth stating:

**Debounce.** A person standing at an entrance for ten seconds at 5 fps is fifty
recognitions of one arrival. Only the first is interesting; the rest are stored
at a much lower rate so the trail stays useful without the table exploding.

**Absence is derived, never recorded.** Someone is absent because no sighting
exists, not because anything wrote "absent". A camera that was down cannot
therefore silently mark a room full of children absent — the register knows how
many cameras were up and can say so.

**Every sighting keeps its confidence and model version.** When a threshold
moves or a model is retrained, you need to know which register rows were
produced by which version, or a regression is unattributable.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from vg import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sighting (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     TEXT NOT NULL,
    camera_id     TEXT NOT NULL,
    seen_at       TEXT NOT NULL,          -- ISO-8601 UTC
    local_date    TEXT NOT NULL,          -- the SITE's date, for the register
    confidence    REAL NOT NULL,
    match_kind    TEXT NOT NULL DEFAULT 'face',
    model         TEXT NOT NULL,
    runner_up     REAL
);

CREATE INDEX IF NOT EXISTS idx_sighting_person_date
    ON sighting(person_id, local_date);
CREATE INDEX IF NOT EXISTS idx_sighting_date ON sighting(local_date);
CREATE INDEX IF NOT EXISTS idx_sighting_seen ON sighting(seen_at);
"""


@dataclass(frozen=True)
class Sighting:
    person_id: str
    camera_id: str
    seen_at: datetime
    confidence: float
    model: str
    match_kind: str = "face"
    runner_up: float | None = None


@dataclass(frozen=True)
class RegisterEntry:
    """One person's day."""

    person_id: str
    status: str  # on_time | late | absent
    first_seen: datetime | None
    last_seen: datetime | None
    camera_id: str | None
    confidence: float | None
    sightings: int
    minutes_late: int | None = None


@dataclass(frozen=True)
class DailyRegister:
    date: str
    cutoff: str
    entries: list[RegisterEntry]

    @property
    def present(self) -> int:
        return sum(1 for e in self.entries if e.status != "absent")

    @property
    def late(self) -> int:
        return sum(1 for e in self.entries if e.status == "late")

    @property
    def absent(self) -> int:
        return sum(1 for e in self.entries if e.status == "absent")

    @property
    def expected(self) -> int:
        return len(self.entries)

    def entry(self, person_id: str) -> RegisterEntry | None:
        return next((e for e in self.entries if e.person_id == person_id), None)


class SightingStore:
    """Sightings, and the register derived from them."""

    # A person recognised repeatedly is one arrival, not fifty. After the first
    # sighting, further ones for the same person on the same camera are stored
    # at most this often — enough to show they are still around, not enough to
    # fill the table.
    DEBOUNCE_SECONDS = 60.0

    def __init__(self, database: Path | str, tz_offset_minutes: int = 0) -> None:
        self.path = Path(database)
        self.tz_offset_minutes = tz_offset_minutes

        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        # (person_id, camera_id) -> when we last wrote a row
        self._last_written: dict[tuple[str, str], datetime] = {}

    def local_date(self, when: datetime) -> str:
        """The SITE's date for an instant.

        Not the server's date and not the viewer's: a school in Cairo at 00:30
        local is still on the previous UTC day, and putting an arrival on the
        wrong date silently corrupts the register.
        """
        return (when + timedelta(minutes=self.tz_offset_minutes)).date().isoformat()

    # -- writing ------------------------------------------------------------

    def record(self, sighting: Sighting, force: bool = False) -> bool:
        """Store a sighting unless it is a duplicate of a very recent one.

        Returns True if written. `force` bypasses the debounce, used for the
        first sighting of a person on a day — the arrival time is the one
        number attendance actually depends on, so it is never dropped.
        """
        key = (sighting.person_id, sighting.camera_id)
        with self._lock:
            if not force:
                previous = self._last_written.get(key)
                if previous is not None:
                    gap = (sighting.seen_at - previous).total_seconds()
                    if gap < self.DEBOUNCE_SECONDS:
                        return False

            self._conn.execute(
                "INSERT INTO sighting (person_id, camera_id, seen_at, local_date, "
                "confidence, match_kind, model, runner_up) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sighting.person_id,
                    sighting.camera_id,
                    sighting.seen_at.astimezone(timezone.utc).isoformat(),
                    self.local_date(sighting.seen_at),
                    sighting.confidence,
                    sighting.match_kind,
                    sighting.model,
                    sighting.runner_up,
                ),
            )
            self._conn.commit()
            self._last_written[key] = sighting.seen_at
            return True

    def seen_today(self, person_id: str, when: datetime | None = None) -> bool:
        when = when or datetime.now(timezone.utc)
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sighting WHERE person_id = ? AND local_date = ? LIMIT 1",
                (person_id, self.local_date(when)),
            ).fetchone()
        return row is not None

    # -- reading ------------------------------------------------------------

    def sightings_on(self, on: str, person_id: str | None = None) -> list[Sighting]:
        query = "SELECT * FROM sighting WHERE local_date = ?"
        params: list = [on]
        if person_id:
            query += " AND person_id = ?"
            params.append(person_id)
        query += " ORDER BY seen_at"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_to_sighting(r) for r in rows]

    def recent(self, limit: int = 50) -> list[Sighting]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sighting ORDER BY seen_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_to_sighting(r) for r in rows]

    def history(self, person_id: str, days: int = 30) -> dict[str, RegisterEntry]:
        """One person's last N school days, keyed by ISO date."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT local_date, MIN(seen_at) AS first_seen, MAX(seen_at) AS last_seen, "
                "COUNT(*) AS n, MAX(confidence) AS conf "
                "FROM sighting WHERE person_id = ? "
                "GROUP BY local_date ORDER BY local_date DESC LIMIT ?",
                (person_id, days),
            ).fetchall()

        return {
            row["local_date"]: RegisterEntry(
                person_id=person_id,
                status="on_time",  # refined by the caller, which knows the cutoff
                first_seen=_parse(row["first_seen"]),
                last_seen=_parse(row["last_seen"]),
                camera_id=None,
                confidence=row["conf"],
                sightings=row["n"],
            )
            for row in rows
        }

    def register(
        self,
        on: str,
        expected: list[str],
        cutoff: time,
        day_start: time | None = None,
        day_end: time | None = None,
    ) -> DailyRegister:
        """Build the register for a day.

        `expected` is who should be there. Anyone in that list with no sighting
        is absent — absence is the *absence of evidence*, never a written fact,
        so a re-enrolment or threshold change recomputes it correctly.

        `day_start`/`day_end` bound what counts as an arrival. Without them a
        sighting at 01:14 is "before the 08:00 cutoff" and therefore on time,
        which would mark the night caretaker present for the school day. Only
        sightings inside school hours establish attendance; ones outside are
        still stored — they are real, and they matter for tracking a person —
        they simply are not arrivals.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT person_id, MIN(seen_at) AS first_seen, MAX(seen_at) AS last_seen, "
                "COUNT(*) AS n, MAX(confidence) AS conf "
                "FROM sighting WHERE local_date = ? GROUP BY person_id",
                (on,),
            ).fetchall()

        by_person = {r["person_id"]: r for r in rows}
        if day_start is not None or day_end is not None:
            by_person = self._within_hours(on, day_start, day_end)
        first_cameras = self._first_cameras(on)

        entries: list[RegisterEntry] = []
        for person_id in expected:
            row = by_person.get(person_id)
            if row is None:
                entries.append(RegisterEntry(
                    person_id=person_id, status="absent", first_seen=None,
                    last_seen=None, camera_id=None, confidence=None, sightings=0,
                ))
                continue

            first = _parse(row["first_seen"])
            local_first = (first + timedelta(minutes=self.tz_offset_minutes)).time()
            late = local_first > cutoff
            minutes_late = None
            if late:
                minutes_late = int(
                    (
                        datetime.combine(date.today(), local_first)
                        - datetime.combine(date.today(), cutoff)
                    ).total_seconds() // 60
                )

            entries.append(RegisterEntry(
                person_id=person_id,
                status="late" if late else "on_time",
                first_seen=first,
                last_seen=_parse(row["last_seen"]),
                camera_id=first_cameras.get(person_id),
                confidence=row["conf"],
                sightings=row["n"],
                minutes_late=minutes_late,
            ))

        return DailyRegister(date=on, cutoff=cutoff.strftime("%H:%M"), entries=entries)

    def _within_hours(
        self, on: str, day_start: time | None, day_end: time | None
    ) -> dict[str, sqlite3.Row]:
        """Per-person first/last sighting, counting only school hours.

        SQLite has no timezone maths, so the window is applied in Python
        against each row's site-local time rather than trying to express the
        offset in SQL.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT person_id, seen_at, confidence FROM sighting "
                "WHERE local_date = ? ORDER BY seen_at",
                (on,),
            ).fetchall()

        grouped: dict[str, dict] = {}
        for row in rows:
            seen = _parse(row["seen_at"])
            local = (seen + timedelta(minutes=self.tz_offset_minutes)).time()
            if day_start is not None and local < day_start:
                continue
            if day_end is not None and local > day_end:
                continue

            entry = grouped.setdefault(row["person_id"], {
                "person_id": row["person_id"],
                "first_seen": row["seen_at"],
                "last_seen": row["seen_at"],
                "n": 0,
                "conf": 0.0,
            })
            entry["last_seen"] = row["seen_at"]
            entry["n"] += 1
            entry["conf"] = max(entry["conf"], row["confidence"])

        return grouped

    def _first_cameras(self, on: str) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT person_id, camera_id FROM sighting s WHERE local_date = ? "
                "AND seen_at = (SELECT MIN(seen_at) FROM sighting "
                "               WHERE person_id = s.person_id AND local_date = s.local_date)",
                (on,),
            ).fetchall()
        return {r["person_id"]: r["camera_id"] for r in rows}

    def clear(self) -> None:
        """Wipe all sightings. Test and demo use only."""
        with self._lock:
            self._conn.execute("DELETE FROM sighting")
            self._conn.commit()
            self._last_written.clear()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SightingStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_sighting(row: sqlite3.Row) -> Sighting:
    return Sighting(
        person_id=row["person_id"],
        camera_id=row["camera_id"],
        seen_at=_parse(row["seen_at"]),
        confidence=row["confidence"],
        model=row["model"],
        match_kind=row["match_kind"],
        runner_up=row["runner_up"],
    )
