# Implementation context: The phone does everything the console does

**Written by `/speckit-plan` on 3 September 2026, against commit `faab0fd`.**

Read this **before** opening any source file. Then open the named anchors only —
not the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code, the
> code wins and this file is wrong. Anchors drift — search for the symbol, do not
> trust the line number.

---

## 1. Anchors — where each edit lands

### Files that are copied, not edited

25 files copy byte-for-byte from `web/src` to `mobile/src` — the list is in
`contracts/parity.md`. **Do not open them.** Copy their bytes and move on; the
parity checker is what proves the copy, not reading it.

The pages and feature components (Pile 2) also copy without edits. Their bodies
compile against the phone's `ui.tsx` because the export names match.

### Files genuinely written

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `mobile/vite.config.ts` | `export default defineConfig` | 15 lines. `plugins: [react()]`, alias `@` → `./src`, `server: { port: 5174 }`. **No proxy at all** | Add `API_PATHS` and the proxy block copied from `web/vite.config.ts`, keeping `changeOrigin: false`, `timeout: 0`, `proxyTimeout: 0`. Keep port 5174. Copy the explanatory comment too — it is the reason the phone can show a picture |
| `mobile/src/components/ui.tsx` | current exports | 120 lines, 8 exports: `toneColors`, `Badge`, `toneGlyph`, `HomeStats`, `Card`, `Stats`, `Toggle`, `Empty` | Replace. Must export the console's **14**: the 8 above minus `HomeStats`, plus `CardHeader`, `PageHeader`, `Field`, `Select`, `DataNotice`, `LoadError`, `StatusDot`. `Card` already takes `tight`. Signatures in `contracts/shell.md` |
| `mobile/src/styles/app.css` | `.row` | 649 lines, **no `@media` at all**. Has `.row__name`, `.row__sub`, `.row__chevron` — the phone idiom is already here | Rewrite. `.row` becomes a flex column, `.row--head` hidden. Reuse the existing `row__name` / `row__sub` / `row__chevron` styles: they are the target shape, already written |
| `mobile/src/app/navigation.ts` | `TABS` | 32 lines, 5 tabs (`home`/`tools`/`people`/`system`/`account`) with 18×18 SVG icon paths | Keep the 5 tabs and the icons. The Tools tab's list must come from the copied `web/src/app/navigation.ts::NAV` (10 entries), not a hand-written one |
| `mobile/src/app/routes.tsx` | `AppRoutes` | 35 lines, 8 routes, no guards at all — any account reaches everything | Rewrite from `web/src/app/routes.tsx`: copy `RequireSignIn`, `RequireRole` and `SigningIn` verbatim, then list the phone's routes. Keep the console's paths exactly — Ask deep-links depend on them |
| `mobile/src/app/AppShell.tsx` | `AppShell` | 56 lines, `<Outlet/>` + tab bar | Keep the shape. Add safe-area insets and make the tab bar order follow `dir` |
| `mobile/src/components/CamGrid.tsx` | `CamGrid` | 31 lines, fixture-driven | Rewrite from `web/src/components/CamGrid.tsx` (350 lines). **Keep `tileRefreshMs(count)`** — it is the backpressure rule, and the phone showing fewer tiles must not make it ask for more |
| `mobile/src/components/CameraFrame.tsx` | `CameraFrame` | 84 lines, fixtures | Replace with the console's 481-line version. Only ~28 lines carry layout (`className=` / `style={{`); the constants `SCALE`, `SNAPSHOT_REFRESH_MS`, `CLOCK_TICK_MS`, `DETECTION_REFRESH_MS` and `BOX_COLOR` copy unchanged |
| `mobile/src/components/CameraModal.tsx` | `CameraModal` | 45 lines | Rewrite as a full-screen sheet |
| `mobile/src/main.tsx` | render call | 19 lines | Mount the six providers in the console's order — see `contracts/shell.md`. `AuthProvider` **outside** `LanguageProvider` |
| `mobile/index.html` | `<head>` | Vite default | Add `viewport-fit=cover` and the same font preconnects as `web/index.html` |
| `tools/check_parity.py` | new file | — | Compare the 25 files as **bytes**. `--no-fixtures` mode asserts no `mockData.ts` and no `Math.random(` under `mobile/src` |
| `dev.ps1` | `$WebPort = 5173` (~line 41), `Invoke-Up`, `Invoke-Test`, `Clear-Ports`, `Show-Help` | `$ApiPort=8000`, `$WebPort=5173`. `Invoke-Up` takes `[bool]$WithEngine, [bool]$WithWeb` and starts npm in a job | Add `$MobilePort = 5174`, a `-Mobile` switch, a third job, 5174 in `Clear-Ports`, the two checkers in `Invoke-Test`, and a line in `Show-Help` |
| `.github/workflows/ci.yml` | `web:` job (~line 92) | Two jobs: `engine`, `web`. `web` does `npm ci` then `node node_modules/typescript/bin/tsc -b --force`, `cache-dependency-path: web/package-lock.json` | Add a `mobile:` job — same steps, `mobile/` working directory. Add the parity checker to the `engine` job (it is Python and needs no Node) |
| `docs/PLAN.md` | `### P9 — Notifications + mobile` (~line 286), `FR-15` (~line 60) | P9 says mobile is wired "**read-only** (view, don't act)". FR-15 "Mobile on real data \| missing" | P9's mobile half is superseded — record that and leave notifications in P9. Point FR-15 at this spec |
| `STATUS.md` | the `Mobile app` row | "**Fake** — entirely fixtures, including random numbers" | Rewrite when it stops being true, and not before |

