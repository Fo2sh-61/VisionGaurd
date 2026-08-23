---

description: "Task list for Find a lost bag — tick areas, search live, pin the cameras that saw one"
---

# Tasks: Find a lost bag

**Input**: Design documents from `/specs/005-lost-bag-search/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md), [context.md](./context.md) — **read context.md before opening any source file**

**Tests**: Included and mandatory. The constitution requires test-first for
business rules, and `AGENTS.md` requires every fix to ship with its regression
test in the same commit. The only-ticked-cameras rule, the two-frame rule, the
replace rule, the colour filter and every honest state are business rules.

**Organization**: Two stories and a polish phase. US1 is the whole feature
without colour and ships on its own. US2 adds colour on top without touching
the job's shape. Stop after either checkpoint and the page is still honest.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 / US2
- Every task names its exact file

## Path Conventions

Engine: `engine/vg/…`, tests `engine/tests/…`. Console: `web/src/…`. Line
endings per context.md §3 — CRLF files stay CRLF, new files match their
neighbour, edit with byte-level scripts.

---

## Phase 1: Setup

**Purpose**: nothing to scaffold — three new files, one rebuild, edits
elsewhere. Three checks that the ground is where the plan says it is.

- [X] T001 Confirm the four gates are green before touching anything: `python -m pytest engine` (expected **811 passed, 6 skipped** at `e101db1`), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`; `rm` any `engine/tests/t_scratch*.py` left by a review agent first; record the count for the commit message
- [X] T002 [P] Add `models.bags` to `engine/engine.yaml` above the `search:` entry: `task: detect`, `weights: models/bagbest.pt`, `imgsz: 640`, `conf: 0.4`, `iou: 0.45`, `half: true`, `version: bags-v1-2026-08-07`, with a comment that it is the owner's fine-tuned YOLO-World, that only `backpack`/`handbag`/`suitcase` are used, and that the other eight classes are deliberately ignored; add a one-line comment above `search:` saying it is history and nothing loads it. CRLF file
- [X] T003 [P] Settle context.md §5's first unknown in a throwaway script (not committed): load `models/bagbest.pt` with `YOLO_AUTOINSTALL=false`, run `predict(classes=[0, 4, 5])` on the walk-through clip's first frame, and confirm the returned `cls` values are only 0/4/5 — if a `WorldModel` ignores `classes=`, note it and plan to filter on `cls` in `bags_from` instead

**Checkpoint**: baseline known-green, config points at the real model, the
one thing the plan could not settle by reading is settled.

---

## Phase 2: Foundational (blocks both stories)

**Purpose**: the wire, the store protocol, the construction plumbing and the
test doubles. Both stories go through `LostQuery` and `LostResult`, and both
are tested with the same fake registry.

**⚠️ CRITICAL**: no story work begins until this phase is complete.

