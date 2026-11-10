# Implementation context: 024 console v2 car plates

**Written by `/speckit-plan` on 10 Nov 2026, against commit `5ea8e67` (worktree `console-v2-plans`).**

Read this **before** opening any source file, then open only the named anchors. If this disagrees
with the code, the code wins. Search for the symbol; line numbers drift. 022's `context.md` owns the
shell, roles, toast, badges, tokens: do not redo them.

---

## 1. Anchors

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/events/vehicles.py` | `SCHEMA` (L56), `_add_missing_columns` (L286) | `vehicle`, `vehicle_pass`, `vehicle_alert_ack` (CASCADE), `vehicle_import_run`. Late columns added by name in a `for table, column, ddl` loop | add `vehicle_gone` to `SCHEMA`; add `("vehicle_pass","plate_width","INTEGER")` and `("vehicle_pass","read_plate","TEXT")` to the loop |
| same | `class VehiclePass` (L190), `_to_pass` (L1266) | frozen dataclass; `_to_pass` guards late columns with `if "x" in keys` | add `plate_width: int \| None = None`, `read_plate: str \| None = None`; read both guarded |
| same | `class Visit` (L219), `VehicleStore.visits` (L852) | `inferred` marks re-entry closure. SQL: `WITH ordered AS (... LEAD ... OVER w)` then `LEFT JOIN vehicle`. `left_at` is set when exited or closed by re-entry | LEFT JOIN `vehicle_gone g ON g.entry_pass_id = o.entry_id`; add `ended_by: str \| None = None` to `Visit`; a mark makes `left_at = g.at`, `inferred=False`, `exit_*` None |
| same | `record_pass` (L485) | positional/keyword args, INSERT lists columns | add `plate_width: int \| None = None`, include in INSERT |
| same | `amend_pass` (L645) | UPDATE with optional `snapshot, plate_crop` pair; returns row untouched when `corrected_by` set | add optional `plate_width`, set it inside the same `if snapshot` branch |
| same | `passes` (L529) | `plate` substring over `plate`/`plate_display`; JOINs `vehicle v` already | add `q` (copy the clause in `search` L445: owner, plate, canonical plate) and `exact` (`p.plate = canonical`) |
| same | `set_plate` (L757) | UPDATE sets plate, display, status, vehicle_id, needs_review=0, corrected_by/at | add `read_plate = COALESCE(read_plate, plate)` in the same UPDATE (right side reads the old value) |
| same | `finish_pass` (L703) | marks finished, then calls `on_pass(record)` when `rowcount == 1` | also require `not record.corrected_by` for the call. Still mark finished |
| same | new `end_visit(entry_pass_id, by_who)` | none | under `self._lock`: find the open visit among `self.inside(since=None)` by `entry_pass_id`; none means return False; else INSERT into `vehicle_gone`; return True. Caller audits first |
| `engine/vg/features/base.py` | `__died_on` (L152), `_run` `except Exception: ... continue` (L291), `stats` (L410) | a raising frame is logged and skipped; `stats` has `died_on` | add `self.__failing: dict[str, tuple[int, str]]`; increment on exception (keep `str(exc)[:200]`), delete on a good frame and in `_closing`/`unwatch`; `stats["failing_on"] = {camera: error}` for runs of 5 or more, only cameras still served |
| `engine/vg/api/app.py` | `_start_vehicles` (L1387), `PlateReader(...)` call (L1424), `record()` (L1448) | reader gets `half=plates.half`, `accelerate=plates.accelerate and chars.accelerate`; `record` passes `read.image`, `read.image_box` | pass `half=False, accelerate=False`; warn when yaml differs; pass `plate_width=(read.image_box or read.box).w` to `record_pass` and `amend_pass` |
| same | `vehicle_passes` route (L3346), `export_passes` route (L3681), `vehicle_visits` | options `limit, plate, gate, direction, status, day` | add `q`, `days` (`Query(None, ge=1, le=31)`), `exact`; `q` on export; new `POST /vehicles/visits/{entry_pass_id}/gone` next to `delete_pass`, same `_need_register`/503/404 pattern as `dismiss_alert` |
| `engine/vg/api/live.py` | `vehicle_passes` (L1625), `_to_wire_pass` (L1637), `_to_wire_visit` (L1752), `correct_plate` (L1868), `delete_pass` (L1828) | `day` becomes a window via `_day_bounds`; wire built field by field | `days`: first = (`day` or today) minus `days-1` days, `since = _day_bounds(first)[0]`, `until = _day_bounds(day)[1]`; wire `plate_width`, `read_plate_display` (display of `read_plate` only if corrected and different); `ended_by`; new `mark_gone(entry_pass_id, actor)`: lookup, `_log(actor,"vehicle.visit.gone",...)` then `store.end_visit` |
| same | `_vehicles_state` (L1476), `_cameras_reading` (L1540), `_vehicles_stage` (L3699), `_stopped_stage` (L3292), `_stats_of` | `_vehicles_state` never looks at the worker's counters; `_cameras_reading` checks camera status only | new `_plate_trouble()` -> `{camera_id: sentence}` from `died_on` + `failing_on` of `self.vehicles_worker` (`_stats_of`); use in the three places as in research R7 |
| `engine/vg/api/store.py` | Protocol block (L186-209), MockStore vehicle block (L303-390) | MockStore raises `SubsystemUnavailable("... demo store.")` for writes | add `mark_gone` to both |
| `engine/vg/api/schemas.py` | `class VehiclePass` (L1973), `class VehicleVisit` (L2080) | `Wire` subclasses, `Confidence` validated 0..1 | add `plate_width: int \| None = None`, `read_plate_display: str \| None = None`, `ended_by: str \| None = None`, `GoneResult` |
| `engine/vg/auth/deps.py` | `OPERATOR_WRITE_PREFIXES` (~L128), `requires_admin` | prefix tuple, checked before admin-write | add the anchored pattern for Gone **through whatever 022 builds for the recording pattern** (same tuple/function) |

### Console (`*` = byte-shared with `mobile/src`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/pages/VehicleGate.tsx` (CRLF) | `VehicleGate`, `Tile`, `prefill` ref | tabs, six `Tile`s (not clickable), alerts strip, `CamGrid`, `VehicleReader`; **no reads table on Live** (it was moved into Movements) | tiles become buttons with selected state; keep `useAsync(getVehicleSummary)`; Live = alerts, tiles, `CamGrid`, reads table + detail panel (new `VehicleLive.tsx`); prefill becomes state `{plate, category?, passId?}` |
| `web/src/components/VehiclePasses.tsx` (CRLF) | `VehiclePassesCard({isAdmin, day})` | list of `getVehiclePasses({limit:100, day})` with in-row `PlateEditor`, one-click remove | rows move to Live with a `filter` prop; detail panel added; Remove gets an inline confirm; weak-read badge from `needsReview`. Movements no longer renders it |
| `web/src/components/VehicleAlerts.tsx` (LF) | `onResolve={(a) => { onRegister(a); void clear(a, true); }}` in `VehicleAlerts` | dismisses as acted-on **before** the form saves | `onResolve` only opens the form with `passId`; the dismissal runs from the register save |
| `web/src/components/VehicleMovements.tsx` (CRLF) | `VehicleMovementsTab`, `matches`, `VisitRow`, `download` | client filter `plateDisplay.includes(query)`; Inside now has no Gone; export sends `day, gate` | digit-fold both sides of `matches`; Gone button (admin and IT) on Inside rows, calls then reloads; `endedBy` label; summary line of observed / estimated / by hand; `download` sends `q` |
| `web/src/components/VehicleRegister.tsx` (CRLF) | `VehicleRegisterTab({isAdmin, prefillPlate})`, `EMPTY_FORM`, `save` | prefill is a plate string in a ref; plate one input; `save` has no hook | prefill object; resolve existing vehicle by exact plate to open edit; plate as letters + number; `onSaved(passId)` callback; IT note line |
| `web/src/components/Plate.tsx` (CRLF) | Latin `<span>` under the chip | inherits page direction | `dir="ltr"` |
| `web/src/services/api.ts`* (CRLF) | `getVehiclePasses` (~L469), `exportVehiclePasses` (~L665), `getVehiclesInside` | `getVehiclePasses({limit, plate, gate, ...day})` | add `q, days, exact` to both; add `markVehicleGone(entryPassId)` |
| `web/src/services/wire.ts`* (CRLF) | `VehiclePass` (L1132), `VehicleVisit` (L1190) | mirrors the schemas | add the three fields and `GoneResult` |
| `web/src/services/format.ts`* (CRLF) | `alertDismissLabel` (L518), `alertAction` (L529), `plateLatin` (L466) | blacklist label "I have dealt with it", expired "Leave it expired" | blacklist: dismissal only (one button); expired: "I have dealt with it"; add `foldDigits(text)` (Arabic-Indic to Western) |
| `web/src/i18n/{keys,en,ar.draft}.ts`* | `gate.*`, `passes.*`, `moves.*`, `register.*`, `reader.*` (123 keys) | `keys.ts` is CRLF, `en.ts` LF | only 024's new strings; `en` is a `Record` so a missing key fails the build |

