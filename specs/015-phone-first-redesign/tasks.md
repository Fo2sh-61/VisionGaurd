---
description: "Tasks for 015 — the phone is built for a phone, and still does everything the console does"
---

# Tasks: The phone is built for a phone, and still does everything the console does

**Input**: `specs/015-phone-first-redesign/` — spec.md, plan.md, research.md, data-model.md, contracts/phone-screens.md, quickstart.md, context.md

**Tests**: no new automated tests. There is no engine change, and the spec asks for none. Proof is the gates in quickstart §1 on every commit, the 360-px audit (§3), and the by-eye walk (§4).

**Design reference**: each rebuilt screen matches its artboard in the canvas source (`context.md` gives the path). Every rebuilt screen **starts from the console page** (`web/src/pages/<Page>.tsx`): keep its hooks, calls, polling, query parameters, notices and wording, then rearrange the markup (research R1). The screen's "Keep" list is in `contracts/phone-screens.md`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 frame · US2 guard on patrol · US3 tools · US4 people and More · US5 proof

---

## Phase 1: Setup

- [X] T001 Confirm the baseline in the working tree: `python tools/check_parity.py` (26 identical), `python tools/check_parity.py --no-fixtures`, and `npx.cmd tsc -b --force` in `web/` and `mobile/`. Record anything already failing in `specs/015-phone-first-redesign/gaps.md` under "Before this feature" (create the file with the G1–G15 table from research R15)
- [X] T002 [P] Write `tools/phone_audit.js`: a self-contained browser script returning `{route, overflowX, smallTargets[], inlineLinks[], lowContrast[], tinyText[]}` for the current page as quickstart §3 defines. Contrast walks ancestors to the first opaque background and uses the WCAG formula; targets exclude hidden and zero-size elements

---

## Phase 2: Foundational — shared truth (commit 1)

**Purpose**: the hooks and wording both apps read. Nothing on the phone can be built before these exist.

- [X] T003 Lift the bell's logic from `web/src/components/AlertBell.tsx` into new `web/src/app/useAlertFeed.ts`: the feed state, status line, seen-list, unread, marker, label, rings, new/seen groups, `open()` and `markSeen` (data-model "AlertFeed"). Then make `AlertBell.tsx` use it with **identical rendered output** (context §1)
- [X] T004 Add the phone wording to `web/src/i18n/keys.ts`, `web/src/i18n/en.ts` and `web/src/i18n/ar.draft.ts` (all CRLF; Edit tool). Tab union → `home|cameras|tools|people|more` (Home, Cameras, Tools, People, More / الرئيسية، الكاميرات، الأدوات، الأشخاص، المزيد). Add a `phone.*` block: back, alerts screen title and "messages sent", today-so-far title and the four figure labels, live now, see all, all cameras, filter all/live/no signal, last picture {time}, no boxes right now, boxes drawn by, in view now {count}, faces/counting/lost bag/knife, not identified, follow, other cameras, more title, account/system/settings/accounts rows, dark mode, sign out, choose (sheet title), done, show filters, workers show/hide {count}, read-only profile note. Remove `nav.tab.system`/`nav.tab.account` and any key no file uses any more
- [X] T005 Copy bytes `web/src/app/useLinkedItem.ts`, `web/src/app/useAlertFeed.ts`, `web/src/i18n/{keys,en,ar.draft}.ts` → `mobile/src/...` (`cp`, not a text rewrite)
- [X] T006 Add `"app/useAlertFeed.ts"` and `"app/useLinkedItem.ts"` to `PARITY_FILES` in `tools/check_parity.py` with a one-line reason each; fix the stale "25 files" docstring count
- [X] T007 Gates (quickstart §1). The phone `tsc` will fail only on `nav.tab.system/account` in `mobile/src/app/tabs.ts`, so point those two at `nav.tab.more` as a stopgap. Start `mock-admin`, open the console bell with items, and compare the closed and open states with before. Commit on `Fo2sh` staging only T002–T006 files: "The alert bell's logic is one hook both apps read"

**Checkpoint**: parity reports 28 files; the console's bell is unchanged.

---

## Phase 3: User Story 1 — Every screen has the phone's frame (P1) 🎯 MVP (commit 2)

