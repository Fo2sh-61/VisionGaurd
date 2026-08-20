# Phase 1 — Data model: Restricted Zones

Two storage changes and three additive wire fields. Nothing existing changes
shape.

---

## 1. `camera.restricted` — the toggle

Added to the existing `camera` table in `engine/vg/ingest/store.py`.

| Column | Type | Notes |
|---|---|---|
| `restricted` | `INTEGER NOT NULL DEFAULT 0` | 1 = the whole frame is a restricted zone |

Added with an `ALTER TABLE` guarded by `PRAGMA table_info(camera)` so an
existing database upgrades in place and a fresh one gets it from `CREATE TABLE`.

**Accessors** on `CameraStore`:
- `set_restricted(camera_id: str, restricted: bool) -> bool` — returns False if
  no such camera, so the endpoint can 404 truthfully.
- `restricted_ids() -> set[str]` — read by the worker.

**Rules**
- Default 0. A new camera is not watched until somebody switches it on.
- A removed camera (`removed_at` set) is excluded from `restricted_ids()`.

---

## 2. `zone_scene` — one row per scene

New table in `engine/vg/events/zones.py`, following `events/sightings.py`.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | uuid4 hex |
| `camera_id` | `TEXT NOT NULL` | |
| `started_at` | `TEXT NOT NULL` | UTC ISO-8601, from `frame.captured_at` |
| `ended_at` | `TEXT` | NULL while the scene is still running |
| `peak_people` | `INTEGER NOT NULL DEFAULT 1` | highest count seen during the scene |
| `clip_path` | `TEXT` | absolute path; NULL when no clip was written |
| `clip_state` | `TEXT NOT NULL DEFAULT 'none'` | `none` \| `recording` \| `saved` \| `replaced` \| `failed` |
| `clip_reason` | `TEXT` | why there is no playable clip; NULL when `saved` |
| `end_reason` | `TEXT` | `nobody` \| `limit` \| `switched_off` \| `shutdown` |

Index: `(camera_id, started_at DESC)` — every query is "recent scenes",
optionally per camera.

### `clip_state` transitions

```
none ──start ok──> recording ──saved──> saved ──next scene saved──> replaced
 │                     │
 │                     └──recorder failed──> failed
 └──recorder refused (already recording) ──> failed
```

`replaced` and `failed` are terminal. Rows are **never deleted** — only the
file on disk goes away.

### Invariants (each gets a test)

1. `clip_state == 'saved'` ⟹ `clip_path` is set and the file exists.
2. `clip_state != 'saved'` ⟹ the Watch clip control is disabled and
   `clip_reason` explains why.
3. At most one row per `camera_id` has `clip_state == 'saved'`.
4. At most one row per `camera_id` has `ended_at IS NULL`.
5. A row is never deleted.

### `SceneStore` methods

| Method | Purpose |
|---|---|
| `open(camera_id, started_at) -> str` | insert, return id |
| `note_people(scene_id, count)` | raise `peak_people` if higher |
| `close(scene_id, ended_at, end_reason)` | set the end |
| `attach_clip(scene_id, path)` | `saved`, and mark that camera's previous `saved` row `replaced` + unlink its file |
| `fail_clip(scene_id, reason)` | `failed` with the operator-readable reason |
| `recent(since_days, camera_id=None) -> list[Scene]` | newest first |
| `close_orphans(reason='shutdown')` | on start, close any row left open by a crash — so nothing shows as recording forever |

---

## 3. Wire changes — all additive

### `Zone` (unchanged shape, redefined meaning)

| Field | Value now |
|---|---|
| `id` | the camera id |
| `name` | the camera name |
| `camera_id` | same as `id` |
| `polygon` | the four frame corners — the zone *is* the frame |
| `enabled` | the `restricted` column |
| `schedule` | `ALWAYS` — no schedules in this feature |
| `breaches_today` | scenes for that camera today (real count) |

### `Breach` — three new optional fields

| Field | Type | Why |
|---|---|---|
| `people` | `int` (default 1) | peak people seen (P4-FR-012) |
| `clip_state` | `str` (default `"none"`) | so the UI can disable Watch clip *and say why* |
| `clip_reason` | `str \| None` | the plain-language reason |

Existing fields are reused: `zone_id`/`zone_name` carry the camera,
`dwell_seconds` carries the scene length, `at` its start, `clip` the playable
clip when there is one. `subject` is a `PersonRef` with
`match = MatchKind.NONE` and name `"Unidentified"` — **rule 1**: this feature
detects bodies and never names anyone.

`status` is `OPEN` while the scene is running, `RESOLVED` once it has ended.
No review workflow in this feature.

### `CameraView.zone` on this page

Left `None` for restricted-zone cameras, so no rectangle is drawn
(P4-FR-002).

---

## 4. Entity summary

| Entity | Lives in | Survives restart |
|---|---|---|
| Restricted flag | `camera.restricted` | **yes** |
| Scene | `zone_scene` | **yes** |
| Clip file | `clips_dir/zones/` | **yes**, one per camera |
| In-flight scene state | `ZonesWorker` memory | no — closed as `shutdown` on next start |
