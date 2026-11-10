# Feature Specification: Restricted Zones, redrawn — polygons on the camera picture

**Feature Branch**: `025-polygon-zones`
**Created**: 2026-11-10
**Status**: Draft
**Input**: User description: "Console v2, restricted zones: the operator draws the area that must stay empty as a polygon on the camera picture. Zone cards with the drawn area, status chips, pause visible to everyone with who and when, a detail panel with counters, watched hours, alert delay and an event log with Watch clip, and an editor shared with work stations. Inside means the person's feet are inside the area. Everything now runs on one NVIDIA Jetson Orin Nano under Ubuntu." Redesign of `001-restricted-zones` (P4). Part of console v2 (P14).

> Keep this short. Describe **what** the user needs and **why** — never how to build it.

## Why this feature

Today a restricted zone is a whole camera: switch it on and every corner of the frame is forbidden. That is useless where a camera also sees a corridor people may walk through and only a doorway that must stay empty. Operators need to draw the exact area, see it on the picture, know at a glance which areas have someone in them, and pause one without anyone wondering later who did it. This spec replaces the whole-frame zone with a drawn area and keeps everything that already works: the log, the recorded clips, the three-clips-per-camera rule.

## User Scenarios & Testing

### Primary story

An administrator opens Restricted zones and sees one card per zone: the camera picture with the drawn area, a chip saying Person in zone, Zone clear or Paused, and two numbers, in zone now and entries today. They press **Draw a zone**, picks the server-room camera, clicks four corners on the floor in front of the door, names it, and saves. That afternoon someone steps into the area; the card turns red, an entry opens in its log, and the camera records. Later they open the zone, reads the entry, and presses **Watch clip**. At night they pause a zone for maintenance; every other signed-in person sees "Paused by {their name} · 22:10".

**Acceptance scenarios**

1. **Given** zones exist, **When** anyone signed in opens the page, **Then** four tiles show in zone now, entries today, zones watching and paused, and each zone appears as a card with the camera picture and its drawn area.
2. **Given** a watched zone, **When** a person's feet are inside the drawn area, **Then** the card shows Person in zone, the person is marked on the picture, and a log entry opens with the time of first sighting.
3. **Given** a person standing beside the zone with their body overlapping it but feet outside, **When** they stay there, **Then** nothing is logged.
4. **Given** the editor with fewer than three points or no name, **When** the administrator looks at Save, **Then** it is disabled and says what is missing.
5. **Given** points placed in the editor, **When** the administrator presses Undo last point or Clear, **Then** the last point or all points are removed and the point count shown follows.
6. **Given** a saved zone, **When** the administrator presses Delete, **Then** an inline question appears ("its log stays; the camera stops watching this area"); only a second confirmation deletes it, and its old entries are still readable.
7. **Given** a zone is paused, **When** anyone opens the page, **Then** the card and the detail say who paused it and when, and no new entries open for it.
8. **Given** a zone's detail with the period set to Today or 7 days, **When** the operator reads the log, **Then** each entry shows time and duration (or "inside now"), the newest three entries of the camera have Watch clip, and older entries say "No clip kept".
9. **Given** a zone set to alert after 10 seconds, **When** someone is inside for 4 seconds and leaves, **Then** the entry is logged but no alert is sent.
10. **Given** a zone set to Outside working hours, **When** someone enters during working hours, **Then** nothing is logged.
11. **Given** the owner's existing whole-camera zones from before this change, **When** the new version first starts, **Then** each appears as a zone covering the whole picture, named after its camera, with the same on/off state and the same history.

### Edge cases

