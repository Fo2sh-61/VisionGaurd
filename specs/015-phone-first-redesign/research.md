# Research: phone-first redesign

17 September 2026. Sources: the approved canvas (17 artboards), and an inventory
of every console screen made by 8 readers, each checked by a second reader for
missed facts, actions and states. The raw inventory was kept for this session
only. What matters from it is below and in `contracts/phone-screens.md`.

---

## R1. Which screens are rebuilt, which stay restyled copies

**Decision.** A screen is **rebuilt** when the design changes its arrangement. A
screen stays a **console copy restyled by CSS** when its arrangement is already a
sequence of cards and forms, and when rebuilding it would put honesty logic at
risk for little visible gain.

"Rebuilt" does not mean written from nothing. The console page is the starting
point: its hooks, state, API calls, polling intervals, query-parameter handling,
`DataNotice`/`LoadError` mounts and wording stay line for line. Only the markup is
rearranged for the phone. That is how nothing gets dropped.

| Screen | Treatment | Why |
|---|---|---|
| Frame (top bar, back header, tabs) | new | The design's main change |
| Home | rebuilt | Attention first, today's figures, live camera |
| Alerts | new | The console bell's list as a full screen |
| Cameras, one camera | new | The console has no such page; built from roster + detections |
| Tools, More | rebuilt / new | Lists behind tabs |
| Attendance, Counting, Lost bag | rebuilt | Chips + sheets, hero result, cards |
| Restricted zones, Knife detection | rebuilt | Review card, toggles, clips as cards |
| Vehicle gate (page + Live tab) | rebuilt | Segmented tabs, stat grid |
| Vehicle Movements / Register / Reader / Passes / PlateEditor | copies, restyled | ~1,900 lines of forms and per-row honesty (dashes, 30-day photos, admin writes); already cards on a phone once `.row` is styled |
| People, a person, a group | rebuilt | Cards, person screen with its actions |
| Track a person | copy, restyled | 1,738 lines; audit-before-return, estimate invalidation, three-way sweep empties, frame-fraction hit tests. The design's arrangement (segmented modes, stacked form, timeline) is reachable with CSS |
| Enrol | copy, restyled | `detections={false}`, polling rules, score thresholds |
| System health | rebuilt (top) + CameraSources copy | Status card, pipeline, capacity, collapsible workers; camera setup (1,318 lines, credentials) stays the console's |
| Settings | rebuilt + AlertSettings copy | Profile rows read-only (R10); alert rules/recipients/log stay the console's |
| Accounts, Sign-in | rebuilt (light) | Cards; the console's dead "Edit" button is not copied (R10) |

**Alternatives.** Rebuilding everything from scratch was rejected: about 11,000
lines of risk, and the inventory found dozens of per-screen rules a fresh
rewrite would drop. Keeping every page a copy (spec 014) was rejected by
Mohamed on 17 September.

## R2. The alert bell's logic is shared, not re-implemented

**Decision.** Lift the non-visual half of `web/src/components/AlertBell.tsx` into
`app/useAlertFeed.ts`: `feedState`, `statusLine`, the per-account seen-list
(`vg.alerts.seen.<account>`, 500 cap, cross-tab `storage` event), `unread`, the
new/seen split and `markSeen`. It goes on `PARITY_FILES`. The console's bell
renders exactly as before from the hook. The phone's `TopBar` shows the marker,
and its `Alerts` screen shows the two groups.

**Rationale.** FR-045 asks for "the same count". Two copies of the seen-list
logic are the drift `check_parity.py` exists to stop, and its header says to
split a differing file rather than exempt it.

**Alternatives.** A mobile copy of AlertBell was rejected because it would drift.
Moving the whole bell into shared code was rejected because the dropdown is
console presentation.

**Behaviour to keep** (critic findings): the demo notice when the attention
capability is `demo`; a ring only when a new id arrives, never on first load;
the marker shows `!` when the feed is not ready and `9+` above nine; opening the
list marks every open item seen, and items arriving while it is open are seen
as they land; the order is engine down → failed → checking → off → ready. On the
phone, "open" means the Alerts screen is mounted. There is no dropdown, so
Escape and outside-tap do not apply. Back closes it.

## R3. `useLinkedItem` becomes shared

**Decision.** Copy `web/src/app/useLinkedItem.ts` to the phone byte-for-byte and
add it to `PARITY_FILES`. Knife detection, Restricted zones, Vehicle alerts and
System health use it as the console does: the linked item gets an outline, is
scrolled into view once, and shows "not in this window" when it is missing.

**Trap.** `holdInView` observes `document.body`, which never grows on the phone
because the page scrolls inside `.app__content`. The first `scrollIntoView` still
works, so the item lands in view; later growth above it can push it off. That is
accepted rather than forking the hook. It is noted in `gaps.md` if the by-eye
check shows it.

## R4. Choices open from chips into a bottom sheet

