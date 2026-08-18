# VisionGuard — Developer Plan

**For:** Mohamed · **Date:** 10 Aug 2026 · **Revised:** 15 Aug 2026 · **Status:** ready to implement

This is the working document. It covers four things:

1. **Fix your workflow** — why you can't kill the server, and the setup that fixes it
2. **The full picture** — what every feature does, in plain terms
3. **Model architecture** — which model, where it runs, and how they layer for speed
4. **GUI-first** — every setting from the browser, no YAML, no CLI

**Document status.** This is the only planning document. `COMPLETION_PLAN.md` is an
**audit record only** — its phase numbering is stale and must not be followed.
`docs/INTEGRATION-PLAN.md` is **superseded**; it names ArcFace as the attendance
embedder, which is wrong (see §0.2).

---

# PART 0 — Decisions log

Settled on 15 Aug 2026. These close questions the rest of this document used to
leave open. Where an older section contradicts one of these, this section wins.

## 0.1 The British School project is severed

No models, no specs, no code, no virtual environment from `E:\British School`
are used by VisionGuard. That project's `004-multicam-person-tracking` spec —
a CLI + cv2 tool on ArcFace, `.pkl` galleries and torchreid — described the same
capability as feature #8 on an incompatible stack. It is not a fallback and not
a reference.

**Five live references must be stripped.** One is functional, not cosmetic:

| Where | What it does | Action |
|---|---|---|
| `engine/tools/serve.py:44` | Prints *"Use the CUDA environment: `E:\British School\.venv\Scripts\python.exe`"* when no GPU is found — actively instructs you to run VisionGuard on the dead project's interpreter | Replace with `.\.venv\Scripts\python.exe` |
| `DEV_PLAN.md` §1.4 | Built the venv by cloning that project's `site-packages` | Rewritten — see §1.4 |
| `models/README.md` ~87–93 | Points at that project's `osnet_ain_x1_0` and ArcFace R50 | Keep the `osnet_ain` ≠ `osnet_x1_0` warning and the SFace ≠ ArcFace warning. Delete the cross-project pointers |
| `engine/vg/infer/faces.py:16` | Docstring calls ArcFace "considerably stronger", sourced from that project | Rewrite — the face model is now settled, see §0.2 |
| `docs/INTEGRATION-PLAN.md:154` | Names ArcFace as the attendance embedder | Stamp SUPERSEDED or delete |

## 0.2 The face model is settled: SFace stays

SFace 128-d is the production face embedder. It is not a placeholder and not a
staging step toward ArcFace. Anything in this repo describing the choice as
"not settled" is out of date.

The consequence is a *simplification*: `gallery.py` records the model name with
every vector and refuses to compare across models. With SFace fixed, that
guard rail now protects a permanent decision rather than deferring one — and the
"switching the face model invalidates every enrolment" warning in §4.3 becomes a
guard against an accident, not a planned migration.

## 0.3 Models you are supplying

You own the weights. VisionGuard does not source, train or download models.

| Model | Status | Effect on the plan |
|---|---|---|
| **Face (SFace)** | ✅ In repo, final | None — settled, §0.2 |
| **Weapons — trained** | 🔜 You will provide (on another machine) | **Re-scopes Phase 4.** See §3.3 |
| **Re-ID** | 🔜 You will provide (on another machine) | **Blocks the Python decision.** See §1.4 |
| **Fights** | 🚧 You are building it; not ready | Phase 7 unchanged — still the longest lead |

## 0.4 Deliberately not changed

- **Auth stays in Phase 2**, after enrolment in Phase 1. Raised, considered, closed.
- **Phase 7 (fights) stays at 3 weeks.** Your classifier is in progress but not
  ready, so the integration work is still costed as if it lands late.

---

# PART 1 — Fix your workflow first

**Do this before writing any feature code.** It costs one day and saves weeks.

## 1.1 Why you can't kill the server

Three separate causes. You've been hitting all three at once.

### Cause 1 — The camera stream holds the server open (this is the main one)

`engine/vg/api/app.py`, the `/cameras/{id}/stream` endpoint:

```python
async def frames():
    last_sequence = -1
    while True:                                   # ← never ends
        if await request.is_disconnected():
            break
```

That loop only exits when **the browser** disconnects. When you press Ctrl-C, uvicorn starts a *graceful* shutdown, which means: stop accepting new connections, then **wait for open ones to finish**. Your browser tab with the enlarged camera view open is an MJPEG connection that never finishes.

So: server waits for browser, browser waits for server. Forever.

This is why it happens *while you're debugging face detection* — that's exactly when the big camera window is open.

### Cause 2 — The cleanup function does nothing

`serve.py` has `_release_children()` to kill orphans. First line:

```python
try:
    import psutil
except ImportError:
    return          # ← silently does nothing
```

`psutil` is **not in `requirements.txt`**. So on your machine this function returns immediately, every time. The safety net was never installed.

### Cause 3 — Shutdown waits 3 seconds per camera, one at a time

`registry.stop()` loops through cameras calling `worker.stop()`, and each one blocks up to 3s joining a thread that's stuck inside a blocking `cv2` read. Two cameras = 6s. Ten = 30s. It looks frozen; it's just slow and serial.

## 1.2 The fixes

