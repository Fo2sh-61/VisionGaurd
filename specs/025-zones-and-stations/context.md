# Implementation context: 025 restricted zones and work stations

**Written by `/speckit-plan` on 10 Nov 2026, against commit `5ea8e67` (worktree `console-v2-plans`).**

Read this **before** opening any source file, then open only the named anchors. If this
disagrees with the code, the code wins. Search for the symbol, not the line number. Everything
marked "(022)" is built by spec 022; read its context first and do not redo it. 025 is
implemented **after** 022 lands (it needs `LiveStore.hours()`, `useNavBadges`, `ToastProvider`,
the roles patterns and the x264 encoder).

---

## 1. Anchors

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/areas.py` | NEW | - | `Area` (frozen dataclass), `AreaStore` (table `area`, `_lock`, `db.connect`), `validate_polygon`, `watching_at(area, local_dt, hours)`, `import_legacy(...)`. Copy the store shape from `events/zones.py::SceneStore.__init__` |
| `engine/vg/events/zones.py` | `SCHEMA` (~48), `SceneStore.open` (~135), `recent` (~280), `counts_since` (~311), `close_orphans` (~247), `END_REASONS` | table `zone_scene` keyed by `camera_id`; `open(camera_id, started_at, continues)` commits then calls `self.on_open(scene_id, camera_id, started_at, continues)`; `counts_since` groups by `camera_id` | add `zone_id`, `alerted` columns (ALTER if missing, then backfill `zone_id = camera_id`); `open(..., zone_id, alert_now)` calls the hook only when `alert_now`; new `alert(scene_id)` that sets `alerted=1` and calls the same hook with `continues=False`; `recent(..., zone_id=None)`; `counts_since_by_zone`; end reason `hours`. Scene gets `zone_id`. `CLIPS_KEPT_PER_CAMERA` logic stays per camera |
| `engine/vg/features/zones.py` | `ZonesWorker.__init__`, `set_restricted` (~207), `restricted` (~229), `analyse` (~234), `_note_candidate`, `_end_run`, `_open` (~353), `_close` (~377), `_start_recording`, `BUSY_REASON` (~120) | state dicts `_candidates`, `_live`, `_last_person_at`, `_announced` keyed by camera id; `analyse` returns before `detector.detect` when the camera is not in `_restricted`; `people = len(self.detector.detect(frame))` | take `areas` (callable or `set_areas`), `clock`, `hours` callable; key the dicts by `area.id`; `analyse` loops the camera's areas, counts people with `point_in_polygon(*feet_point(p), area.polygon)` (import from `features/people.py`), runs the body per area; alert-after-N; change `BUSY_REASON` text to "No clip - the camera was already recording another zone's entry"; `restricted()` returns cameras with at least one area (still used by `_shared_pass_row`); `ZonesResult` gains per-zone counts. Keep every constant and the long comments |
| `engine/vg/features/stations.py` | NEW | - | `StationsWorker(FeatureWorker[StationsResult])`; copy the constructor and `_closing`/`stop` shape from `features/zones.py`; `self.device = "cpu"`; face step modelled on `features/recognition.py::_look` (`person_crops`, `pipeline.observe`, `gallery.match`) but returns only a bool |
| `engine/vg/events/stations.py` | NEW | - | `StationStore`: tables `station_segment`, `station_event`; `open_segment`, `close_segment`, `touch` (heartbeat, at most every 10 s), `add_event` (refuses a duplicate `alert_key`), `acknowledge`, `close_orphans`, `figures(station_id, window)`, `events(station_id, day)`, `open_alerts()`; `on_alert` hook attribute like `SceneStore.on_open`. Copy `events/zones.py` for locking and `_iso`/`_parse` |
| `engine/vg/config.py` | `FEATURES` (~209), `StationsConfig` (NEW), `EngineConfig` (~1287), `load` (~1376-1450), `ZoneConfig`/`Schedule` (~87, ~551) | frozenset of 7 feature names; `zones` tuple parsed from yaml | add `"stations"`; `StationsConfig.parse(raw.get("stations"), "stations")` (frozen, validated) as a new `EngineConfig` field; leave `ZoneConfig`/`Schedule` (the import reads them) |
| `engine/engine.yaml` | `zones:` (~579) | two polygon zones | add the `stations:` block (data-model.md). Leave the two zones until import is proven, then remove them in a separate tidy |
| `engine/vg/alerts/events.py` | `KINDS` (:29), `ALLOWED_FACTS` (~40), `AlertEvent` (~66), `intrusion_opened` (~138) | five kinds; ten facts; no per-event channel | add `"station"`; facts `station`, `assignee`, `limit`; field `channels: frozenset[str] \| None = None`; `station_absent(...)` builder (key `station:<id>:<stamp>`); `intrusion_opened(..., channels=None)` |
| `engine/vg/alerts/store.py` | `DEFAULT_RULES` (~93), `rules()` (~250), `update_rule` (~264) | five rules; `INSERT OR IGNORE` at init | add `("station", 1, 0, None, None, None)`; `rules()` already filters by `KINDS` |
| `engine/vg/alerts/catalogue.py` | `PAGES` (:42), `LABELS` (:51), `TEMPLATES` (:60), `NAME_LIMIT` | `intrusion.opened` template | add `station` to all three; template `station.absent` (en, ar draft) |
| `engine/vg/alerts/service.py` | `on_zone_open` (~233), `_record` (~376), `bind` (~107) | rule decides channels | `on_zone_open(..., zone_id=None)` looks the area up through a bound callable and passes `channels`; `on_station_absent`; `_record` uses `event.channels` when set |
| `engine/vg/auth/deps.py` | `ADMIN_WRITE_PREFIXES` (:97), `OPERATOR_WRITE_PREFIXES` (:128), `requires_admin` | `/zones` already admin-write | add `"/stations"`; add the acknowledge pattern to the operator allowance 022 builds (checked before admin-write) |
| `engine/vg/api/schemas.py` | `Zone` (~398), `ZoneUpdate` (~410), `Breach` (~414), `AttentionItem.kind` (~1256), `AlertKind` (~1321), delivery `kind` (~1439) | `Zone(id, name, camera_id, schedule, enabled, polygon, breaches_today)`; `ZoneUpdate(enabled)` | extend `Zone` additively; `ZoneUpdate` all-optional; new `ZoneCreate`, `WatchedHours`, `Station*`, `FaceReach`; add `"station"` to the three literals; `ZoneStatus`, `StationState` enums |
| `engine/vg/api/app.py` | `get_zones`/`patch_zone` (~2302-2314), `get_breaches` (~2317), `_start_zones` (~1188), call site (~423-434), `_zone_cameras` (~661), `ack_attention` (~3724), `app.state.zones*` (~321), shutdown (~599) | zones endpoints are list + toggle | add POST/PATCH(extended)/DELETE `/zones`, `/stations*`; `_start_stations(...)` after `_start_zones` taking `(face_pipeline, face_gallery)` and the same `detector`; `app.state.stations/_store/_error`; set `stations_store.on_alert`; call `AreaStore` import once before the workers start; stop the stations worker before `zones` at shutdown. Define `/stations/face-reach` **before** `/stations/{id}` |
| `engine/vg/api/live.py` | `zones` (~1066), `set_zone_enabled` (~1089), `intrusion_cameras` (~1114), `breaches` (~1130, `include_replaced=False` at ~1155), `_apply_features` (~882 and the tuple ~906), `_unwatch_everywhere` (~935), `_rated_workers` (~323), `attention` (~2558), `acknowledge` (~2651), `_breaches_state` (~3024), `ASSUMED_MS_PER_FRAME` (~3226), `_shared_pass_row` (~3439), `_vehicles_stage` (~3699), capabilities dict (~2945-2975) | zone = camera; fixture-free | rewrite `zones()` from `AreaStore` + worker results; `create_zone/update_zone/delete_zone` (each `_log` first, then the write, then `zones_worker.set_areas`); `breaches()` with `include_replaced=True` and a `zone_id` filter; stations methods; `_apply_features` row for `stations`; add the stations worker to the three tuples; attention items for zones (per-area in-app) and stations; `acknowledge` routes `station:`; `_stations_state`, `_stations_stage`, `("stations", "Work stations")` in `MockStore.CAPABILITIES` (`api/store.py:925`) |
| `engine/vg/api/store.py` | `MockStore.zones`, `MockStore.CAPABILITIES` (~925) | demo zones | demo stations for `VG_MOCK=1` only (rule 4: demo mode keeps its own); same new methods so the mock and live shapes match |

### Console (`*` = byte-shared with `mobile/src`: edit, copy, run `tools/check_parity.py`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/pages/Intrusion.tsx` | whole file (300 lines) | list of cameras with a toggle, a log with `Watch clip`, `CamGrid` | rewrite as the Zones page: four tiles, one card per zone (picture + polygon + chip + two numbers), detail with Today / last 7 days log, pause / resume, Draw a zone, inline delete question. Keep `useLinkedItem('scene')`, `LOG_REFRESH_MS`, the `<video>` player, `DataNotice capability` |
| `web/src/pages/Stations.tsx` | NEW | - | four tiles, cards, detail (status, times, timeline, event log, rules, Acknowledge alert, Edit station), "Removed stations" list (`includeDeleted`). `CameraFrame detections={false}`; never a name on a body |
| `web/src/components/AreaEditor.tsx` | NEW | - | the shared editor: `CameraFrame live detections={false} badge={null} onPicture={setRect}`, an absolutely placed click layer converting a click to fractions inside the picture rect, undo, clear, point count, the three checks (>= 3 points, no crossing, not almost a line), hours, Notify chips (pre-ticked from the Settings row), "email recipients are set in Settings". Zone fields: alert timing. Station fields: assignee select (from the directory) + face-reach warning, limit minutes |
| `web/src/components/AreaPicture.tsx` | NEW | - | read-only picture + SVG polygon (`viewBox="0 0 1 1"` inside the picture rect), colour by state |
| `web/src/components/CameraFrame.tsx` | `onPicture` prop, `zone` rect overlay (~637) | `onPicture(rect)` already exists; the zone overlay is a rectangle | no change needed; the polygon overlay lives in `AreaPicture` |
| `web/src/components/CameraSources.tsx` | `FEATURES` (~134), `recommendedRate` (~166) | seven rows; `fast` set on track, vehicles, weapons | 022 removes weapons and relabels intrusion; add `{ key: 'stations', label: 'source.feature.stations', cost: 'source.feature.stations.cost' }` (not `fast`) |
| `web/src/components/AlertSettings.tsx` | `settings.alerts.kind.<kind>` (~137, ~219) | rows come from the engine | nothing but the new keys: `settings.alerts.kind.station` and `.sub` |
| `web/src/app/useAttention.ts` | kind maps (~25, ~34, ~48) | `intrusion` to path, action key, query param | add `station`: path `stations`, action `attention.action.station`, param `station` |
| `web/src/app/useNavBadges.ts` (022) | - | 022 creates it | add two sources: zones with someone inside (`GET /zones`, count of `status === 'personInZone'`) and stations `absent` count; no number when the call fails or the count is 0 |
| `web/src/app/routes.tsx` | `AppRoutes` (L62) | `intrusion` route | add `stations` route (022 leaves a placeholder; replace it) |
| `web/src/app/navigation.ts`* and `web/src/types.ts`* | `ToolId` (types.ts ~398), `NAV` | no `stations` | add `'stations'` to `ToolId`, an entry to `NAV` in 022's order, an icon in `ICON`; `HOME_ORDER` as 022 left it |
| `web/src/services/api.ts`* `wire.ts`* `format.ts`* | `getZones` (~321), `setZoneEnabled` (~331), `getBreaches` (~335) | camelCase mapping; `format.ts` owns every rendered string | keep `getZones` fields the phone reads; add `ZoneCard` mapping, `createZone/updateZone/deleteZone`, `getStations`, `getStation`, `createStation/updateStation/deleteStation`, `acknowledgeStation`, `getFaceReach`; `format.ts`: `stationStateTone`, `zoneStatusTone`, `formatDurationShort`, `timelineSegments` |
| `web/src/i18n/{keys,en,ar.draft}.ts`* | flat dot-keys; `en` is a `Record` | `intrusion.*` keys exist | add `zones.*`, `stations.*`, `area.editor.*`, `source.feature.stations*`, `settings.alerts.kind.station*`, `attention.station`, `attention.action.station`, `nav.stations.*`; Arabic into `ar.draft` only |

