---
description: "Tasks for 022 console v2 shell"
---

# Tasks: Console v2 — shell, roles, Home, Population, Health, Settings, Jetson start

**Input**: `specs/022-console-v2-shell/` (plan.md, research.md, data-model.md, contracts/api.md, context.md)
**Tests**: required. The constitution asks for test-first business rules, and AGENTS.md wants every fix shipped with its regression test. Engine tests go in `engine/tests/test_shell_v2.py` unless a task says otherwise.
**Before any task**: read `context.md`. Files marked * are byte-shared with `mobile/src`: copy them after editing.

Stories (from the spec and plan):
- **US1** Roles and accounts (FR 110–115)
- **US2** Settings that really save, plus working days (FR 123–125)
- **US3** The shell: nav, top bar, toast, knife detection gone (FR 101–109, 122, 124, 126–129)
- **US4** Home and Population (FR 116–121)
- **US5** The Jetson start: serving, clips, memory, launcher (FR 130–135)

## Phase 1: Setup

- [X] T001 Junction `web/node_modules` and `mobile/node_modules` from the main checkout into this worktree (memory: worktrees lack node_modules), then run `npx.cmd tsc -b --force` in `web/` and `mobile/` to confirm a clean start
- [X] T002 Create `engine/tests/test_shell_v2.py` with the imports and fixtures from `engine/tests/conftest.py` (`authed`, `sign_in`, `bare_live_store`)

## Phase 2: Foundational

- [X] T003 Add a `Toast` component to `web/src/components/ui.tsx`, and add `web/src/app/ToastContext.tsx` (`ToastProvider`, `useToast().show(text, tone)`, auto-hide after 4 s, `role="status"`). Wrap the shell in `web/src/app/AppShell.tsx`
- [X] T004 [P] In `web/src/styles/tokens.css`*, add `--chrome` and `--frame`, and set `--det-green #3ec776`, `--det-red #e5564a` and `--det-amber #dfa23f`. In `web/src/styles/app.css`, add the global `[dir='rtl'] * { letter-spacing: 0 }`. In `web/index.html`, load Noto Sans Arabic. Copy `tokens.css` to `mobile/src/styles/`

## Phase 3: US1 — roles and accounts

**Independent test**: an IT session gets 403 on `/attendance`, `/groups` and `/people`, can POST recording, and Accounts changes a role with the audit entry written first.

- [X] T005 [US1] Tests in `test_shell_v2.py`:
  - `requires_admin` is true for GET `/attendance`, `/attendance/export`, `/groups`, `/groups/x`, `/people`, `/people/x/history`.
  - `requires_admin` is false for POST and DELETE `/cameras/cam-1/recording`.
  - `requires_admin` is still true for PATCH `/cameras/cam-1` and every `/sources` path.
- [X] T006 [US1] In `engine/vg/auth/deps.py`:
  - Add `/attendance`, `/groups` and `/people` to `ADMIN_PREFIXES`, and remove `/people` from `ADMIN_WRITE_PREFIXES`.
  - Add `OPERATOR_WRITE_PATTERNS = (re.compile(r"^/cameras/[^/]+/recording/?$"),)` and check it in `requires_admin` right after `OPERATOR_WRITE_PREFIXES`.
  - Update the comment above `/people` to explain the reversal (spec 022 P14-FR-110).
- [X] T007 [US1] Grep `web/src/services/api.ts` and `mobile/src` for `/people` and `/groups` callers, and confirm none runs on a page an IT account can open. Record the finding in the commit message
- [X] T008 [US1] In `engine/vg/api/app.py`, make the recording POST and DELETE take the actor from the session user, not the `actor` query parameter. Fix callers in `api.ts`* if they pass it. Add a test that the audit actor is the account name
- [X] T009 [US1] Tests for `UserStore.set_role`:
  - promoting works;
  - demoting the last enabled admin raises `LastAdmin`;
  - a disabled admin does not count;
  - an unknown role raises `ValueError`;
  - after `set_role`, `user_for_token` returns the new role.
- [X] T010 [US1] In `engine/vg/auth/store.py`, implement `LastAdmin(Exception)` and `UserStore.set_role(user_id, role)`. Count and update inside one `with self._lock`. Also select `last_login_at` in `users()` and add it to `User` as an optional field
- [X] T011 [US1] Tests for `PATCH /users/{id}`:
  - admin gets 200, and the audit entry `user.role` exists before the change (assert the order through the store);
  - IT gets 403;
  - demoting the last admin gets 409 with a reason;
  - an unknown id gets 404.
  Also: `GET /users` now includes `lastActive`.
