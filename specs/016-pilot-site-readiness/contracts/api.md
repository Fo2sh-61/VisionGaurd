# Contracts: Pilot site readiness

Wire rules as everywhere: camelCase out, `extra="forbid"`, `Instant` via `_instant()`.
Every write calls `_log` before it changes anything. "Admin" means the path is admin-only
in `auth/deps.py`. The two roles are `admin` and `it`; the spec's "guard" is any account
that is not `admin`.

## The front (Caddy)

| Address | Serves |
|---|---|
| `https://<address>/` (443) | console: `web/dist` |
| `https://<address>:8443/` | phone app: `mobile/dist` |
| `http://…` on any port | nothing (no listener on 80; plain HTTP to 443/8443 is refused) |
| `127.0.0.1:8000` | the engine, plain HTTP, reachable only from the workstation |

Per request, the first rule that matches wins:
1. a page load: `Accept` contains `text/html` and the path is not a media address → `index.html`, `Cache-Control: no-cache`;
2. a proxied path → engine, `X-Forwarded-For` = the client's address, no buffering;
3. a file from the build. `/assets/*` is cached for a year; `manifest.webmanifest` and `sw.js` get `no-cache`;
4. anything else → `index.html`.

## Accounts

### `PATCH /users/{id}` (admin)

Body (any subset): `{ "name": str, "role": "admin" | "it", "disabled": bool }`

| Answer | When |
|---|---|
| 200 `User` | saved; disabling also ends that user's sessions |
| 404 | no such account |
| 409 `{detail}` | it would leave no active administrator |
| 422 | empty name, unknown role |

`User` gains `disabled: bool`. `GET /users` lists disabled accounts too.

## Settings

| Route | Who | Body / answer |
|---|---|---|
| `GET /settings/school` | anyone signed in | `SchoolProfile`, unchanged shape; now read from `site_setting` |
| `PUT /settings/school` | admin | `{name, hoursFrom, hoursTo, lateCutoff, termFrom, termTo}` → 200 `SchoolProfile`; 422 with a plain reason |
| `GET /settings/retention` | admin | `{clipsDays, eventsDays, sightingsDays}` |
| `PUT /settings/retention` | admin | same body → 200; 422 outside 1–3650 |
| `GET /settings/backup` | admin | `{folder: str \| null}` |
| `PUT /settings/backup` | admin | `{folder}` → 200; 422 if the folder does not exist or is inside the data folder |

## People

`DELETE /people/{id}` (admin, unchanged address, 204) now erases everything about the
person (plan J). It returns 409 `{detail}` while an earlier erasure of the same id is
unfinished, and 404 if the person is unknown.

## System Health

`GET /system/health` stays 200 and gains three `pipeline` rows:

| `key` | Healthy | Warning / failure |
|---|---|---|
| `cleanup` | last run finished, within 26 h | "not run yet"; last run incomplete (reason); older than 26 h |
| `backup` | last good backup within 36 h | no folder set; "never"; older than 36 h; last failure's reason |
| `certificate` | valid more than 30 days | expires within 30 days; expired; file missing; "not set up" on a development machine |

## Tools (command line)

| Command | Does |
|---|---|
| `site_cert.py root --out <usb>` | makes the root (public `.crt` + private `.key`) on the USB stick only |
| `site_cert.py site --root <usb>` | makes `site.crt` and `site.key` for `tls.names` in `tls.cert_dir` |
| `backup.py now` | one backup to the saved folder, the same as the nightly one |
| `backup.py restore <folder>` | refuses while the service runs; restores the database and `engine.yaml` |
| `deploy/install.ps1 -Models <folder>` | the install (plan D) |
| `deploy/update.ps1 <kit>` / `-Back` | update, and the way back |
