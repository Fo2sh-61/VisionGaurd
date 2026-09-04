---

description: "Task list for 012-mobile-parity"
---

# Tasks: The phone does everything the console does

**Input**: Design documents from `/specs/012-mobile-parity/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md), [context.md](./context.md)

**Read [context.md](./context.md) first.** It carries the anchors, the traps and
the baseline. It exists so this list does not need to be read alongside the
source.

**Tests**: No test tasks. There is no JavaScript test runner in this repository
and this feature does not add one — that decision and its consequences are in
`research.md` §8. What replaces them: two typechecks, two checkers, and the
by-eye checks in `quickstart.md`, which each story's checkpoint names explicitly.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on unfinished work
- **[Story]**: Which user story the task serves
- Every task names its exact file path

## Two rules that govern almost every task below

1. **Copy bytes, never text.** This repo has mixed line endings and no
   `.gitattributes`. A copy that reads and re-writes text rewrites every ending
   and turns a clean copy into a whole-file diff. `git diff --stat` catches it.
2. **A copied page body is not edited.** If a page seems to need a change, the
   change belongs in the phone's `ui.tsx` or `app.css`. Editing a page body to
   change a *rule* is a defect — rules live in the copied services.

---

## Phase 1: Setup

**Purpose**: Know where we start, and remove the fiction before adding anything.

- [X] T001 Establish the baseline: run `npm ci` then `node node_modules/typescript/bin/tsc -b --force` in `mobile/`, and record the result at the top of `specs/012-mobile-parity/context.md` §4. `mobile/` has never been typechecked in CI, so any errors found here are pre-existing and must not be attributed to this feature
- [X] T002 Record the engine baseline: run `python -m pytest engine` and write the pass/skip split into `specs/012-mobile-parity/context.md` §4, replacing the collected-only count of 1,539
- [X] T003 Delete the fixture data layer: `mobile/src/services/mockData.ts`, `mobile/src/services/api.ts`, `mobile/src/services/ask.ts`, `mobile/src/types.ts`
- [X] T004 Delete the fixture screens: `mobile/src/pages/Home.tsx`, `Tools.tsx`, `ToolPage.tsx`, `People.tsx`, `PeopleGroup.tsx`, `PersonHistory.tsx`, `SystemPage.tsx`, `Account.tsx`, `Login.tsx`
- [X] T005 Delete the fixture shell and components that will be rewritten: `mobile/src/app/AuthContext.tsx`, `mobile/src/app/ThemeContext.tsx`, `mobile/src/components/CameraFrame.tsx`, `CamGrid.tsx`, `CameraModal.tsx`, `ui.tsx`
- [X] T006 [P] Add the engine proxy to `mobile/vite.config.ts`: copy the `API_PATHS` array and the whole `server.proxy` block from `web/vite.config.ts`, including `changeOrigin: false`, `timeout: 0` and `proxyTimeout: 0`, and the comment explaining why. Keep `port: 5174`. Without this the phone gets no data and every camera tile is a black rectangle
- [X] T007 [P] Update `mobile/index.html`: `viewport-fit=cover` in the viewport meta, and the same Albert Sans preconnect and stylesheet links `web/index.html` carries

**Checkpoint**: `mobile/` does not compile, and should not — everything fake is
gone and nothing real has arrived. About 1,480 lines of fiction removed.

---

## Phase 2: Foundational

**⚠️ BLOCKING**: No user story can start until this phase is complete.

**Purpose**: The copied truth, the checker that holds it, and the phone's
vocabulary — the three things every screen depends on.

### The copy (Pile 1 — byte-for-byte)

- [X] T008 [P] Copy `web/src/types.ts` → `mobile/src/types.ts` as bytes
- [X] T009 [P] Copy all 8 files from `web/src/services/` → `mobile/src/services/` as bytes: `api.ts`, `wire.ts`, `http.ts`, `format.ts`, `frame.ts`, `content.ts`, `notes.ts`, `ask.ts`
- [X] T010 [P] Copy all 5 files from `web/src/i18n/` → `mobile/src/i18n/` as bytes: `index.ts`, `keys.ts`, `en.ts`, `ar.ts`, `ar.draft.ts`
- [X] T011 [P] Copy the 10 context and hook files from `web/src/app/` → `mobile/src/app/` as bytes: `AuthContext.tsx`, `CameraContext.tsx`, `CapabilityContext.tsx`, `LanguageContext.tsx`, `SiteContext.tsx`, `ThemeContext.tsx`, `useAsync.ts`, `useAttention.ts`, `useAutoRun.ts`, `useOptions.ts`
- [X] T012 Resolve the existing palette drift, then copy: `web/src/styles/tokens.css` and `mobile/src/styles/tokens.css` differ today despite a comment in the web file claiming they are byte-identical. Take the web file as canonical (it carries the `@keyframes vg-nextcam` block the phone lacks), correct its now-false comment to point at `contracts/parity.md`, and copy it over `mobile/src/styles/tokens.css`

### The checker that keeps the copy honest

- [X] T013 Write `tools/check_parity.py`: compare each of the 25 files named in `specs/012-mobile-parity/contracts/parity.md` between `web/src` and `mobile/src` using `read_bytes()`, never text mode. On a difference, print a unified diff naming which side is which, and exit non-zero. Add a `--no-fixtures` mode asserting that no `mockData.ts` exists under `mobile/src` and that no file under `mobile/src` contains `Math.random(`
- [X] T014 Run `python tools/check_parity.py` and `python tools/check_parity.py --no-fixtures`; both must pass before any further task

### The phone's vocabulary (Pile 3)

- [X] T015 Write `mobile/src/components/ui.tsx` exporting all 14 names the console's exports, with the props and meanings in `specs/012-mobile-parity/contracts/shell.md`: `toneColors`, `toneGlyph`, `Badge`, `Card`, `CardHeader`, `PageHeader`, `Stats`, `Field`, `Select`, `Toggle`, `DataNotice`, `Empty`, `LoadError`, `StatusDot`. `DataNotice` is load-bearing — a version that renders `null` compiles and silently removes every "demo data" warning in the app
- [X] T016 Write `mobile/src/styles/app.css`: `.row` as a flex column with the first child as headline and the rest as one muted line, `.row--head` hidden, `.stats` two across, `.grid-2/3/4` single-column, thumb-sized `.chip-btn` and `.linkbtn`. Reuse the `.row__name` / `.row__sub` / `.row__chevron` rules already in the file's current version — they are the target shape and are already written. Use logical properties throughout (`padding-inline-start`, never `padding-left`) so Arabic needs no second stylesheet
- [X] T017 Write `mobile/src/app/navigation.ts`: keep the five tabs and their 18×18 icon paths from the file's current version, and build the Tools tab's list from the copied `web/src/app/navigation.ts::NAV` rather than by hand. The fixture list had six tools and no vehicle gate at all
- [X] T018 Write `mobile/src/app/AppShell.tsx`: scrolling content area, bottom tab bar with safe-area insets, tab order following `document.documentElement.dir`
- [X] T019 Write `mobile/src/app/routes.tsx`: copy `RequireSignIn`, `RequireRole` and `SigningIn` verbatim from `web/src/app/routes.tsx`, then declare the phone's routes using the **same paths** as the console — Ask deep links carry query parameters and land on those paths
- [X] T020 Write `mobile/src/main.tsx` mounting the providers in the console's order: `ThemeProvider → AuthProvider → LanguageProvider → SiteProvider → CameraProvider → CapabilityProvider`. `AuthProvider` must be outside `LanguageProvider`, because language is a property of the account

### Camera plumbing

- [X] T021 Copy `web/src/components/CameraFrame.tsx` → `mobile/src/components/CameraFrame.tsx`, then adjust only its container styling. 450 of its 481 lines are overlay maths and polling and must not change: keep `SCALE`, `SNAPSHOT_REFRESH_MS`, `CLOCK_TICK_MS`, `DETECTION_REFRESH_MS` and `BOX_COLOR` exactly
- [X] T022 Write `mobile/src/components/CamGrid.tsx` from `web/src/components/CamGrid.tsx`: one column, taller tiles. **Keep `tileRefreshMs(count)` unchanged** — it is the backpressure rule, and showing fewer tiles must not make the phone ask for more. Never override a page's `detections={false}`; a live `CameraFrame` polls recognition boxes, which carry names
- [X] T023 Write `mobile/src/components/CameraModal.tsx` as a full-screen sheet rather than a centred dialog
- [X] T024 [P] Copy `web/src/components/Logo.tsx` → `mobile/src/components/Logo.tsx`

**Checkpoint**: The phone has a shell, a vocabulary and the truth layer. Parity
passes. No screen exists yet.

---

## Phase 3: User Story 1 — Sign in and see what is true (Priority: P1) 🎯 MVP

**Goal**: A guard signs in with their real account on their phone and sees the
campus as it actually is — or is told plainly that it cannot be reached.

**Independent test**: Stop the engine and open the app: every screen says the
system cannot be reached, with a reason, and shows no figure. Start it: the
figures match the console side by side on the same account.

- [X] T025 [P] [US1] Copy `web/src/pages/Login.tsx` → `mobile/src/pages/Login.tsx`. The fixture version accepted any password and had a role picker; this one does neither
- [X] T026 [P] [US1] Copy `web/src/pages/Home.tsx` → `mobile/src/pages/Home.tsx`
- [X] T027 [US1] Wire Login and Home into `mobile/src/app/routes.tsx` behind `RequireSignIn`, and confirm the Ask tab is the index route
- [X] T028 [US1] Typecheck: `cd mobile; node node_modules/typescript/bin/tsc -b --force`. Any missing `ui.tsx` export shows up here, which is the point of ordering Phase 2 first
- [ ] T029 [US1] Verify against `quickstart.md` checks **1** (nothing is invented — engine stopped), **2** (same numbers on both), **3** (a guard sees a guard's console) and **5** (live pictures actually arrive). Check 5 failing with the rest of the page working means T006 was missed

**Checkpoint**: The phone is honest and signed in. This is the MVP — it can be
shown to Mohamed on its own, and it is already more truthful than the app it
replaces.

---

## Phase 4: User Story 2 — Act on an alert from where you are standing (Priority: P2)

**Goal**: The reason the feature exists. A guard confirms or dismisses a knife
alert in the corridor it was raised in, instead of walking back to a desk.

**Independent test**: A waiting weapon entry is opened, its clip plays, "False
alarm" is pressed, and the decision appears on the console named to that account
— all within 30 seconds of unlocking the phone.

- [X] T030 [US2] Copy `web/src/pages/Weapons.tsx` → `mobile/src/pages/Weapons.tsx` and route it
- [ ] T031 [US2] Give the detection list a phone presentation in `mobile/src/styles/app.css` — the entry, its clip and the two decision buttons must be reachable without scrolling past the video. The buttons are the whole point of the screen; nothing is removed, only arranged
- [ ] T032 [US2] Verify against `quickstart.md` check **4** (acting from the phone), including the 30-second timing, that the entry stays in history, and that a second person pressing Confirm on the same entry is told it was already decided

**Checkpoint**: The phone does the urgent thing. Stories 1 and 2 together are a
defensible pilot.

---

## Phase 5: User Story 3 — The everyday tools (Priority: P3)

**Goal**: All seven tools the console groups under "ask" and "watch", on the
phone, answering the same questions with the same figures.

**Independent test**: The Tools tab lists **ten** entries and every one opens a
working screen whose figures match the console.

- [X] T033 [P] [US3] Copy `web/src/pages/Attendance.tsx` → `mobile/src/pages/Attendance.tsx`
- [X] T034 [P] [US3] Copy `web/src/pages/Counting.tsx` → `mobile/src/pages/Counting.tsx`
- [X] T035 [P] [US3] Copy `web/src/pages/LostItems.tsx` → `mobile/src/pages/LostItems.tsx`
- [X] T036 [P] [US3] Copy `web/src/pages/Intrusion.tsx` → `mobile/src/pages/Intrusion.tsx`
- [X] T037 [P] [US3] Copy `web/src/pages/VehicleGate.tsx` → `mobile/src/pages/VehicleGate.tsx`
- [X] T038 [P] [US3] Copy the 8 vehicle and plate components from `web/src/components/` → `mobile/src/components/`: `VehicleAlerts.tsx`, `VehicleMovements.tsx`, `VehiclePasses.tsx`, `VehicleReader.tsx`, `VehicleRegister.tsx`, `Plate.tsx`, `PlateEditor.tsx`, `RecordButton.tsx`
- [X] T039 [US3] Copy `web/src/pages/TrackPerson.tsx` → `mobile/src/pages/TrackPerson.tsx`. At 1,738 lines this is the largest screen in the product — live tracking, past sweeps and 30-second clip playback. Look at it on a 375 px screen before deciding whether it needs its own presentation, and do not pre-emptively rewrite it
- [X] T040 [US3] Route all seven tools in `mobile/src/app/routes.tsx` and confirm the Tools tab renders ten entries from `NAV`
- [ ] T041 [US3] Give the vehicle register and movements tables a phone presentation. They are the widest tables in the product (`'1.5fr .7fr 1.4fr 1.5fr .9fr .9fr'`); the `.row` rule from T016 handles the common case, and these are checked by eye to confirm it reads well. **No column's information may be dropped** — detail moves one tap away, it does not disappear
- [ ] T042 [US3] Verify against `quickstart.md` checks **2** (same numbers), **6** (overlays name only what they should — green names a person, blue says only "same body", amber unidentified) and **9** (nothing missing: all 16 destinations, ten tools)

**Checkpoint**: Everything a guard asks during a shift works on the phone.

---

## Phase 6: User Story 4 — Manage people (Priority: P4)

**Goal**: The directory, one person's history, a group's roster, and enrolling a
new face — from a phone, whose camera may be better for the job than a laptop's.

**Independent test**: An administrator enrols somebody using the phone's camera
with the same five-photo floor and quality scoring, and that person is recognised
afterwards without a restart. A guard sees no enrolment action at all.

- [X] T043 [P] [US4] Copy `web/src/pages/People.tsx` → `mobile/src/pages/People.tsx`
- [X] T044 [P] [US4] Copy `web/src/pages/PeopleGroup.tsx` → `mobile/src/pages/PeopleGroup.tsx`
- [X] T045 [P] [US4] Copy `web/src/pages/PersonHistory.tsx` → `mobile/src/pages/PersonHistory.tsx`
- [X] T046 [US4] Copy `web/src/pages/Enrol.tsx` → `mobile/src/pages/Enrol.tsx` and route it under `RequireRole role="admin"`, matching the console
- [ ] T047 [US4] Confirm `Enrol.tsx` works against a phone camera on a real device: the live moving view, the outlined face, the five tracking points and the quality score. A phone's front camera may behave differently from a laptop's — this is unmeasured and needs Mohamed. If it does not work, report it rather than removing the screen
- [ ] T048 [US4] Verify: the People tab reaches the directory, a person's history and a group roster; a guard account sees no enrolment or removal action, and is refused by the engine when the URL is typed

**Checkpoint**: The people half of the product is on the phone.

---

## Phase 7: User Story 5 — Run the system (Priority: P5)

**Goal**: See what is broken, add a camera, change a setting, manage an account —
from a phone, which is where IT actually is when a camera stops.

**Independent test**: System Health shows the real per-subsystem state including
startup failure reasons, and stays answerable when a subsystem is down.

- [X] T049 [P] [US5] Copy `web/src/pages/SystemHealth.tsx` → `mobile/src/pages/SystemHealth.tsx`
- [X] T050 [P] [US5] Copy `web/src/pages/Settings.tsx` → `mobile/src/pages/Settings.tsx`
- [X] T051 [P] [US5] Copy `web/src/pages/Users.tsx` → `mobile/src/pages/Users.tsx` and route it under `RequireRole role="admin"`
- [X] T052 [US5] Copy `web/src/components/CameraSources.tsx` → `mobile/src/components/CameraSources.tsx`. At 1,318 lines it holds the recorder probing and the add/edit forms
- [ ] T053 [US5] Give the camera channel list a phone presentation. It is the one table using fixed pixel columns (`'64px 1fr 1fr 44px'`) rather than fractions, so the `.row` rule from T016 must be checked against it specifically
- [ ] T054 [US5] Give System Health's worker table a phone presentation — per worker: frames processed, last inference ms, queue depth, dropped frames, and whether it is behind. Frames deliberately not decoded must stay visibly separate from frames dropped; they are not the same thing
- [X] T055 [US5] Route System Health and camera setup under the System tab, and Settings and Users under the Account tab, per `research.md` §7
- [ ] T056 [US5] Verify: with a subsystem stopped, System Health still answers with a reason rather than failing; the capacity projection's two bars stay separate and keep their **measured here** / **estimate** labels

**Checkpoint**: All 16 screens exist. Parity is structurally complete.

---

## Phase 8: User Story 6 — Arabic, right to left (Priority: P6)

**Goal**: The phone reads in Arabic for the guards who read Arabic, and follows
the account rather than the browser on a shared gate phone.

**Independent test**: Switching to Arabic mirrors every screen including the tab
bar, with no English left except names, plates and camera identifiers. Signing
out and in as a different account changes the language with it.

- [X] T057 [US6] Audit `mobile/src/styles/app.css` for physical properties and replace them with logical ones — `padding-left` → `padding-inline-start`, `margin-right` → `margin-inline-end`, `text-align: left` → `text-align: start`. `LanguageContext` already sets `document.documentElement.dir`, so this is all that stands between the phone and a mirrored layout
- [X] T058 [US6] Make the bottom tab bar in `mobile/src/app/AppShell.tsx` order itself by `dir`, and check the tab labels come from `i18n` under `nav.<id>.label` rather than being hardcoded
- [ ] T059 [US6] Verify against `quickstart.md` check **7**: every screen mirrors, the language follows the account across a sign-out and a different sign-in, and the Arabic stays dev-only exactly as on the console — it is the same unproofread draft and this feature does not correct it

**Checkpoint**: Both languages, both directions.

---

## Phase 9: Polish & Cross-Cutting

**Purpose**: Make the gates real, make it runnable by a double-click, and make
the documents stop lying.

- [X] T060 [P] Add a `mobile:` job to `.github/workflows/ci.yml`, mirroring the existing `web` job: `windows-latest`, `node-version: 20`, `cache-dependency-path: mobile/package-lock.json`, `npm ci`, then `node node_modules/typescript/bin/tsc -b --force`. Not `npx` — it has failed to resolve the local binary on Windows, and a gate that fails for its own reasons is worse than no gate
- [X] T061 [P] Add `python tools/check_parity.py` and `python tools/check_parity.py --no-fixtures` to the `engine` job in `.github/workflows/ci.yml` — it is Python and needs no Node — and update the file's opening comment, which currently says "the four gates"
- [X] T062 Update `dev.ps1`: add `$MobilePort = 5174` beside `$WebPort`, a `-Mobile` switch, a third npm job in `Invoke-Up`, port 5174 in `Clear-Ports` and `Invoke-Down`, both checkers in `Invoke-Test`, and a line in `Show-Help`
- [X] T063 [P] Pass `-Mobile` through `launch.ps1` so the desktop shortcut can start the phone app too, and confirm the new process is inside the Win32 job object — closing the window must still stop everything
- [X] T064 [P] Rewrite `mobile/README.md`. It currently describes the fixture app: "same fixtures, same front-end-only scope", "Sign in with any password", and a `services/mockData.ts` in its layout diagram. All three are about to be false
- [X] T065 [P] Update `docs/PLAN.md`: P9's mobile half is superseded by this spec — record that, and leave notifications in P9 untouched. Point `FR-15` ("Mobile on real data | missing") at `specs/012-mobile-parity`
- [X] T066 Update the `Mobile app` row in `STATUS.md`, which says "**Fake** — entirely fixtures, including random numbers". Write what is actually true when it is true, including anything that did not work — `STATUS.md` is CRLF, so edit it as bytes
- [ ] T067 Run the whole of `quickstart.md` end to end against `.\dev.ps1 up -Clip -Mobile -AllowSystemPython`, including check **8** (one hand at 375 px, both themes, no sideways scrolling anywhere) and check **10** (a failed action says so — turn off Wi-Fi mid-action)
- [X] T068 Run the four existing gates plus the two new ones and confirm nothing regressed: `python -m pytest engine` (count must not drop from the T002 baseline), `python -m pyflakes engine/vg engine/tools engine/tests`, `tsc -b --force` in both `web/` and `mobile/`, and both parity checks
- [X] T069 Confirm `web/` is untouched: `git diff --stat web/` should show only `web/src/styles/tokens.css` from T012, and nothing else. If it shows more, something leaked into the console

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)** — starts immediately
- **Phase 2 (Foundational)** — depends on Phase 1. **Blocks every story**
- **Phases 3–8 (Stories)** — all depend on Phase 2. After it, they are
  independent of each other and can run in any order or in parallel
- **Phase 9 (Polish)** — depends on whichever stories are being shipped

### Story dependencies

None between stories. Each copies a different set of page files against a shell
that already exists. US1 is listed first because it is the MVP, not because
anything needs it.

The single ordering constraint inside a story: **copy the page, then typecheck,
then tune the presentation**. Tuning before the typecheck means guessing at what
the page renders.

### Parallel opportunities

- **Phase 2**: T008–T011 are four independent copies. T015–T020 are six
  independent new files. Copies and writes can overlap; T013's checker only
  needs T008–T012 finished before T014 runs it
- **Phase 5**: T033–T038 are six independent copies
- **Phase 6**: T043–T045 are three independent copies
- **Phase 7**: T049–T051 are three independent copies
- **Phase 9**: T060, T061, T063, T064, T065 touch five different files

### Parallel example: Phase 2's copy

```bash
# Four independent byte copies — no ordering between them:
Task: "Copy web/src/types.ts to mobile/src/types.ts"
Task: "Copy web/src/services/ (8 files) to mobile/src/services/"
Task: "Copy web/src/i18n/ (5 files) to mobile/src/i18n/"
Task: "Copy the 10 context and hook files from web/src/app/ to mobile/src/app/"
```

---

## Implementation Strategy

### MVP first

1. Phase 1 — Setup
2. Phase 2 — Foundational (blocks everything)
3. Phase 3 — US1: sign in and see what is true
4. **Stop and show Mohamed.** At this point the phone is honest, which the app it
   replaces never was. Everything after adds screens to a working app

### Incremental delivery

Each story is a shippable increment against a phone that already works:

| After | The phone can |
|---|---|
| US1 | Be trusted — real sign-in, real figures, honest when it cannot reach the engine |
| US2 | Do the urgent thing — decide a knife alert where it happened |
| US3 | Answer a shift's questions — all seven tools |
| US4 | Manage people, and enrol from a phone camera |
| US5 | Run the system — health, cameras, settings, accounts |
| US6 | Be read in Arabic |

### If time runs short

Stop after a completed story, never mid-story. A story left half-copied leaves
routes pointing at screens that do not exist — worse than not starting it. Report
which stories are done and which are not; do not describe a partial phase as
complete.

---

## Notes

- **69 tasks.** 6 stories, 24 foundational and setup tasks, 10 polish.
- The dominant activity is copying, not writing. Roughly 19,000 lines are copied
  and about 1,600 written — see `plan.md`.
- Commit per task or per logical group. Every commit that changes a file on the
  parity list must change both copies.
- `web/` is not modified by this feature except `tokens.css` in T012, and T069
  checks that.
- Anything found that turns out to be a real problem — a page that cannot work on
  a phone, an engine gap, a pre-existing failure — gets reported, not worked
  around silently. A pre-existing failure is information.

---

## What was actually done, 3 September 2026

**Built and proven by machine.** Phases 1-8 implementation, and Phase 9's
tooling and documents. Gates at the end of the run:

| Gate | Result |
|---|---|
| `tsc -b --force` in `mobile/` | **0** — all 16 copied pages compile |
| `tsc -b --force` in `web/` | **0** — the console did not regress |
| `npm run build` in `mobile/` | **0** — 90 modules, 414 kB |
| `python -m pytest engine` | **0 failures**, ~35 skipped (camera-marked) |
| `python -m pyflakes ...` | **0** |
| `python tools/check_parity.py` | 26 files identical |
| `... --no-fixtures` | nothing invented |

Loaded in a browser at 375px with the engine deliberately stopped: the real
sign-in page renders, `scrollWidth == clientWidth == 375` (no sideways
scroll), switching to Arabic flips `dir` to `rtl` with the wording in Arabic
and still no overflow, and `/auth/me` is requested **on the phone's own
origin** — which is the proxy working — fails, and the app shows sign-in
rather than inventing a session.

**Left open deliberately.** Everything below needs a running engine, a real
phone, or Mohamed's eyes. None of it can be claimed from here.

- **T029, T032, T042, T047, T048, T056, T067** — the by-eye checks in
  `quickstart.md`. Nothing past the sign-in screen has been looked at, because
  reaching it needs an engine and an account.
- **T031, T041, T053, T054** — the per-screen presentation work. The
  *mechanism* is in place (`.row` folds; inline grids and fixed-width inputs
  are handled in `app.css`), but whether each screen reads well is exactly the
  thing that cannot be asserted without looking.
- **T059** — Arabic was confirmed on the sign-in page only.
- **T068, T069** — run and checked, but `web/` was being edited by another
  session throughout, so "the console is untouched" could only be confirmed for
  the files this work changed, not by a clean `git diff`.