## 2. Things to copy, not invent

- Gone endpoint and store method: `dismiss_alert` (`events/vehicles.py` L594, `live.py` L1888, `app.py` `dismiss_alert` route): `KeyError` to 404, `SubsystemUnavailable` to 503, audit first.
- The mark table: `vehicle_alert_ack` in `SCHEMA`.
- Owner search clause: `VehicleStore.search`.
- Late column: the `corrected_by` entry in `_add_missing_columns`.
- Failure counter: `__died_on` handling in `FeatureWorker`.
- Tests: `gate_app` fixture and `_pass(...)` helper in `test_vehicles_api.py` (L369, L426); `gate` and `gate_pass` in `test_alerts_events.py` (L461, L476) for the no-message test; `store` fixture in `test_vehicles_store.py`; `test_authorisation.py` `it_client` parametrised tests for IT 403s; `test_health_load.py` L466-506 for `died_on` (copy for `failing_on`).
- The register prefill and edit form already exist: reuse, do not write a second form.

## 3. Traps

- **Parity and CRLF.** `api.ts`, `wire.ts`, `format.ts`, i18n are byte-shared: edit, copy to `mobile/src`, run `check_parity.py` and mobile `tsc`. `api/*.py`, `events/vehicles.py`, `services/*.ts`, `VehiclePasses/Movements/Register/Plate/VehicleGate.tsx` and `keys.ts` are CRLF; `deps.py`, `base.py`, `VehicleAlerts.tsx`, `en.ts` are LF. Edit bytes, check `git diff --stat`.
- **A test parses `_start_vehicles`** (`test_alerts_events.py` ~L845): exactly one `VehiclesWorker(...)` call with `on_final`, and a `store.finish_pass` call. Keep both.
- **`__failing` needs the double underscore** for the reason `__load_window` and `__died_on` have it (a subclass once overwrote `_recent`).
- **`days` with empty `day` means today**; without `days`, empty `day` still means all time. Do not "fix" the old behaviour, other callers (Ask links) rely on it.
- **`Confidence` fields are validated 0..1.** `plate_width` is a plain int; do not send 0 for unknown, send `null`.
- **Status on the wire is the frozen one**, but `amend_pass` and `set_plate` recompute it when the plate changes. Do not add recomputation anywhere else.
- **`CameraFrame` with `live` polls recognition boxes with names.** The Live strip uses `CamGrid feature="vehicles"`, which is plate boxes only. The new detail panel must not show a live camera frame.
- **The reads table must not read the register per row.** One `getVehicleRegister(q=plate)` call, only when a row is opened.
- **Tile `left` is `null` with no exit camera** (`pairing_available` false); render a dash and do not make the tile clickable.
- **Gone is not "inferred"**: three different closings (observed, `inferred`, `endedBy`) must never share a label.
- **Do not add a CSV column** for plate width: the export is a file people may already parse.
- **022 shares `deps.py`, `live.py`, `schemas.py`, `app.py`, `api.ts`, `wire.ts`, `format.ts`, i18n.** Rebase onto 022 before editing the operator allowance and `useNavBadges`.
- `web/node_modules` is absent in a worktree: junction the main checkout's and remove it afterwards (memory: worktrees lack node_modules).

