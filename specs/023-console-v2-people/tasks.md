---
description: "Tasks for 023 console v2 people"
---

# Tasks: Console v2 — Attendance, People, Enrol

**Input**: `specs/023-console-v2-people/` (spec.md, plan.md, research.md, data-model.md, contracts/api.md, context.md, quickstart.md)
**Tests**: required. Engine business rules are written test-first (red, then green). Engine tests go in `engine/tests/test_people_v2.py` unless a task says otherwise.
**Before any task**: read `context.md`. Spec 022 is already built (roles in `auth/deps.py`, `LiveStore.hours()`, `SiteSettingsStore`, `ToastProvider`/`useToast`, `useNavBadges`, v2 `NAV`). Build on it.
**Tags**: `[ENG]` engine task, `[CON]` console task (web, and mobile where parity demands it). `[P]` = different files, no dependency on an unfinished task.
**Line endings**: `engine/vg/api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md` are CRLF. Use Edit; check `git diff --stat` after each task for whole-file churn.
**Parity**: files marked `*` are byte-shared with `mobile/src`. Edit in `web/src`, copy byte-for-byte to `mobile/src` only if the mobile copy was identical before; run `python tools/check_parity.py`.

Stories (from spec and plan):
- **US1** Attendance as recorded: past days, tiles, strip, doorway cameras, export (FR 201-206, 210-212)
- **US2** Mark excused (FR 209, 210)
- **US3** Detail panel and the seven-working-day strip (FR 207, 208)
- **US4** People directory and removal (FR 220-223)
- **US5** Groups with the 30-day figure (FR 224, 225)
- **US6** Enrol (FR 230-237, 241)
- **US7** Platform and badge (FR 240, 242, 243; attendance nav badge)

## Phase 1: Setup

- [ ] T001 [CON] Junction `web/node_modules` and `mobile/node_modules` from the main checkout into this worktree, then run `npx.cmd tsc -b --force` in `web/` and `mobile/` to confirm a clean start. Remove the junctions afterwards with a non-recursive `[IO.Directory]::Delete` (do not leave them for the merge)
- [ ] T002 [ENG] Run `python -m pytest engine/tests/test_attendance.py engine/tests/test_groups.py engine/tests/test_people_page.py engine/tests/test_person_history.py engine/tests/test_alerts_report.py engine/tests/test_shell_v2.py` and record the passing counts as the baseline for this spec
- [X] T003 [ENG] Create `engine/tests/test_people_v2.py` with the imports and fixtures from `engine/tests/conftest.py` (`authed`, `sign_in`, `bare_live_store`, `live_ish_store`) and a `store` fixture copied from `test_groups.py` (throwaway `FaceGallery` + `SightingStore` + the new ledger in a `TemporaryDirectory`, `LiveStore(config=vgconfig.load(), registry=...)`, gallery closed before the tempdir). Helper to enrol a person with a given `created_at` and seed sightings on a given date

## Phase 2: Foundational (blocks every story)

**Purpose**: the ledger, the new status, and `_register` rebuilt "as of a day". Everything else reads through `_register`.

- [X] T004 [ENG] Tests in `test_people_v2.py` for `AttendanceLedger` (`engine/vg/events/attendance.py`), written first:
  - `excuse` then `excused_on(date)` returns the person; two excuses for one person and day give two rows and one entry in the set.
  - `note_removed` then `removed_expected_on(D)` lists the person for `D` earlier than the removal date, and not for the removal day or later (unless they have a sighting that day).
  - `note_hours` inserts a row only when the effective hours differ from the newest row; `hours_on(D)` returns the newest row with `from_date <= D`, else `None`.
  - Rows survive close and reopen of the same file.
