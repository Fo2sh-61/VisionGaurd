# Tasks: Pilot site readiness

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[quickstart.md](quickstart.md), [context.md](context.md). Read `context.md` first.

**Tests**: required. Constitution: test first for business rules and security. Every test
task below is written, and seen failing, before the task that makes it pass.

**Phase 1 is spec 020's gate.** Spec 020 starts only after T001–T030 are merged. They cover
the HTTPS front, the certificate, the services and install, the password-free sign-in
removal and account editing.

**Two apps**: `tools/check_parity.py` keeps `types.ts`, `services/*.ts`, `i18n/*` and some
`app/*` files identical in `web/` and `mobile/`. Pages and components are separate copies.
Every UI task names both apps and is done when **both** pass `npx.cmd tsc -b --force`.

**CRLF files** (`api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`): write bytes, then
check `git diff --stat`.

**Never write the words the SC-007 grep looks for** in a new file (see `context.md`
section 3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no unfinished dependency)
- **[Story]**: US1–US8 below
- Paths are from the repository root

## User stories (from spec.md)

| Story | Priority | Spec scenarios | Requirements |
|---|---|---|---|
| US1 HTTPS front and site certificate | P1 (020 gate) | 13 | P10-FR-007; 020 C, D.1–D.5 |
| US2 Runs by itself: services, own Python, logs, strict, install | P1 (020 gate) | 11, 12, 14 | P10-FR-001…006, -008; 020 D.6 |
| US3 Password-free sign-in removed | P1 (020 gate) | 15 | P10-FR-009, SC-007 |
| US4 Accounts can be changed and disabled | P1 (020 gate) | 18, 19, 20 | P10-FR-013…016, SC-009 |
| US5 Records cleaned, backed up, restorable, migrated | P2 | 4–10 | P3-FR-008…016, SC-003, -004, -010 |
| US6 Erase one person | P2 | 3 | P3-FR-004…007, SC-002 |
| US7 School profile saves; no names on the health grid | P2 | 17, 18, 21 | P10-FR-011…013, -017, SC-008 |
| US8 Update and on-site guide | P3 | 16, 22 | P10-FR-010, -019, SC-005, -006 |

P10-FR-018 (every new sentence in the shared catalogue, English and Arabic draft) applies to
every UI task.

---

## Phase 1: Spec 020's gate (lands first)

### 1a. Setup

- [ ] T001 Add `cryptography>=50` as a named line under a new `# --- site ---` heading in
      `engine/requirements.txt`. It is already installed through `google-auth`; this stops
      it vanishing
- [ ] T002 Add the `tls` block (`names`, `cert_dir`) to `engine/vg/config.py` next to
      `ApiConfig`:
  - each name must be an IP address or `localhost`; anything else is refused with its
    position;
  - an absent block gives `tls=None`;
  - add a commented example to `engine/engine.yaml`;
  - tests in `engine/tests/test_config.py` for both
- [ ] T003 Make `config.load()` in `engine/vg/config.py` read `engine.yaml` and `.env` from
      `VG_HOME` when that is set; unset changes nothing. Test in
      `engine/tests/test_config.py` with a temporary folder
- [ ] T004 Owner step: ask Mohamed to download **Caddy 2.11.7** (`caddy_2.11.7_windows_amd64.zip`)
      and **WinSW 2.12.0** (`WinSW-x64.exe`) from their GitHub release pages into
      `deploy/bin/`. Add `deploy/bin/` to `.gitignore`. Write `deploy/versions.txt` with
      each file's version and SHA-256 (`Get-FileHash`). Never download them yourself

### 1b. US1: HTTPS front and site certificate

**Independent test**: `test_site_cert.py` and `test_front.py` pass. Quickstart Q1–Q3 work on
the recorded clip with a certificate from `site_cert.py`.

