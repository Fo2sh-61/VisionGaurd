# VisionGuard — Plan

**The only plan.** Rules live in `.specify/memory/constitution.md`. Today's state lives in `STATUS.md`.
**Version** 3.0 · **Baseline** commit `03f1fd7` · Supersedes `DEV_PLAN.md`, `COMPLETION_PLAN.md`, `INTEGRATION-PLAN.md`, `PROJECT_ANALYSIS.md`, `DEVELOPMENT_PLAN.md` (all in `docs/archive/`).

---

## 1. What we're building

A vision system for schools and organisations: a site of ~200 cameras answering operator questions about attendance, headcounts, restricted zones, weapons, lost items, and where a person went. Desktop console + phone app.

It is not built for one customer. Every site-specific fact — the site's name, its cameras, its zones, its hours — is configuration, not code.

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
| FR-06 | Weapon detection with mandatory human review | **partial** — knives detected, recorded and reviewed by a person; no alert fan-out until P9, and no gun detection |
| FR-07 | Track a person; face and appearance kept distinct | partial |
| FR-08 | Lost-item search over recorded footage | **partial** — live search of chosen cameras on demand, shipped 23 Aug 2026. No search of recorded footage, because there is no recorded footage |
| FR-09 | People directory, groups, person history | partial |
| FR-10 | Truthful System Health with failure reasons | partial |
| FR-11 | Server-enforced login and roles | **missing** |
| FR-12 | Durable audit trail | **missing** |
| FR-13 | Retention + erasure | **missing** |
| FR-14 | Alert delivery | missing |
| FR-15 | Mobile on real data | **built 3 Sep 2026** — `specs/012-mobile-parity`, unverified on a real phone |
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

### P6 — Knife detection · **shipped 22 Aug 2026** · model manager still to do

**Built.** The owner's trained `knifebest.pt` (one class, knife) on the shared person
pass: the knife model is never called on a frame with nobody in it, and a knife
counts only when its box centre sits inside a person's box, margin zero. Both rules
were measured on the recorded clips, where the false hits were room furniture with
somebody sitting beside it. Three sightings over a second open one entry with one
video; a blink shorter than the gap does not split it; two seconds of nothing closes
it; two minutes cuts it and says so. Every entry waits for a person to press Confirm
or False alarm — recorded against the signed-in account, audited before the write,
never reversible, never deleted. Videos expire at 30 days; entries never do.

**Not built, and deliberately.** The model manager — model table, upload,
activate-on-restart, rollback, benchmarking UI — none of it. Scoring the three
weapon candidates against each other, and the false-alarm rate per camera-hour,
both need eval footage that does not exist. **Guns are not detected by anything**:
the trained model is knife-only. And nothing fans out — Confirm is the single point
an alert spec may hang from, and today it hangs nothing (P9).

**Unmeasured, and one measurement that came out worse than planned.** Accuracy on
school cameras is unknown: the regression suite has 21 labelled ground-truth marks and
not one knife in any of them, so nothing here proves a real knife raises an entry.

The plan also said the thresholds would raise **zero** entries on the two recorded
clips. Run live on 22 Aug 2026 they raised **one** — a 12.5-second scene at 0.76
confidence on footage with no knife in it, followed by three clean loops. The
threshold analysis sampled every 5th frame; the live worker sees frames it skipped.
Call it **one false alarm per four loops of a 40-second clip**, not zero. The review
gate absorbs that, but only up to the point where reviewers stop reading — and the
thresholds cannot be tightened responsibly until there is footage with a real knife
in it, because every lever trades false alarms against missing the real thing.

**Guard rails still owed by the model manager:** an unbenchmarked model cannot be
activated; changing the face model warns it destroys every enrolment.

### P7 — Footage, lost items, real re-ID · 2–3 wk · needs owner model **M1**

Continuous recording + retention · index at ingest so search is a query not a rescan · job-based search API · integrate the owner's re-ID model · clip export for track.

