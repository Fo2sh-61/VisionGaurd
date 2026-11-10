# Feature Specification: Car plates page in console v2

**Feature Branch**: `024-console-v2-plates`
**Created**: 10 Nov 2026
**Status**: Draft
**Input**: Console v2, area "Car plates": the vehicle gate page in three tabs — Live, Movements, Registered vehicles — as drawn in `design/console-v2/HANDOFF.md`. The engine already does almost all of this (specs 006, 007, 013). This is mostly a reorganised page, plus running the plate reader on a Jetson Orin Nano.

> Phase prefix `P14` = console v2. Sibling specs: 022 (shell, roles, home, settings), 023 (attendance, people), 025 (zones and stations), 027 (cameras, camera wall).

## Why this feature

The gate already reads plates, checks the register and raises alerts. Today one long screen mixes the guard's question ("what just came in, is anything wrong?"), the manager's ("who is inside, what happened yesterday") and the administrator's chore (the register). Three tabs separate them, and each car gets a detail view that shows how sure the reader was. The owner will run everything on a Jetson Orin Nano; plate reading must give the same answers there.

## User Scenarios & Testing

### Primary story

A guard opens **Car plates**. On **Live** they see open gate alerts, six counts, the gate cameras and the latest reads. A car not on the register appears as "Not registered" with an alert. They open the row, see the photo, the plate and how sure the reader was, and fix a wrong last letter. An administrator later adds the car from **Registered vehicles** with the plate pre-filled, and the alert is resolved. Next morning a manager opens **Movements**, picks yesterday, sees traffic by hour and gate, and exports the day.

**Acceptance scenarios**

1. **Given** the page opens, **Then** it shows three tabs and Live is selected.
2. **Given** open alerts, **When** Live is shown, **Then** each appears in a strip with plate, gate, time and fitting actions. Not on the register: "Add to the register" or "Just a one-off". Permit expired: "Renew the permit" or "I have dealt with it". Blacklisted: dismissal only. Add and Renew open the register form pre-filled.
3. **Given** six tiles (Entered, Left, Inside now, Not registered, Blacklisted, Cameras reading), **When** one is clicked, **Then** the table shows only matching rows and the tile reads as selected; clicking again clears it.
4. **Given** a row is clicked, **Then** the detail panel shows the plate large, status, photo, vehicle and owner if registered, times seen this week, and the reader's figures: confidence, frames agreed (a pass needs three) and, for passes recorded after this ships, plate width in pixels (100 or more is a comfortable read).
5. **Given** an administrator presses **Fix** and types the right plate, **Then** the row shows it, the change is recorded under their name, and no alert message is sent.
6. **Given** an administrator confirms **Remove this row**, **Then** the row, photo and plate crop are deleted for good and the audit entry naming the plate stays.
7. **Given** Movements, **When** the user picks a day, types a plate or owner, or picks a gate, **Then** the chart, gate summary and Completed visits follow the day; search and gate narrow the lists. Inside now is always right now and says so.
8. **Given** no exit camera is configured, **Then** Inside now says so plainly and shows no figure it cannot stand behind.
9. **Given** an administrator presses **Export this day**, **Then** a file of that day's passes downloads, and the audit entry is written before the file is built.
10. **Given** Registered vehicles, **When** an administrator uploads an Excel or CSV file (English or Arabic), **Then** vehicles are added or updated, a line shows the last import (when, by whom, added, updated, skipped), and unreadable rows are listed with the reason. Good rows are kept when others fail.
11. **Given** an IT user, **Then** they see everything and can dismiss alerts, but every edit control is absent and one line says "Only an administrator can change the register or export the gate log." The engine refuses those actions for IT even if called directly.
12. **Given** a plate anywhere in this area, **Then** it reads as an Egyptian plate: Arabic letters, Arabic-Indic digits, the "مصر · EGYPT" band, Latin transliteration beneath. Letters and digits keep the plate's own right-to-left order whatever the page direction. Search and the register treat Arabic-Indic and Western digits as the same plate.

### Edge cases

- Gate feature not running or a gate camera offline: Live says so with the reason, the Cameras reading tile shows the real number; the page still opens.
- Nothing passed today: "No cars yet today". Zero cars and "reader not running" look different.
- Reader unsure: the row is kept and flagged as a weak read, never hidden, never shown as certain.
- Fix on a car still in view: the correction stands, no message is sent. A plate that is not valid: the editor says why and changes nothing.
- **Gone** on a car that already left: the page refreshes to the true state without an error.

## Requirements

Requirements in console v2 are numbered by spec so a number means one thing across all five: 022 uses P14-FR-1xx, 023 2xx, 024 3xx, 025 4xx (zones) and 5xx (stations), 027 6xx.

