# Implementation Plan: Camera Onboarding — Real, Complete, Editable

**Branch**: `011-camera-onboarding` | **Date**: 2026-09-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-camera-onboarding/spec.md`

## Summary

Camera setup is the one part of the product an operator meets before anything else works, and
five things on that screen are not true: the recorder channel list is a fixture, two Add buttons
save nothing, a discovered-devices scan returns an empty list that reads as "nothing found",
a ticked capture service at `192.168.1.10` does not exist, and the name and area typed against a
recorder channel are thrown away. Three more things are missing rather than false: four of seven
features cannot be assigned, a camera added is analysed by nothing until the engine restarts, and
a camera cannot be corrected once added.

The approach is deliberately small, because most of the machinery already exists and is already
right. `CameraRegistry` already adds and removes one camera at runtime without disturbing the
other 207. `LiveStore.test_connection` already opens a stream for real and reports the truth about
it. `CameraConfig` already carries and validates every field that is missing from storage.
`merge_cameras` already defines what editing a config-file camera means. `ZonesWorker.set_restricted`
already shows how to change what a running worker watches without a race.

So the work is: **override the one store method that was never overridden**, **probe channels with
the prober that already exists**, **give `FeatureWorker` the ability to gain and lose one camera**,
**persist the six columns `CameraConfig` already has**, and **delete the fictions from the console**.

One behaviour change ships with it, and it is the point of the feature: the `features:` list starts
governing knife detection, restricted-area watching and lost-item search, which today ignore it and
run on every enabled camera.

## Technical Context

**Language/Version**: Python 3.14 (system Python; no `.venv` yet — deliberately blocked on the
re-ID handover) · TypeScript 5 / React 18 for the console

**Primary Dependencies**: FastAPI + Pydantic v2 (`Wire` base, `extra="forbid"`), OpenCV
(`cv2.VideoCapture` for capture and probing), SQLite through `vg.db.connect`. **No new dependency
is introduced by this feature.**

**Storage**: SQLite at `engine/data/visionguard.db`, WAL, one connection per store. The `camera`
and `camera_restricted` tables in `engine/vg/ingest/store.py` are the runtime roster;
`engine/engine.yaml` remains the bootstrap seed and is never written back to.

**Testing**: `pytest` from the repo root (`python -m pytest engine`), fixtures in
`engine/tests/conftest.py` — `authed`, `sign_in`, `bare_live_store`, `live_ish_store`. Type check
with `cd web; npx tsc -b --force`. Dead-code check with `python -m pyflakes engine/vg engine/tools
engine/tests`.

**Target Platform**: Windows 11 workstation, RTX 2080 Max-Q for development; deployment hardware
still undecided and explicitly out of scope here.

**Project Type**: Web application — a Python engine (`engine/`) and a React console (`web/`)
talking over one typed HTTP contract, with `web/src/services/api.ts` as the only place the console
speaks to the engine.

**Performance Goals**: No new latency budget. The `docs/PLAN.md` §7 budgets are unchanged and must
still pass. Two new numbers this feature owns: a feature begins analysing a newly assigned camera
**within 10 seconds** (`P13-FR-014`), and a recorder probe completes within a **stated total
budget** with unreached channels reported as unchecked rather than as failures.

**Constraints**: Adding, editing or removing one camera must not interrupt any camera already
running (`P13-FR-025`). No camera password may appear in any response, log, export or audit entry
(`P13-FR-027`). Every write under `/sources` is administrator-only by path and audited before it
happens.

**Scale/Scope**: Camera count is an input everywhere and a constant nowhere. Seven features, four
new endpoints, six new columns, one new method pair on `FeatureWorker`. Capacity, hardware sizing
and multi-machine partitioning are out of scope by the owner's decision on 1 Sep 2026 and remain
`docs/PLAN.md` P8.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — result at the bottom of this section.*

| Principle | How this feature meets it |
|---|---|
| **I. Real-time camera experience** | Adding or editing a camera must not stall a running one. `CameraRegistry.add` already stops and starts exactly one worker; feature rewiring starts and stops exactly one thread. The registry is only touched when the stream itself changed — a features-only edit does not reopen the camera. §7 latency budgets are unchanged and re-checked. |
| **II. Feature isolation** | This feature *strengthens* it. Today knife detection and zone watching run on cameras that did not ask for them, which is the shape of the failure this principle exists to prevent. After it, one camera's feature list decides one camera's analysis, and `unwatch` on one worker touches no other worker and no other camera. |
| **III. Truthful data** | The whole feature. The fabricated channel list, the two Add buttons that save nothing, the invented capture service, and the empty scan that reads as a result are four separate breaches on one screen. Every one is named by a requirement and removed. |
| **IV. Reliability, security, privacy** | Credentials keep going through the single existing redaction (`CameraConfig.redacted_source`, `CameraSource.redacted`) and a test asserts a known password reaches none of the new responses. Every write audits first. Path-based admin enforcement is unchanged — `/sources` is already in `ADMIN_PREFIXES`, so a new route under it is admin-only the day it is written. |
| **V. Complete, business-correct UX** | A camera can be set up, corrected and retired from the console alone, with no config-file editing and no restart — which is the outcome, not the API shape. |

**Rules from `AGENTS.md` that bear directly:**

- *Rule 4 — never show anything untrue.* Four fictions removed; the honest-empty and
  honest-unavailable states replace them.
- *Rule 7 — degradation is payload, never a 5xx.* The scan result, the probe result and the bulk
  add result are all 200 with a state and a reason.
- *Rule 8 — a subsystem that fails to start must say so in the UI.* Extended to the moment of
  assignment: choosing a feature whose worker did not start says so then and there, when the
  operator can act on it, rather than only on System Health.
- *Rule 9 — a feature must never require another feature.* `_apply_features` skips absent workers
  independently; a camera assigned five features of which one cannot start gets the other four.
- *Rule 11-shaped — audit before the act.* `self._log(...)` before every write, as everywhere else.

**Post-design re-check (after Phase 1): passed, with one item to watch.** Making the `features:`
list govern knife detection is a behaviour change on a safety-relevant feature, and Principle III
forbids it being silent. It is handled by three things and none of them is optional: the existing
"no camera is set up as a gate" sentence shape reused for knives and zones on System Health, a
`STATUS.md` entry, and a startup log line naming how many cameras are checked for knives. This is
recorded in Complexity Tracking below because it is the one place the design changes what the
product does rather than only what it says.

## Project Structure

### Documentation (this feature)

```text
specs/011-camera-onboarding/
├── plan.md              # This file
├── research.md          # Phase 0 — six decisions, with the code evidence
├── data-model.md        # Phase 1 — entities, columns, validation, state
├── quickstart.md        # Phase 1 — how to prove it works
├── context.md           # Phase 1 — implementation handoff
├── contracts/
│   └── sources-api.md   # Phase 1 — the wire contract for /sources
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # /speckit-tasks — not created here
```

### Source Code (repository root)

```text
engine/
├── engine.yaml                     # comment the seven feature names; no behaviour change
└── vg/
    ├── config.py                   # FEATURES set; CameraConfig.parse refuses an unknown name
    ├── api/
    │   ├── schemas.py              # DvrConnectRequest/Result, DvrChannel, ScanResult,
    │   │                           #   EditCameraRequest, BulkAddRequest/Outcome
    │   ├── app.py                  # PATCH /sources/{id}, POST /sources/bulk; actor + audit on
    │   │                           #   every write; _start_weapons / _start_zones camera lists
    │   ├── store.py                # MockStore fixtures updated to the new shapes
    │   └── live.py                 # connect_dvr OVERRIDE (the missing one), scan, edit_camera,
    │                               #   bulk_add, _apply_features, _unwatch_everywhere
    ├── features/
    │   ├── base.py                 # watch() / unwatch() / _closing() hook; _threads -> dict
    │   ├── zones.py                # _closing override: close the open scene on its own thread
    │   ├── weapons.py              # _closing override: same
    │   └── lostbag.py              # a camera set; refuse interest outside it
    └── ingest/
        └── store.py                # six columns + migration; CameraStore.update()