**Goal**: five tabs; a top bar with brand, camera status, bell and initials on tab roots; a back header below them; bottom sheets for choices. Every existing screen renders inside the new frame.

**Independent test**: at 360 px, every route in the contract shows the right header, the right tab lights, back returns to the previous screen or the parent, the engine stopped shows "Engine unreachable" within 30 s, and the bell marker matches the console's.

- [ ] T008 [US1] Rewrite `mobile/src/styles/app.css` as the phone design system from the canvas CSS (tokens via `var(--…)`; contrast overrides for `--tx2/--tx3/--am` on `.app` in both themes, research R6; `.top`, `.sub`, `.tabs`, `.chips`, `.sheet`, `.seg`, `.stat`, `.frame` equivalents). Keep and restyle every class name listed in context §1 for the copied components at ≥ 44 px targets. Remove `.btn { width:100% }`. Scope the inline-grid fold rules to `.legacy`
- [ ] T009 [P] [US1] Create `mobile/src/components/Sheet.tsx`: a bottom sheet with scrim, grab handle, title, and focus moved in and restored. Closes on scrim tap, on Escape, and on route change. `role="dialog"`, `aria-modal`, mirrored in RTL
- [ ] T010 [US1] In `mobile/src/components/ui.tsx`, turn `Select` into a chip that opens `Sheet` (same props; one ≥ 44 px option row each, tick on current) and make `PageHeader` render the lead only. Leave `DataNotice` and `LoadError` byte-for-byte as they are
- [ ] T011 [P] [US1] Create `mobile/src/components/TopBar.tsx`: `Logo` + "VisionGuard"; camera status line copied from `web/src/components/TopBar.tsx` (`--rd` for unreachable) + site date; bell button (`useAlertFeed` marker, ring animation, aria-live label) → `/alerts`; initials button → `/more`
- [ ] T012 [P] [US1] Create `mobile/src/components/ScreenHeader.tsx`: back arrow (`phone.back`, `.mirror-rtl`, 44 px) using `history.state.idx > 0 ? navigate(-1) : navigate(parent)`, the title, and an optional action slot for a page to fill
- [ ] T013 [US1] Rewrite `mobile/src/app/tabs.ts`: `TABS` (home, cameras, tools, people, more with icons from the canvas), `SCREENS` prefix table (title key, tab, parent) for every route in `contracts/phone-screens.md`, `isTabRoot`, `screenFor`, `tabFor`; keep `toolEntries`
- [ ] T014 [US1] Rebuild `mobile/src/app/AppShell.tsx`: banner first, then `TopBar` on tab roots or `ScreenHeader` elsewhere, `.app__content` (scroll reset kept), and the tab bar from `TABS` with `aria-current`. A header action slot is provided through a small context `usePageAction(node)`
- [ ] T015 [US1] Update `mobile/src/app/routes.tsx`: add `alerts`, `cameras`, `cameras/:id` and `more` (temporary placeholders are the existing pages until US2/US4 land, never fake content); `account` → `<Navigate to="/more" replace />`; keep the `RequireRole` wrappers
- [ ] T016 [US1] Gates, then run `mock-mobile` at 360×780 and walk every route: header, tab and back correct; nothing overlaps the tab bar or banner. Commit "The phone has five tabs, a top bar and a way back"

**Checkpoint**: MVP. Every existing screen works inside the new frame.

---

## Phase 4: User Story 2 — A guard on patrol (P1) (commit 3)

**Goal**: Home opens on what needs attention, today's figures and a live camera; Alerts is the bell as a screen; Cameras lists every camera and one camera switches overlays; the knife review fits one screen.

**Independent test**: quickstart §4 steps 1–5 pass. Every Home figure equals its tool's figure. Stopping the engine blanks figures to their "unreachable" state, never zeros.

