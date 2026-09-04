# Feature Specification: Camera Onboarding — Real, Complete, Editable

**Feature Branch**: `011-camera-onboarding`
**Created**: 2026-09-01
**Status**: Draft
**Input**: User description: "Ensure camera configuration is working well. Scale is growing. Ensure the system can load an RTSP camera and cameras from a DVR/NVR successfully, and assign each camera to the desired feature(s)."

## Why this feature *(mandatory)*

An administrator setting up a site today can add one direct RTSP camera and it works. Almost
everything else about camera setup either lies or is missing.

- **Connecting a recorder always reports the same sixteen channels**, "connected", 704×576 —
  whatever the recorder actually is, and whether or not it answered at all.
- **Pressing Add on a discovered device, or on recorder channels, saves nothing.** A row appears
  on the screen, the page is refreshed, and the camera is gone.
- **Three features of seven can be chosen.** Track, vehicles, knives and lost items cannot be
  assigned from the console at all, and a camera added there can never be an identity camera or a
  gate camera however it is set up.
- **Three features ignore the list anyway.** Knife detection and restricted-area watching run on
  every enabled camera whether or not anybody asked for them.
- **A camera added is analysed by nothing until the engine restarts.** It streams, and it appears
  in the grid, and no feature looks at it.
- **A camera cannot be corrected.** A wrong area, a wrong frame rate or a mistyped address means
  deleting it and adding it again.

At eight cameras all of this can be worked around by editing the config file and restarting. At the
size this system is heading for, that workaround becomes the only way to configure the product, and
the console becomes a screen that shows things which are not true.

This feature makes camera setup real: what the console says about a recorder is what the recorder
said, what is saved stays saved, every feature can be assigned and taken away, and what is assigned
is what actually runs.

## User Scenarios & Testing *(mandatory)*

### Primary story

An administrator opens camera setup and chooses how the camera arrives — one direct stream, or a
recorder carrying many channels. For a direct stream they paste the address, press Test, and see a
real frame with its size and how long it took to arrive. For a recorder they give its address, its
credentials and the pattern its channels follow, and the console opens every channel for real: the
ones that answered are offered with the picture they gave, and the ones that did not are listed
with the reason. The administrator ticks the channels they want, gives them an area, and chooses
what each is watched for from the full list of features — answering, at the same time, the
questions a feature needs answered: whether people pass close enough to this camera to be
recognised, which gate it watches and which way it faces, whether its whole frame is a restricted
area. They press Add. Every camera they chose is saved, starts streaming, and starts being analysed
by exactly the features they picked, without the engine being restarted. Later they open the same
camera, move it to a different area or take a feature away, and that change lands the same way.

**Acceptance scenarios**

1. **Given** a recorder that is switched off or unreachable, **When** an administrator tries to
   connect to it, **Then** the console states it could not be reached and why, and offers no
   channels at all.
2. **Given** a reachable recorder where four of its sixteen configured channels are actually
   producing video, **When** the administrator connects, **Then** exactly those four are offered,
   each with the picture size it returned, and the other twelve are shown as not answering with
   their reason beside them.
3. **Given** channels ticked and features chosen, **When** Add is pressed, **Then** every ticked
   channel exists as its own camera, and is still there after the page is refreshed and after the
   engine is restarted.
4. **Given** a camera added without knife detection selected, **When** somebody carries a knife
   past it, **Then** no knife detection runs on that camera and no entry is raised.
5. **Given** a camera added with attendance selected and marked as a camera people look at closely,
   **When** an enrolled person walks past it, **Then** they are recognised — without the engine
   having been restarted since the camera was added.
6. **Given** a camera added with vehicles selected, a gate number and a direction, **When** a car
   arrives, **Then** its plate is read and a pass recorded — without a restart.
7. **Given** an existing camera, **When** an administrator changes its area, its analytics rate or
   its features, **Then** the change is saved, takes effect without a restart, and is audited
   before it is written.
8. **Given** the console cannot search the network for devices, **When** an administrator presses
   Scan, **Then** it says so with a reason, rather than showing an empty result that reads as
   "there is nothing on your network".
9. **Given** a camera whose address carries a password, **When** an administrator looks anywhere in
   the console, the logs, an export or the audit trail, **Then** that password is nowhere.
10. **Given** a camera is removed, **When** it goes, **Then** it stops streaming and stops being
    analysed by every feature at once, and the events it already produced remain.
11. **Given** fifty channels ticked in one action, **When** Add is pressed, **Then** fifty outcomes
    are reported — each one added or each one refused with its reason — and no camera that was
    already running is interrupted.

### Edge cases

- **Test passes but Add fails**, because the id is already taken. The operator must be told which
  of the two failed, and why.
- **A feature was chosen whose model did not load when the engine started.** The camera must be
  added and the console must say that feature is not running and why — never accept it silently and
  analyse nothing.
- **Two channels of the same recorder given the same name.** Both are real cameras and both must be
  addable; the console must not silently merge or overwrite one with the other.
- **A recorder gains a channel later.** Connecting again must offer the new one and must not
  duplicate the channels already added.
