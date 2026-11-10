# Data model: 023

Three new tables in the **sightings SQLite file**, owned by `AttendanceLedger`
(`engine/vg/events/attendance.py`). Created with `CREATE TABLE IF NOT EXISTS`, so no migration step.

## excusal

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY AUTOINCREMENT | |
| person_id | TEXT NOT NULL | |
| local_date | TEXT NOT NULL | site-local ISO date |
| excused_by | TEXT NOT NULL | account name, from the session |
| excused_at | TEXT NOT NULL | ISO UTC |

Index `(local_date, person_id)`. No unique key: two administrators each leave a row; status is "a row exists".
A person with an arrival that day is **not** excused, whatever rows exist (arrival wins).

## removed_person

| Column | Type | Notes |
|---|---|---|
| person_id | TEXT PRIMARY KEY | |
| name | TEXT NOT NULL | shown on past days |
| type | TEXT NOT NULL | Student / Staff / Visitor |
| grp | TEXT | the group they were in |
| created_at | TEXT | when enrolled (null = unknown, treated as always) |
| removed_at | TEXT NOT NULL | ISO UTC |
| removed_by | TEXT NOT NULL | |
| had_faces | INTEGER NOT NULL | 1 if a photo was on file, else 0 (then never "expected") |

Written before the gallery delete. Ignored while the id is still in the gallery. Removed people are expected on a past day `D`
if `created_at <= D` and (`removed_at` local date `> D` or they have a sighting on `D`). Never on today's page.
Face vectors are not here; they are deleted with the person.

## hours_snapshot

| Column | Type | Notes |
|---|---|---|
| from_date | TEXT PRIMARY KEY | local date the values are first seen in effect |
| day_start, day_end, late_cutoff | TEXT | `HH:MM` |
| working_days | TEXT | JSON list of weekday ints (from 022) |

Appended only when the effective hours (config overlaid by 022's `site_setting`) differ from the newest row.
`hours_on(D)` = newest row with `from_date <= D`, else current hours.

## Derived (not stored)

- **Status of a person on a day**: `on_time | late` (first sighting inside day bounds vs that day's cut-off), `excused`, `absent`
  (expected, nothing seen, not excused), `unknown` = no record (not expected, or the day not recorded).
- **Recorded day**: any sighting row with that `local_date`.
- **Group 30-day figure**: see research R6. In-memory memo of past days only.

## Wire changes (details in contracts/api.md)

`AttendanceStatus` + `excused`. `AttendanceRecord` + `group`, `lastSeenAt`. `AttendanceResult` + `excused`, `recorded`,
`recognitionElsewhere`; `absent` no longer includes excused; `cameras` = doorway cameras. `GroupSummary` + `attendance30d`,
`recordedDays`. `EnrolmentPhoto` + `reason`, `reasonValue`. `CameraView` + `offlineReason`. New `ExcuseRequest`.
