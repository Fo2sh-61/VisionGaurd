# Implementation Plan: Pilot site readiness

**Branch**: `remote-access` (spec directory `016-pilot-site-readiness`) | **Date**: 17 Oct 2026 |
**Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), spec 020's [plan.md](../020-private-remote-access/plan.md)
sections C and D (carried in below as requirements), and a read of the code at `2c85ebe`.
Mohamed's decisions of 17 Oct 2026:
- the workstation runs VisionGuard as a hidden Windows service (**WinSW**). It starts at
  boot and stays up when the window closes;
- one installer, and **one icon**, which only opens the console window;
- remote PCs and Android phones use the **installable app** (020 section K). There is no
  native APK or exe, and the app updates from the workstation by itself;
- console on **443**, phone app on **8443**;
- **Caddy** in front, and **our own certificate script**.

## Summary

One install puts VisionGuard on the workstation. Two hidden Windows services start at boot
with nobody signed in: the **engine** (unchanged, still on `127.0.0.1:8000`) and **Caddy**,
which serves the two built apps over HTTPS and passes API calls to the engine. People open
the console at `https://<address>/` and the phone app at `https://<address>:8443/`, once, then
install it as an app. After that nobody types an address. There is no native app to build
or hand out, and each installed app picks up a new version from the workstation the next
time it opens. The workstation's one desktop icon opens the console in its own window, and
closing that window no longer stops anything. The
site certificate comes from our own small script. Devices trust a fixed root, and the root's
private key stays on the owner's USB stick.

Records: one shared migration step list runs at start. A settings table holds the school
profile, the three retention periods and the backup folder. One maintenance thread does the
nightly backup and the daily clean-up and records each run for System Health. Erasing a
person removes every row and file about them except the audit.

Buttons: the school-profile Save and the account Edit become real on both apps. The
password-free developer sign-in is deleted.

## What exists today (code at `2c85ebe`)

| Item | State | Evidence |
|---|---|---|
| HTTPS, served apps | None | `serve.py:99` `uvicorn.run` has no TLS; no `StaticFiles`; apps only on Vite 5173/5174 |
| Engine address | `127.0.0.1:8000` | `config.py:688` `ApiConfig` |
| Strict mode | Env `VG_STRICT=1`, off by default | `app.py:1745` `_reraise_if_strict`, 18 call sites, none for a camera |
| Logs | Console only | No handler or file anywhere in `engine/vg` |
| Own Python | None | `.venv` absent; `launch.ps1:252` passes `-AllowSystemPython` |
| Site config path | Fixed | `config.load()` reads `ENGINE_DIR/engine.yaml` and `ENGINE_DIR/.env` (`config.py:1322`) |
| Developer sign-in | Present | `git grep -niE "dev.?sign.?in"` → 97 lines in 30 files |
| Accounts | Read only | `GET /users` only (`app.py:3517`); `UserStore.set_disabled` exists with no route; no role or name change; `user_for_token` already refuses a disabled user (`auth/store.py:332`) |
| School profile | Read only | `GET /settings/school`; values from the frozen `config.hours`, read in 5 places in `live.py` (`hours = self.config.hours`), `app.py:971` (handed to `AlertService` once), and `app.py:2471`, `:2536` (`weapon_window`) |
| Database | One file, `engine/data/visionguard.db` | 12 stores share it (`db.py:48`). No version number. Three copied add-column functions, one drop-column |
| Retention | Partial | Knife clips and gate images expire at 30 days. Zone clips are kept by count, 3 per camera. Delivery log 90 days. `sighting`, `anchor`, `vehicle_pass`, `fall_scene` never deleted; `AppearanceStore.prune`, `AreaCountStore.prune`, `purge_expired` exist but nothing calls them |
| Erasure | Partial | `DELETE /people/{id}` deletes `person` and `face_embedding` and reloads the gallery, audit first. It leaves `sighting`, `anchor`, `appearance_sighting` |
| Backup, restore | None | — |
| Health grid | Shows names on the console | `web/src/pages/SystemHealth.tsx:279` passes no `detections={false}` (the phone does) |
| Page and API paths | Clash | Both apps use `BrowserRouter`. About 10 page paths are also API paths (`/people`, `/weapons`, …), so a reload on them would reach the engine |

