"""Site settings an administrator can change from the console.

One small table, `site_setting`, in the engine's own SQLite file, beside the
alert tables. It holds **only the keys somebody has saved**. Anything not in it
comes from `engine.yaml`, which is the seed: Settings overlays the file, and
deleting a row would hand the file's value back.

`overlay()` is the one place that turns saved values into effective hours and
refuses combinations that cannot work. The store itself only keeps text; the
rules live in `HoursConfig.problem()` so startup and a save apply the same ones.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from vg import db
from vg.config import HoursConfig, _parse_time

log = logging.getLogger(__name__)

#: What may be saved. `name` is the school's name; the rest are `HoursConfig`.
KEYS = ("name", "hours_from", "hours_to", "late_cutoff",
        "term_from", "term_to", "working_days")

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);
"""


class SiteSettingsStore:
    """Key/value rows. One connection, one lock, like every store here."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()

    def get_all(self) -> dict:
        """Every saved key. `working_days` comes back as a list of ints."""
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM site_setting").fetchall()
        saved: dict = {}
        for row in rows:
            if row["key"] not in KEYS:
                continue
            saved[row["key"]] = (json.loads(row["value"])
                                 if row["key"] == "working_days" else row["value"])
        return saved

    def save(self, values: dict, actor: str) -> None:
        """Write these keys, all or none. Unknown keys are refused."""
        unknown = [k for k in values if k not in KEYS]
        if unknown:
            raise ValueError(f"not a site setting: {', '.join(sorted(unknown))}")
        at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            for key, value in values.items():
                text = json.dumps(sorted(set(value))) if key == "working_days" else str(value)
                self._conn.execute(
                    "INSERT INTO site_setting (key, value, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (key, text, at, actor))


def overlay(base: HoursConfig, saved: dict) -> HoursConfig:
    """`base` with the saved values laid over it. ValueError says what is wrong."""
    changes: dict = {}
    for key, field in (("hours_from", "start"), ("hours_to", "end"),
                       ("late_cutoff", "late_cutoff")):
        if key in saved:
            changes[field] = _parse_time(saved[key], key)
    for key in ("term_from", "term_to"):
        if key in saved:
            text = str(saved[key]).strip()
            if text:
                try:
                    date.fromisoformat(text)
                except ValueError:
                    raise ValueError(f"{key}: {text!r} is not a date (YYYY-MM-DD)") from None
            changes[key] = text
    if "working_days" in saved:
        changes["working_days"] = frozenset(saved["working_days"])
    hours = dataclasses.replace(base, **changes)
    reason = hours.problem()
    if reason:
        raise ValueError(reason)
    return hours


def checked_changes(base: HoursConfig, saved: dict, changes: dict) -> dict:
    """The changes to store, after checking them against what is already saved.

    Raises ValueError with the reason; nothing is touched. The name is trimmed
    and may not be blank, because a blank one would hide the school's own name
    in the top bar.
    """
    changes = dict(changes)
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
        if not changes["name"]:
            raise ValueError("the site name cannot be blank")
    overlay(base, {**saved, **changes})
    return changes
