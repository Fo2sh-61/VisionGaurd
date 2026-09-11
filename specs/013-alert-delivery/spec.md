# Feature Specification: Alert Delivery — WhatsApp, SMS, Email and in-app

**Feature Branch**: `013-alert-delivery`
**Created**: 11 Sep 2026
**Status**: Draft
**Input**: User description: "Alert Delivery — WhatsApp, SMS, Email and in-app. The engine
sends a short factual message to a configured list of people when a knife is seen, a
restricted zone is breached, a gate raises an alert, a camera goes dark, and at noon with
the day's attendance counts. Twilio carries WhatsApp and SMS; Gmail carries email; the Home
'Needs your attention' feed is the in-app channel. Full prompt and the owner's decisions of
11 Sep 2026 in `docs/013-ALERTS-SPEC-PROMPT.md`." This is P9 in `docs/PLAN.md` and closes FR-14.

## Why this feature

VisionGuard already sees a knife, a breach, a blacklisted car and a dead camera — and then
waits for somebody to be looking at the screen. A head of security in another building
learns nothing until they walk over. Today the Settings page *looks* as if alerts are
configured: it has rules, channels, destinations and quiet hours, and it says edits save on
their own. None of it reaches the engine, nothing is stored, and nothing is ever sent. That
is a control that does nothing, and it has to become real or go.

After this feature an administrator adds the people who should hear, chooses which kinds of
alert reach which channel, proves the wiring with a test message on a real phone, and can
read back exactly what was sent, to whom, and whether the courier took it.

## User Scenarios & Testing

### Primary story

The head of security adds her WhatsApp number in Settings, in Arabic, and switches WhatsApp
on for knife alerts. She presses **Send test** and the message arrives on her phone; the log
under the recipients shows it as sent, with the time. That afternoon the knife model opens an
entry on the yard camera. Within seconds her phone shows, in Arabic: a possible knife, the
camera, the time, the confidence, **awaiting review — not yet confirmed by a person**, and a
link to the Weapons page. A guard at the desk presses **False alarm**. A second message
follows, naming the guard and the verdict, so she is not left holding a scare. Both messages
are in the log; neither contains a child's name or a picture.

**Acceptance scenarios**

1. **Given** an administrator on Settings, **When** they add a recipient (channel,
   destination, display name, language, on/off), **Then** the recipient is stored by the
   engine, is still there after a restart, and the change is in the audit trail before it
   was saved.
2. **Given** a recipient row, **When** the administrator presses **Send test**, **Then** a
   real message goes to that destination, the audit entry is written first, and the log
   shows the outcome — sent with the courier's reference, or failed with the courier's own
   reason.
3. **Given** WhatsApp is on for knife alerts and two WhatsApp recipients are switched on,
   **When** a knife entry opens, **Then** each recipient receives exactly one message marked
   awaiting review within 10 seconds, and no further message while the entry stays open.
4. **Given** that entry, **When** a person presses Confirm or False alarm, **Then** each of
   the same recipients receives exactly one follow-up carrying the verdict and the
   reviewer's name.
5. **Given** a restricted-zone scene opening, a gate alert being raised, or a camera that
   has shown NO SIGNAL for the configured minutes, **When** the rule for that kind has a
   channel on, **Then** one message per recipient goes out on that channel; when the camera
   comes back, one more says so.
6. **Given** a school day, **When** the site clock reaches 12:00, **Then** each recipient on
   an enabled attendance channel receives the present, late and absent counts per group and
   a link to the Attendance page, and nothing that names a student.
7. **Given** no Twilio keys are configured, **When** an administrator opens Settings or
   System Health, **Then** the WhatsApp and SMS rows say plainly that WhatsApp and SMS
   cannot be sent because no Twilio key is set and that detection is unaffected; every
   would-be send appears in the log as skipped with that reason. The same holds for Gmail.
8. **Given** wrong provider keys, **When** a test send or a real alert is attempted,
   **Then** the failure and the provider's own reason are visible in the log within a
   minute.
9. **Given** a guard signed in, **When** they try to add a recipient or change a rule,
   **Then** the engine refuses; **When** they acknowledge an item in "Needs your attention",
   **Then** it is accepted, audited, and the item leaves the feed without deleting anything.
