"""Areas: a polygon drawn on one camera, with a rule about when it is watched.

A restricted zone and a work station are the same thing seen two ways: a shape
on a picture, and a rule about who stands in it. They share one row here, one
polygon check and one hours rule, so each is written once.

Five decisions worth stating:

**Geometry is fractions of the frame, never pixels.** Origin top-left, every
coordinate 0..1. Nothing here knows a camera's resolution, so the shape stays
right when the stream changes size.

**The shape is refused, not repaired.** Fewer than three points, a point outside
the frame, edges that cross, or a sliver so thin it is a line - each is a 422
with the reason in words. A polygon that crosses itself has no honest "inside",
and the ray-casting test in `features/people.py` would answer differently
depending on which way the edges happened to be listed.

**Delete is soft.** A scene or a station event keeps the id of the area it
happened in, and the log still has to name it a month later. The row stays.

**Hours are decided in one function.** `watching_at` is the only place that
says whether an area is being watched at a given local time. Working days and
times are Settings' (`HoursConfig`), passed in, so a Settings save applies at
the next frame and nothing here reads `engine.yaml` after the one-time import.

**The import happens once and never twice.** Whole-camera zones and the polygons
in engine.yaml become rows carrying an `import_key`. The key survives a soft
delete, so deleting an imported zone does not bring it back at the next start.

There is no threading here beyond one lock around the connection.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from vg import db
from vg.config import WEEKDAYS, HoursConfig, ZoneConfig

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS area (
    id                  TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,           -- zone | station
    name                TEXT NOT NULL,
    camera_id           TEXT NOT NULL,
    polygon             TEXT NOT NULL,           -- JSON [[x, y], ...], fractions
    hours_mode          TEXT NOT NULL,
    hours_from          TEXT,
    hours_to            TEXT,
    notify_in_app       INTEGER NOT NULL DEFAULT 1,
    notify_email        INTEGER NOT NULL DEFAULT 0,
    paused              INTEGER NOT NULL DEFAULT 0,
    paused_by           TEXT,
    paused_at           TEXT,
    alert_after_seconds REAL,
    assignee_id         TEXT,
    limit_minutes       INTEGER,
    created_at          TEXT NOT NULL,
    created_by          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    deleted_at          TEXT,
    deleted_by          TEXT,
    import_key          TEXT UNIQUE,
    import_note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_area_camera ON area(camera_id, kind);
"""

KINDS = ("zone", "station")

#: A zone is watched always, outside the working day, or in a window of its own.
ZONE_HOURS = ("always", "outside_working", "custom")
#: A station is watched during the working day, or in a window of its own.
STATION_HOURS = ("working", "custom")

#: Smallest area a shape may cover, as a fraction of the whole frame. Below
#: this it is a line with a width, not an area anybody can stand in.
MIN_AREA_FRACTION = 0.002

#: Longest a station may be left, in minutes.
LIMIT_MINUTES_MAX = 480

NAME_MAX = 80

#: The whole frame. What an old "restricted camera" becomes.
FULL_FRAME: tuple[tuple[float, float], ...] = (
    (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


class AreaError(ValueError):
    """The area cannot be saved. The message is for the operator, in words."""


class NoSuchArea(KeyError):
    """No area has that id."""


# ---------------------------------------------------------------------------
# the row
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    """One zone or one station."""

    id: str
    kind: str
    name: str
    camera_id: str
    polygon: tuple[tuple[float, float], ...]
    hours_mode: str
    hours_from: str | None = None
    hours_to: str | None = None
    notify_in_app: bool = True
    notify_email: bool = False
    paused: bool = False
    paused_by: str | None = None
    paused_at: datetime | None = None
    #: Zone only. 0 = alert once the entry is confirmed.
    alert_after_seconds: float | None = None
    #: Station only: a `FaceGallery` person id. Never a name.
    assignee_id: str | None = None
    limit_minutes: int | None = None
    created_at: datetime | None = None
    created_by: str = ""
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    import_key: str | None = None
    import_note: str | None = None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


# ---------------------------------------------------------------------------
# the shape
# ---------------------------------------------------------------------------

def validate_polygon(points: Iterable) -> tuple[tuple[float, float], ...]:
    """The polygon as a tuple of (x, y) fractions, or `AreaError` saying why not.

    Checked in this order, because the answers differ: a bow-tie has a signed
    area of zero, and reporting it as "almost a line" would send the operator
    looking for the wrong fault.
    """
    cleaned: list[tuple[float, float]] = []
    for point in points or ():
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError, KeyError):
            raise AreaError("Every point needs an x and a y.") from None
        cleaned.append((x, y))

    if len(cleaned) < 3:
        raise AreaError(
            "An area needs at least 3 points. Add more points around the place "
            "you want watched.")
    for x, y in cleaned:
        if not (math.isfinite(x) and math.isfinite(y)
                and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise AreaError(
                "A point is outside the picture. Every point must sit inside "
                "the camera's frame.")
    if _self_crossing(cleaned):
        raise AreaError(
            "The lines of this shape cross each other. Draw around the place "
            "without crossing back over yourself.")
    if _area(cleaned) < MIN_AREA_FRACTION:
        raise AreaError(
            "This shape is almost a line, so nobody could stand inside it. "
            "Make it wider.")
    return tuple(cleaned)


def _area(points: list[tuple[float, float]]) -> float:
    """Shoelace, absolute. Fractions of the frame, so the frame itself is 1."""
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, c) -> bool:
    """`c`, known collinear with a-b, lies between them."""
    return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))


