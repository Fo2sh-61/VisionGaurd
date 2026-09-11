# Measurements — Workload Placement

**Taken 30 Aug 2026** on the development laptop (RTX 2080 Max-Q, 8 GB), against
the labelled walk-through clip. Every figure here came from a command in this
repository, and the command is written beside it.

> Re-run all of this on the deployment machine. This one is a power-limited
> laptop GPU; it is the floor, not the ceiling.

---

## 1. Site demand — the headline (SC-001)

> **Corrected 12 Sep 2026.** The after figure first published here, 9.17, was
> wrong, and so was everything built on it: 87 cameras a box, "60% of the waste
> is gone", "change 4 is the one that matters", "the gap is face gating". It
> assumed an unwatched camera skips the decode on four frames in five. It does
> not — see §1b. Figures are now in **cores**: how many processor cores the work
> keeps busy flat out. It is the same number that was called "seconds of
> processor time per second" (s/s) on 30 Aug, said plainly.

```
python engine/tools/benchmark.py --site 100 --mix "person=1.0@2,faces=0.15@5,patrol=0.85@0.5,plates=0.05@5"
python engine/tools/benchmark.py --site 100 --mix "person=1.0@2,faces=0.15@5,plates=0.05@5" --decode-hz 5
```

| | cores needed | per camera | cameras per 8-core box | boxes for 100 |
|---|---|---|---|---|
| **Before** — patrol on, every frame converted to pixels | **23.03** | 0.230 | 34 | 3 |
| **After** — patrol off, unwatched frames converted at 5 Hz | **about 14–20** | 0.14–0.20 | 40–57 | 2–3 |
| ~~After, as first published~~ | ~~9.17~~ | ~~0.092~~ | ~~87~~ | ~~2~~ |

**23.03 is the first independent corroboration of the Workload Plan's ~25**,
which matters because that document is not in this repository and nothing else
in the tree could confirm it. Both rest on the same assumption, though: that
capturing a frame costs 6 ms. Nothing in the repository records where that
figure came from, and `benchmark.py` still labels it assumed.

### Where the before actually goes

| | cores | share |
|---|---|---|
| **capture** — decode, then conversion to pixels; 6 ms a frame, assumed | **15.00** | **65%** |
| faces (identity tier, 15% of cameras @ 5 Hz) | 3.30 | 14% |
| person | 2.49 | 11% |
| patrol (85% of cameras @ 0.5 Hz) | 1.87 | 8% |
| plates | 0.30 | 1% |

(The rows sum to 22.96, not 23.03: the person row came from a different run
than the total. 0.07 cores; it changes nothing below.)

Capture is two thirds of the bill — but change 4 could only ever remove the
conversion part of it. The decode stays, on every frame of every camera.

### SC-001 is NOT met, by a long way

The target was ≤ ~5 cores. The after is **about 14–20**. The gap is no longer
face detection: even if change 2 removed the whole faces row, that is 3.30
cores. **The gap is decoding** — 6 to 13.5 cores of the after, which nothing
in this feature can touch (§1b says what could).

Change 2 stays off for the reason in §3: SC-001 is a target, P8-FR-001 is a
constraint, and where they conflict the constraint wins.

Stated plainly rather than reported as a pass: **13% to 39% of the before is
gone, not 60%.** One 8-core box now carries about 40–57 cameras of this mix,
up from 34 — not 87.

## 1b. What `live_capture: watched` really saves (12 Sep 2026)

```
python engine/tools/benchmark.py --decode
```

Research D1 said `grab()` is "demux the next frame, no decode" and `retrieve()`
is "decode the grabbed frame". For OpenCV's FFmpeg backend — the one every RTSP
camera uses — that is wrong. `CvCapture_FFMPEG::grabFrame()` reads the packet
**and decodes it** (`avcodec_send_packet` / `avcodec_receive_frame`).
`retrieve()` only converts the decoded frame from YUV to BGR (`sws_scale`) and
copies it out. DirectShow webcams are alike in principle: the capture graph
converts every frame, and `retrieve()` copies it. So an unwatched camera still
decodes every frame. **What it skips is the conversion.**

The 30 Aug arithmetic charged the whole 6 ms to a converted frame and nothing to
a grabbed one — it assumed the conversion *was* the decode. Measured instead,
on the labelled clip (640×480, 15 fps, 1,544 frames): processor time per frame,
every thread in the process, four runs of the command above, 11–12 Sep:

