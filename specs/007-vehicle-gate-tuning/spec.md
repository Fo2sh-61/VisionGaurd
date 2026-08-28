# Feature Specification: Vehicle Gate Accuracy & Redesign

**Feature Branch**: `007-vehicle-gate-tuning`
**Created**: 2026-08-27
**Status**: Draft
**Input**: User description: "this is enhancement and fine tuning in the vehicle gate feature made. first of all the used model is not functioning good due to anonymous reason. it keeps catching wrong car numbers we have to find a solution. … my first priority is making the model strong enough to catch car numbers perfectly. also I updated the design of the Vehicles feature implement it. Also I need to see the detection box(s) on car plates live not to be hidden as it's now."

## Why this feature

The vehicle gate is built, but the owner cannot trust what it reads: real plates come
back with wrong numbers, and nobody can say why because accuracy has never been
measured against a single real plate. Worse, the live plate boxes have never actually
drawn — the box path fails before anything reaches the screen — so the one tool that
would show a person what the reader sees is invisible. This feature makes the reading
provably accurate, makes the reading visible while it happens, and brings the page up
to the 27 Aug drawing (`design/27-8 design/VisionGuard.dc.html`), which was designed
around exactly this: watching the reader work, and acting on what it finds.

## User Scenarios & Testing

### Primary story

A guard opens **Vehicle gate**. The moment a car reaches the gate, a box appears
around its plate on the live tile — coloured by the car's status, carrying the text
as soon as it reads, and showing how wide the plate is in pixels, because width is
what decides whether a plate can be read at all. Below the tiles, **"What the reader
is seeing now"** lists every read attempt — including the ones that came to nothing —
with its confidence, plausibility, width, and how many frames agree so far, so a
person can watch three frames agree, or watch the reader fail and know whether the
problem is the camera's placement or the reader itself. At the top, alerts wait for a
person: a blacklisted car, an unknown car (with a one-click way onto the register,
and a hint when it is one misread letter away from a car the school knows), an
expired permit. The **Movements** tab answers "what happened on that day": an hourly
traffic chart, gate-by-gate totals, who is inside and completed visits — each row
with its photograph.

Behind all of it, the reading itself is measured against real plates the owner
provides, and is not called fixed until at least 95% of readable plates read exactly
right.

**Acceptance scenarios**

1. **Given** a gate camera is running and a car with a visible plate is in frame,
   **When** the reader detects the plate, **Then** a box is drawn around it on the
   live tile while the car is still there — coloured by status, labelled with the
   read text once text exists, and showing the plate's pixel width.
2. **Given** the owner-supplied set of real plate images with known numbers, **When**
   the measurement is run, **Then** it reports, per plate, whether the plate was
   found and whether it read exactly right — and the overall exact-read rate on
   plates at least 100 pixels wide is at least 95%.
3. **Given** the reader misreads or reads nothing on a frame, **When** a person
   watches "What the reader is seeing now", **Then** that attempt appears with its
   own numbers, and a failed read says "read nothing" in words rather than showing
   a blank.
4. **Given** an unregistered car passes and its plate is one edit away from a
   registered plate, **When** its alert appears, **Then** the alert asks — never
   states — whether it might be that registered car, naming the plate and owner.
5. **Given** an alert is on screen, **When** a person dismisses it, **Then** the
   dismissal is recorded under their account before the alert goes, including
   whether the resolving action was taken.
6. **Given** passes were recorded on an earlier day, **When** that day is picked on
   Movements, **Then** the chart, the gate table and the visit lists show that day,
   and "Export this day" produces exactly that day's passes.
