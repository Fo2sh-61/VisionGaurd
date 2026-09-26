# Implementation Plan: The VisionGuard website, built from the approved design

**Branch**: `017-public-website` (commits land on `Fo2sh`) | **Date**: 27 September 2026 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/017-public-website/spec.md`

## Summary

The design already contains the page's words, layout and nearly all of its motion,
written as plain CSS. It only needs its design-tool wrapper removed. That wrapper
(`support.js`) downloads React and a 3 MB compiler every time the page opens, so it
does not ship. The site is three plain files and two pictures in a new `website/`
folder. There is no build step, so the folder can be uploaded as it is.

The script adds five small things the design's CSS cannot do: the typing question
box, the glow that follows the mouse, the camera-count picker, sending the form, and
scroll animations for Firefox. The form sends straight to sales@vision-guard.org
through FormSubmit. It needs no account; the first message asks for one click on an
"Activate" email. Each requirement's smallest mechanism is in
[research.md](research.md).

## Technical Context

**Language/Version**: HTML, CSS, and plain JavaScript (no framework, no build)

**Primary Dependencies**: none installed. At run time: Google Fonts (Albert Sans, Noto Sans Arabic, JetBrains Mono, as the design links them) and FormSubmit's send address for the form

**Storage**: none. The website stores nothing and sets no cookies of its own

**Testing**: by eye and by a short check script run in the in-app browser (quickstart §2), at 1440, 390 and 360 px. `python -m pytest engine` is run only to prove nothing else moved (no engine code changes)

**Target Platform**: current Chrome, Edge, Safari (Mac and iPhone) and Firefox; any static web host

**Project Type**: static one-page website, separate from the product

**Performance Goals**: first screen in under 2 s (SC-002); smooth scrolling (SC-003). Animations only use movement, fading and colour, as the design does

**Constraints**: must work when served over http(s), not opened as a local file. FormSubmit refuses pages opened as files (research R5). No sideways scroll at 360 px. Reduced-motion stops everything

**Scale/Scope**: one page, 11 sections, about 470 lines of markup, about 70 lines of design CSS, about 150 lines of script

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1.*

| Principle | How this plan keeps it |
|---|---|
| II. Isolation | The website shares no file, call or process with the engine, console or phone app. It cannot break them. |
| III. Nothing untrue | The thank-you shows only when FormSubmit answers `"success":"true"` (R5). The "All systems operational" pill is removed (R7). Footer items without a page are marked "Soon" and are not links (R7). The drawn product scenes stay illustrations. |
| IV. Privacy | The form's details pass through FormSubmit on the way to sales@vision-guard.org. That is the only third party, and it is stated here because the spec said "only to the sales inbox". No analytics, no cookies of our own. |
| V. Complete UX | Every control either works or is marked "Soon". The form has sending, sent and failed states. |

No violations, and Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/017-public-website/
├── spec.md
├── plan.md              # this file
├── research.md          # decisions R1–R8
├── data-model.md        # the contact message and its send states
├── contracts/
│   └── contact-form.md  # what the page sends to FormSubmit and what it expects back
├── quickstart.md        # how to open it, the check script, the by-eye walk
├── context.md           # implementation handoff
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
website/                      # new; nothing else in the repo changes
├── index.html                # the v2 markup: loops written out, hover/focus as classes
├── styles.css                # the design's keyframes + hover/focus rules + Firefox fallback + "Soon"
├── main.js                   # typing, mouse glow, camera picker, form send, scroll fallback
└── assets/
    ├── visionguard.ico       # copied from design/Visionguard website design/assets/
    └── mobile-2.png          # copied from the same folder
.claude/launch.json           # local and git-excluded: add a "website" preview entry
```

**Structure Decision**: one new top-level folder, `website/`, beside `web/` and
`mobile/`, as Mohamed chose. No shared code with either app.

## Complexity Tracking

Empty. What was left out, and why:

- **React, Vite, or a build step**: one fixed page gains nothing from them, and the
  folder would no longer be uploadable as it is.
- **The design runtime `support.js`**: it downloads React and Babel from unpkg on every
  visit.
- **A mail server of our own**: FormSubmit does the same job with no account and no
  server.
- **Rewriting the inline styles into a stylesheet**: the design's inline styles are
  the approved design. Only `style-hover`/`style-focus` and the loops change form.
