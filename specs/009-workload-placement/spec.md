# Feature Specification: Workload Placement — Remove Unread Processor Work

**Feature Branch**: `009-workload-placement`
**Created**: 2026-08-29
**Status**: Draft
**Input**: User description: "Workload Placement — Remove Unread Processor Work. Five independently shippable, config-reversible changes that remove processor work nothing reads, without changing a single detection result. Source: `docs/WORKLOAD-SPEC-PROMPT.md` and the VisionGuard Workload Plan, 29 Aug 2026."

## Why this feature *(mandatory)*

Measured at a 100-camera reference mix, the engine asks for roughly **25 seconds of processor time per second of wall clock** — about a quarter of a second, per camera, every second. About three quarters of that is work **nothing reads**: face recognition running on cameras that cannot produce a face big enough to identify anybody, and video frames decoded and then thrown away because no operator is looking at them.

A machine asked for more than it has drops frames. Dropped frames mean stale overlays, missed arrivals and a System Health page that either reports a fault or — worse — does not notice. It also forces two machines where one should do.

This feature removes the unread work so the same site runs with real headroom on **one 8-core box and one GPU**. It buys **headroom, not cheaper answers**: no detection result may change.

## User Scenarios & Testing *(mandatory)*

### Primary story

An administrator opens System Health on the reference site. Today the page can show a healthy-looking summary while the engine is quietly behind — there is no number on the screen that says "this machine is asked for more than it has". After this feature, the page shows, per feature worker, how much processor and GPU time it is actually using, how deep its queue is, and how many frames it has dropped. When the site is comfortable the page says so; when it is saturated the page says so plainly and names the worker responsible. Meanwhile an engineer can switch each of the five workload changes on or off in configuration alone, re-run the measurement tool, and see the before and after — and re-run the labelled walk-through clip and see that the detections came back identical.

**Acceptance scenarios**

1. **Given** the reference-site configuration and today's settings, **When** an engineer runs the measurement tool before and after all five changes, **Then** the reported processor demand falls from roughly 25 seconds per second to no more than roughly 5 seconds per second, and both figures are printed by the same tool with the same inputs.
2. **Given** the labelled walk-through clip and its 21 ground-truth marks, **When** the clip is replayed with each change applied, **Then** the faces found, the people counted and the plates read are identical to the run before the change, mark for mark.
3. **Given** an administrator on System Health, **When** any feature worker is behind — queue growing or frames being dropped — **Then** the page names that worker, shows its queue depth and dropped-frame count, and states the severity honestly rather than showing a healthy summary.
4. **Given** any one of the five changes has shipped, **When** an engineer reverses it by editing configuration and restarting the engine, **Then** the previous behaviour returns with no code change, no rebuild and no migration.
5. **Given** patrol face recognition is switched off, **When** an operator opens Track a Person, **Then** the page still works and states plainly that names are only attached on identity-tier cameras, rather than silently returning fewer named stops.
6. **Given** face detection is gated to person crops, **When** a camera's shared person pass finds nobody in a frame, **Then** no face work is done on that frame and the attendance register for the clip is unchanged.
7. **Given** a camera nobody has been watching, **When** an operator opens it, **Then** the picture is current and smooth within 1 second and stays within its normal latency budget thereafter; **When** the operator leaves the page, **Then** that camera falls back to the analytics rate within seconds, without affecting any other camera's analysis.
8. **Given** an engineer types a camera count and a feature mix into the measurement tool, **When** it is run, **Then** it prints the processor demand for that site, the same figure per camera, and how many cameras of that mix fit on one 8-core machine and one GPU — without the camera count having been decided in advance.
9. **Given** one of the five changes causes any detection on the labelled clip to differ, **When** the before/after comparison is run, **Then** the change is rejected and not shipped.

### Edge cases

