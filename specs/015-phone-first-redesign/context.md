# Implementation context: The phone is built for a phone, and still does everything the console does

**Written by `/speckit-plan` on 17 September 2026, against commit `34e2bef`** plus
uncommitted work in the tree from a finished session (Mohamed, 17 Sep: "that
session is finished"): `web/src/components/CameraFrame.tsx`, `CameraModal.tsx`,
`web/src/styles/app.css`, `engine/vg/features/{weapons,zones}.py` and tests,
`STATUS.md`, `specs/001-restricted-zones/spec.md`. Build on them. **Never stage
them in this feature's commits.**

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. If this disagrees with the code, the code wins.

The design reference is the canvas's artboard source, one `.dc.html` per screen
(markup and inline styles are the layout spec). This session's copy is in
`C:\Users\Fo2sh\AppData\Local\Temp\claude\E--VisionGuard\8b3f202f-9401-44a3-ada0-385d238dbe7b\scratchpad\canvas\project\`.
The live canvas is https://claude.ai/artifact/VXoNnkdpGzGnQaxhuGVYnb.

---

## 1. Anchors: where each edit lands

### Shared truth (edit in `web/src`, then copy bytes to `mobile/src`)

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `web/src/components/AlertBell.tsx` (LF) | `feedState`, `statusLine`, `seenKey/readSeen/writeSeen`, `useSeen`, `AlertBell` | One file: `CHECK_MS=15_000`, `SEEN_MAX=500`, `type Feed`, `useAsync(getAttention→filter !acknowledged, [], NONE, CHECK_MS)`, `useCapability('attention')`, `useSite().error`, `fresh` state for the new group, `rings` counter, `marker` (`9+`, `!`), `label` (`bell.titleNew`/`bell.title`), panel with `Group` | Move feed/seen/unread/marker/label/rings/newGroup+seenGroup logic into `web/src/app/useAlertFeed.ts`, exporting a hook and the `Feed` type. AlertBell keeps refs, open state, outside/Escape/route-change close, and render. **Rendered DOM must not change.** |
| `web/src/app/useLinkedItem.ts` | `useLinkedItem`, `LINKED_STYLE`, `holdInView` | web only; observes `document.body` | Copy bytes to `mobile/src/app/` |
| `tools/check_parity.py` | `PARITY_FILES` | 26 entries; "the 25 files" in docstring is already stale | Add `"app/useAlertFeed.ts"`, `"app/useLinkedItem.ts"` in the hooks group with a one-line comment each |
| `web/src/i18n/keys.ts` (CRLF) | `` `nav.tab.${'home' \| 'tools' \| 'people' \| 'system' \| 'account'}` `` (~line 58), then `'mobile.tools.lead'`, `'mobile.account.lead'` | `UiKey` is one big union | Tab union → `home\|cameras\|tools\|people\|more`; add `phone.*` keys (list them as a block with a comment). Remove `mobile.account.lead` only if nothing uses it |
| `web/src/i18n/en.ts` (CRLF) | `'nav.tab.home': 'Ask'` (line 15–19) | typed `Record<MessageKey,string>`, so tsc proves completeness | `Home`, add `Cameras`, `More`, drop `system`/`account`; add `phone.*` English |
| `web/src/i18n/ar.draft.ts` (CRLF) | `'nav.tab.home': 'اسأل'` | `Partial` | الرئيسية, add الكاميرات, المزيد, `phone.*` drafts |

Copy each of these to `mobile/src/...` as bytes (`cp`), then run `python tools/check_parity.py`.

### Phone only

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `mobile/src/app/AppShell.tsx` | `AppShell` | `<div.app><DevSignInBanner/><div.app__content><Outlet/></div><nav.tabbar>` with `TABS.map` buttons; scrolls `.app__content` to top on pathname change; `Navigate /login` when no account | Keep banner first and the scroll reset. Add `TopBar` or `ScreenHeader` above `.app__content` from `isTabRoot`/`screenFor`; rebuild tab bar for new `TABS` |
| `mobile/src/app/tabs.ts` | `TABS`, `TAB_PREFIXES`, `tabFor`, `toolEntries` | 5 tabs home/tools/people/system/account; `toolEntries()` = NAV ask+watch | New `TABS`, `SCREENS` table, `isTabRoot`, `screenFor`; keep `toolEntries` |
| `mobile/src/app/routes.tsx` | `AppRoutes`, `RequireRole`, `RequireSignIn`, `SigningIn` | All routes under `<RequireSignIn><AppShell/>`; `people/enrol` and `users` wrapped in `RequireRole role="admin"` | Add `alerts`, `cameras`, `cameras/:id`, `more`; `account` → `<Navigate to="/more" replace/>` |
| `mobile/src/components/ui.tsx` | `Select`, `PageHeader`, `Stats`, `Toggle`, `DataNotice`, `LoadError` | `Select` = native `<select className="input">`; `PageHeader` = `h1.page__title` + `p.page__lead`; `Stats` caps at 2 cols via `--cols`; `DataNotice`/`LoadError` inline-styled, render null when nothing to say | `Select` → chip + `Sheet` (same props); `PageHeader` → lead only; keep DataNotice/LoadError **exactly** (comments say why) |
| `mobile/src/styles/app.css` | whole file | 1003 lines. `.btn` has `width:100%` (~239); `.row` fold (~377); `.app__content [style*='grid-template-columns']` `!important` fold (~812); `.app__content input{min-width:0!important}` (~828); `.app` max-width 560, `100dvh` | Rewrite as the phone design system (canvas CSS), keep every class name copies use (`card card--tight card--dashed card__title card__sub page__lead btn btn--ghost btn--quiet btn--danger chip-btn chip-btn--on/--off/--brand badge badge--dot stats stat stat__label stat__value field field__label input row row--head row--click row--pressable row__name row__sub list-row linkbtn linkbtn--quiet toggle toggle__knob empty notice notice--amber dot dotline glyph camgrid camcard camframe* modal__* progress bar-track bar-fill grid-2/3/4 plan filters edit-row edit-input mirror-rtl`). Scope the grid fold to `.legacy` |
| `mobile/src/components/CameraFrame.tsx` | `CameraFrame`, `StreamImage`, `STALLED_MS` | 481 lines vs web 587; missing stream release + stall back-pressure | Bring level with web (then phone layout only) |
| `mobile/src/components/CameraModal.tsx` | `CameraModal` | 84 lines vs web 160; thinner header | Level with web, then full-screen layer |
| `mobile/src/components/CamGrid.tsx` | `CamGrid` props | missing `activeRef` | Level with web |
| `mobile/src/components/VehicleAlerts.tsx` | — | drops linked item, `useT`, error/loading | Level with web |
| `mobile/src/pages/Home.tsx` (CRLF) | `Home` | copy of console Home except `open(item.to)` | Rebuild; use `item.link` |
| `mobile/src/pages/Account.tsx` | — | 62 lines | Replace with `More.tsx`; delete Account.tsx |
| `mobile/src/pages/{Weapons,Intrusion,SystemHealth}.tsx` | — | differ from web by dropping `useLinkedItem` | Rebuild from the **web** version |

## 2. Things to copy, not invent

- Camera status wording/colour → `web/src/components/TopBar.tsx::TopBar` (the `cameraLabel` ternary; `error ? var(--bd)`. Note `--bd` is undefined in tokens: use `var(--rd)` on the phone).
- Date → `useSite().todayLabel` (split at ` · ` for the date part), or `formatLongDate(site.today, language)`.
- Attention wording and links → `app/useAttention.ts::toAttentionItem`, `item.link`, `acknowledge`.
- Ask → `web/src/pages/Home.tsx::submit` (routes `outcome.to` with `state:{autoRun:true}`; notes via `t(outcome.message, outcome.args)`).
- Seen-list → `AlertBell.tsx::useSeen` (goes into `useAlertFeed`).
- Linked item outline + missing notice → web `Weapons.tsx` / `Intrusion.tsx` usage of `useLinkedItem('entry'|'scene')`.
- Camera tiles, counts, areas → `CamGrid.tsx` (`useCameraGrid`, `getCameraCounts` 1 s poll, area order by first appearance, `describeCount`).
- Detections for one feature → `CameraFrame` props `live`, `feature`, `colour`, `onBoxes`, `onCount`, `detections`; `getCameraDetections(cameraId, feature, colour)`.
- Record → `RecordButton cameraId disabled={camera.offline}`.
- Follow → `TrackPerson.tsx` LiveMode `startFollow(cameraId, x, y)`, `bodyAt()` (smallest box), `getFollow` 1 s poll.
- Admin hint → `useAccount().role === 'admin'`.
- Theme/language → `useTheme()`, `useLanguage()` (as `web/src/pages/Settings.tsx` does).
- Sign out → `useAuth().signOut()` (as `web/src/components/Sidebar.tsx`).
- Brand → `components/Logo.tsx::Logo` (size prop).

## 3. Traps

- **CRLF files**: `mobile/src/pages/{Home,Counting,VehicleGate}.tsx`, `components/{CameraSources,Plate,VehicleMovements,VehiclePasses,VehicleReader,VehicleRegister}.tsx`, `app/{navigation,useAttention}.ts`, `i18n/{en,keys,ar.draft}.ts`, `services/*.ts`, `types.ts`. A rebuilt page written whole with the Write tool turns LF. **That is fine for phone-only files** (nothing compares them), but keep a file's existing ending when editing a shared one. Check with `git ls-files --eol`.
- **Proxy collision**: `/cameras` is an engine API prefix in `mobile/vite.config.ts`. A reload of `/cameras` or `/cameras/:id` in dev returns JSON. That is not a bug: navigate from `/`.
- **Names on pictures**: `CameraFrame` defaults `detections=true`, and face boxes carry names. Pass `detections={false}` on System health's grid, Enrol, and any tile that must not name anybody. Face boxes (`_face_boxes`) are green with `label=name` when identified, otherwise "Unknown", with `match` FACE/NONE. Tracked boxes lead with `#id` and put a name underneath only while a face is inside. Never merge the two.
- **Tile overlays** are on only for Knife detection and Lost bag. Don't turn them on for Cameras or Home.
- **Null is not zero**: the vehicle tiles, counts, capacity, workers' ms, GPU fields, a group's `here`. Render "—".
- **Counting's percentage** comes only from `result.sub`. Never compute one.
- **`Notify parent`** is permanently disabled in the console, with its reason on hover (`attendance.notifyParentWhy`). Show the reason as text.
- **Knife decisions are any-role.** Zone toggle, register writes, remove person, enrol, sources and alert settings are admin (server decides; hide or disable as the console does).
- **`useSite().todayLabel` time** is a browser-clock snapshot every 30 s. Don't add a ticking clock.
- **Weapons retention** reads `useSite().site.clipRetentionDays`, not the weapons API.
- **Track `?person&date`** fill in only; they don't run.
- **`.app__content` scrolls, not the window.** `useLinkedItem`'s ResizeObserver on `body` never fires on the phone (accepted, R3).
- **Provider order** in `mobile/src/main.tsx` is load-bearing (Auth → Language → Site → Camera → Capability → Router). New hooks that call `useSite`/`useCapability` work anywhere under AppShell.
- **iOS zoom**: inputs need 16 px text.
- **Console must not change**: after lifting `useAlertFeed`, open the console (`mock-admin`) and compare the bell closed and open, with 0 and several items.

## 4. Baseline

- `python -m pytest engine` → **1889 passed, 6 skipped** (273 s), at `34e2bef` plus the uncommitted tree.
- `python tools/check_parity.py` → 26 files identical. `--no-fixtures` → clean.
- No engine test is added (no engine change). If a parity test for `check_parity.py` exists by then (`engine/tests/test_parity_gate.py`), keep it green.
- Known flaky under load: `test_recording` forgotten-recording and `test_lost_bag` interest-lapse. Rerun alone before calling them failures.

## 5. Still unknown (check in code, don't assume)

- Whether `/track` LiveMode shows a follow that was started from elsewhere (`getFollow` on mount → FollowBanner). If yes, CameraView's per-person **Follow** calls `startFollow(camera.id, box centre)` then `navigate('/track')`. If not, leave Follow out (gap G6).
- The exact `AttendanceQuery` / `CountQuery` field names and the value meaning "everyone" / "all places" (read `types.ts` `AttendanceQuery`, `useOptions.ts`).
- Whether `getDeliveries` is refused for a guard (`/settings` read is open per `auth/deps.py`, so it should succeed).
- Whether `exportAttendance`'s object-URL download works in a phone browser (by-eye; Mohamed if unsure).