## 2. Things to copy, not invent

- Polygon test: `features/people.py::point_in_polygon`, `feet_point` (tests in `engine/tests/test_zones.py` for the shapes to reuse).
- The scene state machine and its comments: `features/zones.py` (do not rewrite; re-key).
- A store on SQLite with `_lock` and ISO helpers: `events/zones.py`.
- Audit-first, soft write: `live.py::delete_vehicle_pass` (~1836), docstring "The audit entry is written first".
- Person crops for a face check: `features/recognition.py::person_crops`; gallery/pipeline hand-off: `app.py::_start_archive(cfg, people, face=(face_pipeline, gallery))`.
- A failed-start sentence per cause: `live.py::_breaches_state`; a stage: `_vehicles_stage`.
- Tests: `engine/tests/test_zones_live.py` (`FakeDetector`, `FakeRecorder`, `frame()`, `walk()`, `worker()`, `store_and_cameras`), `conftest.py::authed/sign_in/bare_live_store/live_ish_store`, `test_groups.py::store` (a store with real data; close the gallery before the tempdir).
- Console: `ui.tsx` (`Card`, `Badge tone=`, `Empty`, `LoadError`, `DataNotice`, `Field`, `Select`, `Toggle`, `Stats`), `useAsync(load, deps, initial, refreshMs)`, `useLinkedItem`, `TrackPerson.tsx` (click-on-picture with `onPicture`), `ToastProvider` (022).

