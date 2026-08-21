# Feature Specification: Track a person — past paths and live catching, rebuilt

**Feature Branch**: `003-track-person-ux`
**Created**: 2026-08-21
**Status**: Draft
**Input**: User description: "Finish the track person page. The UX for selecting who and when to track must be easier and simpler. Two choices: select a time window to search someone's path in saved footage, or catch someone live over the cameras. ~208 cameras; continuous recording is a hardware headache, so use the DVRs' 30 days of stored video and fetch only what is needed. End-to-end wait 5–10 seconds. Live: show all cameras, click a person to track, optional recording with manual stop or timer. Tracking does not depend on face recognition, but a sustained high-confidence face may name the tracked person."

All design decisions below were settled in discussion with the owner on
2026-08-21; each is marked where it constrains the feature.

## Why this feature

The Track page's engine is real but the page is the worst UX in the console:
choosing who and when to track is clumsy, the clip save writes nothing, and
there is no way at all to point at a person on a live camera and say "follow
them". Meanwhile the two questions an operator actually has — *where did this
person go?* and *where is this person right now?* — are both answerable with
what the system already stores and streams. This feature rebuilds the page
around those two questions and nothing else.

## User Scenarios & Testing

### Primary story

An operator opens Track and picks one of two modes. **Where did someone go**:
they type a name (or open a camera's saved footage and click an unknown
person), and the person's day appears instantly as a chain of confirmed
stops — the moments a camera was genuinely sure it saw them. Clicking a stop
plays that moment's video within seconds, the person highlighted, and playback
keeps flowing like a streaming video while the system quietly fetches what
comes next. **Where is someone now**: they pick an area, pick a camera, and
click a person on the live picture — the person is now tracked across
cameras, optionally recorded, and if a camera ever gets a sustained clear
look at their face, their name appears on the track.

**Acceptance scenarios**

1. **Given** an enrolled person and a chosen day and time window, **When** the
   operator asks for their path, **Then** the chain of confirmed stops
   appears within ~3 seconds without touching any stored video, and every
   stop can state its evidence (how sure, how long, how many confirmations).
2. **Given** a path on screen, **When** the operator clicks a stop, **Then**
   only that stop's footage is fetched and the clip starts playing within
   10–15 seconds with the person highlighted, and keeps playing without
   stalling while later chunks load in the background.
3. **Given** a person who is not enrolled, **When** the operator opens a
   camera's saved footage at a time, scrubs, and clicks the person, **Then**
   the system follows them forward hop by hop, each hop's first frames
   arriving within 10–15 seconds.
4. **Given** a wide search ("this window, many cameras"), **When** the
   operator asks for it, **Then** the page states the estimated wait before
   anything runs, refuses politely if it exceeds the device's measured
   budget, and otherwise runs it in the background with real progress and
   hits appearing as they are found.
5. **Given** the live grid, **When** the operator picks an area, a camera,
   and clicks a person, **Then** that person is tracked from that moment,
   across cameras, with no name shown.
6. **Given** a tracked person whose face is then seen clearly, close, and
   sustained — not one lucky frame, **When** the identification passes the
   same bar path anchors use, **Then** the name attaches to that one unbroken
   track, and disappears the instant the track is lost.
7. **Given** a tracked person being recorded, **When** the operator stops
   manually, the timer expires, or the track is lost, **Then** recording
   stops with the reason shown, having produced one clip segment per camera
   the person passed through.

### Edge cases

- Footage for a stop has expired or the DVR is unreachable: the stop stays on
  the path, the clip area says footage is unavailable and why. The skeleton
  never depends on the video behind it.
- The window contains no confirmed stops: the page says so plainly and offers
  the hop-by-hop start or a background sweep — an empty path is an answer,
  not an error.
- The tracker loses the person mid-recording (crowd, occlusion, camera gap):
  recording stops, the segments so far are kept, and the status says the
  track was lost — never a recording that silently follows the wrong person.
- Two people cross and the tracker cannot be sure it kept the right body: the
  track is treated as broken — the name drops. A wrong name that survives a
  swap is the exact failure this system exists to avoid.
- The clicked person leaves the camera before tracking locks on: the page
  says so and the click can be retried.
- A live tile's camera is down: the tile shows NO SIGNAL as everywhere else;
  it can still be clicked to see status, but not to start a track.

## Requirements

- **TRK-FR-001**: The page MUST offer exactly two modes — *where did someone
  go* (past) and *where is someone now* (live) — switchable in one control.
- **TRK-FR-002**: Face recognition MUST run as a low-rate patrol on every
  camera (owner decision). A recognition becomes a **path anchor** only when
  all gates pass: strong score, no close runner-up, face at or above the
  measured size floor, sustained across several frames over seconds, and
  confirmed again after a gap. Gate *numbers* are calibrated per camera tier
  so corner cameras genuinely can anchor (owner: "don't make it so hard");
  gate *structure* never bends. The decision is made at recognition time and
  each anchor stores its evidence. **Missing legs are better than wrong
  legs** — nothing below the bar is ever drawn.
- **TRK-FR-003**: An enrolled person's path skeleton MUST appear within ~3
  seconds from stored anchors alone, video untouched. Anchor stops are
  face-identified (green); anything stitched between them by body matching is
  appearance-only (blue) and never named by the stitching (constitution
  rule 1).
