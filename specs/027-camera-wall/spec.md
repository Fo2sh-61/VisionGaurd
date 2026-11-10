# Feature Specification: Cameras page and full-window camera wall

**Feature Branch**: `027-camera-wall`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: User description: "Console v2, area Cameras: a grid of live camera tiles (2×2, 3×3, 4×4) with filter chips and search; a single-camera full-screen view with previous/next, a strip of the others, the stream address and Record; and a full-window camera wall that pages through the current filter. Must run on the Jetson Orin Nano without slowing detection." Source: `design/console-v2/HANDOFF.md`, section "Cameras". This is P14 (console v2).

> Every number, camera name, plate and reading in the design is mock data. None of it is a fixture here.

## Why this feature

Today the operator can open one camera at a time, or scroll a long page of tiles with no way to
say "show me only the gates" or "show me what has lost signal". With a site of about 40 cameras
next, finding the right picture is slow, and nobody can leave a screen on a wall and trust it.

After this feature an operator can narrow the cameras by what they watch for, find one by name
or area, see at a glance which pictures are live, stale or missing, open one camera large, and
put the whole current selection on a dark full-window wall that pages through every camera.

## User Scenarios & Testing

### Primary story

A guard at a residential compound sits down at the desk screen. On Cameras they pick **Car
plates** and a 3×3 grid; each tile shows the camera's name, a Live badge, the feature it
serves and its current reading (for a gate, the last plate read). One tile says **No signal**
and shows its last picture, clearly marked as old. They press **Full screen**: the window
turns into a dark wall of the same cameras, with the count of cameras up and alerts waiting
along the top. An amber ring appears round a gate tile when an unknown plate is read. They
press the right arrow to see the next page, click that tile to open the camera large, then
press Escape to come back.

**Acceptance scenarios**

1. **Given** the Cameras page, **When** the operator picks 2×2, 3×3 or 4×4, **Then** the grid
   changes to that many tiles per page and a pager appears when there are more cameras than
   fit.
2. **Given** filter chips All, Attendance, Population, Car plates, Restricted zones, Work
   stations and No signal, **When** the operator picks one, **Then** only cameras doing that
   job (or, for No signal, cameras without a picture now) are shown, and each chip shows how
   many cameras it holds.
3. **Given** the search box, **When** the operator types part of a camera name or area,
   **Then** the list narrows to matching cameras within the current filter.
4. **Given** a tile, **When** it is shown, **Then** it carries the camera name, whether it is
   Live, Stale or No signal, the feature it serves, and the current reading for that feature;
   a reading the engine cannot give is shown as unavailable with a reason, never as zero.
5. **Given** a tile, **When** the operator opens it, **Then** the single-camera view shows the
   large picture, the camera's stream address, Previous and Next within the current filter, a
   strip of the other cameras, and Record.
6. **Given** a camera with no signal, **When** it is opened, **Then** the last picture received
   is shown with a plain statement that it is the last frame and when it arrived, not a live
   view, and Record explains that it cannot start. Administrators and IT may both record (owner
   decision; spec 022, P14-FR-115) — for IT this is new: today recording is an
   administrator write.
7. **Given** the operator presses Record, **When** it starts, **Then** it says recording began
   at that moment and nothing earlier is kept; pressing it again stops it; the result is a
   real saved clip or a plain failure with the reason.
8. **Given** the operator presses **Full screen**, **When** the wall opens, **Then** it fills
   the window with the current filter and search, shows a top bar (title, cameras up, alerts
   waiting, clock, grid size, pager, Exit), and each tile shows only the name, Live / Stale /
   No signal, the feature and the reading.
9. **Given** the wall, **When** a gate tile reads an unknown plate or a station is away,
   **Then** that tile has an amber ring; **When** a person is in a restricted zone or a station
   is absent past its limit, **Then** it has a red ring.
10. **Given** the wall, **When** the operator presses Escape, the left or right arrow, or
    clicks a tile, **Then** it exits, changes page, or opens that camera's single view on top.
11. **Given** an IT account, **When** it opens any tile or the wall, **Then** it sees pictures
    and camera state but no person names, attendance status or people counts by identity.
12. **Given** the wall is open on the Jetson with every camera feature running, **When** the
    detection rate is measured with and without the wall open, **Then** it is the same.

### Edge cases

- **No cameras at all**, or **no camera matches the filter**: two different plain messages;
  the first points to camera setup, the second offers to clear the filter.
- **The engine is not reachable**: the page says so; it does not show an empty grid as if there
  were no cameras.
- **A reading subsystem is not running** (for example plates): the tile says that reading is
  unavailable and why; the picture still shows.
- **A picture is slow or frozen but the camera is not yet counted as down**: the tile says
  Stale, with how old, and is never marked Live.
- **A camera has no feature selected**: the tile shows the picture and "no analysis", not a
  blank reading.
- **A camera drops while the wall is open**: its tile changes to No signal on its own, and the
  count in the top bar follows.
