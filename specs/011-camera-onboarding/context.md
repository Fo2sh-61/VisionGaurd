# Implementation context: Camera Onboarding

**Written by `/speckit-plan` on 2026-09-01, against commit `faab0fd`.**

Read this **before** opening any source file. Then open the named anchors only — not the files
around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code, the code wins and this
> file is wrong. Anchors drift — search for the symbol, do not trust the line number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `api/live.py` | `class LiveStore(MockStore)` | subclasses `MockStore`. **`connect_dvr` is not overridden**, so the live engine answers from the fixture. Constructor already holds every worker: `people_worker`, `recogniser`, `patrol`, `tracking`, `zones_worker`, `weapons_worker`, `lost_watch`, `vehicles_worker`, plus `registry`, `cameras` (the `CameraStore`), `clock`, and one `*_error: str \| None` per subsystem | add `connect_dvr`, `edit_camera`, `bulk_add`, `_apply_features`, `_unwatch_everywhere` |
| `api/live.py` | `LiveStore.test_connection` | **copy this, do not write a second prober.** Folds `username`/`password` into the source when `"://" in source and "@" not in source`; builds `CameraSource("probe", source, target_fps=1)`; `probe.open()` → False means report `probe.health.status` + `probe.health.last_error`; `probe.read()` → `None or frame.is_stale` means "connected, but no frame arrived"; measures with `time.monotonic()`; `finally: probe.close()` | the channel probe is this in a bounded pool |
| `api/live.py` | `LiveStore.add_camera` | folds credentials into `source`, `camera_id = req.id or _slug(req.name)`, calls `self.cameras.add(...)` with **eight** arguments, then `self.registry.add(config)`, then reads `self.registry.worker(config.id)` for an honest initial status (`down`, not `ok`, until the first frame) | pass the six new fields; audit first; call `_apply_features`; return `featureNotes` + `shadowsConfig` |
| `api/live.py` | `LiveStore.remove_camera` | `self.registry.remove(id)` then `self.cameras.remove(id)`, returns `stopped or recorded` | audit first; call `_unwatch_everywhere` |
| `api/live.py` | `LiveStore.scan` | `return []` | return a `ScanResult` with `available: false` and a reason |
| `api/live.py` | `LiveStore.sources` | loops `self.registry.workers` then `self.registry.disabled`; hardcodes `channels=1`; uses `worker.source.redacted` and `cam.redacted_source()` | add `features`, `faces`, `enabled`, `gate`, `direction`, `fps`, `rotate`, `fromConfig` |
| `api/store.py` | `MockStore.connect_dvr` | **the fixture**: `count = 16`, `status=OK`, `resolution="704x576"`, names `f"{req.name or req.host} - Cam {i}"` | keep it as a fixture but move it to the new `DvrChannel` shape |
| `api/store.py` | `MockStore.scan` | three invented devices at `192.168.1.60/63/80` | move to `ScanResult` |
| `api/store.py` | `MockStore._log` | `S.AuditEntry(id=f"a{len(self._audit)+1}", at=now(), actor, action, subject, detail)`, appended to an in-RAM list. **Audit is still RAM-only — that is P3, not this feature** | call it before every `/sources` write |
| `api/store.py` | `class Store(Protocol)` | declares `sources`, `areas`, `scan`, `connect_dvr`, `test_connection` | add `edit_camera`, `bulk_add`; change `scan`'s return type |
| `api/app.py` | `add_source` / `remove_source` (`@app.post("/sources")`) | uses `getattr(store, "add_camera", None)` and raises `503 "camera management needs the live engine"` when absent; `ValueError` → `422`. **Takes no `user`, writes no audit** | add `user: auth_deps.AdminUser`; new `PATCH /sources/{id}` and `POST /sources/bulk` beside them |
| `api/app.py` | `_start_weapons` | `watched = [c.id for c in roster if c.enabled]` — **every enabled camera**. Returns `(worker, scenes, error_sentence)`; the error sentences are the exact strings the page shows | `[c.id for c in roster if c.enabled and "weapons" in c.features]`, and a new sentence for "no camera is set to check for knives" |
| `api/app.py` | `_start_zones` | `watched = [c.id for c in roster if c.enabled]` — same | `"intrusion" in c.features`, same treatment |
| `api/app.py` | `_start_lost` | gates only on `[c.id for c in roster if c.enabled]` being non-empty; `BagWatch` gets **no camera list at all** | pass the `lostitems` cameras |
| `api/app.py` | `_start_people` | `BODY_FEATURES = {"counting","intrusion","track"}` at module scope; `cameras = [c.id for c in roster if c.enabled and BODY_FEATURES.intersection(c.features)]` | unchanged — this one is already right, and is the model for the others |
| `api/app.py` | `_start_recognition` | `if c.enabled and (c.faces or "attendance" in c.features)` | unchanged |
| `api/app.py` | lifespan, the `if cfg is not None and os.getenv("VG_MOCK") != "1":` block | builds `CameraStore(database)` → `merge_cameras(cfg.cameras, cameras.all())` → `CameraRegistry(roster)` → `registry.start()` → `wait_for_first_frame(timeout=8.0)`; stores `app.state.registry`, `app.state.cameras` | nothing, unless the startup log line for knife/zone camera counts goes here |
| `api/schemas.py` | `CameraSource`, `AddCameraRequest`, `DvrConnectRequest`, `DvrChannel`, `DvrConnectResult`, `FoundDevice`, `TestConnectionRequest/Result` | all subclass `Wire`; `SourceStatus = ok\|down\|auth`; `SourceType = NVR\|DVR\|IP camera\|RTSP` | extend per `contracts/sources-api.md`; add `ScanResult`, `EditCameraRequest/Result`, `FeatureNote`, `BulkAddRequest`, `AddCameraOutcome` |
| `features/base.py` | `FeatureWorker.__init__` | `self.cameras = list(cameras)`; `self._threads: list[Thread]`; **one** `self._stop = threading.Event()` for the whole worker; `self._subs: dict[str, object]`; `self._results`, `self._boost_until`; `self._lock` | `_threads` → `dict[str, Thread]`; add `self._drop: dict[str, Event]` |
| `features/base.py` | `FeatureWorker.start` | `if self._threads or not self.cameras: return` — returns early and logs "no cameras assigned" | must stay correct once `cameras` can be empty at start and filled later |
| `features/base.py` | `FeatureWorker._run` | subscribes `maxsize=1`, registers in `_subs`, loops `while not self._stop.is_set()`, `subscription.get(timeout=0.5)`, rate-gates on `_interval_for`, `finally:` pops `_subs` and `bus.unsubscribe` | check the per-camera drop event too; call `self._closing(camera_id)` in the `finally`, **before** unsubscribing |
| `features/base.py` | `FeatureWorker.serves` / `stats` | both read `self.cameras` **without the lock** — safe only because it never mutates | take the lock |
| `features/zones.py` | `ZonesWorker.set_restricted` | one assignment and nothing else. **Read its docstring in full before writing `unwatch`** — it is the record of the exact race this feature must not repeat | add a `_closing` override that closes `self._live[camera_id]` with a reason |
| `features/zones.py` | `ZonesWorker.analyse` | returns `ZonesResult(restricted=False)` **before any detection** when the camera is not restricted, and closes an open scene with reason `"switched_off"` on the camera's own thread | the `_closing` override reuses `self._close(camera_id, at, reason)` |
| `features/weapons.py` | `WeaponsWorker.analyse` | `people = self.people.detect(frame)` on **every** frame, then the knife model only where a person was found; per-camera state in `_last_frame_at`, `_seen`, `_live` | `_closing` override to close an open scene and end its video |
| `features/lostbag.py` | `class BagWatch` | **not a `FeatureWorker`.** One thread, `_interest: dict[str, datetime]`, `_boxes`, `_seen`; driven entirely by the overlay poll | add a `cameras: set[str]` and refuse interest outside it |
| `features/tracking.py` | `TrackingWorker.__init__` | per-camera state is `_seen: dict[str, ...]`, created lazily. Has its own `_follow_lock`, deliberately **not** the base's | `_closing` should drop `_seen[camera_id]`, and must not disturb a running follow |
| `features/vehicles.py` | `VehiclesWorker.__init__` | per-camera state in `_tracks`, `_recent`, `_attempts`, `_read_ms` — all `dict`, all lazy via `setdefault` | `_closing` drops all four |
| `ingest/store.py` | `SCHEMA` | `CREATE TABLE IF NOT EXISTS camera (...)` with **eleven** columns; separate `camera_restricted` table | add the six columns via `PRAGMA table_info` + `ALTER TABLE` |
| `ingest/store.py` | `CameraStore.add` | takes eight arguments, builds `CameraConfig.parse({...}, f"camera {id!r}")`, then inserts. Re-adding a soft-deleted id revives it | take the six new fields |
| `ingest/store.py` | `CameraStore.all` | reads rows into `CameraConfig` | read the six new columns |
| `ingest/store.py` | `merge_cameras` | `merged = {c.id: c for c in configured}; merged.update({c.id: c for c in stored})` — **stored wins, deliberately**, with the reason in the docstring | unchanged. This is what makes editing a YAML camera work, and `fromConfig` is just "no stored row" |
| `ingest/registry.py` | `CameraRegistry.add` | calls `self.remove(config.id)` first so two threads never hold one device; honours `config.enabled` by putting it in `self.disabled`; starts the worker only `if self._started` | unchanged — already correct for runtime add |
| `ingest/registry.py` | `CameraRegistry.remove` | pops from `workers` (and stops it) and from `disabled` | unchanged |
| `config.py` | `class CameraConfig` | fourteen fields; `faces`, `neighbours`, `gate`, `direction`, `face_gate`, `live_capture` all present and all validated. `is_gate` property requires gate + direction + `"vehicles" in features`; `parse` refuses both half-states and refuses `direction: both` | add a `FEATURES` frozenset and make `parse` refuse an unknown feature name |
| `config.py` | `PERSON_FEATURES` | `frozenset({"counting","intrusion","track"})` at module scope | the new `FEATURES` set sits beside it |
| `auth/deps.py` | `ADMIN_PREFIXES` | `("/enrolment", "/sources", "/users")` | **unchanged.** `/sources` is already there, so every new route under it is admin-only the day it is written. Do not add a decorator |
| `web/services/api.ts` | `connectDvr` | `return { channels: result.channels.length }` — **throws the channel list away** | return the channels |
| `web/services/api.ts` | `scanNetwork` | maps a bare `W.FoundDevice[]` | return the `ScanResult` |
| `web/components/CameraSources.tsx` | `addFound` | pushes `{id: \`found-${ip}\`, status:'ok'}` into local state, **calls nothing** | call the bulk endpoint |
| `web/components/CameraSources.tsx` | `addDvr` | pushes `{id: \`dvr-${n}\`, name: \`DVR — 192.168.1.${50+n}\`, status:'ok'}`, **calls nothing, invents the address** | call the bulk endpoint with the ticked channels |
| `web/components/CameraSources.tsx` | `startDvrConnect` | on success rebuilds `Array.from({length: result.channels}, …)` as `CH 1…N` / `Camera 1…N` | render the channels the engine returned |
| `web/components/CameraSources.tsx` | `dvrChannels` initial state | eight invented rows before any recorder is contacted | `[]` |
| `web/components/CameraSources.tsx` | the `source.captureService` block | a ✓ badge and `192.168.1.10` — **a device that does not exist** | delete, with its i18n keys |
| `web/components/CameraSources.tsx` | `FEATURES` | three entries: counting, intrusion, attendance | seven, each with its cost line and its settings |
| `web/components/CameraSources.tsx` | the `dvrStep === 'channels'` rows | name input uses `defaultValue`; area `<select>` has **no `value` and no `onChange`** | controlled |
| `web/i18n/keys.ts` | `'source.*'` union | ~50 keys already | add the new ones; delete `source.captureService`, `source.captureServiceLead` |

