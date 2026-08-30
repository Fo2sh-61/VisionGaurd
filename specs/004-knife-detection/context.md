# Implementation context: Knife detection

**Written by `/speckit-plan` on 2026-08-22, against commit `4e5d4e6`** (the
working tree carries 26 uncommitted paths — web page tweaks,
`web/src/services/frame.ts`, and the deleted `models/knife detection/`
folder — none of them in this feature's files).

Read this **before** opening any source file. Then open the named anchors
only — not the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code,
> the code wins and this file is wrong. Anchors drift — search for the symbol,
> do not trust the line number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/infer/weapons.py` | `class WeaponDetector` | an onnxruntime decoder: `__init__(weights, device="auto", imgsz=640, conf=0.35, iou=0.45)` imports `onnxruntime` (not installed here); `DEFAULT_WEIGHTS` names the deleted `models/knife detection/knife-finetuned-v3.onnx`; `_letterbox`, hand-rolled NMS; `DetectedWeapon(x, y, w, h, confidence, label)` frozen dataclass with `.area`; `CLASS_NAMES = ("knife",)`; `detect(image, min_confidence=None)` returns most-confident first | **rewrite** as a copy of `infer/persons.py::PersonDetector`: `YOLO(str(weights))`, `_resolve_device`, `half` only off CPU, `_warm_up`, `predict(..., verbose=False)` → fractions; keep `DetectedWeapon`, `CLASS_NAMES`, the `detect()` signature, `.version = weights.stem`, `.device`; add `self._lock = threading.Lock()` held around predict; `DEFAULT_WEIGHTS = REPO_DIR / "models" / "knifebest.pt"`; copy `export_tensorrt` |
| `engine/vg/infer/persons.py` | `PersonDetector.raw_boxes` / `people_from` | `self.model.predict(image, device=, imgsz=, conf=, iou=, half=, classes=[0], verbose=False)`; `people_from(boxes, width, height)` reads `box.xyxy[0].tolist()` and `box.conf[0]`, clamps with max/min, sorts by area | copy; drop `classes=` (one-class model); sort by confidence |
| `engine/vg/infer/shared.py` | `SharedDetection.detect(frame, min_area=0.0)` | `list[DetectedPerson]` in fractions from one pass cached on `(camera_id, frame.sequence)`; `.device/.version/.weights` passthrough | the person gate — the worker calls it first, every frame |
| `engine/vg/features/zones.py` | `class ZonesWorker` | `__init__(bus, detector, cameras, scenes, recorder=None, restricted=None, rate_hz=2.0, boost_hz=12.0)`; `analyse(frame)` drives `self._live: dict[camera_id, SceneState]`; `_open/_close/close_all/stop/_start_recording/_stop_recording/scene_on`; `GAP_SECONDS = 1.0`, `MAX_SCENE_SECONDS = 120.0`, `ACTOR`, `BUSY_REASON`; `ZonesResult` frozen dataclass; `stop()` = `super().stop()` then `close_all("shutdown")` | copy to **new** `features/weapons.py` as `WeaponsWorker(bus, people, knives, cameras, scenes, recorder=None, rate_hz=2.0, boost_hz=12.0)`; drop `_restricted`; add `_candidates: dict[camera_id, Candidate(first_at, last_at, hits)]`; `GAP_SECONDS = 10.0`, `CONFIRM_HITS = 3`, `CONFIRM_SECONDS = 1.0`, `CANDIDATE_GAP_SECONDS = 2.0`; `SceneState.peak: float`; `WeaponsResult(checked, people, knives: tuple[DetectedWeapon, ...], scene_id)`; `knives_on(camera_id)` reads `self.payload(camera_id)` |
| `engine/vg/features/base.py` | `FeatureWorker` | `__init__(name, bus, cameras, rate_hz, boost_hz)`; `start()` one daemon thread per camera; an exception in `analyse` is logged per frame; `result()/payload()` drop anything older than `RESULT_TTL_SECONDS = 3.0`; `note_interest(camera_id)` boosts for 2 s; `stats` gives `last_inference_ms` | nothing — inherit |
| `engine/vg/events/zones.py` | `class SceneStore`, `SCHEMA` | `db.connect`, `executescript(SCHEMA)`, `threading.RLock`, helpers `_iso/_parse/_days_ago/_unlink/_to_scene`; `attach_clip` marks that camera's rows beyond three `replaced` then unlinks; `close_orphans` rewrites `recording` → `failed` with a sentence; `recent(since_days, camera_id=None, include_replaced=True)` | copy to **new** `events/weapons.py` as `WeaponSceneStore`; table `weapon_scene` (data-model §1); delete the superseded block in `attach_clip` and call `self.expire(...)` instead; `recent(since, until=None, camera_id=None)`; add `review()`, `expire()`, `note_confidence()` |
| `engine/vg/ingest/recorder.py` | `Recorder.start` / `Recorder.stop` | `start(camera_id, actor)` raises `AlreadyRecording`, returns `Recording(state="recording")`; `stop(camera_id, actor)` joins up to 10 s, returns `Recording` with `state in {saved, failed}`, `path`, `reason`; `Recorder(bus, directory, clock=0, max_seconds=600)` | no change — one instance per feature |
| `engine/vg/api/app.py` | `def _start_zones(cfg, registry, roster, detector, cameras_store)` | `watched = [c.id for c in roster if c.enabled]`; `detector is None` → returns the page's sentence; `SceneStore(database)` + `close_orphans()`; `rate = min(fps)`; own `Recorder(registry.bus, cfg.storage.zone_clips_dir, clock=cfg.timezone)`; `worker.start()`; returns `(worker, scenes, None)`; `except` → `_reraise_if_strict(exc, ...)`, `_reason(exc)` | copy as `_start_weapons(cfg, registry, roster, detector)`: `spec = cfg.models.get("weapons")` → `WeaponDetector(weights=spec.weights, device=spec.device, imgsz=spec.imgsz, conf=spec.conf, iou=spec.iou, half=spec.half)`; `WeaponSceneStore(_database(cfg))`, `close_orphans()`, `expire(now − clip_retention_days)`; recorder into `cfg.storage.weapon_clips_dir` |
| `engine/vg/api/app.py` | `lifespan` — the `_start_zones(` call and `store = LiveStore(` | `app.state.zones, app.state.scenes, app.state.zones_error = _start_zones(cfg, registry, roster, getattr(people, "detector", None), cameras)`; `LiveStore(cfg, registry, gallery, sightings, recogniser, cameras, people, tracking=, anchors=, archive=, counts=, recorder=, users=, scenes=, zones=)`; afterwards `store.zones_error = app.state.zones_error`; the `app.state.*_error: str \| None = None` defaults sit together above the `if cfg is not None` block | add `app.state.weapons / weapon_scenes / weapons_error` defaults; call `_start_weapons(cfg, registry, roster, getattr(people, "detector", None))` right after zones; pass `weapons=`, `weapon_scenes=`; set `store.weapons_error` |
| `engine/vg/api/app.py` | shutdown — `for worker in (` tuple after `recorder.stop_all()` | order: zones, people, recogniser, patrol, tracking; the `recorder` stopped before it is the manual one only | put `getattr(app.state, "weapons", None)` first — its `stop()` closes scenes and stops its own recorder |
| `engine/vg/api/app.py` | `WINDOW_DAYS` / `def window_days(label)` | dict label → days, five labels; unknown → 422 naming `sorted(WINDOW_DAYS)` | add `WEAPON_WINDOWS` tuple + `weapon_window(label, clock, term_from) -> (since, until)`; leave `WINDOW_DAYS` for the other endpoints |
| `engine/vg/api/app.py` | `get_weapons` / `review_weapon` / `get_weapon_cameras` (the `# ---- weapons` block) | `window: str = "Last 30 days"` → `store.weapons(window_days(window))`; review `store.review_weapon(detection_id, review)` → 404 on `None`; **no endpoint in app.py takes a user dependency today** — `actor` travels as a query string on record/track | `since, until = weapon_window(window, clock, term_from)` with `clock = getattr(store, "clock", None) or clock_for(TZ_OFFSET_MINUTES)` and `term_from = getattr(getattr(store, "config", None), "hours", None)`; `review_weapon(detection_id, review, store, user: auth_deps.CurrentUser)` → `store.review_weapon(detection_id, review, reviewer=user.name)`; add `get_weapon_clip` copied from `get_breach_clip` |
| `engine/vg/api/app.py` | `camera_detections` endpoint | `feature` Query pattern already allows `weapons`; boosts `recogniser` always and `tracking` when `feature == "track"` | add the same two lines for `feature == "weapons"` → `app.state.weapons.note_interest(camera_id)` |
| `engine/vg/api/live.py` | `LiveStore.__init__` | kwargs end `... users=None, scenes=None, zones=None`; stores `self.scenes`, `self.zones_worker`; `self.people_worker` — **not** `self.people`, which shadows the directory method; error attrs `recognition_error/people_error/tracking_error` initialised `None`; `zones_error` is set from outside | add `weapons=None, weapon_scenes=None` → `self.weapons_worker`, `self.weapon_scenes`, `self.weapons_error = None` |
| `engine/vg/api/live.py` | `_boxes(camera_id, feature)` | `track` → `_tracked_boxes`; `counting`/`intrusion` → `_person_boxes`; **everything else — weapons included — falls to `_face_boxes`** | insert `if feature == "weapons": return self._knife_boxes(camera_id)` above the default; `_knife_boxes` → `S.Box(x, y, w, h, label="Knife", confidence=, kind="weapon", severity=S.Severity.CRITICAL)` from `self.weapons_worker.knives_on(camera_id)` |
| `engine/vg/api/live.py` | `breaches(since_days)`, `clip_for_breach(scene_id)`, `_scene_clip`, `_no_clip_reason` | entry builder: `names = {c.id: c.name for c in self.registry.configs()}`, `_instant(scene.started_at, self.clock)`, `clip=self._scene_clip(scene)`; clip: `(path, reason)` tuple, `path.resolve().relative_to(root.resolve())`, `is_file()` check, root `self.config.storage.zone_clips_dir` | copy as `weapons(since, until)`, `clip_for_weapon(detection_id)` with root `weapon_clips_dir`, `_weapon_clip(scene)` url `/weapons/{id}/clip`, `_no_weapon_clip_reason` with the `expired` sentence |
| `engine/vg/api/live.py` | the stubs `weapons` / `weapon_cameras` / `review_weapon` under "this list IS the to-do list" | return `[]`, `[]`, `None` | delete; real overrides. `review_weapon(detection_id, review, reviewer=None)`: `self._log(reviewer, f"weapon.{review.verdict.value}", detection_id, review.reason)` **then** `self.weapon_scenes.review(...)`; `weapon_cameras()` = `camera_view(c.id, feature="weapons")` for roster cameras the worker `serves()` |
| `engine/vg/api/live.py` | `capabilities()` → `states["weapons"]`; `_breaches_state()` | a hard-coded `(UNAVAILABLE, "Weapon detection is not built yet…")`; `_breaches_state` is the three-sentence pattern over `zones_worker / zones_error / people_worker / scenes` | `"weapons": self._weapons_state()` copied from `_breaches_state` with the D10 sentences |
| `engine/vg/api/live.py` | `health()` pipeline list | a hard-coded `PipelineStage(key="weapons", detail="Model present but not wired… demo data", healthy=False)` | `self._weapons_stage()` modelled on `_people_stage()`: `worker.stats["last_inference_ms"]`, `knives.version`, `knives.device`, `len(worker.cameras)` |
| `engine/vg/api/live.py` | `_start_of_today()` | local midnight via `self.clock.local(now).replace(hour=0, …).astimezone(utc)` | reuse for Today/Yesterday bounds |
| `engine/vg/api/store.py` | `class Store(Protocol)` weapons lines; `MockStore.weapons / review_weapon / weapon_cameras`; `_log` | `weapons(self, since_days: int)`; `review_weapon(self, detection_id, review)`; `_log(actor, action, subject, detail) -> AuditEntry` appends to `self._audit` | widen per data-model §3; add `clip_for_weapon`; `MockStore.weapons(since, until)` filters `w.at.utc` against both bounds |
| `engine/vg/api/schemas.py` | `class WeaponDetection`, `class WeaponReview` | fields per data-model §2; `WeaponReview.actor: str` **required**; `Wire` is `extra="forbid"` | five optional fields; `actor: str \| None = None` |
| `engine/vg/config.py` | `StorageConfig.zone_clips_dir` property | `return self.clips_dir / "zones"` with a docstring on why a subfolder, not a key | add `weapon_clips_dir` → `self.clips_dir / "weapons"` |
| `engine/vg/config.py` | `class HoursConfig` | `term_from: str = ""` — a string, possibly empty | read by `weapon_window` for "This school year" |
| `engine/engine.yaml` | `models: weapons:` | `weights: models/yolov8m-worldv2-school.pt`, `imgsz: 960`, `conf: 0.25`, comment calls it zero-shot | per data-model §4; `cam-rtsp-1` `features: [intrusion, counting, weapons]` → drop `weapons` |
| `engine/tests/test_no_fixtures.py` | `test_nothing_unavailable_still_returns_rows` | `"weapons": lambda: store.weapons(30)` | `store.weapons(None, None)` |
| `engine/tests/test_zones_live.py` | module doubles; `live_store()` | `FakeDetector(people)` records `asked`; `FakeRecorder(directory, fails=, already=)` writes a stub file; `frame(camera_id, at=, sequence=)`; `worker()` builds a `ZonesWorker` over `NoBus`; `walk(worker, detector, [(seconds, people)])`; `live_store(tmp_path, camera_store, scene_store)` over an unstarted `CameraRegistry(roster)` | copy into **new** `test_weapons_live.py`; add `FakeKnives(hits)` recording `asked`; walk script `(seconds, people, knives)` |
| `engine/tools/benchmark.py` | the `argparse` block | times `models.person` on the labelled clip; `TARGET_CAMERAS = 208`, `RATES = (1, 2, 5)` | `--model` (default `person`) so `--model weapons` times the knife model the same way |
| `web/src/pages/Weapons.tsx` | `export function Weapons` | 330 lines of fixture flow: `WINDOWS` (3 labels), `useState<WeaponState>`, `'live' / 'confirmed' / 'dismissed'` cards, `RecordButton`, `WEAPON_STEPS`, a `detections.map` with a dead "Watch clip" button, `CamGrid title="Highest-risk cameras"` | **rebuild** from `Intrusion.tsx` (research D9); keep `useCapability('weapons')`, `DataNotice`, `useAsync(load, deps, initial, 3_000)`; `CamGrid feature="weapons"` |
| `web/src/pages/Intrusion.tsx` | `export function Intrusion` | `LOG_REFRESH_MS = 3_000`; `playing` holds the whole entry, not its id; `<video key={id} src controls autoPlay>`; `stillListed` note; `counted = !loading && !error`; `clipUrl ? <button className="linkbtn"> : <span>{clipReason}</span>` | copy |
| `web/src/services/api.ts` | `weaponStatus()`, `getWeaponDetections`, `reviewWeapon`, `getWeaponCameras` | `weaponStatus` returns **"Confirmed — police notified"**; list maps `{id, time, location, item, status, tone}` only; `reviewWeapon(id, verdict, actor, reason?)` posts `{verdict, actor, reason}` | map the new fields (`clipUrl: assetUrl(d.clip?.url)`, `clipReason`, `duration: formatDuration(d.seconds)`, `camera`, `area`, `confidence`, `verdict`, `reviewer`, `reviewedAt`, `running: !d.endedAt`, `cut: d.endReason === 'limit'`); status sentences per D9; `reviewWeapon(id, verdict, reason?)` posts `{verdict, reason}` |
| `web/src/services/wire.ts` | `interface WeaponDetection` | camelCase mirror of the Python wire | add `endedAt?`, `seconds?`, `clipState?`, `clipReason?`, `endReason?` |
| `web/src/types.ts` | `WeaponWindow`, `WeaponDetection`, `WeaponState`, `WeaponStep` | 3-label union; 6-field UI type; two fixture-only types | 7-label union; UI type per D9; delete `WeaponState`, `WeaponStep` |
| `web/src/services/content.ts` | `WEAPON_STEPS` | fixture copy ("The clip and the frame are saved immediately") | delete |
| `web/src/components/CamGrid.tsx` | `CamGrid({ … feature })` | `feature?: CameraFeature` is handed to `CameraFrame`, which polls `getCameraDetections(id, feature)` **only in the enlarged view** | pass `feature="weapons"` |

## 2. Things to copy, not invent

- Model runner → `infer/persons.py::PersonDetector` (`__init__`, `_warm_up`,
  `raw_boxes`, `people_from`, `export_tensorrt`, `_resolve_device`).
- Scene machine → `features/zones.py::ZonesWorker.analyse`, `_open`, `_close`.
- Scene store → `events/zones.py::SceneStore` (`SCHEMA`, `attach_clip`'s
  mark-then-unlink order, `close_orphans`, `_to_scene`).
- Worker wiring and honest failure → `api/app.py::_start_zones`,
  `_reraise_if_strict`, `_reason`.
- Entry builder and clip serving → `api/live.py::breaches`, `clip_for_breach`,
  `_scene_clip`; the endpoint → `api/app.py::get_breach_clip`.
- Three-sentence capability → `api/live.py::_breaches_state`; health stage →
  `_people_stage`.
- Audit-first → `api/live.py::track` (`entry = self._log(...)` before the work).
- Local midnight → `api/live.py::_start_of_today`.
- Signed-in user → `vg/auth/deps.py::CurrentUser` (`User.id/email/name/role`,
  `.is_admin`).
- Tests → `tests/test_zones_live.py` doubles, `TestSceneMachine`,
  `TestStorage`, `live_store()`; `tests/conftest.py::authed`, `sign_in`,
  `bare_live_store`.
- Page → `pages/Intrusion.tsx`.

## 3. Traps

- `_boxes` serves **faces** for `feature="weapons"` today. The knife branch
  goes above the default, or the page shows names (rule 1).
- `api.ts::weaponStatus` says "police notified". Nobody is notified. Delete
  it; do not rephrase it.
- `WeaponReview.actor` is required on the wire and `Wire` forbids unknown
  fields: make it optional *before* the console stops sending it, or every
  review 422s.
- `Store.weapons(since_days)` is called directly by `test_no_fixtures.py`; the
  signature change breaks that line first.
- `LiveStore.__init__`: never assign `self.people` (it shadows the directory
  method and `/people` 500s) — and `self.weapons` would shadow `weapons()` the
  same way. Use `self.weapons_worker`.
- The knife model has no `SharedDetection`: one `WeaponDetector` is called
  from every camera thread. The lock lives in `detect()`.
- `SharedDetection.detect(frame)` caches per exact `frame.sequence`; the knife
  worker's call is a cache hit only when counting/zones already processed
  that sequence — otherwise it pays the person pass itself.
- `Recorder.stop` joins up to 10 s on the camera thread — same as zones,
  acceptable; never call it under a lock.
- `attach_clip` in zones deletes superseded files. Copy it and *remove* that
  block: knife videos have no per-camera cap.
- `close_orphans` must keep the `recording → failed` rewrite, or a crash
  leaves a row promising a video.
- `_start_people` returns `None` when no enabled camera has a body feature;
  the knife worker then cannot start — return the D10 sentence, do not
  crash. `VG_STRICT=1` makes any exception fatal in CI
  (`test_smoke_start.py` runs with `VG_MOCK=1`, so it never reaches this
  path).
- CI has no weights: `_start_weapons` must turn `FileNotFoundError` into the
  capability reason, and the detector test must `pytest.skip` without
  `models/knifebest.pt`.
- `Confidence` and `Fraction` are validated 0..1 — clamp `peak_confidence`
  and box fractions before building wire objects, or the endpoint 500s.
- `term_from` is a string (`"2025-09-01"` or `""`), not a date.
- Line endings. CRLF: `api/app.py`, `api/live.py`, `api/schemas.py`,
  `api/store.py`, `config.py`, `events/zones.py`, `engine.yaml`,
  `test_zones_live.py`, `services/api.ts`, `services/wire.ts`,
  `services/format.ts`, `services/content.ts`, `types.ts`, `STATUS.md`,
  `docs/PLAN.md`. LF: `features/zones.py`, `infer/*.py`,
  `test_no_fixtures.py`, `pages/*.tsx`, `AGENTS.md`. New files match their
  neighbour; `git diff --stat` catches a flip.
- `models/*.pt` is gitignored; `MODELS.md` and the `<name>_pt.yaml` sidecars
  are tracked — regenerate with `python engine/tools/audit_models.py` after
  the yaml change.

## 4. Baseline

- `python -m pytest engine` → **768 passed, 6 skipped** at `4e5d4e6`
  (counted from the progress dots — the summary line was not captured; re-run
  before starting).
- New test file this feature adds: `engine/tests/test_weapons_live.py`.
- Nothing failing before this feature starts. Commit or stash the 26
  uncommitted paths first so the feature's diff is its own.
- STATUS.md line to rewrite when done: "Weapons, lost items — **Fake** —
  models present, no worker, no tables" → knives real, lost items still fake.

## 5. Still unknown

- Whether `test_api.py` or `test_page_states.py` pins the review body's
  `actor` or the capability name "Weapon detection" — grep before renaming.
- Whether `Clock` should grow a `start_of_local_day(days_ago)` helper or
  `weapon_window` inlines `_start_of_today`'s arithmetic — decide when
  writing it.
- How wide a YOLO person box is around an outstretched arm on a real
  corridor camera — the margin constant (0) may need to move once a knife
  clip exists.
- Whether this machine's OpenCV opens an `avc1` writer (the recorder logs a
  fallback warning if not) — check the first real clip in the browser.
- `CameraFrame` draws boxes only in the enlarged view; whether a tile should
  show a red knife box too is a UX call for Mohamed, not a plan decision.
