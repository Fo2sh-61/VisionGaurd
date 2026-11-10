# Research: 025 zones and stations

Every finding was read in the code at commit `5ea8e67`. "From 022" means 022's plan already
decides it and 025 builds on it.

## R1 — Where the areas live: one table, soft delete

- **Finding**: today a zone is a camera. `LiveStore.zones()` (`live.py` ~1066) lists every camera;
  `set_zone_enabled` writes `camera_restricted` (`ingest/store.py` ~55, `set_restricted` ~224);
  the zone `id` on the wire is the camera id; `FRAME_CORNERS` is faked into `Zone.polygon`.
  `engine.yaml` polygons (`ZoneConfig`, `config.py` ~551) are read only for the camera overlay
  (`_zone_overlay`, `live.py` ~679) and the people worker's occupancy, which nothing reads
  (grep `zones_on`/`zone_count`: no callers outside `people.py`).
- **Decision**: one `area` table, `kind` = `zone` | `station`, kind-specific columns nullable,
  `deleted_at` for delete. One table because name, camera, polygon, hours and Notify are identical
  and the editor, the validation and the hours rule are written once.
- **Rejected**: two tables (every shared rule twice); a JSON blob column per kind (cannot be
  queried by camera); reusing `camera_restricted` (no polygon, no name, keyed by camera).
- **Delete is soft** because P14-FR-413 keeps the log and totals visible: scenes and station
  events keep their `zone_id` / `station_id`, and the name is read from the row.

## R2 — The zone machine: re-key, do not rewrite

- **Finding**: `ZonesWorker` (`features/zones.py`) is one state machine per camera: dicts
  `_candidates`, `_live`, `_last_person_at`, `_announced` are keyed by `camera_id`, and
  `analyse()` returns before any detection call when the camera is not restricted (the
  "costs nothing" rule). Constants `CONFIRM_SECONDS = 2`, `GAP_SECONDS = 5`,
  `ALERT_AGAIN_AFTER_SECONDS = 60`, `MAX_SCENE_SECONDS = 120` already equal P14-FR-417.
- **Decision**: key those four dicts (and `SceneState`) by zone id. `analyse(frame)` loops the
  camera's areas: for each *watching* area count people whose `feet_point` is inside the polygon
  (a full-frame polygon makes every person inside, so the old behaviour is a special case and
  SC-404's "same scenes as today" is a test, not a hope), then run the unchanged body. The early
  return stays: no area watching now, or none at all, returns before `detector.detect`.
- **Closing on the camera's own thread** is kept (the long comment on `set_restricted` explains the
  race that destroyed clips). `set_restricted(ids)` becomes `set_areas(areas)`: one assignment.
  A paused, deleted or out-of-hours area has its scene closed by `analyse` on the next frame
  (end reasons `switched_off`, new `hours`).
- **Alert after N seconds (408)**: `SceneStore.open()` calls the hook only when the zone's alert
  timing is 0. For N > 0 the worker, while the scene keeps seeing people, calls
  `SceneStore.alert(scene_id)` once `now - started_at >= N`; that method re-uses the same
  `on_open` hook. `_announced` changes meaning from "a scene opened in this run" to "an alert
  was raised in this run", otherwise a 4-second visit that never alerted would silence the
  next arrival (scenario 4 plus the one-minute rule).
- **One clip per camera (edge case)**: the zone recorder (`Recorder`, own instance in
  `_start_zones`) refuses a second `start` with `AlreadyRecording`. That already becomes a
  `fail_clip` with `BUSY_REASON`; the sentence changes to the spec's "No clip - recorded under the
  other zone's entry" (the old text blamed a recording that, by the comment beside it, can only be
  this feature). The recording stops when its owner scene closes, exactly as now.
- **Rejected**: one worker per zone (threads multiply and the per-camera recorder would clash);
  a second polygon-aware worker beside the old one (two sources of truth for one log).

## R3 — Importing what already exists (P14-FR-415)

- **Whole-camera zones**: for every camera with a `camera_restricted` row, or with rows in
  `zone_scene`, create a full-frame zone with `id = camera id` and name = the camera's name;
  paused = the row says not restricted. Using the camera id as the zone id means `zone_scene` rows
  need only `UPDATE ... SET zone_id = camera_id WHERE zone_id IS NULL`: history and clips follow
  with no copying (SC-405).
- **`engine.yaml` polygons**: `zone-desk` (always) imports cleanly. `zone-chem` is
  "outside 08:00-16:00, Monday to Friday" which `Schedule.is_restricted_at` (`config.py` ~130)
  also treats as restricted all weekend. The Watched rule cannot say that, so it becomes Custom
  16:00 to 08:00 and its `import_note` says "weekend daytime was restricted before and is not now;
  min dwell 3 s is now the fixed 2 s". The rule: `always` becomes Always; `outside` with the
  Settings hours and days becomes Outside working hours, else Custom from the window's end to its
  start; `inside` becomes Custom with the window; anything not exactly expressible is written to
  `import_note` and shown on the zone's card. `enabled: false` imports paused.
