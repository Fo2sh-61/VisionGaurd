# Implementation Plan: The phone looks like the console, fits one hand, and keeps in step with it

**Branch**: `014-mobile-ui-parity` (work lands on `Fo2sh`) | **Date**: 11 September 2026 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/014-mobile-ui-parity/spec.md`

## Summary

The phone shows the console's screens unchanged but styles them with a
stylesheet of its own, and then forces them to fit with two blanket rules. That
is why it looks like a different product and why it is misaligned.

The plan gives the phone:
- the console's stylesheet **as a byte copy**;
- a thin phone layer for arrangement only;
- a pinned status line and a back row in its own shell;
- small-card table rows;
- two tiny placement helpers (`PhoneOnly` / `ConsoleOnly`) for the few facts that
  must sit differently.

It also puts every shared screen on the parity list, so the two apps cannot
drift apart again. The console's stylesheet is not edited, and every change to a
shared screen is inert on the console by construction.

## Technical Context

**Language/Version**: TypeScript 5 + React 18 in both front ends (`web/`, `mobile/`), built with Vite; CSS. Python 3.14 for `tools/check_parity.py` and the one new pytest.

**Primary Dependencies**: React, react-router-dom and Vite, all already present. **No new dependency.**

**Storage**: N/A. Nothing is stored and the engine is untouched.

**Testing**:
- `tsc -b --force` in both apps
- `python tools/check_parity.py`, with its list grown from 25 to 55 files
- one new pytest that plants a difference in a shared screen
- `npm run check:format`, with cases for the new camera-status helper
- the quickstart's overflow and tap-size snippets, which turn two by-eye checks
  into numbers
- by-eye walks at 360 px, and Mohamed on a real phone

**Target Platform**:
- phone browsers (Android Chrome, iOS Safari) from 360 px wide, upright and
  sideways
- the console's desktop browsers, unchanged

**Project Type**: two web front ends sharing screen files (console `web/`, phone `mobile/`), plus the Python engine, which this feature does not touch.

**Performance Goals**: zero added engine requests. The status line reads the site data the phone already fetches every 30 s.

**Constraints**:
- the console is identical at desktop width
- 360 px with no sideways scroll
- 44 × 44 px tap targets
- the console's look, with no new style
- the order of work against four parallel jobs (research R14)

**Scale/Scope**:
- 18 phone screens
- 17 shared screen and component files edited, each copied byte for byte
- 30 files added to the parity list
- one new phone stylesheet of a few hundred lines, replacing 1,003
- about 20 new shared words

## Constitution Check

*GATE: must pass before Phase 0 research, and again after Phase 1 design.*

| Principle / rule | Verdict | How |
|---|---|---|
| III. Truthful data; AGENTS rule 4, "never show anything untrue" | **Pass** | The status line comes only from `SiteContext`, with honest "checking" and "unreachable" states. The console's permanent "Campus is calm" is not copied (FR-041). Row labels are checked against where each value is built (`contracts/shared-screens.md` §5), because a wrong label is an untrue one. The Counting "(demo figure)" mark becomes visible on the phone rather than a 45 % opacity. |
| III. Face ≠ clothing; AGENTS rules 1–3 | **Pass** | No overlay code changes. `CameraFrame` and `CamGrid` are copied, and `detections={false}` pages stay as they are. The layout cannot recolour a box: colours come from `boxColor`. |
| AGENTS rule 5, no false precision | **Pass**, and a violation is removed | The parallel System Health task removes the phone's unmeasured graphics-card percentage. This plan's parity list keeps it removed. |
| AGENTS rule 8, a failed subsystem says so in the UI | **Pass** | `DataNotice` and `LoadError` stay in the flow; `phone.css` never hides a notice. The overflow walk would catch one squeezed off-screen. |
| IV. Server-side permissions | **Pass** | Nothing moves from the engine. Hiding an admin action on the phone stays a courtesy. |
| I. Real-time / latency | **Pass** | No new polling. Camera tiles keep `tileRefreshMs`, which is copied. |
| V. Complete UX; dev workflow "partial readiness reported" | **Pass** | FR-034 covers the four hardest screens explicitly. Enrol on a phone camera stays 012's T047, flagged as unmeasured rather than claimed. |
| Dev workflow: a regression test ships with each fix | **Pass** | The parity drift gets a planted-difference pytest, and the camera-status helper gets `check:format` cases. The colour-token bug is fixed elsewhere, with its own pytest. |
| UI changes coordinated across web, mobile and tests | **Pass** | That is what the parity list and the byte-copy rule are. |

No violations need justifying. The two narrow `!important` uses are recorded
under Complexity Tracking below.

## Requirement → smallest mechanism

Mohamed's standing instruction: trace every FR to the least that satisfies it.

| FR | Mechanism | Why nothing bigger |
|---|---|---|
| 029 same look | `mobile/src/styles/app.css` = byte copy of the console's, on the parity list | the look then comes from one file by construction; no hand-matching (R1) |
| 030 alignment | delete the two blanket rules (`[style*=grid-template-columns]` → flex, `.row` fold); `phone.css` arranges each case deliberately | the misalignment comes *from* the blanket rules (R3, R4) |
| 031 360 px, sideways | `phone.css` breakpoints; `vg-*` hooks where a grid does not fit; the overflow snippet finds the rest | auto-fit grids already work once the blanket rule is gone |
| 032 44 px | `phone.css` minimum sizes for `.btn`, `.linkbtn`, `.chip-btn`, `.toggle` hit area, inputs, `.list-row`, tabs | one rule per control class, checked by snippet |
| 033 tables | `.row` as a flex card: `data-label` on ambiguous cells only, `row__actions`, `row__full` | a `<Table>` component would rewrite 19 call sites for the same result |
| 034 key screens | Weapons clip inside the entry (`PhoneOnly`/`ConsoleOnly`); CameraSources and Users hooks; register and health rows as cards | no screen gets its own body |
| 035 status line | phone `StatusLine` in the shell, reading `SiteContext`; one shared `cameraStatus()` in `format.ts` used by `TopBar` too | no new request; one sentence, two callers |
| 036 back | a back row in the phone shell: `navigate(-1)` or the tab's top by `location.key`; duplicate page links wrapped in `ConsoleOnly` | reuses `tabFor()` / `TABS` |
| 037 hover reasons | `PhoneOnly` hint lines at nine sites (`contracts/shared-screens.md` §4) | the same vocabulary trick as `DataNotice` |
| 038 current version | the parallel System Health task, then kept by FR-039 | already in flight |
| 039 refuse drift | add 30 files to `PARITY_FILES`, plus one pytest | the gate already runs in CI and `dev.ps1 test` |
| 040 console unchanged | the console CSS is not edited; every screen hook is inert there; the TopBar sentence moves verbatim | proven by §8's before/after screenshots |
| 041 no invented status | the line has no source but `SiteContext`; the sidebar's calm block is not copied | — |

## Project Structure

### Documentation (this feature)

```text
specs/014-mobile-ui-parity/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R15: every decision, and what it beat
├── data-model.md        # CameraStatus, StatusLine, BackTarget, row cells, SharedFile, PhoneOnly/ConsoleOnly
├── contracts/
│   ├── shared-screens.md  # the 55-file list, allowed hooks, every PhoneOnly/ConsoleOnly, labels, new words
│   └── phone-shell.md     # status line, back row, frame, tab bar
├── quickstart.md        # gates, snippets, the by-eye walks, the before/after console check
├── context.md           # the handoff to /speckit-implement
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks, not yet
```

### Source Code (repository root)

```text
tools/
└── check_parity.py            # PARITY_FILES +30: styles/app.css, 16 pages, 13 components

