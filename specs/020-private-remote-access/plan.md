# Implementation Plan: Private remote access

**Branch**: `remote-access` | **Date**: 17 Oct 2026 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), [research.md](research.md), and a read of the code at
`fb11c50` (17 Oct 2026). Where a document disagreed with the code, the code is reported.

## Summary

Each factory gets its own **NetBird Cloud Free** account: 5 users and 100 machines. The docs
show no card step and do not exclude business use; the owner confirms both in writing
before the pilot. The workstation and each enrolled laptop or phone run the NetBird client.
They talk over encrypted WireGuard tunnels, directly when they can and through a relay that
cannot read the traffic when they cannot. The workstation's firewall and one NetBird policy
let enrolled devices reach only the console's HTTPS ports. People type the workstation's
NetBird **address**, never a name. On the LAN nothing changes: office PCs use the fixed LAN
address.

On the VisionGuard side the work is small and mostly in the engine:
- treat any request from outside the factory network as remote, and slow its video down;
- refuse self sign-up from outside;
- lock accounts after repeated wrong passwords;
- mark the cookie secure;
- record the real address on sign-in audit entries;
- show the VPN state on System Health;
- make both apps installable and honest when offline;
- add phone notifications as a second alert channel next to email.

Everything that makes HTTPS, the Windows service and app serving work is spec 016's job and
is listed below as a prerequisite.

## What exists today (read from the code, 17 Oct 2026)

**Spec 016 is a draft only.** Its `plan.md` is the empty template and it has no `tasks.md`.

| 016 item | State | Evidence |
|---|---|---|
| Windows service, restart after power cut | Not built | Starts only from `dev.ps1` / `launch.ps1` (a job object that dies with the window) |
| HTTPS, site certificate | Not built | `uvicorn.run` in `engine/tools/serve.py:101` has no TLS options; nothing makes a certificate; `config.py` has no `tls` block |
| Workstation serves the apps | Not built | Both apps run only on Vite dev servers (5173 / 5174, localhost); no static mount in the engine |
| Engine on 127.0.0.1 | **Yes** | `engine/engine.yaml` `api.host: 127.0.0.1`; `config.py:689` |
| Developer sign-in removed | Not done | `git grep -niE "dev.?sign.?in"` → 97 lines in 30 files |
| Account disable, role change | Not built | `AuthStore.set_disabled` exists (`auth/store.py:214`) but no route calls it; `app.py` has only `GET /users`; the wire `User` (`schemas.py:1346`) has no disabled or locked field |
| Backups, erasure, migrations, own venv, rotating logs, strict default, on-site guide | Not built | — |
| School profile save, account edit | Not built | `Settings.tsx`, `Users.tsx` Edit buttons save nothing |

**Spec 018 (persistent audit) is a draft only.** The audit lives in memory
(`api/store.py:287`, `_log` at `store.py:1509`), is lost on restart, and has no address
field (`schemas.py` `AuditEntry`: id, at, actor, action, subject, detail). Sign-ins are not
audited (`app.py:1978` only writes a log line).

**Video.**
- Grid tiles poll `GET /cameras/{id}/snapshot?width=&fps=` (`app.py:2113`). Width rounds up
  to 320/480/640/960/1280 (`app.py:220`), quality 70 (`app.py:224`). Clients ask up to 15
  pictures a second per tile, sharing 120 a second per screen (`frame.ts`). Each request
  ends, so tiles hold no connection open.
- A failed tile image is shown as a camera fault: `onError: () => setImageFailed(true)`
  (`CameraFrame.tsx:559`).
- The enlarged view is MJPEG, `GET /cameras/{id}/stream` (`app.py:2176`): 960 px, quality
  70, **every frame the camera makes, no rate cap** (`app.py:2223-2235`).
- One camera address per camera (`config.py:252` `source: str`); no sub-stream.
- No bytes-per-picture measurement exists in the repo.

**Sign-in.**
- The session is a token in a Bearer header or the `vg_session` cookie: HttpOnly,
  SameSite=Strict, **no Secure flag** (`app.py:1925-1931`). It lasts 12 hours from sign-in
  (`auth/store.py:54`).
- Every route except `/healthz`, `/auth/login` and `/auth/register` needs a session
  (`auth/deps.py:54-62`), so every stream, snapshot and clip already requires one.
- **No lockout and no rate limit on sign-in** (`app.py:1957-1983`).
- Sign-in matches the email after `strip()`, case-insensitively (`auth/store.py:240`,
  `COLLATE NOCASE`).
- **Open self sign-up** creates a read-only `it` account (`auth/store.py:49`), limited to 5
  per hour per address (`app.py:2016`).
- No code sets forwarded-address trust: `uvicorn.run` (`serve.py:101`) leaves
  `forwarded_allow_ips` at its default, which an environment variable can widen.
- The dev proxy forwards a fixed list of paths (`web/vite.config.ts:31` `API_PATHS`, and
  the same in `mobile/vite.config.ts`).

**Installable apps.** Neither app has a manifest, a service worker, PNG icons or a
`theme-color`. The only icons are `.ico` files for desktop shortcuts, made by
`tools/make_icon.py` from `web/src/components/Logo.tsx`. Both apps load fonts from Google.

