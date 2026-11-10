# Feature Specification: Restricted zones and work stations — areas drawn on the camera picture

**Feature Branch**: `025-zones-and-stations`
**Created**: 2026-11-10
**Status**: Draft
**Input**: Console v2 (P14). Two features that share one drawn area. Restricted zones: an area that must stay empty; the system logs and records when someone steps in. Work stations: an area that must stay staffed; the system says whether someone is there, how long it has been empty, and alerts when it stays empty too long. Optionally a station belongs to one named person, recognised by face. Everything runs on one NVIDIA Jetson Orin Nano under Ubuntu. Replaces `001-restricted-zones` (P4) and the two earlier drafts (polygon zones, work stations).

> Keep this short. Describe **what** the user needs and **why** — never how to build it.

## Why this feature

Today a restricted zone is a whole camera: switch it on and every corner of the frame is forbidden. That is useless where a camera also sees a corridor people may walk through and only a doorway that must stay empty. And nothing says that a place that must stay staffed (reception, security booth, control room) has been left empty; a supervisor finds out by walking over.

After this feature an administrator draws the exact floor area on the camera picture. For a **zone** the operator sees which areas have someone in them and who paused one. For a **station** the operator sees every post at a glance: staffed, away, or empty past its limit. The log, the recorded clips and the three-clips-per-camera rule of today's zones stay.

## Shared parts (zones and stations)

### The drawn area

- A person counts as **inside** when the point at their feet is inside the area. Body overlap alone does not count. The editor tells the user to draw on the floor, not the wall.
- The area is stored and sent as fractions of the frame (0 to 1), never pixels, so a change of picture size or rotation leaves it on the same part of the scene.
- Several areas may share a camera; a camera may have none.

### The shared editor

The user clicks points on the live camera picture, can undo the last point, clear all, and sees the point count. Save stays disabled until there is a name and at least three points, says what is missing, and refuses a shape that crosses itself or is almost a line. If the camera picture is unavailable the editor says so and does not allow saving blind. Fields common to both: name, camera, watched hours, and Notify In-app / Email. Who receives email is set in Settings and the editor says so. Zone-only and station-only fields are listed in their sections.

### Watched hours

Zones: Always, Outside working hours, or Custom hours (from, to; may cross midnight). Stations: Working hours or Custom hours; no "Always". Working hours come from Settings; if they are not set, the page says it has no hours to follow rather than guessing.

### Notify choice

Owner decision, 10 Nov 2026: an area's own In-app / Email choice decides for that area; the Settings row ("Restricted area entered" for zones, "Work station left empty" for stations) is only the default a new area starts with. This amends spec 013, which had no per-area rules.

### One person detector, no other feature needed

Zones and stations use the person detection already running on the camera, and share it without needing each other. Neither needs any other feature switched on for that camera, nor changes how any other feature behaves. If the camera's person detection is not running, enabling an area on it starts it, and camera setup shows the cost as "shares the person detector".

## Zones (restricted areas)

### Primary story

An administrator opens Restricted zones and sees one card per zone: the camera picture with the drawn area, a chip (Person in zone, Zone clear or Paused), and two numbers, in zone now and entries today. They press **Draw a zone**, pick the server-room camera, click four corners on the floor in front of the door, name it and save. Later someone steps in: the card turns red, an entry opens in the log, the camera records. Another day they open the zone, read the entry and press **Watch clip**. At night they pause a zone for maintenance; every signed-in person sees "Paused by {name} · 22:10".

**Acceptance scenarios**

1. **Given** a watched zone, **When** a person's feet are inside the area, **Then** the card shows Person in zone, the person is marked on the picture, and an entry opens with the time of first sighting. With feet outside and the body only overlapping, nothing is logged.
2. **Given** a saved zone, **When** the administrator presses Delete, **Then** an inline question appears ("its log stays; the camera stops watching this area") and only a second confirmation deletes it. Old entries stay readable.
3. **Given** a paused zone, **When** anyone opens the page, **Then** card and detail say who paused it and when, and no new entry opens. Pausing while someone is inside closes the open entry and keeps what it has.
4. **Given** a zone set to alert after 10 seconds, **When** someone is inside for 4 seconds and leaves, **Then** the entry is logged but no alert is sent.
5. **Given** a zone set to Outside working hours, **When** someone enters during working hours, **Then** nothing is logged.
6. **Given** the owner's existing whole-camera zones, **When** the new version first starts, **Then** each appears as a full-frame zone named after its camera, with the same on/off state, history and clips.

