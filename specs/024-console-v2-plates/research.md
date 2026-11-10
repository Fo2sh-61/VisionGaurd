# Research: 024 car plates

Every finding was read in code at commit `5ea8e67`. Paths are in `context.md`.

## R1 - Gone is one mark row, not a stored visit

- **Finding**: visits are derived from passes by a window function (`VehicleStore.visits`). Nothing records a manual end.
- **Decision**: table `vehicle_gone(entry_pass_id PK, by_who, at)`, `ON DELETE CASCADE` (the same shape as `vehicle_alert_ack`). `visits()` left-joins it: a mark wins, `left_at = mark time`, `ended_by = name`, not `inferred`, not inside. Everything that counts "inside" (summary, per-gate, alert `inside`) already goes through `visits()`, so they all follow with no further change.
- **Pressing Gone on a visit that already closed** is not an error: `200 {ok, changed:false}` and the page reloads. Unknown id, or a pass that is an exit: 404.
- **Audit first**: `vehicle.visit.gone`, written after the "is it still open" read and before the write (same order as `dismiss_alert`).
- **Rejected**: a stored `visit` table (drifts from the log; the module docstring explains why it was refused); a flag on `vehicle_pass` (the entry is evidence and is not edited).

## R2 - IT may press Gone: one more anchored pattern

- **Finding**: `/vehicles` is admin-write by prefix; the operator allowance `OPERATOR_WRITE_PREFIXES` is `("/vehicles/alerts",)` and its comment says keep it tiny and never widen a prefix. 022 adds an anchored pattern for `/cameras/{id}/recording` beside it.
- **Decision**: add `^/vehicles/visits/[^/]+/gone$` the same way. Checked before the admin-write rule, same order as the alerts carve-out. Fix, remove, register, import, export stay refused for IT with no change (all are non-GET under `/vehicles`).
- **Rejected**: prefix `/vehicles/visits` (would open any later write there).

## R3 - Plate width: store the width of the photographed frame

- **Finding**: `PlateBox.w` exists on the live read (`ReadAttempt.width_px`) and on the best frame (`VehiclePassRead.image_box`). It is never stored.
- **Decision**: `vehicle_pass.plate_width INTEGER`, set from `image_box.w` (else `box.w`) in `app.py::record`, and refreshed in `amend_pass` only when a better photo replaces the old one, so width and photo always describe the same frame. Old rows stay `NULL` and the wire sends `null`, shown as "not recorded".
- **Not** added to the CSV export (changes a file people may already parse).

## R4 - Owner search and the week: options on the existing list

- **Finding**: `VehicleStore.passes(plate=...)` is a substring match on plate only. The route takes `day` (one day) or nothing. With `day` empty it returns the newest N of **all time**, not today; the old Movements card therefore showed other days' rows under "today". Live needs a true today.
- **Decision**: three optional query options on `GET /vehicles/passes`: `q` (plate, either digit system, **or** owner, copying the clause in `VehicleStore.search`), `days` (1..31; window of that many days ending at the end of `day` or today), `exact` (plate equals, not contains). Without `days`, behaviour is unchanged. `q` is also accepted by `POST /vehicles/export` so the file matches the screen.
- Live table: `days=1, limit=1000`. Detail panel: `plate=<canonical>&exact=true&days=7&limit=500`, the count is the answer.
- **Limit**: the owner is joined live from the register, so a car removed from the register stops matching by owner. Honest and already how the row displays.
- **Also found**: Movements' client filter compares `plateDisplay.includes(query)`, so typing `1234` finds nothing for `١٢٣٤` (scenario 12). Fix in `format.ts` with a digit-folding helper used on both sides.
- **Tile equals table (SC-003)**: tiles come from `counts_since(start of day)`; the table now asks for the same window. A busy gate over 1000 passes a day would truncate the table, so the page says "showing the latest 1000" instead of hiding it.

## R5 - Fix: keep the original, send nothing

- **Finding 1**: `set_plate` overwrites `plate`. The audit entry names both plates, but the audit trail is in memory only (spec 018), so the original is lost on restart. FR-307 needs it on record.
- **Decision**: `vehicle_pass.read_plate TEXT`, set by `read_plate = COALESCE(read_plate, plate)` in the same UPDATE, so a second fix keeps the first original. Wire `readPlateDisplay` only when corrected and different.
- **Finding 2**: `finish_pass` hands the pass to `on_pass` when the car leaves, using the row as it is **then**. A fix made while the car was still in view is therefore sent as an alert for the corrected plate. The docstring says a correction "does not come through here"; it does come through when the pass is unfinished.
- **Decision**: in `finish_pass`, still mark finished, but do not call `on_pass` when `corrected_by` is set. One condition and one test. The existing test only covers a finished pass.

## R6 - Add / Renew / Add to blacklist: one prefill object

