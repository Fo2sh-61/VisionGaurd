# Feature Specification: Console v2 — shell, roles, Home, Population, Health, Settings, and the Jetson start

**Feature Branch**: `022-console-v2-shell`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: Console v2, the shell and everything that is mostly restyle: sidebar, top bar, toasts, sign in, the two roles, Home, Population, System health, Settings, Accounts, Arabic and right-to-left, and a way to start and stop the whole system on an Ubuntu Jetson. Brief: `design/console-v2/HANDOFF.md`. This is P14 (console v2). Sibling specs: 023, 024, 025 (zones and stations), 027 (cameras page and camera wall).

## Why this feature

The next customer is a residential compound, and the owner will run the whole system (engine, models, cameras, console window) on one small Jetson computer, not a Windows PC. The pages need a calmer shape, the two kinds of user need clear, honest limits, and the system must start and stop on Ubuntu with a double-click, as it does on Windows.

## User Scenarios & Testing

### Primary story

An administrator double-clicks the VisionGuard icon on the Jetson. The console opens once the engine answers. They sign in and land on Home. An IT colleague signs in and sees the same shell without Attendance and People, with a plain note wherever a control is administrator-only. The administrator promotes the colleague from Accounts. Closing the window stops everything.

**Acceptance scenarios**

1. **Given** an administrator, **When** the console loads, **Then** the sidebar shows Home, Attendance, People, Population, Car plates, Restricted zones, Work stations, Cameras, and under SYSTEM: System health & configuration and Settings. Accounts is only in the user menu.
2. **Given** an IT user who calls an administrator-only action directly, **Then** the engine refuses, whatever the screen showed.
3. **Given** a role change in Accounts, **Then** the audit entry is written first; the person's next request uses the new role.
4. **Given** Arabic, **Then** every page is right to left, while numbers, times, emails and charts still read left to right.
5. **Given** an area with no capacity set, **Then** Population shows the count only: no percentage, bar or level.
6. **Given** the Jetson, **When** the owner double-clicks the launcher, **Then** the console opens only after the engine answers, and closing the window stops every process it started.

### Edge cases

- Engine down, or a subsystem failed: the shell still loads and says which part is down and why. Sign in failing and engine unreachable are two different messages, never a blank page.
- No cameras configured: "0 of 0 cameras up", and Home's camera strip says there are none. A camera that is down counts against "N of M" and shows on Home as offline, never as a frozen picture.
- "Nothing needs your attention." and "attention data unavailable" are two different messages.
- A role changes while the user is signed in; the last administrator tries to demote themselves.
- Overlapping cameras: the count is a sum, labelled as an upper bound.
- A name or duration with no Arabic wording is shown as stored, never guessed.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all five: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx (zones) and 5xx (stations), 027 6xx.

Numbered `P14-FR-1xx`. Product-level `FR-xx` belongs to `docs/PLAN.md`.

### Shell

- **P14-FR-101**: The product name everywhere MUST be "VisionGuard". The sidebar MUST show the logo and the site name from Settings.
- **P14-FR-102**: The sidebar MUST list the items in scenario 1, in that order. Attendance and People MUST be administrator-only.
- **P14-FR-103**: Sidebar badges MUST show real counts: Attendance = people not yet arrived; Car plates = open gate alerts; Restricted zones = zones with someone inside; Work stations = stations absent past their limit. A badge with nothing to count MUST be absent; one whose source is unavailable MUST NOT show a number.
- **P14-FR-104**: The sidebar's bottom card MUST read "Site is calm" or "N things need attention", from the same list Home shows.
- **P14-FR-105**: The top bar MUST show the date, "N of M cameras up" (opening System health), the bell and the user. The bell's popover MUST list the alerts and offer **Mark all read**, which clears the unread mark without deleting anything.
- **P14-FR-106**: The user menu MUST offer System health & configuration, Settings, Accounts (administrators only), a language switch, a theme switch and Sign out.
- **P14-FR-107**: In Arabic, the top bar MUST run right to left: date, cameras up, avatar, name, then the bell last at the far left. In English: date, cameras up, bell, name, avatar.
- **P14-FR-108**: Every successful save, dismiss and acknowledge MUST show a toast naming what happened (for example "Cleared — recorded under your name."). A failed one MUST say so with the reason and MUST NOT show a success toast.
- **P14-FR-109**: Sign in MUST offer **Create account** (full name, email, password, confirmation), saying plainly that new accounts get limited access.