### Edge cases

- Camera offline: the card says so and must not read "Zone clear".
- Person detector not running: the page says so with the reason. An empty log is never shown as "nobody entered". Nothing detected yet since start is a different message from unavailable.
- Two zones on one camera, one person in both: each logs its own entry. A camera records one clip at a time, so the second entry says "No clip — recorded under the other zone's entry". The camera still keeps only its last three clips between them.
- A person steps in within the minute after leaving: same incident, no second alert.
- Clips being written while other cameras are busy: detection on every camera keeps its normal pace (P14-FR-420).

### Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all five: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx (zones) and 5xx (stations), 027 6xx.

- **P14-FR-401**: A zone MUST be a drawn polygon on one camera's picture, with at least three points.
- **P14-FR-402**: Points of zones and stations MUST be stored and sent as fractions of the frame, never pixels.
- **P14-FR-403**: Inside MUST mean the feet point is inside the area (zones and stations). Body overlap alone MUST NOT count.
- **P14-FR-404**: Each zone MUST show a status (Person in zone, Zone clear, Paused), in zone now, and entries today. An offline camera or a stopped detector MUST show that instead of Zone clear.
- **P14-FR-405**: The Zones page MUST show four tiles: in zone now, entries today (noting that the latest three clips per camera have a clip), zones watching, and paused.
- **P14-FR-406**: Pausing MUST be visible to every signed-in user with who and when, MUST stop new entries for that zone only, and the paused zone and its history MUST stay listed.
- **P14-FR-407**: Each zone MUST have the Watched rule from "Watched hours" above.
- **P14-FR-408**: Each zone MUST have an alert timing: the moment someone steps in, or after N seconds inside. Entries are logged and recorded either way; the timing decides only when the alert goes. Zero seconds alerts once the scene is confirmed.
- **P14-FR-409**: The zone detail MUST show the log for Today or the last 7 days. Each entry shows its time and duration (or "inside now"), and notes when cut at the maximum clip length.
- **P14-FR-410**: Watch clip MUST play the recorded scene for entries among the latest three clips of each camera. Older entries say "No clip kept". No entry may lead to another scene's clip or to a dead button. Log entries are never deleted.
- **P14-FR-411**: The shared editor (above) MUST work as described, with the camera choice listing only cameras the system really has.
- **P14-FR-412**: The zone editor MUST also offer the alert timing (P14-FR-408).
- **P14-FR-413**: Delete MUST ask inline first. Deleting a zone or a station MUST keep its log and totals visible; the camera stops watching that area.
- **P14-FR-414**: Zones and stations MUST NOT require any other feature to be on, nor change another feature's behaviour (see "One person detector").
- **P14-FR-415**: Existing whole-camera zones MUST carry over as a full-frame zone named after their camera, keeping on/off state, history and clips. Nothing already recorded may disappear. The bootstrap file's polygon zones (with their own schedules, including weekdays) are imported once as drawn zones; the database owns them afterwards. Their schedules map onto the Watched rule as closely as it allows, and anything that does not fit is reported, not silently dropped. To be confirmed in the plan.
- **P14-FR-416**: Drawing, saving, pausing, resuming and deleting a zone MUST be allowed only to administrators, decided by the server, and each MUST be written to the audit trail before it takes effect. Everyone signed in may view (owner decision, 10 Nov 2026; spec 022, P14-FR-115).
- **P14-FR-417**: Scene timing stays: a person must remain two seconds before anything is written, a gap under five seconds does not split a visit, and a camera must be empty a full minute before the next person is a new incident (earlier ones are continuations with no second alert).
- **P14-FR-418**: A new, edited or deleted zone or station MUST take effect on the next frames without a restart.
- **P14-FR-419**: Zones and stations MUST survive a restart; the database is the source of truth. If they cannot be read at start, the page MUST say so, not show an empty list.
- **P14-FR-420**: Saving clips MUST NOT delay or drop detection on any camera. Clips are encoded without a hardware encoder on the Jetson, so the load is shared fairly.
- **P14-FR-421**: Under Arabic, the pages, the editor, counters and the timeline MUST mirror correctly; drawing on the picture is unaffected by direction.
- **P14-FR-422**: A zone's Notify choice MUST feed the same alert delivery as the Settings row "Restricted area entered", with the owner decision under "Notify choice".

### Success criteria (zones)

