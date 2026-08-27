# Feature Specification: Vehicle Gate

**Feature Branch**: `006-vehicle-gate`
**Created**: 2026-08-24
**Status**: Draft
**Input**: User description: "new feature to be added 'Vehicles'. I added a design that has all details of this feature. I don't need fake data as it has in design, I need to wire it and make it functioning perfect. The real code base is in `models/Gate` — inside it, models has 2 .pt files which are the engines for recognising car plates."

## Why this feature

Today the console can say who walked in, but nothing about who drove in. A guard on
the gate writes plates on paper, and nobody can answer "is that contractor's car
still on site?" without walking the car park. This feature photographs every car that
passes a gate, reads its Egyptian plate, and matches it against a register the school
keeps itself — so the console can name the driver, flag a car whose access was
withdrawn, and say which cars came in and have not been seen leaving.

## User Scenarios & Testing

### Primary story

A guard opens **Vehicle gate** on the console. The **Live** tab shows the gate
cameras with a box drawn round each plate as a car arrives, and a running list of the
last few passes — plate, who owns it, which gate, in or out, and whether it is on the
register. When a car the school does not know passes, it still appears in the list,
marked "Not registered", with a button that opens the register form with the plate
already filled in from the photo. When a car whose access has been withdrawn passes,
an item appears on the Home page that a person has to acknowledge.

An administrator opens the **Registered vehicles** tab, searches by plate, owner,
phone or unit, adds a car, edits one, or removes one. The **Movements** tab answers
"how many in, how many out, per gate, today" and "which cars are inside now, and for
how long".

**Acceptance scenarios**

1. **Given** a gate camera is running and a car with a readable plate passes, **When**
   three frames agree on the same plate, **Then** one pass appears in the live list
   within a few seconds with the plate, the gate, the direction, and a status.
2. **Given** the same car is still in view, **When** more frames are read within the
   de-duplication window, **Then** it is still one pass, not many.
3. **Given** a plate that is not on the register, **When** it passes, **Then** it is
   recorded and shown as "Not registered" — never blocked, never discarded — and the
   register form can be opened from that row with the plate pre-filled.
4. **Given** a plate on the register with category "Blacklisted", **When** it passes,
   **Then** an attention item is raised on Home, it stays in history after being
   acknowledged, and it cannot be deleted.
5. **Given** a plate on the register whose permit expired yesterday, **When** it
   passes, **Then** it is recorded as "Permit expired" — shown on the Vehicle gate
   page, not raised on Home.
6. **Given** the reader was unsure of a plate, **When** the pass is recorded, **Then**
   it is kept and marked "needs review" with its confidence, not thrown away.
7. **Given** an administrator fills the register form with a plate typed in English
   digits, **When** they save it, **Then** the same car read from a camera in Arabic
   digits matches it.
8. **Given** an administrator uploads a filled spreadsheet, **When** the import runs,
   **Then** the console reports how many rows were added, how many were skipped as
   duplicates, and why any row failed.
9. **Given** a car entered and has not been seen leaving, **When** the Movements tab
   is opened, **Then** it appears under "Inside now" with the time it entered and how
   long it has been inside.
10. **Given** a plate is removed from the register, **When** the same car passes
    again, **Then** it is recorded as "Not registered" from that pass onward and its
    earlier passes are unchanged.

### Edge cases

- **No gate camera is configured.** The page says so plainly, with the reason, and
  offers no controls that would do nothing. It does not show zeros as though they
  were counts.
- **The gate camera is offline.** The camera tile says "no signal" and names how long
  it has been down. The rest of the page still shows what was recorded before.
- **The plate models are missing or failed to load.** The page states that plates are
  not being read and why. Cameras and the register still work; the pass list is
  empty and says it is empty because nothing is reading, not because nothing drove in.
- **Only an entry camera exists at a gate** (the current state — one laptop webcam).
  Passes are recorded as entries. "Inside now" counts cars that came in, and the page
  states that no exit camera is configured, so no visit has been paired and no stay
  duration is known. It becomes real the day an exit camera is added.
- **The plate is unreadable** — dirty, bent, at a bad angle, or at night with no
  light. Nothing is recorded rather than a guess, and the camera tile still shows the
  car passed.
- **Two cars pass within the de-duplication window at the same camera.** Different
  plates are two passes; the same plate is one.
- **A car leaves through an unwatched gate.** Its open visit is closed when the same
  plate is next seen entering, and the closed visit is marked as inferred rather than
  observed.
- **The register is empty**, which is where every deployment starts. Every pass is
  "Not registered". The page says the register is empty and how to fill it, rather
  than reading as though the system is broken.

