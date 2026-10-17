# Gaps: what the approved design shows that the phone does not

This is the closing report for P13-FR-059 / SC-009. It lists every part of the
canvas that was left out or changed, why, and what the phone shows instead. It
also lists the console defects the rebuild found, and what only a real phone
can confirm.

## Before this feature

Checked 17 September 2026 at `34e2bef`, plus the uncommitted tree:

- console and phone `tsc`: clean
- parity: 26 files identical
- no fixtures
- pyflakes: clean
- pytest: 1889 passed, 6 skipped

Nothing was failing.

## Design parts not built as drawn

| # | Design part | Why | What the phone shows instead |
|---|---|---|---|
| G1 | Per-tool live counts on Tools | They would add seven polls to a list screen, and the four figures that matter are on Home | Each row shows its blurb. When the tool is not live, an amber line gives the state and the engine's reason |
| G2 | "Features running on it" on each camera tile | Only the admin-only `/sources` sends it | Name, area and headcount |
| G3 | "· retrying" on offline tiles | The roster does not say whether a retry is happening | "No signal · Last picture HH:MM" |
| G4 | "Not set up on this camera" for an overlay | Non-admins get no per-camera, per-feature flag | "No boxes from this feature right now." |
| G5 | Blue "clothing match" rows in In view now | The Faces overlay sends no clothing matches | Face rows (name + score) and "Not identified" rows |
| G5b | A colour legend on one camera | Colours mean different things per feature (an unknown face is blue on Faces; blue is a clothing match on Track) | No legend; the In view list says it in words |
| G7 | Photos-on-file grid and Add photo on a person | The engine keeps face measurements, never the photographs | The console's recognition line ("Recognised · 5 photos") |
| G8 | A person's "Today" timeline of sightings | The engine sends last seen and day-level history, not each sighting | Last seen, plus the console's day-by-day history |
| G9 | "No recorded video from…" with recording-range chips | The footage job returns one error string | The console's failed-footage message |
| G10 | One search box for a camera or a name on Catch now | The console's search filters cameras only | Camera search |
| G11 | Movements chips: Today / All / Not registered / Blacklisted | The console filters by day, text and gate | The console's filters |
| G12 | "N things need attention" on More's System health row | No count exists without loading all of System health | The row with a fixed description |
| G13 | Knife detection "N waiting" | The console counts entries in the window and entries still in view | The console's two counts |
| G14 | "Watching" badge on Restricted zones | The console says "Protected" | "Protected" / "Paused" |
| G15 | Tap-to-edit school profile | The console's edit saves nothing (see below) | Read-only rows with a note that changing them from the app is not available yet |
| G16 | The "rows overlap" note under Groups & grades | The sentence is not in the console | The console's own groups lead |
| G17 | The site date in the top bar | No room beside the camera status at 360 px | Home shows the full site date under the greeting |

Built after all:

- **G6, the per-person Follow button.** Track picks up a follow started from
  anywhere on its first poll. So Follow calls `startFollow` with the box centre,
  as a fraction of the frame, then opens Track.

## Console defects found (not changed here; the console is out of scope)

Each can become its own task. The phone does not copy any of them.

1. **Settings: school profile "Edit" saves nothing.** It only changes local
   state, and no API writes it back. That is a fake save in a production path
   (constitution III). The phone shows the rows read-only.
2. **Accounts: the per-row "Edit" button has no handler.** It is a dead
   button. The phone leaves it out, so neither app can edit a user today.
3. **Lost bag: the empty sentence lowercases a raw key** (`lost.colour.red`)
   instead of the translated colour. The phone uses the translated word.
4. **System health: the camera grid can draw face boxes with names.** No
   feature is passed, so the enlarged view falls back to faces. The phone
   passes `detections={false}` (CamGrid gained that prop on the phone only).
5. **Restricted zones: `?scene=` links from the bell are not highlighted.**
   The console never wires `useLinkedItem`, so there is no outline and no "not
   in this window" note. The phone wires it, as Knife detection does.
