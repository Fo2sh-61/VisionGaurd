# Feature Specification: Console v2 — Attendance, People and Enrol

**Feature Branch**: `023-console-v2-people`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: "Console v2, administrator pages: Attendance, People (directory and groups) and the three-step Enrol flow, built from the owner's design handoff. Everything on the Jetson Orin Nano as well as the Windows development PC." People half of P14 in `docs/PLAN.md`.

> Every name, count and time in the design is sample data. None of it ships. Each figure
> comes from the engine, or the page says plainly that it has nothing.

## Why this feature

Attendance, People and Enrol already work, but as three tools. The new console makes them
one place. Three things in the design do not exist yet: marking an absence excused, the
last seven working days beside a person, and a group's attendance over 30 days. Two things
must not pretend to work: telling a manager, and anything that promises more than the
cameras know. IT staff never see these pages.

## User Scenarios & Testing

### Primary story

An administrator opens Attendance: doorway cameras on top, five tiles (everyone, on time,
late, not arrived, excused) that filter the table. They open a name, see first and last
seen, the camera picture and the last seven working days, and press **Mark excused**; the
tiles change and the audit trail shows it under their name. They pick yesterday: a banner
says the page shows that day as recorded. Later they enrol a person: name, camera, five
usable photos, Saved.

**Acceptance scenarios**

1. **Given** a past date, **Then** a banner says it shows that day as recorded; table,
   tiles and export are that day's.
2. **Given** **Notify manager**, **Then** it is disabled and says in words that messages to
   managers are not set up yet.
3. **Given** **Mark excused**, **Then** the audit entry is written first, then the status
   and tiles change.
4. **Given** **Remove**, **Then** an in-place confirmation states what really happens (face
   measurements deleted, recognition stops, past attendance); only on confirming is the
   person removed, audit entry first.
5. **Given** a group card, **Then** it says "no data" rather than zero when nothing was
   watching.
6. **Given** a camera not sending a picture, **Then** Enrol shows it with the reason, it
   cannot be chosen, and the page points to uploading photos.
7. **Given** a photo with no face, several faces or too poor to recognise, **Then** it is
   flagged **Unusable** with its reason and a Remove button; **Save** needs five usable.
8. **Given** unsaved photos and the user leaves, **Then** **Discard and leave** or **Stay**
   is asked; discarding leaves nothing behind. A failed save says why and keeps the photos.
9. **Given** an IT account, **Then** the engine refuses every call and navigation hides the pages.

### Edge cases

- **Recognition not running** or no entrance camera: Attendance says so with the reason, with
  no percentages or zeroes implying "everyone is absent".
- **Entrance camera offline**: stays in the strip, marked offline with time since, with a
  note that arrivals through it are not seen.
- **Nobody enrolled**: "no one is enrolled yet" with a link to Enrol, not "0 of 0".
- **Future date**: not selectable. **Past day with no data**: "nothing was recorded that
  day", not "everyone absent".
- **Closing the window or losing connection during Enrol**: the unsaved session is discarded.
- **Same photo twice, or a different person**: flagged when the engine can tell; otherwise
  the administrator's judgement stands and nothing more is claimed.
- **Two administrators excuse the same person**: both entries recorded, one excused status.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all five: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx (zones) and 5xx (stations), 027 6xx.

Numbered `P14-FR-2nn`. Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Attendance

- **P14-FR-201**: System MUST show, per day, a table of name, department, arrival time,
  arrival camera and status, from what the doorway cameras recorded. First sighting counts
  as arrival, as today.
- **P14-FR-202**: System MUST show a strip of the entrance cameras with a note saying face
  recognition runs on the doorway cameras only. If recognition also runs elsewhere, the
  note says so.
- **P14-FR-203**: Overlays on the strip are attendance's own and name people by face only:
  green = recognised, amber = a face not recognised (rule 1; the design's red would read as
  an alarm and is not used). Clothing and tracking numbers never appear here.
