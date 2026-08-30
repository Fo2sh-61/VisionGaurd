# Contract: System Health — worker load

**Endpoint:** `GET /system/health` (existing). **Server:** `LiveStore.health()`,
`engine/vg/api/live.py:2294`. Admin-gated by path, as today. No new endpoint.

## What changes

`SystemHealth.pipeline` gains one stage, appended after `_lost_stage()`:

```json
{
  "key": "workers",
  "name": "Feature workers",
  "detail": "6 workers, 0 behind",
  "healthy": true,
  "severity": "info",
  "restartable": false
}
```

`SystemHealth.metrics` gains three, all from counters that already increment:

| key | label | unit | source |
|---|---|---|---|
| `dropped` | `Frames dropped` | count | sum of `Subscription.dropped` |
| `passes` | `Detection passes` | count | `SharedDetection.passes` |
| `cpu` | `Processor` | percent | process CPU |

`SystemHealth.cpu_percent` and `gpu_percent` — **declared today (`schemas.py:715`) and
never set** — get filled. When they cannot be read they stay `null`, and the UI renders
that as unavailable with a reason. Never `0`.

## New wire type

```python
class WorkerLoad(Wire):
    name: str
    cameras: int
    frames_processed: int
    last_inference_ms: float
    queue_depth: int
    queue_max: int
    frames_dropped: int
    behind: bool
```

Camel-cased on the wire: `framesProcessed`, `lastInferenceMs`, `queueDepth`,
`queueMax`, `framesDropped`. Carried on the stage as `workers: list[WorkerLoad]`.

## Rules this contract must hold

1. **200, always.** However saturated the machine, `health()` returns 200 with
   degradation as payload (P8-FR-025, constitution rule 7). No new 5xx path.
2. **A worker that is not running is absent from the list**, not present with zeros. A
   stopped worker and an idle worker are different answers.
3. **`behind` is derived, never guessed:** `queue_depth >= queue_max and frames_dropped
   > 0`. If either counter is unreadable, `behind` is omitted rather than assumed false.
4. **`severity` rises to `warn` when any worker is `behind`,** and the stage `detail`
   names it. A healthy summary over a saturated machine is the exact failure P8-FR-021
   forbids.
5. **No per-worker CPU field exists.** See `data-model.md` §2 — it cannot be measured
   for threads in one process and must not be invented.
6. **No feature may be required for this stage to render.** With every worker absent,
   the stage still returns, reporting nothing running (`bare_live_store` covers it).

## Console

`web/src/pages/SystemHealth.tsx` renders the stage. Per `AGENTS.md`, every rendered
string is built in `web/src/services/format.ts` — the engine sends numbers and enums.
`null` CPU/GPU renders through the existing `DataNotice` / unavailable path, never as
`0%`.
