# Implementation context: Arabic console

**Written by `/speckit-plan` on 28 Aug 2026, against commit `988a140`.**

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. This is a snapshot; if it disagrees with the code, the
> code wins and this file is wrong. Anchors drift — search for the symbol, do
> not trust the line number.

---

## 1. Anchors — where each edit lands

### Engine

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `api/schemas.py` | `class Wire` | base type: snake_case in, camelCase out, `extra="forbid"`. `Fraction`/`Confidence` validated 0..1 | add `class Note(Wire): code: str; args: dict[str, str \| int \| float] = {}` |
| `api/schemas.py` | `class Account` (~1408) | `id, name, email, role, initials`. Docstring: "no permissions list — the console asks the server what it may do" | `+ language: Literal["en","ar"] = "en"` |
| `api/schemas.py` | `class SiteInfo` (~966) | `name, today, timezone, tz_offset_minutes, cameras_online, cameras_total, places, areas, clip_retention_days` | `+ digits: Literal["western","arabic"] = "western"` |
| `api/schemas.py` | `class Metric` (~279) | `key`, `label: str` (287), `unit: Literal['count','percent','seconds','ratio','text']` (289) | **delete `label`**. `unit` is an enum and is untouched |
| `api/schemas.py` | `class Box` (~155) | `x,y,w,h`, `label: str \| None` (162), `confidence`, `kind` — comment at 164 says kind "decides how the console colours it"; `"plate"` was added 27 Aug | `label` keeps the **name** meaning only; class wording moves to `kind` |
| `api/schemas.py` | `class Problem` (~990) | `detail: str \| None` (999) | → `Note \| None` |
| `api/schemas.py` | `class AuditEntry` (~957) | `actor, action, subject, detail: str \| None` (963) | unchanged — `action` is already a dotted token |
| `api/schemas.py` | the 19 classes in `data-model.md` §6 | prose `reason`/`detail`/`note`/`*_reason` | → `Note \| None` |
| `api/notes.py` | **new file** | — | the code registry + `note(code, **args) -> S.Note` |
| `api/app.py` | `WINDOW_DAYS` (48) | dict keyed `"Today"…"This school year"`, 5 entries | rekey to tokens |
| `api/app.py` | `WEAPON_WINDOWS` (61) | tuple of 7 labels. Comment at 56 explains why it is **separate** from `WINDOW_DAYS` and must stay so | rekey to tokens, keep separate |
| `api/app.py` | `weapon_window()` (72) | raises 422 at 85–89 with prose detail | detail → `window.unknown` note |
| `api/app.py` | `window_days()` (174) | raises 422 at 175–180, same shape | same |
| `api/app.py` | `get_breaches` (1986) | `window: Annotated[str, Query(description="Today \| Last 7 days \| Last 30 days")] = "Today"` | token default + `Literal` |
| `api/app.py` | `get_weapons` (2019) | `window: Annotated[str, Query()] = "Last 30 days"` | same |
| `api/app.py` | error details at 1482, 1606, 1615, 1646, 1654 | `HTTPException(detail="…")` | → note dicts |
| `api/app.py` | `/auth/login` 1591, `/auth/register` 1620, `/auth/logout` 1682 | the only auth routes; **no `PATCH /auth/me` exists** | add `POST /auth/language` |
| `api/live.py` | the 26 sites in `contracts/notes.md` | — | → `note(...)` |
| `api/store.py` | `class MockStore`, the 28 sites | shares the same schemas as `LiveStore` | → `note(...)`, `demo.` prefix where demo-only |
| `auth/store.py` | `CREATE TABLE IF NOT EXISTS app_user` (51) | `session` table follows at 62. `class User` at 84 with `is_admin` (94) and `initials` (98) properties; `create_user` 134, `users()` 168, `authenticate` 201, `user_for_token` 262 | `+ language TEXT NOT NULL DEFAULT 'en'`, `User.language`, `set_language()` |
| `auth/deps.py` | details at 195, 215 | permissions decided by **path** — `ADMIN_PREFIXES`, `ADMIN_WRITE_PREFIXES`, never a decorator | details → notes. **Do not read `language` here** |
| `ingest/archive.py` | reasons at 1019, 1038 | sweep estimate; `live.py:3178` passes `estimate.reason` straight through | → `note(...)` |

