# Implementation context: 023 console v2 people

**Written by `/speckit-plan` on 10 Nov 2026, against commit `5ea8e67` (worktree `console-v2-plans`).**

Read this **before** opening any source file, then open only the named anchors. If this disagrees with the code, the code wins.
Search for the symbol, not the line. **Depends on 022**: `LiveStore.hours()` (config overlaid by `site_setting`, with `working_days`), the admin-only path rules, `useNavBadges`, toasts. Do not start 023's engine work until 022's `hours()` exists, or stub `hours()` to `self.config.hours` and swap.

---

## 1. Anchors

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/events/attendance.py` | NEW | : | `AttendanceLedger(database)`: copy `sightings.py` (`db.connect`, `RLock`, `SCHEMA`, `close`). Methods: `excuse(person_id, date, by, at)`, `excused_on(date) -> set[str]`, `note_removed(person, removed_at, by)`, `removed_expected_on(date) -> list`, `note_hours(hours, today)`, `hours_on(date)` |
| `engine/vg/events/sightings.py` | `DailyRegister` | `present` = status `!= "absent"`; `absent` = status `== "absent"`; `entry(pid)` is a linear scan | `present` = `on_time`/`late`; add `excused`; `expected` unchanged (all entries) |
| same | `SightingStore.register` | `(on, expected, cutoff, day_start, day_end)`; absent when no row | add `excused: Collection[str] = ()`: absent + id in set -> status `excused` |
| same | `days_recorded`, `history`, `_lateness` | `_lateness(first, cutoff) -> (status, minutes)` | add `has_day(on)` (`SELECT 1 FROM sighting WHERE local_date=? LIMIT 1`) and `person_days(pid, dates)` (one query on `idx_sighting_person_date`, bounds in Python like `history`). Reuse `_lateness` |
| `engine/vg/api/live.py` | `LiveStore.__init__` (L192), `self.sightings` (L225) | takes `gallery`, `sightings` as args | build `self.ledger = AttendanceLedger(sightings.path) if sightings else None`; close it with the rest |
| same | `_register(on, group)` (~L3906) | expected = `gallery.people()` with `photo_on_file`, optionally one group; hours from `self.config.hours` | expected from new `_expected_on(on, wanted)`; hours from `hours_on(on)` (calls `ledger.note_hours` first); pass `excused=ledger.excused_on(on)`; memoise past dates (R6) |
| same | `attendance` (~L3985) | group mode builds `AttendanceRecord` from `register.entries`; `match=FACE if status != "absent"`; metrics Here/Late/Absent/Cameras; `cameras=self.live_cameras()`; person mode builds `days` | group mode: add `group`, `last_seen_at` to records; `excused`, `recorded`, `recognition_elsewhere`; `match` FACE only for on_time/late; metrics add Excused; `cameras` = doorway cameras. Person mode **untouched** except `self.config.hours` -> `self.hours()` (022 does it) |
| same | `_empty_attendance` (~L3944) | all-zero result, `expected 0` | fine as is; add the three new fields defaults |
| same | `people` (~L3776) | `status` from `register.entry(person.id)` | no change once `_register` yields `excused` |
| same | `remove_person` (~L3827) | `_log(...)` then `gallery.remove_person` | after `_log`, before delete: `ledger.note_removed(person, now, actor)` |
| same | `groups` (~L4763) | `here()` counts `status != "absent"` | count on_time/late; add `attendance_30d`, `recorded_days` per group via one 30-day pass (R6) |
| same | `group` (~L4805) | roster = `attendance("group", name, today).records` | none |
| same | `camera_view` (~L368), `_face_boxes` (~L641) | no offline reason; unrecognised face `severity=INFO` | `offline_reason` from `worker.health.status` (`auth`, `down`) or `disabled`; unrecognised -> `severity=WARN` |
| same | `_attendance_counts` (~L2901) | reads `result.absent` for the noon report | unchanged; its test expects the old meaning of `absent`: update |
| same | NEW `week(person_id, date)`, `excuse(person_id, date, actor)` | : | per research R4, R5. `excuse` order: validate -> `_log` -> `ledger.excuse`. Raise `SubsystemUnavailable` when `ledger is None` |
| `engine/vg/api/store.py` | `MockStore._log` (L1357); `attendance`, `groups` fixtures | in-memory audit | add `note_enrolment(actor, name, group, photos)` (calls `_log`), `week`, `excuse` stubs so `-Mock` still runs (rule 4: stubs return empty/raise `SubsystemUnavailable`, never invented rows) |
| `engine/vg/api/schemas.py` | `AttendanceStatus` (L132), `AttendanceRecord` (L494), `AttendanceResult` (L518), `GroupSummary` (L1193), `EnrolmentPhoto` (L1825), `CameraView` (L238) | see contracts | add the fields in `contracts/api.md`; new `ExcuseRequest(Wire)`. `Fraction` for `attendance_30d` |
| `engine/vg/api/app.py` | `get_attendance` (L2418), `export_attendance` (L2428), `commit_enrolment` (L3235), `remove_person` (L3271) | `commit_enrolment(session_id, request)` has no user param | add `POST /attendance/excused`, `GET /attendance/week` next to `get_attendance` (declare `/attendance/week` and `/attendance/export` before any `{param}` route); CSV status/excused/group; `commit_enrolment` gets `user: auth_deps.AdminUser`, calls `store.note_enrolment(...)` then `service.commit`. `_session_view` copies `reason`, `reason_value` |
| `engine/vg/identity/enrolment.py` | `StagedPhoto` (L136), `_assess` (L336), `reject()` | `note` English sentence | add `reason`, `reason_value` fields (defaults None); set at each `reject(...)` call (no_face; several_faces=len(candidates); too_small=biggest; unclear=confidence; cut_off; too_similar=similarity). Keep `note` |

### Console (`*` = byte-shared with `mobile/src`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/main.tsx` | `<BrowserRouter><AppRoutes/></BrowserRouter>` | plain router: no `useBlocker` | `RouterProvider` with `createBrowserRouter([{ path: '*', element: <Root/> }])`; providers move into `Root`; `AppRoutes` unchanged |
| `web/src/pages/Attendance.tsx` | `Attendance` | mode picker (group / person), date, Show and Export buttons, `CamGrid` of **all** cameras, Notify **parent** disabled button | rewrite: header (Enrol a face, Export CSV), strip (`CameraFrame feature="attendance"` per doorway camera), five tiles (filter), group select, search, date (max = today), table, detail panel (status, first/last seen, "no arrival picture is kept", week strip, Mark excused, disabled Notify manager). Reads `?person=&date=&subject=` |
| `web/src/pages/People.tsx` | `People` | tabs All/Student/Staff/Visitor, search, inline confirm (`confirming`, `removing`), groups list, `openHistory` | chips with real counts, group filter, "Showing n of m", true removal sentence, History -> `/attendance?person=<id>`, groups as cards (30-day figure or "no data", link `/people?group=`), overlap note. Keep the `confirming` flow |
| `web/src/pages/PeopleGroup.tsx` | : | per-group roster | restyle only if the new cards link here; otherwise leave |
| `web/src/pages/Enrol.tsx` | `Enrol`, `guidance`, `leave`, `confirmLeave`, `save`, `discard` | steps exist as one page; Back asks once; preview poll `PREVIEW_REFRESH_MS`; cameras from `getCameras` | stepper restyle; camera list shows offline ones disabled with `offlineReason` + upload pointer; photo reasons from codes via i18n; `useBlocker` + `beforeunload` while `session` has photos; treat preview with `at` older than 3 s as no picture; step 3 links |
| `web/src/services/api.ts`* | `getAttendance` (L169), `exportAttendance` (L229), `toDirectoryPerson`, `getPeople` (L880), `removePerson`, `getGroups` (L1092), `getGroup`, enrolment calls (L1012-1090) | `getAttendance` maps to display strings (heading, rows) | add `getRegister(date, group)` returning typed rows + counts; `getWeek`, `excusePerson`; extend `getGroups` mapping with the 30-day figure. **Do not change** `getAttendance` output (phone uses it) |
| `web/src/services/wire.ts*` | `AttendanceStatus` (L21), `DirectoryPerson` (L593) | `'on_time'\|'late'\|'absent'\|'unknown'` | add `'excused'`, the new fields |
| `web/src/services/format.ts*` | `attendanceLabel` (L313), `attendanceTone` | only on_time/late/absent known | add `excused` (tone `neutral`/info), `unknown` word "No record"; photo-reason sentences; offline-reason words |
| `web/src/i18n/{keys,en,ar.draft}.ts*` | `attendance.status.*` (en L765), `attendance.notifyParent*` (L385) | | 023's strings only: tiles, banner, notes, Notify manager + why, removal sentence, photo note (237), reasons. `en` is a `Record`: a missing key fails the build |
| `web/src/app/useNavBadges.ts` (022) | : | 022 creates | add the attendance source (R10) |

