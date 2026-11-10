# Feature Specification: Work Stations — areas that must stay staffed

**Feature Branch**: `026-work-stations`
**Created**: 2026-11-10
**Status**: Draft
**Input**: User description: "Console v2 HANDOFF, 'Work stations' — a new feature, engine and page. An administrator draws a work station on a camera picture. The system tells the operator whether somebody is standing in it, how long it has been empty, and raises an alert when it stays empty past a limit. Optionally a station belongs to one named person, recognised by face." Part of P14 (console v2). The whole system, models and cameras included, now runs on an NVIDIA Jetson Orin Nano under Ubuntu, while development stays on Windows.

## Why this feature

A reception desk, a security booth or a control room is only useful while somebody is in it.
Today VisionGuard can say someone walked into a place that must stay empty (Restricted zones), but nothing says that a
place that must stay staffed has been left empty. A supervisor finds out by walking over.

After this feature an administrator marks the floor area of a post on a camera picture, says
when it matters and how long empty is too long. The operator sees every post at a glance —
staffed, away, or empty past its limit — with today's working time, absence time and a
timeline, and is told when a post has been left empty too long.

## User Scenarios & Testing

### Primary story

An administrator opens Work stations and draws the reception desk on the camera that looks at
it. They leave the assigned person blank, sets "alert when empty for more than 5 minutes" and
chooses working hours. Through the day the card for Reception reads **On station**, and its
timeline fills with green. At 11:20 the receptionist walks away: the card turns **Away**. At
11:25 it turns **Absent — alert**, one alert appears in the feed, and the event log says
"Absence alert — over 5 min". An IT user opens the station, reads the times, and presses
**Acknowledge alert**. When somebody sits down again the card goes green and the log says
"At station".

**Acceptance scenarios**

1. **Given** a station with no assigned person, **When** anyone stands in its area, **Then**
   it reads On station and working time grows.
2. **Given** a station that was staffed, **When** nobody has been inside for the whole
   confirmation period, **Then** it reads Away and "Left station" is logged at the moment
   the last person was seen, not when the absence was confirmed.
3. **Given** a station that is Away, **When** it has been empty longer than its limit,
   **Then** it reads Absent — alert, one "Absence alert — over N min" is logged, and one
   alert is raised — and no second alert while the same absence continues.
4. **Given** an alert, **When** an administrator or IT user presses Acknowledge alert,
   **Then** the acknowledgement is audited before it is saved, the log shows who and when,
   and the card still reads Absent until somebody returns.
5. **Given** a station assigned to a named person and a camera that resolves faces, **When**
   somebody else stands in it, **Then** it does not read On station. **When** the assigned
   person walks in, **Then** it does, because they were recognised in that moment.
6. **Given** that person leaves and a stranger takes the spot, **When** the stranger stands
   there, **Then** it reads Away, never On station: nothing remembers who was there before.
7. **Given** a station assigned to a person on a camera too far away to read faces,
   **When** the operator opens or edits it, **Then** a plain warning says faces cannot be
   read at this distance and that anyone standing there counts.
8. **Given** the time is before the station's watched hours, **Then** the card reads Not
   started with "opens 9:00", no time is counted and no alert can be raised.
9. **Given** a signed-in IT user, **When** they try to draw, edit or delete a station,
   **Then** the system refuses; they may view and acknowledge alerts.

### Edge cases

- **A missed frame is not leaving.** The person detector loses a standing person for a
  second or two routinely. A brief gap changes nothing — the card stays On station, no
  event is logged, no time is lost. Only a gap longer than the confirmation period counts
  as having left. The same applies in reverse: a person walking past the area for a moment
  is not "at station".
- **Away is not Absent.** Away means empty, but not for long: still under the limit, no
  alert. Absent means empty past the limit and an alert has been raised. The page says
  which, and states the limit.
- **Camera offline, or person detection not running.** The station reads Unknown with the
  reason, never Away or Absent — an unwatched post must not look abandoned, nor staffed.
  Time is not counted either way and no alert is raised for the gap.
- **Engine restart.** Today's totals, events and acknowledgements survive. The period the
  engine was down is shown on the timeline as not watched, never as staffed or absent.
- **Hours change or end mid-absence.** An absence ends where the watched hours end; it is
  not carried to the next day.
