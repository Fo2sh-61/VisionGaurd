# Tasks: Cloud trial

**Input**: `specs/021-cloud-trial/` — plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md, context.md (read context.md first).
**Tests**: required (spec Definition of Done). Test first for every engine change.
**Gates after each phase**: `python -m pytest engine` (≥ 2014 passed) · `cd web; npx tsc -b
--force` · `python -m pyflakes engine/vg engine/tools engine/tests`. Preserve CRLF/LF per file.

Stories: **US1** Linux readiness · **US2** cloud profile, one address, no dev sign-in ·
**US3** session end · **US4** measuring · **US5** notebook and bootstrap.

## Phase 1: Setup

- [x] T001 Create a Python 3.11 venv in the scratchpad (`py -3.11 -m venv`), install CPU torch + `engine/requirements.txt`; record the install output for STATUS.md (not committed)
- [x] T002 Run `python -m pytest engine` under that 3.11 venv; list every failure in `specs/021-cloud-trial/evidence/py311.md` before fixing anything

## Phase 2: Foundational

- [x] T003 Write failing tests for the overlay in `engine/tests/test_cloud_trial.py`: dict merge, lists replace, `${VAR}` expansion inside the overlay, missing overlay file → `ConfigError`, `profile` accepts only `""`/`cloud`, `api.console_dir` resolved against the repo
- [x] T004 Implement `VG_CONFIG_OVERLAY` merge, `profile`, and `ApiConfig.console_dir` in `engine/vg/config.py` (copy `_apply_camera_override` style; merge before `_expand`)
- [x] T005 Create `engine/profiles/cloud.yaml`: `profile: cloud`, `site_name`, `api.host 127.0.0.1`, `api.console_dir web/dist`, `storage.*` under `${VG_TRIAL_DIR}` (absolute DB path), `alerts.console_url ${VG_PUBLIC_URL}`, `zones` = one always-on zone on `cam-clip` with the clip's marks rect; add a test that loads `engine.yaml` + this overlay with `VG_CAMERAS=cam-clip` and checks the result

## Phase 3: US1 — the engine runs on Linux

**Independent test**: suite green on Python 3.11 and 3.14; a pipe-encoded clip probes as `h264`/`yuv420p`.

- [x] T006 [P] [US1] Tests in the existing encoder test file (search for `vg.ingest.encoder`): Linux order is `FFMPEG_H264, PIPE_X264, FFMPEG_MP4V` (monkeypatch `sys.platform`); Windows order unchanged; pipe writer writes 30 real frames and `ffprobe` reports `h264` + `yuv420p` (skip with a reason when `ffmpeg`/`ffprobe` are not on PATH)
- [x] T007 [US1] Add `PIPE_X264` and the pipe writer (`isOpened/write/release`, `-movflags +faststart`, stderr captured to the log on failure) in `engine/vg/ingest/encoder.py`
- [x] T008 [P] [US1] Add `nvidia-ml-py` to `engine/requirements.txt` with a one-line reason; note in the header comment that 3.11/3.12 are verified by T002
- [x] T009 [US1] Fix each 3.11 failure from T002 without changing 3.14 behaviour; re-run both suites; update `specs/021-cloud-trial/evidence/py311.md` with the final counts

## Phase 4: US2 — cloud profile, one address, no dev sign-in

**Independent test**: with the overlay, `/` and `/assets/*` load without signing in, a navigation to `/cameras` returns `index.html`, an API fetch to `/cameras` is still 401, and `VG_DEV_SIGNIN=admin` stops the engine at start.

- [x] T010 [P] [US2] Tests in `engine/tests/test_cloud_trial.py`: dev sign-in raises when `profile: cloud`; console served only when `console_dir` set (laptop config: `/` stays 401 as today); assets public; navigation fallback; `/docs` excluded; non-navigation API calls unchanged; `index.html` has `Cache-Control: no-cache`; missing `index.html` → API still runs and the reason is logged and in System Health
- [x] T011 [US2] Refuse dev sign-in for `profile: cloud` in `engine/vg/auth/dev_signin.py` (`role_from_env`), passing the profile from the lifespan in `engine/vg/api/app.py`
- [x] T012 [US2] Serve `console_dir` in `engine/vg/api/app.py` and make its paths public only when set, in `engine/vg/auth/deps.py` (keep `PUBLIC_PATHS`/`PUBLIC_PREFIXES` unchanged for the laptop)
- [x] T013 [P] [US2] Add `--password-env NAME` to `engine/tools/create_user.py` (no echo, no prompt, error if the variable is empty) with a test in `engine/tests/test_cloud_trial.py`
- [x] T014 [US2] Check the `/auth/login` cookie flags work over the https tunnel host (context.md trap); fix only if they would not, with a test

## Phase 5: US3 — the console says when the engine is going away

**Independent test**: with `VG_SESSION_ENDS_AT` set, `/healthz` carries `now/endsAt/stopping` and the console shows the banner; without it, `/healthz` has only `now` added and no banner.

