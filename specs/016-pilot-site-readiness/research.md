# Research: Pilot site readiness

Checked on 17 Oct 2026. ✔ = read in the source named, today.

## R1. The HTTPS front: Caddy

- **Decision**: Caddy 2.11 (latest stable 2.11.7, Oct 2026), Apache-2.0, one `caddy.exe`.
  Mohamed chose it on 17 Oct 2026.
- **Why**:
  - it speaks HTTP/2 with TLS by default (020 D.4);
  - for a client that is not a trusted proxy, Caddy ignores the incoming
    `X-Forwarded-For` "to prevent spoofing" ✔, so the engine only ever sees the real
    address (020 D.2). The Caddyfile also sets `header_up X-Forwarded-For {remote_host}`
    so the rule is visible;
  - responses with an unknown length (MJPEG) are flushed at once by default, and
    `flush_interval -1` turns buffering off completely ✔ (020 D.3);
  - Caddy's docs give two ways to run it as a Windows service: `sc.exe` or WinSW ✔.
- **Rejected**:
  - the engine serving both apps itself: one program fewer, but uvicorn has no HTTP/2, and
    020's address rules (section E) would have to be rewritten;
  - nginx for Windows: its own docs call it "a beta version", and only one worker does
    any work ✔;
  - IIS with ARR: several Windows features and add-ons to install, and it buffers by
    default.

## R2. The ports

- **Decision**: console `https://<address>/` (443), phone app `https://<address>:8443/`.
  The engine stays on `127.0.0.1:8000`, so only the front can reach it.
- **Why**:
  - Mohamed wants nobody typing addresses. Each address is typed once per device, to
    install the app, and after that it is an icon;
  - the console needs no port at all;
  - the two apps need two addresses because an installed app, its service worker and its
    phone-notification subscription each belong to one address (020 D.1).
- **Rejected**: the phone app at `https://<address>/phone`. Two installed apps on one
  address can catch each other's links, and 020's notifications assume separate addresses.

## R3. The site certificate: our own script

- **Decision**: `engine/tools/site_cert.py`, using `cryptography`. Mohamed chose it on
  17 Oct 2026.
- **Why**:
  - it is already installed (50.0.1 ✔, required by `google-auth`), so nothing new is
    downloaded; `requirements.txt` names it so it cannot vanish;
  - it can write the root key only to the owner's USB stick (020 C.3);
  - it can limit the root, with X.509 name constraints, to private addresses and
    `localhost`. A stolen root then cannot vouch for a public website.
- **Rejected**:
  - mkcert: one more download, no name constraints, and the root key stays in its own
    folder on the machine unless moved by hand;
  - openssl from Git for Windows: correct, but many fiddly flags for a non-developer.
- **Unknown until drill D2**: whether every device honours name constraints on a root a
  person installed. Windows Chrome and Edge use Chrome's verifier; Android Chrome is checked
  on a real phone. Fallback: `--no-limits`.

## R4. The service wrapper: WinSW

- **Decision**: WinSW 2.12.0 (latest stable ✔, MIT), one exe per service plus an XML file.
- **Why**:
  - the XML gives "restart after 10 s, three times, reset after an hour, then stay
    stopped" (P10-FR-005);
  - it gives log files that roll by size (P10-FR-006);
  - the same tool runs both the engine and Caddy, so the guide explains one thing once.
- **Rejected**:
  - NSSM: last release 2017, and sometimes flagged by antivirus;
  - pywin32 service code: fragile with a separate Python environment;
  - Task Scheduler "at startup": not a service, and no reliable restart after a crash.

## R5. Migrations: `PRAGMA user_version`

- **Decision**: one numbered step list for the one database file, run at start, one
  transaction per step.
- **Why**:
  - all 12 stores share `visionguard.db`, so one number describes the whole schema;
  - SQLite runs `CREATE`, `ALTER` and `DROP COLUMN` inside a transaction, so a failing
    step leaves the data exactly as it was (P3-FR-016).
- **Rejected**: Alembic. It is listed in `requirements.txt` but never used, and it expects
  SQLAlchemy models these stores do not have.

## R6. Backups: SQLite's online backup

- **Decision**:
  - `sqlite3.Connection.backup()` into a `.partial` folder;
  - then `PRAGMA integrity_check`;
  - then a rename. Only a renamed folder counts (P3-FR-012).
- **Why**: it copies a consistent database while the engine keeps writing (WAL mode).
  Copying the file could catch it half-written.
- **Not backed up**: clips (they expire anyway), `.env` (secrets) and `tls\` (re-made from
  the USB root). The owner keeps `.env` and the root key on the same USB stick.

## R7. Telling a page load from an API call

- **Fact**: both apps use `BrowserRouter`. About 10 page paths are also API paths. The
  apps' `fetch` calls send no `Accept` header, so the browser default is `*/*`. A page load
  sends `Accept: text/html,…`. Images send `image/…`.
- **Decision**: in the front, `Accept` containing `text/html` means "page". The exceptions
  are media addresses, which are opened directly as links: `/clip`, `/snapshot`, `/stream`,
  `/path/legs/…`, `/docs`, `/redoc`, `/openapi.json`.
- **Rejected**:
  - `Sec-Fetch-Mode: navigate`: it is the same signal but not sent by older browsers;
  - an `/api` prefix: it changes the contract for both apps and every test.