- **P14-FR-204**: System MUST show five tiles (everyone, on time, late, not arrived,
  excused) whose numbers equal the rows in the table; pressing one filters the table.
- **P14-FR-205**: Users MUST be able to choose a past date; the page then shows the "as
  recorded" banner, and every figure and the export are that day's.
- **P14-FR-206**: Users MUST be able to filter by group and by name or department; with a
  group chosen, tiles and rows count only that group's people, and "Everyone" is the way back.
- **P14-FR-207**: The detail panel MUST show status, arrival snapshot where one exists,
  first and last seen, and one line per last seven working days. A day with no record says
  "no record", not blank and not absent.
- **P14-FR-208**: **Notify manager** MUST be disabled with a stated reason until a message
  channel to managers exists; never clickable, never a fake send.
- **P14-FR-209**: Users MUST be able to mark an absence as excused. The audit entry MUST be
  written before the status changes and carry actor, person and date. Excused is a human
  decision only, never inferred or set by a camera.
- **P14-FR-210**: Excused MUST be its own tile and MUST NOT be added into on time, late or
  arrived.
- **P14-FR-211**: **Enrol a face** and **Export CSV** MUST be in the header; the export
  MUST include the excused status.
- **P14-FR-212**: Both pages MUST be for administrators only; the engine MUST refuse every
  call behind them from any other role, whatever the console hides.

### People

- **P14-FR-220**: System MUST show a directory with type chips (all, staff, visitors, each
  with its real count), a group filter of existing groups, name search, and "Showing n of m".
- **P14-FR-221**: Each row MUST show type, group, faces on file and today's status; a person
  with no face on file says they cannot be recognised.
- **P14-FR-222**: Users MUST be able to remove a person after an in-place confirmation whose
  wording is true: face measurements deleted, recognition stops without a restart, and the
  past-attendance sentence matches what the engine keeps and pages show.
- **P14-FR-223**: History MUST open Attendance with that person selected.
- **P14-FR-224**: Groups MUST appear as cards with people, on site today and attendance over
  the last 30 days, and a link to the group's people. Attendance says "no data" when it was
  not running, never 0%.
- **P14-FR-225**: The groups page MUST say groups can overlap and do not add up to the total.

### Enrol

- **P14-FR-230**: Step 1 MUST take name (required), type, group (optional, existing) and
  detail (optional), and refuse a missing name with a stated reason.
- **P14-FR-231**: Step 2 MUST list the cameras able to capture; one not sending a picture
  stays visible with the reason and a pointer to uploading photos.
- **P14-FR-232**: Step 2 MUST show a live view with a box on the single face in shot and
  say when it is ready, or when there are none or several.
