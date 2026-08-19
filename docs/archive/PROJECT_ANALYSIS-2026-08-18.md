> **⚠ SUPERSEDED — history only. Do not plan from this file.**
> The current plan is `docs/PLAN.md`; current state is `STATUS.md`.
> Archived 19 Aug 2026.

# VisionGuard — Full Project Analysis (Current State)

**Prepared:** 18 Aug 2026 · **Source:** direct read of the repository at `E:\VisionGuard` (all engine source, both front ends, configs, model inventory, and the three planning documents)
**Purpose:** a complete, honest snapshot of what exists today. This document is input material for writing the final product specification and a development plan to finish the product for end users. Everything below was verified against the code itself, not just the docs, except where marked "documented, not re-run".

---

## 1. What the product is

VisionGuard is a school-campus vision system for **Greenfield International School** (site config; timezone Africa/Cairo). It watches CCTV/webcam feeds and answers operator questions about campus activity through a desktop web console and a mobile app:

- **Attendance** — recognise faces at entrances, build a daily register
- **People counting** — how many people are in an area right now, and history
- **Track a person** — reconstruct one person's path across cameras
- **Restricted zones (intrusion)** — alert when someone enters a zone out of hours
- **Knife/weapon detection** — flag possible weapons for mandatory human review
- **Lost bag (lost items)** — search recorded footage for described objects
- **People directory & enrolment** — who is enrolled, browser-based face enrolment
- **System health** — honest per-subsystem status

A "Fights" feature existed in earlier designs and its code remnants remain (`Fights.tsx`, `/fights` endpoints), but it was **removed from the current design and navigation entirely** — it is unreachable in the UI as of the 18 Aug design.

The product has an unusually strong stated design ethic: the UI must never claim more than the system knows (NO SIGNAL over stale frames, human gate on weapon alerts, false alarms kept in history, audit-before-result on person searches, "DEMO DATA" honesty about fixtures).

---

## 2. Repository layout

```
E:\VisionGuard\
  engine\            Python FastAPI + OpenCV/YOLO backend ("the engine")
    vg\api\          app.py (all endpoints), live.py (LiveStore), store.py (MockStore fixtures), schemas.py
    vg\ingest\       camera capture, reconnect, frame bus, camera DB store
    vg\infer\        model runners: persons (YOLOv8s), faces (YuNet+SFace), tracking (ByteTrack pool)
    vg\features\     FeatureWorker base + people / recognition / tracking workers
    vg\identity\     face gallery (SQLite+NumPy), appearance tracker (loiterwatch wrapper), enrolment service
    vg\events\       sightings store, appearance store, area-count store (all SQLite)
    tools\           serve.py, enroll.py, record.py, calibrate_faces.py, audit_models.py, measure_latency.py
    tests\           10 test files; HANDOFF records 270 passing (documented, not re-run)
    engine.yaml      site config: hours, models, areas, cameras, zones
    data\footage\    2 recorded clips + JSON sidecar with 21 hand-labelled ground-truth marks
  web\               React+Vite desktop console (TypeScript). WIRED to the engine over HTTP.
  mobile\            React+Vite phone app. Still 100% fixtures (mockData.ts) — NOT wired.
  models\            all weights + MODELS.md/README.md inventory; loiterwatch re-ID package lives here too
  design\            .dc.html design specs; "18-8 design/" is the current implemented design
  dev.ps1            one-command dev workflow: up / down / doctor / test / -Mock / -Clip
  DEV_PLAN.md        THE planning document (10→15 Aug, decisions log in Part 0)
  COMPLETION_PLAN.md audit record from 10 Aug (stale numbering; historical value only)
  HANDOFF.md         freshest status note (18 Aug) — matches what I verified in code
  docs\INTEGRATION-PLAN.md  SUPERSEDED (kept for its acceptance-criteria section)
```

Notable repo facts: **not a git repository** (per DEV_PLAN §1.4 note). No `.venv` yet — deliberately blocked (see §10). Runs on system Python 3.14, torch 2.11.0+cu128, CUDA verified on an RTX 2080 Max-Q.

---

## 3. Architecture (verified in code)

### 3.1 Engine pipeline

