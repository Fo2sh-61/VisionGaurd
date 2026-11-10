# Quickstart: checking 024 works

## On Windows (development)

```powershell
python -m pytest engine                       # not below the baseline in context.md
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
git diff --stat                               # CRLF trap: no whole-file diffs
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

The recorded clip has a gate camera with passes, so use it for everything below. Then restart with `-DevSignIn it`.

### As administrator, by eye

1. **Tabs.** Three tabs, Live selected. Nothing from the design (no 2,140, no sample owners).
2. **Tiles equal the table.** Click Entered, Left, Not registered, Blacklisted: the table shows exactly that many rows (SC-003). Click again to clear. Inside now opens Movements. Cameras reading filters nothing.
3. **Alert flow.** On an unregistered car's alert press Add to the register: the form opens with the plate filled in; **close it without saving and the alert is still there**. Open again, save: the alert goes. On a permit-expired alert, Renew opens the existing vehicle's form (not a duplicate-plate error).
4. **Detail panel.** Click a row. Plate, status, photo, owner if registered, seen in the last 7 days, confidence, frames agreed, plate width. An old row says "not recorded" for width.
5. **Fix.** Fix a plate. The row updates, "typed in by you" shows, the original reading is shown, and `GET /audit` has the entry. A bad plate says why and changes nothing.
6. **Fix on a car still in view sends no message.** Covered by the test below; by eye, check the delivery log (Settings, alerts) has no new line.
7. **Remove this row.** Inline confirm; row, photo and crop go; the audit entry stays.
8. **Movements.** Pick a day, type `1234` then `١٢٣٤` (same result), type an owner name, pick a gate. Chart and gate summary stay on the day; lists narrow. Export this day: file downloads; audit shows the export **before** the file.
9. **Gone.** On Inside now press Gone. The car moves to Completed visits as "Ended by hand", the Inside now tile drops by one. Press Gone on a car that just left: no error, list refreshes.
10. **No exit camera** (a config with entry cameras only): Inside now says so, no figure.
11. **Registered vehicles.** Template, import a CSV with Arabic headings and one bad row: good rows kept, bad row listed with the reason, last-import line shows when, by whom, added, updated, skipped. Add a duplicate plate: refused in plain words. Chips filter. Remove asks inline.
12. **Plates read right.** Arabic letters right, digits left, band, Latin line beneath, in the English **and** the Arabic console (SC-008, five real plates).

### As IT (`-DevSignIn it`)

13. Every edit control is absent; one line says "Only an administrator can change the register or export the gate log." Dismiss and Gone work.
14. Direct calls are refused (SC-004). The tests do this; by hand: `PATCH /vehicles/passes/{id}/plate`, `DELETE /vehicles/passes/{id}`, `POST /vehicles/register`, `POST /vehicles/import`, `POST /vehicles/export` all return 403, `POST /vehicles/visits/{id}/gone` returns 200.

### Failing reader

15. In a test (no GPU needed): make the reader raise on every frame. Live shows a reason, "Cameras reading" drops and the note names the camera; with every gate camera failing the counts are dashes with the reason (SC-005).

## On the Jetson: the new deployment board only

The Jetson reachable over SSH today is a test bench: **install nothing of VisionGuard on it.** These wait for the new board.
First check the assumptions in 022's quickstart, then:

- **Font.** `fc-list :lang=ar` lists an Arabic font, or the console ships its own. Open Car plates: the plate chip looks like the Windows one (FR-320).
- **Same readings (FR-318, SC-006).** Run `python engine/tools/eval_plates.py --dataset <owner's set> --truth <truth.csv> --configs theirs,fp32` on the board: `fp32` must equal the reference on every photograph. Confirm System Health shows the plate reader as `.pt` / not accelerated.
- **Beside other features (FR-319, SC-007).** Run all configured cameras and all features for 60 minutes. System Health memory stays under 8 GB and Plate reading is still "running". A pass appears within 10 seconds of crossing a gate camera.
- **Fails plainly.** Start with memory held back (for example a second process taking most of it) and confirm the page names the reader as failing rather than showing live counts.

Nothing here has been run. The 1940-passed baseline was not rerun while planning.
