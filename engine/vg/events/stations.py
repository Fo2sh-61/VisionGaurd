"""Work stations: when somebody was at one, and when it was left empty.

A station is an area (`vg/areas.py`); this file keeps what happened at it.

**Segments, not counters.** `station_segment` holds one row per stretch of one
situation - `on`, `away` or `absent` - from the first moment of it to the last.
Today's working time, absence time, rate and the timeline are all one read over
those rows, clipped to the hours the station is watched. Nothing counts
seconds: a counter running beside the frames can disagree with them, and a row
a second per station is a table nobody can use.

**Time that nobody measured is not time.** Watched hours with no segment over
them are reported as *not watched*, never as on or off station. A stopped
camera or a stopped engine writes nothing and raises nothing; the missing time
is simply missing, and the rate is worked out over the time that was covered.

**An open segment is confirmed, not assumed.** The worker refreshes
`checked_at` at most every `HEARTBEAT_SECONDS`. At start `close_orphans()` ends
every open row at its own `checked_at`, so an engine that died mid-segment
does not leave somebody "at the desk" for the length of the outage.

**One alert per absence.** `station_event.alert_key` is unique and is built
from when the absence began, so a second attempt at the same absence writes
nothing and sends nothing. A restart (or a stall of `stall_seconds`) starts a
NEW absence with a restarted Away clock: if the person is still gone it can
alert again after another limit, because the time in between was not measured.

**Rows are never updated or deleted** except an open segment closing. An
acknowledgement is a new row that points at the alert it answers; it does not
touch the alert, and it does not change the station's state.

Nothing in here knows who anybody is. The assignee is an assignment kept on the
area; a station's record never says who stood there.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from vg import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS station_segment (
    id          TEXT PRIMARY KEY,
    station_id  TEXT NOT NULL,
    state       TEXT NOT NULL,           -- on | away | absent
    started_at  TEXT NOT NULL,           -- ISO-8601 UTC, first moment of it
    ended_at    TEXT,                    -- NULL while open
    checked_at  TEXT NOT NULL            -- last time the worker confirmed it
);
CREATE INDEX IF NOT EXISTS idx_station_segment
    ON station_segment(station_id, started_at);

CREATE TABLE IF NOT EXISTS station_event (
    id            TEXT PRIMARY KEY,
    station_id    TEXT NOT NULL,
    at            TEXT NOT NULL,
    kind          TEXT NOT NULL,         -- at_station | left_station |
                                         -- absence_alert | acknowledged
    limit_minutes INTEGER,
    alert_key     TEXT UNIQUE,
    by_who        TEXT,
    ref           TEXT                   -- on acknowledged: the alert it answers
);
CREATE INDEX IF NOT EXISTS idx_station_event
    ON station_event(station_id, at);
"""

STATES = ("on", "away", "absent")
EVENT_KINDS = ("at_station", "left_station", "absence_alert", "acknowledged")

#: How often an open segment's `checked_at` is refreshed at most.
HEARTBEAT_SECONDS = 10.0


@dataclass(frozen=True)
class Segment:
    id: str
    station_id: str
    state: str
    started_at: datetime
    ended_at: datetime | None
    checked_at: datetime


@dataclass(frozen=True)
class StationEventRow:
    id: str
    station_id: str
    at: datetime
    kind: str
    limit_minutes: int | None = None
    alert_key: str | None = None
    by_who: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class Figures:
    """One station's day, over the hours it was watched.

    `watched_seconds` is the length of the watched window so far; `covered` is
    the part of it some segment speaks for. The rest is `not_watched_seconds`.
    """

    work_seconds: float = 0.0
    away_seconds: float = 0.0
    absent_seconds: float = 0.0
    not_watched_seconds: float = 0.0
    watched_seconds: float = 0.0
    #: on / covered; None until some watched time was covered.
    rate: float | None = None
    #: (state, from, to), state one of on | away | absent | notWatched.
    timeline: tuple[tuple[str, datetime, datetime], ...] = ()

    @property
    def covered_seconds(self) -> float:
        return self.work_seconds + self.away_seconds + self.absent_seconds

    @property
    def off_station_seconds(self) -> float:
        """Time the station was empty, short or long."""
        return self.away_seconds + self.absent_seconds


