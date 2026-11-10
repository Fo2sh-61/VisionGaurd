# Feature Specification: Car plates page in console v2

**Feature Branch**: `024-console-v2-plates`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: User description: "Console v2, area 'Car plates': the vehicle gate page reorganised into three tabs — Live, Movements, Registered vehicles — as drawn in `design/console-v2/HANDOFF.md`. The engine already does almost all of this (spec 006, 007, 013); this is mostly a reorganised page, plus running the plate reader on a Jetson Orin Nano."

> Phase prefix `P14` = console v2. Sibling specs: 022 (shell, roles, home, settings), 023 (attendance, people), 025 (restricted zones), 026 (work stations), 027 (cameras, camera wall).

## Why this feature

The gate already reads plates, checks them against the register, and raises alerts. The page that shows it is one long screen where the guard's question ("what just came in, is anything wrong?") shares space with the manager's questions ("who is inside, what happened yesterday") and the administrator's chore (keeping the register). Console v2 splits those into three tabs and gives every car a proper detail view, including how sure the reader was.

The owner will also run everything, models and cameras included, on a small Jetson Orin Nano computer. Plate reading must give the same answers there as it does today.

## User Scenarios & Testing

### Primary story

A guard opens **Car plates**. On **Live** they see any open gate alerts at the top, six counts, the gate cameras, and the latest reads. A car arrives that is not on the register: it appears in the list as "Not registered", and an alert says so. They click the row, see the photograph, the plate as drawn on the car, and how sure the reader was. The reader has the last letter wrong, so they fix it. An administrator later opens **Registered vehicles**, adds the car with the plate already filled in, and the alert is resolved. The next morning a manager opens **Movements**, picks yesterday, sees traffic by hour and gate, and exports the day.

**Acceptance scenarios**

1. **Given** the Car plates page, **When** it opens, **Then** it shows three tabs — Live, Movements, Registered vehicles — and Live is the one selected.
2. **Given** open gate alerts (blacklisted, not on the register, permit expired), **When** Live is shown, **Then** each alert appears in a strip at the top with its plate, gate, time and the actions that fit it: for a car not on the register, "Add to the register" or "Just a one-off"; for an expired permit, "Renew the permit" or "I have dealt with it"; for a blacklisted car, only dismissal. Add and Renew open the register form already filled in.
3. **Given** six tiles — Entered, Left, Inside now, Not registered, Blacklisted, Cameras reading — **When** the user clicks one, **Then** the reads table shows only the matching rows, the tile reads as selected, and clicking it again clears the filter.
4. **Given** a row in the reads table, **When** it is clicked, **Then** a detail panel shows the plate large, its status, the photograph, the vehicle and owner if registered, how often it was seen this week, and the reader's own figures: confidence, how many frames agreed (a pass needs three), and — for passes recorded after this feature ships — the plate's width in pixels with a note that 100 pixels or more is a comfortable read.
5. **Given** the detail panel, **When** an administrator presses **Fix** and types the correct letters and numbers, **Then** the plate is corrected, the change is recorded under their name, no alert message is sent for it, and the row shows the corrected plate.
6. **Given** the detail panel, **When** an administrator chooses **Remove this row** and confirms, **Then** the row, its photograph and its plate crop are deleted for good and the audit entry naming the plate stays.
7. **Given** Movements, **When** the user picks a day, types a plate or owner, or picks a gate, **Then** the chart, gate by gate and Completed visits follow the chosen day; search and gate narrow the lists shown; Inside now is always right now and says so.
8. **Given** Movements, **When** it is shown, **Then** it has a chart of cars in and out by hour, a gate-by-gate summary, **Inside now** (each car with how long it has been inside and a **Gone** button), and **Completed visits** (in, out, duration). A visit that closed because the car came in again, rather than because an exit was seen, is labelled "Exit estimated".
9. **Given** no exit camera is configured, **When** Movements is shown, **Then** Inside now says plainly that no exit camera is configured and shows no figure it cannot stand behind.
10. **Given** an administrator on Movements, **When** they press **Export this day**, **Then** a file of that day's passes downloads, and the export is written to the audit trail before the file is built.
11. **Given** Registered vehicles, **When** an administrator downloads the template, uploads an Excel or CSV file in English or Arabic, **Then** the vehicles are added or updated, a line shows what the last import did (when, by whom, how many added, updated, skipped), and rows that could not be read are listed with the reason.
12. **Given** the register, **When** the user filters by All / Staff / Visitors / VIP / Blacklisted or searches, **Then** the table narrows to match. **Add a vehicle** and **Edit** open one form: plate (letters and numbers), owner, phone, unit, category, permit valid until, make, colour, notes. **Remove** asks for confirmation in place before deleting.
13. **Given** a user with the IT role, **When** they open any tab, **Then** they can see everything and can dismiss gate alerts, but every control that edits the register, fixes a plate, removes a row, renews a permit, blacklists, imports or exports is absent and a single line says "Only an administrator can change the register or export the gate log." The engine refuses those actions for IT even if called directly.
14. **Given** a plate on screen anywhere in this area, **When** it is drawn, **Then** it reads as an Egyptian plate: Arabic letters, Arabic-Indic digits, the "مصر · EGYPT" band, and the Latin transliteration beneath. Letters and digits are read from the plate's own right-to-left order and are never reordered or mixed up by the page's direction. Search and the register treat Arabic-Indic and Western digits as the same plate.