---

## 2. Things to copy, not invent

- **Probing a stream** → copy `api/live.py::LiveStore.test_connection`. Whole function. It already
  handles credential folding, `open()` failure, the stale-frame case, latency, and `finally: close()`.
- **Redacting a source** → `CameraConfig.redacted_source()` and `CameraSource.redacted`. Both exist.
  Never build a redaction inline.
- **Adding a SQLite column** → copy `events/vehicles.py`, the `for table, column, ddl in (...)` loop
  with `PRAGMA table_info` then `ALTER TABLE … ADD COLUMN`. `auth/store.py` has the same six lines.
  Do not add a migration framework.
- **"No camera is set up for X" honesty** → copy the sentence shape in `api/app.py::_start_vehicles`:
  `"No camera is set up as a gate, so no plates are being read. A gate camera needs a gate number
  and a direction."` A state, a consequence, and what to do.
- **Guarding against an un-overridden store method** → copy the assertion in `test_ask.py`:
  `assert LiveStore.ask is MockStore.ask` (there it asserts sameness deliberately; here assert the
  opposite for `connect_dvr`). This is the cheapest possible test for the bug that caused this
  whole feature.
- **Changing what a running worker watches** → copy `ZonesWorker.set_restricted`: assign, return,
  and let the camera's own thread act on it next frame.
