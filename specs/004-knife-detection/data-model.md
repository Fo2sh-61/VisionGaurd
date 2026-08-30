# Phase 1 — Data model: Knife detection

One new table, five additive wire fields, one optional wire field, one
widened store signature, one config property. Nothing existing changes shape.

---

## 1. `weapon_scene` — one row per scene

New table in `engine/vg/events/weapons.py`, following `events/zones.py`
(`zone_scene`) column for column where the meaning is the same.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | uuid4 hex |
| `camera_id` | `TEXT NOT NULL` | |
| `started_at` | `TEXT NOT NULL` | UTC ISO-8601 — the **first sighting** (`candidate.first_at`), not the moment the scene opened |
| `ended_at` | `TEXT` | NULL while the knife is still in view |
| `peak_confidence` | `REAL NOT NULL` | highest knife confidence seen during the scene; never lowered |
| `model_version` | `TEXT NOT NULL` | `WeaponDetector.version` at open — the weights' stem |
| `clip_path` | `TEXT` | absolute path; NULL when no file |
| `clip_state` | `TEXT NOT NULL DEFAULT 'none'` | `none` \| `recording` \| `saved` \| `expired` \| `failed` |
| `clip_reason` | `TEXT` | why there is no playable video; NULL when `saved` |
| `end_reason` | `TEXT` | `gone` \| `limit` \| `shutdown` |
| `verdict` | `TEXT NOT NULL DEFAULT 'pending'` | `pending` \| `confirmed` \| `dismissed` |
| `reviewed_by` | `TEXT` | the signed-in account's name; NULL while pending |
| `reviewed_at` | `TEXT` | UTC ISO-8601 |
| `review_reason` | `TEXT` | optional free text from the reviewer |

Index: `(camera_id, started_at DESC)` — every read is "recent scenes", the
page's list is "recent scenes in a window".

### `clip_state` transitions

```
none ──recorder accepted──> recording ──saved──> saved ──older than retention──> expired
 │                              │
 │                              └──recorder failed / no frames──> failed
 └──recorder refused (AlreadyRecording) / no recorder──> failed
```

`expired` and `failed` are terminal. **Rows are never deleted**; only the
file goes, and it is unlinked only *after* the row says `expired`.

### `verdict` transitions

```
pending ──review──> confirmed
pending ──review──> dismissed
```

