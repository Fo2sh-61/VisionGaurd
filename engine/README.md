# VisionGuard engine

The backend behind `web/` and `mobile/`. Six layers; the front end only ever
talks to the top one.

```
ingest     RTSP/webcam capture, reconnect, last-good-frame cache
infer      shared model runners — decode once, detect once, fan out
track      per-camera multi-object tracking, stable track ids
features   one file per product feature, consuming tracked detections
events     rules output -> database + clips + pub/sub
api        FastAPI, shaped to match web/src/services/api.ts
```

## Running it

Two terminals. Note there are no `#` comments on these lines — `cmd.exe` does
not strip them the way a POSIX shell does, and will pass them to the program as
arguments.

Terminal 1, the engine (serves on `http://127.0.0.1:8001`; 8000 belongs to an installed engine service):

```
pip install -r engine/requirements.txt
python engine/tools/serve.py
```

PyTorch is not in `requirements.txt` — install it first from pytorch.org,
matched to your CUDA version.

Terminal 2, the web console (`http://localhost:5173`):

```
cd web
npm run dev
```

The web dev server already forwards to port 8001. If you change it, **restart
Vite** — env files are read once at startup, so an edit while it is running has
no effect.

`http://127.0.0.1:8001/docs` is the generated OpenAPI page. **That page is the
contract.** If the front end and the engine disagree, it decides.

## Where the data comes from

Right now: `vg/api/store.py::MockStore` — fixtures in the wire shape, no models
running. `Store` is a Protocol, so going live means implementing it against the
real database and calling `set_store()`. Nothing in `vg/api/app.py` changes, and
features can switch over one at a time.

## Configuration

`engine.yaml` is what the system *is* — cameras, zones, schedules, model paths.
Committed, safe to read.

`.env` is secrets — camera passwords. **Never committed.** Reference them from
the yaml as `${VG_RTSP_1}`; see `.env.example`.

Two conventions worth knowing:

- **Geometry is normalised.** Zones and boxes are fractions of the frame,
  origin top-left, never pixels. Config validation rejects anything outside
  0–1, because pasting pixel coordinates into a normalised field is the easiest
  mistake to make here.
- **Point at `.pt`, never `.engine`.** A TensorRT plan is compiled for one GPU
  and one TensorRT version — a build output for a specific machine, not an
  artifact. A test fails if `engine.yaml` references one.

## Tools

```bash
python engine/tools/serve.py            # the API
python engine/tools/record.py --list    # configured cameras
python engine/tools/record.py --camera cam-laptop --label walk-in --show-zones
python engine/tools/audit_models.py     # regenerate models/MODELS.md
```

### Recording footage

There is no test footage in this project, so `record.py` is how it gets made.
It writes an `.mp4` plus a `.json` sidecar, and **SPACE during recording marks
the moment something happens** — that keypress is the label. A folder of
unlabelled clips is barely more useful than no clips.

Worth capturing early:

| Label | Why |
|---|---|
| `baseline-empty` | Minutes of nothing. The false-alarm set — most valuable, most skipped. |
| `walk-through` | Someone crossing the zone and leaving. |
| `loiter` | Someone entering and staying. |
| `two-people` | Occlusion, where trackers go wrong. |
| `backlit` | The same walk against a window. CCTV's hardest condition. |

## Tests

```bash
cd engine && python -m pytest          # 102 tests
python -m pytest -m camera             # needs a real webcam; skipped by default
```

`tests/test_api.py::TestBehaviouralContract` is the section to read first. The
front end makes promises to users in its own copy — false alarms stay in the
history, weapons always wait for a human, every tracking search is recorded —
and those are tested like any other requirement. A failure there means the UI
is lying to a head teacher, not that a unit test is stale.

## Notes on the models

See `models/README.md`. The short version: the weapons detector is
**YOLO-World with 18 saved text prompts, not a fine-tuned model.** It works
today with no training, but it has never seen school CCTV, and `scissors`,
`screwdriver` and `hammer` are in its prompt list. Treat its scores with
suspicion until there is an eval set to measure them against.