web/src/
├── types.ts                        # CameraSource, DvrChannel, FoundDevice, ScanResult
├── services/api.ts                 # connectDvr keeps the channels; scanNetwork; editCamera;
│                                   #   addCameras (bulk)
├── i18n/{keys,en,ar.draft}.ts      # new source.* keys; delete source.captureService*
└── components/CameraSources.tsx    # delete the fictions; seven features + their settings;
                                    #   controlled channel rows; edit; find-by-name

engine/tests/
├── test_sources.py                 # NEW — probe, scan, bulk, edit, audit, redaction
├── test_feature_assignment.py      # NEW — watch/unwatch, isolation, the _closing race
└── test_ingest.py                  # extended — the six columns, update(), migration
```

**Structure Decision**: The existing engine/console split is kept exactly. No new package, no new
module, no new layer. Every file above already exists except the two new test files — which is the
strongest evidence available that this feature is finishing something rather than adding to it.
The four-file recipe in `AGENTS.md` does not apply: this is not a new product feature, it is the
configuration surface all seven existing features share.

## Design at a glance

Five pieces, in dependency order. Each is independently shippable and each has its own regression
test in the same commit.

**1 · Truthful recorder probe.** `LiveStore.connect_dvr` — the override that was never written —
builds each channel URL from an operator-supplied `{channel}` template, opens it with the same
`CameraSource` probe `test_connection` uses, and returns every channel with what actually happened.
Bounded concurrency under one total budget; a channel the budget never reached reads as *not
checked*, which is a different answer from *did not answer*. Guarded by a test asserting
`LiveStore.connect_dvr is not MockStore.connect_dvr`, copying the `LiveStore.ask is MockStore.ask`
assertion in `test_ask.py` that exists for exactly this bug class.

**2 · Honest scan.** `POST /sources/scan` returns a state, not a bare list: `available: false`
with a reason, rather than `[]` that reads as "your network is empty".

**3 · The feature list governs.** `_start_weapons` and `_start_zones` take the cameras that asked
for them. `BagWatch` refuses interest outside its set. `CameraConfig.parse` refuses a feature name
it does not know, so a typo is caught at load rather than silently doing nothing forever.

**4 · Assignment without a restart.** `FeatureWorker.watch/unwatch`, and `LiveStore._apply_features`
mapping a camera's list onto the eight workers `LiveStore` already holds. `unwatch` sets a
per-camera flag and returns; the camera's **own thread** closes any open scene through a `_closing`
hook and exits — never across threads, for the reason `ZonesWorker.set_restricted` documents at
length.

**5 · Persistence, editing and bulk.** Six columns onto `camera` with the project's existing
`PRAGMA table_info` + `ALTER TABLE` idiom. `CameraStore.update`. `PATCH /sources/{id}` and
`POST /sources/bulk`, both audited first, both admin-only by path. Then the console loses its
fictions and gains the seven features, their settings, editing, and a way to find one camera among
many.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| **A behaviour change on a safety feature** — knife detection stops on cameras that do not list `weapons`, including `cam-laptop`, the only enabled camera in this repository | `P13-FR-010` is the requirement the owner asked for: "assign each camera to the desired feature(s)". A list that three features ignore is not an assignment. Leaving it would also mean 208 cameras each running the shared person detector and the knife model for a feature nobody asked them to run | Preserving today's behaviour would need every existing camera migrated to carry `weapons`. Half the roster lives in `engine.yaml`, which is out of scope to write, so only the database half could be migrated — leaving two cameras behaving differently for a reason invisible on every screen. Instead the change is made loud: System Health reuses the proven "no camera is set up as a gate" sentence shape, `STATUS.md` records it, and startup logs how many cameras are checked for knives |
| **Mutable `cameras` on `FeatureWorker`**, replacing a list that was safe to read without a lock | `P13-FR-014` and `P13-FR-015`. Without it, assigning a feature means restarting the engine, which interrupts every camera on the site to change one | The spec's Assumptions section records the cheaper alternative — tell the operator a restart is needed — and the owner may still take it. It was not made the default because a restart at site scale is an outage, and because the mutation is genuinely small: one dict, one per-camera Event, and two reads that start taking a lock they should arguably have taken already |
