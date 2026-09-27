# Research: the website in its new design

Each decision is the smallest mechanism that meets the spec. Mohamed settled R1, R2 and
R7 on 27 Sep 2026 (plan questions), and the words (R10) at spec time.

## R1. One page carries both layouts, and the screen width picks one

**Decision**: each home page holds two copies of the page, the PC design and the phone
design, one after the other. Each copy has its own stylesheet, loaded with a `media`
attribute: `design-pc.css` for 600 px and wider, `design-phone.css` below. A two-line
rule in `styles.css` hides the copy that does not apply.

**Rationale**: the two designs are not one layout at two sizes. The phone has a menu
panel, a swipeable Tools row with dots, a slide-up "Contact us" bar and a fold-out
footer; the PC has none of them. Two copies let each screen match its drawing exactly
(spec P14-FR-018). Loading each design's CSS only at its own width means the two
designs' rules never meet. They share keyframe names with different values
(`vg-htrack`, `vg-rv`, `vg-ring`, `vg-pop`), and this way nothing has to be renamed or
scoped. The hidden copy is `display:none`, so its animations do not run.

**Cost**: the home page's markup is about twice as big (about 25 KB compressed). It
still loads in well under the 2 s of SC-005. Every section id is in the page twice, so
the phone copy's ids get an `m-` prefix (R6).

**Alternatives**: one layout reshaped for phones with media queries (what spec 017
did). It is lighter, but the phone menu, carousel and fold-out footer could only be
approximated. Mohamed chose exact.

## R2. A converter turns the design files into the site

**Decision**: `tools/build_website.mjs`, one Node file with no packages. Run
`node tools/build_website.mjs` after any design change. It:

1. Reads the four design files. Takes each one's `<style>`, its markup and its
   `class Component`.
2. Runs the design's own `renderVals()` with its starting state (menu shut, first Tools
   card, "25–100" cameras, nothing sent) to get the list data.
3. Writes out every `<sc-for>` loop and `{{ value }}`. Each `<sc-if>` becomes a wrapper
   `<div data-if="name">` that shows or hides its content, `hidden` when it starts
   false.
4. Turns each `onClick="{{ fn }}"`-style handler into `data-on="click:fn"` and each
   `ref="{{ x }}"` into `data-ref="x"`, with `data-i` inside loops. `main.js` acts on
   these by the design's own names (`contracts/page-hooks.md`).
5. Turns `style-hover` and `style-focus` into generated classes with `!important`, since
   an inline style beats any class.
6. Applies the site edits (data-model §3). **Each edit must match exactly once, or the
   build stops and names the edit.** A handler or `sc-if` name it does not know stops it
   too. So a new design can never ship with a silently skipped fix or a dead button.
7. Writes both home pages and both design stylesheets whole. It rewrites only the marked
   header and footer blocks inside the six inner pages. It copies `mobile-2.png` and
   `visionguard.ico`.

**Rationale**: Mohamed redesigned three times on 27 Sep. A hand port of four files (about
2,300 lines) would be redone on each change. The converter makes the next update one
command. It also keeps the header and footer identical on all eight pages. The output
is still plain files with no build on the host: the folder uploads as it is (spec 017,
P14-FR-002).

**Alternatives**: a one-time hand port (Mohamed declined it). Shipping the design
runtime `support.js` (rejected in spec 017: it downloads React and a compiler on every
visit). A general HTML parser package: no. The design files use five template forms
(`sc-for`, `sc-if`, `{{ path }}`, `on*=`/`ref=`, `style-hover`/`style-focus`), and a
matcher that knows nesting is enough.

## R3. Only the listed site edits differ from the design

**Decision**: the design's words, colours, fonts, spacing and motion are used as they
are. The only changes are in data-model §3. They are: the real contact details, working
footer links, "Soon" marks, the form's sending machinery, the language links, the phone
copy's ids, sticky headers kept sticky, and the phone design stretched to full width.

**Rationale**: spec P14-FR-018 (exact), P14-FR-019 and P14-FR-027/028 (keep what works
today).

## R4. Arabic lives under `/ar/`

**Decision**: `website/ar/` holds the Arabic twin of every page, under the same file name
(`ar/index.html`, `ar/about.html`, …). Arabic pages set `<html lang="ar" dir="rtl">`. The
switch links to the twin: `ar/about.html` ↔ `../about.html`. The language is never
guessed from the browser, and no choice is remembered.

**Rationale**: P14-FR-020/021. A separate address can be shared and bookmarked
(spec Assumptions). Same file names make the twin link a fixed rule. GitHub Pages serves
`/ar/` with no set-up.

**Alternatives**: one page swapping text by script (no shareable address, and nothing
readable without the script); a subdomain (new DNS and a second repo).

## R5. Inner pages keep their own bodies and get the design's header and footer

