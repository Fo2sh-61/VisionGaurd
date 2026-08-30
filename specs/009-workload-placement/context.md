# Implementation context: Workload Placement — Remove Unread Processor Work

**Written by `/speckit-plan` on 29 Aug 2026, against commit `988a140`.**

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. Anchors drift — search for the symbol, never the line number.
> If this disagrees with the code, the code wins and this file is wrong.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/engine.yaml` | `tracking:` | `patrol_hz: 0.5` under a long comment block explaining the two tiers | → `0`. Update the comment: it already says "0 switches the patrol tier off entirely" |
| `engine/vg/config.py` | `patrol_hz` (2 sites) | `patrol_hz: float = 0.5` (dataclass default) and `float(raw.get("patrol_hz", 0.5))` (parse default). Validator: `if not 0 <= patrol_hz <= 30` | both `0.5` → `0.0`. **Leave the validator alone** — it already permits and documents 0 |
| `engine/vg/config.py` | `accelerate: bool = True` | already exists on the model config; read at `accelerate=bool(raw.get("accelerate", True))`; honoured in `shared.py::weights_to_load` at `if not accelerate:` | **nothing to write.** Change 5 is `engine.yaml` only |
| `engine/vg/config.py` | `CameraConfig` | has `id, name, source, kind, area, fps, enabled, features, rotate, gate, direction, faces, neighbours`. `fps` is the **analytics** rate and the file says so | add `face_gate: str = ""` and `live_capture: str = "watched"`; reject unknown values at parse, do not silently fall back |
| `engine/vg/api/app.py` | `_start_patrol` | `rate = cfg.tracking.patrol_hz`; `if rate <= 0:` logs `patrol recognition is switched off (tracking.patrol_hz: 0)` and returns `None, None`. Already correct | **no edit.** The off path exists and is already logged |
| `engine/vg/api/app.py` | `_start_recognition` | builds `RecognitionWorker(registry.bus, gallery, sightings, pipeline=…, cameras=…, rate_hz=background, boost_hz=12.0, tracking=tracking, gates=cfg.tracking.identity, anchors=anchors)`. `cameras` = `c.enabled and (c.faces or "attendance" in c.features)` | pass `shared=<SharedDetection>` and the per-camera `face_gate` map |
| `engine/vg/features/recognition.py` | `RecognitionWorker.analyse` | `for observation in self.pipeline.observe(frame.image):` then `observation.face.to_fractions(frame.width, frame.height)`, then `self._record(...)` and `self._weigh(...)` | when gated: get person boxes from `SharedDetection`, run `observe` per crop, **add the crop origin back before `to_fractions`** |
| `engine/vg/infer/faces.py` | `FaceDetector.detect` | stateful — `self._detector.setInputSize(self._size)` only when the size changed. Returns `DetectedFace` with `raw` (the detector row, needed by `alignCrop`) | accept a crop; return coordinates the caller can offset. `raw` must stay valid for `SFaceEmbedder.embed`, which calls `alignCrop` against **the image it was detected in** |
| `engine/vg/infer/shared.py` | `SharedDetection.raw_boxes` | double-checked cache under `_compute_lock(camera_id)`, then `with self._model_lock: boxes = self.detector.raw_boxes(frame.image); self.passes += 1`, then `self._cache[camera_id] = _Cached(frame.sequence, boxes)` | collect threads already blocked on `_model_lock`, run one `raw_boxes([...])`, fan results back positionally. **Cache write is unchanged** |
| `engine/vg/ingest/source.py` | `CameraSource.read` | `ok, image = self._cap.read()`; on success `self._sequence += 1`, builds `Frame`, sets `self._last_good` under `self._frame_ready` and `notify_all()` | split into `grab()` always + `retrieve()` when wanted. Sequence still advances on every grab |
| `engine/vg/ingest/source.py` | `CameraSource.wait_for_frame` | the MJPEG endpoint blocks here on `(last_sequence, 2.0)` | add a watcher count incremented around this wait — this **is** the "somebody is looking" signal |
| `engine/vg/ingest/registry.py` | `CameraWorker._run` | `for frame in self.source.all_frames():` — **unthrottled**, and `if not frame.is_stale: self.bus.publish(frame)` | drive the grab/retrieve split. Do **not** switch to `source.frames()` — see trap 2 |
| `engine/vg/api/app.py` | `stream` | `StreamingResponse`, loops on `worker.source.wait_for_frame(last_sequence, 2.0)`, `multipart/x-mixed-replace` | mark the camera watched for the life of the response; release in `finally` |
| `engine/vg/api/schemas.py` | `class SystemHealth(Wire)` | `cameras_online, cameras_total, recorders_online, recorders_total, severity, gpu_percent, cpu_percent, storage_percent, uptime_seconds, metrics, recorders, pipeline, cameras`. **`cpu_percent` and `gpu_percent` are declared and never set** | add `class WorkerLoad(Wire)`; add `workers: list[WorkerLoad] = []` to `PipelineStage` |
| `engine/vg/api/live.py` | `LiveStore.health` | builds `pipeline = [ingest, _recognition_stage(), _people_stage(), _clock_stage(), _weapons_stage(), _vehicles_stage(), _lost_stage()]` and three metrics | append `_workers_stage()`; add the dropped/passes/cpu metrics; set `cpu_percent`/`gpu_percent` |
| `engine/tools/benchmark.py` | `main` | `--frames`, `--cameras`, `--model`; ends with `for hz in RATES: need = args.cameras * hz` printing `x this machine` | add `--site N` printing site s/s, per-camera s/s, cameras-per-machine, with measured and projected in **separate blocks** |
| `engine/tools/compare_detections.py` | — | does not exist | new. `--record out.json`, `--diff a.json b.json` |
| `web/src/pages/SystemHealth.tsx` | the pipeline render | stages render from `PipelineStage` | render `workers`. Strings belong in `services/format.ts`, never inline |

## 2. Things to copy, not invent

- **A per-model config flag that turns acceleration off** → copy the `plates` /
  `plate_chars` entries in `engine/engine.yaml`. They already use `accelerate: false`
  with the reasoning written out. Change 5 is the same line on `bags`.
- **The off-by-config path with an honest log line** → copy
  `app.py::_start_patrol`'s `if rate <= 0:` block. It is the model for every "switched
  off is not broken" state.
- **Gating an expensive model behind person detection** → copy
  `features/weapons.py` (knives run only on person-present frames) and
  `infer/plates.py` (characters run only on detector crops). Change 2 is the third
  instance of a pattern that already exists twice.
- **Demand-gating on somebody watching** → copy `features/lostbag.py`; its docstring
  already explains the idea and points at `recogniser.note_interest()`.
- **A pipeline stage that degrades honestly** → copy `live.py::_lost_stage` /
  `_recognition_stage`. They already distinguish "off", "broken" and "running".
- **A test store with real data** → copy the `store` fixture in `test_groups.py`
  (throwaway `FaceGallery` + `SightingStore` in a `TemporaryDirectory`). **Close the
  gallery before the tempdir** or Windows fails the teardown.

## 3. Traps

1. **The crop-origin bug is the whole risk of change 2.** YuNet on a crop returns
   coordinates relative to **the crop**. `DetectedFace.to_fractions(frame_w, frame_h)`
   assumes full-frame pixels. Add the crop origin back *before* converting, or every
   face box lands in the wrong place and P8-FR-001 fails. `SFaceEmbedder.embed` calls
   `alignCrop` using `DetectedFace.raw` against **the image the face was found in** —
   so either pass the crop consistently to both, or translate `raw` too. Getting this
   half-right identifies the wrong person, which is worse than failing outright.

2. **Do not switch `CameraWorker._run` to `source.frames()`.** It looks like the fix and
   is the documented bug. `CameraSource.frames()`'s own docstring explains that
   `cap.read()` returns the *next buffered* frame, not the newest, so throttling reads
   makes the stream fall further behind every second. Grab every frame; decode
   selectively. `frames()` is used only by `engine/tools/*` and `test_source.py`.

3. **Never resize a person crop before face detection.** `tracking.identity.face_px: 80`
   is a pixel floor and `engine.yaml` records it as measured — "at 40px the same person
   scores 0.23–0.48 against themselves". Resizing silently changes what that floor means
   and moves identities.

4. **Gating an attendance-only camera costs time, not saves it.** `engine.yaml` states
   `[attendance]` alone "runs 2 models and no GPU at all". `face_gate: person` there
   *adds* the person model and a GPU dependency. Default it on only where `features:`
   already include `counting` / `intrusion` / `track`.

5. **`features/base.py` exists to forbid what change 2 resembles.** Its docstring: the
   first version ran person detection inside the recognition worker, so a
   counting-only camera was processed by nothing. Pass `SharedDetection` (a **model**
   wrapper with its own lock and cache) — never `PeopleWorker`. Write the isolation test.

6. **`_cache` in `SharedDetection` is keyed by `camera_id` and holds one sequence.** It
   is not a multi-frame cache. Batching must still write one `_Cached(sequence, boxes)`
   per camera, with each frame's own boxes. Results come back positionally — do not
   reorder them.

7. **`FeatureWorker` subscribes with `maxsize=1`** (`base.py::_run`), while
   `FrameBus.subscribe` defaults to `maxsize=2`. Queue depth is per subscription, not
   global. `Subscription.dropped` already increments at `framebus.py:48`.

8. **Per-worker CPU cannot be measured.** Workers are threads in one process. Report
   process CPU/GPU plus per-worker inference ms and frame counts. A per-thread CPU share
   would be invented, and Principle III forbids it.

9. **Mixed line endings, no `.gitattributes`.** `api/*.py`, `services/*.ts`, `types.ts`
   and `STATUS.md` are **CRLF**; most other files are LF. A script that reads and writes
   text rewrites every ending and turns a six-line change into a whole-file diff. Read
   and write bytes, or check `b"\r\n" in path.read_bytes()` first. `git diff --stat`
   catches it. **`api/schemas.py`, `api/live.py` and `api/app.py` are all in the CRLF
   set** and this feature edits all three.

10. **Boost and watching are two different questions.** `note_interest` / `BOOST_TTL_SECONDS`
    asks "should this *worker* run faster". Change 4 asks "is anybody looking at this
    *camera's picture*". Do not overload `note_interest` for capture — an overlay poll
    for knives on a grid tile is not somebody watching the video, and conflating them
    re-creates the bug `app.py`'s `FACE_OVERLAYS` comment describes.

11. **A `.engine` is a build output, not an artifact** (`engine.yaml`, `models/README.md`).
    Ship `.pt`; build `.engine` on the target machine. This is why change 5 is
    `accelerate: false` rather than `rm`.

## 4. Baseline

- `python -m pytest engine` at commit `988a140`: **count not captured** — the run was
  interrupted. **T000 captures it on a clean tree before any edit.**
- **Two pre-existing failures**, not caused by this feature:
  `test_api.py::TestWireShape::test_everything_is_camel_case` and
  `::test_time_is_utc_plus_an_explicit_site_offset`. The working tree carries
  uncommitted Arabic-console work touching `api/schemas.py` and `api/app.py`, which is
  the likely cause. **Confirm this on a clean checkout before starting** — if they fail
  on `main` too, they are somebody else's bug; if they pass on `main`, the Arabic work
  broke them and this feature must not be blamed for it.
- New test files: `engine/tests/test_workload.py`, `engine/tests/test_health_load.py`.
- Measurement baseline to record before the first change:
  `python engine/tools/benchmark.py` and `--model bags`. Last recorded in
  `docs/PLAN.md` §7 (22–23 Aug 2026, RTX 2080 Max-Q): person 17.7/22.3 ms, 54.5 fps;
  knife 15.8/17.4 ms, 61.4 fps; bags 27.9/30.9 ms, 35.3 fps.

## 5. Still unknown

- **The Workload Plan of 29 Aug 2026 is not in the repository.** The ~25 s/s and ~31%
  figures cannot be traced. `VisionGuard-Deployment-Decision.html` and
  `VisionGuard-Hardware-Buildlist.html` sit untracked in the repo root and make the same
  argument in different units (442 inferences/sec; 2 vs 9 GPUs). **Re-establish the
  baseline by measurement (T001); do not carry a number forward from a document nobody
  can open.**
- **Whether `psutil` is available or acceptable.** If not, `cpu_percent` / `gpu_percent`
  stay `None` and read as unavailable with a reason. Check before writing the sampler.
- **Whether the site cameras' sub-stream URLs exist per camera.** `docs/PLAN.md` §7.1
  confirms sub-streams exist at ~512 kbps, but no per-camera URL is configured. The
  grab/retrieve split does not need them; a future sub-stream option would.
- **Whether `cv2.VideoCapture.grab()` behaves on the webcam backend on this machine** as
  it does on file and RTSP. Verify on `cam-laptop` before relying on it — MSMF and DSHOW
  have differed here historically.
- **Exact GPU driver version on the deployment machine.** Change 5's FP16 re-measurement
  is gated on it being current, and the deployment machine is still an owner blocker
  (`STATUS.md`, "Blocked on the owner — Target hardware").