## 2. Things to copy, not invent

- A new SQLite store: `events/sightings.py` (`SCHEMA`, `db.connect`, `RLock`) and `events/vehicles.py`.
- Audit first: `LiveStore.remove_person` docstring and order; `delete_vehicle_pass` (~L1836) per 022.
- Disabled-with-reason button: today's `attendance.notifyParent` / `notifyParentWhy` in `Attendance.tsx`.
- Test store with real data: `test_groups.py::store` fixture (throwaway `FaceGallery` + `SightingStore` in a `TemporaryDirectory`; **close the gallery before the tempdir**). Add the ledger to it.
- Test clients: `authed(app, role=...)`, `sign_in`, `bare_live_store`, `live_ish_store` (`conftest.py`). IT 403 pattern: `test_authorisation.py`.
- Clock for dates: `sightings.local_date(now)` and `self.clock`; `_instant(when, clock)` for the wire. Never build an `Instant` by hand.

## 3. Traps

- **Existing tests change on purpose.** Anything that seeds sightings on a fixed past date for people enrolled "now" now sees them not yet enrolled
  (`created_at` after that day). Grep `engine/tests` for `register(` (48 hits) and the files `test_attendance`, `test_groups`, `test_people_page`,
  `test_person_history`, `test_alerts_report`. Fix by giving seeded people an earlier `created_at`, not by weakening the rule.
