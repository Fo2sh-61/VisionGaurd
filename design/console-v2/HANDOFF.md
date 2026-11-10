# VisionGuard console v2 — design handoff

Implementation brief for a Claude Code session working in `Fo2sh-61/VisionGaurd`.
Read `AGENTS.md` and `.specify/memory/constitution.md` first; they outrank this file.

## What is in this folder

| Path | What |
|---|---|
| `design/VisionGuard Console.dc.html` | **The design, in one file.** Markup at the top (`<x-dc>`), then a `class Component` whose `renderVals()` holds every screen's behaviour, all wording (`T` + `T2`, English and Arabic) and the mock data. Treat it as the reference for layout, states and copy, not as code to paste. |
| `design/VisionGuard Console - Canvas.dc.html` | The canvas: the console twice, `role="admin"` and `role="it"`, 1440×900. |
| `design/support.js` | Runtime for the two files above (they only render inside the design editor). |
| `design/assets/visionguard.png` | 128 px export of `assets/visionguard.ico` (window/title-bar icon). |

The live, clickable version is the canvas artifact this was exported from — use it to see states; use this folder to read exact values.

**Every number, name, plate and event in the design is mock data.** Constitution rule 4: none of it may become a fixture in a production path. Each value maps to an engine endpoint below, or the UI says plainly that it is unavailable.

## Scope

Desktop console (Ubuntu window, 1440×900 baseline) for the web app in `web/`. Look = the current console's tokens, trimmed and reorganised.

**Kept / extended:** Home + Ask, Attendance, People (directory, groups, enrol), Population (= `Counting`), Car plates (= `VehicleGate`), Cameras, System health & configuration, Settings, Accounts (= `Users`).
**New:** Restricted zones (redesign of `Intrusion` with drawn polygons), Work stations (new feature), full-screen camera wall.
**Removed from navigation (code may stay):** Lost bag, Track a person, Knife detection. Not part of v2.

## Global shell

- **Brand:** name is **"VisionGuard"** — never "VisionGuard AI". Mark = `web/src/components/Logo.tsx` unchanged (accent square, lens with one square corner). Window icon = `assets/visionguard.ico`.
- **Sidebar:** logo + site name (from Settings › Site name). Main: Home, Attendance*, People*, Population, Car plates, Restricted zones, Work stations, Cameras. Section "SYSTEM": System health & configuration, Settings. Badges: Attendance = not arrived, Car plates = open gate alerts, Restricted zones = zones with someone inside, Work stations = stations absent past limit. Bottom card "Site is calm / N things need attention". (*admin only)
- **Accounts is NOT in the sidebar** — only in the user menu.
- **Top bar:** date · "N of M cameras up" (opens System health) · bell (popover: alerts list, "Mark all read") · user (name, role, initials avatar) → menu: System health & configuration, Settings, Accounts (admin only), language switch, theme switch, Sign out.
- **Arabic top bar order (RTL), right → left:** date … cameras up · avatar · name · bell (bell is the last item, far left). LTR keeps date … cameras · bell · name · avatar.
- **Toast** bottom-centre for every save/dismiss ("Cleared — recorded under your name.").
- **Sign in** with "Create account" (full name, email, password, confirm; note: new accounts get limited access). API: `signIn`, `register` exist.

## Roles (from `web/src/services/content.ts` CAPABILITIES, extended)

| Capability | Admin | IT |
|---|---|---|
| See alerts and camera views | ✓ | ✓ |
| View attendance and people records | ✓ | — |
| Enrol faces | ✓ | — |
| Edit the vehicle register (add/edit/remove/import, fix plate, remove pass, renew, blacklist) | ✓ | — |
| Export attendance and gate logs | ✓ | — |
| Add or remove cameras and recorders | ✓ | ✓ |
| Draw, pause or delete zones and stations | ✓ | — (open question for the owner) |
| Manage accounts | ✓ | — |

