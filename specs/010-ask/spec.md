# Feature Specification: Ask — natural-language query console

**Feature Branch**: `010-ask`
**Created**: 30 Aug 2026
**Status**: Draft
**Input**: User description: "Ask — Natural-Language Query Console. The operator types a question in plain language; Ask maps it to ONE existing tested query and answers only from its real result. The language model is a translator, never the source of a fact."

## Why this feature

VisionGuard already answers the questions a school asks — who arrived, how many
are in the yard, who went where, which car came through gate 1. But the operator
has to know that "was Sara late?" lives on Attendance in person mode, and "where
did she go after that?" lives on Track a Person. A guard at the gate does not
carry that map in his head, so the answer exists and nobody reaches it.

Ask is a box you type a question into. It does not answer the question — it
works out **which existing query the question is**, runs that query, and shows
you its real result with the evidence attached. The language model reads the
question and nothing else. It never sees a face, a frame, or a record, and it
never writes the answer.

## User Scenarios & Testing

### Primary story

A guard types "سارة جت امتى النهاردة؟" into the Ask box. The name is replaced
locally with a placeholder before anything leaves the building; the masked
question goes out and comes back as a machine-readable instruction — *attendance,
person, today*. The engine puts the real name back, runs the same attendance
query the Attendance page runs, and shows the same answer that page would show:
the arrival time, the camera that recognised her, the confidence, and a line
underneath saying **"understood as: attendance · Sara Ahmed · today"** so he can
see what was asked on his behalf. A link takes him to the Attendance page with
that exact query already filled in.

**Acceptance scenarios**

1. **Given** an attendance record exists for a person today, **When** the
   operator asks about her arrival in Arabic, English, Franco-Arabic, or a mix,
   **Then** Ask shows the same arrival time, camera and confidence the
   Attendance page shows for that person and day — no other number, and no
   sentence the system cannot support.
2. **Given** any supported question, **When** the answer appears, **Then** it
   carries the "understood as" line naming the query and its parameters, and a
   link that opens the matching feature page with the same parameters applied.
3. **Given** a question about something the system does not do — the weather,
   next week, a person's mood, why somebody was late — **When** it is asked,
   **Then** Ask says plainly that it cannot answer it and lists what it can
   answer about. It does not guess, and it does not answer a nearby question
   instead.
4. **Given** a question that names a person the system does not know, **When**
   it is asked, **Then** Ask says that name is not in the directory rather than
   returning an empty result that reads like an absence.
5. **Given** a question that matches a query but is missing something it needs —
   "how many people?" with no place — **When** it is asked, **Then** Ask asks
   one short question for the missing piece, in the operator's own language, and
   the wording comes from the console, not from the model.
6. **Given** the subsystem behind the matched query is not running, **When** the
   question is asked, **Then** Ask shows that subsystem's real unavailable state
   with its real reason — the same one the feature page would show — and never
   an answer.
7. **Given** the cloud is unreachable or refuses, **When** a question is asked,
   **Then** Ask says it is temporarily unavailable and says why in plain words.
   Every other part of VisionGuard — detection, recording, the knife gate, the
   register — is unaffected and untouched.
8. **Given** any question at all, **When** it is submitted, **Then** an audit
   entry is written before the answer is returned, holding the question, the
   query it resolved to, its parameters, and the account that asked.

### Edge cases

- **A name that is not masked must not leave the site.** The masking has to cope
  with alef and hamza variants (احمد / أحمد), taa marbuta versus haa (سارة /
  ساره), Arabic-Indic versus Western digits (٢٠٢٦ / 2026), and Latin
  transliterations (Sara / Sarah / سارة). A miss is a privacy breach, not a
  routing failure.
- **A plate is personal data too.** "فين عربية ص ب د ٢٣٤" must go out with the
  plate replaced, in both digit systems, matching the way the register already
  collapses them onto one row.
- **Two people share a first name.** Ask must not pick one. It asks which.
- **Lost items has no history to search.** Bag search runs only on cameras
  somebody is looking at and records nothing, so "where is the red bag?" has no
  stored answer. Ask must say so and offer to open the Lost items page with the
  colour and cameras filled in — never report a result it does not have.
