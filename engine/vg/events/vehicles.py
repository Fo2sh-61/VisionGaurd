"""The vehicle register, and every pass through a gate.

Two tables. The project this technique came from used five; three of those
describe things VisionGuard already records, so they are not here:

    alerts          -> `attention()` / `acknowledge()` already exist
    camera_status   -> `CameraRegistry` already tracks it
    visits          -> derived, see `visits()` below

**Visits are computed, not stored.** A stored visits table needs a row opened
on entry, closed on exit, an `open` flag, and an orphan sweep on shutdown for
the ones that never closed — persistent state describing something the pass
log already records in full, and state that can therefore disagree with it. A
window function over `vehicle_pass` gives the same answer with nothing to
corrupt and no lifecycle to get wrong. At school scale — tens of passes an
hour — this is not a performance question.

**`plate` is canonical and `UNIQUE`, and that is the whole design.** A plate
typed on an English keyboard, one imported from a spreadsheet in Arabic
digits, and one read off a camera must land on the same row or a school ends
up with three records per car. `platetext.normalize` makes them equal; the
constraint makes it a guarantee rather than an intention — checking first and
inserting second still races two simultaneous imports.

**Status is frozen onto the pass when it is written and never recomputed.**
Blacklisting a car today must not rewrite what happened yesterday.
"""

from __future__ import annotations

import csv
import io
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from vg import db, platetext

log = logging.getLogger(__name__)

#: The only categories a registered vehicle may have.
#:
#: Four, not the five the gate-anpr project used: `resident` is dropped
#: because it means nothing at a school. A parent is a Visitor, with their
#: child's class in the unit field. Validated in Python the way `ROLES` is in
#: `auth/store.py`, so an unknown value raises rather than being stored.
CATEGORIES = ("staff", "visitor", "vip", "blacklist")

