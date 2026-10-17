# Tasks: Private remote access

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[owner-checklist.md](owner-checklist.md)

**Tests**: required. Constitution: test first for business rules and security. Every test
task below is written and seen failing before its implementation task.

**Gate before any task here**: the spec 016 and 018 work in the spec's "Depends on" table is
merged: HTTPS front with two app addresses, Windows service, served apps, developer sign-in
removed, account role change and disable, persistent audit with sign-ins. Nothing in this
file starts before that gate unless it is marked **(no gate)**.

**Two apps**: `tools/check_parity.py` keeps only `types.ts`, `services/*.ts` and `i18n/*`
identical in `web/` and `mobile/`. Pages and components are separate copies. Every UI task
below names both apps and is done when **both** pass their check.

**CRLF files** (`api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`): write bytes, then
check `git diff --stat`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no unfinished dependency)
- **[Story]**: US1–US6 below
- Paths are from the repository root

## User stories (from spec.md)

| Story | Priority | Spec scenarios | Requirements |
|---|---|---|---|
| US1 Reach the console from outside, enrolled devices only | P1 | 1–10, 28 | P10-FR-101…110, 123 |
| US2 Locked down | P1 | 17–21 | P10-FR-118…121, 124 |
| US3 Video that fits a remote link | P1 | 11–16 | P10-FR-113…117, 125 |
| US4 Install as an app, honest when offline | P2 | 1, 10 | P10-FR-111, 112 |
| US5 Alerts on the phone | P2 | 22–26 | P9-FR-101…109 |
| US6 Remote status on System Health | P3 | 7, 27 | P10-FR-122 |

---

## Phase 1: Setup

- [x] T001 **(no gate)** *(done 17 Oct 2026: 016 plan.md "020's needs, traced"; 016
      tasks.md Phase 1 is this spec's gate)* When spec 016 is planned, carry plan.md section C (`tls.names`
      from configuration with the LAN and NetBird addresses; devices trust a fixed root;
      root key not kept on the workstation) and section D into
      `specs/016-pilot-site-readiness/plan.md`. Section D covers: two app addresses; proxy
      `/connection` and `/push`; replace `X-Forwarded-For`; unbuffered MJPEG; HTTP/2 if
      available; no-cache for `index.html`, manifest and `sw.js`; Windows service. Order
      016's tasks so those land first
- [ ] T002 **(no gate)** Ask Mohamed to approve the one new library, `pywebpush` (plan,
      Complexity Tracking). On yes, add it pinned to `engine/requirements.txt`
- [ ] T003 Add the `remote:` block (`lan_networks`, `tile_interval_s`, `live_width`,
      `live_fps`, `live_views`), the auth block (`lockout_attempts`, `lockout_window_min`,
      `lockout_min`, `address_attempts`) and `push.allowed_hosts` to `engine/vg/config.py`,
      with validation and the plan's defaults. Seed them in `engine/engine.yaml`. Tests in
      `engine/tests/test_config.py`: a bad CIDR or host pattern and zero or negative numbers
      are refused; an absent block gives the defaults

## Phase 2: Foundational (blocks US2, US3, US6)

- [ ] T004 [P] Write `engine/tests/test_remote.py`:
  - local only for addresses in `lan_networks`;
  - the NetBird range, IPv6, unknown and missing client are remote;
  - `serve.py` passes `forwarded_allow_ips="127.0.0.1"`;
  - `GET /connection` gives the limits and `remote` for a LAN and a remote caller, and 401
    without a session
- [ ] T005 Create `engine/vg/api/remote.py`: `is_remote(request)`, a frozen `RemoteLimits`
      from config, the snapshot pacer keyed by (session, camera, width), and the per-account
      stream slots (each with its last-sent time, freed after 15 s idle or in `finally`)
