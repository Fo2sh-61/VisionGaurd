# Implementation context: 027 cameras page and wall

**Written by `/speckit-plan` on 10 Nov 2026, against commit `5ea8e67` (branch `console-v2-plans`).**

Read this **before** opening any source file, then open only the named anchors. If this disagrees with the code, the code wins. Search for the symbol, not the line number. **Build on 022**: roles, `useAttention`, toasts, tokens (`--chrome`, `--frame`), RTL rules and the IT recording rule are 022's. Do 022's `deps.py` edits first; this spec adds to them.

---

## 1. Anchors

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/api/app.py` | `detections()` (~L2148) | `feature` regex = `S.OVERLAY_FEATURE_PATTERN`, default `None` = faces. Calls `recogniser.note_interest` for `None/attendance/track`, `tracking` for `track`, `weapons`, `vehicles`, `store.note_lost_interest` for `lost`. All through `getattr(request.app.state, ...)` | add `boost: bool = True` and wrap every `note_interest` in `if boost`. Make `feature` required and identity-free only (422 otherwise). Move the face branch to a new `faces()` handler with the same body, boost flag and `FACE_OVERLAYS` pattern |
| same | `camera_counts()` (~L2236), `list_cameras()` (~L2257) | `/cameras/counts`, `/cameras`; `list_cameras` → `store.live_cameras()` | add `GET /cameras/wall` (store method `camera_wall`) next to them. `getattr(store, "camera_wall", None)` like `live_counts` |
| same | `snapshot()` (~L2024) | `width` → `_tile_width`, `fps` → `worker.source.note_tile(fps)` | unchanged |
| same | `GET /attendance` (~L2418) | exact path only | add `GET /attendance/cameras` → `store.attendance_cameras()` |
| same | `start_recording` (~L2279) | `actor` query param default "unknown" | 022 takes the actor from the session; this spec adds nothing but the audit order (below) |
| `engine/vg/auth/deps.py` | `requires_admin` (~L112) | order: admin prefix → safe method returns False → operator allowance → admin-write | add `ADMIN_PATTERNS = (re.compile(r"^/cameras/[^/]+/faces$"),)` checked **before** the safe-method return. 022 adds its recording pattern in the operator allowance, a different spot |
| `engine/vg/api/schemas.py` | `OVERLAY_FEATURES` (~L280), `CameraView` (~L238) | one tuple, one regex | split into `IDENTITY_FREE_OVERLAYS` + `FACE_OVERLAYS`; keep `OVERLAY_FEATURES = both`; two patterns. Add `CameraWall`, `CameraWallEntry`, `WallReading`, `WallPlate`, `WallRing` as `Wire` |
| `engine/vg/api/live.py` | `camera_view` (~L368) | `boxes=self._boxes(id, feature) if online else []`, `feature=None` → `_face_boxes` | `boxes=self._boxes(...) if (online and feature) else []` |
| same | `live_cameras` (~L997), `camera_detections` (~L961), `live_counts` (~L987) | list of views; detections; `{camera: count\|None}` | add `camera_wall()` and `attendance_cameras()` beside `live_counts`. `attendance_cameras` = `{cid: len([f for f in recogniser.faces_on(cid) if f.identified])\|None}` |
| same | `_people_count` (~L665), `_zone_overlay`, `site()` (~L1004) | count from `people_worker.count_on`; `site()` uses `registry.online` and `len(registry.workers)` | `camera_wall` must use the same two figures so `up/total` equal `site()` |
| same | feature table (~L904-916) | `(feature, worker, wanted, error)` rows, e.g. `("counting", self.people_worker, "counting" in wanted, self.people_error)` | copy this idea for `_wall_readers`; use the same `*_error` strings |
| same | `vehicle_alerts` (~L1888) | loops `vehicle_store.passes(limit=200, since=...)`, skips `known` and `dismissed_alerts` | extract `_open_gate_passes()` (records, not wire) and use it in both. `VehiclePass.camera_id` exists on the record |
| same | `_source_view` (~L842), `_redacted` (~L5266) | `ip=config.redacted_source()`, `last_error` raw | route `ip` and `last_error` through `redact_source` |
| same | `start_recording` (~L4956) | `self._log(...)` is **after** `recorder.start` | move `_log` before the start (audit first); keep the failure paths as they are |
| `engine/vg/config.py` | `CameraConfig.redacted_source` (~L516) | `re.sub(r"://([^:/@]+):([^@]+)@", ...)` | new module function `redact_source(text)`; method calls it |
| `engine/vg/api/store.py` | `MockStore` | fixtures, `-Mock` only | `camera_wall()` built from its fixture cameras so `-Mock` works. Labelled as demo like the rest |
| `engine/vg/ingest/registry.py` | `STALE_AFTER_SECONDS = 10.0`, `CameraWorker.status` (~L110) | down when last frame older than 10 s | **read only**: do not change. Age = `now - source.health.last_frame_at` |

### Console (`*` = byte-shared with `mobile/src`: edit, copy, run `tools/check_parity.py`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/services/api.ts`* (CRLF) | `getCameraDetections` (~L88) | `GET /cameras/{id}/detections`, `feature?` | third `options?: {boost?: boolean}`; path `/faces` when feature is `attendance`, `track` or undefined, else `/detections`; send `boost=false` when asked. Add `getCameraWall()`, `getAttendanceCameras()` |
| `web/src/services/wire.ts`* | `CameraDetections` | wire types | add the `CameraWall*` types |
| `web/src/services/format.ts`* (CRLF) | `toCamera` (~L709), `boxColor`, `describeCount` | all strings built here | add `pictureState()`, `wallFeatureLabel`, `readingText`, `ringText`, `chipCounts`, `matchesSearch` |
| `web/src/services/frame.ts`* | `tileRefreshMs(onScreen)` | budget is the const `SCREEN_PICTURES_PER_SECOND = 120`, cap 15, floor 2 | add `budget` parameter; export `WALL_PICTURES_PER_SECOND`, `WALL_MAX_FPS`, `WALL_MIN_FPS = null` |
| `web/src/components/CameraFrame.tsx` (own copy in mobile, not byte-shared) | props, `wantLiveBoxes`, `getCameraDetections(...)` call (~L424), `polling` | `tileOverlay`, `detections`, `paused` exist | add `quiet?: boolean` (passes `boost:false`), `still?: boolean` (fetch one picture, no interval, no `fps` param), `pictureBudget?: number` (to `tileRefreshMs`). Mobile `CameraFrame` calls `getCameraDetections` too: it keeps compiling (options optional) |
| `web/src/app/useAttention.ts` | `Attention` interface, `useAttention` | `{items, acknowledge}`; failure leaves `[]` | add `status: 'loading'\|'ok'\|'unavailable'` |
| `web/src/app/useCameraBoard.ts` | NEW | — | `useAsync`-style poll of `getCameraWall` every 2 s, only while mounted; keeps last data and exposes `error`; ages tick locally between polls |
| `web/src/pages/Cameras.tsx` | NEW | — | header (`PageHeader`), size toggle, chips (`chip-btn`), search, `Full screen` button, grid of `CamTile`, pager. Copy `CamGrid.tsx` (search + pager exist) for the pager/search idea only |
| `web/src/components/CameraView.tsx` | NEW | `CameraModal.tsx` is the nearest (big frame, `RecordButton`, Escape) | page (`cameras/:id`) and wall layer in one component: `CameraFrame live`, Previous/Next, strip, address (admin: `getCameraSources`), `RecordButton` |
| `web/src/pages/CameraWall.tsx` | NEW | — | full-window dark page; no overlay; `useAttention`, `useCameraBoard`, key handler |
| `web/src/app/routes.tsx` | `AppRoutes` (~L62) | `/login` + the shell route | add `cameras`, `cameras/:id` inside the shell; `wall` outside `AppShell`, wrapped in `RequireSignIn`. 022's placeholder for Cameras is replaced |
| `web/src/app/navigation.ts`* | `NAV` (022's new order) | Cameras entry exists as a placeholder, not in the sidebar | switch it on at the end of 8 sections. No badge for Cameras (the design has none) |
| `web/src/components/RecordButton.tsx` | `note` prop; `account.name` passed as actor | works as is | pass 027's note and the processor-cost sentence |
| `web/src/i18n/{keys,en,ar.draft}.ts`* | flat dot-keys; `en` is a `Record` | — | only 027's strings |
| `web/src/styles/app.css` | — | — | wall/tile CSS in **logical properties only**, using 022's `--chrome`/`--frame`; ring styles `ring--amber`, `ring--red` plus a text label element |

## 2. Things to copy, not invent

- Boost pattern and test: `app.py::detections` comments; `engine/tests/test_api.py` ~L348-392 (pins `OVERLAY_FEATURES` against `_boxes`; update it for the split).
- Path rule tests: `engine/tests/test_authorisation.py`; `authed(app, role="it")` from `conftest.py`.
- A store with real data: copy the `store` fixture in `test_groups.py`; `live_ish_store` for cameras configured.
- Small all-cameras read: `/cameras/counts` + `LiveStore.live_counts` (the shape to copy for `/attendance/cameras`).
- Single-camera frame, Escape and record layout: `CameraModal.tsx`; record: `RecordButton.tsx`.
- Per-tile pacing: `CameraFrame.tsx` `tilesOnScreen` set and `tileRefreshMs`.
- Sub-system status/error pairs: the table at `live.py` ~L904-916.
- Audit-first: `live.py::delete_vehicle_pass` docstring.

## 3. Traps

- **`/detections` default meant faces.** Anything that called it with no feature (Enrol, the phone camera page, the old modal) is now a 422 on `/detections`. The shared `getCameraDetections` must pick `/faces` for `undefined`. Grep `mobile/src` for callers that pass no feature before copying `api.ts`.
- **IT and the phone**: a phone page that asks for faces as IT will now 403; `CameraFrame` swallows poll errors, so it just draws nothing. Fine, but check that no phone page shows an error for it.
- **`/cameras` list boxes**: `format.ts::toCamera` still maps `view.boxes`; harmless as `[]`. Do not "fix" it by drawing them.
- **Stale is not a wire value.** Do not add a `stale` to `signal`: `CameraView.stale` already means "serving a last frame of a dropped stream" and would collide.
- **`last_frame_at` moves only on decoded frames** (`source.py` ~L557), so an unwatched camera set to a low analytics rate has older pictures. That is why `pictureEverySeconds` is sent.
- **`paused` never loads a picture** (`asking` only set while `polling`). A No signal tile needs `still`, not `paused`, or it shows a grey box instead of its last picture.
- **Tile fps lies**: `fps` on the snapshot URL comes from `refreshMs`. Pass the wall budget through `tileRefreshMs` or the wall will send `fps=7` and the camera converts at that rate.
- **`useAttention` is polled by 022's sidebar too.** Do not mount a second polling copy on the wall if 022 lifts it into a context; check 022's final shape first.
- **Keys**: Escape inside the single view must `stopPropagation` or the wall exits as well. In RTL the arrow keys mirror.
- **Switched-off cameras** are in `registry.disabled`, not `workers`. `camera_view` already handles both; `camera_wall` must too, and they must not count in `up` or `total`.
- **`sessionStorage` can throw** (private window); wrap every read and write.
- **CRLF**: `api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`. Edit bytes. `git diff --stat` after each file. `live.py` and `app.py` are under `api/`.
- **Redaction is the only secret guard for `/sources`.** Write the test table first: `rtsp://u:p@h/x`, `rtsp://tok@h/x`, `rtsp://h/x?password=p`, `rtsp://h/x?a=1&Token=t`, `http://u:p@h/?key=k`, a path-embedded `/user=u&password=p` (Chinese NVR style, check what `engine.yaml` uses).
- **Worktree**: no `web/node_modules`; junction the main one and remove it with `[IO.Directory]::Delete` (memory note).

## 4. Baseline

- `python -m pytest engine`: **1940 passed, 14 skipped** at `5ea8e67` (not rerun for this plan).
- New test file: `engine/tests/test_camera_wall.py`: wall never carries a name (walk the model fields); wall `up/total` equals `site()`; switched-off not in `up`/`total`; readings say why (people worker None, vehicles store None, camera down) and never 0; ring amber on an open unknown pass and clears on dismiss, red on a running scene and clears on end; `boost=false` leaves every `_boost_until` unchanged over 20 calls; default still boosts; `/faces` 403 for IT and 200 for admin; `/detections` 422 for faces and none; `/cameras` boxes empty; `/attendance/cameras` 403 for IT; IT `POST`/`DELETE` recording 200; `redact_source` table; recording audit before start.
- Update `test_api.py` for the split overlay list. Known flaky under load: `test_recording` forgotten-recording, `test_lost_bag` interest lapse. Rerun alone first.

## 5. Still unknown

- **FR-625 floor** (the one `[NEEDS CLARIFICATION]`): kept open as `WALL_MIN_FPS = null`; the owner decides after the soak test. Either answer fits: `null` never shrinks the page, a number auto-selects a smaller grid when budget/tiles falls under it.
- Provisional numbers: wall budget 16 pictures per second, cap 4 per second per tile, Stale floor 3 s. All measured on the new Jetson.
- Whether a ring from an unknown plate should lapse by time rather than wait for dismissal. Planned: it follows the open alert, so wall and Home agree.
- How 025 will expose "person in zone now" and station state. 027 reads `scenes` (running) today; 025 registers a reader.
- What `engine.yaml` uses for camera addresses (path-style credentials), for the redaction table.
- Whether any phone page shows an error text when a poll fails (IT on a face overlay).

## 6. For 022 (shared files, no conflict in intent; order matters)

- `engine/vg/auth/deps.py`: 022 edits `ADMIN_PREFIXES`, `ADMIN_WRITE_PREFIXES`, the operator allowance. 027 adds `ADMIN_PATTERNS` in the same function. Apply 022 first, then this.
- `web/src/app/navigation.ts`, `routes.tsx`, `useAttention.ts` (new `status`), `api.ts`, `wire.ts`, `format.ts`, `i18n/*`, `tokens.css`, `app.css`: both specs edit; 027 only adds.
- **Gap in 022's scope**: `/track` and `/tracking/*` still return names to IT (`TrackResult`, `LiveTracking`, `FollowView`). Track leaves the nav in 022, so adding `"/track"` and `"/tracking"` to `ADMIN_PREFIXES` is a one-line closure that fits 022's path rule. Recommended; not done here.
- 022's sidebar card should use the new `useAttention().status` so it does not read "calm" when the alerts could not be read.
