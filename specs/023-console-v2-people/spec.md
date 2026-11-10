# Feature Specification: Console v2 — Attendance, People and Enrol

**Feature Branch**: `023-console-v2-people`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: User description: "Console v2, administrator pages: Attendance, People (directory and groups) and the three-step Enrol flow, built from the owner's design handoff. Everything on the Jetson Orin Nano as well as the Windows development PC." This is the people half of P14 (console v2) in `docs/PLAN.md`.

> Every name, count and time in the design is sample data. None of it ships. Each figure
> on these pages comes from the engine, or the page says plainly that it has nothing.

## Why this feature

Attendance, People and Enrol already work, but they were built as three separate tools.
The new console wants them to feel like one place: see who has arrived, filter by what
matters, open a person, enrol or remove someone without leaving the flow. Three things the
design shows do not exist yet: a way to mark an absence as excused, a read of the last
seven working days beside a person, and a group's attendance over 30 days. And two things
the design shows must not pretend to work: telling a manager, and anything that promises
more than the cameras know.

After this feature an administrator opens Attendance and sees today at a glance, can go
back to any past day exactly as it was recorded, can excuse an absence under their own
name, and can manage the people the cameras recognise. IT staff never see any of it.

## User Scenarios & Testing

### Primary story

The head of administration opens Attendance at 9:40. The doorway cameras are shown at the
top with a short note saying which cameras recognise faces. Five tiles show how many
people are everyone, on time, late, not arrived and excused; they press **Not arrived**
and the table narrows to those people. They pick a group, open one name and see when
they were first and last seen, the picture the camera took, and their last seven working
days. The person phoned in sick, so they press **Mark excused**; the tile counts change
and the change is in the audit trail under their name. The next day they pick yesterday in
the date box: a banner says the page shows that day as recorded, and nothing on it can
be edited as if it were today. Later they press **Enrol a face**, fill in a name,
choose a camera, capture five usable photos, and see the Saved step with a link back to
People.

**Acceptance scenarios**

1. **Given** an administrator on Attendance, **When** the page opens, **Then** it shows
   today's table, the strip of entrance cameras with their note, and five tiles whose
   numbers match the table, and pressing a tile filters the table to that status.
2. **Given** a past date is chosen, **When** the page loads it, **Then** a banner says
   the page shows that day as it was recorded, the table and tiles are that day's, and
   the export button downloads that day.
3. **Given** a group is chosen, **When** the table refreshes, **Then** the tiles and rows
   count only that group's people, and "Everyone" is the way back.
4. **Given** a person opened in the detail panel, **When** the administrator reads it,
   **Then** it shows status, snapshot, first and last seen, and one entry for each of the
   last seven working days, with any day that has no record saying so instead of a blank.
5. **Given** the same panel, **When** the administrator looks at **Notify manager**,
   **Then** it is disabled and says in words that messages to managers are not set up
   yet — it is never a button that appears to work.
6. **Given** a person who has not arrived, **When** the administrator presses **Mark
   excused**, **Then** the audit entry is written first, the person shows as excused, and
   the tiles update. Excused is never inferred by the system and never set by a camera.
7. **Given** People, **When** the administrator opens it, **Then** Directory and Groups
   tabs appear; the directory filters by type (All, Staff, Visitors, each with its
   count), by group and by name, and each row shows type, group, how many faces are
   on file and today's status.
8. **Given** a row, **When** the administrator presses **Remove**, **Then** an in-place
   confirmation says the stored face measurements are deleted, the cameras stop recognising the
   person, and what happens to past attendance — worded to match what really happens.
   Only on confirming is the person removed; the audit entry is written first.
9. **Given** a row, **When** the administrator presses **History**, **Then** Attendance
   opens with that person selected.
10. **Given** Groups, **When** the administrator reads a card, **Then** it shows how many
    people are in the group, how many are on site today, and attendance over the last 30
    days, each saying "no data" rather than zero when nothing was watching.
