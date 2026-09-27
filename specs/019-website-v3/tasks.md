---
description: "Tasks for spec 019: the website in its new design, on PC and phone, in English and Arabic"
---

# Tasks: The website in its new design, on PC and phone, in English and Arabic

**Input**: `specs/019-website-v3/`: plan.md, spec.md, research.md (R1–R11),
data-model.md (edits E1–E16), contracts/converter.md, contracts/page-hooks.md,
quickstart.md, context.md.

**Read `context.md` first.** It has the anchors, the traps and the baseline.

**Tests**: no test files. The spec asks for none, and the website has no test runner. The
checks are:
- the converter's own stop-checks (contracts/converter.md);
- a repeat build that changes nothing;
- quickstart §3–§7, run in the in-app browser.

**User stories**, taken from the spec's acceptance scenarios:

| Story | What it delivers | Spec scenarios |
|---|---|---|
| US1 (P1) 🎯 MVP | The English home page on PC is Website v3, with working links and the form | 1, 5, part of 7 |
| US2 (P2) | Phones get the Mobile design: menu, slide-up bar, Tools dots, fold-out footer | 3, 4 |
| US3 (P3) | The Arabic home page, PC and phone, with a working language switch | 2, part of 7 |
| US4 (P4) | About us, Security and Help centre: new look, plus Arabic versions | 6, part of 7 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on unfinished work)
- **[Story]**: US1–US4

---

## Phase 1: Setup

- [X] T001 Check the tree before touching anything. Run `git status --short` and `git diff --stat`. Leave `dev.ps1` (UU), `research/` and `specs/016-pilot-site-readiness/` alone; they belong to other sessions. Confirm `design/Visionguard website full design/` holds the four `.dc.html` files and `assets/`. If `website/` has changes you did not make, queue behind them (context.md §3).
- [X] T002 Create `tools/build_website.mjs` with:
  - the fixed input and output paths (contracts/converter.md);
  - a `fail(file, edit, found)` that prints one clear line and exits non-zero **before any file is written** (collect all output in memory, write at the end);
  - the English form snippets copied **now**, before `website/index.html` is overwritten: the `_honey` input (index.html:462), the `id="contact-failed"` "not sent" block (480) and the `data-again` "Send another" button (487). Turn them into constants for E13/E14, with the ids swapped for `data-failed` / `data-again`.

---

## Phase 2: Foundational (blocks every story)

**⚠️ No story can start until this phase is done.**

- [X] T003 In `tools/build_website.mjs`, write the design reader. For each `.dc.html`:
  - Take the `<style>` text from inside `<helmet>`, and unescape `&lt; &gt; &amp;` (the Mobile designs escape `@property --n` and `--a`; context.md §3).
  - Take the markup: the single outer `<div …>` after `</helmet>`, up to `<script>`.
  - Take `class Component extends DCLogic { … }`, and evaluate it with `new Function('DCLogic','React', src + ';return Component')`. Pass a stub `DCLogic` (with `state` and a no-op `setState`) and `React = {createRef: () => ({current: null})}`.
  - Call `renderVals()` once and keep the values, plus `qs`.
- [X] T004 In `tools/build_website.mjs`, write the template expander. It must:
  - be nesting-aware for `<sc-for list="{{ p }}" as="x">` and `<sc-if value="{{ p }}">`;
  - interpolate `{{ dotted.path }}` with HTML escaping, in both text and attributes;
  - turn `sc-if` into `<div data-if="p" style="display:contents">`, with `hidden` when the starting value is falsy;
  - drop every `hint-placeholder-*` attribute;
  - `fail()` on a non-path expression or a path with no value;
  - add `data-i="n"` to elements inside loops that carry a handler.