**Two apps, one set of shared files.** `tools/check_parity.py` keeps only `types.ts`,
`services/*.ts` (api, wire, http, format, frame, content, notes, ask) and `i18n/*` identical
in both apps. Pages and components (`CameraFrame.tsx`, `Users.tsx`, `SystemHealth.tsx`,
`AlertSettings.tsx`, `Settings.tsx`, `Login.tsx`) are separate copies and already differ, so
every UI task names both and is checked in both.

**Health.** `SystemHealth` (`schemas.py:919`) lists `pipeline: list[PipelineStage]` rows
(`schemas.py:771`: key, name, detail, healthy, severity, restartable), built in
`LiveStore.health()` (`live.py:3835`).

**Alerts.**
- Email through Gmail is the only outbound channel: `CHANNELS = ("email",)`
  (`alerts/events.py:33`). Spec 013's text still names WhatsApp and SMS; the code removed
  them on 11 Sep 2026.
- The channel is also fixed in `AlertChannel = Literal["email"]` (`schemas.py:1373`),
  `AlertRule` and `AlertRuleUpdate` (`schemas.py:1383, 1400`), `normalise_destination`
  (`alerts/store.py:123`), and `REQUIRED_ENV` / `for_channel` (`alerts/providers.py:39,
  151`).
- Messages hold only `ALLOWED_FACTS` (`alerts/events.py:40`). The knife template says
  "Possible knife … not yet confirmed by a person" (`alerts/catalogue.py`).
- Recipients are rows of channel + address, managed only by administrators under
  `/settings/alerts/recipients` (enable, remove, test send; `app.py:3973-3999`).
- The alerts store has **no add-column step**. Its only schema change drops columns
  (`alerts/store.py:221-233`), and the default rules are inserted with a fixed column list
  (`store.py:216`).

**Remote access.** Nothing in the repo mentions a VPN, a tunnel, or remote access.

## Data flow (end to end)

| Flow | Path |
|---|---|
| Remote viewing | camera → workstation decode (unchanged) → snapshot / stream route: `is_remote` decides the limits → HTTPS front → NetBird tunnel → phone or laptop app → the operator sees a paced tile or a reduced live view, or a clip in full |
| Remote sign-in | app → front (real address in `X-Forwarded-For`) → `login`: lockout check → session + audit entry with the address → app |
| Alert to a phone | detection → existing alert event (013) → push rule and enabled phone recipient → web push sender → Google's push service → phone notification → tap → app opens the event over the tunnel → operator acts (e.g. confirms the knife) |
| Remote status | NetBird client → background reader → `remote_access` pipeline row → System Health on both apps |

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React + Vite (web/, mobile/)

**Primary Dependencies**: FastAPI, uvicorn (existing). **New: `pywebpush`** (MPL-2.0, pulls
in `py-vapid`, uses the existing `cryptography`) for phone notifications, needing Mohamed's
approval (T002). The NetBird client (BSD-3) is installed by the owner on devices, not by
the code.

**Storage**: the existing SQLite stores. New:
- a sign-in lock table in the auth store;
- an `alert_rule.push` column and a `push_device` table in the alerts store.

No audit schema change: the address goes into the existing `detail` text.

**Testing**: pytest (engine), `npx.cmd tsc -b --force` (both apps), pyflakes,
`tools/check_parity.py`; drills on real devices for what only a phone in a hand can prove.

**Target Platform**: Windows 11 workstation per site; Windows 10/11 laptops with Chrome or
Edge; Android phones with Chrome.

**Project Type**: web service + two web apps.

**Performance Goals**: one remote live view ≤ 3 Mbit/s, a page of twelve remote tiles ≤ 2
Mbit/s (SC-106, raised 20 Oct 2026); remote live view ≤ 1.5 s behind, remote tile ≤ 1.5 s
old (SC-111);
notification on a locked phone ≤ 30 s (SC-107).

**Constraints**: $0; no card; nothing stored off site; LAN-address behaviour unchanged.

**Scale/Scope**: 1–5 people and 2–10 devices per factory; 1–3 factories; one account each.

## Constitution Check

| Principle / rule | How this plan keeps it |
|---|---|
| I. Real-time camera | LAN address untouched. Remote tiles say "every 0.5 s", never LIVE, and show their last picture's time when a refresh fails. The remote live view is current frames at a lower rate, marked "reduced". Frames are skipped, never queued |
| II. Feature isolation | No feature worker changes. Remote pacing is in the two frame routes only |
| III. Truthful data | Remote status shows when it was checked. The installed app shows a plain "cannot reach the site" page that does not guess why, never cached data. Failed notifications are logged. A notification says "Possible knife" until a person confirms |
| IV. Security, privacy | Enrolled device + real password (sign-up refused from outside) + lockout; Secure cookie; real client address only; media routes keep requiring a session, proved by a test over every route; notifications carry kind, camera and time only, are end-to-end encrypted, go only to known push services, and start switched off per phone |
| Rule 6, fractions | No geometry crosses the wire in this feature |
| Rule 7, degradation is payload | Remote status is a System Health pipeline row; a missing or unreadable client still gives a 200 |
| Rule 8, failures in the UI | Remote status and notification failures are on screen, not only in the log |
| Rule 9, no feature needs another | Remote access needs no feature switched on; notifications follow 013's rules |
| Rule 10, weapons wait for a human | Push titles say "Possible knife" until confirmed |
| Rule 11, audit first | Lock, unlock and refused-sign-up entries are written before the response |
| Owner supplies models | No model involved |

