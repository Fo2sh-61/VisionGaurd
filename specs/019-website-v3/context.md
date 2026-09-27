# Implementation context: the website in its new design

**Written by `/speckit-plan` on 27 September 2026, against commit `b2c1fea`.**

Read this **before** opening any file. Open the named anchors only.

> Verify before trusting. This is a snapshot. If it disagrees with the code or the design
> files, they win. Search for the symbol; line numbers drift.

The design folder is `design/Visionguard website full design/` ("D/" below). It is
untracked today (see Traps).

---

## 1. Anchors: where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `tools/build_website.mjs` | new | — | the converter (contracts/converter.md). Reads the four `D/*.dc.html` |
| design files (input) | `<helmet>`, `</helmet>`, `<script>`, `class Component extends DCLogic` | Each file: `<x-dc><helmet>` with font link, icon, `<style>…</style>`, then `</helmet>`, then one outer `<div …>` wrapper (the page), then `<script>` with `class Component`. v3 sections: NAV 95, HERO 113 (`<section id="top" onMouseMove=…>`), hero stage 141, STATS 216, SITES 226, HOW 238, TOOLS 262, HONEST 288, MOBILE 335, TRUST 396, CONTACT 427 (form 454), footer 486. Mobile: header ~65 (menu `sc-if` 81), HERO 92, STATS 152, SITES 162, HOW 174, TOOLS 198 (carousel `data-snap` 204), HONEST 223, MOBILE 259, TRUST 318, CONTACT 347, FOOTER 403, CTA `sc-if` right after the footer | input only. The AR files have the same layout, about 3 lines lower |
| design script | `state = {…}`, `qs = […]`, `renderVals()` | v3 `state = { sent:false, cams:'25–100' }`; Mobile adds `menuOpen:false, tool:0, openCol:-1, showCta:false`. `qs` = 7 `[text, tag]` pairs. renderVals keys: v3 `typedRef langRef heroMove sitesLoop sent notSent camOpts submit cams steps chips tools sources trust`; Mobile `… menuOpen toggleMenu closeMenu bar1 bar2 bar3 menuLinks showCta tools onToolsScroll toolDots sources tiles logs trust cols` | evaluate once with stubs (converter.md). Emit `qs` as `data-qs` JSON on the `typedRef` span |
| `website/index.html` | whole file | the hand-port of v2 (527 lines), with 017's corrected claims | **replaced** by converter output. Copy its form snippets first: `_honey` input, the `id="contact-failed"` block (the "not sent" text with the mailto and tel links), and the `data-again` "Send another" button. Those become snippets E13 and E14 |
| `website/ar/index.html` | new | — | generated |
| `website/design-pc.css`, `design-phone.css` | new | — | generated. Linked **before** `styles.css`, with `media="(width >= 600px)"` and `media="(width < 600px)"` |
| `website/styles.css` | line 1–69 (v2's design `<style>`), then `/* ---- Added for the website` | 69 lines of v2 design CSS; then the site's own rules: `[hidden]` fix (73), `section[id]{scroll-margin-top:72px}` (75), reduced-motion `scroll-behavior` (77), `.h1`–`.h13` and `.f1` (79–94), tool-card corner glow and line fix (96–99), `.soon` (101–103, Albert Sans, `margin-left`), the `.vg-io` fallback (105–123), the narrow block (125–138), `.pg-*` inner pages (140–160), "PHONE ONLY" (163–end) | **delete** 1–69, 79–94, 125–138 and 163–end. **Keep** 73, 77, 96–99, 105–123 and `.pg-*`. **Add**: `[data-if]{display:contents}[data-if][hidden]{display:none!important}`; the copy switch (`@media (width < 600px){.vg-pc{display:none!important}}` and `@media (width >= 600px){.vg-ph{display:none!important}}`); a marked tablet block `@media (width >= 600px) and (width < 1080px)` for measured fixes only. Make 75 `.vg-pc section[id]` (the phone design has its own 68 px). `.soon`: Rubik, `margin-inline-start`. `.pg-*`: Rubik |
| `website/main.js` | `const qs`, `startTyping`, `hero.addEventListener('mousemove'`, `.vg-how-track`, `camButtons`, `send(to, fields)`, `wire(id, to, fields, fresh)`, `vg-io` block, `vg-offscreen` block | one IIFE; `reduced` from `matchMedia`; typing uses `getElementById('typed'/'lang')`; `wire` finds `-sent`/`-failed` by id and reads `f._honey`, `f.email` …; the fallback uses `querySelector` (one) for `[data-progress]` and `[data-nav]` | typing: loop over every `[data-ref="typedRef"]`, reading `data-qs`; glow: `[data-on="mousemove:heroMove"]`; **delete** `.vg-how-track`; cams: per form via `click:o.pick`; `send` **unchanged**; `wire(form, sentEl, …)` finds `[data-failed]` and `[data-label]` inside the form. The generated forms' "sent" block is the `[data-if="sent"]` in the same `<section>`; the Help form keeps `#help-sent`. Every text from the lang table. Fallback: `querySelectorAll` for progress and nav. **Add**: menu, CTA, Tools dots, footer folds, twin ids, `setCustomValidity` (contracts/page-hooks.md) |
| `website/about.html`, `security.html`, `help.html` | `<header data-nav="1"`, `<footer style="background:#161c19`, the font `<link>` in `<head>` | header at about.html 19–36 (logo `href="./"`, links `./#how`…, classes `h1`/`h2`), footer 72–101 (Soon spans, English pill). Head loads Albert Sans + Noto Sans Arabic | swap the header and footer for `<!-- vg:header --><!-- /vg:header -->` and `<!-- vg:footer --><!-- /vg:footer -->` (the converter fills them). Fonts → the design's link. Link `design-pc.css` / `design-phone.css`. Body untouched. The help form: give its not-sent block `data-failed` and its button label `data-label` |
| `website/ar/{about,security,help}.html` | new | — | a copy of the English page with `lang="ar" dir="rtl"`, `../` paths and a translated body. Every sentence keeps its facts; add none (P14-FR-023) |
| `STATUS.md` | the `\| Website \|` row (line 26) | one very long cell. It says "Every product claim on the page was checked … 19 … reworded" | say: the home page now uses the design's words (spec 019, Mohamed's choice); the 19 are on the site again; Arabic pages exist; two copies per page; there is a converter. **CRLF file** |
| `specs/017-public-website/claims.md` | `## Open with Mohamed` (end) | tables of Changed and True claims | add a closing section: reverted to the design's words on 27 Sep 2026 (spec 019); list which rows are on the site again |

