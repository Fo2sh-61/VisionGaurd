# Phase 0 research: Vehicle Gate

Everything here was resolved by reading the code and running commands, not by
assumption. Where a claim is measured, the command that measured it is given.

---

## 1. What actually comes across from `models/Gate/gate-anpr/`

**Decision**: port ~1,100 lines of four modules. Leave ~3,900.

| Gate file | Lines | Verdict | Where it lands |
|---|---|---|---|
| `anpr/plate_text.py` | 279 | **Port, nearly verbatim** | `engine/vg/platetext.py` |
| `anpr/tracker.py` | 291 | **Port the voting** | inside `features/vehicles.py` |
| `anpr/ocr.py` | 410 | **Port `CHAR_GLYPHS`, `_YoloCharReader`, `_group_by_position`, `_settle_letter_or_digit`** | `infer/plates.py` |
| `anpr/detector.py` | 342 | **Port the YOLO path + `strip_blue_band`, `deskew`, `enhance`** | `infer/plates.py` |
| `anpr/db.py` | 652 | Drop | VisionGuard has `vg/db.py` and the `events/` pattern |
| `anpr/pipeline.py` | 618 | Drop | `FeatureWorker` is this, minus the threading |
| `anpr/capture.py` | 126 | Drop | `vg/ingest/` |
| `anpr/config.py` | 183 | Drop | `vg/config.py` |
| `anpr/web/` | 966 | Drop | The console |
| `anpr/setup_wizard.py` | 232 | Drop | Settings page |

**Rationale**: the four kept modules encode knowledge that cannot be re-derived from
first principles — which Arabic characters are confusable on a plate, that the
coloured band must come off before reading, that the character model emits Latin
transliterations. The dropped modules are re-implementations of things VisionGuard
already does *better*, because VisionGuard's versions carry auth, audit and honest
degradation, and the Gate dashboard has no login at all.

**Alternatives considered**: running gate-anpr as a sidecar service (two databases,
two configs, an unauthenticated port) and copying the folder wholesale (two camera
subsystems in one repo). Both rejected with Mohamed before the spec was written.

### What `tracker.py` actually depends on

Checked by reading its imports: it uses only `plate_text.richer` and
`plate_text.same_plate`, plus `PlateBox` for geometry. So the voting logic ports
cleanly once `platetext.py` exists, and **`near_variants` (the widest function in
`plate_text.py`) has no caller** — it does not need to come across.

---

## 2. Multi-frame voting — the part that makes reading trustworthy

**Decision**: port the weighted-vote scheme, keep the three-frame floor.

Each frame contributes a vote weighted by `ocr_confidence × plausibility ×
plate_width`. Readings within one edit of each other are **merged rather than split**,
because `ه/٥`, `و/٦`, `ب/ت` are the confusions the model actually makes, and letting
them fragment the vote is how a correct plate loses to two wrong ones. A plate is only
recorded once ≥3 frames agree.

**Rationale**: the Gate README states this is what turns a ~90%-per-frame reader into
a system that is right almost every time, and its own test suite covers the merge
behaviour.

**Fits VisionGuard how**: this is the same shape as the knife feature's candidate →
scene state machine (`features/weapons.py:150`), which also refuses to act on one
frame. Same idea, different evidence.

**Alternative rejected**: trusting the highest-confidence single frame. That is the
design that produces a register full of near-miss plates, each of which looks like a
different car.

---

## 3. Where visits come from

**Decision**: derive them from `vehicle_pass` with a window function. **No `visits`
table.**

The Gate project maintains a `visits` row per car with an `open` flag, opened on
entry, closed on exit, plus `close_orphans()` on shutdown for the ones that never
closed. That is persistent state describing something already fully recorded in the
pass log.

```sql
-- shape only; the real one lives in events/vehicles.py
SELECT plate, at AS entered,
       LEAD(at) OVER (PARTITION BY plate ORDER BY at) AS left_at
FROM vehicle_pass WHERE direction IN ('entry','exit')
```

**Rationale**: fewer tables, no lifecycle to corrupt, no shutdown hook, and the answer
cannot drift from the passes it is computed from. At school scale — tens of passes an
hour — an indexed window function is not a performance question.