## Requirements

- **P6-FR-001**: System MUST read Egyptian plates — Arabic letters and Indic digits —
  from a gate camera, and MUST NOT record a plate until at least three frames agree
  on it.
- **P6-FR-002**: System MUST normalise every plate to one canonical form, so that
  Arabic digits and English digits for the same car are the same car, whether the
  plate arrived from a camera, a typed form, or a spreadsheet.
- **P6-FR-003**: System MUST record, for each pass: the time, the camera, the gate
  number, the direction, the plate, the status, the reading confidence, how many
  frames agreed, a photograph of the frame, and a crop of the plate.
- **P6-FR-004**: System MUST classify each pass as one of: registered, not
  registered, blacklisted, permit expired.
- **P6-FR-005**: System MUST keep a pass whose reading confidence is below the accept
  threshold, marked as needing review, rather than discarding it.
- **P6-FR-006**: System MUST treat repeated reads of the same plate at the same camera
  within a configured window as one pass.
- **P6-FR-007**: System MUST never prevent a vehicle from passing. It records; it does
  not gate, block, or actuate anything.
- **P6-FR-008**: Users MUST be able to see the gate cameras live, with a box drawn
  round each detected plate, coloured by the status of that plate.
- **P6-FR-009**: Users MUST be able to see the most recent passes, newest first, with
  plate, owner, gate, direction, status and time.
- **P6-FR-010**: Users MUST be able to search the full pass log by plate, gate,
  direction and status, and export the result.
- **P6-FR-011**: System MUST pair each exit with the entry it belongs to and record
  how long the vehicle stayed, and MUST state that pairing assumes no vehicle left
  through an unwatched gate.
- **P6-FR-012**: System MUST show, per gate and per day, how many vehicles entered,
  how many left, and how many are still inside — and MUST NOT show a paired figure
  when no exit camera exists to pair against.
- **P6-FR-013**: Administrators MUST be able to add, edit and remove a register entry
  holding: plate, owner name, phone, unit or department, category, car make, colour,
  permit expiry and notes. Only the plate is required.
- **P6-FR-014**: The register MUST support exactly four categories: Staff, Visitor,
  VIP, Blacklisted.
- **P6-FR-015**: A register entry MAY carry a permit expiry date. A blank date means
  no expiry. A date in the past makes the vehicle's passes read "Permit expired".
- **P6-FR-016**: Users MUST be able to search the register by plate, owner, phone or
  unit, and filter it by category.
- **P6-FR-017**: Administrators MUST be able to download a blank spreadsheet template
  and upload a filled one, with column headings accepted in English or Arabic, and
  MUST be told how many rows were added, skipped and rejected, and why.
- **P6-FR-018**: Users MUST be able to register a vehicle directly from an
  unregistered pass, with the plate pre-filled from the read.
- **P6-FR-019**: A change to the register MUST take effect at the gates without a
  restart, and MUST apply from the vehicle's next pass onward without altering its
  recorded passes.
- **P6-FR-020**: Removing a register entry MUST require an explicit confirmation that
  states what will happen, and MUST keep that vehicle's past passes.
- **P6-FR-021**: A pass by a blacklisted vehicle MUST raise an item on the Home page
  that waits for a person to acknowledge it. Acknowledged items stay in history and
  cannot be deleted.
- **P6-FR-022**: Writing to the register — add, edit, remove, import — MUST be
  restricted to administrators, decided by the server. Reading is available to any
  signed-in user.
- **P6-FR-023**: Exporting the pass log MUST write an audit entry before the export is
  returned.
- **P6-FR-024**: Each gate camera MUST carry the gate number it watches and the
  direction it sees, and the console MUST show what a camera is configured as.
- **P6-FR-025**: When plate reading is unavailable — no model, no camera, subsystem
  not started — the page MUST say so with the reason, and MUST NOT present zeros,
  placeholders or sample rows as though they were data.
- **P6-FR-026**: Photographs and plate crops MUST be deleted after 30 days. The pass
  record itself MUST be kept regardless of whether its images still exist.
- **P6-FR-027**: The Vehicle gate page MUST draw only its own overlay. It MUST NOT
  show person boxes, tracking IDs, or recognised names on a gate camera.
- **P6-FR-028**: Vehicle gate MUST work with every other feature switched off, and
  switching it on MUST NOT change the behaviour of any other feature.

### Accelerated inference

The plate reader runs two models per car — one to find the plate, one to read its
characters — on top of whatever else is watching that camera. Every model in this
product that can be accelerated MUST be, and the console MUST be honest about it when
one is not.