- **Once**: each imported row has a unique `import_key` (`camera:<id>`, `yaml:<id>`) kept even
  after a soft delete, so deleting an imported zone does not bring it back at the next start.
  The tuple `Config.zones` and `ZoneConfig` stay (the people worker still takes them) but nothing
  else reads them after import; removing the yaml entries is a later tidy.
- **Rejected**: asking the owner to redraw (spec says nothing may disappear); importing every
  camera as a zone (would show dozens of zones nobody ever had).

## R4 — The station machine

One state machine per station, run per frame inside `analyse`, with its times from
`frame.captured_at` (like zones; a test chooses its own clock). `present` = somebody counts this frame.

| From | To | When | Stored time of the change |
|---|---|---|---|
| (none) | On or Away | first frame inside the watched hours: On if present for `return_confirm`, else Away | that frame |
| On | Away | nobody counted for `leave_confirm` (8 s) | the last moment somebody counted |
| Away | On | counted continuously for `return_confirm` (3 s); gaps under 2 s do not break the run | the first moment of the run |
| Away | Absent | `now - away_since >= limit_minutes` | `away_since + limit` exactly |
| any | closed | the watched hours end | the hours end (absence does not carry over) |
| any | gap | no frame for 10 s | closed at the last frame; the next frame starts fresh, Away clock restarts |

- The gap row is what makes SC-505 and SC-506 true with no extra code: a stopped camera or a
  stopped engine writes nothing and raises nothing; the missing time is simply "not watched".
- **Away clock after a gap restarts** rather than continuing: counting a gap as empty time would
  raise an alert for time nobody measured.
- **Alert once per absence**: the alert key is `station:<id>:<away_since>`; `StationStore` refuses a
  second event with the same key, so a restart in the middle of an absence cannot alert twice.
- **Segments, not seconds counters**: `station_segment(station_id, state, started_at, ended_at,
  checked_at)`. The open row's `checked_at` is refreshed at most every 10 s; at start,
  `close_orphans()` sets `ended_at = checked_at`. Today's working time, absence time, rate and
  the timeline are all one query over segments clipped to today's watched window. Rate = on
  seconds / (watched seconds covered by any segment); uncovered watched time is reported as
  not watched (P14-FR-518, 520).
- **Rejected**: counting once a second in a timer thread (a second clock, can disagree with the
  frames); storing a state per second (a row per second per station); estimating the
  time between two sparse samples.

## R5 — The assigned person: a yes/no, nothing remembered

- **Finding**: face recognition (`RecognitionWorker._look`, `features/recognition.py` ~204) already
  crops people (`person_crops`, ~87) and runs `FacePipeline.observe(crop)`; `gallery.match(...)`
  returns a `Match` with `person`. Its results go to attendance, the tracker and anchors. That path
  must not be touched: stations would then need attendance (rule 9) and its "names" would reach
  the tracker (rule 2).
- **Decision**: `StationsWorker` holds the same `FacePipeline` and `FaceGallery` objects
  (`face_pipeline`, `face_gallery` from `_start_enrolment`, as `_start_archive(face=...)` already
  receives them), so there is **one** SFace/YuNet copy in memory (P14-FR-533). Per frame, only for
  a station with an assignee: take the people whose feet are inside the polygon, crop them with
  `person_crops`, call `observe`, `gallery.match`, and set `present = any(match.person.id ==
  assignee)`. The result is a bool. No dict, no set, no list of ids survives the method; the
  worker's only per-station memory is timers about "somebody counted", never who.
- **Deleted from the directory**: if `gallery.person(assignee_id)` is None the station says so and
  counts anyone (spec edge case); the id is kept so restoring the person restores the check.
- **Why a pipeline and not a new model**: SFace is settled and the owner supplies models.
- **Cost control**: the face step runs only when an assigned station has someone standing in it
  (person boxes come from the shared pass, already cached per frame). An empty station, or one
  with no assignee, costs one `feet_point` test per person.
- **Present but not recognised (514)**: `StationsResult` carries `unrecognised: bool` per station
  (a person is in the area, nobody matched). It is a live flag for the card, never stored.

## R6 — Can faces be read here (513)

- **Decision**: *measure*, do not estimate. Two readings:
  1. **While running**: when an assigned station has people inside and `observe` returns nothing,
     the worker runs `pipeline.detector.detect(crop, min_size=20)` (YuNet only, cheap) and keeps
     the widest face found in a 10-minute window. `reach_px` below `stations.min_face_px` (80)
     with at least 5 faces seen means "too small here": the station counts anyone and says so.
     Never measured yet means the normal face check (conservative: nobody reads On station
     without a face).
  2. **At edit time**: `GET /stations/face-reach?cameraId=` runs one YuNet pass on the camera's
     last picture and returns the widest face in pixels, or null when nobody is in view. The editor
     warns when it is under 80 and says "cannot tell yet; have someone stand in the picture"
     when it is null. A person-height rule of thumb was rejected: it would print a number the code
     cannot back (rule 5).