**Passes.** Two owner-accepted risks are recorded in the spec: self sign-up on the factory
network, and no sign-in code.

## Design

### A. The private network (owner set-up, no code)

1. One NetBird account per factory. The owner signs in with a dedicated Google account for
   that factory (e.g. `vg.<factory>@gmail.com`) with 2-Step Verification on. The owner is
   the only dashboard user.
2. Groups: `workstation` (one device) and `operators` (laptops and phones).
3. Add one policy, `operators` → `workstation`, TCP, the console ports from section D, one
   direction. **Then** delete the policy named **Default**. Doing it in that order matters:
   deleting Default first stops all traffic (research R4). Phones then cannot reach each
   other or any other port on the workstation (P10-FR-106).
4. Enrolment: the owner makes a **one-off setup key that expires in 1 day**, named after the
   person and device, auto-group `operators` (or `workstation`). The device joins with it
   once, **with the key only, never through the sign-in page**. Devices that join through
   Google sign-in expire after 24 hours by default; key-joined devices never do (research
   R1), so the workstation never drops off (P10-FR-104).
5. After joining, the owner renames the device in the dashboard (`workstation`,
   `operator-01`, …) and deletes any unused key.
6. Removing a device: delete it in the dashboard (P10-FR-108). Its key was one-off and has
   expired. How fast the tunnel drops is drill D7.
7. Two things the owner never does: delete the **workstation's** device entry, or change the
   account's address range. Either would change the workstation's private address (research
   R5).
8. NetBird has no new-device approval on Free, and its activity log may not be on Free
   (research R1). So the owner keeps his own device list **outside the project**, from the
   blank template in the checklist (who, which device, its NetBird name, date joined, date
   removed).
9. A person who works at two factories joins each factory's account and switches the NetBird
   app between them. Only one factory is reachable at a time. How the client switches
   accounts is checked in T020.

### B. The workstation (owner set-up with a script, small code)

- **Fixed LAN address**: a DHCP reservation on the factory router, or a fixed address on the
  workstation. Owner step.
- **NetBird service**: silent install, then `netbird up --setup-key <key>` from a new
  administrator PowerShell window. The background service runs separately from the NetBird
  window. That it starts at boot with nobody signed in is checked in drill D5 (research R4).
- **Firewall**: a script `tools/remote-firewall.ps1` (new, run once as administrator).
  - For each console port it creates two inbound rules, both `-Profile Any`:
    - one allowing TCP from `LocalSubnet`;
    - one allowing TCP from `100.64.0.0/10`, limited with `-InterfaceAlias` to the NetBird
      adapter. The script finds the adapter by its 100.64 address and prints its name.
    - Microsoft documents both address forms but not one list mixing them, and which
      network profile Windows gives the NetBird adapter is undocumented (research R4).
  - It lists, and with `-Apply` disables, inbound allow rules that open the console ports or
    the front's or Python's programs to any address. Windows made those itself when the
    program first listened.
  - Port numbers are arguments with section D's defaults. Port 8000 is never opened: the
    engine stays on 127.0.0.1.
  - Without `-Apply` it only prints what it would do. `-Undo` removes its own rules and
    re-enables what it disabled. It is safe to run twice.
- **Power**: "Restore on AC power loss" (names vary) in the BIOS, so the workstation boots
  after a power cut by itself. Owner step.

### C. The address people type, and the certificate (spec 016's certificate, one more entry)

**People type the workstation's NetBird address**, e.g. `https://100.81.4.7`, never a
`*.netbird.cloud` name. On Windows and Android those names do not resolve unless the
account also sets DNS servers, and on Android that only works with the phone's Private DNS
switched off (research R5). An address needs no DNS and no phone setting.

Spec 016 makes the site certificate. This spec needs, and hands to 016's plan (T001):
1. The certificate's list of names and addresses is configuration (`tls.names`), not code,
   and includes the LAN address and the NetBird address (P10-FR-107).
2. Devices trust a **root** certificate that never changes. The site certificate it signs is
   re-made when an address changes. Only the root's public `.crt` file is ever copied to a
   device.
3. The root's private key does not stay on the workstation after it has signed the site
   certificate (kept offline by the owner). Where the tools allow, the root is limited to
   the site's own addresses. A stolen workstation or backup must not let anyone make
   certificates every enrolled device would trust.

If the NetBird address ever changes (A.7), the owner adds the new address to `tls.names`
and re-makes the site certificate. Devices keep trusting the root; only their shortcuts
change. System Health warns when the current NetBird address is not in `tls.names` (J).

### D. What spec 016's HTTPS front must do for remote access

These go into spec 016's plan as requirements from this spec (T001):

1. Serve the two built apps at **two addresses**: the console on one port and the phone app
   on another, e.g. `https://<address>/` and `https://<address>:8443/`. 016 picks the
   numbers. Each app needs its own address because installed apps, service workers and
   notification subscriptions belong to one address each. The session cookie is shared
   across ports on the same host, which is fine.