- **P6-FR-029**: Every model the product loads that can run accelerated on the
  machine's GPU MUST do so. This covers the two plate models and the models already in
  use for counting, tracking, intrusion, knife detection, lost bag and pose.
- **P6-FR-030**: The accelerated build MUST be produced on the machine that will run
  it, from the supplied weights, as a deployment step. The supplied weights remain the
  artifact; the accelerated build is never treated as one, never archived, and never
  copied between machines.
- **P6-FR-031**: A single command MUST build the accelerated form of every model the
  configuration asks for, and MUST report for each one whether it succeeded, and why
  if it did not.
- **P6-FR-032**: The accelerated build MUST be produced at the same input size the
  configuration asks for. A build made for a different input size MUST be rejected and
  reported, not loaded.
- **P6-FR-033**: When a model's accelerated build is missing, stale, or refuses to
  load, the system MUST use the supplied weights on the GPU instead, MUST continue to
  work, and MUST state on the System Health page which models are running
  unaccelerated and why. It MUST NOT fall back to the processor.
- **P6-FR-034**: Two families are outside this and MUST NOT be claimed as accelerated:
  the face detector and face recogniser, which are a different runtime entirely; and
  the track association and appearance matcher, which are not neural networks and have
  no GPU form.
- **P6-FR-035**: The System Health page MUST show, per model, which form is loaded and
  how long a frame takes, so a lost acceleration is visible on screen rather than only
  as slowness.

## Success Criteria

- **SC-001**: A car driving past a configured gate camera appears in the live list
  within 5 seconds of passing.
- **SC-002**: Of cars whose plate is at least 100 pixels wide in the frame, at least
  95% are recorded with the correct plate.
- **SC-003**: A guard can tell, in one glance at a row, whether that car is on the
  register, unknown, blacklisted or expired — without opening anything.
- **SC-004**: A car passing is recorded exactly once, even when it is in view for
  twenty seconds.
- **SC-005**: An administrator can add a vehicle to the register and see the next pass
  of that car recognised, without restarting anything.
- **SC-006**: An administrator can import a 2,000-row spreadsheet and be told exactly
  how many rows landed, how many were duplicates, and which rows were rejected.
- **SC-007**: A guard can answer "is that car still inside?" from the Movements tab in
  under 10 seconds.
- **SC-008**: On a console with no gate camera, no model, or an empty register, every
  panel states which of those is true. A person who has never seen the page can tell
  the difference between "nothing drove in" and "nothing is reading".
- **SC-009**: A blacklisted car passing is visible on the Home page without anyone
  having opened the Vehicle gate page.
- **SC-010**: No number shown on the page is invented. Every count on screen can be
  traced to recorded passes, and a figure that cannot yet be computed is absent with a
  reason rather than shown as zero.
- **SC-011**: Every model that can run accelerated is running accelerated after the
  build command has been run, and the System Health page says so for each one.
- **SC-012**: A model that silently lost its acceleration — because the machine, the
  driver, or a library version changed — is visible on the System Health page within
  one restart, without anybody having to time a frame by hand.
- **SC-013**: Rebuilding every accelerated model on a new machine is one command, and
  the command says which models succeeded and which did not.

## Out of scope

- **Barrier or gate control.** Nothing is opened, closed or actuated. The system
  records; a person decides.
- **Non-Egyptian plates.** The models supplied read Arabic letters and Indic digits.
  A European or Gulf plate is out of scope for this phase.
- **Night operation without lighting.** No software fixes a frame with no image in it.
  Infra-red lighting at the gate is a site requirement, not a feature.
- **The mobile app.** The mobile design's "Registered vehicles" card is not built in
  this phase.
- **Accelerating the face detector and recogniser.** They are a different runtime and
  SFace is settled — changing it invalidates every enrolment.
- **A GPU form of track association or the appearance matcher.** Neither is a neural
  network. There is no GPU path and none will be promised.
- **Retraining the plate models on site footage.** The Gate project's collect →
  label → train workflow is valuable and stays available, but is not part of this
  phase.
- **Matching a driver's face to a vehicle.** A plate names a car, never a person in it.
- **Notifying anyone.** No push, no SMS, no email. An attention item appears on the
  console; telling somebody is a person's job.

## Constitution check