### Files deleted

`mobile/src/services/mockData.ts`, `services/api.ts`, `services/ask.ts`,
`types.ts`, `pages/ToolPage.tsx`, and the 8 fixture pages. Delete them **first** —
every stale import then shows up as a `tsc` error instead of hiding.

---

## 2. Things to copy, not invent

- The proxy and its reasoning → copy `web/vite.config.ts` whole, comment included.
- Route guards → copy `web/src/app/routes.tsx::RequireSignIn`, `::RequireRole`,
  `::SigningIn`.
- The tool list → `web/src/app/navigation.ts::NAV`, `::navSectionsFor`,
  `::pathFor`, `::homeTools`. Labels are **not** in there by design; they live in
  `i18n` under `nav.<id>.label` so an Arabic tab bar is possible.
- Loading / error / refresh → `web/src/app/useAsync.ts` → `{data, error, loading, reload}`.
  Never hand-roll a loading flag.
- Camera refresh pacing → `web/src/components/CamGrid.tsx::tileRefreshMs`.
- Overlay colours → `web/src/services/format.ts::boxColor`. Never a literal.
- The phone row idiom → `mobile/src/styles/app.css`'s existing `.row__name`,
  `.row__sub`, `.row__chevron`. Already written, already right.

---

## 3. Traps

- **Line endings.** `services/*.ts`, `types.ts` and `STATUS.md` are CRLF; most
  else is LF, and there is no `.gitattributes`. Copy **bytes**. A copy that reads
  and re-writes text rewrites every ending and turns 25 files into 25 whole-file
  diffs — and makes the parity checker's first run useless. `git diff --stat`
  catches it.
- **`gridTemplateColumns` is inline**, at 28 sites. A media query cannot override
  it by specificity. The phone's `.row` sidesteps this by not being a grid — the
  property becomes inert. Do not reach for `!important`, and do not edit the 28
  call sites.
- **`CameraFrame` with `live` also polls recognition boxes, which carry names.**
  Pages already pass `detections={false}` where an identity must not appear. The
  phone's `CamGrid` must not override it. This is constitution rule 2 and it has
  bitten before.
- **`DataNotice` is load-bearing.** A phone `ui.tsx` returning `null` for it
  compiles and silently removes every "this is demo data" warning in the app.