## 2. Things to copy, not invent

- Sending, the 15 s timeout and "success" as the string `"true"` → `website/main.js::send`,
  as it is.
- The typing loop → `main.js::startTyping` (it is the design's: 55 ms, hold 1800, delete
  22 ms, RTL when `/[؀-ۿ]/`). Only the element lookup changes.
- The camera picker's on/off colours → `main.js` `ON`/`OFF` (they match the design's
  `camOpts`).
- The fallback reveal and the drift maths → `main.js` `vg-io` block and `styles.css`
  105–123.
- The menu's open transforms, the dot styles, the CTA rule (`y > 560`, Contact top <
  0.9 × screen height) → the Mobile design's `renderVals` and `componentDidMount`
  (contracts/page-hooks.md has the values).
- The Arabic footer labels to map in E5: `من نحن`, `الأمان`, `مركز المساعدة`. The other
  Arabic `#` items become "قريبًا".
- The page shell (`<head>`: charset, viewport, title, description, fonts, icon, CSS, `defer`
  script) → today's `website/index.html` head, with the design's font link.

## 3. Traps

- **Escaped CSS in the Mobile designs**: their `<style>` has
  `@property --n{syntax:'&lt;integer&gt;'…}` (and `--a`). The v3 designs have plain
  `'<integer>'`. The converter must unescape `&lt; &gt; &amp;` in style text. Otherwise
  the property is invalid, and the counting numbers and the Trust border light stop.
- **Inline beats class**: every generated hover and focus rule needs `!important`.
- **Sticky dies under `overflow-x:hidden`**: both wrappers (E8). The phone wrapper also
  loses `max-width:430px` and its side shadow (E9), and the CTA bar loses its 430 cap
  (E10).
- **`[data-count]` shows its number through CSS** (`counter(n)` with `--n`). The element
  has no text; do not add any. `[data-live]` is the same trick on a clock.
- **`[data-par]`** floats always, and gets its parallax from the scroll timeline or the
  fallback's `translate`. `translate` and `transform` stack.
- **Reduced motion**: the fallback must not run at all, or `.vg-io [data-reveal]` would
  sit at opacity 0.
- **RTL carousel**: `scrollLeft` is 0 or negative. Use `Math.abs` and `scrollIntoView`
  (R6).
- **Numbers in Arabic text**: wrap `+20 100 253 5081` in `<span dir="ltr">` (or `bdi`).
  Keep the shown number's format as the design writes it. E3 matches "as written in
  each design": look up the exact string in `Mobile AR` first, since it was not found as
  plain `0000 0000` text.
- **The Mobile menu skips 05** (Trust has no id). Keep it that way.
- **FormSubmit refuses `file://`** — serve over http. **No real sends without Mohamed's
  OK.** Test the failure path by blocking the request.
- **The old claims come back on purpose** (R10). Do not "fix" the design's words on the
  home page. Do not copy them into About, Security or Help either.
- **Line endings**: `STATUS.md` is CRLF. Everything in `website/`, `tools/` and the spec
  is LF. Check `git diff --stat`.
- **Other sessions' work in the tree**: `dev.ps1` shows `UU` (an unresolved merge), and
  `research/` and `specs/016-pilot-site-readiness/` are untracked. Not ours; leave them.
- **The design folder is Mohamed's rename**: the old folder shows as deleted and the new
  one as untracked. The converter needs the four `.dc.html` files and `assets/` in the
  repo. Commit them together with the old folder's deletion. **Ask Mohamed before
  committing `uploads/` and `ref/`**: they hold a WhatsApp photo and screenshots.
- **`preview_start` reads the main checkout's `.claude/launch.json`**. Its `website`
  entry (port 8090) already exists.

## 4. Baseline

- `python -m pytest engine` → **1889 passed, 6 skipped** (4 min 5 s) at `b2c1fea`, with
  the tree's uncommitted work. It must not change.
- No pytest file is added. The checks are the converter's own stops, and quickstart §1
  (a second build changes nothing) and §3–§6.

## 5. Still unknown

- **600–1079 px**: whether the v3 header (four links, العربية, Contact us), the 920 px
  hero rings and the Honest card at `left:309px` overlap or push sideways. Measure at 600,
  768 and 900 before writing any tablet fix.
- **The phone number's exact text** in `Mobile` and `Mobile AR` (see Traps).
- **Whether v3 still has a `data-tilt` element**: the camera wall is gone, and `data-tilt`
  appears once, possibly only in CSS. The fallback copes either way.
- **Whether EN and AR `qs` lists differ.** `data-qs` carries each one, so it does not
  matter.
- **Scroll margin on PC**: the v3 header's real height, for `.vg-pc section[id]`.
