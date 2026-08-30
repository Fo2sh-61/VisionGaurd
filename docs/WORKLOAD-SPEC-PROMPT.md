# Spec Prompt — Workload Placement: Remove Unread Processor Work

Use the following as the feature description for `$speckit-specify`.
Suggested branch: `009-workload-placement`.

---

Create one feature specification named **Workload Placement — Remove Unread Processor Work**.

This is a specification request only. Do not implement the feature, edit application source, install dependencies, run migrations, alter the database, or make deployment changes. The only permitted outputs are the normal Spec Kit specification artifacts.

## Read first (authority order)

- `.specify/memory/constitution.md` — highest authority. Especially **I** (Real-Time Camera Experience), **II** (Feature Isolation, Efficient Inference), **III** (Truthful Data), **IV** (Production Reliability).
- `docs/PLAN.md` §7 (speed targets) and `STATUS.md` (what is real today).
- `AGENTS.md` — the four-file feature pattern.
- The **VisionGuard Workload Plan, 29 Aug 2026** (companion to the compute audit) — the measured source for this feature.
- `engine/tools/benchmark.py` — the tool every claim in this feature is checked with.

## Why this feature

At the 100-camera reference site the engine asks for roughly **25 seconds of processor time per second** — about three-quarters of it work that **nothing reads**: face detection on cameras that cannot produce a usable face, and video frames decoded and then discarded. A saturated machine drops frames and fails System Health, and it forces two boxes where one should do. The goal is to remove the unread work so the same site runs with real headroom on **one 8-core box and one GPU**.

## The one hard rule

**No detection result may change.** Every change MUST produce identical detections to today on the labelled walk-through clip and its 21 ground-truth marks — the same faces found, the same people counted, the same plates read. Reliability and honest health come first. A change that saves processor time but risks a missed face, count, or plate is rejected. This work exists to buy **headroom, not cheaper answers**.

## In scope — five changes, cheapest and safest first

Each MUST be independently shippable, measured before/after with `benchmark.py`, and reversible by configuration alone.

1. **Patrol face recognition off by default** (`patrol_hz: 0`). One config line, no code. Removes the largest single processor line; measure what patrol actually cost. Re-enabling later on a gated pipeline is a separate product decision.
2. **Gate face detection to person crops** from the existing shared detection — the same pattern already used for knives (person-present frames) and plate characters (detector crops). Entrance cameras, and any re-enabled patrol camera. **This is the only change that can alter a result — it MUST pass the labelled-clip check before it ships.**
3. **Batch the shared person pass.** Collect frames already queued behind the single shared-detection lock and run them as one call. Throughput only; the `(camera, sequence)` cache key is unchanged, so which boxes belong to which frame does not change.
4. **Capture unwatched cameras at the analytics rate** (or a camera sub-stream); keep full-rate capture for any camera an operator has open. Do this **last** — it touches the live-view latency trade the capture loop was built around.
5. **Delete the bag TensorRT engine** (a free ~31% on that model), **update the GPU driver**, and only then re-measure FP16. No engine rebuild spend before the driver is current.

## Reliability requirement (the priority)

System Health MUST expose real per-worker processor and GPU load, queue depth, and dropped-frame counts, so overload is **visible, never silent**. Feature isolation (Principle II) is preserved — enabling, gating, or failing one feature MUST NOT change another. The latency budgets in `PLAN.md` §7 MUST still be met on the deployment hardware after every change.

## Out of scope — do not touch (measured correct)

One shared person pass fanned out to four features; knife gating on person-present frames; bag demand-gating; **plate reading at FP32 on the un-accelerated weights — do not "optimise" its accuracy**; ByteTrack and the colour matcher on CPU; the boost scoped to the feature actually being watched. No new models. No 200-camera scaling work (that needs the P8 thread-contention measurement, which has not been made).

## Keep it minimal

Prefer config over code. Choose the smallest change that removes each waste. Each change ships and reverses on its own. Do **not** propose refactors beyond these five. Few tasks, each small.

## Success criteria (a non-engineer can check)

- **SC-001**: Reference-site processor demand drops from ~25 s/s to **≤ ~5 s/s**, shown by `benchmark.py` before and after.
- **SC-002**: Detections on the labelled clip are **identical** to today — same faces, counts, plates.
- **SC-003**: System Health shows true load and any dropped frames; no page silently degrades.
- **SC-004**: Each of the five changes can be reversed by configuration alone.
- **SC-005**: The 100-camera reference site is shown to fit **one GPU and one 8-core box**.

Mark anything uncertain as **[NEEDS CLARIFICATION: question]** rather than guessing. Confirm the Constitution check, naming Principles I, II, III, and IV as the ones under load here.