2. Proxy to `127.0.0.1:8000`, including the new `/connection` and `/push` paths, and
   **replace** (not append) `X-Forwarded-For` with the real client address.
3. Pass MJPEG through without buffering.
4. Speak HTTP/2 to browsers if the chosen front can. Over HTTP/1.1 a page commonly gets 6
   connections per host. Two remote live views plus tile and overlay polls come close.
5. Send `Cache-Control: no-cache` for `index.html`, `manifest.webmanifest` and `sw.js`, so an
   installed app never runs yesterday's code. Hashed assets may be cached.
6. Run as a Windows service like the engine.

### E. Telling a remote request apart (engine)

- New configuration block, seeded from `engine.yaml`:

  ```yaml
  remote:
    lan_networks: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128"]
    tile_interval_s: 0.5  # 2 until 20 Oct 2026, raised by the owner (too slow to follow)
    tile_width: 320       # added 20 Oct 2026 after T025's measurement
    live_width: 720       # 480 until 20 Oct 2026, same reason
    live_fps: 10          # 5 until 20 Oct 2026, same reason
    live_views: 2
  ```

  It is validated in `config.py` like every other block, and the defaults hold if it is
  absent.
- `is_remote(request)` in a new `engine/vg/api/remote.py`. A request is **local only when**
  its address is inside `lan_networks`. Anything else is remote: the NetBird range, IPv6, a
  second adapter, or no readable address. This fails safe: a mistake costs video quality,
  never exposure.
- A factory whose own network uses addresses outside the defaults sets `lan_networks` at
  install. Until then its office PCs get remote limits and cannot self-sign-up, which is
  visible and safe.
- **The real address**:
  - `serve.py` sets `forwarded_allow_ips="127.0.0.1"` explicitly, so no environment
    variable can widen it.
  - The front replaces `X-Forwarded-For` (D.2).
  - Drill D12 sends a forged header from the LAN and from a phone and checks that the audit
    and the limits use the true address.
- `GET /connection` (new, any signed-in user) returns
  `{remote, tileIntervalSeconds, liveWidth, liveFps, liveViews, liveViewsOpen}` as a `Wire`
  type. Both apps read it after sign-in and again when a stream is refused. `/connection`
  and `/push` are added to `API_PATHS` in both Vite configs.

### F. Remote video limits (engine + both apps)

**Snapshot route** (`app.py:2113`):
- When remote, the width is capped at `tile_width` and the `fps` hint at 1/`tile_interval_s`, so
  decode rates do not rise for a remote viewer.
- Pacing per (session, camera, width): a request that comes sooner than 0.8 ×
  `tile_interval_s` after the last one **waits until its turn**, then gets a new picture.
  So the screen never sees an error, and one that ignores the pace still gets at most one
  picture per interval.
- More than 4 waiting requests on one session gets 429, so a runaway screen cannot tie up
  the server's threads.

**Stream route** (`app.py:2176`):
- When remote, frames are encoded at `live_width`. The loop sends at most `live_fps` frames
  a second, skipping frames in between, never queueing them.
- Each account's open remote streams are counted in the app's state. Each slot records when
  it last sent a frame. A slot that has sent nothing for 15 seconds is freed, which covers a
  phone that lost signal without closing (P10-FR-115). The count drops in a `finally`.
- Opening one past `live_views` gets 429 and the reason.

**Both apps** (`CameraFrame.tsx` per app, separate copies; `frame.ts` shared):
- When `/connection` says remote, tiles ask every `tileIntervalSeconds`.
- The tile's freshness label reads "every 0.5 s" instead of LIVE.
- When a refresh fails, the label shows the last picture's time ("No picture since 14:05")
  and, once nothing has answered for 5 s, the page shows "Cannot reach the site"
  (P10-FR-125). A slowed response is never a fault, and neither is one lost request: through
  NetBird's relay on mobile data a few are lost, and on 20 Oct 2026 the banner flashed on
  and off while the page worked.
- The enlarged view shows "Live, reduced for remote".
- A refused stream (the `<img>` fails while `liveViewsOpen` ≥ `liveViews`) shows "Close
  another live view first".
- All words go into `i18n/*` (shared) in English and draft Arabic; `format.ts` builds the
  sentences.

**Clips and event snapshots**: untouched (P10-FR-117).

**Bandwidth, measured 20 Oct 2026** (task T025, `engine/tools/measure_remote_video.py`, 60 s
each on the recorded clip, the walk-through camera at 5 pictures a second; the LAN row is still
the earlier estimate):

| View | Size, quality | Rate | Measured |
|---|---|---|---|
| LAN live view today | 960 px, q70, ~60–90 KB | camera rate, 15–25/s | ~7–18 Mbit/s (estimate) |
| Remote live view | 480 px, q70 | 5/s | **0.61 Mbit/s** |
| Remote tile | 320 px, q70, ~9 KB | 1 per 2 s | **0.036 Mbit/s each; 12 tiles 0.43 Mbit/s** |