def _segments_meet(p1, p2, p3, p4) -> bool:
    """Do segments p1-p2 and p3-p4 share any point, touching included."""
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0) and d1 != 0 and d2 != 0
            and (d3 > 0) != (d4 > 0) and d3 != 0 and d4 != 0):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def _self_crossing(points: list[tuple[float, float]]) -> bool:
    """Any two edges that are not neighbours meeting each other."""
    n = len(points)
    for i in range(n):
        a1, a2 = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            # Neighbouring edges share a corner by construction.
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_meet(a1, a2, points[j], points[(j + 1) % n]):
                return True
    return False


# ---------------------------------------------------------------------------
# the hours
# ---------------------------------------------------------------------------

def parse_hhmm(text: str | None) -> dtime:
    try:
        hour, minute = str(text).strip().split(":")
        return dtime(int(hour), int(minute))
    except (ValueError, AttributeError):
        raise AreaError(
            "Hours are written as HH:MM, for example 08:00.") from None


def validate_hours(kind: str, mode: str, hours_from: str | None,
                   hours_to: str | None) -> tuple[str | None, str | None]:
    """The (from, to) to store, or `AreaError`. Both are None unless custom."""
    allowed = ZONE_HOURS if kind == "zone" else STATION_HOURS
    if mode not in allowed:
        raise AreaError(
            f"Watched hours for a {kind} are one of: {', '.join(allowed)}.")
    if mode != "custom":
        return None, None
    if not hours_from or not hours_to:
        raise AreaError("Custom hours need both a start and an end time.")
    start, end = parse_hhmm(hours_from), parse_hhmm(hours_to)
    if start == end:
        raise AreaError("The start and the end of the hours are the same time.")
    if kind == "station" and not start < end:
        # A station is watched inside one day. A window that wraps midnight
        # needs one more rule, and the owner has not asked for night stations.
        raise AreaError(
            "A station's hours must start before they end, on the same day.")
    return f"{start:%H:%M}", f"{end:%H:%M}"


def _working_now(local: datetime, hours: HoursConfig) -> bool:
    """A working day, and between `hours.start` and `hours.end`."""
    return (local.weekday() in hours.working_days
            and hours.start <= local.time().replace(tzinfo=None) < hours.end)


def watching_at(area: Area, local: datetime, hours: HoursConfig) -> bool:
    """Is this area being watched at this site-local time?

    Not deleted; a zone not paused; and the hours rule allows it. `local` must
    already be in site time (`clock.local(...)`), because the working days and
    the clock times are the site's.
    """
    if area.deleted or area.paused:
        return False
    mode = area.hours_mode
    if mode == "always":
        return True
    if mode == "outside_working":
        return not _working_now(local, hours)
    if mode == "working":
        return _working_now(local, hours)
    if mode == "custom":
        start, end = parse_hhmm(area.hours_from), parse_hhmm(area.hours_to)
        now = local.time().replace(tzinfo=None)
        if start <= end:
            return start <= now < end
        return now >= start or now < end      # crosses midnight
    return False


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

