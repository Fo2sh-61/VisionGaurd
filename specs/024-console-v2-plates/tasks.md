---

description: "Task list for 024 console v2 car plates"
---

# Tasks: Car plates in console v2

**Input**: `specs/024-console-v2-plates/` (spec, plan, research, data-model, contracts/api.md, context.md, quickstart)
**Prerequisite**: spec 022 is built on this branch (roles, `OPERATOR_WRITE_PATTERNS`, toast, `useNavBadges`, tokens). Do not redo it.
**Tests**: required. Engine business rules get tests first, all in the new `engine/tests/test_plates_v2.py` (one file, so it can run alone).
**Tags**: `[ENG]` engine, `[CON]` console (web, mobile parity). `[P]` = different files, no dependency on an unfinished task.

## Format: `- [ ] T### [P?] [US?] [ENG|CON] description with exact path`

Paths (relative to the worktree root): engine = `engine/vg/...`, console = `web/src/...`.
CRLF files (edit with the Edit tool, check `git diff --stat`): `engine/vg/events/vehicles.py`, `engine/vg/api/*.py`, `web/src/services/*.ts`, `web/src/i18n/keys.ts`, `VehiclePasses/Movements/Register/Plate/VehicleGate.tsx`. LF: `auth/deps.py`, `features/base.py`, `VehicleAlerts.tsx`, `en.ts`.
Byte-shared with `mobile/src` (edit in web, copy, run `python tools/check_parity.py`): `api.ts`, `wire.ts`, `format.ts`, `i18n/{keys,en,ar.draft}.ts`.

Stories: **US1** Live tab (alerts, tiles, reads, detail, fix, remove). **US2** Movements (search, export, Gone). **US3** Registered vehicles and the alert-to-register flow. **US4** Reader trouble shown plainly; plates stay FP32 `.pt`. **US5** IT read-only note and checks.

---

## Phase 1: Setup

- [ ] T001 Confirm baseline: run `python -m pytest engine` once in the worktree and note the count (plan said 1940 passed, 14 skipped at `5ea8e67`; 022 has since added tests). Record the number for the final report.
- [ ] T002 Junction the main checkout's `web/node_modules` and `mobile/node_modules` into the worktree for `tsc` (remove at the end with non-recursive `[IO.Directory]::Delete`; use `npx.cmd`).
- [ ] T003 Read how 022 built `OPERATOR_WRITE_PATTERNS` in `engine/vg/auth/deps.py` and how `useNavBadges` counts vehicle alerts (`web/src/app/useNavBadges.ts`); note whether 024 needs any badge change (expected: none).

## Phase 2: Foundational (blocks every story)

**Purpose**: the wire shapes, store columns and the test file skeleton that all stories use.

- [x] T004 [ENG] Create `engine/tests/test_plates_v2.py` with the fixtures: copy `gate_app` and `_pass(...)` from `test_vehicles_api.py`, `gate`/`gate_pass` from `test_alerts_events.py`, the `store` fixture from `test_vehicles_store.py` (close the store before the tempdir).
- [x] T005 [ENG] Tests (red first) in `engine/tests/test_plates_v2.py`: `record_pass(plate_width=N)` stores it and the pass reads back `plate_width == N`; an old row (column absent, simulate by creating the DB with the old schema) reads `None`; `amend_pass` with a better photo refreshes `plate_width`, without a photo leaves it.
- [x] T006 [ENG] `engine/vg/events/vehicles.py`: add `vehicle_gone` table to `SCHEMA`; add `("vehicle_pass","plate_width","INTEGER")` and `("vehicle_pass","read_plate","TEXT")` to the `_add_missing_columns` loop; add `plate_width`, `read_plate` (default `None`) to `VehiclePass`; read both guarded by `if "x" in keys` in `_to_pass`; add `plate_width` to `record_pass` (INSERT) and to `amend_pass` (set only inside the `if snapshot` branch).
- [x] T007 [P] [ENG] `engine/vg/api/schemas.py`: `VehiclePass` gains `plate_width: int | None = None`, `read_plate_display: str | None = None`; `VehicleVisit` gains `ended_by: str | None = None`; new `GoneResult(Wire)` with `ok: bool`, `changed: bool`. `plate_width` is a plain int, never 0 for unknown.
- [x] T008 [ENG] `engine/vg/api/live.py`: `_to_wire_pass` sends `plate_width` and `read_plate_display` (display of `read_plate` only when corrected and different from the current plate); `_to_wire_visit` sends `ended_by`. `engine/vg/api/app.py` `record()` passes `plate_width=(read.image_box or read.box).w` to `record_pass` and `amend_pass`. Make T005 green.
- [ ] T009 [P] [CON] `web/src/services/wire.ts`: add `plateWidth`, `readPlateDisplay` to `VehiclePass`, `endedBy` to `VehicleVisit`, and `GoneResult`. Copy byte-for-byte to `mobile/src/services/wire.ts` if the mobile copy was identical before; else port by hand.