- **A camera goes offline mid-change.** Capture rate, gating and batching must all behave the same on a reconnecting camera as they do today: NO SIGNAL is still shown within its budget, and a dropped stream is never presented as live.
- **Nobody is watching any camera.** Every camera is at the analytics rate. Analysis, recording, zone breaches, knife detection and plate reading must all continue exactly as before — "unwatched" reduces capture rate only, never analysis.
- **An operator opens a camera and immediately looks away, then back.** The camera must not oscillate between rates in a way that costs more than leaving it fast. Settling behaviour is a design question for the plan phase, but the 1-second catch-up applies to every opening, not only the first.
- **Everybody is watching every camera.** The site must degrade honestly rather than silently: if full-rate capture on every camera exceeds the machine, System Health says so and names what is behind. It must not quietly drop analytics frames to protect the live view.
- **Batching with one frame in the queue.** A batch of one must cost no more than an unbatched call and must not add latency waiting for a second frame that never arrives.
- **A feature is switched off or fails to start.** Gating, batching and capture-rate changes must not make one feature depend on another. Knife detection failing must not stop counting; patrol being off must not stop attendance.
- **The GPU driver update fails or is refused.** The bag TensorRT engine deletion still stands on its own; the FP16 re-measurement simply does not happen and is reported as not measured, never estimated.
- **Empty vs zero vs unknown on System Health.** "Zero frames dropped" and "drop count not available" are different answers and must read differently.

## Requirements *(mandatory)*

Requirements are numbered `P8-FR-nnn`. This work sits under `docs/PLAN.md` Phase 8 (Scale) as its precursor; product-level `FR-xx` numbers belong to `docs/PLAN.md` and are not reused here.

### The hard rule

- **P8-FR-001**: No change in this feature MAY alter a detection result. Every change MUST be shown, before it ships, to produce **identical** output on the labelled walk-through clip and its 21 ground-truth marks — the same faces found, the same people counted, the same plates read.
- **P8-FR-002**: A change that saves processor time but cannot demonstrate P8-FR-001 MUST be rejected, not shipped behind a flag.

### Shape of every change

- **P8-FR-003**: Each of the five changes MUST be independently shippable — landing one MUST NOT require any other.
- **P8-FR-004**: Each of the five changes MUST be reversible by editing configuration alone: no code change, no rebuild, no migration, no re-enrolment.
- **P8-FR-005**: Each of the five changes MUST be measured before and after with the project's measurement tool, on the same inputs, and the two figures recorded.
- **P8-FR-006**: Where a change can be made in configuration rather than code, the configuration MUST be preferred.

### The five changes

- **P8-FR-007**: Patrol face recognition MUST default to off. The processor cost patrol was incurring MUST be measured and recorded, so the decision to re-enable it later is made on a number.
- **P8-FR-008**: With patrol off, any page whose answer depends on patrol-tier names MUST state plainly that names are attached only on identity-tier cameras. It MUST NOT silently return a thinner answer.
- **P8-FR-009**: Face detection MUST run only on person regions produced by the existing shared person pass, not on whole frames — on identity-tier cameras and on any re-enabled patrol camera. This is the only change that can alter a result and is bound by P8-FR-001.
- **P8-FR-010**: The shared person pass MUST be able to run frames that are already queued behind it as a single call. The frame-to-detection correspondence MUST be unchanged: boxes returned for a frame MUST be the boxes for that exact frame.
- **P8-FR-011**: Batching MUST NOT hold a frame waiting for company. A single queued frame MUST be run immediately.
- **P8-FR-012**: A camera that no operator has open MUST be captured at the analytics rate (or from a lower-rate camera sub-stream). A camera an operator has open MUST be captured at the full live rate.
- **P8-FR-013**: The change in P8-FR-012 MUST NOT alter what analysis runs, only how often frames are captured. Recording, zone breaches, knife detection, counting and plate reading MUST behave as they do today.
- **P8-FR-014**: A camera MUST return to full capture rate as soon as an operator opens it, and MUST be showing a current, smooth picture **within 1 second** of being opened. This 1 second is the catch-up on opening only; once caught up, the camera-to-screen budget in `docs/PLAN.md` §7 (≤ 400 ms) applies unchanged, and MUST NOT be relaxed by this feature.
- **P8-FR-015**: A camera MUST fall back to the analytics rate promptly once no operator has it open — within seconds, not minutes. The saving is lost if a camera anyone glanced at stays expensive.
- **P8-FR-016**: While a camera is catching up, the picture MUST NOT be presented as LIVE if it is in fact stale. Existing freshness and NO SIGNAL behaviour applies unchanged.
- **P8-FR-017**: The bag model's precompiled acceleration artefact MUST be removed, and the bag model measured again without it.
- **P8-FR-018**: The GPU driver MUST be brought current **before** any half-precision re-measurement is attempted. No acceleration artefact MAY be rebuilt before the driver is current.
- **P8-FR-019**: If the half-precision re-measurement is not performed, the result MUST be reported as not measured. It MUST NOT be estimated or carried over from an older driver.