- **Forty or more cameras**: pages, not scrolling; the wall never tries to play every camera at
  once.
- **A filter or page that shrinks while the operator is on a later page**: the wall returns to
  the last page that exists.
- **Arabic**: pager, arrows and bar read right to left; times and counts stay left to right.
- **The stream address contains a password**: it is never shown in full.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all six: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx, 026 5xx, 027 6xx.

Numbered `P14-FR-6xx`. Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Grid, filters and search

- **P14-FR-601**: The Cameras page MUST offer grid sizes 2×2, 3×3 and 4×4, page through the
  cameras when they do not fit, and remember the operator's choice for the session.
- **P14-FR-602**: The page MUST offer the filter chips All, Attendance, Population, Car plates,
  Restricted zones, Work stations and No signal, each with the real number of cameras in it.
  A camera with several features appears under each.
- **P14-FR-603**: The No signal filter MUST contain exactly the switched-on cameras with no
  current picture, so an operator can find what needs attention without scanning the grid.
  A camera switched off on purpose is not "no signal": it is shown as Switched off and is
  left out of the cameras-up total, as System Health already does.
- **P14-FR-604**: A search box MUST narrow the list by camera name or area, together with the
  filter.
- **P14-FR-605**: The camera list, its features and its counts MUST come from the configured
  cameras. The number of cameras is an input: the page and the wall MUST work for one camera
  and for about forty without any change.

### Tiles

- **P14-FR-606**: Every tile MUST show the camera name, its picture state (Live, Stale, or No
  signal), the feature it serves, and the current reading for that feature.
- **P14-FR-607**: A tile MUST be Live only when its picture is current. A picture that is
  late but younger than the point at which the engine counts the camera as down (10 seconds
  today) MUST say Stale and how old — a new state worked out from the picture's age, since
  the engine has only up and down; past that point it MUST say No signal and show the last
  picture received, marked as old, with when it arrived.
- **P14-FR-608**: Each tile MUST draw only the overlay of the feature it is shown for. A tile
  filtered to Car plates shows plate boxes, never tracking numbers or names. Under All, a
  camera with several features shows one identity-free overlay; a tile never falls back to
  the name-carrying face overlay.
- **P14-FR-609**: A reading MUST be what the engine holds now. Where the engine cannot give
  one (feature off, subsystem not running, no capacity set), the tile MUST say so with the
  reason; it MUST NOT show zero, a dash that looks like zero, or a placeholder.
- **P14-FR-610**: Population tiles MUST show a count only, never a percentage unless a
  capacity is set, and MUST NOT imply cameras are de-duplicated.
- **P14-FR-611**: Opening a tile MUST open the single-camera view for that camera.

### Single-camera view

- **P14-FR-612**: The single-camera view MUST show the large picture, the camera name and
  area, its features, Previous and Next within the current filter and search, and a strip of
  the other cameras in that selection.
- **P14-FR-613**: It MUST show the camera's stream address to administrators only (IT never
  sees camera addresses; spec 022, P14-FR-115), with any
  password hidden — including a password or token carried later in the address, not only
  the user-and-password part that is hidden today — and MUST NOT reveal a secret to any role.
- **P14-FR-614**: Record MUST start and stop a real recording, say at once that it keeps only
  what happens after the press, and report failure with its reason. It MUST NOT appear to
  work when the camera has no signal.
- **P14-FR-615**: For a camera with no signal the view MUST show the last picture received,
  clearly marked as the last frame with its age, and never as live.

### Full-window wall

- **P14-FR-616**: **Full screen** MUST open a dark, full-window wall of the current filter and
  search, in the grid size chosen, paged when needed.
- **P14-FR-617**: The wall's top bar MUST show the title (page and filter), cameras up of
  total, alerts waiting, the real clock, grid size, pager (position of total pages), and Exit.
- **P14-FR-618**: Wall tiles MUST show only the name, picture state, feature and reading; for
  gate cameras the reading is the last plate as a plate chip.
- **P14-FR-619**: A wall tile MUST have an amber ring for an unknown plate or a station whose
  person is away, and a red ring for a person in a restricted zone or a station absent past
  its limit. A ring MUST come from a real event and MUST clear when the cause clears.
- **P14-FR-620**: Escape MUST exit the wall; left and right arrows MUST change page; clicking
  a tile MUST open the single-camera view on top of the wall.
- **P14-FR-621**: The wall MUST be fully usable by keyboard, and MUST remain readable from a
  distance (large name and reading, not colour alone: a ring is also named in text).

### Showing the wall must not hurt analysis

- **P14-FR-622**: Showing the Cameras page or the wall MUST NOT slow, pause or reduce any
  camera's analysis; no operator action, number of tiles or page change may cost a
  detection, a read or an alert. Today, looking at a camera's boxes raises that camera's
  analysis rate for a few seconds; grid and wall tiles MUST NOT do this, or sixteen tiles
  would raise sixteen cameras at once. Opening a single camera may, as today.