Three small edits. Roughly 25 lines total.

### Fix 1 — Let the stream know the server is stopping

In `engine/vg/api/app.py`:

```python
# near the top, with the other module-level state
import threading
SHUTTING_DOWN = threading.Event()
```

In `lifespan`, make it the **first** thing in the teardown:

```python
    try:
        yield
    finally:
        SHUTTING_DOWN.set()          # ← add this line first
        for worker in (...):
            ...
```

In the `frames()` generator inside `stream()`:

```python
        while not SHUTTING_DOWN.is_set():        # ← was: while True
            if await request.is_disconnected():
                break
```

### Fix 2 — Give uvicorn a hard deadline

In `engine/tools/serve.py`, in the `uvicorn.run(...)` call:

```python
        timeout_graceful_shutdown=5,
```

After 5 seconds it force-closes whatever is left. Belt and braces with Fix 1.

### Fix 3 — Stop all cameras at once, not one by one

In `engine/vg/ingest/registry.py`, split `CameraWorker.stop()` into two steps:

```python
    def request_stop(self) -> None:
        """Signal only. Returns immediately."""
        self._stop.set()
        self.source.stop()

    def join(self, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
```

Then in `CameraRegistry.stop()`:

```python
    def stop(self, timeout: float = 5.0) -> None:
        for worker in self.workers.values():
            worker.request_stop()               # all at once, instant

        deadline = time.monotonic() + timeout   # ONE total budget
        for worker in self.workers.values():
            worker.join(max(0.0, deadline - time.monotonic()))

        self.bus.close()
        self._started = False
```

Shutdown is now 5 seconds total regardless of camera count. Capture threads are `daemon=True`, so any stragglers die with the process — that's already correct and safe.

### Also: add to `engine/requirements.txt`

```
psutil>=6.0          # process cleanup on shutdown
```

**Result:** Ctrl-C stops the server in under 5 seconds, every time, with the browser open. No terminal killing. No PC restarts.

## 1.3 The two habits that change everything

These are already built into the codebase. You may not know they're there.

### Habit 1 — Use mock mode for front-end work

```powershell
$env:VG_MOCK=1 ; python engine\tools\serve.py
```

Starts in **under a second**. Loads no models. No camera. No GPU. Serves the full API with fixtures.

Use it whenever you're working on React, layout, routing, or anything that isn't the vision pipeline. Which is most of the time.

### Habit 2 — Debug against a recorded clip, not the webcam

You already have two labelled recordings:

```
engine/data/footage/walk-through_cam-laptop_20260805-121705.mp4    103s, 1544 frames
engine/data/footage/baseline-empty_cam-laptop_20260805-121451.mp4
```

The `walk-through` clip has a JSON sidecar with **21 hand-marked ground-truth points** (`event` / `negative` with frame numbers). That is a regression test suite you already own.

Point a camera at it in `engine.yaml`:

```yaml
cameras:
  - id: cam-test
    name: Walk-through clip
    source: file:engine/data/footage/walk-through_cam-laptop_20260805-121705.mp4
    kind: File
    fps: 5
    features: [attendance, counting, intrusion]
```

Files loop automatically (`loop_files=True`). Why this is better than the webcam:

| Webcam | Recorded clip |
|---|---|
| Different every run | Identical every run |
| Locks the device — a crashed process keeps it busy | No device to lock |
| You have to stand in front of it | Runs while you read the logs |
| Can't tell a code change from a lighting change | Any change in output = your code |
| No ground truth | 21 labelled marks |

**Use the webcam only for final confirmation.** Everything else on clips.

## 1.4 The virtual environment — ⛔ BLOCKED, do not build yet

VisionGuard gets its own clean venv, built from `engine/requirements.txt`. The
old plan cloned `site-packages` from another project; that is void (§0.1).

**The Python minor version is not decided, and cannot be until you hand over the
re-ID model.** Do not create `.venv` before then. Building it on the wrong
version means rebuilding it — and a PyTorch wheel is ~2.5 GB each time.

### Why it's blocked — and what is now known

**Measured 15 Aug 2026 on the system interpreter, and it is good news:**

```
python        3.14.0
torch         2.11.0+cu128
cuda          True — NVIDIA GeForce RTX 2080 with Max-Q Design
psutil        7.2.1
187 tests     passing
```

So **CUDA on Python 3.14 is confirmed working.** The `cpython-310` bytecode in
`__pycache__` is a leftover, not evidence of a problem. That removes most of the
risk from 3.14 and makes it the strong default.

**One question remains, and it is the whole blocker:** `engine/requirements.txt`
flags **`torchreid` — Known Python 3.14 risk**, and re-ID is the single dependency
likely to refuse the newest interpreter. If your model needs `torchreid`, 3.14 may
be impossible; if it loads with plain `torch`, 3.14 is settled and fast.

Do not spend 2.5 GB finding out by accident.

`models/osnet_x1_0_market1501.pth` is in the repo, but `models/README.md` records
that **`osnet_ain_x1_0` and `osnet_x1_0` are different architectures and are not
interchangeable.** So the file being present does not tell us what your model needs.

### What unblocks it

Hand over the re-ID model plus these three facts:

1. **Architecture** — `osnet_x1_0`, `osnet_ain_x1_0`, or something else
2. **How it loads** — bare `torch.load`, `torchreid`, or a custom runner
3. **The Python version it was built on**

If it loads with plain `torch` and no `torchreid`, 3.14 is safe and fast.
If it needs `torchreid`, we drop to the newest version `torchreid` supports —
likely 3.12 — and pay the reinstall once, deliberately, rather than twice by accident.

### Then build it, once

```powershell
cd E:\VisionGuard
py -3.XX -m venv .venv                      # XX decided above
.\.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r engine\requirements.txt
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Expect `True` on the second value. If it prints `False`, stop — everything after
this runs ~7× slower and nothing on screen will tell you.

### Then pin it, so it never drifts again

```powershell
pip freeze > engine\requirements.lock.txt
```

`requirements.txt` stays human-readable with its comments; the lock file is what
reproduces the machine.

> **Note:** `E:\VisionGuard` is **not a git repository.** Every instruction in this
> document that says "commit" currently has nothing to commit to. Either `git init`
> here or read those as "keep this file, don't regenerate it."

## 1.5 One command to run everything

Create `E:\VisionGuard\dev.ps1`. One entry point, a few sub-commands.

| Command | What it does |
|---|---|
| `.\dev.ps1 up` | Frees ports, starts engine + web together, colour-prefixed logs in one window, Ctrl-C stops both cleanly |
| `.\dev.ps1 up -Mock` | Same, but `VG_MOCK=1` — instant start, no models. For UI work |
| `.\dev.ps1 up -Clip` | Same, but swaps cameras to the recorded clip. For pipeline work |
| `.\dev.ps1 engine` | Engine only |
| `.\dev.ps1 web` | Front end only |
| `.\dev.ps1 down` | Kill anything on 8000 / 5173, release the webcam. **Your panic button** |
| `.\dev.ps1 doctor` | Pre-flight: venv, GPU, model files, DB, ports, tzdata, node, disk |
| `.\dev.ps1 test` | pytest + pyflakes + tsc |

### What `up` must do, in order

1. **Free the ports first** — `Get-NetTCPConnection -LocalPort 8000` → `Stop-Process`. Never start into an occupied port and get `WinError 10013`.
2. **Pick the venv interpreter explicitly** — `.\.venv\Scripts\python.exe`, never bare `python`. This is how you stop accidentally running CPU-only.
3. **Print the GPU line before starting** — `serve.py` already has `warn_if_cpu_only()`.
4. **Start both as jobs**, tag each line `[engine]` / `[web]` in different colours.
5. **Trap Ctrl-C** → stop both jobs → free ports again → exit.

### What `doctor` must check

Each one is a failure you have already hit or will hit:

| Check | Why |
|---|---|
| `.venv` exists and `torch.cuda.is_available()` | CPU-only is 7× slower and invisible |
| Every `models:` weight in `engine.yaml` exists on disk | A missing file degrades silently |
| `visionguard.db` is writable, and how many people are enrolled | Zero enrolled looks exactly like broken recognition |
| Ports 8000 / 5173 are free | The `WinError 10013` you keep hitting |
| `tzdata` importable | Without it every timestamp is 3 hours out for Cairo |
| `hours:` in `engine.yaml` is not `00:00–23:59` | Night-test mode marks a 01:14 sighting as on-time |
| Node + npm present, `web/node_modules` installed | |
| Free disk space | Footage recording will fill a drive |

Make `doctor` the first thing you run each morning.

## 1.6 A note on hot reload

Don't turn on `--reload` for the engine. The comments in `serve.py` are right — the reloader spawns a child process, and on Windows Ctrl-C often misses it, leaving an orphan holding the camera and the port. That is the problem you're trying to escape.

Instead:

- **Front end** — Vite hot-reloads already. Instant.
- **Engine logic** — write a test, run `pytest`. Milliseconds, no server.
- **Engine pipeline** — restart it. With the fixes above that's ~5s down + ~10s up, and in `-Mock` mode it's under a second.

Fast tests beat hot reload. There are already 187 of them passing.

## 1.7 Your daily loop, after this is done

```powershell
.\dev.ps1 doctor          # once, each morning
.\dev.ps1 up -Mock        # UI work — instant
.\dev.ps1 up -Clip        # pipeline work — deterministic
.\dev.ps1 up              # real cameras — final check only
.\dev.ps1 down            # anything weird
```

Never open a second terminal. Never restart the PC.

---

# PART 2 — What the system actually does

Nine features. Here they are in one table, honestly.

| # | Feature | In one sentence | Status today |
|---|---|---|---|
| 1 | **Attendance** | Recognise faces at entrances, build the daily register | ✅ **Real** (fixed today) |
| 2 | **People directory** | Who is enrolled, who has a photo on file | ✅ **Real** (fixed today) |
| 3 | **Live cameras** | Watch any camera, see detection boxes in real time | ✅ **Real** (fixed today) |
| 4 | **Counting** | How many people are in an area right now | 🟡 Per-camera count real; the page is demo |
| 5 | **Intrusion** | Alert when someone enters a restricted zone out of hours | 🔴 Computed every frame, then **thrown away** |
| 6 | **Weapons** | Flag a possible weapon for a human to review | 🔴 Model ready, no worker |
| 7 | **Lost items** | Search recorded footage for "a red backpack" | 🔴 Model ready, **no footage recorded** |
| 8 | **Track a person** | Reconstruct one person's path across cameras | 🔴 Needs re-ID |
| 9 | **Fights** | Detect a physical altercation | 🔴 **No model exists** — longest lead |

Plus the plumbing: users & login (**none — critical**), alerts & notifications (**no delivery mechanism**), audit log (**not written**), system health (✅ real, now honest).

## The shape of it

```
Cameras ──► Capture ──► Frame bus ──┬──► Face recognition ──► Sightings ──► Attendance
                                    ├──► Person detection ──┬─► Counting
                                    │                       ├─► Intrusion ──► Breaches
                                    │                       └─► Tracking ──► Person paths
                                    ├──► Weapon detection ──► Review queue
                                    └──► Pose ──────────────► Fight detection
                                                                    │
                                              All events ───────────┴──► Database ──► API ──► Web + Mobile