### Edge cases

- The gate feature is not running, or a gate camera is offline: Live says so with the reason and the cameras-reading tile shows the real number; the page still opens.
- Nothing has passed today: an empty list says "No cars yet today", not zero rows pretending to be a result. Zero cars and "reader not running" look different.
- The reader was unsure: the row is kept and flagged as a weak read; it is never hidden and never shown as certain.
- A car is still in view when a guard fixes the plate: the correction stands and no message is sent for that car.
- An alert is dismissed: it leaves the strip, but the pass stays in history with its status unchanged.
- Fix is given a plate that is not valid: the editor says why and changes nothing.
- An import file has some good rows and some bad: the good rows are kept, the bad listed.
- **Gone** pressed on a car that has in fact left already: the page refreshes to the true state without an error.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all six: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx, 026 5xx, 027 6xx.

- **P14-FR-301**: The Car plates page MUST offer three tabs — Live, Movements, Registered vehicles — and every figure on them MUST come from the gate's real records. Nothing in the design's sample plates, owners or counts may appear in the product.
- **P14-FR-302**: Live MUST show gate alerts of three kinds — blacklisted, not on the register, permit expired — each with plate, gate, time and the actions listed in scenario 2. Dismissing an alert MUST leave the pass in history unchanged.
- **P14-FR-303**: Live MUST show six tiles (Entered, Left, Inside now, Not registered, Blacklisted, Cameras reading). Clicking Entered, Left, Not registered or Blacklisted MUST filter the reads table and clicking again MUST clear it. Inside now opens the Inside now list; Cameras reading is a camera count and filters nothing.
- **P14-FR-304**: Live MUST show a strip of the gate cameras with a box round each plate in view, drawn from the gate feature's own readings and not from any other feature's.
- **P14-FR-305**: The reads table MUST list recent passes with plate, owner if registered, gate, direction, time and status (registered, not registered, blacklisted, permit expired, weak read). Status MUST be the one frozen when the pass happened, never rewritten later by a register change.
- **P14-FR-306**: The detail panel MUST show the reader's confidence and how many frames agreed, as numbers from the reading itself, and the plate width in pixels where it was stored with the pass (new engine work: today the width exists only on the live reading and is not stored). A pass without a stored width says "not recorded". It MUST NOT show any figure the reader did not produce.
- **P14-FR-307**: Administrators MUST be able to correct a plate. The correction MUST be audited under the person's name, MUST NOT send an alert message, and MUST keep the original reading on record.
- **P14-FR-308**: Administrators MUST be able to remove one pass, with confirmation. The row, photograph and plate crop MUST go for good; the audit entry naming the plate MUST remain.
- **P14-FR-309**: Movements MUST offer Day, plate/owner search and gate filters as described in scenario 7, and an **Export this day** action that writes its audit entry before building the file. Searching passes by owner is new engine work (today only the plate is searched).
- **P14-FR-310**: Movements MUST show traffic in and out by hour, a gate-by-gate summary, Inside now with a **Gone** action, and Completed visits.
- **P14-FR-311**: Completed visits closed by the car re-entering MUST be labelled "Exit estimated" and counted separately from observed exits. With no exit camera configured, Inside now MUST say so instead of showing a paired figure.
- **P14-FR-312**: **Gone** MUST be audited and MUST close the visit as manually ended, not as an observed exit. This is new engine work: today visits are worked out from passes and nothing records a manual end.
- **P14-FR-313**: Registered vehicles MUST offer template download, Excel/CSV import (English or Arabic headers; both digit systems treated as one plate), a last-import line, search, category chips (All, Staff, Visitors, VIP, Blacklisted) and Add / Edit / Remove with inline confirmation.
- **P14-FR-314**: The vehicle form MUST hold plate (letters and numbers separately), owner, phone, unit, category, permit valid until, make, colour and notes. A duplicate plate MUST be refused with a plain explanation.
- **P14-FR-315**: The IT role MUST see all three tabs read-only and MAY dismiss gate alerts. IT MAY also press Gone. Edit, fix, remove, renew, blacklist, import and export MUST be refused by the engine for IT and absent from the page, with the one-line note from scenario 13.
- **P14-FR-316**: Plates MUST be drawn as in scenario 14, in both English and Arabic console languages, and the plate's own letter order MUST NOT change with the console language.
- **P14-FR-317**: If the gate reader is not running, has stopped, or has no gate camera, the page MUST say so with the reason, in the page itself and not only in a log, and MUST still open.
- **P14-FR-318**: Plate reading on the Jetson MUST give the same readings as the reference the owner's plate test set gives today. Anything that changes readings (reduced numeric precision, a different compiled form of the models) MUST NOT be used for plate reading, even where it would be faster.
- **P14-FR-319**: The plate reader on the Jetson MUST keep working next to the other features within its 8 GB of shared memory, and the page MUST say plainly if it cannot (for example, reader paused for lack of memory), and never show it as running when it is not.
- **P14-FR-320**: The page MUST work in the console window on the Jetson itself with the same behaviour as on the Windows development machine.
- **P14-FR-321**: Apart from the new engine work named in Assumptions, everything this page needs already exists; this feature MUST NOT change how a pass is voted in or what an alert message contains. Owner decision, 10 Nov 2026: both shortcuts are in the first version — **Add to blacklist** on a pass and **Renew the permit** on an alert each open the register form already filled in; no new engine action is needed.
- **P14-FR-322**: Reading plates MUST NOT depend on any other feature being switched on, and failing to read plates MUST NOT affect any other feature.