- [ ] T017 [P] [US2] Bring `mobile/src/components/CameraFrame.tsx`, `CameraModal.tsx` and `CamGrid.tsx` level with the web copies (stream release, `STALLED_MS`, header, count, `RecordButton`, `activeRef`), then make `CameraModal` a full-screen layer with a back arrow (research R9)
- [ ] T018 [P] [US2] Create `mobile/src/app/useTodayFigures.ts` (data-model "TodayFigure", research R7) from `getAttendance`, `getCount`, `getVehicleSummary`, `getBreaches` and `getZones`, gated on `useCapability`, 30 s refresh each, independent failures
- [ ] T019 [US2] Rebuild `mobile/src/pages/Home.tsx` from `web/src/pages/Home.tsx` + `Main.dc.html`: greeting, Ask (input flexes, button fixed), suggested chips strip, "Needs your attention" (bad-tone items get a full-width primary action; every item keeps Acknowledge; `item.link` + `autoRun`), "Today so far" 2×2 tappable tiles, first live camera tile → `/cameras/:id`
- [ ] T020 [P] [US2] Create `mobile/src/pages/Alerts.tsx` from `web/src/components/AlertBell.tsx` panel + `Alerts.dc.html`: call `open()` on mount and `markSeen` for arrivals; feed status line + offLead/reason/demo; "New since you last looked" / "Still open" item cards → `item.link`; "Messages sent" from `getDeliveries(20)` only when it succeeds
- [ ] T021 [P] [US2] Create `mobile/src/pages/Cameras.tsx` from `Cameras.dc.html` (research R8): roster by area, All/Live/No signal chips with counts, counts from `getCameraCounts` (null → "—"), offline "No signal · last picture", `camera.lastKnown`/`noneConfigured` states, tiles → `/cameras/:id`
- [ ] T022 [US2] Create `mobile/src/pages/CameraView.tsx` from `CameraView.dc.html`: `CameraFrame size="lg" live feature=…` with segmented Faces/Counting/Lost bag/Knife (`?feature=`), legend on Faces only, count from `onCount`, "No boxes right now" when empty, `RecordButton`, "In view now" from face boxes (name only on green), other cameras strip. Check context §5 first: add Follow only if verified, otherwise record G6 in `gaps.md`
- [ ] T023 [US2] Rebuild `mobile/src/pages/Weapons.tsx` from **`web/src/pages/Weapons.tsx`** + `Weapons.dc.html`: DataNotice/not-running empty state first; period chip (7 windows via `Select`); counts line (G13); entry cards with the clip on top, camera · area, time, status, reviewer, "still in view", Play/Hide + open in new tab, reason input, then **False alarm / Confirm knife** as two ≥ 48 px buttons side by side; per-entry busy/error; `useLinkedItem('entry')` outline and missing notice; retention line; cameras grid `tileOverlay feature="weapons"` last
- [ ] T024 [US2] Wire `alerts`, `cameras` and `cameras/:id` in `mobile/src/app/routes.tsx` to the new pages; gates; by-eye quickstart §4 steps 1–5 on `-Clip` or `-Mock`. Commit "Home, alerts, cameras and the knife review are built for a phone"

**Checkpoint**: a guard can patrol from the phone.

---

## Phase 5: User Story 3 — Every tool works on a phone (P2) (commit 4)

**Goal**: each tool opens with chips and sheets, shows its result first, and keeps every console fact and action.

