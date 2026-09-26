# Research: The VisionGuard website

Each decision takes the smallest thing that meets the requirement. The source is
`design/Visionguard website design/VisionGuard Website v2.dc.html` ("the design").

## R1. Plain files, and the design runtime does not ship (P14-FR-001, 002)

**Decision**: `website/index.html`, `styles.css`, `main.js` and two pictures. No
framework, no build.
**Rationale**: the design is already HTML with CSS animations. Its runtime,
`support.js`, loads React 18 and `@babel/standalone` from unpkg on every visit and
compiles the page in the browser. That is slow, and it would make the page depend
on a design tool.
**Alternatives**: React + Vite like the console (build step, no gain for one page);
shipping `support.js` as it is (slow, third-party runtime).

## R2. How the markup is ported (P14-FR-001)

**Decision**: copy the design's markup and inline styles as they are. Change only
what the browser cannot read:

| In the design | Becomes |
|---|---|
| `<helmet>` | the page's `<head>` |
| `<sc-for list="{{ x }}">` | the items written out, from `renderVals()` at the end of the design |
| `{{ c.name }}` etc. | the literal values |
| `style-hover="…"` (13 distinct) | a class `h1`…`h13`, with a rule `.hN:hover{… !important}` |
| `style-focus="…"` (6, all the same) | one class `f1`, with a rule `.f1:focus{… !important}` |
| `ref="{{ typedRef }}"`, `ref="{{ langRef }}"` | `id="typed"`, `id="lang"` |
| `onMouseMove`, `onClick`, `onSubmit` | listeners in `main.js` |
| `<sc-if>` form / thank-you | two blocks; the script swaps `hidden` |
| outer `<div style="…overflow-x:hidden">` | `overflow-x:clip` (see R8) |

**Rationale**: the inline styles are the approved design, so copying them is the
most faithful and the fastest route. `!important` is needed because an inline style
beats any class rule.

## R3. Motion (P14-FR-005, 007)

**Decision**: move the design's `<style>` block into `styles.css` unchanged: all 39
keyframes, the `@supports (animation-timeline: view())` block and the reduced-motion
rule. Leave out the design tool's `motion`/`reveal` switches (`applyMotion`). The
reduced-motion media query already does that job for visitors. Port `startTyping()`
as it is, with its seven questions and language tags.

## R4. Scroll animations in Firefox (P14-FR-005, 006; Mohamed chose "yes")

**Decision**: if `CSS.supports('animation-timeline: view()')` is false, and the
visitor has not asked for reduced motion, the script:
1. adds `vg-io` to `<html>`. Only then does CSS hide `[data-reveal]` and hold
   `[data-count]` at 0;
2. adds `vg-in` once, when an IntersectionObserver sees each `[data-reveal]`,
   `[data-count]`, `[data-line]` or `[data-tilt]`. CSS under `.vg-io .vg-in` plays
   the same keyframes on a clock (about 0.8 s; 1.6 s for counts), delayed 0, 0.1,
   0.2 and 0.3 s for the four `[data-stagger]` children;
3. runs one passive scroll handler, limited to one update per frame, for the three
   scroll-linked effects: the progress bar (`scaleX`), the header turning solid over
   the first 240 px, and the two phones' parallax.

**Rationale**: the hiding class is added by the same script that shows things, so if
the script fails nothing stays hidden. Browsers that support scroll timelines never
run it.
**Alternatives**: no fallback (Mohamed said no); a scroll-animation library (a
dependency for about 40 lines of work).

## R5. Sending the form (P14-FR-009 to 012, 014)

**Decision**: FormSubmit's AJAX address,
`POST https://formsubmit.co/ajax/sales@vision-guard.org`. The request and answers are
in [contracts/contact-form.md](contracts/contact-form.md).

Checked on 27 Sep 2026 with a probe to an unused address:
- it answers with `Access-Control-Allow-Origin: *`, so a page on any host can call it;
- `success` is a **string**, `"true"` or `"false"`, not a boolean;
- a page opened as a file is refused: *"Make sure you open this page through a web
  server, FormSubmit will not work in pages browsed as HTML files."*

