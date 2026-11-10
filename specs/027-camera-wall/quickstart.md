# Quickstart: checking 027 works

## On Windows (development)

```powershell
python -m pytest engine                       # count must not drop below the baseline in context.md
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

By eye (admin), on the recorded clip:

1. **Grid.** Cameras appears in the sidebar. Try 2×2, 3×3, 4×4, each chip, and a search for a camera and an area. Every chip shows its count. The grid size is still there after a reload in the same tab.
2. **States.** Unplug or stop a camera source: the tile goes Stale (with its age), then No signal with its last picture marked old, within 10 s plus one 2 s poll. A camera switched off in System Health shows Switched off and is not in No signal.
3. **Readings.** Population shows a count. A gate camera shows its last plate. A camera whose subsystem is off says so with the reason, and never shows 0.
4. **No boost.** On the Cameras page, `GET /system/health` shows the per-camera analysis rate unchanged while sixteen tiles are open. Open one camera large: only that camera speeds up for a few seconds.
5. **Single camera.** Previous and Next follow the filter and search. The strip shows the others. The stream address has no password, even one inside a `?password=` part. Record says "records from now on", then makes a real clip; with the camera down it says it cannot start.
6. **Wall.** Press Full screen. Same filter and size, dark, no sidebar. Cameras up and alerts waiting match the top bar and Home. Left and right change page; Escape exits; a tile opens the single view and Escape closes it first. An unknown plate rings amber with the words "Unknown plate"; a person in a zone rings red.
7. **Arabic.** Switch language: pager and arrows mirror, times and counts stay left to right.

Restart with `-DevSignIn it`:

8. **IT account.** Tiles, strip, single view and wall show no name and no attendance value; Attendance tiles say administrators only. In the browser console, `fetch('/cameras/<id>/faces')` and `fetch('/attendance/cameras')` both return 403. `fetch('/cameras')` shows `boxes: []`. No stream address appears. Record works.

Run the engine checks directly:

```powershell
python -m pytest engine/tests/test_camera_wall.py
```

## On the Jetson: the new deployment board only

The SSH Jetson is a test bench: **install nothing of VisionGuard on it.** These checks wait for the new board (and for 022's launcher).

9. **Soak (SC-004, FR-624).** Launch with all features on across 40 cameras (or the nearest the bench allows). Record detection rate and alert time with the wall closed, then with a 4×4 wall paging, for the same time. The difference must be inside the tolerance the owner sets from these numbers.
10. **Memory.** Read System Health memory (022) with the wall open and closed; it must fit.
11. **Fix the open numbers.** Set `WALL_PICTURES_PER_SECOND`, `WALL_MAX_FPS`, the Stale floor and (owner's call) `WALL_MIN_FPS` from the measurements, and say so in `STATUS.md`.
