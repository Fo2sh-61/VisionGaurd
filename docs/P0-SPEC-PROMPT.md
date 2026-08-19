# Spec Prompt — P0 Truthfulness and Safety Net

Use the following as the feature description for `$speckit-specify`.

---

Create one feature specification named **Truthful Production State** for VisionGuard's P0 phase, **Truthfulness and Safety Net**.

This request is for specification only. Do not implement the feature, edit application source code, install dependencies, run migrations, alter the database, or make deployment changes. The only permitted outputs are the normal Spec Kit specification artifacts.

## Authoritative context

Before drafting the specification, read:

- `.specify/memory/constitution.md` — highest project authority.
- `docs/DEVELOPMENT_PLAN.md`, especially sections 1–16, 20–21, 26 P0, and 27–31.
- `PROJECT_ANALYSIS.md` and `HANDOFF.md` only as supporting historical evidence. Where they conflict with the constitution or `docs/DEVELOPMENT_PLAN.md`, the newer authoritative documents govern.

Treat verified repository behavior as evidence, not as a required implementation design. The specification must describe what operators and stakeholders need and why, without prescribing frameworks, database engines, response-envelope types, class structures, environment-variable names, or file-level changes.

## Feature objective

Make the VisionGuard engine and web console safe to demonstrate and evaluate by ensuring that every user-visible claim is truthful, current, attributable to its actual source, and explicit when unavailable.

In a normal operational run, fixture or fabricated data must never silently replace missing live data. A deliberately selected demonstration mode may use fixtures, but every web view must carry an unmistakable, persistent indication that the entire session is using demonstration data. An operator must never be able to confuse a demo register, detection, incident, user, audit entry, notification, camera state, or metric with a real one.

## Actors

- **School administrator:** uses attendance, people, groups, counting, tracking, incident, and camera views to make operational decisions.
- **IT operator:** uses camera onboarding and System Health to diagnose unavailable cameras, models, storage, or subsystems.
- **Reviewer or auditor:** needs user-visible decisions and searches to be traceable and must not receive a false persistence receipt.
- **Product owner or demonstrator:** may intentionally launch demonstration mode and must be unable to present it accidentally as live production data.

## Required user outcomes

1. **Source truth on every product-data surface**
   - Every structured product-data result exposes a consistent, machine-readable source state using the meanings `live`, `unavailable`, or `demo`.
   - An unavailable result includes a specific, actionable reason suitable for display to an operator.
   - The web console presents the source state clearly and consistently without requiring the user to inspect logs, developer tools, or individual records.
   - An empty live result, a measured zero, a stale result, an unavailable subsystem, and demo data remain distinct states.
   - Raw camera media must continue to distinguish current, stale last-good-frame, and never-captured states truthfully.

2. **No silent fixture fallback in normal operation**
   - Missing configuration, a disabled feature, a failed model, a failed database, or an unavailable worker produces an explicit unavailable state; it never substitutes fixtures.
   - Mixed subsystem health is represented honestly: one working feature must remain usable while another explains why it is unavailable.
   - Normal operation cannot enter demonstration mode because a subsystem failed.

3. **Unmistakable demonstration mode**
   - Demonstration mode requires an intentional launch choice.
   - A persistent, prominent banner appears across all authenticated web-console routes for the entire demo session.
   - Demo state survives navigation and cannot be dismissed or hidden by an ordinary user.
   - Demonstration mode must not write fixture events or fixture identities into operational records.

4. **Correct school-local time and attendance meaning**
   - The school-authoritative current date is derived from the configured school timezone, not from UTC or the viewing device.
   - Every historical or current instant is rendered with the UTC offset that applied at that instant, including across daylight-saving transitions and process restarts.
   - Attendance history applies the configured late cutoff consistently; a late arrival must never be relabelled on-time when viewed in person history.
   - Records close to midnight and records spanning a daylight-saving transition remain assigned to the correct school day.

5. **Truthful identity and tracking language**
   - The tracking experience distinguishes a person named by face evidence from a body followed by appearance continuity.
   - If a tracked body has been named through face evidence, the subject summary must not contradict the name by claiming that no face identification exists.
   - Appearance evidence alone must never be described as proving a person's identity.
   - A correction withdraws an identity claim without pretending the underlying sighting did not occur.

6. **No false actions or persistence claims**
   - Controls whose action cannot yet be completed must be implemented, removed, or visibly disabled with a reason; clicking a control must never produce a fabricated success state.
   - Removed or deferred fight detection must not remain as a reachable production workflow or claim that feedback was durably stored.
   - Track searches, clip actions, parent notifications, weapon-review actions, camera actions, and similar workflows must not claim completion or persistence unless the promised effect occurred.
   - People, group, and history views use real enrolled-person and sighting data when available; otherwise they report unavailability rather than fixtures.

