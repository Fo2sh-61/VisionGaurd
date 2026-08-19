"""Where appearance sightings are stored, and how a path is read back.

A face sighting answers "who arrived". An appearance sighting answers "where
did that body go next" — and the two together are what reconstructs a person's
movement across cameras, which is the whole of the track-a-person feature.

Why a separate table from `sighting`:

  * **Different claim, different strength.** A face match names a person. An
    appearance match only says *this is the same body as the one named earlier*.
    Mixing them in one table would let a weaker claim be read as a stronger one
    by anything that forgot to check the column.
  * **Different retention.** Appearance rows are dense — one per person per
    analysed frame — where face sightings are debounced to arrivals. They age
    out on a much shorter clock.
  * **Different failure.** A wrong face match is a wrong name. A wrong
    appearance match is a *correct* name on the wrong body, which is worse and
    needs to be separately correctable.

Boxes are stored as fractions of the frame, per the geometry rule.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vg import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS appearance_sighting (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id   TEXT NOT NULL,
    person_id   TEXT,
    camera_id   TEXT NOT NULL,
    at_utc      TEXT NOT NULL,
    local_date  TEXT NOT NULL,
    x           REAL NOT NULL,
    y           REAL NOT NULL,
    w           REAL NOT NULL,
    h           REAL NOT NULL,
    confidence  REAL NOT NULL,
    track_id    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_app_date   ON appearance_sighting(local_date);
CREATE INDEX IF NOT EXISTS idx_app_person ON appearance_sighting(person_id, local_date);
CREATE INDEX IF NOT EXISTS idx_app_stable ON appearance_sighting(stable_id, local_date);
"""

# One row per person per analysed frame is far more than a path needs, and it
# would put millions of rows a day on a real site. A person standing still is
# adequately described by a row every few seconds.
DEFAULT_MIN_GAP_SECONDS = 3.0


@dataclass(frozen=True)
class PathStop:
    """A continuous stretch of one identity on one camera."""

    stable_id: str
    person_id: str | None
    camera_id: str
    first_seen: datetime
    last_seen: datetime
    sightings: int
    confidence: float

    @property
    def seconds(self) -> float:
        return (self.last_seen - self.first_seen).total_seconds()


