# Feature Specification: Knife detection — one video per scene, reviewed by a person

**Feature Branch**: `004-knife-detection`
**Created**: 2026-08-22
**Status**: Draft
**Input**: User description: "now we will work on knife detection page. we will find a new added knifebest.pt file use it. it will be so simple page that is if knife is detected on any camera a video is recorded for this scene, but avoid flickering generates multiple videos of the same scene. Period has to have more variations for better UX. be ready because this feature mainly on later spec will push alerts via whatsapp, sms, and gmail, so take this in consideration for later work. simple easy to use page. of course videos can be opened and played. ask me first discuss with me. applying such feature on all cameras is acceptable on processing?"

## Why this feature

The Knife detection page is entirely invented today: a fixture "Main gate"
detection, a review flow that changes nothing, and a status line that once
read "No knife detected on campus" from no measurement at all. Meanwhile the
owner has supplied a trained, single-class knife model, and the engine already
knows how to record a scene to a playable clip (restricted zones). This
feature makes the page real in its simplest honest form: a knife seen on any
camera becomes one entry with one video, which an operator can watch and then
judge. That judgement is the record the later alert feature (WhatsApp, SMS,
Gmail) will send from.

## User Scenarios & Testing

### Primary story

An operator opens **Knife detection**. The page says which cameras are being
checked right now. Somebody on one of those cameras holds a knife. Within a
few seconds an entry appears — camera, area, time — and the scene is being
recorded. The knife goes out of view; ten seconds later the recording stops
and the entry offers **Watch**. The operator watches the clip and presses
**Confirm knife** or **False alarm**; the entry now shows who decided and
when. Nothing is sent to anybody by the detector itself.

**Acceptance scenarios**

1. **Given** knife detection is running on a camera, **When** a person holds a
   knife in view for about a second or more, **Then** one entry appears within
   5 seconds of the first sighting and recording is under way.
2. **Given** a scene is being recorded, **When** the detector loses the knife
   for less than ten seconds and finds it again, **Then** the result is one
   entry and one video, not several.
3. **Given** a scene is being recorded, **When** the knife has been out of view
   for ten continuous seconds, **Then** the video is saved and plays from the
   entry's **Watch** control, and the entry shows how long the scene lasted.
4. **Given** the model flags something for a single frame, or flags an object
   that is not on or beside a person, **When** this happens, **Then** nothing
   is logged and nothing is recorded.
5. **Given** an entry awaiting review, **When** the operator presses **Confirm
   knife** or **False alarm**, **Then** the entry shows that verdict with the
   signed-in account's name and the time, stays in the list, and cannot be
   returned to "awaiting review".
6. **Given** entries from several days, **When** the operator picks
   **Yesterday**, **Then** only entries from yesterday (the site's calendar
   day) are listed; **All** lists everything ever recorded.
7. **Given** an entry older than the retention period, **When** the operator
   views it, **Then** it is still listed, says its video is no longer kept,
   and offers no Watch control.
8. **Given** knife detection is not running, **When** the operator opens the
   page, **Then** it says so and why — it never says "no knife detected".

### Edge cases

- Camera offline: its tile says NO SIGNAL; nothing can be checked there and
  the page must not imply it is.
- Person detection is not running: knives are looked for on people, so the
  page says knives cannot be checked, and why.
- The engine restarts mid-scene: the entry is closed on the next start; the
  video is either saved or marked failed with a reason — never a dead button.
- A manual recording is already running on that camera: the entry is logged
  without a video and says why.
- Two people or two knives in one view: one entry per camera per scene, with
  the highest confidence seen.
- A knife stays in view for a long time: the scene is cut at the limit, the
  entry says so, and a new scene starts while the knife is still there.
- The model file is missing or fails to load: the page and System Health say
  knife detection failed to start, with the reason.
- Nothing has been seen yet: the page says nothing has been seen in the
  chosen period, which is different from "not running".

## Requirements

- **P6-FR-001**: Knife detection MUST run on every enabled camera. There is
  no per-camera switch in this feature.