### Reliability — the priority

- **P8-FR-020**: System Health MUST show, per feature worker, its real processor share, its real GPU share, its queue depth and its dropped-frame count.
- **P8-FR-021**: Saturation MUST be visible. When a worker is behind, System Health MUST name it and reflect that in its severity, never presenting a healthy summary over a saturated machine.
- **P8-FR-022**: Any of those figures that cannot be obtained MUST be shown as unavailable with a reason. A missing measurement MUST NOT be rendered as zero.
- **P8-FR-023**: Enabling, gating or failing any one feature MUST NOT change the behaviour, availability or reported health of another.
- **P8-FR-024**: The latency budgets in `docs/PLAN.md` §7 MUST still be met on the deployment hardware after every change, and MUST be re-checked after each one.
- **P8-FR-025**: System Health MUST remain a 200 response describing degradation, never a server error, however saturated the machine is.

### Measurement — sizing a site whose camera count is not yet decided

- **P8-FR-026**: The camera count MUST be an input to the measurement, never a constant written into it. The same method MUST answer the question at 10 cameras, at 100 and at 208 without being rewritten.
- **P8-FR-027**: The whole-site figure MUST be produced from a stated per-feature camera mix — how many cameras run attendance, counting, intrusion, track, vehicles — not from an assumption that every camera runs every model.
- **P8-FR-028**: The saving MUST be stated **per camera** as well as per site, so that "what does one more camera cost" is answerable without re-running the whole measurement.
- **P8-FR-029**: The project's existing measurement tool MUST be extended to take a camera count and a feature mix and report, in one run: the whole-site processor demand in seconds per second, the same figure per camera, and how many cameras of that mix fit on one 8-core machine and one GPU while still meeting the `docs/PLAN.md` §7 latency budgets. Hardware is then sized from a number rather than from arithmetic somebody redoes by hand.
- **P8-FR-030**: The before and after figures for SC-001 MUST both come from that same tool, run the same way, on the same inputs.
- **P8-FR-031**: The tool MUST report what it measured and what it assumed, separately. A per-model timing taken on this machine and a projection to a camera count nobody has built MUST NOT read as the same kind of fact.

## Success Criteria *(mandatory)*

- **SC-001**: For the same set of cameras, processor demand drops by at least three quarters — at the 100-camera reference mix, from about 25 seconds per second to **no more than about 5 seconds per second**. Per camera that is about 0.25 seconds of processor time each second falling to about 0.05. Both figures come from the same measurement, run the same way, before and after.
- **SC-002**: Detections on the labelled walk-through clip are **identical** to today — the same faces found, the same people counted, the same plates read, against all 21 ground-truth marks.
- **SC-003**: System Health shows true per-worker processor and GPU load, queue depth and dropped frames, and names any worker that is behind. No page silently degrades.
- **SC-004**: Each of the five changes can be reversed by editing configuration alone, and reversing one does not disturb the other four.
- **SC-005**: Somebody can type in a camera count and a feature mix and be told, from measurement, how many machines that site needs — and at the reference mix, **one 8-core box and one GPU** is shown to carry at least 100 cameras with headroom. The answer must not require the camera count to be known in advance.
- **SC-006**: Every latency target in `docs/PLAN.md` §7 that passes today still passes after all five changes.

## Out of scope

Measured correct — do not touch:

- The single shared person pass fanned out to four features.
- Knife detection gated to person-present frames.
- Bag detection gated to demand (only while somebody is looking).
- Plate reading at full precision on the un-accelerated weights. **Do not "optimise" its accuracy or its precision** — the current settings are matched to the source project on measurement.
- ByteTrack and the appearance colour matcher running on the processor.
- The boost scoped to the feature actually being watched.

Also out of scope:

