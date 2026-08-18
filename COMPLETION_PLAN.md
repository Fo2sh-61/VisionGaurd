# VisionGuard — Completion Plan

**Prepared:** 10 August 2026
**Repo:** `E:\VisionGuard` (`web/` React+Vite console, `engine/` FastAPI + OpenCV/YOLO, `models/` weights)
**Purpose:** Get from "the console looks finished" to "the console is finished", with a clear line between what is real and what is still demo data.

---

## 1. Executive summary

Your instinct was right, but the diagnosis was not quite what you thought. You said the app "is looking good only but not ready to be wired with real engine." In fact **the engine is built and it was already wired.** Attendance, face recognition, the sighting store, the register and the live detection boxes are all implemented, tested and connected end to end.

They were dead because of **one missing line of code.**

In `engine/vg/api/app.py`, the function that starts face recognition called `recogniser.start()` on a variable that was never created. That raised `NameError`, which was swallowed by a `try/except Exception` designed to tolerate *operational* failures (a missing model file, a dead camera). The engine logged one line and carried on serving `MockStore` fixtures — invented students, invented arrival times — next to genuinely live camera feeds. Nothing on screen distinguished the two.

That is why the Attendance page showed people who do not exist, and why the enlarged camera view drew no boxes.

**Proof it is a regression, not missing work:** your database at `engine/data/visionguard.db` already contains **93 real recognition events of you** (`Mohamed Fouad`, confidence 0.78–0.85, model `sface-2021dec`) recorded on 7 and 9 August. The pipeline worked. An edit lost the constructor line.

### What I changed today

| # | Fix | File |
|---|---|---|
| 1 | Construct `RecognitionWorker` before starting it | `engine/vg/api/app.py` |
| 2 | Startup failures now return a reason and surface on System Health instead of vanishing | `engine/vg/api/app.py`, `engine/vg/api/live.py` |
| 3 | `VG_STRICT=1` makes the engine refuse to start rather than silently serve fixtures | `engine/vg/api/app.py` |
| 4 | `CRITICAL` log banner when recognition is not live | `engine/vg/api/app.py` |
| 5 | **Second real bug:** `self.people` (the detector worker) was overwriting the inherited `people()` method, so `GET /people` raised `TypeError` and the People page 500'd in live mode. Renamed to `self.people_worker`. | `engine/vg/api/live.py` |
| 6 | System Health now reports the true state of recognition, person detection, fights and weapons instead of a hardcoded "no models loaded" | `engine/vg/api/live.py` |

**Verified:** `187 passed, 6 skipped`. `pyflakes` clean across `vg/`, `tools/`, `tests/`. Recognition stack loads the real models, opens your real database, and produces a real register:

```
Attendance 2026-08-09 → expected=1 present=1 late=1 absent=0
  Mohamed Fouad: late, confidence 0.850, match=face
Health → [info] Face recognition: 1 enrolled, 5 faces, running on 1 camera(s)
```

### Answering your specific questions

**"Do we have a database for this storage or does it need to be prepared first?"**
Yes, it exists and it works. SQLite at `engine/data/visionguard.db`, four tables (`person`, `face_embedding`, `sighting`, `camera`), created automatically on first run, currently holding 1 person / 5 face vectors / 93 sightings / 3 camera records. **It does not need to be prepared.** It does need three things before go-live: tables for the event-producing features (intrusion, weapons, fights) which do not exist yet, migrations, and a retention policy. See Phase 2.

**"In the big camera window I should see realtime face detection."**
That code was already correct and is now live. The enlarged view polls `/cameras/{id}/detections` every 100 ms, and each poll also tells the engine somebody is watching, which raises that camera from ~5 Hz to 12 Hz recognition for two seconds. Green box = recognised and named, blue = a face it will not name. It drew nothing before only because `recogniser` was `None`.

**"I need everything ready, just waiting for the models to be inserted."**
For attendance, that is now true. For the other features it is not, and the honest reason is that *the model is not the missing part* — the missing part is the worker, the event table and the review workflow around it. Section 5 sets out exactly what each one needs.