10. **Given** the engine restarts with an open knife entry, an open scene and a camera still
    offline, **When** it comes back, **Then** no message is sent again for any of them.

### Edge cases

- **The courier is slow or down.** Detection, recording, the knife review gate and every
  console page behave exactly as they do with the courier reachable. Sends queue; a queue
  that fills drops the oldest and records each drop as failed with that reason.
- **A rule has a channel on but nobody receives on it.** Settings says so in a sentence
  ("WhatsApp is on for knife alerts but nobody receives WhatsApp"); the send is logged as
  skipped, not silently absent.
- **A recipient is switched off.** They receive nothing and the skip is logged with that
  reason; switching them back on does not replay anything missed.
- **The engine was down at noon.** The report is logged as skipped with that reason, not
  sent late. It is never sent twice for one day.
- **A knife entry opens while the queue is full**, or **two entries open on two cameras in
  the same second** — each is one event, each gets its own rows, none is merged.
- **The scene that opens has a recognised student in it.** The message names the camera and
  the time, and never the student, never a face, never a frame.
- **The recipient's language is Arabic** and the Arabic wording has not yet been read by a
  native speaker. As with Ask, the Arabic column renders only in dev until Mohamed corrects
  it; a production recipient with Arabic selected is told so in Settings rather than sent
  unreviewed text.
- **The log is unavailable** (the table cannot be read). The Settings card says so with the
  reason instead of showing an empty list.
- **The "Notify parent" button on Attendance** stays disabled with its existing reason.
  Parents are not recipients of this feature and nothing here makes that sentence untrue.

## Requirements

Numbered `P9-FR-xxx`. Product-level `FR-14` belongs to `docs/PLAN.md`.

### What is sent, and when

- **P9-FR-001**: The system MUST send one message per recipient, on each channel a rule has
  switched on, for each of five alert kinds: a knife entry opening (`weapon`), a
  restricted-zone scene opening (`intrusion`), a gate pass raising an alert (`vehicles`), a
  camera that has shown NO SIGNAL for a configured number of minutes (`camera`, default 5),
  and the daily attendance report (`attendance`).
- **P9-FR-002**: A knife entry MUST produce exactly two messages per recipient and no more:
  one when the entry opens, marked **awaiting review — not yet confirmed by a person**, and
  one when a person records the verdict, carrying Confirmed or False alarm and the
  reviewer's name. The detection message is the only action that hangs from detection; no
  lock, call or any other action may.
- **P9-FR-003**: A camera MUST produce one message when it has been NO SIGNAL for the
  configured minutes and one when it is back, never one per poll.
- **P9-FR-004**: The `vehicles` kind MUST send for each of the three reasons a gate pass
  can raise an alert — blacklisted, not registered, expired permit — and an administrator
  MUST be able to switch each reason on or off on the rule. All three are on by default.
  (Decided 11 Sep 2026.) The message MUST wait until the plate reader is done with the
  pass - the car has left the camera - and state the final reading: the reader corrects
  its first reading as the car comes closer, and a message sent from the first one would
  be wrong whenever it does. A person correcting a plate by hand sends nothing. (Decided
  with Mohamed, 11 Sep 2026: a few seconds late and right.) A car still in view when the
  engine stopped is logged at the next start as not sent - never sent late, since the
  message gives a time and no date.
- **P9-FR-005**: Every message MUST be tied to one event — one entry, one scene, one pass,
  one camera transition, one calendar day — so that a restart, a repeated poll, or a
  repeated frame never sends it again.
- **P9-FR-006**: Lost bag, track, counting and every other feature MUST send nothing.

### The message

- **P9-FR-007**: A message MUST carry only facts: what happened, the camera, the time, the
  confidence where there is one, the review state, who decided (a staff name) where a
  person did, and a link that opens the matching console page.
- **P9-FR-008**: A message MUST NEVER contain a student's name, a face, a snapshot, a clip
  or a plate photograph. Plate text and staff names are allowed. This MUST be enforced where
  the message is built, and proved by a test that builds a message from a scene with a
  recognised student and asserts the name and any image are absent.
