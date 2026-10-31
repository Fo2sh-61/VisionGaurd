# Implementation Plan: Cloud trial

**Branch**: `021-cloud-trial` | **Date**: 31 Oct 2026 | **Spec**: [spec.md](spec.md)

## Summary

Run the engine on a free Kaggle T4 notebook against the recorded clip, reach it from
Mohamed's PC through a Cloudflare quick tunnel, and measure the difference against the
local laptop. Seven small pieces, each the smallest thing that meets its requirement:

| # | Piece | Requirement | Mechanism |
|---|---|---|---|
| A | H.264 on Linux | CT-FR-002 | One more encoder in `ingest/encoder.py`: pipe frames to the system `ffmpeg` with `libx264`. Linux only; Windows order unchanged |
| B | Python 3.11/3.12 | CT-FR-001 | No 3.12+ syntax found (`ast` check on every file). Prove it by running the whole suite under the local Python 3.11 with CPU torch, fix what breaks |
| C | Cloud profile | CT-FR-010..013 | `VG_CONFIG_OVERLAY=<file>` deep-merged over `engine.yaml` in `config.load()`; `engine/profiles/cloud.yaml`. A top-level `profile: cloud` that dev sign-in refuses |
| D | One address | CT-FR-020 | `api.console_dir` (unset by default). When set, the engine serves `web/dist`: assets public, browser navigations get `index.html` |
| E | Session end | CT-FR-050 | `VG_SESSION_ENDS_AT` → `/healthz` adds `now`, `endsAt`, `stopping`. One console banner reads it |
| F | Notebook | CT-FR-030..032, 051 | `tools/cloud/pack.ps1` (PC) → private dataset; `tools/cloud/bootstrap.sh` + `stop.sh`; `cloud/visionguard_trial.ipynb` |
| G | Measuring | CT-FR-040..042 | `engine/tools/measure_remote.py`, standard library only, writes `evidence/<label>-<date>.json` and `evidence/comparison.md` |

What is already Linux-safe and stays as is: webcam `CAP_DSHOW` already falls back to the
default backend (`source.py:323`); `serve.py`'s `psutil` clean-up is cross-platform;
`benchmark.py` guards its D3D11/DXGI code by `sys.platform`; `tzdata` installs everywhere
and Linux has a system zone database anyway. NVML is read through `pynvml`, which works on
Linux, but **no requirement pins it** — the laptop has it by hand. Add `nvidia-ml-py`.

## Technical Context

**Language/Version**: Python 3.14 (Windows, unchanged); 3.11 or 3.12 on Kaggle (printed at start)
**Primary Dependencies**: existing; plus `nvidia-ml-py`; on Kaggle only `tensorrt-cu12`, `cloudflared` (pinned release, checksum checked)
**Storage**: a fresh SQLite file in a throwaway folder (`/tmp/vg-trial`), copied to `/kaggle/working` at the end
**Testing**: pytest (baseline **2014 passed, 6 skipped**; one timing test flaked on the first run and passed on the rerun)
**Target Platform**: Kaggle notebook, Linux, 1–2× T4 · Windows 11 laptop unchanged
**Performance Goals**: none new — the trial measures PLAN §7 at a distance
**Constraints**: no model downloads; no keys in the notebook; no webcam; Windows behaviour byte-for-byte the same unless a profile or env var asks
**Scale/Scope**: one camera (`cam-clip`), one admin, a few hours

## Constitution Check

| Principle | How this plan meets it |
|---|---|
| I. Real-time | The whole point: client-side p50/p95 for tiles, boxes and events, both places |
| II. Isolation | No feature code changes. The profile picks cameras via the existing `VG_CAMERAS` |
| III. Truthful | Failed requests counted separately; clock-offset uncertainty printed beside every age; mp4v fallback still warned in System Health; TensorRT vs `.pt` per model in the session summary |
| IV. Security/privacy | Real password only; dev sign-in refused when `profile: cloud`; engine listens on 127.0.0.1 (the tunnel is the only way in); recorded clip and empty DB only; Ask/email keys never present |
| V. Complete | Console banner before the engine goes; output saved on planned stop |
| No model sourcing | Bootstrap only links files from `/kaggle/input/<models dataset>`; a missing file stops the run |

