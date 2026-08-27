---

description: "Task list for Vehicle Gate Accuracy & Redesign"
---

# Tasks: Vehicle Gate Accuracy & Redesign

**Input**: Design documents from `/specs/007-vehicle-gate-tuning/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [context.md](./context.md)

**Tests**: Included and **not optional here** — the constitution requires test-first for business rules and regression fixes, and `AGENTS.md` requires every fix to a known bug to ship with its regression test *in the same commit*. P6-FR-042 names a regression test explicitly.

**Read [context.md](./context.md) before opening any source file.** It carries the anchors, the traps, and the baseline.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5, mapping to the phases below
- Exact file paths in every description

---

## Phase 1: Setup

**Purpose**: Protect the uncommitted work and confirm the dataset is what the plan assumes.

- [X] T001 Put the uncommitted vehicle-gate work on a branch and commit it before editing anything — `git status` shows ~95 modified/untracked entries and `git show HEAD:engine/vg/api/live.py` has no `_plate_boxes`, so the entire vehicle-gate engine exists only in the working tree. Exclude the stray root litter named in `STATUS.md` housekeeping (`$OUT`, `$TMP_LOG`, `.=.swp`, bare numeric files) from the commit.
- [X] T002 [P] Add `Egyptian Car Plates dataset/` to `.gitignore` (2,085 JPEGs, owner-supplied, not repo content) but **not** `Egyptian Car Plates dataset/plate_truth.csv` — the confirmed-truth file is evidence and must be versioned. Create `specs/007-vehicle-gate-tuning/evidence/.gitkeep`.
- [X] T003 [P] Verify the dataset pairing in a throwaway check: `Vehicles/*.jpg|JPG|jpeg` (2,085 images) against `Vehicles Labeling/<stem>.txt` (2,088 labels) — record the unmatched stems in `specs/007-vehicle-gate-tuning/evidence/dataset-inventory.md`, including that label folders are spelled `EALPR Vechicles dataset` and `Vehicles Labeling` (sic) and that every path needs quoting for the spaces.

**Checkpoint**: work is safe, dataset shape is known and written down.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared-file edits every story would otherwise fight over — one `schemas.py`, one `wire.ts`, one SQL `SCHEMA` string.

**⚠️ CRITICAL**: No user story work begins until this phase completes. These tasks touch files that several stories edit; running them once up front is what keeps the stories parallel afterwards.

- [X] T004 Add the new wire types to `engine/vg/api/schemas.py` beside the existing vehicle cluster (search `class VehiclePass`): `ReaderAttempt`, `GateReaderCamera`, `GateReaderNow`, `GateAlert`, `TrafficHour` — field-for-field per [data-model.md](./data-model.md) §"Wire types". Subclass `Wire` (snake_case in, camelCase out, `extra="forbid"`); use `Instant` for times and `Confidence` for 0..1 values.
- [X] T005 Extend the two changed wire types in `engine/vg/api/schemas.py`: `GateSummary` gains `cameras_reading`, `cameras_total`, `cameras_note` (all optional — absent is an admission, per its own docstring); `VehicleVisit` gains `entry_pass_id`, `exit_pass_id`, `entry_has_snapshot`, `exit_has_snapshot`. Keep `needs_review` on `GateSummary` — the export still uses it even though no tile renders it. (Same file as T004 — sequential, not parallel.)
- [X] T006 [P] Mirror all new and changed wire types in `web/src/services/wire.ts` in camelCase, matching the engine field-for-field.
- [X] T007 [P] Append the two new tables to the `SCHEMA` string in `engine/vg/events/vehicles.py` (search for the existing `CREATE TABLE IF NOT EXISTS vehicle_pass`): `vehicle_alert_ack` and `vehicle_import_run`, columns exactly per [data-model.md](./data-model.md) §"Database". `CREATE TABLE IF NOT EXISTS` so existing databases migrate on open.

**Checkpoint**: shared contracts exist; US1–US5 can now proceed in parallel.

---

## Phase 3: User Story 1 — Prove how accurate the reader is, and fix it (Priority: P1) 🎯 THE OWNER'S FIRST PRIORITY

**Goal**: Replace "it keeps catching wrong car numbers, reason unknown" with a measured number, a named cause, and a fix that carries its own before/after evidence.

**Independent Test**: `python engine/tools/eval_plates.py --dataset "…" --configs …` runs to completion, prints per-config detection and read scores, writes a dated evidence file, and gives identical numbers on a second run. No console or UI involvement whatsoever.

**⚠️ Read [research.md](./research.md) §1 and §3 first.** The plan changed during task generation: the FP16 / TensorRT / NMS suspects are **already eliminated** in the working tree (`engine.yaml`'s `plates` and `plate_chars` carry `half: false`, `accelerate: false`, `iou: 0.7`, and `app.py` verifiably passes all four to `PlateReader`). The highest-value comparison is now `theirs` vs `ours-fp32` — is our port faithful — not which precision.

### Tests for User Story 1

- [ ] T008 [P] [US1] Write `engine/tests/test_eval_plates.py` covering the pure parts before the tool exists: YOLO label parsing (`0 cx cy w h`, normalised → pixel box), the IoU-≥0.5 found/not-found rule, exact-read comparison against canonical text via `vg.platetext.normalize`, and the ≥100 px width split. No model, no GPU, milliseconds.

### Implementation for User Story 1

- [ ] T009 [US1] Create `engine/tools/eval_plates.py` with the dataset walk and detection scoring: read `Vehicles/` + `Vehicles Labeling/`, run the plate detector over each image, report recall/precision at IoU 0.5 and the distribution of plate widths in pixels. Reuse the reader construction from `engine/tools/compare_plates.py` — do not write new inference code.
- [ ] T010 [US1] Add the four-config matrix to `engine/tools/eval_plates.py` (`--configs theirs,fp32,fp16,trt`), reusing `compare_plates.py`'s pipeline isolation and the `VG_NO_TENSORRT=1` lever. Each config reports separately in one run so the pairs can be read top to bottom.
- [ ] T011 [US1] Add assisted labelling (`--label`) to `engine/tools/eval_plates.py`: crop each labelled plate, show it with the current reader's proposed text, take confirm/correct/skip from the operator, and append confirmed rows to `Egyptian Car Plates dataset/plate_truth.csv` (columns per [data-model.md](./data-model.md)). Resumable — re-running skips images already in the CSV. A proposal is never truth until confirmed.
- [ ] T012 [US1] Add read scoring (`--truth`) to `engine/tools/eval_plates.py`: exact-read rate per config, overall and for plates ≥100 px wide, plus a per-plate failure list. Write a dated file to `specs/007-vehicle-gate-tuning/evidence/eval-<date>-<config>.md` including the honesty note that this dataset is the models' own training set — a score here is pipeline fidelity, not site generalisation.
- [ ] T013 [US1] Run the detection baseline across all four configs and commit the evidence file. This needs no owner input and establishes whether the plate *detector* is the problem before any text question is asked.
- [ ] T014 [US1] **BLOCKED ON THE OWNER** — labelling session with Mohamed via `--label` until ≥150 confirmed plates ≥100 px wide exist in `plate_truth.csv`. Nothing downstream of this can produce the 95% verdict. Ask for it explicitly and report the feature as partially blocked rather than inventing truth.
- [ ] T015 [US1] Run the read matrix against `plate_truth.csv`, commit the evidence, and write the verdict paragraph: which config wins, and which pair first disagrees. Apply [research.md](./research.md) §3's ladder rungs 1–3 to name the cause.
- [ ] T016 [US1] Act on the verdict. If `theirs` beats `ours-fp32`, diff `engine/vg/infer/plates.py` against `models/Gate/gate-anpr/gate-anpr/anpr/ocr.py` stage by stage on the failing crops (grouping, `settle_letter_or_digit`, `read_order`, normalisation) and fix the divergence — with a before/after measurement and a regression test in `engine/tests/test_platetext.py` or `engine/tests/test_vehicle_voting.py` as the divergence dictates. If the configs tie and the target is met, record "configuration settled" and change nothing.
- [ ] T017 [US1] Correct the stale accuracy claims in `STATUS.md` — the Vehicle gate row still says "Both plate models still run FP16 where the source project ran FP32", which describes the committed tree, not the working one. Replace with what the evidence now shows, and never state an accuracy figure that is not in `evidence/` (P6-FR-041).
- [ ] T018 [US1] **Only if the ladder reaches rung 4** — add an FP32 option to `engine/tools/build_engines.py`. `build(name, weights, imgsz, half, force)` already carries precision through to its report and `spec.half` already gates per model, so this is a CLI flag plus plumbing, not new machinery. Skip entirely if rungs 1–3 settle the question.

**Checkpoint**: the reader's accuracy is a number with evidence behind it, the cause of wrong reads is named, and the fix (if any) ships with its measurement.

---

## Phase 4: User Story 2 — Watch the reader work, live (Priority: P1)

**Goal**: The plate box that has never once drawn appears around a plate while the car is in view, with its width readout; and a table underneath shows every read attempt, so a person can see whether the camera is placed wrong, the reader is failing, or nothing is reading.

**Independent Test**: `pytest engine/tests/test_vehicle_overlay.py` proves a stub `PlateRead` survives the whole path to a wire-valid box. Live: `.\dev.ps1 up -Clip`, open Vehicle gate from `/`, hold a plate to the webcam — box, width, and the votes column climbing to 3/3.

**Root cause, already confirmed** ([research.md](./research.md) §5): `_plate_boxes()` builds `S.Box(kind="plate", …)` and `Box.kind` is `Literal["person","weapon","object","face","match"]` — pydantic raises, so the detections response fails whenever a plate is in view. The console half is already correct (`boxColor()` has the plate branch, `types.ts` types `kind` as `string`). The 24 Aug fix pinned the request side only; nothing tested the response side.

### Tests for User Story 2

- [ ] T019 [US2] Write `engine/tests/test_vehicle_overlay.py` **first and watch it fail**: build a `LiveStore` with a stub vehicles worker whose `plates_on()` returns one `PlateRead`, call `camera_view(camera_id, feature="vehicles")`, and assert the box survives wire validation with `kind == "plate"`, the right `severity` for each register status (registered → info, unknown/expired → warn, blacklisted → critical), fractional geometry inside 0..1, and `plate_width_px` set. This is the P6-FR-042 full-path regression test — it must fail before T020 and pass after.

### Implementation for User Story 2

- [ ] T020 [US2] Fix the bug in `engine/vg/api/schemas.py`: add `"plate"` to the `Box.kind` literal and add `plate_width_px: int | None = None`. **Commit this together with T019** — `AGENTS.md` requires the regression test in the same commit as the fix.
- [ ] T021 [US2] Pass the width through in `engine/vg/api/live.py::_plate_boxes` — `plate_width_px=read.box.w`, which is already source-frame pixels. Everything else in that method is already correct.
- [ ] T022 [P] [US2] Add `plateWidthPx?: number` to the `Box` mirror in `web/src/types.ts` (`kind` is already `string`, so no change there).
- [ ] T023 [P] [US2] Add a plate-width tone helper to `web/src/services/format.ts` — green at ≥100 px, amber below — beside the existing `boxColor`. `format.ts` owns every rendered string and colour decision.
- [ ] T024 [US2] Render the width readout beside plate-kind boxes in `web/src/components/CameraFrame.tsx`, using the size constants already there (`labelFont`, `labelTop`, `labelPad`) so it sits correctly at both tile and enlarged scale.
- [ ] T025 [US2] Add the attempts feed to `engine/vg/features/vehicles.py::analyse`: a per-camera `deque(maxlen=12)` taking one entry per `PlateRead` (time from `frame.captured_at` — never `time.monotonic()`), with the matched track's current `leader` and vote count; plus a rolling per-read milliseconds figure timed around `reader.read_frame`. Add `attempts_on(camera_id)` and `read_ms(camera_id)` accessors shaped like the existing `plates_on` — **including its staleness rule**, which returns empty when the result has aged out.
- [ ] T026 [US2] Extend `engine/tests/test_vehicle_voting.py` with attempts-feed cases: one attempt appended per read including reads that produced no text, the deque bound holds at 12, the leader and vote count travel with each attempt, and timestamps come from the frame.
- [ ] T027 [US2] Implement `vehicle_reader()` in `engine/vg/api/live.py`: assemble `GateReaderNow` from the worker's attempts plus one `GateReaderCamera` per configured gate camera. Camera name/gate/direction come from `CameraConfig` (`name`, `gate`, `direction` — verified present); `finder`/`reader`/`form` come from the loaded `PlateReader` (`plates_loaded.name`, `chars_loaded.name`, `.form`). Reuse `_vehicles_state()` for `reason` so the wording matches the summary, and `_instant(when, clock)` for every time.
- [ ] T028 [US2] Add the `MockStore.vehicle_reader()` counterpart in `engine/vg/api/store.py` — without it `.\dev.ps1 up -Mock` 503s the whole page before any UI exists.
- [ ] T029 [US2] Add `GET /vehicles/reader` to `engine/vg/api/app.py` beside the other `/vehicles` endpoints, returning `S.GateReaderNow`. Call `note_interest()` for the cameras it reports so watching the card boosts the worker exactly as watching a tile does — without it the first poll is empty and stays empty on an idle camera.
- [ ] T030 [P] [US2] Add `getVehicleReader()` to `web/src/services/api.ts`, following the existing vehicle-cluster fetch idiom.
- [ ] T031 [US2] Create `web/src/components/VehicleReader.tsx` — "What the reader is seeing now" per the 27 Aug drawing: the seven columns (time, what it read, confidence, plausibility, width, leading candidate, votes), `read nothing` in words for an empty read, width toned by T023, the per-camera model line from `GateReaderCamera` (real loaded weights and form — **not** the drawing's sample "reader easyocr"), and the closing explanatory paragraph. Poll at 2 s with `useAsync`. Render `reason` instead of the table when nothing is reading.
- [ ] T032 [US2] Mount `VehicleReader` on the Live tab in `web/src/pages/VehicleGate.tsx`, below the camera grid, and add the aiming-aid explanation to the `CamGrid` note per the drawing. Leave `feature="vehicles"` and `tileOverlay` exactly as they are — the existing comment explains why `detections={false}` would be the wrong tool.
- [ ] T033 [US2] Add `/vehicles/reader` cases to `engine/tests/test_vehicles_api.py`: 200 with the honest `reason` when nothing is reading (never a 5xx — degradation is payload), attempts shape, and that a guard may read it.

**Checkpoint**: the boxes draw, the reader is observable, and US1's fix can be seen working rather than only measured.

---

## Phase 5: User Story 3 — Alerts that wait for a person, and the Live tab as drawn (Priority: P2)

**Goal**: The three alert kinds sit at the top of the Live tab with the action that resolves each, dismissals are recorded under the operator's name, and the Live tab matches the 27 Aug drawing — which means the per-pass list goes.

**Independent Test**: With a recorded unknown/blacklisted/expired pass in the database, `GET /vehicles/alerts` returns it; dismissing writes an audit entry *before* the ack row; a guard may dismiss but still may not edit the register; the same car re-alerts on its next pass.

**Owner decision, costs accepted (spec P6-FR-052)**: the pass list leaves the console entirely. Recording is untouched and the API stays — removing UI is not removing API.

### Tests for User Story 3

- [ ] T034 [P] [US3] Write `engine/tests/test_vehicle_alerts.py` first: alerts derive from today's qualifying passes only, a dismissed pass disappears, a *new* pass of the same car raises a fresh alert, the audit entry is written before the ack row, a second dismiss of the same pass is refused, and near-match appears only when exactly one register plate is within one edit (zero or two → no suggestion).
- [ ] T035 [P] [US3] Add the permission cases to `engine/tests/test_authorisation.py` beside the existing `/vehicles` ones: a guard **can** `POST /vehicles/alerts/{id}/dismiss`, and a guard **still cannot** write the register — the carve-out must not widen.

### Implementation for User Story 3

- [ ] T036 [US3] Add the store methods to `engine/vg/events/vehicles.py`: `alert_acks()`, `add_alert_ack(pass_id, by, action_taken)`, and `near_matches(plate)` (select register plates, compare in Python with `platetext.same_plate` — ~2k rows, no index gymnastics). Follow the existing `with self._lock` read/write idiom in that class.
- [ ] T037 [US3] Add the carve-out to `engine/vg/auth/deps.py`: `OPERATOR_WRITE_PREFIXES = ("/vehicles/alerts",)`, checked inside `requires_admin` **before** the `ADMIN_WRITE_PREFIXES` rule so the narrower prefix wins. Permissions stay decided by path — never a decorator.
- [ ] T038 [US3] Implement `vehicle_alerts()` and `dismiss_alert(pass_id, actor, action_taken)` in `engine/vg/api/live.py`. Assemble `GateAlert` from today's passes whose `status_for` is `unknown`/`blacklist`/`expired` and which have no ack; attach near-match only for `unknown`. `dismiss_alert` writes `self._log(actor, "vehicle.alert.dismiss", plate, …)` **before** the ack row — copy the ordering from `delete_pass_record`.
- [ ] T039 [US3] Add `MockStore.vehicle_alerts()` and `dismiss_alert()` to `engine/vg/api/store.py`.
- [ ] T040 [US3] Add `GET /vehicles/alerts` and `POST /vehicles/alerts/{pass_id}/dismiss` to `engine/vg/api/app.py` — the POST takes `auth_deps.CurrentUser` so the audit entry names a real account; 404 unknown pass, 409 already dismissed.
- [ ] T041 [US3] Compute the cameras-reading figures in `engine/vg/api/live.py::vehicle_summary`: `cameras_reading`, `cameras_total`, and `cameras_note` naming the camera not being read and why (offline, or the worker down). All three absent when plate reading is not running — `reason` already carries that case.
- [ ] T042 [P] [US3] Add `getVehicleAlerts()` and `dismissVehicleAlert(passId, actionTaken)` to `web/src/services/api.ts`.
- [ ] T043 [P] [US3] Build the alert sentences in `web/src/services/format.ts` from the `GateAlert` fields — the engine sends facts, `format.ts` writes English. Blacklist wording must say nothing was stopped (there is no barrier to close); near-match must read as a question, never a statement.
- [ ] T044 [US3] Create `web/src/components/VehicleAlerts.tsx` per the drawing: one row per alert, coloured by kind, with the resolving action (`Add to the register` / `Renew the permit`) where one exists and **no action button on blacklist** — giving it one would pretend the software can act. Dismiss on every row. Actions gated on `isAdmin`; dismiss is not.
- [ ] T045 [US3] Rework the Live tab in `web/src/pages/VehicleGate.tsx`: mount `VehicleAlerts` at the top; **remove the "Passing now" card, its `getVehiclePasses` poll, and the `DeletePass` import**; swap the "Needs review" tile for "Cameras reading X of Y"; keep the `Tile` component, the reason card and `CamGrid` untouched. Route the alert's register action through the existing `prefill` ref into the register tab.
- [ ] T046 [US3] Add the alert endpoints to `engine/tests/test_vehicles_api.py` — 200-with-reason when nothing is running, and the dismiss round trip.

**Checkpoint**: the Live tab matches the drawing, alerts wait for a person, and every dismissal is traceable to an account.

---

## Phase 6: User Story 4 — Movements that answer "what happened on that day" (Priority: P2)

**Goal**: A day picker, an hourly traffic chart, gate-by-gate totals with honesty notes, and visit rows carrying the photograph that proves them.

**Independent Test**: With passes recorded on two different days, picking each day changes the chart, the gate table and the visit lists; "Export this day" returns exactly that day and writes its audit entry first; with no exit camera the paired sections say why instead of rendering empty tables.

### Tests for User Story 4

- [ ] T047 [P] [US4] Add store cases to `engine/tests/test_vehicles_store.py`: `until` bounds exclude the next day's passes, `hourly()` groups entries and exits by hour and omits hours with no data, and the visits query returns the entry/exit pass ids it walked.

### Implementation for User Story 4

- [ ] T048 [US4] Add `until` bounds to the query methods in `engine/vg/events/vehicles.py` (`passes`, `counts_since`, `visits`, `gates`) following the existing clause-list-plus-params pattern, and add `hourly(since, until)` as one `GROUP BY` over `vehicle_pass.at` counting entries and exits separately.
- [ ] T049 [US4] Select the entry and exit pass ids (and whether each has a snapshot on disk) through the derived-visits window query in `engine/vg/events/vehicles.py` into the `Visit` dataclass — the query already walks those rows.
- [ ] T050 [US4] Thread the day through `engine/vg/api/live.py`: `vehicle_gates(day)`, `vehicle_visits(day)`, `vehicle_traffic(day)`, and the export. **`vehicles_inside()` takes no day** — "inside now" is only ever now. Map the new visit fields onto the wire in `_to_wire_visit`.
- [ ] T051 [US4] Add the `MockStore` counterparts in `engine/vg/api/store.py`, including `vehicle_traffic()` and `day` parameters on the existing methods.
- [ ] T052 [US4] Add `day` (ISO date, optional, empty = today, 422 on malformed) to `GET /vehicles/gates`, `GET /vehicles/visits` and `POST /vehicles/export` in `engine/vg/api/app.py`, and add `GET /vehicles/traffic?day=`. The export keeps writing its audit entry before the file is built.
- [ ] T053 [P] [US4] Add `getVehicleTraffic(day)` and the `day` parameters to `web/src/services/api.ts`.
- [ ] T054 [US4] Rebuild `web/src/components/VehicleMovements.tsx` per the drawing: the filter bar (day picker, plate-or-owner search, gate select, Search, Export this day), the hourly in/out chart as flex columns with in above the line and out below, gate-by-gate with an all-gates total row and per-gate honesty notes, and the scope line stating that search and gate filter scope the visit tables while the chart and totals stay on the whole day. Keep the existing `VisitRow` and `length()` helpers where they still fit.
- [ ] T055 [US4] Add snapshot thumbnails to the Inside-now and Completed-visit rows, linking `/vehicles/passes/{entryPassId}/snapshot` when `entryHasSnapshot` — clicking opens the full photograph. A pass whose image has aged out at 30 days shows no thumbnail rather than a broken one; the pass row itself stays.
- [ ] T056 [US4] Add the day-scoping cases to `engine/tests/test_vehicles_api.py`: a past day returns that day, a malformed day 422s, `/vehicles/inside` ignores any day given, and `/vehicles/traffic` returns 200 with an empty list on a quiet day.

**Checkpoint**: any recorded day is reachable and every visit row can show its evidence.

---

## Phase 7: User Story 5 — A Registered-vehicles tab that states only facts (Priority: P3)

**Goal**: The Latin transliteration under each plate, and a "last import" line that is a real import or is absent.

**Independent Test**: On a fresh database the import card shows no last-import line; after importing the template through the UI it shows that run's real numbers and date.

### Tests for User Story 5

- [ ] T057 [P] [US5] Add cases to `engine/tests/test_vehicles_store.py`: an import writes exactly one `vehicle_import_run` row inside the same transaction with the numbers the importer reported, and `last_import_run()` returns None on a fresh database.

### Implementation for User Story 5

- [ ] T058 [US5] Record the run in `engine/vg/events/vehicles.py::import_rows` — insert the `vehicle_import_run` row inside the existing transaction — and add `last_import_run()`.
- [ ] T059 [US5] Surface the last import through `engine/vg/api/live.py` and `engine/vg/api/store.py` onto the register response, absent when no import has ever run.
- [ ] T060 [P] [US5] Add `plateLatin(display)` to `web/src/services/format.ts`, with a comment naming `vg/platetext.py::TRANSLIT` as the source of truth to keep it in step. Do **not** add a per-type wire field for it — `format.ts` owns rendered strings.
- [ ] T061 [US5] Add the optional Latin sub-line to `web/src/components/Plate.tsx` behind a prop, so only the register rows show it and the compact row plates stay as they are.
- [ ] T062 [US5] Show the real last-import line in `web/src/components/VehicleRegister.tsx` (or nothing when there is none), turn on the Latin sub-line for its rows, and delete any remaining sample figures from the tab.

**Checkpoint**: nothing on the register tab is invented.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T063 Sweep the whole page for invented numbers against P6-FR-054 and SC-006: every new tile, chart, table and line either carries a measured figure or is absent with a reason. Confirm the two deliberate deviations from the drawing are in place — no "14 fps" on tiles, real model names instead of "reader easyocr" ([research.md](./research.md) §10).
- [ ] T064 [P] Update `STATUS.md`'s Vehicle gate row: boxes now draw (with the regression test that proves it), what the accuracy evidence says, and what remains unmeasured on site plates.
- [ ] T065 [P] Update the Vehicle gate section of `docs/PLAN.md` to match what now exists, and note the pass list's removal with the owner's decision date.
- [ ] T066 Run all four gates and fix what this feature broke: `python -m pytest engine` (baseline 1120 passed / 11 skipped / 3 pre-existing failures in `tests/test_track_page.py` — the count must rise, and those three must not grow), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`, and `.\dev.ps1 up -Clip`.
- [ ] T067 Work through [quickstart.md](./quickstart.md) end to end, including `-Mock` mode for every new endpoint.
- [ ] T068 **Ask Mohamed for the manual checks only he can do**: hold a real plate at the webcam and confirm the box, the width readout and the votes climbing; confirm a real plate now reads correctly; and confirm the redesigned page reads the way he drew it. Report honestly which parts remain unmeasured on site footage.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)** → no dependencies, start immediately.
- **Foundational (Phase 2)** → needs Setup. **Blocks every user story**, because it owns the shared-file edits.
- **US1 (Phase 3)** → needs Foundational only in principle; in practice it touches no shared file at all and could start during Setup. It contains the one owner-blocked task (T014).
- **US2 (Phase 4)** → needs Foundational (T004–T006).
- **US3 (Phase 5)** → needs Foundational (T004, T005, T007). Independent of US2, though both edit `VehicleGate.tsx` (T032 and T045) — sequence those two.
- **US4 (Phase 6)** → needs Foundational (T004, T005). Fully independent of US2 and US3.
- **US5 (Phase 7)** → needs Foundational (T004, T007). Fully independent.
- **Polish (Phase 8)** → needs every story that is being shipped.

### Story independence

US1 is pure offline measurement — no console, no API. US2, US3, US4 and US5 touch different components and different endpoints. The only cross-story file contentions are `VehicleGate.tsx` (US2 T032, US3 T045), `api.ts`, `format.ts` and `store.py`, each of which several stories append to — append-only edits in different regions, so they merge cleanly if not run literally simultaneously.

### Within each story

Tests first and failing (T008, T019, T034, T035, T047, T057) → store/worker → LiveStore → MockStore → endpoint → `api.ts` → component → page. Never skip the MockStore step: `-Mock` mode is the UI loop and a missing mock 503s the page.

### Parallel opportunities

- Setup: T002 and T003 together.
- Foundational: T006 and T007 together, after T004 → T005 (same file, sequential).
- Across stories: once Phase 2 is done, US1, US2, US3, US4 and US5 can run on five tracks.
- Within stories: every `[P]` task — notably T022/T023 (US2), T034/T035 (US3), T042/T043 (US3), T053 (US4), T060 (US5).

---

## Parallel Example: after Foundational

```bash
# Five independent tracks:
Track A (US1): T008 → T009 → T010 → T011 → T012 → T013 → [owner] T014 → T015 → T016
Track B (US2): T019 → T020 → T021 → {T022, T023} → T024 → T025 → …
Track C (US3): {T034, T035} → T036 → T037 → T038 → …
Track D (US4): T047 → T048 → T049 → T050 → …
Track E (US5): T057 → T058 → T059 → {T060} → T061 → T062
```

---

## Implementation Strategy

### Recommended MVP: US1 + US2 together

The owner named accuracy his first priority, so **US1 leads**. But US2 is a one-word schema fix plus its regression test, and it is what makes US1's result *visible* — without it nobody can watch a plate being read, which is exactly the blindness that let this go unmeasured. Ship the pair.

1. Phase 1 → Phase 2.
2. US1 to T013 (detection baseline, no owner needed) **in parallel with** all of US2.
3. **Stop and validate**: boxes draw on the clip and the webcam; detection evidence is committed.
4. Ask Mohamed for the labelling session (T014) — the read verdict waits on it, nothing else does.

### Incremental delivery after that

US3 (alerts + Live tab as drawn) → US4 (Movements) → US5 (register truthfulness). Each is independently demonstrable and none breaks the ones before it.

### Note on the removal

US3's T045 removes the pass list. Per the spec it ships **with** the alerts that take over registering-from-a-read — do not remove it in an earlier phase and leave the duties homeless in between.

---

## Notes

- `[P]` = different files, no dependency on incomplete work.
- Read [context.md](./context.md) before opening source; it names the traps (CRLF files, cp1252 logging, stale-result rules, dataset path spaces).
- The engine files listed are CRLF (`api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`) — edit bytes, and check `git diff --stat` for accidental whole-file rewrites.
- Commit after each task or logical group; the bug fix (T020) and its regression test (T019) must be **one** commit.
- Report honestly at every checkpoint: "T014 blocked on the owner" is worth more than a claim of completion.