- **Finding**: `VehicleAlerts.onResolve` calls `onRegister(alert)` and `clear(alert, true)` together, so the alert is dismissed as "acted on" before the form exists. `VehicleGate` keeps only a plate string in a ref. For an expired permit the plate **is** on the register, so an Add form would be refused as a duplicate.
- **Decision**: the page holds `{plate, category?, passId?}`. The register tab looks the plate up (`getVehicleRegister(q)`, exact canonical match): found means **edit** that vehicle, not found means **add**. Renew focuses "permit valid until"; Add to blacklist sets category. `passId` is dismissed with `actionTaken=true` only from the successful save. Closing the form leaves the alert.
- No new engine action (FR-321). The form's plate becomes two inputs (letters, number) joined with a space; the engine's `normalize` already accepts that.

## R7 - A reader that fails must stop looking healthy

- **Finding**: `FeatureWorker._run` catches an exception from `analyse`, logs it and continues. `died_on` covers a dead thread only. A CUDA out-of-memory on every frame leaves the thread alive, the stage "healthy" and the tile showing live counts. `_vehicles_state()` does not look at the worker's counters at all, so even a dead thread leaves the page saying live (the stage row says stopped; the page does not).
- **Decision**: `__failing: dict[camera, (count, last_error)]` in the base class, cleared by the next good frame; `stats["failing_on"]` lists cameras at 5 or more in a row with the error text (double underscore, as `__died_on` is, for the same subclass-collision reason). In `live.py` a helper `_plate_trouble()` maps `died_on` and `failing_on` to a plain sentence per gate camera ("ran out of memory" when the text says so). Then:
  - `_cameras_reading()` leaves those cameras out and its note names them (the existing "Cameras reading" tile and note),
  - `_vehicles_state()` returns UNAVAILABLE with the reason when **every** gate camera is in trouble, so the counts disappear and the reason shows (SC-005),
  - `_vehicles_stage()` shows the failing row.
- **Rejected**: pausing the reader for lack of memory (needs a memory threshold, a resume rule and a UI state; the spec says "for example"). Failing visibly meets "say plainly, never show as running".
- Base class touched on purpose: every feature gains the counter. Only plates read it in 024.

## R8 - Plates stay `.pt` at full precision

- **Finding**: today `engine.yaml` pins `half: false`, `accelerate: false` for `plates` (L366-367), but `config.py` defaults both to **true** (L633, L641), so a site file that omits them, or an edit, silently changes readings (FP16 changes 6.7%, TensorRT 26.6%: `docs/PLAN.md` L234). `build_engines.py` has no plate exclusion, but `load_model(accelerate=False)` never opens a plan.
- **Decision**: `_start_vehicles` passes `half=False, accelerate=False` and logs a warning when the yaml says otherwise. The single `VehiclesWorker(...)` call stays (a test parses it). Test: a config with `half: true` still builds an FP32 `.pt` reader.
- **Jetson**: SC-006 (identical readings) is `engine/tools/eval_plates.py --configs theirs,fp32` on the owner's plate test set, run on the board. Not run here.

## R9 - Memory on the Jetson

- **Finding**: no allocator exists and none is needed in one process: features share one CUDA context. The plate pair is two `.pt` YOLO models plus per-frame activations; their size is **unmeasured** here (weights are not in the worktree).
- **Decision**: no sharing mechanism. 022 adds the shared-memory reading to System Health; R7 makes an out-of-memory reader visible; SC-007 (60 minutes, all cameras, under 8 GB, reader still running) is measured on the new board. If it does not fit, the levers that already exist are `plate_wake: motion` (fewer reads), the camera analytics rate, and fewer cameras. Reduced precision is not one of them (R8).

## R10 - Plate drawing and font

- **Finding**: `Plate.tsx` already gives the band, Arabic letters and digits, `direction: rtl; unicode-bidi: isolate`, fixed black on white, Latin line beneath. The Latin line inherits the page direction.
- **Decision**: put `dir="ltr"` on the Latin line (SC-008 in the Arabic console). The font is the real FR-320 risk: `web/index.html` loads fonts from `fonts.googleapis.com`, and `Plate.tsx` names `'Noto Sans Arabic'`. Offline, it falls back to whatever Arabic font the board has. Raised with 022 (it owns `index.html`). Check `fc-list :lang=ar` on the board.

## R11 - Things the spec lists as existing, confirmed

Alerts (`GET /vehicles/alerts`), summary, traffic, gates (with `pairingAvailable`), inside, visits (`inferred` = "Exit estimated"), export (POST, audit first), delete (audit first), register CRUD, import, last import (404 when none, with `by_who`), template (CSV), the midnight drop-off of alerts (`vehicle_alerts` reads from start of day, so owner decision on "old" needs no code).

One spec sentence needs a footnote: "status never rewritten by a later register change" is true, but `amend_pass` and `set_plate` do recompute status when **the plate itself** changes. That is by design (a corrected plate may be a blacklisted car) and is not a register change.
