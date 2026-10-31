# Contract: `engine/tools/measure_remote.py`

```text
python engine/tools/measure_remote.py --url URL --label LABEL [--email E] [--minutes 6]
                                      [--camera cam-clip] [--out specs/021-cloud-trial/evidence]
python engine/tools/measure_remote.py --compare            # rebuild comparison.md only
```

- Password: `VG_MEASURE_PASSWORD` if set, else asked without echo. Never an argument, never
  written to a file.
- Standard library only, so it runs from any Python on the PC.
- Exit 0 when a run completed (even with failures — they are in the table); 1 when it could
  not sign in or the URL never answered.

## What it requests

| Measure | Requests | Rate |
|---|---|---|
| Clock offset | `GET /healthz` ×20 | back to back |
| Page-load reads | the GETs the console makes when it first opens (Home, signed in), read off the browser's network panel on 31 Oct 2026: `/healthz`, `/auth/me`, `/system/capabilities`, `/cameras`, `/site`, `/attention` | 30 rounds |
| Tiles | `GET /cameras/{camera}/snapshot?width=640&fps=15` — one tile on screen asks 15 a second (`frame.ts`) | at most 15/s, 60 s |
| Stream | `GET /cameras/{camera}/stream` (MJPEG), frames counted | 30 s |
| Boxes | `GET /cameras/{camera}/detections?feature=counting` | 5 per second (the console's rate at ≤ 4 tiles), 60 s |
| Events | `GET /breaches?window=today`; the clip camera must be switched on as restricted | 4 per second, rest of `--minutes` |
| Server | `GET /system/health` | at start and end |

## Output

`<out>/<label>-<YYYYMMDD-HHMM>.json` (shape in `data-model.md`) and `<out>/comparison.md`:
one row per measure, one column per label (latest run of each), every age printed with its
± clock uncertainty, failures in their own column, and a header naming the machine, GPU,
camera and sample length of each column.