- [x] T015 [P] [US3] Tests for `/healthz` per `contracts/healthz.md` in `engine/tests/test_cloud_trial.py` (unset, set, unparseable value ignored, `stopping` true after `SHUTTING_DOWN.set()`, still public and 200)
- [x] T016 [US3] Implement the `/healthz` fields in `engine/vg/api/app.py`
- [x] T017 [US3] Add `getHealthz()` to `web/src/services/api.ts` and the type to `web/src/types.ts`; banner strings (time left, stopping now, stopped) in `web/src/format.ts`
- [x] T018 [US3] Create `web/src/components/SessionNotice.tsx` (poll 30 s, 10 s inside 15 min, uses `DataNotice`) and mount it in the console layout; nothing renders when `endsAt` is absent; check `tools/check_parity.py`
- [x] T019 [US3] Look at it: `.\dev.ps1 up -Mock -DevSignIn admin` with `VG_SESSION_ENDS_AT` 20 min ahead; screenshot the banner; confirm no banner without it

## Phase 6: US4 — measuring from the PC

**Independent test**: a run against the local engine on the clip writes a JSON and a `comparison.md` with every row filled or marked failed.

- [x] T020 [US4] Freeze the page-load read list and the tile's `/snapshot` width/fps from the browser network panel (`-Mock -DevSignIn admin`) and `CameraFrame.tsx`; write them into `contracts/measure.md`
- [x] T021 [P] [US4] Tests in `engine/tests/test_measure_remote.py`: p50/p95, failures kept out of timings, clock offset picks the shortest round trip, MJPEG frame counting on a canned byte stream, `comparison.md` built from two JSONs with ± uncertainty columns
- [x] T022 [US4] Implement `engine/tools/measure_remote.py` per `contracts/measure.md` (standard library only; password from `VG_MEASURE_PASSWORD` or getpass)
- [x] T023 [US4] Run it against `.\dev.ps1 up -Clip -AllowSystemPython` for 6 minutes; commit `specs/021-cloud-trial/evidence/local-*.json` and `comparison.md` (cloud column empty, marked "not run yet")

## Phase 7: US5 — notebook and bootstrap

**Independent test (local part)**: `bash -n` passes on both scripts; `pack.ps1` produces a zip containing `web/dist/index.html` and no models or footage. The Kaggle run itself is Mohamed's.

- [x] T024 [P] [US5] Create `tools/cloud/pack.ps1`: refuse a dirty tree, `npm run build` in `web`, `git archive HEAD` + `web/dist` → `visionguard-trial.zip`; print its size and commit
- [x] T025 [US5] Read the feature → model mapping for `cam-clip`'s features and write the model list into `tools/cloud/bootstrap.sh` (check for each file; stop naming any missing one)
- [x] T026 [US5] Create `tools/cloud/bootstrap.sh` per plan F: timed steps, `set -euo pipefail`, pip without torch/torchvision, ffmpeg check, model links, `build_engines.py --only`, `benchmark.py` to the trial folder, `create_user.py --password-env`, pinned `cloudflared` with checksum, URL capture, engine start with overlay and `unset VG_DEV_SIGNIN`, `/healthz` wait, watchdog to `stop.sh`
- [x] T027 [US5] Create `tools/cloud/stop.sh`: SIGINT the engine, wait, `sqlite3` backup of the DB, copy logs/evidence/benchmark/summary to `/kaggle/working/trial-<date>/`; idempotent
- [x] T028 [US5] Create `cloud/visionguard_trial.ipynb`: cells for secret → env (Kaggle `UserSecretsClient`), run bootstrap in the background and tail its log, show URL + status, **Stop and save**
- [x] T029 [P] [US5] Test in `engine/tests/test_cloud_trial.py`: `bash -n` on both scripts (skip if no bash), the notebook is valid JSON and contains no secret value or key name other than `VG_ADMIN_PASSWORD`, `pack.ps1` excludes `models/` and `engine/data/`

## Phase 8: Polish

- [x] T030 Fill `specs/021-cloud-trial/quickstart.md` with anything the build changed
- [x] T031 Update `STATUS.md` (CRLF): what was verified on the laptop (3.11 + 3.14 suites, pipe H.264, console serving, banner, local measurement) and what was NOT (everything on Kaggle — list from plan "Not testable")
- [x] T032 All four gates, including `.\dev.ps1 up -Clip -AllowSystemPython` unchanged on Windows; `git diff --stat` for line-ending damage; commit on `021-cloud-trial`, nothing pushed
- [ ] T033 Hand Mohamed the Kaggle steps to run and the exact output to paste back

## Dependencies

- Phase 2 (overlay) blocks US2, US3's console test, US5.
- US1 independent of everything else.
- US3 and US4 independent of each other; US4's T020 needs the console running.
- US5 needs US2 (overlay, password-env) and US3 (`VG_SESSION_ENDS_AT`).

## Parallel

- T006, T008 alongside T003–T005.
- T010, T013, T015, T021 are separate test files/sections and can be written together.
- T024 alongside anything in US3/US4.

## Strategy

MVP = Phase 2 + US1 + US2: the engine runs on Linux and serves one safe address. Then US3
(banner), US4 (the local column of the table), US5 (the Kaggle run). The cloud column only
exists after Mohamed's first Kaggle session.
