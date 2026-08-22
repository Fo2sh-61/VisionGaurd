# Implementation Plan: Knife detection — one video per scene, reviewed by a person

**Branch**: `004-knife-detection` | **Date**: 2026-08-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-knife-detection/spec.md`

## Summary

Make the Knife detection page real with the house four-file pattern and the
restricted-zones machinery already in the tree — no new concurrency, no new
endpoint vocabulary, no new storage engine.

- `infer/weapons.py` is **rewritten** to load the owner's `models/knifebest.pt`
  through ultralytics on the GPU, a copy of `infer/persons.py`. The CPU-only
  ONNX decode it holds today goes (its `.onnx` is already deleted from disk).
- `features/weapons.py` (**new**) — `WeaponsWorker`, a copy of `ZonesWorker`:
  runs on every enabled camera, asks the shared person pass whether anybody is
  in view, runs the knife model only then, keeps only knife boxes whose centre
  sits inside a person's box, opens a scene after three sightings spanning a
  second, records through its own `Recorder` into `clips/weapons/`, closes
  after ten seconds without a knife or at two minutes.
- `events/weapons.py` (**new**) — `WeaponSceneStore`, a copy of `SceneStore`:
  table `weapon_scene` with review columns; retention by days, no per-camera
  cap; rows never deleted.
- `api/live.py` overrides the three stubs that are today's to-do list
  (`weapons`, `review_weapon`, `weapon_cameras`), adds `clip_for_weapon`, a
  knife branch in `_boxes`, the capability state and the health stage.
- `api/app.py` wires `_start_weapons` (copy of `_start_zones`), a clip
  endpoint copied from `/breaches/{id}/clip`, seven period labels, and the
  signed-in user as the reviewer. Audit entry first, then the verdict.
- `web/src/pages/Weapons.tsx` is rebuilt from `Intrusion.tsx`: one list with
  Watch / Open and Confirm / False alarm, the period selector, and a grid of
  the cameras being checked drawing knife boxes only.

Every threshold in the design was measured on the two recorded clips
(`research.md` D2) rather than guessed.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React (web console)

**Primary Dependencies**: FastAPI; ultralytics 8.4.7 + torch 2.11 (CUDA) —
the `.pt` loads and predicts correctly in this pinned runtime (verified);
OpenCV `VideoWriter` via the existing `Recorder`; SQLite via `vg.db.connect`

**Storage**: SQLite (`weapon_scene` table) + clip files under
`storage.clips_dir/weapons/`

**Testing**: pytest (engine), `tsc -b --force` (web), pyflakes, the two
recorded clips as the zero-false-scene regression

**Target Platform**: Windows dev laptop (RTX 2080 Max-Q) now, one workstation
later

**Project Type**: web service (engine) + web console — existing structure

**Performance Goals**: first sighting → entry visible ≤ 5 s; knife inference
measured **p50 15.6 ms / p95 22.9 ms** per frame at 640 on this GPU — the same
cost as person detection; the knife pass runs only on frames with a person

**Constraints**: no new threads outside `FeatureWorker`; the knife model
guards itself with one lock (one instance, many camera threads); no
API-breaking change — additive wire fields only, one store-method signature
widened; `.pt` is the artifact, TensorRT engine is a build step on the target

**Scale/Scope**: every enabled camera (1–3 on the laptop, 208 at target).
Cost per camera at rate *r* Hz: one person pass (shared with counting when
both land on the same frame) plus one knife pass only while somebody is in
view. Worst case at 208 cameras × 2 Hz: ~7× this GPU for knives on top of the
same again for people — a P8 sizing matter, stated in §7 of `docs/PLAN.md`

## Constitution Check

*GATE — evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | How this plan satisfies it |
|---|---|
| I. Real-time | Worker inherits `FeatureWorker` rate limiting, boost and result TTL; knife boxes in the enlarged view come from the same poll as every other overlay; the page polls the list every 3 s |
| II. Isolation, efficient inference | Own worker, own recorder; the person pass is the one allowed reuse (`SharedDetection`, cached per frame); the knife model is never called on a frame with nobody in it; counting/zones/track untouched |
| III. Truthful data | Fixture detection and walk-through deleted; capability `weapons` reports LIVE only with the worker running, else a specific reason; every entry carries camera, time, model version, confidence, verdict, reviewer; "police notified" wording removed |
| IV. Reliability, security, privacy | Reviewer is the session user, never a client-typed name; audit entry before the verdict; scenes survive restart, orphans closed on start; retention removes footage of minors after 30 days while the record stays; failures degrade to a reason, `VG_STRICT` makes them fatal |
| V. Complete UX | Detect → record → list → watch → verdict works end to end; every no-video state has a sentence; seven periods; nothing dead |
| Scale constraints | Thread-per-camera at idle rate, same as zones; cost stated above; no hard-coded camera |

**Gate result: PASS.** No violations to justify; Complexity Tracking left empty.

## Simplicity — each requirement and the smallest thing that meets it

| Requirement | Mechanism | Reused from |
|---|---|---|
| FR-001 all cameras | worker serves every enabled camera in the roster | `_start_zones` camera list |
| FR-002 person in view, knife on a person | `SharedDetection.detect(frame)`; skip the knife model when empty; keep boxes whose centre is inside a person box | `features/zones.py::analyse` |
| FR-003 one second to open | a per-camera *candidate* counter: 3 hits spanning ≥ 1 s, dropped after 2 s without a hit | new, ~25 lines |
| FR-004 10 s gap, 2 min cut | the zones state machine with `GAP_SECONDS = 10` | `features/zones.py` constants |
| FR-005/006 entry + video | `weapon_scene` row + `Recorder` + `FileResponse` clip endpoint | `events/zones.py`, `get_breach_clip` |
| FR-007 review, signed-in user, audit first | existing `POST /weapons/{id}/review` + `CurrentUser` dependency + `_log` before the UPDATE | `api/live.py::track` idiom |
| FR-008 no delete | no endpoint, no SQL DELETE | `test_dismissed_weapons_stay_in_the_history` |
| FR-009 30-day retention | `expire()` on start, on each saved clip and on each list read — no thread | `attach_clip`'s mark-then-unlink |
| FR-010 periods | label → `(since, until)` in `app.py`; store takes bounds | `WINDOW_DAYS`, `_start_of_today` |
| FR-011/015 honest states | `_weapons_state()` + `_weapons_stage()` | `_breaches_state`, `_people_stage` |
| FR-012 knife boxes only | `_boxes(camera, "weapons")` branch before the face default | `_person_boxes` |
| FR-013 independence | worker holds `SharedDetection`, never another worker | rule enforced by `base.py` |
| FR-014 alert-ready record | the row already has everything; `LiveStore.review_weapon` is the single future fan-out point | — |
| FR-016 self-refresh | `useAsync(..., 3_000)` | `Intrusion.tsx` |
| FR-017 config | `models.weapons` in `engine.yaml` (weights, conf); timing constants at the top of `features/weapons.py` | `ModelConfig` |

## Project Structure

### Documentation (this feature)

```text
specs/004-knife-detection/
├── plan.md              # This file
├── research.md          # Phase 0 — measurements and decisions
├── data-model.md        # Phase 1 — table, wire and config changes
├── quickstart.md        # Phase 1 — how to prove it works
├── contracts/api.md     # Phase 1 — endpoint contract deltas
├── context.md           # Phase 1 — handoff for the implementing chat
└── tasks.md             # Phase 2 (/speckit-tasks — not this command)
```

### Source Code (repository root)

```text
engine/vg/
├── infer/weapons.py         # REWRITE — WeaponDetector over the .pt (copy persons.py)
├── features/weapons.py      # NEW — WeaponsWorker: candidate + scene state machine
├── events/weapons.py        # NEW — WeaponSceneStore: weapon_scene table (copy events/zones.py)
├── api/live.py              # EDIT — weapons()/review_weapon()/weapon_cameras()/clip_for_weapon(),
│                            #        _knife_boxes, capability state, health stage
├── api/app.py               # EDIT — _start_weapons, clip endpoint, periods, CurrentUser reviewer
├── api/store.py             # EDIT — protocol + MockStore for the widened signatures
├── api/schemas.py           # EDIT — additive WeaponDetection fields; WeaponReview.actor optional
└── config.py                # EDIT — StorageConfig.weapon_clips_dir property

