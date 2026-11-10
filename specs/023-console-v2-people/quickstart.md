# Quickstart: checking 023 works

## On Windows (development)

```powershell
python -m pytest engine                       # not below baseline (1940 passed, 14 skipped) + the new tests
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

Engine tests (`engine/tests/test_people_v2.py`) must show: a person enrolled after day D is not on D's register; a person removed after D still is, with
their name; a day with no sightings is `recorded: false`; D uses D's cut-off; excused is its own count and arrival beats it; the audit entry exists
before the status changes (also when the store write is made to fail); two excuses give two audit entries and one status; week strip gives `unknown`
for a day not recorded; group 30-day is `null` with recognition off; IT gets 403 on every call; unrecognised face boxes are amber.

Check by eye in the console (admin):

1. **Attendance, today.** Strip shows doorway cameras only, with the note. Tiles (everyone, on time, late, not arrived, excused) add up to the table. Press a tile: table filters.
2. **Excuse.** Open a not-arrived person, Mark excused. Tiles change, `GET /audit` shows `attendance.excuse` with your name.
3. **Past day.** Pick yesterday: banner, that day's figures. Pick a day with no clip data: "nothing was recorded that day", no zeroes as figures.
4. **Week strip.** Seven working days, a day with nothing says "no record".
5. **Notify manager** is disabled and says why.
6. **People.** Chips with real counts, group filter, search, "Showing n of m". Remove a test person: the in-place sentence is the true one; afterwards yesterday's Attendance still lists them.
7. **Groups.** Cards show people, on site, 30-day figure with its days, or "no data". The overlap note is there.
8. **Enrol.** Name required. Pick the clip camera, see the box. Two faces in a photo: flagged with its reason in the page language, removable. Save stays disabled until "5 of 5 usable photos". Click a sidebar link mid-session: Discard and leave / Stay. After discarding, `GET /people` has no new person.
9. **Recognition stopped** (start with no face models): both pages say why and show no percentages or zeroes.
10. **Arabic.** Layout flips, reasons and the removal sentence read in Arabic draft.

Restart with `-DevSignIn it`: pages are gone from the sidebar; `GET /attendance`, `/people`, `/groups`, `/enrolment/sessions` all return 403.

## On the Jetson: the new deployment board only

The Jetson reachable over SSH today is a **test bench**: install nothing of VisionGuard on it. These wait for the new board. First confirm it matches
the assumptions in 022's quickstart (Python 3.10, R36).

- A day's attendance loads, a person is enrolled with the live preview, a person is removed; results match Windows (SC-008).
- The enrol preview shows no stale picture when the camera is unplugged (241); System Health reports memory pressure if enrol + all features run (242).
- A person enrolled on Windows is recognised on the board (243).
- Time the cold read of the group 30-day figure at the real roll (research R6); if above 2 s, apply the SQL variant.
