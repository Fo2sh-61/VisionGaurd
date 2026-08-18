# Closing the loop: wiring the front end to a real engine

> ## ⚠ SUPERSEDED — do not plan from this document
>
> **`DEV_PLAN.md` is the only planning document.** This one predates it and is
> kept for its criteria section, which is still good.
>
> Known-wrong here: §"Attendance" names **ArcFace** as the embedding model. The
> face model is **SFace**, and that is settled — see `DEV_PLAN.md` §0.2. Any
> other model or phase claim in this file should be checked against `DEV_PLAN.md`
> before it is acted on.

The two apps in this repo are complete front ends over fixtures. This document
is the plan for replacing those fixtures with real trained models, and — more
importantly — the **criteria** that define when the seam between them is
correctly built.

Read the criteria section first. Most integration projects fail not because the
models are bad but because the contract between the model layer and the product
layer was never written down, so every feature negotiates its own ad-hoc shape.

---

## 0. What already exists, and what it commits you to

Both apps funnel every data call through one file:

- `web/src/services/api.ts`
- `mobile/src/services/api.ts`

Every function there is already `async` and already returns a typed shape from
`types.ts`. That is the seam. **Nothing in `pages/` should change when the
backend becomes real.** If a page has to change, the contract was wrong.

Two properties of the existing types matter a lot and should be preserved:

| Existing choice | Why it matters for the engine |
|---|---|
| `DetectionBox` / `CameraZone` are in **percentages** of the frame | Model output is normally normalised `[0,1]`; multiply by 100 and it drops in. No resolution coupling, no per-camera calibration in the UI. |
| `Camera.offline` is explicit, separate from "no detections" | The UI is required to say NO SIGNAL rather than show a stale frame. The engine must therefore distinguish *stream down* from *stream up, nothing found*. |
| `tone` (`good`/`warn`/`bad`/`neutral`) is carried on every row | Severity is a backend decision, not a colour the UI invents. Thresholds live server-side and are auditable. |
| Confidence is shown in labels (`"Layla A. 96%"`, `"71%"`) | The product already promises to surface uncertainty. Models must return calibrated scores, not just argmax. |

---

## 1. The linking criteria

These are the acceptance tests for the seam. A feature is "connected" only when
all of them hold.

### 1.1 Contract criteria

1. **One transport shape per existing function.** Every function in `api.ts` maps
   to exactly one endpoint. No endpoint returns a shape the UI has to reassemble.
2. **Normalised geometry.** All boxes/zones as fractions of frame width/height,
   origin top-left, before any rotation correction. The engine owns rotation.
3. **Server-authoritative time.** Every event carries a UTC timestamp plus the
   camera's local offset. The UI never computes "11 min ago" from its own clock.
4. **Stable IDs.** Cameras, people, zones, events and clips all have opaque
   string IDs that survive restarts. The current fixtures already use string IDs.
5. **Confidence is mandatory, not optional.** Any detection surfaced to a user
   carries a `[0,1]` score. The UI decides presentation; the engine never
   silently drops low-confidence results — it labels them.
6. **Degradation is data, not an error.** A camera being down, a model being
   unloaded, or a recorder refusing a password are all *states the UI already
   renders*. They must arrive as normal payload fields, not as HTTP 500s.

### 1.2 Behavioural criteria (these come straight from the UI's promises)

The front end makes explicit honesty commitments. Each becomes a backend test:

| UI promise | Backend acceptance test |
|---|---|
| "NO SIGNAL — showing last received frame" | When a stream drops, the API keeps returning the last frame with `offline: true` within one poll interval. It never returns a stale frame with `offline: false`. |
| Weapon detection always waits for a human | No downstream action (notify, call, lock) can be triggered by the detector alone. The confirm/dismiss endpoint is the *only* thing that fans out. |
| False alarms stay in the history | Dismissed detections are retained and returned by the history endpoint. Deleting them is not an available operation. |
| "Every tracking search is recorded in the audit log" | The audit write is committed **before** the search result is returned. If the audit write fails, the search fails. |
| Paused intrusion zones stay visible | Disabling a zone changes its `enabled` flag only. It is never filtered out of list or camera responses. |
| Fights need ≥3 seconds | The temporal window is enforced server-side and the duration is returned, so the UI's "7 seconds" is the model's actual measurement. |

