---

description: "Task list for the Arabic console"
---

# Tasks: Arabic console

**Input**: Design documents from `/specs/008-arabic-console/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: Included. The constitution requires test-first development for
business rules and regression fixes, and this feature changes a wire contract.
No web test framework is added — see `research.md` decision 8.

**Organization**: Grouped by user story. The stories are slices of the single
primary story in the spec, chosen so each one is worth shipping on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4
- Every task names its file

## Path Conventions

Engine at `engine/vg/`, console at `web/src/`, mobile shell at `mobile/src/`.

> **Before editing any file**: `api/*.py`, `services/*.ts`, `types.ts` and
> `STATUS.md` are **CRLF** and the repo has no `.gitattributes`. Read/write
> bytes or check `b"\r\n" in path.read_bytes()` first. `git diff --stat`
> catches a whole-file rewrite. See `context.md` §3 trap 1.

---

## Phase 1: Setup

**Purpose**: empty structures, no behaviour change

- [X] T001 Create `web/src/i18n/` with empty `keys.ts` (exports `type MessageKey = never` for now), `en.ts`, `ar.ts`, `ar.draft.ts` and `index.ts`
- [X] T002 [P] Create `engine/vg/api/notes.py` with an empty `CODES` frozenset and a `note(code, **args) -> S.Note` helper that raises on an unregistered code
- [X] T003 [P] Add a **P11 — Arabic console** phase to `docs/PLAN.md` §5, after P10, so the `P11-FR-xxx` numbering in the spec has a home

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the machinery that makes a language choosable. Nothing is
translated yet — at the end of this phase you can switch to Arabic and the
console is still entirely English, visibly falling back.

**⚠️ CRITICAL**: no user story can begin until this phase is complete

### Contract

- [X] T004 Add `class Note(Wire)` with `code: str` and `args: dict[str, str | int | float] = {}` to `engine/vg/api/schemas.py`
- [X] T005 Mirror `Note` in `web/src/types.ts` and `web/src/services/wire.ts`
- [X] T006 [P] Write `engine/tests/test_notes.py`: walk the AST of `engine/vg/**/*.py` and assert every `note(...)` code is in `CODES`, and every code in `CODES` is emitted somewhere

### The catalogue

- [X] T007 Implement `t(key, args?)` and the resolution order `ar` → `ar.draft` (dev builds only) → `en` in `web/src/i18n/index.ts`, typing `en.ts` as `Record<MessageKey, string>` and both Arabic files as `Partial<Record<MessageKey, string>>`
- [X] T008 Create `web/src/services/notes.ts` rendering a wire `Note` through `t()`, with an unrecognised code falling back to `t('note.unknown', { code })`

### Where the language lives

- [X] T009 [P] Write the engine test for the language column and endpoint in `engine/tests/test_auth.py` — default `'en'`, round-trip through `POST /auth/language`, `422` on an unknown value, and a caller cannot change another account's language
- [X] T010 Add `language TEXT NOT NULL DEFAULT 'en'` to `app_user` in `engine/vg/auth/store.py`, copying the `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` guard from `engine/vg/events/vehicles.py:293-296`; add `User.language` and `UserStore.set_language()`
- [X] T011 Add `language: Literal["en","ar"] = "en"` to `class Account` in `engine/vg/api/schemas.py`
- [X] T012 Add `POST /auth/language` to `engine/vg/api/app.py` — own account only, no `user_id` parameter, not audited, returns the updated `Account`
- [X] T013 Add `language` to the `Account` interface in `web/src/app/AuthContext.tsx` and the call in `web/src/services/api.ts`

### Applying it

- [X] T014 Create `web/src/app/LanguageContext.tsx` copying the shape of `web/src/app/ThemeContext.tsx`, resolving in the order account → `localStorage['vg.lang']` → `navigator.language` → `'en'`, and setting `lang` and `dir` on the document element
- [X] T015 Mount `LanguageProvider` in `web/src/main.tsx` (**not** `AppShell.tsx` — the providers live in `main.tsx`; the plan named the wrong file)
- [X] T016 Add a language selector to the "how the console looks" card in `web/src/pages/Settings.tsx`, beside the dark-mode `Toggle`
- [X] T017 Add a language toggle to `web/src/pages/Login.tsx` that writes `localStorage['vg.lang']`, so the sign-in page is readable before any account exists

**Checkpoint**: language can be chosen, persists across sign-ins and browsers, and the page direction flips. Every word is still English.

---

## Phase 3: User Story 1 — The console speaks Arabic (Priority: P1) 🎯 MVP

**Goal**: every string the console owns is Arabic, and the page reads right to
left. Engine explanations are still English and visibly falling back — which is
honest, and is what makes this shippable on its own.

**Independent Test**: switch to Arabic and walk every page. Navigation,
headings, buttons, table columns, badges, empty states, loading states and load
errors are Arabic and read right to left. The camera picture is unchanged.

### Window labels stop being English

- [X] T018 [US1] Update the window tests in `engine/tests/test_api.py` to send tokens (`today`, `last7`, `last30`, `last90`, `schoolYear`, `all`) — they must fail before T019
- [X] T019 [US1] Rekey `WINDOW_DAYS` (line 48) and `WEAPON_WINDOWS` (line 61) to tokens in `engine/vg/api/app.py`, keeping the two sets separate as the comment at line 56 requires; update `window_days()`, `weapon_window()`, `get_breaches` and `get_weapons` to `Literal` query types
- [X] T020 [US1] Send tokens from `web/src/services/api.ts` and `mobile/src/services/api.ts`, and move the window wording into the catalogue as `window.*`
- [ ] T073 [US1] **Found during implementation**: `/count?when=Right now` is a *third* English label used as a protocol value (`engine/vg/api/app.py:2222`, compared in `live.py:2006-2019` and `store.py:361,667`). Token-ise it to `now` / `todayByHour` / `weekByDay` with the wording in `count.window.*`. **Deferred**: it edits `engine/vg/api/store.py`, which another session is changing — do it alongside T046.

### Extract and draft, one area at a time

Each task: move the strings into `keys.ts` + `en.ts`, replace them with `t()`
calls, and draft the Arabic into `ar.draft.ts`. **Never join translated
fragments** — pass parameters (`P11-FR-001`).

- [X] T021 [P] [US1] Shell and navigation — `web/src/app/navigation.ts`, `app/AppShell.tsx`, `app/routes.tsx`, `components/Sidebar.tsx`, `components/TopBar.tsx`, `components/ui.tsx`
- [X] T022 [P] [US1] Home and attention — `web/src/pages/Home.tsx`, `app/useAttention.ts`, `services/content.ts`
- [X] T023 [P] [US1] Cameras — `components/CamGrid.tsx`, `components/CameraFrame.tsx`, `components/CameraSources.tsx`. **There is no `pages/Cameras.tsx`** — the plan invented it
- [X] T024 [P] [US1] People and enrolment — `web/src/pages/People.tsx`, `pages/PeopleGroup.tsx`, `pages/PersonHistory.tsx`, `pages/Enrol.tsx`, `pages/Users.tsx` (the plan missed the two sub-pages)
- [X] T025 [P] [US1] Attendance and counting — `web/src/pages/Attendance.tsx`, `pages/Counting.tsx`
- [X] T026 [P] [US1] Track — `web/src/pages/TrackPerson.tsx` (72 strings, the largest single file)
- [X] T027 [P] [US1] Weapons, intrusion and lost items — `web/src/pages/Weapons.tsx`, `pages/Intrusion.tsx`, `pages/LostItems.tsx`
- [X] T028 [P] [US1] Vehicles — `pages/VehicleGate.tsx`, `components/VehicleRegister.tsx`, `components/VehicleMovements.tsx`, `components/VehicleReader.tsx`, `components/VehiclePasses.tsx`. `PlateEditor.tsx` needed nothing — its only literals are key names and a font stack
- [X] T029 [P] [US1] Settings and health — `web/src/pages/Settings.tsx`, `pages/SystemHealth.tsx`
- [X] T030 [P] [US1] Sign-in — `web/src/pages/Login.tsx`
- [X] T031 [US1] Wording functions in `web/src/services/format.ts` — `attendanceLabel` (258), `attendanceStatusLine` (285), `matchLabel` (193), `vehicleCategoryLabel` (239), `formatSchedule` (317) — take a language parameter and return `t()` output. Dates and numbers are US3, not this task
- [X] T032 [US1] Client-side error wording in `web/src/services/api.ts` and `web/src/services/http.ts`

### Right to left

- [X] T033 [US1] Convert the physical direction properties in `web/src/styles/app.css` to logical equivalents. **Only 4 of the 10 were interface** — the other 6 are `.camframe__*` picture geometry and stay physical, now annotated as deliberate
- [X] T034 [US1] Pin `dir="ltr"` on the picture container in `web/src/components/CameraFrame.tsx` (rect at 244–249) so overlay geometry can never mirror — `P11-FR-009`
- [X] T035 [P] [US1] Audit the 42 inline directional styles in `web/src/**/*.tsx`; convert layout ones, leave `CameraFrame`'s `left:`/`top:` percentages physical

**Checkpoint**: US1 complete. An Arabic-reading guard can use the console. Engine explanations still read English.

---

> **Scope correction, measured 29 Aug 2026 — read this before re-planning.**
>
> The plan counted **65** engine prose sites, from an AST scan of the keywords
> `reason`, `detail`, `note`, `label`, `title`. Two wider scans since:
>
> | Scan | Found |
> |---|---|
> | Plan's keyword scan | 65 |
> | Every string literal passed to any `S.*` wire constructor | **164** |
> | Every sentence-like literal outside docstrings in `live.py`, `store.py`, `archive.py` | **~254** |
>
> The last number is the real one, because the prose does not only sit at the
> constructor. It is also in **class constants** (`NO_RECORDER`,
> `NO_CAMERAS`), in **helper returns** (`_lost_state()`, `_cameras_reading()`,
> `_history()` all return prose), in **lookup dicts** (the `states` map behind
> `Capability.reason`), and in `SubsystemUnavailable(...)` messages that become
> a 503 body. Classifying all ~139 not-yet-converted literals by destination
> found essentially **none that fail to reach a screen** — so there is no
> subset that can honestly be scoped out.
>
> Converting them means changing helper *signatures* through the middle of
> `live.py` (3,700 lines), and every field converted also needs its render site
> changed in the console and the mobile shell.
>
> **What was tried, and undone.** Two attempts, both reverted to keep the tree
> green rather than half-migrated:
>
> 1. Retyping the 21 wire fields alone → 1311 passing tests became 7 collection
>    errors, because both stores emit into those fields.
> 2. An AST-offset pass converting 115 constructor sites automatically → left
>    22 computed values (`reason or 'Not running.'`, `self.NO_RECORDER`,
>    conditional literals) that each need a helper refactor, and no console
>    rendering for any of the 15 changed wire fields.
>
> **What is in place and green**: the `Note` wire type, `engine/vg/api/notes.py`
> with its `note()` guard, and `engine/tests/test_notes.py`. The registry is
> deliberately empty — a declared code with no emitter fails its own test.
>
> **Re-estimate before restarting.** The whole of Phase 4 has to land in one
> pass: schema retype, every emitter, every helper that returns prose, both
> stores, both front ends. There is no safe half.

## Phase 4: User Story 2 — The engine's explanations speak Arabic (Priority: P2)

**Goal**: the sentences that say *why* something is unavailable stop being
English prose inside Python. This is the load-bearing half of the feature and
the reason it exists.

**Independent Test**: open the vehicle gate with no exit camera. The reason is
Arabic and still says **cars leaving are not being counted** — cause *and*
consequence (`P11-FR-006`). Open System Health with a subsystem down; every
state and failure reason is Arabic.

### Retype the wire

- [ ] T036 [US2] Retype the 19 prose fields listed in `data-model.md` §6 to `Note | None` in `engine/vg/api/schemas.py`, and **leave every field in the "stays `str`" table alone** — `dismissal_reason`, `WeaponReview.reason`, `ZoneOverlay.label`, the vehicle `unit` fields, `DirectoryPerson.detail`, `plate_display`, `AuditEntry.subject`/`detail`
- [ ] T037 [US2] Delete `Metric.label` (schemas.py:287) and `AttendanceTrend.label` (852); map `metric.*` from `key` and the trend caption from `date` in the console
- [ ] T038 [US2] Split `Box.label` — it keeps the **name** meaning only; class wording (`"Person in zone"`, `"Knife-shaped object"`) moves to `Box.kind` and is labelled by the console. See `context.md` §3 trap 2
- [ ] T039 [US2] Resolve `CountBar.label` — find which buckets have no `at: Instant`; where `at` is present the console formats the caption and the field goes. `context.md` §5 item 2
- [ ] T040 [US2] Move `AlertRule.title`/`detail` and `DeliveryTarget.title` off the wire and into the catalogue — first confirm they are demo-only, `context.md` §5 item 3

### Emit codes

- [ ] T041 [US2] Replace the 26 prose sites in `engine/vg/api/live.py` with `note(...)` calls per `contracts/notes.md`, and register each code in `engine/vg/api/notes.py`
- [ ] T042 [US2] Replace the error details at `engine/vg/api/app.py` lines 86, 176, 1482, 1606, 1615, 1646, 1654 with note payloads
- [ ] T043 [P] [US2] Replace the two details at `engine/vg/auth/deps.py` lines 195, 215 — and do **not** let `language` become readable there
- [ ] T044 [P] [US2] Replace the two sweep-estimate reasons at `engine/vg/ingest/archive.py` lines 1019, 1038
- [ ] T045 [US2] Find where "Sign-in is unavailable, so nothing can be served. See System Health." is built — it was seen at runtime but missed by the AST scan — and convert it and any siblings. `context.md` §3 trap 11
- [ ] T046 [US2] Replace the 28 prose sites in `engine/vg/api/store.py` (`MockStore`) with `note(...)`, using the `demo.` prefix for demo-only wordings

### Render them

- [ ] T047 [US2] Make `web/src/services/http.ts` accept an object `detail` and render it through `services/notes.ts`, **keeping the existing string branch** (lines 144–149) so a half-migrated engine degrades to English rather than `[object Object]`
- [ ] T048 [US2] Render every `Note` field through `services/notes.ts` at its page, and draft Arabic for every registered code in `ar.draft.ts`
- [ ] T049 [P] [US2] Update `mobile/src/types.ts`, `services/api.ts`, `services/mockData.ts`, `pages/PersonHistory.tsx`, `pages/ToolPage.tsx` so the mobile shell compiles against the new types and shows the English fallback. Do not localise it
- [ ] T050 [US2] Re-run the AST scan from `research.md` and confirm the only prose left is the four excluded sites (1 FastAPI title, 3 internal `identity/gallery.py` reasons)

**Checkpoint**: US1 and US2 both work. Every sentence on screen comes from the console.

---

## Phase 5: User Story 3 — Numbers, dates and the audit trail (Priority: P3)

**Goal**: a date reads as an Arabic date, a number uses the school's digits, and
the audit trail is readable by whoever opens it.

**Independent Test**: the same event shows the same clock time in both
languages, with Arabic month and day names in Arabic. Switch the site digit
setting and the digits change without the language changing.

- [ ] T051 [US3] Add `digits: Literal["western","arabic"] = "western"` to `class SiteInfo` in `engine/vg/api/schemas.py` and plumb it from site configuration through `engine/vg/config.py`. `context.md` §5 item 1
- [ ] T052 [US3] Route `formatTime` (41), `formatClock` (64), `formatEventTime` (84), `formatLongDate` (101), `formatShortDate` (112) and `formatDuration` (119) in `web/src/services/format.ts` through `Intl.DateTimeFormat` with the active language
- [ ] T053 [US3] Route `formatCount` (202) and `formatPercent` (205) through `Intl.NumberFormat`, selecting `-u-nu-arab` or `-u-nu-latn` from `SiteInfo.digits`
- [ ] T054 [US3] Write a regression test asserting the instant arithmetic at `format.ts:34` is unchanged and no `timeZone` is passed to `Intl` — the offset is per-instant, and passing a timezone reintroduces the bug P0-03 fixed
- [ ] T055 [US3] Confirm `VehiclePass.plate_display` renders identically in both languages and is **not** passed through `Intl` — `engine/vg/platetext.py` already owns plate digits
- [ ] T056 [US3] Add catalogue entries for the ~20 audit action tokens (`vehicle.pass.delete`, `track.search`, `weapon.confirmed`, `recording.start`, `path.sweep`, …) and render them through `t()` — `P11-FR-018`
- [ ] T057 [US3] Fix the `_log` call sites that pass prose as `subject` — `_log(actor, "vehicle.export", "vehicle passes", …)` and its siblings — to pass data or nothing
- [ ] T058 [US3] Make exports carry the exporter's language, with the audit entry still written **before** the file is built — `P11-FR-019`

**Checkpoint**: all three stories work. Dates, numbers, plates and the audit trail are correct in both languages.

---

## Phase 6: User Story 4 — Review, and the release gate (Priority: P4)

**Goal**: "reviewed by a native speaker" becomes a number on screen and a
condition on the build, instead of a promise.

**Independent Test**: Settings shows approved / draft / missing counts. A
development build renders drafts; a release build does not and falls back to
English.

- [ ] T059 [US4] Compute approved / draft / missing counts from the catalogues at runtime in `web/src/i18n/index.ts`
- [ ] T060 [US4] Show those counts on an admin-only card in `web/src/pages/Settings.tsx` — `P11-FR-003`
- [ ] T061 [US4] Exclude `ar.draft.ts` from release builds so nothing unreviewed reaches a guard — `P11-FR-004`
- [ ] T062 [US4] Review pass with Mohamed: move approved wordings from `ar.draft.ts` into `ar.ts`, correcting as he directs
- [ ] T063 [US4] Confirm the draft count is **zero** before release — `SC-005`
- [ ] T064 [US4] Verify `note.unknown` by sending a made-up code from the engine: a named unavailability appears, never a blank — `P11-FR-007`

**Checkpoint**: the review state is visible and enforced.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T065 [P] Correct the claim in `AGENTS.md` that "format.ts owns every rendered string" — it was false before this feature and true after it; say how the engine now sends codes
- [ ] T066 [P] Update `STATUS.md` with what Arabic actually covers today
- [ ] T067 [P] Mark P11 done in `docs/PLAN.md` with its date
- [ ] T068 Run `python -m pytest engine` — passing count must be **above 1299** and no new failure. The 2 pre-existing `TestWireShape` failures are `store.py:31`'s frozen `TODAY` and are not this feature's
- [ ] T069 Run `cd web; npx tsc -b --force` (never `tsc --noEmit`) and `python -m pyflakes engine/vg engine/tools engine/tests`
- [ ] T070 Run `.\dev.ps1 up -Clip` and confirm on the recorded clip that the picture and every box are pixel-identical in both languages — `SC-006`
- [ ] T071 Walk `quickstart.md` end to end
- [ ] T072 Ask Mohamed for the manual check: wording quality, a sentence containing a Latin camera name or a plate not scrambling, and RTL at phone width

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks every story**
- **US1 (Phase 3)**: depends on Foundational
- **US2 (Phase 4)**: depends on Foundational. Independent of US1 in principle, but its Arabic wordings land in the catalogue US1 builds, so US1 first is the cheaper order
- **US3 (Phase 5)**: depends on Foundational. Genuinely independent of US1 and US2
- **US4 (Phase 6)**: depends on there being drafts to review — in practice after US1 and US2
- **Polish (Phase 7)**: after the stories you intend to ship

### Within each story

- Tests before the change they cover: T018 before T019, T009 before T010–T012, T006 before T041
- Contract before emitters: T036 before T041, T042, T046
- Emitters before renderers: T041–T046 before T048
- `t()` before any extraction: T007 before T021–T032

### Parallel Opportunities

- T002 and T003 in Setup
- T006 and T009 in Foundational — different test files
- **T021–T030 are the big one**: ten extraction tasks over disjoint file sets, all parallel once T007 lands
- T043 and T044 — different engine files
- T049 alongside T047/T048 — mobile is a separate tree
- T065, T066 and T067 — three different documents

### Not parallel, and why

- T021–T032 all append to `keys.ts` and `en.ts`. The *page* edits are disjoint; the **catalogue files are shared**. Either serialise the catalogue writes or split the catalogue per area and re-export from `keys.ts`.
- T036 retypes `schemas.py`, which T041–T046 all import. It must land first and alone.

---

## Parallel Example: User Story 1

```bash
# Once T007 (the t() function) exists, the ten extraction tasks are disjoint:
Task: "Shell and navigation — navigation.ts, AppShell, routes, Sidebar, TopBar, ui"
Task: "Home and attention — Home.tsx, useAttention.ts, content.ts"
Task: "Cameras — Cameras, CamGrid, CameraFrame, CameraSources"
Task: "People and enrolment — People, Enrol, Users"
Task: "Attendance and counting — Attendance, Counting"
Task: "Track — TrackPerson.tsx"
Task: "Weapons, intrusion and lost items"
Task: "Vehicles — six components"
Task: "Settings and health"
Task: "Sign-in — Login.tsx"
```

---

## Implementation Strategy

### MVP (Foundational + US1)

1. Phase 1 Setup
2. Phase 2 Foundational — **blocks everything**
3. Phase 3 US1
4. **Stop and validate**: an Arabic-reading guard can work a full shift. Engine
   explanations still read English, visibly falling back — honest, and the thing
   US2 fixes.

### Incremental delivery

1. Foundational → a language can be chosen; nothing is translated yet
2. + US1 → the console speaks Arabic (**MVP**)
3. + US2 → the explanations speak Arabic too — the reason the feature exists
4. + US3 → dates, digits and the audit trail
5. + US4 → the review state is visible and enforced

### Order to prefer

US2 is the load-bearing half, but US1 first is cheaper: US2's wordings land in a
catalogue that US1 has already built and proved. Doing US2 first means building
the catalogue machinery twice.

---

## Notes

- **Never join translated fragments.** `t('attendance.late', {minutes, cutoff})`,
  never `t('arrived') + n + t('afterCutoff')`. Arabic does not order fragments
  the way English does. This is `P11-FR-001` and the requirement most likely to
  be broken by accident.
- **Some "reasons" are a human's words.** `dismissal_reason` and
  `WeaponReview.reason` were typed by the person reviewing an alert. A code
  there deletes evidence.
- **A wording must carry the consequence**, not only the cause. "No exit camera"
  is not a translation of "no exit camera, so cars leaving are not being
  counted."
- **The camera picture never mirrors.** T034 is the guard. A box on the wrong
  side of a frame is a fabricated picture, not a layout bug.
- Commit each task or logical group; every fix to a known bug ships with its
  regression test in the same commit.