IT view: no Attendance/People in nav, no attendance card/alert/suggestions on Home, Ask about attendance answers "Attendance and people records are open to administrators only." Read-only screens show a one-line "Only an administrator can…" note where the controls would be; dismissing gate alerts and acknowledging station alerts stay allowed for IT. Settings for IT: profile and alert rules read-only, recipients show Receiving/Switched off, appearance & language editable. **The engine enforces roles; the UI only hides** (see `RequireRole` comment in `app/routes.tsx`).

## Screens

### Home
Greeting · Ask box + suggestion chips (routes to a screen with filters set; toast "Opened X") · 3 feature cards (Attendance*, Population, Car plates with last plate chip) · live camera strip (4 tiles, "All cameras →") · "Needs your attention" cards, each with its action link and **Acknowledge** (`getAttention`, `acknowledgeAttention`). Empty state: "✓ Nothing needs your attention."

### Attendance (admin) — `pages/Attendance.tsx`, `getAttendance`, `exportAttendance`
Header: Enrol a face · Export CSV. Entrance-camera strip + note "Face recognition runs on the doorway cameras only. Green box = recognised, red = not enrolled." Status tiles (Everyone/On time/Late/Not arrived/Excused — click filters). Filter row: **Date** (past days; banner "Showing {date} — as it was recorded that day."), **Group**, search. Table: name, department, arrived, camera, status. Detail panel: status, snapshot, first/last seen, last 7 working days, Notify manager (disabled placeholder until messaging exists — must say why, rule 4), Mark excused.

### People (admin) — `People.tsx`, `PeopleGroup.tsx`, `PersonHistory.tsx`, `Enrol.tsx`
Tabs Directory / Groups. Directory: type chips All/Staff/Visitors with counts, group chip (from Groups), search; columns name, type, group, face photos, today; actions History (→ Attendance with person selected), Remove (inline confirm: "Their face photos are deleted… Past attendance stays.") — `removePerson`. Groups: cards with people count, on site today, attendance last 30 days, "See who's in it →". **Enrol:** step 1 name/type/group/detail → step 2 camera picker (offline camera explains itself), live preview with face box, Capture / Upload photos, 5 slots, unusable photo flagged ("2 faces in shot…") with Remove, Save enabled at 5 usable; leaving with photos asks "Discard and leave / Stay" → step 3 Saved: View in People / Enrol someone else. API: `startEnrolment`, `captureEnrolmentPhoto`, `addEnrolmentPhoto`, `removeEnrolmentPhoto`, `commitEnrolment`, `cancelEnrolment` exist.