- **Camera has no stations drawn.** The page says so and offers Draw a station; no demo
  stations appear.
- **Assigned person deleted from the directory.** The station says its assigned person no
  longer exists and falls back to "anyone counts", with the notice.
- **Two people in the area.** Still one station, still On station; the count is not shown.
- **Station on a camera that also has a restricted zone.** Independent; neither needs the
  other.
- **Nothing happened yet today.** An empty log says nobody has been seen since the working
  day began, which differs from unavailable.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all six: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx, 026 5xx, 027 6xx.

Numbered `P14-FR-5nn` (console v2). Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Stations and drawing

- **P14-FR-501**: An administrator MUST be able to create, edit and delete a station on any
  camera. A station has a name, a camera, a floor area, when it is watched, an optional
  assigned person and an empty-time limit in minutes. Several stations may share a camera.
- **P14-FR-502**: The floor area MUST be drawn and edited in the shared area editor
  specified in `specs/025-polygon-zones/spec.md`, and MUST NOT be specified again here. A
  person counts as inside when the point where their feet meet the floor is inside the
  area. Geometry MUST cross the system as fractions of the frame.
- **P14-FR-503**: The station form MUST offer exactly these station-only fields: the
  assigned person (optional, with a note on how far faces can be read) and "alert when
  empty for more than N minutes". Save MUST stay disabled until the shared editor's own
  conditions are met.
- **P14-FR-504**: Deleting a station MUST stop the camera watching that area but MUST keep
  its past events and totals visible in the log.
- **P14-FR-505**: Stations MUST survive a restart. The database is the source of truth.
- **P14-FR-506**: Drawing, editing and deleting MUST be administrator-only, decided on the
  server by what is being asked, not by what the page shows. IT may not (owner decision, 10 Nov 2026; spec 022,
  P14-FR-115).

### Watched hours

- **P14-FR-507**: Each station MUST be watched either during **Working hours**, as set in
  Settings, or during **Custom hours** (from, to). There MUST be no "Always" option.
- **P14-FR-508**: Outside watched hours a station MUST read Not started (before opening) or
  Closed (after closing), count no time, and raise no alert.
- **P14-FR-509**: Changing the working hours in Settings MUST apply to every station that
  follows them, from that moment, without a restart.

### Presence — what "on station" means

- **P14-FR-510**: By default anyone inside the area counts as staffing the station.
- **P14-FR-511**: A station MAY have one assigned person. Then only that person counts.
  Recognition MUST be by face. Clothing or body shape MUST NOT be used to decide that
  someone is the assigned person.
- **P14-FR-512**: Who is standing in a station MUST be decided afresh from the current
  picture each time. A name MUST NOT be remembered from an earlier moment, carried along
  with a body that was recognised before, or stored as "this person is at this station".
  Somebody who leaves and returns, or who walks in after somebody else left, is recognised
  again or not at all.
- **P14-FR-513**: If faces cannot be read at this camera's distance (about 80 pixels
  across), the page MUST warn the operator when the assignee is chosen and on the station
  itself, and the station MUST then count anyone, saying so. It MUST NOT show On station
  for a named person it cannot verify.
- **P14-FR-514**: If an assigned person is in the area but the face cannot be read at that
  moment, the station MUST NOT count it as the assigned person being there. After the
  confirmation period it reads Away, and the page says a person was present but not
  recognised, so the operator does not mistake it for an empty desk.

### State, time and the brief-gap rule

- **P14-FR-515**: A station MUST be in exactly one state, coloured accordingly: **On
  station** (green), **Away** (amber), **Absent — alert** (red), **Not started** (grey).
  When it cannot be known — camera offline, detector not running — it MUST read
  **Unknown** with the reason, in its own neutral colour.
- **P14-FR-516**: A station MUST change from On station to Away only after nobody has been
  seen inside for a confirmation period of a few seconds, and MUST change from Away back
  to On station only after somebody has been seen continuously for a shorter confirmation
  period. Gaps shorter than the confirmation period MUST NOT be counted as leaving, and
  momentary passers-by MUST NOT be counted as staffing. The recorded time of the change is
  the first moment of the new situation, not the moment it was confirmed.