```
Cameras (webcam / RTSP / looped file)
   └─ CameraRegistry → one capture thread per camera → FrameBus (drop-oldest pub/sub)
        ├─ RecognitionWorker   YuNet detect + SFace embed (CPU) → FaceGallery.match → SightingStore
        │      └─ note_face() → binds a recognised name onto the tracked body (one-way)
        ├─ PeopleWorker        YOLOv8s person detect (GPU) → counts + zone occupancy (feet-point in polygon)
        ├─ TrackingWorker      shared YOLO boxes → ByteTrack → loiterwatch appearance stitching → AppearanceStore
        └─ (area-count sampler thread: 60 s samples → area_count table)
   LiveStore (subclasses MockStore, overrides only what is real) → FastAPI → web console
```

Key mechanisms, all implemented and working:

- **`FeatureWorker` base class** — each feature runs its own thread(s) per camera, subscribes to the frame bus, rate-limits itself (~2–5 Hz idle), and **boosts to 12 Hz for 2 s** when a viewer polls `/cameras/{id}/detections` ("demand-driven inference"). Results carry a 3 s TTL, so stale results read as absent rather than current.
- **Features share models, never workers.** The person detector is built once and handed to both PeopleWorker and TrackingWorker. Recognition is fully independent of person detection; no feature requires another to be on.
- **The Store seam** — `MockStore` defines every endpoint's shape with fixtures; `LiveStore` overrides only what is genuinely live. Every feature can go live independently; the un-overridden methods are a precise to-do list (enumerated in §5).
- **Graceful shutdown** is solved (the historical "can't Ctrl-C the server" problem): `SHUTTING_DOWN` event checked by MJPEG generators, `timeout_graceful_shutdown`, parallel camera stop with one shared deadline, `psutil` orphan cleanup. Regression-tested in `test_shutdown.py`.
- **Startup failure is loud, not silent**: every subsystem start returns `(worker, error_reason)`; reasons surface on `/system/health` and as a CRITICAL log banner. `VG_STRICT=1` turns any startup failure into refusal to start. This machinery exists because a swallowed `NameError` once caused the console to serve invented attendance for days.
- **`VG_MOCK=1`** serves the entire API from fixtures with no models/cameras — sub-second start for UI work. `VG_CAMERAS=<ids>` switches cameras without editing YAML (used by `dev.ps1 up -Clip`).

### 3.2 Identity model — the core design invariant

Two kinds of identity evidence, deliberately never merged:

- **FACE** (green in UI): a face names a person. SFace 128-d embeddings; gallery match requires threshold (0.363 default) AND a 0.06 margin over the runner-up, else it refuses to name ("too close to call"). Model name stored with every vector; cross-model comparison is refused outright.
- **APPEARANCE** (blue): clothing/build says only "same body as before". loiterwatch `IdentityStitcher` (NumPy colour/shape features, no neural net, no GPU) maps ByteTrack's churning track IDs onto stable IDs across gaps and cameras. Measured need: ByteTrack alone produced 35 IDs for a handful of people on the test clip.
- Names attach to bodies only when a recognised face sits **inside** that body's box (≥60% containment), in that frame; ambiguity (two candidate bodies) is refused. Bindings expire after 8 h (clothing is not an identity tomorrow). Recognition backfills names onto earlier same-day rows for that stable ID. Operator can `correct` (unname + fresh identity) and `merge`.
- **Tracking never uses recognition to track** — a stored name-binding leaking across identities is the bug that once labelled everyone "Mohamed Fouad".

### 3.3 Frontend architecture

