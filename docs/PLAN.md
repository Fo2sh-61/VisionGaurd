# VisionGuard — Plan

**The only plan.** Rules live in `.specify/memory/constitution.md`. Today's state lives in `STATUS.md`.
**Version** 3.0 · **Baseline** commit `03f1fd7` · Supersedes `DEV_PLAN.md`, `COMPLETION_PLAN.md`, `INTEGRATION-PLAN.md`, `PROJECT_ANALYSIS.md`, `DEVELOPMENT_PLAN.md` (all in `docs/archive/`).

---

## 1. What we're building

A vision system for Greenfield International School: ~208 cameras answering operator questions about attendance, headcounts, restricted zones, weapons, lost items, and where a person went. Desktop console + phone app.

**The architecture is sound and three features already run on real data.** What remains is four foundations, then a sequence of slot-fills.

---

## 2. Where we are

| | Real today | Fake today | Missing entirely |
|---|---|---|---|
| | Camera ingest, attendance, enrolment, live overlays, tracking engine, counting (1 area), system health | Intrusion, weapons, lost items, person history, users, audit, notifications, all of mobile | Auth, event tables, footage recording, retention |

Full per-feature detail: `STATUS.md`.

---

## 3. Five findings that set the order

Verified in code this cycle. These are why P0 and P1 come before any feature work.

| | Finding | Where |
|---|---|---|
| **F1** | Engine silently serves **fake data** when a subsystem is off. An operator cannot tell a real register from an invented one. Constitution forbids it. | `live.py:398, 786, 729, 878, 965` |
| **F2** | Person detector runs **twice per frame** on cameras with both counting and track — two threads, one shared model. Wastes GPU *and* risks corrupted results. | `app.py:157-161`, `people.py:114`, `tracking.py:55` |
| **F3** | Timezone offset is read **once at startup**. Egypt's DST change (late October) shifts every timestamp by an hour until restart. | `live.py:74`, `sightings.py:116` |
| **F4** | SQLite has **no WAL, no busy-timeout**, 5 connections, multiple writer threads → `database is locked` at scale. Lost events, not slowness. | `gallery.py:125`, `events/*.py` |
| **F5** | One thread per camera per feature → **~600 threads at 208 cameras**. Architectural wall. | `features/base.py:98-105` |

---

## 4. What the product must do

| ID | Requirement | Status |
|---|---|---|
| FR-01 | Attendance register from live face recognition, exportable, auditable | partial |
| FR-02 | Browser enrolment with quality gating | partial |
| FR-03 | Live camera view, per-feature overlays, honest offline state | partial |
| FR-04 | People counting per area, live + history | partial |
| FR-05 | Restricted-zone breaches with evidence clip | missing |
| FR-06 | Weapon detection with mandatory human review | missing |
| FR-07 | Track a person; face and appearance kept distinct | partial |
| FR-08 | Lost-item search over recorded footage | missing |
| FR-09 | People directory, groups, person history | partial |
| FR-10 | Truthful System Health with failure reasons | partial |
| FR-11 | Server-enforced login and roles | **missing** |
| FR-12 | Durable audit trail | **missing** |
| FR-13 | Retention + erasure | **missing** |
| FR-14 | Alert delivery | missing |
| FR-15 | Mobile on real data | missing |
| FR-16 | Runs at ~208 cameras, measured | not designed for |
| — | Fight detection | **out of scope** (no model) |
| — | Licence plates | **out of scope** (keep the seam only) |

> **Numbering rule.** `FR-xx` = product level, this file only. Spec-kit specs use their own prefixed numbering, e.g. `P0-FR-001`. Never mix them.

---

## 5. Phases

Effort assumes one experienced engineer; excludes owner-model waits and on-site work. Estimates, not dates.

### P0 — Stop showing anything untrue · 1.5–2 wk · **blocks everything**

