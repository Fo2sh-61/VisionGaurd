# Implementation Plan: Vehicle Gate

**Branch**: `006-vehicle-gate` | **Date**: 2026-08-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-vehicle-gate/spec.md`

## Summary

Read Egyptian plates at a gate, match them against a register the school keeps, and
say which cars are inside. The reading technique comes from `models/Gate/gate-anpr/`;
the plumbing does not — VisionGuard already owns cameras, database, audit, auth and a
console, and this feature plugs into all four through the standard four-file pattern.

Alongside it, restore accelerated inference across the whole repo, because the audit
that preceded this plan found it cold: five engines on disk, none referenced by
config, loaded by a library that is not importable, one built for the wrong input
size. Nothing on screen said so.

**Three decisions carry most of the simplicity in this plan.** Each removes a table,
a subsystem, or a file that a naive port would have added:

1. **Blacklist alerts reuse `attention()` / `acknowledge()`.** The Gate project has
   its own `alerts` table with its own acknowledgement columns. VisionGuard already
   has that mechanism, wired to the Home page and the audit log. → one fewer table,
   one fewer page, and the alert lands where a guard already looks.
2. **Visits are derived from passes, not stored.** The Gate project maintains a
   `visits` table with an `open` flag, opened on entry and closed on exit, plus
   orphan-closing on shutdown. That is a state machine that can corrupt. A window
   function over `vehicle_pass` gives the same answer with no state to go wrong.
   → one fewer table, no open/close lifecycle, no `close_orphans` on shutdown.
3. **Engine selection is one helper, not a subsystem.** `weights_to_load(cfg)` returns
   `<stem>-<imgsz>.engine` if it exists and imports, else the `.pt`, and records which
   it chose. Every runner gains two lines. The naming convention is the one already on
   disk, which makes the size-match rule (P6-FR-032) fall out for free — a 640 config
   simply never names the 480 engine.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 / React 19 (console)

**Primary Dependencies**: FastAPI, ultralytics 8.4.7, torch 2.11.0+cu128, OpenCV,
NumPy. **New**: `openpyxl` (~250 KB, pure Python) for the spreadsheet importer;
`tensorrt_cu12_*` for accelerated inference.

**Storage**: SQLite at `engine/data/visionguard.db` — the same file every other
feature writes to. Plate images as JPEG under `engine/data/plates/<date>/`.

**Testing**: pytest. Baseline **868 passed** at `e9ba8dd`.

**Target Platform**: Windows 11, NVIDIA RTX 2080 Max-Q (development); RTX 6000 Ada
workstation (deployment). Engines are built per machine, never copied.

**Project Type**: Web service + React console.

**Performance Goals**: A pass visible within 5 s (SC-001). Plate reading at ≥5 fps on
one gate camera without starving the person detector that shares the GPU.

**Constraints**: Two models run per plate. The plate model runs every sampled frame;
the character model runs **only on crops the plate model returned** — the same
gating idea that makes knife detection affordable.

**Scale/Scope**: 1 gate camera now, 3–6 later. A register of a few thousand rows.
Tens of passes per hour.

## Constitution Check

*GATE: passed before Phase 0, re-checked after Phase 1.*

| Principle | Gate | Verdict |
|---|---|---|
| I. Real-time camera experience | Plate boxes are fractions, drawn from a live worker with a TTL. Stale results are absent, not shown. | **Pass** |
| II. Feature isolation | `VehiclesWorker` subclasses `FeatureWorker`, owns no threads, and shares no worker with any other feature. Runs with everything else off. | **Pass** |
| III. Truthful data | No fixtures. The design's numbers are placeholders and do not ship. Derived visits are absent, not zero, when there is no exit camera. | **Pass** |
| IV. Reliability, security, privacy | Register writes are admin-only by path prefix. Exports write audit first. Images expire at 30 days. | **Pass** |
| V. Complete UX | All three tabs from the design, every state named — no camera, no model, empty register. | **Pass** |

**Watch items carried into design:**

- `/vehicles` must be added to `ADMIN_WRITE_PREFIXES`, not `ADMIN_PREFIXES` — reading
  the register is a guard's job, writing it is not.
- `_boxes(camera_id, "vehicles")` must branch **above** the face default, for exactly
  the reason recorded in `live.py:267` about knives: falling through would draw a
  person's name beside a car.
- The plate model must not be given to any other feature's worker.

## Project Structure

### Documentation (this feature)

```text
specs/006-vehicle-gate/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── context.md           # Phase 1 — implementation handoff
├── contracts/
│   └── vehicles-api.md  # Phase 1
└── checklists/requirements.md
```

### Source Code (repository root)

```text
engine/vg/
├── platetext.py                 NEW  pure Arabic plate normalisation — no model,
│                                     no I/O. Sits beside clock.py.
├── infer/
│   ├── plates.py                NEW  both plate models in one runner
│   └── shared.py                EDIT add weights_to_load() — the engine picker
├── features/
│   └── vehicles.py              NEW  FeatureWorker + multi-frame voting
├── events/
│   └── vehicles.py              NEW  VehicleStore: register + passes
├── api/
│   ├── schemas.py               EDIT wire types
│   ├── app.py                   EDIT endpoints
│   ├── store.py                 EDIT Store protocol
│   └── live.py                  EDIT overrides, overlay branch, capability,
│                                     pipeline stage, attention items
├── auth/deps.py                 EDIT /vehicles in ADMIN_WRITE_PREFIXES
├── config.py                    EDIT CameraConfig.gate / .direction
└── infer/{persons,weapons,bags}.py  EDIT two lines each — use weights_to_load

