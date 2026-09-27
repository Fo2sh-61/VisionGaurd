# Contract: `tools/build_website.mjs`

## Run

```bash
node tools/build_website.mjs
```

From the repo root. Node 18 or newer, no packages. It takes no arguments. Its paths are
fixed at the top of the file.

## Reads

- `design/Visionguard website full design/VisionGuard Website v3.dc.html` — PC, English
- `… VisionGuard Website v3 AR.dc.html` — PC, Arabic
- `… VisionGuard Mobile.dc.html` — phone, English
- `… VisionGuard Mobile AR.dc.html` — phone, Arabic
- `… assets/mobile-2.png`, `… assets/visionguard.ico`
- the six inner pages, only to find their `vg:header` / `vg:footer` markers

## Writes

| File | How |
|---|---|
| `website/index.html`, `website/ar/index.html` | whole, from the page shell in the converter plus both copies |
| `website/design-pc.css` | the union of the two PC designs' `<style>` (Arabic adds rules only), plus generated hover and focus classes |
| `website/design-phone.css` | the same for the two phone designs |
| `website/{about,security,help}.html`, `website/ar/…` | only between the markers |
| `website/assets/*` | byte copy |

It never touches `styles.css`, `main.js`, or anything outside `website/`.

## Guarantees

1. **Stops, writing nothing**, if:
   - a site edit (data-model §3) matches a number of times other than its rule;
   - a handler, `ref` or `sc-if` name is not in `page-hooks.md`;
   - a `{{ … }}` is anything other than a dotted path, or a path has no value;
   - a form does not have exactly 6 fields;
   - the output still contains any forbidden string (data-model §3);
   - an inner page lacks its markers.

   The message names the file, the edit and what it found.
2. **Same input, same output**: a second run changes no file.
3. **Output is plain HTML and CSS**, with no reference to `support.js`, React or unpkg.
4. **Prints** one line per file written, and the count of hover and focus classes.

## Evaluating the design's script

The design's `class Component` runs inside `new Function`, with two stubs:
- `DCLogic`: a class with `state` and a no-op `setState`;
- `React`: `{ createRef: () => ({ current: null }) }`.

Then `renderVals()` is called once, with the starting state. Its functions are never
called. Only their names become hooks. The design files are Mohamed's own, so running
their script locally is trusting the same author as the rest of the repo.
