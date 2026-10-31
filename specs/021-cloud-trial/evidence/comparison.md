# Cloud trial: response speed, local vs cloud

Written by `engine/tools/measure_remote.py`. One camera (`cam-clip`, the
recorded walk-through), measured from Mohamed's PC. Ages carry ± half the
shortest `/healthz` round trip, because the two clocks are not shared.
Breach age is measured from the breach's own `at` (its scene's start).
Not a site measurement: one clip, one camera, one viewer.

| Measure | local (http://127.0.0.1:8000) |
|---|---|
| Measured for | 6.0 min, from 2026-10-31T10:02 |
| Clock offset (server − PC) | 0 ms ± 1 |
| Read /healthz p50 / p95 | 6 ms / 27 ms |
| Read /auth/me p50 / p95 | 8 ms / 28 ms |
| Read /system/capabilities p50 / p95 | 11 ms / 27 ms |
| Read /cameras p50 / p95 | 7 ms / 26 ms |
| Read /site p50 / p95 | 15 ms / 30 ms |
| Read /attention p50 / p95 | 9 ms / 27 ms |
| Tile pictures received per second (asked: 15) | 14.92 |
| Tile picture p50 / p95 | 13 ms / 30 ms |
| Tile picture size | 22.3 KB |
| Tile failures | 0 |
| Live view frames per second | 12.79 |
| Live view failures | 0 |
| Box age when it arrives p50 | 110 ms ± 1 |
| Box age when it arrives p95 | 221 ms ± 1 |
| Box failures | 0 |
| Breaches seen (in this many seconds) | 2 (in 207.6 s) |
| Breach age when first seen p50 (from its own `at`) | 339 ms ± 1 |
| Breach age when first seen p95 | 476 ms ± 1 |
| Server GPU % / memory MB (start) | 13.0 / 939.0 of 8192.0 |
| Server CPU % of machine (start) | 29.2 |
| Server GPU % / memory MB (end) | 12.0 / 926.0 of 8192.0 |
| Server CPU % of machine (end) | 21.8 |