- **P14-FR-233**: System MUST accept photos by capture or upload into five slots. Each is
  judged usable or unusable with its reason ("2 faces in shot. One person at a time,
  please."), and an unusable photo MUST be removable.
- **P14-FR-234**: **Save** MUST be enabled only at five usable photos and show "n of 5
  usable photos" until then. Nobody is enrolled with fewer.
- **P14-FR-235**: Leaving with photos taken MUST ask discard-or-stay; discarding MUST leave
  no person, no photos and no face data behind.
- **P14-FR-236**: Step 3 MUST confirm the person can now be recognised, with links to People
  and to enrol another. A failed save says why and keeps the photos.
- **P14-FR-237**: The note under the photos MUST say truthfully what is kept. Today the
  engine never stores a photo: photos live only for the enrolment session and only the face
  measurements are saved, so the design's note is true and stays true.

### Platform

- **P14-FR-240**: The pages MUST work with the engine, models, cameras and console window
  all on the Jetson Orin Nano, as well as on the Windows PC, with no feature switched off.
- **P14-FR-241**: The live enrol preview MUST NOT depend on a hardware video encoder; if
  slower on the Jetson it MUST still work and MUST NOT show a stale picture as live.
- **P14-FR-242**: Attendance and Enrol MUST be usable while all other features run, within
  the Jetson's shared 8 GB memory; if the machine cannot keep up, System health says so.
- **P14-FR-243**: Enrolment and attendance MUST keep the same face model on both machines,
  so a person enrolled on one is recognised on the other.

## Success Criteria

- **SC-001**: An administrator can tell today's late and not-arrived counts, and who they
  are, within 5 seconds of opening Attendance.
- **SC-002**: Switching to a past date shows that day's banner and figures in under 2
  seconds, with no figure from a different day.
- **SC-003**: Excusing someone changes the tiles at once, and the audit trail shows the
  entry before the change, with the administrator's name.
- **SC-004**: No control on either page appears to work and does nothing.
- **SC-005**: A new person with five usable photos can be enrolled in under 3 minutes and is
  recognised by a doorway camera afterwards without restarting anything.
- **SC-006**: Leaving Enrol and discarding leaves zero new people and zero new face records,
  checked on the engine, not only on screen.
- **SC-007**: An IT account sees neither page and gets a refusal from the engine on every
  attendance and people call.
- **SC-008**: On the Jetson Orin Nano, with cameras and all enabled features running, a
  day's attendance loads, a person is enrolled and a person is removed with the same results
  as on the Windows PC.
- **SC-009**: With recognition stopped, both pages say why and show no invented zeroes or
  percentages.

## Out of scope

- Shell, roles, Home, Ask and Settings (spec 022); car plates (024); restricted zones and
  work stations (025); cameras and camera wall (027).
- Sending anything to managers (belongs to alert delivery, 013).
- Counting, de-duplication across cameras, tracking people through the site.
- Guardian contact fields; bulk import of people.
- Changing the face model, or erasing past sightings of removed people (P3).

## Constitution check

- **Face names a person; clothing never does**: P14-FR-203. Each feature draws its own overlay.
- **Never show anything untrue**: samples dropped; Notify manager disabled (208); Remove and photo-note wording true (222, 237).
- **No claimed precision**: "no record" and "no data" are not zero (207, 224); groups do not sum (225).
- **Honest degradation**: recognition stopped, camera offline, nobody enrolled each say why; pages stay up.
- **Server-side permissions**: the engine enforces admin-only (212); the console only hides.
- **Audit first** (209, 222): removing, excusing and saving an enrolment are recorded before they happen. Saving an enrolment is not audited today; that is new engine work.
- **No feature requires another**: both pages work with every other feature off.

## Assumptions

- Already real and unchanged: the attendance register for any date with CSV export, the
  directory with photo counts and today's status, groups with people and on-site counts,
  per-person history, removing a person, and the whole enrolment session (start, capture,
  upload, remove photo, commit, cancel) with the five-photo floor and quality scoring.
- New engine work: the **excused** status and its audited marking; the seven-working-day
  strip as one read; a group's 30-day attendance; per-photo unusable reasons if current
  scoring does not give them to the page; entrance cameras and a note reflecting real
  state; a wording check for removal; an audit entry when an enrolment is saved; moving the
  attendance, export, groups, people and history reads behind the administrator-only rule
  (today IT may read them; this reverses that decision, owned by spec 022); and a past day
  rebuilt **as of that day** — today a past date is recomputed from today's enrolled people
  and cut-off, so people enrolled since show absent, people removed since vanish, and a day
  with no sightings shows everyone absent instead of "nothing was recorded". Notify manager
  needs nothing, because it is disabled.
- Working days are Saturday to Thursday unless the administrator changes them in Settings
  (owner decision, 10 Nov 2026; spec 022, P14-FR-123), inside the working calendar dates.
- A removed person still appears on past days exactly as recorded that day (owner decision,
  10 Nov 2026), matching the design's "Past attendance stays." Today their past sightings
  are kept but no page shows them, so this is part of rebuilding a past day as of that day.
- The design's Arabic text is the starting translation and is reviewed by the owner.
