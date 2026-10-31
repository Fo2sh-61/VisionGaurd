# Data model: Cloud trial

No database tables change. Three small shapes:

## Config additions (`engine/vg/config.py`)

| Field | Type | Default | Rule |
|---|---|---|---|
| `profile` (top level) | `"" \| "cloud"` | `""` | Anything else is a `ConfigError` |
| `api.console_dir` | path or empty | empty | Relative to the repo. Set but missing `index.html` → the console is not served and System Health / the log says why; the API still runs |
| `VG_CONFIG_OVERLAY` (env) | file path | unset | Missing file → `ConfigError` |
| `VG_SESSION_ENDS_AT` (env) | ISO 8601 with offset | unset | Unparseable → ignored with a warning, never a crash |

## `/healthz` (public) — see `contracts/healthz.md`

`ok`, `version`, `now` (epoch ms, always), `endsAt` (ISO, only when set), `stopping` (bool,
only when `endsAt` is set).

## Measurement run (`evidence/<label>-<YYYYMMDD-HHMM>.json`)

| Field | Meaning |
|---|---|
| `label`, `url`, `started`, `minutes` | what was measured and for how long |
| `clock` | `offsetMs`, `uncertaintyMs`, `samples` |
| `reads[]` | per path: `n`, `failures`, `p50Ms`, `p95Ms` |
| `tiles` | `requested`, `received`, `perSecond`, `p50Ms`, `p95Ms`, `failures`, `meanBytes` |
| `stream` | `seconds`, `frames`, `perSecond`, `failures` |
| `boxes` | `n`, `ageP50Ms`, `ageP95Ms`, `failures` |
| `events` | `expectedPerLoop`, `seen`, `ageP50Ms`, `ageP95Ms`, `dwellSeconds` |
| `server` | System Health snapshot (GPU, CPU, per-subsystem state) at start and end |

`comparison.md` is rebuilt from every JSON present, one column per label.