### The one-sentence version for your stakeholder

> Attendance, face recognition and live camera analytics are real and running today; intrusion, weapons, fights, counting analytics, lost-item search and person tracking are still demo data, and the system has no authentication yet — that is roughly 8–11 weeks of work, and no part of it should be shown to a school as finished until it is.

---

## 2. Why the architecture is worth keeping

Before the criticism, the credit — because it changes the plan. This codebase is unusually well structured for its stage, and that is why the remaining work is additive rather than a rewrite.

**The `Store` seam.** `MockStore` defines every endpoint's shape; `LiveStore` subclasses it and overrides only what is genuinely live. Everything not yet built keeps returning fixtures and the front end cannot tell. This means **each feature can go live independently** — no flag day, no "nothing works until everything works". The list of methods `LiveStore` does *not* override is a precise, self-maintaining to-do list.

**Features share models, never workers.** `FeatureWorker` enforces that a camera set to `[counting]` alone is fully served without loading a face model. The comments record that this was learned the hard way — counting used to silently depend on attendance being on.

**Demand-driven inference.** Cameras run at a cheap background rate and boost to 12 Hz only while someone is watching. At the 208-camera scale the comments anticipate, running everything at full rate does not fit on any GPU and would be spent on views nobody has open.

**Honest degradation is a design rule, not an afterthought.** Stale frames are flagged and shown under `NO SIGNAL` rather than presented as current. `null` headcount is distinguished from a measured zero. Absence is *derived* from missing sightings, never written — so a camera that was down cannot silently mark a room of children absent, and the register can be recomputed when a threshold changes. The face gallery refuses a match when the top two candidates are within 0.06 of each other, because a confident wrong name on a register gets believed.

**The irony worth naming:** a system this careful about not lying to its operator shipped a failure mode where every number on the Attendance page was invented and nothing said so. That is the specific gap fixes 2–6 close, and the principle behind Phase 2's acceptance criteria.

---

## 3. Honest inventory — what is real, what is not

`LiveStore` overrides 20 of ~34 store methods. Everything else is `MockStore` fixtures.

### Real today

| Capability | Endpoint | Notes |
|---|---|---|
| Camera ingest | — | RTSP / webcam / file, auto-reconnect, health counters |
| Snapshot | `GET /cameras/{id}/snapshot` | JPEG, `X-Frame-Stale` header |
| Live stream | `GET /cameras/{id}/stream` | MJPEG, event-driven not timer-driven |
| **Live detection boxes** | `GET /cameras/{id}/detections` | **Fixed today** |
| Live headcount | `GET /cameras/counts` | One request for the whole grid |
| Camera roster | `GET /cameras` | YAML + runtime additions, DB-persisted |
| Add / remove camera | `POST /sources`, `DELETE /sources/{id}` | Soft delete, history retained |
| Test connection | `POST /sources/test` | Really opens the stream, pulls a frame |
| **Attendance** | `GET /attendance` | **Fixed today.** Group + person mode |
| CSV export | `GET /attendance/export` | Confidence + camera per row, absences included |
| People directory | `GET /people` | **Fixed today** (was 500ing) |
| Groups | `GET /groups` | Derived from gallery |
| Zones | `GET /zones` | Read from `engine.yaml` |
| System health | `GET /system/health` | **Now honest about each subsystem** |
| Site info | `GET /site` | Server-authoritative date — a wrong client clock can't corrupt a register |
| School profile | `GET /settings/school` | |

### Still demo data