- [ ] T006 Pin `forwarded_allow_ips="127.0.0.1"` in `engine/tools/serve.py`. Add the
      `Connection` wire type to `engine/vg/api/schemas.py` and `GET /connection` to
      `engine/vg/api/app.py`. Add `/connection` and `/push` to `API_PATHS` in
      `web/vite.config.ts` and `mobile/vite.config.ts`. T004 passes
- [ ] T007 [P] Add `getConnection()` and the `Connection` type to `services/api.ts` and
      `types.ts` (shared files, both apps); run `python tools/check_parity.py`

**Checkpoint**: the engine knows a remote caller, both apps can ask, and the address cannot
be forged through the engine's own settings.

---

## Phase 3: US2, Locked down (P1). Before anything is reachable from outside

**Independent test**: pytest alone proves the lockout, sign-up refusal, media sessions and
cookie. Drills D8 and D12 prove them on devices.

- [ ] T008 [P] [US2] Write `engine/tests/test_signin_lock.py`:
  - the 5th failure within 15 min locks;
  - the right password gets 423 with the unlock time while locked;
  - attempts while locked do not extend the lock;
  - ` Admin@X.com ` and `admin@x.com` share one count;
  - an unknown email locks the same way with the same answer;
  - the window resets (injected clock); success clears the count;
  - more than 20 failures from one address across emails gives 429;
  - expired rows are deleted;
  - `POST /users/{id}/unlock` works for an admin, is refused for `it` and guard, and is
    audited before the write;
  - `signin.locked` is audited before the 423, with the address;
  - `User.locked_until` is filled for a locked account
- [ ] T009 [US2] Add the `signin_lock` table and its methods to `engine/vg/auth/store.py`.
      The key is `strip()` then ASCII lower-case, cut to 254 characters
- [ ] T010 [US2] In `engine/vg/api/app.py`:
  - wire the lockout and the per-address cap into `login`;
  - add `POST /users/{id}/unlock` (admin-only by its `/users` path in `auth/deps.py`);
  - add `locked_until: Instant | None` to `User` in `schemas.py` and fill it in
    `LiveStore.users()`.
  - Audits use the store's `_log`, actor = the email key for an unknown sender.
  - T008 passes
- [ ] T011 [US2] Create `engine/tools/unlock_account.py <email>` for the owner at the
      workstation. It clears the lock and audits it with actor `workstation`. Add a test
      that loads it by path, as `test_track_page.py` loads its tool
- [ ] T012 [US2] Show "Locked until 14:20" and an Unlock button on a locked account in
      `web/src/pages/Users.tsx` **and** `mobile/src/pages/Users.tsx`, and the locked
      message on both `Login.tsx`. Words in `i18n/*`, sentences in `format.ts`; parity check
- [ ] T013 [P] [US2] Add to `engine/tests/test_remote.py`: `/auth/register` from a remote
      address → 403 "Sign up on the factory network", audited before the answer; from the
      LAN → works as today. Implement in `register` (`app.py`)
- [ ] T014 [P] [US2] Write `engine/tests/test_media_auth.py`:
  - every image, stream and clip GET route found by walking `app.routes` answers 401
    without a session;
  - `PUBLIC_PATHS` is exactly `/healthz`, `/auth/login`, `/auth/register`.
  - It should pass today; it guards the future
- [ ] T015 [P] [US2] Write `engine/tests/test_cookie.py`, then set `secure=True` in
      `_issue_session` (`app.py`) when 016's TLS setting is on; dev over plain HTTP unchanged
- [ ] T016 [US2] Add the real address and "factory network" / "private network" to the
      `detail` of sign-in, failed sign-in, lock, unlock and refused sign-up audit entries.
      Extend 018's sign-in audit tests
- [ ] T017 [US2] Run drills D8 and D12 (plan, Test plan); record in
      `specs/020-private-remote-access/drills.md`

**Checkpoint**: nothing new is exposed, an enrolled device alone gets nothing without a
real password, and guessing is stopped.