- [X] T012 [US1] Implement the user role change:
  - `UserRoleUpdate` in `engine/vg/api/schemas.py` (CRLF).
  - `LiveStore.set_user_role(actor, user_id, role)` in `engine/vg/api/live.py`, calling `_log` first.
  - The route in `app.py`.
  - In `LiveStore.users()`, set `last_active` from `last_login_at` through `_instant`.
- [X] T013 [US1] In `engine/vg/ask/menu.py`, make the attendance and people queries answer IT with the note "Attendance and people records are open to administrators only." (add a note code in `api/notes.py`, mirrored in `web/src/i18n/keys.ts`*/`en.ts`*/`ar.draft.ts`*). Test with an IT session
- [X] T014 [US1] In `web/src/pages/Users.tsx`, replace the dead "Edit" with a role `Select`, calling `updateUserRole` (new in `api.ts`*). Show a toast on success and the reason inline on failure. Rename the "Last active" label to "Last signed in" (i18n). Title it "Accounts"
- [X] T015 [US1] In `web/src/services/content.ts`*, update `CAPABILITIES` to 022's table. Drop `reviewWeapon` and `track`; add record, see plates, mark Gone (IT yes); cameras setup (IT no); zones and stations (IT no). Add the i18n keys

## Phase 4: US2 — settings that save, and working days

**Independent test**: change the hours and untick Friday, restart the engine, and the values are still there. The noon report skips Friday.

- [X] T016 [US2] Tests in `test_shell_v2.py`:
  - `SiteSettingsStore` round-trips each key.
  - `LiveStore.hours()` overlays the saved values on the yaml seed.
  - An invalid cut-off is refused.
  - The working days default is `{5,6,0,1,2,3}`.
  - `events.is_school_day` uses the working days passed in.
  - `PATCH /settings/site`: admin 200 with the audit entry `settings.site` written first, IT 403, invalid 422.
  - `GET /settings/school` includes `workingDays`.
- [X] T017 [US2] Create `engine/vg/settings_store.py`: `SiteSettingsStore(database)` with the `site_setting` table, `get_all()` and `save(values, actor)`, opened with `vg/db.py::connect` like `engine/vg/alerts/store.py`. Wire it up where `AlertsStore` is constructed in `app.py`, using the same database file
- [X] T018 [US2] In `engine/vg/config.py` `HoursConfig`, add `working_days: frozenset[int]` (default Saturday–Thursday) and parse an optional `working_days` list from yaml
- [X] T019 [US2] In `engine/vg/api/live.py`, add `hours()`, which returns `dataclasses.replace(self.config.hours, **saved)` with validation. Replace the five `self.config.hours` reads. Add `save_site_settings(actor, update)` (calls `_log` first). Add `working_days` to `school_profile`
- [X] T020 [US2] In `engine/vg/alerts/events.py`, replace `SCHOOL_WEEKDAYS` with a `working_days` parameter on `is_school_day`. In `engine/vg/alerts/service.py`, let `AlertService` take `hours` as a callable and update the call in `app.py` (~L950). Fix the existing tests that pinned Sunday–Thursday
- [X] T021 [US2] Add `SiteSettingsUpdate` and `SchoolProfile.working_days` to `engine/vg/api/schemas.py`, and the `PATCH /settings/site` route to `app.py`. Mirror them in `web/src/services/wire.ts`* and `api.ts`* (`updateSiteSettings`, `workingDays`)
- [X] T022 [US2] Update `web/src/pages/Settings.tsx`:
  - Profile edits really save (auto-save on Done), with a toast or the inline reason.
  - Add a working days chip row.
  - Rename Term to "Working calendar" and the school wording to "site".
  - Show read-only notes for IT.
  - Delete the Detection zones card.
  - Move every hard-coded string to i18n.
- [X] T023 [US2] In `web/src/components/AlertSettings.tsx`, add a toast on rule and recipient saves. Read-only wording for IT: recipients show as Receiving / Switched off

## Phase 5: US3 — the shell

**Independent test**: admin and IT each see exactly the 022 navigation. Nothing about knives appears anywhere. Arabic flips the layout.