### Roles

- **P14-FR-110**: There are two roles, Administrator and IT. Both see alerts and camera views. Only administrators view attendance and people records, enrol faces, edit the vehicle register, export attendance and gate logs, and manage accounts. Dismissing gate alerts and acknowledging station alerts stay allowed for IT. What else IT may change is P14-FR-115. Hiding people records from IT reverses today's rule, under which IT may read the people directory, groups, attendance and history; the engine must change too.
- **P14-FR-111**: The engine MUST enforce every row of that table; the console MUST only hide or disable. A read-only screen MUST say "Only an administrator can…" where the controls would be.
- **P14-FR-112**: For IT, Home MUST omit the attendance card, attendance alert and attendance suggestions, and Ask about attendance MUST answer "Attendance and people records are open to administrators only."
- **P14-FR-113**: For IT, Settings MUST show the profile and alert rules read-only, recipients as Receiving / Switched off, and keep appearance and language editable.
- **P14-FR-114**: Accounts (administrators only) MUST list "N people can sign in" with role, email and last active, and let an administrator change a role between Administrator and IT. The change MUST be audited before it is made. The system MUST refuse to leave zero administrators and say why.
- **P14-FR-115**: Owner decision, 10 Nov 2026. IT MAY start and stop a recording on a camera, see plate text everywhere plates appear (including the camera wall), and mark a car **Gone**. IT MUST NOT add or remove cameras or recorders, see camera addresses, or draw, pause, edit or delete zones and stations. Recording and Gone are new IT permissions in the engine (today recording is an administrator write and Gone does not exist); camera setup stays administrator-only as today. This overrides the brief's "IT may add or remove cameras".

### Home

- **P14-FR-116**: Home MUST show a greeting, an Ask box with suggestion chips (a chip opens the matching page with its filters set and a toast "Opened X"), three feature cards (Attendance for administrators, Population, Car plates with the last plate read), a live strip of four cameras with "All cameras →", and Needs your attention.
- **P14-FR-117**: Every item in Needs your attention MUST come from real open items, show its action link and an **Acknowledge** that is audited and removes it without deleting anything. Every figure MUST come from the engine or say it is unavailable. A Home item MUST never link to a page that is gone.
- **P14-FR-118**: The live strip MUST pick cameras that are up and show no identity (no names).

### Population

- **P14-FR-119**: Population MUST show the total on site now and the range choices named exactly as the engine's windows: Right now, Today by hour, This week by day. (The third covers the last seven days, which the design calls "Last 7 days"; keep the engine's label or rename it deliberately in both places.)
- **P14-FR-120**: Each area MUST show its count, a sparkline and, only when a capacity is set, a capacity bar and a level (Empty, Quiet, Busy, Near capacity, Over capacity). No capacity means no percentage and no level.
- **P14-FR-121**: Counts from overlapping cameras MUST be shown as an upper bound, with that note on the page. The detail panel MUST show the range's chart, the peak and the cameras covering the area.

### System health & configuration, Settings