- **TRK-FR-004**: Opening a stop MUST fetch only that stop's footage, in
  chunks, first frames within 10–15 seconds, and MUST buffer ahead so
  playback does not stall once started (owner: "like YouTube").
- **TRK-FR-005**: While a stop plays, the system MUST pre-fetch where the
  person plausibly appears next: the next anchor's camera when one exists,
  otherwise the physically adjacent cameras from the camera-adjacency map.
  The adjacency map's configuration UI is a separate future spec; until it
  exists the fallback is the same area (owner decision).
- **TRK-FR-006**: A person who is not enrolled MUST be trackable by opening
  any camera's saved footage within retention, scrubbing to a moment, and
  clicking them — then followed hop by hop, each hop within 10–15 seconds.
- **TRK-FR-007**: A wide sweep MUST state its estimated wait before running,
  MUST be refused above a cap derived from the device's measured speed
  (roughly 15 minutes on today's machine — the number tracks the hardware,
  never hard-coded), and MUST run in the background with honest progress,
  hits appearing as found, and a working cancel.
- **TRK-FR-008**: Every past search — skeleton build, hop, sweep — MUST write
  its audit entry before returning results (constitution rule 11). Starting
  a live track, and starting or stopping a recording, MUST be audited too:
  following a named person is surveillance and reads like it.
- **TRK-FR-009**: The live view MUST show every camera as live tiles,
  partitioned by area, paged, and searchable by area or camera name. A tile
  is a real stream or an honest NO SIGNAL, never a stale frame as live.
- **TRK-FR-010**: Clicking a person on an enlarged live camera MUST start
  tracking them from that moment. Detection activates on that camera on
  demand — no always-on tracking across 208 cameras — and the track follows
  the person across cameras.
- **TRK-FR-011**: A live track is anonymous until a face identification
  passes the same bar as a path anchor. The name then annotates **that one
  unbroken track**, drops the instant the track is lost, and reattaches only
  through a fresh identification. A name is never stored on a body and never
  carried across a track break (constitution rule 2, owner decision).
- **TRK-FR-012**: While tracking, the operator MUST be able to record:
  following the person across cameras, one clip segment per camera. Stopping
  is manual, by timer, or forced by track loss — each with its reason shown.
- **TRK-FR-013**: Stored video MUST only ever be fetched on demand, per
  question asked. The system never records continuously; the DVRs' 30-day
  retention is the archive (owner decision). Unavailable footage degrades
  the clip, never the path.
- **TRK-FR-014**: Every wait MUST be honest: real progress, estimates from
  measured device numbers (DVR fetch speed, processing rate), and no spinner
  that pretends a long job is short. The measurements are taken on the
  target machine, not assumed.
- **TRK-FR-015**: Camera setup MUST gain an "installed for faces" flag
  beside the existing required area, driving each camera's patrol tier
  (face-level cameras patrol harder on their main stream; corner cameras
  patrol lightly on their substream).

## Success Criteria

- **SC-001**: An enrolled person's path skeleton is on screen within 3
  seconds of asking, on the reference machine.
- **SC-002**: A clicked stop's video is playing within 15 seconds (target
  10), and once playing does not stall on the reference clip set.
- **SC-003**: Zero wrong legs by construction: every drawn stop carries
  stored evidence passing every anchor gate — verifiable in tests without a
  camera.
- **SC-004**: Reaching a live track is three clicks: area → camera → person.
- **SC-005**: A name never appears on a live track without an anchor-grade
  identification, and never survives a track break — both pinned by tests.
- **SC-006**: No sweep starts without its estimate shown; none exceeds the
  device budget; a cancelled sweep stops.
- **SC-007**: A recording produces one playable segment per camera the
  person crossed, and its stop reason (manual, timer, track lost) is shown.

## Out of scope

- The camera-adjacency configuration UI ("which camera is next to whom") —
  its own spec under the config section; this feature only consumes the map
  with same-area as fallback.
- Tracking more than one person at a time per operator.
- Continuous recording of any camera by this system.
- Changing the face model, thresholds architecture, or DVR retention.
- Exporting evidence bundles from a track (later work).

## Constitution check

- **Face names, clothing follows (rule 1)**: anchors are face-made and green;
  body-stitched segments are blue and nameless. The two never merge.
- **No stored bindings (rule 2)**: the live name lives exactly as long as one
  unbroken observation and dies with it. Nothing is carried forward.
- **Nothing untrue (rules 4, 5)**: missing legs beat wrong legs; anchors
  carry evidence; waits show measured estimates; the sweep cap moves with
  the hardware instead of pretending a number.
- **Honest degradation (rules 7, 8)**: expired footage degrades a clip, not
  a path; a down camera is NO SIGNAL; a lost track says so.
- **Audit before result (rule 11)**: all past searches, live track starts,
  and recording starts/stops are audited first.

## Assumptions

- "Time zone" in the request means a **time window** (date plus start and
  end) — confirmed by the discussion.
- Recording timer presets: 1, 5, and 10 minutes plus manual stop.
- DVR export speed and on-device processing rates are unknown until
  measured; measuring them is the plan's first task, and the 10–15 second
  and 15-minute figures are targets to validate against those measurements,
  not promises made blind.
- The existing area field on cameras is the partitioning for the live grid;
  cameras added later must always carry one.
- Live streams are display-cheap at scale; the costly part is inference,
  which this design runs only on demand or as low-rate patrol.