| Task | Do |
|---|---|
| P0-01 | Kill fixture fallback. Every response says `live` / `unavailable` / `demo` + reason. Fixtures only under `VG_DEMO=1` with a permanent banner. (F1) |
| P0-02 | Track badge: derive "identified" from the name, not the match kind — `TrackPerson.tsx:307` |
| P0-03 | Timezone per timestamp, not per startup (F3) |
| P0-04 | Person-mode attendance must apply the late cutoff — `live.py:798` |
| P0-05 | Fights: remove page, endpoints, mock methods. `/fights/{id}/feedback` currently claims to save a training label and saves nothing |
| P0-06 | SQLite: WAL + busy-timeout + one connection factory (F4) |
| P0-07 | Dead buttons — implement, remove, or disable with a reason: Attendance "Notify parent", Weapons + Track + CameraModal "Save clip", Health "Restart" |
| P0-08 | Error / empty / degraded states on every page |
| P0-09 | Wire person history + group to the real store (the query already exists) |
| P0-10 | CI: pytest + pyflakes + `tsc -b --force` + strict-mode smoke start |

**Done when:** nothing fake reaches a screen outside demo mode; every page shows its data source; a DST test passes; each fix ships with its regression test.

### P1 — Detect once, and measure speed · 1.5–2 wk

| Task | Do |
|---|---|
| P1-01 | One detection pass per camera per tick, shared by all body features. No feature calls the model directly. (F2) |
| P1-02 | Overlay freshness (`age_ms`) visible in API and UI; stale overlays degrade honestly |
| P1-03 | Remove the private `_tracked_boxes` reach-in from `app.py:1085` |
| P1-04 | Latency + queue + drop metrics on System Health |
| P1-05 | Isolation test: kill one feature, prove the other is unaffected and the UI explains why |
| P1-06 | Measure and publish the §7 latency budgets on the RTX 2080 |

**Done when:** a call-count test proves one detection pass; no two threads enter the model at once.

### P2 — Security · 2–2.5 wk · **gates the pilot**

Users table + argon2 passwords · login/logout/refresh · deny-by-default middleware (only `/healthz` public) · per-endpoint roles enforced server-side (**enrolment and camera changes are admin-only**) · replace the localStorage role · rate limits on auth/enrolment/search · TLS documented · full role × endpoint test matrix.

**Done when:** every endpoint except `/healthz` returns 401 unauthenticated, and editing localStorage achieves nothing.

### P3 — Durable events · 2–2.5 wk

Alembic + baseline migration · tables for breach, weapon detection, audit, zones, clips, users · **append-only audit written before the result returns** · retention sweeper · backup with a **tested** restore · erasure that removes a person from *every* table.

**Done when:** a track search survives restart in the audit table; an erasure request provably leaves no trace; a restore drill succeeds.

### P4 — Restricted zones · **done** (20 Aug 2026)

The template event feature. Built as `spec 001-restricted-zones`: `features/zones.py` (scene state machine) + `events/zones.py` (`zone_scene` table), with `zones()`, `set_zone_enabled()` and `breaches()` overridden in `api/live.py`.

**A zone is a camera.** A camera marked restricted has its *whole frame* restricted — there is no polygon to draw, so the zone-drawing UI in the original plan turned out to be work that did not need doing. Scenes open on the first person and close after one continuous second with nobody, so a flickering detector yields one entry rather than three.

**Two deliberate gaps, both stated on screen:**

- **No schedules.** A restricted camera is restricted around the clock until it is switched off. `Zone.schedule` is always `ALWAYS`.
- **Three clips per camera** (owner decision 2026-08-21; shipped as one, widened the same week). A new scene pushes out *that camera's* oldest clip beyond three, and that entry drops off the log rather than sitting there unwatchable — so a camera shows at most three entries. The rows are never deleted; they wait in `zone_scene` for the audit view P3 brings. The real retention target — roughly a working day of clips, sized to the deployment machine — is an installation decision, not a code one.

**Done when:** ~~entering a zone in restricted hours gives a breach + clip within 5 s; in permitted hours, nothing; a paused zone stays visible and stops alerting.~~ Met, with "restricted hours" read as "restricted at all", per the settled no-schedules decision. A switched-off camera stays listed with its history.

### P5 — Counting accuracy · 0.5–1 wk