**Decision**: About us, Security and Help centre keep their hand-written middle. Their
header and footer sit between `<!-- vg:header -->…<!-- /vg:header -->` and
`<!-- vg:footer -->…<!-- /vg:footer -->` markers, and the converter fills those from the
design (PC and phone copies, with section links pointed at `./#how` and so on). Their own
styles (`.pg-*` in `styles.css`) switch font to Rubik. The Arabic bodies are translated
by hand, sentence by sentence, keeping every fact and adding none (P14-FR-023). Mohamed
reads them before they are published.

**Rationale**: P14-FR-026. With no design for these bodies, hand-written is the only
choice. Stamping the chrome means one design change reaches all eight pages.

## R6. Phone behaviour, section links and the twin ids

**Decision**: `main.js` implements the design's handlers by name:

- `toggleMenu`, `closeMenu`, `m.go`: opens and shuts the menu. The three bars turn into a
  cross using the design's transforms. The menu also shuts when the window grows past the
  phone width (spec edge case).
- `showCta`: the slide-up "Contact us" bar. It shows past 560 px of scroll, but not near
  Contact and not while the menu is open. This is the design's rule from
  `componentDidMount`.
- `onToolsScroll`, `d.go`: the Tools dots follow the swipe, and a tapped dot scrolls to
  its card.
- `c.toggle`: the footer folds, one open at a time; its "+" turns to "×".
- `o.pick`: the camera-count picker (as today).
- `heroMove`: the glow follows the mouse (as today).

**Twin ids**: the phone copy's ids are `m-top`, `m-how`, … and its own links point at
them. A link from elsewhere (`about.html` → `./#how`) can land on the copy that is hidden.
So on load and on `hashchange`, if the target has no box, the page scrolls to its twin
instead. That is about eight lines.

**RTL trap**: in a right-to-left scroller, `scrollLeft` counts down from 0. The active
dot uses `Math.abs(scrollLeft)`, and a tapped dot uses
`scrollIntoView({inline:'start', block:'nearest'})`, not the design's
`scrollTo(offsetLeft - 20)`.

## R7. The switch point is 600 px; big phones stretch; tablets get the PC design

**Decision**: below 600 px, the phone design; 600 px and up, the PC design. The phone
design's 430 px frame (and its side shadow) is removed, so big phones fill the screen
(Mohamed, 27 Sep). Between 600 and 1079 px, the PC design folds as it already does (the
hero's floating cards hide below 1080). Anything that still overlaps there gets the
smallest fix, in one marked block in `styles.css`. It is found by measuring at 600, 768
and 900 px (quickstart §3).

**Rationale**: the widest current phone is 430 px wide upright, and the smallest tablet
is 600. P14-FR-024.

**Known risks to measure**: the header (four links, العربية and Contact us on one row);
the hero rings (920 px wide); the Honest section's card placed at `left:309px`.

## R8. The forms keep today's delivery and speak the page's language

**Decision**: the send path is spec 017's `contracts/contact-form.md`, unchanged: the
contact form goes to sales@, the Help form to support@, the thank-you only on a
confirmed send, and "not sent" otherwise. What is new:

- Each language's "not sent" block, the hidden anti-spam field and "Send another" are
  added into the design's form by the converter (the design has none of them).
- "Sending…" and the two validation messages ("fill in this field", "enter an email") come
  from a four-line table in `main.js`, chosen by `<html lang>`. Validation uses
  `setCustomValidity`, because the browser's own bubble is in the browser's language,
  not the page's (P14-FR-022).
- `main.js` wires every form it finds (one per copy), each to its own "sent" and "not
  sent" blocks.

## R9. What goes

These are replaced by the design's own versions:

- the 017 phone block in `styles.css` (the `max-width:620px/900px/480px/380px` rules, from
  "PHONE ONLY" to the end);
- the old narrow-screen block;
- `.h1`–`.h13` and `.f1`;
- the `.vg-how-track` code in `main.js`;
- the Albert Sans and Noto Sans Arabic fonts.

## R10. Words

**Decision**: the design's words, exactly (Mohamed, 27 Sep). That brings back the 19
sentences listed in `specs/017-public-website/claims.md`. When this ships:

- `STATUS.md`'s Website row stops saying every claim was checked;
- `claims.md` gets a closing section saying the home page reverted to the design's words
  at Mohamed's choice on 27 Sep 2026, and which of the 19 are therefore on the site again.

Security, About and Help keep their checked words.

## R11. Fonts and speed

**Decision**: Rubik (it has Arabic letters), Instrument Serif and JetBrains Mono from
Google Fonts, as the design links them, with `display=swap`. The fallback is
`system-ui`, which has Arabic on Windows, macOS, iOS and Android. The rest is as in spec
017: decorative loops pause off screen on narrow screens; reduced motion stops
everything; the IntersectionObserver fallback runs where scroll timelines are missing.
Every query that used to expect one element now takes all of them, because each page
has two headers and two progress bars.