```

**Everything left to build is one of two shapes:**

- **A worker** that reads frames and produces events → *intrusion, weapons, fights*
- **A store method** that reads those events back → *the page that shows them*

Nothing needs redesigning. The architecture is sound; this is filling in slots.

---

# PART 3 — Model architecture

This is the part you asked about: which models, and how they layer for speed.

## 3.1 The one rule

> **Decode once. Detect once. Fan out to everything.**

The expensive things are: decoding video, and running a model. Both must happen **once per frame**, with the result shared by every feature that needs it.

The codebase already enforces this. Keep it.

## 3.2 The layers

```
L0  CAPTURE      One thread per camera. Native frame rate. Last-good-frame cache.
                 → Cost: decode. Fix per camera. Reduce with sub-streams.

L1  FRAME BUS    Drop-oldest pub/sub. Slow consumers miss frames; they never block.
                 → Cost: ~zero.

L2  PERSON       ONE YOLOv8s pass. Shared by counting + intrusion + track + fight gating.
                 → Cost: ~23ms GPU. THE BIGGEST SHARED WIN. Never run it twice.

L3  TRACK        ByteTrack over L2 boxes. Gives each person a stable ID across frames.
                 → Cost: ~2ms CPU. Required for dwell time, paths, and fight duration.

L4  SPECIALISTS  Only where needed, only when gated:
                   Face    (YuNet + SFace)   entrance cameras only
                   Weapons (YOLO-World)      on person crops only
                   Pose    (YOLOv8s-pose)    only when 2+ people are close
                   Search  (YOLO-World)      offline over recorded footage
                 → Cost: high. Gating is what makes it affordable.

L5  RULES        Zone geometry, schedules, dwell thresholds, debounce.
                 → Cost: ~zero. Pure Python. Already written and tested.

L6  EVENTS       Write rows + save clips.
                 → Cost: disk.