- **The two `ToolId` types are incompatible.** Mobile's is
  `'attend' | 'count' | 'lost' | 'track' | 'weapon' | 'intrude'`; the console's is
  `'attendance' | 'counting' | …`. Delete mobile's `types.ts`; do not merge them.
- **The fixture tool list has six tools and no vehicle gate.** Build the list
  from `NAV` so it cannot happen again.
- **A page URL in dev returns JSON.** The proxy claims top-level paths like
  `/people` and `/system`, which are also route names. Load `/` and click
  through; do not deep-link in dev.
- **`tsc -b --force`, never `--noEmit`** — project references make `--noEmit` a
  no-op that exits 0.
- **`mobile/` has never been typechecked in CI.** Expect the first run to find
  pre-existing errors that have nothing to do with this feature. Say so rather
  than folding them in silently.
- **Language follows the account, not the browser** — a shared gate phone must
  not show the previous guard's language. Copying `LanguageContext` preserves
  this; a `localStorage` shortcut in the shell would break it.

---

## 4. Baseline

- `python -m pytest engine` → **green at commit `faab0fd`**: exit code 0,
  progress reached 100% with no failures. **1,539 tests across 45 files** by
  `--collect-only`.
  **There is no passed/skipped split to record.** `engine/pytest.ini` sets
  `addopts = -q`, and this pytest build prints no final `N passed` line at all —
  confirmed across three separate runs, the last two captured to a file rather
  than piped. The exit code and the 100% progress line are the signal. Do not
  spend time hunting for the count; T002 is satisfied by exit 0.
- `node node_modules/typescript/bin/tsc -b --force` in `mobile/` → **exit 0
  before any change was made.** The phone app had never been typechecked in CI,
  so this was unmeasured; it turns out to have been clean. Any error appearing
  from here is therefore this feature's, with no pre-existing noise to subtract.
- The only warning anywhere is a TensorRT deprecation from
  `test_weapons_live.py`, and a `SyntaxWarning` for `"\V"` in
  `engine/tests/test_source.py:237`. Both predate this feature.
- **`web/src` and `engine/` are being edited by something else while this runs.**
  `types.ts`, `services/api.ts`, `wire.ts` and `format.ts` were all rewritten at
  09:00:41 on 3 Sep — five minutes after they were copied, all four within
  milliseconds of each other, so a batch save rather than a person typing. The
  parity checker caught it immediately and the copies were re-synced. Expect to
  re-sync again, and do not read a parity failure as a mistake in the copy.
- New test files this feature adds: **none in `engine/`**. There is no JavaScript
  test runner in this repository and this feature does not add one. Its
  automated gates are the two typechecks and the two checkers.
- Nothing is known to be failing before this feature starts, except that
  `mobile/` has never been typechecked at all, so its current state is unmeasured.

---

## 5. Still unknown

- **Whether `mobile/` typechecks today.** Never run in CI. Establish it before
  the first copy, so pre-existing errors are not attributed to this work.
- **Which pages need a phone-specific presentation beyond the `.row` rule.** The
  likely three are the vehicle register, the camera channel list in
  `CameraSources.tsx` (which uses fixed pixel columns, `'64px 1fr 1fr 44px'`), and
  System Health's worker table. Confirm by looking at each on a 375 px screen —
  do not pre-emptively rewrite them.
- **Whether `Enrol.tsx` works against a phone camera.** It requests a camera
  stream and scores face quality. A phone's front camera may behave differently
  from a laptop's. Needs a real device.
- **Whether `TrackPerson.tsx` (1,738 lines) is usable one-handed.** The largest
  page by far, with live tracking, past sweeps and clip playback. Assume it needs
  its own phone task; confirm by looking before sizing it.
- **How the phone is served in production.** Dev uses two Vite servers behind one
  proxy each. Nothing was found mounting `dist/` in `engine/vg/api/app.py`, so how
  the console reaches a browser on site is not settled in the repo — and the phone
  inherits that question. Worth asking Mohamed rather than inventing an answer.