- [X] T005 [ENG] Create `engine/vg/events/attendance.py`: `AttendanceLedger(database)` with the three tables from `data-model.md` (`excusal`, `removed_person`, `hours_snapshot`), `CREATE TABLE IF NOT EXISTS`, `db.connect`, `RLock`, `SCHEMA`, `close()`, and the methods `excuse`, `excused_on`, `note_removed`, `removed_expected_on`, `note_hours`, `hours_on`. Copy the shape of `events/sightings.py`
- [X] T006 [ENG] Tests in `test_people_v2.py` for `SightingStore` changes, written first: `register(on, expected, cutoff, day_start, day_end, excused=...)` turns an absent expected id in the set into status `excused`; **arrival wins** (an excused id that arrived is `on_time` or `late`); `DailyRegister.present` counts only `on_time`/`late`; `DailyRegister.excused` exists; `has_day(on)` is true only when a sighting row has that local date; `person_days(pid, dates)` returns that person's first sighting per date in one query and agrees with `_lateness`
- [X] T007 [ENG] In `engine/vg/events/sightings.py`: add the `excused` argument to `SightingStore.register`; change `DailyRegister.present` to `status in ("on_time", "late")`; add `DailyRegister.excused`; add `has_day(on)` (`SELECT 1 FROM sighting WHERE local_date=? LIMIT 1`) and `person_days(pid, dates)` (one query on `idx_sighting_person_date`, bounds applied in Python like `history`, reuse `_lateness`)
- [X] T008 [ENG] Add `AttendanceStatus.EXCUSED = "excused"` in `engine/vg/api/schemas.py`; add to `AttendanceRecord` the fields `group: str | None` and `last_seen_at: Instant | None`; to `AttendanceResult` the fields `excused: int`, `recorded: bool`, `recognition_elsewhere: int` (defaults so every existing constructor, including `_empty_attendance`, still works); add `ExcuseRequest(Wire)` with `person_id`, `date`. Keep `extra="forbid"` and the 0..1 validated types
- [X] T009 [ENG] Tests in `test_people_v2.py` for `LiveStore._register` / `_expected_on`, written first (these are the "rebuild a past day" rules):
  - a person enrolled after day D is not on D's register;
  - a person removed after D is still on D's register with their name; on today's register they are gone at once;
  - a day with no sightings returns `recorded=False` and no rows; today with none yet is a normal day (everyone "not arrived");
  - D uses D's cut-off after hours were changed (read once before and after the change, because the snapshot is lazy);
  - a removed person with no photo on file is never expected (`had_faces = 0`);
  - an unmatched tombstone whose id is still enrolled (failed delete) is ignored.
- [X] T010 [ENG] In `engine/vg/api/live.py`: in `LiveStore.__init__` build `self.ledger = AttendanceLedger(sightings.path) if sightings else None` and close it with the other stores; add `_expected_on(on, wanted)` per research R1 (today = enrolled with a photo; past = enrolled on or before `on`, plus tombstones removed after `on` or with a sighting that day); add `hours_on(on)` (calls `ledger.note_hours(self.hours(), today)` first); rewrite `_register(on, group)` to use them, pass `excused=ledger.excused_on(on)`, return `recorded` from `has_day`, and memoise past dates (research R6, never today, drop a date on excuse)
- [X] T011 [ENG] Update the existing tests that change meaning on purpose (context.md trap 1): grep `engine/tests` for `register(` and fix `test_attendance.py`, `test_groups.py`, `test_people_page.py`, `test_person_history.py`, `test_alerts_report.py` by giving seeded people an earlier `created_at`, never by weakening the rule. Update the noon-report test that pins the old meaning of `absent` (`_attendance_counts`). Run the five files plus `test_people_v2.py`; all green
- [X] T012 [ENG] [P] Add to `MockStore` in `engine/vg/api/store.py`: `week` and `excuse` stubs (rule 4: empty list / raise `SubsystemUnavailable`, never invented rows) and `note_enrolment(actor, name, group, photos)` that calls `_log`, so `-Mock` still runs

**Checkpoint**: the register is correct for any day; the old tests pass on purpose-changed fixtures.

## Phase 3: US1 — Attendance as recorded

**Goal**: tiles equal the table; a past date shows its own day and says so; the strip shows doorway cameras with true colours; export carries excused.
**Independent test**: GET `/attendance` for a past date on the test store returns that day's roll, `recorded`, counts with `expected = present + absent + excused`; IT gets 403.

### Tests first