- **SC-401**: An administrator can draw, name and save a zone in under a minute, and the card shows the polygon in the right place.
- **SC-402**: A person walking into a zone produces an entry within 5 seconds; one walking beside it with feet outside produces none.
- **SC-403**: Pausing shows "Paused by {name} · {time}" to a second signed-in user within a few seconds, and no entry opens while paused.
- **SC-404**: On the recorded walk-through clip, a polygon matching the labelled desk area logs entries at the 12 marks labelled as events and none at the 9 labelled as negatives; a full-frame polygon logs the same scenes as today's whole-camera zone.
- **SC-405**: After the first start on the new version, every previous whole-camera zone shows as a full-frame zone with the same history and zero clips lost.
- **SC-406**: **On the Jetson**: with zones on every camera the owner will connect and clips being saved, entry is logged within 5 seconds, no camera's detection rate falls below its configured rate for longer than a few seconds, and memory stays within the 8 GB shared by processor and graphics. Nothing needs a Windows-only part.
- **SC-407**: The same drawing saved on the Windows PC and loaded on the Jetson lands on the same place of the picture.
- **SC-408**: An operator can tell within 2 seconds whether a zone card shows clear, person inside, paused, or a broken detector.

## Work stations (areas that must stay staffed)

### Primary story

An administrator opens Work stations and draws the reception desk on its camera. They leave the assigned person blank, set "alert when empty for more than 5 minutes" and choose working hours. The card reads **On station** and its timeline fills with green. At 11:20 the receptionist walks away: **Away**. At 11:25: **Absent — alert**, one alert in the feed, and the log says "Absence alert — over 5 min". An IT user opens the station, reads the times and presses **Acknowledge alert**. When somebody sits down again the card goes green and the log says "At station".

**Acceptance scenarios**

1. **Given** a station with no assigned person, **When** anyone stands in its area, **Then** it reads On station and working time grows.
2. **Given** a staffed station, **When** nobody has been inside for the whole confirmation period, **Then** it reads Away and "Left station" is logged at the moment the last person was seen.
3. **Given** an Away station empty longer than its limit, **Then** it reads Absent — alert, one "Absence alert — over N min" is logged and one alert is raised, and no second alert while the same absence continues.
4. **Given** an alert, **When** an administrator or IT user presses Acknowledge alert, **Then** it is audited before it is saved, the log shows who and when, and the card still reads Absent until somebody returns.
5. **Given** a station assigned to a named person on a camera that resolves faces, **When** somebody else stands in it, **Then** it does not read On station; **when** the assigned person walks in, it does, because they were recognised in that moment.
6. **Given** that person leaves and a stranger takes the spot, **Then** it reads Away, never On station: nothing remembers who was there before.
7. **Given** an assigned person on a camera too far away to read faces, **When** the operator opens or edits the station, **Then** a plain warning says faces cannot be read at this distance and that anyone standing there counts.
8. **Given** a time before the watched hours, **Then** the card reads Not started with "opens 9:00", counts no time and raises no alert.
9. **Given** a signed-in IT user, **When** they try to draw, edit or delete a station, **Then** the system refuses; they may view and acknowledge alerts.

### Edge cases

- **A missed frame is not leaving.** The detector routinely loses a standing person for a second or two. A brief gap changes nothing: no event, no time lost. Likewise a person walking past is not "at station".
- **Away is not Absent.** Away is empty but under the limit, no alert. Absent is empty past the limit with an alert raised. The page says which and states the limit.
- **Camera offline or detection not running.** The station reads Unknown with the reason, never Away or Absent. No time is counted and no alert is raised for the gap.
- **Engine restart.** Today's totals, events and acknowledgements survive. The downtime shows on the timeline as not watched.
- **Hours end mid-absence.** The absence ends where the watched hours end; it is not carried to the next day.
- **No stations drawn.** The page says so and offers Draw a station; no demo stations appear.
- **Assigned person deleted from the directory.** The station says so and falls back to "anyone counts".
- **Two people in the area.** Still one station, still On station; no count is shown.
- **Nothing happened yet today.** The log says nobody has been seen since the working day began, which differs from unavailable.

### Requirements

