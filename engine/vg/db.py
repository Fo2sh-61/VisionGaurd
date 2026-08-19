"""One way to open the database.

Every store here — the face gallery, sightings, appearance paths, headcounts
and the camera roster — is a separate SQLite connection onto the same file,
written by several threads at once. Recognition writes a sighting while
counting writes a sample while the API reads the register.

Under SQLite's default rollback journal that combination does not merely go
slowly, it fails: a reader holding an open read transaction makes a writer's
commit raise `database is locked`, and the write is gone. A dropped sighting is
a child missing from a register with nothing in the log to explain it. That is
the failure this module exists to remove.

Three settings, applied to every connection because one unconfigured
connection is enough to lose a write:

**WAL.** Readers stop blocking writers. This is the setting that fixes the
above; `engine/tests/test_db.py` fails without it and passes with it. WAL is a
property of the database file rather than the connection, so the first opener
sets it for everyone — it is still issued on each connection because which one
opens first is not fixed.

**busy_timeout.** A writer that finds the lock held waits its turn. Note that
this was *not* actually missing before: Python's `sqlite3.connect` defaults to
`timeout=5.0`, which sets `busy_timeout` to 5000ms already, so `docs/PLAN.md`
F4 is half right. It is set explicitly here so the value is pinned and visible
instead of inherited from a default that could change.

**foreign_keys.** SQLite ignores foreign keys unless asked, per connection, and
only the gallery was asking. `face_embedding` cascades from `person`, so on any
other connection an erasure request deletes the name and silently leaves the
biometric vectors behind — the worst possible way for a pragma to be missing.

Sidecar `-wal` and `-shm` files appear next to the database. They live under
`engine/data/`, which git already ignores.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: How long a blocked writer waits before giving up. Longer than any write in
#: the engine, short enough that a real deadlock still shows up as an error.
BUSY_TIMEOUT_MS = 5000


def connect(database: Path | str) -> sqlite3.Connection:
    """Open the database the one supported way.

    `check_same_thread=False` because feature workers and the API share a
    connection; each store guards its own with a lock.
    """
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