- **P9-FR-009**: Each recipient has a language, Arabic or English, and MUST receive the
  message in it. The wording catalogue lives in the engine in both languages. This is a
  deliberate exception to the "engine sends codes, console writes sentences" contract of
  P11, because there is no console at the far end of an SMS.
- **P9-FR-010**: The attendance report MUST carry present, late and absent **counts** per
  group and a link to the Attendance page, and nothing else.

### Recipients and rules

- **P9-FR-011**: An administrator MUST be able to keep any number of recipients per external
  channel (WhatsApp, SMS, email). Each has a channel, a destination, a display name, a
  language and an on/off state. Phone numbers are stored in international form.
- **P9-FR-012**: A recipient receives every alert kind whose rule has that recipient's
  channel on. There is no per-recipient filter.
- **P9-FR-013**: Each recipient row MUST offer **Send test**, which really sends, is audited
  before it sends, and lands in the log like any other message.
- **P9-FR-014**: Rules MUST be one row per alert kind with a chip per channel: **In-app ·
  WhatsApp · SMS · Email**. The channel formerly labelled "Push" becomes In-app; no push
  service exists and none is promised. The `vehicles` row additionally carries the three
  reason switches of P9-FR-004.
- **P9-FR-015**: On a fresh install every external channel MUST be off and no recipients
  exist, so nothing is sent until an administrator adds somebody and switches a rule on.
  In-app is on by default.
- **P9-FR-016**: Recipients, rules and the delivery log MUST survive a restart. They live in
  the engine, not the console, and do not wait for the durable audit trail (P3).

### The in-app channel

- **P9-FR-017**: "Needs your attention" on Home (console and phone) MUST show the real open
  items — knife entries awaiting review, today's open zone scenes, today's gate alerts,
  cameras offline past the configured minutes — derived from where those items already
  live, never a second copy that can drift.
- **P9-FR-018**: Acknowledging an item MUST write one audited row and remove the item from
  the feed. It deletes nothing and changes no review state.
- **P9-FR-019**: The `attention` capability MUST read LIVE whenever the feed can be built,
  and carry no reason, because a live capability never explains itself (an existing,
  tested rule). A provider with no keys MUST instead be named on System Health's
  alert-sending row and on Settings, saying which channels cannot send and that detection
  is unaffected.

### The daily report

- **P9-FR-020**: The attendance report MUST go out at 12:00 site time on school days, using
  the site timezone per instant, once per day and never twice after a restart.
- **P9-FR-021**: A noon the engine was down for MUST be logged as skipped with that reason
  and never sent late.
- **P9-FR-022**: A school day is Sunday to Thursday falling inside the term dates held in
  the school profile. No report goes out on Friday, Saturday, or outside term. A public
  holiday inside term still gets a report, which will show everyone absent. (Decided
  11 Sep 2026.)

### The delivery log and honest states

- **P9-FR-023**: Every attempted message MUST be one row in the log with one of four
  outcomes: queued; sent, with the courier's reference; failed, with the courier's reason
  after a bounded number of retries, or because it was dropped from a full queue or was
  still waiting when the engine stopped; or skipped, with the reason (nobody receives on
  the channel, provider not configured, recipient switched off, engine down at noon,
  attendance not being recorded). A message that could not go is a row, never a missing
  row. A channel switched off in a rule is not an attempt and writes nothing, so the log
  is not buried under messages nobody asked for.
- **P9-FR-024**: "Sent" MUST mean only that the courier accepted the message. The console
  MUST NEVER say delivered or read unless the courier reported it.
- **P9-FR-025**: Settings MUST show the log under the recipients: newest first — time,
  kind, channel, recipient name, outcome, reason.
- **P9-FR-026**: With no keys for a provider, the Settings rows for its channels and the
  `attention` capability MUST say which keys are missing, that those channels cannot send,
  and that detection is unaffected. Wrong keys MUST surface as a failed test send or a
  failed row within a minute, with the courier's own reason.
- **P9-FR-027**: Settings MUST show, in a sentence, a rule with a channel on and nobody
  receiving on it, a failed send with its reason, and the log itself being unavailable.
- **P9-FR-028**: Every control on the Alerts section of Settings MUST save through the
  engine on every change and show an error when the save fails. Quiet hours MUST be removed
  from the page rather than left as a control that does nothing; it returns only as its own
  small change if somebody asks for it. (Decided 11 Sep 2026.)