- 80 px is `infer/faces.py::MIN_FACE_PIXELS` (measured by the owner, see its comment). It is
  referenced, not copied, so the two cannot drift.

## R7 — Alerts: one new kind, per-area channels

- **Finding**: `KINDS` (`alerts/events.py:29`) is five names; `AlertEvent.__post_init__` rejects
  others and any fact outside `ALLOWED_FACTS` (~33); `AlertService._record` (`service.py` ~376) asks
  `rule.channel_on(channel)` from the Settings row; `attention()` (`live.py` ~2558) shows
  intrusion items when the row's `in_app` is on. `DEFAULT_RULES` is inserted with `INSERT OR
  IGNORE` (`alerts/store.py` ~216), so a new row appears on existing databases.
- **Decision**: add kind `station` (default In-app on, Email off), templates `station.absent`
  (en and ar; says station, camera, "empty for more than N min", time, and the assignee's name
  only when there is one) and facts `station`, `assignee`, `limit` (P14-FR-524 is the reason the
  spec requires for widening the list). Add `AlertEvent.channels: frozenset[str] | None = None`:
  when set, `_record` uses it in place of the rule's channel flags; when None nothing changes.
  Zone and station hooks fill it from the area row. Home's in-app test reads the same row.
- **Settings row is the default only**: the editor pre-ticks the row's current values for a new
  area; later changes to the row do not move existing areas (the owner's 10 Nov decision).
- **Acknowledge**: writes a `station_event` of kind `acknowledged` (by whom, when). Home's
  `attention()` builds the station items from unacknowledged absence events, so there is one fact and
  no second table. `LiveStore.acknowledge()` routes ids starting `station:` to the station store.
- **Rejected**: new `alert_rule` columns for per-area flags (the flags belong to the area);
  a second alert queue.

## R8 — Permissions and routes

- `/zones` is already in `ADMIN_WRITE_PREFIXES` (`deps.py` ~97): create, edit, pause, delete are
  admin-only with no change. `/stations` is added there. Acknowledge
  (`POST /stations/{id}/acknowledge`) must be open to IT, which a prefix cannot say without opening
  `PATCH /stations/{id}`: it uses the anchored pattern list 022 adds beside
  `OPERATOR_WRITE_PREFIXES` for recording (022 R1). If 022 built a single pattern, turn it into a
  tuple.
- Reads of `/zones` and `/stations` stay open to every signed-in user (owner, 10 Nov).

## R9 — Camera setup and the person detector

- `FEATURES` (`config.py` ~209) gains `stations`; the camera form's list (`CameraSources.tsx`
  `FEATURES` ~134) gains a row "Work stations", cost text "shares the person detector". 022 relabels
  `intrusion` "Restricted zones" in the same list.
- **Saving an area on a camera that does not list the feature** adds the feature through
  `LiveStore.edit_camera` (`live.py` ~747), which already calls `_apply_features`. That is "enabling
  an area starts it" and it avoids a zone that is saved and never watched (rule 4). It writes one
  audit line (`camera.edit`, "changed features").
- `_apply_features` (`live.py` ~881) gets a `("stations", self.stations_worker, "stations" in wanted,
  self.stations_error)` row. `PERSON_FEATURES` does **not** gain `stations`: the people worker only
  feeds counting boxes; stations read `SharedDetection` themselves.

## R10 — Honest states on the pages (rules 4, 7, 8)

- Zone card status comes from the worker: `payload(camera_id)` is None after 3 s of no result, which
  with a camera that is up is "detector stopped", with a camera down is "camera offline". Outside
  watched hours is its own status ("Not watching now"): showing "Zone clear" there would claim a
  check that is not happening.
- Station `unknown` has a reason code (`camera_offline`, `detector_stopped`, `not_running`) and the
  console words it; tiles skip Not started, Closed and Unknown, and name the Unknown ones.
- `_stations_state()` mirrors `_breaches_state()` (`live.py` ~3024): three different failures,
  three different sentences. A System Health stage `stations` sits beside `_vehicles_stage`.

## R11 — Cost and the Jetson (P14-FR-533, SC-406, SC-508)

- Station worker's own cost is small bookkeeping (`ASSUMED_MS_PER_FRAME["stations"] = 1.0`, flagged
  as an estimate until measured) plus the face step on assigned stations only. It joins the readers
  of the shared person pass in `_shared_pass_row` (`live.py` ~3455) and must expose `restricted()` (the
  cameras it asks the pass on, as the zones worker does; see context traps).
- The Windows laptop can measure the figures; the **Jetson** figures wait for the new board. Memory
  needs no new code: 022's System Health memory reading shows the total, and the face models are
  loaded once.
