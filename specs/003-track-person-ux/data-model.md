# Phase 1 — Data model: Track a person

One new table, one new config surface, two in-memory session shapes, and
additive wire types. Nothing existing changes shape.

---

## 1. Storage

### `anchor` (new table, lives in the sightings database file)

Written by the recognition worker via `AnchorStore` when the accumulator's
gates all pass (research D6). An anchor is a **span with evidence**, not an
instant.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `person_id` | TEXT | enrolled person |
| `camera_id` | TEXT | where |
| `started_at` / `ended_at` | TEXT ISO-UTC | the span the evidence covers |
| `local_date` | TEXT | site-local date, same rule as sightings |
| `matches` | INTEGER | how many frames matched |
| `best` / `mean` | REAL | scores |
| `face_px` | INTEGER | smallest face side that contributed |
| `model` | TEXT | face model version |

Indexes: `(person_id, local_date)`, `(local_date)`.

Skeleton query: anchors for person + date + window, ordered by `started_at` —
one indexed read. **Nothing below the gates is ever written**, so the query
cannot return a wrong leg.

### `measured_rates` (one row, same database)

Written by `tools/measure_track.py`; read by every estimate.

| Column | Notes |
|---|---|
| `fetch_x` | archive fetch speed, × real-time |
| `process_fps` | detection+track+encode frames/sec |
| `measured_at` | when; stale measurements are surfaced, not hidden |

Absent row → estimates unavailable, sweeps disabled, page says so.

### Leg chunks (files, not rows)

`clips_dir/track/<job_id>/chunk-NNN.mp4`. Keep-last-N legs per camera (zones
keep-3 idiom). A leg is always re-derivable from the DVR.

## 2. Config (`engine.yaml` → `vg/config.py`)

- `CameraConfig.faces: bool = False` — patrol tier (D5). Existing `area:`
  stays required and partitions the live grid.
- `CameraConfig.neighbours: tuple[str, ...] = ()` — optional; prefetch hint
  until the adjacency-map spec lands. Fallback: same area.
- New `archive:` section — per-DVR playback URL template with `{channel}`,
  `{start}`, `{end}`; per-camera channel mapping; `backend: dvr | footage`.
  Dev default: `footage` over `footage_dir`.
- Patrol rates: `patrol_hz` (default 0.5) and per-tier anchor-gate numbers
  under a `tracking:` section — lenient corner defaults (owner decision).

## 3. In-memory session shapes (engine)

### FollowSession (held by `TrackingWorker`)

| Field | Notes |
|---|---|
| `stable_id` | the followed appearance identity |
| `started_by` / `started_at` | audit facts |
| `camera_id` | where the body currently is |
| `trail` | (camera_id, at) hops so far |
| `recording` | None or {timer_deadline, segments: [Recording]} |
| `ended` | reason: manual / timer / track lost |

Advanced only inside `analyse()` — no thread of its own. One session at a
time (spec: one tracked person per operator scope).

### Leg / sweep jobs (held by the archive runner)

Reuses the `SearchJob` wire shape: `id`, `state` (queued | running | done |
failed), `progress`, plus `chunks_ready`, `chunks_total`, `hits` (sweep).
Restart loses jobs; the page re-offers the action.

## 4. Wire changes — all additive

### `PathAnchor` (new)

`camera_id`, `camera_name`, `place`, `at: Instant`, `until: Instant`,
`matches: int`, `score: Confidence`, `face_px: int` — the evidence travels so
the UI can answer "why do you believe this?". **No box geometry** — an anchor
is a stop on a path, not an overlay.

### `PathSkeleton` (new)

`subject: PersonRef`, `date`, `audit_id` (written before return, `/track`
idiom), `anchors: list[PathAnchor]`, `appearance: list[TrackStop]` (the blue
layer, unchanged shape, never named).

### `FollowView` (new)

`stable_id`, `camera_id`, `camera_name`, `since: Instant`,
`name: str | None` + `match: MatchKind` (FACE only after the sustained gate),
`trail: list[TrailHop]`, `recording: FollowRecording | None`
(`state`, `timer_seconds_left`, `segments: list[Recording]`), `ended_reason:
str | None`.

### `LegJob` / `SweepJob` (new, SearchJob-shaped)

`job: SearchJob`, `chunk_urls: list[str]` (grows as chunks land),
`next_prefetched: str | None`; sweep adds `hits: list[PathAnchor-like]` and
`estimate_seconds`.

### `SweepEstimate` (new)

`seconds`, `camera_hours`, `allowed: bool`, `reason: str | None`,
`measured_at: Instant | None` — the arithmetic shown before anything runs.

### `CameraView` — one additive field

`faces: bool = False` so the console can show which tier a camera is in
(Settings/System Health surfaces, not the Track page).

## 5. Entity summary

| Entity | Lives in | Change |
|---|---|---|
| Anchor | new `anchor` table | new |
| Measured rates | one row, sightings db | new |
| Follow session | TrackingWorker memory | new, no thread |
| Leg/sweep job | archive runner memory + chunk files | new |
| Sighting / appearance rows | existing tables | untouched |
| TrackedIdentity / LiveTracking wire | existing | untouched |
