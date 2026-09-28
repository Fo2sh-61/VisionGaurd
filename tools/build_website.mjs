// Builds the website from Mohamed's design files (spec 019, contracts/converter.md).
//
//   node tools/build_website.mjs
//
// Reads the four .dc.html designs, writes each one out as plain HTML (loops expanded,
// handlers turned into data-on hooks, hover/focus turned into classes), applies the fixed
// list of site edits (specs/019-website-v3/data-model.md §3) and writes:
//   website/index.html, website/ar/index.html          whole
//   website/design-pc.css, website/design-phone.css    whole
//   the vg:header / vg:footer blocks of the six inner pages
//   website/assets/                                     byte copy
// Anything unexpected stops the build before a single file is written.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DESIGN = join(ROOT, 'design', 'Visionguard website full design');
const SITE = join(ROOT, 'website');

const DESIGNS = [
  { screen: 'pc', lang: 'en', file: 'VisionGuard Website v3.dc.html' },
  { screen: 'pc', lang: 'ar', file: 'VisionGuard Website v3 AR.dc.html' },
  { screen: 'phone', lang: 'en', file: 'VisionGuard Mobile.dc.html' },
  { screen: 'phone', lang: 'ar', file: 'VisionGuard Mobile AR.dc.html' },
];
const INNER = ['about.html', 'security.html', 'help.html'];

// The whole handler vocabulary (contracts/page-hooks.md). A design that uses anything
// else stops the build: main.js would not know what to do with it.
const HANDLERS = new Set(['heroMove', 'toggleMenu', 'closeMenu', 'm.go', 'onToolsScroll', 'd.go', 'c.toggle', 'o.pick', 'submit']);
const REFS = new Set(['typedRef', 'langRef', 'toolsRef']);
const CONDITIONS = new Set(['menuOpen', 'showCta', 'c.open', 'notSent', 'sent']);

// Screen widths. Range syntax, so the two never leave a gap at fractional widths.
const MEDIA = { pc: '(width >= 600px)', phone: '(width < 600px)' };

// What the site says where the design says nothing (data-model §5).
const T = {
  en: {
    title: 'VisionGuard',
    description: 'AI vision for workplaces. Ask your cameras a question — in your own language — and get the answer, with footage when there is some.',
    soon: 'Soon',
    again: 'Send another message',
    notSent: 'Your message was not sent. Please email <a href="mailto:sales@vision-guard.org" style="color:inherit;font-weight:600;text-decoration:underline">sales@vision-guard.org</a> or call <a href="tel:+201002535081" style="color:inherit;font-weight:600;text-decoration:underline">+20 100 253 5081</a>.',
  },
  ar: {
    title: 'VisionGuard',
    description: 'رؤية ذكية لأماكن العمل. اسأل كاميراتك سؤالًا — بلغتك — واحصل على الإجابة، مع المقطع المصوَّر عندما يوجد.',
    soon: 'قريبًا',
    again: 'أرسل رسالة أخرى',
    notSent: 'لم تُرسَل رسالتك. من فضلك راسلنا على <a href="mailto:sales@vision-guard.org" style="color:inherit;font-weight:600;text-decoration:underline"><span dir="ltr">sales@vision-guard.org</span></a> أو اتصل على <a href="tel:+201002535081" style="color:inherit;font-weight:600;text-decoration:underline"><span dir="ltr">+20 100 253 5081</span></a>.',
  },
};

// Footer items that now have a page (E5), by the label each design gives them.
const PAGES = {
  en: { 'About us': 'about.html', 'Security': 'security.html', 'Help centre': 'help.html' },
  ar: { 'من نحن': 'about.html', 'الأمان': 'security.html', 'مركز المساعدة': 'help.html' },
};

// The contact form's fields, in the order the design lays them out (E12).
const FIELDS = ['name', 'email', 'company', 'phone', 'site_type', 'message'];

// ---------------------------------------------------------------------------------------
// Stopping: nothing is written until every check has passed.

