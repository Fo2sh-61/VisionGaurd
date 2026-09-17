# Contract: the screens both apps share

The console (`web/src`) and the phone (`mobile/src`) render the **same screen
files**. This contract says:

- which files are shared,
- what a shared screen may carry so the two apps can present it differently,
- what it may never carry.

`tools/check_parity.py::PARITY_FILES` is the source of truth for the list. This
file explains it and does not replace it.

---

## 1. The shared list after this feature (55 files)

| Group | Files |
|---|---|
| Truth (25, from 012) | `types.ts` · `services/{api,wire,http,format,frame,content,notes,ask}.ts` · `i18n/{index,keys,en,ar,ar.draft}.ts` · `app/navigation.ts` · `app/{Auth,Camera,Capability,Language,Site,Theme}Context.tsx` · `app/{useAsync,useAttention,useAutoRun,useOptions}.ts` · `styles/tokens.css` |
| Look (+1) | `styles/app.css`, the console's stylesheet, byte-copied |
| Screens (+16) | `pages/{Attendance,Counting,Enrol,Home,Intrusion,Login,LostItems,People,PeopleGroup,PersonHistory,Settings,SystemHealth,TrackPerson,Users,VehicleGate,Weapons}.tsx` |
| Feature components (+13) | `components/{CamGrid,CameraFrame,CameraModal,CameraSources,Logo,Plate,PlateEditor,RecordButton,VehicleAlerts,VehicleMovements,VehiclePasses,VehicleReader,VehicleRegister}.tsx` |

Everything else is per-app:

| Both apps, each its own copy | Phone only | Console only |
|---|---|---|
| `components/ui.tsx` (the vocabulary), `app/AppShell.tsx`, `app/routes.tsx`, `main.tsx` | `app/tabs.ts`, `pages/Tools.tsx`, `pages/Account.tsx`, `styles/phone.css` | `components/Sidebar.tsx`, `components/TopBar.tsx` |

**How a shared file changes.** Edit `web/src/<file>`, then copy its **bytes** to
`mobile/src/<file>` in the same commit. The repo has mixed CRLF/LF line endings
and no `.gitattributes`, so never read the file as text and write it back.
`git diff --stat` shows whether a copy rewrote every line ending.

## 2. What a shared screen may carry for the phone

Every item here is **inert on the console by construction**. The console's
stylesheet has no rule for it, or its console `ui.tsx` renders nothing extra.

| Hook | Meaning on the phone | Console |
|---|---|---|
| `data-label={t(key)}` on a `.row` cell | the cell's small label in the card (R3) | ignored |
| `className="row__actions"` on a cell holding controls | the card's bottom action bar | no rule |
| `className="row__full"` on a row child that spans the whole row | full card width | no rule; its inline `gridColumn: '1 / -1'` still applies |
| `className="vg-…"` on a non-table inline grid or flex bar | that element's own phone arrangement in `phone.css` | no rule; its inline style still applies |
| `<PhoneOnly>…</PhoneOnly>` | rendered | renders `null` |
| `<ConsoleOnly>…</ConsoleOnly>` | renders `null` | rendered unchanged |

**Moving an English literal into a shared key with identical English wording is
not a console change.** For example, `"one more letter"` becomes
`t('plate.oneMoreLetter')`. English is the production language. The Arabic
draft is dev-only, and gaining a translation there is a fix, not a regression.

## 3. What a shared screen may never carry

- **A class, or a change to an inline style, that changes what the console
  renders.** The console must look and behave as it does today (P13-FR-040).
- **A branch on "am I the phone?".** Such as `useIsPhone()` or a width check in
  code. Presentation differences live in `ui.tsx`, `phone.css` and the two
  wrappers, never in `if` statements inside a screen.
- **A `PhoneOnly` without a console counterpart, or a `ConsoleOnly` without a
  phone counterpart.** They move where a fact appears; they never decide whether
  it exists.

## 4. Every `PhoneOnly` / `ConsoleOnly`, with its counterpart

This list must match the code. A use not listed here is a review failure.

