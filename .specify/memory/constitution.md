<!--
Sync Impact Report
- Version change: template (unratified) -> 1.0.0
- Modified principles:
  - Placeholder Principle 1 -> I. Real-Time Camera Experience
  - Placeholder Principle 2 -> II. Feature Isolation, Efficient Inference
  - Placeholder Principle 3 -> III. Truthful Data and Traceable Decisions
  - Placeholder Principle 4 -> IV. Production Reliability, Security, and Privacy
  - Placeholder Principle 5 -> V. Complete, Business-Correct User Experience
- Added sections:
  - System Scale and Architecture Constraints
  - Development Workflow and Quality Gates
- Removed sections: none
- Follow-up TODOs: none
-->
# VisionGuard Constitution

## Core Principles

### I. Real-Time Camera Experience
Every feature page that presents a camera MUST show a live, current stream from the camera assigned
to that feature. Interaction, overlays, detections, state changes, and operator actions MUST respond
without perceptible avoidable delay. Pipelines MUST favor bounded latency and current frames over
processing every queued frame; stale work MUST be dropped. A disconnected, delayed, frozen, or stale
feed MUST be identified honestly and MUST NOT be presented as LIVE. Each feature MUST define and test
its latency budget on representative deployment hardware and camera load. A feature is not complete
when its analysis is accurate but too late to support the operator's decision.

Rationale: VisionGuard supports time-sensitive school operations. A delayed result can be as harmful
as a wrong result, and a stale frame presented as live destroys operator trust.

### II. Feature Isolation, Efficient Inference
Each camera stream displayed on a feature page MUST reflect that feature's own running analysis engine
and feature-specific state. A feature MUST remain independently startable, stoppable, observable, and
degradable; enabling or failing one feature MUST NOT silently enable, disable, or misrepresent another.
The implementation MAY share immutable model instances, decoded frames, detections, embeddings, or
other model outputs internally when their semantics, freshness, coordinate space, and configuration
are compatible. Such reuse MUST be explicit in architecture, bounded in lifetime, concurrency-safe,
and invisible to the user. Feature workers and business decisions MUST NOT be shared merely because
they consume the same model output.

Rationale: Independent feature behavior prevents cross-feature logical errors, while safe reuse of
expensive inference avoids wasting GPU, CPU, memory, and camera bandwidth.

### III. Truthful Data and Traceable Decisions
Every value, status, alert, health indicator, camera state, count, identity, confidence, timestamp, and
operator outcome shown to an end user MUST come from real current state or durable recorded evidence.
Production paths MUST contain no fixtures, random values, simulated success, cosmetic authentication,
no-op controls, or fake persistence. If a capability is unavailable, degraded, unverified, or still in
demo mode, the UI and API MUST state that fact plainly. System Health MUST report the actual state and
failure reason of every subsystem. Safety- or identity-relevant results MUST retain provenance,
including camera, time, model/version, confidence, review state, and relevant audit records. Evidence
strengths such as face identity and appearance similarity MUST remain distinct and MUST NOT be
silently promoted into stronger claims.

Rationale: This is the final delivery phase for real users. Honest uncertainty and durable evidence
are mandatory for trust, diagnosis, and accountability.

### IV. Production Reliability, Security, and Privacy
VisionGuard MUST fail safely, visibly, and locally. Exceptions MUST NOT silently switch a production
feature to fixture data or fabricated success. Processes MUST recover from transient camera and
service failures where safe, expose persistent failures, and shut down cleanly. Authentication,
authorization, audit, retention, encryption, secrets handling, and least privilege MUST be enforced
server-side before on-site use. Biometric data, footage, and records concerning minors MUST be
minimized, access-controlled, retained only by explicit policy, and erasable through a documented
process. Destructive or safety-relevant automated actions MUST require the defined human decision
gate. Backups, database migrations, recovery behavior, and upgrade/rollback paths MUST be tested.

Rationale: Reliability includes protecting people and data, not merely keeping processes running.

### V. Complete, Business-Correct User Experience
Development MUST implement the intended business outcome, not merely render the UI or satisfy an API
shape. All user-visible features in the approved product scope MUST work end to end, persist their
effects where promised, handle empty/degraded/error states, and remove or clearly disable actions that
cannot yet be honored. Engineers MUST inspect related workflows and invariants for logical errors,
especially identity, attendance, zone schedules, event review, counting, tracking, permissions, and
time-zone behavior. Small UI changes are expected during development; architecture and tests MUST
keep presentation changes inexpensive without weakening contracts or business rules. Future license
plate recognition MUST remain out of current scope unless separately specified, while extension seams
MUST avoid needless barriers to adding it later.