- **P6-FR-002**: A frame MUST be checked for knives only when at least one
  person is in view, and a knife MUST count only when it is on or beside a
  detected person (its box centre lies inside that person's box). A knife
  lying somewhere with nobody near it is, by design, not detected — the page
  says so.
- **P6-FR-003**: An entry MUST open only after the knife has been seen
  repeatedly over at least one second. A single sighting MUST NOT create an
  entry or a video. The entry's time is the first sighting.
- **P6-FR-004**: Recording MUST start when the entry opens and stop after ten
  continuous seconds with no knife in view. Shorter gaps MUST NOT split or
  end the scene. A scene MUST be cut at two minutes; the entry says it was
  cut, and a knife still in view starts a new scene.
- **P6-FR-005**: Each entry MUST show the camera, its area, the time
  (site-local), how long the scene lasted, the highest confidence seen, the
  review state and the video state.
- **P6-FR-006**: A saved video MUST play inline from the entry and MUST be
  openable in its own browser tab. When there is no playable video (still
  recording, failed, no longer kept) the entry MUST say why instead of
  offering a control.
- **P6-FR-007**: Any signed-in user MUST be able to mark an entry **Confirmed**
  or **False alarm**. The server MUST record the signed-in account and the
  time — never a name typed by the client. A verdict moves only from
  "awaiting review" to confirmed or false alarm, never back. The audit entry
  MUST be written before the verdict is stored.
- **P6-FR-008**: Entries MUST never be deleted, and false alarms MUST stay
  listed. There is no delete.
- **P6-FR-009**: Videos MUST be kept for the configured retention period
  (30 days by default). After that the file is removed; the entry stays,
  marked "video no longer kept". There is no per-camera cap on knife videos.
- **P6-FR-010**: The period selector MUST offer Today · Yesterday · Last 7
  days · Last 30 days · Last 90 days · This school year · All. Today and
  Yesterday are the site's calendar days; "This school year" starts at the
  configured term start. The default is Last 30 days.
- **P6-FR-011**: The page MUST state what is actually running — how many
  cameras are being checked — and, when knife detection is not running, the
  reason. It MUST never claim an all-clear from no measurement.
- **P6-FR-012**: The knife page MUST draw only knife boxes (red, labelled
  "Knife" with its confidence) on its cameras — never a face, a name or a
  tracking id.
- **P6-FR-013**: Knife detection MUST NOT require any other feature to be
  switched on for a camera, and switching it on or its failing MUST NOT
  change counting, restricted zones, tracking or attendance.
- **P6-FR-014**: Nothing MUST be sent to anyone because of a detection. The
  human verdict is the only thing a later alert feature may fan out from. An
  entry MUST keep everything such an alert will need: camera, area, time,
  confidence, video, verdict, reviewer, review time.
- **P6-FR-015**: System Health MUST show knife detection as its own stage:
  model version, where it runs (GPU or CPU), how many cameras, and the last
  inference time — or the reason it is not running.
- **P6-FR-016**: The list MUST refresh itself while the page is open: a new
  entry, and a video becoming watchable, appear without navigating away.
- **P6-FR-017**: The model file and the confidence threshold MUST be
  configuration, not code. The timing rules (one second to open, ten seconds
  to close, two-minute cut, retention days) MUST be named in one place and
  stated on the page where they affect what the operator sees.

## Success Criteria

- **SC-001**: A knife held in view produces a visible entry within 5 seconds
  of the first sighting, with recording under way.
- **SC-002**: One scene with detector flicker shorter than ten seconds yields
  exactly one entry and one video.
- **SC-003**: The two recorded clips in the regression suite (neither contains
  a knife) produce zero entries — the measured false hits on them never form
  a scene.
- **SC-004**: Watch plays the scene in the browser; Open shows it in a new
  tab.
- **SC-005**: An operator can tell within 2 seconds whether the page shows
  real checking, an empty-but-working state, or a broken subsystem.
- **SC-006**: A verdict shows on the entry, with the reviewer's name, within a
  second of the click, and survives a page reload and an engine restart.
- **SC-007**: Entries survive an engine restart; videos older than the
  retention period are gone from disk while their entries remain listed.
- **SC-008**: With knife detection running on every camera of the development
  laptop, person detection stays within its measured latency budget
  (p95 ≤ 250 ms), and the plan states the cost per camera for sizing.

## Out of scope

- Sending alerts — WhatsApp, SMS, Gmail, in-app. The next spec. This one only
  records what an alert needs and the one point it may fan out from.
- The Home page "Needs your attention" feed — lands with the alert spec.
- A per-camera on/off switch for knife detection.
- Video of the seconds before the first sighting (no pre-roll buffer).
- A knife with nobody near it.
- Other weapons (guns, bats): the supplied model knows one class, knife.
- Model management, benchmarking UI, choosing between models.
- Deleting or editing entries. Mobile.

## Constitution check

- **No fake data (rule 4)**: the fixture detection, the "Show a live
  detection" walk-through and the "police notified" wording go. Empty,
  degraded and not-running states each get their own sentence.
- **Never claim precision (rule 5)**: the headline counts cameras actually
  being checked; confidence is shown as the model's number, not as a verdict.
- **Honest degradation (rules 7, 8)**: model missing, person detection down,
  recorder busy — each reaches the page and System Health as payload.
- **Feature independence (rule 9)**: consumes the shared person-detection
  result; no other feature needs to be on; nothing else changes.
- **Human gate (rule 10)**: the detector never notifies; confirm/false alarm
  is the only verdict; false alarms stay; no delete.
- **Face vs clothing (rules 1, 3)**: the knife overlay carries no identity;
  the page draws its own boxes.
- **Geometry (rule 6)**: boxes cross the API as fractions of the frame.
- **Privacy (IV)**: videos of minors kept only for the retention period, then
  removed; the record of the event stays without the footage.
- **Audit (rule 11, III)**: the verdict's audit entry is written before the
  verdict.

## Assumptions

- **The owner's four answers were not given; the recommended options were
  taken on 2026-08-22 and can be changed by amending this spec**: all
  cameras, only while a person is in view (Q1 A); review buttons now, alerts
  fan out from Confirm later (Q2 A); videos kept 30 days, entries forever
  (Q3 A); the seven fixed periods (Q4 A).
- The supplied `knifebest.pt` (one class, knife; trained 13 Aug 2026)
  replaces the 18-prompt zero-shot model and the CPU-only ONNX copy of
  itself. Its accuracy on school cameras is unmeasured; the thresholds come
  from the two recorded clips, where the false hits were room furniture
  outside the person's box. A short recorded clip with a real knife is needed
  before go-live and joins the regression suite.
- Starting values, all tunable: confidence 0.5; seen in 3 analysed frames
  spanning at least 1 s to open; 2 s without a knife to close (was 10 s;
  **changed by the owner on 22 Aug 2026** after testing with a real knife —
  ten seconds of nothing at the end of every clip was most of a short clip);
  2-minute cut;
  30-day retention. The video starts when the entry opens, about a second
  after the first sighting; the knife is still in view by definition.
- The reviewer is the signed-in account. Reviewing is an operator action, not
  admin-only.
- The page keeps its existing name, "Knife detection", and its place in the
  navigation.
