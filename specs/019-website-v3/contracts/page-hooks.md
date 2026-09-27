# Contract: the hooks between the generated pages and `main.js`

The converter turns the design's handlers into data attributes and keeps the design's own
names. `main.js` acts on them. This list is the whole vocabulary. If a design uses a name
that is not here, the converter stops with "new interaction in the design: add it to
main.js and to this contract". A new design can therefore never ship a button that does
nothing.

## Handlers: `data-on="event:name"` (plus `data-i="n"` inside a loop)

| Design wrote | Becomes | Where | `main.js` does |
|---|---|---|---|
| `onMouseMove="{{ heroMove }}"` | `data-on="mousemove:heroMove"` | PC hero | sets `--mx`/`--my` in px on that element (skipped under reduced motion) |
| `onClick="{{ toggleMenu }}"` | `data-on="click:toggleMenu"` | phone header | flips the menu; the button's three child bars take the design's open transforms (`translateY(7px) rotate(45deg)`, opacity 0, `translateY(-7px) rotate(-45deg)`); sets `aria-expanded` |
| `onClick="{{ closeMenu }}"`, `onClick="{{ m.go }}"` | `data-on="click:closeMenu"` / `click:m.go` | phone links | shuts the menu; the link then does its normal jump |
| `onScroll="{{ onToolsScroll }}"` | `data-on="scroll:onToolsScroll"` | phone Tools row | active index = `round(abs(scrollLeft) / (firstCard.offsetWidth + 12))`; restyles the dots |
| `onClick="{{ d.go }}"` | `data-on="click:d.go"`, `data-i` | phone Tools dots | `cards[i].scrollIntoView({behavior, inline:'start', block:'nearest'})` |
| `onClick="{{ c.toggle }}"` | `data-on="click:c.toggle"`, `data-i` | phone footer | opens fold `i` and shuts the others; the button's last child turns `rotate(45deg)` |
| `onClick="{{ o.pick }}"` | `data-on="click:o.pick"`, `data-i` | both forms | exactly one camera option on, with the design's on/off colours; `aria-pressed` |
| `onSubmit="{{ submit }}"` | `data-on="submit:submit"` | both forms | the send (R8, spec 017 contract) |

Active and idle dot styles come from the design: active is `width:24px`,
`background:#33705b`; idle is `width:8px`, `background:#c3cfc6`.

## References: `data-ref="name"`

| Name | Where | Use |
|---|---|---|
| `typedRef` | both heroes | the typed question. It carries `data-qs` (JSON of the design's `qs` list) |
| `langRef` | both heroes | the language tag beside it |
| `toolsRef` | phone Tools row | the carousel |

## Conditions: `<div data-if="name" style="display:contents">`

`hidden` when the design's starting state is false. `styles.css`:
`[data-if][hidden]{display:none!important}`.

| Name | Starts | Shown when |
|---|---|---|
| `menuOpen` | hidden | the menu is open |
| `showCta` | hidden | scroll past 560 px, the phone Contact section's top still below 90% of the screen height, and the menu shut |
| `c.open` (with `data-i`) | hidden | that footer fold is open |
| `notSent` | shown | the form, until a send is confirmed |
| `sent` | hidden | the thank-you, after a confirmed send |

## Site hooks (added by the converter's site edits, not in the design)

| Hook | Use |
|---|---|
| `[data-failed]` inside each form | the "not sent" block (E13) |
| `[data-again]` inside each `sent` block | "Send another" (E14) |
| `[data-label]` inside each submit button | the text swapped for "Sending…" |
| `.vg-pc` / `.vg-ph` | the two copies (R1) |
| `data-par`, `data-reveal`, `data-count`, `data-line`, `data-progress`, `data-nav`, `data-stagger` | the design's own motion hooks; the IntersectionObserver fallback reads them in **every** copy (`querySelectorAll`) |

## Page-level behaviour, not tied to a hook

- **Twin ids**: on load and on `hashchange`, if `#x` has no box, scroll to `#m-x` (or
  from `#m-x` to `#x`).
- **Menu and width**: when `(width < 600px)` stops matching, the menu shuts.
- **Reduced motion**: no typing loop (the first question shows still), no glow, no
  fallback reveal, no CTA slide (the bar still shows and hides).