engine/engine.yaml           # EDIT — models.weapons -> knifebest.pt, conf 0.5
engine/tests/
└── test_weapons_live.py     # NEW — detector, state machine, store, API, honesty
engine/tools/benchmark.py    # EDIT (small) — `--model weapons` to time the knife model
models/README.md             # EDIT — the weapons model is now a trained knife model

web/src/
├── pages/Weapons.tsx        # REBUILD from Intrusion.tsx
├── services/api.ts          # EDIT — list/review/clip mapping; "police notified" removed
├── services/wire.ts         # EDIT — additive WeaponDetection fields
├── services/content.ts      # EDIT — delete WEAPON_STEPS
└── types.ts                 # EDIT — WeaponWindow, WeaponDetection; drop WeaponState/WeaponStep
```

**Structure Decision**: existing engine + web layout; two new engine files,
one rewritten, edits elsewhere. No new projects, directories or dependencies.

## Complexity Tracking

None — the gate passed without exceptions.

## Considered and rejected

| Idea | Why not |
|---|---|
| Run the knife model on person crops (PLAN P6 wording) | Measured: removes the empty-room false hits (9 → 1) but *adds* them on the walk-through (1 → 5) and costs 40 ms a batch vs 16 ms a frame. The centre-inside-person test gives the same benefit for free |
| Pre-roll buffer so the video starts before the first sighting | `Recorder` deliberately holds no rolling buffer (memory on every camera all day). The knife is still in view when the scene opens, a second later |
| Start recording on the first hit and delete the file if unconfirmed | Constant recorder churn on a false-positive-prone model; a file delete in the hot path. Confirm first, then record |
| Per-camera switch like restricted zones | Not chosen (Q1 A); the toggle table and its UI are the largest part of 001 |
| Home "Needs your attention" feed | Belongs to the alert spec; turning the `attention` capability LIVE for one kind would misstate the others |
| A retention thread | Three sweep points with no thread do the same job |
| Keeping the ONNX path as a CPU fallback | Needs a second runtime with no CUDA here; the `.pt` falls back to CPU by itself, loudly |