engine/tools/
└── build_engines.py             NEW  one command, every configured model

engine/engine.yaml               EDIT plates model entry; webcam gets gate 1 / entry

engine/tests/
├── test_platetext.py            NEW  normalisation, plausibility, confusions
├── test_vehicle_voting.py       NEW  voting, dedupe, weak reads kept
├── test_vehicles_store.py       NEW  register CRUD, status, derived visits, import
├── test_vehicles_api.py         NEW  endpoints, permissions, audit, degradation
└── test_engine_selection.py     NEW  picker prefers/rejects, reports its choice

web/src/
├── pages/VehicleGate.tsx        NEW  three tabs
├── components/Plate.tsx         NEW  the Egyptian plate chip — used in 5 places
├── app/routes.tsx               EDIT route
├── components/Sidebar.tsx       EDIT nav entry
├── services/api.ts              EDIT calls
├── types.ts                     EDIT types
└── services/format.ts           EDIT status/category/direction labels and tones
```

**Structure Decision**: The four-file feature pattern from `AGENTS.md`, unchanged.
`platetext.py` is top-level rather than under `infer/` because it loads no model and
touches no camera — it belongs with `clock.py` and `config.py`, and that placement is
what makes it testable in milliseconds with no fixtures.

## Phasing — what "simple, fast" means here

Four slices, each of which leaves the repo green and shippable. A reviewer can stop
after any of them.

| Slice | What lands | Why this order |
|---|---|---|
| **A. Acceleration** | `weights_to_load`, `build_engines.py`, three runners updated, System Health reports the form. | Independent of Vehicles, fixes an existing untruth, and gives the plate models somewhere to land. Smallest slice, largest immediate value. |
| **B. Plate reading** | `platetext.py`, `infer/plates.py`, `features/vehicles.py`, voting tests. | Pure + model layers, provable against still images with no database and no console. |
| **C. Register and passes** | `events/vehicles.py`, endpoints, permissions, audit, import. | The whole product with no page yet; every rule testable by `pytest`. |
| **D. The page** | `VehicleGate.tsx`, `Plate.tsx`, routing, formatting. | Nothing to build until C is honest. |

Slice A is deliberately first. It is the one that fixes something already broken.

## Complexity Tracking

| Decision | Why needed | Simpler alternative rejected because |
|---|---|---|
| Repo-wide acceleration inside a feature spec | The path is cold for every model, and the failure is invisible on screen — a truthfulness bug, not a performance one | Plate-only acceleration would leave a cold path beside a warm one, which is how it went cold the first time |
| A second model (characters) behind the first | Per-character detection is ~99% on Egyptian plates against ~94% for general OCR; the published work is consistent on this | One general OCR pass would be one model, and would be wrong often enough to make the register untrustworthy |
| `openpyxl` as a new dependency | P6-FR-017 asks for Excel, and a school's list arrives as `.xlsx` | CSV-only would drop a stated requirement; asking a school office to convert every file is not a simplification, it is a transfer of work |
| A dedicated `Plate.tsx` component | The plate chip appears in five places across three tabs with identical RTL/Arabic-font rules | Inlining it five times is how the design file does it, and is how the five copies drift |