- [X] T024 [US3] Tests in `test_shell_v2.py`:
  - With no camera running `weapons`: `health()` has no `weapons` stage, `GET /settings/alerts` has no `weapon` rule, and Ask has no knives query.
  - With a camera running `weapons` (test config), they appear as before.
- [X] T025 [US3] Implement the T024 behaviour in `engine/vg/api/live.py` (health, alert settings) and `engine/vg/ask/menu.py`. Remove `weapons` from every camera's `features` in `engine/engine.yaml`
- [X] T026 [US3] Rewrite `NAV` in `web/src/app/navigation.ts`*:
  - Order: Home, Attendance (admin), People (admin), Population, Car plates, Restricted zones; then a SYSTEM section with Health and Settings.
  - Drop weapons, lost-items and track.
  - New `HOME_ORDER`.
  - Copy the file to mobile, fix the mobile pages that referenced the removed ids, and confirm with mobile `tsc`.
- [X] T027 [US3] Add a `useNavBadges` hook in `web/src/app/useNavBadges.ts`. It polls every 15 s:
  - attendance not arrived (admin only);
  - open vehicle alerts.
  It returns `undefined` on failure, never 0.
- [X] T028 [US3] Update `web/src/components/Sidebar.tsx`:
  - Brand reads "VisionGuard".
  - Sections from the new `NAV`, with badges.
  - A bottom card reading "Site is calm" or "N things need attention", from `useAttention`.
  - Remove the sign-out button.
  - Use logical CSS.
- [X] T029 [US3] Update `web/src/components/TopBar.tsx`:
  - Date, then "N of M cameras up" (a link to `/system`), then the bell, then the user menu button.
  - The menu holds Health, Settings, Accounts (admin), the language chips, a theme toggle and Sign out.
  - In RTL, the order follows FR-107 through CSS `order`.
  - Close the menu on Escape and on an outside click, like `AlertBell`.