### Population — `Counting.tsx`, `getCount`
Total on site now. Range: **Right now / Today by hour / Last 7 days** (the engine's windows today are Right now / Today by hour / This week by day — align naming with the engine). Area cards: count, level chip (Empty/Quiet/Busy/Near capacity/**Over capacity**), capacity bar, sparkline. **No capacity configured → no percentage or level** (rule 5). Detail panel: chart for the range, peak, cameras covering the area. Note: overlapping cameras are summed, treat as upper bound.

### Car plates — `VehicleGate.tsx` + components; all endpoints exist
Tabs **Live / Movements / Registered vehicles**. Plates render with `components/Plate.tsx` (Arabic letters, Indic digits, "مصر · EGYPT" band, Latin under it via `plateLatin`).
- **Live:** gate alerts strip (blacklisted / not on register / permit expired; actions Add to the register · Renew the permit · dismiss labels from `alertDismissLabel`) — `getVehicleAlerts`, `dismissVehicleAlert`. Six tiles (Entered, Left, Inside now, Not registered, Blacklisted, Cameras reading) — `getVehicleSummary`; click filters the reads table. Gate camera strip. Reads table → detail panel: big plate, status, snapshot, vehicle/owner, **reader: confidence, votes, plate width**, **Fix** (letters + digits editor → `correctVehiclePlate`), seen this week, actions by status, Remove this row (`deleteVehiclePass`).
- **Movements:** Day, plate/owner search, gate, Export this day (`exportVehiclePasses`) · traffic chart in/out by hour (`getVehicleTraffic`) · gate by gate · Inside now with **Gone** (`getVehiclesInside`) · Completed visits with "Exit estimated" (`getVehicleVisits`).
- **Registered vehicles:** import card (Download template, Upload Excel/CSV, last import line — `importVehicles`, `getVehicleLastImport`), search, category chips All/Staff/Visitors/VIP/Blacklisted, Add a vehicle; form plate (letters + digits), owner, phone, unit, category, permit valid until, make, colour, notes; table with Edit / Remove (inline confirm) — `getVehicleRegister`, `addVehicle`, `editVehicle`, `removeVehicle`.

### Restricted zones — redesign of `Intrusion.tsx` (polygon zones are NEW engine work)
Areas that must stay empty. Tiles: in zone now, entries today, zones watching, paused. Zone cards: camera picture with the polygon (red hatched, dashed edge), "ENTERED ZONE" box on the person, status chip Person in zone / Zone clear / Paused, schedule line, in-zone-now / entries-today, pause switch (pauses visible to everyone: "Paused by {name} · {time}"). Detail: live picture, counters, Watched (Always / Outside working hours / Custom hours), Alert (immediately / after N s), event log Today / 7 days with **Watch clip** (last 3 clips per camera; older entries have none), Edit zone, Pause/Resume.
Inside = **feet point** inside the polygon (draw on the floor).

### Work stations — NEW feature (engine + UI)
Areas that must stay staffed. Tiles: staffed now, away, absent past limit, on-station rate today. Station cards: polygon coloured by state — On station (green) / Away (amber) / Absent — alert (red, after the empty-time limit) / Not started (grey, "opens 9:00"); assignee line; working and absence time, on-station %, today's timeline. Detail (mirrors the reference video's panel): status bar, working/absence time, on-station rate, timeline (on/away/absent segments), event log (At station, Left station, Absence alert — over N min, Alert acknowledged), rules (assignee, limit, schedule), **Acknowledge alert**, Edit station.
- Presence = anyone inside by default. **Optional assignee:** only that person counts, recognised by face; if the camera cannot resolve faces (~80 px) the UI warns and anyone counts. Constitution rule 2: the name is a per-frame annotation, never a stored binding carried forward.
- Watched: **Working hours** (from Settings) or **Custom hours** (from/to). No "Always".

### Zone / station editor (shared)
Back link, title, click-to-place points on the camera picture (min 3; Undo last point, Clear; point count shown), name, camera, **When is it watched?** (zones: Always / Outside working hours / Custom; stations: Working hours / Custom), zone: alert after N s; station: assigned person (optional) + face-distance note, alert when empty > N min; Notify In-app / Email (recipients in Settings › Alerts); Save (disabled until name + 3 points) / Cancel / Delete (inline confirm). **Points travel to the engine as fractions of the frame (0–1), never pixels** (rule 6) — the design stores percentages for drawing only.

### Cameras
Grid 2×2 / 3×3 / 4×4, filter chips (All, Attendance, Population, Car plates, Restricted zones, Work stations, No signal), search "Find a camera or area", tiles with feature tag and current reading; tile → full-screen single camera (prev/next, strip, stream address, Record — `startRecording`/`stopRecording`; offline shows last frame clearly marked). **Full screen** button → camera wall: dark full-window grid of the current filter, top bar (title, cameras up, alerts waiting, clock, grid size, pager ‹ n/m ›, Exit), tiles show only name, Live/No signal, feature, reading (plate chip for gates); amber ring = unknown plate / station away, red ring = person in zone / station absent; Esc exits, ←/→ page; tile opens the single-camera view on top.