- [X] T013 [ENG] [US1] Tests in `test_people_v2.py`: `attendance("group", "Everyone", on)` returns `excused` and `recorded`, `absent` excludes excused, `expected = present + absent + excused`; `match` is `FACE` only for `on_time`/`late`; records carry `group` and `last_seen_at`; `cameras` holds only doorway cameras (feature `attendance`), a disabled doorway stays with `offline=True`; `recognition_elsewhere` counts `faces: true` cameras that are not doorways; a past day with no sightings returns `recorded=False`, no records; group mode with a group counts only that group; `groups()` `here` does not count excused as present
- [X] T014 [ENG] [P] [US1] Tests in `test_people_v2.py`: `_face_boxes` sends an unrecognised face with `severity=WARN` and a recognised face unchanged; `camera_view` has `offline_reason` `down`/`auth` from `worker.health.status`, `disabled` for a disabled camera, `None` when online. First grep `ingest/source.py` for the values `worker.health.status` can take, and use only those
- [X] T015 [ENG] [P] [US1] Tests in `test_people_v2.py` for the export: `status` column can be `excused`, a `group` column follows `type`, the summary rows include `excused`, a `recorded: false` day exports only the header and the summary
- [X] T016 [ENG] [P] [US1] Tests in `test_people_v2.py` for permissions: with an IT session, 403 on GET `/attendance`, `/attendance/export`, `/attendance/week`, `/groups`, `/people`, `/enrolment/sessions` and on POST `/attendance/excused`; the same calls with an admin session do not return 403. Follow the pattern in `test_authorisation.py`. Add no line to `auth/deps.py`

### Engine

- [X] T017 [ENG] [US1] In `engine/vg/api/live.py`, `attendance` (group mode): add `group`, `last_seen_at` to records, `excused`, `recorded`, `recognition_elsewhere`; `match=FACE` only for on_time/late; metrics add Excused; `cameras` = doorway cameras. Leave person mode untouched except `self.hours()`. Update `_empty_attendance` defaults. Update `groups()` `here` (on_time/late only). Check the four readers of "absent": `DailyRegister.present`, `groups()`, the `match=` line, and the CSV in `app.py`
- [X] T018 [ENG] [P] [US1] In `engine/vg/api/live.py`: `_face_boxes` unrecognised faces `severity=WARN`; add `offline_reason` to `camera_view` and `offline_reason: "down" | "auth" | "disabled" | None` to `CameraView` in `schemas.py`
- [X] T019 [ENG] [US1] In `engine/vg/api/app.py`, `export_attendance`: write the `excused` status, the `group` column after `type`, the `excused` summary row, and header-only output for `recorded: false`

### Console

- [ ] T020 [CON] [US1] In `web/src/services/wire.ts`*: add `'excused'` to `AttendanceStatus`; add the new fields to the attendance, group, photo and camera shapes per `contracts/api.md`. Copy to `mobile/src/services/`
- [ ] T021 [CON] [US1] In `web/src/services/format.ts`*: add `excused` to `attendanceLabel` (tone neutral/info), change the `unknown` word to "No record" (check it is the `AttendanceStatus` `unknown` and not the plate status near `live.py` ~L556), add offline-reason words. Run `web/scripts/check-format.ts` and add assertions for the new cases. Copy to mobile
- [ ] T022 [CON] [US1] In `web/src/services/api.ts`*: add `getRegister(date, group)` returning typed rows and counts (do not change `getAttendance` output: the phone uses it). Fix the `pct: t.status === 'absent' ? 0 : 100` reader (~L1141) so `excused` is handled. Copy to mobile only if the mobile copy was identical before, else port by hand
- [ ] T023 [CON] [US1] Add 023's strings only to `web/src/i18n/keys.ts`*, `en.ts`*, `ar.draft.ts`*: tiles, "as recorded" banner, "nothing was recorded that day", recognition-off reason, no-one-enrolled, doorway note (with and without "recognition also runs elsewhere"), offline-with-time-since note. Copy all three to mobile; `en` is a `Record`, a missing key fails the build
- [ ] T024 [CON] [US1] Rewrite `web/src/pages/Attendance.tsx` (list part): header with Enrol a face and Export CSV; strip with `CameraFrame feature="attendance"` per doorway camera (offline ones marked with time since, "no picture yet" when there is none); five tiles that filter the table and equal its rows; group select; name/department search; date picker with `max` = today; table; banner for a past day; plain states for recognition off, nobody enrolled, no data day. No percentage or zero when there is nothing to base it on. Read `?person=&date=&subject=` as the old page did
- [ ] T025 [CON] [US1] Run `npx.cmd tsc -b --force` in `web/` and `mobile/`, `python tools/check_parity.py`

**Checkpoint**: Attendance reads as recorded for any day; tiles add up; the strip is amber/green only.