L7  API / GUI    FastAPI → React (and mobile later).
```

## 3.3 Every model, and where it runs

| Feature | Model | File | Size | Device | Cost/frame | Gate |
|---|---|---|---|---|---|---|
| Face detect | YuNet | `face_detection_yunet_2023mar.onnx` | 228 KB | CPU | ~6 ms | attendance cameras only |
| Face embed | **SFace — settled (§0.2)** | `face_recognition_sface_2021dec.onnx` | 37 MB | CPU | ~38 ms/face | faces ≥80 px, max 8/frame |
| Person | YOLOv8s | `yolov8s.pt` | 22 MB | GPU | ~23 ms | any counting/intrusion/track camera |
| Tracking | ByteTrack | *(in ultralytics)* | — | CPU | ~2 ms | on L2 output |
| Weapons | **trained — you supply** | 🔜 incoming | — | GPU | — | **person crops only** |
| Weapons (interim) | YOLO-World v2 | `yolov8m-worldv2-school.pt` | 344 MB | GPU | ~45 ms @960 | zero-shot, see below |
| Weapons (baseline) | YOLOv8n-OIV7 | `yolov8n-oiv7.pt` | 6.9 MB | GPU | ~8 ms | trained, use as the scoring floor |
| Pose | YOLOv8s-pose | `yolov8s-pose.pt` | 23 MB | GPU | ~28 ms | **only when 2+ people are close** |
| Fight classify | 🚧 you are building it | — | ~2 MB | GPU | ~5 ms | on pose sequences |
| Lost items | YOLO-World v2 | `yolov8m-worldv2-search.pt` | 344 MB | GPU | ~45 ms | offline only, never live |
| Re-ID | **you supply** — architecture TBD | 🔜 incoming | — | GPU | ~6 ms/person | on demand, track searches only |

Timings are order-of-magnitude for a mid-range GPU. **Measure on your hardware** — `tools/measure_latency.py` exists.

### Weapons — a trained model is coming, which changes the risk

The model `engine.yaml` points at today is **prompted, not trained**: 344 MB of CLIP
text encoder plus 18 saved phrases, zero-shot, never having seen a school corridor.
Its prompt list includes **`screwdriver`, `scissors`, `hammer`** — every school has
scissors in every classroom, so expect a very high false-alarm rate on those three
specifically. `models/README.md` documents this properly; read it.

**You are supplying a trained weapons model (§0.3), which retires that problem.**
That re-scopes Phase 4:

- **Prompt trimming drops out of the critical path.** It was a mitigation for a
  model you are replacing. Keep the zero-shot model configured as a *fallback*
  only, and don't spend a day tuning phrases you're about to delete.
- **The eval harness becomes more important, not less.** You now have three
  candidates — your trained model, `yolov8n-oiv7.pt`, and the zero-shot one.
  Score all three against the same golden clips. `yolov8n-oiv7.pt` is the honest
  floor: it is genuinely trained, 50× smaller, and already contains `Handgun`,
  `Rifle`, `Knife`, `Dagger`, `Sword`, `Axe`. If your model can't beat it, that is
  worth knowing before a pilot, not after.
- **The human review gate stays regardless.** No weapons model ships without it.

Until the trained weights land, build the Phase 4 worker against the *interface*,
not the model. Swapping weights must be a config change.

## 3.4 The seven optimisations, in order of payoff

### 1. Share the person detector — already done, don't break it

Counting, intrusion, tracking and fight-gating all consume the same YOLOv8s output. Running it per feature would be 4× the cost for identical results.

`FeatureWorker` exists specifically to enforce that features share *models*, never *workers*.

### 2. Gate the expensive models — the biggest remaining win

Don't run a model on a frame that can't contain what it's looking for.

| Model | Naive | Gated | Saving |
|---|---|---|---|
| **Pose** | every frame | only when 2+ people within ~1.5 body-widths | **~95%** |
| **Weapons** | full frame @960 | crop to person boxes @960 | **~70%**, and *more accurate* — the object is bigger in the crop |
| **Face** | every camera | entrance cameras only, faces ≥80 px | already done |
| **Search** | live | offline over recorded footage | 100% of live cost |

Fights are the clearest case: a corridor is empty or has one person the vast majority of the time. Pose only earns its cost when two people are close together.

### 3. Demand-driven rates — already done

Cameras run at ~2–5 Hz in the background and boost to 12 Hz only while someone is watching. The boost expires by itself, so there's nothing to leak.

At 208 cameras, running everything at full rate doesn't fit on any GPU — and would be spent on views nobody has open.

### 4. Resolution per model, not per system

| Model | Size | Why |
|---|---|---|
| Person | 640 | Bodies are large; 960 adds cost, not recall |
| Weapons | 960 **on a crop** | Small objects need pixels — but only inside the person box |
| Face | native | Recognition needs ≥80 px of face. Never downscale before detection |
| Pose | 640 | Keypoints don't need more |

### 5. Batch across cameras — the 208-camera answer

Ultralytics accepts a list of images in one call. Collect frames from N cameras, run one GPU pass, split the results. GPUs are far more efficient at batch 8 than 8× batch 1.

Not needed yet. Design the worker so it can take a list later.

### 6. Sub-streams — halves decode cost, free

Every IP camera serves a low-res sub-stream alongside the main one.

- **Analytics** → sub-stream (640×480, 5 fps)
- **Recording / display** → main stream

Decoding 4K to detect a person is waste. Configure this per camera when you onboard real hardware.

### 7. TensorRT — last, and only on the deployment machine

You already have `.engine` files. They're 2–3× faster than `.pt`.

**But:** a `.engine` is compiled for one GPU model and one TensorRT version. It is a *build output*, not an artifact. `engine.yaml` correctly points at `.pt` files.

Rule: **ship `.pt`, build `.engine` on the target machine.** Never commit one and expect it to work elsewhere.

## 3.5 Fight detection — you are building the classifier

**Status (§0.3): in progress on your side, not ready.** Phase 7 stays costed at
3 weeks and remains the longest lead item, because integration work planned
against a model that hasn't landed is work planned on a guess.

What VisionGuard must build regardless of when your classifier arrives is
**everything upstream and downstream of it** — the pose gate, the per-track
buffer, the feature extractor, and the incident/review path. Those are defined by
the pipeline, not by the classifier. Build them first and leave the classifier as
a swappable box.

**The one thing I need from you when it's ready:** its input contract. Does it
consume pose keypoint sequences, raw clips, or person crops? That decides whether
the buffer holds 17 keypoints per track or decoded frames — and those are very
different amounts of memory per camera.

The design below is unchanged and is what the surrounding code should assume:

```
L2 person boxes
      │
      ▼  gate: 2+ people within ~1.5 body-widths
YOLOv8s-pose  →  17 keypoints per person
      │
      ▼  buffer 2 seconds per track ID (~10 frames at 5 Hz)
Feature extraction:
      · limb velocity + acceleration
      · inter-person wrist/head distance
      · sudden direction changes
      · torso orientation (facing each other?)
      │
      ▼
Small temporal classifier  (1D-CNN, LSTM, or gradient boosting)
      │
      ▼  confidence + duration + participant count
