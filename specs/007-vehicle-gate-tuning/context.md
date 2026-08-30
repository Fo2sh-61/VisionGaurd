# Implementation context: Vehicle Gate Accuracy & Redesign

**Written by `/speckit-plan` on 2026-08-27, against commit `e9ba8dd` + a dirty
working tree (95 modified/untracked entries).**

> Verify before trusting. This is a snapshot; if it disagrees with the code,
> the code wins and this file is wrong. Anchors drift — search for the symbol,
> do not trust line numbers.

**The single most important fact**: the vehicle-gate engine work (including
`_plate_boxes`) exists **only in the uncommitted working tree** — `git show
HEAD:engine/vg/api/live.py` has no `_plate_boxes` at all. You are building on
top of uncommitted work; do not lose it, and expect `git diff` to be huge before
you start.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/api/schemas.py` | `class Box(Wire)` | `x,y,w,h: Fraction`, `label`, `confidence`, `kind: Literal["person","weapon","object","face","match"] = "person"`, `match`, `severity`, `track_id`. Wire = snake→camel, `extra="forbid"`, Fraction/Confidence validate 0..1 | add `"plate"` to the literal; add `plate_width_px: int \| None = None`. **This literal is the invisible-box bug** — `S.Box(kind="plate")` raises today (verified by direct construction) |
| `engine/vg/api/schemas.py` | `class GateSummary(Wire)` | all counts `int \| None`, `gates: int`, `registered`, `reason`, `pairing_available`. Docstring: "absent is an admission" | add `cameras_reading`, `cameras_total`, `cameras_note` (all optional). Keep `needs_review` on the wire |
| `engine/vg/api/schemas.py` | `class VehicleVisit(Wire)` | `plate, plate_display, entered, entry_gate, left_at, exit_gate, minutes, owner, unit, category, inferred` | add `entry_pass_id`, `exit_pass_id` (`str \| None`), `entry_has_snapshot`, `exit_has_snapshot` (bool, default False) |
| `engine/vg/api/schemas.py` | after `class VehiclePass` block (~1428) | vehicle wire types cluster here | new `ReaderAttempt`, `GateReaderCamera`, `GateReaderNow`, `GateAlert`, `TrafficHour` per data-model.md |
| `engine/vg/api/live.py` | `def _plate_boxes` | loops `self.vehicles_worker.plates_on(camera_id)`; status via `vehicle_events.status_for(self.vehicle_store.by_plate(read.text), today)`; severity map blacklist→CRITICAL, unknown/expired→WARN; clamps fractions via `self._frame_size(camera_id)`; label `platetext.display(...) or "Plate"` | pass `plate_width_px=read.box.w` (already int pixels). Currently **raises** — after the schema fix it just works |
| `engine/vg/api/live.py` | `def _boxes` (~282) | `if feature == "vehicles": return self._plate_boxes(camera_id)` | no change — dispatch already right |
| `engine/vg/api/live.py` | `def _vehicles_state` | returns `(S.DataState, reason)` — "no gate camera" / worker None (+`vehicles_error`) / store None | reuse its reason strings for `GateReaderNow.reason`; extend `vehicle_summary` with cameras-reading fields computed from config gate cameras × worker presence × camera offline state |
| `engine/vg/api/live.py` | `vehicle_gates` / `vehicles_inside` / `vehicle_visits` | all call store with `self._start_of_day()` | thread `(since, until)` from a `day` argument; `inside` ignores day (always now). `_instant(when, clock)` for every Instant — never hand-build |
| `engine/vg/api/live.py` | `delete_pass_record` (search `vehicle.pass.delete`) | the `_log`-first idiom, wording style for audit details | copy for `vehicle.alert.dismiss`; new `vehicle_reader()`, `vehicle_alerts()`, `dismiss_alert()`, `vehicle_traffic()` methods |
| `engine/vg/api/app.py` | `@app.get("/vehicles/summary"…` (~2904) | endpoint cluster; `StoreDep`, `Query(...)`, `auth_deps.CurrentUser` on user-named writes (see `delete_pass`, `export_passes`); snapshot endpoint reads `request.app.state.vehicle_store` directly | add `GET /vehicles/reader`, `GET /vehicles/alerts`, `POST /vehicles/alerts/{pass_id}/dismiss` (CurrentUser), `GET /vehicles/traffic`; `day` param on gates/visits/export |
| `engine/vg/api/store.py` | MockStore vehicle methods (search `vehicle_summary`) | every LiveStore override has a fixture-mode twin; `SubsystemUnavailable` → 503 lives here | mock `vehicle_reader/alerts/dismiss/traffic` + accept `day` params. **-Mock mode 500s the page if any new endpoint lacks a mock** |
| `engine/vg/features/vehicles.py` | `VehiclesWorker.analyse` | per frame: `reads = self.reader.read_frame(frame.image)`; tracks matched by IoU 0.25; `track.vote(...)`; `_settle` emits passes; returns `VehiclesResult(reads, passes, too_small)`. `MIN_VOTES=3`. No threading here — `FeatureWorker` owns it | time `read_frame` into per-camera EMA `read_ms`; append one attempt per read to `self._attempts[camera_id]` `deque(maxlen=12)` with the matched track's `leader` snapshot; new accessors `attempts_on(camera_id)`, `read_ms(camera_id)` |
| `engine/vg/features/vehicles.py` | `plates_on` | returns `result.payload.reads`, **empty when result aged out** — the freshness idiom | copy its shape for `attempts_on` |
| `engine/vg/events/vehicles.py` | `SCHEMA` string (two CREATE TABLEs) | `vehicle` (~57), `vehicle_pass` (~74) | append `vehicle_alert_ack` and `vehicle_import_run` per data-model.md |
| `engine/vg/events/vehicles.py` | `VehicleStore.passes` | builds SQL as a list of clauses + params — the filter pattern | add `until` bounds here and in `counts_since`, `visits`, `inside`, `gates`; new `hourly(since, until)` (GROUP BY hour), `alert_acks`/`add_alert_ack`, `record_import_run`/`last_import_run`, `near_matches(plate)` (SELECT plate/owner, filter with `platetext.same_plate` in Python — register is ~2k rows, fine) |
| `engine/vg/events/vehicles.py` | `visits` window SQL | derives visits from passes (LEFT JOIN over ordered passes); `status_for(vehicle, today)` at ~192 decides pass status | select entry/exit pass ids through the window into `Visit`; reuse `status_for` for alert kinds |
| `engine/vg/events/vehicles.py` | `import_rows` | one transaction, returns added/skipped/rejected dict | insert the `vehicle_import_run` row inside the same transaction |
| `engine/vg/auth/deps.py` | `ADMIN_WRITE_PREFIXES` | tuple incl. `"/vehicles"` (comment: guard reads, cannot un-blacklist); `requires_admin(method, path)`; `SAFE_METHODS` | add `OPERATOR_WRITE_PREFIXES = ("/vehicles/alerts",)` checked **before** the admin-write rule in `requires_admin` |
| `engine/tools/eval_plates.py` | NEW | — | build from `tools/compare_plates.py`'s reader construction (four configs, `VG_NO_TENSORRT` lever). Dataset: `Vehicles/*.jpg\|JPG\|jpeg` + `Vehicles Labeling/<stem>.txt`, YOLO `0 cx cy w h` normalised; IoU ≥ 0.5 = found. 2,088 labels vs 2,085 images — skip unmatched pairs and report the count |
| `web/src/types.ts` | `kind: string` (~325) | Box mirror is already loose — plate kind needs no change | add `plateWidthPx?: number` |
| `web/src/services/wire.ts` | vehicle types | camelCase mirrors of schemas | add the five new types + changed fields |
| `web/src/services/api.ts` | `getVehicleSummary` (~417) | the fetch-wrapper idiom for the vehicle cluster; `getCameraDetections` (~84) carries `feature` | add `getVehicleReader`, `getVehicleAlerts`, `dismissVehicleAlert`, `getVehicleTraffic`; `day` params on gates/visits/export |
| `web/src/services/format.ts` | `boxColor` (~154) | **already** has `if (box.kind === 'plate') return severity warn ? amber : green` above the face branch; red via critical first | add `plateLatin(display)` (TS transliteration map — see Traps) and a width-tone helper (≥100 green, else amber) |
| `web/src/components/CameraFrame.tsx` | box render loop | label chip offsets in the size constants (`labelTop` etc.); `wantLiveBoxes = (useStream \|\| tileOverlay) && detections` (~190) | render `plateWidthPx` beside plate-kind boxes, toned |
| `web/src/pages/VehicleGate.tsx` | `Passing now` Card (~182–267) | polls `getVehiclePasses` at 2 s; `DeletePass`; `prefill` ref feeds the register tab; `Tile` renders null → dash+reason; `CamGrid feature="vehicles" tileOverlay only` with the comment explaining why `detections={false}` is the wrong tool | remove the pass list + its poll + `DeletePass` import; add `VehicleAlerts` + `VehicleReader`; retile (needs-review → cameras-reading); keep Tile, CamGrid, capability gating |
| `web/src/components/VehicleMovements.tsx` | `VehicleMovementsTab` (~122) | three Cards: "Today, gate by gate" / "Inside now" / "Completed visits"; `VisitRow` (~69), `length()` min-formatter (~65); useAsync per endpoint | rebuild per drawing: filter bar, inline hourly chart (flex columns), thumbnails (`/vehicles/passes/{id}/snapshot` when `entryHasSnapshot`), "Export this day", scope line |
| `web/src/components/VehicleRegister.tsx` | category chips (~243) | import card + search + inline form + rows via `Plate` | latin sub-line under plates; real last-import line from the new wire field (absent when none) |

## 2. Things to copy, not invent

- Endpoint → LiveStore → MockStore triple: `vehicle_summary` all three layers.
- Four-reader construction + isolation logic: `engine/tools/compare_plates.py`
  (its docstring IS the diagnosis method).
- Audit-first: `live.py` search `vehicle.pass.delete` or `vehicle.export`.
- Store-with-real-data test: `test_groups.py` `store` fixture (tempdir; close
  gallery before tempdir on Windows). Vehicle store tests already exist —
  search `VehicleStore(` under `engine/tests/`.
- Result freshness + boost: `features/vehicles.py::plates_on` +
  `features/base.py::note_interest` (BOOST_TTL, `result()` staleness).
- CSV read/write: `events/vehicles.py::read_csv` / `template_csv` for the truth
  file tooling.
- Auth path tests: `engine/tests/test_authorisation.py` — add the carve-out
  cases beside the existing `/vehicles` ones.

## 3. Traps

- **`S.Box(kind="plate") raises today.** Any test that exercises
  `camera_view(feature="vehicles")` with a plate in view sees a pydantic
  `ValidationError` until the literal is fixed. Fix schema first, then the test
  proves the path.
- **The vehicle-gate engine code is uncommitted.** HEAD has no `_plate_boxes`.
  Commit strategy is implement's problem but losing the tree is fatal.
- **CRLF files**: `api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`. Byte-safe
  edits only; `git diff --stat` catches a whole-file rewrite.
- **`quantize=16` on `predict()`**: what this ultralytics build actually does
  with it is unverified — the source project passes nothing (FP32 default).
  Don't reason from the name; the eval matrix measures it.
- **`plates_on` (and the new `attempts_on`) return `[]` when the result is
  stale** — the reader endpoint must `note_interest()` first or the card's
  first poll is empty and stays empty on an idle camera.
- **Windows console is cp1252**: never log Arabic display text from worker
  threads — transliterate (`features/vehicles.py` has the comment and idiom).
- **Latin line duplication**: `platetext.TRANSLIT` exists in Python. Do NOT add
  a wire field per type for it; `format.ts` owns rendered strings and the
  design itself ships a client-side map. One TS helper (`plateLatin`), with a
  comment naming `platetext.TRANSLIT` as the source to keep in step.
- **MockStore first**: `dev.ps1 up -Mock` is the UI loop; a missing mock method
  turns the whole page into a 503 before the UI exists.
- **Dataset path has spaces** — quote `"Egyptian Car Plates dataset/…"` in every
  command, and the label folder is `Vehicles Labeling` (with the typo'd parent
  `EALPR Vechicles dataset` — sic).
- **Dismiss ≠ silence**: the same car re-alerts on its next recorded pass (new
  pass id) — deliberate, spec edge case; don't "fix" it.
- **`/vehicles/alerts` carve-out ordering**: checked before `ADMIN_WRITE_PREFIXES`
  in `requires_admin`, with tests both ways (guard CAN dismiss, guard still
  CANNOT write the register).
- **Vite dev deep links return JSON** — load `/` and click through (proxy).
- **Suite teardown oddity**: `pytest -q` under this tree prints the FAILED
  summary but the final counts line did not reach a redirected file — the
  baseline below was tallied from the progress dots. If you see the same, count
  the dots, don't assume a hang.

## 4. Baseline

- `python -m pytest` (in `engine/`) → **1120 passed, 11 skipped, 3 failed**
  (1134 collected) at `e9ba8dd` + dirty tree, 2026-08-27.
- Already failing before this feature, not this feature's to fix, must not grow:
  - `tests/test_track_page.py::TestTheMeasurementTool::test_the_tool_imports_and_names_its_own_budget`
  - `tests/test_track_page.py::TestTheDevServerCanReachEveryEndpoint::test_every_served_prefix_is_proxied`
  - `tests/test_track_page.py::TestTheDevServerCanReachEveryEndpoint::test_the_path_prefix_specifically`
- New test files this feature adds: `engine/tests/test_vehicle_overlay.py`,
  `engine/tests/test_vehicle_alerts.py`; plus cases in `test_authorisation.py`
  (carve-out) and wherever the existing vehicle store/API tests live.

## 5. Still unknown

- What `quantize=` really does in the installed ultralytics (vs `half=`) —
  check the library, then trust the measurement.
- Whether `build_engines.py` takes a precision flag (only matters if the ladder
  reaches FP32-TRT).
- The exact visits window SQL shape — pass-id selection is expected to be a
  column addition, verify at the edit.
- Config camera fields available for `GateReaderCamera` (name/gate/direction
  come from config; confirm attribute names in `config.py`).
- Where the existing vehicle store/API tests live and their names — extend
  those files rather than duplicating harnesses.
