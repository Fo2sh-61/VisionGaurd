# Feature Specification: Local Ask — answers on the Jetson, with clips

**Feature Branch**: `spec/028-local-ask`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: User description: "Ask runs fully locally on the Jetson with the least
processing, and is smarter about video clips. Gemini is removed and nothing
leaves the site."

## Why this feature *(mandatory)*

Ask (spec 010) works, but a cloud model chooses the query. It scored 91.9%
against a 95% bar, Egyptian Arabic was its weakest language, its free allowance
cannot cover a school day, and every question sends text off-site. Ask also
stops at rows: a guard who reads "Sara came in at 7:52, gate camera" still has
to go and find the video. This spec makes Ask run entirely on the site's own
Jetson, with nothing sent anywhere, and lets every answer that has a camera and
a time show the moment it describes.

## User Scenarios & Testing *(mandatory)*

### Primary story

A guard types "وريني سارة دخلت امتى النهاردة". Nothing leaves the building.
Word lists on the Jetson find the name, "النهاردة" and "وريني". A small local
meaning model picks *attendance* as the closest match to its example questions.
Ask runs the same attendance query as before and shows the arrival row with
the "understood as" line. Because the guard asked to *see* it, Ask
fetches the first row's clip, about 10 seconds either side of 7:52 on the gate
camera, and plays it. The fetch is in the audit trail before the first frame
plays.

**Acceptance scenarios**

1. **Given** the site has no internet at all, **When** any supported question
   is asked, **Then** Ask answers exactly as it would with internet, and nothing
   is sent off-site.
2. **Given** a question in Egyptian Arabic, standard Arabic, Arabic in Latin
   letters, English or a mix, **When** it names a known person, plate, place,
   group or date, **Then** the "understood as" line shows the right query with
   the right person, plate, place, group and day.
3. **Given** a question whose best match is weak, or whose top two matches are
   close, **When** it is asked, **Then** Ask does not guess. It shows "did you
   mean …?" with two buttons, one for each query in plain words, and runs only
   the one the operator picks.
4. **Given** an answer row with a camera and a time, **When** the operator
   presses "watch clip", **Then** the clip plays. Breaches and weapons use
   their saved clip. Every other row gets a clip from the recorder, from about
   10 s before that moment to 10 s after it.
5. **Given** a question with a video word (وريني, فيديو, مقطع, اشوف, show me,
   video, clip), **When** the answer has at least one row with a camera and a
   time, **Then** the first row's clip is fetched without being asked.
   Without a video word, Ask offers "want me to fetch the clip?" instead.
6. **Given** the recorder is unreachable, or the footage for that moment has
   expired or was never recorded, **When** a clip is asked for, **Then** Ask
   says which of these it is in plain words. The button never spins forever and
   never fails silently.
7. **Given** a feature that is switched off on this site (knife, lost bag or
   tracking under console v2), **When** a question about it is asked, **Then**
   Ask says the feature is switched off on this site. It does not say "nothing
   found" and does not answer with another query.
8. **Given** nobody is asking anything, **When** the cameras are running,
   **Then** Ask does no work at all.
9. **Given** Ask understood "مين اللي اتزوغ من تالتة ب" as the wrong query,
   **When** an administrator marks the right query, **Then** the next person
   who asks it, or something close to it, gets the right query. The
   correction appears in the list of learned examples with who added it and
   when.
10. **Given** an operator picks one of the "did you mean" buttons, **When** the
    answer is shown, **Then** the pick is kept as a suggested example. It
    takes effect only once an administrator approves it.
11. **Given** "وريني كاميرا البوابة دلوقتي" with no past time, **When** it is
    asked, **Then** Ask opens that camera's live view. The same question with
    a past time ("الساعة ٨ الصبح") gets that moment's clip instead.

### Edge cases

- **The meaning model is missing, broken or failed to load.** Ask says it is
  unavailable and why, on the Ask page and in System Health. Every other
  feature runs as before (constitution rule 8).
- **The recorder is fine but the moment is only seconds old.** The recording
  may not be readable yet. Ask says the footage is not available yet, not
  that it does not exist.
