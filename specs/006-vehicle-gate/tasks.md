---
description: "Task list for Vehicle Gate"
---

# Tasks: Vehicle Gate

**Input**: Design documents from `/specs/006-vehicle-gate/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/vehicles-api.md](./contracts/vehicles-api.md), [context.md](./context.md)

**Read [context.md](./context.md) first.** It names every anchor symbol, what shape it is
today, and twelve traps. It exists so this file can stay short.

**Tests**: Included. The constitution requires a regression test in the same commit as
the fix, and `quickstart.md` names the five test files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3

## Path Conventions

Engine at `engine/vg/`, tests at `engine/tests/`, console at `web/src/`.

---

## Already done — do not repeat

This session installed and verified the toolchain. Confirm, don't redo:

- TensorRT **11.2.1.2 cu12** installed; `trt.Builder()` works. ultralytics **8.4.127**.
- `models/yolov8s-640.engine` built, **12.0 ms vs 18.3 ms** on `.pt` (1.52x).
- `infer/tracking.py` — `track_buffer_for()` fixes the lost-ID window.
- `infer/{persons,weapons,bags}.py` — `half=` → `quantize=`, log flood gone.
- `requirements.txt` — `opencv-python<5`, `ultralytics>=8.4.127`, both with reasons.
- Identity threshold **0.60**; patrol stays **0.40**.
- **Baseline: 874 tests pass.** The count must go up, never down.

---

## Phase 1: Setup

**Purpose**: Everything in place before any code is written.

- [X] T001 Copy the two plate weights to `models/plate_detector.pt` and `models/char_detector.pt` from `models/Gate/gate-anpr/gate-anpr/models/`, then run `python engine/tools/audit_models.py` to regenerate `models/MODELS.md` and the sidecars
- [X] T002 [P] Add `openpyxl>=3.1` to `engine/requirements.txt` with a one-line reason, and `pip install openpyxl`
- [X] T003 [P] Add a `plates` entry to `engine/engine.yaml` under `models:` — `task: detect`, `weights: models/plate_detector.pt`, `imgsz: 640`, `conf: 0.35`, `version: acplr-ealpr-2026-08-24` — plus a second `plate_chars` entry for the character model
- [X] T004 Add `gate: int | None` and `direction: str | None` to `CameraConfig` in `engine/vg/config.py`, validating `direction in {"entry","exit"}` in `parse()` and rejecting `"both"` with a `ConfigError`
- [X] T005 Give `cam-laptop` in `engine/engine.yaml` `gate: 1`, `direction: entry`, and `vehicles` in its `features:` list
- [X] T006 [P] Add camera-config tests to `engine/tests/test_config.py`: a gate camera parses, `direction: both` raises `ConfigError`, and every existing camera still parses with both fields absent

**Checkpoint**: `python -m pytest engine/tests/test_config.py` green, 874+ still passing.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Plate reading, storage and permissions. No story can start until this is done.

**⚠️ CRITICAL**: T007–T020 block every user story.

### Accelerated inference — finishing the repo-wide job

- [X] T007 Add `weights_to_load(cfg) -> tuple[Path, str]` to `engine/vg/infer/shared.py`: return `<stem>-<imgsz>.engine` beside the `.pt` when it exists **and** `import tensorrt` succeeds, else the `.pt`; second value is the form, `"TensorRT"` or `"PyTorch CUDA"`
- [X] T008 [P] Create `engine/tests/test_engine_selection.py`: picks the engine when present, falls back when absent, **rejects a wrong-size engine** (640 config must not load `yolov8s-480.engine`), and reports the form it chose
- [X] T009 Create `engine/tools/build_engines.py`: loop every model in `vgconfig.load().models`, call that runner's `export_tensorrt()`, **rename the output to `<stem>-<imgsz>.engine`**, and print one line per model — succeeded or the reason. **Verify the file exists after each export; never infer success from an exit code** (see research §5.2 — a segfaulting build reported exit 0 and produced nothing)
- [X] T010 [P] Use `weights_to_load` in `PersonDetector.__init__`, `WeaponDetector.__init__` and `BagDetector.__init__` (`engine/vg/infer/{persons,weapons,bags}.py`), storing the form on `self.form`
- [X] T011 Add `({self.form})` to the healthy `detail` string of `_weapons_stage` and its siblings in `engine/vg/api/live.py`, so System Health reads `coco-yolov8s on cuda (TensorRT) - 2 camera(s), 11ms`
- [X] T012 Run `python engine/tools/build_engines.py` and fill the measurement table in `specs/006-vehicle-gate/quickstart.md` with real p50 figures — **100 iterations after a 10-frame warm-up**, never a short run

### Plate reading

- [X] T013 [P] Create `engine/vg/platetext.py` — port `normalize`, `display`, `plausibility`, `is_wellformed`, `transliterate`, `edit_distance`, `same_plate`, `richer`, and the digit/letter/confusion tables from `models/Gate/gate-anpr/gate-anpr/anpr/plate_text.py`. **Skip `near_variants`** — research §1 confirms nothing calls it
- [X] T014 [P] Create `engine/tests/test_platetext.py`: `١٢٣٤` and `1234` normalise identically, plausibility scores a real plate above noise, `same_plate` merges `ه/٥` and `و/٦`, and a blank normalises to empty
- [X] T015 Create `engine/vg/infer/plates.py` — one runner holding both models. Copy the YOLO detect path plus `strip_blue_band`, `deskew`, `enhance` from `anpr/detector.py`, and `CHAR_GLYPHS`, `_YoloCharReader`, `_group_by_position`, `_settle_letter_or_digit` from `anpr/ocr.py`. Use `weights_to_load` from T007. **The character model runs only on crops the plate model returned**, mirroring `features/weapons.py`
- [X] T016 Create `engine/vg/features/vehicles.py` — `VehiclesWorker(FeatureWorker[VehiclesResult])` implementing only `analyse(frame)`. Port the weighted voting from `anpr/tracker.py`: vote weight is `ocr_conf × plausibility × plate_width`, readings within one edit **merge** rather than split, and nothing is emitted until 3 frames agree. Timestamps from `frame.captured_at`, never `time.monotonic()`. **Write no concurrency code**
- [X] T017 [P] Create `engine/tests/test_vehicle_voting.py`: three agreeing frames emit one pass, two do not, confusable readings merge their votes, a below-threshold read is emitted flagged rather than dropped, and the same plate inside the dedupe window is one pass not many

### Storage and permissions

- [X] T018 Create `engine/vg/events/vehicles.py` — `VehicleStore` copying the shape of `events/weapons.py::WeaponSceneStore`. Two tables per `data-model.md`: `vehicle` (plate `UNIQUE`, four categories) and `vehicle_pass` (`vehicle_id ... ON DELETE SET NULL`, never CASCADE). Add `EmailTaken`-style `PlateTaken` raised from `sqlite3.IntegrityError`, and `expire(older_than)` copied from `events/weapons.py`
- [X] T019 [P] Add the vehicle wire types to `engine/vg/api/schemas.py` — `VehiclePass`, `RegisteredVehicle`, `VehicleRegistration`, `GateTotals`, `VehicleVisit`, `VehicleImportResult`, `GateSummary`. **`GateSummary` fields are optional ints** so a tile with no number renders a reason, not `0`
- [X] T020 Add `"/vehicles"` to `ADMIN_WRITE_PREFIXES` in `engine/vg/auth/deps.py` — **not** `ADMIN_PREFIXES`; a guard reads the register, an admin writes it

**Checkpoint**: plate reading provable from a still image; `pytest` green; no page yet.

---

## Phase 3: User Story 1 — See what drove in (Priority: P1) 🎯 MVP

**Goal**: A guard opens Vehicle gate and sees the gate camera live with a box round each
plate, plus the last few passes with plate, gate, direction and status.

**Independent Test**: Hold a plate to the webcam. One pass appears within 5 seconds with
the plate rendered right-to-left, boxed in the status colour. With the model absent, the
page says so instead of showing zeros.

### Tests for User Story 1

- [X] T021 [P] [US1] Create `engine/tests/test_vehicles_api.py` with the Live-tab cases: `GET /vehicles/summary` returns `200` with reasons and **no zeros** when nothing is running, `GET /vehicles/passes` returns newest-first, and a bare `LiveStore` gives `200` not `503`
- [X] T022 [P] [US1] Add to `engine/tests/test_no_fixtures.py` an assertion that no vehicle endpoint ever returns the design's placeholder figures (`2140`, `148`, `121`, `27`)

### Implementation for User Story 1

- [X] T023 [US1] Add `vehicles` methods to the `Store` protocol in `engine/vg/api/store.py`: `vehicle_summary`, `vehicle_passes`, `vehicle_cameras`. Leave `MockStore` returning honest emptiness — **do not add vehicle fixtures**
- [X] T024 [US1] Override those three in `LiveStore` (`engine/vg/api/live.py`), reading from `VehicleStore` and `VehiclesWorker`, with `_instant()` for every datetime
- [X] T025 [US1] Add `if feature == "vehicles": return self._plate_boxes(camera_id)` to `LiveStore._boxes` in `engine/vg/api/live.py` — **above the face default**, for the reason the `weapons` branch comment gives. Clamp box fractions to 0..1 before returning
- [X] T026 [US1] Add a `"vehicles"` entry to `LiveStore.capabilities` and a `_vehicles_stage()` copying `_weapons_stage`, both in `engine/vg/api/live.py`, naming the reason when no camera, no model, or no worker
- [X] T027 [US1] Wire `VehiclesWorker` and `VehicleStore` into the lifespan in `engine/vg/api/app.py`, following the `WeaponsWorker` block, and record the failure reason for the capability when either will not start
- [X] T028 [US1] Add `GET /vehicles/summary`, `GET /vehicles/passes`, `GET /vehicles/passes/{id}/snapshot`, `GET /vehicles/cameras` to `_mount()` in `engine/vg/api/app.py` per `contracts/vehicles-api.md`
- [X] T029 [P] [US1] Add the vehicle types and `getVehicleSummary`, `getVehiclePasses`, `getVehicleCameras` to `web/src/types.ts` and `web/src/services/api.ts`
- [X] T030 [P] [US1] Add `plateStatusLabel`, `plateStatusTone`, `directionLabel` to `web/src/services/format.ts` — the engine sends enums, sentences are built here
- [X] T031 [P] [US1] Create `web/src/components/Plate.tsx` — the Egyptian plate chip, RTL, `Noto Sans Arabic`, `مصر · EGYPT` band. Copy the markup from `design/24-8 design/VisionGuard.dc.html`, once
- [X] T032 [US1] Create `web/src/pages/VehicleGate.tsx` with the tab shell and the **Live** tab: six stat tiles, gate camera grid, "Passing now" list. Copy the page shape from `web/src/pages/Weapons.tsx` — `useCapability`, `useAsync`, module-level `NO_X` constants. **Pass `detections={false}` to every `CameraFrame`**
- [X] T033 [US1] Add `path="vehicles"` to `web/src/app/routes.tsx` and a "Vehicle gate — Cars in, cars out" entry to `web/src/components/Sidebar.tsx`

**Checkpoint**: US1 works end to end. `npx tsc -b --force` clean. Ask Mohamed to hold a
plate to the webcam — that is the only check no test can make.

---

## Phase 4: User Story 2 — Keep a register (Priority: P2)

**Goal**: An admin searches, adds, edits and removes vehicles, imports a spreadsheet, and
registers an unknown car straight from its pass.

**Independent Test**: Add a plate, watch the next pass of that car read "Registered" with
no restart. Remove it, watch the next pass read "Not registered" while its old passes stay.

### Tests for User Story 2

- [X] T034 [P] [US2] Create `engine/tests/test_vehicles_store.py`: register CRUD, the four categories rejected outside their set, a duplicate plate raises `PlateTaken`, English and Arabic digits collide on one row, and **removing a vehicle keeps its passes**
- [X] T035 [P] [US2] Add to `engine/tests/test_vehicles_api.py`: a guard (`role="it"`) gets `200` on `GET /vehicles/register` and `403` on `POST`; blacklisting a car does not alter yesterday's pass; an import reports every rejected row with a reason

### Implementation for User Story 2

- [X] T036 [US2] Add register CRUD to `VehicleStore` in `engine/vg/events/vehicles.py` — `add`, `update`, `remove`, `search(q, category)`. Hash-free but same shape as `auth/store.py::create_user`: normalise **outside** the lock, let `UNIQUE` decide the race
- [X] T037 [US2] Add status resolution to `engine/vg/events/vehicles.py`: unknown → blacklist → expired → known, in that order. **Blacklist outranks expiry.** Status is frozen onto the pass at write time and never recomputed
- [X] T038 [P] [US2] Add spreadsheet reading to `engine/vg/events/vehicles.py` — CSV via `csv`, xlsx via `openpyxl`, headings accepted in English and Arabic, every plate through `platetext.normalize`. Return counts plus a reason per rejected row
- [X] T039 [US2] Add `GET /vehicles/register`, `POST /vehicles/register`, `PATCH /vehicles/register/{id}`, `DELETE /vehicles/register/{id}`, `POST /vehicles/import`, `GET /vehicles/template` to `engine/vg/api/app.py`
- [X] T040 [P] [US2] Add the register calls to `web/src/services/api.ts`
- [X] T041 [US2] Add the **Registered vehicles** tab to `web/src/pages/VehicleGate.tsx`: import card, search, category chips, one add/edit form, remove with the confirmation sentence from the design. **An empty register says it is empty and how to fill it** — the design's "2,140 on record" ships nowhere
- [X] T042 [US2] Add a "Register" button to each unregistered row in the Live tab of `web/src/pages/VehicleGate.tsx`, opening the form with the plate pre-filled from the read

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 — Answer who is inside (Priority: P3)

**Goal**: Gate-by-gate totals for today, who is still inside, completed visits, and a
searchable pass log with export.

**Independent Test**: With only an entry camera, "Inside now" lists entries and the page
**states that no exit camera is configured** rather than printing a paired figure.

### Tests for User Story 3

- [X] T043 [P] [US3] Add to `engine/tests/test_vehicles_store.py`: the derived-visit query pairs entry→exit, an unpaired entry reads as still inside, two consecutive entries close the first visit marked **inferred**, and with no exit camera `pairing_available` is false
- [X] T044 [P] [US3] Add to `engine/tests/test_vehicles_api.py`: the export **writes the audit entry before returning the body**, and the pass-log filters narrow correctly

### Implementation for User Story 3

- [X] T045 [US3] Add `gates()`, `inside()`, `visits()` to `engine/vg/events/vehicles.py` using the `LEAD() OVER (PARTITION BY plate ORDER BY at)` window query from `data-model.md`. **No `visits` table** — nothing to open, close, or orphan
- [X] T046 [US3] Add `GET /vehicles/gates`, `GET /vehicles/inside`, `GET /vehicles/visits` and `POST /vehicles/export` to `engine/vg/api/app.py`. Export is a `POST` because a `GET` that writes an audit row is a `GET` that lies about being safe
- [X] T047 [US3] Write the audit entry in the export handler via `self._log(actor, "vehicle.export", ...)` **before** the CSV is built, in `engine/vg/api/live.py`
- [X] T048 [P] [US3] Add the movements calls to `web/src/services/api.ts`
- [X] T049 [US3] Add the **Movements** tab to `web/src/pages/VehicleGate.tsx`: today gate-by-gate, "Inside now", completed visits, pass log with plate/gate/direction/status filters and CSV export. When `pairingAvailable` is false, **say why instead of showing a number**

**Checkpoint**: all three tabs work.

---

## Phase 6: Polish

- [X] T050 [P] Add snapshot expiry to the existing retention sweep so plate images older than `storage.clip_retention_days` are deleted while their pass rows survive — `engine/vg/events/vehicles.py`
- [X] T051 [P] Update `STATUS.md` and `docs/PLAN.md` with what Vehicle gate actually does today
- [X] T052 [P] Replace `half=` with `quantize=` in the three `export_tensorrt()` calls in `engine/vg/infer/{persons,weapons,bags}.py`, finishing the deprecation cleanup started this session
- [X] T053 Run `python -m pytest engine` (count must exceed 874), `cd web; npx tsc -b --force`, and `python -m pyflakes engine/vg engine/tools engine/tests`
- [~] T054 Walk `specs/006-vehicle-gate/quickstart.md` end to end, **empty states first**, and confirm no design placeholder figure appears anywhere in the console — *engine and console both start clean in `-Mock`, all 14 contract endpoints are mounted and refuse an anonymous caller, and no placeholder figure exists anywhere in the vehicle source. The on-screen walk needs a signed-in browser and is **Mohamed's**.*

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001–T006)**: no dependencies
- **Foundational (T007–T020)**: needs Setup — **blocks all three stories**
- **US1 (T021–T033)**: needs Foundational
- **US2 (T034–T042)**: needs Foundational; T042 touches the US1 page, so land US1 first
- **US3 (T043–T049)**: needs Foundational; reads passes US1 already writes
- **Polish (T050–T054)**: after the stories you intend to ship

### Within Foundational

Two independent tracks that can run side by side:

- **Acceleration**: T007 → T008/T010 → T011 → T009 → T012
- **Plate reading**: T013 → T014, then T015 → T016 → T017
- **Storage**: T018, T019, T020 are independent of both

### Parallel Opportunities

- **Setup**: T002, T003, T006 together
- **Foundational**: the three tracks above run concurrently; T008, T010, T013, T014, T017, T019 are all `[P]`
- **US1**: T029, T030, T031 together — three separate front-end files
- **US2**: T034, T035 together; T038 and T040 are independent
- **US3**: T043, T044 together; T048 independent
- **Polish**: T050, T051, T052 together

---

## Parallel Example: Foundational

```bash
# Three tracks, no shared files:
Task: "Add weights_to_load() to engine/vg/infer/shared.py"          # T007
Task: "Create engine/vg/platetext.py"                                # T013
Task: "Create engine/vg/events/vehicles.py"                          # T018
```

## Parallel Example: User Story 1 front end

```bash
Task: "Add vehicle types and calls to web/src/types.ts + services/api.ts"   # T029
Task: "Add plate label helpers to web/src/services/format.ts"              # T030
Task: "Create web/src/components/Plate.tsx"                                # T031
```

---

## Implementation Strategy

### MVP — stop after US1

1. Phase 1 Setup (6 tasks)
2. Phase 2 Foundational (14 tasks)
3. Phase 3 US1 (13 tasks)
4. **STOP.** Hold a plate to the webcam. That is a working product: cars are read,
   photographed and logged, and everything unknown says so.

33 tasks to a demo.

### Incremental delivery

- **+US2 (9 tasks)** — the register becomes fillable, so passes get names
- **+US3 (7 tasks)** — "is that car still inside?" gets an answer
- **+Polish (5 tasks)** — retention, docs, final verification

### If you want it smaller still

Foundational's acceleration track (T007–T012) can be **deferred entirely**. P6-FR-033
already says a missing engine means `.pt` on CUDA, working, with System Health saying
so. Dropping it removes 6 tasks and costs about 6 ms per plate frame. It is in Phase 2
because the repo's acceleration path was found cold and half-fixing it is how it went
cold the first time — not because Vehicles needs it.

---

## Notes

- `[P]` = different files, no dependencies
- **Read [context.md](./context.md) before opening any source file.** Twelve traps are
  listed there, including the `_boxes` face default, `CameraFrame` leaking names, mixed
  line endings, and closing a store before its tempdir on Windows
- Every task's file path is exact; anchors drift, so search for the symbol
- Commit after each task or logical group; a fix and its regression test ship together
- Nothing in the design file's sample data ships — see the placeholder list in T022

---

## Phase 7: The photograph (found missing, 24 Aug 2026)

**P6-FR-003 requires a photograph of the frame and a crop of the plate on every
pass, and P6-FR-026 requires both to be deleted at thirty days with the row kept.**
Neither was built: `record_pass` was being called with `snapshot=None`, so
`hasSnapshot` was always false, `GET /vehicles/passes/{id}/snapshot` always 404'd,
and the page's "every car that passes is photographed" was untrue. Found while
wiring T050, which had nothing to expire.

- [X] T055 Add `gate_images_dir` to `StorageConfig` in `engine/vg/config.py` — `clips_dir / "gate"`, the boundary the retention sweep works inside
- [X] T056 Keep the clearest frame per car in `engine/vg/features/vehicles.py` — `_Track.best_image` / `best_box`, updated when a read beats the best confidence so far, handed to the event layer on `VehiclePassRead`. **No disk access in this file**, which is what keeps it testable without one
- [X] T057 Add `save_pass_images()` to `engine/vg/events/vehicles.py` — encodes with `cv2.imencode` and writes with `Path.write_bytes`, **never `cv2.imwrite`**: OpenCV writes through the platform's narrow filename API and silently returns False for a path it cannot encode, so an Arabic plate on Windows produced no picture and no error. Returns `(None, None)` on any failure — a picture that cannot be written must never cost the pass
- [X] T058 Call it from the pass callback in `engine/vg/api/app.py`, and sweep expired images hourly from the same callback so a machine nobody opens the console on still keeps the thirty-day promise
- [X] T059 [P] Tests in `engine/tests/test_vehicles_store.py` and `engine/tests/test_vehicles_api.py`: both files are written, the filename is ASCII whatever the plate is, a failed write costs the picture and not the pass, expiry deletes the crop as well as the photograph and keeps the row, and an aged-out photograph is a 404 that says "retention" while the pass still lists

---

## Phase 8: The reader was fed the wrong picture (24 Aug 2026)

**Reported:** plates read close to right but wrong, on weights that read the same
plates correctly in the project they came from. It started when the feature was
wired into the system, not before.

**Cause:** `PlateReader.read_frame` handed the character model
`enhance(strip_band(crop))`. Neither belongs there. In gate-anpr the character
reader is marked `wants_full_plate = True`, so it gets the **raw colour crop**, and
`enhance()` is only ever used by the easyocr backend. Stripping the band costs
whole characters on a faded plate — the source project measured two lost reads in
six — and `enhance()` returns a single-channel CLAHE'd, sharpened image, so weights
trained on colour crops were reading greyscale ones.

- [X] T060 Pass `box.crop(frame)` straight to `read_plate` in `engine/vg/infer/plates.py`, with the reason at the call site. `strip_band`, `deskew` and `enhance` stay in the module — they are correct for the reader they were written for — but nothing in the plate path may call them
- [X] T061 [P] Pin it in `engine/tests/test_platetext.py`: the crop reaching the character model is byte-for-byte `box.crop(frame)`, still three-channel, with no rows trimmed off the top, and `read_frame` names neither helper in its code
- [ ] T062 **Mohamed:** hold a plate to the webcam on `.\dev.ps1 up` and confirm the reading is right. Only a real plate can close this

**Still different from standalone, and deliberately left:** both plate models run
FP16 here (`half: true` → `quantize=16`); gate-anpr ran FP32. If the reads are still
off after T062, that is the next thing to change — `half: false` on `plates` and
`plate_chars` in `engine/engine.yaml`, costing a few ms per frame.

---

## Phase 9: Delete a pass (24 Aug 2026, asked for)

A read that is plainly nonsense — a reflection, half a lorry, a plate belonging to
nobody — can be removed from the log. Permanent, administrator only, audited first.

- [X] T063 Add `delete_pass(pass_id)` to `engine/vg/events/vehicles.py` — unlink both images, then delete the row. **No soft-delete flag**: visits and "inside now" are a window query over this table, so a hidden row would need every query to remember to exclude it, and the one that forgets is the bug
- [X] T064 Add `delete_pass(pass_id, actor)` to `LiveStore`, the `Store` protocol and `MockStore`, writing `self._log(actor, "vehicle.pass.delete", plate, ...)` **before** the row goes — the audit outlives the pass and cannot itself be deleted
- [X] T065 Add `DELETE /vehicles/passes/{pass_id}` to `engine/vg/api/app.py`. Admin-only by the existing path rule; `404` when there is no such pass
- [X] T066 [P] `engine/tests/test_vehicles_api.py`: an admin deletes, a guard gets 403, the audit entry names the plate and survives the row, both images go, the pass stops answering "inside now", a second delete is 404, and the register entry and the other passes are untouched
- [X] T067 [P] Create `web/src/components/DeletePass.tsx` — two-step confirm, state local to the button so a refreshing list cannot arm the wrong row — and use it in both the Live tab and the pass log, plus `deleteVehiclePass` in `web/src/services/api.ts`

---

## Phase 10: Why the second car never appeared (24 Aug 2026)

**Reported:** the first read is perfect, then it refuses, even with the same
plate in the same place. Plus a stream of `422` on the overlay poll.

Three separate defects, and they compounded:

- [X] T068 **The overlay was refused at the door.** `GET /cameras/{id}/detections?feature=vehicles` validated against a hand-written regex that predates this feature, so **no gate tile has ever drawn a plate box**. The pattern is now built from `S.OVERLAY_FEATURES` in `engine/vg/api/schemas.py` — one list, in one place
- [X] T069 [P] Pin it in `engine/tests/test_api.py`: every name in `S.OVERLAY_FEATURES` is accepted, something invented is still refused, and **every dispatch literal in `LiveStore._boxes` is a listed feature** — read out of `_boxes` itself, so the next feature cannot repeat this
- [X] T070 **Plate reading never sped up while somebody watched.** Recognition, tracking and weapons all call `note_interest()` from that handler; vehicles did not. The webcam is `fps: 5` and a pass needs 3 agreeing frames, so a plate held up for a second got five looks. Now boosts to 12 Hz like the others
- [X] T071 **The repeat window was compiled in.** P6-FR-006 says *configured*; `DEDUPE_SECONDS = 60.0` was a module constant. Added `VehiclesConfig` to `engine/vg/config.py` and a `vehicles:` block to `engine.yaml`. 60 is right at a barrier and wrong on a desk — the file says so, and says to use 3 while testing
- [X] T072 [P] `engine/tests/test_vehicle_voting.py`: the default still swallows a repeat, a configured short window lets it through, `0` records every settled read, and **no setting splits a car that never left view**
- [X] T073 `getattr` for `app.state.recogniser` in the detections handler, like its three siblings. A bare attribute read turned "the engine has not finished starting" into a 500 — degradation answered with a 5xx

**Recovered, not lost:** `git checkout` on `engine/vg/api/schemas.py` during T069 discarded that file's uncommitted work — the seven vehicle wire types and `RegisterRequest`. Rebuilt from `web/src/services/wire.ts`, the `LiveStore` mappers and endpoint usage, and verified by the suite rather than by memory: `extra="forbid"` means a wrong field name fails loudly, and every field crosses the wire in `test_vehicles_api.py`. Two docstrings are rewrites rather than the originals.
