# Implementation Plan: Console v2 — Attendance, People, Enrol

**Branch**: `console-v2-people` (spec folder `023-console-v2-people`) | **Date**: 10 Nov 2026 | **Spec**: [spec.md](spec.md)
**Code read at**: `5ea8e67`. Shared things come **from 022** (roles in `deps.py`, `LiveStore.hours()` with working days, toasts, `useNavBadges`, tokens/RTL). Not re-planned here.

## Summary

The fact that decides the shape: **the register is rebuilt from today's data on every read.**
`LiveStore._register` takes whoever is enrolled *now* and the cut-off *now* (live.py `_register`),
so a past day is wrong in three ways and the new "as recorded" banner would be a lie
(rule 4). Everything else in the spec (excused, 7-day strip, 30-day group figure) sits on the
same gap: the system never wrote down **who was expected, and under which hours, on a past day**.

The smallest fix is one new store, `AttendanceLedger`, in `engine/vg/events/attendance.py`
(copy `events/sightings.py`), in the **same SQLite file** as sightings, with three tiny tables:

| Table | Holds | Why it is needed |
|---|---|---|
| `excusal` | person, date, who, when | the new status. A human decision, never derived |
| `removed_person` | name, type, group, enrolled-on, removed-on | a removed person stays on past days "as recorded" (owner decision) |
| `hours_snapshot` | cut-off, day bounds, working days, from-date | a past day uses that day's cut-off, not today's |

Absence is still **derived** (no sighting = absent), as `sightings.py` already insists. We do not store
a register per day. Rejected as too complex: a nightly "freeze the day" job (misses days when the
engine was off; two truths).

Everything after that is small:

1. `LiveStore._register(on, group)` becomes the one place that knows "expected as of `on`", "hours as of
   `on`", and "excused". `attendance()`, `people()`, `groups()` and the noon report already call it,
   so all four agree for free.
2. Two new reads (`GET /attendance/week`, `POST /attendance/excused`); two fields on `GroupSummary`;
   per-photo reason codes on `EnrolmentPhoto`; one audit call before enrolment commit.
3. Console: rewrite `Attendance.tsx` (tiles, table, detail panel), restyle `People.tsx` + groups,
   restyle `Enrol.tsx` (it already has the 3 steps, the 5-photo floor and a leave guard).

## Technical Context

Python 3.10-safe (Jetson test-bench figures; deployment board unknown). TypeScript/React. SQLite via
`vg/db.py::connect`. Tests: `python -m pytest engine`, `npx.cmd tsc -b --force` (web + mobile), pyflakes,
`tools/check_parity.py`. Same face model both machines (SFace, settled): nothing here touches it (243).
**Baseline** 1940 passed, 14 skipped. **Scale**: ~40 cameras, but attendance reads only doorway cameras.

## Constitution Check

| Gate | Holds? | How |
|---|---|---|
| Truthful data | Yes | Past day as recorded; "nothing was recorded" is its own answer; "no record" ≠ absent; Notify manager disabled with reason; removal wording tested against the engine |
| Rule 1 / 3 | Yes | Strip uses `CameraFrame feature="attendance"`; unrecognised face boxes become **amber** (today `_face_boxes` sends them blue = the clothing colour — a rule-1 breach this fixes) |
| Rule 5 | Yes | Group 30-day figure is "none" when not running; it carries the number of days it rests on |
| Audit first | Yes | `_log` before excuse, remove, and **enrolment commit** (new) |
| Server-side permissions | Yes | All paths already under `/attendance`, `/groups`, `/people`, `/enrolment`: admin by 022's `deps.py`. New endpoints add nothing to `deps.py` |
| Rule 7 / 8 / 9 | Yes | Both pages say why recognition is off (existing `useCapability`); neither page needs another feature on |

No violations. No complexity tracking.

## Each requirement → the smallest mechanism

| FR | Mechanism |
|---|---|
| 201, 204, 210 | `AttendanceStatus.EXCUSED`; `SightingStore.register(..., excused=set)` turns *absent* into *excused*; `DailyRegister.present` stops using `!= "absent"`. `AttendanceResult` gains `excused`; tiles are numbers the engine already sends |
| 202, 203 | Engine sends only doorway cameras (feature `attendance`) in `cameras`, plus `recognition_elsewhere` (count of `faces: true` cameras that are not doorways). Note text built in console |
| 205 | `/attendance?date=` exists. Engine adds `recorded: false` for a past day with no sightings; console shows banner + "nothing was recorded" |
| 206 | Existing group query + client-side name/department filter |
| 207 | `GET /attendance/week` (new, one read, up to 7 working days, `unknown` = "no record"). First/last seen from `AttendanceRecord.lastSeenAt` (new field) |
| 208 | Disabled `linkbtn`, copy of today's `notifyParent` pattern, new text |
| 209 | `POST /attendance/excused`: `_log` first, then `ledger.excuse`. Refuses future date, someone who already arrived, unknown person, a past day nothing was recorded |
| 211 | CSV already exists; add `excused` column value + summary row |
| 212 | 022 |
| 220–221 | Existing `/people` (photos, group, type, status). Chips and counts computed in console from that list |
| 222 | Existing `DELETE /people/{id}`. Add: write `removed_person` first. Wording fixed in i18n and pinned by a test |
| 223 | Link to `/attendance?person=<id>&date=…`; the page reads it like it reads `subject` today |
| 224, 225 | `GroupSummary.attendance30d` + `recordedDays`, computed from the same `_register`, past days memoised |
| 230–236 | **Exists** in `Enrol.tsx` + `/enrolment/*` (floor is already `REQUIRED_PHOTOS = 5`). New: reason **codes** on photos (the engine sends English sentences today, which cannot be Arabic), camera `offlineReason`, route blocker for in-app leave |
| 237 | Stays true: engine stores vectors only. Wording in i18n, pinned by a test that asserts no image bytes reach the gallery |
| 240–243 | Nothing new needed: no encoder in the preview path (MJPEG snapshots + polled detection), same SFace. Checked on the new board only |