Nothing moves back. `WeaponReview` already refuses `pending` (422); the store
refuses a second review (returns `False`; the endpoint 404s "already
reviewed").

### Invariants (each gets a test)

1. `clip_state == 'saved'` ⟹ `clip_path` set and the file exists; `clip` on
   the wire only then.
2. `clip_state != 'saved'` ⟹ `clip_reason` is a sentence, and the wire
   carries no `clip`.
3. At most one row per `camera_id` has `ended_at IS NULL`.
4. A `saved` row older than `clip_retention_days` does not survive a sweep.
5. `verdict != 'pending'` ⟹ `reviewed_by` and `reviewed_at` are set.
6. A row is never deleted; `recent(None, None)` returns every row ever
   written.

### `WeaponSceneStore` methods

| Method | Purpose |
|---|---|
| `open(camera_id, started_at, confidence, model_version) -> str` | insert, `pending`, return id |
| `note_confidence(scene_id, confidence)` | raise the peak, never lower it |
| `close(scene_id, ended_at, end_reason)` | set the end; closing twice changes nothing |
| `start_clip(scene_id)` | recorder accepted → `recording` |
| `attach_clip(scene_id, path)` | → `saved`; then `expire()` |
| `fail_clip(scene_id, reason)` | → `failed` with the operator's sentence |
| `review(scene_id, verdict, reviewer, at, reason) -> bool` | only when `pending`; `False` otherwise |
| `expire(older_than: datetime) -> int` | `saved` → `expired` + unlink, oldest first, mark then unlink |
| `get(scene_id) -> WeaponScene \| None` | |
| `recent(since, until=None, camera_id=None) -> list[WeaponScene]` | newest first; `None` bounds mean open-ended |
| `close_orphans(reason='shutdown') -> int` | on start; a `recording` orphan becomes `failed` with "The engine stopped while this was recording" |
| `close_db()` | |

`WeaponScene` is a frozen dataclass mirroring the columns, with `running`,
`seconds` and `playable` properties exactly as `Scene` has them.

---

## 2. Wire changes — all additive

### `WeaponDetection` — five new optional fields

| Field | Type | Why |
|---|---|---|
| `ended_at` | `Instant \| None` (default `None`) | `None` means the knife is still in view (the page says "Still in view") |
| `seconds` | `float` (default `0.0`) | how long the scene lasted, so far or in total (P6-FR-005) |
| `clip_state` | `str` (default `"none"`) | so the UI can withhold Watch *and say why* |
| `clip_reason` | `str \| None` | the plain-language reason |
| `end_reason` | `str \| None` | `limit` lets the entry say it was cut at two minutes |

Existing fields, filled by the live store: `at` = first sighting, `camera_id`
/ `camera_name` from the roster, `location` = the camera's area, `item` =
`"Knife"`, `confidence` = peak, `severity` = `CRITICAL` unless dismissed then
`INFO`, `verdict` / `reviewed_by` / `reviewed_at` / `dismissal_reason` from the
row, `clip` only when `saved` (url `/weapons/{id}/clip`), `model_version`
from the row. `box` stays `None` — boxes are live overlay, not history.

### `WeaponReview.actor` — becomes optional

`actor: str | None = None`. The live endpoint records the session user and
ignores this; `MockStore` keeps using it. The console stops sending it.

### `Box` on the knife overlay

`kind="weapon"`, `label="Knife"`, `confidence`, `severity=CRITICAL`,
`match=NONE`, no `track_id`. `format.ts::boxColor` paints `critical` red today.

### `Capability` / `PipelineStage`

No shape change. `CAPABILITIES` entry `("weapons", "Knife detection")` —
name only; the health stage keyed `weapons` becomes real.

---

## 3. Store protocol — one widened signature, one new method

| Method | Today | After |
|---|---|---|
| `weapons(self, since_days: int)` | | `weapons(self, since: datetime \| None, until: datetime \| None = None)` |
| `review_weapon(self, detection_id, review)` | | `review_weapon(self, detection_id, review, reviewer: str \| None = None)` |
| — | | `clip_for_weapon(self, detection_id) -> (path, reason)` — copy of `clip_for_breach` |

`MockStore` implements all three (demo stays a working demo; its
`clip_for_weapon` returns `(None, "Demo mode has no video files.")`).

---

## 4. Configuration

| Where | Change |
|---|---|
| `engine/vg/config.py::StorageConfig` | property `weapon_clips_dir = clips_dir / "weapons"` — a subfolder, not a key, for the reason `zone_clips_dir` gives |
| `engine/engine.yaml::models.weapons` | `weights: models/knifebest.pt`, `imgsz: 640`, `conf: 0.5`, `iou: 0.45`, `half: true`, `version: knife-v3-2026-08-13`; the comment block rewritten |
| `engine/engine.yaml::cameras[cam-rtsp-1].features` | drop `weapons` — every enabled camera is checked, a feature flag would read as a switch |
| `features/weapons.py` constants | `CONFIRM_HITS = 3`, `CONFIRM_SECONDS = 1.0`, `CANDIDATE_GAP_SECONDS = 2.0`, `GAP_SECONDS = 10.0`, `MAX_SCENE_SECONDS = 120.0`, `ACTOR = "knife-detection"` |
| `storage.clip_retention_days` | already 30; now read by `expire()` |

---

## 5. Entity summary

| Entity | Lives in | Survives restart |
|---|---|---|
| Scene + verdict | `weapon_scene` | **yes** |
| Clip file | `clips_dir/weapons/` | **yes**, until `clip_retention_days` |
| Candidate (sightings before a scene) | `WeaponsWorker` memory | no — it is sub-second by design |
| In-flight scene state | `WeaponsWorker` memory | no — closed as `shutdown` on next start |
| Audit entry for a verdict | in-memory audit (P3 makes it durable) | no — as every audit entry today |