### 1.3 Performance criteria

Budgets implied by the current copy — the UI already tells users these numbers,
so they are commitments:

| Feature | Budget | Source of the number |
|---|---|---|
| Weapon detection → alert on screen | **< 2 s** end-to-end | "Detected 14 seconds ago" implies near-real-time; "last check 2 seconds ago" |
| Fight detection → appears in Needs attention | < 60 s | "11 min ago" is acceptable latency for review, but detection itself should be prompt |
| Intrusion breach → alert | < 5 s | it's a security control |
| People counting refresh | ~5 s, "updated seconds ago" | copy on the counting page |
| Lost item search | **< 60 s** | "This usually takes under a minute" |
| Attendance daily summary | ready by 09:00 | Settings default "9:00am each school day" |
| Track a person, full school day | < 30 s | it's an investigation tool, not live |

### 1.4 Capacity criteria — the hard constraint

The demo claims **208 cameras** and "weapon detection runs continuously on all
208". Take that seriously, because it, not model accuracy, is what will size the
build.

Rough arithmetic to do properly before committing:

- **Decode** is the first wall. 208 H.264 1080p streams cannot be decoded on CPU.
  You need hardware decode (NVDEC) and probably sub-streams: pull the camera's
  *secondary* low-res stream (typically 640×360) for continuous analytics, and
  only pull the main stream on demand for clips.
- **Inference scheduling** — you cannot run seven models on every camera at full
  frame rate. The design already implies a tiered schedule, and this should be
  made explicit and configurable:

  | Tier | Cameras | Rate | Models |
  |---|---|---|---|
  | Entrances | ~4–6 | 5–10 fps | face detect + embed |
  | All cameras | 208 | 1–2 fps | person detect, weapons |
  | Zone cameras | ~10 | 2–5 fps | person detect + zone logic |
  | Fight-enabled | subset (design excludes sports halls) | 5+ fps (temporal needs it) | video classifier |
  | Lost items | on demand only | batch over recorded footage | open-vocab detector |

  Note the design already states face recognition runs on 4 cameras only and
  fights are disabled in PE areas. Those aren't UI copy — they're the capacity
  plan.

- **Retention** drives storage more than models do. Decide clip retention
  (30/90 days?) and whether you keep frames or only events + clip pointers.

**Deliverable for this section:** a written capacity model (cameras × fps ×
model × ms/frame → GPU-seconds/second) proving the target hardware can hold the
schedule, with headroom. Do this before buying anything or training anything.

---

## 2. Architecture to build

Six layers. The front end only ever talks to layer 5.

```
1  Ingest        ONVIF discovery, RTSP pull, decode, frame bus
2  Inference     model runners, batched, GPU-scheduled
3  Tracking      per-camera tracks + cross-camera re-ID
4  Events        rules, debounce, clip extraction, persistence
5  API           REST + WebSocket, shaped exactly like services/api.ts
6  Front end     web/ and mobile/ (already built)
```

### Layer 1 — Ingest

- ONVIF WS-Discovery for the "Scan network" flow the UI already has.
- RTSP client per camera with reconnect/backoff. Emits health transitions
  (`ok` / `down` / `auth`) — these map exactly to the existing `SourceStatus`.
- Decode to a shared frame bus (GStreamer, or FFmpeg + shared memory).
- Per-camera "last good frame" cache — this is what backs NO SIGNAL.

Onboarding flows the UI already implements and that this layer must serve:
network scan, DVR/NVR connect-and-enumerate-channels, single IP camera, raw RTSP
URL. Each needs a test-connection endpoint that returns one frame.

### Layer 2 — Inference (model per feature)

Candidate model classes — pick per your data and licensing:

| Feature | Model class | Notes |
|---|---|---|
| Attendance | face detector (SCRFD/RetinaFace) + embedding (ArcFace) + gallery ANN index | The gallery is the "Photo on file" flag already in the People page. No photo → cannot be recognised, which the UI already communicates. |
| People counting | person detector (YOLO family) + tracker + line-crossing | Plus overlap de-dup, see below. |
| Intrusion | person detector + point-in-polygon against zone + schedule | Zones and their hours already modelled. |
| Track a person | person re-ID embeddings (OSNet / CLIP-ReID) + temporal assembly | UI already distinguishes "face match" (green) from "appearance match" (blue) — keep that distinction in the response. |
| Fights | temporal video classifier (X3D / SlowFast / VideoMAE) on clip windows | Needs ≥3 s window per the product rule. |
| Weapons | object detector fine-tuned for weapons, tuned for **recall** | Precision is recovered by the mandatory human review step. |
| Lost items | open-vocabulary detector (OWL-ViT / GroundingDINO) + colour/attribute filter | Matches the UI's item + colour + area + time query. Runs retrospectively over stored footage. |

Two engineering notes that will bite:

- **Multi-camera de-duplication** for counting. The UI explicitly promises "a
  person standing between two cameras is counted once". That needs either a
  camera overlap graph with homography, or re-ID-based merging. Decide early;
  it's a schema decision, not a tuning one.
- **Calibration.** Raw softmax scores are not probabilities. Run temperature
  scaling or isotonic regression per model so the "78% confidence" shown to a
  head teacher means something.

### Layer 3 — Tracking

Per-camera multi-object tracking (ByteTrack or similar) to give stable track
IDs, then cross-camera association via re-ID embeddings for "Track a person".
Store embeddings in a vector index (FAISS/pgvector) keyed by track.

### Layer 4 — Events

Where detections become the things the UI shows:

- Debounce and hysteresis (one fight, not sixty frames of fight).
- Clip extraction on event (pre-roll + post-roll from the main stream).
- Persistence: Postgres for events/people/zones/audit; object store for clips;
  vector index for embeddings.
- The review state machine for weapons: `detected → confirmed | dismissed`,
  with actor and timestamp. This is the table that backs both the incident
  timeline and the honest false-alarm history.

### Layer 5 — API

Map one-to-one onto the existing functions. Illustrative:

```
GET  /attendance?mode=group&group=Grade%208&date=…   → AttendanceResult
GET  /count?place=Cafeteria&when=Right%20now         → CountResult (incl. areas[])
GET  /zones                                          → Zone[]
PATCH/zones/:id            {enabled}                 → Zone
GET  /breaches?window=Today                          → Breach[]
GET  /fights?window=&place=                          → FightIncident[]
POST /fights/:id/feedback  {notAFight:true}          → 204     ← training signal
GET  /weapons/detections?window=                     → WeaponDetection[]
POST /weapons/:id/review   {verdict, actor}          → WeaponDetection
POST /lost-items/search    {item,colour,area,since}  → job id → poll/stream
POST /track                {who,date,from,to}        → TrackResult (audit first!)
GET  /system/health                                  → SystemHealth
GET  /sources                                        → CameraSource[]
POST /sources/scan | /sources/dvr | /sources/test    → onboarding flows
```

Plus a **WebSocket** channel for the things that must arrive unprompted:
weapon detections, fight detections, intrusion breaches, camera up/down. The
Home "Needs your attention" list and the mobile push settings both assume this
exists.

Long-running work (lost-item search) should be job-based: POST returns an id,
progress streams, result is fetched. The UI's "Searching footage…" state is
already built for exactly this.

### Layer 6 — Front end changes

The pages don't change. These do:

1. **`services/api.ts`** — replace bodies with `fetch`. This is the bulk of it.
2. **`services/ask.ts`** — currently keyword matching. Keep the
   `(question, role) => AskOutcome` signature and swap the body for an LLM
   intent call, or leave as-is; it works.
