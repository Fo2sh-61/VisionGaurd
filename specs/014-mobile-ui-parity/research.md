# Research: The phone looks like the console, fits one hand, and keeps in step with it

Every decision below maps to the smallest mechanism that meets the spec's
requirements. Mohamed's standing instruction for plans is "working as desired,
fast and easy, no complexity". Where a bigger mechanism was considered, it is
named under *Alternatives* with the reason it lost.

Mohamed's answers on 11 Sep 2026 settle four of the choices:

- **Styles:** the phone uses an exact copy of the console's styles plus a thin
  phone layer (R1).
- **Table rows:** small cards (R3).
- **Status bar:** pinned, one slim line (R5).
- **By-eye checks:** merge the developer sign-in first, as a separate job (R12).

---

## R1 — Where the phone gets the console's look (P13-FR-029, FR-040)

**Decision.** `mobile/src/styles/app.css` becomes a **byte copy** of
`web/src/styles/app.css` and joins the parity list. The phone's own presentation
moves into a new `mobile/src/styles/phone.css`, which `mobile/src/main.tsx`
imports after `app.css`. The console's stylesheet is not edited at all.

**Rationale.**
- **Why the look differs today.** The phone's stylesheet was written separately.
  Of roughly 106 selectors in the console's file, only 37 have identical bodies
  in the phone's. The rest differ: hard-coded corner radii (`16px`, `13px`,
  `9px`) where the console uses `var(--radius-xl|md|sm)`, and different type
  sizes and paddings. That is why the same page looks like a different product.
- **Copying fixes it by construction.** Every card, badge, button, chip, form,
  notice and camera tile then comes from the one file the console uses.
- **The existing checker keeps it that way.** A future change to the console's
  look reaches the phone in the same commit, or CI fails.
- **No console risk.** The console's CSS is untouched, so FR-040 cannot be broken
  by this half of the work.

**What `phone.css` holds**, and nothing else:
- the phone's shell: app frame, status line, back row, tab bar
- the phone arrangement of console layout rules: `.row`, `.row--head`, `.stats`,
  `.grid-2/3/4`, `.plan`, `.filters`, `.edit-row`, `.camgrid`, `.modal__panel`
- sizes a thumb needs, from R9 and R10
- the hooks from R3, R4 and R7

It is expected to be a few hundred lines, down from the phone's 1,003 today,
because none of the look is restated in it.

**Rules for `phone.css`.**
- **Arrangement only; never a colour or a typeface.** Every colour is a token
  from `tokens.css`.
- **Every override of a console rule carries a one-line reason.** For example,
  `.page__title` drops from 26 px to 22 px because a phone headline competes with
  the status line and tab bar.
- **Equal specificity, loaded later.** That is enough to win; no `!important`
  except in the two places listed under Complexity Tracking in `plan.md`.

**Alternatives.**
- *Fix the phone's own stylesheet by hand.* Smaller today; drifts again on the
  next console change, and nothing would catch it.
- *Split the console's stylesheet into a shared part and a desktop part.*
  Tidiest long term, but it edits the console's CSS and reorders its rules. The
  console would then need proving unchanged.
- *Import the console's stylesheet across projects* (`../../web/src/...`). This
  breaks the settled "two parallel apps, own package and build" decision from
  P13.

**Trap.** The console's `@media (max-width: 900px)` block applies on every phone:
it sets `.grid-4` to two columns and `.grid-3`, `.grid-2` and `.plan` to one.
`phone.css` restates whatever it wants for those classes, and must not assume
they are desktop-sized. The console's `.sidebar`, `.topbar` and `.shell` rules
are inert on the phone, because it never renders those classes.

---

## R2 — The shared screens go on the parity list (P13-FR-038, FR-039)

**Decision.** Add to `PARITY_FILES` in `tools/check_parity.py`:
- all 16 `pages/*.tsx` that both apps have;
- the 13 feature components both apps have: `CamGrid`, `CameraFrame`,
  `CameraModal`, `CameraSources`, `Logo`, `Plate`, `PlateEditor`,
  `RecordButton`, `VehicleAlerts`, `VehicleMovements`, `VehiclePasses`,
  `VehicleReader`, `VehicleRegister`;
- `styles/app.css`, from R1.

The list grows from 25 to 55. Add one pytest that plants a one-byte difference in
a temporary copy of a shared screen and asserts the checker returns 1 (SC-007).

