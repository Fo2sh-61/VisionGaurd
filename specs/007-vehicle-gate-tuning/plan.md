# Implementation Plan: Vehicle Gate Accuracy & Redesign

**Branch**: `007-vehicle-gate-tuning` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-vehicle-gate-tuning/spec.md`

## Summary

Three strands, in priority order. **Accuracy**: the owner has supplied the EALPR
vehicles dataset (`Egyptian Car Plates dataset/`, 2,085 photos with plate-box
labels), so the "measure first" strategy has something to measure against — a new
`eval_plates.py` tool batches the existing four-reader comparison
(`tools/compare_plates.py`) over it, an assisted labelling mode builds the
human-confirmed text subset the 95% read target needs, and the first disagreeing
pair of readers names the cause of wrong reads instead of anyone guessing.
**Visibility**: the live plate boxes have never drawn because `_plate_boxes` sends
`kind="plate"` and the wire schema's `Box.kind` literal does not include it — every
response fails validation. The web side is already finished (`boxColor()` has the
plate branch; `types.ts` types `kind` as `string`), so the fix is one word in one
literal plus the full-path regression test the last fix lacked. **Redesign**: the
27 Aug drawing's Live tab (alerts, reader table, aiming-aid boxes) and Movements tab
(day picker, hourly chart, snapshots), with the pass list removed per the owner's
decision.

**Six decisions carry the simplicity in this plan.** Each keeps a subsystem from
existing:

1. **The box fix is one word plus one test.** Add `"plate"` to the `Box.kind`
   literal and a `plate_width_px` optional field. No new overlay path — the broken
   one is already right except for the literal.
2. **Measurement reuses `compare_plates.py`'s four readers.** `eval_plates.py`
   imports its reader construction and runs the same theirs / fp32 / fp16 / trt
   matrix over the dataset. No new inference code — measurement before
   modification, and the decision rule ("first pair that disagrees") is already
   documented in that tool.
3. **The reader feed is a bounded deque the worker already owns.** `analyse()`
   appends one attempt per read to a `deque(maxlen=12)` per camera; one new
   endpoint serves attempts + per-camera model info + votes-needed in a single
   poll, boosted by the existing `note_interest()`. No stored log, no idle cost.
4. **Alerts are derived, not managed.** An alert is a today's-pass with status
   unknown / blacklist / expired that has no dismissal row. Only dismissals are
   stored (one small table); there is no alert lifecycle to corrupt. The Home
   attention item for blacklist stays exactly as it is.
5. **Visit thumbnails reuse the pass snapshot endpoint.** The visits window query
   already walks passes; selecting the entry/exit pass ids into the wire type
   makes every thumbnail a link to `/vehicles/passes/{id}/snapshot`. No new image
   storage, no new file handling.
6. **Day-scoping is an `until` bound on queries that already take `since`.**
   `passes`, `visits`, `inside`, `gates` and the new hourly all take the picked
   day's bounds; the endpoints gain one `day` parameter.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 / React 19 (console).

**Primary Dependencies**: unchanged — FastAPI, ultralytics, torch + cu128, OpenCV,
NumPy, openpyxl. **No new packages.** TensorRT engines for both plate models exist
on disk (`plate_detector-640.engine`, `char_detector-640.engine`, built 24 Aug).

**Storage**: same SQLite (`engine/data/visionguard.db`). Two tiny new tables:
`vehicle_alert_ack` (dismissals — they are records, "under your name", so they
survive a restart) and `vehicle_import_run` (the real "last import" line — a shown
figure must have a source). Plus one CSV of human-confirmed plate text under the
dataset folder, and dated evaluation evidence under `specs/007-vehicle-gate-tuning/evidence/`.

**Testing**: pytest. Baseline at plan time: see `context.md` §4 — 3 pre-existing
failures in `tests/test_track_page.py` (dev-proxy and measure-tool tests), none of
them vehicle-related.

**Target Platform**: Windows 11, RTX 2080 Max-Q (dev); RTX 6000 Ada (deployment).
Engines built per machine, never copied.

**Project Type**: Web service + React console — the existing structure.

**Performance Goals**: plate box on the tile while the car is in view — the
overlay poll already runs at the boosted 12 Hz cadence, so the budget is "next
poll after detection", ≪ 1 s. Reader card refresh ≤ 2 s. The evaluation run over
2,085 images finishes in minutes on the dev GPU, not hours.

**Constraints**: ≥95% exact reads on plates ≥100 px wide in the confirmed-text
subset before the accuracy strand closes (P6-FR-037). No accuracy figure appears
anywhere until measured (P6-FR-041). The character model runs only on crops the
plate model returned — the cost gate stays.

**Scale/Scope**: 2,085 dataset images; a register around 2,000 rows; one live gate
camera today (`cam-laptop`, gate 1 entry). One page, three tabs, two new wire
types, six new/changed endpoints.

## Constitution Check

*GATE: evaluated before Phase 0; re-checked after Phase 1 design.*

| Principle | How the plan complies |
|---|---|
| I. Real-time experience | Boxes ride the existing boosted overlay poll; the reader feed is demand-driven via `note_interest()` and dies with the viewer. Nothing new polls while nobody watches. |
| II. Feature isolation, efficient inference | No new model passes: attempts are a by-product of `analyse()` already running. The eval tool runs offline, never against the live engine. A reader change stays inside `infer/plates.py` (P6-FR-040). |
| III. Truthful data | Sample figures from the drawing are excluded by construction: alerts derive from real passes, "last import" from a stored run, tiles stay absent-with-reason. The fps figure in the drawing's tile sub-line is **dropped** — the engine does not measure capture fps and will not print a guess (research §10). Near-match is exactly-one-candidate and phrased as a question. |
| IV. Reliability, security, privacy | Alert dismissal is audited before the write, like every other act. Dismissal is deliberately guard-allowed via a narrow path carve-out (research §7) — reading stays open, register writes stay admin. No biometric surface changes. |
| V. Complete, business-correct UX | The redesign lands whole: removal of the pass list ships together with the alert actions and export that replace its duties, so no capability is orphaned mid-way. |
| Model governance (scale & architecture rules) | Evidence-driven selection is the spine: baseline measured before any change, per-change before/after, replacement only by beating the incumbent on the same set with licence and provenance recorded and owner approval (P6-FR-038/-039). |

**Violations needing justification**: none. Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/007-vehicle-gate-tuning/
├── plan.md              # This file
├── research.md          # Phase 0 — root-cause method and design decisions
├── data-model.md        # Phase 1 — tables, wire types, truth-file format
├── quickstart.md        # Phase 1 — how to validate the feature end to end
├── contracts/
│   └── vehicles-api-changes.md   # Endpoint and wire deltas from 006
├── context.md           # Implementation handoff
├── evidence/            # Dated evaluation outputs land here
└── tasks.md             # /speckit-tasks output — not created by /speckit-plan
```

