---
description: "Tasks for 017 — the VisionGuard website, built from the approved design"
---

# Tasks: The VisionGuard website, built from the approved design

**Input**: `specs/017-public-website/`: spec.md, plan.md, research.md, data-model.md,
contracts/contact-form.md, quickstart.md, context.md

**Tests**: no automated tests. The spec asks for none, and no engine code changes.
The proof is the check script and the by-eye walk in quickstart §2–§5, run in the
in-app browser. `python -m pytest engine` must stay at **1889 passed, 6 skipped**.

**Source**: `design/Visionguard website design/VisionGuard Website v2.dc.html` ("the
design"). Open it by the line ranges in context.md §1, never whole. Every part is
**copied, not redrawn**: markup and inline styles stay byte-for-byte. The only
changes are the ones research R2 lists.

**Settled with Mohamed (27 Sep 2026)**:
- Commit after each part, on `Fo2sh`.
- Commit the design folder too.
- One real test send is approved: send once, Mohamed clicks "Activate", then send
  once more to confirm.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different file, no dependency on an unfinished task)
- **[Story]**: US1 the page and its motion · US2 the contact form sends · US3 every
  screen and browser

---

## Phase 1: Setup

- [X] T001 Create `website/` and `website/assets/`, and byte-copy
  `design/Visionguard website design/assets/visionguard.ico` and `mobile-2.png` into
  `website/assets/` (`cp`, not a text rewrite)
- [X] T002 [P] Append the `website` entry from context.md §1 to `.claude/launch.json`
  (local and git-excluded; keep the two existing entries as they are)

---

## Phase 2: Foundational

**Purpose**: the stylesheet and page shell that every section sits in.

- [X] T003 Create `website/styles.css`: copy design lines 15–83 verbatim (base rules,
  39 `@keyframes`, the `[data-*]` hooks, the `@supports (animation-timeline: view())`
  block, the reduced-motion rule). Then append `section[id]{scroll-margin-top:72px}`,
  and `html{scroll-behavior:auto}` inside a
  `@media (prefers-reduced-motion:reduce)` block (research R8)
- [X] T004 Create the `website/index.html` shell:
  - `<!DOCTYPE html>`, `<html lang="en">`, charset, viewport,
    `<title>VisionGuard AI</title>`;
  - a one-line meta description, taken from the footer's sentence (design line 451);
  - the Google Fonts link and the icon from design lines 11–13;
  - `<link rel="stylesheet" href="styles.css">`, and
    `<script src="main.js" defer></script>`;
  - the body holds the design's wrapper div (line 88), with `overflow-x:hidden`
    changed to `overflow-x:clip`. No `support.js`, no `<x-dc>`, no `<helmet>`.

**Checkpoint**: served at http://localhost:8090, the page is blank, with the right
title and icon, and there are no console errors.

---

## Phase 3: User Story 1 — the whole page, moving as designed (P1) 🎯 MVP

**Goal**: every section of the design, in order, with every animation in spec
P14-FR-005, in Chrome and Edge at desktop width. The footer is honest (P14-FR-016,
017).

**Independent test**: open it at 1440 px beside the design. Run quickstart §2; every
check prints `true`. Walk quickstart §3 by eye.

Porting rules for T005–T010 (research R2):
- Expand each `<sc-for>` from `renderVals()` (design lines 513–556) into literal
  items.
- Replace `{{ … }}` with the values.
- Turn each `style-hover="…"` into class `hN`: the same value gets the same class, 13
  classes in all, and T011 writes them.
- Turn each `style-focus="…"` into class `f1`.
- Keep every other inline style exactly.

- [X] T005 [US1] Port NAV and HERO (design lines 90–167) into `website/index.html`:
  - Write out the four camera tiles from `cams` (lines 524–528, colours on line 514).
    "Library east" alone keeps `animation:vg-nextcam 2s ease-in-out infinite`; the
    others get `animation:none`.
  - `ref="{{ typedRef }}"` → `id="typed"`; `ref="{{ langRef }}"` → `id="lang"`.
  - Drop `onMouseMove` (T012 adds the listener).
- [X] T006 [US1] Port STATS, SITES and HOW IT WORKS (design lines 169–213) into
  `website/index.html`:
  - `sitesLoop` = the 8 names twice, 16 items.
  - The 4 `steps`, each with its `delay`.
  - Keep `[data-count]` elements empty. The number comes from CSS (context §3).
- [X] T007 [US1] Port TOOLS and HONEST BY DESIGN (design lines 215–290) into
  `website/index.html`: the 4 `chips` with `dir="auto"`, the 6 `tools` with their
  tag colours, and the 3 `sources`