**Rationale.**
- **The gap.** The checker today guards types, services, words, contexts and the
  palette, but none of the screens. 012 byte-copied them, with nothing to hold
  them there afterwards, which is exactly how System Health drifted within a day.
- **No new machinery.** The gate already runs in CI (`engine` job,
  `python tools/check_parity.py`) and in `.\dev.ps1 test`. So "a release that
  differs is refused" (FR-039) needs only the list extended.
- **Current state.** Every one of the 29 screens and components is byte-identical
  today except `pages/SystemHealth.tsx`. The parallel task "Bring the phone's
  System Health level with the console" is fixing that one. It is also fixing the
  checker's crash on a cp1252 console (`UnicodeEncodeError` while printing a
  diff).

**Stays off the list, deliberately.** These are the phone's shell and
vocabulary, not screens:
- `components/ui.tsx`, where the phone caps `Stats` at two columns and R7 adds
  `PhoneOnly` and `ConsoleOnly`;
- `app/AppShell.tsx`, `app/routes.tsx`, `main.tsx`;
- the phone-only `app/tabs.ts`, `pages/Tools.tsx`, `pages/Account.tsx` and
  `styles/phone.css`;
- the console-only `Sidebar.tsx` and `TopBar.tsx`.

**Alternatives.**
- *A separate "screen checker".* The existing one already does bytes, CRLF
  reporting and CI wiring.
- *Checking in CI only.* It is already in both places.

---

## R3 — Table rows become small cards (P13-FR-033, Mohamed's choice)

**Decision.** In `phone.css`, a `.row` is a small card, not a folded line:

- The **first cell** is the headline, on its own line.
- **Value cells** follow in two columns, each led by a small muted label.
- **Badges** keep the console's badge look. Today's phone rule turns them into
  grey text.
- **Action cells** (buttons, link buttons, chips, toggles) sit along the bottom
  as real, thumb-sized controls, never inline among the values.
- **`.row--head`** stays hidden, since its headings describe columns that no
  longer exist.

The label comes from a `data-label` attribute on the value cell, for example
`data-label={t('attendance.firstSeenLabel')}`. `phone.css` prints it with
`.row [data-label]::before { content: attr(data-label); }`. It is a descendant
selector, because one labelled value, `VisitRow`'s duration, sits inside another
cell. The console has no rule for `data-label`, so it renders exactly as before.

**Most labels are new words.** Only 1 of the 19 table sites has column headings
with translated words: `VehicleReader`'s attempt rows, whose header uses
`reader.col*`. Its cells reuse those keys. Every other ambiguous cell needs a new
shared key in `keys.ts`, `en.ts` and `ar.draft.ts`. There are about 15 of them,
listed in `context.md`.

**Two more inert class hooks.**
- `row__actions` goes on a cell that wraps several controls. Examples are
  Weapons' Watch/Open, People's Track/Remove, Passes' Fix/Remove and the
  Register's Edit/Remove. The phone lays it out as the card's bottom bar.
- `row__full` goes on a child that spans the whole row, where the console uses an
  inline `gridColumn: '1 / -1'`: Weapons' decision strip, People's
  remove-confirmation strip, System Health's per-worker block, and the
  plate-editor span in Passes. The phone gives it the card's full width. An
  inline `gridColumn` means nothing in a flex card, so without the hook these
  would fall into the two-column value flow.

**Why `display: flex`, not grid.** Every table row sets `gridTemplateColumns`
inline (28 sites). An inline style beats any stylesheet rule without
`!important`. As long as the phone's `.row` is not a grid, that inline value is a
property nothing reads, so no row needs `!important` and no call site loses its
console columns. The card's two value columns are made with `flex-basis`, not a
grid.

