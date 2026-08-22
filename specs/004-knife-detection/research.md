# Phase 0 — Research: Knife detection

Everything here was measured or read in the tree at commit `4e5d4e6` on
2026-08-22. The theme: **reuse the zones machinery, and let the two recorded
clips pick every number.**

---

## D1 — The model: `models/knifebest.pt`, on the GPU through ultralytics

**What it is** (read from the checkpoint): YOLOv8s, 11.1 M parameters, one
class `knife`, imgsz 640, trained 13 Aug 2026 with ultralytics 8.4.118 for 80
epochs on a combined public + on-site dataset; own-validation mAP50 0.90,
precision 0.83, recall 0.84. It is the `.pt` behind the
`knife-finetuned-v3.onnx` that `infer/weapons.py` decodes today, and it is
the only knife file left in `models/` (the owner deleted the `knife
detection/` folder from disk this week; it is gitignored like every weight).

**Decision**: load it with `YOLO(weights).predict(..., device, half,
imgsz, conf, iou)` exactly as `infer/persons.py` does. Verified in the pinned
runtime (ultralytics 8.4.7, torch 2.11.0+cu128): names `{0: 'knife'}`, zero
detections on flat grey and on noise, **p50 15.6 ms / p95 22.9 ms** a frame on
the RTX 2080 with FP16 — the same cost as the person model. The ONNX decode
and its onnxruntime dependency go: onnxruntime is not installed here, its GPU
build needs a CUDA the driver cannot offer, and the `.pt` already falls back
to the CPU loudly if it must. TensorRT: copy `export_tensorrt()` from
`persons.py`; the engine is built on the target machine, never archived.

**Kept**: module name `infer/weapons.py`, class `WeaponDetector`, dataclass
`DetectedWeapon(x, y, w, h, confidence, label)` in frame fractions, so the
config key `models.weapons`, the feature name and the capability key stay one
word. The model gets **its own lock** inside `detect()`: `SharedDetection`
guards the person model, nothing guards this one, and one instance is shared
by every camera thread of the worker.

**Alternatives rejected**: `yolov8n-oiv7.pt` cross-check (601 classes, never
benchmarked — P6 model manager work, not this spec); the 18-prompt YOLO-World
model (zero-shot, lists scissors and screwdrivers; the owner supplied a
trained replacement, which is what M2 in `docs/PLAN.md` asked for).

---

## D2 — False alarms, measured, and the three rules that remove them

Both clips in `engine/data/footage/` contain **no knife**. 120 frames sampled
from each (every 5th frame):

| | `baseline-empty` | `walk-through` |
|---|---|---|
| full-frame hits ≥ 0.35 | 25 | 3 |
| full-frame hits ≥ 0.50 | 9 | 1 |
| full-frame hits ≥ 0.60 | 0 | 0 |
| longest run of consecutive sampled frames with a ≥ 0.5 hit | **5** (same spot, 7 of 9 hits at x 0.8, y 0.9) | 1 |
| ≥ 0.5 hits with the box centre **inside a person box** | 2 (runs of 1) | 0 |
| ≥ 0.5 hits inside a person box grown by 25 % | 7 (runs of 2) | 0 |
| ≥ 0.5 hits on **person crops** (rejected, see plan) | 1 | 5 |

What the boxes are: a desk edge and a chair in the bottom-right corner, a
strip light on a wall. Room furniture, never something a person holds. Note
`baseline-empty` is not empty of *people* — somebody sits at the desk in 93 of
120 frames — so "only when a person is in view" alone would not have saved
it; the static corner object sits outside the person's box, which is what
does.

**Decisions** (all starting values, all in one place):

| Rule | Value | Why this value |
|---|---|---|
| confidence threshold (`models.weapons.conf`) | **0.5** | halves the hits vs 0.35; 0.6 would have been blind on these clips and is untested on a real knife |
| knife counts only if its box centre lies inside a person box, margin **0** | measured: 0 % margin leaves no run longer than one frame; 25 % lets the corner object back |
| open a scene after **3** hits spanning **≥ 1.0 s** (`CONFIRM_HITS`, `CONFIRM_SECONDS`) | the longest false run inside a person box is 1 frame; a held knife is visible for seconds |
| drop a candidate after **2 s** without a hit (`CANDIDATE_GAP_SECONDS`) | a blink between the three hits must not reset them, a minute must |
| close a scene after **10 s** without a knife (`GAP_SECONDS`) | the owner's "no flicker" rule; a knife is lost by the detector far more often than a body is (zones use 1 s) |
| cut at **120 s** (`MAX_SCENE_SECONDS`) | same as zones; the entry says it was cut |