A tile asks for a picture the size it is drawn, and in the browser that was 480 px (~16 KB,
about 0.064 Mbit/s; twelve would be ~0.77 Mbit/s, over SC-106's 0.5). So remote tiles are
capped by their own setting, `remote.tile_width: 320`, not by the live view's 480.

So one person away from site with two live views and a page of twelve tiles needed about
1.7 Mbit/s of the factory's upload. A camera faster than the clip's 5 a second does not change
the live view (it is capped at 5 a second) and changes a tile only by how busy the picture is.

**Raised 20 Oct 2026** (owner, on the first remote phone: one picture every 2 s was too slow
to follow anything):

| View | Size, quality | Rate | Expected |
|---|---|---|---|
| Remote live view | 720 px, q70, ~30 KB | 10/s | **~2.5 Mbit/s (estimate)**: the 480 px picture measured above, 2.25 times the pixels, twice the rate |
| Remote tile | 320 px, q70, ~9 KB | 2/s | **0.14 Mbit/s each; 12 tiles 1.7 Mbit/s**: the measured picture at four times the rate |

One person away with two live views and twelve tiles now needs about 6.7 Mbit/s of the
factory's upload. The recorded clip runs at 5 pictures a second, so it cannot show a live
view at 10: drill D10 measures it on a real camera and phone, and its figure replaces the
estimate.

**Workstation cost, measured**: two viewers with two remote live views each added nothing
measurable to the engine's processor use (−0.03 cores, noise, on top of its own 0.84 cores
kept busy flat out on the clip). The pictures are skipped, not encoded, between the five a
second, and decoding the cameras is unchanged.

**Latency budget** (SC-111, constitution I):
- The remote live view is at most 1.5 s behind the camera over mobile data.
- A remote tile's picture is at most 1.5 s old while labelled "every 0.5 s".
- The pacer drops frames, never queues them, so delay cannot build up.
- Measured in drill D10 by pointing a camera at a running clock and comparing the phone
  with the clock.

**Accessibility**: every new state is a text label (never colour alone), through the existing
`Badge` and `DataNotice` components, in English and Arabic. Notifications are plain text.

**Sub-streams: not used.** The workstation already decodes each camera once and re-encodes
small pictures for browsers. A second stream per camera would add decode work at the
workstation and save nothing on the remote link.

### G. Sign-up and sign-in (engine)

**Sign-up from outside**: `register` returns 403 "Sign up on the factory network" when
`is_remote(request)`. This is audited before the answer (P10-FR-124). Nothing else about
sign-up changes.

**Lockout**:
- New table in the auth store: `signin_lock(email_key, failures, first_failure_at,
  locked_until, last_address)`.
  - `email_key` is the typed email made exactly the way sign-in matches it: `strip()`, then
    lower-case (ASCII, as `COLLATE NOCASE` does), cut to 254 characters.
  - It is kept whether or not the account exists, so "locked" never tells an attacker which
    addresses are real.
- On a failed sign-in: count it within a 15-minute window. At 5, set `locked_until = now +
  15 min` and audit `signin.locked` (actor: the email key; detail: the address of the
  attempt) before answering.
- While locked, every attempt gets 423 "This account is locked until 14:20", even with the
  right password. Attempts while locked are not counted and do not extend the lock. A
  success clears the row.
- **Per address**: more than 20 failures in 15 minutes from one address, across any emails,
  makes that address wait 15 minutes (429). It is kept in memory and resets on restart. This
  slows password spraying and one person locking out many accounts.
- **Clean-up**: rows whose window and lock have both passed are deleted on each write.
- **Unlock**:
  - `POST /users/{id}/unlock` lets an administrator lift a lock. `/users` is already
    admin-only by path (`auth/deps.py:83`). It is audited before the write.
  - `engine/tools/unlock_account.py <email>`, run on the workstation itself, lets the owner
    lift a lock when no administrator can sign in.
  - The wire `User` gains `locked_until: Instant | None`, filled by `LiveStore.users()`, so
    both Users pages can show "Locked until 14:20" and an Unlock button.
- The numbers are configuration: `auth.lockout_attempts: 5`, `auth.lockout_window_min: 15`,
  `auth.lockout_min: 15`, `auth.address_attempts: 20`.

### H. Session cookie and media routes (engine)