**Consequence to honour**: with only an entry camera, this query yields entries and no
pairs. That is the correct answer, and P6-FR-012 requires the page to say so rather
than print a zero.

**Alternative rejected**: the stored `visits` table. Its one real advantage is O(1)
"inside now", which is not a constraint we have.

---

## 4. Blacklist alerts

**Decision**: reuse `attention()` and `acknowledge()` on the existing `Store` protocol
(`api/store.py:168-169`). No new alert table, no new page.

**Rationale**: VisionGuard's attention mechanism already does everything the Gate
`alerts` table does — level, acknowledgement, actor, history — and it is already wired
to the Home page a guard is looking at. Building a second one would mean a guard has
two places to check, which is how an alert gets missed.

**Alternative rejected**: porting the `alerts` table. It would have duplicated an
existing subsystem and put the blacklist alert on a page nobody has open.

---

## 5. Accelerated inference — measured findings

### 5.1 The path is cold, and this is why

Verified by command, not inference:

| Check | Result |
|---|---|
| `.engine` files present | 5 |
| Referenced by `engine.yaml` | **0** — every model points at `.pt` |
| `import tensorrt` on the engine's interpreter | `ModuleNotFoundError` |
| Loading `models/yolov8s-480.engine` | fails at `import tensorrt` inside ultralytics' `autobackend.py:350` |
| Person model configured `imgsz` | 640 — the engine on disk is 480 |
| `export_tensorrt()` callers | **none** — dead code on three runners |

`models/README.md:260` already warned the engines were exported by ultralytics 8.4.46
while 8.4.7 is installed.

**None of this was visible on any screen.** That is what makes it a truthfulness
problem rather than a performance one, and it is the direct reason P6-FR-033 and
P6-FR-035 exist.

### 5.2 The version that works — and the one that silently does not

**`pip install tensorrt` gives you TensorRT 11.2.1.2, and it is broken on this GPU.**

It imports. It builds a `Logger`. Then:

```
>>> import tensorrt as trt      # imported 11.2.1.2
>>> l = trt.Logger(trt.Logger.WARNING)   # logger ok
>>> b = trt.Builder(l)          # Segmentation fault (exit 139)
```

**The failure mode is what makes this dangerous.** A segfault kills the interpreter
outright, so ultralytics' export reports **exit code 0** and produces no `.engine`
file. The build looks like it worked. Chasing it through `m.export()` shows only:

```
TensorRT: starting export with TensorRT 11.2.1.2...
[exited with code 0]
```

No traceback, no error, no engine. Two runs were lost to this before the cause was
isolated by calling `trt.Builder` directly.

**Cause, isolated by experiment**: the **CUDA line**, not the GPU. Installing the
same TensorRT version built for cu12 fixes it completely:

```
tensorrt_cu13 11.2.1.2  ->  trt.Builder()  Segmentation fault
tensorrt_cu12 11.2.1.2  ->  trt.Builder()  OK
```

Same version, same GPU, same torch. Only the CUDA line differs. Turing (SM 7.5) is
fine; the cu13 runtime against a cu128 torch is not.

**That the import succeeded proved nothing.** `import tensorrt` works on both. The
crash is at `Builder` construction, which is the first call that actually touches the
CUDA runtime. Any check that acceleration "works" must construct a Builder, not just
import the module.

**Decision — the install that works on this machine:**

```bash
pip install tensorrt_cu12_bindings tensorrt_cu12_libs   # the native library
pip install tensorrt-cu12                               # the `import tensorrt` shim
```

The third line matters: the component packages import as `tensorrt_bindings`, while
ultralytics does `import tensorrt`. Without the shim the export fails to find it.
`tensorrt-cu12` is a tiny sdist and installs in seconds once the components are there.

**Pinning to 10.x is not an option on this interpreter.** Checked: `10.13`, `10.15`,
`10.16` and `11.0` have no cp314 wheels. Python 3.14 has **11.1 and 11.2 only**. That
would have been the natural fix and it does not exist — worth knowing before someone
spends an afternoon looking for it.

**API note**: `Builder.platform_has_fast_fp16` was removed in 11.x. Code carried over
from a 10.x example will `AttributeError` on it.

### 5.2c The version chain, in full

