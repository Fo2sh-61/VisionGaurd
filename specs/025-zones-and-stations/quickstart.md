# Quickstart: checking 025 works

## On Windows (development)

```powershell
python -m pytest engine                       # count must not drop below the baseline in context.md
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

The recorded clip (`engine/data/footage/`) is the regression suite: 12 labelled event marks and
9 labelled negatives. Debug there, not on the webcam.

### Zones, in the console as an administrator

1. **Draw.** Restricted zones, **Draw a zone**. Pick the clip camera. Save stays off until there is
   a name and three points and says what is missing. Try a bow-tie shape and a thin sliver: both are
   refused with a reason. Stop the camera and reopen the editor: it says there is no picture and
   will not save.
2. **Feet, not body.** Draw the labelled desk area. At the 12 event marks an entry opens; at the 9
   negatives nothing does (SC-404). A person whose body overlaps the edge with feet outside logs
   nothing.
3. **Full frame equals today.** Draw a full-frame zone. The same scenes appear as the old
   whole-camera zone produced (compare against the log from before the upgrade).
4. **Pause.** Pause the zone, then sign in as a second user: both see "Paused by {name} - time" and
   no entry opens. Pause while someone is inside: the open entry closes and keeps its times.
5. **Alert timing.** Set 10 seconds, stand in for 4: an entry, no alert in the bell. Stand in for 15:
   one alert. Leave and return within a minute: no second alert.
6. **Hours.** Set Outside working hours and walk in during working hours: nothing is logged. Change
   working hours in Settings: the zone follows at once, no restart.
7. **Delete.** Delete shows an inline question first. After it, the old entries are still readable and
   counted in "entries today".
8. **Clips.** An entry among a camera's three newest has **Watch clip**; older ones say "No clip kept".
   Two zones on one camera with one person in both: two entries, the second says "No clip -
   the camera was already recording another zone's entry".
9. **Upgrade.** Start with a database that has `camera_restricted` rows and scenes: each appears as a
   full-frame zone named after its camera, same on/off, same history and clips (SC-405). The two
   `engine.yaml` zones appear as drawn zones; Chemistry lab shows its import note.
10. **Arabic.** Switch language: pages, editor, tiles and the timeline mirror; drawing is unaffected.

### Stations

11. **Draw a station** on the clip camera, no assignee, limit 1 minute, working hours. Stand in it: the
    card reads On station within 5 seconds (SC-501).
12. **Leaving.** Walk out for 3 seconds and back: no event. Walk out for 20 seconds: one "Left station"
    stamped at the last moment you were seen. Stay out past the limit: Absent, one alert in the bell,
    one "Absence alert - over 1 min" in the log, and no second alert while it continues.
13. **Acknowledge.** As an IT user press **Acknowledge alert**: the audit has `station.ack` before the log
    row, the card still reads Absent. Trying to edit or delete as IT is refused by the server (403).
14. **Assigned person.** Enrol a test face, assign it, stand in the area as someone else: it does not read
    On station. Be the assigned person: it does. Leave, let someone else take the spot: Away, never On.
    Face too small (step back): the warning appears at choice time and the station says anyone counts.
15. **Unknown.** Stop the camera: the card reads Unknown with the reason inside 10 seconds, and no alert
    is raised. Restart the engine: today's totals, events and acknowledgements are unchanged and the
    downtime shows as not watched.
16. **Hours.** Before the opening time the card reads Not started with "opens 9:00" and counts nothing.
17. **Honest empty.** With no stations the page says so and offers **Draw a station**; no demo station.
    Kill the person detector (rename its weights) and start: Work stations says why, and System Health
    has a `stations` row with the reason.

Restart with `-DevSignIn it` for 13 and for the read-only views.

## On the Jetson: the new deployment board only

The Jetson reachable over SSH today is a test bench: install nothing of VisionGuard on it. These
steps wait for the new board (SC-406, SC-407 on the Jetson, SC-508, SC-509 on the Jetson). Report
them as "waiting for the board" until then.

18. Draw a zone on the Windows PC, copy the database across (or redraw), and open it on the Jetson: the
    polygon lands in the same place of the picture (SC-407).
19. With zones and stations on every camera the owner will connect and clips being saved: entry within 5
    seconds, no camera's detection rate below its configured rate for more than a few seconds, ten
    stations updating at least every 2 seconds, and the memory figure on System Health (022) below 8 GB.
    Record the measured per-worker milliseconds from System Health in `STATUS.md`; the table's
    `stations: 1.0` is an estimate until then.
