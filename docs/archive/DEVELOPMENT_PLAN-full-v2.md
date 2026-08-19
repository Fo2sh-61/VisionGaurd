> **⚠ SUPERSEDED — history only. Do not plan from this file.**
> The current plan is `docs/PLAN.md`; current state is `STATUS.md`.
> Archived 19 Aug 2026.

# VisionGuard — Development Plan (Authoritative)

**Status:** ACTIVE · **Version:** 2.0.0 · **Created:** 19 Aug 2026
**Governs:** all VisionGuard delivery work · **Supersedes:** `DEV_PLAN.md`, `COMPLETION_PLAN.md`, `docs/INTEGRATION-PLAN.md`
**Baseline commit:** `03f1fd7` (working tree clean except `.specify/memory/constitution.md`, unstaged)
**Constitution:** `.specify/memory/constitution.md` v1.0.0 (ratified 2026-08-19)

> **Labelling convention used throughout.** `[FACT]` = verified against code this cycle, with file reference. `[REPORTED]` = claimed by a document or the owner, not re-verified here. `[ASSUMPTION]` = my working assumption, falsifiable. `[PROPOSAL]` = recommended decision not yet approved. `[OPEN]` = unresolved, needs an owner decision.
> **MUST** = release blocker. **SHOULD** = justified recommendation.

---

## 1. Executive summary

VisionGuard's ingest, inference and event architecture is sound and three features run on real data today. The remaining work is **not** "attach the missing models" — it is four foundations (truthfulness, shared-inference correctness, security, durable events) plus a sequence of slot-fills the architecture was built to receive.

This cycle's verification produced **five findings that change the plan's shape**, none of which appear in the existing planning documents:

| # | Finding | Severity | Evidence |
|---|---|---|---|
| **F1** | **The Store seam's fixture fallback is now unconstitutional.** `LiveStore` silently falls back to `MockStore` fixtures for attendance, track, people, groups, count and intrusion cameras when a subsystem is off. Constitution III forbids fixtures in production paths. | **CRITICAL** | `engine/vg/api/live.py:398-402, 786-788, 729-740, 878-879, 965-968` |
| **F2** | **The person detector runs twice per frame on any camera with both `counting`/`intrusion` and `track`, from two threads, on one shared non-thread-safe model.** Docs claim "detect once, fan out"; only the model *object* is shared, not its *output*. | **HIGH** | `engine/vg/api/app.py:157-161`; `features/people.py:114`; `features/tracking.py:55`; `features/base.py:98-105` |
| **F3** | **Timezone offset is computed once at construction.** Egypt observes DST; every stored and displayed timestamp silently shifts by one hour across a DST boundary until restart. | **HIGH** | `live.py:74, 1053-1076`; `events/sightings.py:116-137`; `events/counts.py:65-78` |
| **F4** | **SQLite runs without WAL or busy-timeout**, with 5+ independent connections across writer threads. At target scale this produces `database is locked` failures, not slowness. | **HIGH** | `identity/gallery.py:125-128`; `events/*.py` (no `journal_mode`/`busy_timeout` anywhere) |
| **F5** | **Thread-per-camera-per-feature will not reach 208 cameras in one process** (~500–700 threads at target). This is an architectural wall, not a tuning problem. | **HIGH** | `features/base.py:98-105`; `ingest/registry.py` |

Consequently the plan front-loads **P0 Truthfulness** and **P1 Inference correctness** ahead of all feature work. Both are cheap, both unblock honest demonstration, and F1/F2 get more expensive to fix the more features are built on top of them.

**Effort:** ~19–27 engineer-weeks to a defensible on-site pilot, single engineer, excluding owner-model lead times and on-site commissioning. Three externally-supplied models (re-ID, trained weapons, fight classifier) remain unscheduled dependencies. **No delivery dates are given** — see §26 for the assumptions behind these ranges.

---

## 2. Verified implementation baseline

Verified this cycle at `03f1fd7`. "Verified" means I read the implementing code; it does **not** mean I executed it.

| Subsystem | Status | Evidence | Note |
|---|---|---|---|
| Camera ingest, reconnect, last-good-frame | ✅ Verified complete | `ingest/source.py`, `ingest/registry.py` | Health counters, stale flagging real |
| Frame bus, bounded, drop-oldest | ✅ Verified complete | `ingest/framebus.py`; `base.py:123` `maxsize=1` | **Constitution-compliant backpressure** |
| Graceful shutdown (<5 s w/ stream open) | ✅ Verified complete | `app.py:52, 212`; `test_shutdown.py` | Owner acceptance test [REPORTED] passed |
| MJPEG stream, event-driven | ✅ Verified complete | `app.py:641-683` | Waits on frame signal, not a timer |
| Demand-driven rate boost | ✅ Verified complete | `base.py:160-172`; `app.py:716-725` | 2 s TTL, self-expiring |
| Face pipeline + gallery (margin gate, model pinning) | ✅ Verified complete | `identity/gallery.py:201-243` | Refuses ambiguous match — correct |
| Attendance register (derived absence, hours-bounded) | ✅ Verified complete | `events/sightings.py:230-297` | Recomputable; provenance retained |
| Enrolment Studio | ⚠️ Partial | `identity/enrolment.py`; `app.py:1182-1298` | Real, but sessions in-memory and **unauthenticated** |
| Person detection + zone occupancy | ⚠️ Partial | `features/people.py` | Occupancy computed then **discarded**; `min_area` never passed |
| Tracking + appearance identity | ⚠️ Partial | `features/tracking.py`, `identity/appearance.py` | Engine real; UI partly fixture; double-inference (F2) |
| Counting | ⚠️ Partial | `live.py:433-515`, `events/counts.py` | One real area; sums without dedup; over-counts |
| System Health | ⚠️ Partial | `live.py:611-725` | Honest per-subsystem; no latency/freshness metrics |
| Intrusion, weapons, lost items, fights, users, audit, notifications | ❌ Fixtures | `api/store.py` (MockStore) | See §11 |
| Mobile app | ❌ Fixtures | `mobile/src/services/api.ts`, `mockData.ts` | Uses `Math.random()`; not wired |
| Authentication / authorization | ❌ **Absent entirely** | Engine grep: zero matches for jwt/oauth/bcrypt/argon2/passlib; `web/src/app/AuthContext.tsx:29-43` | `localStorage.setItem('vg.role','admin')` = full escalation |

**Test suite:** 11 files under `engine/tests/`. `270 passed` is [REPORTED] in `HANDOFF.md`; **I could not execute it** (engine dependencies live in the Windows environment; my bridge reaches the filesystem only). Task `VG-P0-11` re-establishes an executed baseline. No test covers latency, freshness, authorization, or concurrent model access.

---

## 3. Functional requirement matrix

Requirements derived from approved scope (`web/src/app/navigation.ts` = the shipped feature set), constitution, and owner statements. IDs are stable.

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-01 | Attendance register from live face recognition, exportable, auditable | MUST | Partial |
| FR-02 | Browser enrolment with quality gating | MUST | Partial (unauthenticated) |
| FR-03 | Live camera view, per-feature overlays, honest offline state | MUST | Partial (no freshness signal) |
| FR-04 | People counting per area, live + history, honest about dedup | MUST | Partial (over-counts) |
| FR-05 | Restricted-zone breach detection, alerting, evidence clip | MUST | Missing |
| FR-06 | Knife/weapon detection with mandatory human review | MUST | Missing (model pending) |
| FR-07 | Track a person across cameras, face vs appearance distinct | MUST | Partial |
| FR-08 | Lost-item retrospective search over recorded footage | SHOULD | Missing (no recording) |
| FR-09 | People directory, groups, person history | MUST | Partial (history is fixture) |
| FR-10 | Truthful System Health incl. failure reasons | MUST | Partial |
| FR-11 | Server-enforced authentication and RBAC | MUST | **Missing** |
| FR-12 | Durable audit trail for identity-relevant searches | MUST | **Missing** |
| FR-13 | Retention enforcement + documented erasure path | MUST | **Missing** |
| FR-14 | Alert delivery (channels TBD) | SHOULD | Missing |
| FR-15 | Mobile app on real data | SHOULD | Missing |
| FR-16 | Operate at ~208 cameras with measured service levels | MUST | Not designed for |
| FR-17 | Fight detection | DEFERRED | Out of scope this release (§6) |
| FR-18 | Licence-plate recognition | OUT OF SCOPE | Seam preserved only |