## 3. Traps

- **Rule 2.** `StationsWorker` must hold no `person_id`, no body key, no embedding between frames. The face step returns a bool from a local variable. Do not call `RecognitionWorker`, `tracking`, `anchors` or `sightings` from it, and do not read `RecognitionWorker.faces_on` (stale results would carry a name forward and would need attendance on, rule 9).
- **Rule 3 / `CameraFrame` polls names.** `live` polls recognition boxes with names. Every picture on the Stations page and in the editor passes `detections={false}`. The Zones page keeps its nameless `intrusion` overlay (`_boxes` -> `_person_boxes`).
- **`_person_boxes` needs the people worker** (`people_worker.people_on`), which watches a camera only for `PERSON_FEATURES` (`counting`, `intrusion`, `track`). Zone cards get boxes because `intrusion` is a person feature; `stations` is deliberately **not** added, so station pictures draw no boxes.
- **Tests build `ZonesWorker(..., restricted={"cam-a"})`** in many files (`test_zones_live.py::worker`, `test_alerts_events.py`, `test_shared_pass.py`, `test_feature_assignment.py`). Update the one helper in each to build full-frame `Area`s from the ids; do not keep two ways to say "this camera is watched".
- **`restricted()` is read by `_shared_pass_row`** (`getattr(worker, "restricted")`) to know which cameras a worker really asks the pass on. Give `StationsWorker` the same method (cameras with at least one station) or the pass row over-charges every stations camera.
- **Alert timing and `_announced`.** Today `_announced` means "a scene opened in this run". With alert-after-N it must mean "an alert was raised in this run", else a 4-second visit that never alerted silences the next arrival for a minute (spec scenario 4 + P14-FR-417).
- **Home zone items today show every scene of the day**, including continuations (`attention()` ~2599). Keep that for a zone with `alert_after_seconds == 0`; for N > 0 show the entry only when `alerted = 1`.
- **`breaches()` stops hiding replaced entries.** Tests that pin `include_replaced=False` (`test_zones_live.py::TestBreachLog`) change by design. The replaced row has `clip=None`; the console must say "No clip kept", never show a dead button.
- **Deleting an area while someone is inside** closes its scene on the camera's own thread on the next frame (reason `switched_off`); do not close from the API thread (the comment on `set_restricted` is about a destroyed clip).
- **`import_key` must survive soft delete**, or deleting an imported zone brings it back at the next start.
- **Station clock.** Use `frame.captured_at`, never `time.monotonic()`; the `analyse` of a test chooses its own timestamps. Do not write to the database on every frame: segments change rarely and the heartbeat is rate-limited to 10 s.
- **Stored times are the first moment of the new situation** (left = last person seen; back = first moment of the run), not the moment it was confirmed (P14-FR-516).
- **No `await`/threads in `features/stations.py`.** `FeatureWorker` owns concurrency (AGENTS.md). `FacePipeline.observe` is already called from several threads (recognition, patrol, archive); do not add a lock around it.
- **Rate.** `rate_hz` is per camera, set through `_set_rate` / `_rated_workers`; add the stations worker to `_rated_workers` so editing a camera's rate reaches it.
- **Parity and CRLF.** `api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md` are CRLF: edit bytes, check `git diff --stat`. `navigation.ts`, `api.ts`, `wire.ts`, `format.ts`, `types.ts`, the i18n files are byte-shared: edit, copy to `mobile/src`, run `check_parity.py`, then `tsc -b --force` in **both** apps. The phone's `Intrusion.tsx` uses `getZones`/`setZoneEnabled`/`getBreaches`: keep their returned fields. `ToolId` gains a member; grep `mobile/src` for exhaustive switches on it (none found as `Record<ToolId, ...>` at planning time).
- **Python 3.10 on the Jetson**: no `match`, no `X | Y` in runtime `isinstance`, no `datetime.UTC`; keep `from __future__ import annotations`.
- **The SSH Jetson is a test bench.** Install nothing of VisionGuard on it; Jetson checks wait for the new board.
- **`web/node_modules` is absent in a worktree.** Junction the main checkout's and remove it with a non-recursive `[IO.Directory]::Delete`; use `npx.cmd`.
- **Weapons stay off.** 022 removes knife detection from the console; do not add anything to the weapons path here.