- **Counting is real for one area only.** A headcount question about a demo area
  must carry the same "demo" label the Counting page carries.
- **The model returns something that is not on the menu**, returns prose, or
  returns malformed output. Ask treats all three as "unsupported" and says so.
  It never runs a query it did not recognise.
- **The model routes confidently to the wrong query.** The "understood as" line
  is the operator's only defence, so it must always be visible and must never be
  abbreviated away.
- **Empty result versus unavailable subsystem versus unknown person** must stay
  three distinguishable answers, as they are everywhere else in the console.

## Requirements

Numbered `P12-FR-001`. **P12 is a new phase** — "Ask" is not in `docs/PLAN.md`
today and must be added there when this is planned. It sits after P11, because
Ask answers in Arabic and the console must own its sentences first.

### The answer is never invented

- **P12-FR-001**: Every fact Ask shows MUST come from the result of exactly one
  existing query that the console already exposes and that already has tests.
  Ask MUST NOT introduce a new data source, a new table, or a new calculation.
- **P12-FR-002**: The language model's only output MUST be a choice from a fixed
  menu of supported queries plus that query's parameters, or the verdict
  "unsupported". Any other output — prose, a query not on the menu, malformed
  output — MUST be treated as "unsupported".
- **P12-FR-003**: No sentence shown to the operator may be written by the model.
  Every word of an answer, refusal, clarifier or error MUST come from the
  console's own wording (P11), filled with real values.
- **P12-FR-004**: Every answer MUST show the provenance the underlying query
  already carries — camera, time, confidence, review state — and MUST carry the
  same honesty labels that query carries, including "demo" and "estimated".
- **P12-FR-005**: Every answer MUST show an "understood as" line naming the
  resolved query and its parameters in plain language, and a link that opens the
  matching feature page with the same parameters applied.
- **P12-FR-006**: Where the matched query already has footage or a photograph —
  a breach clip, a knife video, a gate snapshot — Ask MUST show it. Where the
  query has none, Ask MUST NOT imply that footage exists.

### Nothing personal leaves the site

- **P12-FR-007**: Before any text leaves the site, every personal identifier the
  system knows MUST be replaced with a placeholder locally: the names of
  enrolled people, plate text, and the names of vehicle owners in the register.
  A word the site does not recognise — a visitor, a misspelling, somebody who
  was never enrolled — is sent as typed. Ask MUST say so plainly where the
  operator asking can see it, and MUST NOT claim that nothing personal ever
  leaves.
- **P12-FR-008**: Masking MUST be Arabic-normalised. It MUST match across alef
  and hamza forms, taa marbuta and haa, Arabic-Indic and Western digits, and
  common Latin transliterations of the same name.
- **P12-FR-009**: No face, frame, clip, snapshot, embedding, or recorded event
  may leave the site under any circumstance.
- **P12-FR-010**: Placeholders MUST be resolved back to real values locally,
  after the model has answered, and only against records the asking account is
  allowed to see.
- **P12-FR-011**: If a name in the question cannot be resolved to somebody the
  system knows, Ask MUST say so. It MUST NOT return an empty result, which would
  read as "that person was not here".
- **P12-FR-012**: What Ask sends off-site MUST be inspectable — an administrator
  MUST be able to see exactly the text that left, for any question ever asked.
  Because unrecognised words go out as typed (P12-FR-007), this record is the
  only way to know what actually left, so it MUST be complete and MUST be
  written whether the question succeeded or failed.

### Honest states

- **P12-FR-013**: A question outside the supported menu MUST produce a plain
  refusal that names what Ask *can* answer about. It MUST NOT be answered with a
  neighbouring query.
- **P12-FR-014**: A question missing a required parameter MUST produce exactly
  one clarifying question, worded by the console, naming the missing piece. Ask
  MUST NOT invent the missing value.
- **P12-FR-015**: When the subsystem behind the matched query is unavailable,
  Ask MUST surface that subsystem's real unavailable state and reason, and MUST
  NOT return a figure.
- **P12-FR-016**: When the cloud parser is unreachable, refuses, or times out,
  Ask MUST say it is temporarily unavailable, with the reason, and MUST NOT fall
  back to guessing. Every other feature MUST continue to run unaffected.