function fail(file, what, found = '') {
  console.error(`build_website: stopped — ${file}: ${what}${found ? `\n  found: ${found}` : ''}`);
  console.error('Nothing was written.');
  process.exit(1);
}

function count(s, needle) {
  let n = 0, i = 0;
  while ((i = s.indexOf(needle, i)) !== -1) { n++; i += needle.length; }
  return n;
}

// Replace `find` with `replace`, checking the number of matches against `rule`:
// a number (exactly that many) or '>=1' / '>=0'.
function edit(file, id, s, find, replace, rule = 1) {
  const n = typeof find === 'string' ? count(s, find) : (s.match(new RegExp(find.source, find.flags.includes('g') ? find.flags : find.flags + 'g')) || []).length;
  const ok = typeof rule === 'number' ? n === rule : n >= Number(rule.slice(2));
  if (!ok) fail(file, `site edit ${id} expected ${rule} match(es) of ${JSON.stringify(String(find))}`, `${n}`);
  if (typeof find === 'string') return s.split(find).join(typeof replace === 'function' ? replace(find) : replace);
  return s.replace(new RegExp(find.source, find.flags.includes('g') ? find.flags : find.flags + 'g'), replace);
}

const esc = v => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const unesc = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const textOf = html => unesc(html.replace(/<[^>]*>/g, '')).replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------------------------------
// T003 — read a design: its style, its markup and its script's values.

function readDesign(d) {
  const path = join(DESIGN, d.file);
  if (!existsSync(path)) fail(d.file, 'design file not found');
  const src = readFileSync(path, 'utf8').replace(/\r\n/g, '\n');
  const helmet = src.match(/<helmet>([\s\S]*?)<\/helmet>/);
  if (!helmet) fail(d.file, 'no <helmet>');
  const style = helmet[1].match(/<style>([\s\S]*?)<\/style>/);
  const fonts = helmet[1].match(/<link rel="stylesheet" href="(https:\/\/fonts\.googleapis\.com[^"]*)">/);
  if (!style || !fonts) fail(d.file, 'no <style> or font link in <helmet>');
  const markup = src.slice(src.indexOf('</helmet>') + 9, src.indexOf('</x-dc>')).trim();
  if (!markup.startsWith('<div') || !markup.endsWith('</div>')) fail(d.file, 'the page is not one outer <div>');
  const cls = src.match(/class Component extends DCLogic \{[\s\S]*\n\}/);
  if (!cls) fail(d.file, 'no class Component');

  // The design's own script, with the two things it expects from its runtime stubbed out.
  // Only renderVals() is called; none of its functions ever run.
  class DCLogic { constructor() { this.props = {}; } setState() {} }
  const React = { createRef: () => ({ current: null }) };
  let vals, qs;
  try {
    const Component = new Function('DCLogic', 'React', `${cls[0]}\nreturn Component;`)(DCLogic, React);
    const c = new Component();
    vals = c.renderVals();
    qs = c.qs;
  } catch (err) {
    fail(d.file, 'its script did not run', err.message);
  }
  if (!Array.isArray(qs)) fail(d.file, 'no qs list of example questions');
  return { ...d, style: unesc(style[1]).trim(), fonts: fonts[1], markup, vals, qs };
}

// ---------------------------------------------------------------------------------------
// T004/T005 — write out the template: loops, conditions, values and hooks.

function lookup(file, path, scope, vals) {
  const [head, ...rest] = path.split('.');
  let v = head in scope ? scope[head].value : vals[head];
  for (const k of rest) v = v == null ? undefined : v[k];
  if (v === undefined) fail(file, `{{ ${path} }} has no value`);
  return v;
}

// The block (sc-for / sc-if) starting at `at`, with its matching close.
function block(file, s, at, tag) {
  const open = new RegExp(`<${tag}\\b|</${tag}>`, 'g');
  open.lastIndex = at;
  let depth = 0, m;
  while ((m = open.exec(s))) {
    depth += m[0].startsWith('</') ? -1 : 1;
    if (depth === 0) {
      const headEnd = s.indexOf('>', at) + 1;
      return { head: s.slice(at, headEnd), body: s.slice(headEnd, m.index), end: m.index + m[0].length };
    }
  }
  fail(file, `<${tag}> is not closed`);
}