6. **Restricted zones: the switch is shown to every role.** The server refuses
   a guard. The phone shows it only to administrators, as a courtesy.
7. **People: "Enrol a face" is shown to every role.** Enrolment is admin-only
   on the server. The phone shows it only to administrators.
8. **Enrol: Save's disabled reason is only a hover tooltip.** On the phone it
   is written under the buttons.
9. **Vehicle reader: `votesNeeded === 0` never counts as agreed.** The row reads
   "X/0 frames agree" indefinitely. It is untouched in both apps.
10. **Untranslated English** in the console's Settings, Attendance lead,
    Restricted zones notes, Vehicle alerts header, Vehicle reader and Lost bag
    "offline". Where the phone shows the same words, it keeps the same literals
    rather than inventing keys.
11. **The console top bar colours "Engine unreachable" with `var(--bd)`,** which
    the palette never defines. The phone uses red.
12. **The phone's old Home opened an alert's tool, not the item itself**
    (`item.to` instead of `item.link`). Fixed by the rebuild.
13. **The phone's old camera frame never released its MJPEG stream on close.**
    Fixed by bringing it level with the console's.

## Only a real phone can confirm

- One-handed use, the notch and the home indicator, and the tab bar above the
  safe area.
- The on-screen keyboard covering Ask, sign-in or a plate field.
- The Export sheet download (object-URL download) in a phone browser.
- Live MJPEG pictures and the knife clip playing inline on mobile data.
- Draft Arabic wording read by a native speaker (the text is a draft, as
  before).

## Appendix: 360-px audit

The audit script is `tools/phone_audit.js`. It ran in the in-app browser at
360 × 780 against the mock engine (`mock-mobile`, developer sign-in as admin) on
17 September 2026, after the fixes listed below. It counts four things per
route: sideways overflow, targets under 44 px, text under 4.5:1 (3:1 at 24 px
or larger), and text under 12 px.

| Route | en dark | en light | ar dark | ar light |
|---|---|---|---|---|
| `/` | clean | clean | clean | clean |
| `/alerts` | clean | clean | clean | clean |
| `/cameras` | clean | clean | clean | clean |
| `/cameras/:id` | clean | clean | clean | clean |
| `/tools` | clean | clean | clean | clean |
| `/attendance` (form, and with a result) | clean | clean | clean | clean |
| `/counting` (form, and with a result) | clean | clean | clean | clean |
| `/lost-items` | clean | clean | clean | clean |
| `/track` | clean | clean | clean | clean |
| `/intrusion` | clean | clean | clean | clean |
| `/weapons` | clean | clean | clean | clean |
| `/vehicles` (Live, Movements, Registered) | clean | clean | clean | clean |
| `/people` | clean | clean | clean | clean |
| `/people/history/:name` | clean | clean | clean | clean |
| `/people/groups/:name` | clean | clean | clean | clean |
| `/people/enrol` | clean | clean | clean | clean |
| `/more` | clean | clean | clean | clean |
| `/system` | clean | clean | clean | clean |
| `/settings` | clean | clean | clean | clean |
| `/users` | clean | clean | clean | clean |

What the first pass found, all fixed before the table above:

- The zone and DVR-channel switches were 32 px tall. They now have a 44 px
  target with a 32 px track inside.
- A Lost bag area row was 40 px, and a person's open button on People was
  42 px.
- Track's step numbers were 11.5 px. Copied parts' inline text under 12 px is
  now lifted to 12.
- System health's camera-source rows scrolled 51 px sideways, and their
  Edit/Remove links were 34 px wide.
- Vehicle register chips, "Download template" and "Add a vehicle" were 33–40 px
  tall.
- The segmented controls were 40 px.
- The badge glyphs and the bell count were 10–11.5 px.

The mock engine has no knife entries, so the knife review card was measured by
reading the code, not on screen.

**Engine down.** Every engine request was made to fail in the tab. Within 30 s
the top bar and the attention list said "Engine unreachable" and the bell
showed "!". All four Home figures showed "—" with "Could not load"; none showed
0.
