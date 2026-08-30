# Implementation context: Track a person

**Written by `/speckit-plan` on 2026-08-21, against the tree at 602 passed / 6 skipped.**

Read this **before** opening any source file. Then open the named anchors
only. Verify before trusting: anchors drift — search for the symbol, not the
line number. If this file disagrees with the code, the code wins.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/config.py` | `class CameraConfig` | frozen-ish dataclass: `id, name, source, kind, area, fps, enabled, features: tuple, rotate`; `parse()` validates rotate/fps | add `faces: bool = False`, `neighbours: tuple[str, ...] = ()`; new `ArchiveConfig` parsed from an `archive:` yaml section; patrol/gate knobs under `tracking:` |
| `engine/vg/features/recognition.py` | `RecognitionWorker.analyse` | per face: `pipeline.observe(frame.image)` → `gallery.match` → build `RecognisedFace` → `self._record(...)` (debounced sighting) → `self._name_the_body(...)` | feed every match into an `AnchorAccumulator`; call `note_face` only when the accumulator says sustained (D3); pass anchor rows to `AnchorStore` |
| `engine/vg/features/recognition.py` | `_name_the_body` | fires on **every single-frame match**; wraps `tracking.note_face(camera_id, face_box, person_id, score, at)` in try/except-debug | gate behind the accumulator verdict — this is the whole of the name-rule change |
| `engine/vg/events/anchors.py` | NEW | — | `AnchorStore` + `AnchorAccumulator`. Copy `SightingStore`'s idioms exactly: `db.connect`, `SCHEMA` executescript, `threading.RLock`, `_parse` for ISO, `local_date` via `clock_for` |
| `engine/vg/features/tracking.py` | `TrackingWorker.analyse` | per frame: `detector.raw_boxes(frame)` → `pool.for_camera(id).update(...)` → `appearance.observe(...)` → `store.record_many`. Worker also has `note_face` (binds name via `appearance.bind_face` + `store.name_identity` backfill) and `correct()` | advance a `FollowSession` here: hop detection (session.stable_id's camera changed), timer expiry, track-loss (id absent > `LOST_TRACK_SECONDS`), recorder start/stop per hop. No new threads |
| `engine/vg/ingest/archive.py` | NEW | — | `ArchiveSource` seam (`dvr` = ffmpeg subprocess, `footage` = slice local files), bounded 2-thread job runner, 30 s chunk pipeline (fetch → detect/track → burn box → mp4), prefetch queue. The only new concurrency in the feature — keep it all in this one file |
| `engine/vg/api/schemas.py` | `class TrackQuery` (region ~line 561) | `TrackQuery/TrackStop/TrackResult` exist; `SearchJob` exists (~534); `Clip` exists (~251); `Recording` wire exists; `TrackedIdentity/LiveTracking` exist (~980) | add `PathAnchor, PathSkeleton, FollowView, TrailHop, FollowRecording, LegJob, SweepJob, SweepEstimate`; `CameraView` gains `faces: bool = False`. All `Wire` subclasses: snake_case in, camelCase out, `Fraction`/`Confidence` clamp-or-500 |
| `engine/vg/api/app.py` | `get_breach_clip` (~1089) | the clip idiom to copy: `store.clip_for_breach(id)` → `(path, reason)`; `raise HTTPException(404, reason)`; `FileResponse(path, media_type="video/mp4")`; same-origin note for `<video src>` | leg chunks serve identically. New endpoints per contracts/api.md; follow endpoints read `request.app.state`-held workers like `/tracking/live` does; `_stamp` helper (added by 002) exists for Instants outside the store |
| `engine/vg/api/live.py` | `def track` (~1330) | audit-first idiom: `entry = self._log(actor, "track.search", who, detail)` **before** returning; `audit_id=entry.id` in result; `_resolve_person(query)`; `_camera_name` / `_area_of` helpers | copy for `path.skeleton`, `path.leg`, `path.sweep`, `track.follow`, `track.record.*`. Skeleton reads `AnchorStore`; estimates read `measured_rates`; keep `/track` serving unchanged until the page stops calling it |
| `engine/vg/api/store.py` | `class Store(Protocol)` | every new store method needs a protocol line AND a `MockStore` implementation (demo stays a working demo); `SubsystemUnavailable` → 503 | add skeleton/leg/sweep/follow methods; MockStore fakes a plausible follow + canned skeleton |
| `engine/vg/auth/deps.py` | `ADMIN_WRITE_PREFIXES` | `("/cameras", "/people", "/zones")` | **no change** — `/path` and `/tracking` stay operator-open; pin with a test instead |
| `engine/engine.yaml` | `cameras:` | `cam-laptop` (webcam, `[attendance, counting, intrusion, track]`), `cam-clip` (file, disabled, flipped by `-Clip`), `cam-rtsp-1` (disabled) | add `faces: true` to cam-laptop, `archive:` section with `backend: footage`, patrol + gate knobs |
| `engine/tools/measure_track.py` | NEW | — | times a 2-min `footage` fetch (× real-time) and detect+track+encode fps; writes `measured_rates` row |
| `web/src/pages/TrackPerson.tsx` | `export function TrackPerson` | 1025 lines, REBUILD. Current shape worth keeping: `getLiveTracking()` 1 s poll pattern, `seenNow` memo, auto-follow of `seenNow.cameraId`, `Legend`, `Step` components. Subject picking (`chooseByName` with `#p1` fake ids) and `neighboursOf` are fixture-era — replace | two modes; live = area grid (CamGrid) → enlarge → click → `POST /tracking/follow`, then poll `GET /tracking/follow`; past = skeleton → leg player advancing chunk urls |
| `web/src/components/CamGrid.tsx` | default export | exists; used by cameras page; overrides tile refresh by grid size | partition by `camera.area`, page, search box (camera + area names) |
| `web/src/services/api.ts` / `wire.ts` / `types.ts` | `trackPerson`, `getLiveTracking` | exist; `wire.ts` has `LiveTracking/TrackedIdentity` | add follow/skeleton/leg/sweep calls + mirrors; `format.ts` builds all sentences |