## Phase 4: US2 — Mark excused

**Goal**: an administrator excuses an absence; audit first; tiles change.
**Independent test**: POST `/attendance/excused` writes the audit entry, then the status is `excused` in the register.

- [X] T026 [ENG] [US2] Tests in `test_people_v2.py`, written first: `excuse` returns the person's row with status `excused`; the audit entry `attendance.excuse` (subject = name, detail = date, actor = session user) exists **before** the ledger row, proven by making `ledger.excuse` raise and still finding the audit entry; refusals: future date (422), unknown or not-expected person (404), already arrived (409 with the time), past day with no data (409); a second excuse succeeds, writes its own audit entry, leaves one `excused` status; a late excuse for a past day drops that date from the memo; `SubsystemUnavailable` (503) when `ledger is None`; the group 30-day memo does not hold today
- [X] T027 [ENG] [US2] In `engine/vg/api/live.py` add `excuse(person_id, date, actor)`: validate, then `self._log(actor, "attendance.excuse", name, date)`, then `ledger.excuse`, then invalidate that date's memo. Raise `SubsystemUnavailable` when `ledger is None`
- [X] T028 [ENG] [US2] In `engine/vg/api/app.py` add `POST /attendance/excused` next to `get_attendance` (declare literal `/attendance/...` routes above any path-parameter route). Nothing added to `deps.py`: the path is under `/attendance`, admin-only by 022
- [ ] T029 [CON] [US2] In `web/src/services/api.ts`* add `excusePerson(personId, date)`; add the strings (Mark excused, why a refusal happened) to the three i18n files; copy to mobile
- [ ] T030 [CON] [US2] In `web/src/pages/Attendance.tsx`: Mark excused in the detail panel (offered only for a not-arrived person on a recorded day; the engine decides the rest), reload on success, `useToast` for success and for the engine's plain refusal reason, tiles change at once

## Phase 5: US3 — Detail panel and the week strip

**Goal**: first and last seen, seven working days, "no record" distinct from absent, Notify manager disabled with a reason.
**Independent test**: GET `/attendance/week` returns up to 7 working days newest first, with `unknown` for a day not recorded.

- [X] T031 [ENG] [US3] Tests in `test_people_v2.py`, written first: `week(person, date)` returns up to 7 working days on or before `date` (working days from `hours_on(day)`), looking back at most 21 calendar days, newest first; a day arrived is `on_time`/`late` with `seen_at`, `location`, `minutes_late`; excused day is `excused`; recorded day with an expected person and nothing seen is `absent`; a day not recorded, or before enrolment, is `unknown`; the strip's late/on-time agrees with the table for the same person and day (reuse of `_lateness`); empty list with recognition off; one query for the person, not seven `register()` calls
- [X] T032 [ENG] [US3] In `engine/vg/api/live.py` add `week(person_id, date)` per research R5 using `person_days`, `has_day`, `excused_on`, `hours_on`
- [X] T033 [ENG] [US3] In `engine/vg/api/app.py` add `GET /attendance/week?person=&date=` (literal route above any `{param}`)
- [ ] T034 [CON] [US3] In `web/src/services/api.ts`* add `getWeek(personId, date)`; add its strings; copy to mobile
- [ ] T035 [CON] [US3] In `web/src/pages/Attendance.tsx` finish the detail panel: status, first and last seen, "no arrival picture is kept" (plan decision: the engine stores none), week strip of up to 7 working days where `unknown` reads "No record", Mark excused, and **Notify manager** disabled with the stated reason (messages to managers are not set up yet; copy the `notifyParent`/`notifyParentWhy` pattern, never clickable)

## Phase 6: US4 — People directory and removal

**Goal**: real counts, true removal sentence, History opens Attendance.
**Independent test**: after removal, face matching cannot return the id, and yesterday's register still lists the person.

