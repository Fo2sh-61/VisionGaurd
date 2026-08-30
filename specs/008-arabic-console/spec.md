# Feature Specification: Arabic console

**Feature Branch**: `008-arabic-console`
**Created**: 28 Aug 2026
**Status**: Draft
**Input**: User description: "we should make the arabic for this app which was left. I think now is the time and it will help the agent."

## Why this feature

The school is Arabic-speaking and the people who use this tool every day — the
guards at the gate, the staff checking the register — read Arabic. Every word in
the console today is English, including the sentences that explain why a figure
is incomplete or a feature is off. A guard who cannot read *"No exit camera is
configured, so no car can be matched to its exit"* is looking at a number that
is wrong in a way the screen has told him about and he cannot see. That is the
never-show-anything-untrue rule failing through language, and it is the reason
this is worth doing before anything else is added on top.

It is also the foundation for the planned Ask bar. Once the console owns every
sentence in both languages, the Ask bar can answer an Arabic question in Arabic
without a language model ever writing a sentence — which is the only version of
that feature that can be trusted.

## User Scenarios & Testing

### Primary story

A guard signs in and the console is in Arabic: the words, the direction of the
page, the dates, the numbers, and above all the messages that say why something
cannot be shown. He picks the language once, on his own account, and it follows
him to any browser at the gate. Nothing he can reach is in English, and nothing
is blank because a translation was forgotten.

**Acceptance scenarios**

1. **Given** a guard whose account is set to Arabic, **When** he signs in,
   **Then** every page reads right to left in Arabic — headings, buttons, table
   columns, status badges, navigation and form labels included.
2. **Given** the vehicle gate has no exit camera configured, **When** an Arabic
   user opens it, **Then** the explanation appears in Arabic and says the same
   thing the English one says, including the consequence — that cars leaving are
   not being counted.
3. **Given** a page is loading, has failed, is empty, or is showing degraded
   data, **When** an Arabic user reaches it, **Then** those four states are in
   Arabic too, with the same reason the English user gets.
4. **Given** an Arabic user, **When** any time, date, duration, count or
   percentage is shown, **Then** it follows Arabic conventions, and the site's
   timezone rule is unchanged — the instant shown is the same instant.
5. **Given** a signed-in user, **When** they change language in Settings,
   **Then** the console changes without signing out, and the choice is
   remembered on their next sign-in from any browser.
6. **Given** a string that has no Arabic wording yet, **When** an Arabic user
   reaches it, **Then** the English is shown as-is — never a blank, never an
   internal name — and an administrator can see the list of what is still
   missing.
7. **Given** an Arabic user watching a camera, **When** the page is right to
   left, **Then** the camera picture and the boxes drawn on it are **not**
   mirrored, and a box still sits over the thing it describes.

### Edge cases

- **Names are data, not interface.** A person enrolled as "Layla Ahmed", a
  camera named "cam-laptop", an area called "Main entrance" and a group called
  "Grade 8" are shown exactly as they were entered, in either language. Nothing
  the operator typed is ever translated.
- **Plate text already has two digit systems.** The register collapses Arabic
  and Western digits onto one row. A plate must render the way the register
  renders it and must not be transliterated a second time by the language layer.
- **Mixed direction in one sentence.** An Arabic sentence containing a Latin
  camera name, a plate, or a number must not scramble the order of either part.
- **A subsystem is down.** The reason must reach the screen in Arabic. This is
  only possible if the engine stops writing the sentence itself.
- **Nobody is signed in yet.** The sign-in page must be readable in Arabic
  before any account exists to hold a language preference.
- **Empty versus zero versus unknown** must stay three distinguishable things in
  Arabic, exactly as they are in English.

## Requirements

Numbered `P11-FR-001`. **P11 is a new phase** — "Arabic console" is not in
`docs/PLAN.md` today and must be added there when this is planned.

### The language layer

- **P11-FR-001**: Every user-visible string in the console MUST come from one
  place that holds an English and an Arabic wording for each entry. No sentence
  may be assembled by joining translated fragments, because the two languages do
  not order their fragments the same way.
- **P11-FR-002**: A string with no Arabic wording MUST fall back to its English
  wording. It MUST NOT render blank and MUST NOT render an internal identifier.
- **P11-FR-003**: An administrator MUST be able to see which strings have no
  Arabic wording yet, so the gap is a known quantity rather than a surprise on a
  screen.
- **P11-FR-004**: Every Arabic wording MUST be read and approved by a native
  Arabic speaker before it ships. Wordings that have not been approved MUST be
  identifiable as such.

### The engine must stop writing sentences

- **P11-FR-005**: The engine MUST NOT send human-readable sentences that are
  destined for a screen. Every explanation it currently sends as English prose —
  why there is no clip, why a capability is off, why a figure cannot be paired,
  why a recording refused, why a sweep was declined — MUST become a code plus
  the facts it needs, and the console MUST build the sentence.
- **P11-FR-006**: Each such code MUST carry the same meaning as the English
  sentence it replaces, including the consequence. A translation that states the
  cause and drops the consequence is a new bug, not a shorter sentence.