### Source Code (repository root)

```text
engine/
├── vg/
│   ├── api/
│   │   ├── schemas.py        # Box.kind +"plate", Box.plate_width_px; GateSummary
│   │   │                     #   camera fields; VehicleVisit pass ids; new
│   │   │                     #   GateReaderNow / ReaderAttempt / GateAlert /
│   │   │                     #   TrafficHour wire types
│   │   ├── live.py           # _plate_boxes width; reader feed; alerts; day-
│   │   │                     #   bounded movements; cameras-reading summary
│   │   ├── store.py          # MockStore counterparts for every new method
│   │   └── app.py            # /vehicles/reader, /vehicles/alerts (+dismiss),
│   │                         #   /vehicles/traffic, day params on movements
│   ├── auth/deps.py          # narrow guard-writable carve-out for alert dismiss
│   ├── features/vehicles.py  # attempts deque, read_ms, leader snapshot
│   └── events/vehicles.py    # until-bounds, hourly, visit pass ids,
│                             #   vehicle_alert_ack + vehicle_import_run tables,
│                             #   near-match lookup
├── tools/eval_plates.py      # NEW — dataset evaluation + assisted labelling
└── tests/
    ├── test_vehicle_overlay.py   # NEW — full-path box regression
    ├── test_vehicle_alerts.py    # NEW
    └── test_api.py / test_faces.py …  # existing files gain cases where they fit

web/src/
├── types.ts                  # Box.plateWidthPx (kind already string)
├── services/
│   ├── wire.ts               # mirror the new wire types
│   ├── api.ts                # getVehicleReader, getVehicleAlerts, dismissAlert,
│   │                         #   getVehicleTraffic, day params
│   └── format.ts             # plate-width tone helper
├── components/
│   ├── CameraFrame.tsx       # render width readout beside plate-kind boxes
│   ├── VehicleReader.tsx     # NEW — "What the reader is seeing now"
│   ├── VehicleAlerts.tsx     # NEW — alerts strip
│   ├── VehicleMovements.tsx  # rebuilt: filters, chart, snapshots
│   ├── VehicleRegister.tsx   # latin line, real last-import
│   └── Plate.tsx             # optional latin sub-line
└── pages/VehicleGate.tsx     # Live tab rebuilt; pass list removed

Egyptian Car Plates dataset/EALPR Vechicles dataset/   # owner-supplied, read-only
```

**Structure Decision**: existing web-service + console layout; the feature edits
the vehicle-gate slice of the standard four-file engine pattern plus the console
page it feeds. The only genuinely new module is the offline evaluation tool.