- Camera offline: the card says so, the chip must not read "Zone clear", and the page must not imply the area is being watched.
- The person detector is not running: the page says so plainly with the reason. An empty log is never shown as "nobody entered".
- Two zones on one camera, and one person inside both: each zone logs its own entry. A camera records one clip at a time, so the second entry says "No clip — recorded under the other zone's entry" rather than offering a clip of its own; the camera still keeps only its last three clips between them.
- A person steps in during the minute after leaving: it continues the same incident and sends no second alert (existing one-minute rule).
- A drawn area that crosses itself or is almost a line: Save is refused with a plain reason.
- Camera picture unavailable while drawing: the editor says so and does not let the user save blind.
- The camera's picture size or rotation changes after saving: the area still sits on the same part of the scene, because it was stored relative to the frame.
- Nothing has happened yet: the log says nothing has been detected since start, which differs from unavailable.
- Pause pressed while someone is inside: the open entry closes and keeps what it has.
- Clips are being written while more cameras are busy: detection on every camera keeps its normal pace (see SC-006).

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all six: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx, 026 5xx, 027 6xx.

- **P14-FR-401**: Zones MUST be drawn polygons on one camera's picture, with at least three points. Several zones may share a camera, and a camera may have none.
- **P14-FR-402**: A zone's points MUST be stored and sent as fractions of the frame (0 to 1), never as pixels.
- **P14-FR-403**: A person counts as inside when the point at their feet is inside the polygon. Body overlap alone MUST NOT count. The editor MUST tell the user to draw on the floor, not the wall.
- **P14-FR-404**: Each zone MUST show a status: Person in zone, Zone clear, or Paused; plus in zone now and entries today. A camera that is offline or a detector that is down MUST show that instead of Zone clear.
- **P14-FR-405**: The page MUST show four tiles: in zone now, entries today (noting that the latest three clips per camera have a clip), zones watching, and paused.
- **P14-FR-406**: Pausing a zone MUST be visible to every signed-in user, with who paused it and when, and MUST stop new entries for that zone only. A paused zone and its history MUST stay listed.
- **P14-FR-407**: Each zone MUST have a "Watched" rule: Always, Outside working hours, or Custom hours (from, to; may cross midnight). Working hours come from Settings.
- **P14-FR-408**: Each zone MUST have an alert timing: the moment someone steps in, or after N seconds inside. Entries are logged and recorded either way; the timing decides only when the alert goes.
- **P14-FR-409**: The zone detail MUST show the event log for Today or the last 7 days. Each entry shows its time and its duration, or "inside now", and notes when it was cut at the maximum clip length.
- **P14-FR-410**: Watch clip MUST play the recorded scene for entries whose clip was saved, among the latest three clips of each camera. Older entries stay in the log marked "No clip kept". No entry may ever lead to another scene's clip or to a dead button. Log entries are never deleted.
- **P14-FR-411**: The editor MUST let the user place points by clicking on the live camera picture, undo the last point, clear all points, and see the point count. Save MUST stay disabled until there is a name and at least three points, and MUST refuse a shape that crosses itself.
- **P14-FR-412**: The editor MUST offer: name, camera, watched rule, alert timing, and Notify In-app and Email. Who receives email is set in Settings, and the editor says so.
- **P14-FR-413**: Delete MUST ask inline first. Deleting a zone MUST keep its log; the camera simply stops watching that area.
- **P14-FR-414**: The camera choice in the editor MUST list only cameras the system really has, and MUST NOT require any other feature to be switched on for that camera, nor change how any other feature behaves. Zones and stations on a camera share the person detector without needing each other.
- **P14-FR-415**: Existing whole-camera zones MUST carry over as a full-frame zone named after their camera, keeping their on/off state, history and clips. Nothing the owner already recorded may disappear.
- **P14-FR-416**: Drawing, saving, pausing, resuming and deleting a zone MUST be allowed only to accounts permitted by the server, and each MUST be written to the audit trail before it takes effect. Everyone signed in may view. Only administrators may draw, edit, pause, resume or delete a zone (owner decision, 10 Nov 2026; spec 022, P14-FR-115).
- **P14-FR-417**: Scene timing from the current feature stays: a person must remain two seconds before anything is written, a gap under five seconds does not split a visit, and a camera must be empty a full minute before the next person is a new incident (earlier ones are continuations that send no second alert).
- **P14-FR-418**: A new, edited or deleted zone MUST take effect on the next frames without restarting the system.
- **P14-FR-419**: Every zone's polygon, name and settings MUST survive a restart. If zones cannot be read at start, the page MUST say so, not show an empty list.
- **P14-FR-420**: Saving clips MUST NOT delay or drop detection on any camera. Clips are encoded without a hardware encoder on the Jetson, so the load must be shared fairly.
- **P14-FR-421**: Under Arabic the page, the editor and all counters MUST mirror correctly, and drawing on the picture is unaffected by direction.
- **P14-FR-422**: Notify choices on a zone MUST feed the same alert delivery as the Settings row "Restricted area entered". Owner decision, 10 Nov 2026: a zone's own In-app / Email choice decides for that zone; the Settings row is only the default a new zone starts with. This amends spec 013, which had no per-zone rules.

