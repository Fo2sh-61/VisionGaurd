# Implementation context: 022 console v2 shell

**Written by `/speckit-plan` on 10 Nov 2026, against commit `440f1aa` (branch `console-v2-jetson`).**

Read this **before** opening any source file, then open only the named anchors. If this
disagrees with the code, the code wins. Search for the symbol rather than trusting the line
numbers.

---

## 1. Anchors

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/auth/deps.py` | `ADMIN_PREFIXES` (~L83) | `("/enrolment", "/sources", "/users")`; every method is admin-only | add `"/attendance"`, `"/groups"`, `"/people"` |
| same | `ADMIN_WRITE_PREFIXES` (~L97) | `("/cameras", "/people", "/zones", "/vehicles", "/settings")`: reads open, writes admin-only | remove `"/people"` (moved up) |
| same | `OPERATOR_WRITE_PREFIXES` (~L128), `requires_admin` (~L135) | only `("/vehicles/alerts",)`. Order: admin prefix → safe method → operator allowance → admin-write | add an anchored pattern for `^/cameras/[^/]+/recording$`, checked where the operator allowance is |
| `engine/vg/auth/store.py` | `class UserStore`, `ROLES` (L38) | methods: create_user, users, count, set_disabled, authenticate, set_language, sessions. **No set_role**. `users()` does not select `last_login_at` | add `set_role(user_id, role)` with a `LastAdmin` error (count enabled admins inside the same lock/transaction); add `last_login_at` to `users()` |
| same | `user_for_token` | joins `app_user` and reads `role` **on every request** | nothing — a role change applies on the next request |
| `engine/vg/api/app.py` | `GET /users` (~L3325) | only route under /users | add `PATCH /users/{id}` (body `UserRoleUpdate`), 409 on `LastAdmin` |
| same | `GET /settings/school` (~L3744); alert settings routes ~L3770-3813 | no write for the profile | add `PATCH /settings/site` (body `SiteSettingsUpdate`) |
| same | `POST`/`DELETE /cameras/{id}/recording` (~L2277/2286) | take `actor` as a **query param, default "unknown"** | take the actor from the session user, as the attention ack does |
| same | `_mount` (~L1837) | API only; no static files | add `_serve_console(app, folder)` copied from `021-cloud-trial` (see §2), on when `VG_CONSOLE_DIR` is set |
| `engine/vg/api/store.py` | `MockStore._log` (L1357) | `_log(actor, action, subject, detail)` appends to the in-memory `self._audit` | call it first in the new endpoints' store methods |
| `engine/vg/api/live.py` | `self.config.hours` at ~2745, 3864, 3921, 4002, 4867 | frozen `HoursConfig` read directly | replace with `self.hours()` = config overlaid by `site_setting` |
| same | `users()` (~L2520) | builds `S.User(id, name, email, role)`, skips disabled users, never sets `last_active` | set `last_active` from `last_login_at` |
| same | `school_profile` (~L3866) | returns name, hours, term, cut-off, timezone | add `working_days` |
| same | `health()` (~L3538-3600), `_gpu_reading` (L97), weapons stage (~3740-3768) | GPU from pynvml (empty on Jetson); no RAM figure | add `psutil.virtual_memory()` used/total; skip the knife stage when no camera has `weapons` |
| same | `attention()` (~L2558) | weapon items appear only when the weapon rule is in-app **and** detections exist | nothing (no feature, so no items) |
| `engine/vg/config.py` | `HoursConfig` (L688-720) | `start, end, late_cutoff, term_from, term_to`; `parse` enforces start ≤ cut-off ≤ end | add `working_days: frozenset[int]` default `{5,6,0,1,2,3}` |
| same | `FEATURES` (L209-217) | includes `"weapons"` | leave it (engine stays); remove `weapons` from the cameras in `engine.yaml` |
| `engine/vg/alerts/events.py` | `SCHOOL_WEEKDAYS` (L51), `is_school_day` (L247) | hard-coded `{6,0,1,2,3}` (Sun–Thu) | take working days as a parameter |
| `engine/vg/alerts/service.py` | `self.hours` (L85), `_tick_report` (L555-595) | stored at construction | read hours through a callable from `LiveStore.hours` |
| `engine/vg/ask/menu.py` | `_run_weapons` (~L167), `AskQuery(id="weapons"…)` (~L375) | knives answered by Ask | remove; make attendance and people queries role-aware (answer IT with the fixed sentence) |
| `engine/vg/ingest/encoder.py` | `candidates()` (L69), `open_writer` (L105) | non-Windows: `FFMPEG_H264`, then `FFMPEG_MP4V` (which does not play in a browser) | add `PIPE_X264` from `021-cloud-trial` |
| `engine/vg/settings_store.py` | NEW | — | `site_setting` key/value table via `vg/db.py::connect` |

### Console (`*` = byte-shared with `mobile/src`; copy it over and keep `tools/check_parity.py` green)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/app/navigation.ts`* | `NAV` (L220-233), `HOME_ORDER` (L251), `NavSection` | sections ask/watch/manage; no item sets `role`; includes weapons, lost-items, track | new order and sections; `role: 'admin'` on attendance and people; drop weapons, lost-items, track |
| `web/src/app/routes.tsx` | `AppRoutes` (L62), `RequireRole` (L23) | `RequireRole` is used only for `users` | wrap attendance and people too; keep the weapons, lost-items and track routes (code stays) but unlinked |
| `web/src/app/AppShell.tsx` | L8-32 | Sidebar + TopBar + Outlet | wrap in `ToastProvider` |
| `web/src/components/Sidebar.tsx` | brand L69-77, nav L79, sign out L108 | "VisionGuard AI" hard-coded; no badges | "VisionGuard"; badges from `useNavBadges`; calm/attention card; sign out moves to the user menu |
| `web/src/components/TopBar.tsx` | L12-60 | date, cameras up, `<AlertBell/>`, static name + avatar | user menu: health, settings, accounts (admin), language, theme, sign out |
| `web/src/components/AlertBell.tsx` | `AlertBell` L63 | opening the bell marks all seen (client side) | restyle only |
| `web/src/components/ui.tsx` | exports | no Toast | add `Toast` |
| `web/src/components/CameraSources.tsx` | `FEATURES` L135-153 | 7 entries incl. `weapons` ("Check for knives") | remove weapons; relabel intrusion "Restricted zones" |
| `web/src/components/AlertSettings.tsx` | rules map L205 | rows come from the engine's `rules` | relabel intrusion; the engine stops sending `weapon` |
| `web/src/pages/Users.tsx` | row "Edit" L61 | **dead button**, hard-coded "Edit" | role `Select` → `PATCH /users/{id}` → toast |
| `web/src/pages/Settings.tsx` | profile card L115-196, zones card L200-211 | **edits never save** (local state only); hard-coded English labels | save through `PATCH /settings/site`; add working days; "Term" → Working calendar; delete the zones card; move strings to i18n |
| `web/src/pages/Home.tsx` | sections L56-206 | no camera strip; tools grid from `HOME_ORDER` | add a 4-camera strip `CameraFrame … detections={false}`; three feature cards |
| `web/src/pages/Counting.tsx` | `WINDOWS` L13, overlap note L341-345 | hard-coded English in several places | i18n; level from `format.ts` |
| `web/src/services/api.ts`* | `getCount` (L260), `getSchoolProfile` (L1390), `register` (L1441) | the % sub text is hard-coded English | add `updateUserRole`, `updateSiteSettings`; move strings out |
| `web/src/styles/tokens.css`* | `:root` L10-42, `body.dark` L44-66 | `--det-*` and `--radius-*` already present | add `--chrome`, `--frame`; set the detection colours to the design's |
| `web/src/styles/app.css` | L34-40 (Arabic font), L384 | only 2 `[dir=rtl]` rules; Noto Sans Arabic **not loaded** | one global `[dir=rtl]` letter-spacing reset; shell CSS in logical properties |
| `web/index.html` | L7-12 | loads Albert Sans only | add Noto Sans Arabic |
| `web/src/i18n/{keys,en,ar.draft}.ts`* | flat dot-keys; `en` is a `Record` (a missing key fails the build) | — | add only 022's strings |