## Design

### A. HTTPS front: Caddy (020 section D)

- **Caddy 2.11** (Apache-2.0, one `caddy.exe`). Config `deploy/Caddyfile`, two sites:
  - `:443` serves `web/dist` (console);
  - `:8443` serves `mobile/dist` (phone app).
- **No plain HTTP.** No port 80 listener (`auto_https off`). Plain HTTP sent to 443 or 8443
  gets Caddy's refusal, never a page or data (P10-FR-007).
- **What goes where**, the same rule on both sites:
  1. A page load (the browser's `Accept` header contains `text/html`) that is **not** a media
     address → the app's `index.html`. Media addresses: paths ending `/clip`, `/snapshot` or
     `/stream`, any path under `/path/legs/`, and `/docs`, `/redoc`, `/openapi.json`. This
     fixes the page/API clash: reloading `/people` shows the page, while the knife clip link
     (`Weapons.tsx:220`) still opens the clip.
  2. Any path starting with an `API_PATHS` entry, plus `/connection` and `/push` (020) →
     `reverse_proxy 127.0.0.1:8000`.
  3. Anything else → a file from the build, else `index.html`.
- **Real address**: `header_up X-Forwarded-For {remote_host}` replaces whatever the client
  sent. `serve.py` sets `proxy_headers=True, forwarded_allow_ips="127.0.0.1"`, so only Caddy
  is believed.
- **MJPEG**: `flush_interval -1` on the proxy, so video is never buffered.
- **HTTP/2**: on by default with TLS. `protocols h1 h2`; HTTP/3 off, because the firewall
  opens TCP only.
- **Caching**: `Cache-Control: no-cache` on every `index.html` answer and on
  `manifest.webmanifest` and `sw.js`. `/assets/*` (hashed by Vite) are cached for a year.
- **Engine down**: Caddy keeps serving the apps, and API calls get 502. Both apps show one
  new catalogue sentence for 502: "VisionGuard's engine is not running. The reason is in
  `C:\VisionGuard\logs` on the workstation." This keeps rule 8 when strict mode stops the
  engine.
- **Logs**: `C:\VisionGuard\logs\front.log`, 10 MB × 10 files.
- **Drift guard**: `engine/tests/test_front.py` reads `deploy/Caddyfile`. It checks three
  things:
  - every page path in both `routes.tsx` files is not a media address;
  - every media route in `app.routes` is one;
  - the first part of every path in `app.routes` is proxied.

  A new engine route then cannot be forgotten in the front.

### B. Site certificate: `engine/tools/site_cert.py` (020 section C)

- Uses `cryptography`. It is already installed (50.0.1, pulled in by `google-auth`), so it
  becomes a named, pinned line in `requirements.txt`. Nothing new is downloaded.
- New config block in `engine.yaml`, validated in `config.py`:
  `tls: { names: [...], cert_dir: ... }`.
  - `names` holds the LAN address, `127.0.0.1` and `localhost`.
  - The NetBird address is added by 020's owner step (P10-FR-107).
- `site_cert.py root --out E:\`:
  - writes `visionguard-root.crt` and `visionguard-root.key` to the USB stick only;
  - ECDSA P-256, 10 years, CA with path length 0;
  - **limited** (name constraints) to private addresses: 10/8, 172.16/12, 192.168/16,
    100.64/10 (NetBird), 127/8, and the name `localhost`. A stolen root can never vouch for
    a public website;
  - refuses an `--out` inside `C:\VisionGuard` or the backup folder.
- `site_cert.py site --root E:\`:
  - reads `tls.names` and writes `site.crt` and `site.key` into `cert_dir`
    (`C:\VisionGuard\data\tls`), valid 825 days;
  - refuses a name the root does not cover, with a plain reason;
  - when an address changes, re-run it. Devices keep trusting the same root.
- Trust: the installer imports the root `.crt` into the workstation's Local Machine root
  store. The guide shows the two taps on Android and the three clicks on Windows for every
  other device. Only the public `.crt` is ever copied.
- System Health row `certificate`:
  - shows the names and the expiry date;
  - warns 30 days before the end, and fails when expired or missing;
  - says "not set up" on a development machine;
  - 020 J adds its NetBird-address warning to this same row.

### C. Services, folders, logs, strict mode (P10-FR-005, -006, -008)

- **WinSW 2.12** (MIT). Two copies in `app\service\`, each with an XML file:
  - `visionguard-engine` runs `app\.venv\Scripts\python.exe engine\tools\serve.py` with
    `VG_STRICT=1` and `VG_HOME=C:\VisionGuard\data`;
  - `visionguard-front` runs `app\bin\caddy.exe run --config app\deploy\Caddyfile`.
  - Both start automatically at boot.
  - On failure: restart after 10 s, 3 times. The count resets after 1 hour. After the third
    failure the service stays stopped (P10-FR-005).
  - Account: `LocalService`. The installer gives it write access to `data\` and `logs\`
    only (least privilege; GPU and cameras are checked in drill D3).
- **Folders**:
  - `C:\VisionGuard\app\`: one release, with its own `.venv`, `bin\`, `web\dist`,
    `mobile\dist`. Replaced on update; the old one becomes `app.previous\`;
  - `data\`: `engine.yaml`, `.env`, `visionguard.db`, `clips\`, `tls\`;
  - `logs\`.
- **`VG_HOME`**: when set, `config.load()` reads `engine.yaml` and `.env` from it.
  Unset, nothing changes for development.
- **Logs**: `serve.py` adds one rotating file handler, `logs\engine.log`, 10 MB × 10 files
  (P10-FR-006). WinSW's own logs roll by size in the same folder.
- **Strict start**:
  - when a subsystem fails, or a migration fails, the engine writes one plain line to
    `logs\start-failure.txt` and exits; WinSW restarts it up to 3 times;
  - Windows shows the service stopped, and the apps show the "engine is not running" line
    from A;
  - a camera that is offline is never a start failure: none of the 18 strict call sites is
    a camera;
  - the installer checks that every model an enabled feature needs is present before it
    starts the service, so a missing model stops the install, not the site.
- **Workstation icon**: the installer makes one desktop shortcut, "VisionGuard". It runs
  `msedge.exe --app=https://localhost/`, which opens the console in its own window. It
  starts nothing and stops nothing.
  - There is no phone-app icon on the workstation; the phone app is for phones.
  - The developer launcher (`launch.ps1`) and its two shortcuts stay for development only.

### D. Install and update (P10-FR-001…004, -010)

- `tools/make_release.ps1` (developer machine):
  - takes `git archive <tag>` of `engine/` and `deploy/`, builds both apps
    (`npm run build`), adds `caddy.exe` and the WinSW exe;
  - writes `deploy/versions.txt` with each program's version and SHA-256;
  - **no model files** are included.
- `deploy/install.ps1` (site, run once as administrator):
  1. Python 3.14 from the python.org installer in the kit, if missing;
  2. `app\.venv`, then torch, `requirements.txt` and TensorRT (needs internet). There is no
     re-ID model (P10-FR-002), which also settles DEV_PLAN 1.4: the venv no longer waits
     for the re-ID handover;
  3. copies the owner's models from `-Models <folder>`. It checks that every file
     `engine.yaml` names is there; a missing one stops with its name and where it goes.
     Then `build_engines.py`. Nothing is downloaded (P10-FR-003);
  4. `site_cert.py site`, then trusts the root;
  5. the two services and the folder rights;
  6. `create_user.py --role admin`: the installer types the name, email and password. There
     is no default password (P10-FR-004);
  7. the one desktop shortcut;
  8. waits for `https://localhost/healthz`.
- `deploy/update.ps1` (P10-FR-010):
  1. stop both services;
  2. `backup.py now`;
  3. rename `app` to `app.previous` and unpack the new kit;
  4. venv and packages;
  5. start; the engine applies migrations itself;
  6. check `/healthz` within 3 minutes.
  - `update.ps1 -Back` reverses it: `app.previous` returns and `backup.py restore` brings
    back the backup from step 2.

### E. Developer sign-in removed (P10-FR-009, SC-007)

- Delete the module, its test, both banners, and its fields in `schemas.py`, `wire.ts`,
  `api.ts`, `AuthContext.tsx` and `AppShell.tsx`.
- Remove the launcher flags and the AGENTS.md and STATUS.md sections.
- Reword the historical lines in specs 013–015 and the council transcript.
- Done when `git grep -niE "dev.?sign.?in"` prints nothing.
- By-eye checks then sign in with a local test account made by `create_user.py`.

### F. Accounts (P10-FR-014…016)

- `UserStore.update_user(id, name=None, role=None, disabled=None)`, in one
  `BEGIN IMMEDIATE`:
  - it refuses (`LastAdminError`) when no active administrator would remain, whoever asks,
    including about themselves (P10-FR-015);
  - disabling also ends that user's sessions.
- `PATCH /users/{id}` → `User`; 409 with a plain reason for the last administrator.
  - `/users` is already admin-only by path (`ADMIN_PREFIXES`), so a guard is refused
    (P10-FR-013);
  - audit first.
- The wire `User` gains `disabled`.
- Both `Users.tsx`: Edit opens a small form (name, role, active). The phone gains the Edit
  it never had.
- Role changes and disabling already take effect on the next request: `user_for_token`
  reads the row on every call (P10-FR-016).

### G. Migrations (P3-FR-015, -016)

- `engine/vg/migrations.py`: one ordered list of steps, numbered with SQLite's
  `PRAGMA user_version` on the one database file.
  - It runs at start before any store opens, each step inside its own transaction.
  - A failing step rolls back, keeps the old number, logs `step N (<name>) failed: <reason>`
    and stops the engine. This happens with or without strict mode.
- Step 1 adds 016's tables (data model). The three existing add-column functions stay as
  they are, frozen. Every new change from now on (018's audit table included) is a step.
- `alembic` leaves `requirements.txt`. It was never used and its comment claims otherwise.

### H. Settings in the database (P3-FR-008, -009; P10-FR-011, -012)

- New `site_setting` key/value table in a small `SettingsStore`. It holds the school
  profile, the three retention periods and the backup folder.
  - The first read seeds from `engine.yaml`: clips 30, event rows 365, sightings 365.
- `PUT /settings/school`, `PUT /settings/retention`, `PUT /settings/backup`:
  - `/settings` writes are already admin-only by path;
  - they validate like `HoursConfig` (cut-off inside hours, term from before to) and answer
    422 with a plain reason;
  - audit before the write.
- Live use without a restart: `LiveStore` keeps the current profile behind one getter.
  Every place in the table above that reads `config.hours` reads the getter
  instead. `AlertService` gets a callable, not a copy.
- UI: both apps' Settings save the school profile, and an unreachable engine says "not
  saved". The console's Settings also shows the retention periods and the backup folder;
  the phone shows neither, so it has no dead controls.

### I. Maintenance: clean-up and backup (P3-FR-010…014)

- One `Maintenance` thread (`engine/vg/maintenance.py`) checks every 5 minutes, in site time:
  - backup once per day after 02:00;
  - clean-up once per day after 03:00;
  - both also run at start if the last one is more than 24 hours old.
- Each run is a `maintenance_run` row: kind, start, end, finished or not, counts or size,
  reason.
- **Clean-up**:
  - calls each store's own expiry with the saved periods. Clips: knife, zone, gate,
    operator recordings, track legs. Event rows: knife, zone, vehicle passes, falls, alert
    delivery log. Then sightings;
  - it also calls the existing unused prunes at their fixed periods: appearance 14 days,
    counts 90 days, expired sessions;
  - deletes in batches of 5,000 rows, so no long lock;
  - a locked file is retried next run, and the row says "incomplete" with the reason;
  - the alert sender's own daily delete (`_tick_retention`) is removed. The delivery log
    follows the event-rows period, as the spec's assumption says.
- **Backup**:
  - SQLite's online backup copies `visionguard.db` and `engine.yaml` into
    `<folder>\visionguard-YYYY-MM-DD-HHMM.partial\`;
  - then `PRAGMA integrity_check` and a `backup.json` (time, size, schema step, app
    version), then a rename to drop `.partial`. Only a renamed folder counts;
  - keeps the 7 newest and deletes older ones and stale partials;
  - `.env` (Gmail and camera secrets) and `tls\` are **not** backed up: the guide keeps
    those on the owner's USB stick with the root key;
  - clips are not backed up.
- `engine/tools/backup.py now | restore <folder>`. Restore refuses while the service runs,
  checks `backup.json` and integrity, and moves the current database aside. At the next
  start, migrations bring an older backup forward.
- System Health rows `cleanup` and `backup`:
  - "not run yet" and "never" rather than zero;
  - the backup row warns at 36 hours, when there has never been a backup, or when no folder
    is set, naming the last failure (rule 7: still a 200).

### J. Erasure (P3-FR-004…007)

- `DELETE /people/{id}` keeps its address and becomes full erasure.
  1. Count every kind of record.
  2. Write the audit entry: who, whom, when, the counts, no erased data.
  3. In one transaction (one database file, so this works): delete `person` (which
     cascades to embeddings), `sighting`, `anchor`, `appearance_sighting`, and an `erasure`
     row that lists the files still to delete.
  4. Delete the files, then mark the row done.
- An interrupted erasure is finished by the maintenance thread at the next start. Until
  then People says "erasure not finished".
- The gallery reloads at once (P3-FR-007, as today). A live follow of that person on Track
  stops showing the name and drops its recording. An open enrolment for them is cancelled.
- Audit entries mentioning the person stay (P3-FR-006).
- **SC-002 test**: a person with a row in every table and a file of every kind is erased.
  The test then scans every text and blob column of every table, and every file name, for
  their id and name: zero hits outside the audit.

### K. Smaller items

- **P10-FR-017**: the console's `SystemHealth.tsx` passes `detections={false}` (web
  `CamGrid` gains the prop the phone's already has), with a pytest that reads both files.
- **P10-FR-018**: every new sentence goes in `i18n/keys.ts`, `en.ts` and `ar.draft.ts`,
  byte-identical in both apps (`check_parity.py`).
- **Installable apps** (Mohamed, 17 Oct): `public/manifest.webmanifest`, the 192, 512 and
  512-maskable PNG icons (from `tools/make_icon.py`) and the `index.html` link in both
  apps. This is 020 K's first half, brought forward so pilot devices can install the apps.
  020 keeps `sw.js`.
  - No native APK or exe is made.
  - The installed app updates itself: the front sends `index.html` and the manifest with
    `no-cache` (A), so the next open after an update loads the new version from the
    workstation.
- **P10-FR-019**: `docs/ON-SITE-GUIDE.md`, short, covering each heading the requirement
  lists.

## 020's needs, traced

| 020 need (plan section) | Here | Lands in |
|---|---|---|
| C.1 `tls.names` from config, LAN + NetBird address | B | Phase 1 |
| C.2 devices trust a fixed root; site cert re-made on address change | B | Phase 1 |
| C.3 root key not on the workstation; root limited to the site's addresses | B (USB only; private ranges) | Phase 1 |
| D.1 two apps, two addresses | A: console 443, phone 8443 | Phase 1 |
| D.2 proxy incl. `/connection`, `/push`; replace `X-Forwarded-For` | A | Phase 1 |
| D.3 MJPEG unbuffered | A: `flush_interval -1` | Phase 1 |
| D.4 HTTP/2 | A: Caddy h2 | Phase 1 |
| D.5 no-cache `index.html`, manifest, `sw.js` | A | Phase 1 |
| D.6 front as a Windows service | C: `visionguard-front` | Phase 1 |
| Spec 020 "Depends on": P10-FR-005, -007, -009, -014, -016 | C, A+B, E, F | Phase 1 |

**Task order**:
- Phase 1, the 020 gate: A, B, C, the install steps D.1–D.8, E and F.
- Phase 2: G, H, I, J.
- Phase 3: K, the update script and the guide.
- Then the clean-machine drill (SC-006).

## Technical Context

**Language/Version**: Python 3.14 (engine); TypeScript + React + Vite (`web/`, `mobile/`);
PowerShell 5.1 (install scripts)

**Primary Dependencies**: FastAPI, uvicorn (existing). New programs: **Caddy 2.11**
(Apache-2.0) and **WinSW 2.12** (MIT), both free, single files, pinned by SHA-256 in
`deploy/versions.txt`. `cryptography` becomes explicit. `alembic` is removed

**Storage**: the one SQLite file. New tables: `site_setting`, `maintenance_run`, `erasure`

**Testing**: pytest, `npx.cmd tsc -b --force` in both apps, pyflakes,
`tools/check_parity.py`, and the drills in [quickstart.md](quickstart.md)

**Target Platform**: one Windows 11 workstation per site; Chrome or Edge on PCs, Chrome on
Android

**Project Type**: web service + two web apps + install scripts

**Performance Goals**:
- the front adds at most 100 ms to a live view (measured on the clip, quickstart Q3);
- answering over HTTPS within 5 minutes of power returning (SC-005);
- backup and clean-up never stop a camera.

**Constraints**: $0, no card; no model downloaded; engine never reachable except through the
front; nothing in install, backup or clean-up assumes a camera count

**Scale/Scope**: one site, about 16 cameras to start; camera count is read from the database

## Constitution Check

| Principle / rule | How this plan keeps it |
|---|---|
| I. Real-time | No frame path changes. Video is unbuffered through the front, which speaks HTTP/2. The added delay is measured (Q3) |
| II. Feature isolation | No feature worker changes. Maintenance is its own thread and calls each store's own expiry |
| III. Truthful data | The two fake controls become real. Clean-up, backup and certificate rows come from recorded runs and real files ("not run yet", "never"). A stopped engine is named on screen. Restore is proved by a test |
| IV. Reliability, security, privacy | HTTPS only. The root key stays off the workstation, and the root is limited to private addresses. The password-free sign-in is gone. The last administrator is protected, and disabled sessions stop. Erasure is complete and audited. Retention runs daily. Backups are tested by restore. Migrations run in transactions. The service account has least privilege. Secrets are not in backups |
| V. Complete UX | Both apps get the edit forms and their failure states. Nothing the phone cannot do is shown on the phone |
| Rule 7, degradation is payload | Clean-up, backup and certificate are health rows; health stays 200 |
| Rule 8, failures in the UI | Strict mode stops the engine. The front keeps serving both apps, which say the engine is not running and where the reason is (`logs\start-failure.txt`) |
| Rule 9, no feature needs another | Maintenance, front and settings need no feature switched on |
| Rule 10, weapons | No person can delete a knife entry. Retention is the site's audited policy (spec) |
| Rule 11 / audit first | Every new write calls `_log` first. Entries survive a restart only once 018 lands; that is 018's job and is stated, not hidden |
| Owner supplies models | The install copies and builds the owner's files; a missing file stops the install |
| Database is the source of truth | Profile, retention and backup folder move to `site_setting`; `engine.yaml` only seeds |

**Passes**, with two items for Mohamed's eye:
- the strict-mode trade from the spec (rule 8 is kept through the front);
- the delivery log goes from 90 to 365 days, because it is an "event row".

## Decisions made without asking (say if any is wrong)

- Backup after 02:00 and clean-up after 03:00, site time.
- 3 restarts, 10 s apart.
- Site certificate valid 825 days, root valid 10 years.
- Install under `C:\VisionGuard`.
- Services run as `LocalService`.
- `.env` and `tls\` are kept on the owner's USB stick, not in backups.

## Risks (biggest first)

1. **Strict mode with a feature switched on and its model missing stops the whole site.**
   The installer checks the models first, and the guide says to switch unused features off.
2. **A device may refuse a limited root.** Drill D2 checks Windows Chrome and Edge and
   Android Chrome. Fallback: `site_cert.py root --no-limits`, which the guide names.
3. **A browser typing an address sends no server name (SNI).** Caddy must still pick the
   site certificate. Drill D1 checks it; fallback: `default_sni` in the Caddyfile.
4. **GPU or cameras under `LocalService`.** Drill D3. Fallback: `LocalSystem`, recorded as a
   waiver. USB webcams under a service are not promised; the pilot uses network cameras.
5. **The install needs internet for the packages** (torch is about 2.5 GB). The guide says
   so; a wheel folder in the kit is a later option.

## Project Structure

### Documentation (this feature)

```text
specs/016-pilot-site-readiness/
├── plan.md          # this file
├── research.md      # the choices and why
├── data-model.md    # the three new tables and the settings keys
├── contracts/api.md # new and changed endpoints
├── quickstart.md    # checks and drills
├── context.md       # hand-over for the implementing chat
└── tasks.md         # /speckit-tasks, when Mohamed agrees
```

### Source Code (repository root)

```text
deploy/                     # new: Caddyfile, install.ps1, update.ps1, versions.txt,
                            #      service/visionguard-engine.xml, visionguard-front.xml
tools/make_release.ps1      # new
engine/tools/site_cert.py   # new
engine/tools/backup.py      # new (now | restore)
engine/tools/serve.py       # rotating log file, proxy-header trust, start-failure file
engine/vg/config.py         # tls block; VG_HOME
engine/vg/migrations.py     # new
engine/vg/settings_store.py # new: SettingsStore (site_setting)
engine/vg/maintenance.py    # new: clean-up, backup, unfinished erasures
engine/vg/auth/store.py     # update_user + last-admin guard
engine/vg/api/app.py        # PATCH /users/{id}, PUT /settings/*, erasure, startup order
engine/vg/api/live.py       # profile getter, health rows, erase_person
engine/vg/api/schemas.py    # User.disabled, settings and health types
engine/vg/events/*.py       # expiry functions where missing (zones by age, falls, sightings)
engine/vg/alerts/service.py # hours as a callable; _tick_retention removed
engine/tests/               # test_front, test_site_cert, test_migrations, test_settings,
                            # test_maintenance, test_backup_restore, test_erasure, test_users_edit
web/, mobile/               # Users, Settings, SystemHealth, CamGrid (web), i18n,
                            # manifest + icons; remove the developer sign-in pieces
docs/ON-SITE-GUIDE.md       # new
```

**Structure Decision**: the existing engine and two apps. New code only where nothing exists
(`deploy/`, three engine modules, two tools).

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| Caddy, a second program | Two served apps, HTTP/2, unbuffered video (020 D) | The engine serving itself gives HTTP/1.1 only, and 020 E would have to be rewritten |
| WinSW | A real service with bounded restarts (P10-FR-005) | Python service code needs pywin32 and is fragile with a venv. Task Scheduler is not a service and does not restart after a crash |
| Page-or-API rule in the Caddyfile | About 10 page paths are also API paths | Moving the API under `/api` changes the contract for both apps and every test |
| `user_version` step list | Versioned changes with rollback (P3-FR-015, -016) | Alembic expects SQLAlchemy models these stores do not have |