**Only where needed (FR-033's wording).** A label goes on a value cell only where
the bare value is ambiguous: a time, a count, a percentage, a duration, a camera
next to another camera. Names, plates and badges already say what they are. The
per-site list is in `context.md`, taken from the inventory.

**How action cells are found.**
- **Bare controls:** where a control is a direct child of the row, `phone.css`
  finds it by its own class: `.row > :is(button, .btn, .linkbtn, .chip-btn, .toggle)`.
- **Wrappers:** where a wrapper element holds the buttons, that wrapper gets
  `className="row__actions"`. This is an inert class on the console.

`:has()` would avoid touching those wrappers, but a named class is explicit and
survives a refactor.

**Alternatives.**
- *A `<Table>` component in `ui.tsx` rendering differently per app.* It would
  rewrite 28 call sites for the same result.
- *Mohamed's other two options, a tidy line or tap-to-open.* Declined on
  11 Sep 2026.

---

## R4 — The inline grids that are not table rows (P13-FR-030, FR-031)

**Decision.** Each of the 9 elements that set `display: 'grid'` **inline**
keeps its inline style, so the console is unchanged. Only the ones that do not
already fit a phone gain a named class hook, which the console's CSS knows
nothing about. `phone.css` gives each hook its own phone arrangement.

The inventory splits the nine:

| Site | What it is | On the phone |
|---|---|---|
| `CameraSources.tsx` ~885, `'64px 1fr 1fr 44px'` | the DVR channel list: number · name · area · switch, plus an info line spanning 3 | hook `vg-channel-grid`. The rows become flex-wrap, because the children carry inline `gridColumn` spans that would fight a new template: number + name / area + switch / info |
| `CameraSources.tsx` ~1047, `'240px 1fr'` | preview beside the add-camera form | hook `vg-preview-form`, one column |
| `Users.tsx` ~70, `'2fr .6fr .6fr'` | the permissions table: capability · Admin · IT | hook `vg-capability-grid`. It keeps three columns (they fit), **and its `row--head` headings stay visible**. Today's blanket `.row--head { display: none }` hides "Admin" and "IT" and leaves bare yes/no columns, which is a real phone bug |
| `VehicleGate.tsx` ~150, `auto-fit, minmax(180px, 1fr)` | six figure tiles | hook `vg-tiles`, two across, like `Stats` |
| `VehicleReader.tsx` ~340 | the attempt table's column headings | wrapped in `ConsoleOnly` (R7), because its cells carry the same words as `data-label` |
| `Enrol.tsx` ~405, `VehicleRegister.tsx` ~317, `VehicleMovements.tsx` ~441 | forms and tiles on `auto-fit, minmax(190–220px, 1fr)` | **nothing.** They already fall to one column below about 400 px. Today they are broken only by the blanket rule |
| `Enrol.tsx` ~599 | a 48 px box centring one glyph, no template | nothing |

Removing the blanket rule fixes four sites outright. Three need a hook, and one
moves behind `ConsoleOnly`.

Flex rows that overflow at 360 px, such as a filter bar of search, chips and a
button, are not in this inventory, because it covered grids. They are found by
the overflow snippet in `quickstart.md`, and each gets a named hook in
`phone.css` in the same way.

That replaces today's blanket rule, which turns every one of them into a
baseline-aligned wrapping line:

```css
.app__content [style*='grid-template-columns'] { display: flex !important; }
```

Photo strips, forms and headers are all forced through that one rule, and it is
where most of the misalignment Mohamed sees comes from.

**Why `!important` survives here, narrowly.** Only `!important` beats an inline
`grid-template-columns`. The two ways to avoid it were to move the inline style
into the console's CSS (ruled out: the console's stylesheet is not edited) or to
give the phone its own page bodies (ruled out: the screens must stay shared). So
each hook overrides with `!important` **by name**, one screen at a time, with a
one-line reason. That is narrower and more deliberate than today's blanket
attribute selector. It is listed in Complexity Tracking.

**The per-site list** is in `context.md`.

---

## R5 — The status line (P13-FR-035, FR-041, SC-004; Mohamed: pinned, one slim line)

**Decision.** The phone's `AppShell` renders a pinned slim line above the
scrolling content, on every signed-in screen. Reading in the direction of the
language:

- **Date, then the school's name.** One block that shortens from its end, so the
  school's name gives way first.
- **Camera status.** Never shortened. It uses the console's words, colours and
  glyph: checking / all up / some up / engine unreachable.
- **The account's initials** in the console's avatar.

Tapping the line opens a small panel with each fact in full: the school, the date
and time, the camera sentence, the name and the role. The panel reuses
`topbar.*` and `role.*` wording, and links to the Account tab.

**Where the figures come from.** `SiteContext`, which the phone already mounts,
and which already re-asks the engine every 30 seconds. So the line adds **zero**
requests (constitution: latency) and reads "Engine unreachable" within one
refresh (SC-004).