class AreaStore:
    """Every zone and station ever drawn, deleted ones included."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- writing ------------------------------------------------------------

    def create(
        self, *, kind: str, name: str, camera_id: str, polygon: Iterable,
        hours_mode: str, hours_from: str | None = None,
        hours_to: str | None = None, notify_in_app: bool = True,
        notify_email: bool = False, alert_after_seconds: float | None = None,
        assignee_id: str | None = None, limit_minutes: int | None = None,
        actor: str, now: datetime | None = None, area_id: str | None = None,
        paused: bool = False, import_key: str | None = None,
        import_note: str | None = None,
    ) -> Area:
        now = now or datetime.now(timezone.utc)
        area = Area(
            id=area_id or uuid.uuid4().hex, kind=kind, name=name,
            camera_id=camera_id, polygon=tuple(map(tuple, polygon or ())),
            hours_mode=hours_mode, hours_from=hours_from, hours_to=hours_to,
            notify_in_app=bool(notify_in_app), notify_email=bool(notify_email),
            paused=bool(paused),
            paused_by=actor if paused else None,
            paused_at=now if paused else None,
            alert_after_seconds=alert_after_seconds, assignee_id=assignee_id,
            limit_minutes=limit_minutes, created_at=now, created_by=actor,
            updated_at=now, import_key=import_key, import_note=import_note,
        )
        area = self.check(area)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO area (id, kind, name, camera_id, polygon, "
                    "hours_mode, hours_from, hours_to, notify_in_app, "
                    "notify_email, paused, paused_by, paused_at, "
                    "alert_after_seconds, assignee_id, limit_minutes, "
                    "created_at, created_by, updated_at, import_key, "
                    "import_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                    "?,?,?)",
                    (area.id, area.kind, area.name, area.camera_id,
                     json.dumps([list(p) for p in area.polygon]),
                     area.hours_mode, area.hours_from, area.hours_to,
                     int(area.notify_in_app), int(area.notify_email),
                     int(area.paused), area.paused_by, _iso(area.paused_at),
                     area.alert_after_seconds, area.assignee_id,
                     area.limit_minutes, _iso(area.created_at),
                     area.created_by, _iso(area.updated_at), area.import_key,
                     area.import_note))
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise AreaError("That area already exists.") from exc
        return area

    #: What `update` may change. Everything else (kind, id, who made it) is
    #: fixed for the life of the row.
    EDITABLE = frozenset({
        "name", "camera_id", "polygon", "hours_mode", "hours_from", "hours_to",
        "notify_in_app", "notify_email", "alert_after_seconds", "assignee_id",
        "limit_minutes"})

    def update(self, area_id: str, *, now: datetime | None = None,
               **changes) -> Area:
        """Change fields of a live area. The result is re-checked as a whole."""
        stray = set(changes) - self.EDITABLE
        if stray:
            raise ValueError(f"cannot change {sorted(stray)}")
        with self._lock:
            current = self._require(area_id)
            if "polygon" in changes:
                changes["polygon"] = tuple(map(tuple, changes["polygon"] or ()))
            candidate = replace(current, **changes,
                                updated_at=now or datetime.now(timezone.utc))
            candidate = self.check(candidate)
            self._write(candidate)
        return candidate

    def set_paused(self, area_id: str, paused: bool, actor: str,
                   now: datetime | None = None) -> Area:
        """Pause or resume a zone. Who and when are kept; resuming clears them."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            current = self._require(area_id)
            candidate = replace(
                current, paused=bool(paused),
                paused_by=actor if paused else None,
                paused_at=now if paused else None, updated_at=now)
            self._write(candidate)
        return candidate

    def soft_delete(self, area_id: str, actor: str,
                    now: datetime | None = None) -> Area:
        """Mark it deleted. The row, its name and its `import_key` stay."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            current = self._require(area_id)
            if current.deleted:
                return current
            candidate = replace(current, deleted_at=now, deleted_by=actor,
                                updated_at=now)
            self._write(candidate)
        return candidate

    def _write(self, area: Area) -> None:
        self._conn.execute(
            "UPDATE area SET name=?, camera_id=?, polygon=?, hours_mode=?, "
            "hours_from=?, hours_to=?, notify_in_app=?, notify_email=?, "
            "paused=?, paused_by=?, paused_at=?, alert_after_seconds=?, "
            "assignee_id=?, limit_minutes=?, updated_at=?, deleted_at=?, "
            "deleted_by=? WHERE id=?",
            (area.name, area.camera_id,
             json.dumps([list(p) for p in area.polygon]), area.hours_mode,
             area.hours_from, area.hours_to, int(area.notify_in_app),
             int(area.notify_email), int(area.paused), area.paused_by,
             _iso(area.paused_at), area.alert_after_seconds, area.assignee_id,
             area.limit_minutes, _iso(area.updated_at), _iso(area.deleted_at),
             area.deleted_by, area.id))
        self._conn.commit()

    @staticmethod
    def check(area: Area) -> Area:
        """The area with its fields normalised, or `AreaError`."""
        if area.kind not in KINDS:
            raise AreaError(f"An area is a zone or a station, not {area.kind!r}.")
        name = (area.name or "").strip()
        if not name:
            raise AreaError("Give it a name.")
        if len(name) > NAME_MAX:
            raise AreaError(f"The name can be at most {NAME_MAX} characters.")
        if not (area.camera_id or "").strip():
            raise AreaError("Choose a camera.")
        polygon = validate_polygon(area.polygon)
        hours_from, hours_to = validate_hours(
            area.kind, area.hours_mode, area.hours_from, area.hours_to)

        alert_after, limit = area.alert_after_seconds, area.limit_minutes
        assignee = area.assignee_id
        if area.kind == "zone":
            if alert_after is None:
                alert_after = 0.0
            if not (isinstance(alert_after, (int, float))
                    and math.isfinite(alert_after) and alert_after >= 0):
                raise AreaError("The alert delay cannot be negative.")
            limit, assignee = None, None
        else:
            if limit is None or not (1 <= int(limit) <= LIMIT_MINUTES_MAX):
                raise AreaError(
                    f"Say how many minutes empty is too long, from 1 to "
                    f"{LIMIT_MINUTES_MAX}.")
            limit = int(limit)
            alert_after = None
        return replace(
            area, name=name, camera_id=area.camera_id.strip(),
            polygon=polygon, hours_from=hours_from, hours_to=hours_to,
            alert_after_seconds=alert_after, limit_minutes=limit,
            assignee_id=assignee or None)

    # -- reading ------------------------------------------------------------

    def get(self, area_id: str) -> Area | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM area WHERE id = ?", (area_id,)).fetchone()
        return _to_area(row) if row else None

    def _require(self, area_id: str) -> Area:
        area = self.get(area_id)
        if area is None:
            raise NoSuchArea(area_id)
        return area

    def list(self, kind: str | None = None, camera_id: str | None = None,
             include_deleted: bool = False) -> list[Area]:
        """Oldest first, so a list does not reshuffle between polls."""
        query, params = "SELECT * FROM area WHERE 1=1", []
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        if camera_id:
            query += " AND camera_id = ?"
            params.append(camera_id)
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        query += " ORDER BY created_at, id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_to_area(r) for r in rows]

    def import_keys(self) -> set[str]:
        """Every key ever imported, deleted rows included."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT import_key FROM area WHERE import_key IS NOT NULL"
            ).fetchall()
        return {r["import_key"] for r in rows}

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# the one-time import
# ---------------------------------------------------------------------------