- `_issue_session` sets `secure=True` when the site runs HTTPS (016's `tls` setting). Dev
  over plain HTTP keeps working.
- A new test walks `app.routes`. For every GET route whose response is an image, a stream or
  a clip (`/cameras/*/snapshot`, `/cameras/*/stream`, `*/clip`, `*/snapshot`,
  `/path/legs/*/chunks/*`), it asserts 401 with no session. It also asserts that
  `PUBLIC_PATHS` is exactly `/healthz`, `/auth/login`, `/auth/register`.

### I. Address on audit entries (engine, after spec 018)

Sign-in, failed sign-in, lock, unlock and refused sign-up entries get, in `detail`, `from
100.81.4.7 (private network)` or `from 192.168.1.20 (factory network)`. The address is the
real one (E). No schema change.

### J. Remote status on System Health (engine + both apps)

- `engine/vg/remote/status.py` runs `netbird status --json` **on a background thread every
  30 seconds** (3-second timeout) and keeps the last result with its time. The row is then
  never more than about 35 seconds old, inside the spec's "within the last minute". `health()` only
  reads that result, so a slow or hung client never holds up a request.
- One `PipelineStage` row, key `remote_access`, built in `LiveStore.health()`:

  | Client state | Row shows |
  |---|---|
  | Not installed | "not set up" |
  | Installed but cannot be run or read (permission, no answer) | "not connected — cannot read the NetBird client: <reason>" |
  | Management not connected | "not connected" with the client's reason |
  | Otherwise | "connected", with the workstation's NetBird address |

  - Every state also shows "checked 14:05:12".
  - When connected but the address is not in `tls.names`, the row warns that remote devices
    will see a certificate warning.
- System Health stays a 200 in every case. The JSON fields come from the client's source
  (research R4) and are pinned to the tested client version. If `--json` is missing, the
  plain output is parsed.

### K. Installable apps (both apps)

- `public/manifest.webmanifest` in `web/` and `mobile/`:
  - `name` "VisionGuard" / "VisionGuard Mobile", and `short_name`;
  - `start_url` "/", `scope` "/" (each app has its own address, D.1);
  - `display` "standalone", `theme_color`, `background_color`;
  - icons 192, 512 and a 512 maskable.
- `index.html` links the manifest and sets `theme-color`.
- `tools/make_icon.py` also writes the PNGs from `Logo.tsx`, so the icons stay one source.
- A small `public/sw.js` in each app:
  - It caches **nothing** except one plain page shown when a page load fails: "VisionGuard
    cannot be reached right now. Away from the factory, check that NetBird is connected. In
    the factory, check the network." It does not guess the cause (P10-FR-112).
  - Its `fetch` handler only passes requests through and falls back to that page. API calls
    are never cached. Chrome's menu "Install app" no longer needs a service worker, but its
    automatic install prompt still wants a `fetch` handler (research R5).
  - The mobile copy also handles notifications (L).
- Whether Chrome on Android installs a full app or a home-screen shortcut for a private-CA,
  VPN-only address is checked on a real phone (research R5, drill D1). Both open the same
  way.

### L. Phone notifications (engine + mobile)

- **Standard Web Push** with VAPID keys made on the workstation at install time and kept in
  `.env`: `VG_VAPID_PUBLIC_KEY`, `VG_VAPID_PRIVATE_KEY`, and `VG_VAPID_SUBJECT` (the factory's
  own Google address, never a personal one). They are never in the repo and are included in
  016's backup. No Google or Firebase account is needed. The message is encrypted for that
  phone (research R7).
- **Channel**: `push` joins `email` in every place the channel is fixed today:
  - `CHANNELS` in `alerts/events.py`;
  - `AlertChannel`, `AlertRule` and `AlertRuleUpdate` in `schemas.py`, plus both apps'
    `types.ts`;
  - `normalise_destination` in `alerts/store.py`;
  - `REQUIRED_ENV["push"]` and `for_channel("push")` in `alerts/providers.py`.
- **Store** (`alerts/store.py`):
  - an `ADD COLUMN push INTEGER NOT NULL DEFAULT 0` step for existing databases. The store
    has none today, so it is written here, modelled on `auth/store.py:155`;
  - `DEFAULT_RULES`, `RULE_FLAGS` and the rule insert updated;
  - a new table `push_device(id, user_id, label, endpoint, p256dh, auth, created_at,
    last_sent_at, last_error)`.
- **Recipients**:
  - Registering a phone creates its `push_device` row and an `alert_recipient` row (channel
    `push`, destination = the device id, name = person and device label) with **enabled =
    0**. Nothing is sent until an administrator switches it on in the recipient list, the
    same admin-only list (`/settings/alerts/recipients`) that already enables, removes and
    test-sends email recipients (P9-FR-105, -109).
  - Removing the recipient also deletes the device row.
  - The push sender receives the device id as its destination and looks up the keys.
- **Routes** for registering (any signed-in user, own devices only):
  - `GET /push/key`;
  - `POST /push/devices {endpoint, keys, label}`;
  - `DELETE /push/devices/{id}`;
  - `GET /push/devices`.
- **Push address check** (P9-FR-108): `POST /push/devices` accepts only an `https` endpoint
  whose host matches `push.allowed_hosts` in configuration. The default is
  `fcm.googleapis.com`, `*.push.services.mozilla.com`, `*.notify.windows.com` and
  `web.push.apple.com`. It never accepts an IP address, a private or loopback host, or
  anything else; the rest get 400. Without this, any signed-in user could make the
  workstation send requests into the factory network.
- **Accounts**: a disabled or deleted account's devices are deleted (in
  `AuthStore.set_disabled` and on delete, once 016 adds the routes). The sender also skips
  any device whose account is disabled, as a second guard.
- **Message** (P9-FR-102):
  - One fixed template per alert template.
    - The title says what is known: "Possible knife" for an open entry, "Knife confirmed"
      and "False alarm" for the two verdicts. The same pattern applies to the other kinds,
      following `alerts/catalogue.py`.
    - The body is camera and site time ("Gate 2 · 14:05"). The data carries the event's
      console path.
  - Only kind, camera name and time go in (`PUSH_FACTS`, narrower than `ALLOWED_FACTS`). A
    test fails if any other fact reaches a push body.
- **Mobile app**:
  - Settings → "Notifications on this phone" asks permission, subscribes and registers. It
    shows "Waiting for an administrator to switch this phone on" until enabled.
  - The service worker shows the notification. A tap opens the event path. If the site is
    unreachable, the offline page from K shows.
