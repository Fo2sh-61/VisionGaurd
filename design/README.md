# design/

The visual designs the console and the phone app were built from. Open any
`.dc.html` file in a browser — they are self-contained canvases, not a build.

| File | What |
|---|---|
| `VisionGuard.dc.html` | The desktop console. Every page |
| `VisionGuard Mobile.dc.html` | The phone app |
| `VisionGuard Story.dc.html` | The walkthrough — what the product is, for somebody who has not seen it |
| `Home Directions.dc.html` | Explorations of the home page |
| `CamGrid.dc.html` | The camera tile grid on its own |
| `shots/` | PNG exports. These are what the README shows |
| `uploads/` | Source material the designs were made from |
| `track-live-design-prompt.md` | The brief the live-tracking screens were drawn from |
| `deck-stage.js`, `support.js`, `ios-frame.jsx` | The canvas runtime. Not product code |

## These are drawings, not screenshots

The mockups are **dated 2 and 27 August 2026** and the product has moved since.
Most visibly, the sidebar in the older exports still lists **Fights**, which was
removed on 19 August because it was never real, and the site name reads
"Greenfield International School", a placeholder — the product ships with that
field blank.

Treat a design as the intent, and `STATUS.md` as the truth.

## `archive/`

This folder used to contain three generations of the same deck nested inside
each other — `design/` held the 2 August version, `27-8 design/` inside it held
the 27 August version, and `27-8 design/uploads/18-8 design/` inside *that* held
the 18 August version. The newest was the most deeply buried.

Comparing them showed that only **two files** ever actually differed:
`VisionGuard.dc.html` and `VisionGuard Mobile.dc.html`. Everything else — the
other five decks, all nine screenshots, the runtime scripts — was byte-identical
in all three copies.

So the current revisions now sit at the top of this folder, the two files that
genuinely changed are kept at their older revisions in `archive/2026-08-02/`
and `archive/2026-08-18/`, and the duplicate trees are gone. Fifty-six tracked
files became sixteen, and nothing was lost.