### Console

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `app/ThemeContext.tsx` | whole file, 25 lines | `STORAGE_KEY='vg.dark'` (10); `useState` initialiser reads `localStorage` then `matchMedia` (13–16); `useEffect` toggles a body class and writes `localStorage` (20–22) | **copy this shape** for `LanguageContext.tsx`, but persist to the account, not `localStorage` |
| `app/AuthContext.tsx` | `interface Account` (33) | `AuthValue` 41, `AuthProvider` 56, `signIn` 82, `register` 90, `signOut` 98, `useAuth` 117, `useAccount` 124 | `+ language` on the interface; `LanguageContext` reads it |
| `services/http.ts` | `class ApiError` (62) | `detail?: string` (67). At 144–149: `detail = problem?.detail ?? problem?.error`, and `if (typeof detail === 'string') message = detail`. Comment at 37 explains why the token is **not** in `localStorage` | accept an object detail, render via `notes.ts`, **keep the string branch** so a half-migrated engine degrades to English |
| `services/format.ts` | 558 lines, ~20 exports | `formatTime` 41, `siteClock` 56, `formatClock` 64, `formatEventTime` 84, `formatLongDate` 101, `formatShortDate` 112, `formatDuration` 119, `formatCount` 202, `formatPercent` 205, `formatMetric` 209, `attendanceLabel` 258, `attendanceStatusLine` 285, `formatSchedule` 317, `boxColor` 155, `matchLabel` 193. **Zero `Intl` usage.** Line 34 does the instant arithmetic: `new Date(new Date(instant.utc).getTime() + instant.tzOffsetMinutes * 60_000)` | add a language parameter; format through `Intl`. **Line 34 stays exactly as it is** |
| `services/content.ts` | 43 lines | `SUGGESTED_QUESTIONS`, `CAPABILITIES`. Header already says copy stays client-side so "a copy tweak or Arabic translation" needs no backend deploy | lists → keys |
| `components/CameraFrame.tsx` | 467 lines | picture rect at 244–249; box at 373 `left: \`${b.x}%\``; zone at 340; label offsets 351, 421; badges 443 (`left: s.insetX`) and 461 (`right: s.insetX`) | `dir="ltr"` on the picture container. Geometry stays physical |
| `pages/Settings.tsx` | 466 lines | `PageHeader` 169; Cards at 171, 254, 337, 400, 412; **Dark mode `Toggle` at 430** in the "how the console looks" card | language selector beside dark mode; translation-coverage card |
| `app/navigation.ts` | — | ~33 nav labels | → keys |
| `styles/app.css` | 809 lines | **10** physical direction properties, **0** logical. `.row` is a grid with `gridTemplateColumns` set inline; `.list-row` is a full-width button | 10 → logical |
| `types.ts`, `services/wire.ts` | — | `wire.ts` is 1079 lines | `+ Note`, `+ Language` |
| `i18n/*` | **new directory** | — | `keys.ts`, `en.ts`, `ar.ts`, `ar.draft.ts`, `index.ts` |
| `services/notes.ts` | **new file** | — | `Note` → sentence; unknown code → `note.unknown` |

### Mobile

`mobile/src/{types.ts, services/api.ts, services/mockData.ts, pages/PersonHistory.tsx, pages/ToolPage.tsx}` reference `reason`/`detail`. Fixtures
only. Make them compile against the new types and render the English fallback.
Do not localise.

---

## 2. Things to copy, not invent

- **Adding a column to an existing SQLite table** → copy
  `engine/vg/events/vehicles.py:293-296` — `PRAGMA table_info(table)` into a set,
  then `ALTER TABLE {table} ADD COLUMN {column} {ddl}` when absent.