// Which loop an expression belongs to, for data-i.
const loopIndex = (path, scope) => {
  const head = path.split('.')[0];
  return head in scope ? scope[head].index : undefined;
};

function render(d, tpl, scope = {}) {
  let out = '', i = 0;
  for (;;) {
    const next = tpl.slice(i).search(/<sc-(for|if)\b/);
    if (next === -1) { out += fill(d, tpl.slice(i), scope); break; }
    out += fill(d, tpl.slice(i, i + next), scope);
    const at = i + next, tag = tpl.startsWith('<sc-for', at) ? 'sc-for' : 'sc-if';
    const b = block(d.file, tpl, at, tag);
    if (tag === 'sc-for') {
      const list = b.head.match(/list="\{\{ ([\w.]+) \}\}"/), as = b.head.match(/\bas="(\w+)"/);
      if (!list || !as) fail(d.file, 'an sc-for without list/as', b.head);
      const items = lookup(d.file, list[1], scope, d.vals);
      if (!Array.isArray(items)) fail(d.file, `{{ ${list[1]} }} is not a list`);
      items.forEach((item, index) => { out += render(d, b.body, { ...scope, [as[1]]: { value: item, index } }); });
    } else {
      const cond = b.head.match(/value="\{\{ ([\w.]+) \}\}"/);
      if (!cond) fail(d.file, 'an sc-if without value', b.head);
      const name = cond[1];
      if (!CONDITIONS.has(name)) fail(d.file, `new condition in the design: "${name}". Add it to main.js and contracts/page-hooks.md`);
      const on = lookup(d.file, name, scope, d.vals);
      const idx = loopIndex(name, scope);
      out += `<div data-if="${name}"${idx === undefined ? '' : ` data-i="${idx}"`} style="display:contents"${on ? '' : ' hidden'}>`
        + render(d, b.body, scope) + '</div>';
    }
    i = b.end;
  }
  return out;
}

// Values and hooks in a stretch of markup with no blocks left in it.
function fill(d, s, scope) {
  s = s.replace(/\s+hint-[\w-]+="[^"]*"/g, '');
  s = s.replace(/\son([A-Z]\w*)="\{\{ ([\w.]+) \}\}"/g, (_, ev, path) => {
    if (!HANDLERS.has(path)) fail(d.file, `new interaction in the design: "${path}". Add it to main.js and contracts/page-hooks.md`);
    const idx = loopIndex(path, scope);
    return ` data-on="${ev.toLowerCase()}:${path}"${idx === undefined ? '' : ` data-i="${idx}"`}`;
  });
  s = s.replace(/\sref="\{\{ (\w+) \}\}"/g, (_, name) => {
    if (!REFS.has(name)) fail(d.file, `new ref in the design: "${name}". Add it to main.js and contracts/page-hooks.md`);
    return ` data-ref="${name}"` + (name === 'typedRef' ? ` data-qs="${esc(JSON.stringify(d.qs))}"` : '');
  });
  return s.replace(/\{\{\s*([^}]*?)\s*\}\}/g, (_, expr) => {
    if (!/^[\w.]+$/.test(expr)) fail(d.file, `{{ ${expr} }} is not a plain value`);
    const v = lookup(d.file, expr, scope, d.vals);
    if (typeof v === 'function' || (typeof v === 'object' && v !== null)) fail(d.file, `{{ ${expr} }} is not text`);
    return esc(v);
  });
}

// ---------------------------------------------------------------------------------------
// T006 — style-hover / style-focus become classes. An inline style beats any class, so
// every declaration is marked !important.

