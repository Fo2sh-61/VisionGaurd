# Implementation context: Pilot site readiness

**Written by `/speckit-plan` on 17 Oct 2026, against commit `2c85ebe` (branch
`remote-access`, which includes the falls work).**

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. Anchors drift — search for the symbol, not the line number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/tools/serve.py` | `uvicorn.run(` (~:101) | `host`, `port` from `cfg.api`; `reload`, `log_level`, `timeout_graceful_shutdown=5`; no TLS, no proxy args, no log handler | add `proxy_headers=True, forwarded_allow_ips="127.0.0.1"`; add the rotating handler under `VG_HOME`'s `logs\`; write `start-failure.txt` when startup raises |
| `engine/vg/config.py` | `def load(` (~:1322) | reads `ENGINE_DIR/engine.yaml` unless `path` is given; `_load_dotenv(ENGINE_DIR / ".env")` is fixed | when `VG_HOME` is set, read both from it; add the `tls` block parse next to `ApiConfig` (~:688) |
| `engine/vg/config.py` | `class HoursConfig` (~:637) | frozen; parses from, to, late_cutoff (must lie inside), term_from, term_to | reuse its validation for `PUT /settings/school`; do not duplicate it |
| `engine/vg/db.py` | `def connect(` (:48) | WAL, `busy_timeout` 5000, `foreign_keys` ON; every store opens its own connection to the one file | `migrations.run(path)` is called before any store opens |
| `engine/vg/api/app.py` | `_database(cfg)` (~:915 on main) | resolves `storage.database_url`; seven call sites inline the same replace() | call migrations once, early in startup, outside every subsystem's try/except (a failing step must stop the engine even without strict) |
| `engine/vg/api/app.py` | `def _reraise_if_strict` (~:1745) | 18 call sites, one per subsystem; none is a camera | unchanged; the service sets `VG_STRICT=1` |
| `engine/vg/api/app.py` | `@app.get("/users"` (~:3517) | only users route; `/users` is in `ADMIN_PREFIXES` | add `PATCH /users/{id}` beside it |
| `engine/vg/api/app.py` | `@app.delete("/people/{person_id}"` (~:3463) | admin; calls `LiveStore.remove_person` | point it at the new full erasure |
| `engine/vg/api/app.py` | `@app.get("/settings/school"` (~:3936) | read-only; `/settings` writes are admin by path | add the three PUTs and two GETs |
| `engine/vg/api/app.py` | `AlertService(` … `hours=cfg.hours` (~:971) | the hours are copied in once | pass a callable reading the live profile |
| `engine/vg/api/app.py` | `weapon_window(` uses at ~:2471, ~:2536 | `getattr(hours, "term_from", "")` | read the live profile |
| `engine/vg/api/live.py` | `hours = self.config.hours` (5 places: ~:2995, 4172, 4229, 4310, 5175) | frozen config read per call | replace with one `self.hours` getter backed by `SettingsStore` |
| `engine/vg/api/live.py` | `def remove_person` | audit first → `gallery.remove_person` → reload; leaves `sighting`, `anchor`, `appearance_sighting` | becomes the full erasure (plan J) |
| `engine/vg/api/live.py` | `def health(` | builds `pipeline: list[PipelineStage]`; copy `_alerts_stage` for a new row | add `cleanup`, `backup`, `certificate` rows |
| `engine/vg/auth/store.py` | `class UserStore` | `ROLES = ("admin", "it")`; has `set_disabled` (:214), `end_all_sessions` (:347), `purge_expired` (:355, never called); `user_for_token` refuses disabled (:332) | add `update_user` with the last-admin check inside `BEGIN IMMEDIATE` |
| `engine/vg/api/schemas.py` | `class User(Wire)` (~:1295 on main) | `id, name, email, role, last_active` | add `disabled: bool` |
| `engine/vg/alerts/service.py` | `_tick_retention` (~:597) | daily delete of `alert_delivery` at `log_retention_days` (90) from the sender loop (~:331) | remove; maintenance owns it at `retention.events_days` |
| `engine/vg/events/*.py` | `WeaponSceneStore.expire`, `VehicleStore.expire`, `FallSceneStore.expire` (falls.py:351) | mark the row expired, then unlink the file; rows are kept | maintenance calls them; add row deletion at the events period |
| `engine/vg/events/zones.py` | `CLIPS_KEPT_PER_CAMERA = 3` (:77) | count rule, no age rule | add an age expiry for clips |
| `engine/vg/events/appearance.py`, `counts.py` | `prune(keep_days=14)`, `prune(keep_days=90)` | never called | maintenance calls them |
| `web/src/pages/SystemHealth.tsx` | `<CamGrid` (:279) | no `detections` prop | pass `detections={false}` |
| `web/src/components/CamGrid.tsx` | `<CameraFrame` (:185) | has no `detections` prop at all | add it, copying `mobile/src/components/CamGrid.tsx` (:35 default, :191 pass-through) |
| `web/src/pages/Users.tsx` | the `linkbtn` "Edit" (:61) | no handler, hard-coded English | open the edit form |
| `mobile/src/pages/Users.tsx` | header comment (:20) | no Edit at all | add Edit |
| `web/src/pages/Settings.tsx` | school profile block (:116–192) | `editKey` toggles inputs that only call `setProfile` | add Save → `api.saveSchoolProfile`, "not saved" on failure |
| `mobile/src/pages/Settings.tsx` | `phone.settings.readOnly` | read-only | admins get the same edit form |
| `web/vite.config.ts`, `mobile/vite.config.ts` | `const API_PATHS` | identical except web has `/falls` | the Caddyfile proxies every first path segment of `app.routes` (test enforces it) |

## 2. Things to copy, not invent

- A health row → copy `LiveStore._alerts_stage`.
- A daily job in site time → copy `alerts/service.py::_tick_retention` (once per site-local
  day), then delete the original.
- Add-a-column → do **not** copy the three ad-hoc functions (`CameraStore._migrate`,
  `VehicleStore._add_missing_columns`, `UserStore._ensure_columns`); new changes are
  `migrations.py` steps.
- An admin tool that asks for a password → `engine/tools/create_user.py`.
- Building `.engine` files → `engine/tools/build_engines.py` (already checks the file on
  disk, because the cu13 wheel segfaults with exit code 0).
- A test store with real data → the `store` fixture in `test_groups.py`; close the gallery
  before the tempdir.
- PNG icons → extend `tools/make_icon.py`, which already renders `Logo.tsx`.

## 3. Traps

- **Do not write the regex's target words in any new file.** SC-007 is
  `git grep -niE "dev.?sign.?in"`. Say "developer sign-in" or "password-free sign-in".
  The file and flag names can be written with a wildcard, such as `dev_sign*.py` or
  `DevSign*Banner.tsx`.
- **Roles are `admin` and `it`.** The spec's "guard" is any non-admin account.
- **Page paths clash with API paths** (`/people`, `/weapons`, `/settings`, `/system`,
  `/users`, `/track`, `/vehicles`, `/intrusion`, `/lost-items`, `/attendance`, `/falls`;
  the phone also has `/cameras`). The front's `Accept: text/html` rule exists for this.
  Test both apps.
- **Direct links to API files**: `Weapons.tsx:220` (both apps, `clipUrl`, new tab) and
  `VehiclePasses.tsx:117` (snapshot). They must stay media addresses. Downloads use
  fetch + blob (`http.ts`), so they are unaffected.
- **Strict mode stops everything** when any enabled feature fails to start. The installer
  checks models first.
- **One database file**: the erasure transaction can span every store's tables through a
  single connection. Do not open per-store transactions for it.
- **Track recordings**: `clips_dir/track` and the path-leg jobs (`archive.py`, jobs held in
  memory). Find which files belong to a followed person before writing erasure (see
  section 5).
- **CRLF files**: `api/*.py`, `services/*.ts`, `types.ts`, `STATUS.md`. Write bytes, then run
  `git diff --stat`.
- **Audit durability** is spec 018's job. 016's audit-first calls go through `_log`, which
  is in memory until 018 lands.
- `requirements.txt` claims `alembic` is for migrations. Remove the line when
  `migrations.py` lands.

## 4. Baseline

- `python -m pytest engine` → **2006 passed, 14 skipped** at `2c85ebe` (5 min 8 s).
- New test files: `test_front.py`, `test_site_cert.py`, `test_migrations.py`,
  `test_users_edit.py`, `test_settings.py`, `test_maintenance.py`,
  `test_backup_restore.py`, `test_erasure.py`, plus `engine/tests/data/pre016.sql`.
- `engine/tests/test_dev_sign*.py` is deleted with the feature, so the count drops by its
  tests. Say so in the commit.

## 5. Still unknown

- Which on-disk files name a person: track legs and chunks, operator recordings
  (`app.py` ~:1047 writes to `clips_dir` itself). Read `archive.py` before writing erasure.
- What "person history" reads (`/people/history/:name`), and whether anything besides
  `sighting`, `anchor` and `appearance_sighting` stores per-person rows.
- Whether camera passwords live only in `.env` or also in the `camera` table (this decides
  whether a restore needs `.env` back first).
- Whether Caddy picks the site certificate for a connection with no server name (drill D1),
  or needs `default_sni`.
- Whether the WinSW exit code reaches the Services console (only the "stopped" state is
  promised).