- **A React provider that persists a display preference** → copy
  `web/src/app/ThemeContext.tsx` whole. 25 lines, exactly the right shape.
- **Arabic digits** → `engine/vg/platetext.py:96 to_arabic_digits`,
  `101 normalize`, `128 display(canonical, arabic_digits=True)`. **Reference
  only.** Plates keep their own path; the console's `Intl` numbering must not
  touch `plate_display`.
- **A test that builds a real store** → the `store` fixture in
  `engine/tests/test_groups.py`: throwaway `FaceGallery` + `SightingStore` in a
  `TemporaryDirectory`. **Close the gallery before the tempdir** or Windows
  fails teardown.
- **A signed-in test client** → `authed(app, role="admin")` from
  `engine/tests/conftest.py`. `engine/tests/test_api.py:20-27` shows the pattern
  for a fresh `MockStore` per test.

---

## 3. Traps

1. **Mixed line endings, no `.gitattributes`.** `api/*.py`, `services/*.ts`,
   `types.ts` and `STATUS.md` are **CRLF**; most other files are LF. This
   feature edits `schemas.py`, `app.py`, `live.py`, `store.py`, `api.ts`,
   `format.ts`, `http.ts`, `types.ts` — nearly all of them CRLF. A script that
   reads and writes text rewrites every ending and turns a six-line change into
   a whole-file diff. Read/write bytes, or check
   `b"\r\n" in path.read_bytes()` first. `git diff --stat` catches it.

2. **`Box.label` means two things.** A person's **name** on recognition boxes,
   and a **class name** in `MockStore` (`"Person in zone"`, `"Knife-shaped
   object"`). Turning it wholesale into a code destroys the name; leaving it
   wholesale leaves English on screen. The split is in `data-model.md` §6, and
   this is the field family that once made everyone read as "Mohamed Fouad".

3. **`VehiclePass.unit` is not `Metric.unit`.** The first is the owner's
   department, typed by an operator — data. The second is a `Literal` enum.
   Same field name, opposite treatment. Also on `RegisteredVehicle`,
   `VehicleRegistration`, `VehicleVisit`.

4. **Some "reasons" are a human's words.** `WeaponDetection.dismissal_reason`
   and `WeaponReview.reason` are typed by the person who reviewed the alert.
   Replacing them with a code deletes evidence.

5. **The camera picture must never mirror.** `dir="ltr"` on the
   `CameraFrame` picture container, geometry stays physical `left`/`top`. A box
   on the wrong side of the frame is a fabricated picture, not a layout bug.

6. **Do not hand `Intl` a timezone.** `Instant` is `utc` + `tzOffsetMinutes` and
   `format.ts:34` already adds the offset. `Intl` formats the resulting
   wall-clock only. Passing `timeZone` would reintroduce the bug P0-03 fixed —
   the offset is per-instant, not per-startup. Use `_instant(when, clock)` in
   `api/live.py` on the engine side; never build an `Instant` by hand.

7. **`pytest` is already red.** `1299 passed, 2 failed, 6 skipped` at `988a140`
   (~176s). Both failures are
   `test_api.py::TestWireShape::{test_everything_is_camel_case,
   test_time_is_utc_plus_an_explicit_site_offset}`, both caused by
   `api/store.py:31` `TODAY = date(2026, 7, 29)`: the demo breaches are
   `TODAY - 2/3/9` days, so the newest left a 30-day window on 26 Aug 2026 and
   `/breaches?window=Last 30 days` returns `[]`. **Not this feature's fault and
   not this feature's job.** Do not "fix" it by editing the tests.

8. **`formatCount` already follows the browser.** `format.ts:202` calls
   `toLocaleString()` with no locale, so counts silently use whatever the
   browser is set to. This feature makes it explicit — that is a fix, not a
   regression, and the rendered digits may change on some machines.

