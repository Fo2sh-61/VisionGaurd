# Quickstart: proving the phone looks like the console, fits one hand, and keeps in step

The checks that prove the spec, in the order to run them. Each names the success
criterion it proves. The shapes are in `data-model.md` and the rules are in
`contracts/`; this file only runs them.

---

## 0. Before starting

Four other jobs must have landed on `Fo2sh` first (research R14):

| Job | Why it comes first |
|---|---|
| System Health brought level with the console | it edits `SystemHealth.tsx`, `format.ts`, `i18n` and `check_parity.py` |
| The console's "Campus is calm" line fixed | it edits `i18n` |
| Undefined colour tokens fixed | it edits `Attendance.tsx` and `CameraSources.tsx` |
| Developer sign-in merged, phone included | the by-eye checks below need it |

Check with:

```powershell
git log --oneline -15 Fo2sh
```

Look for all four. If the developer sign-in has not merged, sections 3–7 are
Mohamed's to run.

**Before the first change, take the console "before" screenshots (§8).** They
cannot be taken afterwards.

## 1. The automated gates (P13-FR-039, SC-007)

```powershell
python tools/check_parity.py                  # "parity: 55 files identical in web/ and mobile/."
python tools/check_parity.py --no-fixtures    # "fixtures: none."
python -m pytest engine                       # green; count ≥ 1,564 collected + this feature's test
python -m pyflakes engine/vg engine/tools engine/tests
cd web;    npx tsc -b --force;  npm run check:format;  cd ..
cd mobile; npx tsc -b --force;  cd ..
```

Expected:
- All exit 0.
- `check:format` includes the four camera-status cases: checking, all up, some up,
  unreachable.
- Never use `tsc --noEmit`: project references make it a silent no-op.

**SC-007 by hand, once:**
1. Append a space to the end of `mobile/src/pages/Weapons.tsx`.
2. Run `python tools/check_parity.py`. It must exit 1 and name `pages/Weapons.tsx`.
3. Restore the file with `git checkout -- mobile/src/pages/Weapons.tsx`.

The pytest does the same thing on every run.

## 2. Start it

```powershell
.\dev.ps1 up -Mock -Mobile -AllowSystemPython -DevSign* admin
```

- The console runs on 5173 and the phone on 5174, both against the mock engine,
  both signed in as "Developer".
- In the in-app browser, set the viewport to **360 × 780** and open
  `http://localhost:5174/`.
- **Load `/` and click through.** A page URL typed in dev returns the engine's
  JSON, because the proxy owns those paths. That is not a broken page.

## 3. Every screen at 360 px (SC-001, SC-003)

Walk all 18 screens:
- Ask (Home) · Tools · Attendance · Counting · Lost items · Track · Intrusion ·
  Knife alerts · Vehicles
- People · a person's history · a group · Enrol
- System · Account · Settings · Accounts
- Sign-in (signed out)

On each, run both snippets in the browser's JavaScript tool. **Both must return
`[]`.**

**Sideways overflow.** Anything reaching past the screen's edges:

```js
(() => { const w = document.documentElement.clientWidth;
  return [...document.querySelectorAll('body *')]
    .filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.right > w + 0.5 || r.left < -0.5); })
    .slice(0, 20)
    .map(e => `${e.tagName.toLowerCase()}.${[...e.classList].join('.')} → ${Math.round(e.getBoundingClientRect().right)}px`); })()
```

**Small tap targets.** Anything pressable under 44 × 44 px:

```js
(() => [...document.querySelectorAll('body :is(button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=switch])')]
  .filter(e => e.offsetParent !== null)
  .map(e => [e, e.getBoundingClientRect()])
  .filter(([, r]) => r.width < 44 || r.height < 44)
  .map(([e, r]) => `${e.tagName.toLowerCase()} "${(e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 24)}" ${Math.round(r.width)}×${Math.round(r.height)}`))()
```

Then screenshot the screen and look at it. Nothing may overlap, stick out of its
card, or sit out of line with its neighbours (P13-FR-030).

Run the walk three more times:
- **Arabic:** switch in Settings. Every screen should mirror, including the
  status line, the back row and the cards.
- **Dark:** switch the theme.
- **Sideways:** 780 × 360. The status line and tab bar shrink, and the content
  keeps most of the height.