- **P14-FR-623**: Only the tiles on screen MAY ask for pictures, and the demand MUST stay
  bounded however many cameras exist; a tile that leaves the screen stops asking.
- **P14-FR-624**: On the target box (Jetson Orin Nano, shared 8 GB memory, hardware decode, no
  hardware encode) a full 4×4 wall with all features running MUST keep detection rate and
  alert time within a stated tolerance of the same system with the wall closed, and MUST fit
  in the memory left over. The tolerance is set when measured.
- **P14-FR-625**: When the box is short of resources the wall MUST lower picture rate or
  size first and say so on the tile, and never lower analysis.
- **P14-FR-626**: Recording from the single-camera view MUST be reported to the operator as
  costing processor time on this box, and MUST NOT run unless asked for.

### Roles, language and honesty

- **P14-FR-627**: A tile, strip or wall MUST show only what the viewer's role may see. IT sees
  pictures, state and non-identity readings; it MUST NOT see names, attendance status or
  identity-based counts, and the engine MUST refuse them, not only the console hide them.
  Today an IT account can ask any camera for its face boxes, which carry names; closing
  that is new engine work, and because permissions are decided by address, the plan must
  find an address-based way to do it.
- **P14-FR-628**: Alerts waiting on the wall MUST be the number of open items in Home's
  Needs your attention (the same list as the sidebar's "N things need attention"), and
  MUST be marked unavailable if the count cannot be read.
- **P14-FR-629**: Wording, directions and number formats MUST follow the chosen language,
  including right-to-left layout.
- **P14-FR-630**: If a part of the page cannot load (cameras, readings, alerts), it MUST say
  so on that part and the rest MUST keep working.

## Success Criteria

- **SC-001**: An operator finds a named camera among 40 in under 5 seconds using filter and
  search.
- **SC-002**: Every camera without a current picture is in the No signal filter, and no tile
  claims Live while its picture is older than the stated limit.
- **SC-003**: Unplugging a camera turns its tile to No signal, with its last picture marked as
  old, within the time System Health already uses, and the top-bar count follows.
- **SC-004**: On the Jetson, a 4×4 wall paging across 40 cameras with all features on leaves
  detection rate and alert time within the tolerance fixed under P14-FR-624, measured with the
  wall open against closed.
- **SC-005**: Escape, the arrow keys and tile clicks behave as listed, and nothing shown on
  the wall or Cameras page is a fixture.
- **SC-006**: An IT account opening every tile and the wall sees no person name or attendance
  value, and a direct request for one is refused.
- **SC-007**: The wall shows the same cameras-up number as the top bar and the same
  alerts-waiting number as Home's Needs your attention.

## Out of scope

- Shell, roles, language switch and System Health (spec 022).
- Attendance and people pages, enrolment (spec 023).
- Car plates page and the plate reader (spec 024); the wall only shows its last read.
- Restricted zones: drawing, schedules, alerts (spec 025); the wall only shows its ring.
- Work stations: drawing, rules, timelines (spec 026); the wall only shows its ring.
- Adding, editing or removing cameras (camera setup), and changing which features a camera runs.
- Recorded playback, clip search, PTZ control, audio, picture-in-picture, saved layouts or
  custom wall arrangements, and a second monitor.
- Cross-camera counting without double counting; any new model.

## Constitution check

- **I, Real-time:** stale and missing pictures are named, never Live (P14-FR-607, -615).
- **II, Isolation:** a tile draws only its own feature's overlay (P14-FR-608); viewing is
  separated from analysis (P14-FR-622 to -625).
- **III, Truth:** no fixtures; unavailable readings say why; no capacity means no percentage;
  counts are not claimed de-duplicated (P14-FR-609, -610, -628).
- **IV, Security:** the engine enforces what IT may see; the stream address never leaks a
  password (P14-FR-613, -627).
- **V, Complete:** empty, error and partial states are specified; Record is real or refuses.
- **Scale:** camera count is an input, about 40 expected, 208 the target (P14-FR-605, -623).

## Assumptions

- "Cameras up" and "alerts waiting" use the same sources as the top bar and Home.
- A camera's filter membership comes from its configured features.
- No signal uses the same 10-second rule System Health already uses; Stale is the new,
  shorter band before it.
- Grid size and the chosen filter are remembered per operator session only.
- Recording is the existing start/stop recording; on the Jetson it encodes on the processor.
- Existing tile pacing (only on-screen tiles ask, fixed shared budget) is kept as the base.
- Wall ring colours and Live/Stale/No signal text are meant as a pair; a ring is never the only signal.
- IT sees plate text and plate chips on tiles and the wall (owner decision; spec 022, P14-FR-115).
- **[NEEDS CLARIFICATION: When picture demand must be cut on the Jetson, what is the lowest picture rate an operator will accept on the wall before it should show fewer cameras per page instead? The owner will decide once the Jetson soak test has measured it.]**