- [X] T004 Reshape the wire in `engine/vg/api/schemas.py` per [data-model.md](./data-model.md) §3: `LostQuery(cameras: list[str] = [], colour: str | None = None, item: str = "bag")` — **drop `area` and `since`**; `LostHit` + `colour: str | None = None`, `colours: list[str] = []`; `SearchJob.state` Literal gains `"stopped"`; new `UnavailableCamera(camera_id, camera_name, reason)`; `LostResult` + `cameras_checked: int = 0`, `cameras_unavailable: list[UnavailableCamera] = []`, `hidden_by_colour: int = 0`, `frames_checked: int = 0`, `seconds_limit: float = 60.0`, `seconds_elapsed: float = 0.0`. Additive except `LostQuery`. CRLF file
- [X] T005 Widen the store protocol in `engine/vg/api/store.py`: `Store` gains `lost_search(self) -> S.LostResult | None` and `stop_lost_search(self) -> None`; `MockStore.search_lost` fills the new fields honestly (`cameras_checked=1`, the rest zeros, fixture hits get `colour="black"`, `colours=["black"]`), stores the result in `self._last_lost`; `MockStore.lost_search` returns it (or `None`); `MockStore.stop_lost_search` is a no-op; rename the `CAPABILITIES` entry to `("search_lost", "Lost bag search")`. CRLF file
- [X] T006 [P] Add `("GET", "/lost-items/search")` and `("DELETE", "/lost-items/search")` to `TestCoverage.REQUIRED` in `engine/tests/test_api.py`; confirm `engine/tests/test_no_fixtures.py` still constructs `S.LostQuery(item="bag")` (it does — `item` keeps its default) and that the bare-store expectation is `hits == []`. LF files
- [X] T007 Thread the subsystem through construction: in `engine/vg/api/live.py` add `lost=None` to `LiveStore.__init__` storing `self.lost_search_job = lost` (**not** `self.lost_search` — that is the method name from T005's protocol, and assigning it would shadow the method the way `self.people` once did) and `self.lost_error: str | None = None`; in `engine/vg/api/app.py` add `app.state.lost = None` and `app.state.lost_error = None` beside the other defaults, pass `lost=app.state.lost` into `LiveStore(...)`, set `store.lost_error = app.state.lost_error` after it. CRLF files
- [X] T008 [P] Create `engine/tests/test_lost_bag.py` with the doubles: `frame(camera_id, at, sequence)` copied from `test_weapons_live.py`; `bag(x, y, w, h, confidence, label="backpack")` returning a `DetectedBag`; `FakeBags(boxes_by_camera: dict[str, list])` whose `detect(image)` records every call in `asked` — because the real detector takes only an image, the job must call `detect` with the frame's image and the fake's `FakeWorker` tags each frame's image with its camera id (a 1-pixel marker, or a dict keyed by `id(image)`) so `asked` can be resolved to camera ids; `FakeWorker(config, frames: list[Frame], status="ok")` whose `last_frame()` hands out the next scripted frame and then repeats the last; `FakeRegistry(workers: dict, disabled: dict)` with `worker(id)`, `configs()`, `disabled`, `online`, `total`; `FixedNow()` callable so the job's clock is the test's; `live_store(tmp_path, lost=None)` copied from `test_weapons_live.py` (keep the `clips_dir` redirect); then write and watch fail `test_bare_live_store_search_is_failed_not_done` (`bare_live_store.search_lost(S.LostQuery())` → `job.state == "failed"`, `hits == []`; capability UNAVAILABLE with a reason) and `test_demo_mode_still_searches` (`MockStore().search_lost(S.LostQuery(cameras=["x"]))` → `done`, one hit, `cameras_checked == 1`). CRLF file (its neighbour `test_weapons_live.py` is CRLF)

**Checkpoint**: the wire carries the new shape, demo mode still works, the
doubles exist, `python -m pytest engine` is green with two more tests.
Nothing on screen has changed.

---

## Phase 3: User Story 1 — tick cameras, search live, pin the ones that saw a bag (Priority: P1) 🎯 MVP

**Goal**: an operator ticks areas or cameras, presses Search, and for up to a
minute the chosen cameras are looked at; any that saw a bag twice come to the
front of the grid, marked, with the bag outlined. Nothing runs when nobody is
searching. No colour yet.

**Independent test**: `.\dev.ps1 up -Clip` — Search is disabled until the clip
camera is ticked; a search over it ends on its own at 60 s with "1 camera
checked over 60 seconds. No bag seen."; System Health shows *Lost bag search ·
bagbest on cuda · idle*; with a real bag on the webcam the camera pins with a
badge and an amber box within seconds. Covers acceptance scenarios 1, 2, 3, 5,
6 and P7-FR-001–005, 008–016.

### Tests for User Story 1 ⚠️ write first, watch them fail

All in `engine/tests/test_lost_bag.py`, driven with the Phase 2 doubles. No
camera, no model, no sleeping — the job takes a `now` callable.

- [X] T009 [P] [US1] `test_only_chosen_cameras_are_ever_analysed` in `engine/tests/test_lost_bag.py` — registry with `cam-a`, `cam-b`, `cam-c`; query `cameras=["cam-a", "cam-c"]`; run the job to completion; `FakeBags.asked` resolves to `{"cam-a", "cam-c"}` only (**SC-004, P7-FR-003**)
- [X] T010 [P] [US1] `test_a_single_frame_is_not_a_result` in `engine/tests/test_lost_bag.py` — `cam-a` shows a bag in exactly one frame then nothing; after the search `hits == []` and `cameras == []`, but `frames_checked > 0` (the two-frame rule, D1)
- [X] T011 [P] [US1] `test_a_bag_seen_twice_pins_its_camera_with_a_box` in `engine/tests/test_lost_bag.py` — `cam-a` shows a bag in three frames; `LostResult.hits` has one entry for `cam-a` with `box.kind == "object"`, `box.severity is WARN`, `box.label == "Backpack"`, `box.match is NONE`, `box.track_id is None`, `confidence` = the best of the three, `at` = the last frame's time, `note` mentions "3 times"; `cameras[0].id == "cam-a"` and carries the same box (**P7-FR-008, 009, 015**)
- [X] T012 [P] [US1] `test_an_unchanged_frame_is_not_analysed_twice` in `engine/tests/test_lost_bag.py` — `FakeWorker` repeats the same `sequence` five times; `FakeBags.asked` has one call for that camera
- [X] T013 [P] [US1] `test_the_search_ends_at_the_limit` in `engine/tests/test_lost_bag.py` — `FixedNow` advanced past `started_at + LIMIT_SECONDS` between rounds; `job.state == "done"`, the thread is not alive, `seconds_elapsed >= LIMIT_SECONDS` (**SC-002, P7-FR-010**)
- [X] T014 [P] [US1] `test_a_new_search_replaces_the_running_one` in `engine/tests/test_lost_bag.py` — start A over `cam-a`, then B over `cam-b` while A runs; A's `state == "stopped"`, A's thread joined, `lost_search()` returns B, and B's hits never include `cam-a` (**P7-FR-011**)
- [X] T015 [P] [US1] `test_stop_keeps_the_hits` in `engine/tests/test_lost_bag.py` — a bag confirmed on `cam-a`, then `stop()`; `state == "stopped"`, the hit is still there, `GET` still returns it
- [X] T016 [P] [US1] `test_an_offline_camera_is_named_not_dropped` in `engine/tests/test_lost_bag.py` — `cam-b` with `status="offline"`; it is in `cameras_unavailable` with the reason "offline", `cam-a` is still checked, the search still completes (**P7-FR-013**)
- [X] T017 [P] [US1] `test_an_unknown_camera_is_named_not_404` in `engine/tests/test_lost_bag.py` — query includes `"cam-nope"`; the endpoint returns 200, `cameras_unavailable` names it with "Not a camera on this engine.", the rest run
- [X] T018 [P] [US1] `test_a_search_of_nothing_fails_with_a_sentence` in `engine/tests/test_lost_bag.py` — `cameras=[]` → 200, `job.state == "failed"`, `job.error == "No camera was chosen."`, no thread started
- [X] T019 [P] [US1] `test_a_tiny_box_is_ignored` in `engine/tests/test_lost_bag.py` — a bag box of `w*h < MIN_BOX_FRACTION` in every frame → no hit
- [X] T020 [P] [US1] `test_the_overlay_carries_no_name_and_drops_after_the_hold` in `engine/tests/test_lost_bag.py` — a `LiveStore` with a fake job whose `boxes_on("cam-a")` returns one hit and whose recogniser names a face on the same camera: `store.overlay("cam-a", "lost")` is one amber `object` box labelled "Backpack" with `match == NONE`; `store.overlay("cam-a", "attendance")` still carries the name; with `FixedNow` moved past `OVERLAY_HOLD_SECONDS` the `lost` overlay is `[]` (**rules 1 and 3, D5**)
- [X] T021 [P] [US1] `test_a_lost_poll_does_not_wake_face_recognition` in `engine/tests/test_lost_bag.py` — through `authed(app)`: `GET /cameras/cam-a/detections?feature=lost` leaves `recogniser.boosted == []`; `feature=attendance` still boosts (the knife-page lesson)
- [X] T022 [P] [US1] `test_works_with_every_other_feature_off` in `engine/tests/test_lost_bag.py` — `_start_lost` on a roster whose only camera has `features: []`, with `bags.BagDetector` monkeypatched to a stub, returns a search object and no error; no person detector is constructed (**rule 9, P7-FR-014**)
- [X] T023 [P] [US1] `test_capabilities_say_why` in `engine/tests/test_lost_bag.py` — `bare_live_store` → UNAVAILABLE; with `lost_error = "weights not found"` → UNAVAILABLE containing it; with a fake search object → LIVE and `reason is None`; `health().pipeline` has a `search_lost` stage whose `healthy` matches and whose detail says `idle` or `searching N cameras` (**P7-FR-016, D6**)
- [X] T024 [P] [US1] `test_endpoints_through_the_app` in `engine/tests/test_lost_bag.py` — `POST /lost-items/search` → 200 `running`; `GET` → same id; `DELETE` → 204 and `GET` → `stopped`; `GET` before any POST → 404; `authed(app, role="it")` can POST (pins `/lost-items` out of the admin prefixes)

### Implementation for User Story 1

- [X] T025 [US1] Create `engine/vg/infer/bags.py` as a copy of `engine/vg/infer/weapons.py`: the `os.environ.setdefault("YOLO_AUTOINSTALL", "false")` lines at the **top of the module** with the CLIP comment; `DEFAULT_WEIGHTS = REPO_DIR / "models" / "bagbest.pt"`; `BAG_CLASSES = {0: "backpack", 4: "handbag", 5: "suitcase"}`; `DetectedBag(x, y, w, h, confidence, label)` frozen with `.area`; `BagDetector(weights, device="auto", imgsz=640, conf=0.4, iou=0.45, half=True)` with `FileNotFoundError` naming the file, `_resolve_device`, the lock round `predict(..., classes=list(BAG_CLASSES), verbose=False)`, `_warm_up`, static `bags_from(boxes, w, h)` labelling from `BAG_CLASSES[int(box.cls[0])]` (skip any other index, per T003), sorted most-confident first, `export_tensorrt`; docstring per research D1 — what the model is, that it is a `WorldModel`, the three classes kept and the eight ignored, the measured cost. LF file
- [X] T026 [US1] Create `engine/vg/features/lostbag.py` — a **job, not a `FeatureWorker`** — per [data-model.md](./data-model.md) §1: constants `LIMIT_SECONDS = 60.0`, `CONFIRM_FRAMES = 2`, `ROUND_PAUSE_SECONDS = 0.1`, `OVERLAY_HOLD_SECONDS = 5.0`, `MIN_BOX_FRACTION = 0.01`, each with its reason; dataclasses `Hit(at, box, label, confidence, colour=None, colours=frozenset())`, `Unavailable(camera_id, camera_name, reason)`, `Job(id, query, started_at, ends_at, state, cameras, checked, unavailable, hits, frames_checked, error)` with `seconds_elapsed(now)` and `confirmed()` (cameras with `>= CONFIRM_FRAMES` hits); `class BagSearch(registry, detector, clock, limit_seconds=LIMIT_SECONDS, now=None)`: `start(query) -> Job` (stops and joins any running job first; empty `cameras` → a `failed` job with "No camera was chosen." and no thread; unknown ids → `Unavailable("Not a camera on this engine.")`, `registry.disabled` → "The camera is switched off."; one `threading.Thread(daemon=True, name="lost-bag-search")`), `current() -> Job | None`, `stop()` (set the event, join ≤ 2 s), `boxes_on(camera_id) -> list[Hit]` (hits with `now - at <= OVERLAY_HOLD_SECONDS`), `stats` (`{"cameras", "last_inference_ms", "state"}`); `_run(job)`: loop until the event or `now >= ends_at`, per camera `worker = registry.worker(cid)`; `status != "ok"` → unavailable once; `frame = worker.last_frame()`; skip if `None` or `sequence` unchanged; `detector.detect(frame.image)`; keep boxes with `w*h >= MIN_BOX_FRACTION`; append `Hit` per box; count `frames_checked`; check the stop event **between cameras**; `time.sleep(ROUND_PAUSE_SECONDS)` after a round that saw no new frame; a camera that never produced a frame → unavailable "The camera sent no frames." at the end; any exception → `state = "failed"`, `error = _reason`, logged, never raised. All times from `now()` — **wall clock, this is live**. Module docstring: why a job and not a worker (D2), why no person gate (a lost bag has nobody near it), the cost table (D8). LF file
- [X] T027 [US1] Wire the subsystem at startup in `engine/vg/api/app.py`: `_start_lost(cfg, registry, roster)` copied from `_start_weapons` — `enabled = [c.id for c in roster if c.enabled]`, none → `(None, "No camera is running, so there is nothing to search.")`; `spec = cfg.models.get("bags")`, missing → `(None, "No 'bags' model is configured in engine.yaml.")`; `BagDetector(weights=spec.weights, device=spec.device, imgsz=spec.imgsz, conf=spec.conf, iou=spec.iou, half=spec.half)`; `BagSearch(registry, detector, clock_for(cfg.timezone))` — **no start call**; `FileNotFoundError` → `f"Lost bag search failed to start ({exc})"`, other exceptions → `_reraise_if_strict` then the reason; returns `(search, error)`. Call it in `lifespan` right after `_start_weapons`, assigning `app.state.lost, app.state.lost_error`; on shutdown call `getattr(app.state, "lost", None).stop()` **before** the worker loop (it is not a worker). CRLF file
- [X] T028 [US1] Replace the `search_lost` stub in `engine/vg/api/live.py` (delete it from the "to-do list" section) with a new `# -- lost bag` section beside `# -- knife detection`: `search_lost(query)` → `self.lost_search_job.start(query)` then `self._lost_result(job)`, or a `failed` result with the capability sentence when there is no search object; `lost_search()` → `_lost_result(current())` or `None`; `stop_lost_search()`; `_lost_result(job)` per [contracts/api.md](./contracts/api.md) — names from `self.registry.configs()`, `location = self._area_of(...)`, one `S.LostHit` per confirmed camera (best confidence, last `at`, `note = f"Seen {n} times over {secs:.0f} seconds"`, `box` via `_bag_box(hit)`, `clip=None`, colour fields from the hit), `cameras = [self.camera_view(cid, feature="lost")]` for each, `job` mapped with `progress = min(1.0, elapsed / limit)`, the six new counts, every fraction and confidence clamped 0..1. CRLF file
- [X] T029 [US1] Make the overlay honest in `engine/vg/api/live.py`: insert `if feature == "lost": return self._bag_boxes(camera_id)` in `_boxes` **above the face default**, beside the `weapons` branch and its comment; `_bag_boxes` → `S.Box(x, y, w, h, label=hit.label.title(), confidence=, kind="object", severity=S.Severity.WARN)` from `self.lost_search_job.boxes_on(camera_id)`, `[]` without a search object; replace the hard-coded `"search_lost"` tuple in `capabilities()` with `self._lost_state()` (D6's four sentences, copied from `_weapons_state`); add `self._lost_stage()` to the `health()` pipeline after `_weapons_stage()` — detail `f"{version} on {device} · idle"` or `f"… · searching {n} cameras"`, unhealthy with the reason. CRLF file
- [X] T030 [US1] Serve the endpoints in `engine/vg/api/app.py`: keep `POST /lost-items/search` (wrap `SubsystemUnavailable` → 503 the way the neighbours do); add `GET /lost-items/search` → `store.lost_search()` or `HTTPException(404, "No search has been run.")`; add `DELETE /lost-items/search` with `status_code=204` → `store.stop_lost_search()`; all tagged `lost-items`; widen `camera_detections`' `Query(pattern=...)` to `^(attendance|track|counting|intrusion|weapons|lost)$` — **no boost change**, `lost` is deliberately absent from `FACE_OVERLAYS`. CRLF file
- [X] T031 [P] [US1] Mirror the wire in the console: `web/src/services/wire.ts` per data-model §3 (`LostQuery {cameras: string[]; colour?: string | null; item?: string}`, `LostHit + colour?, colours?`, `SearchJob.state` + `'stopped'`, `UnavailableCamera`, `LostResult` + the six fields); `web/src/types.ts` → `LostQuery {cameras: string[]; colour?: string}`, `LostHit {cameraId, camera, area, time, confidence: string, note, colour?, colours: string[]}`, `LostResult {state, hits, cameras, camerasChecked, unavailable: {camera, reason}[], hiddenByColour, framesChecked, secondsElapsed, secondsLimit, error?}`; `web/src/services/content.ts` loses `LOST_SINCE` and its comment; `web/src/app/navigation.ts` blurb → `'Look for it now'`. CRLF except `navigation.ts` (LF)
- [X] T032 [US1] Rewrite the service in `web/src/services/api.ts`: `CameraFeature` gains `'lost'`; `searchLostItem({cameras, colour})` posts `{cameras, colour: colour ?? null}` with no timeout override; `getLostSearch()` GET; `stopLostSearch()` DELETE (`204`, no body); `toLostResult(r)` mapper filling `types.ts`'s shape (`confidence: formatPercent`, `time: formatTime(h.at)`, `unavailable` with camera names, `cameras: r.cameras.map(c => toCamera(c, `Bag seen · ${formatTime(hit.at)}`))`); delete `SEARCH_TIMEOUT_MS` if nothing else uses it (context.md §5). CRLF file
- [X] T033 [US1] Add `pinned?: string[]` to `web/src/components/CamGrid.tsx`: `useMemo` sorts `shown` so pinned ids come first in the given order; a pinned tile gets the `activeId` outline **and** a `Badge tone="warn"` reading "Bag seen" in `camcard__meta`; prop comment says it is the only prop that reorders the roster and why (a search result is the one case where order is the answer). LF file
- [X] T034 [US1] Rebuild `web/src/pages/LostItems.tsx` per research D7: keep `chipStyle`, `DataNotice`, `change()`, the summary line; **delete** `useAutoRun`, `BAGS`, `LOST_SINCE`, the area `Select`, the ranked list, `found`, "Watch clip", "This is it"; add the **area tree** from `useCameras().cameras` grouped by `area ?? 'Unassigned'` — one checkbox per area (all / none / indeterminate), an expand toggle revealing one checkbox per camera, ticked ids in a `Set<string>`; colour chips kept but reduced to `Any` only for this story (US2 restores the palette); **Search** disabled until the set is non-empty, becomes **Stop** while `running`; `phase: idle | running | done | stopped | failed`; poll `getLostSearch()` every 1 s while running (`useEffect` + `setInterval`, cleared on unmount and on phase change); a status line built from the counts — running: "Checking N cameras · Ms of 60"; done with hits: "N cameras checked · bags seen on M"; done without: "N cameras checked over 60 seconds. No bag seen."; stopped: "Stopped after Ms · N cameras checked"; failed: the error; unavailable cameras listed by name with their reasons; `<CamGrid title="Cameras searched" note="Amber boxes mark a possible bag. Cameras that saw one are first." feature="lost" tileOverlay pinned={hits.map(h => h.cameraId)} cameras={result?.cameras ?? []} />`; PageHeader lead "Tick the areas to check and press Search. The cameras are looked at live for up to a minute; nothing is recorded." LF file

**Checkpoint**: tick → search → pin → open works end to end; the clip
produces nothing and says so; Stop works; System Health is honest. Every
entry is a bag of any colour. **Shippable.**

---

## Phase 4: User Story 2 — narrow by colour, leniently (Priority: P2)

**Goal**: an operator picks a colour; bags whose lenient colour set lacks it
are hidden, and the page says how many. The filter is tolerant where lighting
makes the answer uncertain (research D3).

**Independent test**: with a real bag on the webcam, picking its colour still
pins the camera; picking a colour it is not unpins it and shows "1 bag hidden
by colour"; dimming the room does not change the first answer for a black or
a strongly coloured bag. Covers acceptance scenario 4 and P7-FR-006, 007.
Engine work needs only Foundational; the chips need T034.

### Tests for User Story 2 ⚠️ write first, watch them fail

- [X] T035 [P] [US2] `test_colour_under_seven_lights` in `engine/tests/test_lost_bag.py` — table-driven from research D3: for each palette colour and each of the seven lighting transforms (normal, dim ×0.45, very dim ×0.25, bright ×1.6, warm lamps, cool daylight, dim + warm), build a synthetic crop (colour + noise + a dark strap across 10 %) and a mid-grey frame under the same light; `name_colour(crop, frame).lenient` **must contain the true name in every row**, with `grey`/`white` both mapping to `light`; print a strict-accuracy summary but assert only on the lenient set (the acceptance bar in data-model §2)
- [X] T036 [P] [US2] `test_colour_filter_hides_with_a_count` in `engine/tests/test_lost_bag.py` — two cameras each confirm a bag, one with `colours={"blue","black"}` and one with `{"red"}`; query `colour="blue"` → one hit, `hidden_by_colour == 1`, the red camera is **not** in `cameras`; `colour=None` → two hits, `hidden_by_colour == 0` (**P7-FR-006, 007**)
- [X] T037 [P] [US2] `test_an_unknown_colour_is_422_naming_the_palette` in `engine/tests/test_lost_bag.py` — `POST` with `colour="purple"` → 422 whose detail lists the six names
- [X] T038 [P] [US2] `test_a_hit_carries_its_colour_on_the_wire` in `engine/tests/test_lost_bag.py` — the `LostHit` from T011's scenario has `colour` set and `colours` a non-empty list

### Implementation for User Story 2

- [X] T039 [US2] Create `engine/vg/infer/colour.py` per data-model §2: `PALETTE` (`black`, `light`, `red`, `blue`, `green`, `yellow`) with Lab references, `ACHROMATIC_CHROMA = 14`, `HUE_TOLERANCE_DEG = 35`, `DARK_L = 70`, `LIGHT_L = 150`; `ColourGuess(best: str, lenient: frozenset[str])`; `name_colour(crop_bgr, frame_bgr) -> ColourGuess` — central 60 % of the crop, grey-world gain from the frame mean, median pixel, `cv2.COLOR_BGR2LAB`, chroma gate, hue bins, lenient set (hue within tolerance; achromatic neighbours; a dark chromatic adds `black`); `crop_for(image, box)` helper that clamps a fraction box to pixels; `KNOWN_COLOURS` tuple exported for the endpoint's validation. No model, no GPU, no state. Docstring: the two halves of "independent of lighting" from D3, and the measured numbers marked synthetic. LF file
- [X] T040 [US2] Name the colour at hit time in `engine/vg/features/lostbag.py`: in `_run`, for each kept box call `name_colour(crop_for(frame.image, box), frame.image)` and store `colour=guess.best`, `colours=guess.lenient` on the `Hit`; wrap it so a colour failure (degenerate crop) logs once and leaves the fields empty rather than losing the hit. LF file
- [X] T041 [US2] Apply the filter in `engine/vg/api/live.py::_lost_result`: when `query.colour` is set, a confirmed camera counts only if **any** of its hits has `query.colour in hit.colours`; the rest increment `hidden_by_colour`; the surviving `LostHit` carries the best matching hit's `colour`/`colours`. Validate `query.colour` against `KNOWN_COLOURS` in `search_lost` and raise `ValueError` → the endpoint turns it into 422 naming the palette (`engine/vg/api/app.py`). CRLF files
- [X] T042 [US2] Restore the colour chips in `web/src/pages/LostItems.tsx`: palette `Black · Grey or white · Red · Blue · Green · Yellow · Any` sending `black / light / red / blue / green / yellow / undefined`, swatches from the existing `COLOURS` dots with `light` as a light-grey gradient; a change of colour invalidates the result (`change()`), and the status line gains "Colour: blue — N bags hidden" when a filter was applied, plus one sentence under the chips: "Colour is judged from the camera picture and can be wrong in poor light. Pick Any if the bag is not found." LF file
- [X] T043 [P] [US2] Add the lenient-set wording to the hit's status in `web/src/services/api.ts::toLostResult`: the camera's status override becomes `Bag seen · ${time} · looked ${colours.join(' or ')}` when colours are present. CRLF file

**Checkpoint**: colour narrows without hiding the right bag in the measured
cases, and says what it hid. **Shippable.**

---

## Phase 5: Polish & cross-cutting

- [X] T044 Add `"bags"` to `--model` in `engine/tools/benchmark.py` (`from vg.infer.bags import BagDetector as Detector`, timed through `detect`, the "clip contains no bag" note mirrored from the weapons branch); run it and put the row (p50 / p95 / fps) in `docs/PLAN.md` §7 beside the person and knife rows. LF / CRLF
- [X] T045 [P] Update `models/README.md`: a section for `bagbest.pt` (the owner's fine-tuned YOLO-World, 11 classes, the three used, research D1's numbers, the `YOLO_AUTOINSTALL` guard, accuracy on real bags unmeasured); the "second custom model: appearance search" section becomes history — `yolov8m-worldv2-search.pt` no longer serves lost items; regenerate `models/MODELS.md` with `python engine/tools/audit_models.py` (the sidecar yamls are gitignored — only `MODELS.md` ships). LF
- [X] T046 Run the four gates from the repo root: `rm engine/tests/t_scratch*.py` if present; `python -m pytest engine` (count must be **above 811** — 30+ new tests), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`; `git diff --stat` must show no whole-file line-ending flips
- [X] T047 Run the pipeline check from [quickstart.md](./quickstart.md) §3 — `.\dev.ps1 up -Clip`: Search disabled until ticked; a full search over the clip ends at 60 s with the counted sentence; *Lost bag search · bagbest on cuda · idle* on System Health; Stop after five seconds; People counting unchanged during a search; clean restart
- [X] T048 [P] Update `STATUS.md`: the "Lost items — **Fake**" row becomes **Real** — on demand, live only, ticked cameras, two-frame rule, lenient colour, nothing recorded, nothing alerted, accuracy on real bags unmeasured; add "a recorded clip with a bag in it" to "Blocked on the owner"; bump the gates line. CRLF
- [X] T049 [P] Update `docs/PLAN.md`: FR-08 from "missing" to "partial — live search on demand; no recorded-footage search until continuous recording exists"; P7 gains a paragraph saying what was built (the job, the two-frame rule, lenient colour) and what was not (recording, index-at-ingest, re-ID); §7 gains the bag row from T044. CRLF
- [ ] T050 Ask Mohamed for the manual check in [quickstart.md](./quickstart.md) §4 — a bag on a chair, moved mid-search, the colour under dimmed light, an empty chair, a double press, a restart — and to record the bag clip into `engine/data/footage/` with `python engine/tools/record.py`. Only his eyes, his bag and his lamps can do these
- [ ] T051 Commit `engine/`, `web/`, `models/README.md`, `models/MODELS.md`, `STATUS.md`, `docs/PLAN.md` and `specs/005-lost-bag-search/` together, tests in the same commit, stating the before and after pytest counts (811 → the new number) and the four owner answers from spec.md Assumptions in the message

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Setup — **blocks both stories**
- **US1 (Phase 3)**: needs Foundational
- **US2 (Phase 4)**: engine tasks (T035–T041) need only Foundational, except
  T040 which edits the job T026 creates; the page tasks T042–T043 need T034
- **Polish (Phase 5)**: needs whichever stories you shipped

### The real cross-story dependencies

Two. T040 adds a call inside the `_run` loop T026 writes, and T042 restores
chips to the page T034 rebuilds. Everything else in US2 stands on
Foundational alone — `colour.py` is a pure function and its test needs
nothing from US1.

### Within each story

Tests first and failing → model runner → job → store → API → console. Never
the reverse: a passing test written after the code proves the test, not the
code.

### Parallel opportunities

- T002 and T003 together (a yaml edit and a throwaway script)
- T006 and T008 while T004/T005/T007 are in progress (different files)
- The sixteen US1 tests T009–T024 in one pass — one file, no shared logic
- T031 (console wire) alongside T025–T030 (engine)
- T033 (CamGrid) alongside T032 (api.ts) — different files
- T035 and T036–T038 together; T039 (colour.py) alongside T041 (live.py)
- T045, T048, T049 together at the end

---

## Parallel Example: User Story 1

```bash
# The sixteen tests, written together, all failing:
T009 test_only_chosen_cameras_are_ever_analysed
T010 test_a_single_frame_is_not_a_result
T011 test_a_bag_seen_twice_pins_its_camera_with_a_box
T012 test_an_unchanged_frame_is_not_analysed_twice
T013 test_the_search_ends_at_the_limit
T014 test_a_new_search_replaces_the_running_one
T015 test_stop_keeps_the_hits
T016 test_an_offline_camera_is_named_not_dropped
T017 test_an_unknown_camera_is_named_not_404
T018 test_a_search_of_nothing_fails_with_a_sentence
T019 test_a_tiny_box_is_ignored
T020 test_the_overlay_carries_no_name_and_drops_after_the_hold
T021 test_a_lost_poll_does_not_wake_face_recognition
T022 test_works_with_every_other_feature_off
T023 test_capabilities_say_why
T024 test_endpoints_through_the_app

# Then two files make most of them pass:
T025  engine/vg/infer/bags.py
T026  engine/vg/features/lostbag.py
# and the wiring makes the rest:
T027–T030  app.py, live.py
# while the console goes in parallel:
T031–T034  wire.ts, types.ts, api.ts, CamGrid.tsx, LostItems.tsx
```

---

## Implementation Strategy

### MVP: Phase 1 → 2 → 3 (US1), then stop and look

34 tasks. Tick, search, pin, open. The clip produces nothing and the page
says exactly how many cameras it checked. Every bag of every colour is a
result. Shippable, and it is the half with the moving parts: the job, the
two-frame rule, the replace rule, the overlay above the face default.

### Then US2 — colour

9 tasks. A pure function with a table-driven test, one call inside the job's
loop, one filter in the mapper, the chips back on the page. Small, because
the job's shape does not change: colour is named at hit time and filtered at
read time, and nothing in between cares.

### Then polish

8 tasks, three of which only Mohamed can do.
