# Phase 1 — Data model: Restricted Zones

Two storage changes and three additive wire fields. Nothing existing changes
shape.

---

## 1. `camera_restricted` — the toggle

**Corrected after the pipeline run.** This section originally specified a
`restricted` column on the existing `camera` table. That could never work, and
the recorded-clip check is what proved it: **most cameras have no row in
`camera` at all.** The baseline roster comes from `engine.yaml`; that table
holds only what the console has added since. The toggle therefore 404'd on
every camera a site starts with, including the walk-through clip.

Inserting a stub `camera` row on first toggle was considered and rejected:
`merge_cameras` lets a stored row win a clash, so flipping a toggle would
quietly freeze that camera's name, fps and features, and later edits to
`engine.yaml` would stop taking effect with nothing on screen to say why.

New table in `engine/vg/ingest/store.py`:

| Column | Type | Notes |
|---|---|---|
| `camera_id` | `TEXT PRIMARY KEY` | not a foreign key — the camera may live only in `engine.yaml` |
| `restricted` | `INTEGER NOT NULL DEFAULT 0` | 1 = the whole frame is a restricted zone |
| `changed_at` | `TEXT NOT NULL` | UTC ISO-8601 |

Created by `CREATE TABLE IF NOT EXISTS`, so an existing database gains it on
the next start without losing a row and without migration tooling.

**Accessors** on `CameraStore`:
- `set_restricted(camera_id: str, restricted: bool) -> None` — an upsert. It
  accepts any id, because this table cannot see which cameras exist.
- `restricted_ids() -> set[str]` — read by the worker and by `LiveStore`.

**Rules**
- Default off. A new camera is not watched until somebody switches it on.
- **Existence is checked against the roster, not this table.**
  `LiveStore.set_zone_enabled` refuses an id that is not in
  `registry.configs()`, which is how the endpoint 404s truthfully.
- `CameraStore.remove` deletes the row: removing a camera has to stop it being
  watched. The scenes it already produced are kept.
- `LiveStore._restricted_ids()` intersects with the roster, so a camera removed
  after somebody restricted it does not keep appearing as a watched area.

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
none ──start ok──> recording ──saved──> saved ──4th newer clip saved──> replaced
 │                     │
 │                     └──recorder failed──> failed
 └──recorder refused (already recording) ──> failed
```

`replaced` and `failed` are terminal. Rows are **never deleted** — only the
file on disk goes away.

### Invariants (each gets a test)

1. `clip_state == 'saved'` ⟹ `clip_path` is set and the file exists.
2. `clip_state != 'saved'` ⟹ there is no Watch clip control and
   `clip_reason` explains why. `replaced` rows are not listed at all;
   `failed` and `recording` ones are, with their reason in place of the
   button.
3. At most `CLIPS_KEPT_PER_CAMERA` (3) rows per `camera_id` have
   `clip_state == 'saved'`.
4. At most one row per `camera_id` has `ended_at IS NULL`.
5. A row is never deleted.

### `SceneStore` methods

| Method | Purpose |
|---|---|
| `open(camera_id, started_at) -> str` | insert, return id |
| `note_people(scene_id, count)` | raise `peak_people` if higher |
| `close(scene_id, ended_at, end_reason)` | set the end |
| `attach_clip(scene_id, path)` | `saved`, and mark that camera's `saved` rows beyond the newest three `replaced` + unlink their files |
| `fail_clip(scene_id, reason)` | `failed` with the operator-readable reason |
| `recent(since_days, camera_id=None, include_replaced=True) -> list[Scene]` | newest first; `include_replaced=False` is what the console's log asks for |
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
| Restricted flag | `camera_restricted` | **yes** |
| Scene | `zone_scene` | **yes** |
| Clip file | `clips_dir/zones/` | **yes**, newest three per camera |
| In-flight scene state | `ZonesWorker` memory | no — closed as `shutdown` on next start |
