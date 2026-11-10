# Quickstart: checking 022 works

## On Windows (development)

```powershell
python -m pytest engine                       # count must not drop below the baseline in context.md
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
.\dev.ps1 up -Clip -AllowSystemPython -DevSignIn admin
```

Check by eye in the console:

1. **Sidebar.** It lists Home, Attendance, People, Population, Car plates, then Health and
   Settings under SYSTEM. The brand reads "VisionGuard". Accounts appears only in the user
   menu.
2. **Accounts.** Change a test account to Admin. A toast appears, and the audit log (`GET
   /audit`) shows `user.role` before the change. Demoting the only admin is refused, with the
   reason shown.
3. **Settings.** Change the working hours, untick Friday, then reload the page. The values
   stay. A cut-off outside the hours is refused with a reason.
4. **Population.** An area with no capacity shows a count only.
5. **Knife detection.** Nothing about knives appears in the nav, Home, Settings alert rows,
   the camera watch-for list, System Health or Ask.
6. **Arabic.** Switch the language from the user menu. The layout flips, the top bar order
   matches the spec, and numbers and emails read left to right.

Restart with `-DevSignIn it`:

7. **IT account.** Attendance and People are gone. `GET /attendance` returns 403. Ask about
   attendance answers with the administrators-only sentence. Recording a camera works.

## On the Jetson — the new deployment board only

The Jetson reachable over SSH today is a test bench: **install nothing of VisionGuard on it.**
These steps wait for the new board. First check it matches the assumptions
(`python3 --version` → 3.10, `cat /etc/nv_tegra_release` → R36) and update `plan.md` if not.

```bash
cd ~/VisionGuard && git checkout console-v2-jetson
# console built on the PC: copy web/dist over, or run `npm ci && npm run build` if Node exists
./tools/install-shortcut.sh
```

8. **Launch.** Double-click VisionGuard on the desktop. The console window opens once the
   engine answers, within a minute (SC-006). Home, Population and System Health show real
   data. System Health shows memory as one shared figure.
9. **Close.** Close the window, then run `pgrep -af serve.py`, which should print nothing.
   Repeat with `kill -9` on the launcher script itself: the engine still goes.
10. **Modes.** Run `./launch.sh --mock` and `./launch.sh --clip`. Both start. A mode that
    cannot run (for example, no clip file) says why in a message box.
11. **Clips.** Record a camera for 5 seconds. The clip plays in the console.