Owner decision, 10 Nov 2026: an unanswered gate alert is not marked "old"; it stays as it is until dismissed or until it drops off at midnight.

Owner decision, 10 Nov 2026: IT MAY press **Gone** (spec 022, P14-FR-115). It is audited under their name like any other Gone.

## Success Criteria

- **SC-001**: A guard can find any of today's passes and see how sure the reader was in under 10 seconds.
- **SC-002**: A car not on the register appears in the strip and the table within 10 seconds of it leaving the camera's view, and an administrator can go from that alert to a saved register entry in under 30 seconds with the plate pre-filled.
- **SC-003**: Every figure on the six tiles equals the count of the matching rows in the table for the same day; checked on one recorded day.
- **SC-004**: An IT user cannot change the register, fix a plate, remove a row, import or export by any route, including calling the engine directly.
- **SC-005**: With the gate stopped, the page opens, says it is stopped and why, and shows no number as live.
- **SC-006**: On the Jetson, plate reading over the owner's plate test set gives readings identical to the reference on every photograph, and the page shows a pass within 10 seconds of a plate crossing a gate camera while the other features are running.
- **SC-007**: After a 60-minute run on the Jetson with all configured cameras, memory stays under the 8 GB limit and the plate reader is still reported as running.
- **SC-008**: An Arabic plate such as one with three letters and four digits is shown with its letters and digits in the same order as on the physical plate, in both console languages, checked on at least five real plates.

## Out of scope

- Shell, roles, Home, Settings and alert rules: spec 022. Attendance and people: 023. Restricted zones: 025. Work stations: 026. Cameras, the camera wall and gate/direction assignment on a camera: 027.
- Changing how plates are read, voted or stored; improving accuracy; new models. Accuracy on the school's own gate is still unmeasured and this spec does not claim it.
- Barriers or any blocking of vehicles. Nothing is blocked.
- Alert message delivery (spec 013) and its wording.
- Setting up the Jetson itself (operating system, models, camera connection) beyond what plate reading needs to behave the same.

## Constitution check

- Rule 4 / III: no sample plates or numbers from the design survive; empty, stopped and unknown are shown as different things (FR-301, FR-317, edge cases).
- Rule 5: Inside now and counts claim only what the exit camera supports; "Exit estimated" is labelled (FR-311).
- Rule 9 / II: the gate does not need any other feature on (FR-322). The gate strip draws only gate boxes (FR-304).
- Rule 8: a stopped reader is announced in the page (FR-317, FR-319).
- Rule 11-style audit: export, fix, remove, Gone are audited before they happen (FR-307, FR-308, FR-309, FR-312).
- Server-side permissions: the engine enforces IT limits (FR-315).
- Rule 7: the page degrades as content, never as an error screen.
- The reference-exact plate readings rule comes from the settled finding that half precision and the compiled form changed readings (6.7% and 26.6%); FR-318 requires the same on the Jetson.

## Assumptions

- The engine already supplies alerts, summary, reads, correction, removal, traffic, inside now, visits, export, register, import and last import.
- New engine work: **Gone** (a stored, audited manual end of a visit); storing the plate width on each new pass; searching passes by owner; a week of passes for one plate ("seen this week" — today passes are read one day at a time). "Exit estimated" already exists.
- The memory limit means the Jetson may need fewer or lighter features running alongside plates; how that is decided belongs to the plan.
- The existing 30-day photo retention and 3-frame agreement are unchanged.