### System health & configuration — `SystemHealth.tsx`, `CameraSources.tsx`
As today: cameras online, pipeline with workers, capacity bars + per-worker table, camera sources (edit: name, area, address, rotation, switched on, watch-for features incl. **Restricted zones** and **Work stations** — "shares the person detector", gate/direction for plates, analytics rate with recommendation), add via Scan / DVR-NVR / IP camera / RTSP, cameras needing attention.

### Settings — `Settings.tsx`, `AlertSettings.tsx`
Site profile (click to edit, auto-save): site name, working hours, **working calendar (from–to dates; replaces school "Term")**, attendance cut-off. Alerts: rows Gate alert (+ which gate kinds), **Restricted area entered**, **Work station left empty**, Camera offline, Daily attendance — In-app / Email chips. Recipients (send test, remove, on/off, add with language). What was sent (log, Refresh). Appearance & language (dark mode, English/العربية). Detection-zones card from v1 is gone (zones have their own page).

### Accounts (admin, from user menu) — `Users.tsx`
"{n} people can sign in", rows with role badge, email, last active, Edit → role select (Admin/IT). Role table as above.

## Arabic / RTL rules
- `dir="rtl"` on the root; use logical CSS (`inset-inline-*`, `margin-inline-*`, `border-inline-*`, `text-align:start/end`). Toggle knobs and badges must use logical properties.
- **No `letter-spacing` on Arabic** (breaks letter joins) — the design zeroes it under `[dir="rtl"]`.
- Email, password, time, date, number inputs: `direction:ltr`, right-aligned. Emails, IPs and phones inside Arabic sentences are wrapped in LRI/PDI isolates (`⁦…⁩`).
- Time-series (sparklines, population bars, gate traffic, station timelines, 7-day attendance strip) stay **left-to-right** in Arabic.
- Arrows flip in copy (`Open →` / `← فتح`, back links `← People` / `→ الأشخاص`).
- Data from the engine (camera names, areas, durations, day names, colours) needs Arabic — the design's `PLACE_AR` / `COL_AR` tables show the expected wording; the real fix is engine-side display names or i18n keys, not string replacement.
- Arabic font: Noto Sans Arabic, line-height 1.65.

## Tokens
From the design's `PAL` (light/dark) — matches `web/src/styles/tokens.css` plus: `--chrome`, `--frame` (camera background), `--det-green #3ec776`, `--det-red #e5564a`, `--det-amber #dfa23f`. Density A: base 15px, page padding 34/40/60, H1 28px, detail panel 360px, content max 1080px. Fonts: Albert Sans (UI), Noto Sans Arabic, JetBrains Mono (addresses), Ubuntu (window chrome).

## i18n
All new wording is in the design's `T2` object (en + ar). Move it into `web/src/i18n/keys.ts`, `en.ts`, `ar.draft.ts` (Arabic stays "draft" until reviewed by a native speaker, per spec 008).

## Engine work (new endpoints / features)
1. **Zones with polygons:** extend zones to `{ id, name, camera_id, polygon: [[x,y]…] (fractions), schedule: always|outside_hours|custom{from,to}, alert_delay_s, enabled, paused_by, paused_at, notify{in_app,email} }`; CRUD + events with clip refs (`getBreaches` today). Feet-point-in-polygon test in the intrusion feature.
2. **Work stations:** new feature per `AGENTS.md` "four files" (`features/stations.py` on the shared person detector, `events/stations.py`), `{ id, name, camera_id, polygon, assignee?, empty_limit_min, schedule: working_hours|custom{from,to}, notify }`, live state (on/away/absent/closed, away_for), today's totals, timeline segments, events, acknowledge.
3. **Accounts:** change a user's role (admin only, audited).
4. **Alert kinds:** `zones`, `stations` in alert settings + delivery log.
5. **Camera features:** `stations` alongside `intrusion` in the camera's `features:` list.

Suggested start: put this folder at `design/console-v2/`, then `/speckit-specify` one spec per area (shell + roles, people/enrol, plates, zones, stations, camera wall) rather than one giant spec.
