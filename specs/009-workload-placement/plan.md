# Implementation Plan: Workload Placement — Remove Unread Processor Work

**Branch**: `009-workload-placement` | **Date**: 29 Aug 2026 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-workload-placement/spec.md`

## Summary

Five independent changes remove processor work nothing reads, without altering a single
detection. Four are configuration; one is code. Research (`research.md`) found that most
of the machinery already exists in the tree and is simply unused: `CameraSource` already
separates grab from decode through OpenCV, `Subscription.dropped` already counts dropped
frames, `SharedDetection.passes` already counts model calls, and `accelerate: false` is
already a per-model config key that the plate models use.

The approach is therefore: **surface what exists, change config where config suffices,
and write code in exactly two places** — the face-gating crop path and the capture
grab/retrieve split. A comparison harness ships first, because change 2 cannot be
allowed near the tree until there is something that can prove it changed nothing.

## Technical Context

**Language/Version**: Python 3.11 (engine), TypeScript 5 / React (console)

**Primary Dependencies**: OpenCV (`cv2.VideoCapture`, `FaceDetectorYN`), ultralytics YOLO,
FastAPI + Pydantic, ONNX Runtime (SFace). `psutil` is the one candidate addition, for
process CPU — see Complexity Tracking.

**Storage**: SQLite (`engine/data/visionguard.db`). **No schema change in this feature.**

**Testing**: `pytest` (`engine/tests/`), `npx tsc -b --force`, `pyflakes`.
Fixtures per `AGENTS.md`: `authed`, `bare_live_store`, `live_ish_store`.

**Target Platform**: Windows 11 workstation; RTX 2080 Max-Q (8 GB laptop) is today's
measurement floor, not the deployment machine.

**Project Type**: Web service (Python engine) + React console. Engine-side only, except
one System Health panel.

**Performance Goals**: Site demand ≤ ~5 s of processor time per second at the 100-camera
reference mix (~0.05 s/camera/s), down from ~25 s/s (~0.25 s/camera/s). All `docs/PLAN.md`
§7 budgets still met: person detect ≤ 250 ms p95 (22.3 ms today), knife ≤ 250 ms p95
(17.4 ms today), camera→screen ≤ 400 ms.

**Constraints**: **No detection result may change** (P8-FR-001). Every change reversible
by configuration alone (P8-FR-004). No feature may come to depend on another (P8-FR-023).
System Health stays 200 under all degradation (P8-FR-025).

**Scale/Scope**: Camera count is deliberately **an input, not a constant** — the owner has
not fixed it. Every figure is reported per camera as well as per site. 100 is the
reference mix for the before/after comparison only.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — result at the bottom of this file.*

| Principle | Risk in this feature | How the design answers it |
|---|---|---|
| **I — Real-Time Camera Experience** | Change 4 touches the capture-latency trade directly. Getting it wrong makes every unwatched camera lag when opened. | Grab/retrieve split, not a throttled read loop (research D1). The device buffer is still drained every frame, so the trap `CameraSource.frames()`'s docstring documents cannot occur. The 1 s catch-up budget (P8-FR-014) is met with no queue to drain. §7 budgets re-checked after every change (P8-FR-024). |
| **II — Feature Isolation, Efficient Inference** | Change 2 makes face recognition consume person detection. `features/base.py` exists to forbid exactly the bug this resembles. | `RecognitionWorker` holds `SharedDetection` — a **model** wrapper with its own lock and cache — never `PeopleWorker`. Constitution II expressly permits sharing model instances and forbids sharing workers. T014 is an isolation test that proves attendance survives counting being off. |
| **III — Truthful Data** | Two ways to lie: a cheaper detection presented as the same one, and an unmeasurable figure rendered as zero. | The comparison harness (T002) ships **before** change 2 and is its gate. Per-worker CPU share is *not* obtainable for threads in one process — it is reported as unavailable with a reason rather than invented (research D6). Patrol going off is stated on the page, not silently absorbed (P8-FR-008). |
| **IV — Production Reliability** | Saturation must be visible; every change must be backed out by an operator, not a redeploy. | All five reverse through `engine.yaml` alone. Change 5 becomes `accelerate: false` rather than deleting a file, because a deleted file is not reversible by configuration (research D5). System Health gains a workers stage built from counters that already exist. |

**Gate result: PASS**, with one declared narrowing recorded in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/009-workload-placement/
├── plan.md              # This file
├── research.md          # Phase 0 — D1..D9, the code findings
├── data-model.md        # Phase 1 — no DB change; wire + config shapes
├── quickstart.md        # Phase 1 — how to prove each change
├── contracts/
│   ├── system-health.md # The workers pipeline stage
│   └── config.md        # The four config keys
├── context.md           # Implementation handoff
└── tasks.md             # /speckit-tasks output
```