- **P14-FR-122**: System health & configuration MUST keep today's content (cameras online, pipeline workers, capacity, per-worker load, camera sources, cameras needing attention) in the new frame, and MUST list **Restricted zones** and **Work stations** among a camera's watch-for choices, noting they share the person detector. It MUST stay answerable, with reasons, when everything it describes is broken.
- **P14-FR-123**: Settings MUST let an administrator edit, with automatic saving: site name, working hours, **working days** (Saturday to Thursday unless changed; nothing sets working days today, so this is new), a **working calendar** (from–to dates, replacing "Term"), and the attendance cut-off. Attendance's seven-day strip, the daily report and work stations on working hours all use these working days.
- **P14-FR-124**: Settings alert rows MUST be: Gate alert (with which kinds), **Restricted area entered** (today's intrusion alert, renamed), **Work station left empty** (a new alert kind), Camera offline, Daily attendance, each with In-app / Email chips, plus recipients, "what was sent", appearance and language. The old detection-zones card MUST be gone. There is no weapon alert row (see P14-FR-129).
- **P14-FR-125**: The daily attendance report and its "school day" wording MUST follow the working calendar. Owner decision, 10 Nov 2026: the report is sent on working days inside the working calendar dates, replacing today's Sunday–Thursday inside the term.

### Arabic, right to left, look

- **P14-FR-126**: In Arabic the whole console MUST lay out right to left with direction-aware spacing and no letter spacing on Arabic text. Email, password, time, date and number fields read left to right but right-aligned; emails, addresses and phone numbers inside Arabic sentences stay intact. Time-series (sparklines, population bars, gate traffic, station timelines, the 7-day attendance strip) MUST stay left to right. Arrows and back links MUST flip.
- **P14-FR-127**: Engine wording that is not a sentence (camera names, areas, durations, day names, colours) MUST be translated from codes by the console, not by replacing strings. Arabic stays in draft until a native speaker reviews it.
- **P14-FR-128**: The console MUST adopt the redesign's tokens and light and dark themes, keeping detection colours and their meaning: green = recognised face, blue = clothing, amber = unidentified, red = alarm.
- **P14-FR-129**: Lost bag, Track a person and Knife detection MUST be removed from navigation; their engine behaviour is untouched. Owner decision, 10 Nov 2026: knife detection is not part of v2 at all. It is switched off, is not offered among a camera's watch-for choices, and nothing related to it appears anywhere in the console (no page, Home item, alert row, badge or Ask answer). Because nothing is detected, nothing waits for a human verdict, so rule 10 holds.

### Starting on the Jetson

- **P14-FR-130**: On Ubuntu on the Jetson there MUST be one double-clickable launcher that starts the engine and the console window, opens the console only once the engine answers, and says plainly in the window when something fails to start.
- **P14-FR-131**: Closing the launcher window MUST stop every process it started, including when closed by force. Nothing may be left holding a camera or the ports.
- **P14-FR-132**: The launcher MUST offer the modes the Windows one has: no browser, a mock mode with no models, and a recorded-clip mode. A mode that cannot run MUST say why.
- **P14-FR-133**: The camera count MUST be an input read from configuration, never a constant, in the launcher, shell, Home and Population. **[NEEDS CLARIFICATION: how many cameras must one Jetson carry? The owner will decide after the Jetson soak test. So far that test found 44 cameras at 2 checks a second fully kept up, while 80 cameras at 1 check a second kept up with only 70% of the work; the 50-camera overnight run is still to come.]**
- **P14-FR-134**: The console MUST be usable on the Jetson's own display with its video encoding done on the processor (the board has no hardware encoder), and System health MUST report memory use honestly as one shared pool.
- **P14-FR-135**: Development on Windows MUST keep working exactly as today.

## Success Criteria

- **SC-001**: An administrator and an IT user each see exactly the navigation, cards and read-only notes of the role table; an IT user's direct attempt at any administrator-only action is refused.
- **SC-002**: A role change is in the audit trail before it takes effect, and the person's next action follows the new role.
- **SC-003**: Every number on Home, the badges and the top bar matches the page it points to, or the page says it is unavailable. No design value appears in a live build.
- **SC-004**: Population shows no percentage or level for any area without a capacity, and labels summed overlapping cameras as an upper bound.
- **SC-005**: In Arabic every page reads right to left with the stated top bar order, and numbers, emails and charts stay left to right, checked by eye by Mohamed.
- **SC-006**: **On the Jetson**: double-click the launcher, the console opens within a minute of the engine answering, Home, Population and System health load with real data from the Jetson's own cameras and models, and closing the window leaves no engine, model or camera process running.
- **SC-007**: With the engine stopped, the shell and System health explain what is down instead of showing a blank page or an error code.
- **SC-008**: The existing automated checks pass with the count not dropping.

## Out of scope

- Attendance, People and Enrol (023); Car plates (024); Restricted zones and Work stations (025); Cameras page and camera wall (027).
- Changing the face model, tracking or detection logic; building or choosing models.
- New messaging channels (Notify manager stays disabled with its reason); native Arabic review.

## Constitution check

- **III Truthful data** (P14-FR-103, 117, 120, 121): no fixtures; live state or "unavailable".
- **Rule 1 / 3** (P14-FR-118, 128): colours keep their meaning; the Home strip shows no names.
- **Server-side permissions** (P14-FR-111, 114): the engine decides by path; role change audited first.
- **Degradation is payload** (P14-FR-122): System Health stays answerable; a failed subsystem is named in the UI.
- **Feature isolation**: no page here requires another feature to be on.
- **Scale and hardware** (P14-FR-133, 134): the Jetson's capacity must be measured, not assumed.

## Assumptions

- Two roles stay; no third. "N of M cameras up" counts configured, switched-on cameras.
- The launcher is a standard Ubuntu desktop shortcut wrapping a script; the Windows one stays.