---

## Phase 4: US1, Reach the console from outside (P1)

**Independent test**: drills D1 (first half), D1-PC, D2–D7, D11 on the pilot workstation
with 016 installed.

- [ ] T018 [US1] Create `tools/remote-firewall.ps1`:
  - for each console port, one rule from `LocalSubnet` and one from `100.64.0.0/10`
    limited by `-InterfaceAlias` to the NetBird adapter (found by its 100.64 address), both
    `-Profile Any`;
  - it lists inbound allow rules opening the console ports, the front's program or Python
    to any address, and disables them only with `-Apply`;
  - without `-Apply` it only prints;
  - `-Undo` removes its rules and re-enables what it disabled;
  - ports are arguments, defaulting to 016's; port 8000 is never opened.
  - Check on a Windows 11 PC with `Get-NetFirewallRule | Get-NetFirewallAddressFilter`, and
    from an office PC on the LAN afterwards
- [ ] T019 [US1] Confirm 016's certificate step reads `tls.names`, accepts IP addresses, and
      lists the LAN and NetBird addresses; that only the root's public `.crt` is handed to
      devices; and that the root key is not left on the workstation
- [ ] T020 [US1] Walk owner-checklist parts A, B (except B11), C (except C8), D (except D8
      and D9), E and F on the pilot. Mohamed follows the text alone; the developer only
      times him and notes where he stumbles. Fix every step whose screen or wording
      differs, including how the NetBird app switches between two factories' accounts.
      Record the phone enrolment time in `drills.md` (SC-108)
- [ ] T021 [US1] Run drills D1 (with NetBird on), D1-PC, D2, D3, D4, D5, D6, D7 and D11;
      record date, device, result and time taken in `drills.md`. A failure stops this
      story until it is fixed or re-planned

**Checkpoint**: enrolled devices reach the console from anywhere; nobody else can.

---

## Phase 5: US3, Video that fits a remote link (P1)

**Independent test**: pytest for the limits; drill D10 for real bytes and the words on
screen.

- [ ] T022 [P] [US3] Write `engine/tests/test_remote_video.py`:
  - remote snapshot width capped at 480 and the `fps` hint capped;
  - a request inside 0.8 × `tile_interval_s` waits, then gets a new picture, with no error;
  - more than 4 waiting requests on one session → 429;
  - LAN requests are unchanged;
  - the remote stream sends ≤ `live_fps` frames a second at `live_width`;
  - the third concurrent remote stream for one account → 429;
  - a client that vanishes without closing frees its slot within 15 s;
  - a remote caller gets an unreduced event snapshot and clip (one of weapons or falls)
- [ ] T023 [US3] Apply the limits in the snapshot route (`app.py:2113`) and the stream route
      (`app.py:2176`) using `remote.py`. Frames are skipped, never queued. T022 passes
- [ ] T024 [US3] In `frame.ts` (shared) and in `web/src/components/CameraFrame.tsx` **and**
      `mobile/src/components/CameraFrame.tsx`:
  - when `getConnection().remote`, tiles poll every `tileIntervalSeconds` and show "every 2
    s" instead of LIVE;
  - a failed refresh shows "No picture since 14:05", and the page shows "Cannot reach the
    site";
  - the enlarged view shows "Live, reduced for remote";
  - a refused stream shows "Close another live view first".
  - Words in `i18n/*`, sentences in `format.ts`; parity check; `tsc` in both apps
- [ ] T025 [US3] Create `engine/tools/measure_remote_video.py`. Against the recorded clip
      (`dev.ps1 up -Clip`) it reads 60 s of the remote stream and 60 s of a 12-tile remote
      page and prints Mbit/s, plus the workstation's extra load in cores kept busy, at 2
      remote viewers × 2 live views. Write the measured figures into plan.md's bandwidth
      table and workstation-cost line in place of the estimates
