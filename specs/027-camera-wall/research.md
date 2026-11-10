# Research: 027 cameras page and wall

Checked against the code at commit `5ea8e67`. Paths are in `engine/vg/` unless they start with `web/`.

## R1 — Why sixteen tiles raise sixteen cameras

- **Finding**: `api/app.py::detections()` calls `note_interest(camera_id)` for the recogniser (feature none, `attendance`, `track`), tracking (`track`), weapons, vehicles (`vehicles`) and the lost-bag watch (`lost`). Each call sets `_boost_until` for `BOOST_TTL_SECONDS` (`features/base.py::note_interest`). `CameraFrame` polls it for every tile with `tileOverlay`, every 0.2 to 1.5 s (`tileBoxRefreshMs`).
- **Decision**: add `boost: bool = True` to the overlay reads. `False` skips every `note_interest`. Existing pages (Car plates, Knife, Lost) keep the default, so they behave as today. Grid tiles on the new Cameras page send `boost=false`. The wall sends nothing, because wall tiles draw no overlay (FR-618).
- **Single camera** keeps the default (`boost=true`): the spec allows it, as today.
- **Not the same thing**: `snapshot?fps=` calls `CameraSource.note_tile` (picture conversion rate, not analysis). That is picture demand and is bounded by R4.
- **Rejected**: removing the boost for tiles everywhere. The Car plates page relies on it so a plate held up to a gate tile is read (comment in `detections()`).

## R2 — Names reach IT today (FR-627)

Three open reads carry a name, all readable by IT because nothing is admin-only except `/enrolment`, `/sources`, `/users`, and writes under `/cameras`, `/zones`, `/vehicles`, `/settings` (`auth/deps.py`; 022 widens this):

1. `GET /cameras/{id}/detections` with no `feature`, `attendance` or `track` → `_face_boxes` / `_tracked_boxes` (`live.py`), whose `Box.label` is the person's name.
2. `GET /cameras` → `list_cameras` → `live_cameras()` → `camera_view(cid)` whose default `feature=None` fills `boxes` with `_face_boxes`. The console never draws these (`CameraFrame` uses only its own poll: `const boxes = liveBoxes ?? []`), but IT can read them.
3. `/track` and `/tracking/*` (`TrackedIdentity`, `FollowView`, `TrackResult.cameras` built with `camera_view(c)` at `live.py` L4160, L4423). Out of this spec's scope; see "For 022" in context.md.

- **Decision**: a query string is not a path, and AGENTS.md says permissions are decided by path. So the name-carrying overlay gets its own path, `GET /cameras/{id}/faces`, and one anchored admin pattern in `deps.py` next to 022's recording pattern. `/detections` then accepts only identity-free features and answers 422 for the rest. `camera_view` fills `boxes` only when a feature is named, so the `/cameras` list is `[]` for boxes.
- **Alternatives rejected**: passing the query string into `requires_admin` (works, but a missing `feature` would have to count as "faces", which is the default-open shape that caused this); filtering by role inside the handler (the forbidden pattern).
- **Knock-on**: callers of the old shape are `getCameraDetections` (web and mobile, one function in the shared `api.ts`) and `CameraFrame` (both apps). One function picks the path from the feature. A phone page asking for faces as IT gets 403, and `CameraFrame` already swallows poll errors (`.catch(() => {})`).
- **`people_count`** on `CameraDetections` and `CameraView` is a body count from the person detector, not identity-based. IT keeps it. Attendance recognised-now count is identity-based, so it is served only from `/attendance/cameras`.

## R3 — The one new read, and why not extend `/cameras`

`CameraProvider` polls `/cameras` every 5 s (`ROSTER_REFRESH_MS`). That is too slow for SC-003 (10 s) and it carries `snapshotUrl`, `streamUrl` and boxes the grid does not need. A new small read is cheaper and says only what a tile needs:

- **Decision**: `GET /cameras/wall`, polled every 2 s only while the Cameras page or the wall is mounted (`useCameraBoard`). Worst case a drop shows 10 s + 2 s after the last picture. SC-003 says "within 10 seconds"; the plan reports 10 s plus one poll honestly.
- **Same numbers as System Health**: entries come from `registry.workers` (up/down) and `registry.disabled` (off), the same sources as `site()` (`cameras_online`, `cameras_total`, enabled only). A test asserts the wall's up/total equals `site()` (SC-007).
- **Picture age** comes from `worker.source.health.last_frame_at`, the value `CameraWorker.status` already compares to `STALE_AFTER_SECONDS` (10 s, `ingest/registry.py`). Stale is derived on the console (spec: "a new state worked out from the picture's age").
- **Low-rate cameras**: `last_frame_at` moves only when a frame is decoded (`source.py` ~L557), at least at the camera's analytics rate (`CameraConfig.fps`, 5 by default, set per camera). A camera set to 0.5 per second would look stale at 3 s. So the entry carries `pictureEverySeconds = 1 / fps` and the console uses `max(3 s, 2 × that)`. Without it Stale would lie on slow cameras.

## R4 — Picture demand on the Jetson (FR-622 to 625)