7. **Given** no exit camera exists (today's reality), **When** Movements is opened,
   **Then** "Inside now" and "Completed visits" say plainly why they cannot be
   computed instead of showing empty tables that look like quiet days.
8. **Given** the redesign removes the per-pass list, **When** an administrator needs
   the day's record, **Then** the export still contains every pass, and the
   photographs still open from the visit rows that reference them.

### Edge cases

- **Plate reading is not running.** Tiles show dashes with the one reason, the reader
  table says nothing is being read, and no alert is raised — the page must not look
  quiet when it is actually blind.
- **A gate camera goes offline.** Its tile says NO SIGNAL and the page states the
  consequence in words — e.g. that exits through that gate are not being counted and
  "inside" is an over-count until it returns.
- **The plate is physically too small.** The width readout is the aiming aid: it goes
  amber below the comfortable line so an operator learns to move the camera, not to
  distrust the software. Nothing is rejected for being small; small only weighs less.
- **The owner has not yet provided evaluation material.** The accuracy work has
  nothing to measure against: accuracy remains "unmeasured", every claim on screen
  and in the docs says so, and the redesign ships independently — the two halves must
  not block each other.
- **Two registered plates are both one edit from an unknown read.** No suggestion is
  shown. A guess between two candidates is a coin toss, and the alert must never put
  a wrong name next to a car.
- **The same unknown car passes again after its alert was dismissed.** The next
  recorded pass raises a fresh alert; a dismissal applies to the pass it was raised
  for, not to the car for ever.
- **More than one gate camera is being read.** Each reader-table attempt names the
  camera it came from; two cars at two gates must not interleave into one unreadable
  stream.
- **A replacement reader is adopted.** Everything outside reading — the register,
  recorded passes, statuses, exports, other features — behaves identically before
  and after; only the reading gets better.

## Requirements

Numbering continues the vehicle-gate series from `specs/006-vehicle-gate`
(which ended at P6-FR-035).

### Reading accuracy — the priority

- **P6-FR-036**: An evaluation set of real Egyptian plate images with their known
  correct text, supplied by the owner, MUST exist in the project's test data. A
  single command MUST measure the reader against it and report, per plate: found or
  not found, read text versus true text, exact or wrong. Each run's result MUST be
  kept as dated evidence alongside the set.
- **P6-FR-037**: On plates at least 100 pixels wide in the image, the exact-read rate
  MUST reach at least 95%. Below 100 pixels the rate is measured and reported with no
  target — that regime belongs to camera placement, not software.
- **P6-FR-038**: The current reader MUST be measured as-is before anything is
  changed, and every candidate cause of wrong reads — including every known
  difference between this reader and the source project it was ported from — MUST be
  either eliminated or shown harmless, with a before/after measurement for each
  change. No fix may be claimed without its number.
- **P6-FR-039**: Only if the current reader still misses the target after the
  evidence-driven fixes MAY it be replaced. Replacement candidates MAY be sourced
  from the internet — the owner authorised this on 27 Aug 2026 as an exception, for
  the plate reader only, to the settled rule that the owner supplies all models. Any
  candidate MUST arrive with its licence and origin recorded, MUST be measured on the
  same evaluation set, and MUST beat the fixed current reader there before it ships.
  The owner approves the final choice.
- **P6-FR-040**: A reader change MUST be invisible outside reading: the same
  behaviours, the same recorded data, the same statuses, the same pages, every other
  feature untouched.
- **P6-FR-041**: No accuracy level may be claimed anywhere — on the page, in system
  health, in documents — that has not been measured on the evaluation set. Until the
  set exists, the claim is "unmeasured", written out.

### Seeing the reading live

- **P6-FR-042**: While a plate is in a gate camera's view, its box MUST be drawn on
  that camera's live tile within the overlay's freshness budget — coloured by the
  car's status (registered, not registered, blacklisted, expired), labelled with the
  read text once a read exists, with the reading confidence and the plate's width in
  pixels, the width coloured by the 100-pixel comfort line. Because the previous
  "fix" for invisible boxes was pinned only at the request side while the response
  side still failed, a regression test MUST prove the whole journey — from a plate
  found by the reader to a box accepted by the interface contract.
- **P6-FR-043**: The Live tab MUST show "What the reader is seeing now": every read
  attempt, newest first — time, what it read (or "read nothing", in words),
  confidence, plausibility, plate width, the leading candidate for that car, and
  votes gathered out of votes needed. When more than one gate camera is read, each
  attempt names its camera. The list exists only while somebody is watching the page
  and costs nothing when nobody is.
- **P6-FR-044**: The Live tab MUST state, per gate camera, which plate-finder and
  which character-reader are loaded and how long a read takes — so a changed or
  fallen-back model is visible on the page where its work shows, not only on System
  Health.
- **P6-FR-045**: A gate camera that is offline MUST have the consequence stated in
  words next to it — what is no longer being counted because it is down.

### Alerts that wait for a person

- **P6-FR-046**: The Live tab MUST show an alert for each unresolved pass that needs
  a person: a blacklisted car (wording MUST say nothing was stopped — there is no
  barrier to close, and the alert carries no action button because there is nothing
  the software can do), an unregistered car (action: add it to the register, plate
  pre-filled from the read), an expired permit (action: open that vehicle's entry to
  renew it). Alerts stay until a person clears them, and survive leaving the page.
- **P6-FR-047**: Dismissing an alert MUST write an audit entry first — who, which
  alert, and that it was dismissed without its action. Taking the action resolves the
  alert through the action's own audited write. The existing Home-page attention item
  for blacklisted cars is unchanged; unknown and expired alerts appear only on the
  Vehicle gate page, never on Home.
- **P6-FR-048**: When exactly one registered plate is within one edit of an unknown
  read, the unknown car's alert MUST suggest it as a question — plate and owner —
  and MUST NOT merge, rename, or record the pass as that car. Zero or several
  candidates: no suggestion.

### The 27 Aug redesign

- **P6-FR-049**: The Live tab MUST match the 27 Aug drawing: alerts at top, six
  tiles, the gate-camera grid with the aiming-aid explanation, the reader table, and
  a closing pointer to Movements. The "Passing now" per-pass list is removed.
- **P6-FR-050**: The sixth tile is "Cameras reading X of Y": how many gate cameras
  are actually being read of those configured, and when short, which one is not and
  why. The "Needs review" tile from the first build is retired with the pass list.
- **P6-FR-051**: The Movements tab MUST match the drawing: a day picker (any day
  with recorded passes, defaulting to today), a plate-or-owner search, a gate
  filter, and "Export this day"; an hourly in/out traffic chart; a gate-by-gate
  table with an all-gates total row and per-gate honesty notes; "Inside now" and
  "Completed visits" rows each carrying a snapshot thumbnail that opens the pass
  photograph. The search and gate filter scope the two visit tables; the chart and
  totals stay on the whole picked day, and a scope line says exactly that. The
  export writes its audit entry before the file is built, as today.
- **P6-FR-052**: The per-pass list leaves the console entirely — Live and Movements.
  This supersedes the display half of P6-FR-009 and P6-FR-010 and the row placement
  of P6-FR-018; it was the owner's decision on 27 Aug 2026, made knowing the costs:
  weak reads lose their review surface, a nonsense read can no longer be deleted
  from the console, registering from a read exists only while its alert stands, and
  until an exit camera is installed recorded passes are visible only through the
  export. Recording itself is unchanged: every pass is still written with its
  photograph, crop, confidence, votes and review flag, and the export still returns
  all of it.
- **P6-FR-055**: The console MUST show every recorded pass — photograph,
  plate, time, gate, direction and status — with an administrator able to
  remove one in a single click. **This reverses the console half of
  P6-FR-052**, at the owner's request on 28 Aug 2026 and for a reason the
  original decision did not anticipate: "Inside now" and the visit tables are
  derived from *pairing* an entry with an exit, so a gate with one camera has
  nothing to pair against and correctly refuses to print a figure. With the
  pass list also gone, a gate that had recorded nine cars showed none of them
  anywhere. A page that hides real recorded data is as dishonest as one that
  invents it. Recording, retention, permissions and the audit entry are all
  unchanged; only the display returns, and smaller — the confidence and vote
  counts stay behind the reader card's Details toggle.

- **P6-FR-053**: The Registered vehicles tab MUST match the drawing where it does
  not already: the Latin transliteration line under each plate, and an import card
  whose "last import" line states the real most recent import — rows added, rows
  skipped, when — or is absent when no import has ever run. Nothing on the tab may
  show a sample figure.
- **P6-FR-054**: Every count in the new layout that cannot be measured MUST render
  as absent with its reason, never as zero — carried forward from the first build
  and re-verified across every new element this redesign adds.

## Success Criteria

- **SC-001**: One command measures the reader on the owner's evaluation set and
  reports at least 95% exact reads on plates 100 pixels or wider; run twice, it
  gives the same answer, and its result is kept as dated evidence.
- **SC-002**: A person watching a gate tile sees the box around a plate while the
  car is still in front of the camera, with its status colour, text and width — on
  the first car, without touching anything.
- **SC-003**: From the Live tab alone, a person can tell which of three problems
  they have — the camera is placed wrong (widths amber), the reader is failing
  (attempts wrong or empty), or the system is not reading (stated reason) — without
  opening a log.
- **SC-004**: A guard answers "what happened at gate N on day D?" from Movements in
  under 10 seconds, and "Export this day" returns exactly that day.
- **SC-005**: Every dismissed alert is traceable in the audit log to the account
  that dismissed it.
- **SC-006**: No figure on the page is invented: sample lines, zeros standing in for
  "unknown", and unmeasured accuracy claims do not appear anywhere in the new
  layout.
- **SC-007**: If the reader is replaced, a person using every other page notices
  nothing: same behaviours, same records, better reads.

## Out of scope

- **The mobile app's Vehicles screen.** The 27 Aug mobile drawing includes one; the
  mobile app is entirely demo data and stays out, per the owner (27 Aug 2026).
- **Every other screen in the 27 Aug design folder.** Only the Vehicles screen is
  implemented by this feature.
- **Retraining models on site footage.** The collect → label → train path stays
  available but is not this feature.
- **Barrier control, notifications, non-Egyptian plates, night operation without
  lighting** — unchanged from the first build's exclusions.
- **Rebuilding the voting, merging and de-duplication scheme.** It is sound; it may
  be tuned only where a measurement on the evaluation set demands it.

## Constitution check

| Rule | How this feature honours it |
|---|---|
| Truthful data, no fixtures | The drawing's sample figures ("2,140 on record", "Last import: 2,140 rows", alert examples) must not survive into the build. Unmeasured accuracy is written as unmeasured (P6-FR-041). Absent-with-reason carries through every new element (P6-FR-054). |
| Model selection is evidence-driven | Exactly this feature's spine: measured baseline, per-change before/after, replacement only by beating the incumbent on the same set, licence and origin recorded, owner approval (P6-FR-036…039). |
| The owner supplies all models | Amended by the owner, 27 Aug 2026, for the plate reader only: candidates may be fetched from the internet, owner approves the final weights (P6-FR-039). The settled-rules list is updated to record this exception when the feature lands. |
| Never claim precision the code lacks | The near-match is a question, never a merge (P6-FR-048). Width below the comfort line is an aiming aid, not a rejection. Inside-now still refuses to print without an exit camera. |
| Each feature draws its own overlay | Gate tiles draw plate boxes only; the box carries a plate, never a person's name (P6-FR-042). |
| Geometry crosses as fractions | Unchanged; the pixel width shown is display information computed from the frame, not wire geometry in pixels. |
| Degradation is payload, never a 5xx | The invisible-box defect was precisely a validation failure standing in for a payload; the regression test in P6-FR-042 pins the fixed path. |
| Detections wait for a human | Alerts wait for a person, dismissals are audited first, blacklist history and its Home item are unchanged (P6-FR-046, -047). |
| Audit before the result | Alert dismissal and the day export both write first (P6-FR-047, -051). |
| Feature isolation | Vehicle gate still runs with everything else off; a reader swap touches nothing outside reading (P6-FR-040, SC-007). |
| Real-time experience | The box must appear while the car is still there; the reader table and boxes run only while watched, so idle cost stays zero (P6-FR-042, -043). |

## Assumptions

- **The owner provides the evaluation material** — photographs or a short recording
  of real plates with their true numbers, enough to make 95% a meaningful figure.
  Until it arrives, the accuracy half is blocked and says so; the redesign half
  proceeds. (Chosen 27 Aug 2026, with the target: 95% at ≥100 px.)
- **Diagnose first, replace on evidence** was chosen by the owner on 27 Aug 2026
  over replacing immediately, and over never replacing.
- **Dropping the per-pass list** was the owner's decision on 27 Aug 2026, taken
  after the costs were laid out (P6-FR-052 records them). The engine keeps
  recording everything; presentation is what changes.
- **Two known suspects** go into the diagnosis first: the reader runs at a lower
  numeric precision than the source project it was ported from, and until the box
  path is fixed nobody has ever seen what the reader sees live. Neither is assumed
  to be the cause; both get measured.
- **"One edit"** for the near-match suggestion is the same closeness rule the
  frame-voting already uses to merge readings — one rule, not two.
- **Alert lifetime**: an alert belongs to the pass that raised it. It survives
  page reloads until cleared; a new qualifying pass raises a new one. Cleared
  blacklist items remain in history per the first build.
- **The reader table's depth** is the last handful of attempts per camera — enough
  to watch votes gather; it is a live window, not a stored log.
- **The design file is the drawing of record** for layout and wording:
  `design/27-8 design/VisionGuard.dc.html`, Vehicle gate section only.