- [ ] T026 [US3] Drill D10 on a real phone over mobile data, including the latency check
      against a running clock (SC-111); record in `drills.md`

**Checkpoint**: one person away uses about 2–3 Mbit/s of the factory's upload at most, and
the screen says honestly what it is showing.

---

## Phase 6: US4, Install as an app, honest when offline (P2)

**Independent test**: drill D1 shows "Install app" on Chrome Android and on Chrome and Edge
for Windows; with NetBird off, the plain offline page.

- [ ] T027 [P] [US4] Extend `tools/make_icon.py` to write 192 px, 512 px and 512 px
      maskable PNGs for each app from `web/src/components/Logo.tsx` into `web/public/` and
      `mobile/public/`
- [ ] T028 [P] [US4] Add `manifest.webmanifest` to `web/public/` and `mobile/public/`:
  - name, short_name, `start_url` "/", `scope` "/", `display` "standalone";
  - theme and background colours;
  - the icons.
  - Link it and add `theme-color` in both `index.html`
- [ ] T029 [US4] Add `sw.js` to `web/public/` and `mobile/public/`:
  - the `fetch` handler passes every request through;
  - on a failed page load it returns one cached plain page in English and Arabic: "cannot
    be reached right now; away from the factory, check NetBird; in the factory, check the
    network";
  - it caches nothing else, never an API answer.
  - Register it from both apps' entry files
- [ ] T030 [US4] `npx.cmd tsc -b --force` in `web/` and `mobile/`; build both; then the
      checklist steps C8 and D8, and the second half of drill D1 (NetBird off), on the pilot
      devices; record in `drills.md`

---

## Phase 7: US5, Alerts on the phone (P2)

**Independent test**: pytest for rules, content, addresses and failures; drill D9 for a
real locked phone.

- [ ] T031 [P] [US5] Write `engine/tests/test_push.py`:
  - the push rule is off by default;
  - a newly registered phone's recipient is disabled until an admin enables it;
  - only `https` endpoints on `push.allowed_hosts` are accepted (`http://…`, an IP literal,
    `192.168.1.1` and `127.0.0.1:8000` give 400);
  - a body holds only kind, camera and time;
  - an open knife is titled "Possible knife", the verdicts "Knife confirmed" / "False
    alarm";
  - a disabled account gets nothing and its devices are deleted;
  - removing the recipient deletes the device;
  - 404/410 removes the device and logs `failed: device gone`;
  - no network logs `failed: no internet`;
  - an existing alerts database gains the `push` column without losing rules;
  - with email off and push on for a kind, only the push is sent (P9-FR-107)
- [ ] T032 [US5] `engine/vg/alerts/events.py`: `CHANNELS = ("email", "push")` and
      `PUSH_FACTS`. `engine/vg/alerts/catalogue.py`: the push title per template
- [ ] T033 [US5] `engine/vg/alerts/store.py`:
  - an ADD COLUMN step for `alert_rule.push` (modelled on `auth/store.py:155`), and
    `DEFAULT_RULES`, `RULE_FLAGS` and the rule insert updated;
  - the `push_device` table;
  - `normalise_destination` for `push` (destination = device id);
  - phone recipients created with `enabled = 0`; removing one deletes its device row
- [ ] T034 [US5] `engine/vg/alerts/providers.py`: `REQUIRED_ENV["push"]` (the three VAPID
      variables), `for_channel("push")`, and a sender that looks up the device's keys and
      sends with `pywebpush`. A missing key reports the channel as not configured, as email
      does today
- [ ] T035 [US5] In `engine/vg/api/schemas.py`, add `push` to `AlertChannel`, `AlertRule`
      and `AlertRuleUpdate`; mirror in `types.ts`. In `app.py`, add `GET /push/key`,
      `POST /push/devices` (address check), `GET /push/devices` and
      `DELETE /push/devices/{id}`, own devices only. In `AuthStore.set_disabled` and 016's
      account delete, delete that account's devices. T031 passes