- **A row has a time but no camera, or a camera but no time** (a gate total, a
  directory entry). It gets no "watch clip" button. The button is never shown
  disabled.
- **A video word with nothing to show** ("وريني الفيديو" on an empty result).
  Ask shows the empty result as it is and fetches nothing.
- **A date word Ask does not know** ("أول امبارح العصر"). If it cannot place
  the day, it asks which day. It does not assume today without saying so on
  the "understood as" line.
- **Two people share a name; a plate is typed in Arabic-Indic digits.** Same
  rules as spec 010: Ask asks which person, and the register collapses both
  digit forms onto one row.
- **The Jetson is under full camera load.** Ask may answer more slowly, but it
  must not slow the cameras (SC-006).
- **A correction that would make Ask worse.** A learned example that pulls a
  test question to the wrong query is refused, with the question it would
  break. It is not saved quietly.
- **A correction typed with a child's name in it.** The example is kept with
  the name, plate and date replaced by placeholders. A learned example never
  stores who it was about, and it covers everybody, not only that child.
- **"Live view" of a camera that is offline, or that the account may not
  see.** Ask says it is offline, or that it is not permitted, the same way the
  camera page would. It never opens a blank or frozen view that looks live.

## Requirements *(mandatory)*

Numbered `P15-FR-001`. P15 is a new phase after P14 (console v2) and must be
added to `docs/PLAN.md` when this is planned. Everything in P12 still holds
unless a line below replaces it.

### Local only

- **P15-FR-001**: Choosing the query MUST happen entirely on the site's own
  hardware. No question, word, placeholder or result may leave the site, and
  Ask MUST work with the internet cut off.
- **P15-FR-002**: The cloud parser MUST be removed, not left as a fallback.
  P12-FR-007 and P12-FR-012 (sending text off-site and recording what went)
  are replaced by this line. The audit entry MUST still hold the question as
  typed, and the "sent off-site" record MUST always be empty.
- **P15-FR-003**: Masking MUST stay. It is now how names and plates resolve to
  real people and vehicles, not a privacy shield. P12-FR-008 and P12-FR-010
  still apply.
- **P15-FR-004**: Choosing the query MUST stay behind the single seam of
  P12-FR-022. Nothing else in Ask changes when the chooser changes.

### Understanding the question, cheapest first

- **P15-FR-005**: Ask MUST recognise, from word lists and before anything
  heavier runs: enrolled names and registered plates (existing), the site's
  places and groups (from site data, so a new room or class is known without a
  code change), date words, and video words.
- **P15-FR-006**: Date words MUST be understood in all four ways people write
  them: Egyptian Arabic (النهاردة, امبارح, الاسبوع ده), standard Arabic
  (اليوم, أمس, هذا الأسبوع), Arabic in Latin letters (ennaharda, embare7) and
  English (today, yesterday, this week). Each one maps to the same windows the
  queries already accept.
- **P15-FR-007**: The query MUST be chosen by a small local meaning model that
  compares the question with example questions. Each query on the menu MUST
  have about 15 examples, kept as site data the owner can read, and no model
  training.
- **P15-FR-008**: When the best match is below a confidence floor, or the top
  two are closer than a set margin, Ask MUST offer "did you mean A or B?"
  buttons instead of answering. Both thresholds MUST be set from the test set
  (SC-001), not chosen by hand, and MUST be changeable without a code change.
- **P15-FR-009**: A question that matches nothing on the menu well enough MUST
  get the P12-FR-013 refusal, not a "did you mean".
- **P15-FR-010**: Ask MUST do no work between questions: no background
  indexing, no warm-up loop, no periodic task. The model may stay loaded in
  memory while idle.
- **P15-FR-011**: The operator's choice on a "did you mean" button MUST be
  audited, and MUST run exactly one query, as every answer does.
- **P15-FR-012**: Ask MUST learn from use without training. A learned
  question becomes one more example for its query and takes effect from the
  next question. It MUST be stored masked: names, plates and dates are
  replaced by placeholders (decided 10 Nov 2026).

### Learning from use

- **P15-FR-022**: An administrator MUST be able to mark any answered question
  as misunderstood and choose the right query. That question becomes a
  learned example straight away.