11. **Given** Enrol step 1, **When** the administrator gives a name, type, optional group
    and optional detail and continues, **Then** step 2 lists the cameras; one that is not
    sending a picture is shown with the reason, cannot be chosen to capture from, and
    points to uploading photos instead.
12. **Given** step 2, **When** photos are captured or uploaded, **Then** five slots fill
    in; a photo with no face, more than one face, or too poor to recognise from is
    flagged **Unusable** with its reason and a Remove button; **Save** is enabled only at
    five usable photos.
13. **Given** photos taken but not saved, **When** the administrator tries to leave,
    **Then** they are asked to **Discard and leave** or **Stay**, and discarding leaves
    nothing behind.
14. **Given** Save pressed, **When** it succeeds, **Then** step 3 says the person is
    enrolled and can now be recognised, with **View in People** and **Enrol someone
    else**; if it fails, the page says why and keeps the photos.
15. **Given** an IT account, **When** it opens either page by address or any engine call,
    **Then** the engine refuses it; the pages are absent from navigation for IT.

### Edge cases

- **Recognition is not running** (model failed, no entrance camera configured): Attendance
  says so with the reason, and shows no percentages or zeroes that imply "everyone is
  absent".
- **Entrance camera offline**: it stays in the strip, marked offline with the time since,
  and the page notes that arrivals through it are not being seen.
- **No expected list** (nobody enrolled): Attendance says "no one is enrolled yet" and
  links to Enrol; it does not show 0 of 0.
- **Future date or today before the first doorway sighting**: not arrived is truthful;
  a future date is not selectable.
- **Past day with no recorded data** (before the system ran, or cameras down): says
  "nothing was recorded that day", not "everyone absent".
- **Someone removed after a past day**: that day's page still reads as recorded; see the
  clarification on what "past attendance stays" means.
- **Leaving Enrol by closing the window or losing connection**: the unsaved session is
  discarded, not left half-enrolled.
- **Same photo twice, or a photo of a different person**: flagged unusable when the
  engine can tell; otherwise the administrator's judgement stands and is not claimed
  otherwise.
- **Two administrators**: excusing the same person twice records both entries and leaves
  one excused status.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all six: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx, 026 5xx, 027 6xx.

Numbered `P14-FR-2nn`. Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Attendance

- **P14-FR-201**: System MUST show, per day, a table of name, department, arrival time,
  arrival camera and status, taken from what the doorway cameras actually recorded. First
  sighting counts as arrival, as today.
- **P14-FR-202**: System MUST show a strip of the entrance cameras with a note saying that
  face recognition runs on the doorway cameras only. The note MUST reflect the real
  situation: if recognition also runs on other cameras, it MUST say so rather than repeat
  the design's sentence.