- **P14-FR-501**: An administrator MUST be able to create, edit and delete a station on any camera. A station has a name, camera, floor area (drawn in the shared editor; see P14-FR-402, 403, 411), watched hours, an optional assigned person and an empty-time limit in minutes.
- **P14-FR-503**: The station form MUST offer, besides the shared fields, only: the assigned person (optional, with a note on how far faces can be read) and "alert when empty for more than N minutes".
- **P14-FR-506**: Drawing, editing and deleting a station MUST be administrator-only, decided on the server. IT may not (owner decision, 10 Nov 2026; spec 022, P14-FR-115). Acknowledging an alert is allowed to administrators and IT (P14-FR-523).
- **P14-FR-507**: Each station MUST be watched during Working hours (Settings) or Custom hours (from, to), with no "Always". Changing working hours in Settings MUST apply at once to every station that follows them, without a restart.
- **P14-FR-508**: Outside watched hours a station MUST read Not started (before opening) or Closed (after closing), count no time and raise no alert.
- **P14-FR-510**: By default anyone inside the area counts as staffing the station.
- **P14-FR-511**: A station MAY have one assigned person; then only that person counts. Recognition MUST be by face. Clothing or body shape MUST NOT be used to decide that someone is the assigned person.
- **P14-FR-512**: Who is in a station MUST be decided afresh from the current picture each time. A name MUST NOT be remembered from an earlier moment, carried with a body recognised before, or stored as "this person is at this station". Somebody who leaves and returns is recognised again or not at all.
- **P14-FR-513**: If faces cannot be read at this camera's distance (about 80 pixels across), the page MUST warn when the assignee is chosen and on the station, and the station MUST count anyone, saying so. It MUST NOT show On station for a named person it cannot verify.
- **P14-FR-514**: If an assigned person is in the area but the face cannot be read at that moment, the station MUST NOT count them. After the confirmation period it reads Away, and the page says a person was present but not recognised.
- **P14-FR-515**: A station MUST be in exactly one state: **On station** (green), **Away** (amber), **Absent — alert** (red), **Not started** (grey). When it cannot be known it MUST read **Unknown** with the reason, in its own neutral colour.
- **P14-FR-516**: On station changes to Away only after nobody has been seen inside for a confirmation period of a few seconds; Away changes back only after somebody has been seen continuously for a shorter period. Shorter gaps are not leaving; momentary passers-by are not staffing. The recorded time of a change is the first moment of the new situation, not when it was confirmed.
- **P14-FR-517**: Away MUST become Absent when empty longer than the limit, counted from the moment the last person left.
- **P14-FR-518**: For today each station MUST show working time (On station), absence time (Away or Absent), and the on-station rate (working time as a share of watched time so far). Time the system could not watch MUST be excluded from the rate and shown as not watched.
- **P14-FR-519**: The page MUST show a timeline of today in segments On station, Away, Absent past limit and Not watched, always left to right, also in Arabic.
- **P14-FR-520**: Time MUST be measured, never estimated. If part of today could not be measured the figures say so.
- **P14-FR-521**: When a station becomes Absent the system MUST raise one alert per absence, in the in-app feed and bell, and MAY send it on other channels switched on for a new alert kind "Work station left empty" in the alert rules of spec 022 (default In-app only). Alert delivery (spec 013) knows five kinds only and must gain this one. The station's own Notify choice decides for it (see "Notify choice"). No second alert for the same absence; a new absence is a new alert. A message when somebody returns is optional.
- **P14-FR-522**: Each station MUST keep an event log: At station, Left station, Absence alert — over N min, Alert acknowledged (by whom). Events cannot be deleted. Earlier days stay available.
- **P14-FR-523**: Administrators and IT users MUST be able to acknowledge a station's alert. The acknowledgement MUST be audited before it is saved and MUST NOT change the station's state or remove any record.
- **P14-FR-524**: Alert messages MUST state only facts: station, camera, how long empty, the limit, the time. No picture, and no name except the assigned person where one exists (owner decision, 10 Nov 2026: e.g. "Reception (Ahmed) empty for 6 min").
- **P14-FR-525**: The Work stations page MUST show four tiles: staffed now, away, absent past limit, and the on-station rate today (average over open stations, with "of N open stations"). Stations that are Not started, Closed or Unknown are not counted in any tile; Unknown ones are named.
- **P14-FR-526**: Each card MUST show the camera picture with the area coloured by state, the name, the assignee line ("Assigned to X · recognised by face" or "Anyone at the station counts"), working time, absence time, the rate, today's timeline, and "opens 9:00" while not started.
- **P14-FR-527**: The detail MUST show status, times and rate, timeline, event log, the rules (assignee, limit, schedule), **Acknowledge alert** (while an unacknowledged alert exists) and **Edit station** (administrators).
- **P14-FR-528**: The picture on this page MUST NOT show names or identity boxes. The assigned-person check is shown as a state, never a label on a body.
- **P14-FR-529**: The navigation badge for Work stations MUST count stations Absent past limit and show nothing at zero. Every sentence MUST appear in English and Arabic; the Arabic is drafted and not yet read by a native speaker.
- **P14-FR-531**: A station that fails to start MUST say so on the page and in System Health with the reason. An empty page on a broken detector MUST NOT read as "everybody is at their station" or "nobody is".
- **P14-FR-532**: No fixture, random or example station may reach the live page. Demo mode keeps its own.
- **P14-FR-533**: The whole feature (drawing, live state, face check, timeline, alerts) MUST work on the Jetson Orin Nano under Ubuntu, with models on its graphics processor and 8 GB shared. The face check MUST NOT need a second copy of the face model beyond what attendance uses. The feature MUST state its measured cost on that machine, not an estimate, and MUST NOT depend on a hardware video encoder.
- **P14-FR-534**: Stations are watched at a few analyses a second per camera, set per camera as for every feature; the recommendation in camera setup MUST include stations.

