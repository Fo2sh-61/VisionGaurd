# Contract: phone screens

What each phone screen must offer. "Keep" lists are the console facts and
actions that must survive the rearrangement. They are the minimum, not the whole:
the console page itself is the full checklist, and a rebuilt screen starts from
it (research R1).

## Routes and tabs

| Path | Tab | Header | Screen | Admin only |
|---|---|---|---|---|
| `/` | home | TopBar | Home | |
| `/alerts` | home | back → `/` | Alerts | |
| `/cameras` | cameras | TopBar | Cameras | |
| `/cameras/:id` | cameras | back → `/cameras` | One camera (`?feature=attendance\|counting\|lost\|weapons`) | |
| `/tools` | tools | TopBar | Tools | |
| `/attendance` | tools | back → `/tools` | Attendance | |
| `/counting` | tools | back → `/tools` | People counting | |
| `/lost-items` | tools | back → `/tools` | Lost bag | |
| `/track` | tools | back → `/tools` | Track a person | |
| `/intrusion` | tools | back → `/tools` | Restricted zones | |
| `/weapons` | tools | back → `/tools` | Knife detection | |
| `/vehicles` | tools | back → `/tools` | Vehicle gate | |
| `/people` | people | TopBar | People | |
| `/people/enrol` | people | back → `/people` | Enrol | yes |
| `/people/groups/:name` | people | back → `/people` | A group | |
| `/people/history/:name` | people | back → previous (group or `/people`) | A person | |
| `/more` | more | TopBar | More | |
| `/system` | more | back → `/more` | System health | |
| `/settings` | more | back → `/more` | Settings | |
| `/users` | more | back → `/more` | Accounts | yes |
| `/login` | — | none | Sign-in | |
| `/account` | — | redirect → `/more` | — | |

**The paths are a contract.** Ask answers and alert links deep-link into them
with query parameters. Keep every parameter the console reads:
`/attendance?mode&subject&date`, `/counting?place&window`, `/weapons?window&entry`,
`/intrusion?window&scene`, `/vehicles?tab&plate&date&gate&pass`,
`/track?person&date` (fills in, does not run), `/people?query`,
`/system?camera`. Navigation carries `state.autoRun` exactly as the console does.

## Frame

- **TopBar**: Logo + "VisionGuard". Status line: `topbar.checkingCameras` /
  `allCamerasUp` / `someCamerasUp` / `engineUnreachable`, in the console's colours,
  plus the site date. Bell button (44 px) with the `useAlertFeed` marker → `/alerts`.
  Initials (44 px) → `/more`.
- **ScreenHeader**: back arrow (44 px, `aria-label` = `phone.back`, mirrors in RTL)
  and the screen title.
- **TabBar**: five tabs, 44 px or more each, `aria-current` on the active one,
  above the safe-area inset.
- `DevSignInBanner` stays pinned above everything.

## Screens

**Home.** Keep: the greeting, Ask with the result note and suggested questions,
and every attention item. For each item keep its kind badge, title, sub, the
action opening `item.link` with `autoRun`, and Acknowledge. New: the four
TodayFigures (data-model), and the first live camera from the roster → `/cameras/:id`.
Nothing-needs-attention wording appears only when the feed is `ready` and empty.

**Alerts.** Keep: every `useAlertFeed` state and its wording: engine down,
failed, checking, off + `offLead` + reason, demo notice, calm, waiting. Keep the
groups "New since you last looked" and "Still open", and each item's link. New:
"Messages sent" from `getDeliveries(…)`, only when that call succeeds; a refusal
hides the section.

**Cameras / One camera.** Research R8. Keep: `camera.lastKnown` degraded notice,
`camera.noneConfigured`, the offline last-frame notice, `RecordButton`, and the
count from the same poll as the boxes.

**Tools.** The seven `ask` + `watch` entries from `NAV`, with label, blurb and
non-live capability state.

