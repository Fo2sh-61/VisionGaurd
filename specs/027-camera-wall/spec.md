# Feature Specification: Cameras page and full-window camera wall

**Feature Branch**: `027-camera-wall`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: Console v2, area Cameras: a grid of live tiles (2×2, 3×3, 4×4) with filter chips and search; a single-camera view; and a full-window camera wall that pages through the current filter. Must run on the Jetson Orin Nano without slowing detection. Source: `design/console-v2/HANDOFF.md`, "Cameras". This is P14 (console v2).

> Every number, camera name, plate and reading in the design is mock data. None of it is a fixture here.

## Why this feature

Today the operator opens one camera at a time, or scrolls a long page of tiles with no way to
say "only the gates" or "what has lost signal". With about 40 cameras next, finding the right
picture is slow and nobody can leave a screen on a wall and trust it. After this feature an
operator can filter by what cameras watch for, search by name or area, see which pictures are
live, stale or missing, open one camera large, and put the selection on a dark full-window wall.

## User Scenarios & Testing

### Primary story

A guard picks **Car plates** and a 3×3 grid. Each tile shows the camera name, a Live badge, the
feature and its reading (for a gate, the last plate). One tile says **No signal** and shows its
last picture, marked old. They press **Full screen**: a dark wall of the same cameras, with
cameras up and alerts waiting along the top. A gate tile gets an amber ring on an unknown plate.
They press the right arrow for the next page, click a tile to open that camera large, then press
Escape to come back.

**Acceptance scenarios**

1. **Given** grid size, chips and search, **When** the operator changes them, **Then** the tiles
   and pager follow, and each chip shows its camera count (P14-FR-601 to -604).
2. **Given** a tile, **When** shown, **Then** it has name, Live / Stale / No signal, feature and
   reading; a reading the engine cannot give says so with a reason, never zero (-606, -609).
3. **Given** a tile is opened, **Then** the single view has the large picture, stream address
   (administrators only), Previous / Next, a strip of the others, and Record (-612 to -615).
4. **Given** Record is pressed, **Then** it says recording began now and nothing earlier is kept;
   the result is a real clip or a plain failure with the reason (-614). Administrators and IT
   may both record (owner decision, 10 Nov 2026; spec 022, P14-FR-115); for IT this is new,
   because today recording is an administrator write.
5. **Given** **Full screen**, **Then** the wall opens with the current filter and search; Escape,
   arrows and tile clicks work; rings show unknown plates, away stations and zone breaches
   (-616 to -621).
6. **Given** an IT account opens any tile or the wall, **Then** it sees no person names,
   attendance status or identity-based counts (-627).
7. **Given** the wall open on the Jetson with all features running, **Then** detection rate is
   the same as with it closed (-622 to -625).

### Edge cases

- **No cameras**, or **none match the filter**: two different messages; the first points to
  camera setup, the second offers to clear the filter.
- **Engine not reachable**: the page says so; no empty grid pretending there are no cameras.
- **A reading subsystem is not running** (for example plates): the tile says so and why; the
  picture still shows. **No feature selected**: the picture and "no analysis".
- **A camera drops while the wall is open**: its tile turns to No signal on its own and the
  top-bar count follows.
- **Forty or more cameras**: pages, never scrolling. If the filter shrinks while on a later
  page, the wall returns to the last page that exists.
- **Arabic**: pager, arrows and bar read right to left; times and counts stay left to right.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all five: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx (zones) and 5xx (stations), 027 6xx.

Numbered `P14-FR-6xx`. Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Grid, filters and search

- **P14-FR-601**: Offer grid sizes 2×2, 3×3, 4×4; page when cameras do not fit; remember the
  choice for the session.
- **P14-FR-602**: Offer chips All, Attendance, Population, Car plates, Restricted zones, Work
  stations and No signal, each with the real camera count. A camera with several features
  appears under each.
- **P14-FR-603**: No signal MUST hold exactly the switched-on cameras with no current picture.
  A camera switched off on purpose shows as Switched off and is left out of cameras up, as
  System Health already does.
- **P14-FR-604**: Search narrows by camera name or area, together with the filter.
- **P14-FR-605**: Cameras, features and counts MUST come from the configured cameras. The count
  is an input: one camera and about forty MUST work unchanged.

### Tiles

- **P14-FR-606**: Every tile MUST show name, picture state, feature, and current reading.
- **P14-FR-607**: Live only when the picture is current. Late but younger than the point where
  the engine counts the camera as down (10 seconds today) MUST say Stale and how old; Stale is
  a new state worked out from the picture's age, since the engine has only up and down. Past
  that point: No signal, the last picture marked old, and when it arrived.
- **P14-FR-608**: A tile MUST draw only the overlay of the feature it is shown for (Car plates:
  plate boxes, never tracking numbers or names). Under All, a multi-feature camera shows one
  identity-free overlay; a tile never falls back to the name-carrying face overlay.
- **P14-FR-609**: A reading MUST be what the engine holds now. If it cannot give one (feature
  off, subsystem not running, no capacity set), say so with the reason; never zero, a dash
  that looks like zero, or a placeholder.
- **P14-FR-610**: Population tiles show a count only, never a percentage unless a capacity is
  set, and never imply de-duplication across cameras.
- **P14-FR-611**: Opening a tile opens the single-camera view.

### Single-camera view

- **P14-FR-612**: Show the large picture, camera name and area, features, Previous / Next within
  the current filter and search, and a strip of the others in that selection.
