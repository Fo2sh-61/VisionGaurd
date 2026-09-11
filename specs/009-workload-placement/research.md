# Phase 0 research: Workload Placement

**Written 29 Aug 2026 against commit `988a140`.** Everything below was read in the
code, not assumed. Where the spec and the code disagree, the code is recorded and
the spec's wording is corrected in the plan.

---

## D1 — Where the wasted decode actually is

**Finding:** `CameraWorker._run` (`engine/vg/ingest/registry.py:66`) consumes
`self.source.all_frames()` — the **unthrottled** path. `CameraSource.frames()`, which
throttles to `target_fps`, exists but is used only by `engine/tools/*` and
`engine/tests/test_source.py`. **Nothing in production ever throttles capture.**

So every camera decodes every frame the device produces (~25–30/s), publishes it to
the bus, and each `FeatureWorker` samples it down to ~5 Hz. Roughly five in six decoded
frames are discarded unread. That is the second half of the 25 s/s.

**The trap the code already names.** `CameraSource.frames()`'s docstring is explicit:
`cap.read()` returns the *next* buffered frame, not the newest, so sleeping between
reads makes the stream fall progressively behind. You must pull frames off the device.
It concludes: *"at 208 cameras the answer is sub-streams and a lower device rate, not
re-introducing the lag."*

**Decision: split grab from decode.** OpenCV's `VideoCapture` already separates
`grab()` ~~(demux the next frame, no decode)~~ from `retrieve()` ~~(decode the grabbed
frame)~~. Grab every frame — the buffer stays drained and the latency trap is avoided —
and `retrieve()` only when a frame is actually wanted. This gets the saving *without*
the trade the docstring warns about.

> **Corrected 12 Sep 2026 — the split struck through above is wrong for the backend
> that matters.** On OpenCV's FFmpeg backend, which every RTSP camera uses, `grab()`
> reads the packet **and decodes it**; `retrieve()` only converts the decoded frame
> to BGR and copies it out. The decision still stands — it avoids the lag trap and
> `live_capture: watched` is unchanged — but what it saves is the conversion, not the
> decode: somewhere between about 10% and 60% of a frame's capture cost on the
> labelled clip, not five frames in six (`benchmark.py --decode`; `measurements.md` §1b). The
> decoded-and-discarded frames in the Finding above are still decoded. Removing that
> cost needs hardware decode or camera sub-streams — a follow-on, recorded in §1b.

**Alternatives rejected:**
- *Lower `target_fps` and use `frames()`* — re-introduces exactly the lag the docstring
  documents. Rejected on the code's own evidence.
- *Camera sub-streams* — the right long-term answer (`docs/PLAN.md` §7.1 confirms the
  site cameras have ~512 kbps sub-streams) but it needs per-camera URLs the owner has
  not supplied, and it is not reversible by configuration alone on a camera whose
  sub-stream URL is unknown. Keep as a follow-on, not this feature.

## D2 — What "watched" means, in code that already exists

**Finding:** two independent signals are already in the tree.

1. `FeatureWorker.note_interest(camera_id)` + `BOOST_TTL_SECONDS = 2.0`
   (`features/base.py:157`). Called from the overlay-poll endpoint
   (`api/app.py:1909–1928`) and the lost-bag watch (`api/live.py:861`). This is
   *per worker*, not per camera.
2. The MJPEG endpoint `stream()` (`api/app.py:1795`) blocks on
   `worker.source.wait_for_frame(last_sequence, 2.0)`. **An open MJPEG response is
   literally an operator looking at that camera's video.**

**Decision:** capture rate keys off (2) — a per-camera count of open MJPEG streams,
plus the snapshot endpoint. Signal (1) stays exactly as it is and is not touched.

**Rationale:** the live view is the only consumer that needs every decoded frame.
Analytics never did. Counting open streams answers "is anybody looking at *this
camera's picture*" precisely, whereas `note_interest` answers "does some feature want
to run faster", which is a different question and is already correctly wired.

**The 1-second budget (P8-FR-014) falls out for free:** the first `retrieve()` after a
stream opens returns the frame grabbed microseconds ago. There is no catch-up queue to
drain, because grabbing never stopped.

## D3 — Face gating, and the one rule it could break

**Finding:** `RecognitionWorker.analyse` (`features/recognition.py:118`) calls
`self.pipeline.observe(frame.image)` — the whole frame, every time.