**Part built, 23 Aug 2026 — live bag detection.** The owner supplied `bagbest.pt`,
so the half of this phase that does not need recording went in. It is **not** a
search: an operator ticks cameras and picks a colour, and any bag of that colour
is outlined in amber on the live tiles, continuously, the way attendance draws
faces. The tile's own overlay poll is what makes the model run, so work happens
only for cameras somebody is looking at and stops within seconds of them leaving.
Idle cost is zero. Colour is matched leniently against a set rather than one
name, because a dark blue bag looks black in poor light.

**Not built, and the page no longer implies otherwise.** No continuous recording,
so no clip to watch and no "missing since" period — both were removed from the
page rather than left as buttons that could not work. No index at ingest: a search
looks at live frames, not at history, so a bag that was taken before the search
started cannot be found. No re-ID.

**What it is honestly worth.** Accuracy on real bags is unmeasured — there is no
clip with a bag in it. Accuracy on footage *without* one is measured and is not
clean: 19 bag-class detections over 706 sampled frames of the no-bag clips, of
which a black office chair accounts for most, held steadily enough that the
two-frame rule cannot reject it (research D10). So a hit is presented as a
**possible** bag for a person to look at, never as a finding.

### Vehicle gate — **built 24 Aug 2026** · out of phase order, at the owner's request

Not one of the ten phases. The owner supplied two trained plate models — a plate
detector and a character reader, both on the Egyptian EALPR set — and asked for the
gate ahead of the queue, so it was specified and built as `specs/006-vehicle-gate`.

**Built.** A camera becomes a gate camera by being given a gate number and a
direction in `engine.yaml`; `both` is refused, because one camera cannot tell you
which way a car was going. Plates are read on those cameras only. **Nothing is
recorded from one frame**: each frame casts a weighted vote — reading confidence ×
plausibility × how big the plate was — readings within one edit merge instead of
competing, and a car is written only when three frames agree. The same plate at the
same camera inside sixty seconds is one pass, not twenty. Every pass keeps a
photograph of the clearest frame and a crop of the plate; both are deleted at thirty
days and the row is kept for good. A weak read is recorded and flagged for review
rather than discarded.

The register is a spreadsheet import or a form: plate, owner, unit, category, expiry.
Plates are normalised, so a plate typed in English digits, imported in Arabic digits
and read off a camera all land on one row — the database constraint decides, not a
lookup. A pass reads as registered, not registered, blacklisted or permit expired,
decided at the moment of the pass and never rewritten afterwards; blacklisting a car
today does not change what yesterday's pass said. Only blacklist raises an attention
item. A guard reads the register and the log; only an administrator changes them or
exports the log, and the export writes its audit entry before it builds the file.

**Not built, and the page says so rather than implying otherwise.** Nothing is
blocked, actuated or opened — the software records, it does not gate. Nothing fans
out: a blacklisted car raises an item on Home and sends no message to anybody.
"Inside now" needs a gate with **both** an entry and an exit camera; with one
camera the page states that no exit camera is configured instead of printing a
figure, and a visit closed because the car was seen entering again is labelled an
estimated exit, never an observed one.

**Measured on 27 Aug**, against the owner's EALPR set — 2,086 photos, 2,142
plates, via `engine/tools/eval_plates.py`. Three results settle three arguments.
Plate **detection** is 99.8% recall. Our **port is faithful**: gate-anpr's own
code and ours at FP32 read all 2,086 photos identically, 100.0%, so the software
is not the cause of a wrong number. And the two accelerations reverted on 24 Aug
were costing far more than anyone guessed — FP16 changes 6.7% of readings and the
TensorRT plan changes **26.6%**, one in four, on a model that classifies single
characters. Both stay off permanently and the plate models run the `.pt` at FP32.

**Still unmeasured, and it is the half that matters.** That dataset is what the
models were trained on, so it proves pipeline fidelity and predicts nothing about
the school's gate. Read accuracy on real plates needs a human-confirmed truth file
(`eval_plates.py --label`, waiting on Mohamed) and site captures. Until both
exist, no screen may state an accuracy figure. Evidence and the full verdict:
`specs/007-vehicle-gate-tuning/evidence/`.