- **P14-FR-301**: Three tabs. Every figure MUST come from the gate's real records; nothing from the design's sample plates, owners or counts may appear.
- **P14-FR-302**: Live MUST show gate alerts (blacklisted, not on the register, permit expired) with the actions in scenario 2. Dismissing MUST leave the pass in history unchanged.
- **P14-FR-303**: Six tiles. Entered, Left, Not registered and Blacklisted filter the table (click again to clear). Inside now opens the Inside now list; Cameras reading is a count and filters nothing.
- **P14-FR-304**: A strip of gate cameras with a box round each plate in view, drawn from the gate feature's own readings only.
- **P14-FR-305**: The reads table lists recent passes: plate, owner if registered, gate, direction, time, status (registered, not registered, blacklisted, permit expired, weak read). Status is the one frozen when the pass happened, never rewritten by a later register change.
- **P14-FR-306**: The detail panel MUST show confidence and frames agreed from the reading itself, and plate width where stored (new engine work: today the width exists only on the live reading and is not stored). No stored width says "not recorded". It MUST NOT show any figure the reader did not produce.
- **P14-FR-307**: Administrators MUST be able to correct a plate. Audited under their name, MUST NOT send an alert message, MUST keep the original reading on record.
- **P14-FR-308**: Administrators MUST be able to remove one pass, with confirmation, as in scenario 6.
- **P14-FR-309**: Movements offers Day, plate/owner search and gate filters, and **Export this day** (audit entry first). Searching by owner is new engine work (today only the plate is searched).
- **P14-FR-310**: Movements shows traffic by hour, a gate-by-gate summary, Inside now (each car with time inside) with a **Gone** action, and Completed visits (in, out, duration).
- **P14-FR-311**: Visits closed by the car re-entering MUST be labelled "Exit estimated" and counted apart from observed exits. With no exit camera, Inside now MUST say so.
- **P14-FR-312**: **Gone** MUST be audited and MUST close the visit as manually ended, not as an observed exit. New engine work: today visits are worked out from passes and nothing records a manual end.
- **P14-FR-313**: Registered vehicles: template download, Excel/CSV import (English or Arabic headers; both digit systems one plate), last-import line, search, chips (All, Staff, Visitors, VIP, Blacklisted), Add / Edit / Remove with inline confirmation.
- **P14-FR-314**: One vehicle form: plate (letters and numbers separately), owner, phone, unit, category, permit valid until, make, colour, notes. A duplicate plate MUST be refused with a plain reason.
- **P14-FR-315**: IT sees all tabs read-only, MAY dismiss alerts and MAY press Gone. Edit, fix, remove, renew, blacklist, import and export MUST be refused by the engine for IT and absent from the page, with the note from scenario 11.
- **P14-FR-316**: Plates drawn as in scenario 12 in both console languages; the plate's letter order MUST NOT change with the language.
- **P14-FR-317**: If the gate reader is not running, has stopped or has no gate camera, the page MUST say so with the reason in the page itself, and still open.
- **P14-FR-318**: Plate reading on the Jetson MUST give the same readings as the reference the owner's plate test set gives today. Anything that changes readings (reduced numeric precision, a different compiled form of the models) MUST NOT be used for plates, even if faster.
- **P14-FR-319**: The plate reader on the Jetson MUST keep working beside other features within its 8 GB of shared memory, MUST say plainly if it cannot (for example paused for lack of memory), and never show as running when it is not.
- **P14-FR-320**: The page MUST behave the same in the console window on the Jetson as on the Windows development machine.
- **P14-FR-321**: Apart from the new engine work named here, everything needed exists; this feature MUST NOT change how a pass is voted in or what an alert message contains. Owner decision, 10 Nov 2026: both shortcuts are in the first version — **Add to blacklist** on a pass and **Renew the permit** on an alert each open the register form pre-filled; no new engine action is needed.
- **P14-FR-322**: Reading plates MUST NOT depend on any other feature being on, and failing to read MUST NOT affect any other feature.

Owner decision, 10 Nov 2026: an unanswered gate alert is not marked "old"; it stays until dismissed or until it drops off at midnight.

Owner decision, 10 Nov 2026: IT MAY press **Gone** (spec 022, P14-FR-115). It is audited under their name like any other Gone.

**New engine work** (all else already exists: alerts, summary, reads, correction, removal, traffic, inside now, visits, export, register, import, last import, "Exit estimated"): **Gone**; storing plate width on each new pass; searching passes by owner; a week of passes for one plate (today passes are read one day at a time). The existing 30-day photo retention and 3-frame agreement are unchanged. How the Jetson's memory limit is shared across features belongs to the plan.

## Success Criteria

- **SC-001**: A guard finds any of today's passes and sees how sure the reader was in under 10 seconds.
- **SC-002**: A car not on the register appears in the strip and table within 10 seconds of leaving camera view; an administrator goes from that alert to a saved register entry in under 30 seconds with the plate pre-filled.
- **SC-003**: Each of the six tiles equals the count of matching table rows for the same day, checked on one recorded day.
- **SC-004**: An IT user cannot change the register, fix a plate, remove a row, import or export by any route, including calling the engine directly.
- **SC-005**: With the gate stopped, the page opens, says it is stopped and why, and shows no number as live.
- **SC-006**: On the Jetson, plate reading over the owner's plate test set is identical to the reference on every photograph, and a pass shows within 10 seconds of crossing a gate camera while other features run.
- **SC-007**: After a 60-minute Jetson run with all configured cameras, memory stays under 8 GB and the plate reader is still reported as running.
- **SC-008**: An Arabic plate (three letters, four digits) shows letters and digits in the physical plate's order in both console languages, checked on at least five real plates.

## Out of scope

- Shell, roles, Home, Settings, alert rules (022); attendance and people (023); zones and stations (025); cameras, the wall, gate/direction assignment on a camera (027).
- Changing how plates are read, voted or stored; accuracy work; new models. Accuracy on the school's own gate is unmeasured and this spec does not claim it.
- Barriers or blocking vehicles. Alert message delivery and wording (spec 013). Setting up the Jetson itself beyond what plate reading needs.

## Constitution check

- Rule 4: no sample data survives; empty, stopped and unknown look different (FR-301, FR-317).
- Rule 5: Inside now claims only what the exit camera supports; "Exit estimated" is labelled (FR-311).
- Rule 9: the gate needs no other feature; its strip draws only gate boxes (FR-304, FR-322).
- Rule 8 and 7: a stopped reader is announced in the page, which degrades as content, never an error screen (FR-317, FR-319).
- Audit before action: export, fix, remove, Gone (FR-307, 308, 309, 312). The engine enforces IT limits (FR-315).
- FR-318 comes from the settled finding that half precision and the compiled form changed readings (6.7% and 26.6%).