Fight incident → review queue
```

**If the classifier is still open, prefer gradient boosting on hand-crafted
features.** It trains on a few hundred clips, runs in ~1 ms, and is *explainable* —
which matters enormously when a school asks why a child was flagged. A neural model
that cannot answer that question is a liability in this specific product.

**The bottleneck is data, not code** — which is why this stays a 3-week phase even
though you are already working on the model. `tools/record.py` produces clips with
labelled marks and the `walk-through` sidecar shows the format. That is your
labelling tool and it already exists; use it rather than building another.

## 3.6 Adding any new model — the four-file contract

| Step | File | What you write |
|---|---|---|
| 1 | `vg/infer/<model>.py` | Load weights, return typed detections. Copy `infer/persons.py` |
| 2 | `vg/features/<feature>.py` | Subclass `FeatureWorker[Result]`, implement `analyse(frame)` |
| 3 | `vg/events/<feature>.py` | Persist events. Copy `events/sightings.py` |
| 4 | `vg/api/live.py` | Override the store method that returns fixtures today |

Then: add a `models:` entry and put the feature name in the camera's `features:` list.

**The API contract and the entire front end stay untouched.** That's the payoff of the `Store` seam — `LiveStore` overrides only what's real, everything else keeps serving fixtures, and the UI can't tell.

Threading, rate limiting, on-demand boost and result freshness are all inherited from `FeatureWorker`. **You write no concurrency code.**

### Four rules that must not be broken

1. A feature must never require another feature to be switched on
2. Geometry crosses the API as **fractions of the frame**, never pixels
3. Degradation arrives as **payload, never a 5xx** — health stays 200 even when everything is broken
4. **A subsystem that fails to start must say so in the UI**, not just the log ← *this is the rule the recognition bug broke*

---

# PART 4 — GUI-first

Your requirement: everything insertable and configurable through the browser. Here's what that means concretely.

## 4.1 The rule

> **The database is the source of truth. `engine.yaml` is only the bootstrap default.**

Today, changing a model or a zone means editing YAML and restarting. That's fine for you and impossible for a school IT admin.

`add_camera` already does this correctly — it writes to the DB, **not** back into `engine.yaml`, because "rewriting a config file from a web request destroys its comments and turns a typo into a failed restart." Every other setting should follow that pattern.

## 4.2 The eight GUIs to build

| GUI | Replaces | What it does | Phase |
|---|---|---|---|
| **Model Manager** | `models:` in YAML | Upload weights → benchmark → compare → activate → rollback | 3b |
| **Camera Wizard** | `cameras:` in YAML | Scan → test with live preview → name → tick features → set fps | 1 |
| **Zone Editor** | `zones:` polygons | **Draw the polygon with the mouse** on a live frame + schedule picker | 4 *(table in 2)* |
| **Enrolment Studio** | `tools/enroll.py` | Capture or upload, quality bar per photo, require ≥3 varied | 1 |
| **Threshold Tuner** | `tools/calibrate_faces.py` | Slider + live FAR/FRR curve against a labelled set | 2 |
| **Review Queue** | — | The human gate: clip, confirm/dismiss + reason | 5 |
| **Alert Builder** | `settings/alerts` | *If \<event\> in \<area\> during \<hours\> then notify \<targets\>* | 8 |
| **Diagnostics** | reading log files | Per-camera fps, per-model ms, GPU use, **"DEMO DATA" badges** | 2 |

## 4.3 Model Manager — the one you asked for

This is what "just insert the model" should look like.

```
┌─────────────────────────────────────────────────────────────┐
│  Models                                          [+ Upload] │
├─────────────────────────────────────────────────────────────┤
│  Person detection                                           │
│  ● yolov8s.pt        640px  conf .35   23ms  ACTIVE         │
│  ○ yolo11m.pt        640px  conf .35   41ms  [Benchmark]    │
│                                                             │
│  Weapons                                                    │
│  ● yolov8m-worldv2-school.pt   960px   45ms  ACTIVE         │
│    ⚠ prompted, not trained · 18 prompts   [Edit prompts]    │
│  ○ yolov8n-oiv7.pt             640px    8ms  [Benchmark]    │
│                                                             │
│  Face recognition                                           │
│  ● sface-2021dec     128-d  thr .363   38ms  ACTIVE         │
│    ⚠ switching models requires re-enrolling everyone        │
└─────────────────────────────────────────────────────────────┘
```

**What happens when you click Benchmark:**

1. Runs the model over a stored labelled clip (you already have `walk-through` with 21 marks)
2. Reports ms/frame, peak VRAM, and precision/recall against those marks
3. Shows it **side by side with the currently active model**
4. `[Activate]` marks it active in the DB
5. `[Rollback]` returns to the previous one

**What it needs:** a `model_version` table — `id, feature, filename, imgsz, conf, device, version, active, benchmarked_at, ms_per_frame, precision, recall`.

### v1 does not hot-swap — and that's deliberate

The tempting version of `[Activate]` reloads the weights inside the running worker,
no restart. **`FeatureWorker` cannot do that today**, and adding it means solving
mid-flight weight replacement on a live thread while frames are in the buffer.
That is a new capability, not a slot-fill, and it does not belong in the same
sprint as the first event feature.

**v1:** `[Activate]` writes to the DB and the affected worker restarts. With the
Phase 0 shutdown fixes that is a few seconds, and it is *obviously correct*.
**v2:** true hot-swap, once there's a reason to want it.

This is why Model Manager is now **Phase 3b**, separate from intrusion (Part 5).

**Three guard rails the GUI must enforce:**

- **The face model is settled (§0.2) — SFace, permanently.** The GUI should treat
  changing it as a destructive administrative action, not a normal swap: every
  stored embedding becomes meaningless, because vectors from different face models
  are not comparable and produce plausible-looking nonsense when mixed.
  `gallery.py` already refuses a mismatch. The GUI must warn loudly and offer bulk
  re-enrolment — but the expected answer is *no*.
- Uploading a `.engine` must warn that it only works on the machine that built it.
- A newly uploaded model **cannot be activated before it has been benchmarked.**
  Grey the button out. Activating an unmeasured model is how a silent regression
  reaches a school.

## 4.4 Zone Editor — stop editing coordinates by hand

Today a zone is this, in YAML:

```yaml
rect: [0.10, 0.18, 0.52, 0.62]
```

Nobody can picture that. The GUI:

1. Show a live frame from the camera
2. Click to place polygon points, drag to adjust, double-click to close
3. Schedule picker: `Always` / `Outside these hours` / `During these hours` + day checkboxes
4. Dwell slider — "ignore people who pass through in under **2** seconds"
5. Live preview — the person detector runs and highlights **who is currently inside**

The maths is already written and tested: `point_in_polygon` handles concave shapes, and `Schedule.is_restricted_at()` handles all three modes. The GUI is a thin layer over working code.

Geometry stays **normalised (0–1)** so it survives a camera resolution change.

## 4.5 Enrolment Studio — the Phase 1 blocker

You cannot enrol 400 students from a command line.

```
┌──────────────────────────────────────────────────────────┐
│  Enrol: Ahmed Hassan          Student · Grade 8          │
├──────────────────────────────────────────────────────────┤
│   [live camera preview, face box drawn]                  │
│                              [Capture]  [Upload photos]  │
│                                                          │
│   Photo 1  ████████░░  82%  front, good light      [×]   │
│   Photo 2  ███████░░░  71%  slight left            [×]   │
│   Photo 3  █████░░░░░  54%  ⚠ too small (61px)     [×]   │
│                                                          │
│   ⚠ 2 usable. Need 3+ from different angles.             │
│                                    [Save]  (disabled)    │
└──────────────────────────────────────────────────────────┘
```

**Quality score comes from things the pipeline already measures:** face pixel width (≥80), detector confidence, and — critically — **cosine similarity against the person's other photos.** If a new photo scores 0.95 against an existing one, it adds nothing; you want varied angles, not duplicates.

Plus: bulk import (CSV + photo folder), and enrolment **from the actual entrance camera** at the actual mounting angle — not a laptop webcam.

## 4.6 "DEMO DATA" badges — the durable fix

Every page whose store method still returns fixtures must say so **on screen**:

```
┌────────────────────────────────────────────────────┐
│ ⚠  DEMO DATA — weapon detection is not running.    │
│    This page shows example data.        [Details]  │
└────────────────────────────────────────────────────┘
```

This is the permanent fix for what went wrong: for days the console served invented attendance next to real camera feeds, and nothing on screen distinguished them.

Cheap to build — `/system/health` already knows which subsystems are live. Add a `data_source: "live" | "demo"` field per feature and render the banner from it.

---

# PART 5 — Build order

Eleven weeks to a defensible pilot. Phases 3–8 can run in parallel with two developers.

| Phase | What | Time | Blocks pilot? |
|---|---|---|---|
| **0** | ✅ **DONE 15 Aug** — 3 shutdown fixes, `dev.ps1`, clip camera, British School severed | **1 day** | — |
| **0b** | **Venv + lock file** — ⛔ blocked on the re-ID handover (§1.4) | ½ day | — |
| **1** | **Attendance for real** — ✅ Enrolment Studio · ⬜ Camera Wizard · ⬜ bulk import · ✅ real school hours | 2 wks | — |
| **2** | **Security + data** — login, roles server-side, events DB + migrations, **zones table**, audit, DEMO badges | 2 wks | 🔴 **YES** |
| **3** | **Intrusion** — first event feature; sets the pattern | 1 wk | — |
| **3b** | **Model Manager** — `model_version` table, upload, benchmark, activate-on-restart | 1.5–2 wks | — |
| **4** | **Weapons** — worker, review queue, eval harness across 3 candidates | 1.5 wks | — |
| **5** | **Counting** — time-series table, areas, capacity | 1 wk | — |
| **6** | **Footage + lost items + track** — recording, retention, search index, re-ID | 2 wks | — |
| **7** | **Fights** — ⚠ **start collecting data in week 1** | 3 wks | — |
| **8** | **Notifications** — actual email/SMS/WhatsApp delivery | 1 wk | — |

## Phase 0 — ✅ done 15 Aug 2026

All of it except the venv, which is the only part waiting on you.

**Shipped:** the 3 shutdown fixes (§1.2) · `psutil` + `pyflakes` + `pytest` in
`requirements.txt` · real school hours (**06:30–16:00**, late after 08:00) ·
the `cam-clip` camera · `dev.ps1` with `up`/`down`/`doctor`/`engine`/`web`/`test` ·
all 5 British School references severed (§0.1) · a `face:` section and a
commented `reid:` placeholder in `engine.yaml` · **9 new regression tests** in
`engine/tests/test_shutdown.py`, one per shutdown cause. **196 tests pass.**

`VG_CAMERAS=<ids>` was added to `config.load()` so `-Clip` can switch cameras
without rewriting `engine.yaml` — the file stays the single readable description
of the site, and an unknown id is a hard error rather than a silent zero-camera run.

**Still blocked on the re-ID handover:** building `.venv` · `requirements.lock.txt`.

**One acceptance test is yours to run**, because it needs a real console — no
tool can deliver a genuine Ctrl-C to a Windows process:

```powershell
.\dev.ps1 up -Clip -AllowSystemPython   # open http://localhost:5173, enlarge a camera
# then Ctrl-C. It must stop in under 5 seconds with the tab still open.
```

## The zones table moves to Phase 2

`live.py` already says it outright — `set_zone_enabled` keeps its override
**in memory**, with the comment *"until the events database lands."* Zones live in
`engine.yaml` and nowhere else.

If intrusion (Phase 3) is built against YAML zones and the Zone Editor (Phase 4)
then moves zones into the database, Phase 3 gets rewritten. **Create the `zone`
table in Phase 2**, alongside the events DB and migrations that phase already
brings. Phase 3 then reads zones from the database on its first day, and the Zone
Editor becomes what it should be — a drawing surface over a table that already
exists, with no schema work of its own.

`engine.yaml` keeps its `zones:` block as the **bootstrap seed**, exactly as §4.1
describes for every other setting.

## Do these in Phase 0 or 1, they're one-liners with big consequences

| Fix | Where | Why |
|---|---|---|
| Real school hours | `engine.yaml` `hours:` | Currently `00:00–23:59`. A 01:14 sighting reads as on-time |
| Add `psutil` | `requirements.txt` | Cleanup is a silent no-op without it |
| `pyflakes` in CI | `dev.ps1 test` | Catches the exact bug class that killed recognition, in 1 second |
| `VG_STRICT=1` in CI | env | Refuse to start rather than silently serve fixtures |
| Delete or build dead buttons | "Save clip", "Notify parent", "Restart" | A dead button in a demo is worse than no button |

## Phase 3 comes before 4–8 deliberately

Intrusion is the **smallest possible gap** between "computed" and "recorded" — person detection and zone geometry already run on every frame and the result is discarded. One worker and one table turns it real.

Build it first because it establishes the event pattern that weapons, fights and counting all copy.

---

# PART 6 — Definition of done

Per phase. If you can't demo it, it isn't done.

| Phase | Done when… |
|---|---|
| **0** | Ctrl-C stops the server in <5s with the browser open. `.\dev.ps1 up` starts everything. No file in the repo names `E:\British School` |
| **0b** | `doctor` passes clean, including `torch.cuda.is_available() == True` |
| **1** | You enrol 20 people through the browser, and next morning the register matches reality |
| **2** | An unauthenticated request returns 401. Every demo page is visibly labelled. Zones are read from the DB, not YAML |
| **3** | Walk into a zone during restricted hours → breach + clip in seconds. During permitted hours → nothing |
| **3b** | Upload a model in the browser, benchmark it against `walk-through`, activate it, and see the change take effect |
| **4** | All three weapons candidates scored on the same golden clips, false-alarm rate per camera-hour published, review round-trips |
| **5** | Counting page numbers match a manual count |
| **6** | Search "red backpack" over yesterday's footage returns real hits with timestamps |
| **7** | Staged fight detected; the "not a fight" button actually stores a training label |
| **8** | A real alert arrives on a real phone |

---

# What to do next

**Today — none of this is blocked:**

1. Apply the three shutdown fixes (§1.2) — ~25 lines
2. Set real school hours in `engine.yaml`
3. Add `psutil` to `requirements.txt`
4. Strip the five British School references (§0.1) — `serve.py:44` is the one that matters

**This week:**

5. Write `dev.ps1` — `up`, `down`, `doctor` first; the rest can wait
6. Add the clip camera to `engine.yaml` and stop debugging against the webcam
7. Add inert `face:` and `reid:` sections to `engine.yaml`

**Waiting on you, and holding up Phase 0b:**

8. **The re-ID model** — plus its architecture, how it loads, and the Python version
   it was built on (§1.4). Until this lands, `.venv` does not get built.
9. **The trained weapons model** — needed before Phase 4 can be scored honestly (§3.3)
10. **The fight classifier's input contract** — keypoints, clips, or crops (§3.5)

**Then Phase 1**, and don't start Phase 3 until Attendance is genuinely finished. One feature a school trusts completely is worth more than six that half-work.

---

## Appendix — file map

| Path | What lives there |
|---|---|
| `engine/vg/config.py` | Reads `engine.yaml` + `.env`, validates everything |
| `engine/vg/ingest/` | Camera capture, reconnect, frame bus |
| `engine/vg/infer/` | Model runners — one file per model |
| `engine/vg/features/` | One file per product feature |
| `engine/vg/events/` | Database writes |
| `engine/vg/api/app.py` | Every endpoint |
| `engine/vg/api/store.py` | `MockStore` — the fixtures |
| `engine/vg/api/live.py` | `LiveStore` — **what it doesn't override is your to-do list** |
| `web/src/services/api.ts` | The only place the UI talks to the engine |
| `web/src/pages/` | One file per page |
| `models/README.md` | **What each model actually is.** Read before touching weapons |
| `engine/data/footage/` | Recorded clips + labelled marks — your test fixtures |