### Vehicle gate, second pass — **27 Aug 2026** · `specs/007-vehicle-gate-tuning`

The owner reported plates coming back wrong, supplied the EALPR dataset, and asked
for the redesigned Vehicles screen. Three strands, and one of them was a bug nobody
had found.

**Gate tiles had never once drawn a plate box.** The 24 Aug fix repaired the overlay
*request*; the response failed one layer down, because `kind="plate"` was missing
from the wire contract's `Box.kind` literal — so a plate in view took the whole
detections response down rather than appearing on it. The console half had been
right since the feature shipped. Fixed, and pinned by a test that ends at a
validated `CameraView`, because a test that stops at the box proves nothing about
screens. Boxes now also carry the plate's width in pixels: the aiming aid, green at
100px and above, amber below, and never a rejection.

**The reader is now observable.** "What the reader is seeing now" lists every read
attempt including the failures, with confidence, plausibility, width, the leading
candidate and votes-out-of-three. The pass log cannot answer what this answers — it
holds successes by construction, so a gate recording nothing looks identical whether
the camera is too far away, the model is failing, or nothing started.

**Alerts wait for a person** at the top of the Live tab — blacklisted, unregistered,
expired permit. Derived from passes, never stored; only the dismissal is a row, and
it is audited first and cannot be undone. A dismissal is per pass, not per car.
Dismissing is the one write under `/vehicles` a guard may make.

**The pass list is gone from the console**, at the owner's request and with the
costs accepted: registering from a read moved onto the alert, and the day's record
lives in the export. Recording is untouched. Movements gained a day picker, an
hourly chart, and snapshot thumbnails on every visit row.

**Waiting on the owner:** a labelling session (`eval_plates.py --label`) to produce
the confirmed-truth file, and site captures. Those are what turn "our port is
faithful" into "and it reads real plates correctly".

### P8 — Scale to 208 · 2–3 wk + hardware

Synthetic camera harness · staged benchmarks 1 → 8 → 32 → 104 → 208 · bounded worker pools replacing thread-per-camera (F5) · multi-process partitioning · sub-streams · UI pagination · decide Postgres **from measurement, not preference**.

**Done when:** the real camera mix holds its latency budgets for 4 hours on the real hardware, and killing one partition doesn't affect the others.

### P9 — Notifications · 1–2 wk

Alert rules + delivery log · in-app delivery · email/SMS only if required.

**The mobile half of this phase is superseded** by P13 below. It said the phone
would be wired **read-only** — "view, don't act, actions are riskier on a
phone". Mohamed was shown that position on 3 September 2026 and chose full
parity instead: the phone does everything the console does, including acting.
The risk the old wording named is real and is answered the same way the console
answers it — the engine decides what an account may do, and the phone stores no
role and no token. Nothing about alert delivery changes; nothing is sent to
anybody by P13.

### P10 — Go live · 1–2 wk + on-site

Operations runbook · failure drills · on-site calibration · parallel-run attendance against a manual roll call for 5 days · residual-risk review · constitution compliance review.

### P11 — Arabic console · 1.5–2 wk · `specs/008-arabic-console`

The school is Arabic-speaking and every word in the console is English — including the sentences that explain why a figure is incomplete. A guard who cannot read "no exit camera, so cars leaving are not being counted" is looking at a number that is wrong in a way the screen already told him about.

Message catalogue with an English and an Arabic column · right-to-left layout · dates and numbers through `Intl` · language held per account. The load-bearing half is a **contract change**: the engine writes 65 English sentences into `reason` / `detail` / `note` fields and ships them to the screen. Those become a code plus its facts, and the console builds the sentence — which is also what would let an Ask-bar agent reason about them.

**Done when:** a guard who reads no English can work a full shift, every engine explanation appears in Arabic with its consequence intact, and the camera picture is never mirrored.