**Checkpoint**: columns, wire and test skeleton exist; stories can start.

---

## Phase 3: US1 - Live tab: alerts, tiles, reads, detail, fix, remove (P1, MVP)

**Goal**: a guard sees alerts, six clickable tiles, the gate cameras and today's reads; opens a row for the reader's figures; admin fixes or removes.
**Independent test**: with the clip store, tile counts equal the number of table rows for the same day; fix keeps the original; fixing a car still in view sends no message.

### Tests first (engine)

- [x] T010 [P] [US1] [ENG] `engine/tests/test_plates_v2.py`: `GET /vehicles/passes?days=1` returns today only and `days` without `day` means today; without `days` and without `day` still returns all time (old behaviour kept); `days=7&exact=true&plate=<canonical>` returns only that plate across 7 days; `days=0` and `days=32` are 422.
- [x] T011 [P] [US1] [ENG] `engine/tests/test_plates_v2.py`: fixing a plate keeps `read_plate` (the reader's own plate); a second fix keeps the FIRST original; wire `readPlateDisplay` is null for an uncorrected pass and for a correction equal to the original.
- [x] T012 [P] [US1] [ENG] `engine/tests/test_plates_v2.py`: a pass corrected before it is finished does not call `on_pass` when `finish_pass` runs, but is still marked finished (copy the no-message pattern from `test_alerts_events.py`); an uncorrected pass still sends.
- [x] T013 [P] [US1] [ENG] `engine/tests/test_plates_v2.py`: audit entry for fix and for remove is written before the change (patch the store to raise and assert the audit line exists).

### Engine

- [x] T014 [US1] [ENG] `engine/vg/events/vehicles.py` `VehicleStore.passes`: add `q` (owner, plate, canonical plate, copying the clause in `search`; both digit systems) and `exact` (`p.plate = canonical`). Keep the `plate` substring option.
- [x] T015 [US1] [ENG] `engine/vg/events/vehicles.py` `set_plate`: add `read_plate = COALESCE(read_plate, plate)` to the same UPDATE. `finish_pass`: still mark finished, call `on_pass` only when `rowcount == 1` and not `record.corrected_by`.
- [x] T016 [US1] [ENG] `engine/vg/api/live.py` `vehicle_passes`: `days` window (`first = (day or today) - (days-1)`, `since = _day_bounds(first)[0]`, `until = _day_bounds(day or today)[1]`); pass `q`, `exact`. `engine/vg/api/app.py` `vehicle_passes` route: add `q`, `days` (`Query(None, ge=1, le=31)`), `exact`. Update the `Protocol` in `engine/vg/api/store.py` and `MockStore` signature. Make T010-T013 green.

### Console

- [ ] T017 [P] [US1] [CON] `web/src/services/api.ts`: `getVehiclePasses` accepts `q`, `days`, `exact`. Add i18n keys needed by Live (`gate.*`, `passes.*`) to `web/src/i18n/keys.ts`, `en.ts`, `ar.draft.ts` (only 024's strings; `en` is a `Record` so a missing key fails the build). Copy `api.ts` and i18n to `mobile/src`.
- [ ] T018 [P] [US1] [CON] `web/src/components/Plate.tsx`: `dir="ltr"` on the Latin line (SC-008 in the Arabic console).
- [ ] T019 [US1] [CON] New `web/src/components/VehicleLive.tsx`: alerts strip (`VehicleAlerts`), tiles, `CamGrid feature="vehicles"` (plate boxes only, never a live recognition frame), reads table loaded with `getVehiclePasses({days:1, limit:1000})`, filter state from the tile, and "showing the latest 1000" when truncated. Empty today says "No cars yet today"; stopped reader looks different from zero cars.
- [ ] T020 [US1] [CON] `web/src/pages/VehicleGate.tsx`: tiles become buttons with selected state (Entered, Left, Not registered, Blacklisted filter; click again clears; Cameras reading filters nothing; Left shows a dash and is not clickable when `left` is null; Inside now switches to the Movements tab); keep `useAsync(getVehicleSummary)`; prefill becomes state `{plate, category?, passId?}`; Live is the default tab; keep `?tab=`, `?plate=`, `?date=`, `?gate=`, `?pass=`.
- [ ] T021 [US1] [CON] `web/src/components/VehiclePasses.tsx`: take a `filter` prop; weak-read badge from `needsReview`; detail panel (plate large, status, photo, owner and make/colour from ONE `getVehicleRegister(q=plate)` call only when a row opens, count of reads from `plate=<canonical>&exact=true&days=7&limit=500` labelled "last 7 days", confidence, frames agreed, plate width or "not recorded", original reading when `readPlateDisplay`); Fix via existing `PlateEditor`; Remove with inline confirm. No live camera frame in the panel. Movements stops rendering this card.

**Checkpoint**: Live works on its own; SC-003 holds on the clip.

---

## Phase 4: US2 - Movements: search, export, Gone (P2)

**Goal**: day/plate/owner/gate filters, traffic and gate summary, Inside now with Gone, Completed visits, honest closings, export that follows the screen.
**Independent test**: Gone closes an open visit as `endedBy`, the Inside count drops, and pressing it twice is not an error.

### Tests first (engine)

- [x] T022 [P] [US2] [ENG] `engine/tests/test_plates_v2.py`: Gone on an open visit returns `{ok:true, changed:true}`, the visit leaves `inside`, appears in `visits()` with `ended_by == actor`, `inferred is False`, no exit fields; the summary Inside count and the per-gate count drop.
- [x] T023 [P] [US2] [ENG] `engine/tests/test_plates_v2.py`: Gone on an already-closed visit returns 200 `changed:false`; unknown id and an exit pass id return 404; no vehicle log returns 503; deleting the entry pass cascades the mark away.
- [x] T024 [P] [US2] [ENG] `engine/tests/test_plates_v2.py`: audit `vehicle.visit.gone` is written before the mark (force `end_visit` to raise, audit still present, nothing marked).
- [x] T025 [P] [US2] [ENG] `engine/tests/test_plates_v2.py` (IT): `it_client` gets 200 on Gone and 403 on fix, remove, register add/edit/remove, import, export (copy the `test_authorisation.py` parametrised pattern).
- [x] T026 [P] [US2] [ENG] `engine/tests/test_plates_v2.py`: `q` owner search finds a pass by owner name and by plate in both digit systems; `POST /vehicles/export` with `q` writes only matching rows and the audit entry before the file.

### Engine

- [x] T027 [US2] [ENG] `engine/vg/events/vehicles.py`: `VehicleStore.end_visit(entry_pass_id, by_who)` (under `self._lock`, find the open visit among `inside(since=None)`; none returns False; else INSERT into `vehicle_gone` and return True). `visits()` LEFT JOINs `vehicle_gone g ON g.entry_pass_id = o.entry_id`; `Visit.ended_by`; a mark makes `left_at = g.at`, `inferred=False`, exit fields None, not inside.
- [x] T028 [US2] [ENG] `engine/vg/api/live.py` `mark_gone(entry_pass_id, actor)`: look up (KeyError for unknown or exit pass), `_log(actor, "vehicle.visit.gone", plate, entry time and gate)` BEFORE `store.end_visit`, return `GoneResult`. Add to `store.py` Protocol and to `MockStore` (raises `SubsystemUnavailable("... demo store.")`). `app.py`: `POST /vehicles/visits/{entry_pass_id}/gone` beside `delete_pass`, same `_need_register`, 404, 503 pattern as `dismiss_alert`; `q` on the export route.
- [x] T029 [US2] [ENG] `engine/vg/auth/deps.py`: add one anchored pattern `^/vehicles/visits/[^/]+/gone$` to `OPERATOR_WRITE_PATTERNS` (POST is already covered by 022's method check; widen only if not). Make T022-T026 green.

### Console

- [ ] T030 [P] [US2] [CON] `web/src/services/format.ts`: add `foldDigits(text)` (Arabic-Indic and extended to Western). `web/src/services/api.ts`: add `markVehicleGone(entryPassId)`; `exportVehiclePasses` accepts `q`. Add `moves.*` keys. Copy shared files to `mobile/src`.
- [ ] T031 [US2] [CON] `web/src/components/VehicleMovements.tsx`: `matches` folds digits on both sides (typing `1234` finds `١٢٣٤`); Gone button on Inside now rows for admin and IT, call then reload, no error when `changed:false`; label "Ended by hand" from `endedBy`, kept apart from "Exit estimated" (`inferred`) and observed exits; completed-visits summary line of observed / estimated / by hand; `download` sends `day`, `gate`, `q`; Inside now says it is "right now" and says so plainly when no exit camera (no figure).

**Checkpoint**: Movements and Gone work for admin and IT.

---

## Phase 5: US3 - Registered vehicles and the alert-to-register flow (P2)

**Goal**: Add/Renew/Add-to-blacklist open the register form pre-filled; the alert is dismissed only after a successful save.
**Independent test**: closing the form without saving leaves the alert; saving removes it; Renew on an expired car opens edit, not a duplicate error.

- [ ] T032 [P] [US3] [CON] `web/src/services/format.ts`: `alertDismissLabel` and `alertAction`: blacklisted gets dismissal only (one button); expired gets "I have dealt with it" (not "Leave it expired"). Copy to `mobile/src`; check `check_parity.py`.
- [ ] T033 [US3] [CON] `web/src/components/VehicleAlerts.tsx` (LF): `onResolve` only opens the form (passes `passId`); remove the immediate `void clear(a, true)`; the dismissal with `actionTaken=true` runs from the register save callback.
- [ ] T034 [US3] [CON] `web/src/components/VehicleRegister.tsx`: prefill is an object `{plate, category?, passId?}` (not a ref string); look the plate up with `getVehicleRegister(q)` exact canonical match: found opens EDIT of that vehicle, not found opens ADD; Renew focuses "permit valid until"; Add to blacklist sets category; plate is two inputs (letters, number) joined with a space on save; duplicate plate refused with a plain reason; `onSaved(passId)` callback; closing leaves the alert. Add `register.*` keys.
- [ ] T035 [US3] [CON] Wire the "Add to blacklist" shortcut on a pass in the detail panel (`VehiclePasses.tsx`) to open the register form pre-filled with category blacklisted (admin only; no new engine action).

**Checkpoint**: SC-002 flow works end to end.

---

## Phase 6: US4 - Reader trouble shown plainly; FP32 pin (P2)

**Goal**: a plate reader that fails every frame or died never shows as running; plates never use reduced precision or a compiled plan.
**Independent test**: a reader raising on every frame makes the page say so with the reason.

### Tests first (engine)

- [x] T036 [P] [US4] [ENG] `engine/tests/test_plates_v2.py`: `FeatureWorker` counter: 5 consecutive raising frames put the camera in `stats["failing_on"]` with the error text (max 200 chars); 4 do not; one good frame clears it; `unwatch`/closing a camera drops its entry (copy `test_health_load.py` L466-506 for `died_on`).
- [x] T037 [P] [US4] [ENG] `engine/tests/test_plates_v2.py`: with a failing gate camera `_cameras_reading()` leaves it out and the note names it; with every gate camera failing or dead `_vehicles_state()` is UNAVAILABLE with the reason and no counts; "ran out of memory" appears when the error text says so; `_vehicles_stage()` shows the failing row; System Health stays 200.
- [x] T038 [P] [US4] [ENG] `engine/tests/test_plates_v2.py`: a config with plates `half: true, accelerate: true` still builds the plate reader with `half=False, accelerate=False` (FP32 `.pt`) and logs a warning.

### Engine

- [x] T039 [US4] [ENG] `engine/vg/features/base.py` (LF): `self.__failing: dict[str, tuple[int, str]]` (double underscore); increment in the `_run` `except Exception` path keeping `str(exc)[:200]`; delete on a good frame and in `_closing`/`unwatch`; `stats["failing_on"] = {camera: error}` for runs of 5 or more, only cameras still served.
- [x] T040 [US4] [ENG] `engine/vg/api/live.py`: new `_plate_trouble()` mapping `died_on` and `failing_on` of `self.vehicles_worker` (via `_stats_of`) to `{camera_id: sentence}`; use it in `_cameras_reading()`, `_vehicles_state()` and `_vehicles_stage()` as in research R7. Never raise; degradation is payload.
- [x] T041 [US4] [ENG] `engine/vg/api/app.py` `_start_vehicles`: pass `half=False, accelerate=False` to `PlateReader(...)`; warn when the yaml differs. Keep exactly one `VehiclesWorker(...)` call with `on_final` and the `store.finish_pass` call (a test in `test_alerts_events.py` parses them). Make T036-T038 green.
- [ ] T042 [US4] [CON] Live tab shows the reader-trouble reason from the summary (`reason`, `camerasNote`) in the page, with counts as dashes when absent (SC-005). Add the keys.

**Checkpoint**: SC-005 holds in tests.

---

## Phase 7: US5 - IT read-only note and finishing (P3)

- [ ] T043 [P] [US5] [CON] Every edit control (Fix, Remove, Add/Renew/Blacklist, register edit, import, export) absent for `role !== 'admin'` across Live, Movements and Registered vehicles; one line says "Only an administrator can change the register or export the gate log." Gone and alert dismissal remain. Use `useAccount().role` as a hint only.
- [ ] T044 [P] [CON] Type check and parity: `cd web && npx.cmd tsc -b --force`, `cd mobile && npx.cmd tsc -b --force`, `python tools/check_parity.py`.
- [x] T045 [P] [ENG] `python -m pyflakes engine/vg engine/tools engine/tests`.
- [x] T046 [ENG] Run `python -m pytest engine/tests/test_plates_v2.py`, then the touched files (`test_vehicles_api.py`, `test_vehicles_store.py`, `test_alerts_events.py`, `test_authorisation.py`, `test_health_load.py`), then `python -m pytest engine` once; the count must not drop. Flaky under load: `test_recording` forgotten-recording, `test_lost_bag` interest lapse; rerun alone first.
- [ ] T047 `git diff --stat`: confirm no whole-file diffs (CRLF); remove the `node_modules` junctions (T002).
- [ ] T048 Not done here, report only: by-eye checks (quickstart items 1-15) need the running app, and every Jetson check (FR-318 to FR-320, SC-006, SC-007, plate font via `fc-list :lang=ar`) waits for the new board. Do not connect to the test bench.

---

## Dependencies and order

- Phase 1, then Phase 2 (T004-T009) blocks all stories.
- Inside each story: tests, then engine, then console. Console tasks need the wire (T009) and `api.ts` additions.
- US1 (T010-T021) first (MVP). US2, US3 and US4 are independent of each other after Phase 2; US3 depends on T021 for the pass-detail shortcut (T035) and on T020 for prefill state.
- Shared files across stories (`events/vehicles.py`, `live.py`, `app.py`, `store.py`, `api.ts`, `format.ts`, i18n): edit sequentially, not in parallel.
- Phase 7 runs last.

## Parallel examples

- T007 and T009 (schemas vs wire.ts); all `[P]` test tasks inside a phase (one file, so write them together, run them together).
- T018 (Plate.tsx) alongside T017.

## Implementation strategy

MVP = Phases 1-3. Then US2 (Gone is the largest new engine piece), US4, US3, finish with US5. 48 tasks; none adds a package, model or store file.