> **Corrected 22 Aug 2026, after building it.** The claim below was measured on
> every 5th frame. Run live, the walk-through clip raised **one** scene in four
> loops (12.5 s, peak 0.76): the worker sees frames this analysis skipped. The
> thresholds are unchanged — they are still the best available guess — but
> SC-003 as written is not met, and cannot be retuned honestly until there is
> footage with a real knife to trade against.

With these, **neither clip produces a scene** (SC-003), and the regression
test replays exactly these measured sequences through the state machine.
Real accuracy on school cameras is still unmeasured — there is no footage
with a knife. `quickstart.md` §4 asks Mohamed to record one.

---

## D3 — Person gating through the shared pass

**Decision**: the worker holds the `SharedDetection` that `_start_people`
built and calls `detect(frame)` first. No person → return, the knife model is
never called. People → run the knife model on the **full frame**, then filter
boxes against the person boxes from the same call.

**Cost**: when counting/zones already ran the person model on that exact
frame (same `sequence`), the call is a cache hit. On a camera with no body
feature the knife worker pays the person pass itself at its own rate — that is
the price of "all cameras" (Q1 A), and it is the cheaper half of the pair
because most cameras show nobody most of the day.

**Rule 9**: knife detection needs the person *model object*, not the counting
*feature*. `_start_people` only builds the object when some enabled camera has
a body feature; otherwise knife detection reports "Person detection is not
running, so knives cannot be checked" — the same compromise restricted zones
already make, with the same sentence shape.

---

## D4 — The scene machine: `ZonesWorker` plus a candidate phase

Copy `features/zones.py` and change four things: no `_restricted` toggle
(every served camera is watched); a **candidate** per camera before `_open`
(D2); `GAP_SECONDS` 10; the entry records **peak confidence** instead of peak
people. End reasons: `gone` · `limit` · `shutdown`. Time comes from
`frame.captured_at`, never the wall clock, so the tests drive a two-minute
scene in microseconds exactly as `test_zones_live.py` does.

The worker's result per frame (`WeaponsResult`) carries the qualifying knife
boxes, so `_boxes(camera, "weapons")` reads them without touching the state
machine — the same reason `ZonesResult` exists.

---

## D5 — Recording: the zones recipe, unchanged

Own `Recorder(registry.bus, cfg.storage.weapon_clips_dir, clock=...)`, for the
reasons `_start_zones` states: a manual recording must never be refused by an
automatic one, and this feature's retention must never run over somebody
else's folder. `AlreadyRecording` → entry without a video and the sentence
saying so. Recording starts when the scene opens — about a second after the
first sighting — and the entry's `at` is the first sighting. No pre-roll (see
the plan's rejected list).

---

## D6 — Storage and retention

Copy `events/zones.py` to `events/weapons.py`: table `weapon_scene`, same
idioms (`db.connect`, `RLock`, ISO UTC, `close_orphans` on start). Differences:
review columns (`verdict`, `reviewed_by`, `reviewed_at`, `review_reason`),
`peak_confidence`, `model_version`, **no `replaced` state and no per-camera
cap**. Instead `expire(older_than)` marks `saved` rows `expired` — *before*
unlinking, same mark-then-unlink order — and runs at three points: engine
start, every `attach_clip`, every list read. No thread. `recent()` returns
expired rows; they stay listed with "Video no longer kept (older than 30
days)". `clip_retention_days` already exists in `StorageConfig` (30).

---

## D7 — Review and audit

Reuse `POST /weapons/{id}/review` and its tests. Two changes: the endpoint
takes `user: auth_deps.CurrentUser` and passes `user.name` as the reviewer —
the body's `actor` becomes optional and is ignored by the live store (the
wire is `extra="forbid"`, so the console must be able to omit it); and
`LiveStore.review_weapon` calls `self._log(reviewer, f"weapon.{verdict}",
scene_id, reason)` **before** `scenes.review(...)`, the `track` idiom. The
wire already refuses `pending` as a target verdict (422); the store refuses a
second verdict (row not `pending` → `None` → 404 "already reviewed").

Severity on the wire: `CRITICAL` while pending or confirmed, `INFO` once
dismissed. `item` is always "Knife"; `location` is the camera's area.

