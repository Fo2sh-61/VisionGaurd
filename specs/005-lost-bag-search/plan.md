# Implementation Plan: Find a lost bag

**Branch**: `005-lost-bag-search` | **Date**: 2026-08-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-lost-bag-search/spec.md`

## Summary

Tick areas (or cameras inside them), optionally a colour, press Search. One
thread looks at those cameras' current frames with the owner's `bagbest.pt`
for up to a minute; cameras that saw a bag come to the front of the grid,
marked, with the bag outlined. Nothing runs when nobody is searching, nothing
is recorded, and no result ever names a person.

Three things carry the work: a job that polls `last_frame()` instead of a
worker with threads ([research D2](./research.md)); a colour namer that
measures hue in Lab after grey-world normalisation and matches *leniently*
where lighting makes the answer uncertain (D3, measured); and the existing
job-shaped wire, which fits a live search as well as it fitted the footage
search it was drawn for (D4).

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 / React 18 (console)
**Primary Dependencies**: FastAPI, ultralytics 8.4.7 + torch cu128 (already pinned), OpenCV, NumPy — nothing new
**Storage**: **none.** A search lives in memory for its minute and is gone. No table, no file, no clip (spec, out of scope)
**Testing**: pytest (engine), `tsc -b --force` (console); fake registry + fake frames + fake detector, the knife pattern
**Target Platform**: Windows workstation with an NVIDIA GPU; CPU fallback stays loud
**Project Type**: web service + console
**Performance Goals**: a ten-camera search finishes or times out inside 60 s (SC-002); idle cost zero (D8)
**Constraints**: only ticked cameras are analysed, ever (SC-004); a new search discards the old one; no other page's numbers move (SC-006)
**Scale/Scope**: 208 cameras all ticked = one round every ~6 s, ~10 looks each per minute, one thread (D8)

## Constitution Check

| Principle | How this plan meets it | Watch |
|---|---|---|
| I — Real-time | The grid is the live grid; boxes come from the search's own hits within the last few seconds and are dropped after (D5) | a held box over a moved bag — bounded hold, tested |
| II — Isolation | Own model, own lock, own thread, no shared cache; can fail alone and says so (D6); rule 9 test: searches with every other feature off | must not touch `SharedDetection` |
| III — Truthful | Empty result states cameras checked and seconds; unavailable cameras named with reasons; colour hides with a count; capability says why when off | the bare grid after a search — forbidden by P7-FR-012 |
| IV — Safe, private | Nothing saved; no identity anywhere in the path; any signed-in user, no new permission (reveals nothing the live pages do not) | `_boxes` default is faces — branch must sit above it |
| V — Complete | Form → search → grid → open camera works end to end on the first increment; Stop works; nothing dead | `useAutoRun` removed, not left firing into an empty form |
| Scale | On demand, bounded, one thread; cost stated per camera count (D8) | re-measure on the workstation |
| Model evidence | Loaded, timed, scored on the two clips (D1); accuracy on real bags **unmeasured** — a model file present is not acceptance | quickstart §4 asks the owner to put a bag down |

No violations. Complexity Tracking not needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-lost-bag-search/
├── plan.md              # this file
├── research.md          # D1–D9, with the two measurements
├── data-model.md        # the in-memory job, the wire, the config
├── contracts/api.md     # POST / GET / DELETE /lost-items/search, the overlay
├── quickstart.md        # how to prove it works, and what only Mohamed can prove
├── context.md           # handoff for the implementing chat
└── tasks.md             # /speckit-tasks — not this command
```

### Source Code (repository root)

```text
engine/
├── engine.yaml                       # models.bags — the owner's weights
├── vg/infer/bags.py                  # NEW: BagDetector, copy of infer/weapons.py, classes=[0,4,5]
├── vg/infer/colour.py                # NEW: name_colour() — Lab + grey-world + lenient set; no model
├── vg/features/lostbag.py            # NEW: BagSearch — one job, one thread, last_frame() loop
├── vg/api/schemas.py                 # LostQuery reshaped; LostHit + colour; LostResult + counts
├── vg/api/store.py                   # protocol: search_lost, lost_search, stop_lost_search; MockStore
├── vg/api/live.py                    # real search_lost / lost_search / stop; _bag_boxes; _lost_state/_stage
├── vg/api/app.py                     # _start_lost; GET + DELETE endpoints; feature pattern gains lost
└── tests/
    ├── test_lost_bag.py              # NEW: job machine, colour, overlay, endpoints, honest states
    ├── test_no_fixtures.py           # LostQuery call updated
    └── test_api.py                   # REQUIRED routes gain GET + DELETE

web/src/
├── pages/LostItems.tsx               # rebuilt: area tree, colour chips, Search/Stop, pinned grid
├── components/CamGrid.tsx            # + pinned: string[]
├── services/api.ts                   # searchLostItem(cameras, colour); getLostSearch; stopLostSearch
├── services/wire.ts                  # LostQuery / LostHit / LostResult mirrors
├── services/content.ts               # LOST_SINCE deleted
├── app/navigation.ts                 # blurb: "Look for it now"
└── types.ts                          # LostQuery / LostHit / LostResult UI shapes

models/README.md, STATUS.md, docs/PLAN.md   # bagbest described; lost items Real; P7 partial
```

**Structure Decision**: the four-file feature pattern in `AGENTS.md`, minus the
events file — the spec forbids persistence, so there is nothing to write — and
with `features/lostbag.py` holding a job rather than a `FeatureWorker` (D2).
The console is a rebuild of one page plus one new prop on the shared grid.

## Increments

Each stands on its own and leaves the page honest.

1. **Search and find** — detector, job, wire, endpoints, page with area tree
   and pinned grid. No colour. Ships: a bag on a ticked camera marks that
   camera. (P7-FR-001–005, 008–016)
2. **Colour** — `colour.py`, the lenient filter, the hidden count, the chips.
   (P7-FR-006, 007)
3. **Polish** — benchmark row, `models/README.md`, `STATUS.md`, `PLAN.md`, the
   owner's manual check with a real bag.

## What this plan does not do

- Search recorded video. There is none (P7).
- Watch for bags continuously. The thread exists only during a search.
- Detect the model's other eight classes. Out of scope in the spec.
- Track a bag between cameras, or say whose it is.
- Promise colour accuracy. D3 is synthetic; the page hedges on purpose.
