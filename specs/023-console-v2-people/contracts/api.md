# API changes: 023

Wire rules unchanged: snake_case in Python, camelCase out, `extra="forbid"`, fractions 0..1 (clamp before sending).
**Permissions**: nothing is added to `auth/deps.py`. 022 already puts `/attendance`, `/groups`, `/people`, `/enrolment` behind admin-only.
Every endpoint below is under one of those prefixes, so IT is refused by path.
Degradation is payload: with recognition off the reads return empty with the reason on `/system/capabilities`; only writes that cannot happen return 503.

## New

### `POST /attendance/excused`
Body `ExcuseRequest { personId: string, date: string }` (ISO date) -> `AttendanceRecord` (that person's row for that day, status `excused`).
- Audit `attendance.excuse` (subject = person name, detail = date) is written **before** the row is stored. Actor = session user.
- 404 unknown person or not expected that day. 422 future date. 409 "already arrived at 07:42" (the plain reason). 409 "nothing was recorded that day".
- 503 (`SubsystemUnavailable`) when recognition / the ledger is not running.
- A second excuse for the same person and day succeeds, writes its own audit entry, and leaves one `excused` status.

### `GET /attendance/week?person=<id>&date=<ISO>`
Returns `AttendanceDay[]`, newest first, up to 7 **working days** on or before `date` (working days from 022's settings), looking back at most 21 calendar days.
Per day: `status` = `on_time | late | excused | absent | unknown`. `unknown` means **no record** (day not recorded, or person not yet enrolled).
`seenAt`, `location`, `minutesLate` as `AttendanceDay` has them today. Empty list with recognition off.

## Changed

| Endpoint / type | Change |
|---|---|
| `AttendanceStatus` | adds `excused`. `unknown` is shown as "No record" |
| `AttendanceRecord` | adds `group: string \| null`, `lastSeenAt: Instant \| null` |
| `GET /attendance` (group mode) | result adds `excused: number`, `recorded: boolean`, `recognitionElsewhere: number`. `absent` now **excludes** excused; `expected = present + absent + excused`. `cameras` = doorway cameras only (feature `attendance`), offline ones kept. A past day with no sightings returns `recorded: false`, no records, zeroes that the page must not print as figures. Past days use that day's roll, cut-off and removed people (research R1, R3) |
| `GET /attendance` (person mode) | unchanged shape. Still `days` of days seen; Ask and the phone read it |
| `GET /attendance/export` | `status` column can be `excused`; summary rows add `excused`; a `group` column is added after `type`; `recorded: false` days export a header and the summary only |
| `GET /groups`, `/groups/{name}` | `GroupSummary` adds `attendance30d: number \| null` (0..1) and `recordedDays: number`. `null` = no data. Today is included only once its late cut-off has passed. `here` now counts on time + late only |
| `GET /people` | `attendanceToday` may be `excused` |
| `DELETE /people/{id}` | writes a `removed_person` row before the delete; otherwise unchanged (204, audit `person.remove` first, 503 / 404 as today) |
| `POST /enrolment/sessions/{id}/commit` | takes the admin user; writes audit `person.enrol` (name, group, photo count) **before** committing |
| `EnrolmentPhoto` | adds `reason: "no_face" \| "too_small" \| "several_faces" \| "unclear" \| "cut_off" \| "too_similar" \| null` and `reasonValue: number \| null` (pixels, face count, score). `note` stays |
| `CameraView` | adds `offlineReason: "down" \| "auth" \| "disabled" \| null` |
| `_face_boxes` overlay | unrecognised faces now `severity: warn` (amber). Recognised unchanged (green). Clothing blue stays tracking's |

## Not changing

`/enrolment/preview/{camera}` (already `offline` + `at`, no names), session create / photo / capture / delete / cancel,
`POST /auth/*`, `/system/capabilities`, person-mode `days`, Ask.