function hoverClasses(d, html, rules) {
  const tag = d.screen === 'pc' ? 'p' : 'm';
  return html.replace(/<[a-zA-Z][^>]*\sstyle-(?:hover|focus)="[^"]*"[^>]*>/g, el => {
    const add = [];
    el = el.replace(/\sstyle-(hover|focus)="([^"]*)"/g, (_, kind, css) => {
      const key = `${kind}|${css}`;
      if (!rules.has(key)) rules.set(key, `${kind === 'hover' ? 'h' : 'f'}${tag}${[...rules.keys()].filter(k => k.startsWith(kind)).length + 1}`);
      add.push(rules.get(key));
      return '';
    });
    const cls = add.join(' ');
    return /\sclass="/.test(el) ? el.replace(/\sclass="([^"]*)"/, ` class="$1 ${cls}"`) : el.replace(/\s*(\/?)>$/, ` class="${cls}"$1>`);
  });
}

function hoverCss(rules) {
  return [...rules].map(([key, name]) => {
    const [kind, css] = key.split(/\|(.*)/s);
    const body = css.split(';').map(x => x.trim()).filter(Boolean).map(x => `${x}!important`).join(';');
    return `.${name}:${kind}{${body}}`;
  }).join('\n');
}

// ---------------------------------------------------------------------------------------
// T007 — the site edits (data-model §3). Each names how often it must match.

function siteEdits(d, html, where) {
  const f = `${d.file} (${where})`;
  const t = T[d.lang];

  // E1–E3: the real contact details instead of the design's placeholders.
  html = edit(f, 'E1', html, 'sales@visionguard.ai', 'sales@vision-guard.org', '>=1');
  html = edit(f, 'E2', html, 'tel:+20200000000', 'tel:+201002535081', '>=1');
  html = edit(f, 'E3', html, '+20 2 0000 0000', '+20 100 253 5081', '>=0');

  // E4: the WhatsApp card opens a chat.
  let wa = 0;
  html = html.replace(/<a href="#"([^>]*)>([\s\S]*?)<\/a>/g, (all, attrs, inner) => {
    if (!/WhatsApp|واتساب/.test(textOf(inner))) return all;
    wa++;
    return `<a href="https://wa.me/201002535081" target="_blank" rel="noopener"${attrs}>${inner}</a>`;
  });
  if (wa !== 1) fail(f, 'site edit E4 expected 1 WhatsApp card', `${wa}`);

  // E5: footer items that now have a page. E6: everything else with nowhere to go is
  // marked Soon and stops being a link.
  const seen = {};
  html = html.replace(/<a href="#"([^>]*)>([\s\S]*?)<\/a>/g, (all, attrs, inner) => {
    const label = textOf(inner);
    const page = PAGES[d.lang][label];
    if (page) { seen[label] = (seen[label] || 0) + 1; return `<a href="${page}"${attrs}>${inner}</a>`; }
    attrs = attrs.replace(/\sclass="[^"]*"/, '');
    return `<span class="soon" aria-disabled="true"${attrs}>${inner} <small>${t.soon}</small></span>`;
  });
  for (const label of Object.keys(PAGES[d.lang])) {
    if (seen[label] !== 1) fail(f, `site edit E5 expected 1 footer link "${label}"`, `${seen[label] || 0}`);
  }

  // E7: the language switch goes to the twin page (the page's own path is filled in later).
  html = edit(f, 'E7', html, /href="VisionGuard%20(?:Website%20v3|Mobile)(?:%20AR)?\.dc\.html"/, 'href="{{TWIN}}"', '>=1');

  // E16: Arabic pages sit one folder down.
  if (d.lang === 'ar') html = edit(f, 'E16', html, '"./assets/', '"../assets/', '>=0');
  return html;
}

