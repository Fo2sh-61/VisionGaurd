"""Headcount history, so "today by hour" can be a measurement.

The counting page has always offered *Today by hour* and *This week by day*.
Until now both were invented numbers, because nothing ever wrote a headcount
down — the engine could say how many people are in a room right now and had no
memory of a minute ago.

This is that memory. One row per area per sample, and the page reads it back.

**Per area, not per camera.** The question is "how busy was the cafeteria",
which is a property of the place. Cameras come and go; areas are what an
operator reasons about.

**Sampled, not per frame.** A row every `SAMPLE_SECONDS` is plenty for an hourly
chart and keeps the table small enough to query without an index scan. At one
row per area per minute, a 12-area site writes about 17,000 rows a day.

**Bars are averages, not maxima.** "How busy was the hall at 9am" is answered by
the typical number over that hour, not the single highest frame — one person
walking past the lens at the wrong moment should not define the hour.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS area_count (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    area        TEXT NOT NULL,
    at_utc      TEXT NOT NULL,
    local_date  TEXT NOT NULL,
    local_hour  INTEGER NOT NULL,
    people      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_area_count_date ON area_count(local_date, area);
CREATE INDEX IF NOT EXISTS idx_area_count_at   ON area_count(at_utc);
"""

#: How often a sample is written. A minute is fine for an hourly chart and
#: keeps the table two orders of magnitude smaller than per-frame writes.
SAMPLE_SECONDS = 60.0


@dataclass(frozen=True)
class AreaPoint:
    """The typical headcount in one area over one bucket of time."""

    area: str
    label: str
    people: int


class AreaCountStore:
    """Writes headcount samples, and reads them back as chart buckets."""

    def __init__(self, database: Path | str, tz_offset_minutes: int = 0) -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tz_offset_minutes = tz_offset_minutes

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._last_sample: datetime | None = None

    def _local(self, when: datetime) -> datetime:
        return when + timedelta(minutes=self.tz_offset_minutes)

    # -- writing ------------------------------------------------------------

    def record(self, counts: dict[str, int], at: datetime | None = None,
               force: bool = False) -> int:
        """Write one sample per area, or skip if it is too soon.

        Returns how many rows were written, so a caller can count real samples
        rather than attempts.
        """
        at = at or datetime.now(timezone.utc)
        with self._lock:
            if (not force and self._last_sample is not None
                    and (at - self._last_sample).total_seconds() < SAMPLE_SECONDS):
                return 0

            local = self._local(at)
            rows = [
                (area, at.isoformat(), local.strftime("%Y-%m-%d"), local.hour, people)
                for area, people in counts.items()
            ]
            if not rows:
                return 0

            self._conn.executemany(
                "INSERT INTO area_count (area, at_utc, local_date, local_hour, people) "
                "VALUES (?, ?, ?, ?, ?)", rows,
            )
            self._conn.commit()
            self._last_sample = at
            return len(rows)

    # -- reading ------------------------------------------------------------

    def by_hour(self, on: str) -> dict[str, list[AreaPoint]]:
        """One day, bucketed by hour. `{hour label: [per-area points]}`.

        Only hours that were actually sampled appear. An hour with no rows is
        absent rather than zero — the engine was not running, which is not the
        same as nobody being there.
        """
        with self._lock:
            rows = list(self._conn.execute(
                "SELECT local_hour, area, AVG(people) AS people FROM area_count "
                "WHERE local_date = ? GROUP BY local_hour, area ORDER BY local_hour",
                (on,),
            ))

        buckets: dict[str, list[AreaPoint]] = {}
        for row in rows:
            label = f"{int(row['local_hour']):02d}:00"
            buckets.setdefault(label, []).append(
                AreaPoint(area=row["area"], label=label,
                          people=int(round(row["people"]))))
        return buckets

    def by_day(self, days: int = 7) -> dict[str, list[AreaPoint]]:
        """The last `days` days, bucketed by date."""
        since = (self._local(datetime.now(timezone.utc)) - timedelta(days=days)
                 ).strftime("%Y-%m-%d")
        with self._lock:
            rows = list(self._conn.execute(
                "SELECT local_date, area, AVG(people) AS people FROM area_count "
                "WHERE local_date >= ? GROUP BY local_date, area ORDER BY local_date",
                (since,),
            ))

        buckets: dict[str, list[AreaPoint]] = {}
        for row in rows:
            buckets.setdefault(row["local_date"], []).append(
                AreaPoint(area=row["area"], label=row["local_date"],
                          people=int(round(row["people"]))))
        return buckets

    def samples_on(self, on: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM area_count WHERE local_date = ?", (on,),
            ).fetchone()[0]

    def prune(self, keep_days: int = 90) -> int:
        cutoff = self._local(datetime.now(timezone.utc) - timedelta(days=keep_days)
                             ).strftime("%Y-%m-%d")
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM area_count WHERE local_date < ?", (cutoff,))
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "AreaCountStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