| Capability | Endpoint | Model? | Real blocker |
|---|---|---|---|
| Intrusion breaches | `GET /breaches` | ✅ shared | **No event table.** Occupancy is computed every frame and thrown away |
| Zone enable/disable | `PATCH /zones/{id}` | — | In-memory only, lost on restart |
| Weapon detections | `GET /weapons/detections` | ✅ `yolov8m-worldv2-school.pt` | No worker, no event table, no clip capture |
| Weapon review | `POST /weapons/{id}/review` | — | Nothing to review |
| Fights | `GET /fights` | ❌ **none** | No trained model. Longest lead time |
| Fight feedback | `POST /fights/{id}/feedback` | — | Claims to store a training label; stores nothing |
| Counting page | `GET /count` | ✅ shared | Per-camera counts are real; areas, capacity, history are fixture. No time-series table |
| Lost items | `POST /lost-items/search` | ✅ `yolov8m-worldv2-search.pt` | No footage recording, no index. Cannot search footage that was never kept |
| Track a person | `POST /track` | ⚠️ `osnet` present, `torchreid` not installed | No cross-camera re-ID, no path reconstruction |
| Group roster | `GET /groups/{name}` | — | Mock |
| Person history | `GET /people/{p}/history` | — | Mock — though `SightingStore.history()` exists and works |
| Users | `GET /users` | — | Mock. No user table |
| Home "needs attention" | `GET /attention` | — | Mock. Should aggregate real events |
| Alert rules / delivery | `GET /settings/*` | — | Mock, **and no delivery mechanism exists at all** |
| Audit log | `GET /audit` | — | Mock. `recordTrackSearch()` is an explicit no-op |
| Network scan / DVR | `POST /sources/scan`, `/dvr` | — | Mock |

### Dead UI controls

`CameraModal` "Save clip" · `Weapons` "Save clip" · `Attendance` "Notify parent" · `SystemHealth` "Restart" · `Login` role picker (see below).

---

## 4. The five things that must not reach a school

Ranked by consequence, not effort.

### 4.1 There is no authentication — CRITICAL

`web/src/app/AuthContext.tsx` is a hardcoded two-account object and a `localStorage` role picker. There is no password, no token, no session. The API has **zero** auth: every endpoint is open.

Anyone who can reach port 8000 can pull the full student directory, every attendance record, live camera streams and the biometric gallery. `localStorage.setItem('vg.role','admin')` in a browser console is a full privilege escalation. Even the `admin`-only "Notify parent" gate is client-side cosmetics.

This is a school, and the subjects are minors. **Non-negotiable before any pilot.**

### 4.2 Biometric data of minors — legal, not just technical