- **A test store with real data** → copy the `store` fixture in `test_groups.py`. Throwaway
  `FaceGallery` + `SightingStore` in a `TemporaryDirectory`, `LiveStore(config=vgconfig.load(),
  registry=...)`. **Close the gallery before the tempdir** or Windows fails the teardown.
- **A wire type** → subclass `Wire`. snake_case in, camelCase out, `extra="forbid"`.
- **datetime → wire** → `_instant(when, clock)` in `api/live.py`. Never build an `Instant` by hand;
  the offset is per-instant, not per-startup.

---

## 3. Traps

- **Closing a scene from the request thread destroys a recording.** This already happened once and
  the docstring on `ZonesWorker.set_restricted` is the record of it: closing a scene on the API
  thread while the camera's own thread was mid-`analyse` made that thread open a *second* scene,
  whose clip then replaced the first one's. So `unwatch` must set a flag and return. The `_closing`
  hook runs **on the camera's own thread**, in `_run`'s `finally`. Never anywhere else.
- **`FeatureWorker._stop` is one Event for the whole worker.** It cannot express "stop this one
  camera". A per-camera Event is required; `stop()` still sets the global one.
- **`self.cameras` is read without the lock** in `serves()` and `stats`. Safe today only because it
  never mutates. The moment `watch`/`unwatch` exist, both reads need the lock — and `stats` already
  takes it for other fields, so it is one line.
