# Research: 022 console v2 shell

Every decision below was checked against the code at commit `440f1aa`.

## R1 — Roles by path, not by response

- **Decision**: add `/attendance` and `/groups` to `ADMIN_PREFIXES`, move `/people` there from
  `ADMIN_WRITE_PREFIXES`, and allow `POST|DELETE /cameras/{id}/recording` for IT with one
  pattern next to `OPERATOR_WRITE_PREFIXES` (today that list is only `("/vehicles/alerts",)`).
- **Rationale**: AGENTS.md: permissions are decided by path, never per endpoint. A prefix
  cannot express `/cameras/*/recording` without also opening camera edits, hence one
  anchored pattern.
- **Alternatives**: moving recording to a new `/recordings/{camera}` path (rejected: changes
  the wire for web and phone); a role check inside the handler (rejected: the pattern AGENTS.md
  forbids).
- **Knock-on**: any page an IT user still opens that reads `/people` or `/groups` will now get
  403. Known readers are Track (leaves the nav) and Ask. `implement` must grep `api.ts` for
  `/people` and `/groups` callers and confirm none is on an IT page.

## R2 — Role change

- **Decision**: `UserStore.set_role(user_id, role)` runs in one transaction. It counts enabled
  admins and refuses with a `LastAdmin` error if the change would leave none. Exposed as
  `PATCH /users/{id}` with `{role}`; `/users` is already admin-only. `_log(actor, "user.role",
  email, "it → admin")` is written before the call.
- **Rationale**: `user_for_token` re-reads `role` from `app_user` on every request, so the
  person's next request uses the new role. No session work is needed.
- **Last active**: there is only `last_login_at` (written on sign-in). Show it as "Last signed
  in". Tracking every request would mean a write per request for a label; rejected.

## R3 — Settings that actually save

- **Finding**: `Settings.tsx` says "edits save on their own", but there is no write call and
  no endpoint. This is a rule-4 breach today.
- **Decision**: new `vg/settings_store.py`: one table `site_setting(key TEXT PRIMARY KEY,
  value TEXT, updated_at, updated_by)`, opened with `vg/db.py::connect` like
  `alerts/store.py`. `LiveStore.hours()` returns `dataclasses.replace(config.hours, **saved)`.
  The database wins and `engine.yaml` stays the seed (settled rule). Reads that change:
  `live.py` (5 places use `self.config.hours`) and `AlertService.hours` (given a callable).
- **Working days**: a new key `working_days` (Python weekday ints), default Saturday–Thursday
  `{5,6,0,1,2,3}` (owner, 10 Nov 2026). It replaces the hard-coded `SCHOOL_WEEKDAYS`
  `{6,0,1,2,3}` in `alerts/events.py`. Tests that pin Sunday–Thursday change with it.
- **Term → working calendar**: label only. The wire keeps `term_from/term_to`, which avoids
  touching six readers and the phone.
- **Endpoint**: `PATCH /settings/site`. `/settings` is already admin-write.
  `GET /settings/school` stays for the phone and gains `working_days`.

## R4 — Knife detection out of v2

- **Decision**: the console drops `weapons` from the watch-for list, `NAV`, `HOME_ORDER`, the
  alert rows and `CAPABILITIES`. The engine: `ask/menu.py` drops the weapons query; `health()`
  omits the knife stage when no camera has `weapons`; alert settings stop listing the
  `weapon` rule in that case. Engine code otherwise stays (spec: "engine behaviour untouched").
- **Rationale**: rule 10 holds because nothing is detected. Leaving the stage visible as "not
  running" would contradict "nothing related appears".

## R5 — Toasts, badges, user menu

- **Toast**: none exists today. Add `app/ToastContext.tsx` + `Toast` in `ui.tsx`, used only in
  the console. They are new files, so the phone parity list is unaffected.
- **Badges**: a single `useNavBadges` hook polls every 15 s, the same cadence as
  `useAttention`. Attendance comes from the attendance summary (admin only); Car plates comes
  from `getVehicleAlerts`. A failed call shows no badge, never 0.
- **Mark all read**: already exists client-side (`useAlertFeed.markSeen`, localStorage); no
  server change.
- **Language and theme**: today they live only in Settings (and on Login). The user menu
  reuses `useLanguage().setLanguage` and `useTheme().toggle`.

## R6 — Population levels

- **Decision**: compute the level in `format.ts` from `count / capacity`: 0 people is Empty,
  under 70% Quiet, under 90% Busy, up to 100% Near capacity, over 100% Over capacity. With
  capacity 0 there is no level. This uses the engine's existing 0.7 / 0.9 thresholds
  (`_fill_severity`) and adds "Over capacity" above 100%.
- Range labels stay the engine's three windows. "This week by day" covers the last 7 days.

## R7 — The Jetson launcher

- **Decision**: `launch.sh [--mock] [--clip] [--no-browser]`:
  1. Use `.venv/bin/python` if present, else `python3`.
  2. If `web/dist/index.html` is missing, say so plainly. The console is built on the Windows
     PC with `npm run build` and copied, so the Jetson needs no Node.js.
  3. Start the engine with `setpriv --pdeathsig KILL python engine/tools/serve.py`, with
     `VG_CONSOLE_DIR=web/dist` (plus `VG_MOCK=1` or `VG_CAMERAS=cam-clip`).
  4. Poll `http://127.0.0.1:8000/healthz` for up to 90 s.
  5. Open `chromium-browser --app=http://localhost:8000 --user-data-dir=~/.config/visionguard-window`
     in the foreground.
  6. When that window closes, `trap` sends SIGINT to the engine, then SIGKILL after 10 s.
     Failures appear in a `zenity --error` box.
- **Why it matches the Windows job object**: `--pdeathsig` kills the engine even if the
  launcher itself is killed. The dedicated `--user-data-dir` makes Chromium a separate
  process that exits when its window closes. Without it, Chromium hands the URL to a running
  browser and returns at once.
- **Serving**: copy `_serve_console` from `021-cloud-trial:engine/vg/api/app.py`, together
  with its wiring and tests. One origin means one port, no Vite and no CORS on the Jetson.
- **Clips**: copy `PIPE_X264` and `_ffmpeg_with_x264` from
  `021-cloud-trial:engine/vg/ingest/encoder.py`. The Jetson has no hardware encoder; `apt`'s
  ffmpeg has libx264.
- **Shortcut**: `tools/install-shortcut.sh` writes `~/.local/share/applications/visionguard.desktop`
  and a Desktop copy. The icon is `design/console-v2/assets/visionguard.png`, copied to `assets/`.
- **Alternatives rejected**: systemd service (it outlives the window, so the opposite of the
  promise); Electron/Tauri wrapper (a new toolchain on an Arm board for a window frame); Vite
  on the Jetson (needs Node.js and two processes).

## R8 — Memory on System Health

- **Finding**: GPU memory comes from `pynvml`, which does not exist on Jetson (no NVML), so
  those fields come back empty there. System RAM is not reported anywhere.
- **Decision**: add `memory_used_mb` and `memory_total_mb` from `psutil.virtual_memory()`. The
  console labels it "Memory (shared by processor and graphics)" when the GPU reading is
  missing and the machine is aarch64. This is one reading, not a new subsystem.

## R9 — Arabic in a production build (for the owner)

- **Finding**: `ar.ts` (approved Arabic) is empty, and `ar.draft.ts` is shown only in
  development builds. So the Jetson, which runs a production build, shows **English
  everywhere** until the Arabic is approved.
- **Decision**: unchanged, as FR-127 requires. Raised with the owner so it is not a surprise
  at the compound.