- **A camera that came from the config file is edited.** The console must state plainly what
  happens to that edit the next time the config file changes, because the stored row and the file
  are two sources for one camera.
- **The last camera carrying a feature is removed or unassigned.** That feature must report that
  nothing is being watched for it, with the reason — not disappear, and not report zero as if it
  had looked.
- **Nothing versus unknown.** "This recorder has no channels" and "we could not ask this recorder"
  are different answers and must read differently.
- **A camera is added while another is reconnecting.** The reconnecting camera's backoff, NO SIGNAL
  state and last-good-frame behaviour must be untouched.

## Requirements *(mandatory)*

Requirements are numbered `P13-FR-nnn`. This work sits after `docs/PLAN.md` Phase 12; product-level
`FR-xx` numbers belong to `docs/PLAN.md` and are not reused here.

### Truthful onboarding

- **P13-FR-001**: Connecting to a recorder MUST report only what that recorder answered. No count,
  status, channel name, resolution or address may be produced by the system itself.
- **P13-FR-002**: Every channel offered for adding MUST have been opened and returned a frame.
  Channels that did not answer MUST be listed separately, each with its reason.
- **P13-FR-003**: How a recorder's channels are addressed MUST be an operator-supplied pattern with
  a placeholder for the channel, in the same spirit as the archive playback template. A recorder
  that spells its addresses differently MUST be usable without a code change.
- **P13-FR-004**: Failing to reach a recorder MUST arrive as a readable reason beside the form, not
  as a server error, and never as an empty channel list that reads like success.
- **P13-FR-005**: No path in camera setup may present an invented device, channel, status,
  resolution, latency or address.
- **P13-FR-006**: Pressing Add MUST persist. Nothing may appear in the camera list that has not
  been written and will not survive a refresh and a restart.
- **P13-FR-007**: Searching the network for devices MUST either find real devices or state plainly
  that it is not available, with a reason. An empty result that means "not built" is forbidden.
- **P13-FR-008**: Testing a single stream MUST keep its current behaviour — open the stream, pull a
  real frame, and report a failure as a readable reason rather than an error status.

### Assigning features

- **P13-FR-009**: Every feature the engine can run MUST be assignable per camera from the console:
  attendance, counting, restricted area, track a person, vehicle gate, knife detection, lost items.
- **P13-FR-010**: A feature that is not assigned to a camera MUST NOT run on that camera. This
  MUST be true of every feature, including the ones that today run on every enabled camera.
- **P13-FR-011**: The settings a feature needs MUST be set at the same time as the feature: whether
  people are close enough to this camera to be recognised, the gate number and direction, whether
  the whole frame is a restricted area, the picture rotation, and the analytics rate.
- **P13-FR-012**: An incomplete combination MUST be refused with a reason naming exactly what is
  missing — a camera set to read plates with no gate number is refused, not half-run.
- **P13-FR-013**: The console MUST state what each feature costs to run on a camera, so the choice
  is made knowingly.
- **P13-FR-014**: Assigning a feature MUST take effect without restarting the engine. The camera
  MUST begin being analysed by that feature within 10 seconds of being saved.
- **P13-FR-015**: Unassigning a feature MUST stop that analysis on that camera, and MUST NOT
  disturb the same feature on any other camera, nor any other feature on this one.
- **P13-FR-016**: If a feature cannot run — its model failed to load, or its subsystem did not
  start — assigning it MUST say so with the reason at the moment it is assigned, and the camera
  MUST still be added.
- **P13-FR-017**: What a camera is assigned to MUST read the same everywhere it is shown: the
  camera list, System Health, and the feature's own page.

### Correcting a camera

- **P13-FR-018**: An existing camera MUST be editable: its name, area, address, credentials,
  analytics rate, rotation, features, each feature's settings, and whether it is enabled.
- **P13-FR-019**: Editing MUST NOT change which camera it is, so everything already recorded
  against it stays attached to it.
- **P13-FR-020**: Editing a camera that came from the config file MUST state plainly what happens
  to that edit when the config file next changes.
- **P13-FR-021**: Every add, edit, enable, disable and removal MUST be audited **before** it is
  written, naming who did it, which camera, and what changed.
- **P13-FR-022**: Removing a camera MUST stop it streaming and stop every feature analysing it, and
  MUST keep the events it already produced.

### Honest whatever the size

- **P13-FR-023**: Nothing in camera setup may assume a camera count. Adding one camera and adding a
  hundred MUST work the same way.
- **P13-FR-024**: Adding several cameras in one action MUST report an outcome for each, and MUST
  NOT abandon the rest on the first failure.
- **P13-FR-025**: Adding, editing or removing one camera MUST NOT interrupt, restart or degrade any
  camera already running.
- **P13-FR-026**: The camera list MUST stay readable and usable as the number of cameras grows —
  findable by name, area and status, without the page becoming the only way to find one camera.

### Secrets and permissions

- **P13-FR-027**: A camera's password MUST never appear in the console, a log line, an error
  message, an exported file, or an audit entry.
