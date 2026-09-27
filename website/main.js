// VisionGuard website. The pages are generated from the design by tools/build_website.mjs;
// this script acts on the design's own handler names (specs/019-website-v3/contracts/
// page-hooks.md). No framework, no globals.
(() => {
  'use strict';

  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const phone = matchMedia('(width < 600px)');
  const lang = document.documentElement.lang === 'ar' ? 'ar' : 'en';

  // Every text the site shows by itself, in the page's language (data-model §5).
  const TEXT = {
    en: {
      sending: 'Sending…',
      required: 'Please fill in this field.',
      email: 'Please enter an email address, like name@company.com.',
    },
    ar: {
      sending: 'جارٍ الإرسال…',
      required: 'من فضلك املأ هذا الحقل.',
      email: 'من فضلك اكتب بريدًا إلكترونيًا صحيحًا، مثل name@company.com.',
    },
  }[lang];

  // Every element carrying the design's handler `name`, in every copy of the page.
  const on = name => [...document.querySelectorAll(`[data-on$=":${name}"]`)];
  const shown = el => !!el && el.getClientRects().length > 0;

  // ---- Hero question box: types and erases the design's example questions (design: startTyping)
  function startTyping(typed, tag, qs) {
    let qi = 0, ci = 0, del = false;
    const tick = () => {
      const [q, l] = qs[qi];
      typed.parentNode.dir = /[؀-ۿ]/.test(q) ? 'rtl' : 'ltr';
      if (tag && tag.textContent !== l) tag.textContent = l;
      if (!del) { ci++; if (ci > q.length) { del = true; setTimeout(tick, 1800); return; } }
      else { ci--; if (ci === 0) { del = false; qi = (qi + 1) % qs.length; } }
      typed.textContent = q.slice(0, ci);
      setTimeout(tick, del ? 22 : 55);
    };
    tick();
  }

  document.querySelectorAll('[data-ref="typedRef"]').forEach(typed => {
    let qs;
    try { qs = JSON.parse(typed.dataset.qs); } catch { return; }
    if (!qs.length) return;
    const copy = typed.closest('.vg-pc,.vg-ph') || document;
    const tag = copy.querySelector('[data-ref="langRef"]');
    if (reduced) { // nothing moves: the first question shows, still
      typed.textContent = qs[0][0];
      typed.parentNode.dir = /[؀-ۿ]/.test(qs[0][0]) ? 'rtl' : 'ltr';
      if (tag) tag.textContent = qs[0][1];
    } else startTyping(typed, tag, qs);
  });

  // ---- Hero glow follows the mouse (design: heroMove)
  if (!reduced) on('heroMove').forEach(hero => hero.addEventListener('mousemove', e => {
    const r = hero.getBoundingClientRect();
    hero.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    hero.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }));

  // ---- Phone menu (design: toggleMenu, closeMenu, m.go). The three bars become a cross
  // with the design's own transforms.
  let menuOpen = false;
  const menuButtons = on('toggleMenu');
  function setMenu(open) {
    menuOpen = open;
    document.querySelectorAll('[data-if="menuOpen"]').forEach(w => { w.hidden = !open; });
    menuButtons.forEach(b => {
      const [b1, b2, b3] = b.children;
      if (b1) b1.style.transform = open ? 'translateY(7px) rotate(45deg)' : 'none';
      if (b2) b2.style.opacity = open ? '0' : '1';
      if (b3) b3.style.transform = open ? 'translateY(-7px) rotate(-45deg)' : 'none';
      b.setAttribute('aria-expanded', String(open));
    });
    queueCta();
  }
  menuButtons.forEach(b => {
    b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', () => setMenu(!menuOpen));
  });
  [...on('closeMenu'), ...on('m.go')].forEach(a => a.addEventListener('click', () => setMenu(false)));
  addEventListener('keydown', e => { if (e.key === 'Escape' && menuOpen) setMenu(false); });
  // The phone design is gone past 600 px, so its menu shuts with it (spec edge case).
  phone.addEventListener('change', () => { if (!phone.matches && menuOpen) setMenu(false); });

  // ---- The phone's slide-up "Contact us" bar (design: showCta). Shown past 560 px of
  // scroll, but not near Contact and not while the menu is open.
  const cta = document.querySelector('[data-if="showCta"]');
  let ctaQueued = false;
  function updateCta() {
    ctaQueued = false;
    if (!cta) return;
    const contact = document.getElementById('m-contact');
    const nearContact = contact && contact.getBoundingClientRect().top < innerHeight * 0.9;
    cta.hidden = !(scrollY > 560 && !nearContact && !menuOpen);
  }
  function queueCta() { if (cta && !ctaQueued) { ctaQueued = true; requestAnimationFrame(updateCta); } }
  if (cta) { addEventListener('scroll', queueCta, { passive: true }); addEventListener('resize', queueCta); updateCta(); }

  // ---- The phone's Tools row (design: onToolsScroll, d.go). The dots follow the swipe; a
  // tapped dot brings its card in. In Arabic the row scrolls right to left, where
  // scrollLeft counts down from 0, hence abs() and scrollIntoView.
  const row = document.querySelector('[data-ref="toolsRef"]');
  const dots = on('d.go');
  if (row && dots.length) {
    const paint = active => dots.forEach((d, i) => {
      d.style.width = i === active ? '24px' : '8px';
      d.style.background = i === active ? '#33705b' : '#c3cfc6';
      d.setAttribute('aria-current', String(i === active));
    });
    let current = 0;
    row.addEventListener('scroll', () => {
      const w = row.children[0] ? row.children[0].offsetWidth + 12 : 1;
      const i = Math.min(dots.length - 1, Math.round(Math.abs(row.scrollLeft) / w));
      if (i !== current) { current = i; paint(i); }
    }, { passive: true });
    dots.forEach(d => d.addEventListener('click', () => {
      const card = row.children[Number(d.dataset.i)];
      if (card) card.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', inline: 'start', block: 'nearest' });
    }));
  }

  // ---- The phone footer's folds (design: c.toggle): one open at a time, "+" turns to "×".
  on('c.toggle').forEach(btn => btn.addEventListener('click', () => {
    const footer = btn.closest('footer') || document;
    const i = btn.dataset.i;
    const opening = !!footer.querySelector(`[data-if="c.open"][data-i="${i}"][hidden]`);
    footer.querySelectorAll('[data-on="click:c.toggle"]').forEach(b => {
      const open = opening && b.dataset.i === i;
      const panel = footer.querySelector(`[data-if="c.open"][data-i="${b.dataset.i}"]`);
      if (panel) panel.hidden = !open;
      if (b.lastElementChild) b.lastElementChild.style.transform = open ? 'rotate(45deg)' : 'none';
      b.setAttribute('aria-expanded', String(open));
    });
  }));
  on('c.toggle').forEach(b => b.setAttribute('aria-expanded', 'false'));

  // ---- Section links and the two copies. Each section is in the page twice (the phone
  // copy's ids carry m-). A link from another page may name the copy that is hidden at
  // this width; then the page goes to its twin instead.
  function toTwin() {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    const el = document.getElementById(id);
    if (shown(el)) return;
    const twin = document.getElementById(id.startsWith('m-') ? id.slice(2) : 'm-' + id);
    if (shown(twin)) twin.scrollIntoView({ behavior: 'instant', block: 'start' }); // as the browser's own jump to #id
  }
  addEventListener('hashchange', toTwin);
  if (location.hash) addEventListener('load', toTwin);

  // ---- Forms send through FormSubmit (specs/017-public-website/contracts/contact-form.md):
  // the contact form to sales, the Help centre's question form to support. The thank-you
  // shows only when FormSubmit confirms; anything else says "not sent" and keeps what was
  // typed.
  async function send(to, fields) {
    const abort = new AbortController();
    let timer;
    const late = new Promise((_, reject) => {
      timer = setTimeout(() => { abort.abort(); reject(new Error('no answer within 15 s')); }, 15000);
    });
    try {
      const res = await Promise.race([late, fetch('https://formsubmit.co/ajax/' + to, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(fields),
        signal: abort.signal,
      })]);
      const data = await Promise.race([late, res.json()]);
      if (res.ok && (data.success === 'true' || data.success === true)) return true;
      console.warn('FormSubmit did not accept the message:', data.message);
    } catch (err) {
      console.warn('The message could not be sent:', err);
    } finally {
      clearTimeout(timer);
    }
    return false;
  }

  // The browser's own "fill in this field" bubble speaks the browser's language, not the
  // page's; these make it speak the page's.
  function ownMessages(form) {
    const fields = form.querySelectorAll('input,select,textarea');
    // A message set on an earlier try would keep a now-correct field invalid (autofill
    // does not always fire `input`), so every press of Send starts clean; the browser then
    // checks again and `invalid` sets the message only where it still applies.
    const button = form.querySelector('button[type="submit"]');
    if (button) button.addEventListener('click', () => fields.forEach(el => el.setCustomValidity('')));
    fields.forEach(el => {
      el.addEventListener('invalid', () => {
        el.setCustomValidity('');
        if (el.validity.valueMissing) el.setCustomValidity(TEXT.required);
        else if (el.validity.typeMismatch) el.setCustomValidity(TEXT.email);
      });
      el.addEventListener('input', () => el.setCustomValidity(''));
    });
  }

  // form: the <form>; idle: what hides once sent; sent: the thank-you; fresh: the field
  // that starts empty on "Send another".
  function wire(form, idle, sent, to, fields, fresh) {
    if (!form || !sent) return;
    const failed = form.querySelector('[data-failed]');
    const button = form.querySelector('button[type="submit"]');
    const label = button && button.querySelector('[data-label]');
    if (!failed || !label) return;
    const idleText = label.textContent;
    let sending = false;
    ownMessages(form);
    form.addEventListener('submit', async e => {
      e.preventDefault(); // the browser's own required/email checks have already passed
      if (sending) return;
      const f = form.elements;
      if (f._honey && f._honey.value) { failed.hidden = false; return; } // a bot filled the hidden field

      sending = true;
      failed.hidden = true;
      button.disabled = true;
      label.textContent = TEXT.sending;
      const ok = await send(to, { ...fields(f, form), _replyto: f.email.value, _template: 'table', _honey: '' });
      sending = false;
      if (ok) {
        idle.hidden = true;
        sent.hidden = false;
        return;
      }
      failed.hidden = false; // everything typed stays in the fields
      button.disabled = false;
      label.textContent = idleText;
    });

    // "Send another": the form comes back with who they are still filled in; only the
    // message itself starts empty.
    const again = sent.querySelector('[data-again]');
    if (again) again.addEventListener('click', () => {
      form.elements[fresh].value = '';
      button.disabled = false;
      label.textContent = idleText;
      sent.hidden = true;
      idle.hidden = false;
      form.elements[fresh].focus();
    });
  }

  // Number of cameras: exactly one on, in each form (design: o.pick, camOpts).
  const ON = { background: '#33705b', color: '#fff', borderColor: '#33705b' };
  const OFF = { background: '#fff', color: '#1f2b26', borderColor: '#d5ddd6' };
  document.querySelectorAll('form[data-on="submit:submit"]').forEach(form => {
    const cams = [...form.querySelectorAll('[data-on="click:o.pick"]')];
    cams.forEach(b => {
      b.setAttribute('aria-pressed', String(b.style.background.replace(/\s/g, '') === 'rgb(51,112,91)'));
      b.addEventListener('click', () => cams.forEach(o => {
        Object.assign(o.style, o === b ? ON : OFF);
        o.setAttribute('aria-pressed', String(o === b));
      }));
    });

    const section = form.closest('section') || document;
    wire(form, form.closest('[data-if="notSent"]') || form, section.querySelector('[data-if="sent"]'),
      'sales@vision-guard.org', f => {
        const pressed = cams.find(b => b.getAttribute('aria-pressed') === 'true');
        return {
          name: f.name.value,
          email: f.email.value,
          company: f.company.value,
          phone: f.phone.value,
          site_type: f.site_type.value,
          cameras: pressed ? pressed.textContent.trim() : '',
          message: f.message.value,
          _subject: 'Website enquiry: ' + f.company.value,
        };
      }, 'message');
  });

  const help = document.getElementById('help-form');
  wire(help, help, document.getElementById('help-sent'), 'support@vision-guard.org', f => ({
    name: f.name.value,
    email: f.email.value,
    topic: f.topic.value,
    question: f.question.value,
    _subject: 'Help centre: ' + f.topic.value,
  }), 'question');

  // ---- Scroll animations where the browser has no scroll timelines (Firefox; spec 017 R4).
  // ?motion=fallback forces it, for testing in Chrome. Never under reduced motion, and the
  // hiding class is added here, so if this script fails nothing stays hidden.
  const forced = new URLSearchParams(location.search).get('motion') === 'fallback';
  if (!reduced && (forced || !CSS.supports('animation-timeline: view()')) && 'IntersectionObserver' in window) {
    document.documentElement.classList.add('vg-io');

    const io = new IntersectionObserver(entries => entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add('vg-in'); io.unobserve(en.target); }
    }), { threshold: 0, rootMargin: '0px 0px -12% 0px' });
    document.querySelectorAll('[data-reveal],[data-count],[data-line],[data-tilt]').forEach(el => io.observe(el));

    // The effects tied to the scroll position itself, in every copy of the page.
    const bars = [...document.querySelectorAll('[data-progress]')];
    const navs = [...document.querySelectorAll('[data-nav]')];
    const phones = [...document.querySelectorAll('[data-par]')];
    const drift = { a: [90, -50], b: [160, -90] }; // px, from vg-parA / vg-parB
    let queued = false;
    const update = () => {
      queued = false;
      const max = document.documentElement.scrollHeight - innerHeight;
      const read = max > 0 ? Math.min(1, scrollY / max) : 0;
      bars.forEach(bar => { bar.style.transform = `scaleX(${read})`; });
      const k = Math.min(1, scrollY / 240); // vg-nav: solid with a soft shadow over the first 240 px
      navs.forEach(nav => {
        nav.style.background = `rgba(${Math.round(251 - 9 * k)},${Math.round(252 - 7 * k)},${Math.round(250 - 8 * k)},${(0.8 + 0.14 * k).toFixed(3)})`;
        nav.style.boxShadow = `0 10px 30px rgba(30,42,36,${(0.08 * k).toFixed(3)})`;
      });
      phones.forEach(el => {
        if (!el.offsetParent) return; // in the copy that is hidden at this width
        // 0 as the phone enters at the bottom, 1 as it leaves at the top. Measured from
        // layout (offsetTop), not the moved box, so the drift does not feed on itself.
        const top = el.offsetParent.getBoundingClientRect().top + el.offsetTop;
        const p = Math.min(1, Math.max(0, (innerHeight - top) / (innerHeight + el.offsetHeight)));
        const [from, to] = drift[el.dataset.par] || [0, 0];
        el.style.translate = `0 ${(from + (to - from) * p).toFixed(1)}px`;
      });
    };
    const queue = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
    addEventListener('scroll', queue, { passive: true });
    addEventListener('resize', queue);
    update();
  }

  // ---- Pause decorative infinite loops while their section is off screen (phone perf).
  // Only toggles a class on <section>/header/footer; styles.css decides what it pauses.
  if (!reduced && matchMedia('(max-width:900px)').matches && 'IntersectionObserver' in window) {
    const sio = new IntersectionObserver(entries => entries.forEach(en => {
      en.target.classList.toggle('vg-offscreen', !en.isIntersecting);
    }), { rootMargin: '200px 0px 200px 0px', threshold: 0 });
    document.querySelectorAll('header,section,footer').forEach(el => sio.observe(el));
  }
})();