**Attendance.** Keep: the group/person mode, group or person choice, date, Show,
Export sheet (with its error), heading and sub, stats, follow-up rows (group) or
recent days (person), Notify parent disabled with its reason visible (not only on
hover), the entrance cameras grid (no feature), and the `?mode&subject&date` link
with `autoRun`.

**People counting.** Keep: place, window, Show, heading and sub (percentage only
from the engine), stats, areas including `live:false` marked "demo figure",
`barsTitle` + bars with each segment's name/value/demo visible without hover, the
upper-bound note, cameras (`feature="counting"`), the 1 s refresh on "Right now"
only, and the empty states.

**Lost bag.** Keep: the `search_lost` DataNotice, area and camera ticks with
expand, offline banner (one/many), the colour chips (7 wire values), colour
note, the watching grid with `tileOverlay` and `feature="lost"`, the "possible
bag, not found" wording, and the empty states.

**Restricted zones.** Keep: the running breach status line, zone rows with
Protected/Paused badge, the toggle (admin: shown; others: badge only), the
pause-visibility note, the period (today/last7/last30), breach cards (zone, time,
people, duration, status, clip watch/hide, clip reason), the three empty states,
linked `?scene=` outline and missing notice, the plain camera grid (no feature),
and the 15 s / 3 s polls.

**Knife detection.** Keep: the `weapons` DataNotice and not-running empty state,
the seven-window period, the entry count and "still in view", cameras checked,
retention line from `useSite()`, and each entry card: clip (watch/hide, open in
new tab), camera · area, time, status text and tone, reviewer and time, reason
input, **Confirm knife** / **False alarm** (any role, 44 px, side by side under
the clip), per-entry busy and error. Also keep the linked `?entry=` outline and
missing notice, the grid with `tileOverlay` and `feature="weapons"`, and the
3 s / 15 s polls. There is no delete.

**Vehicle gate.** Keep: tabs Live/Movements/Registered with `?tab`. Live: the six
tiles (null → "—") with their notes, summary and cameras errors, VehicleAlerts
(resolve admin, dismiss, linked `?pass=`), gate cameras `feature="vehicles"`, and
VehicleReader (details, fix plate admin). Movements and Registered stay the console
components (R1).

**People.** Keep: search seeded from `?query`, type tabs with counts, each row
(name, sub or enrolled date, recognition line, last seen), open history, Track
today (`presetPerson`), Remove (admin, two-step, error), Enrol (admin), groups
list → group page, and the loading/error/empty variants.

**A person.** Keep everything `PersonHistory` shows: back target from state,
summary, day-by-day bars and flags, DataNotice/LoadError and the empty states. Add
Track today and Remove (admin, two-step) taken from the People row. Never a
camera picture.

**A group.** Keep: summary (`here` null → count only), roster → history with
`from: 'group'`, and the three states.

**Enrol, Track a person.** Console copies (R1). Keep `detections={false}` on
Enrol's camera, and the Save-disabled reason visible as text.

**System health.** Keep: the checking / engine-silent / LoadError-over-stale
states, cameras online, the summary, every pipeline row (name, detail, status,
tone), workers per stage (collapsible, all figures, `behind`), the capacity card
omitted when absent and every nullable figure → "—", the linked `?camera=`
notice, the needing-attention grid with `detections={false}`, and CameraSources
(admin, copy).

**Settings.** Keep: school profile values read-only, AlertSettings (copy: rules,
vehicle sub-reasons, recipients, test, delivery log, admin gating by disabling),
and the zones summary → `/intrusion`. Appearance and language move to More.

**More.** Account name and role, site name when set, System health, Settings,
Accounts (admin), dark mode (`useTheme`), language (`useLanguage().setLanguage`,
saved to the account), and Sign out (`useAuth().signOut`).

**Accounts.** Every user row fact from `getUsers(language)`, with no dead Edit.

**Sign-in.** Everything `Login.tsx` does, including the pre-account language
picker.