- [X] T005 In `tools/build_website.mjs`, write the hook rewriter:
  - `onEvent="{{ name }}"` becomes `data-on="event:name"` (lower-case event) and `ref="{{ name }}"` becomes `data-ref="name"`.
  - It uses the known-name lists from `contracts/page-hooks.md`: handlers `heroMove toggleMenu closeMenu m.go onToolsScroll d.go c.toggle o.pick submit`; refs `typedRef langRef toolsRef`; conditions `menuOpen showCta c.open notSent sent`. Any other name calls `fail()`.
  - The `typedRef` element also gets `data-qs='[…]'` (the design's `qs`, JSON, attribute-escaped).
- [X] T006 In `tools/build_website.mjs`, turn `style-hover="…"` and `style-focus="…"` into deterministic classes, numbered in order of first appearance and separate per screen (`vh1…`, `vf1…`). Merge them into any existing `class`. Emit CSS rules with every declaration marked `!important`. Print the class counts.
- [X] T007 In `tools/build_website.mjs`, write the site-edit engine:
  - An ordered table of `{id, screens, langs, find, replace, rule}`, where `rule` is `1`, `>=1`, `per-form` or `all`. A count outside the rule calls `fail()` naming E-number, file and count.
  - The form check: each `data-on="submit:submit"` form has exactly 6 fields (`input:not([type=hidden]),select,textarea`), named in order `name email company phone site_type message` (E12).
  - The output guard (data-model §3): no `visionguard.ai`, `0000 0000`, `.dc.html`, `href="#"`, `{{`, `<sc-`, `style-hover`, `style-focus`, and no ` on[A-Z]…=` attribute. Otherwise `fail()`.
- [X] T008 In `tools/build_website.mjs`, write the writers:
  - **Page shell**, based on today's `website/index.html` `<head>`:
    - the design's font link, the icon, title and description;
    - `<html lang dir>`;
    - `design-pc.css` with `media="(width >= 600px)"`, then `design-phone.css` with `media="(width < 600px)"`, then `styles.css`;
    - `main.js` with `defer`;
    - a first comment: "Generated by tools/build_website.mjs. Do not edit."
  - **CSS writer**: per screen, the English design's style, plus the rules only the Arabic design adds, plus the hover and focus classes.
  - **Asset copy**: `mobile-2.png` and `visionguard.ico`, as bytes.
  - **Writing**: write a file only when its content changed, all at the end. Print one line per file written.
- [X] T009 [P] Clean up `website/styles.css` (context.md §1 row).
  - **Delete**: lines 1–69 (v2 design CSS), `.h1`–`.h13` and `.f1`, the narrow-screen block, and everything from "PHONE ONLY" to the end.
  - **Keep**: the `[hidden]` fix, the reduced-motion `scroll-behavior`, the tool-card glow/line fix, the `.vg-io` fallback and `.pg-*`.
  - **Add**: `[data-if]{display:contents}` and `[data-if][hidden]{display:none!important}`; the copy switch (`.vg-pc` hidden below 600 px, `.vg-ph` hidden from 600 px, both `!important`); an empty marked block `@media (width >= 600px) and (width < 1080px)` for tablet fixes.
  - **Change**: `section[id]` scroll margin becomes `.vg-pc section[id]`; `.soon` uses Rubik and `margin-inline-start`; `.pg-*` uses Rubik.
- [X] T010 [P] Rework the base of `website/main.js` (context.md §1 row):
  - a text table keyed by `<html lang>`, holding "Sending…", "fill in this field" and "enter an email" in English and Arabic (data-model §5);
  - a helper `on(name)` returning every `[data-on$=":name"]`;
  - typing runs over every `[data-ref="typedRef"]`, reading `data-qs`, with its sibling `[data-ref="langRef"]` (one ticker for all copies; the first question shown still under reduced motion);
  - the glow is bound on `on('heroMove')`;
  - delete the `.vg-how-track` block;
  - the fallback uses `querySelectorAll` for `[data-progress]` and `[data-nav]`;
  - `send()` is unchanged.

**Checkpoint**: the converter runs end to end on `Website v3` with an empty edit table, and stops on the guard. That proves the guard works.

---

## Phase 3: User Story 1 — The English home page on PC is Website v3 (P1) 🎯 MVP

**Goal**: from 600 px up, `/` is Website v3: every section, word, colour, font and animation. It has real contact details, working footer links, "Soon" on the rest, and a form that sends as today.

**Independent test**: `node tools/build_website.mjs`, then serve `website/` and open `/`:
- quickstart §3 at 1440, 1024, 900, 768 and 600 px (every PC check `true`);
- §5 against `Website v3` at 1440;
- §6 on the PC form (validation, failure, double press; **no real send**);
- §7 (reduced motion, `?motion=fallback`).

- [X] T011 [US1] In `tools/build_website.mjs`, fill the edit table for `Website v3` (English, PC): E1, E2, E3, E4 (WhatsApp card → `https://wa.me/201002535081`, `target="_blank" rel="noopener"`), E5 (About us / Security / Help centre → `about.html` / `security.html` / `help.html`), E6 (every other `href="#"` → a Soon span), E7 (`VisionGuard%20Website%20v3%20AR.dc.html` → `ar/`), E8 (`overflow-x:hidden` → `clip` on the outer wrapper, which also gets `class="vg-pc"`), and E12–E15 on its form. Look up each exact `find` string in the design file first.
- [X] T012 [US1] Generate `website/index.html` (PC copy only for now) and `website/design-pc.css` by running `node tools/build_website.mjs`. Run it again and confirm `git status --short website` shows no new change. Confirm the file contains no `support.js`.
- [X] T013 [US1] Wire the forms in `website/main.js`:
  - `wire(form, sentEl, to, fields, fresh)` runs for every `on('submit')` form. `sentEl` is the `[data-if="sent"]` in the same `<section>`. Inside the form it uses `[data-failed]` and `[data-label]`.
  - The `_honey` check stays. `setCustomValidity` uses the text table: set it on `invalid`, clear it on `input`. "Send another" uses `[data-again]`.
  - Camera options come from `on('o.pick')`, per form, with the design's on/off colours and `aria-pressed`. The value sent is the button's text.
  - Also, in `website/help.html`, add `data-failed` to its not-sent block and `data-label` to its button's text span, so the Help form keeps working through the same `wire` (with `#help-sent`).
- [X] T014 [US1] Measure the PC copy at 600, 768, 900 and 1024 px (quickstart §3; context.md §5): the header row, the 920 px hero rings, the Honest card at `left:309px`. For each overlap or sideways push found, add the smallest fix to the tablet block in `website/styles.css`, scoped `.vg-pc` and marked `!important`, with a comment naming the width it was seen at. Add nothing that was not measured.
- [X] T015 [US1] Verify US1 with quickstart §3 (PC widths), §5 (PC, by eye), §6 (PC form: validation, failure via blocked `formsubmit.co`, double press) and §7. Every check `true`. Record anything the design does that the site does not.

**Checkpoint**: the English PC home page is done and can be demoed. Phones still see the PC design until US2.

---

## Phase 4: User Story 2 — Phones get the Mobile design (P2)

**Goal**: below 600 px, `/` shows the Mobile design, stretched to the full width, with its menu, slide-up "Contact us" bar, Tools dots and fold-out footer working.

**Independent test**: quickstart §3 at 599, 430, 390 and 360 px; §4 (English); §5 against `Mobile` at 390; §6 on the phone form.

- [X] T016 [US2] In `tools/build_website.mjs`, add `Mobile` (English, phone):
  - edits E1–E3, E6, E7 (→ `ar/`), E8, E9 (drop `max-width:430px`, `margin:0 auto` and the side `box-shadow` on the wrapper, which gets `class="vg-ph"`), E10 (the CTA bar's `max-width:430px`), E11 (`id="x"` → `id="m-x"`, `href="#x"` → `href="#m-x"`, applied after expansion) and E12–E15;
  - the footer-fold links for About us / Security / Help centre get E5;
  - write the phone copy after the PC copy in `website/index.html`, and write `website/design-phone.css`.
- [X] T017 [US2] In `website/main.js`, build the menu:
  - `on('toggleMenu')` flips the `[data-if="menuOpen"]` wrapper. The button's three child bars get the design's transforms (contracts/page-hooks.md), and `aria-expanded` is set.
  - `on('closeMenu')` and `on('m.go')` shut it.
  - The menu also shuts when `matchMedia('(width < 600px)')` stops matching.
- [X] T018 [US2] In `website/main.js`, show the `[data-if="showCta"]` bar only when all three hold: `scrollY > 560`; the shown Contact section's top is still at or below `0.9 × innerHeight`; the menu is shut. Use a passive scroll listener, queued with `requestAnimationFrame`. The bar still shows and hides under reduced motion; its slide is stopped by the global reduced-motion rule.
- [X] T019 [US2] In `website/main.js`, build the Tools dots:
  - `on('onToolsScroll')` sets the active index to `round(abs(scrollLeft) / (firstCard.offsetWidth + 12))`, then restyles the `on('d.go')` dots (active `24px #33705b`, idle `8px #c3cfc6`).
  - A dot's click calls `cards[i].scrollIntoView({behavior:'smooth', inline:'start', block:'nearest'})`, with `behavior:'auto'` under reduced motion.
- [X] T020 [US2] In `website/main.js`, build the footer folds: `on('c.toggle')` with `data-i` opens `[data-if="c.open"][data-i="i"]` and shuts the others. The button's last child turns `rotate(45deg)`, and back to `none` when shut. Set `aria-expanded`.
- [X] T021 [US2] In `website/main.js`, add twin ids. On load and on `hashchange`: if `#x` has no box (`!el.getClientRects().length`), scroll to `#m-x` instead (or from `#m-x` to `#x`), respecting reduced motion.
- [X] T022 [US2] Verify US2 with:
  - quickstart §3 at 599, 430, 390 and 360;
  - §4 in English: menu, bar, dots, folds, the width-growth close, and a cross-page link from `/about.html`, which will work fully after US4;
  - §5 against `Mobile` at 390;
  - §6 on the phone form.

  Also confirm that at 600 px exactly the PC copy shows, and at 599 the phone copy does.

**Checkpoint**: the English home page is done on both screens.

---

## Phase 5: User Story 3 — The Arabic home page (P3)

**Goal**: `/ar/` is `Website v3 AR` on PC and `Mobile AR` on phones, reading right to left. The switch goes both ways, and every message is in Arabic.

**Independent test**: quickstart §3 on `/ar/` at all nine widths; §4 in Arabic (the RTL Tools row especially); §5 against both AR designs; §6 in Arabic; the switch from `/` to `/ar/` and back, on both screens.

- [X] T023 [US3] In `tools/build_website.mjs`, add `Website v3 AR` and `Mobile AR`:
  - **Edits**:
    - E1–E4; E5 with `من نحن` / `الأمان` / `مركز المساعدة`; E6 with `قريبًا`; E7 → `../`; E8–E11;
    - E12 and E13, with the Arabic not-sent text from data-model §5 and the number wrapped in `<span dir="ltr">`;
    - E14 (`أرسل رسالة أخرى`), E15 and E16 (`./assets/` → `../assets/`).
  - For E3, find each Arabic design's exact number string first (context.md §3).
  - **CSS**: add the rules only the AR styles have (`[dir="rtl"] …`, `vg-travel-rtl`, `vg-dash-rtl`) into `design-pc.css` and `design-phone.css`.
  - **Output**: generate `website/ar/index.html` with `<html lang="ar" dir="rtl">`, `../` paths, and an Arabic `<title>` and description.
- [X] T024 [US3] Verify US3 with quickstart §3 on `/ar/`, §4 in Arabic, §5 against `Website v3 AR` (1440) and `Mobile AR` (390), and §6 in Arabic (the validation bubble and "not sent" in Arabic on an English browser). Also check that the typing box turns right-to-left for Arabic questions, and that phone digits keep their order.

**Checkpoint**: both home pages are done, in both languages, on both screens.

---

## Phase 6: User Story 4 — About us, Security, Help centre: new look and Arabic (P4)

**Goal**: all six inner pages have the design's header (with the phone menu on phones) and footer, Rubik fonts, and a switch to their twin. The English words are unchanged; the Arabic ones say the same facts.

**Independent test**: quickstart §3 on the six pages at all nine widths; the switch goes to the twin page; from each page at 390 px, the menu's Contact lands on the phone Contact section; the Help form's failure path works in both languages.

- [X] T025 [US4] In `tools/build_website.mjs`, add header and footer stamping:
  - For each of the six inner pages, replace the text between `<!-- vg:header -->` and `<!-- /vg:header -->` with the PC and phone headers (the phone one includes its menu), and the same for `vg:footer`. Take them from the same-language designs after all edits.
  - Section links become `./#x` / `./#m-x`, and the logo becomes `./`.
  - The language link points at the twin (`ar/about.html` ↔ `../about.html`).
  - Wrap them in `.vg-pc` / `.vg-ph`.
  - `fail()` if a marker is missing.
- [X] T026 [P] [US4] In `website/about.html`, `website/security.html` and `website/help.html`:
  - replace the header and footer with the two marker pairs;
  - switch the `<head>` font link to the design's (Rubik, Instrument Serif, JetBrains Mono);
  - link `design-pc.css` and `design-phone.css` (with their `media`) before `styles.css`.

  Leave every word of the bodies untouched.
- [X] T027 [P] [US4] Create `website/ar/about.html`:
  - Start from `website/about.html` (after T026).
  - Set `lang="ar" dir="rtl"`, `../` for CSS, JS and assets, and an Arabic `<title>` and description.
  - Translate the body sentence by sentence into plain Modern Standard Arabic. Keep every fact; add none (P14-FR-023).
- [X] T028 [P] [US4] Create `website/ar/security.html` the same way. Keep every stated limit exactly, for example "the audit is lost on restart" and "Ask sends masked questions to Google".
- [X] T029 [P] [US4] Create `website/ar/help.html` the same way. Its question form keeps the same field names, and the topic options are translated. Its not-sent block (`data-failed`, support@vision-guard.org, number in `<span dir="ltr">`), its "Send another" (`data-again`) and its `data-label` span are in Arabic. It still sends to support@vision-guard.org.
- [X] T030 [US4] Run `node tools/build_website.mjs` to stamp all six pages, and run it again to confirm there is no second change. Then verify US4:
  - quickstart §3 on all six pages, at all nine widths;
  - the switch on each page opens its twin;
  - the §4 cross-page link from `/about.html` and `/ar/about.html` at 390 px;
  - the Help form's §6 failure path in both languages;
  - the sticky header on each page.
- [X] T031 [US4] Write `specs/019-website-v3/arabic-review.md` for Mohamed. It lists every Arabic sentence the site adds that is not from his design: the three inner pages side by side with their English source, plus the texts in data-model §5. He reads this before anything is published.

**Checkpoint**: all eight pages are done.

---

## Phase 7: Polish and cross-cutting

- [X] T032 [P] Update the `| Website |` row in `STATUS.md`. It must say:
  - the home page now uses the design's words (spec 019, Mohamed's choice, 27 Sep 2026), and the 19 sentences in `claims.md` are on the site again;
  - there are Arabic pages under `/ar/`;
  - each home page carries a PC copy and a phone copy;
  - `tools/build_website.mjs` builds it.

  Remove "every product claim on the page was checked". **STATUS.md is CRLF**: edit as bytes and check `git diff --stat` shows a small change.
- [X] T033 [P] In `specs/017-public-website/claims.md`, append a closing section: "Reverted to the design's words, 27 Sep 2026 (spec 019, Mohamed's choice)". List which rows of the Changed table are back on the home page, and note that Security, About and Help keep their checked words.
- [X] T034 Run the whole of `specs/019-website-v3/quickstart.md` once more end to end (§1 twice, then §3 on all eight pages at all nine widths, §7). Confirm `git diff --stat` shows LF files unchanged in line endings.
- [X] T035 Run the repo checks from AGENTS.md: `python -m pytest engine` (must be **1889 passed, 6 skipped**, as in context.md §4), `python -m pyflakes engine/vg engine/tools engine/tests`, and `cd web; npx tsc -b --force`. None should move, since no engine or console file changed. Report any failure as it is.
- [X] T036 Commit on `Fo2sh`, staging only:
  - `website/`
  - `tools/build_website.mjs`
  - `STATUS.md`
  - `specs/017-public-website/claims.md`
  - `specs/019-website-v3/`
  - from the design folder, only the four `.dc.html` files and `assets/`, together with the deletion of the old `design/Visionguard website design/` (Mohamed's rename)

  **Ask Mohamed before staging `uploads/`, `ref/`, `support.js` or `.thumbnail`.** Leave `dev.ps1`, `research/` and `specs/016-…` unstaged. Write a plain-sentence message with the Co-Authored-By line.
- [ ] T037 Hand over to Mohamed, then stop. Ask him to:
  - read `arabic-review.md`;
  - look at the site by eye on a real phone (English and Arabic);
  - give the OK for one real send from `/ar/` (quickstart §6).

  Publish (quickstart §9) only after his explicit go-ahead.

---

## Dependencies and execution order

- **Setup (T001–T002)** comes first. T002 must copy the form snippets before anything overwrites `website/index.html`.
- **Foundational (T003–T010)** blocks every story. T003→T008 are in one file, so they run in order. T009 (`styles.css`) and T010 (`main.js`) can run alongside them.
- **US1 (T011–T015)** starts after Foundational. It is the MVP.
- **US2 (T016–T022)** needs US1's generated page; the phone copy is appended after the PC copy.
- **US3 (T023–T024)** needs US1 and US2 (it adds the Arabic twins of both copies).
- **US4 (T025–T031)** needs US3, because stamping the Arabic pages uses the Arabic designs' header and footer. T026–T029 can start as soon as US1 is done; only T025/T030 wait for US3.
- **Polish (T032–T037)** comes last. T032 and T033 can run any time after US3.

Within a story, the converter tasks come before the `main.js` tasks that act on their hooks, and every story ends with its verify task.

## Parallel opportunities

- **Phase 2**: T009 (`website/styles.css`) and T010 (`website/main.js`) run alongside T003–T008 (`tools/build_website.mjs`).
- **US4**: T026, T027, T028 and T029 are four different files and can run in parallel. The three Arabic pages are independent translations.
- **Polish**: T032 (`STATUS.md`) and T033 (`claims.md`).

```text
# US4 in parallel, after T026 lands:
Task: "Create website/ar/about.html — translated body, lang/dir, ../ paths, markers"
Task: "Create website/ar/security.html — same, every stated limit kept"
Task: "Create website/ar/help.html — same, Arabic form texts, still sends to support@"
```

## Implementation strategy

1. **MVP = Setup + Foundational + US1.** The English PC home page is Website v3, and its form sends. Stop and check it against the design (T015).
2. **US2** brings phones onto their own design. The English site is then complete.
3. **US3** adds Arabic on both screens.
4. **US4** brings the inner pages into the new look and into Arabic.
5. **Polish** updates the records and commits. It stops at Mohamed's review. Nothing is published without his go-ahead.

## Notes

- The design's words are used exactly, including the 19 sentences from `claims.md`. Do not "correct" them on the home page. Do not copy them into About, Security or Help (plan, Complexity Tracking).
- Never hand-edit `website/index.html`, `website/ar/index.html` or `design-*.css`. Change the converter or the design, then rebuild.
- If the converter stops on a design change later, fix the edit table, not the output.
- No real form send without Mohamed's OK. Test the failure path by blocking the request.