Rationale: A polished partial workflow can still mislead or block an operator. Completion means the
entire real-world task works correctly and clearly.

## System Scale and Architecture Constraints

- The target organization contains approximately 208 cameras arranged into real sites, areas, and
  zones. Designs MUST use configuration or persistent data, never hard-coded single-camera assumptions.
- Capacity plans MUST state camera count, enabled features per camera, input resolution and FPS,
  inference cadence, model placement, CPU/GPU/VRAM/RAM/network/storage budgets, and failure domains.
- The system MUST support staged load testing up to the 208-camera target using representative streams
  and feature mixes. Claims of scale or latency MUST be backed by measurements on documented hardware.
- Backpressure MUST be bounded. Camera capture, inference, storage, API delivery, and UI rendering MUST
  not create unbounded queues or allow old frames to masquerade as current work.
- Camera and feature scheduling MAY exploit demand-driven inference, batching, hardware acceleration,
  model-output reuse, and per-feature cadence, provided the real-time and isolation principles hold.
- Deployment topology MAY use multiple processes, GPUs, or workstations. The plan MUST identify when a
  single-node design ceases to meet measured service levels and how workloads are partitioned.
- Model selection is evidence-driven. Missing or replacement models MUST be requested from the owner
  early, with an explicit input/output contract, license, performance target, and evaluation dataset.
- The eventual workstation may be powerful, but code MUST remain resource-aware and observable rather
  than depending on unspecified future capacity.

## Development Workflow and Quality Gates

- Begin each feature or correction with verified repository evidence and an explicit end-to-end data
  flow: camera/input -> model or rule -> durable state -> API -> UI -> operator action.
- Define acceptance criteria for correctness, latency, freshness, degradation, persistence, security,
  accessibility, and resource use before implementation.
- Test-first development is REQUIRED for business rules and regression fixes. Unit, contract,
  integration, end-to-end, failure-injection, and representative load tests MUST be applied in
  proportion to risk. Safety-critical and identity-related paths require adversarial and negative cases.
- No feature is DONE while it relies on fixtures, no-op persistence, dead controls, undocumented manual
  steps, or an unvalidated model. Partial readiness MUST be reported explicitly.
- Every model-backed feature MUST have versioned evaluation evidence. Thresholds and accuracy claims
  MUST be calibrated on representative on-site data; a model file being present is not acceptance.
- Reviews MUST check cross-feature effects, concurrency, stale-data behavior, time zones, authorization,
  migrations, retention, recovery, observability, and UX states—not only the edited happy path.
- UI refinements MAY be incorporated incrementally, but contract or schema changes MUST be coordinated
  across engine, web, mobile, tests, and documentation.
- A release candidate requires clean automated checks, zero known critical or high-severity defects,
  no silent failure paths, a documented residual-risk review, and an operator-facing deployment and
  recovery runbook. "No bugs" is pursued through prevention, verification, and transparent triage;
  no absolute defect-free claim may be made without evidence.

## Governance

This constitution is the highest project-level engineering authority. Specifications, plans, tasks,
code reviews, and release decisions MUST demonstrate compliance. When another document conflicts with
it, this constitution governs unless amended first.

Amendments require: (1) a written proposal describing the change and rationale; (2) an impact analysis
covering active specifications, architecture, tests, deployment, privacy, and operator workflows;
(3) owner approval; and (4) a migration plan for any affected implementation. The constitution uses
semantic versioning: MAJOR for incompatible removals or redefinitions of governing principles, MINOR
for new principles or materially expanded obligations, and PATCH for clarifications that do not change
obligations.

Every feature plan MUST include a constitution check before design approval. Every implementation
review MUST cite evidence for applicable quality gates. Before an on-site or production release, the
team MUST perform and record a full compliance review; any exception requires an owner-approved,
time-bounded waiver with risk, mitigation, and removal date. Waivers MUST NOT conceal fake data,
misrepresent system health, bypass authorization, or remove a required human safety gate.

**Version**: 1.0.0 | **Ratified**: 2026-08-19 | **Last Amended**: 2026-08-19