- [ ] T005 [P] [US1] Write `engine/tests/test_site_cert.py`:
  - the root is a CA with path length 0, ECDSA P-256, 10 years;
  - its name constraints permit exactly 10/8, 172.16/12, 192.168/16, 100.64/10, 127/8 and
    the name `localhost`;
  - `--no-limits` makes a root without constraints;
  - the site cert's names equal `tls.names`, it is for server use, valid 825 days, signed
    by the root;
  - a public address in `tls.names` is refused with a plain reason;
  - `root --out` inside the install folder or the backup folder is refused (both passed in
    as parameters so the test uses temporary paths);
  - the root key is never written to `cert_dir`
- [ ] T006 [US1] Create `engine/tools/site_cert.py` with `root --out <usb> [--no-limits]` and
      `site --root <usb>` (plan B), using `cryptography`. It reads `tls.names` and
      `tls.cert_dir` through `vg.config.load()`. T005 passes
- [ ] T007 [P] [US1] Write `engine/tests/test_front.py`, which reads `deploy/Caddyfile` as
      text and checks:
  - every page path in `web/src/app/routes.tsx` and `mobile/src/app/routes.tsx` is not a
    media address;
  - every media route in `vg.api.app` routes (ending `/clip`, `/snapshot`, `/stream`, or
    under `/path/legs/`) is one;
  - the first part of every engine route path, plus `/connection` and `/push`, is
    proxied;
  - `:443` serves `web/dist` and `:8443` serves `mobile/dist`;
  - there is no `:80` site and `auto_https off` is set;
  - it has `flush_interval -1`, `header_up X-Forwarded-For {remote_host}` and
    `protocols h1 h2`;
  - `no-cache` applies to `index.html` answers, `manifest.webmanifest` and `sw.js`, and
    `/assets/*` is cached for a year;
  - Caddy logs to `C:\VisionGuard\logs\front.log`, 10 MB × 10
- [ ] T008 [US1] Write `deploy/Caddyfile` (plan A, rules in `contracts/api.md`). T007 passes
- [ ] T009 [US1] In `engine/tools/serve.py`, pass `proxy_headers=True` and
      `forwarded_allow_ips="127.0.0.1"` to `uvicorn.run`. Add a test to
      `engine/tests/test_front.py` that captures the call's arguments with a fake
      `uvicorn.run`. This is the first half of 020's T006
- [ ] T010 [US1] Add a `certificate` row to `LiveStore.health()` in `engine/vg/api/live.py`,
      copying `_alerts_stage`:
  - it reads `site.crt` from `tls.cert_dir`, re-read when the file changes;
  - "not set up" when there is no `tls` block;
  - a warning within 30 days of the end; a failure when expired or missing;
  - it lists the names;
  - add the note codes to `engine/vg/api/notes.py` and the keys to `i18n/` in both apps;
  - tests in `engine/tests/test_health_rows.py` for each state, health still 200
- [ ] T011 [P] [US1] Add the "engine is not running" sentence (plan A) to `i18n/keys.ts`,
      `en.ts` and `ar.draft.ts`. Show it from `services/http.ts` when the front answers
      502, 503 or 504. These are shared files, so make the change in `web/` and copy the
      bytes to `mobile/`. Run `python tools/check_parity.py`
- [ ] T012 [P] [US1] Make both apps installable (plan K):
  - `web/public/manifest.webmanifest` and `mobile/public/manifest.webmanifest`: name,
    `short_name`, `start_url` and `scope` "/", `display` "standalone", theme and
    background colours, icons;
  - 192, 512 and 512-maskable PNG icons written by `tools/make_icon.py` into both
    `public/` folders;
  - `<link rel="manifest">` and `theme-color` in `web/index.html` and `mobile/index.html`;
  - no `sw.js` (that stays in 020)
- [ ] T013 [US1] Run quickstart Q1–Q3 on the recorded clip:
  - Caddy from `deploy/bin/` and a certificate from T006;
  - reloads on `/people` and `/weapons` show the page, and a knife clip link plays;
  - a forged `X-Forwarded-For` never reaches the engine log;
  - write Q3's measured delay into `quickstart.md`

### 1c. US2: Runs by itself