- **P14-FR-517**: A station MUST change from Away to Absent when it has been empty longer
  than its limit, counted from the moment the last person left.
- **P14-FR-518**: For today, each station MUST show **working time** (time On station),
  **absence time** (time Away or Absent), and the **on-station rate** (working time as a
  share of watched time so far). Time the system could not watch MUST be excluded from the
  rate and shown as not watched on the timeline.
- **P14-FR-519**: The page MUST show a timeline of today in segments On station, Away,
  Absent past limit and Not watched, always left to right, also in Arabic.
- **P14-FR-520**: A station's time MUST be measured, never estimated. If part of today
  could not be measured the figures say so.

### Alerts and events

- **P14-FR-521**: When a station becomes Absent the system MUST raise one alert, once per
  absence. It MUST appear in the in-app feed and bell, and MAY be sent on any other
  channels switched on for a new alert kind "Work station left empty" in the alert rules
  of `specs/022-console-v2-shell/spec.md`. By default only In-app is on. As for zones, a station's own Notify choice in the shared editor decides for that station and the Settings row is only its starting default (owner decision for zones, 10 Nov 2026, applied to the shared editor). A second alert for
  the same absence MUST NOT be sent; a new absence is a new alert. When somebody returns,
  one more message MAY say so, as the design's wording describes.
- **P14-FR-522**: Each station MUST keep an event log with: At station, Left station,
  Absence alert — over N min, and Alert acknowledged (by whom). Events cannot be deleted.
- **P14-FR-523**: Administrators and IT users MUST be able to acknowledge a station's alert.
  The acknowledgement MUST be audited before it is saved and MUST NOT change the station's
  state or remove any record.