- **P15-FR-023**: An operator's choice on a "did you mean" button MUST be kept
  as a *suggested* example. It becomes a learned example only once an
  administrator approves it. Operators can teach, but they cannot change Ask
  on their own.
- **P15-FR-024**: Before a learned example is kept, Ask MUST check it against
  the test set (SC-001). If it would send any test question that is correct
  today to the wrong query, it MUST be refused, naming the question it would
  break.
- **P15-FR-025**: Administrators MUST see every learned example: the masked
  question, its query, who added or approved it, and when. They MUST be able
  to remove one. Adding, approving and removing are all audited, and the
  audit entry is written before the change takes effect.
- **P15-FR-026**: The examples the owner wrote MUST stay apart from the
  learned ones, so that removing every learned example puts Ask back to its
  measured starting point.

### Clips

- **P15-FR-013**: Every answer row with both a camera and a time MUST offer
  "watch clip". A row without both MUST NOT show the button at all.
- **P15-FR-014**: Rows that already have a saved clip (breaches, weapons) MUST
  play that clip. Every other row MUST get a clip from the recorder, from about
  10 s before that moment to 10 s after it.
- **P15-FR-015**: Fetching from the recorder MUST work for any camera and any
  time the recorder holds, not only for tracking legs. Opening the recorder up
  this way MUST NOT change how tracking uses it.
- **P15-FR-016**: A question with a video word MUST fetch the first row's clip
  automatically. Any other answer with a clip-able row MUST offer "want me to
  fetch the clip?". Nothing is fetched unless one of these two happens.
- **P15-FR-017**: Every clip fetch MUST be audited (account, camera, time
  span, which question it came from) **before** the clip plays.
- **P15-FR-018**: When a clip cannot be shown, Ask MUST give the real reason:
  the recorder is unreachable, the footage has expired, it was never recorded,
  it is not available yet, or the clip queue is full. It MUST NOT show a dead
  button or a spinner that never ends.
- **P15-FR-019**: A clip MUST be shown only to an account allowed to see that
  row and that camera, decided server-side by path as today.
- **P15-FR-020**: A question asking to see a camera or place with no past
  time ("وريني كاميرا البوابة دلوقتي") MUST open that camera's live view, as
  the console already shows it. This is one new menu entry that reads no data
  and does no calculation (decided 10 Nov 2026). With a past time, the same
  question gets that moment's clip (P15-FR-014). An offline or forbidden
  camera gets the same honest state the camera page shows.

### Honest about what is switched off

- **P15-FR-021**: A query whose feature is switched off on this site (under
  console v2, P14-FR-129: knife, lost bag, tracking) MUST answer "this feature
  is switched off on this site". It MUST NOT answer "nothing found", MUST NOT
  be routed to a neighbouring query, and MUST still appear in what Ask says it
  can answer about, marked as switched off.

## Success Criteria *(mandatory)*

- **SC-001**: On a test set of at least 200 questions, mostly Egyptian Arabic,
  written or corrected by Mohamed, Ask picks the right query with the right
  details for at least 95% of them, overall **and** for Egyptian Arabic on its
  own. A "did you mean" whose two buttons include the right query counts as
  not wrong but is reported separately. Measured with the existing corpus tool.
- **SC-002**: On the same set, no more than 2% of questions get a confident
  answer to the wrong query, meaning no "did you mean" was shown and the
  answer is wrong. Out-of-scope questions are refused at least 90% of the time.
- **SC-003**: With the network cable pulled, every question in the test set
  gets the same result it gets with the network connected.
- **SC-004**: On the Jetson with all cameras running, the operator sees the
  "understood as" line within 1 second of pressing enter, not counting the
  query itself. The time is measured and written into the evidence.
- **SC-005**: Ask's extra memory on the Jetson is measured and stays under
  500 MB.
- **SC-006**: While ten questions are asked back to back, every camera's
  analysis rate stays within 5% of its rate with Ask idle.
- **SC-007**: For a row from the last day on a reachable recorder, the
  operator sees the clip start within 10 seconds of pressing "watch clip".
  Each failure cause in P15-FR-018 shows its own message, checked one by one.
