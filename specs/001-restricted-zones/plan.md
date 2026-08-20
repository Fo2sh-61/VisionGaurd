# Implementation Plan: Restricted Zones — real cameras, full-frame zones, auto-recorded clips

**Branch**: `001-restricted-zones` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-restricted-zones/spec.md`

## Summary

Make the Restricted Zones page real with the least new machinery: a "zone" IS a
camera (full frame), so `GET /zones` serves the real camera roster with a
persisted per-camera toggle, a new `ZonesWorker` consumes the existing shared
person-detection pass and runs a small scene state machine (start recording on
first person, stop after 1 s of nobody, cap at 2 minutes), scenes land in a
SQLite table following the existing `events/` pattern, and the existing
`/breaches` endpoint serves them with a playable clip URL. One clip per camera
is kept; older entries stay listed with an honest "clip replaced" note.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React (web console)

**Primary Dependencies**: FastAPI, ultralytics YOLO via existing
`SharedDetection`, OpenCV `VideoWriter` via existing `Recorder`, SQLite via
`vg.db.connect`

**Storage**: SQLite (`zone_scene` table, `camera.restricted` column) + clip
files under the configured clips directory, `zones/` subfolder

**Testing**: pytest (engine), `tsc -b --force` (web), pyflakes, recorded
labelled clip for pipeline verification

**Target Platform**: Windows dev laptop now, single workstation later

**Project Type**: web service (engine) + web console — existing structure

**Performance Goals**: detection → visible log entry ≤ 5 s; no second
detection pass (shared with counting/track per P1-01)

**Constraints**: no new models, no new concurrency primitives (FeatureWorker
owns threading), no API-breaking changes — only additive wire fields

**Scale/Scope**: all configured cameras (2 on the dev laptop, 208 at target);
one clip per camera bounds storage at ~cameras × 2 min of video

## Constitution Check

*GATE — evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | How this plan satisfies it |
|---|---|
| I. Real-time | Worker inherits FeatureWorker rate limiting and result TTL; page shows live cameras through the existing tiles; log poll on the page keeps entries ≤ 5 s behind |
| II. Isolation, efficient inference | Own worker (`features/zones.py`), no worker sharing; detection shared through `SharedDetection` (the one allowed reuse); a camera that is not restricted never triggers a detector call from this worker; other features untouched |
| III. Truthful data | Fixture zones/breaches deleted from the live path; `capabilities()` flips `breaches` to LIVE with worker running, UNAVAILABLE with reason otherwise; replaced clips say so; open scenes shown as still running |
| IV. Reliability, security, privacy | Toggle writes already admin-only via `ADMIN_WRITE_PREFIXES` (`/zones`); scenes and toggle survive restart in SQLite; recorder failure surfaces as a scene without a clip plus the reason, never a fake save |
| V. Complete UX | Toggle → detect → record → log → watch clip works end to end; Watch clip stops being a dead button; empty/degraded states worded on the page |

**Gate result: PASS.** No violations to justify; Complexity Tracking left empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-restricted-zones/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions and traps
├── data-model.md        # Phase 1 — table + wire changes
├── quickstart.md        # Phase 1 — how to prove it works
├── contracts/api.md     # Phase 1 — endpoint contract deltas
└── tasks.md             # Phase 2 (/speckit-tasks — not this command)
```

### Source Code (repository root)

Follows the house four-file pattern (`AGENTS.md` — "Adding a feature"), except
no `infer/` file is needed (the person model already has one) and no
`engine.yaml` change is needed (the toggle lives in the database).

```text
engine/vg/
├── features/zones.py        # NEW — ZonesWorker: scene state machine
├── events/zones.py          # NEW — SceneStore: zone_scene table (copy sightings.py)
├── ingest/store.py          # EDIT — camera.restricted column + accessor
├── api/live.py              # EDIT — zones()/set_zone_enabled()/breaches()
│                            #        overrides, capabilities(), zones overlay
├── api/app.py               # EDIT — wire worker at startup; clip FileResponse
└── api/schemas.py           # EDIT — additive Breach fields only

engine/tests/
└── test_zones_live.py       # NEW — state machine, replace rule, restart, API

web/src/
├── pages/Intrusion.tsx      # EDIT — cameras-as-zones list, real log, Watch clip
├── services/api.ts          # EDIT — breach clip URL + additive fields
└── services/wire.ts         # EDIT — additive Breach fields
```

**Structure Decision**: existing engine + web layout; two new engine files,
edits elsewhere. No new projects, no new directories.

## Complexity Tracking

None — the gate passed without exceptions.
