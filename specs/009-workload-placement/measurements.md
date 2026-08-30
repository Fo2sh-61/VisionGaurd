# Measurements — Workload Placement

**Taken 30 Aug 2026** on the development laptop (RTX 2080 Max-Q, 8 GB), against
the labelled walk-through clip. Every figure here came from a command in this
repository, and the command is written beside it.

> Re-run all of this on the deployment machine. This one is a power-limited
> laptop GPU; it is the floor, not the ceiling.

---

## 1. Site demand — the headline (SC-001)

```
python engine/tools/benchmark.py --site 100 --mix "person=1.0@2,faces=0.15@5,patrol=0.85@0.5,plates=0.05@5"
python engine/tools/benchmark.py --site 100 --mix "person=1.0@2,faces=0.15@5,plates=0.05@5" --decode-hz 5
```

| | site s/s | per camera | cameras per 8-core box | boxes for 100 |
|---|---|---|---|---|
| **Before** — patrol on, decode at the camera's 25 Hz | **23.03** | 0.230 | 34 | 3 |
| **After** — patrol off, decode at the 5 Hz analytics rate | **9.17** | 0.092 | 87 | 2 |

**23.03 s/s is the first independent corroboration of the Workload Plan's
~25 s/s**, which matters because that document is not in this repository and
nothing else in the tree could confirm it.

### Where the before actually goes

| | s/s | share |
|---|---|---|
| **decode** | **15.00** | **65%** |
| faces (identity tier, 15% of cameras @ 5 Hz) | 3.30 | 14% |
| person | 2.49 | 11% |
| patrol (85% of cameras @ 0.5 Hz) | 1.87 | 8% |
| plates | 0.30 | 1% |

Decode is two thirds of the bill. That reorders the whole feature: **change 4
is the one that matters**, and change 2 — the only risky one — was worth 14%
at most.

### SC-001 is NOT met

The target was ≤ ~5 s/s. The measured after is **9.17**. The gap is face
detection, and closing it needs change 2, which is switched off because it
cannot demonstrate that identities are unchanged (§3). That is the spec's own
rule working as intended: SC-001 is a target, P8-FR-001 is a constraint, and
where they conflict the constraint wins.

Stated plainly rather than reported as a pass: **60% of the waste is gone, not
80%.** One 8-core box now carries 87 cameras of this mix instead of 34.

## 2. Bag model — change 5, REJECTED

Both paths, back to back, same 40 clip frames:

| | p50 | p95 | throughput |
|---|---|---|---|
| TensorRT `bagsearch-640.engine` | 22.3 ms | **23.3 ms** | 44.8 fps |
| PyTorch CUDA `bagsearch.pt` | 21.5 ms | **29.0 ms** | 44.2 fps |

The spec claimed deleting the engine was "a free ~31%". There is no saving.
The medians are within noise and TensorRT is clearly better on p95, which is
the figure a latency budget is set from. `test_platetext.py` already recorded
the intent — "an opt-out for two models, not a retreat from TensorRT" — and it
was right. Reverted under P8-FR-002.

**Also found, not fixed:** `accelerate` never reaches the bag or person
detector. Both call `load_model(weights, imgsz)` without passing it, so
`accelerate: false` on those models in `engine.yaml` is silently ignored. It
works for plates only because `infer/plates.py` passes it through. A config
key nothing reads is a setting somebody believes they changed. Left alone
here: fixing it changes how the person model loads, which is not this
feature's business.

## 3. Face gating — change 2, BUILT AND OFF

```
python engine/tools/compare_detections.py --gate-check --frames 60
```

| | |
|---|---|
| Faces found, whole frame | 60 |
| Faces found, gated to person crops | **60** |
| Frames where the count differs | **0** |
| Box drift | mean 2.1 px in x, 5.5 px in y; **max 11 px** |

**No face is lost.** The crop padding clears the head and the offset
arithmetic puts every box back in frame coordinates correctly — if either were
wrong this would show as missing faces or wild displacement, and it shows
neither.

**But the boxes are not identical**, and that is inherent rather than a bug:
YuNet is told its input size, so a 160×240 crop is a different computation
from a 640×480 frame. The shift moves the five landmarks; `alignCrop` then
warps a slightly different patch; and that patch is what the embedding — the
thing that decides *who* a face is — is computed from.

Nobody has shown a 5-pixel shift never flips an identity. Until somebody
measures that against a real enrolled roll, P8-FR-002 applies: unproven means
off, not on-by-default. `face_gate` therefore defaults to `frame`, and the
machinery, its tests and its check are all in place for the day that
measurement exists.

## 3b. Batching — change 3, SHIPPED, OFF, AND BUYS NOTHING TODAY

```
python engine/tools/compare_detections.py --batch-check --frames 40
```

| | |
|---|---|
| Boxes changed | **none** — identical |
| Model calls, unbatched | 40 |
| Model calls, batched | **40** |

**The TensorRT engine is compiled with a fixed batch size of 1.** Handed three
images it raises `input size torch.Size([3, 3, 640, 640]) not equal to max
model size (1, 3, 640, 640)`. Batching only works on the `.pt`, and the person
model loads the engine — so on this machine the saving is zero.