### Isolation and reliability

- **P9-FR-029**: Sending MUST never run on a camera thread. Events go on a bounded queue
  drained by one sender. A courier that is slow or down MUST change nothing about
  detection, recording, review or the console.
- **P9-FR-030**: A full queue MUST drop the oldest event and log the drop as failed with
  that reason, never silently.
- **P9-FR-031**: No other feature may require alert delivery to be configured or on, and
  alert delivery may not require any other feature to be on.

### Permissions, audit and secrets

- **P9-FR-032**: Adding, changing or removing a recipient, changing a rule, and Send test
  MUST be administrator-only, decided server-side by path, and MUST write the audit entry
  before the thing they record.
- **P9-FR-033**: Acknowledging an in-app item MUST be the one write here a guard may make,
  audited and naming the account, exactly as dismissing a gate alert is.
- **P9-FR-034**: Provider secrets MUST live only in the engine's environment file, never in
  the engine configuration, and MUST never appear in a response, a log line, a delivery-log
  row or an audit entry.
- **P9-FR-035**: The terms accepted MUST be recorded, as Ask recorded Gemini's: Twilio and
  Google see the text of every message, and what leaves the site is bounded by P9-FR-007
  and P9-FR-008.
- **P9-FR-036**: The console MUST never talk to a courier. It configures and reads; the
  engine sends.
- **P9-FR-037**: The demo store keeps its fixtures for `-Mock`; the live path MUST NOT
  borrow any of them, and a test MUST pin that.

## Success Criteria

- **SC-001**: An administrator adds a WhatsApp number, an SMS number and a Gmail address,
  presses Send test on each, and each message arrives on the real phone and in the real
  inbox; the log shows each as sent, with the time.
- **SC-002**: A knife entry opening on the recorded clip produces exactly one message per
  switched-on channel per recipient within 10 seconds, marked awaiting review; pressing
  Confirm or False alarm produces exactly one follow-up. Restarting the engine re-sends
  nothing.
- **SC-003**: A zone scene, a blacklisted car and a camera offline for the configured minutes
  each produce their message; lost bag, track and counting produce nothing.
- **SC-004**: At 12:00 site time on a school day the attendance report arrives with counts
  only — no student name in it.
- **SC-005**: With no provider keys, Settings and System Health say so plainly, detection
  carries on, and every would-be send is in the log as skipped with the reason. With wrong
  keys, the failure is visible within a minute with the courier's reason.
- **SC-006**: Every recipient, rule and log row survives a restart; every change and test
  send is audited before it happens; a guard cannot change recipients or rules and can
  acknowledge an in-app alert.
- **SC-007**: No message ever contains a student's name, a face or an image — proved by a
  test, not a review — and an Arabic recipient receives Arabic.
- **SC-008**: The existing automated gates pass, including the phone app's type check and
  the console-phone parity check, and the Settings page shows nothing it cannot save.

## Out of scope

- Parents as recipients. The disabled "Notify parent" button stays disabled with its reason.
- Push notifications to phones. In-app means the Home feed, nothing more.
- Images, clips or snapshots in any message.
- Inbound replies — acknowledging by answering a WhatsApp.
- Per-camera, per-zone or per-recipient rules; escalation chains; quiet hours.
- Delivery or read receipts beyond what the courier returns.
- Meta's WhatsApp API directly, or any second provider per channel.
- Any change to detection, review or gate logic; gun detection.
- The durability of the audit trail (P3).
- Mobile work. The shared contract files carry the change to the phone; the phone's own
  copy of the Settings page needs only to keep compiling.

## Constitution check

- **III — Truthful data.** This feature exists to remove a fake save. P9-FR-023 to
  P9-FR-028 make every state on screen a state the engine holds: "sent" is what the courier
  said, "skipped" is a row with a reason, an unconfigured provider is a sentence, a missing
  recipient is a sentence. P9-FR-017 keeps the in-app feed derived from the stores that
  already hold the items, so it cannot drift from the pages it points at. P9-FR-037 keeps
  the live path off the fixtures.
