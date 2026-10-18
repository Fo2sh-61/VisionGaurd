# Quickstart: checking pilot site readiness

## Automated (every change)

```powershell
python -m pytest engine
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python -m pyflakes engine/vg engine/tools engine/tests
python tools/check_parity.py
git grep -niE "dev.?sign.?in"      # must print nothing (SC-007)
```

The new tests that must pass:

| Test | Proves |
|---|---|
| `test_front.py` | every page path loads the app; every media route and every engine path reaches the engine |
| `test_site_cert.py` | the root is limited to private addresses; the site cert carries `tls.names`; a name outside the limits is refused; the root key cannot be written under `C:\VisionGuard` |
| `test_migrations.py` | a database from before 016 (`engine/tests/data/pre016.sql`, a row in every table) is brought forward with nothing lost (SC-004); a failing step leaves the data and the number unchanged |
| `test_users_edit.py` | name, role and disable are saved and audited first; the last administrator cannot be demoted or disabled by anyone (SC-009); a disabled user's token fails on the next request |
| `test_settings.py` | school profile and retention survive a restart, are refused for `it`, and the late cut-off is used by attendance at once |
| `test_maintenance.py` | 31-day clip and 366-day sighting gone, counts recorded; a locked file gives "incomplete"; "not run yet" before the first run |
| `test_backup_restore.py` | backup, then restore into an empty folder: every person, embedding, event, account and setting matches, and an enrolled face matches again (SC-003); a half-made backup does not count; 7 kept |
| `test_erasure.py` | after erasure, a scan of every table and file finds the person only in the audit (SC-002); an interrupted erasure is finished at the next start |

## On the recorded clip (developer machine)

- **Q1**: `.\dev.ps1 up -Clip`, then the same with Caddy in front (`caddy run --config
  deploy\Caddyfile` with a test certificate). Both apps open on 443 and 8443. Reloading
  `/people` and `/weapons` shows the page. A knife clip link plays the clip.
- **Q2**: `curl -k -H "X-Forwarded-For: 1.2.3.4" https://localhost/healthz`. The engine log
  shows `127.0.0.1`, never `1.2.3.4`.
- **Q3**: open the live view directly (`:8000`) and through the front, side by side. The
  front adds at most 100 ms. Note the number.

## Drills (need the workstation or a real device; Mohamed checks by eye)

| Drill | Steps | Pass |
|---|---|---|
| D1 address with no name | Open `https://<LAN address>/` on a PC that trusts the root | padlock, no warning (Caddy picked the site cert with no server name) |
| D2 limited root | Trust the root on Windows Chrome, Windows Edge and Android Chrome; open both apps | no warning on any. If one warns: re-make with `--no-limits`, note which device |
| D3 service account | Install; reboot; nobody signs in | both services running; GPU in use; a network camera live |
| D4 power cut | Pull the plug, restore power | HTTPS answers within 5 minutes (SC-005) |
| D5 strict stop | Rename one enabled model file, restart the service | service stopped after 3 tries; both apps say the engine is not running; `logs\start-failure.txt` names the model |
| D6 update and back | `update.ps1` with a new kit, then `-Back` | the previous version runs on the pre-update backup |
| D7 clean machine | A person who is not the developer follows `docs/ON-SITE-GUIDE.md` on a clean Windows 11 PC | done in one working day (SC-006) |
| D8 install as an app | Install the console on a PC and the phone app on a phone from their addresses | each opens from its icon |

## Results

**Install drill 1, 18 Oct 2026.** Mohamed's laptop stood in for the workstation (RTX 2080
Max-Q, Windows 11, Wi-Fi 192.168.1.5, `tls.names` 192.168.1.5 / 127.0.0.1 / localhost).
Kit `v0.16.0-drill1` from `tools/make_release.ps1`, which worked on its first run.
D4 is set aside for now by Mohamed's decision (the laptop is not kept on day and night).

- `install.ps1` ran steps 1–9. The engine then failed: the dev setup's `.engine` files
  (TensorRT 11.2) had been copied into an install with TensorRT 11.4. Fixed in `cfab60e`
  (copy no plans, rebuild a plan that will not open, fall back to `.pt` if one still
  will not). After the rebuild, both services ran and `https://localhost/healthz` answered.
- **D3, in part**: under `LocalService`, person and pose ran on TensorRT on the GPU, and
  the laptop webcam opened and delivered frames. Not yet: a reboot with nobody signed
  in, and a network camera (there is none here).
- **D5, by accident**: the failed start stopped after three restarts, and
  `logs\start-failure.txt` named what failed (person detection, the TensorRT plan).
  Both apps showing "engine is not running" was not checked by eye.
- Not yet: D1, D2, D6, D7, D8, and Q1–Q3.

**Install drills 2 and 3, same day: running it again.**

- From kit `v0.16.0-drill2`: step 4 found every copied plan stale and rebuilt it
  (person and pose were already rebuilt). Step 6 then stopped on WinSW `refresh`, which
  2.12 does not have; fixed in `0342c79`.
- From the installed copy, `C:\VisionGuard\app\deploy\install.ps1`: every step ran or
  skipped as it should. The services were kept and updated, the administrator was kept,
  the firewall rules were kept, and the Public-network warning named the Wi-Fi.
  `https://localhost/healthz` answered and the engine started with both cameras and
  TensorRT. "Safe to run twice" holds.
- `search` (the old bag model nothing loads) fails to build because the `clip` package is
  missing. The step goes on and the summary says so; nothing depends on it.
