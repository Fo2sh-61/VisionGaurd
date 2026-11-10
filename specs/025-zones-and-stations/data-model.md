# Data model: 025

All tables are in the one SQLite file the engine already uses (`StorageConfig.database_url`, opened
with `vg/db.py::connect`, schema created in the store's `__init__` like `SceneStore`).

## area (new, `engine/vg/areas.py::AreaStore`)

One row per zone or station.

| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | uuid hex for new areas; **a camera id** for an imported whole-camera zone; `yaml id` for an imported polygon zone |
| kind | TEXT | `zone` or `station` |
| name | TEXT | 1 to 80 characters, trimmed |
| camera_id | TEXT | must exist in the roster at save time |
| polygon | TEXT | JSON `[[x, y], ...]`, fractions 0..1 |
| hours_mode | TEXT | zone: `always`, `outside_working`, `custom`. station: `working`, `custom` |
| hours_from, hours_to | TEXT NULL | `HH:MM`, only for `custom`. Zone: may cross midnight. Station: `from < to` |
| notify_in_app | INTEGER | 0 or 1; starts as the Settings row's value |
| notify_email | INTEGER | 0 or 1; starts as the Settings row's value |
| paused | INTEGER | zone only; 0 default |
| paused_by, paused_at | TEXT NULL | account name, ISO instant; set on pause, cleared on resume |
| alert_after_seconds | REAL NULL | zone only; 0 = alert once the entry is confirmed |
| assignee_id | TEXT NULL | station only; a `FaceGallery` person id |
| limit_minutes | INTEGER NULL | station only; 1 to 480 |
| created_at, created_by, updated_at | TEXT | |
| deleted_at, deleted_by | TEXT NULL | soft delete; the row stays for names and history |
| import_key | TEXT NULL UNIQUE | `camera:<id>` or `yaml:<id>`; kept after delete |
| import_note | TEXT NULL | what the old schedule could not say, in plain words |

Rules enforced by `AreaStore` and the API (422 with a reason): at least 3 points; every
coordinate within 0..1; no two edges cross; area at least `MIN_AREA_FRACTION` (0.002 of the
frame, so "almost a line" fails); a station needs `limit_minutes`; custom hours need both times;
`assignee_id` must exist in the gallery (a *later* deletion from the gallery is not an error: the
station reports it and counts anyone).

Effective watching of an area at a local time: not deleted, zone not paused, and `hours_mode`
allows it. `outside_working` is the complement of "a working day and between `hours.start` and
`hours.end`", with the working days and times from 022's `LiveStore.hours()`. `working` for a
station is that same window. Nothing here reads `engine.yaml` after the one-time import.

## zone_scene (existing, `events/zones.py`)

- Add `zone_id TEXT` (nullable). Backfill once: `UPDATE zone_scene SET zone_id = camera_id WHERE zone_id IS NULL`.
- Add index `idx_zone_scene_zone ON zone_scene(zone_id, started_at DESC)`.
- Add `alerted INTEGER NOT NULL DEFAULT 0` (set when the alert for this entry was raised; lets a
  restart not alert a second time and lets Home show only entries that did alert).
- New end reason `hours` (watched hours ended). `END_REASONS` is documentation; no CHECK exists.
- Retention is unchanged: `CLIPS_KEPT_PER_CAMERA = 3`, per camera, across zones.
- `camera_restricted` is left in place and no longer read after import.

## station_segment (new, `events/stations.py::StationStore`)

| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| station_id | TEXT | no foreign key; survives soft delete |
| state | TEXT | `on`, `away`, `absent` |
| started_at | TEXT | ISO UTC, the first moment of the situation |
| ended_at | TEXT NULL | NULL while open |
| checked_at | TEXT | last time the worker confirmed the segment (refreshed at most every 10 s) |

Index `(station_id, started_at)`. **Today's figures** are sums of these rows clipped to the
station's watched window for the day, in site-local time (`LiveStore._start_of_today`, which exists).
Watched time with no segment is *not watched*. `close_orphans()` at start sets `ended_at =
checked_at` on open rows.

## station_event (new)

| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | |
| station_id | TEXT | |
| at | TEXT | ISO UTC; the first moment of the change (`left_station` = last person seen) |
| kind | TEXT | `at_station`, `left_station`, `absence_alert`, `acknowledged` |
| limit_minutes | INTEGER NULL | on `absence_alert`: the limit in force then |
| alert_key | TEXT NULL UNIQUE | `station:<id>:<away_since stamp>` on `absence_alert` |
| by_who | TEXT NULL | account name on `acknowledged` |
| ref | TEXT NULL | on `acknowledged`: the `absence_alert` event id it answers |

Rows are never updated or deleted. An alert is *unacknowledged* when no `acknowledged` row refers
to it. The log wording ("Absence alert, over 5 min", "Alert acknowledged by Mona") is built by the
console from `kind`, `limitMinutes` and `byWho`.

## engine.yaml (seed, new block)

```yaml
stations:
  leave_confirm_seconds: 8     # nobody this long = Away
  return_confirm_seconds: 3    # somebody this long = back
  gap_tolerance_seconds: 2     # a missed detection shorter than this does not break a run
  stall_seconds: 10            # no frame this long = not watched
  min_face_px: 80              # below this, faces are too small to check an assignee
```

Parsed into `StationsConfig` in `config.py` (frozen dataclass, validated: all positive, `return <= leave`).

## Wire types (details in contracts/api.md)

`Zone` (extended, additive), `ZoneCreate`, `ZoneUpdate`, `WatchedHours`, `Station`, `StationDetail`,
`StationCreate`, `StationUpdate`, `StationEvent`, `TimelineSegment`, `FaceReach`.
`AlertKind` and `AttentionItem.kind` gain `"station"`; `DeliveryRow.kind` likewise.

## Existing data that moves (read-only facts)

- Old zone `id` on the wire is a camera id, so every id the console or the phone stored still
  resolves after import.
- `breaches()` today hides entries whose clip was replaced (`include_replaced=False`, `live.py`
  ~1155). From 025 it lists them with "No clip kept" (P14-FR-410). The row count of today's log
  is then the "entries today" figure.
