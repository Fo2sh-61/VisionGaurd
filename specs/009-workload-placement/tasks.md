---

description: "Task list for Workload Placement — Remove Unread Processor Work"
---

# Tasks: Workload Placement — Remove Unread Processor Work

**Input**: Design documents from `/specs/009-workload-placement/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [context.md](./context.md)

**Tests**: REQUIRED, not optional. `P8-FR-001` says no detection may change and `P8-FR-002` says a change that cannot demonstrate that is rejected. The constitution requires test-first for business rules, and `AGENTS.md` requires every fix to ship with its regression test in the same commit.

**Organization**: one phase per change. Each is independently shippable, independently reversible, and independently testable — that is `P8-FR-003` and `P8-FR-004`, not a convenience.

**Read [context.md](./context.md) before opening any source file.** It records the anchors, the code to copy, and eleven traps. Trap 1 (crop origin) and trap 2 (do not use `frames()`) are where this feature breaks if it breaks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different files, no dependency on incomplete work
- **[Story]**: US1–US6, mapping to the five changes plus honest health

---

## Phase 1: Setup — establish the truth before touching anything

**Purpose**: nothing in this feature means anything without a before. The ~25 s/s figure comes from a document that is not in the repository (research, "Open"), so it is re-established by measurement rather than quoted.

- [X] T001 Capture the test baseline on a clean tree: `git stash` the uncommitted Arabic-console work, run `python -m pytest engine -q`, record the pass/skip count, and confirm whether `test_api.py::TestWireShape::test_everything_is_camel_case` and `::test_time_is_utc_plus_an_explicit_site_offset` fail on `main` too. Write the answer into `specs/009-workload-placement/context.md` §4
- [X] T002 [P] Record the measurement baseline: `python engine/tools/benchmark.py`, `--model weapons`, `--model bags`. Write the p50/p95/throughput figures into `specs/009-workload-placement/context.md` §4 beside the 22–23 Aug 2026 numbers from `docs/PLAN.md` §7
- [X] T003 [P] Commit `VisionGuard-Deployment-Decision.html` and `VisionGuard-Hardware-Buildlist.html` from the repository root, or fold their figures into `docs/PLAN.md` §7. Untracked evidence cannot be cited

**Checkpoint**: a real before exists, from this machine, and no claim rests on a document nobody can open.

---

## Phase 2: Foundational — the gate every change must pass

**⚠️ CRITICAL**: T004–T006 block every phase below. Nothing that can alter a detection may be written before the thing that proves it did not.

- [X] T004 Write `engine/tools/compare_detections.py` with `--record out.json` and `--diff a.json b.json`. It replays `engine/data/footage/walk-through_*.mp4` and records per frame: person boxes, face boxes with identity and score, and plate reads. **It drives the models directly over clip frames in order — never through the live worker threads**, which rate-limit independently and would report scheduling noise as a regression (research D9)
- [X] T005 Extend `engine/tools/benchmark.py` with `--site N` and a per-feature camera mix, printing site seconds/second, per-camera seconds/second, and cameras-per-machine against the `docs/PLAN.md` §7 budgets. Camera count is an argument, never a constant (P8-FR-026). Print measured timings and projected site arithmetic in **separate blocks** (P8-FR-031)
- [X] T006 [P] Add `face_gate` and `live_capture` to `CameraConfig` and `models.person.batch` in `engine/vg/config.py`, per `contracts/config.md`. Unknown values are a startup error, never a silent fallback. Omitting every key must reproduce today's behaviour
- [X] T007 [P] Record the golden run: `python engine/tools/compare_detections.py --record specs/009-workload-placement/baseline-detections.json`. This file is what every later change is diffed against

**Checkpoint**: `--diff` on two unchanged runs reports `identical`. If it does not, the harness is non-deterministic and must be fixed before anything else — a flaky gate is worse than no gate.

---

## Phase 3: User Story 1 — Patrol face recognition off (Priority: P1) 🎯 MVP

**Goal**: remove the largest single processor line with one config value, and measure what patrol actually cost.

**Independent test**: start with `.\dev.ps1 up -Clip`; the log reads `patrol recognition is switched off (tracking.patrol_hz: 0)`; attendance still names people on `faces: true` cameras; `--site 100` shows the drop.

- [X] T008 [US1] Set `tracking.patrol_hz: 0` in `engine/engine.yaml` and change both code defaults from `0.5` to `0.0` in `engine/vg/config.py` (the dataclass default and the `raw.get("patrol_hz", 0.5)` parse default). **Leave the `0 <= patrol_hz <= 30` validator alone** — it already permits and documents 0
- [X] T009 [US1] Make Track a Person state plainly that names come only from identity-tier cameras when patrol is off (P8-FR-008). Engine sends the state; the sentence is built in `web/src/services/format.ts`, never inline in the page
- [X] T010 [P] [US1] Regression test in `engine/tests/test_workload.py`: `patrol_hz: 0` starts no patrol worker and returns no startup error, and a non-zero value still starts one. Use `live_ish_store`
- [X] T011 [US1] Measure and record: `python engine/tools/benchmark.py --site 100` before and after. This number is what a later decision to re-enable patrol on a gated pipeline gets made on

**Checkpoint**: patrol is off by default, the console says so rather than silently naming fewer people, and its cost is now a recorded number.

---

## Phase 4: User Story 2 — Bag acceleration off (Priority: P1)

**Goal**: a free saving on a model that only runs while somebody is watching. One config line, fully independent of every other change.

**Independent test**: System Health shows the bag model as `PyTorch CUDA` rather than `TensorRT`; `benchmark.py --model bags` moves.

- [ ] T012 [P] [US2] Set `accelerate: false` on the `bags` entry in `engine/engine.yaml`, copying the reasoning comment already on `plates` / `plate_chars`. **Do not delete `models/bagsearch-640.engine`** — a deleted file is not reversible by configuration, which `P8-FR-004` requires (research D5)
- [ ] T013 [P] [US2] Record `python engine/tools/benchmark.py --model bags` before and after
- [ ] T014 [US2] Update the GPU driver on the measurement machine, then re-measure FP16. **Until this is actually run, report it as not measured** — never estimated, never carried over from an older driver (P8-FR-019). No `.engine` may be rebuilt before the driver is current (P8-FR-018)

**Checkpoint**: the bag model runs unaccelerated by config, and any FP16 claim is either measured or explicitly absent.

---

## Phase 5: User Story 3 — Batch the shared person pass (Priority: P2)

**Goal**: pure throughput. By construction no result can change — results return positionally and the cache key is untouched.

**Independent test**: `compare_detections --diff` says `identical`; `--site 100` improves; a single camera is no slower than before.

- [X] T015 [P] [US3] Test first, in `engine/tests/test_workload.py`: a single caller with no other thread waiting runs immediately and waits for nobody (P8-FR-011); several threads blocked together produce one model call; **each frame gets its own boxes back**. Assert on `SharedDetection.passes`, as the existing call-count test does
- [X] T016 [US3] Batch `SharedDetection.raw_boxes` in `engine/vg/infer/shared.py`: collect threads **already blocked** on `_model_lock`, run one `detector.raw_boxes([...])`, fan results back positionally. `self._cache[camera_id] = _Cached(frame.sequence, boxes)` stays exactly as it is (trap 6). No batching window, no timer
- [X] T017 [US3] Gate it behind `models.person.batch` in `engine/engine.yaml` so it reverses by config
- [X] T018 [US3] Prove it: `compare_detections --diff` against `baseline-detections.json`, and person-detect p95 still ≤ 250 ms

**Checkpoint**: batching is on, detections are byte-identical, and one camera alone is not penalised.

---

## Phase 6: User Story 4 — Gate face detection to person crops (Priority: P2) ⚠️ the only change that can alter a result

**Goal**: stop running YuNet on whole frames where the shared person pass already says where the people are.

**Independent test**: `compare_detections --diff` says `identical` on faces **and** on the identities attached to them. Setting `face_gate: frame` restores today's behaviour exactly.

**Read [context.md](./context.md) traps 1, 3, 4 and 5 before writing a line.** This phase is where the feature breaks if it breaks.

- [X] T019 [P] [US4] Test first, in `engine/tests/test_workload.py`: a face detected inside a person crop reports **full-frame** fractions identical to the ungated path. This is trap 1 — YuNet returns crop-relative coordinates and `DetectedFace.to_fractions(frame_w, frame_h)` assumes full-frame pixels. Getting this half-right identifies the wrong person
- [X] T020 [P] [US4] Isolation test in `engine/tests/test_workload.py`: with `counting`, `intrusion` and `track` all switched off, a `face_gate: person` camera still recognises faces. `RecognitionWorker` must hold `SharedDetection` — a model wrapper with its own lock and cache — never `PeopleWorker` (trap 5, and the whole reason `features/base.py` exists)
- [X] T021 [US4] Let `FaceDetector.detect` in `engine/vg/infer/faces.py` run on a crop and return coordinates the caller can offset. `DetectedFace.raw` must stay valid for `SFaceEmbedder.embed`, which calls `alignCrop` against the image the face was found in — pass the crop consistently to both, or translate `raw` too
- [X] T022 [US4] Gate `RecognitionWorker.analyse` in `engine/vg/features/recognition.py` to person boxes from `SharedDetection`, adding the crop origin back **before** `to_fractions`. **Never resize a crop** — `tracking.identity.face_px: 80` is a measured pixel floor (trap 3). Copy the gating pattern from `features/weapons.py` and `infer/plates.py`
- [X] T023 [US4] Pass `SharedDetection` and the per-camera `face_gate` map into `RecognitionWorker` from `_start_recognition` in `engine/vg/api/app.py`. Default `face_gate: person` **only** where the camera's `features:` already include `counting`, `intrusion` or `track`; `frame` otherwise — on an attendance-only camera gating adds the person model and a GPU dependency and costs time (trap 4)
- [X] T024 [US4] **The gate.** `python engine/tools/compare_detections.py --diff baseline-detections.json after-gating.json` must say `identical`. If it does not, `P8-FR-002` says reject the change — do not ship it behind a flag and do not adjust a threshold to make the diff pass
- [ ] T025 [US4] Confirm by eye on the clip that face boxes land on faces: `.\dev.ps1 up -Clip`. A crop-offset bug draws boxes in plausible-looking wrong places that a diff on counts alone would miss

**Checkpoint**: faces are found only inside people, every box and identity is unchanged, and attendance survives counting being switched off.

---

## Phase 7: User Story 5 — Capture unwatched cameras at the analytics rate (Priority: P3)

**Goal**: stop decoding five frames in six that nothing reads. **Last, as the spec instructs** — it touches the live-view latency trade the capture loop was built around.

**Independent test**: open a camera nobody has been watching; it is current and smooth within 1 second. Leave it; it drops back within seconds. Analysis continues unchanged while nobody looks.

- [X] T026 [P] [US5] Test first, in `engine/tests/test_workload.py`: with no watcher, frames are still **grabbed** at the device rate and the sequence still advances, but decode happens at `fps`; with a watcher, every frame decodes. A stale frame is still published and flagged exactly as today (P8-FR-016)
- [X] T027 [US5] Split grab from decode in `CameraSource.read` in `engine/vg/ingest/source.py`: `grab()` always, `retrieve()` when the frame is wanted. **Do not switch `CameraWorker._run` to `source.frames()`** — that is trap 2, the documented latency bug, and `frames()`'s own docstring explains why
- [X] T028 [US5] Add a per-camera watcher count in `engine/vg/ingest/source.py` around `wait_for_frame`, and mark the camera watched for the life of the MJPEG response in `stream` in `engine/vg/api/app.py`, releasing in `finally`. **Do not overload `note_interest`** — a knife overlay poll on a grid tile is not somebody watching the video (trap 10)
- [X] T029 [US5] Drive the split from `CameraWorker._run` in `engine/vg/ingest/registry.py`, gated by `live_capture` so it reverses by config
- [X] T030 [US5] Verify `cv2.VideoCapture.grab()` behaves on the webcam backend on this machine as it does on file and RTSP — MSMF and DSHOW have differed here historically (context §5)
- [ ] T031 [US5] **Ask Mohamed for the manual check**: camera opens current within 1 second, drops back within seconds of leaving, reopens with no accumulated lag, NO SIGNAL still appears within its budget, and nothing stale is ever labelled LIVE. This can only be confirmed by eye

**Checkpoint**: unwatched cameras cost a fifth of what they did, and a watched one is no slower to open than before.

---

## Phase 8: User Story 6 — Honest load on System Health (Priority: P1 — the reliability requirement)

**Goal**: saturation is visible, never silent. **Fully independent of the five changes** — it shares no file with them except `live.py` and `schemas.py`, so it can be worked in parallel from the end of Phase 2. Land it before the site is asked to trust any of the numbers above.

**Independent test**: with the engine under load, each running worker shows frames processed, inference ms, queue depth and dropped frames, and any worker that is behind is named.

- [X] T032 [P] [US6] Test first, in `engine/tests/test_health_load.py`: `bare_live_store` returns the workers stage with nothing running and **200**, not a 5xx (P8-FR-025); a stopped worker is **absent from the list**, not present with zeros; `behind` is omitted rather than assumed false when a counter is unreadable
- [X] T033 [US6] Add `WorkerLoad` to `engine/vg/api/schemas.py` and `workers: list[WorkerLoad]` to `PipelineStage`, per `contracts/system-health.md`. `api/schemas.py` is **CRLF** — read and write bytes or check first (trap 9)
- [X] T034 [US6] Add `_workers_stage()` to `LiveStore.health` in `engine/vg/api/live.py`, built from counters that already increment: `FeatureWorker.stats`, `Subscription.dropped` (`framebus.py:48`), `len(Subscription._frames)` against `maxsize`, `SharedDetection.passes`. Copy the honest-degradation shape of `_lost_stage` / `_recognition_stage`. `api/live.py` is CRLF
- [X] T035 [US6] Fill `SystemHealth.cpu_percent` and `gpu_percent` — declared today and never set. **No per-worker CPU field**: workers are threads in one process and a per-thread share would be invented (trap 8). When a reading is unavailable it stays `null` and renders with a reason, never `0`
- [X] T036 [US6] Raise stage severity to `warn` when any worker is behind, and name it in `detail`. A healthy summary over a saturated machine is exactly what `P8-FR-021` forbids
- [X] T037 [US6] Render the workers stage in `web/src/pages/SystemHealth.tsx`. Every rendered string is built in `web/src/services/format.ts` — the engine sends numbers and enums

**Checkpoint**: an operator can see which worker is behind, and an unavailable reading says so instead of reading as zero.

---

## Phase 9: Polish & cross-cutting

- [X] T038 Run the whole of [quickstart.md](./quickstart.md) end to end, including §6 — reverse each of the five keys one at a time and confirm the other four are unaffected (`P8-FR-003`, `SC-004`)
- [ ] T039 [P] Update `STATUS.md` and `docs/PLAN.md` §7 from evidence: the new §7 measured rows, the new `--site` figures, and P1-04 (latency / queue / drop metrics on System Health) now done
- [X] T040 [P] Record the final before/after in `specs/009-workload-placement/` — site s/s, per-camera s/s and cameras-per-machine, with measured and projected clearly separated
- [ ] T041 Run the four gates: `python -m pytest engine` (count must not drop from T001), `cd web; npx tsc -b --force`, `python -m pyflakes engine/vg engine/tools engine/tests`, and `.\dev.ps1 up -Clip`

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)** — no dependencies. Start here.
- **Phase 2 (Foundational)** — depends on Phase 1. **Blocks US1–US5.** T004 and T007 in particular: no change that can alter a detection may be written before the harness that proves it did not.
- **US1, US2** — config only, no code. Either can ship the day Phase 2 lands.
- **US3** — depends on T006 (the `batch` key).
- **US4** — depends on T004/T007 (the gate) and T006 (`face_gate`). Ships after US1, which reduces what it has to be correct about: patrol cameras stop running faces at all.
- **US5** — depends on T006 (`live_capture`). **Do this last**, per the spec.
- **US6** — depends only on Phase 2. **Parallel with everything.**
- **Phase 9** — depends on whichever stories shipped.

### Within each story

Test → implementation → config gate → measure → prove. The tests in T015, T019, T020, T026 and T032 are written **first and must fail**.

### Parallel opportunities

- T002, T003 together in Phase 1
- T006, T007 together once T004 exists
- **US6 (T032–T037) runs alongside US1–US5 throughout** — different files
- US1 and US2 are both single config lines and are independent of each other
- Within US4: T019 and T020 are different tests and parallel
- T039 and T040 in Phase 9

---

## Parallel example: after Phase 2

```bash
# Independent tracks, different files:
Task: "T008 [US1] patrol_hz 0 in engine.yaml + config.py"
Task: "T012 [US2] accelerate: false on bags in engine.yaml"
Task: "T032 [US6] honest-health tests in engine/tests/test_health_load.py"
```

---

## Implementation Strategy

### MVP (US1 only)

1. Phase 1 — baseline
2. Phase 2 — the harness and the site measurement
3. Phase 3 — patrol off
4. **Stop and validate**: `--site 100` shows the drop, `compare_detections --diff` says identical, Track a Person says plainly where names now come from
5. Ship. One config line, the largest single saving, fully reversible

### Incremental delivery

Each phase ships and reverses on its own — that is `P8-FR-003` and `P8-FR-004`, not a nicety. Order: US1 → US2 → US3 → US4 → US5, cheapest and safest first, with US6 landing alongside so that by the time anyone is asked to believe the numbers, the page can show whether the machine is keeping up.

### Two rules that override convenience

1. **If `compare_detections --diff` is not `identical`, the change is rejected** (`P8-FR-002`). Not shipped behind a flag, not fixed by moving a threshold.
2. **Nothing is reported that was not measured.** FP16 after a driver update that has not happened reads as *not measured*. A per-worker CPU share that cannot exist reads as *unavailable, with a reason*. Never as zero.

---

## Notes

- 41 tasks. Few, each small — the spec asked for that explicitly.
- Two new files only: `engine/tools/compare_detections.py` and the two test files. Everything else edits an existing seam.
- Four of the five changes are configuration. Only US4 and US5 are code.
- `api/schemas.py`, `api/live.py` and `api/app.py` are **CRLF**; most other files are LF, and there is no `.gitattributes`. `git diff --stat` catches a whole-file rewrite.
- The `AGENTS.md` four-file feature pattern does **not** apply: this feature adds no model, no feature worker and no event writer.

---

## What actually happened — 30 Aug 2026

Recorded here because three tasks did not end the way the plan assumed, and the
reasons are worth more than the ticks.

**T012/T013 — change 5 REVERTED.** The spec claimed deleting the bag TensorRT
engine was "a free ~31%". Measured back to back on the same 40 clip frames:

| | p50 | p95 | throughput |
|---|---|---|---|
| TensorRT `bagsearch-640.engine` | 22.3 ms | **23.3 ms** | 44.8 fps |
| PyTorch CUDA `bagsearch.pt` | 21.5 ms | **29.0 ms** | 44.2 fps |

There is no 31% saving. They are within noise on the median and TensorRT is
clearly better on p95, which is the figure a latency budget is set from.
`test_platetext.py` already encoded the opposite intent — "an opt-out for two
models, not a retreat from TensorRT" — and it was right. Reverted under
P8-FR-002: a change that cannot demonstrate its claim is rejected.

Found on the way: **`accelerate` never reaches the bag or person detector.**
`BagDetector` and `PersonDetector` both call `load_model(weights, imgsz)`
without passing it, so `accelerate: false` on those models in `engine.yaml` is
silently ignored. It works for plates because `infer/plates.py` passes it. A
config key nothing reads is a setting somebody believes they changed. Not
fixed here — it is a latent bug of its own, and fixing it would change how the
person model loads, which is not this feature's business.

**T024 — change 2 is SHIPPED BUT OFF BY DEFAULT.** `--gate-check` runs both
paths over the labelled clip. Gating finds **every** face the whole-frame pass
finds, 60 of 60, so the crop padding and the offset arithmetic are correct.
But the boxes land up to **11 pixels** away, 5 on average.

That is inherent, not a bug: YuNet is told its input size, so a 160x240 crop is
a different computation from a 640x480 frame. The shift moves the five
landmarks, `alignCrop` then warps a slightly different patch, and the embedding
that decides WHO a face is changes with it. Nobody has shown that never flips an
identity. P8-FR-002 says unproven means off, so `face_gate` defaults to `frame`
and the machinery waits for a measurement against a real enrolled roll.

**T001 — the baseline could not be taken on a clean tree.** The working tree
carries ~50 files of uncommitted Arabic-console work and stashing it was not a
risk worth taking uninvited. Two failures predate this feature —
`test_everything_is_camel_case` and `test_time_is_utc_plus_an_explicit_site_offset`,
both `IndexError` because `/breaches?window=last30` returns an empty list. Same
root cause, nothing to do with camelCase or timezones, and not caused by this
work.

**The before number, measured.** `benchmark.py --site 100` gives **21.09 s/s**,
close to the spec's ~25 and the first independent corroboration of a figure
whose source document is not in the repository. The breakdown is the finding:

| | s/s | share |
|---|---|---|
| decode | 15.00 | **71%** |
| faces | 3.30 | 16% |
| person | 2.49 | 12% |
| plates | 0.30 | 1% |

Decode is nearly three quarters of the bill, which makes change 4 the one that
matters and change 2 — now off — worth much less than its risk.

### Closed after the first report

- **T009 done.** Track a Person now says when only the entrance cameras were
  looking for faces. Two things worth recording about how: the console has not
  called `/track` since the anchor-table rewrite, so putting the fact there
  alone would have been a field nothing renders — it went on `PathSkeleton`,
  the endpoint actually used. And it travels as an **enum**, not a sentence:
  `notes.py` says on its face that nothing carries `Note` on the wire yet and
  that converting is "deliberately not half-done", so shipping a 66th English
  sentence would have been building the debt `008` exists to pay off.
- **T002/T011/T040 done** — `measurements.md`, with before and after.
- **T039 done** — `STATUS.md` and `docs/PLAN.md` §7, from evidence.
- **T005 extended** — `--decode-hz`, so the tool can express the after as well
  as the before, and unknown feature names in `--mix` are now **refused** rather
  than silently costed at zero. A typo used to produce a confident total that
  was quietly too low, which is how a site ends up one box short.

### Still not done, and why

| | Why |
|---|---|
| ~~T001~~ | **done** without stashing — a throwaway `git worktree` at HEAD proved all three failures predate this branch |
| T003 | figures folded into `docs/PLAN.md` §7 so they are citable; the two files are still untracked and want committing or deleting |
| T014 GPU driver + FP16 | machine admin, and reported as *not measured* until run |
| T018 batching equality | **done** — `--batch-check` says identical, and caught two real bugs of mine plus a TensorRT limit that makes the saving zero for now |
| T024 gating equality | done as far as it can be — the remaining question is identity stability against a real enrolled roll |
| T038 reversal | config half **done** as tests; the by-eye half needs Mohamed |
| T030 | **done** — grab/retrieve verified on both file and webcam backends, and it caught a spin that would have burned a core per camera |
| T025/T031 by-eye checks | Mohamed is testing manually |
| T038 full reversal walk | needs the by-eye half above |