---

## 4. Requirement-to-implementation gap analysis

Only non-obvious gaps are listed; §11 carries the full matrix.

| ID | Gap | Root cause | Fix location |
|---|---|---|---|
| FR-01 | Person-mode attendance hardcodes every historical day to `ON_TIME`, ignoring the late cutoff | `live.py:798-806` sets `status=S.AttendanceStatus.ON_TIME` unconditionally | `live.py` + `SightingStore.history()` must apply cutoff |
| FR-03 | UI cannot tell a 100 ms-old overlay from a 2.9 s-old one; both render identically | `Result.age_seconds` exists (`base.py:41`) but is never surfaced through `CameraDetections` | `schemas.py`, `live.py:308-331`, `CameraFrame.tsx` |
| FR-04 | Over-counts (owner observed 4–6 for one person) | `PeopleWorker.analyse` calls `detect(frame.image)` with **no `min_area`**, though the parameter exists and works (`persons.py:138-163`); `conf: 0.35` uncalibrated | `features/people.py:114`, `config.py`, `engine.yaml` |
| FR-04 | "Counted once across overlapping cameras" is rendered when `deduplicated` is true, but nothing can ever set it true | `api.ts:276` renders the claim; `live.py:497` hardcodes `False` | Decision required — §5, `[OPEN-3]` |
| FR-07 | Subject bar always reads "Not identified by face" even when the box shows the name | `TrackPerson.tsx:307` derives `identified` from `seenNow.match === 'face'`; `/tracking/live` sets `match=APPEARANCE` **always and correctly** (`app.py:1105-1107`) | Derive from `seenNow.name` presence |
| FR-12 | `/track` returns an `audit_id` receipt for a record that exists only in RAM and dies on restart | `store.py:830-835` `_log()` appends to a Python list | Durable `audit` table |
| FR-16 | One OS thread per camera per feature | `base.py:98-105` | Worker-pool redesign, §17 |

---

## 5. Code/documentation discrepancies

| # | Document claim | Reality | Action |
|---|---|---|---|
| D1 | `DEV_PLAN.md` §3.4: "Share the person detector — already done, don't break it" | Only the *instance* is shared; inference runs twice (F2) | Correct the claim; `VG-P1-01` implements it for real |
| D2 | `DEV_PLAN.md` §1.4: "187 tests passing"; `HANDOFF.md`: "270 pass" | Neither executed this cycle | Publish an executed count only (`VG-P0-11`) |
| D3 | `COMPLETION_PLAN.md` §4.3: "School hours are still in night-test mode" | **Already fixed** — `engine.yaml:22-25` has 06:30/16:00/08:00 | Archive the document (§9) |
| D4 | `DEV_PLAN.md` Part 5 phase numbering | Stale; contradicts `COMPLETION_PLAN.md` phases | Both superseded by this plan |
| D5 | `README.md`: "Both apps are front end only… Nothing talks to a model yet" | Web is fully wired to the engine | Rewrite `README.md` (`VG-P0-13`) |
| D6 | `engine.yaml:101-114` documents a `face:` model block | [FACT] Declarative only — `FacePipeline()` constructs with its own defaults and never reads it | Either wire it or mark it non-functional |
| D7 | UI states weapon alerts, fight duration and lost-item search timings as commitments | No implementation exists behind any of them | Budgets recorded in §15; no claim shipped before measurement |

---

## 6. Scope and explicit non-goals

**In scope:** FR-01 through FR-16.

**Explicit non-goals for this release:**

1. **Fight detection (FR-17).** No model exists; the UI was already removed from navigation. [PROPOSAL] Complete the removal rather than maintaining dead surface — see `VG-P0-05`. Re-enters as a fresh spec when the owner's classifier and its input contract arrive.
2. **Licence-plate / vehicle recognition (FR-18).** Constitution-mandated non-goal. Seam preserved: the four-file feature contract (§12) already accepts it with no architectural change.
3. **Cross-camera counting de-duplication** — [OPEN-3] below. [PROPOSAL] ship v1 honestly as "summed, not de-duplicated" and remove the UI claim; de-dup is a schema-level decision requiring cross-camera identity, and folding it into counting now couples counting to tracking in violation of Principle II.
4. **True model hot-swap.** Activate-on-restart only (owner decision, already settled).
5. **Multi-site deployment.** Single site, ~208 cameras.

**Open decisions blocking design:**

| ID | Decision | Blocks | Default if unanswered |
|---|---|---|---|
| OPEN-1 | Deployment hardware for 208 cameras (GPU count/model, RAM, storage, network) | §17 capacity plan | Plan assumes 1× RTX 6000 Ada-class + partitioning; unverified |
| OPEN-2 | Do site cameras expose low-res sub-streams? | Decode budget (≈4× swing) | Assume yes; benchmark both |
| OPEN-3 | Counting de-dup in v1, or honest summation? | FR-04 scope, schema | Honest summation (§6.3) |
| OPEN-4 | Retention durations: clips / footage / appearance rows / sightings | Storage sizing, privacy position | 30 d clips, 14 d appearance, 365 d sightings |
| OPEN-5 | Alert channels required at v1 | FR-14 scope | In-app only; email deferred |
| OPEN-6 | Is mobile in scope for this release? | ~2–3 weeks of effort | Yes, read-only subset |
| OPEN-7 | Arabic/RTL at launch? | Layout throughout | No |
| OPEN-8 | Lawful basis + consent flow for biometrics of minors | **Gates deployment entirely** | None — owner/legal must answer |

---

## 7. Target architecture

Preserves what works; changes exactly four things.

```
Cameras ─► CaptureWorker pool (bounded, N workers ≪ N cameras)   ◄── CHANGE 4 (P8)
              └─► FrameBus (drop-oldest, maxsize=1)  [unchanged, compliant]
                     └─► DetectionPass  ── ONE YOLO pass per camera per tick  ◄── CHANGE 1 (P1)
                            │   publishes an immutable, timestamped DetectionSet
                            ├─► PeopleWorker    (counts, zone occupancy)
                            ├─► TrackingWorker  (ByteTrack + appearance)
                            ├─► IntrusionWorker (NEW, P4)
                            └─► WeaponWorker    (NEW, P6; own model, gated on person crops)
                     └─► RecognitionWorker (independent; own models, CPU)
                                    │
                     EventStore (SQLite+WAL → Postgres at scale)  ◄── CHANGE 3 (P3)
                                    │
                     Store seam: LiveStore returns REAL or EXPLICITLY-UNAVAILABLE   ◄── CHANGE 2 (P0)
                                 (fixtures only behind VG_DEMO=1)
                                    │
                     FastAPI + AuthN/AuthZ middleware  ◄── (P2)
                                    │
                            web/  ·  mobile/
```

**Change 1 — `DetectionSet` contract (fixes F2).** One detection pass per camera per tick publishes an immutable result consumed by every body-feature. Required contract fields, per Constitution II: `camera_id`, `frame_sequence`, `captured_at`, `model_name`, `model_version`, `imgsz`, `conf`, `coordinate_space` (`"fractions"`), `boxes[]` with per-box confidence, `produced_at`, `ttl`. Consumers MUST reject a set whose freshness exceeds their budget rather than using it. Ownership: the detection pass owns the model; **no consumer may call the model directly**, which also removes the concurrent-access hazard.

**Change 2 — honest degradation.** `LiveStore` never returns `MockStore` data. Every payload carries `data_source: "live" | "unavailable" | "demo"` plus `unavailable_reason`. Fixtures are reachable only when `VG_DEMO=1`, which forces a persistent UI banner.