### P12 — Ask · 1–1.5 wk · `specs/010-ask`

A guard at the gate knows the answer exists and not which page holds it. Ask is a box he types a question into, in Arabic, Franco-Arabic, English or a mixture. It does not answer the question — it works out **which of the system's existing queries the question is**, runs that one, and shows its real result with the evidence attached.

The language model reads a masked sentence and returns one menu id with its parameters, or "unsupported". It never sees a face, a frame or a record, and it never writes a word the operator reads: `AskAnswer` has no free-text field, so there is nowhere for an invented fact to live. Names and plates are replaced locally before anything leaves the site; a word the site does not recognise goes as typed, and Ask says which ones did.

Fourteen queries, one flat answer shape, one page. Adding a fifteenth is one row in `vg/ask/menu.py` plus its wording. The provider is Gemini's free tier and is swappable in one file — the seam is `parse(question) -> query + params | unsupported`.

**Done when:** a supported question returns the same figures the matching page shows; no known name or plate leaves the site on an Arabic test set; the four honest states each produce their own message with a reason; and with the cloud unreachable, detection, recording, the knife gate and the vehicle register are untouched.

### P13 — The phone does everything the console does · `specs/012-mobile-parity`

The phone app was made entirely of fixtures. Every figure on it was invented, several were regenerated at random on each visit, and any password signed you in as the same person with full rights. A guard holding it was looking at a school that did not exist, and could not tell.

It now runs the same product: all 16 screens, every action, both languages, both roles, against the same engine. It keeps its own shape — five tabs, not a shrunken sidebar — and its own package and build, because Mohamed chose two parallel apps over one shared codebase.

The console's pages import nothing from the desktop shell, so the phone ships its own **vocabulary** rather than its own pages: the same component names with phone bodies, and the same class names styled for a narrow screen. Every page and feature component is a byte copy that compiles against it unedited. ~7,950 lines are copied under a checker, ~11,000 copied and recompiled, ~1,600 genuinely written.

The known cost of copying is drift, and it is not hypothetical — `tokens.css` had already drifted while carrying a comment promising it could not. So `tools/check_parity.py` compares the shared files as bytes and fails the build when they differ, and CI gained a `mobile` job because the phone had never been typechecked there at all.

**Done when:** with the engine stopped every screen says so and shows no figure; a guard can decide a knife alert from the corridor it was raised in; the figures match the console side by side; and it is usable one-handed at 375px in both languages. The last of those needs a real phone and Mohamed.


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
| Camera → detection ready (person) | ≤ 250 ms | **22 ms p95 — passes** |
| Knife pass, on frames with a person | ≤ 250 ms | **17 ms p95 — passes** |
| Overlay freshness | ≤ 200 ms | not measured (P1-02) |
| Zone breach → visible | ≤ 5 s | built (P4), not yet timed by hand |
| Weapon detection → review queue | ≤ 2 s | built (P6); the confirm rule adds ~1 s by design, not yet timed end to end by hand |
| Camera drops → NO SIGNAL shown | ≤ 2 s | not measured |
| Lost bag search | ≤ 60 s | **replaced 23 Aug 2026** — there is no search to time. Bags are outlined live on the cameras being watched; a box appears within a second of the model seeing one |

**Measured 22–23 Aug 2026**, `python engine/tools/benchmark.py [--model weapons|bags]`,
on an RTX 2080 Max-Q (8 GB, laptop) on CUDA, timed over 60 frames of the labelled
walk-through clip:

| Model | p50 | p95 | throughput |
|---|---|---|---|
| `yolov8s.pt` (person) | 17.7 ms | 22.3 ms | 54.5 frames/sec |
| `knifebest.pt` (knife) | 15.8 ms | 17.4 ms | 61.4 frames/sec |
| `bagsearch.pt` (bags) | 27.9 ms | 30.9 ms | 35.3 frames/sec |

**Re-measured 30 Aug 2026**, same clip, same machine, during workload placement:

| Model | p50 | p95 | throughput |
|---|---|---|---|
| person | 12.2 ms | 16.6 ms | 81.8 frames/sec |
| bags, TensorRT | 22.3 ms | 23.3 ms | 44.8 frames/sec |
| bags, PyTorch CUDA | 21.5 ms | 29.0 ms | 44.2 frames/sec |

Nothing in that work touched a model's settings, so the person row moving is
**not** an improvement anybody earned — most likely a TensorRT engine present
now that was not in August. Treat the two blocks as two states of one laptop
rather than a trend.

The bag rows settle a question the workload plan got wrong: the compiled plan
was supposed to be costing ~31%. It is not. The medians are within noise and
TensorRT is better on p95, which is the figure a budget is set from.

### The hardware decision, 29 Aug 2026

Two reviews sit untracked in the repository root —
`VisionGuard-Deployment-Decision.html` and `VisionGuard-Hardware-Buildlist.html`.
Their load-bearing conclusions, recorded here so they can be cited without
opening a file that is not in git. **Commit them or delete them; untracked
evidence is not evidence.**

**Own the hardware, do not rent cloud inference.** This is a 24/7/365 workload.
A single cloud GPU costs $4,600–8,800 a year at that duty cycle and pays for a
whole workstation in 7–14 months. Cloud's one advantage is elastic scaling, and
it is worth nothing when the load never drops.

**The right shape is inference at the edge, management in the cloud** — remote
access without a child's face ever leaving the building.

**The "18× this machine" row above is a worst case, not a forecast.** A realistic
200-camera school needs roughly **two modern L4/A10-class GPUs**. The gap between
2 and 18 is software choices, not a hardware wall — which is exactly what
`specs/009-workload-placement` went and measured.

**What one camera costs the GPU**, in relative work units at 2 passes/second:

| Camera job | Runs | Units |
|---|---|---|
| Counting / intrusion | person detection (shared) | 2 |
| Entrance / attendance | person + face | 2 — face is on the CPU, so ~0 extra GPU |
| Weapon watch | person + knife, person-gated | 2.7 |
| **Gate / plates** | plate finder + character reader @ 5 Hz | **20** |

Plates are ten times heavier than anything else. Put them only at real gates.
The GPU is 60–70% of the bill; everything else is a fixed supporting cast.

### Whole-site demand, 30 Aug 2026

Per-model milliseconds do not answer "how many boxes do we buy". This does:

```powershell
python engine/tools/benchmark.py --site 100
```

It takes a camera count and a per-feature mix and prints seconds of processor
time per second, the same figure per camera, and how many cameras one box
carries. **The camera count is an argument, never a constant** — the site has
not fixed one, and a tool with 208 written into it would need editing the day
that changed.

| 100 cameras | site s/s | per camera | cameras per 8-core box |
|---|---|---|---|
| Before workload placement | 23.03 | 0.230 | 34 |
| After | 9.17 | 0.092 | 87 |

Decode was **65%** of the before figure — frames pulled off cameras nobody was
watching and discarded. Full breakdown and caveats in
`specs/009-workload-placement/measurements.md`.

The knife model costs the same as the person model, and it ran on that clip without
a single detection — which is the right answer, because there is no knife in it.
It is a **second** pass, but only on frames that had a person in them, so the sizing
arithmetic below stays the person model's question.

The bag model costs about 1.6× the person model and runs on the **whole** frame —
there is no person gate, because a lost bag is precisely the one with nobody near
it. It is absent from the scaling arithmetic below on purpose: it runs only while
somebody is holding down a search, never continuously, so it adds nothing to the
steady-state load. Idle cost is zero.

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
| ~~M2~~ | ~~Trained weapons model + class list + eval footage~~ | **ANSWERED 22 Aug 2026 — `knifebest.pt` supplied**, one class, trained 13 Aug 2026, now wired and shipped. Eval footage with a knife in it is still outstanding, so accuracy on school cameras remains unmeasured |
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