- [X] T030 [US3] In `web/src/app/routes.tsx`, wrap attendance, people and people/* in `RequireRole role="admin"`. Leave the weapons, lost-items and track routes in place but unlinked
- [X] T031 [US3] In `web/src/components/CameraSources.tsx` `FEATURES`, remove `weapons` and relabel `intrusion` as "Restricted zones" (`source.feature.intrusion`). In `AlertSettings.tsx`, relabel the intrusion row "Restricted area entered"
- [X] T032 [US3] Toasts. Call `useToast()` on success in:
  - acknowledge on Home;
  - dismissing a gate alert in `web/src/pages/VehicleGate.tsx`;
  - Accounts, Settings and alert settings (from T014, T022, T023).
  Failures keep their inline notice.
- [X] T033 [US3] In `web/src/pages/Login.tsx`, restyle to the v2 tokens and brand "VisionGuard". The behaviour is unchanged

## Phase 6: US4 — Home and Population

- [X] T034 [US4] In `web/src/pages/Home.tsx`:
  - Add three feature cards: Attendance (admin), Population (sum of areas right now), and Car plates (the last plate, through `components/Plate.tsx`).
  - Each card shows "unavailable" when its call fails.
  - Add a 4-camera strip: cameras that are up, `CameraFrame … live detections={false}`, and "All cameras →" to `/system` until spec 027 adds `/cameras`.
  - Omit the attendance pieces for IT.
- [X] T035 [US4] Add `populationLevel(count, capacity)` to `web/src/services/format.ts`*: Empty / Quiet / Busy / Near capacity / Over capacity, and `null` when capacity is 0. Add a unit check through `web/scripts/check-format.ts` if that script exists, else a small TS assert script
- [X] T036 [US4] In `web/src/pages/Counting.tsx` and `api.ts`* `getCount`:
  - Move the hard-coded English to i18n.
  - Show the level chip and capacity bar only with a capacity.
  - Keep the upper-bound note.
  - Rename the page title to "Population".

## Phase 7: US5 — the Jetson start

- [X] T037 [US5] Copy the console serving from `021-cloud-trial`:
  - `_serve_console` and its call into `engine/vg/api/app.py`, gated by the `VG_CONSOLE_DIR` env var.
  - Its tests, from `021-cloud-trial:engine/tests/test_cloud_trial.py`, into `test_shell_v2.py`.
  - Default off: the Windows dev setup is unchanged.
- [X] T038 [US5] Copy `PIPE_X264`, `_ffmpeg_candidates` and `_ffmpeg_with_x264` from `021-cloud-trial:engine/vg/ingest/encoder.py`, plus any matching `recorder.py` pipe handling and their tests. Windows keeps Media Foundation first
- [X] T039 [US5] Add `memory_used_mb` and `memory_total_mb` to `SystemHealth` in `engine/vg/api/schemas.py` and `live.py` `health()`, using `psutil.virtual_memory()`. Test that they are ints. Show them in `web/src/pages/SystemHealth.tsx`, labelled shared when there is no GPU reading
- [X] T040 [US5] Create `launch.sh` at the repo root:
  - Flags `--mock`, `--clip` and `--no-browser`.
  - Use the venv, else `python3`.
  - Check `web/dist`.
  - Start the engine with `setpriv --pdeathsig KILL … engine/tools/serve.py` and `VG_CONSOLE_DIR=web/dist`.
  - Wait for `/healthz` for up to 90 s.
  - Open `chromium-browser --app=http://localhost:8000 --user-data-dir=$HOME/.config/visionguard-window`.
  - On exit, a trap sends SIGINT, then SIGKILL after 10 s.
  - Show errors with `zenity`, else `notify-send`, else echo.
  - Write the file with LF line endings and the executable bit (`git update-index --chmod=+x`).
- [X] T041 [US5] Create `tools/install-shortcut.sh`. It writes `~/.local/share/applications/visionguard.desktop` and a Desktop copy marked trusted (`gio set … metadata::trusted true`). It takes `--remove`. Copy the icon `design/console-v2/assets/visionguard.png` to `assets/visionguard.png`
- [X] T042 [US5] Add a "Starting on Ubuntu (Jetson)" section to `AGENTS.md` "How to work". Say that the SSH Jetson is a test bench only

## Phase 8: Polish and checks

- [X] T043 Move every new string into `web/src/i18n/keys.ts`*/`en.ts`*/`ar.draft.ts`* and copy them to mobile. Run `python tools/check_parity.py` and `python tools/check_parity.py --no-fixtures`
- [X] T044 Run `python -m pytest engine`. The result must be ≥ 1940 passed, plus the new tests. Rerun known flaky tests alone first
- [X] T045 Run `python -m pyflakes engine/vg engine/tools engine/tests`, then `npx.cmd tsc -b --force` in `web` and `mobile`. Check `git diff --stat` for whole-file line-ending churn
- [X] T046 Run `.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin` and then `-DevSignIn it` (from the **main checkout's** launch config only if it is free; otherwise run this worktree's `dev.ps1` directly). Walk quickstart steps 1–7
- [X] T047 Update `STATUS.md`: roles, Settings saving and knife detection gone. List the Jetson items as waiting for the new board

## Dependencies

- Phase 1 → Phase 2 → stories. US1 and US2 can run in parallel (different engine files except `app.py` and `schemas.py`: do their edits one at a time). US3 needs T003 (toast) and T026 before T028. US4 needs US3's shell. US5 is independent of the others except `app.py`.
- Within each story, the tests come before the implementation.

## Implementation strategy

MVP = US1 + US2: the engine rules and the two honesty fixes. They are small and testable without the UI. Then US3 for the visible redesign, US4, and US5 last, because its checks wait for the new Jetson anyway.

## Done, 10 Nov 2026

All tasks are ticked. Built by two parallel lanes of Sonnet agents (engine, console), then reviewed and fixed by the main Opus session. Not covered:
- **T040/T041 (`launch.sh`, the shortcut)** are written and checked for bash syntax only. They have **not been run on a Jetson**, because the SSH Jetson is a test bench. They wait for the new board, as do quickstart steps 8–11.
- **T046** was checked by eye in mock mode as admin and as IT. That covered the shell, Arabic, the user menu, Settings and Accounts, plus the 403s for IT. The recorded clip was not run, because the worktree has no models or footage.

Review additions beyond the task list:
- `/track` and `/tracking` are now admin-only (they returned names to IT).
- Recording is audited before it starts and before it stops.
- People's "Track today" button is removed.
- The phone hides Attendance and People for IT (routes, tab, Home figure).
- The suggestion chips are v2 questions.
- The greeting is neutral.
- The date follows the language.
- The knife row is filtered in both apps.
- "student records" now reads "people records".