### Source Code (repository root)

```text
engine/
├── engine.yaml                        # changes 1, 4, 5 — config only
├── vg/
│   ├── config.py                      # patrol_hz default 0.5 -> 0; face_gate; live_capture
│   ├── infer/
│   │   ├── shared.py                  # batch the person pass (change 3)
│   │   └── faces.py                   # detect within a crop, offset back (change 2)
│   ├── features/
│   │   └── recognition.py             # take SharedDetection, gate to person boxes (change 2)
│   ├── ingest/
│   │   ├── source.py                  # grab/retrieve split + watcher count (change 4)
│   │   └── registry.py                # CameraWorker._run drives the split
│   └── api/
│       ├── app.py                     # stream() marks the camera watched
│       ├── schemas.py                 # WorkerLoad wire type
│       └── live.py                    # health(): the workers stage
└── tools/
    ├── benchmark.py                   # --site mode (P8-FR-029)
    └── compare_detections.py          # NEW — the P8-FR-001 gate

web/src/pages/SystemHealth.tsx         # render the workers stage
engine/tests/
├── test_workload.py                   # NEW — gating, batching, capture, reversal
└── test_health_load.py                # NEW — honest load reporting
```

**Structure Decision**: the existing `AGENTS.md` four-file feature pattern does **not**
apply — this feature adds no model, no feature worker and no event writer. It edits
existing seams only. Every file above already exists except two tools and two test files.

## Ordering, and why

Cheapest and safest first, exactly as the spec requires. The ordering is not arbitrary:

1. **T000–T002 first.** Baseline measurement and the comparison harness. Nothing that
   can alter a detection may be written before the thing that proves it did not.
2. **Change 1 (patrol off)** — one config line, zero risk, largest single saving. It also
   *reduces* what change 2 has to be correct about, since patrol cameras stop running
   faces at all.
3. **Change 5 (`accelerate: false` on bags)** — one config line, isolated to a model that
   only runs while somebody watches. Promoted ahead of the code changes because it is
   free and independent. The driver update and FP16 re-measure stay separate and gated.
4. **Change 3 (batching)** — pure throughput, no result can change by construction.
5. **Change 2 (face gating)** — the only change that can alter a result. Ships last of the
   analysis changes, behind the harness, per-camera and opt-in.
6. **Change 4 (capture rate)** — last, as the spec instructs, because it touches the
   live-view latency trade.
7. **System Health** runs alongside and lands before the site is asked to trust any of it.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| **Per-worker CPU share is reported as unavailable, not measured** — a stated narrowing of P8-FR-020 | Feature workers are threads inside one process. The OS attributes CPU to the process. A per-thread number would be an invention, and Principle III forbids inventing one. | Splitting workers into processes would make the number real, but that is P8's multi-process partitioning — a far larger change than this feature, and explicitly out of scope. What is reported instead — process CPU/GPU, plus per-worker inference ms, frames processed, queue depth and drop counts — identifies the expensive worker, which is the operator's actual question. |
| **`psutil` as a new dependency** (process CPU/GPU sampling) | `SystemHealth.cpu_percent` and `gpu_percent` are already declared on the wire and unset. Filling them honestly needs a portable process-CPU reading. | Parsing OS-specific tools by hand is more code and more failure modes on Windows. If `psutil` is refused, the fields stay `None` and read as unavailable with a reason — the feature still lands, with less. |
| **A new tool, `compare_detections.py`, that is not one of the five changes** | P8-FR-001 and P8-FR-002 are unenforceable without it. The spec's Assumptions already record that no such harness exists and that providing one is plan-phase design work. | Eyeballing the clip. Rejected: 21 ground-truth marks across three model families is not an eyeball check, and "identical" is a claim that needs a diff. |

## Post-design Constitution re-check

Re-evaluated after Phase 1 artifacts. **PASS.**

- No fixture, random value or fake persistence is introduced. The new System Health panel
  is built entirely from counters that already increment in production code.
- Face and clothing evidence are untouched; recognition's gates, thresholds and
  accumulator are not modified. Change 2 alters *which pixels YuNet is shown*, nothing else.
- No permission decision moves. No endpoint is added outside the existing path-prefix rules.
- Degradation stays payload: the workers stage reports absent subsystems as unavailable
  with a reason, and `health()` continues to return 200.
- One residual risk, stated plainly: change 2 is the only change that can move a face box,
  and the crop-origin offset (research D3) is where it would happen. That is why T002
  precedes it and T012 gates it.