**The same wording by construction.** The camera-status decision moves out of
the console's `TopBar.tsx` into one shared, pure helper in
`services/format.ts`, a parity file that already "owns every rendered string".
The helper takes `site` and `error` and returns the state, the i18n key and its
arguments, the colour token and the glyph. Each shell calls `t(key, args)`
itself. Both `TopBar.tsx` and the phone's line call it. The console's top bar is
unchanged on screen; only where its sentence is built moves. The expression moves
**verbatim**.

**Colour of the unreachable state.** Today that expression colours "engine
unreachable" with `var(--bd)`, a token defined nowhere. So the console shows the
most important warning in plain text colour, with an invisible `!` glyph. That
bug is not fixed here, because fixing it changes the console's look, which this
spec forbids. It belongs to the separate task in R15. Whichever colour that task
settles on, the shared helper carries it to both apps at once.

**A deliberate reading of FR-035.** One slim line at 360 px, in Arabic, cannot
hold the school, the date, the full camera sentence, the name and the role in
full. The line never shortens the camera status, which is the safety-relevant
fact. The school's name shortens first, and the role is one tap away in the
panel. If Mohamed wants the role on the line itself, the date moves into the
panel instead. The layout supports either.

**Not copied:** the console's sidebar block "Campus is calm — Nothing urgent right
now", which is always shown whatever is happening (FR-041). The parallel task
"Stop the console sidebar always saying 'Campus is calm'" is handling the
console's side.

**Alternatives.**
- *Copy `TopBar.tsx`'s ten lines into the phone shell.* That is two copies of the
  sentence, the exact drift this feature exists to end.
- *A new endpoint for the phone.* The data already arrives.

---

## R6 — The back control (P13-FR-036, SC-005)

**Decision.** The phone's `AppShell` renders a back row at the top of the
scrolling content on every screen that is not a tab's top. Tab tops are `/`,
`/tools`, `/people`, `/system` and `/account`; every other path gets the row.

- **Label:** a new shared word, `action.back`. It is always true, where naming
  the previous screen from history often is not.
- **Chevron:** carries `mirror-rtl`, so it points the way the language reads.
- **Behaviour:** if React Router's `location.key !== 'default'`, there is an
  in-app screen behind this one, so `navigate(-1)`. Otherwise the screen was
  opened with nothing behind it (a reload, a discarded tab brought back, a
  bookmark), so `navigate(<the tab's top>)`, using the existing `tabFor()` and
  `TABS`.

**Duplicates.** Three shared screens already carry their own back link, and on
the phone each would sit under the new one:
- `PeopleGroup` ("‹ People", hard-coded English)
- `PersonHistory` ("‹ People" or "‹ group", hard-coded English)
- `Enrol` (`enrol.backToPeople`)

Each is wrapped in `ConsoleOnly` (R7), so the phone renders only its shell's back
row and the console renders exactly what it does now. Their hard-coded English
moves into the shared words. That is a real defect in Arabic on both apps today.

TrackPerson's "Back to the cameras" is **not** navigation; it switches the page's
own mode. It stays visible, and only its hard-coded English is fixed.

**Alternatives.**
- *A pinned back button.* Mohamed chose one slim pinned line, and the back row
  would be a second one.
- *Relying on the phone's own back gesture.* It is invisible, and the spec says
  "visible".

---

## R7 — Placing the same fact differently per app: `PhoneOnly` and `ConsoleOnly` (P13-FR-037, FR-034, FR-036)

**Decision.** Both `ui.tsx` files gain two tiny exports:

| | Console's `ui.tsx` | Phone's `ui.tsx` |
|---|---|---|
| `PhoneOnly` | `null` | its children |
| `ConsoleOnly` | its children | `null` |

A shared screen uses them where the same fact or action must sit in a different
place on each app. This is the vocabulary trick `DataNotice` already uses: one
call site, and each app decides the presentation. The console's DOM is
untouched, because `PhoneOnly` renders nothing there and `ConsoleOnly` renders
its children unchanged.

**The rule that keeps it honest.** They move where a fact appears; they never
decide whether it exists. Every `PhoneOnly` has a console counterpart (a hover
`title`, a `ConsoleOnly` twin, or the same fact visible elsewhere), and the
reverse. Every use is listed in `contracts/shared-screens.md`, and a new one
without its twin is a review failure.