| decoder threads | `grab()` | `grab()` + `retrieve()` | `retrieve()` share, per run |
|---|---|---|---|
| 12 — FFmpeg's default, how the engine opens a camera | 1.19–1.47 ms | 1.38–2.06 ms | **24%, 25%, 10%, 29%** |
| 1 — the work alone | 0.44–0.57 ms | 0.79–1.37 ms | **50%, 44%, 52%, 58%** |

**The conversion is somewhere between about 10% and 60% of a frame's capture
cost** — not all of it. With twelve threads the decoder spends much of its time
sharing the work out; that lands on `grab()`, shrinks the conversion's share,
and makes it noisy — single passes ranged from nothing to 41%. One thread
measures just the work. The fourth run was slower across the board — the same
laptop, busier. None of them is how a real camera arrives, one frame every
40 ms, which is why the answer is a range and not a number.

**Not claimed: paced runs.** Pacing the loop at the clip's own 15 fps was tried
by hand. Windows charges processor time, at each clock tick, to whichever
thread happens to be running, so a loop that sleeps between frames is
mis-counted. Read both ways, the same paced runs disagreed about the
conversion's share by 14 to 22 points — 79% against the processor's own cycle
counter's 65%, and 57% against 35% — where unpaced single-thread runs agreed to
within 0.2. Even with exact cycle counts, paced runs put the conversion
anywhere from 35% to 68%: too wide to use, and no command here reproduces it.
Recorded so nobody repeats the experiment expecting a clean answer.

**Also by hand, 11 Sep:** a 1080p25 H.264 copy of the clip, written through
`cv2.VideoWriter(CAP_MSMF, 'avc1')`, gave `grab()` 21.35 ms and `grab()` +
`retrieve()` 23.37 ms — a 9% share. That writer produces about 50 Mbit/s, far
above a real camera's 2–8, and decoding cost rises with bitrate while
conversion cost does not, so this understates the share a real camera would
show.

### The site, re-derived

The 30 Aug rows, with the capture split measured instead of assumed. `--site`
now does this itself: capture is two rows — `grab` on every frame, `retrieve`
only on frames something reads — and it prints the cautious end of the range as
the headline, with the other end beside it.

| 100 cameras, after | conversion = 10% | conversion = 60% | as first published (100%) |
|---|---|---|---|
| person, faces, plates | 6.17 | 6.17 | 6.17 |
| `grab` — the decode, all 25 frames a second | 13.50 | 6.00 | 0 |
| `retrieve` — conversion, 5 frames a second | 0.30 | 1.80 | 3.00 |
| **cores needed** | **19.97** | **13.97** | 9.17 |
| cameras per 8-core box | 40 | 57 | 87 |
| boxes for 100 | 3 | 2 | 2 |

What the feature really saved, of the before's 23.03: patrol off, 1.87 cores;
converting unwatched frames at 5 Hz instead of 25, 1.2 to 7.2 cores. **About 3
to 9 cores in all, not the 13.86 first published.**

### What is left, and what would remove it — follow-on, not built

**Decoding is the biggest cost left**, and `watched` cannot touch it. Two ways
would:

- **Hardware decode.** This OpenCV build (4.14.0 pip wheel) decodes on the GPU
  when asked: `cv2.VideoCapture(path, cv2.CAP_FFMPEG,
  [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY])` opened D3D11VA
  (`CAP_PROP_HW_ACCELERATION` read back 2). On the 1080p file above, `grab()`
  fell from 21.35 ms of processor time a frame to **0.39 ms**, at about 1,000
  frames a second. `retrieve()` then costs about 11 ms — copying the frame back
  from the GPU and converting NV12 to BGR — which is exactly the part `watched`
  skips. **With hardware decode, `watched` finally saves what it was meant to.**
  On this Optimus laptop it picked device 0, the Intel UHD 630; the NVIDIA
  decoder stayed at 0%. `CAP_PROP_HW_DEVICE` chooses the adapter. Measured by
  hand on 11 Sep; no command here reproduces it yet. Building it means a
  `CameraSource.open()` change and a fallback when no hardware decoder exists,
  and it must be re-measured on the deployment box.
- **Camera sub-streams**, already named in research D1: fewer pixels and frames
  to decode at the source.

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

Grabbing a frame without converting it is only cheap if `grab()` *waits* for a
frame. (This section said "decoding" on 30 Aug; `grab()` is the decode — §1b.)
Measured on both backends, unwatched, over 2 seconds:

| | converted | grabs | verdict |
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

Conversion rates are unchanged and correct either way: 5 Hz unwatched (the
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