- [X] T036 [ENG] [US4] Tests in `test_people_v2.py`, written first: `remove_person` writes the audit entry, then the tombstone, then deletes (a failing gallery delete still leaves the audit entry and the person enrolled, the tombstone ignored); after removal `gallery.match` cannot return the id; yesterday's register still lists the person by name; today's does not; `people()` `attendance_today` may be `excused`. Add the wording pin: the removal sentence key in `en.ts` states face measurements are deleted, recognition stops without a restart, and past attendance stays as recorded
- [X] T037 [ENG] [US4] In `engine/vg/api/live.py` `remove_person`: after `_log`, before the delete, call `ledger.note_removed(person, now, actor)` (record `had_faces`, `created_at`, group, type)
- [ ] T038 [CON] [US4] Add strings (chips, "Showing n of m", cannot-be-recognised, removal sentence, overlap not needed here) to the three i18n files; copy to mobile. Extend `toDirectoryPerson`/`getPeople` mapping in `api.ts`* only as needed; keep outputs the phone reads
- [ ] T039 [CON] [US4] Rewrite `web/src/pages/People.tsx`: type chips with real counts (Student chip only when someone is one), group filter of existing groups, search, "Showing n of m", rows with type, group, faces on file, today's status (including excused), "cannot be recognised" for no face; keep the inline `confirming` flow with the true removal sentence; History links to `/attendance?person=<id>` (`PersonHistory.tsx` stays routed, no longer linked from here). Make Attendance honour `?person=` by selecting that person
- [ ] T040 [CON] [US4] Run `npx.cmd tsc -b --force` in `web/` and `mobile/`, `python tools/check_parity.py`

## Phase 7: US5 — Groups with the 30-day figure

**Goal**: cards with people, on site, 30-day figure and the days it rests on, or "no data"; overlap note.
**Independent test**: `groups()` returns `attendance30d` `null` with recognition off, and a number with `recordedDays` otherwise.

- [X] T041 [ENG] [US5] Tests in `test_people_v2.py`, written first: `attendance30d` is `null` and `recorded_days` 0 with recognition off or no recorded working day in the last 30; otherwise `arrived / (expected - excused)` summed over recorded working days, in 0..1 (clamped); a non-working day is skipped; a past day is memoised and dropped when someone is excused for it; today is never memoised; one pass serves all groups; a person in two groups counts in both and the groups need not sum to the total
- [X] T042 [ENG] [US5] In `engine/vg/api/schemas.py` add `attendance_30d: Fraction | None` and `recorded_days: int` to `GroupSummary`; in `live.py` `groups()` compute them from the memoised `_register` pass (research R6). Measure the cold read on the recorded clip data or a seeded ~500-person store and note the figure in the final reply; do not build the SQL variant unless it passes 2 s
- [ ] T043 [CON] [US5] Extend the `getGroups` mapping in `api.ts`* with the 30-day figure and days (mobile output unchanged); add strings (card text "82% over 11 days", "no data", the overlap note); copy to mobile
- [ ] T044 [CON] [US5] In `web/src/pages/People.tsx` render groups as cards: people, on site today, 30-day figure with its days or "no data" (never 0%), link to `/people?group=`, and the note that groups can overlap and do not add up to the total. Restyle `PeopleGroup.tsx` only if the cards link there

## Phase 8: US6 — Enrol

**Goal**: reasons in the page language, offline cameras with reason, guarded leave, audited commit.
**Independent test**: committing an enrolment writes `person.enrol` first; a photo with two faces carries `reason = several_faces`, `reason_value = 2`; discarding leaves no rows.