**Independent test**: `test_logging.py`, `test_check_models.py` and `test_deploy.py` pass.
On the workstation, drills D1, D3, D4 and D5 pass (Mohamed checks by eye).

- [ ] T014 [P] [US2] Write `engine/tests/test_logging.py`:
  - with `VG_LOGS` set, `serve.py`'s log set-up adds exactly one rotating file handler,
    `engine.log`, 10 MB × 10;
  - unset, it adds none;
  - an exception during startup writes `start-failure.txt` in `VG_LOGS`: one line naming
    what failed and why
- [ ] T015 [US2] Implement T014 in `engine/tools/serve.py`. T014 passes
- [ ] T016 [P] [US2] Write `engine/tests/test_check_models.py`, then create
      `engine/tools/check_models.py`:
  - it lists every model file an enabled feature in the loaded config needs;
  - each missing one prints `missing: <file> → <where it goes>`, and the tool exits 1;
  - it never downloads anything
- [ ] T017 [P] [US2] Create `deploy/service/visionguard-engine.xml` and
      `deploy/service/visionguard-front.xml` (plan C).
  - Engine: runs `app\.venv\Scripts\python.exe engine\tools\serve.py` with environment
    `VG_STRICT=1`, `VG_HOME=C:\VisionGuard\data`, `VG_LOGS=C:\VisionGuard\logs`.
  - Front: runs `app\bin\caddy.exe run --config app\deploy\Caddyfile`.
  - Both: start automatically; three `onfailure restart` of 10 sec, then `none`;
    `resetfailure` 1 hour; logs roll by size into `C:\VisionGuard\logs`; account
    `LocalService`.
  - `engine/tests/test_deploy.py` parses both files and checks those values
- [ ] T018 [US2] Write `engine/tests/test_strict.py`. Start the app under `VG_STRICT=1` with a
      camera whose source cannot be opened (copy how `test_sources.py` builds one) and
      assert startup succeeds: an offline camera is never a start failure. If the full
      startup is too heavy for a test, say so in the task and leave it to drill D5
- [ ] T019 [US2] Create `deploy/install.ps1 -Models <folder> -Root <usb>` with plan D's steps
      1–8:
  - Python 3.14 from the kit if missing;
  - `app\.venv` with torch, `requirements.txt` and TensorRT;
  - copy the models, then `check_models.py`, then `build_engines.py`;
  - `site_cert.py site`, then `Import-Certificate` into `Cert:\LocalMachine\Root`;
  - the two services, via the WinSW `install` command, and `icacls` rights for
    `LocalService` on `data\` and `logs\` only;
  - `create_user.py --role admin`;
  - **one** desktop shortcut "VisionGuard" →
    `msedge.exe --app=https://localhost/`, with the existing icon;
  - wait for `https://localhost/healthz`.
  - It stops at the first failed step with a plain message, and is safe to run twice
- [ ] T020 [US2] Create `tools/make_release.ps1 <tag>`:
  - `git archive` of `engine/` and `deploy/` at the tag;
  - `npm run build` in `web/` and `mobile/`, copying both `dist/` folders;
  - `deploy/bin/` programs, checked against `deploy/versions.txt` (it refuses on a
    mismatch);
  - the python.org installer from a folder Mohamed names;
  - a kit folder and a zip;
  - **no model files**
- [ ] T021 [US2] Drills on the workstation, Mohamed by eye:
  - D1: an address with no server name gets the padlock; if not, add `default_sni` to the
    Caddyfile;
  - D3: GPU and a network camera work under `LocalService`; if not, record the
    `LocalSystem` waiver;
  - D4: power cut; HTTPS answers within 5 minutes;
  - D5: strict stop.
  - Write the results into `quickstart.md`

### 1d. US3: Password-free sign-in removed

**Independent test**: `git grep -niE "dev.?sign.?in"` prints nothing. All checks are
green.

- [ ] T022 [US3] Engine: delete `engine/vg/auth/dev_sign*.py` and
      `engine/tests/test_dev_sign*.py`, and their uses in `engine/vg/api/app.py` and
      `engine/vg/api/schemas.py`. pytest is green. Say in the commit how many tests left
      with the file
