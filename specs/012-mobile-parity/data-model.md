# Phase 1 — Data model

This feature adds **no data**. It stores nothing, defines no new shape, and asks
the engine for nothing it does not already answer. What follows is therefore not
a schema but the thing this feature actually has to get right: **which file goes
in which pile**, because that is what decides whether the copy stays honest.

## The three piles

Every file in `web/src` lands in exactly one.

### Pile 1 — Truth. Copied byte-for-byte, held byte-for-byte.

Decides *what is true*: what the engine is asked, what comes back, what a value
means, and what words describe it. Contains no layout, so there is no reason for
the phone's copy to differ — and every reason for it not to.

| File | Lines | Why it is truth |
|---|---|---|
| `types.ts` | 625 | The shapes both apps render |
| `services/api.ts` | 1,447 | Every call to the engine |
| `services/wire.ts` | 1,261 | Parsing and validating the engine's answers |
| `services/http.ts` | 285 | The session. Explains at length why no token is stored |
| `services/format.ts` | 684 | Every rendered string: times, dates, percentages, box colour |
| `services/frame.ts` `content.ts` `notes.ts` `ask.ts` | 204 | Frame geometry, page copy, notes, the Ask router |
| `i18n/keys.ts` `en.ts` `ar.ts` `ar.draft.ts` `index.ts` | 2,431 | Every word, both languages, and `DIRECTION` |
| `app/AuthContext.tsx` | 133 | Who is signed in. Stores no role |
| `app/CameraContext.tsx` | 174 | The camera list |
| `app/CapabilityContext.tsx` | 91 | Whether a feature is real, demo or absent |
| `app/SiteContext.tsx` | 104 | Site name, today, timezone |
| `app/LanguageContext.tsx` | 97 | Language, and `documentElement.dir` |
| `app/ThemeContext.tsx` | 32 | Light / dark |
| `app/useAsync.ts` `useAttention.ts` `useAutoRun.ts` `useOptions.ts` | 295 | Loading, error and refresh behaviour |
| `styles/tokens.css` | 89 | The palette. Where the drift already happened |
| **Total** | **7,952** | |

**Rule**: a change to any of these lands in both apps in the same commit.
`tools/check_parity.py` fails the build otherwise.

**Why `format.ts` belongs here and not in the phone's own hands**: it owns
`formatTime`, `formatEventTime`, `attendanceLabel`, `boxColor`. If the phone got
its own copy that was allowed to differ, a time could read `7:42am` on the desk
and `07:42` on the phone for the same event. It is also the one file with real
assertions behind it (`web/scripts/check-format.ts`), which the phone inherits
free — but only while the file is identical.

### Pile 2 — Screens. Copied, then recompiled against the phone's vocabulary.

Decides *what is on screen*: which figures, which actions, which order, which
rules about who may do what. The body is not edited; it simply resolves
`Card`, `PageHeader`, `.row` and friends to phone implementations.

| Group | Files | Lines |
|---|---|---|
| Pages | Home, Attendance, Counting, Intrusion, Weapons, VehicleGate, LostItems, TrackPerson, People, Enrol, PeopleGroup, PersonHistory, Settings, SystemHealth, Users, Login | 6,151 |
| Feature components | CameraSources (1,318), VehicleMovements (584), VehicleRegister (530), CameraFrame (481), VehicleReader (367), PlateEditor (256), VehiclePasses (224), RecordButton (160), VehicleAlerts (159), Plate (101), Logo (26) | 4,206 |

**Not copied**: `Sidebar.tsx` (102) and `TopBar.tsx` (60) — desktop chrome, and
nothing outside the shell imports them.

**Rule**: a page body may be edited only when the phone genuinely needs a
different presentation, and each such edit is its own task with its own reason.
Editing one to change a rule is a defect: the rule lives in Pile 1.

### Pile 3 — Look. Written once, for the phone.

Decides *how it looks*. This is the only pile that is new code.

| File | Lines | What it is |
|---|---|---|
| `components/ui.tsx` | ~350 | The same 14 exports as the console's, with phone bodies |
| `styles/app.css` | ~700 | The phone's stylesheet — `.row` as a stacked card, logical properties for RTL |
| `app/AppShell.tsx` | ~120 | Scrolling content area, bottom tab bar, safe-area insets |
| `app/navigation.ts` | ~90 | Five tabs, built from the copied tool list |
| `app/routes.tsx` | ~110 | The console's `RequireSignIn` / `RequireRole` guards, phone paths |
| `components/CamGrid.tsx` | ~150 | One column, taller tiles |
| `components/CameraModal.tsx` | ~80 | A full-screen sheet rather than a dialog |
| `main.tsx` | ~25 | Mounts the copied providers in the console's order |
| **Total** | **~1,600** | |

## The contract between the piles

`contracts/shell.md` records it precisely. In one line: **Pile 3 must export
every name Pile 2 imports, with the same props and the same meaning.** A phone
`Badge` may be a different shape; it may not be a different tone.

## What is deleted

Not migrated, not adapted — removed, so a stale import cannot compile.

| File | Lines | Why |
|---|---|---|
| `mobile/src/services/mockData.ts` | 392 | Fixtures. Some regenerate at random on each visit |
| `mobile/src/services/api.ts` | 301 | Fixture `runTool`, invented figures |
| `mobile/src/services/ask.ts` | 26 | Fixture question router |
| `mobile/src/types.ts` | 305 | An incompatible shape — `ToolId` is `'attend' \| 'count' \| 'lost' \| 'track' \| 'weapon' \| 'intrude'` where the console's is `'attendance' \| 'counting' \| …`. Replaced by the copy, not merged |
| `mobile/src/pages/ToolPage.tsx` | 456 | One generic screen rendering one invented `ToolAnswer` for every tool. The console has a real page per tool |
| `mobile/src/pages/Home.tsx` `People.tsx` `PeopleGroup.tsx` `PersonHistory.tsx` `SystemPage.tsx` `Account.tsx` `Login.tsx` `Tools.tsx` | 934 | Fixture screens. Replaced by the console's real ones |
| `mobile/src/components/*` `mobile/src/app/*` | ~500 | Replaced by Pile 1 copies and Pile 3 rewrites |

About **1,480 lines of fiction** in the services and types alone.

## State transitions

None introduced. The two the phone must render correctly both already exist in
Pile 1 and are copied whole:

- **A weapon entry**: `waiting → confirmed | false alarm`, decided by a named
  human, never by the app, never deleted. The phone calls the same
  `reviewWeapon`, so the transition is the engine's as before.
- **A session**: `checking → signed in → signed out | revoked`. `AuthContext`
  and `http.ts` copy verbatim, so a revoked session behaves identically on the
  phone.