**Change 3 — durable events.** Alembic-managed schema; WAL + `busy_timeout`; one connection factory instead of five ad-hoc connections; Postgres migration path defined but not required until measurement demands it.

**Change 4 — bounded worker pools.** Thread-per-camera replaced by a fixed pool sized from measurement, with per-camera scheduling by feature cadence and viewer demand.

**Unchanged and explicitly protected:** frame bus semantics, demand-driven boost, `FeatureWorker` inheritance model, the face/appearance evidence split, fractional geometry, derived absence, the four-file feature contract.

---

## 8. Proposed simplified repository structure

Current layout is good. Only documentation is disordered — four files currently claim to be the plan.

```
VisionGuard/
  engine/                     unchanged
  web/  mobile/  models/      unchanged
  design/                     unchanged (see VG-P0-14 re: stale screenshots)
  specs/                      NEW — spec-kit feature folders (one per phase entering work)
  docs/
    DEVELOPMENT_PLAN.md       THIS FILE — the only plan
    REQUIREMENTS.md           NEW — FR-xx definitions and acceptance criteria
    ARCHITECTURE.md           NEW — extracted from DEV_PLAN Parts 2-3, corrected
    OPERATIONS.md             NEW — runbook: deploy, backup, recover, rollback
    adr/                      NEW — one file per architectural decision
    archive/                  NEW — historical, clearly marked non-current
  .specify/                   spec-kit (constitution lives here)
  PROJECT_ANALYSIS.md         → moves to docs/archive/ once §2 supersedes it
  HANDOFF.md                  stays at root — living status, ≤1 page
  README.md                   rewritten: what it is, how to run, where the docs are
```

---

## 9. Cleanup, migration, archive, and removal plan

No file is deleted. Every move is recoverable through git.

| File | Classification | Action | Rationale |
|---|---|---|---|
| `DEV_PLAN.md` | Archive | → `docs/archive/DEV_PLAN-2026-08-15.md` + banner | Superseded; Parts 2–3 content migrates to `ARCHITECTURE.md`; §0 decisions log migrates to `docs/adr/` |
| `COMPLETION_PLAN.md` | Archive | → `docs/archive/COMPLETION_PLAN-2026-08-10.md` | Audit record; D3 shows it is already factually stale |
| `docs/INTEGRATION-PLAN.md` | Archive | → `docs/archive/` | Self-marked SUPERSEDED; its §1 acceptance criteria migrate to `REQUIREMENTS.md` |
| `PROJECT_ANALYSIS.md` | Archive after supersession | → `docs/archive/` | §2 of this plan is the living successor |
| `HANDOFF.md` | Keep, reshape | Trim to current status only | Must not accumulate into a rival plan |
| `README.md` | Rewrite | `VG-P0-13` | D5: actively wrong |
| `web/src/pages/Fights.tsx` | Remove after verification | `VG-P0-05` | Unreachable; no model; recoverable via git |
| `/fights*` endpoints + `MockStore` fight methods | Remove after verification | `VG-P0-05` | `POST /fights/{id}/feedback` **claims persistence it does not perform** — Principle III violation |
| `ICON.fights` (`navigation.ts:32`) | Remove | With `VG-P0-05` | Dead key |
| `design/shots/*.png` | Verify then archive | `VG-P0-14` | `README.md:46-49` says they no longer match the build |
| `design/` duplicate tree (root copy vs `18-8 design/`) | Merge | `VG-P0-14` | Two near-identical trees; keep dated folder, archive root duplicate |
| `index.html` (root, 0 bytes) | Remove after verification | `VG-P0-14` | Empty; no reference found |
| `_to_delete/` | Owner deletes | Manual | Bridge cannot delete; contains install zip + git lock litter |
| `models/knife detection/kaggle.json` | **Security** | Confirm untracked; owner MUST rotate the key | API credential; now gitignored, but it existed on disk before ignore rules |

---

## 10. Authoritative documentation hierarchy

Exactly one home per artefact. Any document not listed is historical.

| Artefact | Authoritative location |
|---|---|
| Engineering principles | `.specify/memory/constitution.md` |
| Product scope + functional requirements | `docs/REQUIREMENTS.md` |
| Development plan, phases, tasks | `docs/DEVELOPMENT_PLAN.md` (this file) |
| Per-feature specs, plans, tasks | `specs/<NNN>-<feature>/` (spec-kit) |
| Architecture | `docs/ARCHITECTURE.md` |
| Architectural decisions | `docs/adr/` |
| Verified implementation status | §2 + §11 of this file |
| API contract | Generated OpenAPI at `/docs` (`app.py` docstrings are the source) |
| Model inventory | `models/README.md` (hand-written) + `models/MODELS.md` (generated) |
| Deployment + operator runbook | `docs/OPERATIONS.md` |
| Current status snapshot | `HANDOFF.md` (≤1 page) |
| Historical | `docs/archive/` |

**Status vocabulary** — every active status document MUST use exactly these: `verified-complete` · `partial` · `missing` · `blocked` · `deferred` · `removed-from-scope` · `awaiting-model` · `awaiting-on-site-validation`.

**Spec-kit relationship** [PROPOSAL]: this file is the *program* plan. Spec-kit operates at *feature* granularity — each phase below enters `$speckit-specify` → `$speckit-plan` → `$speckit-tasks` when picked up, producing `specs/NNN-<name>/`. Task IDs here (`VG-Pn-nn`) are the stable cross-reference. This plan is not regenerated by spec-kit; it is updated by the maintenance loop (§32).

---

## 11. Feature completion matrix

End-to-end per Constitution: input → processing → persistence → API → authz → UI → operator action → audit.

| Feature | Input | Processing | Persist | API | AuthZ | Web | Mobile | Audit | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| Attendance | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ⚠️ | ⚠️ | `partial` |
| Enrolment | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | `partial` |
| Live cameras | ✅ | ✅ | n/a | ✅ | ❌ | ✅ | ❌ | n/a | ⚠️ | `partial` |
| Counting | ✅ | ⚠️ | ✅ | ✅ | ❌ | ✅ | ❌ | n/a | ⚠️ | `partial` |
| Tracking | ✅ | ✅ | ✅ | ✅ | ❌ | ⚠️ | ❌ | ❌ | ✅ | `partial` |
| Intrusion | ✅ | ⚠️ discarded | ❌ | fixture | ❌ | ✅ | ❌ | ❌ | ⚠️ | `missing` |
| Weapons | ✅ | ❌ | ❌ | fixture | ❌ | ✅ | ❌ | ❌ | ❌ | `awaiting-model` |
| Lost items | ❌ no footage | ❌ | ❌ | fixture | ❌ | ✅ | ❌ | ❌ | ❌ | `missing` |
| People/groups/history | ✅ | ✅ | ✅ | ⚠️ history fixture | ❌ | ✅ | ❌ | n/a | ⚠️ | `partial` |
| Users / auth | ❌ | ❌ | ❌ | fixture | ❌ | cosmetic | ❌ | ❌ | ❌ | `missing` |
| Audit | ❌ | ❌ | ❌ RAM only | fixture | ❌ | ✅ | ❌ | ❌ | ❌ | `missing` |
| Notifications | ❌ | ❌ | ❌ | fixture | ❌ | ✅ | ❌ | ❌ | ❌ | `missing` |
| System health | ✅ | ✅ | n/a | ✅ | ❌ | ✅ | ❌ | n/a | ⚠️ | `partial` |
| Fights | ❌ | ❌ | ❌ | fixture | ❌ | removed | remnant | ❌ | ❌ | `removed-from-scope` |

---

## 12. Critical logical errors

Ranked by consequence. All `[FACT]`.