def import_legacy(
    store: AreaStore, *,
    cameras_restricted: Mapping[str, bool],
    scene_camera_ids: Iterable[str],
    camera_names: Mapping[str, str],
    yaml_zones: Iterable[ZoneConfig],
    hours: HoursConfig,
    notify: tuple[bool, bool] = (True, False),
    now: datetime | None = None,
) -> int:
    """Turn what exists today into areas. Returns how many it created.

    * Every camera with a `camera_restricted` row, or with scenes in the log,
      becomes a **whole-frame zone whose id is the camera id**. Using the camera
      id means the old scene rows already name it and the old ids a console or
      phone stored still resolve. Paused unless the row says restricted.
      Cameras never switched on and with no history become nothing.
    * Every polygon in engine.yaml becomes a drawn zone keyed `yaml:<id>`.
      Anything its schedule said that the Watched-hours rule cannot say goes in
      `import_note`, in plain words, so nothing changes silently.

    Idempotent: a row is skipped when its `import_key` is already in the store,
    and the key stays after a delete, so a deleted zone never comes back.
    """
    now = now or datetime.now(timezone.utc)
    seen = store.import_keys()
    made = 0
    notify_in_app, notify_email = notify

    cameras = list(dict.fromkeys([*cameras_restricted, *scene_camera_ids]))
    for camera_id in cameras:
        key = f"camera:{camera_id}"
        if key in seen:
            continue
        try:
            store.create(
                kind="zone", name=camera_names.get(camera_id) or camera_id,
                camera_id=camera_id, polygon=FULL_FRAME, hours_mode="always",
                notify_in_app=notify_in_app, notify_email=notify_email,
                alert_after_seconds=0.0, actor="import", now=now,
                area_id=camera_id,
                # The row says whether the whole camera was switched on.
                paused=not cameras_restricted.get(camera_id, False),
                import_key=key)
            made += 1
        except AreaError:
            log.exception("could not import camera zone %s", camera_id)

    for zone in yaml_zones:
        key = f"yaml:{zone.id}"
        if key in seen:
            continue
        mode, start, end, note, never = _legacy_hours(zone, hours)
        try:
            store.create(
                kind="zone", name=zone.name, camera_id=zone.camera_id,
                polygon=zone.polygon, hours_mode=mode, hours_from=start,
                hours_to=end, notify_in_app=notify_in_app,
                notify_email=notify_email, alert_after_seconds=0.0,
                actor="import", now=now,
                area_id=zone.id if store.get(zone.id) is None else None,
                paused=(not zone.enabled) or never,
                import_key=key, import_note=note)
            made += 1
        except AreaError:
            log.exception("could not import engine.yaml zone %s", zone.id)
    if made:
        log.info("imported %d area(s) from the old zone settings", made)
    return made


