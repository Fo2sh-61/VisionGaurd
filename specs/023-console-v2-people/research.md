# Research: 023 console v2 people

All checked against code at `5ea8e67`.

## R1 — A past day is rebuilt from today, so "as recorded" needs history

- **Finding**: `LiveStore._register(on, group)` (live.py) takes `self.gallery.people()` with a photo on
  file, `self.config.hours` and `sightings.register(on, expected, cutoff, day_start, day_end)`. Nothing about `on`
  changes who is expected. So: someone enrolled after `on` reads absent; a removed person
  vanishes (their `person` row is gone, `remove_person` only keeps sightings); a day with no
  sightings reads "everyone absent" (`register` marks every expected id absent); a changed cut-off
  rewrites history.
- **Decision**: `AttendanceLedger` (R2) plus one function `LiveStore._expected_on(day)`:
  - **today**: enrolled people with a photo on file (as now). Removed people are gone at once.
  - **a past day**: people enrolled on or before that local date (`created_at`, null = always) with a
    photo on file **plus** removed people whose `removed_on` is after that day, or who have a sighting that day.
- **No-data day**: `SightingStore.has_day(on)` (`SELECT 1 … LIMIT 1`). A past day with no sightings returns `recorded=false`
  and no rows. Today with none yet stays a normal day: everyone "not arrived" is true.
- **Why not freeze a register per day**: engine off = missing day; two sources of truth; a late excuse must
  still apply. Absence stays "no evidence", as `sightings.py` states.
- **Cost**: tests that seed sightings on a fixed past date with people created "now" will now see those people as
  not yet enrolled. They change by design (context §3).

## R2 — Where the new rows live

- **Decision**: `engine/vg/events/attendance.py`, class `AttendanceLedger(database)`, same file as sightings
  (`sightings.path`), `db.connect`, own `RLock`, `SCHEMA` string: copy `sightings.py`.
  Built in `LiveStore.__init__` when `sightings` is not None; closed where sightings is closed.
- **Excusal**: `excusal(id, person_id, local_date, excused_by, excused_at)`. No unique key: two administrators
  both write a row (spec edge case), status is "any row exists".
- **Removed**: `removed_person(person_id PK, name, type, grp, created_at, removed_at, removed_by, had_faces)`.
  Written **before** the gallery delete (same order as the audit). If the delete then fails, the person is still in the
  gallery, and `_expected_on` ignores a tombstone whose id is enrolled. So no cleanup code.
- **Hours**: `hours_snapshot(from_date PK, day_start, day_end, late_cutoff, working_days)`. See R3.
- **Privacy**: a removed person's name stays in `removed_person` and in sightings by id. This is the owner's
  decision (10 Nov): past attendance stays. Face vectors still go (cascade in gallery). The removal sentence
  says exactly this.

## R3 — Cut-off and working days as of a day

- **Problem**: 022 saves hours with no history; only the latest value exists.
- **Decision**: lazy snapshot. `LiveStore.hours_on(day)`: before every register read call
  `ledger.note_hours(self.hours(), today)`, which inserts a row only if the effective hours differ from the
  newest snapshot. `hours_on(day)` = the newest snapshot with `from_date <= day`, else current hours.
  Does not touch 022's save code. **Limit, stated honestly**: a change is dated the day it is first read
  (seconds after the save). Days before the first snapshot use the current hours (nothing earlier is known).
- **Rejected**: changing 022's `PATCH /settings/site` to append history (couples the specs).
- If this proves too heavy for the owner, the whole of R3 can be dropped: past days then use today's cut-off.
  Nothing else depends on it.

## R4 — Excused

- `AttendanceStatus.EXCUSED = "excused"`. `SightingStore.register(..., excused: set[str] = frozenset())`:
  an expected person with no arrival and an id in `excused` gets status `excused`. **Arrival wins**: someone excused
  who then shows up is on time or late; the excusal row stays (audit truth), the status is the evidence.
- `DailyRegister.present` today is `status != "absent"`. It must become `status in (on_time, late)`.
  Same for `live.py` `groups()` (`e.status != "absent"`) and the `match=` at `attendance()` (`status != "absent"`).
  `absent` = not arrived and not excused; `expected = present + absent + excused`. Grep done: those are the only readers
  of the old meaning besides CSV (`app.py`) and the noon report (`_attendance_counts`, which reads `.absent` — excused people are
  correctly not "absent" there; its test must be updated).
- **Endpoint** `POST /attendance/excused {personId, date}`. Refuses: future date (422), unknown or not-expected person
  (404), already arrived (409 with the time), past day with no data (409). Audit first:
  `_log(actor, "attendance.excuse", person.name, date)`. Actor = the session user, as `remove_person` does.
- **Undo**: spec silent; not built. Flagged in plan.

## R5 — Seven working days

- **Decision**: `GET /attendance/week?person=<id>&date=<D>` returns up to 7 `AttendanceDay`, newest first: the working days
  (`hours_on(day).working_days`, from 022) on or before `D`, looking back at most 21 calendar days.
  Per day: arrival (on time / late, with time, camera, minutes late) from sightings, else `excused`, else
  `absent` if the day was recorded and the person was expected, else `unknown` = "no record" (day not recorded, or
  not yet enrolled). The existing wire status `unknown` carries "no record"; its i18n label changes to "No record".
- **Query**: one SQL for the person: `WHERE person_id=? AND local_date IN (…)` (uses `idx_sighting_person_date`),
  hour bounds applied in Python as `history()` does. Do **not** call `register()` seven times: it loads a whole day's rows.
  Cut-offs come from `hours_on(day)` per day.
- **Reuse**: `SightingStore._lateness` for on-time/late, so the strip and the table cannot disagree. A test asserts it.