**What it is used for.**
- **Hover-only reasons.** The inventory found 15 real tooltips. Three duplicate
  visible text and need nothing (TrackPerson's anchor `why`, RecordButton's
  reason, the Movements shot). Three explain a control whose tap opens the
  explanation itself (the reader's Fix, the passes' Fix, the pass photograph),
  so they are one tap away already. The other nine carry something a phone user
  would otherwise never see, and get a `PhoneOnly` line:
  - **Attendance:** export needs a register first; why "Notify parent" is always
    disabled. Shown once above the list, not under every row.
  - **Enrol:** why Save is blocked. Today it is literal English, so it gets a key.
  - **Counting:** each bar segment's figure, and its "(demo figure)" mark. Today
    the mark is only a 45 % opacity. This is an honesty item.
  - **Passes and Movements:** that Remove and Gone are **permanent**. There is no
    confirmation step, so on a phone that is the only warning. Shown once per
    list.
  - **The traffic chart:** each hour's in and out counts. Today they are bar
    heights plus a tooltip.
  - **The plate editor:** which "+" adds a letter and which a digit. Today they
    are two identical "+" buttons, and literal English.

  A disabled button cannot receive a tap on most phone browsers, so for a
  disabled control "one tap away" is not available. The reason has to be on the
  screen.
- **The knife clip (FR-034).** See R8.
- **Duplicate back links (FR-036).** People-group's, person-history's and
  enrolment's own back links are wrapped in `ConsoleOnly`, so the phone shows only
  its shell's back row. Nothing is rendered and then hidden.
- **The reader table's column headings (R4).**

**Alternatives.**
- *A `useIsPhone()` hook with branches inside the screens.* That invites two
  different screens in one file, which is exactly the drift this feature ends.
- *A `Hint` component only.* It covers the tooltips, but not the clip or the
  back links.

---

## R8 — The four screens where arrangement matters most (P13-FR-034, SC-006)

These are the 012 leftovers T031, T041, T053 and T054, now done against this spec.
Each is solved with the same tools as everything else: the R3 small card, an R4
hook, R7's placement, and `phone.css`. No screen gets its own page body.

- **Knife alerts (`Weapons.tsx`).** Today one `<video>` plays **after the whole
  list** (`maxHeight: 420`). On a phone, pressing Watch sends the clip to the
  bottom of the page, away from the entry and its two decision buttons, which
  breaks SC-006.
  - The fix: the player moves into a small local `ClipPlayer` used twice. The
    phone's copy renders inside the playing entry, between its clip controls and
    its decision strip (`PhoneOnly`, `row__full`). The console's copy stays after
    the list (`ConsoleOnly`).
  - The entry then reads top to bottom: camera and time → Watch → the clip → the
    two decision buttons.
- **Camera channel list (`CameraSources.tsx`).**
  - The DVR channel grid and the preview-beside-form get R4 hooks.
  - The source summary row (name and meta, status badge, reconnect reason,
    Edit/Remove) is an inline flex row, and gains hook `vg-source-summary` to wrap.
  - The four wide inputs (`minWidth` 220–340 px) already shrink under the kept
    `min-width: 0` rule.
- **Vehicle register and movements.**
  - Register rows, visit rows and pass rows become R3 cards, with Edit/Remove,
    Fix/Remove and Gone as `row__actions`.
  - The register's search, chips and "+ Add" bar is an inline flex row, and gets a
    wrap hook.
  - The movement filters and the gate tiles are `auto-fit` and need nothing.
  - Hard-coded English on these rows ("Edit", "Remove", "Keep it") moves into
    the shared words while the lines are being touched.
- **System Health workers (`SystemHealth.tsx`).**
  - The pipeline rows become cards. Each one's worker block becomes `row__full`,
    and inside it each worker is its own small card.
  - The worker figures are already worded strings ("{n} frames · {ms} ms",
    "queue {d}/{max} · {n} dropped"), so they need no labels.
  - Nothing on this screen shows "skipped" frames today, so FR-034's "kept
    separate" is met by never combining them with dropped ones.
  - This screen is being brought level with the console by the parallel task.
    Start it only after that task has landed.

---

## R9 — Sizes a thumb needs (P13-FR-032, SC-003)

**Decision.** `phone.css` gives every pressable control at least 44 × 44 px.

- `.btn`: the console's is 42 px high.
- `.linkbtn`: becomes `inline-flex` with `min-height: 44px`.
- `.chip-btn`, `select`, `input`, `.list-row` and `.tabbar__item`.
- `.toggle`: its hit area grows through padding, so the visible switch keeps the
  console's size.