## 4. Baseline

- `python -m pytest engine`: **1940 passed, 14 skipped** at `5ea8e67` (not rerun for this plan). After 022 lands the count rises; use the count at 022's merge as the floor.
- New test files: `engine/tests/test_areas.py` (polygon rules, hours rule, import mapping, idempotent import, soft delete), `test_zones_areas.py` (feet vs body, two zones one camera, alert-after-N, pause/hours/delete closing scenes, clip sentence, full-frame equals old behaviour on `walk()` scripts), `test_stations.py` (machine table in research R4, gap handling, one alert per absence and per restart, assigned-person bool with a fake pipeline, no-name-survives pin, too-small-faces fallback, unknown reasons, segments sum, orphans, acknowledge audit-first and unchanged state, IT/admin permissions in `test_authorisation.py` style).
- Known flaky under load: `test_recording` forgotten-recording and `test_lost_bag` interest lapse. Rerun those alone first.
- The recorded-clip regression (SC-404, SC-502) is a manual `-Clip` run plus a scripted `walk()`; the 12 event and 9 negative marks are in `engine/data/footage/`.

## 5. Still unknown

- Exact names 022 gave its operator-pattern tuple, `LiveStore.hours()` return type, and `useNavBadges` shape: read 022's merged code, then adapt the three call sites named above.
- Whether any phone page needs the richer `Zone` fields (assumed no; the phone keeps its current Zones screen).
- Whether the person detector's boxes at the labelled desk give feet inside the polygon at all 12 marks (SC-404); the polygon for that test is drawn on the clip, not guessed. Tune `leave_confirm_seconds` / `return_confirm_seconds` there (SC-502).
- Whether 80 px is the right face floor for SFace on the footage (the spec says to confirm); it is read from `infer/faces.py::MIN_FACE_PIXELS` through `StationsConfig.min_face_px`.
- Night stations (open question 1 in plan.md) and the import rule for cameras never switched on (open question 3).
- Real per-worker milliseconds for `stations` on the Jetson: only the new board can say.
