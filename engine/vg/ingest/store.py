"""Cameras added at runtime.

`engine.yaml` seeds the cameras a site starts with. Everything added afterwards
through the console lands here instead, because rewriting a config file from a
web request is a bad idea: comments get destroyed, concurrent writes corrupt it,
and a typo takes the whole engine down at the next restart.

So the roster is the union of two sources — YAML for the committed baseline,
SQLite for whatever operations added since. Only the second is writable at
runtime, and a bad row in it can be deleted without touching the config.

Cameras are soft-deleted. Removing one from the console should stop it being
watched, not erase the evidence that it existed and produced events.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from vg import db
from vg.config import CameraConfig

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS camera (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'RTSP',
    area        TEXT NOT NULL DEFAULT 'Unassigned',
    fps         REAL NOT NULL DEFAULT 5.0,
    rotate      INTEGER NOT NULL DEFAULT 0,
    features    TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    restricted  INTEGER NOT NULL DEFAULT 0,
    removed_at  TEXT,
    created_at  TEXT NOT NULL
);
"""

#: Columns added after the table first shipped, with the SQL to add each one.
#: A fresh database gets them from `SCHEMA`; an existing one gets them here,
#: because `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
#: exists — which is exactly how a new column silently never arrives on the
#: one machine that matters, the one with the data on it.
UPGRADES: tuple[tuple[str, str], ...] = (
    ("restricted", "ALTER TABLE camera ADD COLUMN restricted INTEGER NOT NULL DEFAULT 0"),
)


class CameraStore:
    """Runtime camera roster, persisted."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._upgrade()
        self._conn.commit()

    def _upgrade(self) -> None:
        """Add any column this database predates. In place, keeping every row."""
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(camera)").fetchall()
        }
        for column, sql in UPGRADES:
            if column not in existing:
                log.info("adding camera.%s to %s", column, self.path.name)
                self._conn.execute(sql)

    def add(
        self,
        camera_id: str,
        name: str,
        source: str,
        kind: str = "RTSP",
        area: str = "Unassigned",
        fps: float = 5.0,
        features: tuple[str, ...] = ("counting",),
        rotate: int = 0,
    ) -> CameraConfig:
        """Add or re-add a camera.

        Re-adding a soft-deleted id revives it rather than failing, which is
        what an operator means when they add back a camera they removed by
        mistake.
        """
        config = CameraConfig.parse(
            {
                "id": camera_id,
                "name": name,
                "source": source,
                "kind": kind,
                "area": area,
                "fps": fps,
                "features": list(features),
                "rotate": rotate,
            },
            f"camera {camera_id!r}",
        )

        with self._lock:
            self._conn.execute(
                "INSERT INTO camera "
                "(id, name, source, kind, area, fps, rotate, features, enabled, "
                " removed_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "  name=excluded.name, source=excluded.source, kind=excluded.kind, "
                "  area=excluded.area, fps=excluded.fps, rotate=excluded.rotate, "
                "  features=excluded.features, enabled=1, removed_at=NULL",
                (
                    config.id, config.name, config.source, config.kind, config.area,
                    config.fps, config.rotate, ",".join(config.features),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

        log.info("camera %s added (%s)", config.id, config.redacted_source())
        return config

    def remove(self, camera_id: str) -> bool:
        """Soft-delete. Events already recorded against this camera survive."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE camera SET removed_at = ?, enabled = 0 "
                "WHERE id = ? AND removed_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), camera_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def set_enabled(self, camera_id: str, enabled: bool) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE camera SET enabled = ? WHERE id = ? AND removed_at IS NULL",
                (1 if enabled else 0, camera_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def set_restricted(self, camera_id: str, restricted: bool) -> bool:
        """Mark a camera's whole frame a restricted area, or stop.

        Returns False when there is no such camera, so the endpoint above can
        404 truthfully instead of reporting a change it did not make.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE camera SET restricted = ? WHERE id = ? AND removed_at IS NULL",
                (1 if restricted else 0, camera_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def restricted_ids(self) -> set[str]:
        """Cameras whose whole frame is a restricted area, right now.

        A removed camera is excluded: soft-deleting one has to stop it being
        watched, or "remove" means nothing.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM camera WHERE restricted = 1 AND removed_at IS NULL"
            ).fetchall()
        return {row["id"] for row in rows}

    def all(self) -> list[CameraConfig]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM camera WHERE removed_at IS NULL ORDER BY created_at"
            ).fetchall()

        cameras = []
        for row in rows:
            try:
                cameras.append(CameraConfig.parse(
                    {
                        "id": row["id"], "name": row["name"], "source": row["source"],
                        "kind": row["kind"], "area": row["area"], "fps": row["fps"],
                        "rotate": row["rotate"], "enabled": bool(row["enabled"]),
                        "features": [f for f in row["features"].split(",") if f],
                    },
                    f"stored camera {row['id']!r}",
                ))
            except Exception as exc:
                # One malformed stored row must not take out the whole roster.
                log.error("skipping stored camera %s: %s", row["id"], exc)
        return cameras

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def merge_cameras(
    configured: tuple[CameraConfig, ...], stored: list[CameraConfig]
) -> list[CameraConfig]:
    """YAML baseline plus runtime additions, stored winning on a clash.

    An operator editing a camera in the console should see their change take
    effect; if YAML won, the edit would appear to work and then silently revert
    on restart.
    """
    merged = {c.id: c for c in configured}
    merged.update({c.id: c for c in stored})
    return list(merged.values())