engine/tests/
└── test_parity_gate.py        # NEW: a planted one-byte difference must fail the gate
                               # (extend the System Health task's test instead, if it added one)

web/src/                       # every shared file here is then byte-copied to mobile/src
├── services/format.ts         # + cameraStatus(site, error), pure, lifted from TopBar
├── components/TopBar.tsx      # console-only: calls cameraStatus(); renders the same
├── components/ui.tsx          # + PhoneOnly (null) and ConsoleOnly (children)
├── i18n/{keys,en,ar.draft}.ts # + about 20 words (contracts/shared-screens.md §7)
├── pages/{Weapons,Attendance,Enrol,Counting,PeopleGroup,PersonHistory,
│          Users,Intrusion,People,SystemHealth,VehicleGate}.tsx
└── components/{CameraSources,VehicleMovements,VehiclePasses,
                VehicleReader,VehicleRegister,PlateEditor}.tsx
                               # hooks only: data-label, row__actions, row__full, vg-*, PhoneOnly/ConsoleOnly

web/scripts/check-format.ts    # + the four camera-status cases

mobile/src/
├── styles/app.css             # REPLACED by a byte copy of web/src/styles/app.css
├── styles/phone.css           # NEW: the phone layer (arrangement only)
├── main.tsx                   # + import '@/styles/phone.css' after app.css
├── components/ui.tsx          # + PhoneOnly (children) and ConsoleOnly (null)
├── components/StatusLine.tsx  # NEW: phone-only pinned line + tap panel
└── app/AppShell.tsx           # + StatusLine above the content, + the back row