## R6 — Group 30-day figure

- **Definition**: over the last 30 calendar days up to today, for each day that is a working day **and** recorded
  (`has_day`): `arrived / (expected − excused)` for that group's members as of that day. `attendance30d` = total arrived ÷ total
  expected over those days, 0..1, or **null** when recognition is not running or no such day exists.
  `recordedDays` says how many days it rests on, and the card shows both ("82% over 11 days").
  Today counts only once today's late cut-off has passed; before that it is skipped, so a morning with few arrivals never drags the figure down.
- **Cost**: 30 `_register` calls (Everyone), each pulling that day's rows. Past days never change except by a late excuse,
  so memoise per past date `{person_id: (status, group)}` in `LiveStore` and drop that date's entry when someone is
  excused for it. Today is never memoised. Expect a one-off cold read of a few seconds at ~500 people and 40 cameras.
  **Measure on the clip; if the cold read passes 2 s, replace the Python day pass by a UTC-bounded SQL `GROUP BY`.** (Not built now.)
  One pass over the 30 days serves all groups: group the same per-person results.
- **Rule 5**: the page says "no data" when `null`, never 0%. It also says groups overlap (225), nothing sums them.

## R7 — Entrance strip and the colours

- Doorway = enabled or disabled camera whose `features` contain `attendance`. `LiveStore.attendance` returns these in `cameras`
  (today it returns **every** camera: `live_cameras()`). Disabled doorways stay with `offline=true`.
- `recognition_elsewhere` = number of cameras with `faces: true` that are not doorways (live.py L887: identity runs when
  `config.faces or "attendance" in features`).
- Offline "time since": `CameraView.captured_at` is the last frame time; the console computes the elapsed time. Never a frame: "no picture yet".
- **Colours**: `_face_boxes` sends an unrecognised face with `match=NONE`, `severity=INFO`, which `boxColor()` paints **blue** —
  the clothing colour (rule 1). Set `severity=WARN` for unrecognised faces: `boxColor` already returns amber for it. One line, one test.
  The default camera grid shares `_face_boxes`, so it becomes amber too, which is what AGENTS.md says it should be.

## R8 — Enrol

- **Exists and stays**: three stages in `Enrol.tsx`, `REQUIRED_PHOTOS = 5` (enrolment.py L75), Save enabled only when `ready`, discard
  asks first (`confirmLeave`), staged photos live in memory only (`EnrolmentService._sessions`, TTL 30 min, vectors only on commit), the
  floor refused again at commit (422), preview polled at 300 ms with `offline` and `at`.
- **Gap 1 — reasons are English sentences** (`_assess` builds `note=` strings). The console must word things (AGENTS idiom). Add `reason`
  (`no_face | too_small | several_faces | unclear | cut_off | too_similar`) and `reason_value` (pixels, face count, score) to `StagedPhoto` and
  `EnrolmentPhoto`. `note` stays for the phone. "Same photo twice" is `too_similar` (cosine over `TOO_SIMILAR`). "A different person"
  is not detectable with one vector per photo and no reference: not claimed.
- **Gap 2 — leaving by the sidebar is not guarded.** `confirmLeave` covers only the page's own Back button. The app uses `BrowserRouter`
  (main.tsx), and `useBlocker` needs a data router. Smallest change: `RouterProvider` over `createBrowserRouter([{ path: '*', element: <App/> }])`,
  `AppRoutes` unchanged inside. `react-router-dom ^6.26` supports it (web and mobile). Plus `beforeunload` while a session has photos.
  Closing the window needs nothing more: the session is memory-only and expires (SC-006 holds without a cancel call).
- **Gap 3 — camera reason.** The wire has `offline` only; `worker.health.status` is `ok | auth | down` (ingest/source.py). Add `offlineReason`
  (`down | auth | disabled`) to `CameraView`; the console words it and points to upload.
- **Gap 4 — enrolment is not audited.** `commit_enrolment` (app.py) calls the service directly. Add `store.note_enrolment(actor, name, group, photos)`
  that calls `_log` **before** `service.commit`, with `user: AdminUser`.
- **Stale preview**: treat a preview whose `at` is older than 3 s as "no picture", never as live (241).
- **Photo note (237)**: true today; pin with a test that a committed session leaves rows only in `person` and `face_embedding`.

## R9 — People page

- `/people` already carries `photos`, `group`, `type`, `attendanceToday`, `lastSeen`. Counts for chips are counted in the console from that list.
  Student chip: shown only when someone is a student (the compound has none); Staff and Visitor always, with counts.
- Removal copy (222): "Deletes their face measurements, so cameras stop recognising them from the next frame, with no restart. Past attendance
  stays as recorded." Pinned by a test: after `remove_person`, `gallery.match` cannot return the id, and yesterday's register still lists them.
- History button → `/attendance?person=<id>`. `PersonHistory.tsx` stays routed (Ask and the phone link there) but is no longer linked from People.

## R10 — Attendance badge (022's `useNavBadges`)

- Source: `getAttendance({mode:'group', subject:'Everyone', date: today})`. Badge number = late + not arrived, **only after the late cut-off has passed
  today** (before that, "not arrived" is normal). No cut-off known or recognition off → no badge.

## R11 — Alternatives rejected

| Idea | Why not |
|---|---|
| Add status + excused to the person-mode `days` list | Ask and the phone read `days`; changing its meaning breaks them. New endpoint is additive |
| A `/attendance/{person}` path | collides with `/attendance/export` |
| Keep English photo notes | cannot be Arabic; rule "sentences are built in the console" |
| Websocket for tiles | polling every 15 s via `useAsync(..., refreshMs)` is enough |
| Store arrival snapshots | unrequested storage and retention decision |