**Independent test**: for each tool, walking the console page beside the phone finds nothing missing (the contract's Keep list); the audit shows no overflow at 360 px.

- [ ] T025 [P] [US3] Rebuild `mobile/src/pages/Tools.tsx` from `Tools.dc.html`: Ask and Watch groups from `toolEntries()`, each row with icon, label, blurb, and non-live capability state (research R11)
- [ ] T026 [P] [US3] Rebuild `mobile/src/pages/Attendance.tsx` from `web/src/pages/Attendance.tsx` + `Attendance.dc.html`: mode/group-or-person/date as chips (sheets; date native), Show, Export in the header action slot with inline error, hero heading/sub + stats, follow-up cards (name, status badge, time) or recent-day cards, Notify parent disabled with `attendance.notifyParentWhy` visible, entrance cameras grid, `?mode&subject&date` + `autoRun`
- [ ] T027 [P] [US3] Rebuild `mobile/src/pages/Counting.tsx` (keep CRLF or accept LF: phone-only) from `web/src/pages/Counting.tsx` + `Counting.dc.html`: place/window chips, Show, hero number with `result.sub` verbatim, stats, areas as rows with bar and value (live:false → "demo figure", dashed), `barsTitle` + bars whose segment names/values are listed under each bar (no hover), upper-bound note, cameras `feature="counting"`, 1 s refresh on "Right now" only
- [ ] T028 [P] [US3] Rebuild `mobile/src/pages/LostItems.tsx` from `web/src/pages/LostItems.tsx` + `LostBag.dc.html`: DataNotice, area rows (≥ 44 px checkbox + expand) with camera ticks, offline banner, colour chips with swatches, colour note, watching grid `tileOverlay feature="lost" colour`, empty states using the translated colour name (R10)
- [ ] T029 [P] [US3] Rebuild `mobile/src/pages/Intrusion.tsx` from **`web/src/pages/Intrusion.tsx`** + `Zones.dc.html`: status card, zone rows (Protected/Paused badge; toggle for admin only, 44 px), pause note, period chip, breach cards (zone, time, people, duration, status, watch/hide clip, reason), three empty states, `useLinkedItem('scene')`, plain grid, 15 s/3 s polls
- [ ] T030 [P] [US3] Rebuild `mobile/src/pages/VehicleGate.tsx` from `web/src/pages/VehicleGate.tsx` + `VehicleGate.dc.html`: segmented Live/Movements/Registered (`?tab`), Live stat grid (2 columns, null → "—", notes), errors, and `VehicleAlerts`, gate cameras and `VehicleReader` in order. Movements/Registered render the console components inside `<div className="legacy">`. Bring `mobile/src/components/VehicleAlerts.tsx` level with web first
- [ ] T031 [P] [US3] Restyle Track a person without editing its body: wrap the route element `mobile/src/pages/TrackPerson.tsx` in `.legacy`; add phone CSS for its mode chips (segmented look), form fields stacked, anchor/stop rows, sweep panel, leg player controls ≥ 44 px, and legend. Verify all three modes at 360 px on the clip engine
- [ ] T032 [US3] Gates; audit (quickstart §3) on the seven tool routes in en/light; by-eye quickstart §4 step 6. Commit "Every tool opens with chips and shows its answer first"

---

## Phase 6: User Story 4 — People and More (P2) (commit 5)

**Goal**: the directory, a person, a group, enrolment, More, System health, Settings, Accounts and Sign-in, built for a phone.

**Independent test**: the contract's Keep lists for these screens hold; admin-only controls are hidden for `-DevSignIn it` and work for `admin`.

- [ ] T033 [P] [US4] Rebuild `mobile/src/pages/People.tsx` from `web/src/pages/People.tsx` + `People.dc.html`: search (`?query`), type chips with counts, person cards (initials, name, type badge, `p.sub || p.enrolled`, recognition line, last seen), Track today, Remove (admin, two-step, error), Enrol button (admin) in header action slot, groups rows, all loading/error/empty variants
- [ ] T034 [P] [US4] Rebuild `mobile/src/pages/PersonHistory.tsx` from `web/src/pages/PersonHistory.tsx` + `Person.dc.html`: big initials, name, badges, Track today + Remove (admin, two-step) actions, the console's summary and day-by-day history as cards, back target from navigation state, every state; no camera picture. Record G7/G8 in `gaps.md`
- [ ] T035 [P] [US4] Rebuild `mobile/src/pages/PeopleGroup.tsx` from `web/src/pages/PeopleGroup.tsx`: summary card (`here` null → count only), roster cards → history with `from:'group'`, states
- [ ] T036 [P] [US4] Restyle `mobile/src/pages/Enrol.tsx` via `.legacy` + CSS only; confirm `detections={false}` is intact and the Save-disabled reason shows as text (if it only exists as `title`, add a visible caption in a phone wrapper, not by editing the copy)
- [ ] T037 [P] [US4] Create `mobile/src/pages/More.tsx` from `More.dc.html`; delete `mobile/src/pages/Account.tsx`: account card (name, role, site name when set), rows System health / Settings / Accounts (admin), dark mode toggle (`useTheme`), language segmented (`useLanguage().setLanguage`), Sign out (`useAuth().signOut`)
- [ ] T038 [P] [US4] Rebuild `mobile/src/pages/SystemHealth.tsx` from **`web/src/pages/SystemHealth.tsx`** + `SystemHealth.dc.html`: overall card, pipeline rows with badges, workers per stage collapsible (all figures, `behind`), capacity card (omitted when absent; nulls → "—"; cores wording), `useLinkedItem('camera')` notice, needing-attention grid `detections={false}`, CameraSources (admin) inside `.legacy`
- [ ] T039 [P] [US4] Rebuild `mobile/src/pages/Settings.tsx` from `web/src/pages/Settings.tsx` + `Settings.dc.html`: school profile rows **read-only** with a note (R10/G15), AlertSettings inside `.legacy`, zones summary row → `/intrusion`; appearance/language removed (on More)
- [ ] T040 [P] [US4] Rebuild `mobile/src/pages/Users.tsx` (cards, no dead Edit) and restyle `mobile/src/pages/Login.tsx` (keep pre-account language picker; inputs 16 px; buttons ≥ 48 px) from their web pages
- [ ] T041 [US4] Wire `more` in `mobile/src/app/routes.tsx`; gates; audit on these routes (en/light); check admin vs `it` sign-in. Commit "People, More, System health and Settings are built for a phone"

---

## Phase 7: User Story 5 — Fit, legibility and honesty, proven (P1 for release) (commit 6)

**Goal**: SC-001 to SC-009 measured, gaps reported, and the console unchanged.

**Independent test**: `gaps.md` appendix shows zeros for every route × variant (or a written reason), and the console walk finds no difference.

- [ ] T042 [US5] Run `tools/phone_audit.js` on every contract route in en/light, en/dark, ar/light, ar/dark at 360×780; fix every overflow, small target, low contrast and tiny text in `mobile/src/styles/app.css` or the page; record the final table in `gaps.md` appendix
- [ ] T043 [US5] Honesty sweep: search `mobile/src` for literal numbers or sample text from the canvas ("Mohamed", "Laptop webcam", "10:42", "[SCHOOL", "3 of", "8%"), `Math.random`, and disabled-looking buttons with no handler; `python tools/check_parity.py --no-fixtures`
- [ ] T044 [US5] Engine-down check: stop the engine while the phone is open; within 30 s the top bar says unreachable, Home figures show no numbers, and the bell shows `!` (quickstart §4 step 1)
- [ ] T045 [US5] Console regression: start `mock-admin` at desktop width and compare the bell, Home, Knife detection, Restricted zones and System health with before; `web` tsc
- [ ] T046 [US5] Finalise `specs/015-phone-first-redesign/gaps.md`: final G-list, console defects found (research R10), and what only Mohamed can check on a real phone (quickstart §5)
- [ ] T047 [US5] Add one line to `STATUS.md` (CRLF; only this hunk staged, using `git apply --cached` with a patch of that hunk) and tick FR-15's phone note in `docs/PLAN.md` if it names 375 px/unverified. Full gates; commit "The phone redesign is measured at 360 px and its gaps are written down"

---

## Dependencies & Execution Order

- **Setup (T001–T002)** → **Foundational (T003–T007)** → **US1 (T008–T016)** → then **US2, US3, US4 in parallel** (different files; each shares only `routes.tsx`, whose wiring tasks T024/T041 run one after another) → **US5 (T042–T047)**.
- Within US1: T008 first (every component styles against it), T009/T011/T012 in parallel, then T010, T013 → T014 → T015 → T016.
- Within US2: T017 and T018 before T019/T022; T020, T021 and T023 are independent.
- US3 T030 brings `VehicleAlerts` level first. T031 touches only CSS and the route wrapper.
- `mobile/src/styles/app.css` is shared by every story after T008. Stories add page-specific rules in clearly headed sections at the end of the file, and a merge is only ever appending.

## Parallel Example: after US1 lands

```text
US2: T017 camera parts · T018 today figures · T020 Alerts · T021 Cameras · T023 Knife
US3: T025 Tools · T026 Attendance · T027 Counting · T028 Lost bag · T029 Zones · T030 Vehicles · T031 Track CSS
US4: T033 People · T034 Person · T035 Group · T036 Enrol CSS · T037 More · T038 System · T039 Settings · T040 Users/Login
```

Each worker owns only its listed files, appends its CSS under its own heading, and reports any wording key it needs but could not find instead of adding one. New keys go through the lead (T004 pattern) so the shared catalogue stays byte-identical.

## Implementation Strategy

1. **MVP = US1**: the frame alone fixes navigation, the missing bell and the missing way back on every screen, and ships as commit 2.
2. **US2** next: it is what a guard uses minute to minute, including the knife review.
3. **US3 and US4** in parallel.
4. **US5** closes: measured proof, gaps, console unchanged.