- **IV — Secrets.** P9-FR-034: keys live in the environment file only and never leave in
  any response, log or audit row. The camera-password test from camera onboarding is the
  pattern.
- **IV — Minors' data.** P9-FR-007 and P9-FR-008 bound what leaves the site to facts about
  an event: camera, time, confidence, state, staff name, plate text. No student name, no
  face, no image, ever, enforced at the point of building and pinned by a test. P9-FR-035
  records that the couriers see every message and that the owner accepts this on that
  basis.
- **IV — The human decision gate. This feature deliberately amends it.** PLAN §6 says
  "No notify/call/lock can be triggered by the detector. The review endpoint is the only
  thing that fans out", and the weapon review method's docstring says the same. The owner
  decided on 11 Sep 2026 that a knife entry opening sends a message marked awaiting review
  and that the verdict sends a second. **The cost is stated plainly**: the measured
  false-alarm rate is not zero (one 12.5 s entry per roughly four loops of clean footage,
  per STATUS), so false alarms will reach phones. What does not change: no lock, call or
  other action hangs from detection (P9-FR-002); the verdict still needs a person; false
  alarms stay in history. The PLAN §6 row and the docstring MUST be amended when this is
  planned, so the documents stop disagreeing with the code.
- **II — A feature must not slow another.** P9-FR-029 to P9-FR-031: one bounded queue, one
  sender, off every camera thread. A courier outage costs nothing but the messages, and
  those are logged as such.
- **V — No no-op controls.** The Alerts section either saves for real or the control goes;
  quiet hours goes (P9-FR-028). Every honest state has a sentence.
- **Server-side permissions.** P9-FR-032 and P9-FR-033: admin by path, with acknowledgement
  the single guard write, mirroring gate-alert dismissal.
- **Audit before the write.** P9-FR-013, P9-FR-018, P9-FR-032.

## Assumptions

- **Providers are decided**: Twilio for WhatsApp and SMS, Gmail SMTP with an App Password
  for email, one implementation per channel behind one seam. The product sells in Egypt
  only.
- **Non-secret settings** (on/off per provider, timeouts, the camera-offline minutes, the
  report hour) sit in an `alerts:` section of the engine configuration; secrets in
  `engine/.env` under `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
  `TWILIO_SMS_FROM`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`.
- **The site timezone is Africa/Cairo** and is read from the site clock per instant, not
  fixed at startup.
- **Log retention is 90 days.** Rows older than that are removed; nothing else here is ever
  deleted. To be challenged if the school wants longer.
- **A bounded number of retries** means a small fixed count with a short pause between,
  after which the row is failed with the last reason. No retry framework.
- **The queue is bounded at a small fixed size** set in the engine configuration, sized so
  a day of alerts at the school's scale fits with room to spare.
- **The existing wire shapes change**: the rule shape gains WhatsApp and renames push to
  in-app; the single-destination delivery-target shape becomes a list of recipients; the
  in-app item gains the `vehicles` kind; the unused WebSocket frame is not built on. The
  shared contract files carry these to the phone.
- **Gate reasons default to all three on.** The owner chose every gate alert as the
  starting point, with the switches there for a school that finds unregistered visitors
  too noisy. A reason switched off is logged as skipped with that reason, not dropped.
- **The daily report counts** come from the attendance register as the Attendance page
  already computes them, per group; the report adds no calculation of its own.
- **The verdict goes to exactly the recipients the "awaiting review" message went to**, so
  whoever got the scare gets the answer. A recipient added in between hears nothing about
  that entry; one switched off or removed in between gets no verdict.
- **A long incident is one incident.** The knife and zone features cut a scene at two
  minutes and reopen at once while the knife or the person is still there. The reopened
  entry is a continuation and sends nothing; only the first entry of a continuous run
  sends, so a person standing in a restricted room for ten minutes is one message, not
  five.
- **Arabic wording is drafted by the agent** and renders only in dev until Mohamed corrects
  it, exactly as Ask's did.
- **Message text is short** — a few lines, no formatting, so one WhatsApp, one SMS segment
  where possible, and one plain-text email say the same thing.
- **The console link in a message** is the console's own address as configured, opening the
  Weapons, Zones, Vehicles, Cameras or Attendance page with the item selected where the
  page supports it.
