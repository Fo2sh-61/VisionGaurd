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
})();
