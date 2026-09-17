# Data model: The phone looks like the console, fits one hand, and keeps in step with it

This feature stores nothing and adds no engine data. Every "entity" below is a
value the front end already has, or derives from what the engine already sends.
No endpoint, table or wire type changes.

---

## CameraStatus (derived; shared by both apps)

The state the console's top bar shows today, lifted into one pure helper so the
console and the phone cannot word it differently (research R5).

| Field | Type | Source |
|---|---|---|
| `state` | `'checking' \| 'allUp' \| 'someUp' \| 'unreachable'` | derived, below |
| `online` | `number` | `site.camerasOnline` |
| `total` | `number` | `site.camerasTotal` |
| `label` | string | `topbar.checkingCameras` / `topbar.allCamerasUp` / `topbar.someCamerasUp` / `topbar.engineUnreachable` |
| `colour` | token | `--ac` for all up · `--am` for checking or some up · for unreachable, whatever `TopBar.tsx` uses when this is built. Today that is `--bd`, a token defined nowhere (research R15), and the helper moves the expression verbatim |
| `glyph` | `'✓' \| '!'` | `✓` only when all up |

**Derivation** (the order matters; it is `TopBar.tsx`'s order today):

1. `error` set → `unreachable`. Never a zero, which would read as every camera
   being down.
2. `site === null` → `checking`.
3. `online === total` → `allUp`.
4. otherwise → `someUp`.

**Freshness.** `SiteContext` re-asks every 30 s. So `unreachable` appears within
one refresh of the engine stopping (SC-004). The helper adds no request.

## StatusLine (phone only)

What the pinned slim line shows (P13-FR-035).

| Fact | From | On the line | In the tap panel |
|---|---|---|---|
| Date | `useSite().todayLabel` (the school's date and time as the engine reports them, not the phone's clock) | short date | date and time |
| School | `useSiteName()` | shortens first | in full |
| Cameras | `CameraStatus` | in full, never shortened | the same sentence |
| Who | `useAccount().initials` / `.name` | initials in the console's `.avatar` | name |
| Role | `useAccount().role` → `role.admin` / `role.it` | — | in full |

Nothing on the line is invented. Before the first answer it reads "Checking
cameras…" and shows no count (FR-041).

## BackTarget (phone only)

| Input | Rule |
|---|---|
| path is a tab's top: `/`, `/tools`, `/people`, `/system`, `/account` | no back row |
| any other path, and `location.key !== 'default'` | back = `navigate(-1)` |
| any other path, and `location.key === 'default'` (a reload, a discarded tab brought back, a bookmark) | back = `navigate(TABS[tabFor(path)].path)` |

Label: `action.back`. The chevron carries `mirror-rtl`.

## Row cell kinds (how a shared table row reads on the phone)

A shared screen's `.row` keeps its console markup. `phone.css` decides the
arrangement from what each cell is.

| Kind | How it is recognised | Phone arrangement |
|---|---|---|
| Headline | first child of `.row` | own line, the console's `.row__name` weight |
| Labelled value | `[data-label]` | two per line; the label is small and muted above the value |
| Plain value | any other cell | two per line, no label (self-explanatory: a name, a plate, a camera) |
| Badge | `.badge` | the console's badge, never muted |
| Action | `:is(button, .btn, .linkbtn, .chip-btn, .toggle)` as a direct child, or a `.row__actions` wrapper | along the bottom, at least 44 × 44 px, 8 px apart |
| Full-width child | `.row__full` (where the console uses inline `gridColumn: '1 / -1'`) | the card's full width, in DOM order |
| Column headings | `.row--head` | hidden, **except** inside `.vg-capability-grid`, where they are the only thing saying which column is Admin and which is IT |

The console never reads `data-label`, `.row__actions`, `.row__full` or any `vg-*`
hook class. Each is inert there by construction, because the console's
stylesheet is not edited (research R1).

## SharedFile (the parity list after this feature)

| Group | Files | Count |
|---|---|---|
| Truth (unchanged from 012) | `types.ts`, `services/*` (8), `i18n/*` (5), `app/navigation.ts`, 6 contexts, 4 hooks | 25 |
| Look | `styles/app.css` | **+1** |
| Screens | the 16 shared `pages/*.tsx` | **+16** |
| Feature components | `CamGrid`, `CameraFrame`, `CameraModal`, `CameraSources`, `Logo`, `Plate`, `PlateEditor`, `RecordButton`, `VehicleAlerts`, `VehicleMovements`, `VehiclePasses`, `VehicleReader`, `VehicleRegister` | **+13** |
| **Total** | | **55** |

**Rule.** A file on the list is byte-identical in `web/src` and `mobile/src`. CI
and `.\dev.ps1 test` refuse anything else (P13-FR-039).

**Per-app by design:** `components/ui.tsx`, `app/AppShell.tsx`,
`app/routes.tsx`, `main.tsx`, and:

| Phone only | Console only |
|---|---|
| `app/tabs.ts`, `pages/Tools.tsx`, `pages/Account.tsx`, `styles/phone.css` | `components/Sidebar.tsx`, `components/TopBar.tsx` |

## PhoneOnly / ConsoleOnly (vocabulary; two exports in each `ui.tsx`)

| | Console's `ui.tsx` | Phone's `ui.tsx` |
|---|---|---|
| `<PhoneOnly>{…}</PhoneOnly>` | `null` | children |
| `<ConsoleOnly>{…}</ConsoleOnly>` | children | `null` |

**Invariant.** They change *where* a fact or action appears, never *whether* it
exists. Every use has a counterpart on the other app. The full list of uses, with
each counterpart, is in `contracts/shared-screens.md`.

The phone's hint line is `<PhoneOnly><p className="hint">…</p></PhoneOnly>`.
`.hint` is styled only in `phone.css`.