- [X] T045 [ENG] [US6] Tests in `test_people_v2.py` and `engine/tests/test_enrolment.py`, written first: each rejection sets `reason`/`reason_value` (`no_face`; `several_faces` = face count; `too_small` = biggest face in pixels; `unclear` = score; `cut_off`; `too_similar` = similarity) and `note` stays; `EnrolmentPhoto` carries them camelCased; `commit_enrolment` writes audit `person.enrol` (name, group, photo count) **before** `service.commit` and requires an admin (IT 403); a failed commit keeps the audit entry and the session; a committed session leaves rows only in `person` and `face_embedding` (pins the photo note, P14-FR-237); a cancelled or expired session leaves no person and no face rows (SC-006)
- [X] T046 [ENG] [US6] In `engine/vg/identity/enrolment.py` add `reason` and `reason_value` to `StagedPhoto` (defaults `None`) and set them at each `reject(...)` call in `_assess`; in `schemas.py` add them to `EnrolmentPhoto`; in `app.py` `_session_view` copy them; `commit_enrolment` gets `user: auth_deps.AdminUser` and calls `store.note_enrolment(...)` before `service.commit`; implement `note_enrolment` on `LiveStore` (`_log` first)
- [ ] T047 [CON] [US6] Add strings for each photo reason (with the value, e.g. "2 faces in shot. One person at a time, please."), the offline-camera reasons and the upload pointer, the leave dialog, step 3 links, and the photo note (237) to the three i18n files; reason sentences are built in `format.ts`* from the codes; copy to mobile
- [ ] T048 [CON] [US6] In `web/src/main.tsx`: replace `<BrowserRouter><AppRoutes/></BrowserRouter>` with `RouterProvider` over `createBrowserRouter([{ path: '*', element: <Root/> }])`; move the providers into `Root`; `AppRoutes` unchanged. Check that `react-router-dom` in `web/` supports it (`^6.26`) and that the 022 providers (`ToastProvider`, account, site, language) still wrap everything
- [ ] T049 [CON] [US6] Restyle `web/src/pages/Enrol.tsx`: stepper; camera list shows offline cameras disabled with their `offlineReason` words and an upload pointer; live view with `detections={false}` (the preview endpoint draws the box); treat a preview whose `at` is older than 3 s as no picture, never as live; photo cards show Usable/Unusable with the reason from the code and a Remove button; "n of 5 usable photos" until Save is enabled; `useBlocker` plus `beforeunload` while the session holds photos (Discard and leave / Stay); a failed save says why and keeps the photos; step 3 links to People and to enrol another
- [ ] T050 [CON] [US6] Run `npx.cmd tsc -b --force` in `web/` and `mobile/`, `python tools/check_parity.py`

## Phase 9: US7 — Platform and the attendance badge

- [ ] T051 [CON] [US7] In `web/src/app/useNavBadges.ts` and `web/src/services/navBadges.ts` replace 022's attendance slot with the 023 rule: late plus not arrived, **only after today's late cut-off has passed**; no badge when the cut-off is unknown, recognition is off, or the call fails (absent, never 0). Add a test in `web/scripts/` if a pattern exists there; otherwise cover the counting function with an assertion script
- [ ] T052 [ENG] [US7] Confirm FR 241-243 by reading the code and say so in the final reply: the enrol preview path has no encoder, the face model is unchanged, nothing here touches SFace. Record the Jetson checks as waiting for the new deployment board (the SSH bench gets nothing installed; do not connect)

## Phase 10: Polish and verification

- [ ] T053 [ENG] Run `python -m pytest engine` (baseline 1940 passed, 14 skipped plus 022's and the new tests; the count must not drop). If a known flaky timing test fails (`test_recording` forgotten-recording, `test_lost_bag` interest lapse) rerun it alone before reporting
- [ ] T054 [ENG] Run `python -m pyflakes engine/vg engine/tools engine/tests`; fix anything from this spec's files
- [ ] T055 [CON] Run `npx.cmd tsc -b --force` in `web/` and `mobile/`, `python tools/check_parity.py`, and `web/scripts/check-format.ts`
- [ ] T056 [ENG] Run `git diff --stat` and confirm no whole-file line-ending churn in the CRLF files (`api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`)
- [ ] T057 [ENG] Update `STATUS.md` (CRLF, use Edit): the excused status, the ledger, past days as recorded, the week strip and 30-day figure, per-photo reason codes, audited enrolment, amber unrecognised faces. Update docs only where they would now be untrue
- [ ] T058 [CON] Remove the `node_modules` junctions from T001 if still present. The by-eye checks in `quickstart.md` (items 1-10, IT account, Arabic) are left for the owner: no servers are started in this lane

## Dependencies and order

- T001-T003 first. Phase 2 (T004-T012) blocks everything; inside it T004 before T005, T006 before T007, T008 before T009-T010, T010 before T011.
- US1 engine (T013-T019) before US1 console (T020-T025). US2, US3 need US1's `wire.ts`, `api.ts` and `Attendance.tsx` shell. US4 and US5 share `People.tsx` (T039 before T044). US6 is independent of US2-US5 after Phase 2 apart from the i18n files and `api.ts`, which every story edits: serialise those edits.
- `wire.ts`, `format.ts`, `api.ts` and the i18n files are touched by many tasks: copy to mobile after each task that edits them, not only at the end.
- The engine half of any story can run in parallel with another story's console half.

## Not built (kept out on purpose)

Per-day frozen register, manager messaging, arrival pictures, undo of an excuse, new roles, any change to the face model, tracking, or the person-mode `days` list that Ask and the phone read.