- **P14-FR-613**: Show the stream address to administrators only (IT never sees camera
  addresses; spec 022, P14-FR-115), with any password hidden, including a password or token
  later in the address, not only the user-and-password part hidden today. No role sees a secret.
- **P14-FR-614**: Record MUST start and stop a real recording, say at once that it keeps only
  what happens after the press, report failure with its reason, and with no signal say it
  cannot start, never appear to work. Administrators and IT may both record (owner decision;
  spec 022, P14-FR-115); for IT this is new, since recording is an administrator write today.
- **P14-FR-615**: With no signal, show the last picture marked as the last frame with its age,
  never as live.

### Full-window wall

- **P14-FR-616**: **Full screen** opens a dark, full-window wall of the current filter and
  search, in the chosen grid size, paged when needed.
- **P14-FR-617**: Top bar: title (page and filter), cameras up of total, alerts waiting, real
  clock, grid size, pager (position of total), Exit.
- **P14-FR-618**: Wall tiles show only name, state, feature and reading; gate cameras show the
  last plate as a plate chip.
- **P14-FR-619**: Amber ring for an unknown plate or a station whose person is away; red ring
  for a person in a restricted zone or a station absent past its limit. A ring MUST come from a
  real event and clear when the cause clears.
- **P14-FR-620**: Escape exits; left and right arrows change page; a tile click opens the
  single view on top of the wall.
- **P14-FR-621**: Fully usable by keyboard and readable from a distance: large name and reading,
  and a ring is also named in text, never colour alone.

### Showing the wall must not hurt analysis

- **P14-FR-622**: Showing the page or wall MUST NOT slow, pause or reduce any camera's analysis;
  no action, tile count or page change may cost a detection, a read or an alert. Today,
  looking at a camera's boxes raises that camera's analysis rate for a few seconds; grid and
  wall tiles MUST NOT do this, or sixteen tiles would raise sixteen cameras at once. Opening a
  single camera may, as today.
- **P14-FR-623**: Only on-screen tiles ask for pictures; demand stays bounded however many
  cameras exist; a tile that leaves the screen stops asking.
- **P14-FR-624**: On the target box (Jetson Orin Nano, shared 8 GB memory, hardware decode, no
  hardware encode) a full 4×4 wall with all features running MUST keep detection rate and
  alert time within a tolerance of the same system with the wall closed, and fit in the memory
  left over. The tolerance is set when measured.
- **P14-FR-625**: When the box is short of resources, the wall lowers picture rate or size
  first and says so on the tile, never lowering analysis.
- **P14-FR-626**: Recording is reported as costing processor time on this box (it encodes on
  the processor) and MUST NOT run unless asked for.

### Roles, language and honesty

- **P14-FR-627**: A tile, strip or wall MUST show only what the role may see. IT sees pictures,
  state and non-identity readings, plus plate text and chips (owner decision, 10 Nov 2026;
  spec 022, P14-FR-115); never names, attendance status or identity-based counts, and the
  engine MUST refuse them, not only the console hide them. New engine work: today an IT account
  can ask any camera for its face boxes, which carry names; because permissions are decided
  by address, the plan must find an address-based way to close it.
- **P14-FR-628**: Alerts waiting MUST equal the open items in Home's Needs your attention (the
  sidebar's "N things need attention") and show unavailable if the count cannot be read.
- **P14-FR-629**: Wording, directions and number formats follow the chosen language, including
  right to left.
- **P14-FR-630**: If a part cannot load (cameras, readings, alerts), it says so on that part and
  the rest keeps working.

## Success Criteria

- **SC-001**: An operator finds a named camera among 40 in under 5 seconds with filter and search.
- **SC-002**: Every camera without a current picture is in No signal, and no tile claims Live
  while its picture is older than the stated limit.
- **SC-003**: Unplugging a camera turns its tile to No signal, last picture marked old, within
  10 seconds (System Health's rule), and the top-bar count follows.
- **SC-004**: On the Jetson, a 4×4 wall paging across 40 cameras with all features on leaves
  detection rate and alert time within the tolerance fixed under P14-FR-624, wall open against
  closed.
- **SC-005**: Escape, arrows and tile clicks behave as listed; nothing shown is a fixture.
- **SC-006**: An IT account opening every tile and the wall sees no person name or attendance
  value, and a direct request for one is refused.
- **SC-007**: The wall shows the same cameras-up number as the top bar and the same
  alerts-waiting number as Home.

## Out of scope

- Shell, roles, System Health (022); attendance, people (023); plate reader (024); zones and
  stations (025). The wall only shows their last read or ring.
- Camera setup, and which features a camera runs.
- Playback, clip search, PTZ, audio, picture-in-picture, saved layouts, a second monitor,
  cross-camera counting without double counting, any new model.

## Constitution check

- Stale and missing pictures are named, never Live (-607, -615); a tile draws only its own
  feature's overlay (-608); viewing is separate from analysis (-622 to -625).
- No fixtures; unavailable readings say why; no capacity, no percentage (-609, -610, -628).
- The engine enforces what IT may see; no secret in the stream address (-613, -627).
- Camera count is an input, about 40 expected, 208 the target (-605, -623).

## Assumptions

- Filter membership comes from configured features. No signal is System Health's 10-second
  rule; Stale is the new, shorter band before it.
- Grid size and filter are remembered per operator session only.
- Existing tile pacing (only on-screen tiles ask, fixed shared budget) is kept as the base.
- **[NEEDS CLARIFICATION: When picture demand must be cut on the Jetson, what is the lowest picture rate an operator will accept on the wall before it should show fewer cameras per page instead? The owner will decide once the Jetson soak test has measured it.]**