- [ ] T023 [P] [US3] Apps: delete `web/src/components/DevSign*Banner.tsx` and
      `mobile/src/components/DevSign*Banner.tsx`. Remove their uses in both `AppShell.tsx`,
      and in the shared `AuthContext.tsx`, `services/api.ts` and `services/wire.ts` (copy
      the bytes, parity check). Both `tsc` are clean
- [ ] T024 [US3] The rest:
  - the launcher flag in `dev.ps1`;
  - the "Temporary — seeing a page yourself" section of `AGENTS.md`, replaced by one line:
    sign in with a local account made by `engine/tools/create_user.py`;
  - the lines in `STATUS.md`;
  - reword the historical lines in `specs/013-alert-delivery/`,
    `specs/014-mobile-ui-parity/` and `specs/015-phone-first-redesign/`, and in the
    council transcript under `.agents/skills/llm-council/transcripts/`.
  - Done when the grep prints nothing (SC-007)

### 1e. US4: Accounts

**Independent test**: `test_users_edit.py` passes. On both apps an administrator renames,
changes the role of, and disables an account; the disabled account is signed out on its
next click.

- [ ] T025 [P] [US4] Write `engine/tests/test_users_edit.py`:
  - `PATCH /users/{id}` saves name, role and disabled;
  - the audit entry is written before the write (make the write fail: the entry exists);
  - an `it` caller gets 403; unknown id 404; empty name or unknown role 422;
  - the last active administrator cannot be demoted or disabled, by another account or by
    themselves: 409 with a plain reason, every way (SC-009);
  - with two administrators, one can be disabled;
  - a disabled user's token fails on its next request, and a role change applies on the
    next request;
  - `GET /users` shows `disabled`;
  - `MockStore` answers 503, never a fake save
- [ ] T026 [US4] Add `UserStore.update_user(id, name=None, role=None, disabled=None)` to
      `engine/vg/auth/store.py`:
  - in one `BEGIN IMMEDIATE`;
  - raises `LastAdminError` when no active administrator would remain;
  - disabling calls `end_all_sessions`
- [ ] T027 [US4] Add `PATCH /users/{id}` to `engine/vg/api/app.py` (409 on
      `LastAdminError`), `disabled: bool` to `User` in `engine/vg/api/schemas.py`, the fill
      in `LiveStore.users()`, and `SubsystemUnavailable` in `MockStore`. T025 passes
- [ ] T028 [US4] Shared: add `updateUser()` to `services/api.ts`, `disabled` to `types.ts`
      and `services/wire.ts`, and the words to `i18n/`. Write them in `web/`, copy the
      bytes to `mobile/`, and run the parity check
- [ ] T029 [US4] Edit form (name, role, active) in `web/src/pages/Users.tsx` (the dead
      Edit button gets its handler) and `mobile/src/pages/Users.tsx` (a new Edit per row):
  - a 409 shows the engine's reason;
  - an unreachable engine says "not saved";
  - both `tsc` are clean
- [ ] T030 Gate check: run quickstart's automated block. Then mark in
      `specs/020-private-remote-access/tasks.md` that 016's Phase 1 is merged, and that
      020's T006 `serve.py` pin was done by T009 here

**Checkpoint, spec 020's gate**: HTTPS on 443 and 8443, the site certificate, both services,
the install, no password-free sign-in, and account editing. Spec 020 may start.

---

## Phase 2: Foundational for records (blocks US5, US6, US7)

- [ ] T031 [P] Create `engine/tests/data/pre016.sql` once, from the schema as it is before
      this phase:
  - open every store on a temporary database;
  - insert one row in every table;
  - save `iterdump()`.

  Then write `engine/tests/test_migrations.py`:
  - a fresh database gets the latest `user_version` and the three new tables;
  - `pre016.sql` is brought forward with the row count of every table unchanged (SC-004);
  - an injected failing step stops start with `step N (<name>) failed: <reason>` and leaves
    `user_version` and every table unchanged (P3-FR-016);
  - a second run is a no-op
