# Implementation Plan: The phone does everything the console does

**Branch**: `012-mobile-parity` | **Date**: 3 September 2026 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-mobile-parity/spec.md`

## Summary

The phone app is a parallel, independent app: the same product, all of it, in a
shape made for a hand. Mohamed chose a real copy over shared code, so
`mobile/` keeps its own package, its own build and its own design.

The plan's whole job is to make that copy cheap to do and impossible to let rot.

Two facts from the research decide everything below.

**The console's pages import nothing from the desktop shell.** Not the sidebar,
not the top bar — checked across every page and component, zero matches. A page
already renders into whatever container is around it, through a small shared
vocabulary: `ui.tsx`, a handful of CSS classes, `CamGrid`, `CameraFrame`.

**So the phone ships its own vocabulary, not its own pages.** Give `mobile/` a
`ui.tsx` that exports the same names with phone bodies, and an `app.css` that
styles the same classes for a narrow screen, and a copied page compiles and
renders phone-shaped with its body untouched. The design differs; the
functionality cannot, because it is the same code.

That splits the 20,000 lines into three piles:

| Pile | Lines | What happens to it |
|---|---|---|
| Decides **what is true** — services, wire, types, i18n, contexts, hooks, tokens | ~7,950 | Copied byte-for-byte, and **held** byte-for-byte by a checker |
| Decides **what is on screen** — 16 pages, 12 feature components | ~10,300 | Copied, then compiled against the phone's vocabulary |
| Decides **how it looks** — `ui.tsx`, `app.css`, shell, camera tiles | ~1,600 | Genuinely written, once |

Roughly 1,600 lines are new work. The rest is a copy that a script keeps honest.

**The drift risk is real and is answered directly.** Two copies do drift — this
repo already proves it: `web/src/styles/tokens.css` opens with a comment saying
it is "kept byte-identical to `mobile/src/styles/tokens.css`", and it is not.
So the first pile gets `tools/check_parity.py`, which fails if any file in it
differs between the two apps. Drift stops being a thing you hope about.

## Technical Context

**Language/Version**: TypeScript 5.6, React 18.3, targeting ES2022

**Primary Dependencies**: react, react-dom, react-router-dom 6.26 — already the
exact versions `web/` uses. `mobile/package.json` and `web/package.json` list
identical dependencies today, and `tsconfig.app.json` is byte-identical between
them. Nothing new is added.

**Storage**: None in the app. Every figure comes from the engine.
`localStorage` holds two display preferences only — theme, and the language the
sign-in page needs before there is an account to ask. No token, ever.

**Testing**: There is no JavaScript test runner in this repository, and this
feature does not add one. The gates that exist are `tsc -b --force`,
`npm run check:format` (a hand-rolled assertion script over `services/format.ts`),
and the engine's `pytest`. This plan adds two more: the parity checker, and a
fixture checker. Screen correctness on a phone is confirmed by eye — that is
stated plainly rather than dressed up.

**Target Platform**: A phone browser on the school network, served from the same
origin as the engine. Not an app-store build.

**Project Type**: Web front end. Two independent apps against one engine.

**Performance Goals**: A page is usable within 2 seconds of a tap on school
Wi-Fi. Camera tiles refresh at the rate `CamGrid` already computes from tile
count — the phone shows fewer tiles at once, so it asks for less, not more.

**Constraints**: Usable one-handed at 375 px wide with no sideways scrolling.
Live camera pictures must reach the phone, which requires same-origin serving —
see the proxy note in Research. No new engine endpoint: if a screen needs
something the engine does not expose, that is a finding, not a licence to invent.

**Scale/Scope**: 16 screens, 10 tools, 2 languages, 2 themes, 2 roles.
~7,950 lines copied under a checker, ~10,300 copied and recompiled, ~1,600 written.

## Constitution Check

*GATE: passed before Phase 0, re-checked after Phase 1 design — see the bottom
of this section.*

| Principle | How this feature satisfies it |
|---|---|
| **I. Real-time camera experience** | The phone uses the copied `CameraFrame`, which already drops stale frames and says NO SIGNAL rather than holding the last picture. The phone shows fewer tiles at once than a desktop grid, so its per-tile refresh is no worse. A phone that cannot reach the engine says so and shows nothing. |
| **II. Feature isolation** | Nothing in this feature touches the engine, so no worker, model or cadence changes. A camera without a feature simply has no screen for it; `CapabilityContext` already carries that and is copied whole. |
| **III. Truthful data** | This feature is mostly a **deletion** of fake data. `mobile/src/services/mockData.ts`, the fixture `api.ts`, `ask.ts`, its `types.ts` and `ToolPage.tsx` are removed, not replaced. Because they are deleted, any surviving import fails `tsc` — the gate is free. A second checker greps the built phone bundle for the fixture names so a copy cannot creep back. |
| **IV. Security & privacy** | The phone stores no role, no account and no token — it copies `http.ts` and `AuthContext` unchanged, so the session works exactly as the console's does and every refusal comes from the engine. Hiding a tab is convenience; a guard typing an admin URL is refused by the server. Audit entries are written by the engine before the act, from the phone as from the desk, because it is the same `api.ts` call. |
| **V. Complete, business-correct UX** | Parity is the requirement: all 16 screens, all actions, both languages, both roles. Copying the page bodies rather than re-implementing them is what makes "don't miss something" checkable — a missing screen is a missing file, not a subtly different rule. |

**Re-check after Phase 1 design**: passed. The design adds no engine change, no
new data, and no new user-visible claim. The one place it could have weakened a
principle — reshaping wide tables — is handled by moving detail one tap away,
never by dropping a column. Recorded in `research.md` under *Wide tables*.

**No entries in Complexity Tracking.** The design adds no pattern, no dependency
and no project. It removes 1,200 lines of fixtures.

## Project Structure

### Documentation (this feature)

```text
specs/012-mobile-parity/
├── plan.md              # This file
├── research.md          # Phase 0 — the decisions and what was rejected
├── data-model.md        # Phase 1 — what crosses into the phone, and the three piles
├── quickstart.md        # Phase 1 — how to run it and prove it
├── context.md           # Phase 1 — implementation handoff
├── contracts/
│   ├── parity.md        # Which files must stay byte-identical, and the checker
│   └── shell.md         # The phone's vocabulary: same names, phone bodies
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
mobile/
├── package.json               # unchanged — deps already match web/ exactly
├── tsconfig.app.json          # unchanged — already byte-identical to web/
├── vite.config.ts             # REWRITTEN: gains web/'s API proxy. Without it
│                              #   the phone gets no data and no camera picture
│                              #   at all — the session cookie is SameSite=Strict
├── index.html                 # viewport + theme-colour for a phone
└── src/
    ├── main.tsx               # mounts the copied providers
    ├── types.ts               # COPY of web/src/types.ts (deletes the fixture one)
    ├── services/              # COPY of web/src/services/ — all 8 files, verbatim
    │   ├── api.ts             #   (the fixture api.ts and ask.ts are deleted)
    │   ├── wire.ts  http.ts  format.ts  frame.ts  content.ts  notes.ts  ask.ts
    ├── i18n/                  # COPY of web/src/i18n/ — verbatim. RTL comes free:
    │                          #   LanguageContext sets documentElement.dir
    ├── app/
    │   ├── AuthContext.tsx        # COPY, verbatim
    │   ├── CameraContext.tsx      # COPY, verbatim
    │   ├── CapabilityContext.tsx  # COPY, verbatim
    │   ├── LanguageContext.tsx    # COPY, verbatim
    │   ├── SiteContext.tsx        # COPY, verbatim
    │   ├── ThemeContext.tsx       # COPY, verbatim
    │   ├── useAsync.ts  useAttention.ts  useAutoRun.ts  useOptions.ts  # COPY
    │   ├── AppShell.tsx       # WRITTEN — scrolling content + bottom tab bar
    │   ├── navigation.ts      # WRITTEN — 5 tabs reaching all 16 destinations
    │   └── routes.tsx         # WRITTEN — same guards, phone paths
    ├── pages/                 # COPY of all 16 web pages, bodies untouched
    ├── components/
    │   ├── ui.tsx             # WRITTEN — same 14 exports, phone bodies
    │   ├── CamGrid.tsx        # WRITTEN — one column, taller tiles
    │   ├── CameraFrame.tsx    # COPY with a phone container; the overlay maths
    │   │                      #   is 450 of its 481 lines and does not change
    │   ├── CameraModal.tsx    # WRITTEN — full-screen sheet, not a dialog
    │   ├── Logo.tsx           # COPY
    │   └── CameraSources.tsx  Plate.tsx  PlateEditor.tsx  RecordButton.tsx
    │                          VehicleAlerts.tsx  VehicleMovements.tsx
    │                          VehiclePasses.tsx  VehicleReader.tsx
    │                          VehicleRegister.tsx     # COPY, bodies untouched
    │                          # (Sidebar.tsx and TopBar.tsx are desktop-only —
    │                          #  not copied, and nothing imports them)
    └── styles/
        ├── tokens.css         # COPY, verbatim — and the drift stops here
        └── app.css            # WRITTEN — the phone's stylesheet