Pass `min_area` (already implemented in `persons.py:138`, never called) · calibrate `conf` against the labelled clip · either build cross-camera de-dup or remove the UI's "counted once" claim · areas/capacity UI.

**Done when:** counts match a manual count within agreed tolerance, and no claim on screen exceeds what the code does.

### P6 — Model manager + weapons · 2–3 wk · needs owner model **M2**

Model table, upload, benchmark against the labelled clip, activate-on-restart, rollback · weapon worker on person crops · review workflow with no delete · score all three candidates on identical clips · publish false-alarm rate per camera-hour.

**Guard rails:** an unbenchmarked model cannot be activated; changing the face model warns it destroys every enrolment.

### P7 — Footage, lost items, real re-ID · 2–3 wk · needs owner model **M1**

Continuous recording + retention · index at ingest so search is a query not a rescan · job-based search API · integrate the owner's re-ID model · clip export for track.

### P8 — Scale to 208 · 2–3 wk + hardware

Synthetic camera harness · staged benchmarks 1 → 8 → 32 → 104 → 208 · bounded worker pools replacing thread-per-camera (F5) · multi-process partitioning · sub-streams · UI pagination · decide Postgres **from measurement, not preference**.

**Done when:** the real camera mix holds its latency budgets for 4 hours on the real hardware, and killing one partition doesn't affect the others.

### P9 — Notifications + mobile · 1–2 wk

