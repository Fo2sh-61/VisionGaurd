// VisionGuard website. Ported from the design's Component class; no framework, no globals.
(() => {
  'use strict';

  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- Hero question box: types and erases seven questions (design: startTyping)
  const qs = [['Who was absent today?', 'English'], ['مين غاب النهارده؟', 'العربية'], ['el cafeteria zahma dlw2ty?', 'Franco'], ['حد دخل الـ server room بعد 6؟', 'Mixed'], ['7ad la2a black backpack fel lobby?', 'Franco + English'], ['في حد دخل منطقة ممنوعة النهارده؟', 'العربية'], ['Where did Layla go today?', 'English']];
  const typed = document.getElementById('typed');
  const lang = document.getElementById('lang');

  function startTyping() {
    let qi = 0, ci = 0, del = false;
    const tick = () => {
      const [q, l] = qs[qi];
      typed.parentNode.dir = /[؀-ۿ]/.test(q) ? 'rtl' : 'ltr';
      if (lang.textContent !== l) lang.textContent = l;
      if (!del) { ci++; if (ci > q.length) { del = true; setTimeout(tick, 1800); return; } }
      else { ci--; if (ci === 0) { del = false; qi = (qi + 1) % qs.length; } }
      typed.textContent = q.slice(0, ci);
      setTimeout(tick, del ? 22 : 55);
    };
    tick();
  }

  if (typed && lang) {
    if (reduced) typed.textContent = qs[0][0]; // nothing moves: show the first question, still
    else startTyping();
  }

  // ---- Hero glow follows the mouse (design: heroMove)
  const hero = document.getElementById('top');
  if (hero && !reduced) {
    hero.addEventListener('mousemove', e => {
      const r = hero.getBoundingClientRect();
      hero.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      hero.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
  }

  // ---- Number of cameras: exactly one on (design: camOpts)
  const camButtons = [...document.querySelectorAll('[data-cams]')];
  const ON = { background: '#33705b', color: '#fff', borderColor: '#33705b' };
  const OFF = { background: '#fff', color: '#1f2b26', borderColor: '#d5ddd6' };
  camButtons.forEach(b => b.addEventListener('click', () => {
    camButtons.forEach(o => {
      Object.assign(o.style, o === b ? ON : OFF);
      o.setAttribute('aria-pressed', String(o === b));
    });
  }));

  // ---- Contact form: sends to the sales inbox through FormSubmit (contracts/contact-form.md).
  // The thank-you shows only when FormSubmit confirms; anything else says "not sent".
  const form = document.getElementById('contact-form');
  const sent = document.getElementById('contact-sent');
  const failed = document.getElementById('contact-failed');
  const button = form && form.querySelector('button[type="submit"]');
  const label = document.getElementById('send-label');
  let sending = false;

  async function send(fields) {
    const abort = new AbortController();
    let timer;
    const late = new Promise((_, reject) => {
      timer = setTimeout(() => { abort.abort(); reject(new Error('no answer within 15 s')); }, 15000);
    });
    try {
      const res = await Promise.race([late, fetch('https://formsubmit.co/ajax/sales@vision-guard.org', {
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

  if (form) {
    form.addEventListener('submit', async e => {
      e.preventDefault(); // the browser's own required/email checks have already passed
      if (sending) return;
      const f = form.elements;
      if (f._honey.value) { failed.hidden = false; return; } // a bot filled the hidden field

      sending = true;
      failed.hidden = true;
      button.disabled = true;
      label.textContent = 'Sending…';
      const on = camButtons.find(b => b.getAttribute('aria-pressed') === 'true');
      const ok = await send({
        name: f.name.value,
        email: f.email.value,
        company: f.company.value,
        phone: f.phone.value,
        site_type: f.site_type.value,
        cameras: on ? on.dataset.cams : '',
        message: f.message.value,
        _subject: 'Website enquiry: ' + f.company.value,
        _replyto: f.email.value,
        _template: 'table',
        _honey: '',
      });
      sending = false;
      if (ok) {
        form.hidden = true;
        sent.hidden = false;
        return;
      }
      failed.hidden = false; // everything typed stays in the fields
      button.disabled = false;
      label.textContent = 'Send message';
    });
  }

  // ---- Scroll animations where the browser has no scroll timelines (Firefox; research R4).
  // ?motion=fallback forces it, for testing in Chrome. Never under reduced motion, and the
  // hiding class is added here, so if this script fails nothing stays hidden.
  const forced = new URLSearchParams(location.search).get('motion') === 'fallback';
  if (!reduced && (forced || !CSS.supports('animation-timeline: view()')) && 'IntersectionObserver' in window) {
    document.documentElement.classList.add('vg-io');

    const io = new IntersectionObserver(entries => entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add('vg-in'); io.unobserve(en.target); }
    }), { threshold: 0.15 });
    document.querySelectorAll('[data-reveal],[data-count],[data-line],[data-tilt]').forEach(el => io.observe(el));

    // The three effects tied to the scroll position itself
    const bar = document.querySelector('[data-progress]');
    const nav = document.querySelector('[data-nav]');
    const phones = [...document.querySelectorAll('[data-par]')];
    const drift = { a: [90, -50], b: [160, -90] }; // px, from vg-parA / vg-parB
    let queued = false;
    const update = () => {
      queued = false;
      const max = document.documentElement.scrollHeight - innerHeight;
      if (bar) bar.style.transform = `scaleX(${max > 0 ? Math.min(1, scrollY / max) : 0})`;
      if (nav) { // vg-nav: solid with a soft shadow over the first 240 px
        const k = Math.min(1, scrollY / 240);
        nav.style.background = `rgba(242,245,242,${(0.78 + 0.16 * k).toFixed(3)})`;
        nav.style.boxShadow = `0 10px 30px rgba(30,42,36,${(0.08 * k).toFixed(3)})`;
      }
      phones.forEach(el => {
        // 0 as the phone enters at the bottom, 1 as it leaves at the top. Measured from
        // layout (offsetTop), not the moved box, so the drift does not feed on itself.
        const top = el.offsetParent.getBoundingClientRect().top + el.offsetTop;
        const p = Math.min(1, Math.max(0, (innerHeight - top) / (innerHeight + el.offsetHeight)));
        const [from, to] = drift[el.dataset.par];
        el.style.translate = `0 ${(from + (to - from) * p).toFixed(1)}px`;
      });
    };
    const queue = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
    addEventListener('scroll', queue, { passive: true });
    addEventListener('resize', queue);
    update();
  }
})();