**This check caught a hazard, not just a limitation.** That exception is raised
inside the shared detection path, where `FeatureWorker._run` catches per-frame
exceptions and logs them. Switching batching on with TensorRT loaded would have
made detection **quietly stop** on affected frames — a caught exception, a log
line nobody reads, and boxes silently missing. It is now detected once, warned
about in plain words, and permanently falls back to one frame at a time.

Two smaller corrections came out of the same run:

- **`passes` counts real model calls**, not trips through the lock. It reaches
  System Health, and a fallback that ran three images singly must not report
  itself as one pass — that would show a halved workload on a machine where
  the model ran just as often.
- The first implementation keyed pending answers **by camera**, so two frames
  from one camera collided: the second thread popped the first one's answer,
  discarded it, and the first woke to find nothing. Frames came back empty —
  and an empty answer means "nobody in this picture", which is a wrong
  detection, not a slow one. Now keyed by frame.

To make batching worth anything, the engines need rebuilding with a dynamic
batch. P8-FR-018 says not before the GPU driver is current, so that waits.

## 3c. The capture loop nearly cost more than it saved

```
python engine/tools/compare_detections.py   # not this - measured by hand, see below
```

Grabbing a frame without decoding it is only cheap if `grab()` *waits* for a
frame. Measured on both backends, unwatched, over 2 seconds:

| | decoded | grabs | verdict |
|---|---|---|---|
| webcam, before the fix | 10 (5.0 Hz ✔) | **1,316,628** | spinning a full core |
| webcam, after | 10 (5.0 Hz ✔) | **653** | correct |
| file, before | 11 | 13,606 | spinning |
| file, after | 11 | 821 | correct |

**658,000 grabs a second.** On an RTSP stream `grab()` blocks for a frame
interval, so the loop paces itself and the buffer is genuinely drained — which
is the entire reason for grabbing rather than sleeping. On a webcam it returns
instantly, and the loop burned a whole core doing nothing.

A hundred cameras each spinning a core is **worse than the waste this feature
exists to remove**, and it would not have looked like a bug — just a busy
machine. The loop now sleeps 2 ms after any grab that returned in under 4 ms;
a backend that genuinely blocks never reaches that line.

Decode rates are unchanged and correct either way: 5 Hz unwatched (the
analytics rate), 30 Hz watched (the camera's own rate).

## 4. Latency budgets (SC-006)

`docs/PLAN.md` §7, re-checked:

| Path | Budget | Measured |
|---|---|---|
| Camera → detection ready (person) | ≤ 250 ms p95 | **16.6 ms p95** (12.2 p50, 81.8 fps) — passes |
| Bag model | not budgeted | 23.3 ms p95 |

`docs/PLAN.md` §7 records 22.3 ms p95 and 54.5 fps for the person model on
22–23 Aug. It now reads 16.6 ms and 81.8 fps on the same clip and the same
machine.

**This feature did not make that faster and no such claim is made here.**
Nothing in it touches the person model's settings. The likely cause is a
TensorRT engine for `yolov8s` being present now and not then. The honest
reading is that §7's row was measured in a different state of the machine, not
that a 33% improvement was earned — which is exactly why the sizing output
separates what it measured from what it assumed.

## 5. Test suite

| | |
|---|---|
| Collected | **1371** |
| Added by this feature | **51** |
| Clean `HEAD` baseline | 1307 |
| Failing | 3, all proven pre-existing — see below |

The count went **up**, which is the `AGENTS.md` bar.

**The three failures were not caused by this work, and this is now proven.**
A throwaway `git worktree` at `HEAD` (988a140) — a clean checkout carrying
neither this feature nor the uncommitted Arabic work — fails the same three.
They predate both. No stash was needed and nothing in the working tree was
touched.

The arithmetic closes exactly:

| | tests |
|---|---|
| Clean `HEAD` | 1307 |
| plus uncommitted Arabic work (`test_language`, `test_notes`) | 13 |
| plus this feature (`test_workload`, `test_health_load`) | **51** |
| **Total now** | **1371** |

- `test_everything_is_camel_case` and `test_time_is_utc_plus_an_explicit_site_offset`
  — one shared cause: `/breaches?window=last30` returns an empty list and both
  index `[0]`. Nothing to do with camelCase or timezones.
- `test_weapons_live.py::test_today_is_right_on_the_day_the_clocks_change` —
  fails in isolation too; a DST test in a file that already had uncommitted
  changes before this feature started.

## 6. What has not been measured

- **After-figures on the deployment machine.** Everything here is the laptop.
- **FP16 after a GPU driver update.** The driver has not been updated, so this
  reads as *not measured* rather than estimated (P8-FR-019).
- **Identity stability under face gating.** The one measurement that would let
  change 2 ship. Needs a real enrolled roll, not the clip.
- **The by-eye checks**: camera catch-up within 1 second, overlay positions,
  NO SIGNAL timing. These need a person watching a screen.