- [X] T008 [US1] Port ON YOUR PHONE and TRUST (design lines 292–380) into
  `website/index.html`: the phone markup exactly as it is; the image
  `./assets/mobile-2.png`; the 4 `trust` cards with their delays
- [X] T009 [US1] Port CONTACT (design lines 382–439) into `website/index.html`:
  - Email card: `mailto:sales@vision-guard.org`, showing "sales@vision-guard.org".
  - Call us: `tel:+201002535081`, showing "+20 100 253 5081".
  - WhatsApp: `https://wa.me/201002535081` with `target="_blank"
    rel="noopener"`.
  - Give the inputs `name` attributes: `name`, `email`, `company`, `phone`,
    `site_type`, `message`.
  - Give the four camera buttons `data-cams` and `aria-pressed`, with 25–100 on.
  - Give the form `id="contact-form"`.
  - Keep the thank-you block from lines 431–435 in the page with `hidden` and
    `id="contact-sent"`.
  - In the note, "privacy policy" becomes plain text followed by "(coming soon)".
- [X] T010 [US1] Port the FOOTER (design lines 441–471) into `website/index.html`
  (research R7):
  - Delete the "All systems operational" pill (line 452).
  - Turn these 15 links into
    `<span class="soon" aria-disabled="true">Label <small>Soon</small></span>`:
    Offices, Factories, Warehouses, Hospitals, Retail & malls, About us, Careers,
    Partners, Security, Privacy policy, Terms of service, Help centre, LinkedIn, X,
    YouTube.
  - In the language switch, "العربية" becomes the same kind of `.soon` span.
  - Section links and the logo stay as links.
  - Afterwards, confirm `grep -c 'href="#"' website/index.html` prints 0.
- [X] T011 [P] [US1] Append to `website/styles.css`:
  - the 13 `.hN:hover{…}` rules and `.f1:focus{…}`, every declaration
    `!important` (context §3: inline beats class);
  - `.soon`: the footer's colour at about 55% opacity, `cursor:default`, and the
    `small` as a tiny pill in `#2e3933`, not a link colour.
- [X] T012 [US1] Create `website/main.js` in one IIFE, with no globals:
  - Port `startTyping()` (design lines 493–506) against `#typed`, `#lang` and the 7
    `qs` (line 479). Keep the RTL test, and the 55 / 1800 / 22 ms timings.
  - Port `heroMove` (line 518) as a `mousemove` listener on `#top`.
  - Camera picker: clicking a `[data-cams]` button sets it on (bg and border
    `#33705b`, text `#fff`) and the others off (bg `#fff`, text `#1f2b26`, border
    `#d5ddd6`), and updates `aria-pressed`.
- [X] T013 [US1] Verify, then commit 1:
  - Start the `website` preview. At 1440 px, run quickstart §2 (all `true`),
    scroll to the bottom and confirm the header is still at the top, and walk
    quickstart §3 against the design side by side.
  - Take one screenshot of the hero and one of the phone section.
  - Commit on `Fo2sh`, staging only `website/`, `design/Visionguard website design/`
    and `specs/017-public-website/`: "The website is the approved design, moving as
    designed". Do not stage `dev.ps1` (unresolved merge), `research/` or
    `specs/016-*`; they belong to other work.

**Checkpoint**: the MVP. A visitor on Chrome or Edge sees the whole designed page,
moving. The form only validates for now.

---

## Phase 4: User Story 2 — the contact form really sends (P1)

**Goal**: "Send message" delivers to sales@vision-guard.org, and the thank-you is
never shown unless it did (P14-FR-009 to 014; contracts/contact-form.md;
data-model.md).

**Independent test**: quickstart §4. With the request forced to fail, the page says
"not sent" and keeps the text. With delivery working, the thank-you shows and the
message arrives.

- [X] T014 [US2] In `website/index.html`, inside `#contact-form`:
  - Add a honeypot: `<input type="text" name="_honey" tabindex="-1"
    autocomplete="off" aria-hidden="true">`, placed off-screen with inline
    `position:absolute;left:-9999px`.
  - Under the button, add
    `<div id="contact-failed" hidden role="alert">`, styled like the note (line 427)
    in `#a5372c`: "Your message was not sent. Please email
    <a href="mailto:sales@vision-guard.org">sales@vision-guard.org</a> or call
    <a href="tel:+201002535081">+20 100 253 5081</a>."
  - Give the button's label span `id="send-label"`.