- **P12-FR-017**: Ask MUST NOT be required by any other feature, and MUST NOT be
  required to be on for any other feature to work.

### Read-only, permissioned, audited

- **P12-FR-018**: Ask MUST be read-only. It MUST NOT write, change, delete,
  review, confirm, export, or acknowledge anything in any feature.
- **P12-FR-019**: A resolved query MUST run with the asking account's own
  permissions, decided server-side. Ask MUST NOT let anybody reach data their
  role would refuse them on the feature page.
- **P12-FR-020**: An audit entry MUST be written **before** the answer is
  returned, holding the question as typed, the text that was sent off-site, the
  resolved query and parameters, the outcome, and the account.
- **P12-FR-021**: The question as typed MUST be stored locally only, and MUST
  fall under the same retention and erasure policy as the records it names.

### The seam

- **P12-FR-022**: Choosing the query MUST sit behind a single boundary — a
  question goes in, a supported query with parameters or "unsupported" comes
  out. Replacing the cloud model with a local one, or with a rule-based matcher,
  MUST require no change anywhere else in Ask.
- **P12-FR-023**: The menu of supported queries MUST be derived from what the
  system genuinely exposes, so a query that is removed or added is reflected in
  what Ask claims it can answer, and no menu entry can point at a query that
  does not exist.

### Languages

- **P12-FR-024**: Ask MUST accept Modern Standard Arabic, Egyptian dialect,
  Franco-Arabic, English, and a mixture of them in one question.
- **P12-FR-025**: The answer MUST be in the language of the asking account, and
  the language of the question MUST NOT change it.

## Success Criteria

- **SC-001**: For every supported question in the test set, the figure Ask shows
  is identical to the figure the matching feature page shows for the same
  parameters. No answer contains a number, name, time or place that the query
  result does not contain.
- **SC-002**: Across an Arabic, Franco-Arabic, English and mixed test set, no
  face, frame, clip, embedding or record leaves the site, and no name or plate
  the system knows leaves it either — in any spelling, either digit system, or
  a transliteration. Verified by inspecting the exact text sent for every
  question in the set. Words the site does not recognise are the known,
  deliberate exception, and the same inspection shows exactly which ones left.
- **SC-003**: On the same test set, at least 95% of supported questions route to
  the correct query with the correct parameters, and every one that does not is
  visibly wrong on the "understood as" line rather than silently wrong.
- **SC-004**: Each of the four honest states — out of scope, ambiguous,
  subsystem offline, cloud unreachable — produces its own distinct message, with
  a reason, and never a figure. Verified case by case.
- **SC-005**: Every question asked appears in the audit trail with its resolved
  query, and no feature record is created, changed or deleted by any question.
- **SC-006**: With the cloud unreachable for a full session, detection,
  recording, the knife review gate and the vehicle register behave exactly as
  they do with it reachable.
- **SC-007**: An operator gets an answer, a clarifier, or a refusal within a few
  seconds of pressing enter, and can always see which query ran.

## Out of scope

- Any change to detection, tracking, recognition or feature logic. Ask adds no
  data and no model that looks at a picture.
- Any new query. Ask reaches only what the console already exposes today.
- Writing anything: no confirming a knife alert, no acknowledging, no exporting,
  no enrolling by voice or text.
- Searching recorded footage for lost items. There is no recorded footage and no
  bag history to search; Ask can only open the page.
- Answering from the model's own knowledge — about the school, about people,
  about anything. If the answer is not in a query result, there is no answer.
- Voice input, speech, or reading answers aloud.
- Conversation memory across questions. Each question stands alone.
- The mobile app.

## Constitution check

- **III — Truthful data.** This is the whole feature. P12-FR-001 to
  P12-FR-006 exist so that no shown value can originate anywhere but a real
  query result, and so that provenance and honesty labels — demo, estimated,
  unverified — survive the trip through Ask instead of being polished off. The
  "understood as" line is the anti-fabrication device: the operator can always
  see what was actually asked on their behalf.
- **III — no fixtures.** Ask must never answer from a fixture. When the store
  behind a query is the demo store, the answer carries the demo label the page
  carries.