- **SC-008**: Every clip that plays has an audit entry written before it.
  Checked on every clip in the test run.
- **SC-009**: After 20 administrator corrections on questions the test set
  does not contain, the test-set score is no lower than before, and each
  corrected question is now routed correctly. Removing every learned example
  gives back exactly the starting score.

## Out of scope

- Writing answers with a model. P12-FR-003 still holds: every sentence comes
  from the console's own wording.
- New queries or calculations. The one exception is the live-view entry in
  P15-FR-020, which reads no data.
- Learning that changes a model's weights. Learning only adds examples.
- Searching footage for things ("find the red bag in yesterday's video").
  Clips are fetched for a known camera and moment only.
- Conversation memory, voice input, reading answers aloud.
- Training or fine-tuning any model, and any model running on a camera frame
  for Ask.
- Changing how tracking, breaches or weapons record their own clips.

## Constitution check *(mandatory)*

- **III, truthful data.** Nothing changes in where answers come from. The new
  risk is a confident wrong route, so P15-FR-008 adds "did you mean" and
  SC-002 measures confident wrong answers instead of assuming there are none.
  A switched-off feature says so (P15-FR-021) rather than reading as empty.
- **III, no dead controls.** "Watch clip" appears only where a clip can exist,
  and every failure has a real reason (P15-FR-013, P15-FR-018).
- **IV, privacy.** This is the biggest gain. The accepted risk in spec 010,
  unrecognised words sent off-site as typed, is gone because nothing leaves.
  Clips of named children are footage, so they get the same server-side
  permissions and an audit entry before playback.
- **IV, audit.** Each clip fetch, "did you mean" choice and learned-example
  change is audited, and the entry is written before the result or the
  change, as track searches already are (AGENTS rule 11).
- **IV, security.** Learning is the only write Ask has. Only an administrator
  can make it take effect (P15-FR-022, P15-FR-023), and the check is
  server-side by path. Learned examples are stored masked, so they hold no
  personal data (P15-FR-012).
- **III, measured, not assumed.** Learning cannot quietly lower accuracy:
  P15-FR-024 refuses an example that breaks a test question, and P15-FR-026
  keeps a way back to the measured starting point.
- **I and II, latency and isolation.** Ask shares the Jetson with about 40
  cameras. It does no work between questions (P15-FR-010), and SC-006 checks
  that it does not slow the cameras while it answers. If the model fails to
  load, only Ask is affected, and the UI says so.
- **Settled rules.** The owner supplies the model. It is never downloaded,
  trained or sourced by us. The `.engine` file is built on the Jetson.

## Assumptions

- **The meaning model is multilingual-e5-small** (MIT licence, about 118 million
  parameters, Arabic supported, checked on Hugging Face). Mohamed supplies
  `onnx/model.onnx` (about 470 MB) and `onnx/tokenizer.json` (about 17 MB) into
  `models/ask/`. On the Jetson it runs as a half-precision engine built on the
  board. The 500 MB in SC-005 is a starting budget, to be challenged once
  measured.
- **The fourteen menu entries from spec 010 stay as they are, plus live view
  (P15-FR-020).** Each has about 15 example questions, written first and then
  corrected by Mohamed.
- **Operators' "did you mean" choices wait for approval** before they teach
  Ask (P15-FR-023), because one mis-click by a guard should not change the
  answers for everybody. Challenge this if approving them is too much work.
- **The model files are downloaded by Mohamed on his own machine.** This
  session's network cannot reach Hugging Face, and the 470 MB file cannot go
  through git. `models/ask/` is ignored by git for that reason.
- **The archive's `dvr` backend is the recorder** for clips. On a development
  machine the `footage` backend stands in, so clips are testable without a
  recorder.
- **±10 s** is the default clip span, adjustable in configuration.
- **A clip is a plain recording**, with no outlines drawn on it. Tracking's
  outlined chunks stay as they are.
- **Who may watch a clip:** anyone allowed to see the row and that camera live.
  No new role.
- **The test set is new and separate** from spec 010's 37 questions. Those 37
  stay in it.
- **Ask stays marked "not ready"** in System Health until SC-001 is met.
