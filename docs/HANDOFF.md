# Handoff — 20 Aug 2026

Where the project stands and what to do next. Read `AGENTS.md` first, then
this, then `docs/PLAN.md`.

**Commit:** `7e8b732` · **Tests:** 490 passed, 6 skipped · all four gates green
**Repo:** https://github.com/Fo2sh-61/VisionGaurd (private) · branches `main`
and `plan/final-production-roadmap`, both at the same commit.

---

## Done this cycle

**P0 — stop showing anything untrue. Complete, all ten tasks.**

The last two were P0-08 and P0-10. P0-08 found more than missing empty states:

- Weapons showed a green tick reading *"No knife detected on campus · last
  check 2 seconds ago"* from a `useState('clear')` nothing ever changed, while
  no weapons worker existed — directly under the banner saying the feature was
  unavailable.
- System Health rendered `lead="Loading…"` forever on a failed request, and
  drew every pipeline row green so "Needs attention" appeared in a healthy
  badge.
- People printed a hard-coded `'2,118 people'` regardless of what the engine
  returned.
- Lost Items sat on "Searching…" permanently if the search threw.

**P1 — detect once, and measure. Three of six.**

- **P1-01** the person detector ran twice per frame on cameras with both
  counting and track, from two threads against one model. Now one shared pass.
  Verified on the clip: 15 frames → 15 passes, not 30.
- **P1-03** removed a `getattr(store, "_tracked_boxes")` reach-in.
- **P1-06** measured: **p95 18 ms** against a 250 ms budget, 57.5 frames/sec
  on the RTX 2080 Max-Q. `python engine/tools/benchmark.py`.

**P2 — security. Complete.**

Was: `localStorage.setItem('vg.role','admin')` and nothing else. argon2
accounts, opaque revocable sessions, deny-by-default middleware over every
route, admin-only by path. First account: `python engine/tools/create_user.py`.

---

## Not done, and worth knowing

**P1-02, P1-04, P1-05** — overlay freshness, latency/drop metrics on System
Health, and the feature-isolation test.

**The CI workflow has never been observed running.** `.github/workflows/ci.yml`
is committed and the remote now exists, so it should fire on push, but nobody
has looked at the Actions tab.

**Knife detection is built but switched off.** `engine/vg/infer/weapons.py`
decodes `knife-finetuned-v3.onnx` correctly and is tested, but nothing imports
it and `capabilities()` still reports weapons unavailable. It is **CPU-only**:
onnxruntime needs its own CUDA runtime, this machine has no CUDA toolkit (only
the copy PyTorch carries), and the GPU build wants CUDA 13 against a driver
capped at 12.7. **The fix is the `.pt` file** the model was exported from —
it would load through PyTorch like every other model. It is on the owner's
Google Drive at `knife_training_v2/train/weights/best.pt`.

> **Do not load this ONNX through ultralytics.** It was exported with 8.4.118;
> the pinned runtime is 8.4.7 and misreads the output, returning four
> detections on every frame — including an empty room — with "confidences" of
> 90 and 100. That is why the decode is written out by hand.

**re-ID is confirmed but not wired.** `models/osnet_x1_0_market1501.pth` is
plain `osnet_x1_0` (no instance-norm keys), Market-1501, 512-d. The ambiguity
the plan worried about is resolved. `engine.yaml` still has it commented out.

**One knife model class only.** `knife-finetuned-v3.onnx` detects `knife` and
nothing else. The currently configured zero-shot model also claims handguns and
rifles. Switching loses gun detection — an owner decision, not taken yet.

---

## Owner decisions, answered 20 Aug 2026

| | |
|---|---|
| **Consent for biometrics of minors** | **Granted.** No longer gates deployment |
| **Retention** | **3 days.** ~3.5 TB not ~35 TB — two drives, not an array |
| **Sub-streams** | **Yes** on site cameras (not the dev laptop webcam) |
| **Hardware** | Still open. §7 of the plan has the arithmetic |

The 3-day retention has an operational edge the Lost Items page must state
plainly when P7 builds it: a bag reported missing on Monday cannot be searched
for on Thursday.

---

## Traps this cycle set, so nobody re-treads them

**The console and the engine must be one origin.** A live view is
`<img src=".../stream">`, an image tag cannot send an Authorization header, and
the session cookie is `SameSite=Strict`. Point `VITE_API_BASE` at the engine
directly and JSON keeps working while every camera goes black — the most
confusing possible half-failure. The dev server proxies the engine for this
reason; production must serve both from one origin.

**`new URL(relative)` throws.** With a same-origin base, `BASE + path` is
relative and `new URL()` needs a second argument. Without it every request died
before a socket opened, and the error handler confidently reported *"Cannot
reach the engine. Is it running?"* about an engine that was running and
answering. An error message that names a probable cause is worse than a vague
one once that cause stops being the real one.

**The repo has mixed line endings** — `core.autocrlf=false`, no
`.gitattributes`, some files CRLF and some LF. Editing with a tool that
normalises turns a 30-line change into a 900-line diff. A `.gitattributes`
would end this.

**`loiterwatch` is a live dependency, not leftover.** `vendor/loiterwatch/`
is pip-installed editable and imported by the appearance matcher. `docs/PLAN.md`
§8 still says the British School project is "severed, nothing from it is used" —
that line is wrong and should be fixed.

---

## What to do next

Suggested order:

1. **Finish P1** — P1-02, P1-04, P1-05. Small, and P1-04 has most of its
   measurement already in `engine/tools/benchmark.py`.
2. **P3 — durable events.** The last foundation. Alerts, audit and searches
   still live in RAM and vanish on restart. The constitution requires the audit
   row to be committed *before* a track search returns its result.
3. Then feature work: P4 zones, P5 counting, P6 weapons, P7 footage.

**Cleanup the owner asked for and then paused:** `models/` mixes weights,
third-party source (`loiterwatch`) and old training experiments. ~57 MB is
verified unreferenced and safe to delete. Nothing has been moved.

---

## Running it

```powershell
python engine/tools/create_user.py   # once, or nobody can sign in
.\dev.ps1 up -Clip                   # engine + console, on the labelled clip
.\dev.ps1 test                       # the four gates
.\dev.ps1 down                       # frees 8000 / 5173
```

Manual walkthrough: `docs/MANUAL-TEST.md`.