class StationStore:
    """Every segment and every event, for every station ever drawn."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._touched: dict[str, datetime] = {}
        #: Called after an absence alert's row is committed, with
        #: `(station_id, camera_id, at, away_since, station, limit_minutes,
        #: assignee, channels)`. Alert delivery sets it; it must only hand the
        #: event over.
        self.on_alert = None

    # -- segments -----------------------------------------------------------

    def open_segment(self, station_id: str, state: str,
                     started_at: datetime) -> str:
        if state not in STATES:
            raise ValueError(f"a segment is one of {STATES}, not {state!r}")
        segment_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO station_segment "
                "(id, station_id, state, started_at, checked_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (segment_id, station_id, state, _iso(started_at),
                 _iso(started_at)))
            self._conn.commit()
        self._touched[segment_id] = started_at
        return segment_id

    def close_segment(self, segment_id: str, ended_at: datetime) -> None:
        """End a segment. Closing a closed one changes nothing."""
        with self._lock:
            self._conn.execute(
                "UPDATE station_segment SET ended_at = ?, checked_at = ? "
                "WHERE id = ? AND ended_at IS NULL",
                (_iso(ended_at), _iso(ended_at), segment_id))
            self._conn.commit()
        self._touched.pop(segment_id, None)

    def touch(self, segment_id: str, at: datetime) -> bool:
        """The worker still sees this segment. Written at most every
        `HEARTBEAT_SECONDS`; returns whether it wrote."""
        last = self._touched.get(segment_id)
        if last is not None and (at - last).total_seconds() < HEARTBEAT_SECONDS:
            return False
        with self._lock:
            self._conn.execute(
                "UPDATE station_segment SET checked_at = ? "
                "WHERE id = ? AND ended_at IS NULL AND checked_at < ?",
                (_iso(at), segment_id, _iso(at)))
            self._conn.commit()
        self._touched[segment_id] = at
        return True

    def close_orphans(self) -> int:
        """End every open segment where it was last confirmed. At start only."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE station_segment SET ended_at = checked_at "
                "WHERE ended_at IS NULL")
            self._conn.commit()
        self._touched.clear()
        return cursor.rowcount

    def segments(self, station_id: str, start: datetime,
                 end: datetime) -> list[Segment]:
        """Segments that overlap [start, end), oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM station_segment WHERE station_id = ? "
                "AND started_at < ? AND (ended_at IS NULL OR ended_at > ?) "
                "ORDER BY started_at", (station_id, _iso(end), _iso(start))
            ).fetchall()
        return [_to_segment(r) for r in rows]

    # -- events -------------------------------------------------------------

    def add_event(self, station_id: str, at: datetime, kind: str, *,
                  limit_minutes: int | None = None, alert_key: str | None = None,
                  by_who: str | None = None, ref: str | None = None
                  ) -> str | None:
        """Write one event. None when `alert_key` was already used: that
        absence has been alerted, and a second row must not exist."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"an event is one of {EVENT_KINDS}, not {kind!r}")
        event_id = uuid.uuid4().hex
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO station_event (id, station_id, at, kind, "
                    "limit_minutes, alert_key, by_who, ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (event_id, station_id, _iso(at), kind, limit_minutes,
                     alert_key, by_who, ref))
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return None
            self._conn.commit()
        return event_id

    def absence_alert(self, station_id: str, camera_id: str, at: datetime,
                      away_since: datetime, station: str, limit_minutes: int,
                      assignee: str | None = None,
                      channels: frozenset[str] | None = None) -> str | None:
        """Record that a station has been empty past its limit, once.

        The key is built from when the absence began. Returns the event id, or
        None (and sends nothing) when this absence was already alerted.
        """
        key = f"station:{station_id}:{_iso(away_since)}"
        event_id = self.add_event(
            station_id, at, "absence_alert", limit_minutes=limit_minutes,
            alert_key=key)
        if event_id is None:
            return None
        # After the commit: the row is the event, and a failing hook costs a
        # message, never the record.
        if self.on_alert is not None:
            try:
                self.on_alert(station_id, camera_id, at, away_since, station,
                              limit_minutes, assignee, channels)
            except Exception:
                log.exception("station %s: the alert hook failed", station_id[:8])
        return event_id

    def acknowledge(self, station_id: str, by_who: str, at: datetime,
                    event_id: str | None = None) -> str | None:
        """Answer an unacknowledged alert: a new row pointing at it.

        Without `event_id`, the newest unacknowledged alert of the station.
        None when there is nothing to answer. The alert row is not touched.
        """
        with self._lock:
            open_ones = self.open_alerts(station_id)
            target = None
            if event_id is None:
                target = open_ones[0] if open_ones else None
            else:
                target = next((e for e in open_ones if e.id == event_id), None)
            if target is None:
                return None
            return self.add_event(station_id, at, "acknowledged",
                                  by_who=by_who, ref=target.id)

    def open_alerts(self, station_id: str | None = None,
                    since: datetime | None = None) -> list[StationEventRow]:
        """Absence alerts nobody has acknowledged, newest first."""
        query = ("SELECT a.* FROM station_event a WHERE a.kind = 'absence_alert' "
                 "AND NOT EXISTS (SELECT 1 FROM station_event k "
                 "WHERE k.kind = 'acknowledged' AND k.ref = a.id)")
        params: list = []
        if station_id is not None:
            query += " AND a.station_id = ?"
            params.append(station_id)
        if since is not None:
            query += " AND a.at >= ?"
            params.append(_iso(since))
        query += " ORDER BY a.at DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_to_event(r) for r in rows]

    def get_event(self, event_id: str) -> StationEventRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM station_event WHERE id = ?", (event_id,)
            ).fetchone()
        return _to_event(row) if row else None

    def events(self, station_id: str, start: datetime,
               end: datetime) -> list[StationEventRow]:
        """One station's events in [start, end), newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM station_event WHERE station_id = ? "
                "AND at >= ? AND at < ? ORDER BY at DESC, rowid DESC",
                (station_id, _iso(start), _iso(end))).fetchall()
        return [_to_event(r) for r in rows]

    # -- the day ------------------------------------------------------------

    def figures(self, station_id: str,
                windows: Iterable[tuple[datetime, datetime]],
                until: datetime) -> Figures:
        """Sums of segments clipped to the watched `windows`, up to `until`.

        `windows` are the stretches the station was meant to be watched; time
        in them that no segment covers is *not watched*. An open segment
        counts up to `until` while it was confirmed recently, and otherwise
        only up to its last confirmation - the engine may be down.
        """
        clipped = [(a, min(b, until)) for a, b in windows if a < until]
        clipped = [(a, b) for a, b in clipped if a < b]
        if not clipped:
            return Figures()
        lo, hi = min(a for a, _ in clipped), max(b for _, b in clipped)
        segments = self.segments(station_id, lo, hi)

        totals = {"on": 0.0, "away": 0.0, "absent": 0.0}
        watched = 0.0
        timeline: list[tuple[str, datetime, datetime]] = []
        for w_start, w_end in clipped:
            watched += (w_end - w_start).total_seconds()
            cursor = w_start
            for seg in segments:
                s_end = self._effective_end(seg, until)
                a, b = max(seg.started_at, w_start), min(s_end, w_end)
                if b <= a:
                    continue
                if a > cursor:
                    timeline.append(("notWatched", cursor, a))
                timeline.append((seg.state, max(a, cursor), b))
                totals[seg.state] += (b - max(a, cursor)).total_seconds()
                cursor = max(cursor, b)
            if cursor < w_end:
                timeline.append(("notWatched", cursor, w_end))
        covered = sum(totals.values())
        return Figures(
            work_seconds=totals["on"], away_seconds=totals["away"],
            absent_seconds=totals["absent"],
            not_watched_seconds=max(0.0, watched - covered),
            watched_seconds=watched,
            rate=(totals["on"] / covered) if covered > 0 else None,
            timeline=tuple(timeline))

    @staticmethod
    def _effective_end(seg: Segment, until: datetime) -> datetime:
        if seg.ended_at is not None:
            return seg.ended_at
        if (until - seg.checked_at).total_seconds() <= 2 * HEARTBEAT_SECONDS:
            return until
        return seg.checked_at

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# helpers - the same ISO form as events/zones.py
# ---------------------------------------------------------------------------

def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_segment(row: sqlite3.Row) -> Segment:
    return Segment(
        id=row["id"], station_id=row["station_id"], state=row["state"],
        started_at=_parse(row["started_at"]), ended_at=_parse(row["ended_at"]),
        checked_at=_parse(row["checked_at"]))


def _to_event(row: sqlite3.Row) -> StationEventRow:
    return StationEventRow(
        id=row["id"], station_id=row["station_id"], at=_parse(row["at"]),
        kind=row["kind"], limit_minutes=row["limit_minutes"],
        alert_key=row["alert_key"], by_who=row["by_who"], ref=row["ref"])