## 4. Baseline

- `python -m pytest engine`: **1940 passed, 14 skipped** at `5ea8e67` (not rerun while planning).
- New test file: `engine/tests/test_plates_v2.py`: Gone (open visit closed, already-closed no-op, 404 for an exit pass, audit before write, IT 200, derived counts drop, cascade on pass delete); plate width stored on new, `null` on old; `q` owner and both digit systems; `days=7` + `exact`; `days` without `day` is today; fix keeps `read_plate` across two fixes; fix before finish sends no message; failing counter (5 in a row, reset by a good frame, text carried); `_vehicles_state` and `_cameras_reading` with a failing gate; FP32 pin with `half: true` in the config; IT 403 on fix, remove, register, import, export.
- Known flaky under load: `test_recording` forgotten-recording and `test_lost_bag` interest lapse. Rerun alone first.

## 5. Still unknown

- How 022 shapes the IT operator allowance (tuple of regexes or a function). Match it.
- Whether 022's `useNavBadges` already counts vehicle alerts. Its plan says it does (FR-103), so 024 adds no badge source; confirm after 022 lands.
- Whether 022 will self-host Noto Sans Arabic (R10). If not, the plate looks different offline.
- Plate-model memory cost and whether SC-007 holds: only the new board can say.
- Whether the Jetson's Python is 3.10 (no 3.11 syntax in anything new here).
- The owner's answers to the three small choices in `plan.md` ("For the owner").
