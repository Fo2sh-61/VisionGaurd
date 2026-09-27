# Quickstart: check the new website works

## 1. Build

```bash
node tools/build_website.mjs
```

It prints each file it wrote. Run it a second time: `git status --short website` must
show no further change (the build is repeatable). If it stops, the message names the
design file and the edit that no longer fits (`contracts/converter.md`).

## 2. Open it

```bash
python -m http.server 8090 --directory website
```

Or use `preview_start` with the `website` entry in `.claude/launch.json`. Pages:
`/`, `/about.html`, `/security.html`, `/help.html`, and the same under `/ar/`.

## 3. Check script (in-app browser, `javascript_tool`)

Run it on all eight pages at 1440, 1024, 900, 768, 600, 599, 430, 390 and 360 px
(`resize_window`). Every value must be `true`.

```js
const all = s => [...document.querySelectorAll(s)];
const shown = s => all(s).filter(e => e.getClientRects().length);
const html = document.documentElement.outerHTML;
const home = !!document.querySelector('.vg-pc #top');
({
  oneCopy: !home || shown('.vg-pc').length + shown('.vg-ph').length === 1,
  rightCopy: !home || (innerWidth < 600 ? shown('.vg-ph').length : shown('.vg-pc').length) === 1,
  noSideScroll: document.documentElement.scrollWidth <= innerWidth,
  noDeadLinks: all('a[href="#"]').length === 0,
  noDesignLeft: !/visionguard\.ai|0000 0000|\.dc\.html|\{\{|<sc-|style-hover|style-focus|support\.js/.test(html),
  realContacts: html.includes('sales@vision-guard.org') && html.includes('tel:+201002535081'),
  langRight: document.documentElement.lang === (location.pathname.includes('/ar/') ? 'ar' : 'en'),
  rtlRight: (document.documentElement.dir === 'rtl') === location.pathname.includes('/ar/'),
  twinLink: all('a').some(a => a.pathname === (location.pathname.includes('/ar/')
      ? location.pathname.replace('/ar/', '/') : location.pathname.replace(/\/([^/]*)$/, '/ar/$1'))),
  soonMarked: all('.soon').every(e => e.tagName === 'SPAN' && e.querySelector('small')),
  headerSticks: shown('header').every(h => getComputedStyle(h).position === 'sticky'),
})
```

Then scroll to the bottom and back. The shown header must still be at the top:
`shown('header')[0].getBoundingClientRect().top === 0`.

Anything that overlaps between 600 and 1079 px gets the smallest fix, in the marked
tablet block in `styles.css` (research R7). Record each fix there with the width it was
seen at.

## 4. Phone behaviour (390 px, both languages)

- **Menu**: tap ☰. The menu slides in, the bars become ×, and `aria-expanded` is `true`.
  Tap "Tools": the menu shuts and the page lands on Tools with its heading visible. Open
  the menu, then widen the window past 600 px: the menu shuts and the PC design shows.
- **Contact bar**: scroll past the hero; the bar slides up. It is gone near Contact and
  while the menu is open.
- **Tools row**: swipe; the dots follow. Tap the third dot; the third card slides in.
  Repeat in Arabic, where the row runs right to left.
- **Footer**: tap "Company"; it opens with a ×. Tap "Trust"; Company shuts and Trust
  opens. About us, Security and Help centre open their pages; the rest show "Soon".
- **Cross-page link**: from `/about.html` at 390 px, tap Contact in the menu. It lands
  on the phone Contact section, not at the top of the page.

## 5. By eye, against the design

Open each design file beside the site at the same width: the PC design at 1440, the
phone design at 390. Compare in both languages. Every section, card, word and animation
must be there, and nothing added beyond data-model §3. Look hardest at:
- the hero phone's tracking box and chat toast;
- the floating cards (PC only, 1080 px and wider);
- the counting numbers;
- the radar;
- the two floating phones in "On your phone";
- the Trust border light;
- the shimmering footer word.

## 6. The forms (both languages, both copies)

- **Validation**: leave Company empty and press Send. The message is in the page's
  language, and no `formsubmit.co` request is made.
- **Failure**: block `formsubmit.co` (or override `fetch` to reject) and press Send.
  The "not sent" block shows, in the page's language, with the email and phone. No
  thank-you. The fields keep their text.
- **Double press**: one request only.
- **Real send, only with Mohamed's OK**: one message from `/ar/` at 390 px, which
  reaches sales@ with every field (SC-006).

## 7. Reduced motion and Firefox

As spec 017 quickstart §5. Reduced motion is checked on the Arabic phone copy too.

## 8. Nothing else moved

```bash
python -m pytest engine
```

Same count as `context.md` §4. `git status` shows only:
- `website/`
- `tools/build_website.mjs`
- `STATUS.md` and `specs/017-public-website/claims.md` (R10)
- this spec folder
- the design folder (only the four `.dc.html` files and `assets/`; see context §3)

## 9. Publish, only after Mohamed has looked

As spec 017 quickstart §7. `Copy-Item website\* $d -Recurse -Force` now also carries
`ar/`, `design-pc.css` and `design-phone.css`. Afterwards, open
https://www.vision-guard.org/ar/ and run §3 once there.
