"""SQLite storage: vehicles, passage events, matched visits, alerts."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH
from . import plate_text

# Africa/Cairo is UTC+3 year-round (Egypt reintroduced DST in 2023 — if that
# matters for your reports, swap this for zoneinfo).
CAIRO = timezone(timedelta(hours=3))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Registered / known vehicles ------------------------------------------------
CREATE TABLE IF NOT EXISTS vehicles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plate         TEXT NOT NULL UNIQUE,      -- canonical key, see plate_text
    plate_display TEXT,
    owner_name    TEXT,
    phone         TEXT,
    unit          TEXT,                      -- apartment / office / dept
    category      TEXT NOT NULL DEFAULT 'resident',
                                             -- resident|staff|visitor|vip|blacklist
    car_make      TEXT,
    car_color     TEXT,
    valid_from    TEXT,
    valid_until   TEXT,                      -- NULL = never expires
    notes         TEXT,
    photo_path    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicles_cat ON vehicles(category);

-- Every plate read that survived voting ---------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,            -- ISO8601 local time (Africa/Cairo)
    ts_utc         TEXT NOT NULL,
    plate          TEXT NOT NULL,
    plate_display  TEXT,
    camera_id      TEXT NOT NULL,
    gate_number    INTEGER NOT NULL,
    direction      TEXT NOT NULL,            -- entry | exit
    status         TEXT NOT NULL,            -- known | unknown | blacklist | expired
    vehicle_id     INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    confidence     REAL NOT NULL,
    ocr_confidence REAL,
    plausibility   REAL,
    votes          INTEGER,
    low_confidence INTEGER NOT NULL DEFAULT 0,
    snapshot       TEXT,                     -- full frame, relative path
    plate_crop     TEXT,                     -- cropped plate, relative path
    reviewed       INTEGER NOT NULL DEFAULT 0,
    corrected_from TEXT,                     -- set when a guard fixes a misread
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_ts     ON events(ts_utc DESC);
CREATE INDEX IF NOT EXISTS ix_events_plate  ON events(plate);
CREATE INDEX IF NOT EXISTS ix_events_gate   ON events(gate_number, direction);
CREATE INDEX IF NOT EXISTS ix_events_status ON events(status);

-- Entry matched to its exit ---------------------------------------------------
CREATE TABLE IF NOT EXISTS visits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plate           TEXT NOT NULL,
    vehicle_id      INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    entry_event_id  INTEGER REFERENCES events(id) ON DELETE CASCADE,
    exit_event_id   INTEGER REFERENCES events(id) ON DELETE SET NULL,
    entry_ts        TEXT NOT NULL,
    exit_ts         TEXT,
    entry_gate      INTEGER,
    exit_gate       INTEGER,
    duration_min    REAL,
    open            INTEGER NOT NULL DEFAULT 1   -- 1 = still inside
);
CREATE INDEX IF NOT EXISTS ix_visits_open  ON visits(open, plate);
CREATE INDEX IF NOT EXISTS ix_visits_plate ON visits(plate, entry_ts DESC);

-- Alerts shown on the guard screen -------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    level        TEXT NOT NULL,             -- info | warning | danger
    kind         TEXT NOT NULL,             -- unknown | blacklist | expired
                                            -- | low_confidence | camera_down
    message      TEXT NOT NULL,
    plate        TEXT,
    event_id     INTEGER REFERENCES events(id) ON DELETE CASCADE,
    gate_number  INTEGER,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    ack_by       TEXT,
    ack_ts       TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_open ON alerts(acknowledged, id DESC);

-- Camera health ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera_status (
    camera_id   TEXT PRIMARY KEY,
    last_frame  TEXT,
    online      INTEGER NOT NULL DEFAULT 0,
    fps         REAL,
    last_error  TEXT,
    updated_at  TEXT
);
"""

_local = threading.local()