The first message to a new address triggers an "Activate Form" email to
sales@vision-guard.org. Mohamed's forwarding takes it to his Gmail, and he clicks it
once. Until then FormSubmit answers `"false"`, and the form shows "not sent" with the
email and phone. That is the honest state the spec asks for, with no extra code.

Without the script (still loading, or failed), the browser would submit the form
itself. With no `action` that was a GET to the page, which puts everything typed into
the address bar and sends nothing (found while testing). So the form carries
`action="https://formsubmit.co/sales@vision-guard.org" method="POST"`, FormSubmit's
ordinary address: the script always cancels it, and without the script the message
still really goes, with FormSubmit's own confirmation page.

Spam: a hidden `_honey` field. FormSubmit drops a message where it is filled, and the
script does not send such a message at all. Timeout: 15 s, then "not sent".
**Alternatives**: Web3Forms (Mohamed would have to fetch a key); a server of our own
(slow to ship); a `mailto:` form (not what was asked).

## R6. Contact cards (P14-FR-013)

**Decision**: `mailto:sales@vision-guard.org`, `tel:+201002535081`,
`https://wa.me/201002535081`. The number is shown as "+20 100 253 5081". The hours and
the "one business day" wording stay as designed.

## R7. Things that must not pretend (P14-FR-016, 017)

**Decision**:
- Remove the footer's "All systems operational" pill.
- Each footer item with no page is a `<span class="soon" aria-disabled="true">`,
  not a link. It keeps its words and place, is dimmed, and carries a small "Soon" tag.
  These are: Offices, Factories, Warehouses, Hospitals, Retail & malls, About us,
  Careers, Partners, Security, Privacy policy, Terms of service, Help centre,
  LinkedIn, X and YouTube.
- Language switch: "English" stays selected, and "العربية" is dimmed with "Soon".
- The form's note keeps its sentence, but "privacy policy" is plain text followed by
  "(coming soon)".
- The WhatsApp card was `href="#"` and now opens WhatsApp (R6). After this, no
  `href="#"` is left on the page.

## R8. Layout traps the design hides (P14-FR-003, 008)

**Decision**:
- **Sticky header**: `overflow-x:hidden` on the outer wrapper turns it into a scroll
  box, and a sticky header inside it stops sticking. Use `overflow-x:clip`: it clips
  the same way without making a scroll box.
- **Headings under the header**: give every `section[id]` a `scroll-margin-top` of
  about 72 px.
- **Smooth scroll with reduced motion**: add `scroll-behavior:auto` inside the
  reduced-motion query.
- **Scroll animations frozen inside `overflow:hidden`** (found while building): a
  scroll-linked animation follows the nearest *scroll container*, and an
  `overflow:hidden` box is one even though it never scrolls. So every count, line,
  reveal and parallax inside such a box stood still at one frame. The phone's
  "Arrived" showed 48 instead of 142. The same `overflow:clip` fix goes on the 15
  boxes that held them: the numbers strip, `#honest`, `#mobile`, the phone's screen
  and its inner area, the four phone tiles and the four Trust cards. It clips the
  same way.
- **360 px**: likely spots are the hero note at `left:-28px`, the phone stage
  (`left:calc(50% - 250px)`, 560 px tall), the footer's `grid-column:span 2`, and the
  four-across camera picker. The wrapper's clip already stops sideways scroll. Fix
  only what the check finds cut off, with one `@media (max-width:520px)` block.

  **What the check found** (measured at 360–620 px): the phone scene is 532 px wide
  and was cut on both sides below about 610 px. It now shrinks as one picture (×0.74
  up to 620 px, ×0.56 up to 480, ×0.52 up to 380) and gives back the height. The
  header's four section links wrapped into a 240-px stack that stuck over a quarter
  of the screen, so up to 620 px they are hidden. The same links are in the hero and
  the footer. That is a small change to the design, flagged for Mohamed. The hero
  note, the footer and the camera picker were not cut.