- **IV — Privacy.** P12-FR-007 to P12-FR-012 are the site boundary. Biometrics
  and footage never leave, ever. Every name and plate the system knows leaves
  only as a placeholder, and what left is inspectable afterwards.
  **One residual risk is accepted deliberately**: a word the site does not
  recognise as an identifier is sent as typed, so an operator who types the name
  of a visitor, or of a child who was never enrolled, sends that name off-site.
  Minimisation for minors therefore rests on the masking dictionary being
  complete for everybody enrolled, on P12-FR-007's plain warning, and on
  P12-FR-012's record of what left. This is a decision to revisit before go-live
  if the provider contract or the school's consent position changes.
- **IV — Reliability.** P12-FR-016 and P12-FR-017: the cloud is an optional
  translator on a non-safety path. Losing it degrades Ask visibly and nothing
  else at all. Ask must never sit between a detection and its human gate.
- **IV — Security.** P12-FR-019 keeps permissions where they already are:
  server-side, by path. Ask must not become a second place where access is
  decided, or a way to read past a role.
- **IV — Audit.** P12-FR-020 follows the existing rule — the entry is written
  before the result returns, as track searches already do.
- **Never claim precision the code lacks.** A headcount answered from an area
  that over-counts, or a plate read that has never been measured on this site,
  must reach the operator with that caveat intact.
- **A feature must never require another feature.** P12-FR-017. Ask depends on
  the console owning its sentences (P11) to be *translatable*, but no feature
  depends on Ask.
- **Face and clothing stay distinct.** Ask inherits this by not touching it: it
  shows what the query returns, and a "same body" answer must not be reported as
  a named person.

## Assumptions

- **P11 ships first.** Ask answers in the operator's language, and P12-FR-003
  forbids the model from writing sentences, so the console must already own
  every sentence. Ask is planned after the Arabic console.
- **The supported menu is today's read queries**, and no more: attendance for a
  person or a group on a day; headcount for a place; restricted-zone breaches in
  a window; knife detections in a window; vehicle passes filtered by plate,
  gate, direction, status or day, plus what is inside now and gate totals;
  where a named person went on a day; one person's history; and what the system
  itself is doing (health and capabilities). Lost items is a deep-link only,
  because it stores nothing.
- **Ask is available to any signed-in account**, and answers only what that
  account's role already permits.
- **A question with no time in it means today, or now for live figures**, and
  the "understood as" line states which was assumed, so a wrong assumption is
  visible rather than silent.
- **One question, one query.** A question that needs two queries to answer —
  "who was late *and* which car did they arrive in" — is treated as ambiguous
  and gets a clarifier, not two answers stitched together.
- **The masking dictionary is built from the site's own records** — enrolled
  people, the vehicle register — and is rebuilt when they change, so a person
  enrolled this morning is masked this afternoon.
- **The test sets are ours to write.** Mohamed supplies or corrects the Arabic
  and Franco-Arabic questions; the expected query for each is fixed before the
  parser is built, so SC-003 is measured, not asserted.
- **The engine may reach the internet** from the school's network, and Ask uses
  a cloud model. The provider is chosen when this is planned, and a written
  no-training / data-privacy guarantee is a condition of choosing it, not a
  detail to settle afterwards. No provider means no Ask, not a quiet fallback.
- **An unrecognised word is sent as typed** (decided 30 Aug 2026). Masking
  covers everybody enrolled and every plate in the register; a visitor, a
  misspelling or an unenrolled child typed into the box leaves the site as text.
  This buys routing accuracy — over-masking every proper noun would leave the
  model guessing at a sentence full of placeholders — and it is paid for with a
  real, stated privacy limit. It is written down in P12-FR-007, warned about on
  screen, and recorded in P12-FR-012.
- **Ask answers straight away**, with the "understood as" line beside the
  answer, rather than asking the operator to approve the query first. A guard
  asking twenty questions a shift will not confirm each one, and a confirmation
  he stops reading is worse than no confirmation. The cost is real and accepted:
  a confidently wrong route produces a true answer to a question nobody asked,
  and the only thing standing between that and a bad decision is the line and
  the link beside it. That is why P12-FR-005 makes the line mandatory and the
  edge cases forbid abbreviating it away, and why SC-003 measures wrong routes
  rather than assuming there are none.