| Screen | Wrapper | What | Its counterpart |
|---|---|---|---|
| `Weapons.tsx` | `PhoneOnly` | the clip player **inside** the playing entry, above its decision strip (`row__full`) | the `ConsoleOnly` player after the list |
| `Weapons.tsx` | `ConsoleOnly` | the clip player after the whole list, as today | the `PhoneOnly` player in the entry |
| `PeopleGroup.tsx` | `ConsoleOnly` | the page's own "‹ People" link | the phone shell's back row |
| `PersonHistory.tsx` | `ConsoleOnly` | the page's own back link (both places it is rendered) | the phone shell's back row |
| `Enrol.tsx` | `ConsoleOnly` | the page's own "People" back link | the phone shell's back row |
| `VehicleReader.tsx` | `ConsoleOnly` | the attempt table's column headings | the same words as each cell's `data-label` |
| `Attendance.tsx` | `PhoneOnly` | one hint line above the register: why "Notify parent" is disabled (`attendance.notifyParentWhy`) | the button's hover `title` |
| `Attendance.tsx` | `PhoneOnly` | hint under the export button when there is no register yet (`attendance.showRegisterFirst`) | the button's hover `title` |
| `Enrol.tsx` | `PhoneOnly` | hint under Save when it is blocked (new key; today literal English) | Save's hover `title` |
| `Counting.tsx` | `PhoneOnly` | each segment's figure and "(demo figure)" in the legend | the segment's hover `title` |
| `VehiclePasses.tsx` | `PhoneOnly` | one line above the list saying Remove is permanent (`passes.removeTitle`) | Remove's hover `title` |
| `VehicleMovements.tsx` | `PhoneOnly` | one line above "Inside now" saying Gone is permanent (`moves.goneTitle`) | Gone's hover `title` |
| `VehicleMovements.tsx` | `PhoneOnly` | the traffic chart's per-hour in/out counts as text under the chart (new key) | each bar's hover `title` |
| `PlateEditor.tsx` | `PhoneOnly` ×2 | a caption under each "+": "letter" / "digit" (new keys; today literal English) | each "+"'s hover `title` |

Tooltips that need nothing:
- **Already visible elsewhere:** TrackPerson's anchor `why`, RecordButton's
  reason, the Movements shot.
- **One tap away:** the reader's Fix, the passes' Fix, the pass photograph link.

## 5. Row labels (`data-label`)

A label goes on a cell only where the bare value is ambiguous (P13-FR-033):

- **Use** an existing key when one already has the right wording, such as the
  register form's field labels or the reader's `reader.col*`.
- **Otherwise** add `<screen>.<name>Label`.
- **Confirm each wording** against where the value is built before writing it.
  A wrong label is an untrue label.

| Screen / row | Cell | Suggested wording | Confirm against |
|---|---|---|---|
| `Attendance` register row | `row.time` | "First seen" | where `AttendanceRow.time` is built in `services/api.ts` |
| `Attendance` person-days row | `day.time` | "First seen" | `AttendanceDay.time` |
| `Users` row | `user.lastActive` | "Last active" | `user.lastActive` |
| `Intrusion` row | `breach.time` · `breach.duration` | "Entered" · "Stayed" | the breach mapping in `services/api.ts` |
| `People` row | the last-seen cell (4th) | "Last seen" | `p.lastSeen` |
| `Weapons` row | `entry.time` · `entry.duration` · `entry.confidence` | "Seen" · "Lasted" · "Confidence" | the detection mapping |
| `VehicleMovements` visit row | the duration in the last cell | "Stayed" | `visit` duration |
| `VehiclePasses` row | the time cell | "Read at" | the pass mapping |
| `VehicleReader` attempt row | time, confidence, plausible, width, candidate, votes | reuse `reader.colTime` … `reader.colVotes` | the header at ~340 |
| `VehicleRegister` row | unit · valid until | reuse the form's `register.*` field labels | the form at ~317 |

## 6. The `vg-*` hooks

| Hook | Element | Phone arrangement |
|---|---|---|
| `vg-channel-grid` | `CameraSources` DVR channel rows (`'64px 1fr 1fr 44px'`) | flex-wrap: number + name / area + switch / info line |
| `vg-preview-form` | `CameraSources` preview beside the add form (`'240px 1fr'`) | one column |
| `vg-source-summary` | `CameraSources` source summary row (inline flex) | wraps; Edit/Remove as a thumb-sized bar |
| `vg-capability-grid` | `Users` permissions table (`'2fr .6fr .6fr'`) | keeps three columns **and shows its `row--head` headings** |
| `vg-tiles` | `VehicleGate` figure tiles | two across |
| `vg-register-filters` | `VehicleRegister` search · chips · "+ Add" bar (inline flex) | wraps: search full width, then chips, then the add button |
| *(found by the overflow snippet)* | any inline flex bar that overflows at 360 px | its own named hook, added here when found |

## 7. New shared words

These go in `i18n/keys.ts`, `en.ts` and `ar.draft.ts`. The Arabic stays a
dev-only draft.

- `action.back` — "Back"
- the new `…Label` keys from §5
- `enrol.saveNeeds` — the Save reason, with a count argument. Today it is
  literal English.
- `plate.oneMoreLetter` and `plate.oneMoreDigit`. Today they are literal English.
- `counting.demoFigure` — "demo figure"
- `moves.hourCounts` — "{hour} — {in} in, {out} out"
- `register.keepIt` — "Keep it". Also `action.edit` if it does not already exist,
  for the register row's hard-coded "Edit" / "Remove".

**Known debt, not fixed here.** This hard-coded English is on elements the phone
does not newly show:

| Where | Text |
|---|---|
| `Users` | "Edit" |
| `Weapons` | "cut at two minutes" |
| `Intrusion` | "1 person" / "N people" |
| `People` | "Track today" / "Remove" |
| `TrackPerson` | "Date" / "From" / "To" / "Back to the cameras" |
| the console-only back links | their labels |

It is recorded in `context.md` so it is not mistaken for finished.