## Success Criteria

- **SC-001**: An administrator can draw, name and save a zone in under a minute, and the card appears with the polygon on the right place of the picture.
- **SC-002**: A person walking into a drawn area produces a log entry within 5 seconds; a person walking beside it, with feet outside, produces none.
- **SC-003**: Pausing a zone shows "Paused by {name} · {time}" to a second signed-in user without a refresh longer than a few seconds, and no entry opens while it is paused.
- **SC-004**: On the recorded walk-through clip, a polygon matching the clip's labelled desk area logs entries at the 12 marks labelled as events and none at the 9 labelled as negatives; and a full-frame polygon logs the same scenes as today's whole-camera zone on that clip.
- **SC-005**: After the first start on the new version, every previous whole-camera zone shows as a full-frame zone with the same history, and zero clips are lost.
- **SC-006**: **On the Jetson**: with zones drawn on every camera the owner will connect, and clips being saved, a person entering a zone is logged within 5 seconds, no camera's detection rate falls below its configured rate for longer than a few seconds, and total memory use stays within the 8 GB the CPU and graphics share. Nothing about zones needs a Windows-only part.
- **SC-007**: The same drawing, saved on the Windows development PC and loaded on the Jetson, lands on the same place of the picture.
- **SC-008**: An operator can tell within 2 seconds whether a zone card shows a clear area, a person inside, a pause, or a broken detector.

## Out of scope

- Work stations: they reuse the editor specified here, and are specified separately.
- Alert delivery channels and rules in Settings, and who may change them.
- Counting how many people are in a zone beyond this page's own numbers; no de-duplication across cameras.
- Telling who is in a zone. A zone says someone is there, never who.
- More than three clips per camera; editing or deleting log entries.
- Zones that span more than one camera.
- Hardware video encoding on the Jetson (none exists).

## Constitution check

- **No fake data (rule 4)**: the design's zones, names, entries and clips are mock. The page shows only real zones; unavailable states say why.
- **Geometry (rule 6)**: P14-FR-402.
- **Feature independence (rule 9)**: zones share the person detector's output and need no other feature on (P14-FR-414).
- **Honest degradation (rules 7, 8)**: offline camera, stopped detector and unreadable zone list are shown as page content, never a server error.
- **Truthful precision (rule 5)**: "in zone" is a feet-point test on one camera; nothing here claims a person count across cameras.
- **No delete of history**: zones may be deleted, their log may not.
- **Audit before write**: P14-FR-416.
- **Face vs clothing (rule 1) and tracking (rule 2)**: zones name nobody and store no identity.
- **Server-side permissions**: the interface hides, the system decides.

## Assumptions

- The new design supersedes the earlier "no schedules" decision (P4): zones have Watched rules. Confirmed by the owner, 10 Nov 2026.
- "Outside working hours" means the hours set in Settings, outside which the zone is watched.
- The latest-three-clips rule stays per camera, not per zone.
- A full-frame zone is how an old whole-camera zone is expressed now; no special case remains.
- The bootstrap file already describes some polygon zones (with their own schedules, including weekdays). They are imported once as drawn zones and the database owns them from then on, as for every other setting; their schedules map onto the Watched rule as closely as it allows, and anything that does not fit is reported, not silently dropped. To be confirmed in the plan.
- Entries today count scene entries in site-local time, not individual people.
- A zone with a delay of zero alerts as soon as the scene is confirmed after the two-second check.
- The Jetson runs the engine, the models, the cameras and the console window together; the owner continues to develop on a Windows PC.