- **P11-FR-007**: An unrecognised code arriving from the engine MUST be shown as
  a plain "something is unavailable" message naming the code, never swallowed
  and never rendered as an empty space.

### Direction and layout

- **P11-FR-008**: In Arabic the whole console MUST read right to left —
  navigation, page layout, tables, forms, lists and buttons.
- **P11-FR-009**: The camera picture and every overlay box, point and label
  drawn on it MUST NOT be mirrored in either language. A mirrored picture is a
  false picture.
- **P11-FR-010**: No page may overflow, overlap or clip its own text in Arabic
  at the widths the console already supports.

### Numbers, dates and times

- **P11-FR-011**: Dates, times, durations, counts and percentages MUST follow
  the chosen language's conventions.
- **P11-FR-012**: The instant shown MUST NOT change with language. The existing
  rule that timezone is resolved per timestamp stands untouched.
- **P11-FR-013**: The digit system used for numbers MUST be a site setting, so
  the console can be made to match the paperwork the school already uses.

### Choosing the language

- **P11-FR-014**: Language MUST be a property of the user's account, held by the
  engine, so a shared guard station shows each person their own language.
- **P11-FR-015**: Users MUST be able to change their own language, and the
  change MUST take effect without signing out.
- **P11-FR-016**: The sign-in page MUST offer both languages before anybody is
  signed in.
- **P11-FR-017**: No feature may require Arabic to be on, and none may require
  it to be off.

### Audit and exports

- **P11-FR-018**: Audit entries MUST be recorded in a form that does not depend
  on the language of whoever caused them, and MUST be readable in the language
  of whoever reads them later.
- **P11-FR-019**: An exported file MUST carry the language of the person who
  asked for it, and the export MUST still be audited before the file is built.

## Success Criteria

- **SC-001**: A guard who reads no English can complete a full shift — watch the
  cameras, read the gate, confirm or reject a knife alert, check who is present —
  without meeting an English word.
- **SC-002**: Every explanation the engine can produce about why something is
  unavailable appears in Arabic, with the same meaning as the English, and none
  of them is left as English prose inside the engine.
- **SC-003**: Changing language takes effect immediately and is still in force
  at the next sign-in from a different browser.
- **SC-004**: No page in Arabic has text that runs off the edge, overlaps
  another element, or is cut off, at desktop and phone widths.
- **SC-005**: Every string in the console has an Arabic wording, and every one of
  them has been read by a native speaker before release.
- **SC-006**: The camera picture and its boxes look identical in both languages,
  and a box still sits over the thing it describes.
- **SC-007**: An administrator can see, at any time, how many strings are still
  without an approved Arabic wording.

## Out of scope

- Any language other than English and Arabic.
- Translating anything an operator typed or a camera produced — people's names,
  camera names, area names, group names, plate text, notes.
- The Ask bar agent. It is the next specification and depends on this one.
- Voice, speech, or reading anything aloud.
- The mobile app, which is still entirely fixtures.
- Rewording the existing English. This feature adds a second language; it does
  not re-edit the first.

## Constitution check

- **Never show anything untrue.** A missing translation must show the English,
  not a blank — a blank claims there is nothing to say. This is why P11-FR-002
  exists.
- **Honest degradation.** The whole point of P11-FR-005 and P11-FR-006 is that
  the degradation messages survive translation intact. A shorter Arabic sentence
  that drops the consequence would silently undo P0-08.
- **The camera image is evidence.** P11-FR-009 keeps it unmirrored. Right-to-left
  applies to the interface, never to the picture.
- **A feature must never require another feature.** P11-FR-017. The console must
  work in English with the language layer half-finished, and in Arabic with any
  subsystem down.
- **Server-side permissions.** Language is a preference, not a permission. It
  must not become a second place where roles are decided.
- **Audit.** P11-FR-018 keeps audit meaningful across languages; storing an
  English sentence would make the trail unreadable to an Arabic reader and
  untranslatable afterwards.
- **Latency budget.** This is a front-end concern with no per-frame cost. The
  engine's change is to stop building strings, which makes it do less work, not
  more.

## Assumptions

- Arabic means Modern Standard Arabic as used in Egyptian school administration,
  not a spoken dialect.
- The web console is the target. The mobile app is fixtures and is excluded.
- Language belongs to the account rather than the browser, because the gate
  station is shared.
- Arabic-Indic digits are the sensible default for a school in Egypt, matching
  the plate register, with the site able to choose otherwise (P11-FR-013).
- Exported files follow the exporter's language. An English-reading administrator
  who wants English columns exports them himself.
- I draft all the Arabic wording and Mohamed corrects it before release. Nothing
  unreviewed reaches a live screen (P11-FR-004).
- Scale, measured on 28 Aug 2026: about 400 user-visible strings across 43 files
  in the console, and 65 English sentences written inside the engine that reach
  a screen — 37 in production paths and 28 more in the demo store, which shares
  the same wire types and so must move with them. These are the two piles of
  work.