- [ ] T036 [US5] Add the three VAPID variable names (no values) to the `.env` example. Add a
      "make VAPID keys" step to 016's install procedure, and make sure `.env` is in 016's
      backup
- [ ] T037 [US5] `mobile/public/sw.js`: `push` shows the notification; `notificationclick`
      opens the event path. In `mobile/src/pages/Settings.tsx` add "Notifications on this
      phone": ask permission, subscribe with the VAPID key, register, and show "Waiting
      for an administrator" until enabled
- [ ] T038 [US5] In `web/src/components/AlertSettings.tsx` **and**
      `mobile/src/components/AlertSettings.tsx`: the push column next to email in the
      rules; phone recipients in the recipient list (person and device), with enable,
      remove and test send; push rows in the delivery log. Words in `i18n/*`; parity check
- [ ] T039 [US5] Checklist step D9 and drill D9 with Chrome swiped away and the phone
      locked; record in `drills.md`

---

## Phase 8: US6, Remote status on System Health (P3)

**Independent test**: pytest with canned client output; drill D6 shows "not connected".

- [ ] T040 [P] [US6] Write `engine/tests/test_remote_status.py` with canned
      `netbird status --json` outputs and the plain-text fallback:
  - no client → "not set up";
  - a client that cannot be run → "not connected — cannot read the NetBird client:
    <reason>";
  - management down → "not connected" with the reason;
  - healthy → "connected" with the address;
  - address missing from `tls.names` → a warning;
  - every state shows the time checked;
  - `health()` never runs the client itself;
  - System Health is 200 in every case
- [ ] T041 [US6] Create `engine/vg/remote/status.py`: a background thread runs the client
      every 30 s (3 s timeout), keeps the last result and its time, and parses the fields
      in research R4. Note the client version the parser was tested against
- [ ] T042 [US6] Add the `remote_access` `PipelineStage` to `LiveStore.health()`
      (`engine/vg/api/live.py:3835`). Render it in `web/src/pages/SystemHealth.tsx`
      **and** `mobile/src/pages/SystemHealth.tsx`. T040 passes. Then checklist step B11 on
      the pilot

---

## Phase 9: Polish and gates

- [ ] T043 Update `STATUS.md` with what remote access does and what the drills showed
- [ ] T044 `python -m pytest engine`: green, and the count did not drop
- [ ] T045 `npx.cmd tsc -b --force` in `web/` and `mobile/`, and `python tools/check_parity.py`:
      clean
- [ ] T046 `python -m pyflakes engine/vg engine/tools engine/tests`: clean
- [ ] T047 `.\dev.ps1 up -Clip`: LAN video unchanged, and remote limits applied for a caller
      outside `lan_networks` (for example a test address)
- [ ] T048 Every drill in `drills.md` (D1–D12, D1-PC) has a date and a pass, or an
      owner-approved waiver naming the risk

---

## Dependencies & execution order

- **016 and 018 gate** → everything except T001 and T002.
- T003 → T004–T007 → US2, US3, US6.
- **US2 before US1**: nothing is opened to the outside until the lockout, sign-up refusal
  and cookie are done.
- US1 → US3's drill (D10 needs remote access working).
- US4 → US5 (notifications need the service worker and an installed phone app).
- US6 any time after Phase 2 (`tls.names` comes with the gate).
- Phase 9 last.

## Parallel opportunities

- T004 and T007 alongside T005/T006.
- T008, T013, T014 and T015 (different test files).
- T022 with T027/T028 (engine work vs app assets).
- T031 and T040 test files.

## Implementation strategy

1. Setup + foundational.
2. **US2 then US1**: the minimum that is safe to switch on. Stop and run the US1 drills.
3. US3, so remote use does not swamp the factory's upload.
4. US4 + US5 together (they share the service worker).
5. US6.
6. Gates.