3. **New: real auth.** `AuthContext` currently trusts `localStorage`. Needs
   token issue/refresh, and **roles enforced server-side** — the code comment in
   `routes.tsx` already flags that the current guard is a product rule, not a
   security boundary.
4. **New: error and empty states.** Every page currently assumes success. Needs
   per-request error handling, retry, and a degraded mode when the engine is
   unreachable.
5. **New: pagination/virtualisation.** 1,742 students and 208 cameras will not
   render as flat lists.
6. **New: live channel** wiring for the WebSocket above.

---

## 3. Sequencing

Do it in this order; each stage is independently demonstrable.

| Stage | Goal | Done when |
|---|---|---|
| **A. Contract** | Freeze the API spec against `types.ts`. Write it as OpenAPI. | Front end runs unchanged against a *mock server* implementing the spec. Delete the fixture files. |
| **B. Ingest** | Real cameras in, health out. | System health page shows true camera/recorder state; onboarding flows add a real camera; NO SIGNAL is real. |
| **C. One model end-to-end** | Prove the whole pipeline on the narrowest feature. | Intrusion works live: person detector + zone + event + alert. Chosen because it needs no training data and no re-ID. |
| **D. Always-on detection** | Weapons at scale, with the human gate. | Weapon alert < 2 s on all cameras; confirm/dismiss writes an incident; false alarms appear in history. |
| **E. Identity features** | Face gallery + attendance. | Daily attendance matches a manual roll call to an agreed accuracy on a pilot group. |
| **F. Counting** | Multi-camera dedup. | Counts validated against manual count in one area, across a camera overlap. |
| **G. Temporal + retrieval** | Fights, then lost items. | Fights hit an agreed recall on a labelled test set; lost-item search returns < 60 s. |
| **H. Track a person** | Cross-camera re-ID. | Path reconstruction validated against a known walked route; audit entry present for every search. |
| **I. Hardening** | Auth, pagination, errors, monitoring. | Pen-test passed; engine restart doesn't lose events. |

Stage A is the one people skip and the one that determines whether the rest is
painful. Do not start C until A is done.

---

## 4. The feedback loop

The UI already collects labels — wire them to training, or the buttons are lies:

- "Not a fight" → negative example for the fight classifier.
- Weapon "false alarm — kitchen utensil" → hard negative for the weapon detector.
- Attendance corrections → face gallery updates.

Build: label store → periodic export → retrain → **shadow evaluation** against
production traffic → promote by version. Never hot-swap a model without a
held-out comparison; keep `model_version` on every event so a regression is
attributable.

---

## 5. Decisions needed before starting

These block the contract and only you can answer them:

1. **Which models already exist, trained on what?** The plan above assumes
   greenfield. If some are trained, stages E/G shorten considerably.
2. **Target hardware.** How many GPUs on the school server? This decides the
   camera schedule in §1.4.
3. **Do cameras expose sub-streams?** If not, decode cost roughly quadruples.
4. **Retention policy** for clips and frames — drives storage sizing and,
   separately, the privacy position.
5. **Face recognition legality.** Biometric processing of minors is regulated
   very differently by jurisdiction (GDPR Art. 9, BIPA-style laws, local
   education rules). This is a prerequisite, not a later step — it may constrain
   which features can ship at all, and consent/retention rules will shape the
   People schema. Get a written position before building the gallery.
6. **Arabic/RTL.** The Settings page currently admits full RTL "lands next
   build". If it's needed at launch, scope it now — it affects layout
   throughout, not just strings.

---

## 6. What not to do

- Don't let the engine invent UI strings. It returns states and numbers; the
  front end formats them. Otherwise localisation and copy changes require a
  backend deploy.
- Don't collapse the "detected" and "confirmed" states for weapons to simplify
  the schema. That distinction is the product's core safety claim.
- Don't filter low-confidence results server-side to make demos look clean. The
  UI is built to show uncertainty and the history is meant to be honest.
- Don't start model work before stage A. A mock server that satisfies the
  contract is worth more than a good model with no agreed interface.