- **P14-FR-203**: Any overlay on the strip is attendance's own — it names people by face
  only, and green means recognised by face, amber means a face that is not recognised
  (rule 1; the design's red for "not enrolled" would read as an alarm and is not used);
  clothing and tracking numbers never appear here.
- **P14-FR-204**: System MUST show five tiles — everyone, on time, late, not arrived,
  excused — whose numbers equal the rows in the table, and pressing one filters the table.
- **P14-FR-205**: Users MUST be able to choose a past date. The page MUST then show a
  banner saying it shows that day as recorded, and every figure and the export MUST be
  that day's.
- **P14-FR-206**: Users MUST be able to filter by group and by name or department.
- **P14-FR-207**: The detail panel MUST show status, the arrival snapshot where one
  exists, first and last seen, and one line for each of the last seven working days. A
  day with no record MUST say "no record", not be left blank or shown as absent.
- **P14-FR-208**: **Notify manager** MUST be disabled with a stated reason until a
  message channel to managers exists. It MUST NOT be clickable, fake a send, or show a
  confirmation.
- **P14-FR-209**: Users MUST be able to mark an absence as excused. The audit entry MUST
  be written before the status changes, carry the actor, person and date, and excused
  MUST be a human decision only.
- **P14-FR-210**: Excused MUST count as its own tile and MUST NOT be added into on time,
  late or arrived.
- **P14-FR-211**: **Enrol a face** and **Export CSV** MUST be available from the header;
  the export MUST include the excused status.
- **P14-FR-212**: Both pages MUST be reachable by administrators only; the engine MUST
  refuse every call behind them from any other role, whatever the console hides.

### People

- **P14-FR-220**: System MUST show a directory with type chips (all, staff, visitors,
  each with its real count), a group filter that lists only groups that exist, and name
  search, with the footer "Showing n of m".
- **P14-FR-221**: Each row MUST show type, group, number of faces on file and
  today's status; a person with no face on file MUST say they cannot be recognised
  rather than show an empty cell.
- **P14-FR-222**: Users MUST be able to remove a person after an in-place confirmation
  whose wording is true: the stored face measurements are deleted, recognition stops
  without a restart, and the sentence about past attendance matches what the engine
  really keeps and what pages can show.
- **P14-FR-223**: History MUST open Attendance with that person selected.
- **P14-FR-224**: Groups MUST appear as cards showing people, on site today and
  attendance over the last 30 days, with a link to the people in the group. A group's
  attendance MUST say "no data" when attendance was not running, never 0%.
- **P14-FR-225**: The groups page MUST say that groups can overlap and do not add up to
  the total, as the design does, because it is true.

### Enrol

- **P14-FR-230**: Step 1 MUST take name (required), type, group (optional, from existing
  groups) and detail (optional), and MUST refuse a missing name with a stated reason.
- **P14-FR-231**: Step 2 MUST list the cameras able to capture; a camera that is not
  sending a picture MUST remain visible with the reason and a pointer to uploading
  photos.
- **P14-FR-232**: Step 2 MUST show a live view with a box on the single face in shot and
  say when it is ready, or when there are none or several.
- **P14-FR-233**: System MUST accept photos by camera capture or upload into five slots.
  Each photo MUST be judged usable or unusable with its reason ("2 faces in shot. One
  person at a time, please."), and an unusable photo MUST be removable.
- **P14-FR-234**: **Save** MUST be enabled only at five usable photos, and MUST show
  "n of 5 usable photos" until then. Nobody is enrolled with fewer.
- **P14-FR-235**: Leaving with photos taken MUST ask discard-or-stay; discarding MUST
  leave no person, no photos and no face data behind.
- **P14-FR-236**: Step 3 MUST confirm the person can now be recognised, with links to
  People and to enrol another. A failed save MUST say why and keep the photos.
- **P14-FR-237**: The note under the photos MUST say truthfully what is kept after saving.
  Today the engine never stores a photo: photos live only for the enrolment session and
  only the face measurements are saved, so the design's note is true and stays true.

### Platform

- **P14-FR-240**: The pages MUST work with the engine, its models and cameras and the
  console window all running on the Jetson Orin Nano, as well as on the Windows PC, with
  no feature switched off on either.
- **P14-FR-241**: The live enrol preview MUST NOT depend on a hardware video encoder; if
  the picture is slower on the Jetson, the page MUST still work and MUST NOT show a stale
  picture as live.
- **P14-FR-242**: Attendance and Enrol MUST be usable while all other features are
  running, within the Jetson's shared 8 GB memory; if the machine cannot keep up, System
  health says so, as today.
- **P14-FR-243**: Face recognition for enrolment and attendance MUST keep the same face
  model on both machines so a person enrolled on one is recognised on the other.

## Success Criteria

- **SC-001**: An administrator can tell today's late and not-arrived counts, and who
  they are, within 5 seconds of opening Attendance.
- **SC-002**: Switching to any past date shows that day's banner and figures in under 2
  seconds, and no figure on the page is from a different day.
- **SC-003**: Excusing someone changes the tiles at once and the audit trail shows the
  entry before the change, with the administrator's name.
- **SC-004**: No control on either page appears to work and does nothing; Notify manager
  shows its reason and cannot be pressed.
- **SC-005**: A new person with five usable photos can be enrolled in under 3 minutes and
  is recognised by a doorway camera afterwards without restarting anything.
- **SC-006**: Leaving Enrol and discarding leaves zero new people and zero new face
  records; this is checked on the engine, not only on screen.
- **SC-007**: An IT account sees neither page and gets a refusal from the engine on every
  attendance and people call.
- **SC-008**: On the Jetson Orin Nano, with the cameras and all enabled features
  running, a day's attendance loads, a person is enrolled and a person is removed with
  the same results as on the Windows PC.
- **SC-009**: With recognition stopped, both pages say why and show no invented zeroes
  or percentages.

## Out of scope

- Shell, roles, Home, Ask and Settings (spec 022).
- Car plates (024), restricted zones (025), work stations (026).
- Cameras and camera wall, including the top-bar camera count (027).
- Sending anything to managers — Notify manager stays disabled; messaging belongs to
  alert delivery (013).
- Counting, de-duplication across cameras, and tracking people through the site.
- Guardian contact fields (not in the new design).
- Changing the face model, or erasing past sightings of removed people (P3).
- Bulk import of people.

## Constitution check

- **A face names a person; clothing never does.** The doorway strip and enrol view name
  by face only. Nothing here uses clothing or a tracking number.
- **Each feature draws its own overlay.** Attendance's strip shows attendance boxes only;
  Enrol shows its own face box. Pages that must not show identity are not touched.
- **Never show anything untrue.** Every sample figure in the design is dropped. Notify
  manager is honestly disabled. Excused is real and audited. The Remove wording and the
  enrolment photo note must match what the engine does.
- **No claimed precision.** No percentage where nothing was watched; "no record" and
  "no data" are different from zero. A group's numbers do not add to the total.
- **Honest degradation.** Recognition stopped, camera offline, or no one enrolled each
  says so with a reason; pages stay up.
- **Server-side permissions.** Admin-only is enforced by the engine on every route; the
  console only hides.
- **Audit first.** Removing, excusing and saving an enrolment are recorded before they
  happen. (Saving an enrolment is not audited today; that is new engine work.)
- **No feature requires another.** Attendance and Enrol work with every other feature
  switched off.

## Assumptions

- Already real and unchanged in behaviour: the attendance register for any date with CSV
  export, the people directory with photo counts and today's status, groups with people
  and on-site counts, per-person history, removing a person, and the whole enrolment
  session (start, capture, upload, remove photo, commit, cancel) with the five-photo
  floor and quality scoring.
- New engine work: the **excused** status and its audited marking; the seven-working-day
  strip as one read; a group's 30-day attendance; per-photo unusable reasons if the
  current scoring does not give them to the page; the entrance cameras and their note
  reflecting real state; a wording check for removal; an audit entry when an enrolment
  is saved; moving the attendance, attendance export, groups, people and history reads
  behind the administrator-only rule (today IT may read them — this reverses that
  decision, owned by spec 022); and a past day rebuilt **as of that day** — today a past
  date is recomputed from today's enrolled people and today's cut-off, so people enrolled
  since show as absent and people removed since vanish, and a day with no sightings shows
  everyone absent instead of "nothing was recorded". Notify manager needs nothing,
  because it is disabled.
- Working days are Saturday to Thursday unless the administrator changes them in Settings
  (owner decision, 10 Nov 2026; spec 022, P14-FR-123), inside the working calendar dates.
- A removed person still appears on past days exactly as recorded that day (owner
  decision, 10 Nov 2026), matching the design's "Past attendance stays." Today their past
  sightings are kept but no page shows them, so this is part of rebuilding a past day as
  of that day.
- The design's Arabic text is the starting translation and is reviewed by the owner.