9. **`.row` is a grid with inline `gridTemplateColumns`.** It mirrors under
   `dir="rtl"` on its own, which is correct. Do not "fix" it by hardcoding an
   order.

10. **Both stores move together.** `MockStore` and `LiveStore` implement the
    same schemas. A field retyped for one is retyped for both, or demo mode
    stops type-checking.

11. **The AST scan missed at least one string.** "Sign-in is unavailable, so
    nothing can be served. See System Health." appears at runtime on a 503 but
    is not in the 69-site inventory — it is built somewhere the scan did not
    reach. **Re-run the scan in `research.md` after the refactor** and confirm
    the remaining count is only the excluded four.

12. **Deep links do not work in dev.** A page URL returns JSON through the
    proxy. Load `/` and click through.

13. **`.\dev.ps1 up -Reload` orphans processes on Windows.** Do not enable
    `--reload` on the engine. Tests beat hot reload here anyway.

---

## 4. Baseline

- `python -m pytest engine` → **1299 passed, 2 failed, 6 skipped** at `988a140`
  (176s). The 2 failures are pre-existing — trap 7.
- `cd web; npx tsc -b --force` → clean. Never `tsc --noEmit`; project
  references make it a silent no-op.
- `python -m pyflakes engine/vg engine/tools engine/tests` → clean.
- New test file: `engine/tests/test_notes.py`.
- New web files: `web/src/i18n/*`, `web/src/services/notes.ts`,
  `web/src/app/LanguageContext.tsx`. **No web test framework is added** — see
  `research.md` decision 8.

---

## 5. Still unknown

Check these in code rather than assume.

1. **Where `SiteInfo.digits` comes from.** `engine.yaml` has no site typography
   section and `engine/vg/config.py` was not read at plan time. The field needs
   a config source and a `western` default.

2. **`CountBar.label` versus `CountBar.at`.** `at: Instant | None` sits beside
   the label. Where `at` is present the console can format the caption itself
   and the field is dead weight; where `at` is `None` the label is all there is.
   Find which buckets have no `at` before deleting the field.

3. **Do `AlertRule` and `DeliveryTarget` exist in `LiveStore`?** They were found
   only in `MockStore` (`store.py:1162-1171`). If they are demo-only, their
   copy moves wholesale into the console catalogue and the wire fields go. If
   `LiveStore` serves them too, check what it sends first.

4. **Where "Sign-in is unavailable, so nothing can be served" is built.** Trap
   11. There may be siblings.

5. **How many console strings there really are.** The scan found 644 candidates
   across 43 files including enum values and fixture data; the honest estimate
   is ~400. The exact set falls out of extraction, and the biggest files are
   `TrackPerson.tsx` (72), `format.ts` (53), `Settings.tsx` (40),
   `VehicleRegister.tsx` (39), `CameraSources.tsx` (35), `navigation.ts` (33).

6. **Whether any `_log` call passes prose as `subject`.** Two do —
   `_log(actor, "vehicle.export", "vehicle passes", …)` is one. `action` is
   already a clean dotted vocabulary (`vehicle.pass.delete`, `track.search`,
   `weapon.confirmed`, `recording.start`, `path.sweep`, …); only `subject` and
   `detail` need a pass.

6. **The prose count in the plan is wrong — ~254, not 65.** The plan's AST scan
   looked at the keywords `reason`, `detail`, `note`, `label`, `title`. A scan
   of *every* string literal passed to an `S.*` constructor finds 164; counting
   every sentence-like literal outside docstrings in `live.py`, `store.py` and
   `archive.py` finds ~254. The prose is not only at the constructor — it is in
   class constants (`NO_RECORDER`, `NO_CAMERAS`), in helper returns
   (`_lost_state`, `_cameras_reading`, `_history`), in the `states` dict behind
   `Capability.reason`, and in `SubsystemUnavailable(...)` messages that become
   a 503 body. Almost all of it reaches a screen. See the scope note above
   Phase 4 in `tasks.md` for what was tried and why it was reverted.