tools/
└── check_parity.py            # NEW — fails if a "must be identical" file differs

dev.ps1                        # gains -Mobile; `test` runs the two new checkers
.github/workflows/ci.yml       # gains a mobile tsc job. CI checks mobile
                               #   nowhere today — the fake app was never typechecked
docs/PLAN.md                   # P9's mobile half is superseded; FR-15 moves
STATUS.md                      # "Mobile app — Fake" stops being true
```

**Structure Decision**: Two independent front-end apps against one engine, as
Mohamed chose. `web/` is untouched by this feature — not one line — so the
console cannot regress while the phone is built. The relationship between them
is not an import, it is a **copy with a checker**: `tools/check_parity.py` names
the files that must stay identical and fails the build when they are not.

Deleted, not migrated: `mobile/src/services/mockData.ts` (392),
`mobile/src/services/api.ts` (301, all fixtures), `mobile/src/services/ask.ts`
(26), `mobile/src/types.ts` (305, a different and incompatible shape — its
`ToolId` is `'attend' | 'count' | …` where the console's is `'attendance' |
'counting' | …`), and `mobile/src/pages/ToolPage.tsx` (456, a generic screen that
rendered one invented answer object for every tool). About 1,480 lines of fiction
go.

## Complexity Tracking

No violations. Nothing to justify.