Alert rules + delivery log · in-app delivery · email/SMS only if required · mobile wired **read-only** (view, don't act — actions need the same server-side authorization and are riskier on a phone).

### P10 — Go live · 1–2 wk + on-site

Operations runbook · failure drills · on-site calibration · parallel-run attendance against a manual roll call for 5 days · residual-risk review · constitution compliance review.

---

## 6. Honesty acceptance tests

The UI makes these promises. Each is a backend test — carried forward from the old integration plan because they are still correct.

| Promise on screen | Test |
|---|---|
| "NO SIGNAL — showing last received frame" | When a stream drops, the API returns the last frame with `offline: true` within one poll. It never returns a stale frame as current. |
| A weapon alert always waits for a human | No notify/call/lock can be triggered by the detector. The review endpoint is the only thing that fans out. |
| False alarms stay in history | Dismissed detections are retained and returned. There is no delete operation. |
| "Every tracking search is recorded" | The audit row is committed **before** the result returns. If the audit write fails, the search fails. |
| A paused zone stays visible | Disabling changes only the `enabled` flag; it is never filtered from any response. |
| Face vs clothing | Green = face names a person. Blue = clothing says same body only. Never merged into one number or colour. |

---

## 7. Speed targets

One row is measured. The rest are still targets.

| Path | Target p95 | Measured |
|---|---|---|
| Camera → screen (watched) | ≤ 400 ms | not measured |
| Camera → detection ready | ≤ 250 ms | **18 ms — passes** |
| Overlay freshness | ≤ 200 ms | not measured (P1-02) |
| Zone breach → visible | ≤ 5 s | built (P4), not yet timed by hand |
| Weapon detection → review queue | ≤ 2 s | feature not built (P6) |
| Camera drops → NO SIGNAL shown | ≤ 2 s | not measured |
| Lost-item search | ≤ 60 s | feature not built (P7) |

**Measured 20 Aug 2026**, `python engine/tools/benchmark.py`, on an RTX 2080
Max-Q (8 GB, laptop) with `yolov8s.pt` on CUDA, timed over 60 frames of the
labelled walk-through clip: p50 17.3 ms, p95 18.0 ms, 57.5 frames/sec.

Re-run it on the deployment workstation. This is a power-limited laptop GPU
without TensorRT, so it is the floor, not the ceiling.

### What that means for 208 cameras

Detection throughput, not per-frame latency, is what sets the hardware. At
57.5 frames/sec measured:

| Every camera detecting at | Needs |
|---|---|
| 1 Hz | 3.6× this machine |
| 2 Hz | 7.2× this machine |
| 5 Hz | 18.1× this machine |

An upper bound, and deliberately pessimistic: it assumes every camera runs
person detection at that rate. The real deployment runs fewer models on fewer
cameras, and P1-01 removed the duplicate pass that made cameras with both
counting and track cost twice this. Size the workstation from a re-run on the
real hardware with the real feature mix, not from this table.

---

## 8. Settled — do not reopen

- **SFace is the permanent face model.** Not a step toward ArcFace. Changing it invalidates every enrolment.
- **The owner supplies all models.** VisionGuard never sources, trains, or downloads them.
- **The database is the source of truth**; `engine.yaml` is only the bootstrap seed.
- **Model activation restarts the worker.** No hot-swap.
- **The British School project is severed.** Nothing from it is used.
- **New features follow the four-file pattern:** `infer/` → `features/` → `events/` → override in `live.py`.
- **Ship `.pt`, build `.engine` on the target machine.** TensorRT files are build outputs, never artifacts.

---

## 9. Waiting on you

| | Need | Blocks |
|---|---|---|
| **M1** | Re-ID model + architecture name + how it loads + Python version built on | `.venv` creation, P7 — **highest leverage** |
| **M2** | Trained weapons model + class list + eval footage | Honest P6 scoring. The current model is zero-shot and lists scissors and screwdrivers |
| ~~D1~~ | ~~Lawful basis + consent for biometrics of minors~~ | **ANSWERED 20 Aug 2026 — permission granted.** No longer gates deployment |
| **D2** | Target hardware (GPUs, RAM, storage, network) | The 208-camera plan. Sizing arithmetic now in §7 |
| ~~D3~~ | ~~Do the site cameras have low-res sub-streams?~~ | **ANSWERED 20 Aug 2026 — yes.** The laptop webcam does not, but it is a development device, not a site camera |
| ~~D4~~ | ~~Retention: how long for clips, footage, sightings?~~ | **ANSWERED 20 Aug 2026 — 3 days of footage.** See §7.1 |
| **D5** | Rotate the Kaggle API key — it sat unignored in `models/knife detection/kaggle.json` | Security |

Defaults if unanswered: 14-day appearance rows / 365-day sightings; in-app alerts only; no Arabic RTL at launch; counting stays honestly "summed, not de-duplicated".

### 7.1 Storage, now that retention is 3 days

Answered 20 Aug 2026: **3 days of recorded footage**, and the site cameras do
have low-resolution sub-streams.

At 208 cameras recording a ~512 kbps sub-stream continuously:

| | |
|---|---|
| Per camera | ~5.5 GB/day |
| All 208 | ~1.15 TB/day |
| **3 days** | **~3.5 TB** |

Call it **6–8 TB usable** with the database, evidence clips and headroom.

That is two drives, not a disk array — the 30-day default would have needed
~35 TB. It is the single biggest cost reduction available on this project, and
it also shrinks the privacy exposure: footage of children stops existing after
three days rather than a month.

**The catch:** a lost item reported on Monday cannot be searched for on
Thursday. Three days is a real operational limit, not just a storage setting,
and the Lost Items page must say so plainly rather than returning no hits.

---

## 10. Done means

**A task is done** when: it works and can be demonstrated · tests written first for business rules · no fake data, no dead controls, no silent no-op saves · error and empty states handled · authorization enforced (after P2) · audit written where identity is involved · documentation updated in its one home.

**A feature is done** when the whole chain works: camera → processing → saved to database → API → permissions → web UI → operator action → audit → recovery. A page existing, a model file being present, or an endpoint returning the right shape are each not enough on their own.

**Ready to release** when: P0, P2, P3 complete · every in-scope feature done or honestly marked out of scope · accuracy measured on real school data · speed targets met at the real camera count · zero known critical or high defects · consent and retention in place · operator runbook written and drills passed.

---

## 11. Keeping this true

After each work cycle: check `git status` and the diff → re-read the code that changed → update `STATUS.md` and section 2 **from evidence, not intention** → add any new findings to section 3 → never mark something done without a test.

If a document ever disagrees with the code, the code wins and the document gets fixed — never the other way round.