---

## D8 — Seven periods

`app.py` keeps the label vocabulary out of the store, as its comment asks:
`WEAPON_WINDOWS` plus `weapon_window(label, clock, term_from) -> (since,
until)`. Today and Yesterday are site-local calendar days (the
`_start_of_today` arithmetic, lifted into a helper); "Last N days" is rolling;
"This school year" starts at `hours.term_from` when set, else 365 days; "All"
is `(None, None)`. `Store.weapons` widens from `since_days: int` to
`(since, until)`; `MockStore.weapons` and `test_no_fixtures.py` line 127 follow.
Unknown label → 422 naming the allowed ones. `/breaches` is untouched.

---

## D9 — The page

Rebuilt from `Intrusion.tsx`, which already has the list, the 3 s poll, the
inline `<video>` and the "replaced while watching" pattern. Per entry: camera ·
area · time · duration · confidence · status badge · **Watch** (inline,
toggles) · **Open** (`<a target="_blank">` to the same-origin clip URL) ·
**Confirm knife** / **False alarm** while pending, else "Confirmed by *name*,
*time*" / "False alarm — *reason*". Headline: "*N* cameras being checked" from
`/weapons/cameras`; the list's own header counts entries in the chosen period.
Grid: `CamGrid feature="weapons"` so the enlarged view polls knife boxes.
Gone: `RecordButton`, `useSite`, `WEAPON_STEPS`, the `WeaponState` walk-through,
and `weaponStatus()`'s "Confirmed — police notified" — nobody is notified in
this spec, and saying so would be the most dangerous sentence on the page.

Knife boxes are `kind="weapon"`, `severity=CRITICAL`, so `boxColor()` already
paints them red; the label is "Knife" and the confidence travels in
`confidence` — no name ever reaches this overlay.

---

## D10 — Honest states

| Situation | `capabilities().weapons` | Page |
|---|---|---|
| worker running, store open | LIVE | list + grid |
| worker failed to start | UNAVAILABLE "Knife detection failed to start (*reason*)" | banner, no all-clear |
| person model absent | UNAVAILABLE "Person detection is not running, so knives cannot be checked — knives are looked for on people." | banner |
| no enabled camera | UNAVAILABLE "No camera is running, so nothing is being checked for knives." | banner |
| store failed | UNAVAILABLE "The knife log is not available…" | banner |

System Health gets a real `weapons` stage (healthy with model version, device,
camera count, last inference ms; otherwise the reason) replacing today's
"demo data" warning. `test_nothing_unavailable_still_returns_rows` keeps
holding: an unavailable `weapons` returns `[]`.

---

## D11 — What the alert spec will find ready

- One row per scene with camera, area (via roster), first sighting, end,
  peak confidence, model version, clip path/state, verdict, reviewer, time,
  reason — everything a WhatsApp/SMS/Gmail message needs.
- One method — `LiveStore.review_weapon` — where a confirmed verdict becomes
  known server-side after its audit entry. That is the only place a later
  notifier may hang, which is rule 10 by construction.
- `CAPABILITIES` already lists `attention`; `AttentionItem.kind = "weapon"` and
  `useAttention`'s "Review the detection" → `/weapons` exist unused.

Nothing in this spec sends, queues or schedules anything.

---

## Open risks

- **Accuracy is unmeasured on school cameras.** Every number in D2 comes from
  one room and one webcam. A recorded knife clip is the first thing to do
  after this lands (quickstart §4).
- **Person boxes and outstretched arms.** Margin 0 was the measured choice; a
  knife held at arm's length on a far camera may put its centre outside the
  body box. Revisit with the knife clip; the margin is one constant.
- **GPU load at 5 Hz on every camera** — fine for 1–3 cameras here; at 208 it
  is the same arithmetic as person detection (PLAN §7). The worker rate is
  `min(camera fps)` like zones; lower it there if the laptop stalls.
- **H.264 encoder**: the recorder falls back to mp4v on a machine without one
  and the browser then shows no picture — watch the log on the first clip.
- **Mixed line endings**: `api/*.py`, `config.py`, `events/zones.py`,
  `engine.yaml`, `services/*.ts`, `types.ts`, `test_zones_live.py`, `STATUS.md`,
  `docs/PLAN.md` are CRLF; `features/zones.py`, `infer/*.py`, pages are LF.
  `git diff --stat` catches a flip.
