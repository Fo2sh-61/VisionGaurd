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
    removed_at  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS camera_restricted (
    camera_id   TEXT PRIMARY KEY,
    restricted  INTEGER NOT NULL DEFAULT 0,
    changed_at  TEXT NOT NULL
);
"""


class CameraStore:
    """Runtime camera roster, persisted."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

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
            # Removing a camera has to stop it being watched, or "remove"
            # means nothing. The scenes it already produced are kept.
            self._conn.execute(
                "DELETE FROM camera_restricted WHERE camera_id = ?", (camera_id,)
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

    # -- restricted areas ---------------------------------------------------
    #
    # Its own table rather than a `restricted` column on `camera`, because
    # most cameras have no row in `camera` at all: the baseline roster comes
    # from engine.yaml and only what the console added since is stored here.
    # A column could therefore never be written for the very cameras a site
    # starts with — the toggle 404'd on every one of them.
    #
    # Inserting a stub `camera` row instead would be worse: `merge_cameras`
    # lets a stored row win a clash, so flipping a toggle would quietly freeze
    # that camera's name, fps and features at whatever they were, and later
    # edits to engine.yaml would stop taking effect with nothing to say why.

    def set_restricted(self, camera_id: str, restricted: bool) -> None:
        """Mark a camera's whole frame a restricted area, or stop.

        Accepts any id: this table knows nothing about which cameras exist,
        and the roster — engine.yaml plus this store — is what the caller
        checks before writing. Returning a "did that camera exist" answer from
        here would be an answer to a question it cannot see.
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO camera_restricted (camera_id, restricted, changed_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(camera_id) DO UPDATE SET "
                "  restricted = excluded.restricted, changed_at = excluded.changed_at",
                (camera_id, 1 if restricted else 0,
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def restricted_ids(self) -> set[str]:
        """Cameras whose whole frame is a restricted area, right now."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT camera_id FROM camera_restricted WHERE restricted = 1"
            ).fetchall()
        return {row["camera_id"] for row in rows}

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