- **The identity tier is a move between two workers, not a toggle.** `recogniser` serves
  `faces or "attendance" in features`; `patrol` serves the complement. Changing `faces` means
  `watch` on the new tier **before** `unwatch` on the old, or there is an instant where neither is
  looking at that camera.
- **Patrol is off by default.** `tracking.patrol_hz: 0` in `engine.yaml`, and it is off on
  measurement, not preference. So `self.patrol` is usually `None` and `_apply_features` must
  tolerate that — as it must for every worker that failed to start.
- **A features-only edit must not reopen the stream.** `CameraRegistry.add` calls `remove` first,
  which stops the capture thread and drops the device. Doing that to add a tickbox is a visible
  stutter for nothing. Touch the registry only when `source`, `fps`, `rotate` or `enabled` changed.
- **`registry.add` honours `enabled`** by routing the config into `self.disabled` and returning
  `None`. Code that does `worker = registry.add(config); worker.status` will crash on a disabled
  camera. `add_camera` already guards this with `if worker else SourceStatus.DOWN`.
- **`WeaponsWorker` costs the shared person detector on every frame it processes.** That is why
  gating it on the feature list matters at 208 cameras, and it is why `ZonesWorker` — which returns
  before any detection when a camera is not restricted — is the cheaper of the two to leave wrong.
- **`cam-laptop` does not list `weapons`.** So gating knives on the feature list stops knife
  detection on the only enabled camera in this repository. That is the config file already saying
  what it wants, but it is still a behaviour change that needs a `STATUS.md` line and a System
  Health sentence. Do not ship it quietly.
- **Mixed line endings, no `.gitattributes`.** `api/*.py`, `services/*.ts`, `types.ts` and
  `STATUS.md` are **CRLF**; most other files are LF. Editing with a script that reads and writes
  text rewrites every ending and turns a six-line change into a whole-file diff. Read/write bytes,
  or check `b"\r\n" in path.read_bytes()` first. `git diff --stat` catches it.

  **This was documented here and still happened.** Four files went CRLF→LF during
  implementation — `engine.yaml`, `test_lost_bag.py`, `api/live.py` and `CameraSources.tsx` —
  and the diff read 7,962 insertions instead of the real 2,347. The specific mistake:
  `pathlib.Path.write_text(..., newline="\n")` **forces** LF on a file that was CRLF, and the
  Write tool does the same to a whole file it replaces. Neither is caught by tests, tsc or
  pyflakes — only by `git diff --stat` looking implausible. Check it after every scripted edit,
  not at the end. Repair is
  `b = p.read_bytes(); assert b"\r\n" not in b; p.write_bytes(b.replace(b"\n", b"\r\n"))`.
- **`CameraFrame` with `live` also polls recognition boxes, which carry names.** Any camera preview
  added to the setup screen must pass `detections={false}`.
