# Implementation Plan: The phone is built for a phone, and still does everything the console does

**Branch**: `015-phone-first-redesign` (commits land on `Fo2sh`) | **Date**: 17 September 2026 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/015-phone-first-redesign/spec.md`

## Summary

Rebuild the phone app's frame and the screens whose layout the approved design
changes. The heavy feature parts stay as copies of the console's, restyled by the
phone's stylesheet. Nothing new is asked of the engine: every screen reads the
same `services/api.ts` calls the console reads. Everything that decides what is
true stays byte-identical in both apps and is checked by `tools/check_parity.py`.
Two hooks join that shared list: the alert bell's logic and the linked-item
scroll. The console's look and behaviour do not change.

The smallest mechanism per requirement is in [research.md](research.md). The
screen-by-screen split between "rebuilt" and "restyled copy" is R1.

## Technical Context

**Language/Version**: TypeScript 5.6, React 18.3, react-router-dom 6.26 (both front ends); Python 3.14 for the gates

**Primary Dependencies**: none added. Vite 5 dev server, `tools/check_parity.py`, `web/scripts/check-format.ts`

**Storage**: none. Browser `localStorage` only where the console already uses it (bell seen-list, theme, pre-sign-in language)

**Testing**: `python -m pytest engine` (baseline **1889 passed, 6 skipped** at `34e2bef` plus the tree's uncommitted work); `npx tsc -b --force` in `web/` and `mobile/`; `python tools/check_parity.py` and `--no-fixtures`; `python -m pyflakes engine/vg engine/tools engine/tests`; a 360-px audit script run in the in-app browser (quickstart §3)

**Target Platform**: phone browsers, 360–430 px wide, upright and sideways; English (LTR) and Arabic (RTL); light and dark

**Project Type**: web app, two front ends (`web/` console, `mobile/` phone) over one engine

**Performance Goals**: no more engine requests than the console makes for the same screen. Home adds four summary reads, refreshed every 30 s. The one-camera screen polls detections at the console's rate, only while it is open.

**Constraints**: no engine changes; no console change a person can see; touch targets ≥ 44 px; text contrast ≥ 4.5:1 (3:1 at ≥ 24 px); text ≥ 12 px; no sideways scroll at 360 px

**Scale/Scope**: 5 tabs; 21 routes (17 drawn in the design, 4 following its patterns); about 13,500 lines in `mobile/src` today. About 5,500 are rebuilt, about 6,000 stay as restyled copies.

## Constitution Check

*GATE: passed before Phase 0 and re-checked after Phase 1.*

| Principle | How this plan keeps it |
|---|---|
| I. Real-time camera | Camera pictures reuse `CameraFrame`, brought level with the console's copy: stream released on unmount, stall back-pressure (R9). Offline cameras say "No signal" with their last-picture time, never "LIVE". |
| II. Feature isolation | The one-camera screen draws one feature's boxes at a time through `getCameraDetections(id, feature)`. Tool screens keep their own `feature` on `CamGrid`. Home's figures each come from their own feature's call and fail on their own. |
| III. Truthful data | No placeholder from the design is carried over. Unknown shows a dash or "Not counted" with its reason. Design parts without data are left out and listed in `gaps.md` (R15). The console's fake school-profile edit is **not** copied (R10). |
| IV. Reliability, security | Server decides permissions. Admin-only controls are hidden as a courtesy only (`useAccount().role`). Engine down → top bar "Engine unreachable", Home shows no figure. |
| V. Complete UX | Every console fact and action is on a phone screen, at most one tap away (inventory in research R1; contract in `contracts/phone-screens.md`). |
| Rules 1–2 (face vs clothing) | Legend and badges keep green/blue/amber. The in-view list names only green face boxes; it never promotes a clothing match. |
| Rule 3 (own overlay) | See II. |
| Rule 5 (no false precision) | Counting keeps the "added across cameras" note; no capacity → no percentage. |
| Rule 7–8 (degradation visible) | `DataNotice` / `LoadError` stay mounted unconditionally at the top of every screen. |
| Rule 10 (knife waits for human) | Knife review keeps both decisions, reason, history; no delete. |
| Rule 11 (track audit) | Track keeps the console's own page body and API calls untouched (R1). |

No violations, and Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/015-phone-first-redesign/
├── spec.md
├── plan.md              # this file
├── research.md          # decisions R1–R15, gap register
├── data-model.md        # phone view models: tab map, alert feed, today figures, gap
├── contracts/
│   └── phone-screens.md # routes, tabs, back behaviour, per-screen parity contract
├── quickstart.md        # gates + 360-px audit + by-eye walk
├── context.md           # implementation handoff
├── gaps.md              # written during implement; the closing report's gap list
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
tools/check_parity.py                 # + app/useAlertFeed.ts, app/useLinkedItem.ts on PARITY_FILES

web/src/                              # console — no visible change
├── app/useAlertFeed.ts               # NEW, shared: bell feed state, seen-list, unread (lifted from AlertBell)
├── components/AlertBell.tsx          # uses useAlertFeed; renders exactly as today
└── i18n/{keys,en,ar.draft}.ts        # + phone keys (nav.tab.cameras|more, phone.*), copied to mobile

mobile/src/
├── app/
│   ├── AppShell.tsx                  # REBUILT: TopBar on tab roots, ScreenHeader below, TabBar
│   ├── tabs.ts                       # REBUILT: home|cameras|tools|people|more + screen table (title, parent)
│   ├── routes.tsx                    # + /alerts /cameras /cameras/:id /more; /account → /more
│   ├── useAlertFeed.ts               # byte copy (parity)
│   ├── useLinkedItem.ts              # byte copy (parity)
│   └── useTodayFigures.ts            # NEW phone-only: Home's four figures
├── components/
│   ├── ui.tsx                        # Select → chip + bottom sheet; PageHeader → lead only (title is in the header)
│   ├── Sheet.tsx                     # NEW bottom sheet
│   ├── TopBar.tsx                    # NEW brand + status + bell button + initials
│   ├── ScreenHeader.tsx              # NEW back arrow + title
│   ├── CameraFrame.tsx               # brought level with web copy (stream release, stall back-pressure)
│   ├── CameraModal.tsx               # full-screen layer: header, picture, count, RecordButton
│   ├── CamGrid.tsx                   # brought level with web copy (activeRef), phone tile layout
│   └── VehicleAlerts.tsx             # brought level with web copy (linked item, i18n)
├── pages/
│   ├── Home.tsx                      # REBUILT
│   ├── Alerts.tsx                    # NEW
│   ├── Cameras.tsx                   # NEW
│   ├── CameraView.tsx                # NEW
│   ├── Tools.tsx                     # REBUILT
│   ├── More.tsx                      # NEW (replaces Account.tsx)
│   ├── Attendance.tsx Counting.tsx LostItems.tsx Intrusion.tsx Weapons.tsx
│   │   VehicleGate.tsx People.tsx PersonHistory.tsx PeopleGroup.tsx
│   │   SystemHealth.tsx Settings.tsx Users.tsx Login.tsx      # REBUILT phone layouts
│   └── TrackPerson.tsx Enrol.tsx     # console copies, restyled by CSS only
└── styles/app.css                    # REWRITTEN: phone design system; legacy class names kept for copies
```