- **`present` and `absent` change meaning.** Three readers use `!= "absent"` (`DailyRegister.present`, `groups()`, the `match=` line in `attendance()`). Miss one and an excused person counts as present.
- **Excused arrival wins.** Never mark someone excused if they have arrived that day; never hide the excusal row either.
- **Today never uses tombstones.** A removed person leaves today's page at once; they appear only on days that are now past.
- **Mixed line endings.** AGENTS.md says `api/*.py`, `services/*.ts`, `types.ts` are CRLF. This worktree checked out LF; **check `b"\r\n" in path.read_bytes()` in the real tree** and run `git diff --stat`.
- **Parity.** `api.ts`, `wire.ts`, `format.ts`, `types.ts`, i18n are copied to `mobile/src`; mobile's Attendance, People and PersonHistory pages use `getAttendance`, `getPeople`, `getGroups`, `getHistory`. Keep their outputs; run mobile `tsc`.
- **`CameraFrame live` polls recognition boxes that carry names.** On Enrol use `detections={false}` for the live view (the preview endpoint draws the box). On Attendance the strip *wants* `feature="attendance"` (names are the point there, green/amber only).
- **`UNKNOWN` status** is also used by `live.py` ~L556 (plate status, a different enum string in a different type). Check it is not `AttendanceStatus` before reusing the label.
- **Hours snapshot is lazy** (R3): it records the first read after a change. A test that changes hours must read once before and after.
- **Group 30-day memo** must drop a date when someone is excused for it, and never hold today.
- **Route order in FastAPI**: `/attendance/week` and `/attendance/export` are literal paths; keep them above anything with a path parameter.
- **`/groups/{name}` carries names in URLs** (existing). Leave.
- `web/node_modules` is absent in a worktree: junction the main checkout's, remove afterwards (memory note); `npx.cmd` in PowerShell.

## 4. Baseline

- `python -m pytest engine`: **1940 passed, 14 skipped** at `5ea8e67` (not re-run for this plan). Known flaky under load: `test_recording` forgotten-recording, `test_lost_bag` interest lapse.
- New test file: `engine/tests/test_people_v2.py` (list in quickstart). Updated: the tests named in the first trap.

## 5. Still unknown

- Does the owner want **arrival pictures**? None exist (no image in `sighting`). Plan says "no arrival picture is kept".
- **Undo an excuse**: not in the spec; not built.
- **Excused in the 30-day figure**: plan removes it from the denominator; owner to confirm.
- Cold-read time of the group 30-day pass at ~500 people (measure; SQL variant in research R6).
- Whether the compound has Students at all (chip shown only when someone is one).
- The attendance badge rule (late + not arrived after cut-off) is the planner's choice, not the spec's.
- Whether `worker.health.status` has values besides `ok | auth | down` (grep `ingest/source.py` before writing the `offlineReason` words).
