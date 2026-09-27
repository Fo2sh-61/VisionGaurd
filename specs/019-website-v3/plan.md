# Implementation Plan: The website in its new design, on PC and phone, in English and Arabic

**Branch**: `019-website-v3` (commits land on `Fo2sh`) | **Date**: 27 September 2026 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/019-website-v3/spec.md`

## Summary

A small converter, `tools/build_website.mjs`, turns Mohamed's four design files into the
site. Each home page carries two copies, the PC design and the phone design. Each copy
has its own stylesheet, loaded only at its own width, so each screen matches its drawing
exactly. The converter applies a fixed list of 16 site edits: real contact details,
working links, "Soon" marks, the form's sending machinery, and the language links. It
stops if any edit no longer fits the design. Arabic lives under `/ar/`. The three inner
pages keep their bodies (translated for Arabic) and get the design's header and footer
stamped in. `main.js` gains the phone's menu, slide-up bar, Tools dots and fold-out
footer, keyed by the design's own handler names. Next design update: run the converter,
then check.

## FR → mechanism

| FR | Smallest mechanism |
|---|---|
| 018 exact design | converter writes the design out as it is; only data-model §3 differs (R2, R3) |
| 019 footer links | edits E5 (three pages) and E6 (everything else becomes "Soon") |
| 020 Arabic pages | `website/ar/`, same file names, `lang="ar" dir="rtl"` (R4) |
| 021 switch → twin | edit E7; the twin's name is fixed by rule |
| 022 texts in the page's language | the "Soon", "not sent" and "Send another" blocks per language (converter); "Sending…" and validation from a four-line table in `main.js` via `setCustomValidity` (R8) |
| 023 Arabic inner pages say the same | translated sentence by sentence; Mohamed reads them before publishing |
| 024 phone below 600 px, no sideways scroll | two copies + `media` stylesheets (R1, R7); a tablet fix block only where measured |
| 025 phone menu | `toggleMenu` / `closeMenu` hooks (contracts/page-hooks.md) |
| 026 inner pages' new look | stamped header and footer, `.pg-*` switched to Rubik (R5) |
| 027 real contact details | edits E1–E4 plus the output guard |
| 028 forms deliver as today | spec 017's send path unchanged; `wire()` runs for every form found |

## Technical Context

**Language/Version**: HTML, CSS and plain JavaScript for the site. The converter is a
Node script (Node 22 on this machine; any Node from 18 up will do).

**Primary Dependencies**: none installed. At run time: Google Fonts (Rubik, Instrument
Serif, JetBrains Mono) and FormSubmit, both as today.

**Storage**: none. No cookies, and no remembered language.

**Testing**: the converter's own stop-checks; the check script and by-eye walk in
quickstart §3–§6 (eight pages, nine widths); `python -m pytest engine` only to show that
nothing else moved.

**Target Platform**: current Chrome, Edge, Safari (Mac and iPhone) and Firefox; GitHub
Pages as today.

**Project Type**: static website, separate from the product.

**Performance Goals**: first screen under 2 s (SC-005). The hidden copy is
`display:none`, so it costs download only (about 25 KB compressed), never animation.

**Constraints**: no build on the host (the folder uploads as it is); served over http(s)
for FormSubmit; no sideways scroll from 360 px up; reduced motion stops everything.

**Scale/Scope**: 4 design files (about 2,300 lines) → 2 generated home pages, 6 inner
pages, 2 generated stylesheets, `styles.css`, `main.js`. The converter is about 250
lines. The `main.js` additions are about 120 lines.

## Constitution Check

*GATE: checked before Phase 0 and again after Phase 1.*

| Principle | How this plan keeps it |
|---|---|
| II. Isolation | The site and converter share no file, call or process with the engine, console or phone app. |
| III. Nothing untrue: wiring | Thank-you only on a confirmed send. Every link either works or is a "Soon" span. The converter refuses output with a design placeholder, a dead `href="#"` or an unknown handler (converter.md). No "All systems operational" pill. |
| III. Nothing untrue: words | **Violation, justified below.** The design's words bring back 19 sentences found untrue or overclaiming (017 `claims.md`). |
| IV. Privacy | Unchanged. Form fields go through FormSubmit to sales@ or support@ only. No analytics. |
| V. Complete UX | The phone menu, fold-out footer, Tools dots and slide-up bar all work. The forms have sending, sent and not-sent states in both languages. |
| Scale claims need measurements | Same violation: "208 cameras on a single site" is back. |

Re-checked after Phase 1: nothing new. The converter's guard is a strengthening of III for
wiring.

## Project Structure

### Documentation (this feature)

```text
specs/019-website-v3/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R11
├── data-model.md        # pages, the two copies, site edits E1–E16, added texts
├── contracts/
│   ├── converter.md     # what the converter reads, writes and refuses
│   └── page-hooks.md    # the handler vocabulary between pages and main.js
├── quickstart.md        # build, check script, phone walk, forms, publish
├── context.md           # implementation handoff
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
tools/
└── build_website.mjs        # new: the converter
website/
├── index.html               # generated (was hand-ported v2)
├── about.html               # header/footer markers added; head switches fonts
├── security.html            # same
├── help.html                # same
├── design-pc.css            # new, generated
├── design-phone.css         # new, generated
├── styles.css               # old phone block and .h1–.h13 removed; data-if, copy
│                            #   switch, tablet fixes, .pg-* on Rubik, Soon for both languages
├── main.js                  # hooks by design name, twin ids, per-language texts,
│                            #   every form and every copy
├── assets/                  # refreshed from the design folder
└── ar/
    ├── index.html           # generated
    ├── about.html           # new, translated
    ├── security.html        # new, translated
    └── help.html            # new, translated, with the question form
STATUS.md                    # Website row: words are the design's, not checked (CRLF)
specs/017-public-website/claims.md   # closing section: reverted at Mohamed's choice
```

**Structure Decision**: `website/` stays the site. The converter sits with the other
repo tools in `tools/`. No shared code with `web/` or `mobile/`.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| III (and the scale-claims rule): the design's words include 19 sentences checked as untrue or overclaiming on 27 Sep 2026 | Mohamed chose "the design's words exactly" when asked, with this consequence stated in the question | Keeping the corrected words was offered and recommended; he declined. The plan limits the damage: Security, About and Help keep their checked words, and STATUS.md and claims.md are updated so that no record claims the page was checked (R10). |

What was left out, and why:

- **Scoping or renaming CSS so both designs share one stylesheet**: loading each
  design's CSS only at its own width does the same job with no rewriting (R1).
- **A general HTML parser or template package**: the design files use five fixed
  template forms (R2).
- **Remembering the visitor's language**: not asked for, and it would need storage and a
  redirect (R4).
- **A third, tablet layout**: out of scope; tablets get the PC design with measured
  fixes only (R7).
- **Generating the inner pages' bodies**: there is no design for them (R5).