| ID | Error | Consequence | Location | Fix |
|---|---|---|---|---|
| **E1** | Silent fixture fallback in production paths | An operator cannot distinguish a real register from an invented one — the exact failure that already cost days | `live.py:398, 786, 729, 878, 965` | `VG-P0-01` |
| **E2** | Double inference on one shared, non-thread-safe model from two threads | Wasted GPU **and** a real race: concurrent `predict()` on one ultralytics model may return corrupted or cross-contaminated results | `app.py:157-161` + `people.py:114` + `tracking.py:55` | `VG-P1-01` |
| **E3** | Fixed timezone offset captured at construction | Every timestamp — arrival times, registers, audit — silently shifts one hour across Egypt's DST boundary until restart. Corrupts the attendance record | `live.py:74`; `sightings.py:116`; `counts.py:65` | `VG-P0-03` |
| **E4** | Audit entries live in a Python list | `/track` returns `audit_id` as a receipt for a record destroyed on restart — the UI promises "always logged" | `store.py:830-835`; `app.py:955-966` | `VG-P3-04` |
| **E5** | `POST /fights/{id}/feedback` documents "stored as a negative training example"; stores nothing | API success implying persistence — Principle III | `app.py:827-840` | `VG-P0-05` |
| **E6** | Person-mode attendance forces every historical day to `ON_TIME` | Late history reads as perfect attendance | `live.py:798-806` | `VG-P0-04` |
| **E7** | `min_area` implemented but never passed; `conf` uncalibrated | Over-counting (4–6 for one person) | `people.py:114` | `VG-P5-01` |
| **E8** | Zone enable/disable held in `getattr`-initialised dict | Pausing a zone silently reverts on restart | `live.py:388-396` | `VG-P3-03` |
| **E9** | SQLite without WAL/busy-timeout across 5 connections and multiple writer threads | `database is locked` under load — data loss, not slowness | `gallery.py:125`; `events/*.py` | `VG-P0-06` |
| **E10** | `/tracking/live` reaches into `store._tracked_boxes` via `getattr` | Private coupling; silently returns `[]` if renamed | `app.py:1085-1094` | `VG-P1-04` |
| **E11** | Overlay freshness never surfaced (up to 3 s stale renders as current) | Principle I violation | `base.py:56`; `schemas.py` | `VG-P1-03` |
| **E12** | Track subject badge always "Not identified by face" | Contradicts the named box beside it; erodes trust in the face/appearance distinction | `TrackPerson.tsx:307` | `VG-P0-02` |
| **E13** | Enrolment sessions in memory; restart loses staged photos with no user-facing explanation | Silent work loss | `identity/enrolment.py` | `VG-P4-06` (SHOULD) |

---

## 13. Security and privacy blockers

Every item **MUST** clear before any on-site use.

| ID | Blocker | Detail |
|---|---|---|
| **S1** | **No authentication on any endpoint** | Verified: zero auth libraries in `engine/`. Anyone reaching :8000 pulls the full student directory, attendance history, live streams, and can **enrol or delete faces**. `POST /enrolment/*` and `DELETE /sources/{id}` are unauthenticated mutations |
| **S2** | **Client-side-only authorization** | `AuthContext.tsx:29-43` — `localStorage.setItem('vg.role','admin')` is total escalation. Roles MUST be enforced server-side per endpoint |
| **S3** | **Biometric data of minors, no lawful basis on record** | GDPR Art. 9 / Egypt PDPL 151/2018. Gallery stores vectors not images (good, `gallery.py:22-24`) but DPIA, lawful basis, guardian consent + withdrawal, and a documented erasure path are all absent. **[OPEN-8] gates deployment** |
| **S4** | No encryption at rest for the biometric DB; no TLS in front of the API | Plain SQLite file; HTTP only |
| **S5** | No durable audit (E4) | Searching for a named child leaves no record surviving restart |
| **S6** | No retention enforcement | `clip_retention_days: 30` configured, enforced nowhere; `prune()` methods exist and are never called |
| **S7** | No rate limiting | Enrolment and search endpoints are unbounded |
| **S8** | Credential exposure | `models/knife detection/kaggle.json` was present unignored before this cycle. **Owner MUST rotate that key.** `.env` handling is otherwise correct |
| **S9** | No data-erasure implementation | `remove_person` deletes gallery rows; sightings and appearance rows for that person survive — an erasure request cannot be honoured |

---

## 14. Data model and migration plan

**Existing** (all `[FACT]`, created ad-hoc at first use): `person`, `face_embedding`, `sighting`, `appearance_sighting`, `area_count`, `camera`.

**New tables (P3):**

| Table | Key columns | Notes |
|---|---|---|
| `app_user` | id, email, password_hash (argon2id), role, active, created_at, last_login | Roles server-side |
| `session` | id, user_id, issued_at, expires_at, revoked_at | Or stateless JWT + revocation list — ADR required |
| `audit` | id, at_utc, actor_user_id, action, subject_type, subject_id, detail, ip | **Append-only**; written before result returns |
| `zone` | id, camera_id, name, polygon(JSON), enabled, min_dwell_seconds, schedule(JSON), updated_by | Migrated from `engine.yaml` seed |
| `breach` | id, zone_id, camera_id, started_at, ended_at, person_id?, stable_id?, severity, status, clip_id? | P4 |
| `weapon_detection` | id, camera_id, at_utc, item, confidence, model_version, box, clip_id, verdict, reviewed_by, reviewed_at, dismissal_reason | P6; **no delete endpoint** |
| `clip` | id, camera_id, path, started_at, ended_at, bytes, retention_until | P7 |
| `model_version` | id, feature, filename, imgsz, conf, device, version, active, benchmarked_at, ms_per_frame, precision, recall | P6 |
| `alert_rule` / `notification` | — | P9 |

**Migration mechanics:**

1. `VG-P0-06` **first**: single connection factory, `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`. Cheap, high value, unblocks everything.
2. `VG-P3-01`: adopt Alembic (already a dependency, unused). Baseline migration captures the six existing tables **as they are**; no destructive change.
3. Zones: `engine.yaml` remains bootstrap seed; a startup reconciler inserts missing zones and never overwrites operator edits (the `add_camera` pattern, `app.py:988-1004`).
4. Postgres path: schema written portably; `[ASSUMPTION]` SQLite+WAL suffices below ~50 cameras and Postgres becomes necessary approaching 208 — **to be decided by measurement in `VG-P8-02`, not by preference.**

---

## 15. Real-time streaming and inference design

Per Constitution I, each feature declares a budget, measured on documented hardware. **These are targets, not achievements — nothing here is measured yet.**

| Path | Target (p95) | Measured | Method |
|---|---|---|---|
| Capture → display (MJPEG, watched) | ≤ 400 ms | — | Timestamp burned into a test pattern; camera-to-screen photo timing |
| Capture → detection available | ≤ 250 ms boosted | — | `Result.at` vs `produced_at` |
| Overlay freshness while watched | ≤ 200 ms | — | New `age_ms` field (`VG-P1-03`) |
| Intrusion breach → visible | ≤ 5 s | — | Synthetic zone entry on the labelled clip |
| Weapon detection → review queue | ≤ 2 s | — | Injected frame |
| Operator action → confirmed | ≤ 500 ms | — | API timing |
| Camera drop → NO SIGNAL shown | ≤ 2 s | — | Kill the stream, observe |
| Reconnect | ≤ 10 s | — | Restore, observe |
| Lost-item search | ≤ 60 s | — | P7 |

**Design rules (already partly satisfied):** bounded queues everywhere (`maxsize=1` drop-oldest — compliant today); analysis skips rather than queues when not due (`base.py:131-136` — compliant); results carry TTL and read as absent when stale (`base.py:176-182` — compliant, but **the staleness is invisible to the UI**, which `VG-P1-03` fixes); a frame older than its consumer's budget MUST be dropped, never processed late.

**Instrumentation (`VG-P1-05`):** per-camera per-feature histograms for capture→analyse, analyse duration, queue depth, drops, and stream client count — exposed on System Health and to Prometheus.

---

## 16. Feature isolation and output-sharing design

`DetectionSet` (§7 Change 1) is the only sanctioned sharing point. Its contract:

| Property | Rule |
|---|---|
| Meaning | "Persons detected in one frame by one model configuration" — nothing feature-specific |
| Provenance | `model_name`, `model_version`, `imgsz`, `conf` travel with every set |
| Coordinate space | Fractions, origin top-left, post-rotation. Never pixels across a boundary |
| Freshness | `captured_at` + `produced_at`; consumers reject beyond their own budget |
| Ownership | The detection pass owns the model. **No consumer may call the model directly** — this is what removes E2's race |
| Concurrency | Immutable after publish; consumers never mutate |
| Lifecycle | Invalidated on camera restart, model change, or config change |
| Failure | Detection failure → consumers report `unavailable` with reason; they MUST NOT fall back to a previous set |

**What stays unshared, by rule:** feature workers, event state, thresholds, business decisions, review workflows. A camera running `counting` and `track` shares one detection pass but has two fully independent workers, two independent failure domains, and two independent enable/disable switches.

**Isolation test (`VG-P1-06`):** with `counting` and `track` both on, killing the tracking worker MUST leave counting unaffected and MUST make the track page say why — asserted in an automated test, not by inspection.

---

## 17. 208-camera capacity strategy

**1. Current proven capacity `[FACT]`:** 1 camera, 4 features, one process, on an RTX 2080 Max-Q. Nothing beyond this is measured.

**2. Required architectural changes:**

| Wall | Why it fails | Change |
|---|---|---|
| Thread explosion (F5) | 208 capture + up to 208×3 feature threads ≈ 500–700 OS threads; GIL contention and scheduler thrash | Bounded worker pools; cameras become work items, not thread owners |
| Decode | 208 × 1080p H.264 cannot be CPU-decoded | NVDEC + **sub-streams for analytics** (main stream only for clips/enlarged view) — depends on [OPEN-2] |
| Inference throughput | Per-camera batch-1 wastes the GPU | Batch across cameras (ultralytics accepts lists); design `DetectionSet` to accept a batch from day one |
| SQLite writes (F4/E9) | Appearance rows every 3 s per person per camera | WAL now; Postgres decision from measurement |
| MJPEG delivery | One HTTP connection per viewer per camera | Cap concurrent streams; grid stays on snapshot+counts polling (already correct) |
| Single process | One crash takes all 208 cameras | Partition into N engine processes by camera group; shared DB; supervisor restarts a group, not the site |

**3. Unverified assumptions `[ASSUMPTION]`:** sub-streams available; ~1–2 Hz analytics cadence adequate for non-entrance cameras; face recognition on ≤6 entrance cameras only; weapons on person crops only; ≤10 concurrent operators.

**4. Required benchmarks (`VG-P8-01`..`04`), staged 1 → 8 → 32 → 104 → 208 using looped files as synthetic cameras:** decode-only ceiling per host; detection throughput vs batch size; end-to-end latency under load; DB write throughput at target event rates; memory/VRAM ceiling; failure-injection at scale.

**5. Hardware-dependent decisions:** GPU count and placement, process partition size, Postgres cutover — **all deferred to measurement.** [OPEN-1] must be answered first.

**6. Distribution threshold [PROPOSAL]:** move to multi-process when measured p95 capture→detection on the target mix exceeds its budget at any stage, or when a single process exceeds ~60% of host RAM. Publish the measured camera count per process rather than guessing it.

**No readiness claim may be made until the staged tests pass on the actual deployment hardware.**

---

## 18. Model inventory and owner requests

Classification per constitution: `integrated-and-validated` · `integrated-uncalibrated` · `available-not-integrated` · `interim` · `missing` · `blocked` · `unsuitable` · `awaiting-evaluation`.

| Feature | Model | Classification |
|---|---|---|
| Person detection | `yolov8s.pt` | **integrated-uncalibrated** — `conf 0.35` never calibrated; over-counts (E7) |
| Face detection | YuNet | integrated-uncalibrated |
| Face embedding | SFace 128-d | **integrated-uncalibrated** — threshold `0.363` is the published default; 1 person enrolled; margin gate has never fired |
| Tracking | ByteTrack | integrated-and-validated (35→stable IDs measured on the labelled clip) |
| Appearance re-ID | loiterwatch stitcher | integrated-uncalibrated. **Not a neural net — no GPU path exists. Do not promise one** |
| Weapons | `yolov8m-worldv2-school.pt` | **interim / unsuitable for production** — zero-shot; prompt list includes scissors, screwdriver, hammer |
| Weapons baseline | `yolov8n-oiv7.pt` | available-not-integrated — genuinely trained; the honest scoring floor |
| Lost items | `yolov8m-worldv2-search.pt` | available-not-integrated |
| Pose | `yolov8s-pose.pt` | available-not-integrated (fights only — deferred) |
| Deep re-ID | `osnet_x1_0_market1501.pth` | **blocked** — `osnet_x1_0` ≠ `osnet_ain_x1_0`; wrong architecture yields confident nonsense. Do **not** wire against the in-repo file |
| Fight classifier | — | missing / deferred |
| TensorRT `.engine` × 5 | — | **unsuitable as artefacts** — compiled for this RTX 2080 + a newer ultralytics; rebuild on target |

### Model Inputs Required From Owner

| # | Feature | Model | Required contract | Blocking impact |
|---|---|---|---|---|
| **M1** | Track a person | Body re-ID | Architecture name; load path (plain `torch` vs `torchreid`); **Python version built on**; input shape + preprocessing; embedding dim + normalisation; licence; a small labelled cross-camera set | **Blocks `.venv` creation and the Python-version decision** (`torchreid` may not support 3.14). Highest-leverage single unblock |
| **M2** | Weapons | Trained detector | Framework/format; input shape; class list; per-class thresholds; training-data description; target precision/recall **at a stated FP-per-camera-hour**; licence; ≥200 representative eval frames incl. hard negatives (scissors, phones, rulers) | Blocks honest P6 scoring. Interim model MUST NOT ship |
| **M3** | Fights | Classifier | Input contract: pose-keypoint sequence vs raw clip vs person crops; window length; output shape | Deferred — but the answer changes buffer memory per camera |
| **M4** | All | Eval datasets | Representative on-site footage per feature | Without these, no accuracy claim is defensible |

A weight file is not acceptance. Each model requires versioned evaluation evidence, calibration on representative data, error analysis, and a deployment benchmark before its feature can be `verified-complete`.

---

## 19. Web and mobile completion

**Web:** wired and structurally sound. Remaining: honest `data_source` banners (P0), track page truthfulness (P0), overlay freshness (P1), real login + session handling + 401/403 states (P2), pagination/virtualisation for 1,742 students and 208 cameras (P8) — currently flat lists, error/empty/degraded states per page (P0/P4), remove or implement dead controls (P0).

**Mobile [OPEN-6]:** entirely fixture-backed including `Math.random()` counts (`mobile/src/services/api.ts:43`). [PROPOSAL] scope v1 to a **read-only** subset — home, attendance, people, person history, system health, camera view — reusing the web `wire.ts`/`format.ts` contracts. Operator actions (weapon review, zone toggles) stay desktop-only in v1: they need the same server-side authorization and are higher-risk on a small screen. Effort ~2–3 weeks after P2 lands.

---

## 20. Observability and truthful System Health

**MUST:** every subsystem reports actual state + failure reason (partly done, `live.py:663-725`); every fixture-backed surface carries `data_source` (P0); per-camera/feature latency, freshness, drops, queue depth (P1); DB health (WAL mode, size, lock waits, oldest unpruned row); model provenance per feature (name, version, device, ms/frame); worker restart counts; stream client count.

Structured JSON logs with `camera_id` / `feature` / `event`. Prometheus endpoint [PROPOSAL]. Health stays HTTP 200 when everything it describes is broken — already correct, protected by test.

---

## 21. Test and validation strategy

Test-first is REQUIRED for business rules and regression fixes (constitution).