- [ ] T032 Create `engine/vg/migrations.py`:
  - `STEPS`, plus `run(path)` using `PRAGMA user_version`, one transaction per step;
  - step 1 creates `site_setting`, `maintenance_run` and `erasure` (`data-model.md`);
  - call it once in `engine/vg/api/app.py` startup, before any store opens and outside
    every subsystem's try/except;
  - remove the `alembic` line from `engine/requirements.txt`.
  - T031 passes
- [ ] T033 [P] Write `engine/tests/test_settings_store.py`:
  - the first read of each key seeds from config;
  - set then get round-trips;
  - values survive reopening;
  - every key's validation from `data-model.md` refuses bad values
- [ ] T034 Create `engine/vg/settings_store.py` (`SettingsStore`). Open it in app startup and
      hand it to `LiveStore`. T033 passes

**Checkpoint**: the schema is versioned and settings live in the database.

---

## Phase 3: US5, Records cleaned, backed up, restorable (P2)

**Independent test**: `test_maintenance.py`, `test_backup_restore.py`, `test_settings.py`
(retention and backup) and `test_health_rows.py` pass. System Health shows the last clean-up
and backup.

- [ ] T035 [P] [US5] Write `engine/tests/test_maintenance.py` with an injected clock and
      temporary folders:
  - a 31-day clip of every kind (knife, zone, gate, fall, operator recording, track leg) is
    gone, and its row says expired;
  - a 366-day sighting, knife row, zone row, vehicle pass, fall row and delivery-log row
    are gone; younger ones are kept;
  - appearance rows older than 14 days, counts older than 90 days and expired sessions are
    gone;
  - the counts are in `maintenance_run`;
  - a locked file gives `ok=0` "incomplete" with the reason, and is retried next run;
  - rows are deleted in batches of 5,000;
  - it runs once per site-local day after 03:00, and at start when the last run is more
    than 24 h old;
  - it uses the saved periods
