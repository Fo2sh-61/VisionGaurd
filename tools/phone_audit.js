/* Phone screen audit - paste into the browser's JavaScript console (or the
 * in-app browser's JavaScript tool) on a phone-app page at 360 px wide.
 *
 * Spec 015 (phone-first redesign) measures four things on every screen, and
 * this is the measuring tape so the numbers are the same every time:
 *
 *   overflowX    how far the screen scrolls sideways. Must be 0.
 *   smallTargets controls a finger presses that are under 44 x 44 px.
 *   lowContrast  text under 4.5:1 against what it sits on (3:1 at 24 px+).
 *   tinyText     text under 12 px.
 *
 * `inlineLinks` are links and link-buttons sitting inside a run of text. WCAG
 * exempts those from the size rule, so they are listed apart and judged by eye.
 *
 * Nothing here changes the page. It returns a plain object, and leaves itself
 * behind as `window.__vgAudit()` so the next screen of the same visit can be
 * measured without pasting it again. */
(window.__vgAudit = () => {
  const content = document.querySelector('.app__content') || document.scrollingElement;
  const vw = document.documentElement.clientWidth;

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false;
    return !el.closest('[hidden],[aria-hidden="true"]');
  };

  const label = (el) => {
    const text = (el.getAttribute('aria-label') || el.textContent || el.value || '').trim().replace(/\s+/g, ' ');
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).join('.')}` : '';
    return `${el.tagName.toLowerCase()}${cls} "${text.slice(0, 40)}"`;
  };

  // --- sideways overflow ---------------------------------------------------
  const overflowX = Math.max(0, content.scrollWidth - content.clientWidth,
    document.documentElement.scrollWidth - vw);
  const wide = [];
  for (const el of document.querySelectorAll('.app *')) {
    const r = el.getBoundingClientRect();
    // A strip that scrolls sideways on purpose (chips, other cameras) holds
    // things past the edge by design; the strip itself must still fit.
    if (el.parentElement?.closest('.chips, .hscroll')) continue;
    if (r.width > 0 && (r.right > vw + 1 || r.left < -1) && visible(el)) {
      // Only report the outermost offender, not every child inside it.
      if (!wide.some((w) => w.contains(el))) wide.push(el);
    }
  }

  // --- touch targets -------------------------------------------------------
  const smallTargets = [];
  const inlineLinks = [];
  const targets = document.querySelectorAll(
    'button, a[href], input:not([type=hidden]), select, textarea, [role=switch], [role=button], summary');
  for (const el of targets) {
    if (!visible(el) || el.disabled) continue;
    // A camera tile's picture inside its button is not a second target.
    if (el.closest('.camframe') && el.closest('button') !== el) continue;
    // A native checkbox inside a label: the label is the target.
    const host = (el.matches('input[type=checkbox],input[type=radio]') && el.closest('label')) || el;
    const r = host.getBoundingClientRect();
    if (r.width >= 44 && r.height >= 44) continue;
    const parent = host.parentElement;
    const inText = parent && getComputedStyle(host).display.startsWith('inline')
      && /\S/.test([...parent.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(''));
    (inText ? inlineLinks : smallTargets).push(`${label(host)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }

  // --- contrast and size ---------------------------------------------------
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const [r, g, b, a = '1'] = m[1].split(/[ ,/]+/).filter(Boolean);
    return { r: +r, g: +g, b: +b, a: +a };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const blend = (top, under) => ({
    r: top.r * top.a + under.r * (1 - top.a),
    g: top.g * top.a + under.g * (1 - top.a),
    b: top.b * top.a + under.b * (1 - top.a),
    a: 1,
  });
  const backgroundOf = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const bg = parse(getComputedStyle(n).backgroundColor);
      if (bg && bg.a > 0) {
        layers.push(bg);
        if (bg.a >= 1) break;
      }
    }
    let out = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    if (out.a < 1) out = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of layers.reverse()) out = blend(layer, out);
    return out;
  };
  // Pictures are judged by eye: text over a camera frame or video sits on pixels.
  const overImage = (el) => !!el.closest('.camframe, .frame, video, img, picture, canvas');

  const lowContrast = [];
  const tinyText = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.querySelector('.app') || document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el) || !visible(el)) continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize);
    const text = node.textContent.trim().slice(0, 40);
    if (size < 12) tinyText.push(`${size}px "${text}"`);
    if (overImage(el)) continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    const bg = backgroundOf(el);
    const shown = fg.a < 1 ? blend(fg, bg) : fg;
    const [hi, lo] = [lum(shown), lum(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const bold = Number(cs.fontWeight) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) lowContrast.push(`${ratio.toFixed(2)}:1 < ${need} ${size}px "${text}"`);
  }

  return {
    route: location.pathname + location.search,
    theme: document.body.classList.contains('dark') ? 'dark' : 'light',
    dir: document.documentElement.dir || 'ltr',
    width: vw,
    overflowX,
    wide: wide.slice(0, 10).map(label),
    smallTargets,
    inlineLinks,
    lowContrast,
    tinyText,
  };
})();