**Decision.** The phone's `ui.tsx` `Select` keeps its props (`value`, `onChange`,
`options`, `label`). It renders a chip showing the current label, and tapping
the chip opens `Sheet` with one 44+ px row per option and a tick on the current
one. Every screen that uses `Select`, copies included, gets sheets without an
edit. A raw `<select>` in a copied component stays native: a phone browser
already opens it as a bottom picker. Date and time inputs stay native pickers
for the same reason.

`Field` + `Select` inside a rebuilt screen's filter row renders as chips in a
horizontally scrolling `.chips` strip (label in the sheet title, not above the
chip).

## R5. Header, back and tabs come from one route table

**Decision.** `app/tabs.ts` holds `TABS` (home, cameras, tools, people, more) and
`SCREENS`, an ordered prefix table: `{ prefix, tab, title: MessageKey, parent }`.
`AppShell` shows `TopBar` when the path is a tab root (`/`, `/cameras`, `/tools`,
`/people`, `/more`). Every other path gets `ScreenHeader`, with its title from
`SCREENS` and a back arrow. Back calls `navigate(-1)` when
`window.history.state?.idx > 0`, else `navigate(parent)`. The arrow is
`.mirror-rtl`, so it points right in Arabic.

Tab ownership: `/cameras*` → cameras; `/attendance /counting /lost-items /track
/intrusion /weapons /vehicles /tools` → tools; `/people*` → people; `/system
/settings /users /more` → more; `/alerts` and `/` → home. `/account` redirects
to `/more`.

**Pages' own titles.** On the phone, `PageHeader` renders the lead only: the title
is already in the header, and a second big title wastes the first screen. Copied
pages need no edit.

## R6. Contrast and size are fixed in the phone stylesheet

**Decision.** `styles/tokens.css` is shared and cannot change for the phone.
`styles/app.css` re-declares only the failing text tokens on the phone's root:
`.app { --tx3: … }` and `body.dark .app { --tx3: … }`, plus `--tx2` and `--am`
where the audit finds them under 4.5:1. The starting values are the ones the
canvas used: light `--tx2 #4c5a52`, `--tx3 #63706a`, `--am #765a0f`; dark
`--tx2 #b0bcb4`, `--tx3 #93a198`, `--am #dcb461`. The audit script
(quickstart §3) is what decides whether they stay. There is no text under 12 px,
and body text is 15 px. Inputs are 16 px, or iOS zooms on focus.

`.btn { width: 100% }` is removed (audit finding 1, 12 Sep): full width only
where a screen asks for it. `.app__content [style*=grid-template-columns]`
folding stays, but only inside restyled copies (`.legacy` wrapper class set by
those pages' route element). Rebuilt screens use real grids.

## R7. Home's "Today so far"

**Decision.** `app/useTodayFigures.ts` (phone only) makes four reads, each
refreshed every 30 s, each failing on its own:

| Figure | Call | Shown | Unknown / off |
|---|---|---|---|
| Arrived | `getAttendance({mode:'group', subject: everyone, date: today})` | `result.heading`, first two stats | capability `attendance` not live → its notice word |
| People in view | `getCount({place: all, window: 'now'})` | `result.heading` number + `result.sub` (percentage only when the engine gives one) | same pattern |
| Cars in | `getVehicleSummary()` | `entered` (null → "—") | `reason` |
| Restricted areas | `getBreaches('today')` + `getZones()` | breach count today, paused-zone count | same |

Each tile opens its tool with the same query the tile read. A figure whose
capability is `unavailable` shows the capability's short state ("Not running"),
never 0. While the first answer is on its way it shows "…", not a number.

**Alternative.** Leaving the figures out was rejected: all four are backed by calls
the console already makes, and Mohamed approved them.

## R8. Cameras tab and the one-camera screen

**Decision.**
- **Cameras**: `useCameras()` roster grouped by area, in first-appearance order,
  with chips All / Live / No signal counted client-side. Counts come from
  `getCameraCounts()` at CamGrid's rate, with null → "—". Tiles are plain pictures
  (`tileOverlay` off) with name, area, count, or "No signal · last picture HH:MM"
  when offline. Tap → `/cameras/:id`.
- **One camera**: `CameraFrame size="lg" live` with `feature` from a segmented
  control: Faces (`attendance`) · Counting (`counting`) · Lost bag (`lost`) ·
  Knife (`weapons`), default from `?feature=`. Only that feature's boxes are
  drawn. The legend shows only for Faces. The in-view count comes from
  `onCount`. `RecordButton` sits under the picture as in the console modal.
  "Other cameras" is a horizontal strip.
- **In view now** (Faces only): one row per box from `onBoxes`. A green box's
  label is shown as the name with a "Face" badge; every other box reads "Not
  identified". `_face_boxes` sends no clothing matches, so there are no blue rows
  on this overlay. **Follow** is shown only if `startFollow(camera.id, cx, cy)`
  followed by `/track` is verified to show the active follow (context §5).
  Otherwise it is left out and listed in gaps.

## R9. Camera parts brought level with the console first

**Decision.** Before building on them, bring `mobile/src/components/CameraFrame.tsx`,
`CameraModal.tsx`, `CamGrid.tsx` and `VehicleAlerts.tsx` level with the web copies:
stream released on unmount (`StreamImage`), `STALLED_MS` back-pressure, the
modal's header, count and `RecordButton`, CamGrid's `activeRef`, VehicleAlerts'
linked item and i18n. Then change only their layout for the phone. The phone's
`CameraModal` is a full-screen layer with `ScreenHeader`-style back, not a
centred dialog. A copied page that opens it keeps its state underneath.

## R10. Console defects are not copied onto the phone

Found by the inventory, and reported rather than fixed, because the console must
not change here:

| Console defect | Phone does |
|---|---|
| Settings' school-profile "Edit" changes local state only; nothing is saved | Shows the profile read-only |
| Accounts' per-row "Edit" button has no handler | Leaves it out |
| Lost bag's empty text lowercases a raw key (`lost.colour.red`) | Uses the translated colour name |
| Hard-coded English on Settings, Attendance lead, Vehicle reader, Lost bag "offline", Intrusion notes | Copied as-is where the component is copied; rebuilt screens use the same literal text (no new keys invented for console wording) |
| System health's camera grid can draw face boxes with names | Phone passes `detections={false}` there |
| Phone Home opened `item.to` (tool page), not `item.link` (the exact item) | Rebuilt Home uses `item.link` |
| Phone CameraFrame never released its stream | Fixed by R9 |

These go to Mohamed in the closing report. Each can become its own task.

## R11. Tools rows show state, not live counts

**Decision.** Each of the seven rows shows its name and the console's blurb. When
the tool's capability is not `live`, the row adds its short state ("Not running",
"Demo data") in amber. Live counts on every row would add seven polls to a list
screen. The four figures that matter are on Home (R7). The design's per-tool
counts are recorded in `gaps.md` as deliberately left out.