| Layer | Coverage required | Status |
|---|---|---|
| Unit | Zone geometry, schedules, register derivation, gallery matching/margin, appearance binding | Good |
| Contract | Every endpoint's schema; **`data_source` present on every payload** | New (P0) |
| Integration | Worker → store → API per feature | Partial |
| **Regression** | One test per error in §12 — E1..E13 | **New; each fix MUST ship with its test** |
| Concurrency | Two features on one camera; single detection pass asserted; isolation on failure | **New (P1)** |
| Failure injection | Camera drop/reconnect, model load failure, DB lock, disk full | **New (P4)** |
| Authorization | Every endpoint × every role, negative cases | **New (P2)** |
| Performance | §15 budgets on documented hardware | **New (P1/P8)** |
| Load | Staged 1→208 | **New (P8)** |
| On-site | §22 | New |

**Deterministic fixtures already owned and under-used:** `walk-through_cam-laptop_20260805-121705.mp4` + 21 hand-labelled ground-truth marks. This is the regression suite and the Model-Manager benchmark input. All pipeline work uses clips; the webcam is for final confirmation only.

**CI (`VG-P0-12`):** pytest + `pyflakes` + `npx tsc -b --force` (**not** `--noEmit` — project references make it a silent no-op) + `VG_STRICT=1` smoke start.

---

## 22. On-site commissioning

Sequenced; each step gates the next. **Cannot begin until [OPEN-8] is resolved.**

1. Site survey — camera positions, mounting heights, lighting, face pixel width at entrances (`MIN_FACE_PIXELS = 80` is measured, not guessed), sub-stream availability [OPEN-2], network topology.
2. Network and storage validation against the §17 budget.
3. Camera onboarding via the UI; verify every stream, then NO SIGNAL and reconnect behaviour.
4. **Enrol from the real entrance cameras at the real mounting angle** — not a laptop webcam. Pilot group ≥50 people, ≥3 varied captures each.
5. Threshold calibration with `tools/calibrate_faces.py` on that data; publish measured FAR/FRR. **This produces the first defensible accuracy number.**
6. Zone drawing with the operator; verify schedules against the real timetable.
7. Parallel-run attendance against a manual roll call for ≥5 school days; publish agreement.
8. Weapons eval on-site (three candidates, same golden clips) → publish FP per camera-hour → operator sign-off before enabling.
9. Latency and load validation at the real camera count.
10. Operator training + `OPERATIONS.md` handover; failure drills (camera down, engine restart, DB restore).

---

## 23. Backup, recovery, rollback, and operations

**MUST before pilot:** nightly DB backup with a **tested** restore (untested backup ≠ backup); documented restore procedure with RTO/RPO; migration rollback path per Alembic revision; engine rollback by version tag; clip/footage retention sweeper with a dry-run mode; supervised service start (Windows Service or NSSM) with restart-on-crash; disk-space monitoring with alerting before footage fills the drive; secrets in `.env` only, documented rotation; documented rebuild of TensorRT engines on the target host.

`OPERATIONS.md` carries all of the above plus: daily checks, reading System Health, adding a camera, enrolling a person, responding to a weapon alert, what to do when a camera is down, and how to file a defect.

---

## 24. Risk register

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Deployed without auth | Critical | Medium | P2 gates the pilot. No exceptions |
| R2 | Biometric/minors legal challenge | Critical | Medium | [OPEN-8] resolved before commissioning; DPIA parallel to engineering |
| R3 | Recognition accuracy collapses at scale | Critical | **High** | Calibrate on-site before any claim; 1 enrolled person tells us nothing |
| R4 | 208 cameras infeasible on chosen hardware | Critical | Medium | Staged benchmarks **before** hardware purchase; [OPEN-1] |
| R5 | E2 race produces wrong detections intermittently | High | Medium | `VG-P1-01`; concurrency test |
| R6 | E3 DST corrupts the register | High | **Certain** at the boundary | `VG-P0-03` before the October transition |
| R7 | Owner models arrive late or unsuitable | High | Medium | Build against interfaces; interim never ships; M1 is the top ask |
| R8 | Weapons false alarms exhaust reviewer trust | High | High | Human gate + published FP rate + per-class thresholds + operator sign-off |
| R9 | SQLite lock failures lose events | High | Medium | `VG-P0-06` now; Postgres decision by measurement |
| R10 | Faces too small at real entrances | High | High | Survey **before** buying cameras |
| R11 | Single planning source drifts again | Medium | High | §10 hierarchy + §32 loop |
| R12 | Scope creep from UI refinement | Medium | Medium | Presentation changes must not alter contracts |
| R13 | Kaggle key exposure | Medium | Certain (was on disk) | **Owner rotates key** |
| R14 | `torchreid` blocks Python 3.14 | Medium | Medium | M1 answers it; do not build `.venv` before then |

---

## 25. Critical path and parallel workstreams

**Critical path:** `P0 Truthfulness` → `P2 Security` → `P3 Events` → `P4 Intrusion` → `P8 Scale` → commissioning.

`P1` is not strictly on the path but MUST precede any new body-feature, or E2 is replicated into each one.

**Parallelisable now, no dependencies:** P0 documentation tasks; benchmark harness construction (P8 tooling); DPIA and consent workflow ([OPEN-8], legal, not engineering); collecting weapons eval footage; mobile scoping.

**Owner-blocked, unschedulable:** M1 re-ID (blocks `.venv`, P7 track), M2 weapons (blocks P6 scoring), M3 fights (deferred).

**Highest-leverage single action:** deliver **M1** — it unblocks the environment decision, the lock file, and P7 simultaneously.

---

## 26. Dependency-ordered phases

Effort ranges assume **one experienced engineer**, familiarity with the codebase, and no on-site access; they exclude owner-model lead times, legal work, and commissioning. `[ASSUMPTION]` — these are estimates, not commitments, and no calendar dates are implied.

---

### P0 — Truthfulness and safety net · 1.5–2 weeks · **MUST** · no dependencies

**Objective:** the console never shows anything untrue. **Outcome:** the system becomes safely demonstrable to a stakeholder, and every later phase inherits an honest baseline.

| Task | Description | Files | Risk |
|---|---|---|---|
| `VG-P0-01` | Remove fixture fallback from `LiveStore`; add `data_source` + `unavailable_reason` to every payload; fixtures only behind `VG_DEMO=1` with a forced banner (E1) | `live.py`, `schemas.py`, `store.py`, `wire.ts`, `format.ts`, all pages | Med — touches every endpoint; contract tests first |
| `VG-P0-02` | Track subject badge derives `identified` from name presence (E12) | `TrackPerson.tsx:307` | Low |
| `VG-P0-03` | DST-safe timezone: resolve offset per timestamp, not once (E3) | `live.py`, `sightings.py`, `counts.py`, `appearance.py` | Med — verify with a DST-crossing test |
| `VG-P0-04` | Person-mode attendance applies the late cutoff (E6) | `live.py:798-806` | Low |
| `VG-P0-05` | Reconcile fights: remove page, endpoints, MockStore methods, dead icon; **or** return 410 (E5) | 12 files (§9) | Low — recoverable via git |
| `VG-P0-06` | DB connection factory: WAL, `busy_timeout`, `foreign_keys` (E9) | `gallery.py`, `events/*.py` | Low, high value |
| `VG-P0-07` | Dead controls: implement, remove, or truthfully disable with reason | `Attendance.tsx:165`, `Weapons.tsx:206`, `TrackPerson.tsx:844`, `CameraModal.tsx:50`, `api.ts:517` | Low |
| `VG-P0-08` | Clear remaining fixtures from the track page | `TrackPerson.tsx` | Low |
| `VG-P0-09` | Error/empty/degraded state per page | `web/src/pages/*` | Low |
| `VG-P0-10` | Wire `history()`/`group()` to `SightingStore` (query exists; only the override is missing) | `live.py` | Low |
| `VG-P0-11` | Execute and publish the real test baseline | — | Low |
| `VG-P0-12` | CI: pytest + pyflakes + `tsc -b --force` + `VG_STRICT=1` smoke | `dev.ps1`, CI config | Low |
| `VG-P0-13` | Rewrite `README.md` (D5) | `README.md` | Low |
| `VG-P0-14` | Documentation consolidation + archive moves (§9) | `docs/` | Low |