## 2. Things to copy, not invent

- **Store + accumulator**: `events/sightings.py::SightingStore` (schema,
  lock, `_parse`, `local_date`) and `events/sightings.py::record` (debounce —
  understand it to see why anchors can't be derived from it).
- **Audit-first**: `api/live.py::track` and `_empty_track` — `_log(...)`
  before return, `audit_id` in the payload.
- **Clip serving**: `api/app.py::get_breach_clip` — `(path, reason)` tuple,
  404-with-reason, `FileResponse`, same-origin comment.
- **On-demand boost**: `features/base.py::note_interest` — follow and
  enlarged views renew it per poll.
- **503 idiom**: `api/app.py::_enrolment` — absent subsystem carries its
  reason; `SubsystemUnavailable` in stores.
- **Recording control**: `ingest/recorder.py::Recorder.start/stop` — raises
  `AlreadyRecording`; `Recording` has `state/reason/path`; there is a
  `max_seconds` cap already.
- **Job wire shape**: `schemas.py::SearchJob` — the lost-items search is
  already job-shaped; reuse, don't redesign.
- **Tests**: `tests/test_people_page.py` — FakePipeline/FakeRegistry
  patterns, tempdir + close-gallery-before-tempdir teardown;
  `conftest.py::authed/sign_in`.

## 3. Traps

- **Debounce blindness** (the big one): `SightingStore.record` thins repeats
  to one row per 60 s per (person, camera). Any "sustained over seconds"
  logic MUST run in the worker on live frames — stored rows cannot prove it.
- **`note_face` today names a body from ONE frame.** The name-rule change is
  gating this call, not adding machinery. Backfill (`name_identity`) then
  stays correct because it only ever fires after the gate.
- **Stable-id lifetime is the name's lifetime.** `LOST_TRACK_SECONDS = 6.0`;
  `TRACK_BUFFER` is deliberately scaled ×30 because ByteTrack quotes
  `track_buffer` against an implied 30 fps — do not "fix" that constant.
- **One `FacePipeline` is already shared across per-camera threads** inside a
  worker — a second worker instance sharing it adds no new concurrency class.
- **`Recorder` is one recording per camera** — hop logic must stop the old
  camera before starting the new one or the new start raises
  `AlreadyRecording`.
- **`FeatureWorker.start()` spawns one thread per camera** — putting `track`
  on 208 cameras means 208 threads at idle rate; fine at current scale,
  noted for scale-up, not this feature's problem.
- **TrackPerson.tsx has a local-time parsing trap** it already solved
  (`nowMinutes` vs `nowLabel` comment) — keep that pattern in the rebuilt
  window validation.
- **`<video>`/`<img>` cannot send Authorization headers** — chunk URLs must
  stay same-origin (dev proxy), exactly like breach clips and streams.
- **Mixed line endings** — `api/*.py`, `services/*.ts`, `types.ts` are CRLF;
  most others LF. See AGENTS.md; `git diff --stat` catches a flip.
- **MockStore must implement every new protocol method** or demo mode breaks
  the page — the fixture store is the working demo, not dead weight.

## 4. Baseline

- `python -m pytest engine` → **602 passed, 6 skipped** (~75 s)
- New test file this feature adds: `engine/tests/test_track_page.py`
- Nothing failing before the feature starts
- STATUS.md line to rewrite when done: "Track a person — Engine real, page
  part fake — badge bug, clip save writes nothing"

## 5. Still unknown — check in code, don't assume

- Real DVR playback URL dialect and export speed — `measure_track.py`
  answers it; until then the `footage` backend is the truth.
- Whether burn-in encode speed on the dev laptop sustains 30 s chunks — the
  same tool answers; drop to 15 s chunks if not.
- `AppearanceStore.path_for` collapse behaviour at window edges (gap_seconds
  = 60) — read `_collapse` before wiring the blue layer into the skeleton.
- How `CamGrid` picks tile refresh (`tileRefreshMs`) — read it before adding
  paging so page size and refresh scale together.
- Whether `pool.for_camera` creates trackers lazily for cameras added at
  runtime — matters for follow-on-any-camera; check `infer/tracking.py`.
