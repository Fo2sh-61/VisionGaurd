"""What the attendance register needs to remember that sightings cannot.

A past day is read "as recorded": who was on the roll then, which cut-off
applied, who had been excused. Sightings alone know none of that, and the
gallery only knows today. Three small tables in the sightings file fill the gap:

**excusal.** A person's absence a human has accounted for. No unique key: two
administrators each leave a row and the status is "a row exists". An arrival
always wins over a row - the register decides that, not this table.

**removed_person.** Written before the gallery delete, so a person taken out of
the system still reads by name on the days they belonged to. Face vectors are
not here: they leave with the person.

**hours_snapshot.** The cut-off and working days, dated the first time a change
is seen. Lazy on purpose: nothing in Settings had to change for this.

Each call opens its own short connection, so nothing here holds the sightings
file open after the sightings store itself is closed.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Collection, Iterator

from vg import db
from vg.clock import Clock, clock_for

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS excusal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    TEXT NOT NULL,
    local_date   TEXT NOT NULL,
    excused_by   TEXT NOT NULL,
    excused_at   TEXT NOT NULL          -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_excusal_date ON excusal(local_date, person_id);

CREATE TABLE IF NOT EXISTS removed_person (
    person_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL,
    grp          TEXT,
    created_at   TEXT,
    removed_at   TEXT NOT NULL,         -- ISO-8601 UTC
    removed_by   TEXT NOT NULL,
    had_faces    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS hours_snapshot (
    from_date     TEXT PRIMARY KEY,
    day_start     TEXT NOT NULL,
    day_end       TEXT NOT NULL,
    late_cutoff   TEXT NOT NULL,
    working_days  TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class RemovedPerson:
    person_id: str
    name: str
    type: str
    group: str | None
    created_at: datetime | None
    removed_at: datetime
    removed_by: str
    had_faces: bool


@dataclass(frozen=True)
class HoursSnapshot:
    from_date: str
    day_start: time
    day_end: time
    late_cutoff: time
    working_days: frozenset[int]


def _hm(value: time) -> str:
    return value.strftime("%H:%M")


def _time(value: str) -> time:
    hour, minute = value.split(":")[:2]
    return time(int(hour), int(minute))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AttendanceLedger:
    """Excusals, removed people and the hours in force on past days."""

    def __init__(self, database: Path | str, clock: Clock | int | str = 0) -> None:
        self.path = Path(database)
        self.clock = clock_for(clock)
        self._lock = threading.RLock()
        # The newest snapshot, remembered so a register read that changes
        # nothing costs no database work.
        self._newest: HoursSnapshot | None = None
        self._newest_loaded = False
        with self._open() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _open(self) -> Iterator:
        with self._lock:
            conn = db.connect(self.path)
            try:
                yield conn
            finally:
                conn.close()

    # -- excusals -----------------------------------------------------------

    def excuse(self, person_id: str, date: str, by: str, at: datetime) -> None:
        with self._open() as conn:
            conn.execute(
                "INSERT INTO excusal (person_id, local_date, excused_by, excused_at) "
                "VALUES (?, ?, ?, ?)",
                (person_id, date, by, at.astimezone(timezone.utc).isoformat()),
            )
            conn.commit()

    def excused_on(self, date: str) -> set[str]:
        with self._open() as conn:
            rows = conn.execute(
                "SELECT DISTINCT person_id FROM excusal WHERE local_date = ?",
                (date,),
            ).fetchall()
        return {r["person_id"] for r in rows}

    def excused_among(self, person_id: str, dates: Collection[str]) -> set[str]:
        """Which of `dates` this one person is excused on, in one query."""
        wanted = list(dates)
        if not wanted:
            return set()
        marks = ",".join("?" for _ in wanted)
        with self._open() as conn:
            rows = conn.execute(
                "SELECT DISTINCT local_date FROM excusal "
                f"WHERE person_id = ? AND local_date IN ({marks})",
                [person_id, *wanted],
            ).fetchall()
        return {r["local_date"] for r in rows}

    # -- removed people -----------------------------------------------------

    def note_removed(self, person, removed_at: datetime, by: str) -> None:
        """Remember who they were, before the gallery forgets them."""
        with self._open() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO removed_person (person_id, name, type, grp, "
                "created_at, removed_at, removed_by, had_faces) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    person.id, person.name, person.type, person.group,
                    person.created_at.astimezone(timezone.utc).isoformat()
                    if person.created_at else None,
                    removed_at.astimezone(timezone.utc).isoformat(),
                    by,
                    1 if person.photo_on_file else 0,
                ),
            )
            conn.commit()

    def removed_expected_on(
        self, date: str, seen: Collection[str] = ()
    ) -> list[RemovedPerson]:
        """Removed people who belonged on the register of a past `date`.

        Enrolled on or before that day, with a photo then, and either removed
        after it or seen on it (removed later the same day, after arriving).
        """
        with self._open() as conn:
            rows = conn.execute(
                "SELECT * FROM removed_person WHERE had_faces = 1"
            ).fetchall()

        out: list[RemovedPerson] = []
        for row in rows:
            created = _parse(row["created_at"])
            if created is not None and self.clock.local_date(created) > date:
                continue
            removed = _parse(row["removed_at"])
            if self.clock.local_date(removed) <= date and row["person_id"] not in seen:
                continue
            out.append(RemovedPerson(
                person_id=row["person_id"], name=row["name"], type=row["type"],
                group=row["grp"], created_at=created, removed_at=removed,
                removed_by=row["removed_by"], had_faces=True,
            ))
        return out

    # -- the hours in force -------------------------------------------------

    def note_hours(self, hours, today: str) -> None:
        """Record `hours` as of `today` if they differ from the newest row.

        Called before every register read, so a change is dated the day it was
        first read - seconds after the save. Nothing earlier is known.
        """
        current = HoursSnapshot(
            from_date=today, day_start=hours.start, day_end=hours.end,
            late_cutoff=hours.late_cutoff,
            working_days=frozenset(hours.working_days),
        )
        with self._lock:
            newest = self._load_newest()
            if newest is not None and _same(newest, current):
                return
            with self._open() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO hours_snapshot (from_date, day_start, "
                    "day_end, late_cutoff, working_days) VALUES (?, ?, ?, ?, ?)",
                    (today, _hm(current.day_start), _hm(current.day_end),
                     _hm(current.late_cutoff),
                     json.dumps(sorted(current.working_days))),
                )
                conn.commit()
            self._newest = current
            self._newest_loaded = True

    def hours_on(self, date: str) -> HoursSnapshot | None:
        """The newest snapshot in force on `date`, or None if none is that old."""
        with self._open() as conn:
            row = conn.execute(
                "SELECT * FROM hours_snapshot WHERE from_date <= ? "
                "ORDER BY from_date DESC LIMIT 1",
                (date,),
            ).fetchone()
        return _snapshot(row) if row else None

    def _load_newest(self) -> HoursSnapshot | None:
        if not self._newest_loaded:
            with self._open() as conn:
                row = conn.execute(
                    "SELECT * FROM hours_snapshot ORDER BY from_date DESC LIMIT 1"
                ).fetchone()
            self._newest = _snapshot(row) if row else None
            self._newest_loaded = True
        return self._newest

    def close(self) -> None:
        """Nothing stays open between calls; kept so it closes like the others."""

    def __enter__(self) -> "AttendanceLedger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _snapshot(row) -> HoursSnapshot:
    return HoursSnapshot(
        from_date=row["from_date"],
        day_start=_time(row["day_start"]),
        day_end=_time(row["day_end"]),
        late_cutoff=_time(row["late_cutoff"]),
        working_days=frozenset(json.loads(row["working_days"])),
    )


def _same(a: HoursSnapshot, b: HoursSnapshot) -> bool:
    return (a.day_start, a.day_end, a.late_cutoff, a.working_days) == (
        b.day_start, b.day_end, b.late_cutoff, b.working_days)