- [ ] T036 [P] [US5] Add the missing expiry and age deletes, each in its own store:
  - zone clips by age in `engine/vg/events/zones.py`;
  - row deletion by age for `weapon_scene` (`events/weapons.py`), `zone_scene`,
    `vehicle_pass` (`events/vehicles.py`) and `fall_scene` (`events/falls.py`);
  - `SightingStore.delete_older_than` (`events/sightings.py`);
  - the operator-recording sweep, next to its writer (`app.py` near the "Operator
    recordings" comment)
- [ ] T037 [US5] Create `engine/vg/maintenance.py`, a `Maintenance` thread:
  - a 5-minute tick in site time;
  - the clean-up calls each store with the `SettingsStore` periods and records
    `maintenance_run`;
  - start it in app startup as its own subsystem.
  - Remove `_tick_retention` from `engine/vg/alerts/service.py`. Remove
    `alerts.log_retention_days` from `config.py` and `engine.yaml`; an old site file
    that still has it gets one log line, not a refusal.
  - T035 passes
- [ ] T038 [P] [US5] Write `engine/tests/test_backup_restore.py`:
  - a backup makes a named folder with the database, `engine.yaml` and `backup.json`, and
    passes the integrity check;
  - a failure part-way leaves only `.partial`, which does not count and is cleaned up
    later;
  - eight backups leave the seven newest;
  - no folder set gives `ok=0` "no folder";
  - restore into an empty `VG_HOME`: every table's rows match, an enrolled embedding
    matches again through `FaceGallery` (SC-003), and an account signs in;
  - restore refuses while `127.0.0.1:8000/healthz` answers (stubbed);
  - an older backup is brought forward at the next start
- [ ] T039 [US5] Add the backup to `engine/vg/maintenance.py` (after 02:00, SQLite
      `backup()`, `integrity_check`, `backup.json`, rename, keep 7), and create
      `engine/tools/backup.py now | restore <folder>`. T038 passes
- [ ] T040 [P] [US5] Write the retention and backup parts of `engine/tests/test_settings.py`:
  - `GET`/`PUT /settings/retention` and `/settings/backup` are admin only (`it` gets 403);
  - audit first;
  - 422 outside 1–3650, for a missing folder, or for a folder inside the data folder;
  - values survive a restart (scenario 5)
- [ ] T041 [US5] Add those routes to `engine/vg/api/app.py`, with types in `schemas.py` and
      `LiveStore` methods. T040 passes
- [ ] T042 [US5] Add `cleanup` and `backup` rows to `LiveStore.health()` in
      `engine/vg/api/live.py`, copying `_alerts_stage`:
  - "not run yet", "never", incomplete with the reason;
  - the 36-hour warning naming the last failure, and "no folder set";
  - note codes in `notes.py`, keys in `i18n/` in both apps;
  - tests in `engine/tests/test_health_rows.py`; health stays 200 (SC-010)
- [ ] T043 [US5] In `web/src/pages/Settings.tsx`, add the administrators' section for the
      three retention periods and the backup folder. Shared API functions and words go in
      both apps (parity). The phone shows nothing new

---

## Phase 4: US6, Erase one person (P2)

**Independent test**: `test_erasure.py` passes; SC-002's scan finds nothing outside the
audit.

- [ ] T044 [US6] Read `engine/vg/archive.py`, the person-history route and the
      follow-recording routes (`follow_record_start` in `app.py`). Find every file and row
      that names a person beyond `sighting`, `anchor` and `appearance_sighting`, and
      write the list into `context.md` section 5
- [ ] T045 [P] [US6] Write `engine/tests/test_erasure.py`:
  - set up a person with a row in every per-person table and a file of every kind from
    T044;
  - `DELETE /people/{id}`, then scan every text and blob column of every table, and every
    file name under the clips folder, for their id and name: zero hits outside the audit
    (SC-002);
  - the audit entry is written before, with counts and no erased data (P3-FR-005);
    older audit entries are untouched (P3-FR-006);
  - recognition stops without a restart (P3-FR-007);
  - a second person with the same name is untouched;
  - a failure after the rows are deleted leaves an `erasure` row with `files_left`, which
    is finished at the next start, and the same id gets 409 meanwhile;
  - an `it` caller gets 403
- [ ] T046 [US6] Implement `erase_person` in `engine/vg/api/live.py`:
  - one connection, one transaction (`context.md` traps);
  - point `DELETE /people/{id}` in `app.py` at it;
  - finish unfinished erasures in app startup;
  - a live Track follow of that person stops showing the name and drops its recording;
  - an open enrolment for them is cancelled.
  - T045 passes
- [ ] T047 [US6] People pages in `web/` and `mobile/`:
  - the remove confirmation says it erases every record about **this one person**;
  - "erasure not finished" shows when the engine says so;
  - words in `i18n/`, parity

---

## Phase 5: US7, School profile and the health grid (P2)

**Independent test**: `test_settings.py` (school) and `test_console_identity.py` pass. On
both apps an administrator saves the profile, and it is there after a restart.

- [ ] T048 [P] [US7] Write the school part of `engine/tests/test_settings.py`:
  - `PUT /settings/school` by an administrator is saved, audited first, and kept after a
    restart (SC-008);
  - an `it` caller gets 403 (P10-FR-013);
  - backwards term dates or a cut-off outside the hours get 422, and nothing is saved;
  - attendance marks late against the new cut-off at once, and term dates follow
    (P10-FR-012);
  - the alerts' school-day check and `weapon_window`'s school year use the new term;
  - of two saves, the later wins and both are audited
- [ ] T049 [US7] Add a `LiveStore.hours` getter backed by `SettingsStore`:
  - it replaces the five `self.config.hours` reads in `engine/vg/api/live.py`;
  - `AlertService` takes a callable (`app.py` near `hours=cfg.hours`,
    `alerts/service.py` `self.hours`);
  - the `weapon_window` callers in `app.py` read the getter;
  - add `PUT /settings/school`, reusing `HoursConfig`'s checks.
  - T048 passes
- [ ] T050 [US7] Save the school profile from both apps:
  - in `web/src/pages/Settings.tsx`, Edit/Done becomes a Save, and a failure says "not
    saved";
  - in `mobile/src/pages/Settings.tsx`, administrators get an edit form in place of
    `phone.settings.readOnly`;
  - `saveSchoolProfile()` in the shared `services/api.ts`; words; parity; both `tsc`
- [ ] T051 [P] [US7] Write `engine/tests/test_console_identity.py`, which reads both
      `SystemHealth.tsx` files and asserts the grid gets `detections={false}`. Then add the
      `detections` prop to `web/src/components/CamGrid.tsx` (copy
      `mobile/src/components/CamGrid.tsx`) and pass `false` from
      `web/src/pages/SystemHealth.tsx` (P10-FR-017)

---

## Phase 6: US8, Update and on-site guide (P3)

**Independent test**: drills D6, D7, D2 and D8 pass.

- [ ] T052 [US8] Create `deploy/update.ps1 <kit>` and `-Back` (plan D):
  - stop both services;
  - `backup.py now`;
  - `app` → `app.previous`, then unpack;
  - venv and packages;
  - start, and check `/healthz` within 3 minutes;
  - `-Back` restores `app.previous` and that backup
- [ ] T053 [US8] Write `docs/ON-SITE-GUIDE.md`, short, with the P10-FR-019 headings:
  - install; accounts; cameras; alert email keys;
  - backup and restore; update and the way back;
  - trust the certificate on Windows and Android;
  - the engine will not start (`logs\start-failure.txt`); a camera goes dark.
  - It also says that `.env` and the root key live on the owner's USB stick, and that
    unused features must be switched off
- [ ] T054 [US8] Drills, Mohamed by eye:
  - D2: a limited root on Windows Chrome, Edge and Android Chrome; re-make with
    `--no-limits` if one refuses;
  - D6: update and back;
  - D8: install as an app on a PC and a phone;
  - D7: a person who is not the developer installs on a clean PC in one day (SC-006).
  - Write the results into `quickstart.md`

---

## Final phase: Polish

- [ ] T055 [P] Update `STATUS.md` (CRLF), the P3 and P10 rows of `docs/PLAN.md`, and
      `AGENTS.md`: `deploy/` and the logs folder in "Where things live", and the services
      in "How to work"
- [ ] T056 Full check:
  - `python -m pytest engine`: the count against the 2006 baseline, minus the deleted
    test file's tests;
  - both `tsc`, pyflakes, `tools/check_parity.py`, and the SC-007 grep.
  - Report any failure plainly

---

## Dependencies & execution order

- **Phase 1** first. Within it:
  - 1a before everything;
  - US1 (T005–T013) before US2's install (T019), which needs the Caddyfile and
    `site_cert.py`;
  - US3 and US4 are independent of US1 and US2, and of each other.
- **Phase 2** after Phase 1 (it touches the same startup in `app.py`). It blocks US5, US6
  and US7.
- **US5, US6, US7** are independent of each other after Phase 2. They share `app.py` and
  `live.py`, so run them one after another, not at once.
- **US8** last: it needs the install (US2) and the backup (US5).

## Parallel examples

- Phase 1 start: T005 (cert test), T007 (front test), T014 (logging test), T016
  (check_models) and T025 (accounts test) are all different files.
- US3 and US4 can run beside US1 in other sessions. Only one writer at a time on
  `app.py`, `schemas.py` and the shared `services/*.ts`.
- Phase 3: T035, T036 and T038 are different files.

## Implementation strategy

1. **Phase 1 is the MVP**: a site that serves both apps over HTTPS, runs as a service,
   installs from one script, has no password-free sign-in, and lets an administrator
   manage accounts. It also opens spec 020.
2. Then records (Phase 2, US5, US6), then the profile and grid (US7), then update and the
   guide (US8).
3. Commit after each task, or each test-and-code pair. Every fix ships with its test.
