# Research: Vehicle Gate Accuracy & Redesign

Phase 0 output. Every unknown from the Technical Context resolved to a decision,
with rationale and the alternatives that lost.

## 1. How wrong reads get diagnosed

**Decision**: batch the existing four-reader matrix over the owner's dataset.
`tools/compare_plates.py` already builds four pipelines that isolate one variable
per pair — `theirs` (the gate-anpr code, unchanged), `ours-fp32` (.pt, FP32),
`ours-fp16` (.pt, `half`), `ours-trt` (the engine as deployed) — and documents the
decision rule: *the first pair that disagrees names the cause*. A new
`engine/tools/eval_plates.py` imports that reader construction and runs it over
`Egyptian Car Plates dataset/EALPR Vechicles dataset/` (2,085 images, YOLO plate
boxes, class 0, one `.txt` per image).

**Rationale**: verified facts line up behind exactly these suspects. The source
project calls `predict(frame, conf=…, verbose=False)` — no `imgsz`, no precision
argument, so FP32 at ultralytics defaults.

**Correction found while generating tasks (27 Aug), and it moves the whole
diagnosis:** the calling-convention suspects have **already been eliminated in
the working tree**. `engine.yaml`'s `plates` and `plate_chars` blocks now carry
`half: false`, `accelerate: false`, `iou: 0.7`, `conf: 0.35` — matched to
gate-anpr exactly — with a comment recording that the mismatch was measured
("this engine asked for FP16 and a TensorRT plan, and set NMS at 0.45 where
ultralytics defaults to 0.7"). `app.py` passes all four through to
`PlateReader`, verified. So the deployed reader is already FP32 `.pt` with
gate-anpr's thresholds.

Two consequences. **STATUS.md is stale** — it still says "Both plate models
still run FP16 where the source project ran FP32"; that line describes the
committed tree, not the working one, and must be corrected. And **the remaining
suspects are narrower and more serious**: if the owner still sees wrong plates
with the calling convention already matched, the cause is either (a) the port
logic itself in `infer/plates.py` (grouping, letter/digit settling, read order,
normalisation) diverging from gate-anpr's `ocr.py`, or (b) the model's real
capability on site plates as opposed to its own training set, or (c) camera
placement. The `theirs` vs `ours-fp32` pair isolates (a) exactly, which is now
the highest-value comparison in the matrix rather than a formality.

Guessing has already cost one wrong fix (the greyscale-crop episode); STATUS.md
records that lesson.

**Alternatives considered**: (a) eyeball debugging against the webcam — rejected,
not reproducible, locks the camera, and the repo rule is "debug against recorded
material"; (b) replacing the model first — rejected by the owner on 27 Aug
(measure first); (c) writing a fresh comparison harness — rejected, one exists
with the logic already right.

## 2. Ground truth for the 95% read target

**Decision**: the dataset's labels are boxes only, so read-text truth is built
with an assisted labelling mode: `eval_plates.py --label` crops each labelled
plate, proposes the current reader's text, and a person (the owner) confirms or
corrects it. Confirmed rows land in a `plate_truth.csv` beside the dataset
(image, box, text, confirmed-by, date). Target ≥150 confirmed plates ≥100 px wide
— enough that 95% is a claim and not a coin flip.

**Rationale**: the constitution requires calibration on representative data and
human-verified truth; a model must not grade its own homework, so every row is
human-confirmed even when the proposal was right. 150+ keeps the binomial
uncertainty on a 95% claim within a few points.

**Alternatives considered**: treating model output as truth (rejected — circular);
hand-typing without proposals (rejected — slower, no accuracy gain); recruiting
the character-training set of EALPR (not present in what the owner added).

**Honesty note carried into every evidence file**: this dataset is what the
supplied models were trained on. A score here measures *pipeline fidelity* — does
our port reproduce the source project on its own data — not generalisation to the
school's gate. Site-camera captures remain the final check (`tools/record.py`,
owner's hand test), and the evidence file must say which set a number came from.

## 3. What happens with the measurements

**Decision**: because the deployed configuration is already the conservative one
(§1), the ladder runs in the opposite direction to a normal tuning exercise —
it asks *what may be given back*, and what remains once nothing can be.

1. **Confirm the current config is the best of the four.** If `ours-fp32` ties
   `theirs`, the port is faithful and configuration is settled — record it and
   stop tuning.
2. **If `theirs` beats `ours-fp32`, the port is the bug.** Diff `infer/plates.py`
   against `models/Gate/gate-anpr/gate-anpr/anpr/ocr.py` stage by stage on the
   failing crops. This is now the likeliest remaining software cause.
3. **If both are equally good on the dataset but the owner still sees wrong
   plates at the gate**, the software is faithful and the gap is site reality —
   model capability on non-training-set plates, or plate width/angle/lighting.
   Site captures decide, not this dataset (§2 honesty note).
4. **Give acceleration back only if it is free.** With accuracy pinned by the
   truth subset, re-measure FP16 and TensorRT; adopt whichever fastest form
   loses nothing measurable. `build_engines.py` already carries precision
   through `build(half=…)` and `spec.half`, so an FP32-engine option is a small
   CLI addition rather than new machinery — worth it only if FP32-TRT proves
   both faster and lossless. The owner's standing TensorRT preference makes
   this rung worth measuring rather than assuming.
5. **Replacement**, per §4, only if 1–3 leave the target unmet.

Each step's before/after lands in `evidence/`. `VG_NO_TENSORRT=1` and the
`half`/`accelerate` keys in `engine.yaml` are the existing levers; no new
configuration surface is needed.

**Rationale**: P6-FR-038 requires per-change numbers, and the changes worth
numbering are no longer "which precision" — that was already decided by
measurement — but "is our port faithful" and "may we have the speed back".

**Alternatives considered**: re-litigating FP16 as a suspect (rejected — already
measured and already reverted); INT8 (needs a calibration set and risks exactly
the 38-class character model — rejected in 006 and still rejected).

## 4. The replacement contingency (only if every rung fails)

**Decision**: not executed in this feature unless the ladder in §3 exhausts. If
triggered: candidates are fetched from the internet under the owner's 27 Aug
authorisation, each recorded with licence and origin, each measured on the same
truth subset, adopted only if it beats the fixed incumbent (P6-FR-039). The
shortlist to start from, in order of fit: another Egyptian-plate YOLO detector +
character model pairing from the EALPR lineage; a general licence-plate detector
paired with an Arabic-capable OCR (e.g. the PaddleOCR family); a commercial-grade
open ALPR stack if licence terms allow. Retraining on the supplied dataset stays
out of scope per the spec.

**Rationale**: the spec's order of attack; the constitution's model-replacement
path (contract, licence, performance target, evaluation dataset) is exactly what
§§1–3 produce as a by-product.

## 5. Why the boxes are invisible, and the fix

**Decision**: root cause is confirmed, not suspected: `LiveStore._plate_boxes()`
constructs `S.Box(kind="plate", …)` and `schemas.Box.kind` is
`Literal["person", "weapon", "object", "face", "match"]` — pydantic raises on
construction, so the detections response fails whenever a plate is in view. The
console is already correct (`boxColor()` has a `kind === 'plate'` branch;
`types.ts` types `kind: string`). Fix: add `"plate"` to the literal, add optional
`plate_width_px: int | None` (§6), and a regression test that walks the full
path — a `LiveStore` with a stub worker returning one `PlateRead` →
`camera_view(feature="vehicles")` → assert the box survives wire validation with
its kind, colourable severity and width.

**Rationale**: the 24 Aug fix pinned the *request* side only; the failure moved
one layer down and nothing caught it because no test constructs a plate box
through the schema. The full-path test is the spec's explicit requirement
(P6-FR-042).

**Alternatives considered**: reusing `kind="object"` (rejected — `boxColor()`
dispatches on `"plate"`, and the kind is what keeps plate colouring out of every
other feature's rules); loosening `kind` to `str` (rejected — the literal is the
contract doing its job; it caught a real drift, just with no test to report it).

## 6. The width readout (aiming aid)

**Decision**: the engine sends `plate_width_px` on plate boxes — the plate's
width in source-frame pixels, the number `MIN_PLATE_WIDTH_PX` and the vote weight
already use. `CameraFrame` renders it beside plate-kind boxes, green at ≥100 px,
amber below (threshold from the drawing and P6-FR-037's readable line).

**Rationale**: fractions stay the wire geometry (constitution); the pixel width
is display information the engine measured, not layout the client computes — the
client cannot recover source pixels from fractions without knowing the capture
resolution.

**Alternatives considered**: sending frame dimensions and letting the client
multiply (rejected — two fields and a formula to get one number the engine
already has); folding width into the label string (rejected — the tone colouring
needs the number).

## 7. Alerts: derivation, dismissal, permission

**Decision**: an alert **is** a pass — today's passes with status `unknown`,
`blacklist` or `expired` that have no dismissal row. New table
`vehicle_alert_ack(pass_id PRIMARY KEY, by, at, action_taken)`; dismissing writes
the audit entry first, then the row. `GET /vehicles/alerts` assembles them;
`POST /vehicles/alerts/{pass_id}/dismiss` clears one. The Home attention item for
blacklisted cars is untouched — it is the security record; the gate-page alert is
the operational surface. Near-match (P6-FR-048): at assembly time, an unknown
plate is compared against the register with the same one-edit rule the voting
uses (`platetext.same_plate`); exactly one candidate → the suggestion, else
nothing. Dismissal is guard-allowed: `auth/deps.py` gains a narrow
`OPERATOR_WRITE_PREFIXES = ("/vehicles/alerts",)` checked before the `/vehicles`
admin-write rule — still path-decided, no decorator.

**Rationale**: deriving from passes means no alert lifecycle to corrupt and no
state machine (the same argument that kept visits derived in 006). Dismissals are
records the drawing promises ("recorded too, under your name") — RAM would lose
them, so they get the one small table. Guards do the dismissing at a gate; the
actions inside an alert (register, renew) stay admin and the buttons follow
`isAdmin` exactly like today's Register button.

**Alternatives considered**: reusing the Home `attention()` mechanism for all
three kinds (rejected — unknown and expired must never reach Home, and bending
the mechanism to carry page-scoped items complicates the one alerting path that
works); storing alerts as rows (rejected — a second copy of pass facts that can
drift); admin-only dismissal (rejected — the person at the gate is a guard, and
"waits for a person" means the person on duty).

## 8. Day-scoped Movements

**Decision**: store queries that take `since` gain an `until`; `visits`,
`inside`, `gates`, and new `hourly(day)` take the picked day's bounds. Endpoints
gain `day: str = ""` (ISO date, empty = today, validated). "Export this day"
passes the same bound to the existing audited export. Hourly traffic is one SQL
`GROUP BY` over `vehicle_pass.at` by hour, entries and exits separately, hours
present in the day's data only.

**Rationale**: smallest change that makes any recorded day reachable; derived
figures stay derived. "Inside now" for a *past* day is meaningless — the design
keeps it labelled as "now", so `inside` continues to read from today regardless
of the picker, and the scope line says so.

**Alternatives considered**: a generic date-range query API (rejected — the page
asks day questions; ranges are the export's job); materialising daily rollups
(rejected — thousands of rows a day need no cache).

## 9. Visit rows carry their evidence

**Decision**: the visits window query selects the entry and exit pass ids it
already walks past; `VehicleVisit` gains `entry_pass_id` / `exit_pass_id` (and
has-snapshot flags), and the thumbnail is simply the existing
`/vehicles/passes/{id}/snapshot`. Clicking opens the full photograph.

**Rationale**: the photographs already exist per pass with retention handled;
linking beats copying. No new endpoint, no new storage.

## 10. What the drawing shows that will not be built as drawn

**Decision**: two deliberate deviations, both on honesty grounds, both to be
visible in the PR description. (a) The tile sub-line's "14 fps" is dropped — the
ingest layer does not measure capture fps, and printing a guess violates the
truthfulness rule; the sub-line carries gate · direction (and the reader card
carries measured per-read milliseconds instead). (b) The reader-info line's
"reader easyocr" is sample text; the real line prints the actual loaded weights
names and forms (e.g. `plate_detector-640 · TensorRT`), which is what P6-FR-044
wants — a changed or fallen-back model visible where its work shows.

**Rationale**: never show anything untrue outranks matching a mock pixel-for-pixel.

## 11. The reader feed

**Decision**: `VehiclesWorker.analyse()` appends one attempt per `PlateRead` to a
per-camera `deque(maxlen=12)` — timestamp (`frame.captured_at`), camera, display
text or empty, confidence, plausibility, width px, the matched track's current
leader and vote count, and votes-needed. A rolling per-read milliseconds figure
(EMA around `read_frame`) rides the same structure. One endpoint
`GET /vehicles/reader` returns `{cameras: [name, gate, direction, finder, reader,
form, read_ms], attempts: [...], votes_needed}` and calls `note_interest()` so
watching the card boosts the worker exactly like watching a tile does. The
console polls it at 2 s.

**Rationale**: attempts are a by-product of work already done — zero extra model
cost, zero idle cost, and the deque bound keeps it a live window, not a log
(matching the spec's assumption). One endpoint, one poll, one card.

**Alternatives considered**: SSE/websocket push (rejected — nothing else in the
console streams; polling at 2 s is the established idiom); persisting attempts
(rejected — the pass log is the record; attempts are diagnostics).

## 12. What the redesign removes

**Decision**: the "Passing now" list, its per-row Register/Delete controls and
the `DeletePass` usage leave `VehicleGate.tsx`; the `Tile` grid, reason card and
`CamGrid` stay. The engine endpoints for passes and pass-deletion **stay** — the
export and snapshot paths use the same records, the API is contract-tested, and
deleting working audited endpoints buys nothing while the owner may yet want a
maintenance surface elsewhere. The register-from-read path lives on the unknown
alert (prefill from the pass, exactly the current `prefill` ref mechanism).

**Rationale**: the owner's 27 Aug decision with costs accepted is about the
console surface; the recording contract (P6-FR-052) is explicit that nothing
stops being recorded. Removing UI ≠ removing API.

## 13. The real "last import" line

**Decision**: `vehicle_import_run(id, at, added, skipped, rejected, by)` — one
row inserted per import inside the existing import transaction; the register card
shows the latest row or nothing. Mock store shows a plausible mock in mock mode
only.

**Rationale**: the drawing's "Last import: 2,140 rows · 6 skipped · 12 Aug" must
be a fact or absent (P6-FR-053). The audit log is RAM until P3, so it cannot be
the source.

## 14. Cameras-reading tile

**Decision**: `GateSummary` gains `cameras_reading`, `cameras_total`, and
`cameras_note` (names the camera that is not being read and why — offline, or
the worker down). Computed from the configured gate cameras against the vehicles
worker's serving set and each camera's offline state. Replaces the needs-review
tile, which retires with the pass list.
