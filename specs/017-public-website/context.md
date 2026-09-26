# Implementation context: The VisionGuard website

**Written by `/speckit-plan` on 27 September 2026, against commit `980e505`.**

Read this **before** opening any file. All four website files are new. The source is
one file: `design/Visionguard website design/VisionGuard Website v2.dc.html` ("the
design", 562 lines). Open it by the line ranges below, not whole.

> Verify before trusting. This is a snapshot. If it disagrees with the design file,
> the design file wins.

---

## 1. Anchors — where each piece comes from

| New file | Take from the design | Shape there today | The edit |
|---|---|---|---|
| `website/index.html` `<head>` | lines 10–13 `<helmet>` | font link (Albert Sans, Noto Sans Arabic, JetBrains Mono), icon `./assets/visionguard.ico` | real `<head>`: add `<title>VisionGuard AI</title>`, a meta description, `styles.css`, `main.js` with `defer`. Drop `support.js` (line 6) |
| `website/styles.css` | lines 15–83, the `<style>` body | 39 `@keyframes`; `[data-*]` hooks; `@supports (animation-timeline: view())` block at 68–81; reduced-motion at 83 | copy verbatim, then add: `.h1`–`.h13` hover rules and `.f1` focus rule (all `!important`), `section[id]{scroll-margin-top:72px}`, `scroll-behavior:auto` under reduced motion, the `.vg-io` fallback (R4), `.soon`, a `@media (max-width:520px)` block only if the 360-px check needs it |
| `website/index.html` body | lines 88–473 | NAV 90 · HERO 110 (mosaic 135) · STATS 169 · SITES 179 · HOW 191 · TOOLS 215 · HONEST 245 · MOBILE 292 · TRUST 351 · CONTACT 382 · footer 441 | port per research R2. Expand every `<sc-for>` from `renderVals()` (lines 513–556). Wrapper line 88: `overflow-x:hidden` → `clip` |
| `website/main.js` | lines 476–558, `class Component` | `qs` (7 questions and tags) line 479; `startTyping()` 493–506; `heroMove` 518; `camOpts` 522 (default `'25–100'`, colours on/off); `submit` 523 is a fake `setState({sent:true})` | port `startTyping` and `heroMove` as they are; picker toggles the four buttons' inline colours; replace `submit` with the real send (contract); add the scroll fallback (R4). Drop `applyMotion` and `componentDidUpdate` |
| `website/assets/` | `design/…/assets/visionguard.ico`, `mobile-2.png` | 26 KB and 36 KB | byte copy |
| `.claude/launch.json` | existing file; git-excluded (`.git/info/exclude` line 9) | two entries, `mock-admin` (5173) and `mock-mobile` (5174), each `powershell … dev.ps1 up …` | append `{"name":"website","runtimeExecutable":"python","runtimeArgs":["-m","http.server","8090","--directory","website"],"port":8090}` |

**Loop data to write out** (all in `renderVals()`):
- `cams` (4 tiles, 524–529): each has `name, feed, x, y, w, h, color, label, drift,
  halo, delay`. Colours: G `#3ec776`, B `#5b9bd8`, R `#e5564a`, A `#dfa23f` (line 514).
  Only "Library east" has `halo: vg-nextcam…`; the other three have `animation:none`.
- `sitesLoop` (519): the 8 names twice (16 items, needed for the seamless `-50%`
  marquee).
- `steps` (531–534), `chips` (536), `tools` (538–543), `sources` (546–548) and `trust`
  (551–554).

**Hover classes**: 13 distinct `style-hover` values across 40 uses. Most common:
`color:#fff` ×20 (footer links), `color:#1f2b26` ×4 (nav links), and the phone-tile
lift ×4. `style-focus` has one value ×6: `border-color:#33705b;box-shadow:0 0 0 4px
rgba(51,112,91,.14)`.

## 2. Things to copy, not invent

- Typing loop → the design's `startTyping()` (lines 493–506). It sets
  `dir="rtl"` when the text has Arabic (`/[؀-ۿ]/`), types at 55 ms, holds
  1800 ms, and deletes at 22 ms.
- Mouse glow → `heroMove` (line 518). It sets `--mx` and `--my` in px on the hero
  section; the glow div at line 113 reads them.
- Form markup and thank-you → lines 409–435 as they are. Only the send logic is new
  (`contracts/contact-form.md`, `data-model.md`).
- Scroll-linked styles that the fallback must reproduce: `vg-rv` (line 31),
  `vg-zoom` (46), `vg-count` (45), `vg-line` (52), `vg-tilt` (44), `vg-nav` (43),
  `vg-progress` (42), `vg-parA`/`vg-parB` (47–48).

## 3. Traps

- **Inline beats class.** Every hover and focus rule needs `!important`, or nothing
  happens on hover.
- **Sticky header dies under `overflow-x:hidden`.** The wrapper at line 88 must be
  `overflow-x:clip` (research R8).
- **`[data-count]` shows its number through CSS**: `[data-count]::after{content:
  counter(n)}`, with `--n` registered by `@property` (line 34) and set inline, e.g.
  `--n:208;counter-reset:n var(--n)`. The element has no text. Do not "fix" it by
  adding text.
- **`[data-live]`** (the phone's "People in view") uses the same counter trick, run by
  a clock (`vg-live`, steps(1)), not by scrolling. It needs no fallback.
- **`[data-par]`** has a floating animation at all times (line 63). Inside `@supports`
  (76–77) that float is combined with the parallax. In the fallback, keep the float
  animation and apply the parallax as `translate` from the script. `translate` and
  `transform` stack, so the two do not fight.
- **`[data-tilt]`** has an inline tilted `transform` (line 137) as its resting look.
  In the fallback, `.vg-in` plays `vg-tilt` on a clock to flat.
- **The fallback must not hide anything under reduced motion.** The reduced-motion
  rule (`*{animation:none!important}`) would leave a `.vg-io [data-reveal]` at
  opacity 0. So skip the fallback entirely when
  `matchMedia('(prefers-reduced-motion: reduce)')` matches, and make `.vg-in` set the
  end state (`opacity:1`) itself, not only through animation fill.
- **FormSubmit refuses `file://`** and answers `success` as the string `"true"`
  (research R5).
- **No real test sends without Mohamed's OK.** A send emails sales@vision-guard.org,
  and the first one triggers the activation email. Test failure paths by blocking
  the request.
- **Line endings**: all new files are LF. None of the CRLF files listed in AGENTS.md
  are touched.
- **Other sessions**: `dev.ps1` shows `UU` (an unresolved merge) and
  `specs/016-pilot-site-readiness/` is untracked. Both belong to someone else. Leave
  them, and stage only `website/` and this spec folder.

## 4. Baseline

- `python -m pytest engine` → **1889 passed, 6 skipped** (4 min 16 s) at `980e505`
  plus the tree's uncommitted work. It must not change.
- This feature adds no pytest file. Its checks are quickstart §2 (the script) and §3
  (by eye).

## 5. Still unknown

- **How the phone stage looks at 360 px.** It is built for about 560 px (two phones
  at fixed 240 and 260 px). The clip stops sideways scroll, but the left phone may be
  cut. Check, then scale the stage in the 520-px media block if needed.
- **Whether FormSubmit's `_template: "table"` and `_subject` render as expected** in
  the forwarded Gmail copy. Only visible after the first activated send.