- **P14-FR-524**: Alert messages MUST state only facts: station, camera, how long it has
  been empty, the limit, the time. They MUST NOT contain a picture, and MUST NOT name
  anybody except, where one is assigned, the staff member the station belongs to
  (owner decision, 10 Nov 2026: naming the assigned person is wanted, e.g. "Reception
  (Ahmed) empty for 6 min").

### The page

- **P14-FR-525**: The Work stations page MUST show four tiles: staffed now, away, absent
  past limit, and the on-station rate today (average over open stations, with "of N open
  stations"). A station that is Not started, Closed or Unknown MUST NOT be counted in any
  tile; the Unknown ones are named.
- **P14-FR-526**: Each station card MUST show the camera picture with the area coloured by
  state, the name, the assignee line ("Assigned to X · recognised by face", or "Anyone at
  the station counts"), working time, absence time, the on-station rate, today's timeline,
  and "opens 9:00" while not started.
- **P14-FR-527**: The detail panel MUST show the status, the times and rate, the timeline,
  the event log, the rules (assignee, limit, schedule), **Acknowledge alert** (while an
  unacknowledged alert exists), and **Edit station** (administrators).
- **P14-FR-528**: The picture on this page MUST NOT show names or identity boxes. The only
  identity this feature uses is the assigned-person check, and it is shown as a state,
  never as a label on a body.
- **P14-FR-529**: The navigation badge for Work stations MUST count stations Absent past
  limit and show nothing at zero. Every sentence MUST appear in English and Arabic; Arabic
  wording is drafted and not yet read by a native speaker.

### Isolation, honesty and the Jetson

- **P14-FR-530**: Work stations MUST use the person detection already running for the
  camera and MUST NOT require any other feature to be switched on, nor change any other
  feature's behaviour. If the camera's person detection is not running for any other
  reason, enabling stations on it MUST start it, and the cost shown in camera setup is
  "shares the person detector".
- **P14-FR-531**: A station that fails to start MUST say so on the page and in System
  Health with the reason. An empty page on a broken detector MUST NOT read as "everybody
  is at their station" or "nobody is".
- **P14-FR-532**: No fixture, random or example station may reach the live page. The demo
  mode keeps its own.
- **P14-FR-533**: The whole feature — drawing, live state, face check for assigned people,
  timeline, alerts — MUST work when the engine runs on an NVIDIA Jetson Orin Nano under
  Ubuntu, with the models on its graphics processor and eight gigabytes of memory shared
  between processor and graphics. Face reading of an assigned person MUST not require a
  second copy of the face model beyond what attendance already uses, and the feature MUST
  state its measured cost on that machine, not an estimate. The feature MUST NOT depend on
  a hardware video encoder, which the Jetson does not have.
- **P14-FR-534**: Stations are watched at a rate of a few analyses a second per camera. The
  rate is set per camera as for every feature and the recommendation in camera setup MUST
  include stations.

## Success Criteria

- **SC-001**: An administrator draws a station on a real camera and within 5 seconds of
  someone standing in it the card reads On station.
- **SC-002**: Walking out and back within the confirmation period produces no event;
  walking out for longer produces exactly one Left station and, past the limit, exactly
  one alert — checked on the recorded footage.
- **SC-003**: With an assigned person, a second person standing in the station never
  reads On station, and the assigned person doing so does — each time they walk in,
  recognised again from that moment. A test pins that no name survives the person leaving.
- **SC-004**: On a camera where faces are too small, the warning appears when the
  assignee is chosen and the station counts anyone, saying so.
- **SC-005**: Switching the camera off or stopping person detection turns the station to
  Unknown with a reason within 10 seconds and raises no absence alert.
- **SC-006**: After an engine restart, today's totals, events and acknowledgements are
  unchanged and the downtime is shown as not watched.
- **SC-007**: An IT user cannot draw, edit or delete a station; IT
  users and administrators can acknowledge an alert; every acknowledgement and every change is in
  the audit trail before it took effect.
- **SC-008**: On the Jetson Orin Nano under Ubuntu, with the engine, its models and the
  console running together, ten stations across the cameras update their state at least
  every 2 seconds, and memory in use stays below the eight gigabytes with the figure
  reported on System Health.
- **SC-009**: The existing automated checks pass on both Windows and the Jetson.

## Out of scope

- Drawing and editing the area — specified once in `specs/025-polygon-zones/spec.md`.
- Counting how many people are in a station, or identifying anyone not assigned.
- Shift rosters, several assigned people per station, or schedules per weekday.
- Payroll or attendance-style reports for staff; the page measures posts, not people's
  hours. This is not employee attendance and does not feed it.
- An "Always" watch setting.
- Alerting parents, visitors or anyone outside the configured recipients.
- Any new model: the person detector and face model already in the system are used.
- Weapon detection or any other feature's behaviour.

## Constitution check

- **Rule 2 — recognition never tracks.** P14-FR-511 to P14-FR-514: the assigned person is a
  per-moment check on who is in the area; nothing stores or carries it, and the page never
  draws a name on a body.
- **Rule 1 — face names, clothing says "same body".** Only a face confirms an assigned
  person; clothing is never used for the assignment.
- **Rule 3 — each feature draws its own overlay.** The station picture shows stations only,
  and carries no identities.
- **Rule 4 and 5 — nothing untrue, no claimed precision.** Unknown is its own state,
  downtime is "not watched", measured times only, and faces that cannot be read say so
  rather than pretending.
- **Rule 6 — fractions.** P14-FR-502.
- **Rule 7 and 8 — degradation is payload; a failed start says so.** P14-FR-515, 031.
- **Rule 9 — no feature requires another.** P14-FR-530.
- **Rule 10 and 11** are not touched: there is no weapon or track-search path here.
- **Server-side permissions and audit before the write.** P14-FR-506, 023.
- **Minors and biometrics.** No face data is stored by this feature; the assigned-person
  check reads the existing enrolment and writes nothing.
- **Latency and the Jetson.** P14-FR-533 and SC-008 state the budget on the target machine.

## Assumptions

- Working hours come from Settings; if they are not set, a station on working hours says it
  has no hours to follow rather than guessing.
- The confirmation periods are a few seconds to leave and a shorter time to return; exact
  values are tuned on the recorded footage and held in configuration, not hard-coded.
- The Settings row "Work station left empty" is already in `specs/022-console-v2-shell/spec.md`;
  the delivery side is new: alert delivery (`specs/013-alert-delivery/spec.md`) knows five
  kinds only and must gain this one.
- Event history is kept, never deleted; today's view is the default, with earlier days
  available as the log.
- The Jetson's lack of a hardware video encoder is irrelevant here: the feature reads
  decoded frames and encodes nothing.
- The face-distance threshold of about 80 pixels is the design's figure and is to be
  confirmed against the face model on the recorded footage.