## R12. Wording

**Decision.** Every new phone word is a key in the shared catalogue: `keys.ts`,
`en.ts`, and an Arabic draft in `ar.draft.ts`. It is written in `web/src/i18n` and
the bytes are copied to the phone. The union changes from
`nav.tab.${home|tools|people|system|account}` to
`nav.tab.${home|cameras|tools|people|more}`. `nav.tab.home` becomes "Home" and its
Arabic draft becomes الرئيسية. Other new keys sit under `phone.*`. The console
renders none of them. All three files are CRLF: edit with the Edit tool or
byte-safe scripts, then check `git diff --stat`.

## R13. Brand in the top bar

**Decision.** `Logo` (the console's mark) at 32 px plus "VisionGuard", the
product name without the sidebar's "AI" suffix, which does not fit next to the
status line at 360 px. The site name, when set, replaces nothing: it is shown on
More. The status line is `topbar.*` wording with the console's colours, and the
date is `todayLabel`'s date part. The time is left out, because the console's
time is a browser-clock snapshot refreshed every 30 s (critic finding) and a
phone header has no room for it.

## R14. Verification without a real phone

**Decision.** Use the in-app browser at 360×780, the temporary dev sign-in, and
the side-port engine on the recorded clip (see memory: `dev-signin-temporary`).
The audit script from quickstart §3 is run on every route in 4 variants and
reports sideways overflow, targets under 44 px, contrast under the limit and
text under 12 px. Only things a hand or a real camera can judge go to Mohamed.

## R15. Gap register (initial, finalised in `gaps.md` during implement)

| # | Design part | Why it is not built as drawn | What the phone shows instead |
|---|---|---|---|
| G1 | Per-tool live counts on Tools | Seven extra polls on a list screen | Blurb + capability state (R11) |
| G2 | "Features running on it" per camera tile | Only the admin-only `/sources` sends it | Name, area, count |
| G3 | "· retrying" on offline tiles | The roster does not say a retry is happening | "No signal · last picture HH:MM" |
| G4 | "Not set up on this camera" per overlay | No per-camera, per-feature flag for non-admins | "No boxes from this feature right now" |
| G5 | Blue "clothing match" rows in In view now | The Faces overlay sends no clothing matches | Face / Not identified rows |
| G6 | Per-person Follow button | Pending check (R8) | Link to Track a person, if not verified |
| G7 | Photos-on-file grid + Add photo | The engine keeps embeddings, not photographs | "Face on file · N photos" badge |
| G8 | Person's "Today" timeline of sightings | Engine sends last seen + day bars, not each sighting | Last seen + the console's day-by-day history |
| G9 | "No recorded video from…" with recording-range chips | The leg job returns one error string | The console's failed-footage message |
| G10 | One search for camera or name on Catch now | The console's search filters cameras only | Camera search |
| G11 | Movements chips Today / All / Not registered / Blacklisted | The console has day, search and gate filters | The console's filters |
| G12 | "N things need attention" on More's System health row | No summary count without loading all of System health | Row without a count |
| G13 | Knife "N waiting" | The console counts entries in the window and "still in view" | The console's two counts |
| G14 | Zones badge "Watching" | The console says "Protected" | "Protected" / "Paused" |
| G15 | Tap-to-edit school profile | The console's edit saves nothing (R10) | Read-only rows |