- **Failure**:
  - An expired subscription (404/410 from the push service) removes the device and logs
    `failed: device gone`.
  - No internet logs `failed: no internet`.
  - Retries follow 013's existing bounded policy.
- **Email**: unchanged and optional. A strict factory turns off email in the rules and uses
  push only (P9-FR-107).

### M. Owner checklist

[owner-checklist.md](owner-checklist.md): numbered steps with times, written for someone
who is not a network expert (P10-FR-123). Steps that need a screen this spec builds are
marked "after spec 020 is built".

## Test plan

**Automated** (pytest unless noted):

| Test | Proves |
|---|---|
| `test_remote.py` | local only inside `lan_networks`; NetBird, IPv6, unknown and missing addresses are remote; `serve.py` pins `forwarded_allow_ips`; `/connection` payload; sign-up refused from outside, allowed on the LAN, audited |
| `test_remote_video.py` | remote snapshot width cap; early requests wait rather than fail; > 4 waiting → 429; LAN unaffected; remote stream fps ≤ `live_fps`; third stream 429; slot freed by a client that vanishes; one event snapshot and clip unreduced for a remote caller |
| `test_signin_lock.py` | 5 failures lock; right password refused while locked; attempts while locked do not extend; padded and capitalised email share one count; unknown email locks the same way; window resets; per-address cap; expired rows deleted; unlock admin-only and audited; `unlock_account.py` works; lock audited before the answer with the address; `User.locked_until` filled |
| `test_media_auth.py` | every media route 401 without a session; `PUBLIC_PATHS` exact |
| `test_cookie.py` | Secure flag on when TLS is on, off in dev |
| `test_remote_status.py` | not set up / cannot read / not connected / connected from canned output; checked-at time; certificate warning; health never waits on the client; System Health 200 when the client is missing |
| `test_push.py` | push rule off by default; new phone recipient disabled until enabled; only allowed https hosts accepted (http, IP literal, 192.168.x, 127.0.0.1 refused); body holds kind/camera/time only; open knife titled "Possible knife"; disabled account gets nothing and its devices are deleted; removing the recipient deletes the device; 410 removes the device and logs; no internet logs; existing alerts database gains the `push` column |
| `npx.cmd tsc -b --force` in web/ and mobile/ | types clean |
| `python tools/check_parity.py` | shared files identical |
| `python -m pyflakes engine/vg engine/tools engine/tests` | clean |

**Drills on real devices.** They need the pilot workstation with 016 installed. Results go
into this spec directory as `drills.md`.

| Drill | Steps | Pass |
|---|---|---|
| D1 Phone outside | Phone on mobile data, Wi-Fi off, NetBird on; tap app; then switch NetBird off and open the app again | sign-in page ≤ 10 s, no warning (SC-101); with NetBird off, the plain offline page, no old page (scenario 10) |
| D1-PC Laptop outside | Enrolled laptop on a phone hotspot; open the app in Chrome, then Edge | console, no warning in either browser |
| D2 Not enrolled | Second phone without NetBird, mobile data; open the NetBird address and the factory's public address | no answer (SC-102) |
| D3 Office, no internet | Unplug the factory router's internet for 10 minutes; office laptop on the LAN address; walk past a camera | console works, event saved (SC-103) |
| D4 Internet back | At the end of D3, plug the internet back and start a timer | remote works ≤ 5 min, nobody touches the workstation (SC-104) |
| D5 Power cut | At a quiet time, after a backup: pull the workstation's power, restore | remote works ≤ 5 min of boot, nobody signs in; the NetBird address is unchanged (SC-104) |
| D6 Vendor unreachable | On the factory router block NetBird's management, signal and relay hosts for 15 min; meanwhile switch NetBird off and on on the phone | LAN console normal; System Health "not connected"; an already-open session keeps working; whether the phone reconnects is recorded |
| D7 Device removed | (a) Delete the phone in the dashboard and start a stopwatch. (b) Disable the person's account; from the factory Wi-Fi try the LAN address and wait for an alert | (a) cannot reach the workstation ≤ 2 min (SC-105); (b) refused, no notification (scenarios 20, 26) |
| D8 Lockout | 5 wrong passwords from the phone; then the right one; then unlock from another admin and with `unlock_account.py` | 6th refused even when right; both unlocks work (SC-109) |
| D9 Notification | Admin switches on push for knife and for this phone; phone locked, Chrome swiped away; trigger a knife on the recorded clip | notification ≤ 30 s, "Possible knife" + camera + time only; tap opens the entry (SC-107) |
| D10 Video | Phone remote: one live view 60 s, then the tile page 60 s, then a third live view; read bytes from the phone's data usage and T025's tool; point a camera at a running clock and compare the phone with the clock; then switch NetBird off for a minute | ≤ 3 / ≤ 2 Mbit/s for twelve tiles (SC-106); live view ≤ 1.5 s behind, tile ≤ 1.5 s old (SC-111); labels "every 0.5 s" and "Live, reduced for remote"; third refused with its message; on drop, tiles show "No picture since" and the page "Cannot reach the site" |
| D11 Nothing else reachable | From an enrolled phone try the workstation on another port (e.g. 8000, 3389), try another enrolled device's address, and try a second factory's workstation address | all refused (scenario 3, P10-FR-106, -109) |
| D12 Forged address | From a LAN laptop send a request with `X-Forwarded-For: 100.81.4.9`; from an enrolled phone send `X-Forwarded-For: 192.168.1.5`; then from the phone try self sign-up | audit shows the true addresses; limits follow the true address; sign-up refused (SC-110) |