**Acceptance:** no code path returns `MockStore` data unless `VG_DEMO=1`; every page shows its data source; a DST-boundary test passes; every §12 error fixed in this phase has a failing-then-passing regression test; `dev.ps1 test` green. **Evidence:** test output, before/after screenshots, the diff.

---

### P1 — Inference correctness and real-time instrumentation · 1.5–2 weeks · **MUST** · after P0

**Objective:** one detection pass per camera per tick, provably; latency becomes measurable. **Outcome:** halves GPU cost on multi-feature cameras, removes a data-corruption race, makes Principle I testable.

| Task | Description | Files |
|---|---|---|
| `VG-P1-01` | `DetectionSet` publisher; consumers read it; **no consumer calls the model** (E2) | `features/base.py`, `people.py`, `tracking.py`, `app.py:157-161`, new `features/detection.py` |
| `VG-P1-02` | Batch-capable detection interface (used at N=1 now, batching later) | `infer/persons.py` |
| `VG-P1-03` | Surface overlay freshness (`age_ms`) end-to-end; UI degrades when stale (E11) | `schemas.py`, `live.py`, `CameraFrame.tsx` |
| `VG-P1-04` | Public tracking read API; remove `getattr` into `_tracked_boxes` (E10) | `app.py:1085`, `live.py` |
| `VG-P1-05` | Latency/queue/drop instrumentation → System Health | `base.py`, `live.py`, `SystemHealth.tsx` |
| `VG-P1-06` | Feature-isolation test: kill one worker, assert the other is unaffected and the UI says why | `engine/tests/test_isolation.py` (new) |
| `VG-P1-07` | Measure and publish §15 budgets on the RTX 2080 baseline | `tools/measure_latency.py` |

**Acceptance:** a camera with `counting`+`track` runs exactly one detection pass per tick (asserted by a call-count test); no two threads ever enter the model concurrently; overlay age is visible in the API and rendered; §15 table has real numbers for the single-camera baseline.

---

### P2 — Security foundation · 2–2.5 weeks · **MUST — GATES PILOT** · after P0

| Task | Description |
|---|---|
| `VG-P2-01` | `app_user` + `session` tables; argon2id hashing |
| `VG-P2-02` | Login/refresh/logout; server-side session or JWT + revocation (ADR required) |
| `VG-P2-03` | AuthN middleware — deny by default; explicit public allowlist (`/healthz` only) |
| `VG-P2-04` | Per-endpoint RBAC, server-enforced; **enrolment and camera mutation are admin-only** |
| `VG-P2-05` | Replace `AuthContext` localStorage role with real session; 401/403 handling |
| `VG-P2-06` | Rate limiting on auth, enrolment, search |
| `VG-P2-07` | TLS termination documented; secrets handling reviewed |
| `VG-P2-08` | Authorization test matrix — every endpoint × every role, negative cases |

**Acceptance:** unauthenticated request to **any** endpoint except `/healthz` returns 401; an `it`-role token is refused admin actions server-side; `localStorage` tampering achieves nothing; the test matrix passes. **This phase is a hard release gate.**

---

### P3 — Durable events and persistence · 2–2.5 weeks · **MUST** · after P0/P2

`VG-P3-01` Alembic + baseline migration · `VG-P3-02` event tables (§14) · `VG-P3-03` zones to DB with `engine.yaml` reconciler (E8) · `VG-P3-04` **durable append-only audit, written before result returns** (E4) · `VG-P3-05` retention sweeper with dry-run · `VG-P3-06` backup + **tested** restore · `VG-P3-07` erasure path covering all tables holding a person (S9).

**Acceptance:** migrations apply and roll back on a copy of the real DB; a track search survives restart in the audit table; a person-erasure request removes every trace across all tables, proven by test; a restore drill succeeds from a backup.

---

### P4 — Intrusion (the event-feature template) · 1–1.5 weeks · **MUST** · after P1/P3

Deliberately first among event features: occupancy is **already computed every frame and discarded** (`people.py:113-134`) — the smallest gap between computed and recorded, so it establishes the pattern weapons and counting copy.

`VG-P4-01` `IntrusionWorker` consuming `DetectionSet` + `Schedule.is_restricted_at()` + `min_dwell_seconds` · `VG-P4-02` `breach` rows; override `breaches()` · `VG-P4-03` clip capture with configured pre/post-roll · `VG-P4-04` zone editor UI (draw on a live frame) · `VG-P4-05` failure-injection tests · `VG-P4-06` persist enrolment sessions (E13, SHOULD).

**Acceptance:** entering a restricted zone during restricted hours produces a breach with a clip within 5 s; during permitted hours, nothing; a sub-dwell pass at the frame edge, nothing; a paused zone stays visible and stops alerting.

---

### P5 — Counting correctness · 0.5–1 week · **MUST** · after P1

`VG-P5-01` pass `min_area`, expose in config, calibrate `conf` against the labelled clip (E7) · `VG-P5-02` remove or satisfy the de-dup claim ([OPEN-3]) · `VG-P5-03` areas/capacity management in the UI · `VG-P5-04` validate against a manual count.

**Acceptance:** counting matches a manual count within an agreed tolerance on the labelled clip **and** in one real area; no UI claim exceeds what the code does.

---

### P6 — Model Manager + weapons · 2–3 weeks · after P3 · **blocked on M2 for scoring**

`VG-P6-01` `model_version` table + upload + benchmark-against-labelled-clip + activate-on-restart + rollback · `VG-P6-02` `WeaponWorker` on person crops, built against the **interface** · `VG-P6-03` `weapon_detection` table + review workflow (no delete) · `VG-P6-04` clip/still evidence · `VG-P6-05` three-candidate eval harness · `VG-P6-06` per-class thresholds.

**Guard rails the Model Manager MUST enforce:** an unbenchmarked model cannot be activated; uploading a `.engine` warns it is host-specific; changing the face model is a destructive administrative action with bulk re-enrolment (expected answer: no).

**Acceptance:** all three candidates scored on identical golden clips; FP per camera-hour published; review round-trips and dismissed detections remain in history; the human gate is provably the only path to any downstream action.

---

### P7 — Footage, lost items, re-ID track · 2–3 weeks · after P3 · **blocked on M1**