Getting one engine built on this machine meant resolving a four-link chain. Each link
was only visible after the one before it was fixed, and none of it is guessable.

| Link | Symptom | Resolution |
|---|---|---|
| `pip install tensorrt` → cu13 | `trt.Builder()` **segfaults**, export exits **0** with no file | install the **cu12** components |
| `tensorrt_cu12_bindings` alone | `import tensorrt` still fails; it imports as `tensorrt_bindings` | also install the `tensorrt-cu12` shim |
| TensorRT 10.x (what ultralytics 8.4.7 wants) | no cp314 wheels for 10.13 / 10.15 / 10.16 / 11.0 | **not available** — Python 3.14 has 11.1 and 11.2 only |
| ultralytics 8.4.7 + TRT 11 | `AttributeError: NetworkDefinitionCreationFlag has no EXPLICIT_BATCH` | upgrade ultralytics to **8.4.127** |
| ultralytics 8.4.127 + TRT 11 + FP16 | `ModuleNotFoundError: modelopt` | on TRT 11, FP16 is routed through NVIDIA `modelopt` — either install it or export FP32 |

**ultralytics 8.4.7's version guard is the root of the fourth link.** It reads
`is_trt10 = major >= 10`, which is *true* for TensorRT 11, so it takes the
TensorRT-10 branch and then calls APIs that 11 removed. 8.4.127 adds a separate
`is_trt11` and guards `EXPLICIT_BATCH` behind `flag = 0 if is_trt10`.

### 5.2d The ultralytics upgrade, verified

8.4.7 → 8.4.127 is 120 patch releases and it drives person, knife, lost-bag and pose
detection, not just plates. Verified against the labelled clip
(`engine/tools/benchmark.py`, which runs on `walk-through_cam-laptop_*.mp4`):

| | 8.4.7 | 8.4.127 |
|---|---|---|
| **people detected (60 frames)** | **64** | **64** |
| p50 | 18.6 ms | 19.4 ms |
| p95 | 22.2 ms | 24.9 ms |
| throughput | 52.9 fps | 49.4 fps |

**Detection is identical.** Timing differs by about a millisecond, which is noise on a
Max-Q part that throttles.

**Two consequences of the upgrade that need work in Slice A:**

- **`opencv-python` was pulled from 4.x to 5.0.0.** YuNet and SFace run through
  OpenCV's DNN module, so this is the upgrade's real risk. `cv2.FaceDetectorYN` and
  `cv2.FaceRecognizerSF` both still exist — checked — but the face pipeline needs
  running against a real face before this is called safe.
- **`half=` is deprecated in favour of `quantize=`.** Every runner passes
  `half=self.half`, so the logs now carry a deprecation warning per inference call and
  a future release will remove it. Small, mechanical, and it belongs in Slice A rather
  than being left to rot.

**Requirement this creates**: `build_engines.py` must **verify the file exists** after
each export, and must not infer success from an exit code. A tool that trusts the exit
code here would have reported six successful builds and produced nothing — which is
precisely the class of untruth P6-FR-031 exists to prevent. This is now the single
most important detail in Slice A.

**Two further traps, both measured:**

- **`pip install tensorrt` takes ~20 minutes and prints nothing**, because the
  meta-package is an sdist that downloads and builds a **1.96 GB** wheel at install
  time. It is not hung. Install the `_bindings` + `_libs` component wheels directly
  and it is far quicker.
- **`pip install --only-binary=:all: tensorrt-cu12` fails**, because the meta-package
  is an sdist and the flag rejects it. That reads as "no wheel for Python 3.14" and is
  false — the component wheels for cp314 exist.
- **ultralytics auto-installs `onnx` and `onnxruntime-gpu` during an engine export**
  (~180 MB) unless `YOLO_AUTOINSTALL=false`. `infer/persons.py:34` already sets it for
  the engine's own process; a standalone export script must set it too. One package
  failed with `Access is denied` writing to `C:\Python314\Lib\site-packages`, so the
  environment is now in a partially-installed state — worth a `pip check`.

### 5.2b Measured, on this machine

`yolov8s` at `imgsz=640`, FP16, batch 1, RTX 2080 Max-Q, 30 iterations after warm-up:

| Form | ms/frame |
|---|---|
| `.pt` on CUDA | **19.7** |
| TensorRT | *(recorded in `quickstart.md` once `build_engines.py` has run)* |

The `~12 ms` in `infer/persons.py:13` is from an earlier library and hardware state.
Treat 19.7 ms as the number to beat, not that one.

### 5.3 How a runner picks its weights

**Decision**: one helper, `weights_to_load(cfg) -> (Path, str)`, in `infer/shared.py`.

```
<stem>-<imgsz>.engine   exists and tensorrt imports  ->  use it,  form="TensorRT"
otherwise                                            ->  use .pt, form="PyTorch CUDA"
```

The `<stem>-<imgsz>` convention is **already what is on disk** — `yolov8s-480.engine`,
`yolov8s-pose-640.engine`, `yolov8m-worldv2-search-960.engine`.

This is the smartest part of the plan and it is worth being explicit about why:
because the input size is *in the filename*, P6-FR-032 ("a build made for a different
input size must be rejected") needs no comparison logic at all. A config asking for
640 simply never names the 480 file. The rule enforces itself.

`form` is then surfaced through the *existing* `_*_stage()` detail strings — see
`live.py:1600`, which already prints `f"{version} on {device} - ..."`. Adding the form
to that sentence satisfies P6-FR-035 with no new wire type and no new page.

**Alternative rejected**: a manifest recording which engine matches which model, with
hashes and versions. More correct in theory; it is a second source of truth that can
disagree with the filesystem, and the filename already carries the only fact that
matters.

### 5.4 What cannot be accelerated, and must not be claimed

- **YuNet + SFace** are ONNX through OpenCV DNN, not ultralytics. SFace is settled in
  `AGENTS.md` — changing it invalidates every enrolment.
- **ByteTrack and the appearance matcher** are not neural networks. `AGENTS.md` says
  plainly: no GPU path, do not promise one.

P6-FR-034 names both so a later reader cannot assume they were covered and quietly
forgotten.

### 5.5 Expected cost of the plate pass

The character model runs **only on crops the plate detector returned**. On a frame
with no car, one model runs; on a frame with a car, two — and the second on a small
crop, not a full frame. This is the same gating that makes knife detection affordable
(`features/weapons.py:1-16`), and it is why two YOLO11m models at a gate is a
different proposition from two models on every frame.

Real timings are recorded in `quickstart.md` after `build_engines.py` has run. **No
speed-up figure is quoted in this plan**, because the honest ones do not exist yet —
the `~12 ms` in `infer/persons.py:13` predates the current library and hardware state.

---

## 6. Spreadsheet import

**Decision**: add `openpyxl` (~250 KB, pure Python, no compiled extensions).
Not currently installed — verified.

CSV is handled by `csv` from the standard library. Column headings are matched in
English and Arabic, and both digit systems normalise through `platetext.normalize`,
so `١٢٣٤` and `1234` land on the same row.

**Alternative rejected**: CSV only. P6-FR-017 asks for Excel because a school office's
list arrives as `.xlsx`. Telling them to convert every file is not simplification.

---

## 7. Camera configuration

**Decision**: two optional fields on `CameraConfig` (`config.py:179`) — `gate: int |
None` and `direction: "entry" | "exit" | None`.

Both default to `None`, so every existing camera parses unchanged and no other feature
notices. A camera is a gate camera when it has both **and** carries `vehicles` in its
`features:` list.

**Validation**: `direction` must be `entry` or `exit`. **`both` is deliberately not
accepted** — Mohamed's decision, and the Gate project's own README calls
single-camera direction inference "noticeably less reliable". A camera states what it
sees; it does not guess.

**For now**: `cam-laptop` gains `gate: 1`, `direction: entry`, and `vehicles` in its
features.

---

## 8. Snapshot storage and expiry

**Decision**: JPEG pairs under `engine/data/plates/<YYYY-MM-DD>/`, expired by an
`expire(older_than)` method copied from `events/weapons.py:277`.

The pass row keeps its image paths as text and survives their deletion — a pass whose
images have aged out is still a pass, and `WeaponScene.playable` (`events/weapons.py:123`)
is the existing precedent for "the record outlives its media".

Retention is 30 days, read from `storage.clip_retention_days`, not a literal — so it
cannot drift from the number the console already shows.