#: What a pass can be. Decided at write time, in this order — see `status_for`.
STATUSES = ("known", "unknown", "blacklist", "expired")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle (
    id            TEXT PRIMARY KEY,
    plate         TEXT NOT NULL UNIQUE,
    plate_display TEXT NOT NULL,
    owner_name    TEXT,
    phone         TEXT,
    unit          TEXT,
    category      TEXT NOT NULL,
    car_make      TEXT,
    car_colour    TEXT,
    valid_until   TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicle_category ON vehicle(category);

CREATE TABLE IF NOT EXISTS vehicle_pass (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,
    camera_id     TEXT NOT NULL,
    gate          INTEGER NOT NULL,
    direction     TEXT NOT NULL,
    plate         TEXT NOT NULL,
    plate_display TEXT NOT NULL,
    status        TEXT NOT NULL,
    -- SET NULL, never CASCADE. Removing a car from the register must keep
    -- its passes: that history is what a removal exists to preserve.
    vehicle_id    TEXT REFERENCES vehicle(id) ON DELETE SET NULL,
    confidence    REAL NOT NULL,
    votes         INTEGER NOT NULL,
    needs_review  INTEGER NOT NULL DEFAULT 0,
    snapshot      TEXT,
    plate_crop    TEXT,
    created_at    TEXT NOT NULL,
    -- Who typed this plate in by hand, and when. NULL means the reader's own
    -- answer. A person's correction outranks the reader's: once this is set,
    -- the automatic "the car got closer and reads better now" amendment
    -- leaves the row alone. Somebody looked at the photograph.
    corrected_by  TEXT,
    corrected_at  TEXT,
    -- When the reader was done with this pass: its car left the camera, so
    -- the reading could not change again. NULL while it still can. The gate
    -- alert waits for this (spec 013); a NULL left by a stopped engine is
    -- closed at the next start (`close_unfinished`).
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_pass_at    ON vehicle_pass(at DESC);
CREATE INDEX IF NOT EXISTS ix_pass_plate ON vehicle_pass(plate, at DESC);
CREATE INDEX IF NOT EXISTS ix_pass_gate  ON vehicle_pass(gate, at DESC);

-- A dismissed alert. **Alerts themselves are never stored**: one exists while
-- a qualifying pass of today has no row here, which is why there is no alert
-- lifecycle to drift out of step with the log it describes.
--
-- The dismissal IS stored, because it is a record — "recorded too, under your
-- name" is a promise the page makes, and RAM would forget it at the next
-- restart. The audit entry is written BEFORE this row, and there is no delete
-- path: an acknowledgement cannot be taken back, here or anywhere else.
--
-- CASCADE, unlike vehicle_pass above, and for the opposite reason: this row
-- describes a pass rather than preserving one, so when an administrator
-- deletes a pass its dismissal has nothing left to be about.
CREATE TABLE IF NOT EXISTS vehicle_alert_ack (
    pass_id       TEXT PRIMARY KEY REFERENCES vehicle_pass(id) ON DELETE CASCADE,
    by_who        TEXT NOT NULL,
    at            TEXT NOT NULL,
    -- 1 when the resolving action was taken (registered / renewed), 0 for a
    -- bare dismissal. The difference is worth keeping: "I dealt with it" and
    -- "not worth acting on" are different answers to the same alert.
    action_taken  INTEGER NOT NULL DEFAULT 0
);

-- What the register tab's "last import" line is allowed to say.
--
-- The design draws "Last import: 2,140 rows · 6 skipped · 12 Aug". That is
-- either a fact or it is absent (P6-FR-053), and the audit log cannot be the
-- source because it still lives in RAM until P3. So the importer records its
-- own run, inside the same transaction as the rows it wrote.
CREATE TABLE IF NOT EXISTS vehicle_import_run (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,
    added         INTEGER NOT NULL,
    updated       INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL,
    rejected      INTEGER NOT NULL,
    by_who        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_import_at ON vehicle_import_run(at DESC);

-- A visit somebody ended by hand: "this car is gone". The entry pass stays
-- exactly as it was seen; this row only says a person closed the visit, and
-- who. Never an exit pass: nobody saw the car leave, so no exit is invented.
-- The audit entry is written BEFORE this row. CASCADE like vehicle_alert_ack:
-- the mark describes an entry pass, so it has nothing left to be about when
-- an administrator deletes that pass.
CREATE TABLE IF NOT EXISTS vehicle_gone (
    entry_pass_id TEXT PRIMARY KEY REFERENCES vehicle_pass(id) ON DELETE CASCADE,
    by_who        TEXT NOT NULL,
    at            TEXT NOT NULL
);
"""


class PlateTaken(ValueError):
    """That plate already has a register entry. Safe to show a user."""


@dataclass(frozen=True)
class Vehicle:
    """One registered car."""

    id: str
    plate: str
    plate_display: str
    owner_name: str | None = None
    phone: str | None = None
    unit: str | None = None
    category: str = "visitor"
    car_make: str | None = None
    car_colour: str | None = None
    valid_until: str | None = None
    notes: str | None = None
    last_seen: datetime | None = None

    @property
    def blacklisted(self) -> bool:
        return self.category == "blacklist"

    def expired_on(self, today: date) -> bool:
        """Has this permit lapsed?

        Computed rather than stored: a stored "expired" flag needs a nightly
        job to stay true and is wrong between midnight and whenever that job
        runs.
        """
        if not self.valid_until:
            return False
        try:
            return date.fromisoformat(self.valid_until) < today
        except ValueError:
            return False


@dataclass(frozen=True)
class VehiclePass:
    """One car, through one gate, once."""

    id: str
    at: datetime
    camera_id: str
    gate: int
    direction: str
    plate: str
    plate_display: str
    status: str
    confidence: float
    votes: int
    needs_review: bool
    vehicle_id: str | None = None
    owner_name: str | None = None
    unit: str | None = None
    snapshot: str | None = None
    plate_crop: str | None = None
    #: Who typed this plate in by hand. None means the reader's own answer.
    corrected_by: str | None = None
    #: Width in pixels of the plate in the photograph the reading came from.
    #: None for a pass recorded before this was kept: unknown, never 0.
    plate_width: int | None = None
    #: What the reader itself read, kept when a person corrected the plate.
    #: None until a correction happens.
    read_plate: str | None = None

    @property
    def has_snapshot(self) -> bool:
        """The row outlives its images by thirty days. Never assume the file."""
        return bool(self.snapshot) and Path(self.snapshot).is_file()


@dataclass(frozen=True)
class Visit:
    """An entry, and the exit it was paired with — if there was one."""

    plate: str
    plate_display: str
    entered: datetime
    entry_gate: int
    left_at: datetime | None = None
    exit_gate: int | None = None
    owner_name: str | None = None
    unit: str | None = None
    category: str | None = None
    #: True when the visit was closed by the car being seen entering again
    #: rather than by an observed exit. Reported, never presented as observed.
    inferred: bool = False
    #: The passes this visit was derived from, so a row can show the
    #: photograph that proves it. The images stay where they are — one store,
    #: one retention rule — and the console links at them by pass id.
    #:
    #: `*_has_snapshot` is separate from the id because an image is deleted at
    #: thirty days while its pass row is kept for ever. False means "no
    #: picture to show", never "no such pass".
    entry_pass_id: str | None = None
    exit_pass_id: str | None = None
    entry_has_snapshot: bool = False
    exit_has_snapshot: bool = False
    #: Who ended this visit by hand ("this car is gone"). Distinct from
    #: `inferred` (the car was seen entering again) and from an observed exit.
    ended_by: str | None = None

    def minutes(self, now: datetime) -> float:
        end = self.left_at or now
        return round((end - self.entered).total_seconds() / 60.0, 1)

    @property
    def inside(self) -> bool:
        return self.left_at is None


def status_for(vehicle: Vehicle | None, today: date) -> str:
    """What a pass by this car reads as.

    **Blacklist outranks expiry**, deliberately. A withdrawn contractor whose
    permit also lapsed is a security event, not a quiet amber row.
    """
    if vehicle is None:
        return "unknown"
    if vehicle.blacklisted:
        return "blacklist"
    if vehicle.expired_on(today):
        return "expired"
    return "known"


class VehicleStore:
    """The register and the pass log. One connection, guarded."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._add_missing_columns()
        self._conn.commit()
        #: Called with the `VehiclePass` once the reader is done with it - see
        #: `finish_pass`. Alert delivery (spec 013) sets it and reads only the
        #: facts a message may carry - never the owner's name. Not the worker's
        #: `on_pass`, which is what writes the pass in the first place.
        self.on_pass = None

    def _add_missing_columns(self) -> None:
        """Bring an existing database up to the current shape.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a new column never reaches a gate that has been running —
        and gates are exactly the thing nobody wants to wipe to get a feature.
        Adding by name, guarded by what is actually there, is idempotent and
        needs no version number to go stale.
        """
        for table, column, ddl in (
            # Who typed this plate in by hand. NULL means the reader's own
            # answer, which is what lets an automatic correction know to leave
            # a human's correction alone.
            ("vehicle_pass", "corrected_by", "TEXT"),
            ("vehicle_pass", "corrected_at", "TEXT"),
            # How wide the plate was in the photograph, in pixels: the
            # reader's own measure of how good a look it had. NULL = unknown.
            ("vehicle_pass", "plate_width", "INTEGER"),
            # What the reader read before a person corrected it.
            ("vehicle_pass", "read_plate", "TEXT"),
        ):
            existing = {r["name"] for r in
                        self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        # When the reader was done with each pass. Every pass a running gate
        # already holds is done - the code before this column sent its alert at
        # the first reading - so they are marked as they are. Left NULL, the
        # first start after the upgrade would log each one as never sent.
        existing = {r["name"] for r in
                    self._conn.execute("PRAGMA table_info(vehicle_pass)")}
        if "finished_at" not in existing:
            self._conn.execute("ALTER TABLE vehicle_pass ADD COLUMN finished_at TEXT")
            self._conn.execute("UPDATE vehicle_pass SET finished_at = created_at")

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()

    # -- the register -------------------------------------------------------

    def add(
        self,
        plate: str,
        owner_name: str | None = None,
        phone: str | None = None,
        unit: str | None = None,
        category: str = "visitor",
        car_make: str | None = None,
        car_colour: str | None = None,
        valid_until: str | None = None,
        notes: str | None = None,
    ) -> Vehicle:
        """Register a vehicle. Raises `PlateTaken` on a duplicate.

        Normalising happens **outside** the lock, and the `UNIQUE` constraint
        decides the race rather than a read-then-write. Two simultaneous
        imports of the same list would otherwise both find nothing and both
        insert. Same reasoning as `auth/store.py::create_user`.
        """
        if category not in CATEGORIES:
            raise ValueError(
                f"unknown category: {category!r}; expected one of {CATEGORIES}")

        canonical = platetext.normalize(plate)
        if not canonical:
            raise ValueError("a vehicle needs a plate")

        record = Vehicle(
            id=uuid.uuid4().hex, plate=canonical,
            plate_display=platetext.display(canonical),
            owner_name=_clean(owner_name), phone=_clean(phone),
            unit=_clean(unit), category=category, car_make=_clean(car_make),
            car_colour=_clean(car_colour), valid_until=_clean(valid_until),
            notes=_clean(notes),
        )
        now = _iso(_now())
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO vehicle (id, plate, plate_display, owner_name,"
                    " phone, unit, category, car_make, car_colour, valid_until,"
                    " notes, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (record.id, record.plate, record.plate_display,
                     record.owner_name, record.phone, record.unit,
                     record.category, record.car_make, record.car_colour,
                     record.valid_until, record.notes, now, now),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise PlateTaken("That plate is already registered.") from exc

        log.info("registered %s as %s", platetext.transliterate(canonical),
                 record.category)
        return record

    def update(self, vehicle_id: str, **fields) -> Vehicle | None:
        """Change a register entry.

        Applies from the vehicle's **next** pass. Recorded passes keep the
        status they were written with — P6-FR-019.
        """
        allowed = {
            "owner_name", "phone", "unit", "category", "car_make",
            "car_colour", "valid_until", "notes", "plate",
        }
        changes = {k: v for k, v in fields.items() if k in allowed}
        if "category" in changes and changes["category"] not in CATEGORIES:
            raise ValueError(f"unknown category: {changes['category']!r}")

        if "plate" in changes:
            canonical = platetext.normalize(changes.pop("plate"))
            if not canonical:
                raise ValueError("a vehicle needs a plate")
            changes["plate"] = canonical
            changes["plate_display"] = platetext.display(canonical)

        if not changes:
            return self.vehicle(vehicle_id)

        changes["updated_at"] = _iso(_now())
        assignments = ", ".join(f"{k} = ?" for k in changes)
        try:
            with self._lock:
                self._conn.execute(
                    f"UPDATE vehicle SET {assignments} WHERE id = ?",
                    (*changes.values(), vehicle_id),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise PlateTaken("That plate is already registered.") from exc
        return self.vehicle(vehicle_id)

    def remove(self, vehicle_id: str) -> bool:
        """Delete a register entry. **Its passes are kept.**

        `ON DELETE SET NULL` on the pass table is what makes that true. The
        car keeps passing and is still photographed; from its next pass it is
        logged as not registered.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM vehicle WHERE id = ?", (vehicle_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def vehicle(self, vehicle_id: str) -> Vehicle | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM vehicle WHERE id = ?", (vehicle_id,)).fetchone()
        return _to_vehicle(row) if row else None

    def by_plate(self, plate: str) -> Vehicle | None:
        """Look a car up by any spelling of its plate."""
        canonical = platetext.normalize(plate)
        if not canonical:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM vehicle WHERE plate = ?", (canonical,)).fetchone()
        return _to_vehicle(row) if row else None

    def search(self, query: str = "", category: str = "") -> list[Vehicle]:
        """The register, filtered. Matches plate, owner, phone or unit.

        The plate is matched on its **canonical** form as well as raw, so
        searching `1234` finds a car whose plate was read as `١٢٣٤`.
        """
        sql = ["SELECT * FROM vehicle"]
        where, params = [], []

        if category and category != "all":
            where.append("category = ?")
            params.append(category)

        text = (query or "").strip()
        if text:
            canonical = platetext.normalize(text)
            like = f"%{text}%"
            clause = ("owner_name LIKE ? OR phone LIKE ? OR unit LIKE ? "
                      "OR plate LIKE ? OR plate_display LIKE ?")
            params += [like, like, like, like, like]
            if canonical:
                clause += " OR plate LIKE ?"
                params.append(f"%{canonical}%")
            where.append(f"({clause})")

        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY owner_name IS NULL, owner_name, plate")

        with self._lock:
            rows = self._conn.execute(" ".join(sql), params).fetchall()
        return [_to_vehicle(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) AS n FROM vehicle").fetchone()["n"])

    # -- passes -------------------------------------------------------------

    def record_pass(
        self,
        at: datetime,
        camera_id: str,
        gate: int,
        direction: str,
        plate: str,
        confidence: float,
        votes: int,
        needs_review: bool,
        today: date,
        snapshot: str | None = None,
        plate_crop: str | None = None,
        plate_width: int | None = None,
    ) -> VehiclePass:
        """Write one pass. The status is decided here and never revisited."""
        canonical = platetext.normalize(plate)
        vehicle = self.by_plate(canonical)
        status = status_for(vehicle, today)

        record = VehiclePass(
            id=uuid.uuid4().hex, at=at, camera_id=camera_id, gate=int(gate),
            direction=direction, plate=canonical,
            plate_display=platetext.display(canonical), status=status,
            confidence=float(confidence), votes=int(votes),
            needs_review=bool(needs_review),
            vehicle_id=vehicle.id if vehicle else None,
            owner_name=vehicle.owner_name if vehicle else None,
            unit=vehicle.unit if vehicle else None,
            snapshot=snapshot, plate_crop=plate_crop,
            plate_width=int(plate_width) if plate_width else None,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO vehicle_pass (id, at, camera_id, gate, direction,"
                " plate, plate_display, status, vehicle_id, confidence, votes,"
                " needs_review, snapshot, plate_crop, created_at, plate_width)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.id, _iso(at), camera_id, record.gate, direction,
                 record.plate, record.plate_display, status, record.vehicle_id,
                 record.confidence, record.votes, int(record.needs_review),
                 snapshot, plate_crop, _iso(_now()), record.plate_width),
            )
            self._conn.commit()
        return record

    def passes(
        self,
        limit: int = 100,
        plate: str = "",
        gate: int | None = None,
        direction: str = "",
        status: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        q: str = "",
        exact: bool = False,
    ) -> list[VehiclePass]:
        """The pass log, newest first, filtered.

        `q` is the owner search: owner, unit, plate (raw, display and
        canonical, so `1234` finds `١٢٣٤`). `exact` makes `plate` mean this
        plate and no other, not a substring.
        """
        sql = [
            "SELECT p.*, v.owner_name AS v_owner, v.unit AS v_unit",
            "FROM vehicle_pass p LEFT JOIN vehicle v ON v.id = p.vehicle_id",
        ]
        where, params = [], []

        if plate and exact:
            where.append("p.plate = ?")
            params.append(platetext.normalize(plate) or plate)
        elif plate:
            canonical = platetext.normalize(plate)
            where.append("(p.plate LIKE ? OR p.plate_display LIKE ?)")
            params += [f"%{canonical or plate}%", f"%{plate}%"]
        text = (q or "").strip()
        if text:
            like = f"%{text}%"
            canonical = platetext.normalize(text)
            clause = ("v.owner_name LIKE ? OR v.unit LIKE ? "
                      "OR p.plate LIKE ? OR p.plate_display LIKE ?")
            params += [like, like, like, like]
            if canonical:
                clause += " OR p.plate LIKE ?"
                params.append(f"%{canonical}%")
            where.append(f"({clause})")
        if gate is not None:
            where.append("p.gate = ?")
            params.append(int(gate))
        if direction:
            where.append("p.direction = ?")
            params.append(direction)
        if status:
            where.append("p.status = ?")
            params.append(status)
        if since is not None:
            where.append("p.at >= ?")
            params.append(_iso(since))
        if until is not None:
            where.append("p.at < ?")
            params.append(_iso(until))

        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY p.at DESC LIMIT ?")
        params.append(int(limit))

        with self._lock:
            rows = self._conn.execute(" ".join(sql), params).fetchall()
        return [_to_pass(r) for r in rows]

    # -- alerts -------------------------------------------------------------
    #
    # An alert is not a row. It is a today's pass whose status needs a person
    # and which nobody has dismissed yet, so there is no alert lifecycle to
    # drift out of step with the log it describes — the same argument that
    # keeps visits derived rather than stored.

    def dismissed_alerts(self, since: datetime | None = None) -> set[str]:
        """Pass ids somebody has already dealt with."""
        sql = ("SELECT a.pass_id FROM vehicle_alert_ack a"
               " JOIN vehicle_pass p ON p.id = a.pass_id")
        params: list = []
        if since is not None:
            sql += " WHERE p.at >= ?"
            params.append(_iso(since))
        with self._lock:
            return {r["pass_id"]
                    for r in self._conn.execute(sql, params).fetchall()}

    def dismiss_alert(self, pass_id: str, by_who: str,
                      action_taken: bool = False) -> bool:
        """Record that a person dealt with this alert. False if already done.

        **The audit entry is written by the caller, before this runs.** Same
        order as `delete_pass`, for the same reason: the record of who did
        something must not depend on the something having succeeded.

        There is no undo. An acknowledgement that can be withdrawn is not an
        acknowledgement, and nothing else in this product lets one be.
        """
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM vehicle_pass WHERE id = ?",
                (pass_id,)).fetchone()
            if exists is None:
                raise KeyError(pass_id)
            already = self._conn.execute(
                "SELECT 1 FROM vehicle_alert_ack WHERE pass_id = ?",
                (pass_id,)).fetchone()
            if already is not None:
                return False
            with self._conn:
                self._conn.execute(
                    "INSERT INTO vehicle_alert_ack (pass_id, by_who, at,"
                    " action_taken) VALUES (?, ?, ?, ?)",
                    (pass_id, by_who, _iso(_now()), int(bool(action_taken))))
        return True

    def near_matches(self, plate: str) -> list[Vehicle]:
        """Registered cars within one misread of this plate.

        Compared in Python rather than in SQL because the rule is
        `platetext.same_plate` — the same one-edit test the frame voting uses,
        so a near miss means the same thing in both places. The register is a
        couple of thousand rows; this is a scan and it does not need to be
        anything cleverer.

        **The caller must refuse to suggest anything unless there is exactly
        one.** Two candidates is a coin toss, and putting a wrong name against
        a stranger's car is worse than saying nothing.
        """
        canonical = platetext.normalize(plate)
        if not canonical:
            return []
        with self._lock:
            rows = self._conn.execute("SELECT * FROM vehicle").fetchall()
        return [_to_vehicle(r) for r in rows
                if r["plate"] != canonical
                and platetext.same_plate(canonical, r["plate"])]

    def amend_pass(self, pass_id: str, plate: str, confidence: float,
                   votes: int, needs_review: bool, today: date,
                   snapshot: str | None = None,
                   plate_crop: str | None = None,
                   plate_width: int | None = None) -> VehiclePass | None:
        """Correct a reading as more of the same car is seen.

        **This is not rewriting history.** The car arrived once; the row is
        that arrival, and the plate on it is the system's best reading of it.
        A gate sees a car for five to ten seconds and the last look is far
        better than the first, so refusing to improve the row would mean
        deliberately keeping the worst answer of the fifty available.

        What is frozen stays frozen — `at` and `direction` are what happened.
        The **status is recomputed**, and it has to be: a corrected plate may
        now match a registered car, or a blacklisted one, and leaving the
        stale verdict beside the new plate would be the worst of both.

        The photograph is replaced only when a better one came with the
        correction; the old files are removed so a corrected pass does not
        leak images nothing points at.
        """
        canonical = platetext.normalize(plate)
        if not canonical:
            return None
        vehicle = self.by_plate(canonical)
        status = status_for(vehicle, today)

        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot, plate_crop, corrected_by FROM vehicle_pass"
                " WHERE id = ?", (pass_id,)).fetchone()
            if row is None:
                return None
            if row["corrected_by"]:
                # **A person outranks the reader.** Somebody looked at the
                # photograph and typed what they saw; a later frame reading
                # differently is not new information about that, and silently
                # undoing their correction while they watch would be the most
                # infuriating behaviour this page could have.
                return self.pass_by_id(pass_id)
            with self._conn:
                self._conn.execute(
                    "UPDATE vehicle_pass SET plate = ?, plate_display = ?,"
                    " status = ?, vehicle_id = ?, confidence = ?, votes = ?,"
                    " needs_review = ?"
                    + (", snapshot = ?, plate_crop = ?, plate_width = ?"
                       if snapshot else "")
                    + " WHERE id = ?",
                    (canonical, platetext.display(canonical), status,
                     vehicle.id if vehicle else None, float(confidence),
                     int(votes), int(bool(needs_review)))
                    + ((snapshot, plate_crop,
                        int(plate_width) if plate_width else None)
                       if snapshot else ())
                    + (pass_id,))
            if snapshot:
                for old in (row["snapshot"], row["plate_crop"]):
                    if old not in (snapshot, plate_crop):
                        _unlink(old)
        return self.pass_by_id(pass_id)

    def finish_pass(self, pass_id: str) -> VehiclePass | None:
        """The reader is done with this pass: its car has left the camera.

        The row now holds the best reading there will be, so this - not
        `record_pass` - is what hands it to `on_pass`. The first three frames
        that agree are the worst look the camera gets, and `amend_pass` can
        still turn an unregistered car into a blacklisted one; a message sent
        from the first reading would be the wrong message whenever the reader
        corrects itself. A few seconds late and right (decided 11 Sep 2026).

        A person's correction (`set_plate`) does not come through here:
        somebody has already looked at the photograph.

        Once only: a pass already finished, or closed at a start, hands
        nothing on. Read before it is marked, so a failed read leaves the pass
        unfinished for the next start to close rather than silently done.
        """
        record = self.pass_by_id(pass_id)
        if record is None:
            return None
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE vehicle_pass SET finished_at = ?"
                " WHERE id = ? AND finished_at IS NULL", (_iso(_now()), pass_id))
            self._conn.commit()
        # A failing hook costs a message, never the pass. A pass a person has
        # already corrected sends nothing: somebody looked at the photograph,
        # and a message built from it would be the reader's guess, not theirs.
        if (cursor.rowcount == 1 and self.on_pass is not None
                and not record.corrected_by):
            try:
                self.on_pass(record)
            except Exception:
                log.exception("pass %s: the alert hook failed", pass_id[:8])
        return record

    def close_unfinished(self, before: datetime) -> list[VehiclePass]:
        """Passes the last run recorded but never finished, now closed.

        A hard kill runs no `finally`, so a car still in view when the engine
        stopped never had its reading finished. Closed here, at the next start,
        and handed back so the caller can log their messages as not sent -
        never send them late. `before` is this start: a pass the new reader
        wrote since is still its to finish.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.*, v.owner_name AS v_owner, v.unit AS v_unit"
                " FROM vehicle_pass p LEFT JOIN vehicle v ON v.id = p.vehicle_id"
                " WHERE p.finished_at IS NULL AND p.created_at < ?"
                " ORDER BY p.at", (_iso(before),)).fetchall()
            self._conn.executemany(
                "UPDATE vehicle_pass SET finished_at = ? WHERE id = ?",
                [(_iso(_now()), row["id"]) for row in rows])
            self._conn.commit()
        return [_to_pass(row) for row in rows]

    def set_plate(self, pass_id: str, plate: str, by_who: str,
                  today: date) -> VehiclePass | None:
        """A person read the photograph and typed what it says.

        **This wins over anything the reader decides afterwards**, which is
        what `corrected_by` records. The status is recomputed for the same
        reason an automatic correction recomputes it: the typed plate may
        match a registered car, or a blacklisted one, and a stale verdict
        beside a corrected plate is the worst of both.

        What happened is untouched — the time, the gate, the direction and the
        photograph are the event. Only the reading of the plate changes, and
        the row now says a human made it.
        """
        canonical = platetext.normalize(plate)
        if not canonical:
            raise ValueError(
                "That is not a readable plate. It needs at least one letter "
                "or one digit.")
        vehicle = self.by_plate(canonical)
        status = status_for(vehicle, today)

        with self._lock:
            if self._conn.execute("SELECT 1 FROM vehicle_pass WHERE id = ?",
                                  (pass_id,)).fetchone() is None:
                return None
            with self._conn:
                self._conn.execute(
                    "UPDATE vehicle_pass SET plate = ?, plate_display = ?,"
                    " status = ?, vehicle_id = ?, needs_review = 0,"
                    # The right side reads the OLD plate: the first fix keeps
                    # what the reader read, a second fix keeps that first one.
                    " read_plate = COALESCE(read_plate, plate),"
                    " corrected_by = ?, corrected_at = ? WHERE id = ?",
                    (canonical, platetext.display(canonical), status,
                     vehicle.id if vehicle else None, by_who, _iso(_now()),
                     pass_id))
        return self.pass_by_id(pass_id)

    def pass_by_id(self, pass_id: str) -> VehiclePass | None:
        """One pass, by id. Indexed lookup rather than a scan of the log."""
        with self._lock:
            row = self._conn.execute(
                "SELECT p.*, v.owner_name AS v_owner, v.unit AS v_unit"
                " FROM vehicle_pass p LEFT JOIN vehicle v ON v.id = p.vehicle_id"
                " WHERE p.id = ?", (pass_id,)).fetchone()
        return _to_pass(row) if row else None

    def delete_pass(self, pass_id: str) -> bool:
        """Remove one pass, and the two photographs kept with it.

        **This is permanent, and it is meant to be.** There is no hidden flag
        and no bin: a row somebody deleted must not keep answering "who is
        inside", and visits are derived from this table, so a soft delete
        would need every query to remember to exclude it. The one that
        forgets is the bug.

        The audit entry is written by the caller, **before** this runs, and
        the audit cannot be deleted. That is what keeps the log honest without
        keeping the row.

        False means there was no such pass. Deleting twice is not an error
        worth a different answer.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot, plate_crop FROM vehicle_pass WHERE id = ?",
                (pass_id,)).fetchone()
            if row is None:
                return False
            # The files first: a row deleted with its images left behind
            # leaves two orphans nothing will ever point at again, and the
            # retention sweep only knows about files a row still names.
            _unlink(row["snapshot"])
            _unlink(row["plate_crop"])
            self._conn.execute("DELETE FROM vehicle_pass WHERE id = ?",
                               (pass_id,))
            self._conn.commit()
        return True

    def counts_since(self, since: datetime) -> dict:
        """The Live-tab tiles. Every value real or absent, never a filler."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT direction, status, needs_review FROM vehicle_pass"
                " WHERE at >= ?", (_iso(since),)).fetchall()

        return {
            "entered": sum(1 for r in rows if r["direction"] == "entry"),
            "left": sum(1 for r in rows if r["direction"] == "exit"),
            "unknown": sum(1 for r in rows if r["status"] == "unknown"),
            "blacklist": sum(1 for r in rows if r["status"] == "blacklist"),
            "expired": sum(1 for r in rows if r["status"] == "expired"),
            "needs_review": sum(1 for r in rows if r["needs_review"]),
        }

    # -- visits, derived ----------------------------------------------------

    def visits(self, since: datetime | None = None,
               until: datetime | None = None) -> list[Visit]:
        """Entries paired with the exit that followed them, computed.

        `LEAD` over each plate's passes in time order. An entry whose next
        pass is an exit is a completed visit; an entry with nothing after it
        is a car still inside; an entry followed by **another entry** is a
        visit that closed without being seen to, which is reported as
        `inferred` rather than presented as observed.

        No table, no `open` flag, no orphan sweep — and no way for the answer
        to disagree with the passes it is computed from.
        """
        sql = """
            WITH ordered AS (
              SELECT p.plate, p.plate_display, p.at, p.direction, p.gate,
                     p.vehicle_id,
                     -- The pass ids come through the same window that
                     -- already walks these rows, so a visit can point at the
                     -- photographs that prove it without a second query.
                     p.id              AS entry_id,
                     p.snapshot        AS entry_snapshot,
                     LEAD(p.at)        OVER w AS next_at,
                     LEAD(p.direction) OVER w AS next_direction,
                     LEAD(p.gate)      OVER w AS next_gate,
                     LEAD(p.id)        OVER w AS next_id,
                     LEAD(p.snapshot)  OVER w AS next_snapshot
              FROM vehicle_pass p
              WINDOW w AS (PARTITION BY p.plate ORDER BY p.at)
            )
            SELECT o.*, v.owner_name, v.unit, v.category,
                   g.by_who AS gone_by, g.at AS gone_at
            FROM ordered o LEFT JOIN vehicle v ON v.id = o.vehicle_id
            LEFT JOIN vehicle_gone g ON g.entry_pass_id = o.entry_id
            WHERE o.direction = 'entry'
        """
        params: list = []
        if since is not None:
            sql += " AND o.at >= ?"
            params.append(_iso(since))
        if until is not None:
            # Bounded on the ENTRY, so a day's visits are the cars that came
            # in that day. A visit that ran past midnight still belongs to the
            # day it started, which is how somebody asking "what happened on
            # Tuesday" means it.
            sql += " AND o.at < ?"
            params.append(_iso(until))
        sql += " ORDER BY o.at DESC"

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        out: list[Visit] = []
        for row in rows:
            # A person's mark only closes a visit nothing else closed: an
            # observed exit or a re-entry that came later is better evidence.
            by_hand = (row["gone_by"] is not None
                       and row["next_direction"] is None)
            exited = row["next_direction"] == "exit"
            closed_by_reentry = row["next_direction"] == "entry"
            if by_hand:
                left_at = _parse(row["gone_at"])
            elif exited or closed_by_reentry:
                left_at = _parse(row["next_at"])
            else:
                left_at = None
            out.append(Visit(
                plate=row["plate"], plate_display=row["plate_display"],
                entered=_parse(row["at"]), entry_gate=row["gate"],
                left_at=left_at,
                exit_gate=row["next_gate"] if exited else None,
                owner_name=row["owner_name"], unit=row["unit"],
                category=row["category"], inferred=closed_by_reentry,
                ended_by=row["gone_by"] if by_hand else None,
                entry_pass_id=row["entry_id"],
                entry_has_snapshot=bool(row["entry_snapshot"]),
                # Only for an observed exit. A visit closed by the car being
                # seen entering again has no exit photograph, because nobody
                # ever saw it leave — offering the re-entry's picture as the
                # exit would be presenting an inference as an observation.
                exit_pass_id=row["next_id"] if exited else None,
                exit_has_snapshot=bool(row["next_snapshot"]) if exited else False,
            ))
        return out

    def inside(self, since: datetime | None = None,
               until: datetime | None = None) -> list[Visit]:
        return [v for v in self.visits(since, until) if v.inside]

    def end_visit(self, entry_pass_id: str, by_who: str) -> bool:
        """A person says this car has gone. False if the visit was not open.

        **The audit entry is written by the caller, before this runs.** Only a
        visit that is open right now can be ended; one already closed (seen
        leaving, seen entering again, or marked before) changes nothing, so
        pressing the button twice is not an error. No exit pass is invented.
        """
        with self._lock:
            if not any(v.entry_pass_id == entry_pass_id
                       for v in self.inside(since=None)):
                return False
            with self._conn:
                self._conn.execute(
                    "INSERT INTO vehicle_gone (entry_pass_id, by_who, at)"
                    " VALUES (?, ?, ?)", (entry_pass_id, by_who, _iso(_now())))
        return True

    def hourly(self, since: datetime, until: datetime,
               offset_minutes: int = 0) -> list[dict]:
        """Entries and exits by hour of the SITE'S day, for the traffic chart.

        **The shift happens here, in minutes, and that detail is the whole
        reason this takes an offset at all.** The obvious version groups on the
        stored UTC hour and lets the caller add `offset // 60` — which is exact
        for Cairo and for every whole-hour zone, and an hour wrong for half the
        clock in India (+5:30) or Iran (+3:30). `strftime` with a minutes
        modifier is correct everywhere and costs nothing.

        Only hours that have something in them appear: a bar of height zero at
        3am is noise, and an empty list is the honest answer for a day nothing
        happened.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT strftime('%H', at, ? || ' minutes') AS hour,"
                " direction, COUNT(*) AS n"
                " FROM vehicle_pass WHERE at >= ? AND at < ?"
                " GROUP BY hour, direction ORDER BY hour",
                (int(offset_minutes), _iso(since), _iso(until))).fetchall()

        by_hour: dict[int, dict] = {}
        for row in rows:
            slot = by_hour.setdefault(
                int(row["hour"]), {"hour": int(row["hour"]),
                                   "entered": 0, "left": 0})
            slot["entered" if row["direction"] == "entry" else "left"] += row["n"]
        return [by_hour[h] for h in sorted(by_hour)]

    def gates(self, since: datetime, until: datetime | None = None) -> list[dict]:
        """Per gate: how many in, how many out, how many still inside."""
        sql = ("SELECT gate, direction, COUNT(*) AS n FROM vehicle_pass"
               " WHERE at >= ?")
        params: list = [_iso(since)]
        if until is not None:
            sql += " AND at < ?"
            params.append(_iso(until))
        sql += " GROUP BY gate, direction"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        totals: dict[int, dict] = {}
        for row in rows:
            entry = totals.setdefault(row["gate"], {"gate": row["gate"],
                                                    "entered": 0, "left": 0})
            entry["entered" if row["direction"] == "entry" else "left"] += row["n"]

        inside_by_gate: dict[int, int] = {}
        for visit in self.inside(since):
            inside_by_gate[visit.entry_gate] = inside_by_gate.get(
                visit.entry_gate, 0) + 1
        for gate, entry in totals.items():
            entry["inside"] = inside_by_gate.get(gate, 0)

        return [totals[g] for g in sorted(totals)]

    # -- retention ----------------------------------------------------------

    def expire(self, older_than: datetime) -> int:
        """Delete plate images past their retention. **Rows are kept.**

        A pass whose photographs have aged out is still a pass — the time, the
        gate, the plate and the status are the record, and they are kept for
        good. Same precedent as `WeaponScene.playable`.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, snapshot, plate_crop FROM vehicle_pass"
                " WHERE at < ? AND (snapshot IS NOT NULL OR plate_crop IS NOT NULL)",
                (_iso(older_than),)).fetchall()

            cleared = 0
            for row in rows:
                _unlink(row["snapshot"])
                _unlink(row["plate_crop"])
                self._conn.execute(
                    "UPDATE vehicle_pass SET snapshot = NULL, plate_crop = NULL"
                    " WHERE id = ?", (row["id"],))
                cleared += 1
            self._conn.commit()
        if cleared:
            log.info("cleared images from %d expired gate passes", cleared)
        return cleared

    # -- import -------------------------------------------------------------

    def import_rows(self, rows: list[dict], by_who: str = "") -> dict:
        """Load a list of register rows. Reports every one it refused.

        A silent partial import is the worst outcome: the office believes the
        list is loaded and finds out at the gate. Every rejection carries its
        reason and its row number.

        **The run is recorded**, because the register tab shows a "last
        import" line and that line is either a fact or it is absent
        (P6-FR-053). The audit log cannot be the source — it still lives in
        RAM until P3, so it would forget at the next restart.
        """
        added = updated = skipped = 0
        problems: list[str] = []

        for number, raw in enumerate(rows, start=2):   # row 1 is the heading
            fields = _map_headings(raw)
            plate = platetext.normalize(fields.get("plate", ""))
            if not plate:
                problems.append(f"row {number}: no readable plate")
                continue

            category = (fields.get("category") or "visitor").strip().lower()
            if category not in CATEGORIES:
                problems.append(
                    f"row {number}: unknown category {category!r} "
                    f"(expected one of {', '.join(CATEGORIES)})")
                continue

            existing = self.by_plate(plate)
            try:
                if existing is not None:
                    self.update(existing.id, category=category, **{
                        k: v for k, v in fields.items()
                        if k in ("owner_name", "phone", "unit", "car_make",
                                 "car_colour", "valid_until", "notes") and v
                    })
                    updated += 1
                    skipped += 1
                else:
                    self.add(plate=plate, category=category, **{
                        k: v for k, v in fields.items()
                        if k in ("owner_name", "phone", "unit", "car_make",
                                 "car_colour", "valid_until", "notes")
                    })
                    added += 1
            except (ValueError, PlateTaken) as exc:
                problems.append(f"row {number}: {exc}")

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO vehicle_import_run (id, at, added, updated,"
                " skipped, rejected, by_who) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, _iso(_now()), added, updated, skipped,
                 len(problems), by_who))

        return {"added": added, "updated": updated,
                "skipped_duplicates": skipped, "problems": problems}

    def last_import_run(self) -> dict | None:
        """The most recent import, or None if nobody has ever run one.

        None is the honest answer on a fresh database, and the console shows
        no line at all rather than a row of zeros — "0 rows imported" reads as
        a failed import rather than as an import that never happened.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM vehicle_import_run ORDER BY at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {"at": _parse(row["at"]), "added": row["added"],
                "updated": row["updated"], "skipped": row["skipped"],
                "rejected": row["rejected"], "by_who": row["by_who"]}


# --- spreadsheets ----------------------------------------------------------

#: Column headings accepted, in English and Arabic. A school's list arrives
#: however the previous system exported it.
HEADINGS = {
    "plate": ("plate", "رقم اللوحة", "اللوحة", "plate_number"),
    "owner_name": ("owner_name", "owner", "اسم المالك", "المالك"),
    "phone": ("phone", "mobile", "الهاتف", "الموبايل"),
    "unit": ("unit", "department", "الوحدة", "القسم", "الشقة"),
    "category": ("category", "type", "الفئة", "النوع"),
    "car_make": ("car_make", "make", "model", "الماركة", "الموديل"),
    "car_colour": ("car_colour", "car_color", "colour", "color", "اللون"),
    "valid_until": ("valid_until", "expiry", "تاريخ الانتهاء", "صالح حتى"),
    "notes": ("notes", "note", "ملاحظات"),
}

_HEADING_LOOKUP = {
    alias.strip().lower(): field
    for field, aliases in HEADINGS.items() for alias in aliases
}


def save_pass_images(folder: Path, camera_id: str, at: datetime, plate: str,
                     image, box=None) -> tuple[str | None, str | None]:
    """Write the photograph and the plate crop for one pass.

    Returns `(snapshot, crop)` as paths, either of which may be None.

    **Never raises.** A pass is a record of a car going through a gate; a
    photograph is evidence attached to it. A full disk, a permission error or
    a frame that would not encode must cost the picture, never the row — the
    time, gate, plate and status are the part that is kept for good.

    The filename is transliterated ASCII on purpose, and both files are
    encoded in memory and written with `Path.write_bytes` rather than by
    `cv2.imwrite`. Neither is fussiness: OpenCV writes through the platform's
    narrow filename API and silently returns False for a path it cannot
    encode, so an Arabic plate on a Windows machine produces no picture and
    no error. The plate is in the database anyway; the filename is only for a
    human eye.
    """
    if image is None:
        return None, None

    import cv2

    stamp = at.strftime("%Y%m%d-%H%M%S")
    safe_plate = "".join(
        c for c in platetext.transliterate(platetext.normalize(plate))
        if c.isascii() and c.isalnum()) or "unread"
    safe_camera = "".join(
        c if c.isascii() and (c.isalnum() or c in "-_") else "-"
        for c in camera_id)
    stem = f"{safe_camera}-{stamp}-{safe_plate}"

    def write(path: Path, picture, quality: int) -> str | None:
        ok, buffer = cv2.imencode(".jpg", picture,
                                  [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return None
        path.write_bytes(buffer.tobytes())
        return str(path)

    snapshot = crop = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = write(folder / f"{stem}.jpg", image, 85)

        if box is not None:
            patch = box.crop(image, pad=0.25)
            if patch.size:
                crop = write(folder / f"{stem}-plate.jpg", patch, 92)
    except Exception:  # noqa: BLE001 - the row matters, the picture does not
        log.exception("could not save the images for a gate pass on %s",
                      camera_id)

    return snapshot, crop


def _map_headings(raw: dict) -> dict:
    """Whatever the spreadsheet called its columns, in our names."""
    out: dict = {}
    for key, value in raw.items():
        field = _HEADING_LOOKUP.get(str(key or "").strip().lower())
        if field and value is not None:
            out[field] = str(value).strip()
    return out


def read_csv(data: bytes) -> list[dict]:
    """Rows from a CSV. UTF-8 with or without a BOM — Excel writes one."""
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def read_xlsx(data: bytes) -> list[dict]:
    """Rows from an .xlsx. Raises `RuntimeError` if openpyxl is absent."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:      # pragma: no cover - declared in requirements
        raise RuntimeError(
            "openpyxl is not installed, so .xlsx cannot be read. "
            "Save the list as CSV, or pip install openpyxl."
        ) from exc

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    try:
        headings = [str(h or "") for h in next(rows)]
    except StopIteration:
        return []
    out = [dict(zip(headings, row)) for row in rows if any(
        cell is not None for cell in row)]
    workbook.close()
    return out


def template_csv() -> bytes:
    """The blank import template, with one example row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(HEADINGS))
    writer.writerow(["ب ج د 1234", "Tarek Nassar", "01012345678", "IT",
                     "staff", "Hyundai Elantra", "grey", "", ""])
    return buffer.getvalue().encode("utf-8-sig")


# --- helpers ---------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        # The row already says the image is gone. A locked file costs disk,
        # which is not worth failing the sweep over.
        log.warning("could not delete expired plate image %s: %s", path, exc)


def _to_vehicle(row: sqlite3.Row) -> Vehicle:
    return Vehicle(
        id=row["id"], plate=row["plate"], plate_display=row["plate_display"],
        owner_name=row["owner_name"], phone=row["phone"], unit=row["unit"],
        category=row["category"], car_make=row["car_make"],
        car_colour=row["car_colour"], valid_until=row["valid_until"],
        notes=row["notes"],
    )


def _to_pass(row: sqlite3.Row) -> VehiclePass:
    keys = row.keys()
    return VehiclePass(
        id=row["id"], at=_parse(row["at"]), camera_id=row["camera_id"],
        gate=int(row["gate"]), direction=row["direction"], plate=row["plate"],
        plate_display=row["plate_display"], status=row["status"],
        confidence=float(row["confidence"]), votes=int(row["votes"]),
        needs_review=bool(row["needs_review"]), vehicle_id=row["vehicle_id"],
        owner_name=row["v_owner"] if "v_owner" in keys else None,
        unit=row["v_unit"] if "v_unit" in keys else None,
        snapshot=row["snapshot"], plate_crop=row["plate_crop"],
        # Guarded like the joined columns above: a row selected before this
        # column existed still parses, which matters while a gate is running.
        corrected_by=row["corrected_by"] if "corrected_by" in keys else None,
        plate_width=(int(row["plate_width"])
                     if "plate_width" in keys and row["plate_width"] else None),
        read_plate=row["read_plate"] if "read_plate" in keys else None,
    )