| Rule | How this feature honours it |
|---|---|
| A face names a person; clothing says "same body" | A plate names a **car**, never the person driving it. The register's owner name belongs to the vehicle, not to whoever is in the seat, and the page never implies the owner was present. |
| Tracking never uses recognition to track | Plate reading is not used to track a person, and no vehicle identity is carried into the person tracker. |
| Each feature draws its own overlay | The gate camera draws plate boxes only. No person boxes, no tracking IDs, no recognised names. |
| Never show anything untrue | No fixtures. Every count on the page comes from recorded passes. The design's sample figures — "2,140 on record", "148 entered today", "Last import: 2,140 rows" — are placeholders and must not survive into the build. An empty register shows as empty and says why. |
| Never claim precision the code lacks | "Inside now" depends on pairing, which depends on an exit camera existing. With only an entry camera the page says what is not known instead of showing a paired figure. |
| Geometry crosses the API as fractions | Plate boxes travel as fractions of the frame, never pixels. |
| Degradation is payload, never a 5xx | A missing model, a dead camera or a stopped subsystem is described in the response, not signalled by an error code. |
| A subsystem that fails to start must say so in the UI | If either plate model fails to load, the page says plates are not being read, and names the reason. |
| A feature must never require another feature | Vehicle gate runs with attendance, counting, tracking and everything else switched off. |
| Detections wait for a human | A blacklisted pass raises an attention item that a person acknowledges. It stays in history and there is no delete. |
| Searches write the audit entry before returning | Exporting the pass log writes the audit entry first. |
| A subsystem in a degraded state must say so on screen | This is not hypothetical here. The acceleration in this repo went cold at some point — five accelerated builds exist on disk, none is referenced by the configuration, and the library that loads them is no longer importable. Nothing on any screen said so. P6-FR-033 and P6-FR-035 exist so that cannot happen again silently. |
| Ship the supplied weights; build the accelerated form on the target machine | P6-FR-030. An accelerated build is compiled against one GPU and one library version. It is a deployment step, never an archived artifact. |
| No GPU path may be promised where none exists | P6-FR-034 names the two families that are excluded and why, rather than leaving a reader to assume everything is accelerated. |
| The owner supplies all models | The two plate models are supplied in `models/Gate`. Nothing is downloaded, sourced or trained. |
| Database is the source of truth | Vehicles, passes and visits live in the engine's database. Configuration seeds it; it does not replace it. |

## Assumptions

- **The Gate project is a source of technique, not a service.** VisionGuard already
  owns camera capture, configuration, a database, an audit log, authentication and a
  console. What the Gate project has that VisionGuard does not is plate
  normalisation, the multi-frame voting that makes a read trustworthy, the character
  map for the supplied model, and the trick of stripping the coloured "مصر/EGYPT"
  band before reading. Those come across; its duplicate camera, web and database
  layers do not.
- **The register starts empty**, by decision. Every pass is "Not registered" on day
  one, and the fastest way to fill the register is the button on an unregistered pass.
- **The laptop webcam is the first gate**, configured as Gate 1, entry. Real
  RTSP/DVR cameras replace it later, and the same page must work unchanged when they
  do.
- **One camera never guesses direction.** A camera says what it is configured to see.
  Inferring "entering" from a plate growing in the frame is a guess, and the Gate
  project's own documentation calls it noticeably less reliable.
- **Three agreeing frames** is the recording threshold, and the confidence below which
  a pass is flagged for review is a configured value, not a hard-coded one — both
  need tuning against real site footage.
- **De-duplication window** defaults to 60 seconds per camera, following the Gate
  project.
- **Photographs are kept 30 days**, matching the existing clip retention. Pass records
  are kept indefinitely.
- **Plates render in Arabic** on the console, right-to-left, as they appear on the car.
  The rest of the console stays in English.
- **Categories are Staff, Visitor, VIP, Blacklisted.** "Resident" from the Gate
  project is dropped — it means nothing at a school. A parent is a Visitor, with their
  child's class in the unit field.
- **Acceleration is repo-wide in this feature, not plate-only.** Deciding otherwise
  would have left a cold acceleration path sitting next to a warm one, which is how it
  went cold in the first place. The build covers every model the configuration asks
  for.
- **The accelerated build is produced on this machine now.** The deployment
  workstation is a different GPU, so its builds are made there, from the same supplied
  weights, by the same command.
- **FP16, not INT8.** All five existing accelerated builds are FP16 and it is the
  settled default in this repo. INT8 would need a calibration set of real plate images
  and risks accuracy on the 38-class Arabic character model — exactly where accuracy
  matters most. Worth measuring later, against real footage, not assumed now.
- **The existing accelerated builds are stale and are not reused.** They were produced
  by a newer version of the inference library than the one installed, and the person
  one was built for a smaller input size than the configuration asks for. They are
  rebuilt, not adopted.
- **Accuracy depends far more on camera placement than on code.** A plate under
  60 pixels wide will not read. Camera angle, distance and lighting are a site
  concern that this feature can measure and report on, but cannot fix.