**Gate: passes.** Re-checked after design: passes.

**Deviation from the request, on purpose**: the request said bind `0.0.0.0`. The tunnel
runs on the same machine, so `127.0.0.1` is enough and exposes nothing else. Kaggle has no
inbound ports either way.

## Design notes

**A. Encoder.** `Encoder` gains a `pipe` flag; `open_writer` starts
`ffmpeg -f rawvideo -pix_fmt bgr24 -s WxH -r FPS -i - -c:v libx264 -pix_fmt yuv420p
-movflags +faststart <path>` and returns a small writer with `isOpened/write/release`.
Linux order: OpenCV avc1 → pipe x264 → mp4v. Windows order untouched. The test writes
real frames through the pipe (runs wherever `ffmpeg` is on PATH — it is on the laptop) and
checks with `ffprobe` that the stream is `h264` / `yuv420p`.

**C. Overlay.** Dicts merge key by key; lists and scalars replace. An overlay path that
does not exist is a `ConfigError`, never silently ignored. `cloud.yaml` sets: `profile:
cloud`, `site_name`, `api.host: 127.0.0.1`, `api.console_dir: web/dist`, `storage.*` under
`${VG_TRIAL_DIR}`, `alerts.console_url: ${VG_PUBLIC_URL}`. (A yaml zone on `cam-clip`
was planned here and dropped — see "Changed during implementation".)

**D. Console.** Only when `console_dir` is set: `GET /assets/*` and the root files
(`/`, `/favicon.*`, `/manifest.webmanifest`) are public and served from the folder; a GET
with `Sec-Fetch-Mode: navigate` and `Accept: text/html…` gets `index.html` (so a reload on
`/cameras` gives the page, not 401 JSON). `/docs` and `/openapi.json` are excluded. The
cost: opening a clip URL directly in a new tab shows the console instead of the video —
written in the quickstart. `index.html` gets `Cache-Control: no-cache`.

**E. Banner.** `/healthz` is public, so it carries only `ok`, `version`, `now` (ms), and
when set `endsAt` and `stopping`. Nothing about the site. The console polls it every 30 s
(every 10 s inside the last 15 minutes) and shows: "This trial engine stops at 18:40 — in
25 minutes", then "The engine is stopping now", then "The engine has stopped". No banner
when `endsAt` is absent, so the laptop looks the same.

**F. Notebook flow.** Steps, each timed: GPU + Python + driver → inputs present (code zip,
models, clip, secret) → `pip install` the requirements minus torch/torchvision →
`ffmpeg` present → link models into `models/` → **build TensorRT engines** (`build_engines.py
--only` the models `cam-clip` uses; failures leave the `.pt` and are listed) →
`benchmark.py` (server-side numbers, before the engine takes the GPU) → `create_user.py
--password-env VG_ADMIN_PASSWORD` → start `cloudflared` → read its `trycloudflare.com`
address → start the engine with the overlay → wait for `/healthz` → print the address.
A watchdog calls `stop.sh` at the deadline (default: start + 11 h 30 m): SIGINT the engine,
wait, `sqlite3 .backup` the DB, copy logs and evidence to `/kaggle/working/trial-<date>/`.
The notebook's last cell calls the same `stop.sh`.

The code reaches Kaggle as a private dataset made by `pack.ps1` from a commit
(`git archive`) plus a fresh `web/dist` — no GitHub token, no Node on Kaggle.

