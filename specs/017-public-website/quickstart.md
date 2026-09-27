# Quickstart: check the website works

## 1. Open it

It must be served, not double-clicked. FormSubmit refuses pages opened as files.

```bash
python -m http.server 8090 --directory website
```

Then open http://localhost:8090. Or use the in-app browser: `preview_start` with the
`website` entry in `.claude/launch.json` (local, git-excluded). That entry runs the
command above.

## 2. Check script (in-app browser, `javascript_tool`)

Run at 1440, 390 and 360 px wide (`resize_window`). Every line must print `true`.

```js
const q = s => document.querySelectorAll(s);
({
  sections: ['top','how','tools','honest','mobile','contact'].every(id => document.getElementById(id)),
  noSideScroll: document.documentElement.scrollWidth <= innerWidth,
  noDeadLinks: q('a[href="#"]').length === 0,
  noStatusPill: !document.body.textContent.includes('All systems operational'),
  soonMarked: q('.soon').length === 15,          // 14 footer items + العربية (About us, Security, Help centre are pages; Schools and Supermarkets added, 27 Sep)
  mail: !!q('a[href="mailto:sales@vision-guard.org"]').length,
  phone: !!q('a[href="tel:+201002535081"]').length,
  whatsapp: !!q('a[href="https://wa.me/201002535081"]').length,
  noDesignRuntime: ![...q('script')].some(s => /support\.js|unpkg/.test(s.src)),
  headerSticks: getComputedStyle(document.querySelector('header')).position === 'sticky',
})
```

Then scroll to the bottom and back. Check that the header is still at the top of the
viewport: `document.querySelector('header').getBoundingClientRect().top === 0`.

## 3. By eye, against the design

Open the design file beside the site at the same width. Walk the table in spec
P14-FR-005 section by section. Every motion listed must be seen. Pay particular
attention to:
- the hero typing, including the Arabic questions running right to left;
- the numbers counting up when scrolled to;
- the phones floating and drifting;
- the activity log scrolling;
- the green light running round the Trust card.

## 4. The form

- **Validation**: leave Company empty and press Send. The browser flags the field,
  and nothing is sent (check the network list for no `formsubmit.co` request).
- **Failure**: block `formsubmit.co` (or go offline) and press Send. The page shows
  "not sent" with the email and phone. The thank-you does not appear, and the fields
  keep their text.
- **Double press**: the button is disabled while sending. One request only.
- **Real send, with Mohamed's OK only** (it emails sales@vision-guard.org): send one
  message. The first ever send brings an "Activate Form" email. After Mohamed clicks
  it, send again. The thank-you appears, and the message reaches his inbox with every
  field, and Reply goes to the visitor's address (SC-004).

## 5. Reduced motion and Firefox

- **Reduced motion**: turn on "reduce motion" in the OS (Windows: Settings ›
  Accessibility › Visual effects › Animation effects off) and reload. Nothing moves,
  and all content is visible (SC-007).
- **Firefox**, if installed: sections slide in, numbers count up, the progress bar
  fills and the header turns solid.

## 6. Nothing else moved

```bash
python -m pytest engine
```

The count must be the same as the baseline in `context.md` §4. The website touches
no engine, console or phone file. `git status` shows only `website/` and this spec
folder.

## 7. Publish an update

The live site is the public repo `Fo2sh-61/vision-guard-website` (GitHub Pages, custom
domain www.vision-guard.org since 27 Sep 2026; vision-guard.org forwards to it). The
`CNAME` file holds `www.vision-guard.org`; GitHub manages it, so do not delete it. It holds only the site: `index.html`, `styles.css`, `main.js`,
`assets/`, plus `CNAME` and `.nojekyll`. `website/` in this repo stays the source.

```powershell
$d = Join-Path $env:TEMP "vg-site"; Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
gh repo clone Fo2sh-61/vision-guard-website $d
Copy-Item website\* $d -Recurse -Force
git -C $d add -A; git -C $d commit -m "Update the website"; git -C $d push
```

GitHub rebuilds in about a minute.

**DNS at Spaceship** (set once): four `A` records on `@` — 185.199.108.153,
185.199.109.153, 185.199.110.153, 185.199.111.153 — and a `CNAME` on `www` →
`fo2sh-61.github.io`. The `MX` and `TXT` records belong to the ImprovMX email
forwarding; leave them alone.