## 2. Things to copy, not invent

- Serving the built console from the engine: copy `021-cloud-trial:engine/vg/api/app.py::_serve_console`, its call site (grep `_serve_console(`) and `test_cloud_trial.py`'s serving tests.
- H.264 clips on Linux: copy `021-cloud-trial:engine/vg/ingest/encoder.py` (`PIPE_X264`, `_ffmpeg_candidates`, `_ffmpeg_with_x264`) and the matching `recorder.py` pipe handling if the diff has any.
- Linux process handling (pid files, SIGINT, then kill): `021-cloud-trial:tools/cloud/stop.sh::stop_pid`.
- A store on SQLite: `engine/vg/alerts/store.py` (`__init__` uses `db.connect(self.path)`).
- Audit-first endpoints: `live.py::delete_pass` (~L1828), which writes the audit entry first.
- Test clients: `authed(app, role=…)`, `sign_in` and `bare_live_store` in `engine/tests/conftest.py`; `test_authorisation.py` for path rules.
- Admin-only hint in the UI: `AlertSettings.tsx:122` (`useAccount().role === 'admin'`) and the `settings.alerts.adminOnly` key.

## 3. Traps

- **Parity.** `navigation.ts`, `api.ts`, `wire.ts`, `format.ts`, `content.ts`, `tokens.css`, the i18n files and the contexts are byte-copied to `mobile/src`. Edit, then copy, then run `check_parity.py`. Removing weapons, lost-items and track from `NAV` removes them from the phone too (intended); mobile `tsc` will catch dangling imports.
- **CRLF.** `api/*.py`, `services/*.ts` and `types.ts` are CRLF. Edit bytes, then check `git diff --stat`.
- **The /people move** will 403 any IT page that still reads it. Grep `api.ts` for `/people` and `/groups` callers before moving it.
- **Working days default changes Sun–Thu to Sat–Thu.** Tests pinning `SCHOOL_WEEKDAYS` will fail by design; update them to read the default.
- **`CountResult.deduplicated` defaults to True in the schema**; `LiveStore.count` sets False. Keep it False, or the console prints "counted once" (a rule-5 breach).
- **Chromium on Ubuntu is a snap.** `--user-data-dir` must be under `$HOME`, or the snap refuses it. Without a dedicated profile the command returns at once and the launcher would stop the engine.
- **pynvml does not exist on the Jetson**, so the GPU fields are empty there. That is honest; do not fake them.
- **The Arabic draft is dev-only.** A production build (the Jetson) shows English until `ar.ts` is approved.
- **The SSH Jetson is a test bench.** Install nothing of VisionGuard on it. Launcher checks wait for the new board.
- `web/node_modules` is absent in a worktree. Junction the main checkout's copy and remove it afterwards (see memory: worktrees lack node_modules).

## 4. Baseline

- `python -m pytest engine`: **1940 passed, 14 skipped** at `440f1aa` (4 min 14 s on the Windows laptop).
- New test file: `engine/tests/test_shell_v2.py` (path rules, set_role and last admin, settings save, hours overlay, working days and the report, knife absent from health/alerts/ask, memory reading).
- Known flaky under load: `test_recording` forgotten-recording and `test_lost_bag` interest lapse. Rerun those alone first.

## 5. Still unknown

- Which SQLite file `site_setting` should live in. Use the one `AlertsStore` uses unless `vg/db.py` says otherwise.
- Whether the new Jetson ships the same JetPack/Python as the test bench.
- Whether `zenity` is present on the Jetson desktop image. Fall back to `notify-send`, then to terminal text.
- Whether any phone page reads `/people` or `/groups` as IT.