- Any new model.
- Re-enabling patrol on a gated pipeline — that is a separate product decision, made later on the number this feature measures.
- Scaling to 200+ cameras. That needs the Phase 8 thread-contention measurement, which has not been made.
- Any refactor beyond the five changes named above. Extending the measurement tool (P8-FR-029) is measuring work, not a sixth product change: it touches no production path and no detection.
- Rebuilding any acceleration artefact before the GPU driver is current.

## Constitution check *(mandatory)*

The four principles under load here:

- **I — Real-Time Camera Experience.** Change 4 touches the trade the capture loop was built around: full-rate capture exists so a watched camera looks current. Dropping unwatched cameras to the analytics rate must not make a camera an operator has just opened look stale, and a stale feed must still never be labelled LIVE. This is why change 4 ships **last**, and why P8-FR-021 re-checks the §7 budgets after every change.
- **II — Feature Isolation, Efficient Inference.** This whole feature is Principle II's second half: reuse expensive inference rather than repeat it. The first half must survive it — P8-FR-020 requires that gating face detection behind the shared person pass, or batching that pass, does not make any feature depend on another being enabled or healthy. Change 2 in particular creates a real coupling risk: face recognition would begin consuming an output that person detection produces.
- **III — Truthful Data.** Two obligations. Detections must not change (P8-FR-001), because a cheaper answer presented as the same answer is a false one. And a figure that cannot be measured — the half-precision number after a driver update that did not happen, a per-worker load the host will not report — must read as unavailable with a reason, never as zero (P8-FR-016, P8-FR-019).
- **IV — Production Reliability.** Saturation must be visible, not silent (P8-FR-017, P8-FR-018), and System Health must keep describing degradation as payload rather than failing (P8-FR-022). Every change must be reversible by configuration alone (P8-FR-004), so a change that misbehaves on site is backed out by an operator edit rather than a redeploy.

No fixtures, random values or fake persistence are introduced. No face-versus-clothing evidence is merged. No permission decision moves to the browser.

## Assumptions

- The measured figures quoted here — about 25 seconds of processor time per second at the reference mix, and about 31% saved on the bag model by deleting its acceleration artefact — come from the VisionGuard Workload Plan of 29 Aug 2026. **That document is not in this repository.** The plan and tasks phases should either bring it in or reproduce its numbers from a fresh run, so that every claim in this spec traces to something a reader can check.
- Two adjacent documents *are* in the working tree, untracked: `VisionGuard-Deployment-Decision.html` and `VisionGuard-Hardware-Buildlist.html`. The first makes the same argument in a different unit — 442 inferences per second at a realistic feature mix, and a 2-versus-9 GPU spread depending on software choices rather than hardware. It supports SC-005 but is not the source of the 25 s/s figure. Neither is committed; both should be, or their numbers folded into `docs/PLAN.md` §7.
- **The site's final camera count is not decided.** The owner's goal is a system that scales up as cameras are added without the hardware bill climbing with it. So no figure here is written as "the 100-camera answer": 100 is the reference mix used for the before/after comparison, nothing more. Every figure is also stated per camera, and the camera count is something you type in rather than something the tool assumes.
- "About 5 seconds per second" is a ceiling, not a target to tune to. Any figure at or below it satisfies SC-001.
- Patrol is currently on at 0.5 Hz in the shipped configuration; change 1 is therefore a change of default behaviour on an existing deployment, not a new option.
- "Identical detections" is judged on the labelled walk-through clip against its 21 ground-truth marks, plus the plate readings — that is the regression evidence the project already owns. No comparison harness for this exists today; providing one is design work for the plan phase, not a sixth product change.
- Change 4's 1-second figure is the catch-up an operator sees when opening a camera that was idling. It is deliberately separate from, and does not relax, the ≤ 400 ms camera-to-screen budget that applies once the camera is caught up.
- Extending the measurement tool to report a whole-site figure, a per-camera figure and a cameras-per-machine figure is agreed and in scope (P8-FR-029). It is a tool, not a product path: it must never be wired into anything an operator sees.
- Per-worker processor and GPU share is assumed obtainable from the host operating system on the deployment machine. If it is not, P8-FR-019 governs: the figure reads as unavailable with a reason.
- The GPU driver update (change 5) is an operator action on the deployment machine, not something this feature performs.
- No database schema change, migration or re-enrolment is expected by any of the five changes.
