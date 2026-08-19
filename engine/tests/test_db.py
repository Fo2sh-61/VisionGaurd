"""How the database gets opened, and why it is opened only one way.

The rule these defend: **a write that succeeded must not be refused because
something else was reading at the same time.** The engine has five separate
connections onto one file and several writer threads — recognition writes a
sighting while counting writes a sample while the API reads the register.

Under the default rollback journal that combination fails outright. A reader
holding an open read transaction makes a writer's commit raise `database is
locked`, and `test_a_held_reader_does_not_refuse_a_writer` below fails without
WAL for exactly that reason. It is dropped events, not slowness, and a dropped
sighting is a child missing from a register with nothing in the log to say so.

One correction to F4 as written in `docs/PLAN.md`: the stores were *not*
missing a busy timeout. Python's `sqlite3.connect` defaults `timeout=5.0`,
which sets `busy_timeout` to 5000ms already. The factory sets it explicitly
anyway so the value is visible and pinned rather than inherited, but WAL and
`foreign_keys` are the two settings that actually change behaviour here.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import numpy as np
import pytest

from vg import db
from vg.events.appearance import AppearanceStore
from vg.events.counts import AreaCountStore
from vg.events.sightings import SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.store import CameraStore

MODEL = "sface"


def pragmas(conn: sqlite3.Connection) -> tuple[str, int, int]:
    return (
        conn.execute("PRAGMA journal_mode").fetchone()[0],
        conn.execute("PRAGMA busy_timeout").fetchone()[0],
        conn.execute("PRAGMA foreign_keys").fetchone()[0],
    )


@pytest.fixture
def tmp() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# -- the factory ------------------------------------------------------------


def test_the_factory_sets_all_three(tmp: Path):
    conn = db.connect(tmp / "v.db")
    try:
        assert pragmas(conn) == ("wal", db.BUSY_TIMEOUT_MS, 1)
    finally:
        conn.close()


def test_the_factory_makes_the_directory(tmp: Path):
    """A fresh install has no `engine/data/` until something opens the database."""
    conn = db.connect(tmp / "nested" / "deeper" / "v.db")
    try:
        assert (tmp / "nested" / "deeper" / "v.db").exists()
    finally:
        conn.close()


def test_rows_come_back_by_name(tmp: Path):
    """Every store relied on `row_factory` before; the factory owns it now."""
    conn = db.connect(tmp / "v.db")
    try:
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('x')")
        assert conn.execute("SELECT a FROM t").fetchone()["a"] == "x"
    finally:
        conn.close()


# -- every store, not just most of them -------------------------------------


def test_every_store_is_routed_through_the_factory(tmp: Path):
    """F4 was five connections, only one of which was configured.

    A single unconfigured connection is enough to lose a write, so this asserts
    the whole set rather than trusting that a new store remembered.
    """
    path = tmp / "visionguard.db"
    stores = [
        SightingStore(path),
        AreaCountStore(path),
        AppearanceStore(path),
        CameraStore(path),
        FaceGallery(path, model=MODEL, threshold=0.363),
    ]
    try:
        for store in stores:
            mode, timeout, fk = pragmas(store._conn)
            assert mode == "wal", f"{type(store).__name__} is not in WAL"
            assert timeout == db.BUSY_TIMEOUT_MS, f"{type(store).__name__} has no busy timeout"
            assert fk == 1, f"{type(store).__name__} does not enforce foreign keys"
    finally:
        for store in stores:
            store.close()


# -- the failure this actually prevents -------------------------------------


def test_a_held_reader_does_not_refuse_a_writer(tmp: Path):
    """The F4 regression, and the reason WAL is not optional.

    The attendance page holds a read open while recognition writes to the same
    table. Under the rollback journal the writer's commit is refused with
    `database is locked` — verified: this test fails with `journal_mode=delete`
    and passes with WAL. The busy timeout does not save it, because the reader
    is not going to let go.
    """
    path = tmp / "v.db"
    writer = db.connect(path)
    reader = None
    try:
        writer.execute("CREATE TABLE sighting_like (a INTEGER)")
        writer.execute("INSERT INTO sighting_like VALUES (1)")
        writer.commit()

        reader = db.connect(path)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sighting_like").fetchone()

        # The write must land while that read is still open.
        writer.execute("INSERT INTO sighting_like VALUES (2)")
        writer.commit()

        reader.rollback()
        assert reader.execute("SELECT count(*) FROM sighting_like").fetchone()[0] == 2
    finally:
        writer.close()
        if reader is not None:
            reader.close()


def test_two_writer_threads_both_land(tmp: Path):
    """Several feature workers write at once; none of them may be dropped.

    This one passed before the change too — Python's default `timeout=5.0`
    already covers it. It is here because the factory now sets the timeout
    explicitly, and a later `timeout=0` or a changed default would silently
    reintroduce the failure this whole module is about.
    """
    path = tmp / "v.db"
    setup = db.connect(path)
    setup.execute("CREATE TABLE t (who TEXT)")
    setup.commit()
    setup.close()

    failures: list[BaseException] = []
    barrier = threading.Barrier(4)

    def write(who: str):
        conn = db.connect(path)
        try:
            barrier.wait(timeout=10)
            for _ in range(25):
                conn.execute("INSERT INTO t VALUES (?)", (who,))
                conn.commit()
        except BaseException as exc:      # noqa: BLE001 - the point of the test
            failures.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=write, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not failures, f"a writer was refused: {failures[0]!r}"

    check = db.connect(path)
    try:
        assert check.execute("SELECT count(*) FROM t").fetchone()[0] == 100
    finally:
        check.close()


def test_deleting_a_person_takes_their_vectors(tmp: Path):
    """`ON DELETE CASCADE` is inert unless the connection enforces it.

    Biometric erasure that silently leaves the vectors behind is the worst
    possible way for this pragma to be missing.
    """
    gallery = FaceGallery(tmp / "v.db", model=MODEL, threshold=0.363)
    try:
        gallery.add_person("p1", "Test Person")
        gallery.add_embedding("p1", _unit(), MODEL)
        assert _embedding_count(gallery) == 1

        assert gallery.remove_person("p1")
        assert _embedding_count(gallery) == 0
    finally:
        gallery.close()


def _unit() -> np.ndarray:
    v = np.ones(128, dtype=np.float32)
    return v / np.linalg.norm(v)


def _embedding_count(gallery: FaceGallery) -> int:
    return gallery._conn.execute("SELECT count(*) FROM face_embedding").fetchone()[0]