def _legacy_hours(zone: ZoneConfig, hours: HoursConfig):
    """(mode, from, to, note, never) for an old schedule.

    `never` means the old window covered no time at all, so the zone is
    imported paused rather than invented a meaning.
    """
    schedule = zone.schedule
    notes: list[str] = []
    mode, start, end, never = "always", None, None, False
    days = {WEEKDAYS.index(d) for d in schedule.days if d in WEEKDAYS}
    every_day = len(days) == 7

    if schedule.mode == "always" or schedule.start is None or schedule.end is None:
        pass
    elif schedule.start == schedule.end:
        # An empty window: outside it is always, inside it is never.
        if schedule.mode == "inside":
            never = True
            notes.append("Its old hours covered no time at all, so it is "
                         "imported paused.")
    elif schedule.mode == "outside":
        if (days == set(hours.working_days) and schedule.start == hours.start
                and schedule.end == hours.end):
            mode = "outside_working"
        else:
            # Outside the window every day: from its end to its start.
            mode = "custom"
            start, end = f"{schedule.end:%H:%M}", f"{schedule.start:%H:%M}"
            if not every_day:
                notes.append(
                    "Weekend daytime was restricted before and is not now: "
                    "watching used to apply all day on the days not listed.")
    else:  # inside
        mode = "custom"
        start, end = f"{schedule.start:%H:%M}", f"{schedule.end:%H:%M}"
        if not every_day:
            notes.append(
                "It used to be restricted on the listed days only; the hours "
                "now apply every day.")

    if abs(zone.min_dwell_seconds - 2.0) > 1e-9:
        notes.append(
            f"Its minimum stay of {zone.min_dwell_seconds:g} s is now the "
            f"fixed 2 s.")
    return mode, start, end, " ".join(notes) or None, never


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _iso(when: datetime | None) -> str | None:
    return when.astimezone(timezone.utc).isoformat() if when else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_area(row: sqlite3.Row) -> Area:
    return Area(
        id=row["id"], kind=row["kind"], name=row["name"],
        camera_id=row["camera_id"],
        polygon=tuple((float(x), float(y)) for x, y in json.loads(row["polygon"])),
        hours_mode=row["hours_mode"], hours_from=row["hours_from"],
        hours_to=row["hours_to"], notify_in_app=bool(row["notify_in_app"]),
        notify_email=bool(row["notify_email"]), paused=bool(row["paused"]),
        paused_by=row["paused_by"], paused_at=_parse(row["paused_at"]),
        alert_after_seconds=row["alert_after_seconds"],
        assignee_id=row["assignee_id"], limit_minutes=row["limit_minutes"],
        created_at=_parse(row["created_at"]), created_by=row["created_by"],
        updated_at=_parse(row["updated_at"]),
        deleted_at=_parse(row["deleted_at"]), deleted_by=row["deleted_by"],
        import_key=row["import_key"], import_note=row["import_note"],
    )