**Structure Decision**: the two-app layout stays. Rebuilt and new files live only
in `mobile/src`. The two new hooks and the new wording are written once in
`web/src` and copied byte-for-byte, as the parity rule requires. The console's
only source changes are `AlertBell.tsx`, which now calls the lifted hook with
identical behaviour, and additions to the i18n catalogue.

## Delivery steps (each one a commit on `Fo2sh`)

1. **Shared truth**: `useAlertFeed` lifted, `useLinkedItem` shared, phone
   wording added, parity list extended. Console bell checked by eye.
2. **Frame**: stylesheet, Sheet, TopBar, ScreenHeader, AppShell, tabs, routes,
   `ui.tsx`. Every existing screen still compiles and renders inside the new
   frame.
3. **Tab roots**: Home, Alerts, Cameras, CameraView (with CameraFrame, CameraModal
   and CamGrid synced), Tools, More.
4. **Tools**: Attendance, Counting, Lost bag, Restricted zones, Knife detection,
   Vehicle gate, and the restyled Track.
5. **People and More**: People, a person, a group, Enrol restyled, System health,
   Settings, Accounts, Sign-in.
6. **Proof**: 360-px audit in 4 variants (en/ar × light/dark), by-eye walk,
   `gaps.md`, STATUS.md line, console regression check.

Gates before every commit: phone `tsc`, console `tsc`, parity, no-fixtures,
pyflakes, and pytest with its count not dropping.

## Complexity Tracking

None.
