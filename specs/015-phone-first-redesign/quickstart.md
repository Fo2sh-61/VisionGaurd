# Quickstart: proving the phone redesign works

## 1. Gates (every commit)

```powershell
cd web;    npx.cmd tsc -b --force; cd ..
cd mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
python tools/check_parity.py --no-fixtures
python -m pyflakes engine/vg engine/tools engine/tests
python -m pytest engine          # baseline 1889 passed, 6 skipped - must not drop
git diff --stat                  # line counts plausible (CRLF trap)
```

Expected: every command exits 0. Parity reports the shared file count, now 28.

## 2. Run the phone against the mock engine

`.claude/launch.json` already has `mock-mobile`: `dev.ps1 up -Mobile -Mock
-AllowSystemPython -DevSign* admin`, with the phone on 5174, signed in as admin.
Start it with `preview_start {name: "mock-mobile"}`. For the guard's view, use
`-DevSign* it`. For live pictures and real boxes, swap `-Mock` for `-Clip`. Load
`http://localhost:5174/` and move by tapping. A deep URL like `/weapons` hits the
proxy and returns JSON (see memory `dev-deep-link-hits-proxy`). To reach a page
directly, run
`history.pushState({}, '', '/weapons'); dispatchEvent(new PopStateEvent('popstate'))`.

## 3. The 360-px audit (every screen, four variants)

`resize_window {width: 360, height: 780}`. Then for each route in
`contracts/phone-screens.md`, in English/light, English/dark, Arabic/light and
Arabic/dark, run `tools/phone_audit.js` through the browser JavaScript tool (paste
its text). It returns:

- `overflowX`: `.app__content.scrollWidth - clientWidth`. **Must be 0.**
- `smallTargets`: every `button, a, input, select, [role=switch], summary` that is
  visible and measures under 44×44. **Must be empty** (inline text links inside
  a sentence are listed separately and judged by eye).
- `lowContrast`: every visible text node whose colour against its first opaque
  background is under 4.5:1 (3:1 at 24 px or larger). **Must be empty.**
- `tinyText`: visible text under 12 px. **Must be empty.**

Record the four numbers per route in `gaps.md`'s appendix. Anything above zero is
fixed or explained there.

## 4. By-eye walk (developer sign-in, clip engine)

1. The top bar shows the logo, "VisionGuard", camera status and bell. Stop the
   engine: within 30 s it says "Engine unreachable", and Home shows no figure.
2. Bell → Alerts: the groups match the console's bell for the same account. The
   marker clears after opening, and the console's bell clears too (same browser).
3. Home figure tiles each open their tool with the same numbers.
4. Cameras → a camera → switch Faces/Counting/Lost bag/Knife: only that
   feature's boxes, and the legend only on Faces. Back returns to Cameras.
5. Knife detection with an entry (clip engine or mock): the clip and both
   decision buttons are on one 360-px screen. Decide; the status updates; the
   entry stays.
6. Attendance: the group chip opens a sheet; Show; the result sits above the
   filters' fold; Export downloads.
7. Arabic: the tabs, back arrow, sheets and top bar mirror.
8. Console at desktop width: the bell, Home and every page look as before.

## 5. Hand to Mohamed

What only a real phone can confirm: holding it one-handed, the notch and home
indicator, the keyboard over forms, and export download on a phone browser.