7. **Useful degraded, empty, and error states**
   - Every in-scope web page has a purposeful loading, empty-live, unavailable, degraded, and unexpected-error state where applicable.
   - System Health remains usable when described subsystems are broken and identifies the affected subsystem and reason.
   - A failed page request must not erase the known camera roster; cameras remain visible with truthful offline or unavailable status.

8. **Operational safety net**
   - Concurrent operational reads and writes must not fail or lose accepted data under the representative single-site P0 workload.
   - Restart and shutdown release camera, worker, and persistence resources cleanly so the application can restart without manual database or device cleanup.
   - Automated checks must detect regression to silent fixtures, incorrect school dates or offsets, false late status, fake persistence, and contradictory identity language.
   - The documented test count and readiness status must come from an executed check, not an unverified report.

9. **Accurate operator and developer documentation**
   - The root README must describe the real current architecture and run modes.
   - Superseded plans remain recoverable as history but cannot appear authoritative.
   - One clear documentation hierarchy tells contributors where requirements, architecture, operations, current status, and historical material live.

## Scope boundaries

### In scope

- VisionGuard engine and web-console behavior covered by P0.
- Data provenance and unavailable-state behavior for every existing engine/web product surface.
- Demonstration-mode labelling and isolation.
- School-local dates, per-instant timezone offsets, and attendance late-status correctness.
- Tracking identity wording, false/dead controls, removal of deferred fight surfaces, real people/group/history reads, page state completeness, operational persistence reliability, executable quality checks, and documentation consolidation.

### Out of scope

- Building intrusion, weapons, lost-item recording/search, notifications, or other missing feature pipelines.
- Shared person-detection output and inference scheduling, which belong to P1.
- Authentication and role enforcement, which belong to P2. P0 must not imply that current cosmetic roles are a security boundary.
- New durable event schemas, audit storage, retention, erasure, backup, and migration architecture beyond the immediate P0 operational safety requirement; those belong to P3.
- The 208-camera worker-pool and deployment topology redesign, which belongs to P8.
- Wiring the fixture-only mobile prototype. Mobile is not a P0 production surface and must not be represented as released or live.
- Fight detection, licence-plate recognition, model hot-swap, and model accuracy claims.

## Specification requirements

- Write prioritized, independently testable user stories, beginning with an operator distinguishing live, unavailable, and demonstration data.
- Include Given/When/Then acceptance scenarios for normal live operation, intentional demo operation, subsystem startup failure, runtime failure after prior success, empty live data, measured zero, stale camera frames, unavailable history, daylight-saving boundaries, local midnight, late attendance history, tracking identity wording, dead controls, restart, and concurrent persistence activity.
- Define testable functional requirements using stable `FR-` identifiers local to this feature. Preserve references to program requirements `FR-01`, `FR-03`, `FR-04`, `FR-07`, `FR-09`, and `FR-10` from the development plan where relevant, but do not renumber or redefine the program-level requirements.
- Define key domain concepts without implementation details, including Product Data Result, Data Source State, Unavailability Reason, Demonstration Session, School-Local Instant, Degraded Subsystem, and User-Visible Action.
- Define measurable, technology-agnostic success criteria. At minimum cover:
  - zero fixture-backed responses during normal operation;
  - source state visible on every in-scope product-data view;
  - demo indication visible throughout every demo route and impossible to dismiss;
  - correct school date and attendance classification across representative daylight-saving and midnight boundary cases;
  - zero user-visible success confirmations for actions whose effect did not occur;
  - clean restart after normal shutdown;
  - all P0 regression and contract checks passing from one documented command.
- Include assumptions and dependencies. Treat the existing camera ingest, last-good-frame behavior, bounded frame delivery, recognition, enrolment, people detection, appearance tracking, counting history, and System Health as existing partial capabilities that must be preserved.
- Explicitly state that provenance metadata does not itself make unavailable data live and does not authorize mixing demo and operational records.
- Do not select the transport shape for provenance, persistence technology, timezone library, test framework, frontend state architecture, or CI provider. Those are planning decisions.
- Use at most three clarification markers, only when a decision materially changes scope or operator experience and no safe default exists. Prefer the defaults and boundaries above.

## Required quality bar

The resulting specification is ready for planning only when:

- each requirement is observable and testable;
- no requirement depends on a specific code structure or technology;
- each user-visible promise has at least one positive and one failure/degraded acceptance scenario;
- empty, zero, stale, unavailable, and demo are never treated as synonyms;
- the specification does not expand into P1, P2, P3, P8, or P9 implementation work;
- it complies with all five constitution principles, particularly truthful data, visible failure, feature isolation, and complete business-correct workflows.

Return the normal Spec Kit specification and quality checklist. Stop after specification validation and report readiness for clarification or planning. Do not proceed to planning, task generation, or implementation.

---