The system stores face embeddings of children. Under GDPR Art. 9 (and Egypt's PDPL No. 151/2018, if deployed locally) this is special-category biometric data with heightened consent requirements for minors.

`gallery.py` already makes the right engineering choice — it stores vectors, never images, which limits the blast radius — and its own docstring correctly notes this "does not by itself settle the legal position."

**Needed:** a Data Protection Impact Assessment, a lawful basis, guardian consent capture and withdrawal, a retention schedule, a documented subject-access/erasure path, and encryption at rest. This runs in parallel with engineering from day one because it gates deployment, not code.

### 4.3 School hours are still in night-test mode

`engine/engine.yaml`:

```yaml
hours:
  from: "00:00"
  to:   "23:59"
```

The file's own comment explains this is for testing after dark. Left as-is, a caretaker seen at 01:14 is marked present for the school day. My verification reproduced exactly this: your 7 August sighting at 01:14 Cairo local was scored `on_time`.

**Fix:** real hours (e.g. `07:00`–`15:30`, `late_cutoff: 08:00`) before any real register. One-line change, high consequence.

### 4.4 One person is enrolled, from a laptop webcam

The gallery holds you, 5 vectors, captured at close range on a webcam. A real deployment needs hundreds of people enrolled from the actual entrance cameras at the actual mounting angle. `gallery.py` is right that several varied captures beat one good one.

The `0.363` cosine threshold is OpenCV Zoo's published default, and `faces.py` says plainly it "is a starting point, not a truth". With one person enrolled the margin gate never fires — there is no runner-up. **Accuracy at scale is unmeasured**, and it is the number the stakeholder will ask about.

### 4.5 Silent degradation was possible at all

Now fixed, but the class of bug matters more than the instance. A `try/except Exception` around a startup path meant a typo produced a console that looked perfectly healthy while every number on it was invented — for days. Phase 2 makes "is this real or demo?" answerable from the UI on every page.

---

## 5. The delivery plan

Eleven weeks to a defensible pilot. Phases 3–7 are largely parallelisable across two engineers; the ordering below assumes one.

### Phase 0 — Stabilise (DONE today, ~½ day remaining)

- [x] Fix `RecognitionWorker` instantiation
- [x] Make startup failures loud and visible on System Health
- [x] Add `VG_STRICT=1`
- [x] Fix the `self.people` method collision
- [ ] **You:** set real school hours in `engine.yaml`
- [ ] **You:** run the engine and confirm your own face boxes green in the enlarged view
- [ ] Add `pyflakes` (or `ruff`) to CI — it catches this exact bug class in under a second

*Acceptance:* start the engine, stand in front of the camera, see a green box with your name, then see yourself on the Attendance register with a real arrival time.

### Phase 1 — Attendance production-ready (2 weeks)

The only feature close to done. Finish it completely before starting another — one genuinely trustworthy feature demos far better than six half-built ones.

1. **Enrolment UI** — replace `tools/enroll.py` with a console page: capture from a live camera or upload photos, show per-photo quality, require ≥3 varied captures, allow deletion. Nobody enrols 400 students from a CLI.
2. **Bulk import** — CSV of name/type/group/guardian + a photo folder.
3. **Threshold calibration** — `tools/calibrate_faces.py` exists; run it on real enrolments from the real cameras and set the operating point from measurement, not the published default.
4. **Accuracy report** — measured FAR/FRR on a held-out set. This is what makes the stakeholder claim defensible.
5. **Wire `history()` and `group()`** to `SightingStore` — the query already exists, only the store override is missing.
6. **Person-mode attendance is wrong today** — `live.py` hardcodes every historical day to `ON_TIME` and never applies the late cutoff. Fix.
7. **"Notify parent"** — either implement or remove. A dead button in a demo is worse than no button.

*Acceptance:* enrol 20 people through the UI; register matches ground truth for a full day; export opens in Excel with traceable confidences; a threshold change recomputes history correctly.

### Phase 2 — Security and data foundation (2 weeks) — **blocks pilot**

1. **Real authentication** — password login, hashed (argon2/bcrypt), JWT or server session, `users` table, roles enforced **server-side** on every endpoint. Delete the localStorage role picker.
2. **Events database** — the single largest structural gap. Tables for `breach`, `weapon_detection`, `fight_incident`, `count_sample`, `audit`, `user`, plus Alembic migrations (already in `requirements.txt`, unused). Every event-producing feature waits on this; build it once, properly.
3. **Audit log** — make `/audit` real. `recordTrackSearch` is currently a documented no-op. Searching for a named child must leave a record.
4. **Retention** — `clip_retention_days: 30` is configured and enforced nowhere. Add the sweeper.
5. **Encryption at rest** for the biometric DB; TLS in front of the API; rate limiting.
6. **A "demo data" badge in the UI.** Every page whose store method is still `MockStore` should say so on screen. This is the durable fix for what went wrong here.

*Acceptance:* unauthenticated request to any endpoint returns 401; an `it`-role token is refused admin actions server-side; a track search appears in the audit log; a page backed by fixtures is visibly labelled.

### Phase 3 — Intrusion (1 week) — the template

Deliberately first among the event features: person detection and zone geometry **already work every frame** and the result is discarded. This is the smallest gap between "computed" and "recorded", so it establishes the event pattern the rest reuse.

1. `IntrusionWorker` consuming `PeopleWorker` occupancy, applying `Schedule.is_restricted_at()` (already implemented and tested) and `min_dwell_seconds`.
2. Write `breach` rows; override `LiveStore.breaches()`.
3. Persist zone enable/disable to the DB.
4. Zone editor UI — draw a polygon on a live frame. Editing normalised coordinates in YAML is not an operator workflow.
5. Clip capture on breach, using the configured pre/post-roll.

*Acceptance:* walk into a restricted zone during restricted hours → a breach appears on the Intrusion page within seconds with a clip; walk through during permitted hours → nothing; a sub-dwell pass through the edge of frame → nothing.

### Phase 4 — Weapons (1.5 weeks)

Model present (`yolov8m-worldv2-school.pt`, YOLO-World, 18 saved prompts, `conf: 0.25` tuned for recall).

1. `WeaponWorker` on cameras with the `weapons` feature.
2. Detections → event table; wire `weapons()`, `review_weapon()`.
3. **Preserve the human gate.** The design is explicit that detection alone never notifies, calls or locks anything. Keep it.
4. Clip + still capture as evidence.
5. **Evaluate before trusting.** `engine.yaml` says this model "is zero-shot, not fine-tuned, and has never seen school CCTV. Treat its scores with suspicion until the eval harness says otherwise." Score it against `yolov8n-oiv7.pt` on real footage and pick on evidence.

*Acceptance:* golden-clip set scored, FP rate per camera-hour published, review workflow round-trips, dismissed detections remain visible in history.

### Phase 5 — Counting and analytics (1 week)

Per-camera counts are already real; the page is not.

1. `count_sample` time-series table, written at a low rate.
2. Areas + capacity in config; wire `count()` for "Right now", "Today by hour", "This week by day".
3. Cross-camera de-duplication for overlapping views (the UI already claims "counted once across overlapping cameras" — make it true or remove the claim).

### Phase 6 — Lost items and person tracking (2 weeks)

Both need **footage that is actually recorded.** `footage_dir` is configured; `tools/record.py` exists; nothing runs it in production. You cannot search footage you never kept.

1. Continuous segmented recording + retention sweeper.
2. Lost items: index detections from `yolov8m-worldv2-search.pt` at ingest so search is a DB query, not a re-scan. Make the endpoint a job + poll — the UI's "Searching footage…" state is already built for it.
3. Track: install `torchreid` (note the flagged Python 3.14 risk — validate early), wire `osnet_x1_0_market1501.pth`, reconstruct paths from sightings + re-ID.
4. Track searches **must** write audit rows before returning. The contract in `app.py` already says the audit is committed before the result; honour it.

### Phase 7 — Fights (3 weeks, start data collection in week 1)

The only feature with **no model at all**. `yolov8s-pose.pt` is the intended input; the classifier on top does not exist.

Longest lead time and it is dominated by data, not code. Begin collecting and labelling staged + real footage in week 1, in parallel with everything above.

Also: `POST /fights/{id}/feedback` currently claims "not a fight" is stored as a negative training example. It is not stored at all. Either build the loop or change the copy.

### Phase 8 — Notifications (1 week)

`GET /settings/delivery` returns email/SMS/WhatsApp/app targets. **No delivery mechanism exists.** Implement, or remove from the UI before the stakeholder sees it and assumes it works.

---

## 6. The "just plug in the model" contract

This is what you were really asking for. Adding a new detection feature should touch four small files and nothing else.

```
                    ┌──────────────┐
   RTSP / webcam ─► │ CameraSource │ ─► FrameBus ─┬─► RecognitionWorker ─► SightingStore
                    └──────────────┘              ├─► PeopleWorker ──────► (zone occupancy)
                                                  ├─► WeaponWorker ─────► EventStore   ◄── to build
                                                  └─► YourNewWorker ────► EventStore
                                                                              │
                                                        LiveStore ◄───────────┘
                                                            │
                                                     FastAPI (frozen contract)
                                                            │
                                                     services/api.ts ─► pages/
```

**To add a feature:**

1. `vg/infer/<model>.py` — load weights, return typed detections. Follow `infer/persons.py`.
2. `vg/features/<feature>.py` — subclass `FeatureWorker[YourResult]`, implement `analyse(frame)`. Threading, rate limiting, boost and result-freshness are inherited; write no concurrency code.
3. `vg/events/<feature>.py` — persist events. Follow `events/sightings.py`.
4. `vg/api/live.py` — override the store method that currently returns fixtures.

`engine.yaml` gets a `models:` entry and the camera gets the feature name in its `features:` list. **The API contract and the entire front end stay untouched** — that is the payoff of the `Store` seam.

**Three rules the codebase already enforces. Keep them:**

- A feature must never require another feature to be switched on.
- Geometry crosses the API as fractions of the frame, never pixels.
- Degradation arrives as payload, never as a 5xx. System Health must stay 200 even when everything it describes is broken.

**And one rule this incident adds:**

- A subsystem that fails to start must say so *in the UI*, not only in the log. If a page is serving fixtures, the page says so.

---

## 7. Risk register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Recognition accuracy collapses at scale | Critical | **High** | Phase 1 calibration on real cameras before any accuracy claim. One enrolled person tells you nothing |
| Deployed without auth | Critical | Medium | Phase 2 gates the pilot. No exceptions |
| Biometric/minors legal challenge | Critical | Medium | DPIA + consent from day one, parallel to engineering |
| Faces too small on real entrances | High | High | `MIN_FACE_PIXELS = 80` is measured, not guessed. Survey mounting positions **before** buying cameras |
| Weapons model false positives | High | High | Human gate (already designed in) + eval harness before enabling |
| No fight training data | High | Certain | Start collection week 1 |
| GPU capacity at 208 cameras | High | Medium | Demand-driven rate limiting exists; load-test early |
| `torchreid` on Python 3.14 | Medium | Medium | Already flagged in `requirements.txt`. Validate in Phase 6 week 1 |
| `.engine` files are machine-specific | Medium | Low | Already documented — always ship `.pt`, build TensorRT on the target host |
| Windows timezone | Low | Certain | `tzdata` is in `requirements.txt`; without it every timestamp is 3 hours out for Cairo |

---

## 8. What to tell the stakeholder

**Show, with confidence:** live multi-camera view, enlarged view with real-time face detection and named boxes, attendance register built from real recognition, CSV export with traceable confidences, camera onboarding, System Health honestly reporting what is and is not running.

**Say plainly:** intrusion, weapons, fights, counting analytics, lost-item search and person tracking are demo data today. Give the phase and the date for each.

**Do not claim** any accuracy number until Phase 1 calibration produces one.

**Ask for:** a decision on the security/legal timeline (it gates everything), access to real entrance cameras for calibration, and permission to begin collecting fight footage now.

The strongest position is that the hard part — the ingest, inference and event architecture — is built and proven; what remains is mostly attaching known models to a known pattern. That is a materially better story than a prettier demo with nothing behind it, and it has the advantage of being true.

---

## Appendix A — Run it

```bash
# Engine
cd E:\VisionGuard
pip install -r engine/requirements.txt
python engine/tools/serve.py              # http://127.0.0.1:8000/docs

# Refuse to start rather than silently serve fixtures (use in CI / production)
set VG_STRICT=1 && python engine/tools/serve.py

# Console
cd web && npm install && npm run dev      # http://localhost:5173

# Enrol a face (until the Phase 1 UI exists)
python engine/tools/enroll.py --name "Student Name" --type Student --group "Grade 8"

# Catch the bug class that caused this
python -m pyflakes engine/vg engine/tools engine/tests
```

**Startup log should now read:**

```
recognition on ['cam-laptop'] - 1 enrolled, 5 faces, 5 Hz idle / 12 Hz watched
```

If instead you see `FACE RECOGNITION IS NOT RUNNING`, the reason follows on the same line and also appears on the System Health page.

## Appendix B — Files changed today

| File | Change |
|---|---|
| `engine/vg/api/app.py` | `RecognitionWorker` construction; `_start_people`/`_start_recognition` return an error reason; `_reason()` / `_reraise_if_strict()`; `VG_STRICT`; `CRITICAL` banner |
| `engine/vg/api/live.py` | `self.people` → `self.people_worker` (method-shadowing bug); `recognition_error` / `people_error`; real `_recognition_stage()` and `_people_stage()` on System Health |

Verification: `187 passed, 6 skipped` · `pyflakes` clean · recognition stack loads real models and real DB · `pyflakes` confirmed to flag the original bug on a reverted copy and pass on the fixed one.
