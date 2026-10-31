# Implementation context: Cloud trial

**Written by `/speckit-plan` on 31 Oct 2026, against commit `2c85ebe`** (branch
`021-cloud-trial`, cut from `remote-access`).

Read this before opening any source file. Anchors drift — search the symbol.

## 1. Anchors

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/config.py` | `def load(` | reads `engine.yaml`, `_load_dotenv`, then `raw = _expand(raw, "engine.yaml")`; builds `EngineConfig(...)` field by field at the end; `api=ApiConfig(host, port, cors_origins, poll_seconds)` | after `yaml.safe_load`, before `_expand`: merge `VG_CONFIG_OVERLAY` file. Add `profile` and `api.console_dir` |
| `engine/vg/config.py` | `class ApiConfig` | frozen dataclass, 4 fields | add `console_dir: Path \| None = None` |
| `engine/vg/config.py` | `_apply_camera_override` | `VG_CAMERAS` → enabled flags; unknown id = `ConfigError` | unchanged; bootstrap sets `VG_CAMERAS=cam-clip` |
| `engine/vg/config.py` | `_resolve(value, default)` | relative → `REPO_DIR / p` | reuse for `console_dir` |
| `engine/vg/ingest/encoder.py` | `candidates()` | win32 → `(MSMF_H264, FFMPEG_H264, FFMPEG_MP4V)`, else `(FFMPEG_H264, FFMPEG_MP4V)` | Linux gets `PIPE_X264` second. `Encoder` is a frozen dataclass `(backend, fourcc, label, plays_in_browser)` |
| `engine/vg/ingest/encoder.py` | `open_writer` | loops `_ordered()`, `cv2.VideoWriter(...)`, `isOpened()` | branch for the pipe encoder; return an object with `isOpened/write/release` |
| `engine/vg/auth/dev_signin.py` | `role_from_env` | env `VG_DEV_SIGNIN`; raises if not a role or if `VG_STRICT=1` | add a `profile` argument (or read config) → raise when `"cloud"` |
| `engine/vg/auth/deps.py` | `PUBLIC_PATHS`, `is_public` | frozenset with `/healthz`; `PUBLIC_PREFIXES = ()` deliberately | console paths public **only when** `console_dir` is set — keep it out of the static sets so the laptop's allowlist is unchanged |
| `engine/vg/api/app.py` | `async def healthz` (~l.1946) | returns `{"ok": True, "version": app.version}` | add `now`, `endsAt`, `stopping` (contract) |
| `engine/vg/api/app.py` | `SHUTTING_DOWN = threading.Event()` (~l.215), `lifespan` (~l.255) | set first thing in the `finally` | `stopping` reads it |
| `engine/vg/api/app.py` | `users_db = ...` (~l.289) | falls back to `engine/data/visionguard.db`, else `cfg.storage.database_url` minus `sqlite:///` | nothing — overlay's `database_url` is enough. Use an absolute path in the overlay |
| `engine/vg/api/app.py` | `_reraise_if_strict` | `VG_STRICT=1` makes any subsystem failure fatal | do not use VG_STRICT for the cloud profile |
| `engine/tools/create_user.py` | `getpass.getpass("  password  ")` (~l.94) | interactive only; args `--email --name --role --list` | add `--password-env NAME` (no echo, no confirm prompt) |
| `engine/tools/serve.py` | `uvicorn.run(...)` | `--host/--port` default from config; `psutil` clean-up | nothing; check it starts on 3.11 |
| `engine/tools/build_engines.py` | `--only` | builds `<stem>-<imgsz>.engine` next to the weights and confirms the file exists | bootstrap calls `--only` with the clip's models |
| `engine/requirements.txt` | `# --- config / util` | no `pynvml` / `nvidia-ml-py` listed | add `nvidia-ml-py` |
| `engine/engine.yaml` | `- id: cam-clip` | `source: file:engine/data/footage/walk-through_...mp4`, `fps: 5`, `features: [attendance, counting, intrusion, track, falls]`, `enabled: false` | **do not edit** — overlay + `VG_CAMERAS` |
| `engine/engine.yaml` | `zones:` | `zone-desk` is on **`cam-laptop`**, rect `[0.10, 0.18, 0.52, 0.62]` | overlay replaces `zones` with one zone on `cam-clip` |
| `web/src/services/api.ts` | `getSystemHealth` etc. | the only place the UI talks to the engine | add `getHealthz()` |
| `web/src/main.tsx` | `<BrowserRouter>` | path routes, not hash — hence the navigation fallback | — |

## 2. Copy, don't invent

- Env override pattern → `config.py::_apply_camera_override`
- `${VAR}` expansion → `config.py::_expand` (missing var with no default = `ConfigError`)
- Startup refusal wording → `dev_signin.py::role_from_env`
- Console notices → `ui.tsx` `DataNotice`; strings → `format.ts`
- Client tests → `conftest.py` `authed(app)`; overlay tests build a config with
  `vgconfig.load(path)` from a temp file
- Clip marks → `engine/data/footage/walk-through_cam-laptop_20260805-121705.json`
  (`duration_seconds 103.42`, `fps 15`, `marks[]` of `{kind: event|negative, at_seconds,
  frame}`, a `zone-desk` polygon in fractions)

## 3. Traps

- **CRLF**: `api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md` are CRLF. Use Edit, check
  `git diff --stat`.
- `pynvml` is installed on the laptop by hand, not by requirements.
- The footage clip and models are **not in git**; `pack.ps1` must not try to include them.
- The marks file names camera `cam-laptop` — it was recorded there. Its zone is the same
  rect area as `zone-desk`; marks `kind` meanings (`event` vs `negative`) are not
  documented in code — check `record.py` before relying on them beyond counting.
- `/healthz` is the **only** public endpoint by design (`deps.py` docstring). Anything added
  to it must say nothing about the site.
- A cookie set by the engine over plain HTTP behind the HTTPS tunnel: check `set_cookie`
  flags in `/auth/login` (`secure`, `samesite`) still work through
  `https://*.trycloudflare.com`.
- `tools/check_parity.py` compares web and mobile; a web-only banner may need an entry.
- One timing test flaked in the baseline run (see memory: `test_recording` / `test_lost_bag`)
  — rerun alone before calling it a regression.

## 4. Baseline

- `python -m pytest engine` → **2014 passed, 6 skipped** at `2c85ebe` (first run had 1
  timing flake; second run clean).
- New tests: `test_cloud_trial.py`, `test_measure_remote.py`; extended `test_encoder.py`
  (check the name — search for tests importing `vg.ingest.encoder`).

## 5. Still unknown

- Which GETs the console makes on first opening the Cameras page — read the network panel
  with `-Mock -DevSignIn admin`, then freeze the list in `measure_remote.py`.
- The width / fps hint a camera tile sends to `/snapshot` (read `CameraFrame.tsx`).
- Exact model names `cam-clip`'s features use (`person`, faces, re-ID, falls) — read the
  feature → model mapping before writing `bootstrap.sh --only`.
- Whether `/stream` is the MJPEG path name (`app.py` ~l.2176).