- [X] T015 [US2] In `website/main.js`, the form's `submit` handler (the browser's own
  `required` / `type=email` checks run first):
  - If `_honey` is filled, show `#contact-failed` and stop.
  - Otherwise: disable the button and set the label to "Sending…". Then
    `fetch('https://formsubmit.co/ajax/sales@vision-guard.org', {method:'POST'})`
    with JSON headers and the body from the contract. `cameras` comes from the `on`
    picker button, and `_subject` is `Website enquiry: <company>`. Use an
    AbortController that aborts after 15 s.
  - If `data.success === "true" || data.success === true`: hide the form and show
    `#contact-sent`.
  - In every other case (non-2xx, non-JSON, rejected or aborted): show
    `#contact-failed`, re-enable the button, restore "Send message", keep the
    fields, and `console.warn` FormSubmit's `message`.
- [X] T016 [US2] Verify the failure paths in the in-app browser (quickstart §4). To
  make the request fail, override `window.fetch` with `javascript_tool` in three
  ways:
  1. a rejecting fetch → "not sent";
  2. a fetch resolving to `{"success":"false"}` → "not sent";
  3. a fetch that never resolves → "not sent" after 15 s.

  Also check: empty Company → no request; the button is disabled during a send.
  Then reload to restore the real fetch.
- [ ] T017 [US2] Real send, approved by Mohamed on 27 Sep 2026 for exactly this
  sequence:
  1. Fill Full name "VisionGuard website test", Work email sales@vision-guard.org,
     Company "VisionGuard", and the message "Test from the new website — please
     ignore". Send.
  2. The page is expected to say "not sent", because FormSubmit is waiting for
     activation. Ask Mohamed to click "Activate Form" in Gmail, and wait for him.
  3. Send once more. The thank-you should appear. Ask Mohamed to confirm that the
     email arrived with every field and that Reply is addressed to the Work email.

  No further real sends. If step 3 still says "not sent", stop and report it.
- [X] T018 [US2] Commit 2 (`website/` only): "The contact form sends to
  sales@vision-guard.org, and says so when it cannot"

**Checkpoint**: the site is shippable on Chrome, Edge and Safari at desktop width.

---

## Phase 5: User Story 3 — every screen and every browser (P2)

**Goal**: 360 px phones without sideways scroll (P14-FR-003); Firefox gets the scroll
animations (research R4); reduced motion shows everything still (P14-FR-006, 007).

**Independent test**:
- quickstart §2 passes at 390 and 360 px;
- with the fallback forced on, sections slide in and numbers count up;
- with animations disabled, every section is fully visible.

- [X] T019 [P] [US3] Append the fallback to `website/styles.css`, all under `.vg-io`
  (research R4):
  - `[data-reveal]:not(.vg-in){opacity:0}`;
  - `.vg-in` plays `vg-rv .8s cubic-bezier(.2,.8,.2,1) both`, or `vg-zoom` for
    `[data-reveal="zoom"]`, **and** sets `opacity:1` itself;
  - `[data-stagger]>*:nth-child(4n+2|4n+3|4n).vg-in` get delays of
    .1s / .2s / .3s;
  - `[data-count].vg-in` plays `vg-count 1.6s ease-out both`;
  - `[data-line]` gets `transform-origin:left`; before `.vg-in` it is
    `transform:scaleX(0)`, and `.vg-in` plays `vg-line .8s both`;
  - `[data-tilt].vg-in` plays `vg-tilt 1.2s both`;
  - `[data-progress]` and `[data-nav]` are left to the script.
- [X] T020 [US3] Add the fallback to `website/main.js` (research R4, context §3):
  - It runs only when `!CSS.supports('animation-timeline: view()')`, or when the URL
    has `?motion=fallback` (for testing in Chrome), and never when
    `matchMedia('(prefers-reduced-motion: reduce)').matches`.
  - Add `vg-io` to `<html>`.
  - One IntersectionObserver (threshold 0.15) adds `vg-in` once to
    `[data-reveal],[data-count],[data-line],[data-tilt]` and then unobserves.
  - One passive `scroll` listener, throttled with `requestAnimationFrame`, sets:
    - `[data-progress]` → `transform:scaleX(scrollY/(scrollHeight-innerHeight))`;
    - `[data-nav]` → the `vg-nav` end look (background `rgba(242,245,242,.94)`,
      shadow `0 10px 30px rgba(30,42,36,.08)`), blended over the first 240 px;
    - `[data-par="a"|"b"]` → `translate` from 90 px to −50 px (a) and 160 px to
      −90 px (b) as the element crosses the viewport. It leaves `transform` alone,
      so the float keeps playing.
  - Run the scroll handler once on load.