## 4. The status line (P13-FR-035, SC-004)

1. On any screen, the line shows the date, the school, the console's camera
   sentence in the console's colour, and your initials. Tap it: the panel shows
   the school, date and time, the camera sentence, the name and the role.
2. Stop the engine only, not the phone: close its job, or stop whatever holds
   port 8000. **Within 30 s** every screen reads "Engine unreachable", with no
   count.
3. Start the engine again. Within 30 s the line returns to the camera count.
4. Compare with the console's top bar at the same moment. The words should be
   identical.

## 5. The back row (P13-FR-036, SC-005)

1. From Tools, open each tool, then press the back row. You should land on Tools.
2. People → a person → back → People. People → a group → a person → back → the
   group.
3. A screen opened with nothing behind it. In dev, reloading a tool's URL
   returns engine JSON (the proxy owns `/weapons`, `/people` and the rest), so
   simulate it instead:
   1. Load `/` fresh.
   2. Run
      `history.replaceState({}, '', '/weapons'); dispatchEvent(new PopStateEvent('popstate'))`
      in the JavaScript tool. The screen then has React Router's `default` key,
      just as after a real reload.
   3. Press back. You should land on Tools, the tab's top, not the sign-in page
      and not a blank screen.
4. People-group, person-history and Enrol show **one** back control, not two.
5. In Arabic the chevron points right, the way Arabic reads back.

## 6. The knife alert (P13-FR-034, SC-006)

With a waiting knife entry (the mock engine has some):

1. Start a timer.
2. From the Ask tab's "Needs your attention", or from Tools → Knife alerts, open
   the entry.
3. Press Watch. The clip plays **inside the entry**, and "Confirm knife" and
   "False alarm" are right under it.
4. Decide. The whole task should take **under 30 s**, with no scrolling past the
   clip to find the buttons.
5. Open the console's Knife alerts. The decision is there against the same
   account, and the console's clip still plays after the list, as before.

## 7. Everything the console says on hover is on the phone (P13-FR-037)

Go through `contracts/shared-screens.md` §4 row by row. Each `PhoneOnly` line
appears where it says:

- **Attendance:** the "Notify parent" reason, once above the register; the export
  hint before a register is shown.
- **Enrol:** the Save reason while fewer than the required photos are usable.
- **Counting:** figures and "(demo figure)" in the legend.
- **Passes and Movements:** the "permanent" lines; the per-hour counts under the
  traffic chart.
- **Plate editor:** "letter" / "digit" under the two "+" buttons.

Then open the same screens on the console. None of these lines appear there;
the hover titles still do.

## 8. The console has not changed (P13-FR-040, SC-008)

**Before the first change**, on `Fo2sh` with §0's jobs landed:
1. Set the console to **1440 × 900** on 5173.
2. Screenshot every console screen in English, light theme.
3. Save the screenshots in the session scratchpad, not the repo.

**After**, take the same screenshots and compare each pair by eye. Nothing
should differ. What changed in the shared screens is inert on the console by
construction (`contracts/shared-screens.md` §2), so a difference means a hook
was styled by the console, or a `ConsoleOnly` / `PhoneOnly` was swapped.

Also check the console's top bar in all four camera states, using §4's stop and
start. It should read exactly as before.

## 9. Side by side (P13-FR-029, SC-002)

Open the same screen on the console and on the phone, next to each other:
Knife alerts, Vehicles (register), System, People. The cards, badges, buttons,
chips, notices and words should be the same; only the arrangement differs.
Anything that looks like a different product is a `phone.css` rule restating
style rather than arrangement.

## 10. A real phone (Mohamed)

The last check, and it cannot be delegated:

- a ~360 px Android phone, plus an iPhone if one is to hand
- one-handed, on the school's Wi-Fi
- English and Arabic
- Knife alerts, Vehicles and Enrol with the phone's own camera. Enrol is still
  012's T047, unmeasured.

## 11. Update the record

- `STATUS.md`: in the Mobile app row, replace "nothing has been looked at on a
  real phone" with what §10 found. Only once it is true.
- `docs/PLAN.md`: add a P13 line pointing at `specs/014-mobile-ui-parity`, and
  update FR-15's status.
- `specs/012-mobile-parity/tasks.md`: mark the 12 open tasks "superseded by 014"
  with the date. Do not tick them.