def now_local() -> datetime:
    return datetime.now(CAIRO)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """One connection per thread; camera workers and the web app each get one."""
    key = str(path or DB_PATH)
    conn = getattr(_local, "conns", {}).get(key)
    if conn is None:
        Path(key).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(key, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        if not hasattr(_local, "conns"):
            _local.conns = {}
        _local.conns[key] = conn
    return conn


def init(path: Path | str | None = None) -> sqlite3.Connection:
    return connect(path)


# --- vehicles ----------------------------------------------------------------

def upsert_vehicle(conn: sqlite3.Connection, **kw: Any) -> int:
    """Insert or update a registered vehicle. `plate` may be raw; it is normalised."""
    plate = plate_text.normalize(kw.pop("plate", ""))
    if not plate:
        raise ValueError("vehicle needs a plate")
    now = _iso(now_local())
    fields = {
        "plate": plate,
        "plate_display": plate_text.display(plate),
        "owner_name": kw.get("owner_name"),
        "phone": kw.get("phone"),
        "unit": kw.get("unit"),
        "category": kw.get("category") or "resident",
        "car_make": kw.get("car_make"),
        "car_color": kw.get("car_color"),
        "valid_from": kw.get("valid_from"),
        "valid_until": kw.get("valid_until"),
        "notes": kw.get("notes"),
        "photo_path": kw.get("photo_path"),
        "updated_at": now,
    }
    cur = conn.execute("SELECT id FROM vehicles WHERE plate=?", (plate,))
    row = cur.fetchone()
    if row:
        sets = ", ".join(f"{k}=?" for k in fields if k != "plate")
        vals = [v for k, v in fields.items() if k != "plate"]
        conn.execute(f"UPDATE vehicles SET {sets} WHERE id=?", [*vals, row["id"]])
        conn.commit()
        return int(row["id"])
    fields["created_at"] = now
    cols = ", ".join(fields)
    qs = ", ".join("?" * len(fields))
    cur = conn.execute(
        f"INSERT INTO vehicles ({cols}) VALUES ({qs})", list(fields.values())
    )
    conn.commit()
    return int(cur.lastrowid)


def find_vehicle(conn: sqlite3.Connection, plate: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM vehicles WHERE plate=?", (plate_text.normalize(plate),)
    ).fetchone()


def classify(conn: sqlite3.Connection, plate: str, when: datetime | None = None
             ) -> tuple[str, sqlite3.Row | None]:
    """Return (status, vehicle_row). status in known|unknown|blacklist|expired."""
    v = find_vehicle(conn, plate)
    if v is None:
        return "unknown", None
    if (v["category"] or "").lower() == "blacklist":
        return "blacklist", v
    when = when or now_local()
    today = when.date().isoformat()
    if v["valid_until"] and str(v["valid_until"])[:10] < today:
        return "expired", v
    if v["valid_from"] and str(v["valid_from"])[:10] > today:
        return "expired", v
    return "known", v


def near_vehicle(conn: sqlite3.Connection, plate: str) -> sqlite3.Row | None:
    """
    The one registered vehicle a read was probably a misread of.

    Voting fixes a reader that is wrong differently each frame. It cannot fix
    one that is wrong the *same* way every frame — ن and ب differ by a dot,
    and the character model here reads one as the other on most frames of the
    same plate. That car is registered, its owner is on file, and the guard
    sees "unregistered vehicle".

    So: when a plate matches nothing, look for a registered one it is a single
    glyph away from. Deliberately conservative — the answer is only used to
    tell the guard what the car might be, never to admit it. If two registered
    vehicles are equally close the question is genuinely ambiguous and nothing
    is suggested.
    """
    norm = plate_text.normalize(plate)
    if not norm:
        return None
    hits = [v for v in conn.execute("SELECT * FROM vehicles")
            if plate_text.same_plate(norm, v["plate"])]
    return hits[0] if len(hits) == 1 else None


def search_vehicles(conn: sqlite3.Connection, q: str = "", category: str = "",
                    limit: int = 200, offset: int = 0) -> list[sqlite3.Row]:
    where, args = [], []
    if q:
        norm = plate_text.normalize(q)
        where.append(
            "(plate LIKE ? OR owner_name LIKE ? OR phone LIKE ? OR unit LIKE ?)"
        )
        args += [f"%{norm or q}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if category:
        where.append("category=?")
        args.append(category)
    sql = "SELECT * FROM vehicles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    return conn.execute(sql, [*args, limit, offset]).fetchall()


def delete_vehicle(conn: sqlite3.Connection, vehicle_id: int) -> None:
    conn.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
    conn.commit()


# --- events ------------------------------------------------------------------

def recent_event(conn: sqlite3.Connection, plate: str, camera_id: str,
                 within_seconds: int) -> sqlite3.Row | None:
    """
    The event this read is a repeat of, if there is one.

    Matching on the exact plate is not enough, and that is the whole reason a
    single car used to fill the log with three or four rows: the reader spells
    the same plate differently from frame to frame, and every spelling looked
    like a brand-new vehicle. One camera cannot see two cars one glyph apart
    within its dedupe window, so a near-match on the same camera is a repeat,
    not a second car.
    """
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(seconds=within_seconds))
    rows = conn.execute(
        "SELECT * FROM events WHERE camera_id=? AND ts_utc>=? "
        "ORDER BY id DESC LIMIT 25",
        (camera_id, cutoff),
    ).fetchall()
    for r in rows:
        if r["plate"] == plate:
            return r
    for r in rows:
        if plate_text.same_plate(plate, r["plate"]):
            return r
    return None


def improve_event(conn: sqlite3.Connection, event_id: int, *, plate: str,
                  confidence: float, ocr_confidence: float | None = None,
                  plausibility: float | None = None, votes: int | None = None,
                  low_confidence: bool = False, snapshot: str | None = None,
                  plate_crop: str | None = None) -> bool:
    """
    Replace a logged read with a better one of the same car.

    The dedupe window exists so one car makes one row, but it used to mean the
    first reading won outright — including when the car came closer and the
    system then read the plate perfectly. Keeping the better read (and only the
    better read) is what lets a car be identified correctly without being
    counted twice.
    """
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None or confidence <= (row["confidence"] or 0.0):
        return False
    status, veh = classify(conn, plate)
    conn.execute(
        "UPDATE events SET plate=?, plate_display=?, status=?, vehicle_id=?, "
        "confidence=?, ocr_confidence=?, plausibility=?, votes=?, "
        "low_confidence=?, snapshot=COALESCE(?, snapshot), "
        "plate_crop=COALESCE(?, plate_crop) WHERE id=?",
        (plate, plate_text.display(plate), status, veh["id"] if veh else None,
         confidence, ocr_confidence, plausibility, votes,
         int(bool(low_confidence)), snapshot, plate_crop, event_id),
    )
    conn.execute("UPDATE visits SET plate=?, vehicle_id=? "
                 "WHERE entry_event_id=? OR exit_event_id=?",
                 (plate, veh["id"] if veh else None, event_id, event_id))
    conn.commit()
    return True


def insert_event(conn: sqlite3.Connection, **kw: Any) -> int:
    now_l = kw.pop("when", None) or now_local()
    fields = {
        "ts": _iso(now_l),
        "ts_utc": _iso(now_l.astimezone(timezone.utc)),
        "plate": kw["plate"],
        "plate_display": plate_text.display(kw["plate"]),
        "camera_id": kw["camera_id"],
        "gate_number": kw["gate_number"],
        "direction": kw["direction"],
        "status": kw["status"],
        "vehicle_id": kw.get("vehicle_id"),
        "confidence": kw.get("confidence", 0.0),
        "ocr_confidence": kw.get("ocr_confidence"),
        "plausibility": kw.get("plausibility"),
        "votes": kw.get("votes"),
        "low_confidence": int(bool(kw.get("low_confidence"))),
        "snapshot": kw.get("snapshot"),
        "plate_crop": kw.get("plate_crop"),
        "created_at": _iso(now_local()),
    }
    cols = ", ".join(fields)
    qs = ", ".join("?" * len(fields))
    cur = conn.execute(
        f"INSERT INTO events ({cols}) VALUES ({qs})", list(fields.values())
    )
    conn.commit()
    return int(cur.lastrowid)


def list_events(conn: sqlite3.Connection, *, limit: int = 100, offset: int = 0,
                gate: int | None = None, direction: str = "", status: str = "",
                plate: str = "", date_from: str = "", date_to: str = ""
                ) -> list[sqlite3.Row]:
    where, args = [], []
    if gate:
        where.append("e.gate_number=?"); args.append(gate)
    if direction:
        where.append("e.direction=?"); args.append(direction)
    if status:
        where.append("e.status=?"); args.append(status)
    if plate:
        # Match letters and digits independently so a partial plate still
        # finds the car. Searching "طن 39" must reach "طنب 395" — a single
        # LIKE on the whole normalised string would not, because the missing
        # letter breaks the substring.
        norm = plate_text.normalize(plate)
        letters, _, digits = norm.partition(" ")
        if letters and digits:
            where.append("e.plate LIKE ? AND e.plate LIKE ?")
            args += [f"%{letters[0]}%", f"%{digits}%"]
            for ch in letters[1:]:
                where[-1] += " AND e.plate LIKE ?"
                args.append(f"%{ch}%")
        elif norm:
            where.append("e.plate LIKE ?")
            args.append(f"%{norm}%")
        else:
            where.append("e.plate LIKE ?")
            args.append(f"%{plate}%")
    if date_from:
        where.append("e.ts>=?"); args.append(date_from)
    if date_to:
        where.append("e.ts<=?"); args.append(date_to + "T23:59:59")
    sql = ("SELECT e.*, v.owner_name, v.unit, v.category, v.phone "
           "FROM events e LEFT JOIN vehicles v ON v.id=e.vehicle_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.id DESC LIMIT ? OFFSET ?"
    return conn.execute(sql, [*args, limit, offset]).fetchall()


def count_events(conn: sqlite3.Connection, **kw: Any) -> int:
    rows = list_events(conn, limit=1_000_000, **kw)
    return len(rows)


def correct_event(conn: sqlite3.Connection, event_id: int, new_plate: str) -> None:
    """Guard fixes a misread. Re-classifies and rewrites the linked visit."""
    ev = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not ev:
        raise KeyError(event_id)
    norm = plate_text.normalize(new_plate)
    status, veh = classify(conn, norm)
    conn.execute(
        "UPDATE events SET plate=?, plate_display=?, status=?, vehicle_id=?, "
        "reviewed=1, corrected_from=? WHERE id=?",
        (norm, plate_text.display(norm), status,
         veh["id"] if veh else None, ev["plate"], event_id),
    )
    conn.execute("UPDATE visits SET plate=?, vehicle_id=? "
                 "WHERE entry_event_id=? OR exit_event_id=?",
                 (norm, veh["id"] if veh else None, event_id, event_id))
    conn.commit()


# --- visits (stay duration) ---------------------------------------------------

def open_visit(conn: sqlite3.Connection, plate: str,
               fuzzy: bool = True) -> sqlite3.Row | None:
    """
    The visit this plate is currently inside on, if any.

    The fuzzy fallback is what makes the occupancy count come back down. A car
    is read by the entry camera and again, separately, by the exit camera, and
    the two readings only have to differ by one glyph for an exact match to
    fail — at which point the exit is filed as an orphan, the entry stays open
    forever, and "inside now" only ever climbs. Nothing about the exact match
    is lost: it is still tried first, and the loose match is only consulted
    when the strict one finds nothing.
    """
    exact = conn.execute(
        "SELECT * FROM visits WHERE plate=? AND open=1 ORDER BY id DESC LIMIT 1",
        (plate,),
    ).fetchone()
    if exact or not fuzzy:
        return exact
    for r in conn.execute(
            "SELECT * FROM visits WHERE open=1 ORDER BY id DESC LIMIT 300"):
        if plate_text.same_plate(plate, r["plate"]):
            return r
    return None


def register_passage(conn: sqlite3.Connection, event: sqlite3.Row | dict) -> dict:
    """
    Fold one event into the visit table.

    entry -> open a visit (closing any stale one first, e.g. a car that left
             through an unmonitored gate).
    exit  -> close the matching open visit and compute the stay in minutes.
    """
    e = dict(event)
    plate, ts = e["plate"], e["ts"]
    result: dict[str, Any] = {"visit_id": None, "duration_min": None}

    if e["direction"] == "entry":
        stale = open_visit(conn, plate)
        if stale:
            conn.execute("UPDATE visits SET open=0 WHERE id=?", (stale["id"],))
        cur = conn.execute(
            "INSERT INTO visits (plate, vehicle_id, entry_event_id, entry_ts, "
            "entry_gate, open) VALUES (?,?,?,?,?,1)",
            (plate, e.get("vehicle_id"), e["id"], ts, e["gate_number"]),
        )
        result["visit_id"] = int(cur.lastrowid)
    else:  # exit
        v = open_visit(conn, plate)
        if v:
            dur = None
            try:
                dur = round(
                    (datetime.fromisoformat(ts)
                     - datetime.fromisoformat(v["entry_ts"])).total_seconds() / 60,
                    1,
                )
            except Exception:
                pass
            conn.execute(
                "UPDATE visits SET exit_event_id=?, exit_ts=?, exit_gate=?, "
                "duration_min=?, open=0 WHERE id=?",
                (e["id"], ts, e["gate_number"], dur, v["id"]),
            )
            result.update(visit_id=int(v["id"]), duration_min=dur)
        else:
            # Exit with no recorded entry - car got in before the system was
            # running, or the entry camera missed it. Log it so it is visible.
            cur = conn.execute(
                "INSERT INTO visits (plate, vehicle_id, exit_event_id, entry_ts, "
                "exit_ts, exit_gate, open) VALUES (?,?,?,?,?,?,0)",
                (plate, e.get("vehicle_id"), e["id"], ts, ts, e["gate_number"]),
            )
            result["visit_id"] = int(cur.lastrowid)
            result["orphan_exit"] = True
    conn.commit()
    return result


def currently_inside(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT vi.*, v.owner_name, v.unit, v.category, e.plate_display "
        "FROM visits vi "
        "LEFT JOIN vehicles v ON v.id=vi.vehicle_id "
        "LEFT JOIN events e ON e.id=vi.entry_event_id "
        "WHERE vi.open=1 ORDER BY vi.entry_ts DESC"
    ).fetchall()


def list_visits(conn: sqlite3.Connection, limit: int = 200, plate: str = "",
                min_minutes: float | None = None) -> list[sqlite3.Row]:
    where, args = ["1=1"], []
    if plate:
        where.append("vi.plate LIKE ?")
        args.append(f"%{plate_text.normalize(plate) or plate}%")
    if min_minutes is not None:
        where.append("vi.duration_min >= ?"); args.append(min_minutes)
    return conn.execute(
        "SELECT vi.*, v.owner_name, v.unit, v.category FROM visits vi "
        "LEFT JOIN vehicles v ON v.id=vi.vehicle_id "
        f"WHERE {' AND '.join(where)} ORDER BY vi.id DESC LIMIT ?",
        [*args, limit],
    ).fetchall()


# --- alerts -------------------------------------------------------------------

def add_alert(conn: sqlite3.Connection, level: str, kind: str, message: str,
              plate: str = "", event_id: int | None = None,
              gate_number: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO alerts (ts, level, kind, message, plate, event_id, "
        "gate_number) VALUES (?,?,?,?,?,?,?)",
        (_iso(now_local()), level, kind, message, plate, event_id, gate_number),
    )
    conn.commit()
    return int(cur.lastrowid)


def open_alerts(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alerts WHERE acknowledged=0 ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def ack_alert(conn: sqlite3.Connection, alert_id: int, by: str = "guard") -> None:
    conn.execute(
        "UPDATE alerts SET acknowledged=1, ack_by=?, ack_ts=? WHERE id=?",
        (by, _iso(now_local()), alert_id),
    )
    conn.commit()


def ack_all_alerts(conn: sqlite3.Connection, by: str = "guard") -> None:
    conn.execute("UPDATE alerts SET acknowledged=1, ack_by=?, ack_ts=? "
                 "WHERE acknowledged=0", (by, _iso(now_local())))
    conn.commit()


# --- camera health -------------------------------------------------------------

def set_camera_status(conn: sqlite3.Connection, camera_id: str, online: bool,
                      fps: float | None = None, error: str | None = None) -> None:
    now = _iso(now_local())
    conn.execute(
        "INSERT INTO camera_status (camera_id, last_frame, online, fps, "
        "last_error, updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(camera_id) DO UPDATE SET last_frame=excluded.last_frame, "
        "online=excluded.online, fps=excluded.fps, "
        "last_error=COALESCE(excluded.last_error, camera_status.last_error), "
        "updated_at=excluded.updated_at",
        (camera_id, now if online else None, int(online), fps, error, now),
    )
    conn.commit()


def camera_statuses(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM camera_status ORDER BY camera_id").fetchall()


# --- stats ---------------------------------------------------------------------

def daily_stats(conn: sqlite3.Connection, day: str | None = None) -> dict:
    day = day or now_local().date().isoformat()
    row = conn.execute(
        "SELECT "
        " SUM(direction='entry') AS entries,"
        " SUM(direction='exit')  AS exits,"
        " SUM(status='unknown')  AS unknown,"
        " SUM(status='blacklist') AS blacklist,"
        " SUM(low_confidence=1)  AS low_conf,"
        " COUNT(*) AS total "
        "FROM events WHERE substr(ts,1,10)=?",
        (day,),
    ).fetchone()
    inside = conn.execute("SELECT COUNT(*) c FROM visits WHERE open=1").fetchone()
    return {
        "day": day,
        "entries": row["entries"] or 0,
        "exits": row["exits"] or 0,
        "unknown": row["unknown"] or 0,
        "blacklist": row["blacklist"] or 0,
        "low_conf": row["low_conf"] or 0,
        "total": row["total"] or 0,
        "inside": inside["c"] or 0,
    }


def hourly_counts(conn: sqlite3.Connection, day: str | None = None) -> list[dict]:
    day = day or now_local().date().isoformat()
    rows = conn.execute(
        "SELECT substr(ts,12,2) h, direction, COUNT(*) c FROM events "
        "WHERE substr(ts,1,10)=? GROUP BY h, direction", (day,)
    ).fetchall()
    table = {f"{h:02d}": {"hour": f"{h:02d}", "entry": 0, "exit": 0}
             for h in range(24)}
    for r in rows:
        if r["h"] in table:
            table[r["h"]][r["direction"]] = r["c"]
    return list(table.values())


def purge_old(conn: sqlite3.Connection, keep_days: int) -> int:
    """Delete snapshot references older than keep_days. Returns rows touched."""
    cutoff = (now_local() - timedelta(days=keep_days)).date().isoformat()
    cur = conn.execute(
        "UPDATE events SET snapshot=NULL, plate_crop=NULL "
        "WHERE substr(ts,1,10) < ? AND snapshot IS NOT NULL", (cutoff,)
    )
    conn.commit()
    return cur.rowcount


def bulk_import(conn: sqlite3.Connection, rows: Iterable[dict]) -> dict:
    """Import many vehicles. Returns counts and per-row problems."""
    ok = failed = 0
    problems: list[str] = []
    for i, r in enumerate(rows, start=2):  # row 1 = header
        try:
            norm = plate_text.normalize(str(r.get("plate", "")))
            if not norm:
                raise ValueError("empty or unreadable plate")
            if not plate_text.is_wellformed(norm):
                problems.append(
                    f"صف {i}: لوحة غير معتادة '{norm}' — تم استيرادها كما هي"
                )
            upsert_vehicle(conn, **r)
            ok += 1
        except Exception as exc:
            failed += 1
            problems.append(f"صف {i}: {exc}")
    return {"imported": ok, "failed": failed, "problems": problems}