- **Today**: `CameraFrame` asks for pictures only when on screen and the page is visible (`useOnScreen`, `usePageVisible`), shares `SCREEN_PICTURES_PER_SECOND = 120` across tiles (`services/frame.ts::tileRefreshMs`, capped 15 and floored 2 fps), and requests width in multiples of 160 (`snapshot` rounds to `TILE_WIDTHS`). The engine caches one JPEG per frame and size (`CameraWorker.snapshot_jpeg`).
- **The problem on a wall**: 16 tiles × 7.5 pictures per second = 120 JPEG conversions per second on a CPU that also runs detection and has no hardware encoder.
- **Decision**: `tileRefreshMs(onScreen, budget = SCREEN_PICTURES_PER_SECOND)`; the wall passes `WALL_PICTURES_PER_SECOND` (start at 16, so about 1 picture per second per tile at 4×4, capped at 4 per second at 2×2) and a tile at the reduced rate says "Slower picture on the wall". Numbers are provisional; the Jetson soak sets them.
- **FR-625 read literally** (lower the rate when the box is short): needs a load figure the console can trust. System Health has CPU via psutil but a feedback loop is new machinery. Not planned. The wall is always in the cheap mode and says so. Flagged.
- **Pages**: only the current page's tiles are mounted, so pictures for other pages are never fetched (FR-623). 208 cameras is 13 pages of 16.
- **Recording** (FR-626): `RecordButton` already starts nothing until pressed. The processor-cost sentence is new text only.

## R5 — Readings for each feature

| Feature (chip) | Source today | When it cannot answer |
|---|---|---|
| Population (`counting`) | `LiveStore._people_count(camera, online)` → `people_worker.count_on` | `people_worker is None` → `subsystem_off` + `people_error`; camera down → `camera_down`; `None` from the worker → `not_measured` (never 0) |
| Car plates (`vehicles`) | newest `vehicle_store.passes(since=start_of_day)` row per `camera_id` (the row has `camera_id`, status, plate_display, at) | `vehicle_store is None` → `subsystem_off` + `vehicles_error`; none today → `none_today` (a fact, not zero) |
| Restricted zones (`intrusion`) | `scenes.recent()` row for the camera with `running` | `zones_worker is None` → `subsystem_off` + `zones_error` |
| Work stations | arrives with 025: a reader registered in `_wall_readers` | until then the feature cannot be on a camera, so no tile asks |
| Attendance (`attendance`) | identity-based, so **admin path only**: `GET /attendance/cameras` → faces identified right now (`recogniser.faces_on`) | IT tile reads "Administrators only" |

Weapons, lost-items and track are not chips (022 removed knives; the others have their own pages). A camera that runs only those shows its picture and "No analysis shown here".

**Readers are a table** (`LiveStore._wall_readers: dict[str, Callable]`) so 024 and 025 add one line each and the response type does not change.

## R6 — Rings (FR-619)

- **Amber, unknown plate**: an open `unknown` gate pass for that camera (the same filter `vehicle_alerts()` applies: today, status not `known`, not dismissed). Extract that filter into `_open_gate_passes()` so Home and the wall cannot disagree. The ring clears when the alert is dismissed or the day rolls (alerts are today only).
- **Red, person in restricted zone**: a running scene on that camera (`events/zones.py::Scene.running`); clears when the scene ends.
- **Amber and red for stations**: 025. The ring has a closed set of causes, `unknown_plate | zone_breach | station_away | station_absent`, so 025 only fills two more.
- A ring is **text first**: the console writes "Unknown plate" or "Person in zone" on the tile, colour second (FR-621).

## R7 — Alerts waiting (FR-628)

022 already defines the sidebar card as `useAttention().items.length`. The wall top bar uses the same hook, so the number is the same list by construction.

**Gap found**: `useAttention()` returns only `{ items, acknowledge }` (`web/src/app/useAttention.ts`). `items` starts as `[]` and a failed poll leaves it `[]`, so today "0 alerts" and "could not read alerts" look identical. That would make the wall claim "0 waiting" when it does not know (FR-628, rule 4). Decision: add one additive field `status: 'loading' | 'ok' | 'unavailable'` to the hook's result (set in its existing `.catch`). Existing callers ignore it. The wall shows a dash and "unavailable" unless `status === 'ok'`. 022's sidebar card should use it too; see "For 022" in context.md.

## R8 — Stream address with no secrets (FR-613)

- **Finding**: `CameraConfig.redacted_source()` and `live._redacted()` are the same regex, `://user:pass@` only. A password in a query (`?password=`, `?token=`) or a token as the only userinfo (`rtsp://token@host`) passes through unmasked. `last_error` (`f"{type(exc).__name__}: {exc}"`, `source.py` ~L526) can contain the address too, and `/sources` returns it.
- **Decision**: one function `redact_source()` in `config.py`: mask userinfo whatever its shape, and mask the value of any query key matching `pass|pwd|token|key|secret|auth|sig` (case-insensitive). Both existing call sites and `_source_view`'s `last_error` use it. Test with a table of shapes.
- **Who sees it**: `/sources` is already admin-only. The single view fetches it only when `useAccount().role === 'admin'`. IT never makes the call. No new endpoint.

## R9 — Wall route and keyboard

- `/wall` sits beside `/login` under `RequireSignIn`, outside `AppShell`, so there is no sidebar or top bar to hide. It takes the filter from the URL (`?f=&q=&n=&p=`), so Exit returns to the same grid.
- Escape exits; if the single view is open on top, Escape closes it first (it stops propagation).
- Arrows: in Arabic the pager and arrow keys mirror, so the key matches the arrow drawn on screen. Pages wrap nowhere; at the first page the previous arrow is disabled. When the filter shrinks, the page clamps to the last page that exists (FR edge case).
- **Ring and state text** on a dark ground use `--chrome` and `--frame` from 022.

## R10 — IT recording (FR-614)

The path rule and the actor from the session user are 022's (P14-FR-115). 027 adds only the single-view Record button for IT, plus a test that IT `POST` and `DELETE` on `/cameras/{id}/recording` pass. One gap that is 027's: `start_recording` writes its audit entry **after** the recorder starts (`live.py::start_recording`), against the audit-first rule. A one-line reorder when the actor change is made (see context.md traps).