**`features/base.py`'s module docstring exists to forbid what this change looks like:**
*"the first version of this system ran person detection inside the recognition worker,
so a camera configured for counting alone was processed by nothing at all... Features
share **models**, never **workers**."*

**Decision:** `RecognitionWorker` takes the `SharedDetection` object, never
`PeopleWorker`. `SharedDetection` (`infer/shared.py:167`) is a model wrapper with its
own lock and cache; it runs the model itself and needs no feature to be enabled. This
is the reuse Constitution Principle II explicitly permits ("MAY share immutable model
instances... Feature workers and business decisions MUST NOT be shared").

**The trap that would have made this a loss.** `engine/engine.yaml` documents that a
camera with `features: [attendance]` alone "runs 2 models and no GPU at all". Gating
faces behind person detection would **add** the person model — and a GPU dependency —
to exactly those cameras. On an attendance-only camera the change costs time rather
than saving it.

→ Gating is therefore **per-camera and opt-in** (`face_gate: person`), defaulting on
only where the camera's feature list already runs person detection
(`counting`/`intrusion`/`track`). An attendance-only camera keeps whole-frame
detection. This also satisfies P8-FR-004: one config key, reversible.

**The correctness risk, named precisely.** `DetectedFace.to_fractions(frame_w,
frame_h)` converts detector pixels to frame fractions. Run YuNet on a crop and it
returns coordinates **relative to the crop**. Converting those against the full frame's
width and height puts every face box in the wrong place — the single most likely way
this change breaks P8-FR-001. The crop origin must be added back before conversion.

Two more, both smaller:
- `FaceDetector.detect` calls `self._detector.setInputSize(self._size)` only when the
  size changed (`infer/faces.py:130`). Person crops vary in size every frame, so this
  now fires on nearly every call. Correct, but no longer free.
- `tracking.identity.face_px: 80` is a **pixel** floor and the config comment records
  it as measured, not chosen ("at 40px the same person scores 0.23–0.48 against
  themselves"). The crop must be passed at native resolution — **never resized** — or
  the floor silently changes meaning and identities change with it.

## D4 — Batching the shared pass

**Finding:** `SharedDetection` (`infer/shared.py:167`) holds a global `_model_lock`
around `self.detector.raw_boxes(frame.image)`, plus a per-camera `_compute_lock` and a
`_cache` keyed by `camera_id` holding one `_Cached(sequence, boxes)`.

**Decision:** collect the frames already blocked on `_model_lock` and run them as one
`raw_boxes([...])` call, then fan the results back to their waiters. `_cache` keying is
untouched: each waiter still writes `_cache[camera_id] = _Cached(frame.sequence,
boxes_for_that_frame)`.

**Rationale:** batching is the one change that is pure throughput. The frame-to-boxes
correspondence is preserved by construction because results come back positionally.

**P8-FR-011 (no waiting for company) is satisfied by design, not by a timer:** only
threads *already blocked* are collected. A lone caller finds an empty waiter set and
runs immediately. There is no batching window to tune and no added latency.

**Alternative rejected:** a time-windowed batcher (wait up to N ms for more frames).
It buys larger batches at the cost of latency on every call, and it would need a tuning
knob that Principle I would then have to police.

## D5 — The bag acceleration artefact

**Finding:** the spec says "delete the bag TensorRT engine". `models/bagsearch-640.engine`
exists and `infer/shared.py::weights_to_load(..., accelerate=True)` prefers it.

**But deleting a file is not reversible by configuration alone**, which P8-FR-004
requires. And the mechanism already exists: `config.py:426` defines `accelerate: bool =
True` per model, `config.py:452` reads it, and `engine.yaml` already uses
`accelerate: false` on both plate models for exactly this reason.

**Decision: set `accelerate: false` on the `bags` model in `engine.yaml`.** One line,
reversible, and it produces the identical runtime effect. Deleting the `.engine` file
is optional housekeeping afterwards, not the mechanism.

This is a correction to the spec's wording, recorded here rather than silently applied.

## D6 — What System Health can already see

**Finding:** the counters the spec asks for mostly exist and are simply never surfaced.

| Asked for | Where it already is |
|---|---|
| Dropped frames | `Subscription.dropped` (`ingest/framebus.py:37`), incremented on every overflow at `:48` |
| Queue depth | `len(Subscription._frames)` against `Subscription.maxsize` |
| Per-worker work | `FeatureWorker.stats` — `frames_processed`, `last_inference_ms` |
| Camera-level drops | `SourceHealth.frames_dropped` (`ingest/source.py:89`), already on the wire as `framesDropped` |
| Model passes | `SharedDetection.passes` (`infer/shared.py:190`) — its docstring already says "System Health can report it later" |

**Decision:** add a `workers` pipeline stage built from these existing counters. No new
measurement machinery. Per-*process* CPU and GPU is the only genuinely new reading, and
`SystemHealth` already carries `cpu_percent` / `gpu_percent` fields
(`api/schemas.py:715`) that are currently unset.

**Per-worker CPU share is not obtainable in this architecture and must not be faked.**
Workers are threads in one process; the OS attributes CPU to the process, not the
thread. The honest reading is process-level CPU/GPU plus per-worker *inference
milliseconds and frame counts*, which is what actually identifies the expensive worker.
P8-FR-022 governs the difference: what cannot be measured reads as unavailable with a
reason. This is a deliberate, stated narrowing of P8-FR-020 and is carried into the
plan's Complexity Tracking table.

## D7 — Patrol off

**Finding:** `config.py:699` `patrol_hz: float = 0.5` (the default) and `:714`
`float(raw.get("patrol_hz", 0.5))` (the parse default), plus `engine.yaml`
`tracking.patrol_hz: 0.5`. `app.py::_start_patrol:885` already handles `rate <= 0`
cleanly — logs "patrol recognition is switched off" and returns `None, None`.

**Decision:** change all three to `0`. No code path needs writing; the off case is
already implemented and already logged.

**The visible consequence (P8-FR-008):** with patrol off, only `faces: true` /
`attendance` cameras attach names. `docs/PLAN.md` §5 P7 and `STATUS.md` both describe
Track a Person naming stops from patrol anchors. That page must say plainly that names
come only from identity-tier cameras — otherwise it silently returns fewer named stops,
which Principle III forbids.

## D8 — Measuring it

**Finding:** `engine/tools/benchmark.py` times one model over 60 clip frames and prints
`cameras × hz ÷ throughput` for a uniform mix (`RATES = (1, 2, 5)`, `TARGET_CAMERAS =
208`). It cannot express a mixed site, and it reports multiples of "this machine"
rather than seconds of processor time.

**Decision:** add a `--site` mode taking a camera count and a per-feature mix, printing
site seconds/second, per-camera seconds/second, and cameras-per-machine. It reuses the
measured per-model throughput it already computes; only the arithmetic is new.

Per P8-FR-031 the output must separate **measured** (per-model timings on this machine)
from **projected** (the site arithmetic). The existing tool already models this honesty
— "Upper bound: assumes every camera runs person detection at that rate."

## D9 — Proving detections did not change

**Finding:** no before/after comparison harness exists. `engine/data/footage/` holds
`walk-through_*.mp4` with a `.json` sidecar of 21 `event`/`negative` marks by frame
number. `engine/tools/smoke.py` and `eval_plates.py` are the nearest existing shapes.

**Decision:** a `engine/tools/compare_detections.py` that replays the clip and writes a
deterministic per-frame record (person boxes, face boxes + identities, plate reads),
then diffs two such records. Ship it **before** change 2 — it is the gate change 2 has
to pass, and P8-FR-002 says a change that cannot demonstrate equality is rejected.

**Determinism caveat:** the shared detection cache is keyed on `(camera_id, sequence)`
and worker threads rate-limit independently, so a *live* run does not sample identical
frames twice. The comparison must therefore drive the models directly over the clip
frames in order, not through the live worker threads. Otherwise the harness reports
differences that are scheduling noise, and P8-FR-001 becomes unprovable.

## Open, carried into the plan

- **The VisionGuard Workload Plan, 29 Aug 2026 is not in the repository.** The ~25 s/s
  and ~31% figures cannot be traced. `VisionGuard-Deployment-Decision.html` (untracked,
  repo root) argues the same case in different units — 442 inferences/sec at a
  realistic mix, 2 vs 9 GPUs depending on software. T001 re-establishes the baseline by
  measurement so nothing rests on an absent document.
- **`python -m pytest engine` currently has 2 pre-existing failures** on this branch:
  `test_api.py::TestWireShape::test_everything_is_camel_case` and
  `::test_time_is_utc_plus_an_explicit_site_offset`. The working tree carries
  uncommitted Arabic-console work touching `api/schemas.py` and `api/app.py`. **Not
  caused by this feature**; the full pass count was not captured (the run was
  interrupted). T000 captures it on a clean tree before anything else starts.
