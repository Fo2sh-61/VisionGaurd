# Implementation context: Find a lost bag

**Written by `/speckit-plan` on 2026-08-23, against commit `e101db1`** (clean
working tree except the untracked junk — `$OUT`, `150`, `270`, `274`, `913`,
`models/Gate/`, `models/bag traker/` — none of it this feature's).

Read this **before** opening any source file. Then open the named anchors
only — not the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code,
> the code wins and this file is wrong. Anchors drift — search for the symbol,
> do not trust the line number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/infer/weapons.py` | `class WeaponDetector` | `__init__(weights, device="auto", imgsz, conf, iou, half)`; `FileNotFoundError` if missing; `_resolve_device`; `half` only off CPU; `self._lock = threading.Lock()` held round `predict(..., verbose=False)`; static `weapons_from(boxes, w, h, min_confidence)` clamps to fractions, reads `box.cls[0]`; `export_tensorrt`; `CLASS_NAMES = ("knife",)`; `DEFAULT_WEIGHTS = REPO_DIR / "models" / "knifebest.pt"` | **copy** to new `infer/bags.py` as `BagDetector`: `DEFAULT_WEIGHTS = … / "bagbest.pt"`; `BAG_CLASSES = {0: "backpack", 4: "handbag", 5: "suitcase"}`; pass `classes=list(BAG_CLASSES)` into `predict`; `DetectedBag(x, y, w, h, confidence, label)`; label from `BAG_CLASSES[int(box.cls[0])]`; conf default 0.4; docstring per research D1 — it is a `WorldModel`, the `YOLO_AUTOINSTALL` guard is why it loads |
| `engine/vg/infer/persons.py` | top of module | `os.environ.setdefault("YOLO_AUTOINSTALL", "false")` with the comment about CLIP | the same two lines go in `bags.py` — without them a World checkpoint may try to pip-install |
| `engine/vg/features/weapons.py` | `class WeaponsWorker` | a `FeatureWorker` — **do not copy the class**. Copy only: `_on_a_person`-style pure helpers, the constants-with-reasons block at the top, `BUSY_REASON` wording style, the `# noqa: BLE001 - reported, never raised` idiom | new `features/lostbag.py` is a **job**, not a worker: `class BagSearch(registry, detector, clock, limit_seconds=60)`, `start(query) -> Job`, `current() -> Job \| None`, `stop()`, `boxes_on(camera_id) -> list[Hit]` (≤ `OVERLAY_HOLD_SECONDS` old, **wall clock** — this is live), `stats` for health. One `threading.Thread(daemon=True)` per `start`; a `threading.Event` to stop; `_run(job)` loops `for cid in job.cameras: worker = registry.worker(cid); frame = worker.last_frame()`; skip if `frame.sequence == last_seen[cid]`; `detector.detect(frame.image)`; filter `box.w*box.h >= MIN_BOX_FRACTION`; `name_colour(crop, frame.image)`; append `Hit`; `time.sleep(ROUND_PAUSE_SECONDS)` after a round with no new frame; ends when `datetime.now(utc) >= job.ends_at` or the event is set |
| `engine/vg/features/base.py` | `FeatureWorker.RESULT_TTL_SECONDS`, `stats` | wall-clock TTL 3 s; `stats` returns `cameras`, `last_inference_ms` | nothing to edit; `BagSearch.stats` mirrors the keys `{"cameras", "last_inference_ms", "state"}` so `_lost_stage` reads like `_weapons_stage` |
| `engine/vg/ingest/registry.py` | `CameraRegistry.worker(camera_id)`, `CameraWorker.last_frame()`, `.status`, `.config`; `registry.configs()`; `registry.disabled` | `worker()` → `None` for unknown/disabled; `status == "ok"` when delivering; `last_frame()` → `Frame \| None` (`camera_id, image BGR, captured_at UTC, sequence, is_stale`) | read-only. Unknown id → `Unavailable(reason="Not a camera on this engine.")`; `registry.disabled[id]` → `"The camera is switched off."`; `status != "ok"` → `"The camera is offline."`; `last_frame() is None` after the whole search → `"The camera sent no frames."` |
| `engine/vg/api/schemas.py` | `class LostQuery` / `LostHit` / `SearchJob` / `LostResult` (the `# lost items` block, after `Clip`) | `LostQuery(item: str, colour, area, since)`; `LostHit(camera_id, camera_name, at, confidence, note, box, clip)`; `SearchJob(id, state: Literal["queued","running","done","failed"], progress 0..1, submitted_at, clips_searched, clips_total, error)`; `LostResult(job, query, hits, cameras)` | per data-model §3: `LostQuery(cameras: list[str] = [], colour: str \| None = None, item: str = "bag")` — **drop `area`, `since`**; `LostHit` + `colour`, `colours: list[str] = []`; `SearchJob.state` + `"stopped"`; new `UnavailableCamera`; `LostResult` + `cameras_checked`, `cameras_unavailable`, `hidden_by_colour`, `frames_checked`, `seconds_limit`, `seconds_elapsed`. `Wire` is `extra="forbid"` — the console must stop sending `area`/`since` in the same commit |
| `engine/vg/api/store.py` | `Store` protocol `search_lost(self, query)`; `MockStore.search_lost` (builds two `LostHit` and one `CameraView`; `SearchJob(state="done", clips_searched=284, …)`); `CAPABILITIES` tuple `("search_lost", "Lost item search")`; `SubsystemUnavailable` | protocol + `lost_search(self) -> LostResult \| None`, `stop_lost_search(self) -> None`; Mock: keep the fixture, fill the new fields (`cameras_checked=1`, zeros, `colour="black"`, `colours=["black"]`), remember it in `self._last_lost` for `lost_search`, `stop` no-op; rename the capability to `"Lost bag search"` |
| `engine/vg/api/live.py` | `LiveStore.__init__` kwargs end `… zones=None, weapons=None, weapon_scenes=None`; error attrs `weapons_error` etc. | `self.weapons_worker` (never `self.weapons` — shadows the method) | add `lost=None` → `self.lost_search` (**not** `self.lost` — nothing shadows today but keep the convention), `self.lost_error: str \| None = None` |
| `engine/vg/api/live.py` | `search_lost` stub under "this list IS the to-do list" | returns a `failed` job with `id="unavailable"` | **delete**; real `search_lost` / `lost_search` / `stop_lost_search` go in a new `# -- lost bag` section next to `# -- knife detection`. Mapper `_lost_result(job) -> S.LostResult`: names from `{c.id: c.name for c in self.registry.configs()}`; `location` via `_area_of`; hits filtered by `query.colour in hit.colours` when colour set, `hidden_by_colour` = the rest; one `LostHit` per camera with `len(hits) >= CONFIRM_FRAMES`, best confidence, `at` = last, `note = f"Seen {n} times over {secs:.0f} seconds"`; `cameras` = `[self.camera_view(cid, feature="lost")]` per hit camera; clamp every fraction and confidence |
| `engine/vg/api/live.py` | `_boxes(camera_id, feature)` | `track` → `_tracked_boxes`; `counting`/`intrusion` → `_person_boxes`; `weapons` → `_knife_boxes` (inserted above the default with a comment about the knife trap); default → `_face_boxes` | insert `if feature == "lost": return self._bag_boxes(camera_id)` **above the default**; `_bag_boxes` → `S.Box(x, y, w, h, label=hit.label.title(), confidence=, kind="object", severity=S.Severity.WARN)` from `self.lost_search.boxes_on(camera_id)`, `[]` without a search object |
| `engine/vg/api/live.py` | `capabilities()` → `"search_lost": (UNAVAILABLE, "Lost item search is not built yet…")`; `_weapons_state()`; `_weapons_stage()`; `health()` pipeline list | the three-sentence pattern | `"search_lost": self._lost_state()` with D6 sentences; `self._lost_stage()` in the pipeline list after `_weapons_stage()`: `f"{version} on {device} · idle"` or `"· searching N cameras"` |
| `engine/vg/api/live.py` | `_area_of(camera_id)` | reads the live roster first (fixed in `e101db1`), then `engine.yaml`, then the id | reuse for `location` |
| `engine/vg/api/app.py` | `_start_weapons(cfg, registry, roster, detector)` | `watched = [c.id for c in roster if c.enabled]`; `spec = cfg.models.get("weapons")`; `FileNotFoundError` → `f"Knife detection failed to start ({exc})"`; `_reraise_if_strict`; returns `(worker, scenes, error)` | copy as `_start_lost(cfg, registry, roster)` → `(search, error)`: no detector parameter (no person gate); `spec = cfg.models.get("bags")`; `BagDetector(weights=spec.weights, …)`; `BagSearch(registry, detector, clock_for(cfg.timezone), limit_seconds=60)`; **no `.start()`** — nothing runs until a POST; no enabled camera → `(None, "No camera is running, so there is nothing to search.")` |
| `engine/vg/api/app.py` | `lifespan`: the `_start_weapons(` call; `app.state.weapons = None` defaults; `LiveStore(… weapons=, weapon_scenes=)`; `store.weapons_error = …`; shutdown `for worker in (getattr(app.state, "weapons", None), …)` | | `app.state.lost = None`, `app.state.lost_error = None`; call `_start_lost` after `_start_weapons`; pass `lost=app.state.lost`; `store.lost_error = app.state.lost_error`; on shutdown `getattr(app.state, "lost", None)` → `.stop()` **before** the worker loop (it is not a worker; it has no `.stop()` signature mismatch — give `BagSearch.stop()` no arguments) |
| `engine/vg/api/app.py` | `search_lost` endpoint (`@app.post("/lost-items/search")`) | `return store.search_lost(query)` | keep; add `@app.get("/lost-items/search")` → `store.lost_search()` or `HTTPException(404, "No search has been run.")`; `@app.delete("/lost-items/search", status_code=204)` → `store.stop_lost_search()`; all tagged `lost-items`; wrap `SubsystemUnavailable` → 503 the way the other endpoints do (grep `except SubsystemUnavailable`) |
| `engine/vg/api/app.py` | `camera_detections`: `Query(pattern="^(attendance\|track\|counting\|intrusion\|weapons)$")`; `FACE_OVERLAYS = (None, "attendance", "track")` | the recogniser is boosted only for `FACE_OVERLAYS` | widen the pattern with `\|lost`; **no other change** — `lost` is not in `FACE_OVERLAYS`, which is the point; no worker to boost |
| `engine/vg/auth/deps.py` | `ADMIN_PREFIXES`, `ADMIN_WRITE_PREFIXES` | `/lost-items` in neither | nothing — and a test pins it |
| `engine/tests/test_weapons_live.py` | `FakeDetector`, `FakeKnives`, `frame()`, `live_store()` (redirects `clips_dir` into `tmp_path`), `TestHonestStates`, `test_a_weapons_poll_boosts_knives_and_leaves_face_recognition_alone`, `TestStandsAlone` | the doubles and the endpoint-through-`authed(app)` pattern | copy into new `test_lost_bag.py`: `FakeBags(boxes_by_camera)` recording `asked: list[str]` — **note** the real detector takes an image, so the fake registry's `FakeWorker.last_frame()` returns a `Frame` whose `camera_id` the job passes through; `FakeRegistry(workers: dict, disabled: dict)` with `worker(id)`, `configs()`, `disabled`; `FakeClock`/fixed `datetime` so the limit test needs no sleep — give `BagSearch` a `now` callable (default `datetime.now(utc)`) for this |
| `engine/tests/test_no_fixtures.py` | `"search_lost": lambda: store.search_lost(S.LostQuery(item="bag")).hits` | `item` is still accepted with a default | unchanged **if** `item` keeps its default; `bare_live_store.search_lost(S.LostQuery())` must return `hits == []` with `job.state == "failed"` |
| `engine/tests/test_api.py` | `TestCoverage.REQUIRED` list: `("POST", "/lost-items/search")` | one row per `api.ts` function | add `("GET", "/lost-items/search")` and `("DELETE", "/lost-items/search")` |
| `engine/engine.yaml` | `models:` block — `search:` entry (`yolov8m-worldv2-search.pt`, imgsz 960) | the comment above `models:` was rewritten for knives | add `bags:` per data-model §4, above `search:`; leave `search:` with a one-line comment "history — the zero-shot search model; `bags` replaced it 23 Aug 2026" |
| `web/src/pages/LostItems.tsx` | `export function LostItems` | 344 lines: `BAGS` chips, `COLOURS` chips (`{name, dot}` with `Any` as a gradient), `chipStyle(on)`, `Field/Select` for area + `LOST_SINCE`, `useAutoRun(run)`, `phase: idle\|searching\|done\|failed`, `change(set)` invalidates on any input change, ranked hit list with *Watch clip* / *This is it*, `CamGrid title="Where the bag was seen"` with **no `feature`** (→ faces) | **rebuild**: keep `chipStyle`, the colour chips (palette → `Black · Grey or white · Red · Blue · Green · Yellow · Any`, sending `light` for the second), `change()`, `DataNotice`, the summary line; replace the area `Select` with the **area tree** (from `useCameras().cameras`, group by `area ?? 'Unassigned'`, `Set<string>` of ticked ids, area checkbox = all/none/indeterminate, expand toggle); Search disabled when the set is empty; `phase` gains `stopped`; poll `getLostSearch()` every 1 s while `running` (a `useEffect` with `setInterval`, cleared on unmount); **Stop** button → `stopLostSearch()`; status line from `camerasChecked / secondsElapsed / secondsLimit / hiddenByColour / camerasUnavailable`; `CamGrid title="Cameras searched" feature="lost" tileOverlay pinned={hits.map(h => h.cameraId)}`; delete `useAutoRun`, `BAGS`, `LOST_SINCE`, the ranked list, `found` |
| `web/src/components/CamGrid.tsx` | `CamGrid({ …, feature, tileOverlay })`; `const tile = (cam) => (<button className="camcard" style={cam.id === activeId ? {outline…} : undefined}>`; `shown` is the paged list; `byArea` groups by `cam.area \|\| UNPLACED` | `activeId` is a single outline | add `pinned?: string[]`: sort `shown` so pinned ids come first in the given order (`useMemo`); a pinned tile gets the outline **and** a small `Badge tone="warn"` "Bag seen" in `camcard__meta`; document that it is the only prop that reorders the roster, and why (a search result is the one case where order *is* the answer) |
| `web/src/components/CameraFrame.tsx` | `tileOverlay`, `boxRefreshMs`, the `FACE_OVERLAYS` comment | added for knives in `3b021f1` | nothing — `feature="lost"` flows through `getCameraDetections(camera.id, feature)` |
| `web/src/services/api.ts` | `searchLostItem(query: LostQuery)` posting `{item, colour: 'Any'→null, area, since}` with `SEARCH_TIMEOUT_MS`; maps `hits` to `{camera, time, confidence%, strong, note}`; `cameras: result.cameras.map(toCamera(c, statusOverride))`; `export type CameraFeature = 'attendance' \| 'track' \| 'counting' \| 'intrusion' \| 'weapons'` | | `searchLostItem({cameras, colour})` posts `{cameras, colour}` (no timeout override needed — it returns at once); `getLostSearch()` GET; `stopLostSearch()` DELETE; mapper `toLostResult(r)` fills the UI shape in types.ts; `CameraFeature` + `'lost'` |
| `web/src/services/wire.ts` | `interface LostQuery` / `LostHit` / `SearchJob` / `LostResult` | camelCase mirrors | mirror data-model §3: `LostQuery {cameras: string[]; colour?: string \| null; item?: string}`; `LostHit + colour?, colours?`; `SearchJob.state` + `'stopped'`; `UnavailableCamera`; `LostResult` + the six fields |
| `web/src/types.ts` | `LostQuery {item, colour, area, since}`, `LostHit {camera, time, confidence, strong, note}`, `LostResult {label, sub, hits, cameras, searched}` | UI shapes | `LostQuery {cameras: string[]; colour?: string}`; `LostHit {cameraId, camera, area, time, confidence: string, note, colour?, colours: string[]}`; `LostResult {state, hits, cameras, camerasChecked, unavailable: {camera, reason}[], hiddenByColour, framesChecked, secondsElapsed, secondsLimit, error?}` |
| `web/src/services/content.ts` | `export const LOST_SINCE = […]` with the "Search vocabulary for Lost Items" comment | | delete both |
| `web/src/app/navigation.ts` | `{ id: 'lost-items', …, label: 'Lost bag', blurb: 'Search footage for it' }` | | `blurb: 'Look for it now'` — "footage" is a promise there is no footage to keep |
| `models/README.md` | the knife headline section; "The second custom model: appearance search" section describing `yolov8m-worldv2-search.pt` | the search model is presented as serving lost items | new section for `bagbest.pt` (what it is, the three classes used, D1's numbers, the eight classes deliberately ignored); the search-model section becomes history |
| `engine/tools/benchmark.py` | `--model` with `choices=("person", "weapons")` | added for knives | add `"bags"` → `from vg.infer.bags import BagDetector as Detector`, timed through `detect` |

## 2. Things to copy, not invent

- Model runner → `infer/weapons.py::WeaponDetector` whole file; change names,
  weights, classes, the docstring.
- Honest start-up → `api/app.py::_start_weapons` (`FileNotFoundError` → the
  capability sentence; `_reraise_if_strict`; `_reason`).
- Three-sentence capability → `api/live.py::_weapons_state`; health stage →
  `_weapons_stage` (reads `version`/`device` off the detector with `getattr`).
- Overlay branch and box builder → `api/live.py::_knife_boxes` and the
  comment above `if feature == "weapons"`.
- Endpoint through a real store → `test_weapons_live.py::TestClipEndpoint`
  (`app_module.set_store(store); create_app(); authed(app)`; restore
  `MockStore()` after).
- Boost isolation test → `test_a_weapons_poll_boosts_knives_and_leaves_face_recognition_alone`.
- Rule 9 test → `TestStandsAlone` (monkeypatches `persons.PersonDetector`
  with a stub; do the same for `bags.BagDetector`).
- Tile overlay + pinned outline → `CamGrid.tsx` `tile()` and the Knife page's
  `<CamGrid … feature="weapons" tileOverlay />`.
- Chip buttons → the present `LostItems.tsx::chipStyle` and `COLOURS`.
- Area grouping → `CamGrid.tsx`'s `byArea` loop (`cam.area || UNPLACED`);
  the tree in the page does the same grouping over `useCameras().cameras`.
- Colour experiment → the script in research D3 is the unit test, table-driven
  over its seven lighting rows.

## 3. Traps

- **`_boxes` falls through to faces.** The `lost` branch goes above the
  default or the page shows names. Knife detection shipped with this missing.
- **`bagbest.pt` is a `WorldModel`.** Without `YOLO_AUTOINSTALL=false` set
  *before* `from ultralytics import YOLO`, loading can try to pip-install
  CLIP. Put the `os.environ.setdefault` at the top of `bags.py` as
  `persons.py` does — not inside the class.
- **Eleven classes, three wanted.** Pass `classes=[0, 4, 5]` to `predict`;
  do not filter afterwards and do not let `laptop` (which fires on every desk)
  reach a result.
- **`Wire` forbids unknown fields.** Removing `area`/`since` from `LostQuery`
  422s every request from a console still sending them. Engine and console
  change in one commit.
- **`last_frame()` returns the same frame until the camera delivers.** Skip on
  unchanged `sequence` or the job will count one frame as ten and `note` will
  say "seen 40 times" about one look.
- **Wall clock, not frame clock, for the overlay hold and the limit.** This is
  live; the knife worker's frame-time hold was right *there* because it also
  runs on clips. Make `now` injectable for the tests instead.
- **Stop must join.** A replaced search's thread left running would write hits
  into a job nobody reads and hold the detector lock against the new one.
  `stop()` sets the event and joins with a timeout of a couple of seconds; the
  loop checks the event between cameras, not only between rounds.
- **Do not raise `AlreadyBusy`.** The spec says replace.
- **An empty `cameras` list is payload, not a 422.** `job.state = "failed"`
  with a sentence; the page disables Search anyway.
- **`useAutoRun` must go**, not be left. Home's suggested question lands on
  this page with `autoRun: true`.
- **`CamGrid` reorders nothing today.** `pinned` is the first prop that does;
  keep it the only one, and keep the reorder inside `useMemo` so the grid
  does not reshuffle on every count poll.
- **Line endings.** CRLF: `api/app.py`, `api/live.py`, `api/schemas.py`,
  `api/store.py`, `engine.yaml`, `services/api.ts`, `services/wire.ts`,
  `services/content.ts`, `types.ts`, `STATUS.md`, `docs/PLAN.md`. LF:
  `infer/*.py`, `features/weapons.py`, `pages/*.tsx`, `components/*.tsx`,
  `app/navigation.ts`, `tests/test_no_fixtures.py`, `tests/test_api.py`,
  `models/README.md`. New files match their neighbour; `git diff --stat`
  catches a flip. Write with byte-level edits.
- **Agents leave scratch files in `engine/tests/`.** `t_scratch*.py` and
  `t_demo_scratch.py` appeared during the knife review and broke pyflakes.
  `rm` them before running the gates.

## 4. Baseline

- `python -m pytest engine` → **811 passed, 6 skipped** at `e101db1`
  (817 collected; the 6 skips are `--camera` tests).
- New test file this feature adds: `engine/tests/test_lost_bag.py`.
- Nothing failing. `test_recording.py` has one timing test that fails under
  heavy machine load and passes alone — pre-existing, not this feature's.
- STATUS.md line to rewrite when done: "Lost items — **Fake** — model
  present, no worker, no tables" → real, on demand, live only.

## 5. Still unknown

- Whether `predict(classes=[…])` on a `WorldModel` filters by index the same
  way it does on a plain YOLO (it should — measured output used the names
  dict by index — but confirm on the first run, and fall back to filtering
  `weapons_from` by `cls` if not).
- How the real crop looks: a backpack on a chair in the laptop webcam may be
  a 40-pixel box. `MIN_BOX_FRACTION = 0.01` is a guess at the floor; the
  owner's §4 check decides.
- Whether `note` should say the class ("backpack seen 14 times") — the model's
  class accuracy between the three bag types is unmeasured; the plan uses the
  class only as the box label. Mohamed's call after §4.
- `SEARCH_TIMEOUT_MS` in `api.ts` — referenced by the old `searchLostItem`;
  find whether anything else uses it before deleting it.