- [X] T021 [US3] Verify the fallback in the in-app browser at
  `http://localhost:8090/?motion=fallback`:
  - sections fade up as they are reached; 208 / 3 / 7 count up; the tile top lines
    draw;
  - the progress bar fills, and the header turns solid;
  - the phones drift while floating.

  If Firefox is installed on this machine, open the page there as well. If not, add
  "open it in Firefox" to the handover list (T027).
- [X] T022 [US3] Narrow screens:
  - `resize_window` to 390×844, then 360×800; run quickstart §2 at each, and scroll
    the whole page.
  - Fix only what is cut off or overflowing, in one
    `@media (max-width:520px){…}` block at the end of `website/styles.css` (context
    §5 and research R8 list the suspects). For example, scale the phone stage
    (`#mobile [data-reveal="1"]` with height 560) down and centre it, pull the hero
    note in from `left:-28px`, and let the footer's first column `span 1`.
  - Reset with the `desktop` preset afterwards.
- [X] T023 [US3] Reduced motion (the in-app browser cannot emulate it):
  - inject `<style>*{animation:none!important;transition:none!important}</style>`
    with `javascript_tool`;
  - confirm every `[data-reveal]` has computed opacity 1, and that the three count
    elements show 208, 3 and 7 (read their `::after` content);
  - confirm nothing is left hidden.

  Then ask Mohamed for one by-eye check with Windows "Animation effects" off
  (quickstart §5).
- [X] T024 [US3] Commit 3 (`website/` only): "The website fits a 360-pixel phone, and
  Firefox gets the scroll animations too"

**Checkpoint**: every requirement in the spec is met, apart from the checks that only
Mohamed can do by eye.

---

## Phase 6: Polish and handover

- [ ] T025 Final gates:
  - quickstart §2 at 1440, 390 and 360 px, all `true`;
  - no console errors on load or during a full scroll;
  - `python -m pytest engine` → 1889 passed, 6 skipped;
  - `git status --short` shows no new change outside `website/` and
    `specs/017-public-website/`.
- [ ] T026 [P] Add a "Website" row to `STATUS.md`. **The file is CRLF**: use the
  Edit tool and check `git diff --stat STATUS.md` shows a small change. The row
  covers:
  - "Real — static one-page site in `website/`, the approved v2 design";
  - the form sends through FormSubmit to sales@vision-guard.org, and its activation
    state as T017 left it;
  - footer items marked Soon;
  - the three claims awaiting Mohamed's confirmation (spec, Constitution check);
  - not yet published to vision-guard.org.
- [ ] T027 Commit 4 (`STATUS.md` hunk only, plus any `website/` fix from T025):
  "STATUS says what the website is and what it is not yet". Then hand over to
  Mohamed with the list only he can check:
  - the page beside the design, by eye;
  - an iPhone in Safari;
  - Firefox, if T021 could not;
  - reduced motion (T023);
  - the Gmail copy from T017;
  - the three claims on the page ("208 cameras on a single site", "Amber — waiting
    for human review", "Arabic & English, full right-to-left");
  - where to upload `website/` to publish it.

---

## Dependencies and execution order

- **Setup (T001–T002)** → **Foundational (T003–T004)** → **US1 (T005–T013)** →
  **US2 (T014–T018)** → **US3 (T019–T024)** → **Polish (T025–T027)**.
- US2 needs US1's contact markup (T009). US3 needs the whole page (US1) to measure.
  The stories share `index.html`, `styles.css` and `main.js`, so they run one after
  another, not side by side.
- Within US1, T005–T010 all edit `index.html`, in page order. T011
  (`styles.css`) can run beside them. T012 (`main.js`) can start once T005 has put
  `#typed`, `#lang` and `#top` in place.

## Parallel opportunities

```text
T002 (launch.json)      alongside  T001 (copy assets)
T011 (hover/Soon CSS)   alongside  T005–T010 (markup)
T019 (fallback CSS)     alongside  T020 (fallback script)
T026 (STATUS.md)        alongside  T025 (final gates)
```

## Implementation strategy

1. **MVP = US1**: the designed page, moving, in Chrome and Edge. After T013 Mohamed
   can already look at it.
2. **US2** makes the one thing that must really work (the form) work, and prove it
   with one real message.
3. **US3** widens it to phones, Firefox and reduced motion.
4. Commit after each story, as Mohamed chose: four commits on `Fo2sh`.

## Notes

- Never redraw a part of the design. If something looks wrong, compare against the
  design's line range before changing a style.
- New files are LF. The only CRLF file touched is `STATUS.md` (T026).
- No real form sends beyond the two in T017.