**G. Measuring.** Clock offset from 20 `/healthz` calls, taking the one with the shortest
round trip (offset ± half that round trip, printed). Then, for `--minutes` (default 6):
page-load reads (list in `contracts/measure.md`), snapshot tiles as the console asks for
them, 30 s of the MJPEG stream, box age from `/cameras/cam-clip/detections` `at`, and
breach age from `/breaches` `at`. A breach is raised after the zone's dwell time by design;
the table says so instead of subtracting it. The clip's marks give the expected number of
entries per loop; the table shows expected vs seen.

## Project Structure

```text
specs/021-cloud-trial/
├── plan.md  research.md  data-model.md  quickstart.md  context.md  tasks.md
├── contracts/healthz.md  contracts/measure.md
└── evidence/                       # measure_remote output lands here

engine/vg/config.py                 # VG_CONFIG_OVERLAY merge; profile; api.console_dir
engine/vg/ingest/encoder.py         # pipe x264 encoder, Linux order
engine/vg/auth/dev_signin.py        # refuse when profile is cloud
engine/vg/auth/deps.py              # console paths public only when console_dir set
engine/vg/api/app.py                # healthz fields; console mount + navigation fallback
engine/profiles/cloud.yaml          # new
engine/tools/create_user.py         # --password-env
engine/tools/measure_remote.py      # new
engine/requirements.txt             # nvidia-ml-py
engine/tests/test_cloud_trial.py    # new: overlay, profile, dev sign-in, console, healthz
engine/tests/test_encoder.py        # extend: Linux order, pipe writes real H.264
engine/tests/test_measure_remote.py # new: stats, offset, table
web/src/components/SessionNotice.tsx + Layout + api.ts + format.ts
tools/cloud/pack.ps1  bootstrap.sh  stop.sh
cloud/visionguard_trial.ipynb
STATUS.md
```

## Complexity Tracking

| Addition | Why | Simpler option rejected |
|---|---|---|
| Pipe encoder | OpenCV's pip wheel has no H.264 encoder on Linux | Saving mp4v → a player with no picture (the bug `encoder.py` exists to prevent); re-encoding afterwards → clips unplayable until a second job runs |
| Navigation fallback | Console routes and API routes share paths (`/cameras`) | Changing the console to a `/app` base path touches every link and the Windows setup |

## Changed during implementation (31 Oct 2026)

- **No yaml zone.** Restricted areas are now whole cameras switched on in the console
  and kept in the database (`camera_restricted`); `zones:` in yaml no longer drives
  breaches. The first local measurement saw 0 breaches because of it. `bootstrap.sh`
  now switches `cam-clip` on with the console's own call (`PATCH /zones/cam-clip`,
  audited), and the clip's marks are no longer used as an expected count: they were
  drawn for the old desk zone.
- **loiterwatch** (tracking's appearance matcher) is installed by hand on the laptop and
  was in no instruction. Found by the Python 3.11 run; now installed by `bootstrap.sh`
  and noted in `requirements.txt`.
- **cloudflared** comes from Cloudflare's signed apt repository rather than a pinned
  binary with a checksum: apt checks the signature, and no checksum had to be guessed.
- **Console middleware instead of `deps.py`**: the console's files are served by a
  middleware that runs before `authenticate` and only when `console_dir` is set, so
  `PUBLIC_PATHS` is untouched and the laptop's rules are byte-for-byte the same.
- **Mobile copies**: `api.ts`, `wire.ts`, `format.ts`, `keys.ts`, `en.ts` are parity
  files, so the phone app got the same (unused there) additions.
- **Keep-alive cell** in the notebook: an interactive Kaggle session may stop when no
  cell runs; cell 4 stays running while the console is in use (unverified).

## Not testable from this machine

WSL is not installed, so nothing here runs on Linux before Kaggle. These are Mohamed's to
run, with the output pasted back: the notebook end to end; OpenCV's own avc1 on Linux; NVML
on Kaggle; TensorRT build times on a T4; whether `/kaggle/working` survives an interactive
session's end; the cloud column of the table.
