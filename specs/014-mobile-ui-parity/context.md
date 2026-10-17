# Implementation context: The phone looks like the console, fits one hand, and keeps in step with it

**Written by `/speckit-plan` on 11 September 2026, against commit `569efe0`.**

The point of this file: the planning chat has just read every file the plan
names. The implementing chat has not, and rebuilding that by opening whole
files is the single largest avoidable cost in the whole loop. So write down
here what the next chat would otherwise go and re-read.

Read this **before** opening any source file. Then open the named anchors
only — not the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code,
> the code wins and this file is wrong. Anchors drift — search for the symbol,
> do not trust the line number.
>
> **Four other jobs edit some of these files first** (research R14):
> - System Health brought level with the console
> - "Campus is calm"
> - the undefined colour tokens
> - the developer sign-in merge
>
> Line numbers below are from **before** them. Re-find each anchor by its
> symbol.

---

## 1. Anchors — where each edit lands

### Tooling

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `tools/check_parity.py` | `PARITY_FILES` (~48–99) | 25 paths relative to each `src/`, grouped under comments: types; 8 services; 5 i18n; `app/navigation.ts`; 6 contexts and 4 hooks; `styles/tokens.css`. `check_parity()` reads the module globals `WEB`, `MOBILE` and `PARITY_FILES` at call time, compares **bytes**, reports CRLF/LF separately, and returns 0 or 1. The docstring (~19) says "the 25 files". It crashes printing a diff on a cp1252 console (~166); the System Health job is fixing that | Add three commented groups: **The look** (`styles/app.css`), **Screens** (the 16 shared `pages/*.tsx`), **Feature components** (the 13). Update the docstring count. Do not remove any line; the comment at ~43–47 explains why |
| `engine/tests/test_parity_gate.py` | new | — | Load `tools/check_parity.py` with `importlib.util.spec_from_file_location`. Monkeypatch `WEB`/`MOBILE` to two `tmp_path` dirs and `PARITY_FILES` to one file. Identical bytes → 0. One byte flipped → 1. Same text with CRLF vs LF → 1. Use `capsys`. **If the System Health job already added a test for this script, extend that file instead** |