// E8–E10: the outer wrapper keeps the sticky header sticky; the phone design fills the
// screen instead of sitting in a 430 px frame.
function wrapperEdits(d, html) {
  const f = d.file;
  const end = html.indexOf('>') + 1;
  let open = html.slice(0, end);
  open = edit(f, 'E8', open, 'overflow-x:hidden', 'overflow-x:clip', 1);
  if (d.screen === 'phone') {
    open = edit(f, 'E9', open, 'max-width:430px;margin:0 auto;', '', 1);
    open = edit(f, 'E9', open, /;box-shadow:[^;"]*/, '', 1);
  }
  open = open.replace(/^<div/, `<div class="${d.screen === 'pc' ? 'vg-pc' : 'vg-ph'}"`);
  html = open + html.slice(end);
  if (d.screen === 'phone') html = edit(f, 'E10', html, 'width:100%;max-width:430px;', 'width:100%;', 1);
  return html;
}

// E17: a box with overflow:hidden is a scroll container, and every view() timeline inside
// it measures against that box, which never scrolls — so the counting numbers, reveals,
// phone drift and card lines inside it sit frozen at their end state (found live, 28 Sep:
// 23 of 45 scroll effects on the PC page). overflow:clip clips the same way without being
// a scroll container; the spec 017 site used it on the stats strip for this reason.
const SCROLL_HOOK = /\sdata-(?:reveal|count|line|tilt|par)="/;
function clipNotHide(d, html) {
  const edits = [];
  for (const m of html.matchAll(/<([a-zA-Z][\w-]*)\b[^>]*\sstyle="[^"]*overflow(?:-[xy])?:\s*hidden[^"]*"[^>]*>/g)) {
    const b = block(d.file, html, m.index, m[1]);
    if (!SCROLL_HOOK.test(b.body)) continue;
    edits.push([m.index, m[0], m[0].replace(/(overflow(?:-[xy])?):\s*hidden/g, '$1:clip')]);
  }
  for (const [at, from, to] of edits.reverse()) html = html.slice(0, at) + to + html.slice(at + from.length);
  return { html, count: edits.length };
}

// E11: the phone copy's ids get an m- prefix so each id is in the page once.
function prefixIds(d, html) {
  const ids = [...html.matchAll(/\sid="([\w-]+)"/g)].map(m => m[1]);
  if (!ids.length) fail(d.file, 'site edit E11 found no ids');
  for (const id of ids) {
    html = edit(d.file, 'E11', html, ` id="${id}"`, ` id="m-${id}"`, 1);
    html = edit(d.file, 'E11', html, `href="#${id}"`, `href="#m-${id}"`, '>=0');
  }
  return html;
}

// E12–E15: the design's form gets what makes it send (spec 017's contract).
function formEdits(d, html) {
  const t = T[d.lang];
  let forms = 0;
  html = html.replace(/<form\b([^>]*)>([\s\S]*?)<\/form>/g, (all, attrs, body) => {
    forms++;
    if (!attrs.includes('data-on="submit:submit"')) fail(d.file, 'a form without the design\'s submit handler');
    let i = 0;
    body = body.replace(/<(input|select|textarea)\b/g, m => {
      if (i >= FIELDS.length) { i++; return m; }
      return `${m} name="${FIELDS[i++]}"`;
    });
    if (i !== FIELDS.length) fail(d.file, `site edit E12 expected ${FIELDS.length} form fields`, `${i}`);
    const honey = '\n          <input type="text" name="_honey" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px">';
    const submit = body.match(/<button type="submit"[\s\S]*?<\/button>/);
    if (!submit) fail(d.file, 'site edit E13 found no submit button');
    const labelled = submit[0].replace(/<span style="position:relative">/, '<span data-label style="position:relative">');
    if (labelled === submit[0]) fail(d.file, 'site edit E13 found no label inside the submit button');
    const failed = `\n          <div data-failed hidden role="alert" style="font-size:14px;color:#a5372c;line-height:1.5">${t.notSent}</div>`;
    body = body.replace(submit[0], labelled + failed);
    return `<form action="https://formsubmit.co/sales@vision-guard.org" method="POST"${attrs}>${honey}${body}</form>`;
  });
  if (forms !== 1) fail(d.file, 'expected one contact form', `${forms}`);

  // E14: after a confirmed send, the visitor can send another.
  const again = `<button type="button" data-again class="vg-again" style="margin-top:6px;background:transparent;color:#1f2b26;padding:13px 20px;border-radius:12px;font:inherit;font-weight:600;font-size:16px;border:1px solid #c3ccc4;cursor:pointer;transition:background .2s">${t.again}</button>`;
  const at = html.indexOf('<div data-if="sent"');
  if (at === -1 || html.indexOf('<div data-if="sent"', at + 1) !== -1) fail(d.file, 'site edit E14 expected one thank-you block');
  // The wrapper holds one <div>; the button goes in just before that div closes.
  const b = block(d.file, html, at, 'div');
  const inner = b.body.trimEnd();
  if (!inner.endsWith('</div>')) fail(d.file, 'site edit E14: the thank-you block has an unexpected shape');
  const body = inner.slice(0, -6) + `  ${again}\n        </div>` + b.body.slice(inner.length);
  return html.slice(0, at) + b.head + body + '</div>' + html.slice(b.end);
}

// ---------------------------------------------------------------------------------------
// Everything the output must no longer contain (data-model §3).

const FORBIDDEN = ['visionguard.ai', '0000 0000', '.dc.html', 'href="#"', '{{', '<sc-', 'style-hover', 'style-focus', 'support.js'];
function guard(file, html) {
  for (const bad of FORBIDDEN) {
    const at = html.indexOf(bad);
    if (at !== -1) fail(file, `the output still contains "${bad}"`, html.slice(Math.max(0, at - 80), at + 80).replace(/\s+/g, ' '));
  }
  const on = html.match(/<[^>]*\son[A-Z]\w*=[^>]*>/);
  if (on) fail(file, 'the output still has a design handler', on[0].slice(0, 160));
}

// ---------------------------------------------------------------------------------------
// T008 — build the copies, the pages and the stylesheets.

const designs = DESIGNS.map(readDesign);
const rules = { pc: new Map(), phone: new Map() };
const copy = {};
const clips = [];
for (const d of designs) {
  let html = render(d, d.markup);
  html = hoverClasses(d, html, rules[d.screen]);
  html = wrapperEdits(d, html);
  const clipped = clipNotHide(d, html);
  html = clipped.html;
  clips.push(`${d.screen}-${d.lang} ${clipped.count}`);
  html = siteEdits(d, html, 'page');
  html = formEdits(d, html);
  if (d.screen === 'phone') html = prefixIds(d, html);
  copy[`${d.screen}-${d.lang}`] = html;
}

// The design's CSS for each screen: the English design's, plus what only the Arabic adds.
function screenCss(screen) {
  const en = designs.find(d => d.screen === screen && d.lang === 'en').style.split('\n');
  const ar = designs.find(d => d.screen === screen && d.lang === 'ar').style.split('\n');
  const have = new Set(en.map(l => l.trim()));
  const extra = ar.filter(l => !have.has(l.trim()));
  return `/* Generated by tools/build_website.mjs from the ${screen === 'pc' ? 'Website v3' : 'Mobile'} designs. Do not edit.\n`
    + `   Loaded only at ${MEDIA[screen]}. */\n`
    + en.join('\n') + '\n'
    + (extra.length ? `/* Arabic design only */\n${extra.join('\n')}\n` : '')
    + `/* style-hover / style-focus */\n${hoverCss(rules[screen])}\n`;
}

function shell(lang, body) {
  const t = T[lang], up = lang === 'ar' ? '../' : '';
  const fonts = designs.find(d => d.lang === lang && d.screen === 'pc').fonts;
  return `<!DOCTYPE html>
<!-- Generated by tools/build_website.mjs from "design/Visionguard website full design". Do not edit: change the design or the converter, then rebuild. -->
<html lang="${lang}"${lang === 'ar' ? ' dir="rtl"' : ''}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${t.title}</title>
<meta name="description" content="${esc(t.description)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="${fonts}">
<link rel="icon" href="${up}assets/visionguard.ico">
<link rel="stylesheet" href="${up}design-pc.css" media="${MEDIA.pc}">
<link rel="stylesheet" href="${up}design-phone.css" media="${MEDIA.phone}">
<link rel="stylesheet" href="${up}styles.css">
<script src="${up}main.js" defer></script>
</head>
<body>
${body}
</body>
</html>
`;
}

// The twin of a page in the other language.
const twin = (lang, page) => lang === 'en' ? `ar/${page === 'index.html' ? '' : page}` : `../${page === 'index.html' ? '' : page}`;

const out = new Map();
for (const lang of ['en', 'ar']) {
  const body = `${copy[`pc-${lang}`]}\n\n${copy[`phone-${lang}`]}`.split('{{TWIN}}').join(twin(lang, 'index.html'));
  const file = join(SITE, lang === 'ar' ? 'ar' : '', 'index.html');
  const html = shell(lang, body);
  guard(file, html);
  out.set(file, html);
}
out.set(join(SITE, 'design-pc.css'), screenCss('pc'));
out.set(join(SITE, 'design-phone.css'), screenCss('phone'));

// Inner pages: the header and footer of both copies, stamped between the markers.
function chrome(lang, page) {
  const pick = (html, tag) => {
    const at = html.indexOf(`<${tag}`);
    if (at === -1) fail(`${lang} design`, `no <${tag}> to stamp into ${page}`);
    return block(`${lang} design`, html, at, tag);
  };
  const piece = (screen, tag) => {
    const html = copy[`${screen}-${lang}`];
    const b = pick(html, tag);
    let s = html.slice(html.indexOf(`<${tag}`, 0), b.end);
    s = s.replace(new RegExp(`^<${tag}`), `<${tag} class="${screen === 'pc' ? 'vg-pc' : 'vg-ph'}"`);
    return s;
  };
  let s = {
    header: `${piece('pc', 'header')}\n${piece('phone', 'header')}`,
    footer: `${piece('pc', 'footer')}\n${piece('phone', 'footer')}`,
  };
  for (const k of Object.keys(s)) {
    s[k] = s[k]
      .replace(/href="#(m-)?top"/g, 'href="./"')
      .replace(/href="#([\w-]+)"/g, 'href="./#$1"')
      .split('{{TWIN}}').join(twin(lang, page));
  }
  return s;
}

for (const lang of ['en', 'ar']) {
  for (const page of INNER) {
    const file = join(SITE, lang === 'ar' ? 'ar' : '', page);
    if (!existsSync(file)) { console.log(`skip   ${file} (not written yet)`); continue; }
    let html = readFileSync(file, 'utf8');
    const s = chrome(lang, page);
    for (const k of ['header', 'footer']) {
      const re = new RegExp(`<!-- vg:${k} -->[\\s\\S]*?<!-- /vg:${k} -->`);
      if (!re.test(html)) fail(file, `no <!-- vg:${k} --> … <!-- /vg:${k} --> markers`);
      html = html.replace(re, () => `<!-- vg:${k} -->\n${s[k]}\n<!-- /vg:${k} -->`);
    }
    guard(file, html);
    out.set(file, html);
  }
}

// ---------------------------------------------------------------------------------------
// Write only what changed, now that every check has passed.

let written = 0;
for (const [file, content] of out) {
  if (existsSync(file) && readFileSync(file, 'utf8') === content) continue;
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, content);
  console.log(`wrote  ${file.slice(ROOT.length + 1)}`);
  written++;
}
for (const asset of ['mobile-2.png', 'visionguard.ico']) {
  const from = readFileSync(join(DESIGN, 'assets', asset));
  const to = join(SITE, 'assets', asset);
  if (existsSync(to) && readFileSync(to).equals(from)) continue;
  mkdirSync(dirname(to), { recursive: true });
  writeFileSync(to, from);
  console.log(`copied website/assets/${asset}`);
  written++;
}
console.log(`hover/focus classes: pc ${rules.pc.size}, phone ${rules.phone.size}. overflow:hidden → clip (E17): ${clips.join(', ')}. ${written ? `${written} file(s) changed.` : 'Nothing changed.'}`);