## Source Code (what changes)

```text
engine/vg/events/attendance.py     NEW  AttendanceLedger (3 tables)
engine/vg/events/sightings.py      register(excused=), DailyRegister.present/excused, has_day()
engine/vg/api/live.py              _register, attendance, people, groups, remove_person, week, excuse, camera_view
engine/vg/api/store.py             MockStore: excuse/week stubs, note_enrolment (audit)
engine/vg/api/schemas.py           EXCUSED, record/result/group/photo/camera fields, ExcuseRequest
engine/vg/api/app.py               POST /attendance/excused, GET /attendance/week, audit in commit, CSV
engine/vg/identity/enrolment.py    StagedPhoto.reason, reason_value
engine/tests/test_people_v2.py     NEW
web/src/pages/{Attendance,People,PeopleGroup,Enrol}.tsx   rewrite / restyle
web/src/main.tsx                   BrowserRouter -> data router (useBlocker)
web/src/app/useNavBadges.ts        attendance badge source (file is 022's)
web/src/services/{api,wire,format}.ts*   web/src/i18n/{keys,en,ar.draft}.ts*   web/src/types.ts*
* = byte-shared with mobile/src: edit, copy, check_parity.py
```

## Order of work

1. Ledger + `_register` + tests (the past-day rebuild). Existing tests that pin "past day = today's roll" change **on purpose** (context §3).
2. Excuse, week, group 30-day, removal tombstone, enrolment audit, reason codes. Test each.
3. Wire + `api.ts` + parity copy; then pages: Attendance, People/groups, Enrol.
4. Checks (quickstart). Jetson checks wait for the new board; the SSH bench gets nothing installed.

## Still open (kept open, design fits either answer)

- **Arrival picture** (spec story says "the camera picture"; 207 says "where one exists"). The engine keeps **no** arrival picture (`sightings` has no image). Plan: the panel says "no arrival picture is kept". If the owner wants pictures, it is a new store with a retention decision, not part of 023.
- **Undo an excuse**: spec has none. Plan has none; the table design allows a later delete.
- **Excused in the 30-day figure**: plan takes excused days out of the denominator (neither for nor against). Owner to confirm.

## Deliberately not done

No per-day frozen register; no manager messaging; no arrival photos; no new role code; no change to the
face model, tracking, or the person-mode `days` list that Ask and the phone read.

## Build order and shared pieces (cross-check, 10 Nov 2026)

Order: **022 first**, then **023, 024 and 025 in parallel**, then **027** (its wall readings use 024's plate-trouble state and 025's per-zone status and `alerted` flag).

Shared pieces have one owner, so no spec re-plans them:
- `auth/deps.py`: 022 built `OPERATOR_WRITE_PATTERNS` (a tuple of compiled regexes, POST/DELETE only, checked right after `OPERATOR_WRITE_PREFIXES`) and moved `/track` and `/tracking` into `ADMIN_PREFIXES`. 024 (Gone) and 025 (station acknowledge) each **add one line** to `OPERATOR_WRITE_PATTERNS`; if Gone or acknowledge is not POST/DELETE, widen the method check there. 027 creates `ADMIN_PATTERNS` (checked before the safe-method return) for `/cameras/{id}/faces`.
- `ToolId` and `NAV`: 022 did **not** add placeholders. 025 adds `stations` (`ToolId`, `NAV` after Restricted zones, `nav.stations.*` keys); 027 adds `cameras` (`ToolId`, `NAV` last in the main section, `nav.cameras.*` keys). Each touches only its own entry, so they do not collide.
- `useNavBadges` (`web/src/app/useNavBadges.ts`, fetching through `web/src/services/navBadges.ts`): 022 built the vehicle-alerts slot and an attendance slot counting not-arrived. 023 replaces the attendance rule with its own (late plus not arrived, after the cut-off); 025 adds zones and stations.
- `useAttention`: 022's sidebar card uses `useAlertFeed`, which already has a status. 027 adds the additive `status` field to `useAttention` itself for the wall.
- `LiveStore._register` (`live.py`, around 3921): 022 swaps its hours read for `self.hours()`. 023 then rewrites the function on top of that.
- The audit-first example is `live.py::delete_pass` (~L1828). There is no `delete_vehicle_pass`. `dismiss_alert` is at ~L1946.
- Also update `web/src/services/api.ts` (~L1141: `pct: t.status === 'absent' ? 0 : 100`) and `format.ts` (~L317, the closed `known` list) so `excused` is handled in both copies. That makes four readers of "absent", not three.