### Shared helpers and vocabulary (edit `web/src`, then copy the bytes to `mobile/src`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/services/format.ts` | top-level exports (`formatLongDate`, `formatTime`, `formatEngineBusy`, `capacityShare`, …) | **CRLF.** On the parity list. `web/scripts/check-format.ts` imports from it and asserts. Functions take a `language` argument rather than `t` | Add `cameraStatus(site, error)`, a pure function returning `{ state, key, args, colour, glyph }`. Move the logic from `TopBar.tsx` ~10–23 **verbatim**, colour expression included (data-model `CameraStatus`) |
| `web/scripts/check-format.ts` | the `eq(name, got, want)` helper and the import list at the top | runs with `npm run check:format` in `web/`. Not in CI or `dev.ps1` | Import `cameraStatus` and add four cases: error set → unreachable; `site` null → checking; `online === total` → allUp; otherwise someUp |
| `web/src/components/TopBar.tsx` | `TopBar()` | ~10–23 compute `online`, `total`, `allWell`, `color` (`error ? 'var(--bd)' : allWell ? 'var(--ac)' : 'var(--am)'`) and `cameraLabel` (engineUnreachable → checkingCameras → allCamerasUp{total} → someCamerasUp{online,total}). The glyph `{allWell ? '✓' : '!'}` is at ~42–44. It renders `header.topbar`: `todayLabel` on the left; on the right, the status span, then name, role and `.avatar` | Replace ~10–23 with `const s = cameraStatus(site, error)` and `t(s.key, s.args)`. **The render stays byte-for-byte the same shape**, with `s.colour` and `s.glyph` in the two places. Console-only file |
| `web/src/components/ui.tsx` | the exports: `toneColors`, `Badge`, `toneGlyph`, `Card`, `CardHeader`, `PageHeader`, `Stats`, `Field`, `Select`, `Toggle`, `DataNotice`, `Empty`, `LoadError`, `StatusDot` | imports `type { ReactNode }`. `Stats` sets `gridTemplateColumns: repeat(cols, 1fr)` inline | Add `export function PhoneOnly(_: { children: ReactNode }) { return null; }` and `export function ConsoleOnly({ children }: { children: ReactNode }) { return <>{children}</>; }`. **Not** a parity file |
| `mobile/src/components/ui.tsx` | same exports | differs from the console's only in its header comment and `Stats`: capped at 2, passing `'--cols'` instead of `gridTemplateColumns`, because `phone.css` must style it | Add the mirror image: `PhoneOnly` renders its children, `ConsoleOnly` returns `null` |
| `web/src/i18n/{keys,en,ar.draft}.ts` | flat `'key': 'wording'` maps; `keys.ts` is the key list | `en.ts` ~15–22 holds `nav.tab.*` (**Home's tab is labelled "Ask"**); ~46–53 hold `sidebar.calm*`, `topbar.*` and `role.*`. Existing keys reused here: `attendance.notifyParentWhy` (~319), `attendance.showRegisterFirst` (~314), `passes.removeTitle` (~612), `moves.goneTitle` (~617), `reader.col*`, `register.*` form labels, `action.remove`, `action.cancel` | Add the words in `contracts/shared-screens.md` §7. The Arabic is a dev-only draft. Three other jobs edit these files first; re-read them before adding |

### The phone's own files

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `mobile/src/styles/app.css` | whole file | 1,003 lines. The phone's own styles, 37 of ~106 selectors identical to the console's. It holds two blanket rules to lose: the `.row` fold (~377–417: first child 100%, the rest muted 12.5 px with `·` separators) and `.app__content [style*='grid-template-columns'] { display: flex !important }` (~812–821). `.mob-header`, `.mob-avatar` and `.tool-header*` are dead | **Replace** with a byte copy of `web/src/styles/app.css`, which starts with `@import './tokens.css';` like this one. Carry the phone-only parts into `phone.css` first (next row) |
| `mobile/src/styles/phone.css` | new | — | The phone layer, built with the `frontend-design` skill under the brief "the console's look, arranged for one hand at 360 px". Carry over from the old file: `.app` (100dvh), `.app__content` (`env(safe-area-inset-top)` padding), `.screen`, `.tabbar*` (`env(safe-area-inset-bottom)`), `.list-row` min-height 48, `.edit-row` stacked, `.edit-input` 16 px, `.filters` as a column, `.grid-2/3/4` and `.plan` in one column, `.stats { grid-template-columns: repeat(var(--cols, 2), 1fr) }`, `.row__sub`, `.row__chevron`, the inputs `min-width: 0 !important` rule, and `.modal__panel` as a sheet. New: the `.row` card (R3), the `.row--head` hide except in `.vg-capability-grid`, the `vg-*` hooks (R4), the 44 px minimums (R9), 16 px inputs (R10), `@media (max-height: 500px)` (R11), `.hint`, the status line and the back row |
| `mobile/src/main.tsx` | the imports (~1–11) | same providers and order as the console. `import '@/styles/app.css'` at ~11 | Add `import '@/styles/phone.css';` on the line after it |
| `mobile/src/app/AppShell.tsx` | `AppShell()` | 75 lines. It redirects to `/login` when there is no `account`. A `useEffect` scrolls `.app__content` to the top on a `pathname` change. `active = tabFor(pathname)`. It renders `.app` → `.app__content` → `<Outlet/>` → `nav.tabbar` (the `TABS` map, inline SVG icons, `aria-current`) | Put `<StatusLine/>` **before** `.app__content`, since the scroll reset targets `.app__content`. Put the back row first inside `.app__content` when the path is not a tab's top (`TABS.map(t => t.path)`). The back action is `location.key !== 'default' ? navigate(-1) : navigate(TABS.find(t => t.id === tabFor(pathname))!.path)`. After the developer sign-in merge this file may also render `DevSign*Banner`; keep it |
| `mobile/src/components/StatusLine.tsx` | new, phone only | — | Reads `useSite()` (`site`, `error`, `todayLabel`), `useSiteName()`, `useAccount()` (`name`, `initials`, `role`), `useT()` and `cameraStatus()`. Pinned line plus tap panel, per `contracts/phone-shell.md` |

### Shared screens (edit `web/src`, copy the bytes; every change inert on the console)

| File | Anchor | Shape today (from the inventory) | The edit |
|---|---|---|---|
| `pages/Weapons.tsx` | `detections.map`, the row with `'1.1fr .9fr .9fr .8fr .6fr 1.2fr 1.4fr'` (~174) | Cells: camera (`row__name`), area, `entry.time`, `entry.duration` (+ literal "cut at two minutes"), `entry.confidence`, a badge in a `<span>`, then a **flex span of clip controls**: Watch/Hide `linkbtn` (`setPlaying(c => c?.id === entry.id ? null : entry)`) and an "Open" `<a className="linkbtn">`, or a reason. Then the verdict `<span style={{gridColumn: '1 / -1'}}>` (~216–253), only when `verdict === 'pending'`: Confirm knife (`btn`), False alarm (`btn btn--ghost`), reason input (`minWidth: 180`). **One `<video>` after the whole list** (~257–274): `width: 100%`, `maxHeight: 420`, driven by `playing` (an entry object) | Extract the player into a local `ClipPlayer({ entry })`. Inside the row, after the clip-controls span: `<PhoneOnly>{playing?.id === entry.id && <div className="row__full"><ClipPlayer entry={entry}/></div>}</PhoneOnly>`. Wrap the after-list player in `<ConsoleOnly>`. Add `row__actions` to the clip-controls span and `row__full` to the verdict span. Add `data-label` on time, duration and confidence |
| `pages/Attendance.tsx` | register row `'1.4fr 1fr 1fr 1fr'` (~176); person-days row `'1.2fr 1.2fr .8fr 1fr'` (~214); export button (~132–144) | The register row has `row__name`, a badge span, `{row.time}` (`row__muted`), and an admin-only **always-disabled** "Notify parent" `linkbtn` with `title={t('attendance.notifyParentWhy')}` (otherwise `attendance.adminOnly` text). The day row has date, `day.where`, `day.time` and a badge. The export has `disabled={!result \|\| exporting}`, with a title of `downloadCsv` or `showRegisterFirst`. `var(--bad)` at ~153 belongs to the token job | `data-label` on `row.time` and `day.time`. One `PhoneOnly` hint above the register list with `notifyParentWhy`, and one under the export when `!result` |
| `pages/Enrol.tsx` | back link (~345–349); photo row `'56px 1fr 110px 1.4fr 40px'` (~589); Save (~657–667) | The back link is a `linkbtn` with `t('enrol.backToPeople')`, and the comment at ~320 calls it "Back to People, from any step". Save has `disabled={!session.ready \|\| busy}` and a title of literal English, `Needs ${session.requiredCount} usable photos from different angles`. The field grid (~405) is auto-fit. The placeholder (~599) uses `var(--bg3, …)`, which has a fallback | Wrap the back link in `ConsoleOnly`. Move the Save literal to `enrol.saveNeeds` and use it in both the `title` and a `PhoneOnly` hint shown when `!session.ready` |
| `pages/Counting.tsx` | the bar segment (~147–149); the legend (~170) | Segment `title`: `${part.name}: ${part.value}${part.live ? '' : ' (demo figure)'}`; a demo segment is only `opacity: 0.45` (~154). The legend shows `part.name` | `PhoneOnly` in each legend item: the value, plus `(t('counting.demoFigure'))` when `!part.live`. Move the title's literal to the same key |
| `pages/PeopleGroup.tsx` | back link (~38–39) | `linkbtn`, `navigate('/people')`, text "‹ People" (hard-coded) | Wrap it in `ConsoleOnly`. Its text is console-only debt |
| `pages/PersonHistory.tsx` | `backLabel` (~25); buttons (~39, ~62) | Hard-coded `‹ People` / `‹ ${groupName}`; two render sites | Wrap both buttons in `ConsoleOnly` |
| `pages/Users.tsx` | row `'1.2fr .7fr 1.6fr .9fr .5fr'` (~46); capability grid (~70) | The row has `row__name`, a role badge span, an email span, `user.lastActive` (`row__muted`), and an "Edit" `linkbtn` (hard-coded, debt). The capability grid is `'2fr .6fr .6fr'`, `fontSize: 13.5`: 3 `<span className="row--head">` headings, then 3 flat spans per capability | `data-label` on `lastActive`. `className="vg-capability-grid"` on the grid |
| `pages/Intrusion.tsx` | row `'1.2fr 1fr .8fr .9fr .8fr 1.1fr'` (~224) | `breach.zone` (`row__name`), `breach.time`, a literal "1 person"/"N people" (debt), `breach.duration`, a badge span, then a clip `linkbtn` or a reason | `data-label` on time and duration |
| `pages/People.tsx` | `row row--click` (~152–163), `'1.5fr .7fr 1.4fr 1.5fr .9fr .9fr'` | `role="button"`, `tabIndex`, `onClick`/`onKeyDown`. Cells: name and sub, a type badge span, a recognition sentence, last seen (4th), a today badge, a **flex actions cell** ("Track today" / "Remove", hard-coded, each with `stopPropagation`), and a confirm strip with `gridColumn: '1 / -1'` holding two `chip-btn`s | `data-label` on last seen. `row__actions` on the actions cell. `row__full` on the confirm strip |
| `pages/SystemHealth.tsx` | pipeline row `'1.2fr 1.6fr 1fr .8fr'` (~73); worker block (~94–123) | The worker block is `className="row__sub"` with `gridColumn: '1 / -1'`. Worker rows are `'1fr 1fr 1fr 1fr'`: name, `formatWorkerThroughput`, `formatWorkerQueue`, and a Behind badge or keeping-up text. **Being re-synced by another job; start after it lands** | `className="row__sub row__full"` on the worker block. Nothing else |
| `pages/VehicleGate.tsx` | tiles (~150) | `repeat(auto-fit, minmax(180px, 1fr))`, gap 12, six `<Tile>` | `className="vg-tiles"` |
| `components/CameraSources.tsx` | the source summary row (~547–581); the DVR channel div (~885); the success two-column layout (~1047) | The summary is an inline flex, space-between: name and meta (`flex:1`), status badge, reconnect reason, Edit/Remove `linkbtn`s. The channel div is `'64px 1fr 1fr 44px'`, `alignItems: center`, gap 10: id · name input · area select (or a message spanning `'span 2'`) · `role="switch" className="toggle"`, plus an info line at `gridColumn: '2 / span 3'`. The two-column layout is `'240px 1fr'`, gap 16: preview, then a form. Wide inputs: ~639 (300), ~830 (340), ~995 (width 220), ~1002 (280). Tokens at ~1258–1302 belong to the token job | `vg-source-summary`, `vg-channel-grid` and `vg-preview-form` on those three elements |
| `components/VehicleMovements.tsx` | `VisitRow` (~164–256), row at ~194; `TrafficChart` (~108–162); the "Inside now" card (~510–561) | The `VisitRow` columns are conditional on `showLeft`, with inline `gap: 14, alignItems: 'center', padding: '12px 0', borderTop`. Cells: Shot · Plate · owner and unit · in-at and gate · (out-at and gate) · a trailing span (estimated badge, duration, admin Gone `linkbtn` with `title={t('moves.goneTitle')}` at ~241–252). Each chart bar has `title` `${hourLabel} — ${entered} in, ${left} out`, with hour labels at ~141–146 | `row__actions` on the trailing span. Wrap the duration in its own `<span data-label=…>`. A `PhoneOnly` "Gone is permanent" line above the Inside-now list. A `PhoneOnly` caption under the chart using `moves.hourCounts` |
| `components/VehiclePasses.tsx` | row (~107); image link (~115–131); Fix (~190–198); Remove (~205–216) | `'68px 120px 1fr .7fr .6fr 1fr'`, with inline gap, alignment, padding, border and opacity. Cells: an image link (literal title, `alt=""`) · Plate, or `PlateEditor` at `gridColumn: '2 / -1'` · owner, gate and corrected-by · a direction badge · the time · a trailing flex cell (status badge, Fix, Remove with `title={t('passes.removeTitle')}`) | `data-label` on the time. `row__actions` on the trailing cell. `row__full` on the editor span. A `PhoneOnly` "Remove is permanent" line above the list |
| `components/VehicleReader.tsx` | `AttemptRow` (~177), `COLUMNS`; the header (~340–345) | A 7-column row with inline gap, alignment, padding, border and 13.5 px type; **no buttons**. The header uses the same `COLUMNS`, holds 7 `t('reader.col*')` spans, and is uppercase | Wrap the header in `ConsoleOnly`. Each cell gets `data-label={t('reader.col…')}` |
| `components/VehicleRegister.tsx` | the filter bar (~260–301); the row (~407); the delete confirmation (~475–512) | The filter bar is an inline flex: search (`flex:1`, `minWidth: 200`) · category chips · "+ Add a vehicle". The row is `'120px 1.2fr .8fr .8fr .9fr 118px'`, with inline gap, alignment, padding and border. Cells: Plate · owner and car · unit · a category badge · valid until · an actions flex ("Edit" / "Remove", hard-coded) | `vg-register-filters` on the bar. `data-label` on unit and valid-until, reusing `register.*`. `row__actions` on the actions cell. Move "Edit", "Remove" and "Keep it" into keys |
| `components/PlateEditor.tsx` | the two "+" buttons (~173–181, ~198–206) | Titles are the literals "one more letter" / "one more digit"; the visible glyph is only `+` | Keys `plate.oneMoreLetter` / `plate.oneMoreDigit` in the titles, plus a `PhoneOnly` caption under each |

## 2. Things to copy, not invent

- The camera sentence → `web/src/components/TopBar.tsx` ~10–23, moved verbatim into `format.ts::cameraStatus`.
- The avatar, glyph circle and badge → the console's `.avatar`, `.glyph` and `Badge` / `toneGlyph`. `phone.css` never restates them.
- The tab-top list and "which tab owns this path" → `mobile/src/app/tabs.ts::TABS` and `::tabFor`.
- A wrapper that renders nothing on one app → `ui.tsx::DataNotice`, the existing precedent.
- Checker loading and assertions → `tools/check_parity.py::check_parity` (it reads module globals at call time); `web/scripts/check-format.ts::eq`.
- Reaching a page in dev without the proxy → `history.pushState({}, '', '/users'); dispatchEvent(new PopStateEvent('popstate'))`. Use `replaceState` for "nothing behind it".
- Right-to-left arrows → the `.mirror-rtl` class, which is in both stylesheets.

## 3. Traps

- **Line endings.** `services/*.ts` (so `format.ts`), `types.ts` and `STATUS.md` are **CRLF**; most other files are LF, and there is no `.gitattributes`. Copy web → mobile as **bytes**. After any edit, `git diff --stat` must show only the lines you meant.
- **Every shared edit is two files.** Edit `web/src/…`, then copy the bytes to `mobile/src/…`. Once the list includes screens, the gate catches a forgotten copy. That is the point, not an obstacle.
- **Inline styles beat stylesheets.**
  - The phone's `.row` must be `display: flex`, never grid, or all 19 rows' inline `gridTemplateColumns` wake up.
  - A `vg-*` hook needs `!important` to beat an inline `display` or `grid-template-columns`.
  - The vehicle rows' inline `gap: 14`, `alignItems: center`, `padding` and `borderTop` **do** apply to the phone's flex card. Check those cards by eye against the others.
- **`.row--head` is hidden globally on the phone, except in `vg-capability-grid`.** There the headings are the only thing saying which yes/no column is Admin and which is IT.
- **Use `data-label` as a descendant selector** (`.row [data-label]::before`), not `.row > [data-label]`. The `VisitRow` duration sits inside the trailing span.
- **Badges are wrapped** in a `<span>` cell. `.row > .badge` matches nothing.
- **People's row is both tappable and holds buttons**, and each button uses `stopPropagation`. Keep the card's tap and the buttons' taps separate.
- **The console's `@media (max-width: 900px)` applies on every phone.** `.grid-4` gets two columns, `.grid-3`, `.grid-2` and `.plan` get one. `phone.css` restates whatever it needs.
- **`.stats` has no columns in the console's CSS.** The phone's `Stats` passes `--cols`, so `phone.css` must carry `.stats { grid-template-columns: repeat(var(--cols, 2), 1fr) }`, or every figure stacks.
- **`.screen`, `.row__sub` and `.row__chevron` exist only in the phone's old file,** and are used by `Tools.tsx` and `Account.tsx`. Carry them into `phone.css`, or those two pages lose their styling when `app.css` is replaced.
- **iOS zooms on focus below 16 px,** and the console's inputs are 14 px.
- **`var(--bd)` does not exist.** The `TopBar` unreachable colour is unset today. Move it verbatim; the token job fixes it. Do not fix it here, because it changes the console.
- **`CameraFrame` with `live` also polls recognition boxes, which carry names.** Nothing here may change a `detections={false}`.
- **A page URL in dev returns JSON.** Load `/` and click through.
- **`tsc -b --force`, never `--noEmit`.**
- **Status line placement.** The status line must sit **outside** `.app__content`. The shell's scroll reset targets that div, and a status line inside it would scroll away.
- **Sign-in is outside `AppShell`,** so it has no status line and no back row. That is correct: there is no account to show.
- **Known debt that stays.** This hard-coded English is not fixed here (`contracts/shared-screens.md` §7):
  - Users "Edit"; Weapons "cut at two minutes"; Intrusion "1 person / N people"; People "Track today / Remove"
  - TrackPerson "Date / From / To / Back to the cameras"
  - the console-only back links

  Report it, and do not claim the phone is fully Arabic.

## 4. Baseline

- `python -m pytest engine` → **1,564 tests collected across 46 files**, on 11 Sep 2026 at `569efe0`. That count is from `--collect-only`; the suite was not run in this session, because other sessions were editing engine files. `engine/pytest.ini` sets `-q` and this pytest prints no final `N passed` line, so exit 0 is the signal, as 012 found. The working tree then held uncommitted engine edits from another session (`test_health_load.py`, `api/live.py`, `features/base.py`).
- **`python tools/check_parity.py` fails at `569efe0`.** `services/format.ts`, `i18n/en.ts`, `i18n/ar.draft.ts` and `i18n/keys.ts` differ, the System Health drift. It then crashes with `UnicodeEncodeError` while printing the diff. The System Health job owns both. Expect it green before starting.
- `tsc` was **not run** in this session, because parallel sessions were building and `-b` writes `tsbuildinfo`. 012 recorded both apps clean.
- New test file: `engine/tests/test_parity_gate.py`, or an extension of the System Health job's test if it made one.

## 5. Still unknown

- **What `AttendanceRow.time` and `AttendanceDay.time` mean** (first seen? arrival?). Find where each is built in `services/api.ts` before writing its label. The same goes for every row in `contracts/shared-screens.md` §5.
- **Horizontal padding.** Where shared pages get it on the phone. The old `.app__content` had `padding: calc(safe-top + 18px) 0 14px`, with **no inline padding**, and shared pages are not wrapped in `.screen`. Find the rule that currently gives them their side margins before replacing the file.
- **`VehicleRegister` delete confirmation.** Is it a child of the row (so it needs `row__full`) or a sibling after it?
- **`action.edit`.** Whether it already exists.
- **Whether the System Health job added a pytest** for `check_parity.py`.
- **Whether the developer sign-in merge renders `DevSign*Banner` in the phone shell,** and where. The status line must sit consistently with it.
- **The Arabic status line at 360 px.** How much of the school's name survives. Settle it by eye.
- **The traffic chart's per-hour counts at 360 px.** Whether a wrapped text line or a figure per bar reads better. Settle it by eye.