## Risks (biggest first)

1. **NetBird changes or ends the Free plan, or says business use or one account per factory
   needs a paid plan.** Remote access stops; nothing on site does. Mitigation: ask NetBird in
   writing before the pilot (checklist A1). The same clients can point at a self-hosted
   NetBird server later.
2. **Spec 016 is mostly unbuilt.** There is no HTTPS, no service, no served apps and no
   account disable, so remote access cannot start until those land. Mitigation: sections C
   and D go into 016's plan (T001); 020's tasks are gated on them.
3. **The 5-user limit.** If key-joined devices count as users, 1–5 people with one or two
   devices each can pass 5. Mitigation: NetBird question 2 before any real device joins; if
   yes, the fallback is fewer devices per person or the owner's call on a paid plan.
4. **Phones and private certificates.** Android may install a shortcut rather than a full
   app for a private-CA address; some phones nag about a user-installed certificate.
   Mitigation: drill D1 on the actual pilot phones before promising anything.
5. **Factory upload speed is unknown.** A slow line makes even reduced video poor.
   Mitigation: the remote limits are configuration; snapshots and clips work on any line.
6. **Owner-accepted: self sign-up on the factory network and no sign-in code.** Anyone on
   the factory network can make a read-only account. A stolen, still-enrolled phone with a
   saved password reaches the console until the owner removes it. Mitigation: removal takes a
   few minutes, sessions last 12 hours, lockout stops guessing, sign-up is refused from
   outside.

## Fallbacks (in order)

1. **NetBird self-hosted**, same clients, own management server. NetBird's quickstart needs a
   Linux machine (1 CPU, 2 GB), a public domain name pointing at a public IP, and TCP 80,
   TCP 443 and UDP 3478 open (research R1). A domain and an always-on public machine are not
   $0 for most factories, so this needs the owner's say-so.
2. **Cloudflare Zero Trust Free** (WARP + cloudflared). Needs a card at sign-up (the owner
   must waive decision 2). Traffic passes through Cloudflare. With TLS decryption off, it
   cannot see the page contents, but it does see addresses, ports and timing (research R1).
3. **Oracle Always Free VM as a WireGuard relay.** Needs a card; Oracle may reclaim idle
   machines.

## Project Structure

### Documentation (this feature)

```text
specs/020-private-remote-access/
├── spec.md
├── plan.md              # this file
├── research.md          # candidates, decision table, sources
├── tasks.md
└── owner-checklist.md   # the owner's numbered steps
```

### Source Code (repository root)

```text
engine/vg/api/remote.py           # is_remote, limits, stream slots, /connection   (new)
engine/vg/remote/status.py        # reads the NetBird client in the background     (new)
engine/vg/api/app.py              # snapshot/stream pacing, sign-up refusal, lockout,
                                  #   unlock, cookie, /connection, /push routes
engine/vg/api/schemas.py          # Connection, User.locked_until, AlertChannel push
engine/vg/api/live.py             # remote_access pipeline row, users() locked_until
engine/vg/auth/store.py           # signin_lock table
engine/vg/alerts/events.py        # CHANNELS + "push", PUSH_FACTS
engine/vg/alerts/store.py         # push column step, push_device, normalise_destination
engine/vg/alerts/providers.py     # web push sender, REQUIRED_ENV["push"]
engine/vg/alerts/catalogue.py     # push titles per template
engine/vg/config.py, engine.yaml  # remote:, auth lockout numbers, push.allowed_hosts
engine/tools/serve.py             # forwarded_allow_ips pinned
engine/tools/unlock_account.py    # owner unlock at the workstation                (new)
engine/tools/measure_remote_video.py                                                (new)
engine/tests/test_remote.py, test_remote_video.py, test_signin_lock.py,
             test_media_auth.py, test_cookie.py, test_remote_status.py, test_push.py (new)
web/public/, mobile/public/       # manifest.webmanifest, icons, sw.js            (new)
web/vite.config.ts, mobile/vite.config.ts   # API_PATHS + /connection, /push
web/src/, mobile/src/             # types.ts, api.ts, frame.ts, format.ts, i18n (shared);
                                  #   CameraFrame, Users, Login, SystemHealth,
                                  #   AlertSettings, Settings (each app's own copy)
tools/remote-firewall.ps1         # one-time firewall rules                         (new)
tools/make_icon.py                # also writes 192/512 PNGs
```

`tls.names` belongs to spec 016's configuration; this spec only reads it.

**Structure Decision**: the existing layout. No new project, no new process.

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| `pywebpush` dependency | Web Push needs RFC 8291 encryption and VAPID signing | Writing the encryption by hand is riskier than a small, widely used library |
| Service worker in each app | Offline notice (P10-FR-112) and notification display (P9-FR-101) | Without one, an installed app shows the browser's error page and cannot receive pushes |
| Background thread for NetBird status | System Health must never wait on an external program | Running it inside the request would block every request while the client is slow |