- **`tsc --noEmit` is a silent no-op** here — project references. Use `npx tsc -b --force`.
- **Run pytest from the repo root.** `python -m pytest engine`. Three tests in `test_track_page.py`
  read files by relative path and fail from inside `engine/`.
- **Audit is still in RAM** (`MockStore._audit`, a list). Auditing these writes is correct and
  required; making the audit durable is P3 and not this feature. Do not let one become the other.

---

## 4. Baseline

- `python -m pytest engine` at commit `faab0fd` → **green, exit code 0**, run 1 Sep 2026.
  **1,420 tests collected** (`--collect-only -q`, summed per file). Raw output in
  `specs/011-camera-onboarding/evidence/pytest-baseline.txt`. The count must not drop.
- **Do not try to read the pass/skip split off a captured run.** OpenCV writes
  `[ERROR:…] open VIDEOIO/FFMPEG: Failed to initialize VideoWriter` to stderr **mid-progress**, so
  with `2>&1` it lands inside pytest's progress line and corrupts it — and on this machine the
  final `N passed, M skipped` summary line did not survive the capture at all. Counting the
  progress dots off such a file undercounts badly (it gave 1,226 against 1,420 collected). Redirect
  stderr away (`2>/dev/null`) when you want the summary line, and treat exit code 0 as the green
  signal.
- `STATUS.md` records 1,246 passed / 6 skipped as of 27 Aug 2026. That is **before** the Ask work
  landed and is not the current number — read the evidence file, not `STATUS.md`.
- New test files this feature adds:
  - `engine/tests/test_sources.py` — probe honesty, scan honesty, bulk outcomes, edit, audit
    ordering, credential redaction, admin-only.
  - `engine/tests/test_feature_assignment.py` — `watch`/`unwatch`, cross-feature and cross-camera
    isolation, the `_closing` race, the identity-tier move.
  - `engine/tests/test_ingest.py` — extended for the six columns, `update()`, and the migration
    being a no-op on an existing database.
- Nothing is failing before this feature starts.
- One pre-existing noise line in the output, unrelated: `open VIDEOIO/FFMPEG: Failed to initialize
  VideoWriter`, from a recorder test on a machine with no writable codec. It does not fail anything.

---

## 5. Still unknown

Check these in code; do not assume.

- ~~Does `SharedDetection` cache grow per frame?~~ **Checked — it does not.** `infer/shared.py`
  holds `self._cache: dict[str, _Cached]` and `self._compute_locks: dict[str, Lock]`, both keyed by
  **camera id**, one entry each. So unwatching leaks one small entry per camera, not one per frame.
  Worth dropping in `_closing` for tidiness; not a correctness problem, and not a reason to delay.
- **Does `TrackerPool.for_camera` allocate lazily, and is there a way to release one?** A ByteTrack
  instance per camera is not free, and unwatching `track` should return it.
- **Can `RecognitionWorker` take `watch()` unchanged?** It is a `FeatureWorker` and keys state per
  camera, but it also calls into `tracking.note_face` — check whether anything in it is built from
  the camera list at construction rather than looked up per frame.
- **What does `CameraSource.open()` do on a URL whose host does not resolve?** The probe budget
  depends on it honouring `CAP_PROP_OPEN_TIMEOUT_MSEC` (set to 5000 in `source.py`). If DNS
  resolution blocks past that, 32 channels against a bad hostname will overrun the budget and the
  "not checked" path becomes the normal path rather than the edge case.
- ~~How `dev.ps1 -Clip` switches cameras.~~ **Checked — it sets `VG_CAMERAS=cam-clip`**, an env
  filter on the roster, not a YAML edit. `cam-clip`'s features are
  `[attendance, counting, intrusion, track]` — no `weapons`, no `vehicles`, no `lostitems`. So
  under `-Clip`, once knives are gated on the feature list, **zero cameras check for knives**, and
  "no camera is set to check for knives" is exactly what the test and the screen should say.

  Two further facts, checked in `config.py::_apply_camera_override`, that the tests must not trip
  over: it runs **inside `config.load()`**, so it filters `cfg.cameras` only — a camera added
  through the console lives in the `CameraStore` and is merged in *afterwards*, so **it still runs
  under `-Clip`**. And it works by `replace(c, enabled=c.id in wanted)` rather than by dropping
  cameras, so the others stay in the roster as disabled and appear in `registry.disabled`. An
  unknown id in `VG_CAMERAS` is a hard `ConfigError`, deliberately.