### Success criteria (stations)

- **SC-501**: Within 5 seconds of someone standing in a new station on a real camera, the card reads On station.
- **SC-502**: On the recorded footage, walking out and back within the confirmation period produces no event; walking out longer produces exactly one Left station and, past the limit, exactly one alert.
- **SC-503**: With an assigned person, a second person never reads On station and the assigned person does each time they walk in, recognised again. A test pins that no name survives the person leaving.
- **SC-504**: On a camera where faces are too small, the warning appears when the assignee is chosen and the station counts anyone, saying so.
- **SC-505**: Switching the camera off or stopping detection turns a station to Unknown with a reason within 10 seconds and raises no absence alert.
- **SC-506**: After an engine restart today's totals, events and acknowledgements are unchanged and the downtime shows as not watched.
- **SC-507**: An IT user cannot draw, edit or delete a station; IT and administrators can acknowledge; every acknowledgement and change is in the audit trail before it took effect.
- **SC-508**: **On the Jetson**, with engine, models and console running together, ten stations across the cameras update their state at least every 2 seconds, and memory stays below 8 GB with the figure reported on System Health.
- **SC-509**: The existing automated checks pass on both Windows and the Jetson.

## Out of scope

- Telling who is in a zone (a zone says someone is there, never who); identifying anyone in a station who is not assigned.
- Counting people beyond each page's own numbers; no de-duplication across cameras.
- Areas that span more than one camera; more than three clips per camera; editing or deleting log entries.
- Shift rosters, several assigned people per station, per-weekday schedules, an "Always" setting for stations.
- Payroll or attendance-style reports; this is not employee attendance and does not feed it.
- Alert channels and rules in Settings (spec 022); alerting anyone outside the configured recipients.
- Any new model; weapon detection; hardware video encoding on the Jetson (none exists).

## Constitution check

- **Rules 1, 2 (face vs clothing, recognition never tracks)**: zones name nobody; the station's assigned-person check is a per-moment face check, nothing stored or carried (P14-FR-511 to 514).
- **Rule 3 (own overlay)**: each page draws its own areas and no identities (P14-FR-528).
- **Rules 4, 5 (nothing untrue, no claimed precision)**: real data only (P14-FR-532); Unknown and "not watched" are their own states; measured times only; "in zone" is a feet-point test on one camera.
- **Rule 6 (fractions)**: P14-FR-402.
- **Rules 7, 8 (degradation is payload; failed start says so)**: P14-FR-404, 419, 515, 531.
- **Rule 9 (no feature needs another)**: P14-FR-414.
- **History is never deleted; audit before write**: P14-FR-410, 413, 416, 522, 523.
- **Server-side permissions**: P14-FR-416, 506; the interface hides, the system decides.
- **Biometrics**: no face data is stored here; the check reads the existing enrolment and writes nothing.
- **The Jetson**: SC-406, P14-FR-533 and SC-508 state the budget on the target machine.

## Assumptions

- The new design supersedes the earlier "no schedules" decision (P4): zones have Watched rules (confirmed by the owner, 10 Nov 2026). "Outside working hours" means the hours set in Settings.
- The latest-three-clips rule stays per camera, not per zone. Entries today count scene entries in site-local time, not people.
- Confirmation periods (a few seconds to leave, shorter to return) are tuned on the recorded footage and held in configuration. The 80-pixel face threshold is the design's figure, to be confirmed against the face model on the footage.
- The Jetson runs engine, models, cameras and console window together; the owner continues to develop on a Windows PC.