class AppearanceStore:
    """Appearance sightings, and the paths built from them."""

    def __init__(self, database: Path | str, tz_offset_minutes: int = 0,
                 min_gap_seconds: float = DEFAULT_MIN_GAP_SECONDS) -> None:
        self.path = Path(database)
        self.tz_offset_minutes = tz_offset_minutes
        self.min_gap_seconds = min_gap_seconds

        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        # Last write per (camera, stable id), for the sampling gate. In memory
        # because it is a rate limiter, not a record.
        self._last_write: dict[tuple[str, str], datetime] = {}

    def local_date(self, when: datetime) -> str:
        """The date at the *site*, not on the server.

        A path belongs to a school day, and a server in another timezone must
        not decide where the boundary falls.
        """
        return (when + timedelta(minutes=self.tz_offset_minutes)).strftime("%Y-%m-%d")

    # -- writing ------------------------------------------------------------

    def record(self, sighting, force: bool = False) -> bool:
        """Store one sighting, or skip it as too soon after the last.

        Returns whether a row was written, so a caller can count real writes
        rather than attempts.
        """
        key = (sighting.camera_id, sighting.stable_id)
        with self._lock:
            previous = self._last_write.get(key)
            if (not force and previous is not None
                    and (sighting.at - previous).total_seconds() < self.min_gap_seconds):
                return False

            self._conn.execute(
                "INSERT INTO appearance_sighting "
                "(stable_id, person_id, camera_id, at_utc, local_date, "
                " x, y, w, h, confidence, track_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sighting.stable_id, sighting.person_id, sighting.camera_id,
                 sighting.at.isoformat(), self.local_date(sighting.at),
                 sighting.x, sighting.y, sighting.w, sighting.h,
                 sighting.confidence, sighting.track_id),
            )
            self._conn.commit()
            self._last_write[key] = sighting.at
        return True

    def record_many(self, sightings) -> int:
        return sum(1 for s in sightings if self.record(s))

    def name_identity(self, stable_id: str, person_id: str, on: str | None = None) -> int:
        """Backfill a name onto rows already written for this identity.

        Recognition usually happens *after* the body has been seen for a few
        frames, and a path that starts only from the moment of the face match
        would be missing its beginning — which is often the part being asked
        about. Scoped to one day so an identity reused later cannot inherit a
        name retroactively.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE appearance_sighting SET person_id = ? "
                "WHERE stable_id = ? AND person_id IS NULL "
                "AND local_date = COALESCE(?, local_date)",
                (person_id, stable_id, on),
            )
            self._conn.commit()
            return cursor.rowcount

    def unname_identity(self, stable_id: str) -> int:
        """Strip a name after an operator correction.

        The rows stay: they are a true record that a body was there. Only the
        claim about who it was is withdrawn.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE appearance_sighting SET person_id = NULL WHERE stable_id = ?",
                (stable_id,),
            )
            self._conn.commit()
            return cursor.rowcount

    # -- reading ------------------------------------------------------------

    def path_for(self, person_id: str, on: str, gap_seconds: float = 60.0
                 ) -> list[PathStop]:
        """One person's movements on one day, as camera-to-camera stops.

        Consecutive rows on the same camera are collapsed into a single stop.
        `gap_seconds` is how long a break has to be before returning to the
        same camera counts as a *new* visit rather than the same one — without
        it, someone pacing in and out of view produces dozens of stops.
        """
        with self._lock:
            rows = list(self._conn.execute(
                "SELECT * FROM appearance_sighting "
                "WHERE person_id = ? AND local_date = ? ORDER BY at_utc",
                (person_id, on),
            ))
        return self._collapse(rows, gap_seconds)

    def path_for_identity(self, stable_id: str, on: str, gap_seconds: float = 60.0
                          ) -> list[PathStop]:
        """The same, for an unnamed body. Used when nobody was recognised."""
        with self._lock:
            rows = list(self._conn.execute(
                "SELECT * FROM appearance_sighting "
                "WHERE stable_id = ? AND local_date = ? ORDER BY at_utc",
                (stable_id, on),
            ))
        return self._collapse(rows, gap_seconds)

    def _collapse(self, rows, gap_seconds: float) -> list[PathStop]:
        stops: list[PathStop] = []
        for row in rows:
            at = datetime.fromisoformat(row["at_utc"])
            last = stops[-1] if stops else None

            same_place = last is not None and last.camera_id == row["camera_id"]
            continuous = (
                same_place and (at - last.last_seen).total_seconds() <= gap_seconds
            )
            if continuous:
                stops[-1] = PathStop(
                    stable_id=last.stable_id,
                    person_id=last.person_id,
                    camera_id=last.camera_id,
                    first_seen=last.first_seen,
                    last_seen=at,
                    sightings=last.sightings + 1,
                    confidence=max(last.confidence, float(row["confidence"])),
                )
            else:
                stops.append(PathStop(
                    stable_id=row["stable_id"],
                    person_id=row["person_id"],
                    camera_id=row["camera_id"],
                    first_seen=at,
                    last_seen=at,
                    sightings=1,
                    confidence=float(row["confidence"]),
                ))
        return stops

    def identities_on(self, on: str) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(
                "SELECT DISTINCT stable_id FROM appearance_sighting "
                "WHERE local_date = ? ORDER BY stable_id", (on,),
            )]

    def count_on(self, on: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM appearance_sighting WHERE local_date = ?", (on,),
            ).fetchone()[0]

    def prune(self, keep_days: int = 14) -> int:
        """Drop old rows. These are dense and their value decays fast."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM appearance_sighting WHERE local_date < ?", (cutoff,),
            )
            self._conn.commit()
            return cursor.rowcount

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM appearance_sighting")
            self._conn.commit()
            self._last_write.clear()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "AppearanceStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