- **P13-FR-028**: Camera setup MUST remain administrator-only, decided by the server, and MUST NOT
  depend on the console hiding a control.

## Success Criteria *(mandatory)*

- **SC-001**: Connecting to a recorder that is switched off produces a reason and zero channels,
  every time. It never produces a channel list.
- **SC-002**: Every channel the console offers, when added, produces a picture. A channel that
  cannot produce one is never offered.
- **SC-003**: Everything added is still there after the page is refreshed and after the engine is
  restarted.
- **SC-004**: All seven features can be assigned and taken away per camera, and a feature that was
  not chosen never runs on that camera — provable by watching one camera's analysis stop when the
  feature is removed while the same feature keeps running on another camera.
- **SC-005**: A camera added or changed is being analysed by its chosen features **within 10
  seconds**, with no restart.
- **SC-006**: An administrator can correct a mistyped camera without deleting it, and its recorded
  history is still attached afterwards.
- **SC-007**: No camera password can be found anywhere a person or an export can reach.
- **SC-008**: Adding fifty channels in one action reports fifty outcomes and interrupts no camera
  that was already running.
- **SC-009**: An administrator who has never edited the config file can set up a site's cameras end
  to end and assign every feature, using the console alone.

## Out of scope

Answered by the owner on 1 Sep 2026 and deliberately excluded:

- **Load, capacity and hardware sizing.** How many cameras one machine carries waits for the target
  hardware, and belongs to `docs/PLAN.md` P8 with `specs/009-workload-placement`. Nothing here may
  claim a camera limit or a performance figure.
- **Splitting cameras across several machines.** Multi-process partitioning is P8.
- **Several factories, and a shared cloud between them.** A separate product decision and a
  separate spec.
- **ONVIF.** Recorders are addressed by an operator-supplied pattern, not by a discovery protocol.
- **Building network discovery.** Being honest that it is unavailable satisfies P13-FR-007;
  actually finding devices on the network is optional and not required by any success criterion.
- **Any new model, and any change to detection accuracy or thresholds.**
- **Zone geometry.** Restricted-area shapes stay on the Intrusion page; this feature only assigns
  whether a camera watches a restricted area at all.
- **Writing changes back into `engine.yaml`.** The config file stays the bootstrap seed and the
  database stays the source of truth.
- **Replacing thread-per-camera.** That is P8's bounded worker pools, and this feature must not
  depend on it.

## Constitution check *(mandatory)*

- **Nothing untrue** (III). This is the whole feature. The fabricated recorder channel list, the
  Add buttons that save nothing, and the empty scan that reads as "nothing found" are three
  separate breaches of Principle III in one screen, and each is named by a requirement above.
- **A feature must never require another feature** (Principle II, rule 9). Assigning or removing
  one feature on one camera must leave every other feature and every other camera untouched —
  P13-FR-015 and P13-FR-025.
- **Honest degradation, never a 5xx** (rule 7). An unreachable recorder, a feature whose model did
  not load, and an unavailable network scan are all payload with a reason.
- **A subsystem that fails to start must say so in the UI** (rule 8). P13-FR-016 extends this to
  the moment of assignment, which is when the operator can act on it.
- **Server-side permissions** (IV). Camera setup already sits behind `ADMIN_PREFIXES` by path;
  every new endpoint must be reachable only under a prefix that keeps it there.
- **Audit before the act** (III). P13-FR-021 — the entry is written before the change, as
  everywhere else in the system.
- **Secrets** (IV). Camera passwords are already folded into the source string and redacted in one
  place; every new path — recorder templates, edit, bulk add, audit — must use that same redaction.
- **Real-time experience** (I). P13-FR-025: setup must never be the reason a running camera
  stutters. Latency budgets in `docs/PLAN.md` §7 are unchanged by this feature.

## Assumptions

- **The largest piece of work is making assignment take effect without a restart.** Feature workers
  take their camera list once, when they are constructed, and have no way to gain or lose a camera
  afterwards. P13-FR-014 and P13-FR-015 require that to change. If the owner would rather accept a
  restart, both requirements soften to "the console states plainly that a restart is needed and
  when" — but a restart at site scale interrupts every camera, which is why it is not the default
  here.
- **Recorder channels are cameras.** Each channel that is ticked becomes its own camera with its
  own id, area and features, rather than a recorder being one thing with sixteen streams inside it.
  This matches how every feature already addresses a camera.
- **"Seven features" means what the engine can run today**: attendance, counting, restricted area,
  track a person, vehicle gate, knife detection, lost items. Lost items and restricted area are
  already partly per-camera by other means (live interest, and the restricted flag); those means
  stay, and the feature list becomes the single place a camera says what it is for.
- **The identity tier stays a per-camera decision, not a per-feature one.** A camera can carry
  attendance without being an identity camera; that combination is legal and is what the patrol
  tier is for.
- **No new dependency is assumed.** Opening a channel to prove it works uses the same capture path
  that Test connection already uses.
- **Existing cameras are not migrated.** A camera seeded from `engine.yaml` keeps working exactly as
  it does now; it simply becomes editable, and P13-FR-020 covers what that means.