`VG-P7-01` continuous segmented recording + retention · `VG-P7-02` index detections at ingest so search is a DB query, not a re-scan · `VG-P7-03` job-based search API (POST → id → poll; the UI's "Searching footage…" state already expects this) · `VG-P7-04` integrate the owner's re-ID model · `VG-P7-05` clip export for track (the agreed stitched main-view design) · `VG-P7-06` audit before result, durable.

---

### P8 — Scale · 2–3 weeks + hardware · **MUST** · after P4

`VG-P8-01` synthetic camera harness (looped files) · `VG-P8-02` staged benchmarks 1→8→32→104→208 · `VG-P8-03` bounded worker pools replacing thread-per-camera (F5) · `VG-P8-04` multi-process partitioning + supervisor · `VG-P8-05` sub-stream support ([OPEN-2]) · `VG-P8-06` UI pagination/virtualisation · `VG-P8-07` Postgres decision **from measurement**.

**Acceptance:** the representative 208-camera feature mix sustains its §15 budgets for ≥4 hours on documented hardware, with a killed partition recovering without affecting others. **No readiness claim before this passes.**

---

### P9 — Notifications and mobile · 1–2 weeks · SHOULD · after P2/P3 · [OPEN-5], [OPEN-6]

`VG-P9-01` alert rule engine + durable delivery log · `VG-P9-02` in-app delivery · `VG-P9-03` email/SMS/WhatsApp per [OPEN-5], or remove the UI claims · `VG-P9-04` mobile wiring, read-only subset.

---

### P10 — Commissioning and release · 1–2 weeks + on-site · **MUST**

`VG-P10-01` `OPERATIONS.md` · `VG-P10-02` failure drills · `VG-P10-03` on-site calibration (§22) · `VG-P10-04` parallel-run validation · `VG-P10-05` residual-risk review · `VG-P10-06` constitution compliance review (§29).

---

## 27. Definition of Done

A task is Done when **all** hold: acceptance criteria met and demonstrable; automated tests written **first** for business rules and passing; no fixture, random value, or no-op persistence in its production path; degraded/empty/error states implemented; server-side authorization enforced (post-P2); latency budget measured where applicable; audit written where identity-relevant; documentation updated in its single authoritative location; System Health reflects it truthfully; the diff is reviewed and the working tree explainable.

A **feature** is Done only when the full chain works: input → processing → persistence → API → authz → web (and mobile if in scope) → operator action → audit → monitoring → recovery. A page existing, a model file being present, or an endpoint returning the right schema are each individually insufficient.

---

## 28. Release gates

| Gate | Criterion |
|---|---|
| G1 | P0 complete — zero fixture-backed production paths |
| G2 | P2 complete — no unauthenticated endpoint; RBAC matrix passes |
| G3 | P3 complete — durable audit; tested restore; erasure path proven |
| G4 | Every in-scope feature `verified-complete` per §27, or explicitly `removed-from-scope` with the UI honestly reflecting it |
| G5 | Accuracy calibrated on representative on-site data; FAR/FRR and weapons FP-per-camera-hour published |
| G6 | §15 latency budgets met at the deployed camera count on documented hardware |
| G7 | **Zero known critical or high-severity defects**; residual risks documented and owner-accepted. (No absolute defect-free claim is made — that is unverifiable) |
| G8 | [OPEN-8] resolved: lawful basis, consent, retention, erasure documented and implemented |
| G9 | `OPERATIONS.md` complete; operator trained; failure drills passed |
| G10 | Constitution compliance review recorded (§29); any waiver owner-approved, time-bounded, and not concealing fake data, misrepresenting health, bypassing authorization, or removing a human gate |

---

## 29. Constitution compliance

Principle-by-principle against v1.0.0.

| Principle | Current | Plan response |
|---|---|---|
| **I. Real-Time Camera Experience** | ⚠️ Partial — bounded queues and drop-oldest are **compliant today** (`base.py:123-136`, `framebus.py`); but no budgets are defined, no freshness is surfaced (E11), and no latency is measured | §15 budgets; `VG-P1-03`, `VG-P1-05`, `VG-P1-07`; P8 at scale |
| **II. Feature Isolation, Efficient Inference** | ❌ Violated — `FeatureWorker` isolates workers correctly, but the shared *model instance* without a shared *output contract* both wastes inference and creates a race (E2) | `VG-P1-01` `DetectionSet` with the §16 contract; `VG-P1-06` isolation test |
| **III. Truthful Data and Traceable Decisions** | ❌ **Systemically violated** — fixture fallback (E1), RAM-only audit (E4), fake persistence (E5), invisible staleness (E11), contradictory badge (E12) | P0 in full; `VG-P3-04` durable audit |
| **IV. Production Reliability, Security, Privacy** | ❌ Violated — no authN/authZ, no encryption, no retention, no erasure, no tested backup; shutdown and failure-surfacing are already good | P2, P3; §22, §23 |
| **V. Complete, Business-Correct UX** | ⚠️ Partial — dead controls, logical errors E6/E7/E8, fixture pages | P0, P4, P5; §27 |
| **Scale constraints** | ❌ Not designed for 208 (F5); no measurement | §17, P8 |
| **Workflow and quality gates** | ⚠️ Partial — good unit tests; no test-first discipline recorded, no CI, no authorization or performance tests | `VG-P0-11/12`; §21 |

**Two constitution-driven reversals of prior direction, recorded explicitly:**

1. **The fixture fallback must go.** It was a deliberate virtue in `DEV_PLAN.md`/`COMPLETION_PLAN.md` ("each feature moves across on its own; the console does not care"). Principle III now forbids it. The *seam* is kept — it is genuinely valuable for independent rollout — but the fallback becomes an explicit `unavailable` payload rather than invented data.
2. **"Detect once, fan out" must become real.** It was documented as already done; it is not (E2). Principle II permits the sharing but requires an explicit contract, which §16 now supplies.

---

## 30. Git change strategy

**Branch:** `plan/final-production-roadmap` for documentation and planning. Feature work uses spec-kit's per-feature branches off `main`.

**Protected:** `.specify/memory/constitution.md` is currently modified and unstaged — **owner work, not touched by me.**

**Changeset separation** (one concern per commit): governance/constitution · this plan · documentation consolidation and archive moves · repository cleanup · each code fix with its regression test.

**Prohibited:** `reset --hard`, force-push, history rewriting, branch deletion, discarding uncommitted work, indiscriminate `clean`.

**Commit messages** (conventional): `docs: add authoritative development plan v2.0.0` · `docs: archive superseded planning documents` · `fix(api): remove fixture fallback from LiveStore` · `fix(engine): resolve timezone offset per timestamp` · `perf(engine): share one detection pass across body features` · `feat(auth): enforce server-side authorization`.

**Every code commit fixing a §12 error MUST include its regression test in the same commit** — so traceability from error → fix → proof is a single, reviewable unit.

**Operational note:** git operations issued through my device bridge leave `.lock` and `tmp_obj_*` litter because the bridge cannot delete files. Routine git work SHOULD be done in a local terminal.

---

## 31. Evidence ledger

Compact traceability. Extend, don't restate.

| Req | Status | Evidence | Verified | Gap | Next task |
|---|---|---|---|---|---|
| FR-01 | partial | `sightings.py:230-297`; `live.py:785-857` | 03f1fd7 | E6; no authz | `VG-P0-04` |
| FR-02 | partial | `identity/enrolment.py`; `app.py:1182-1298` | 03f1fd7 | Unauthenticated; in-memory | `VG-P2-04` |
| FR-03 | partial | `app.py:625-731`; `live.py:88-131` | 03f1fd7 | E11 freshness | `VG-P1-03` |
| FR-04 | partial | `live.py:433-515`; `counts.py` | 03f1fd7 | E7; dedup claim | `VG-P5-01` |
| FR-05 | missing | `people.py:113-134` computes, discards | 03f1fd7 | No worker/table | `VG-P4-01` |
| FR-06 | awaiting-model | `models/README.md` | 03f1fd7 | Interim unsuitable | M2, `VG-P6-02` |
| FR-07 | partial | `features/tracking.py`; `live.py:861-938` | 03f1fd7 | E12; E2; re-ID | `VG-P0-02` |
| FR-08 | missing | — | 03f1fd7 | No recording | `VG-P7-01` |
| FR-09 | partial | `live.py:729-755` | 03f1fd7 | History fixture | `VG-P0-10` |
| FR-10 | partial | `live.py:611-725` | 03f1fd7 | No latency metrics | `VG-P1-05` |
| FR-11 | missing | grep: zero auth libs in `engine/` | 03f1fd7 | Everything | `VG-P2-01` |
| FR-12 | missing | `store.py:830-835` | 03f1fd7 | E4 | `VG-P3-04` |
| FR-13 | missing | `engine.yaml:44`; `prune()` uncalled | 03f1fd7 | S6, S9 | `VG-P3-05` |
| FR-14 | missing | `store.py` delivery fixtures | 03f1fd7 | No mechanism | `VG-P9-01` |
| FR-15 | missing | `mobile/src/services/api.ts:43` | 03f1fd7 | All fixtures | `VG-P9-04` |
| FR-16 | missing | `base.py:98-105` | 03f1fd7 | F5 | `VG-P8-03` |

---

## 32. Maintenance loop

After each development cycle: inspect `git status`, relevant diffs, recent commits → re-inspect changed implementation paths → compare against §3 → update §2/§11/§31 **from evidence, never from intent** → record new gaps and logical errors in §12 → update §24 risks and §25 critical path → synchronise the §10 documentation set → archive superseded material safely → update §8 if structure changed → **never mark work complete without tests and evidence** → commit only when authorized → leave the repository in an explainable git state.

Bump this document's version: MAJOR for phase restructuring, MINOR for new phases/tasks, PATCH for status updates.

---

**Prepared by:** Claude (lead technical planner) · **Baseline:** `03f1fd7`
**Not committed** — awaiting owner authorization (§30).