- **web/**: React + Vite + TypeScript. All data flows through `services/api.ts` → `http.ts` → engine REST (base URL from `.env.local` `VITE_API_BASE`). `wire.ts` mirrors engine schemas; `format.ts` converts wire shapes to display shapes so `pages/` never changed during wiring. Pages: Home(Ask), Attendance, Counting, LostItems, TrackPerson, Intrusion, Weapons, People (+PeopleGroup, PersonHistory, Enrol), SystemHealth, Settings, Users, Login. Navigation is grouped ASK / WATCH / MANAGE; current labels: "Lost bag", "Knife detection", "Restricted zones". Fights is gone from nav.
- **mobile/**: same stack, different shell (5 bottom tabs, one generic tool screen). **Entirely on fixtures** — `services/api.ts` imports from `mockData.ts` with artificial delays and `Math.random()` counts. Wiring it means replacing function bodies with the same HTTP calls web uses (the seam was built for this).
- Geometry crosses the wire as fractions (0–1); UI multiplies to percentages. Camera tiles poll `/cameras/counts` once per grid; enlarged view polls `/cameras/{id}/detections` ~100 ms with a `feature` parameter selecting the overlay.
- **Auth is cosmetic**: `AuthContext.tsx` is a hardcoded account object; role checks are client-side only; the API has zero authentication on any endpoint.

---

## 4. Data layer (verified schemas)

Single SQLite file `engine/data/visionguard.db`, tables created on first use:

| Table | Written by | Contents |
|---|---|---|
| `person` | FaceGallery / enrolment | id, name, type, group, detail |
| `face_embedding` | FaceGallery | person_id, **model name**, dims, vector blob, quality, source |
| `sighting` | SightingStore (recognition) | person, camera, UTC + site-local date, confidence, match_kind, model, runner_up. Debounced to 60 s per person/camera; first-of-day always written (arrival time). |
| `appearance_sighting` | AppearanceStore (tracking) | stable_id, optional person_id, camera, time, fractional box, confidence, track_id. Sampled ≥3 s gap; `path_for()` collapses rows into camera-to-camera stops. Separate from `sighting` on purpose (different claim strength, retention, failure mode). |
| `area_count` | counts sampler | one row per area per 60 s; hourly/daily averages feed the counting charts |
| `camera` | CameraStore | cameras added via the UI (soft delete; merged with engine.yaml at boot, DB wins clashes) |

Design principles enforced in code: attendance is a **view over sightings** (absence is derived, never written; register recomputable); every sighting keeps confidence + model version; site-local date is computed with the site's tz offset, never the server's or client's.

**What does NOT exist yet:** tables for breaches, weapon detections, fight incidents, users, audit, zones (zones live in engine.yaml; enable/disable override is in-memory and lost on restart). No Alembic migrations in use (alembic is installed, unused). No retention sweeper running (`clip_retention_days: 30` configured, enforced nowhere; `AreaCountStore.prune`/`AppearanceStore.prune` exist but nothing calls them). No footage recording runs in production (`tools/record.py` exists as a manual tool).

---

## 5. Feature-by-feature truth table (as of 18 Aug 2026)

### Real end-to-end

| Feature | Evidence |
|---|---|
| **Camera ingest** | RTSP/webcam/file with auto-reconnect, health counters, last-good-frame cache, MJPEG stream, JPEG snapshot with `X-Frame-Stale`, per-camera live detections, one-call grid headcounts, add/remove/test camera (DB-persisted) |
| **Attendance** | Done per owner. Register from real sightings, bounded by real school hours (06:30–16:00, late after 08:00), late minutes computed, camera-count honesty metric, CSV export with per-row confidence+camera and absences included |
| **Enrolment Studio** | `/people/enrol` — staged sessions (nothing written until commit), per-photo quality scoring (face pixels ≥80, detector confidence, similarity-vs-existing to force varied angles), 3-photo floor, capture-from-camera or upload |
| **People directory & groups** | From the gallery; `photo_on_file` honesty flag; today's status per person |
| **Live overlays** | Per-feature overlays via `_boxes(camera_id, feature)`: attendance→faces (green/blue), track→appearance IDs (+name only when a face is inside the body now), counting→unlabelled bodies |
| **People counting (partial)** | **Real for "Main entrance"** (the laptop webcam), capacity 40 from engine.yaml, 1 s polling, live YOLO boxes, real hour/day history from `area_count` (60 s samples, bars split per area, live/demo flag per part). Other areas are demo and labelled as such. Sums across cameras, `deduplicated: false` — no cross-camera de-dup exists |
| **Tracking (engine)** | ByteTrack + loiterwatch appearance IDs, stable across frames/cameras; `/tracking/live` returns real IDs; face→body naming + backfill + operator correct/merge all implemented |
| **System health** | Honest per-subsystem stages incl. startup-failure reasons; fights/weapons explicitly self-report as not wired |
| **Zones (read)** | Real from engine.yaml, occupancy computed per frame via feet-point ray casting (concave polygons, schedules with 3 modes — all implemented AND tested) |

### Fake / demo (MockStore fixtures still serving)

| Capability | The real gap |
|---|---|
| **Intrusion breaches** | Occupancy is computed every frame **and thrown away**. No breach table, no worker writing events, no clip capture. Smallest real-vs-recorded gap in the codebase. |
| **Zone enable/disable** | In-memory only; lost on restart. No zones table. |
| **Weapon detections + review** | Model file present; **no worker, no event table, no clip evidence, no review persistence**. |
| **Lost items search** | Search model present; **no footage recorded, no index**; endpoint returns fixtures after a delay. |
| **Track-a-person UI (partial)** | Backend returns real face+appearance stops, but the page still has fixture elements: badges/confidence styling, past-path fallback, and a "save clip" that writes nothing. Known bug: subject bar says "Not identified by face" even when the box names them (page derives `identified` from `match`, and `_tracked_boxes` always sets `match=APPEARANCE`; must derive from name presence). |
| **Fights** | No model (owner is building one). Endpoints+page exist but are unreachable from nav. Feedback endpoint claims to store a training label; stores nothing. |
| **Users / login** | No user table, no passwords, no tokens, no server-side roles. **Every endpoint is open.** |
| **Home "needs attention"** | Fixtures; should aggregate real events once they exist. |
| **Alert rules / delivery** | Fixtures; **no notification delivery mechanism exists at all** (no email/SMS/WhatsApp). |
| **Audit log** | `/audit` returns fixtures. Live `track()` does call an internal `_log` and returns an `audit_id`, but there is no durable audit table — the write-before-result contract is honoured only in-memory. |
| **Network scan / DVR connect** | Mock. |
| **Person history page** (`/people/{p}/history`) | Mock, though `SightingStore.history()` exists and works — only the store override is missing. |
| **Dead UI controls** | Camera modal "Save clip", Weapons "Save clip", Attendance "Notify parent", SystemHealth "Restart". |

---

## 6. API surface (implemented in `app.py`, all shapes mirrored in `services/wire.ts`)

Meta: `/healthz`, `/site` · Cameras: snapshot, MJPEG stream, `/cameras/{id}/detections?feature=`, `/cameras/counts`, `/cameras` · Intrusion: `/zones` (GET/PATCH), `/breaches`, `/intrusion/cameras` · Weapons: detections, review (the human gate), cameras · Fights: list, feedback, cameras · Attendance: `/attendance`, `/attendance/export` (CSV) · Counting: `/count` · Lost items: `/lost-items/search` · Track: `/track` (audit-before-result contract), `/audit`, `/tracking/live`, `/tracking/{id}/correct` · Enrolment: sessions CRUD + photos + capture + commit · Directory: `/people`, `/groups`, `/groups/{name}`, `/people/{p}/history`, `/users` · Attention: list + ack · Sources: CRUD + scan + dvr + test + areas · Settings: school, alerts, delivery · System: `/system/health`.

Contract rules enforced throughout: one endpoint per UI function; geometry as fractions; server-authoritative time (UTC + site offset on every instant); confidence mandatory on detections; **degradation is payload, never 5xx** (health returns 200 even when broken; failed camera test returns `ok:false`, not an error status).

---

## 7. Model inventory (from `models/README.md` + `engine.yaml`, cross-checked)

| Model | File | Status |
|---|---|---|
| Person detect | `yolov8s.pt` (COCO, GPU, 640) | ✅ the workhorse; wired |
| Face detect | `face_detection_yunet_2023mar.onnx` (227 KB, CPU) | ✅ wired |
| Face embed | `face_recognition_sface_2021dec.onnx` (37 MB, CPU, 128-d) | ✅ wired. **SETTLED permanently** (DEV_PLAN §0.2) — switching face models invalidates every enrolment; gallery refuses mixed models |
| Tracking | ByteTrack (in ultralytics, CPU) | ✅ wired |
| Appearance re-ID | loiterwatch IdentityStitcher (NumPy, not a neural net, **no GPU path**) | ✅ wired |
| Weapons (interim) | `yolov8m-worldv2-school.pt` — YOLO-World v2, **prompted not trained**, 18 prompts incl. scissors/screwdriver/hammer (guaranteed false-alarm sources in a school) | Present, NOT wired. Configured `conf: 0.25` for recall; human gate is the design mitigation |
| Weapons (baseline) | `yolov8n-oiv7.pt` — genuinely trained, 601 classes incl. weapon classes, 50× smaller | Present; the honest scoring floor for the eval harness |
| Weapons (final) | **Owner will supply a trained model** | Incoming; Phase-4 worker must be built against the interface so weights are a config swap |
| Search / lost items | `yolov8m-worldv2-search.pt` — 35 clothing/object prompts (incl. `hijab` — tuned for the actual population) | Present, NOT wired; colour comes from a separate histogram step |
| Pose | `yolov8s-pose.pt` | Present; foundation for fights; NOT wired |
| Fights classifier | — | **Does not exist.** Owner building it; input contract (keypoints vs clips vs crops) still undeclared |
| Deep re-ID | `osnet_x1_0_market1501.pth` present, but **the real re-ID model is being handed over separately**; osnet_x1_0 ≠ osnet_ain_x1_0 (not interchangeable; wrong one gives confident nonsense) | ⛔ do not wire against the file in the repo |
| TensorRT `.engine` files (5) | Build outputs compiled for this laptop's RTX 2080 + a newer ultralytics | Never portable artifacts; rule is ship `.pt`, build `.engine` on the target machine |

Owner supplies all models; VisionGuard never sources or trains them. TensorRT everywhere is a stated goal but tensorrt is not installed yet (`pip install tensorrt` fresh; the only existing copy lives in a severed project's venv). Note ByteTrack and loiterwatch are not neural nets and have **no GPU path** — do not promise one.

---

## 8. The rules that must not break (hard invariants, each rooted in a real bug)

1. **A face names a person; clothing only says "same body".** Never merged into one number or colour. Green = face, blue = clothing, amber = unidentified.
2. **Tracking never uses recognition to track.** Names are a live annotation on top; a stored binding leaking across identities is what made everyone read as one person.
3. **Each feature draws its own camera overlay** (`_boxes(camera_id, feature)`). Tracking IDs on the attendance page was a real bug.
4. **Never claim precision the code lacks.** Counting sums across cameras with no de-dup (`deduplicated: false`); no capacity set → no percentage shown.
5. **Geometry crosses the API as fractions, never pixels.**
6. **Degradation is payload, not 5xx.**
7. (From the recognition incident) **A subsystem that fails to start must say so in the UI**, not only the log; fixture-backed pages must be visibly labelled.
8. A feature must never require another feature to be switched on.
9. Weapon detection **always** waits for a human; the review endpoint is the only thing that fans out. False alarms stay in history; there is no delete.
10. Track searches write the audit entry **before** the result returns.

---

## 9. Known bugs and immediate next steps (from HANDOFF, 18 Aug — verified plausible against code)

1. **Track badge bug (small):** subject bar shows "Not identified by face" even when the box names the person. Fix: derive `identified` from name presence, not from `match` (which is always APPEARANCE for tracked boxes, by design).
2. **Clear Track page's remaining fake data** — show only real sightings.
3. **Clip recording:** agreed design is continuous export of whatever was on the main view, stitched into one video across the operator's (or auto-follow's) camera sequence. Nothing is written today.
4. **Counting accuracy:** reads 4–6 with one person present. `person.conf` is 0.35; `PeopleWorker` ignores the `min_area` gate that `PersonDetector.detect()` already supports. Needs tuning against the real scene.

---

## 10. Blockers, external dependencies, and settled decisions

**Blocked / waiting on the owner (Mohamed):**

- **Re-ID model handover** + three facts (architecture; loads via plain torch or torchreid; Python version it was built on). This **blocks creating `.venv`** — if torchreid is needed, Python 3.14 may be impossible and the whole environment drops to ~3.12. Until then the project deliberately runs on system Python 3.14 (`-AllowSystemPython`).
- **Trained weapons model** (on another machine) — re-scopes weapons work; until it lands, build the worker against the interface.
- **Fight classifier input contract** (keypoints vs clips vs crops) — decides buffer design; the classifier itself is in progress, not ready.

**Settled decisions (do not reopen):**

- SFace is the permanent face embedder (not a placeholder for ArcFace).
- The old "British School" project is fully severed — nothing from it is used or referenced.
- Model Manager v1 activates via DB-write + worker restart, **not** hot-swap.
- Auth lands in Phase 2 (after enrolment/attendance polish), per an explicit considered-and-closed decision.
- DB is source of truth; `engine.yaml` is bootstrap seed only (pattern already followed by `add_camera`).

**Working-style constraints (recorded in HANDOFF):**

- Ask ~4 clarifying questions before acting; surface choices, don't decide for him.
- He supplies all models — never source or train them.
- Dev loop: `.\dev.ps1 doctor` / `up [-Mock|-Clip]` / `down`; tests via `python -m pytest engine` (270 pass) and `cd web && npx tsc -b --force` (plain `--noEmit` is a silent no-op due to project references).

---

## 11. What must not reach a school (production gaps, ranked by consequence)

1. **No authentication anywhere.** Anyone who reaches port 8000 can pull the student directory, attendance, live streams, and the biometric gallery; `localStorage` role edit = full "privilege escalation". Non-negotiable before any pilot.
2. **Biometric data of minors** — face embeddings of children fall under GDPR Art. 9 / Egypt PDPL 151/2018. Gallery stores vectors, never images (good), but a DPIA, lawful basis, guardian consent + withdrawal, retention schedule, subject-access/erasure path, and encryption at rest are all outstanding. Gates deployment, runs parallel to engineering.
3. **No events database** — breaches/weapons/fights/audit/users/zones tables don't exist; every event feature waits on this single structural gap.
4. **Recognition accuracy is unmeasured at scale** — 1 person enrolled, from a laptop webcam; threshold 0.363 is the published default, not calibrated; the margin gate has never fired (no runner-up exists). `tools/calibrate_faces.py` exists for this.
5. **No notification delivery** of any kind, while the settings UI implies email/SMS/WhatsApp.
6. **No footage recording/retention in production** — lost items and clip evidence are impossible until it runs; retention config is enforced nowhere.
7. **Dead buttons** in a demo (save clip, notify parent, restart) — build or remove.

---

## 12. The extension pattern (how every remaining feature gets built)

Adding a detection feature touches four files and nothing else — the pattern is proven by the three existing workers:

1. `vg/infer/<model>.py` — load weights, return typed detections (copy `infer/persons.py`)
2. `vg/features/<feature>.py` — subclass `FeatureWorker[Result]`, implement `analyse(frame)`; threading/rate/boost/freshness inherited, zero concurrency code
3. `vg/events/<feature>.py` — persist events (copy `events/sightings.py`)
4. `vg/api/live.py` — override the store method that returns fixtures today

Plus a `models:` entry in engine.yaml and the feature name on the camera. The API contract and both front ends stay untouched.

**Everything left to build is one of two shapes:** a worker that turns frames into events (intrusion, weapons, fights), or a store method that reads events back (the pages that show them). The architecture needs no redesign.

Recommended build order from DEV_PLAN Part 5 (≈11 weeks to a defensible pilot): Phase 1 finish attendance ops (bulk import, camera wizard) → **Phase 2 security + events DB + zones table + audit + DEMO badges (blocks pilot)** → Phase 3 intrusion (the template event feature — computed already, just discarded) → 3b Model Manager (upload → benchmark against the labelled clip → activate-on-restart) → 4 weapons (worker + review queue + 3-candidate eval harness) → 5 counting (time-series done; areas/capacity/de-dup claims) → 6 footage recording + lost items + re-ID track → 7 fights (data collection starts week 1) → 8 notifications.

Definition-of-done per phase is written and concrete (e.g. Phase 3: walk into a zone in restricted hours → breach + clip within seconds; permitted hours → nothing).

---

## 13. Environment & tooling facts a plan must respect

- Windows, PowerShell workflow via `dev.ps1` (up/down/doctor/test, -Mock, -Clip, -AllowSystemPython). Ports 8000 (engine) / 5173 (web) / 5174 (mobile).
- GPU: RTX 2080 Max-Q; torch 2.11.0+cu128 on Python 3.14 verified CUDA-true. Face pipeline deliberately CPU (GPU reserved for detection).
- Deterministic testing assets exist and matter: the `walk-through` clip + 21 labelled ground-truth points is the regression suite and the intended Model-Manager benchmark input; prefer clips over webcam for all pipeline work.
- `engine.yaml` currently: real school hours (06:30–16:00, late 08:00), one enabled camera (`cam-laptop`, area "Main entrance", features attendance+counting+intrusion+track), the clip camera (disabled by default), an RTSP placeholder (disabled), two zones (one always-on test zone on the laptop cam), one area capacity (Main entrance: 40). The `face:` model block is **declarative only** (FacePipeline doesn't read it yet); `reid:` is deliberately commented out pending handover.
- Scale ambition on record: ~208 cameras. Existing answers: demand-driven rates (built), batching across cameras (designed, not needed yet), sub-streams for decode (config-time), TensorRT on the deployment machine (later), tiered per-feature schedules (documented in INTEGRATION-PLAN §1.4).
- Performance budgets already promised by UI copy: weapon alert < 2 s end-to-end; intrusion breach < 5 s; lost-item search < 60 s; counting refresh ~5 s; full-day track < 30 s.

---

## 14. Honest overall assessment

**Strengths.** The architecture is genuinely sound and proven in three live features; the Store seam means every remaining feature lands independently with no flag day; honesty-by-design is implemented, not aspirational (stale flags, None-vs-zero, margin-gated naming, per-feature overlays, startup-failure surfacing); the identity model (face vs appearance separation, expiring bindings, refusal on ambiguity) is unusually careful; test coverage is real (270 passing) and there is a labelled regression clip.

**Weaknesses / risks.** Everything event-shaped is still fixtures; security is absent entirely; the mobile app is 100% mock; three critical models are external dependencies with no dates (re-ID, trained weapons, fights); recognition accuracy is a single-person anecdote; the legal/biometric position for minors is unaddressed; there is no git history, no venv, no migrations, and single-file SQLite as the sole store; counting over-counts today (conf/min_area tuning); cross-camera de-duplication — which the UI copy already promises — is unbuilt and is a schema-level decision, not a tuning one.

**The one-sentence status:** camera ingest, attendance (with browser enrolment), live overlays, engine-side tracking, and single-area counting with history are real today; intrusion, weapons, lost items, fights, the track UI's polish, users/auth, audit, notifications, and the entire mobile app are demo data; the remaining work is dominated by one events database, one auth layer, three externally-supplied models, and a sequence of worker+table+override slot-fills the architecture was explicitly built to receive.

---

## 15. Inputs the final product spec still needs (open questions)

These are the decisions a specification must close, because the code cannot decide them:

1. **Pilot scope and hardware**: how many cameras, which entrances get attendance, what GPU(s) on the school server (sizes the schedule per INTEGRATION-PLAN §1.4), do the cameras expose sub-streams?
2. **Auth model**: user roles list, session mechanism (JWT vs server session), who administers users.
3. **Retention policy**: clips, footage, appearance rows, sightings — durations drive storage sizing and the privacy position.
4. **Legal position for biometrics of minors**: lawful basis, consent capture flow, erasure path — may constrain which features ship at all.
5. **The three model handovers** (re-ID + its 3 facts; trained weapons; fight classifier + input contract) and their dates.
6. **Notification channels** actually required for v1 (email? SMS? WhatsApp? in-app only?).
7. **Counting de-duplication**: accept "summed, not de-duplicated" honestly in v1, or require the cross-camera identity work now?
8. **Clip recording design** is agreed in principle (stitched main-view export) — needs format, storage location, and retention parameters.
9. **Mobile app**: is wiring it to the engine in scope for the final product, or is desktop-first acceptable?
10. **Arabic/RTL**: needed at launch or not (affects layout throughout, not just strings).
