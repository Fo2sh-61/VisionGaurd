# Data model: Workload Placement

**No database change. No migration. No re-enrolment.** This feature adds no table, no
column and no persisted row. What follows is the config shape and the one new wire type.

## 1. Configuration (the reversal surface)

Every change reverses through `engine/engine.yaml`. These four keys are the whole of
P8-FR-004.

| Key | Where | Today | After | Reverses change |
|---|---|---|---|---|
| `tracking.patrol_hz` | `config.py:699` default, `:714` parse default, `engine.yaml` | `0.5` | `0` | 1 — patrol face recognition |
| `cameras[].face_gate` | new, per camera | absent | `person` \| `frame` | 2 — face gating |
| `models.person.batch` | new, on the person model entry | absent | `true` \| `false` | 3 — batched person pass |
| `cameras[].live_capture` | new, per camera | absent | `watched` \| `always` | 4 — capture rate |
| `models.bags.accelerate` | `config.py:426`, already exists | `true` (implicit) | `false` | 5 — bag acceleration |

### `face_gate`
- `person` — YuNet runs on person crops from the shared pass.
- `frame` — YuNet runs on the whole frame, as today.
- **Default is `person` only where the camera's `features:` already include one of
  `counting`, `intrusion`, `track`.** Otherwise `frame`. Research D3: on an
  attendance-only camera, gating *adds* the person model and a GPU dependency, so
  defaulting it on there would cost time rather than save it.

### `live_capture`
- `watched` — decode every frame only while an operator has the camera open; otherwise
  decode at the camera's `fps`. Frames are still **grabbed** at the device rate either
  way, so no lag accumulates.
- `always` — decode every frame, as today.
- Default `watched`.

> **Corrected 12 Sep 2026:** "decode" in this file means `retrieve()`, which on
> OpenCV's FFmpeg backend is only the conversion to pixels. `grab()` is the decode,
> and it runs on every frame in both states. See `measurements.md` §1b.

### Validation rules
- `patrol_hz`: existing rule holds — `0 <= patrol_hz <= 30`, `0` means off
  (`config.py:715`). No change needed; the value moves, the rule does not.
- `face_gate`, `live_capture`: unknown value is a **startup error**, not a silent
  fallback. `config.py` already rejects unknown keys (`config.py:710` pattern) and this
  follows it.

## 2. Wire type — `WorkerLoad`

One per running feature worker, inside the new `workers` pipeline stage.
`Wire` subclass: snake_case in Python, camelCase out, `extra="forbid"`.

| Field | Type | Meaning | Source that already exists |
|---|---|---|---|
| `name` | `str` | worker name — `recognition`, `patrol`, `people`, `tracking`, `weapons`, `vehicles`, `lost` | `FeatureWorker.name` |
| `cameras` | `int` | cameras this worker serves | `len(FeatureWorker.cameras)` |
| `frames_processed` | `int` | frames analysed since start | `FeatureWorker.frames_processed` |
| `last_inference_ms` | `float` | slowest recent per-frame cost | `FeatureWorker.stats` |
| `queue_depth` | `int` | frames waiting | `len(Subscription._frames)` |
| `queue_max` | `int` | subscription capacity | `Subscription.maxsize` |
| `frames_dropped` | `int` | frames the bus discarded | `Subscription.dropped` (`framebus.py:37,48`) |
| `behind` | `bool` | queue full **and** dropping | derived |

**Nothing here is new measurement.** Every counter above already increments in
production code and is simply never read. `SharedDetection.passes` (`shared.py:190`)
joins them as a site-level metric; its docstring already anticipates this.

### The field that is deliberately absent
There is **no `cpu_percent` per worker.** Workers are threads in one process; the OS
attributes CPU to the process. Inventing a per-thread share would breach Principle III.
Process-level CPU and GPU fill the existing `SystemHealth.cpu_percent` /
`gpu_percent` fields (`schemas.py:715`), which are declared today and never set.

## 3. State transitions — camera capture

```
             operator opens the camera (MJPEG stream, or snapshot)
  ┌────────────┐  ───────────────────────────────────────────►  ┌───────────┐
  │  SAMPLED   │                                                │  WATCHED  │
  │ grab all   │  ◄───────────────────────────────────────────  │ grab all  │
  │ decode @fps│      last stream closes + grace expires        │ decode all│
  └────────────┘                                                └───────────┘
```

**Invariant, and the reason this design is safe:** `grab()` runs at the device rate in
*both* states. Only `retrieve()` (the decode) is conditional. The buffer is never
allowed to back up, so the latency trap documented in `CameraSource.frames()` cannot
occur, and the transition to WATCHED needs no catch-up.

- Entering WATCHED is immediate on the first stream open — P8-FR-014's 1 second is the
  first decode, not a queue drain.
- Leaving WATCHED waits for a short grace after the last reader closes — P8-FR-015
  ("within seconds, not minutes") and the flicking-between-pages edge case.
- A **stale** frame is still published and flagged exactly as today. Change 4 changes
  decode cadence only; it touches no freshness or NO SIGNAL behaviour (P8-FR-016).
