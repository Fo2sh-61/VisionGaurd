# Feature Specification: Restricted Zones — real cameras, full-frame zones, auto-recorded clips

**Feature Branch**: `001-restricted-zones`
**Created**: 2026-08-20
**Status**: Draft
**Input**: User description: "Finish the restricted zones page to be fully ready with no bugs or fake data. The camera list with toggles shows all cameras in the current configuration, not fake ones. No orange rectangle inside a camera view — a toggled camera's entire frame IS the restricted zone. A log section shows scenes where a person was detected in a restricted zone; the system automatically records video when a person appears and stops after one second of no detection (to ride out flicker), saves the clip, and plays it from a Watch clip button. To bound storage, only the last scene is kept."

## Why this feature

The Restricted Zones page today is entirely invented: fixture cameras, drawn
polygons, and breaches that never happened. An operator cannot use it for
anything. Meanwhile the engine already detects people on every configured
camera and throws the result away. This feature makes the page real in the
simplest honest form: any camera can be marked restricted as a whole, and when
a person shows up there, the operator gets a log entry and a recorded clip.

## User Scenarios & Testing

### Primary story

An operator opens Restricted Zones and sees the cameras the system actually
has — the same ones on the Home page — each with a toggle. They switch
"Main entrance" on. When a person walks into that camera's view, an entry
appears in the detection log and the system starts recording. When the person
has been gone for a full second, the recording stops and is saved. The
operator presses **Watch clip** on the log entry and sees what happened.

**Acceptance scenarios**

1. **Given** cameras configured in the system, **When** the operator opens the
   page, **Then** the list shows exactly those cameras with their real on/off
   state — never an invented camera, never a missing one.
2. **Given** a camera toggled on, **When** one or more people appear in its
   view, **Then** a log entry appears and recording starts.
3. **Given** a recording in progress, **When** no person is detected for one
   continuous second, **Then** the recording stops, is saved, and can be
   played from the log entry.
4. **Given** detection flickers (person lost for less than a second and found
   again), **When** this happens mid-scene, **Then** the result is one
   continuous clip, not several fragments.
5. **Given** a camera toggled off, **When** a person appears in its view,
   **Then** nothing is logged and nothing is recorded.
6. **Given** an older log entry whose clip has been replaced by a newer scene,
   **When** the operator looks at it, **Then** its Watch clip control says the
   clip is no longer kept — it is disabled with that reason, never a dead
   button and never someone else's clip.

### Edge cases

- Camera offline while toggled on: the page shows the camera as offline. No
  detection is possible and the page must not imply the area is being watched.
- Person detection is not running (subsystem failed or not started): the page
  must say so plainly. An empty log on a broken detector must not read as
  "nobody entered".
- A person is already standing in view at the moment the toggle is switched
  on: the scene starts from the first detection after the toggle.
- Toggling a camera off during an active recording: the recording stops and
  saves what it has.
- The engine restarts mid-recording: whatever was safely saved remains; the
  page never lists a clip that cannot actually be played.
- No cameras configured at all: the list is empty with a plain statement, not
  demo cameras.
- Nothing detected yet: the log says nothing has been detected since the
  engine started, which is different from "unavailable".

## Requirements

- **P4-FR-001**: The camera list MUST contain exactly the cameras in the
  current system configuration. No fixture data may reach this page outside
  demo mode.
- **P4-FR-002**: Each camera MUST have a toggle. A toggled-on camera's entire
  frame is the restricted zone — there is no rectangle or polygon to draw or
  display inside the view.
- **P4-FR-003**: Toggle state MUST survive an engine restart.
- **P4-FR-004**: Changing a toggle MUST be allowed only for admins, enforced
  server-side; all signed-in roles may view the page.
- **P4-FR-005**: When one or more people are detected on a toggled-on camera,
  the system MUST create a log entry and start recording that camera.
- **P4-FR-006**: Recording MUST stop after one continuous second with no
  person detected. Gaps shorter than one second MUST NOT split or end the
  clip.
- **P4-FR-007**: A stopped recording MUST be saved and playable from its log
  entry via Watch clip.
- **P4-FR-008**: To bound storage, only the most recent scene's clip is kept
  **per camera** — a busy camera never replaces a quiet camera's clip. Log
  entries for replaced clips MUST remain listed, with the Watch clip control
  disabled and stating why.
- **P4-FR-009**: A recording MUST have a maximum length; if a person stays
  past it, the clip ends there and the log entry says it was cut at the limit.
- **P4-FR-010**: A toggled-off camera MUST remain visible in the list, and
  existing log entries MUST remain visible. Toggling off changes only whether
  new detections are treated as restricted-zone scenes.
- **P4-FR-011**: Marking a camera restricted MUST NOT require any other
  feature to be enabled on that camera, and MUST NOT change the behaviour of
  any other feature.
- **P4-FR-012**: Each log entry MUST show which camera, when (site-local
  time), how many people were seen at peak, and how long the scene lasted.

## Success Criteria

- **SC-001**: The camera list matches the system's real configuration exactly
  — verified by comparing against the cameras the Home page shows.
- **SC-002**: A person entering a restricted camera's view produces a visible
  log entry within 5 seconds.
- **SC-003**: A detection gap shorter than one second never produces a second
  clip — one walk-through with flicker yields exactly one entry and one clip.
- **SC-004**: Watch clip on the newest entry plays the recorded scene.
- **SC-005**: With no cameras toggled on, nothing is ever recorded and the
  log gains no entries.
- **SC-006**: An operator can tell within 2 seconds whether the page is
  showing real data, an empty-but-working state, or a broken subsystem.

## Out of scope

- Drawing zones inside a frame (rectangles or polygons) — the whole frame is
  the zone.
- Schedules or restricted hours — a toggled camera is restricted around the
  clock until toggled off.
- Keeping more than the most recent scene's clip per camera. (Interim rule:
  the goal is to keep clips for roughly a working day, sized against the
  storage of the real deployment machine — decided at installation, not now.)
- Notifications or alerts fanning out from a detection.
- Deleting or editing log entries from the UI.
- Durable storage of the log across restarts (P3 owns durability; see
  Assumptions for what survives today).

## Constitution check

- **No fake data (rule 4)**: this feature exists to remove the last fixtures
  from this page. Empty and broken states are stated plainly.
- **Honest degradation (rules 7, 8)**: detector down or camera offline is
  shown on the page as payload, never hidden, never a 5xx.
- **Feature independence (rule 9)**: restricted zones consume the shared
  person-detection results; no other feature needs to be on.
- **Paused zone stays visible**: toggling off never removes the camera or its
  history from any response.
- **Geometry**: no geometry crosses the API at all — the zone is the full
  frame by definition.
- **No delete**: log entries cannot be deleted; only clips are replaced, and
  that replacement is stated on the entry.

## Assumptions

- Toggling is an admin action; viewing is for any signed-in role.
- A toggled camera is restricted at all times — no schedule.
- Maximum clip length is 2 minutes; the log entry says when a scene was cut
  at the limit.
- The saved clip file survives a restart; the log is rebuilt on start from
  the clips that still exist. Entries whose clips were already replaced are
  lost on restart until P3 makes events durable — the page does not pretend
  otherwise.
- "One second of no detection" is measured continuously; the peak person
  count shown on an entry is the highest seen during the scene.
