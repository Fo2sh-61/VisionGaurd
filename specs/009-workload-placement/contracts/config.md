# Contract: configuration — the reversal surface

Every one of the five changes reverses by editing `engine/engine.yaml` and restarting.
No code change, no rebuild, no migration, no re-enrolment. This file is the whole of
P8-FR-004, and `quickstart.md` §6 is how it is proven.

## Change 1 — patrol face recognition

```yaml
tracking:
  patrol_hz: 0        # was 0.5
```

Also change the two code defaults so "off" is the default for a fresh install:
`config.py:699` (`patrol_hz: float = 0.5`) and `config.py:714`
(`float(raw.get("patrol_hz", 0.5))`).

**No new code path.** `app.py::_start_patrol:885` already handles `rate <= 0`: it logs
`patrol recognition is switched off (tracking.patrol_hz: 0)` and returns `None, None`.
Reverse by setting any value in `0 < x <= 30`.

## Change 2 — face gating

```yaml
cameras:
  - id: cam-laptop
    face_gate: person     # person | frame
```

- `person` — YuNet runs on person crops from the shared pass.
- `frame` — whole frame, exactly as today. **This is the reversal.**
- Default: `person` where `features:` already include `counting`, `intrusion` or
  `track`; `frame` otherwise (research D3 — an attendance-only camera would otherwise
  gain the person model and a GPU dependency it does not have today).

## Change 3 — batched person pass

```yaml
models:
  person:
    batch: true          # false restores one-frame-at-a-time
```

Batches only threads **already blocked** on `SharedDetection._model_lock`. There is no
window to tune: a lone caller finds no waiters and runs immediately (P8-FR-011).

## Change 4 — capture rate

```yaml
cameras:
  - id: cam-laptop
    live_capture: watched   # watched | always
```

- `watched` — decode every frame only while an operator has the camera open; otherwise
  decode at the camera's `fps`.
- `always` — decode every frame, as today. **This is the reversal.**

Frames are **grabbed** at the device rate in both states. Only the decode is
conditional, which is what keeps `docs/PLAN.md` §7's camera→screen budget intact.

## Change 5 — bag acceleration

```yaml
models:
  bags:
    accelerate: false     # was implicitly true
```

**Not a file deletion.** `config.py:426` already defines `accelerate: bool = True`,
`config.py:452` reads it, `shared.py:139` honours it, and both plate models already use
`accelerate: false` for the same reason. A deleted `.engine` file is not reversible by
configuration, which P8-FR-004 requires; this key is.

Deleting `models/bagsearch-640.engine` afterwards is optional housekeeping and must not
be the mechanism. The GPU driver update and the FP16 re-measurement stay separate
(P8-FR-018) and are reported as not measured until actually run (P8-FR-019).

## Validation

- Unknown `face_gate` / `live_capture` values are a **startup error**, never a silent
  fallback — `config.py` already rejects unknown keys and this follows that pattern.
- `patrol_hz` keeps its existing rule: `0 <= patrol_hz <= 30` (`config.py:715`).
- Omitting every key above must reproduce **today's behaviour except patrol**, so an
  existing `engine.yaml` upgrades without edits.