docs/PLAN.md · STATUS.md · specs/012-mobile-parity/tasks.md   # record, once true
```

**Structure decision.** This keeps 012's two-app structure. The one change to how
the apps are organised is that screens and the console's stylesheet join the
list of files held byte-identical.

## Order of work

See research R14. In short:

1. **Wait.** The System Health, "Campus is calm" and colour-token jobs must merge
   first, and the developer sign-in merge before the by-eye checks.
2. **Console "before" screenshots** (quickstart §8), before any change.
3. **The phone look:** the `app.css` copy, `phone.css` and the `main.tsx` import.
   It touches nothing the parallel jobs touch.
4. **Vocabulary and shell:** `PhoneOnly`/`ConsoleOnly`, `cameraStatus()`,
   `StatusLine`, the back row, the new words.
5. **Shared screens, one at a time.** Edit it in `web/src`, copy the bytes, run
   the parity gate. The order: Weapons (SC-006) → the vehicle screens →
   CameraSources → System Health → the rest.
6. **The parity list +30,** and the pytest.
7. **The quickstart,** end to end. Then Mohamed on a real phone. Then the record.

## Complexity Tracking

| What | Why it is needed | Simpler alternative rejected because |
|---|---|---|
| `!important` in the `vg-*` hook rules (3–4 elements) | only `!important` beats an inline `grid-template-columns` / `display` | moving the inline style into the console's CSS edits the console's stylesheet, which Mohamed ruled out. Page bodies per app break parity. Today's blanket attribute selector is exactly what misaligns the screens |
| `min-width: 0 !important` on inputs (kept from today) | 11 inputs carry an inline `minWidth` of 200–340 px | the same two alternatives, rejected for the same two reasons |
| `PhoneOnly` / `ConsoleOnly` (two new exports per `ui.tsx`) | the knife clip, the duplicate back links, the reader headings and nine hover reasons must sit differently per app with the console's DOM unchanged | a `useIsPhone()` branch invites two screens in one file; CSS hiding renders things twice. The twin rule and the registry in `contracts/shared-screens.md` §4 keep them honest |

## Constitution re-check after design

Unchanged: every gate passes.

The design adds no data path, no request and no permission surface. It removes
two blanket CSS overrides and one phone-only honesty violation (the System Health
percentage, via the parallel task, then held by the parity list). The only new
runtime code is:
- `cameraStatus()`, a pure function moved from `TopBar`;
- the phone's `StatusLine` and back row;
- two wrappers.

None of them can invent a value.