Neighbouring actions in a card get at least 8 px between them. SC-003 is checked
by the measuring snippet in `quickstart.md`, not by eye.

## R10 — Typing on a phone

**Decision.** Inputs are `font-size: 16px` on the phone. Below 16 px, iOS Safari
zooms the whole page when a field is focused, and the page then stays zoomed.
This is a well-known phone trap, and the console's 14 px inputs would hit it.

The status line and tab bar are part of the fixed frame, not the scrolling
content. So when the keyboard opens, the field being typed in scrolls into view
normally.

## R11 — 360 px, sideways, notches (P13-FR-031)

**Decision.**
- **Widths:** the phone layer targets 360 px as its narrowest width.
- **Camera grid:** one camera per row below 480 px, two above, which includes
  landscape.
- **Short screens:** with `max-height: 500px` (a phone held sideways), the status
  line and tab bar drop their padding, and the tab labels hide behind their icons
  so the content keeps most of the height.
- **Notches and home indicators:** the safe-area insets the shell already uses
  (`env(safe-area-inset-*)`) are kept.
- **Inputs:** the existing phone rule that lets 11 inline-`minWidth` inputs shrink
  (`min-width: 0 !important`) is kept. It is the second `!important` in
  Complexity Tracking.

## R12 — How the work is checked (Mohamed: merge the developer sign-in first)

**Decision.** Every by-eye check runs against the mock engine with the
developer sign-in:

```
.\dev.ps1 up -Mock -Mobile -AllowSystemPython -DevSign* admin
```

It runs in the in-app browser, sized to 360 × 780 and then 780 × 360, then
Arabic, then dark. Two snippets from `quickstart.md` measure sideways overflow
and small tap targets on each screen, so those two checks are numbers rather than
opinions. The console is compared at 1440 × 900 against screenshots taken before
the first change.

The developer sign-in lives on `claude/dev-sign*`. Merging it into `Fo2sh`, with the
phone's copies of the files it touches, is its own task, and it runs only after
the System Health task has landed. Until it merges, the checks are Mohamed's.
Mohamed does the final pass on a real phone either way.

## R13 — The design plugin

**Decision.** The phone layer (`phone.css` and the shell) is built with the
`frontend-design` skill. Its brief pins the direction: "the console's look,
arranged for one hand at 360 px". Its own guidance says a brief that names a
direction wins over its default push for a new identity. What it contributes
here is its quality floor:

- a consistent spacing rhythm, and alignment
- touch sizes
- visible focus
- reduced motion respected
- critiquing its own screenshots

It does not choose colours, typefaces or wording; those come from the console.

## R14 — Order of work, alongside the other sessions

Three other jobs touch the same files, and each runs in its own worktree:

1. **System Health level** (`SystemHealth.tsx`, `format.ts`, `i18n`,
   `check_parity.py`). **Must land before** R2 and R5, because both touch
   `format.ts` and the parity list.
2. **"Campus is calm"** (`Sidebar.tsx`, `i18n`). Must land before any `i18n`
   edit here (R6's `action.back` and the translated back links). Otherwise the
   two jobs conflict in `en.ts`, `keys.ts` and `ar.draft.ts`.
3. **Developer sign-in merge.** Must land before R12's checks, and after job 1.
4. **Undefined colour tokens** (`TopBar.tsx`, `Attendance.tsx`,
   `CameraSources.tsx`, `TrackPerson.tsx`, and a new pytest). Must land before
   this feature edits `Attendance.tsx` and `CameraSources.tsx`.

014 therefore starts from `Fo2sh` after jobs 1, 2 and 4 have merged. The CSS-only
work (R1, R3, R4 and R9–R11 in `phone.css`) touches none of their files, so it
may start earlier, as long as it takes the console's `app.css` as it stands when
the copy is made.

## R15 — Found while planning, fixed elsewhere

Four colour tokens are used by the screens but defined nowhere:

- `--bd` in `TopBar.tsx`, the unreachable state
- `--bad` in `Attendance.tsx` and in three places in `CameraSources.tsx`, the
  connection errors
- `--warn` in `CameraSources.tsx`
- `--ln` in `TrackPerson.tsx`

The browser drops such a declaration silently, so each renders uncoloured.
(`--bg3` in `Enrol.tsx` has a fallback and is fine.) Fixing them changes the
console's look in those states, so it is flagged as its own task, with a pytest
that fails on any undefined token, rather than slipped into a spec that promises
the console does not change.
