# Implementation Plan: Console v2 — shell, roles, Home, Population, Health, Settings, Jetson start

**Branch**: `console-v2-jetson` (spec folder `022-console-v2-shell`) | **Date**: 10 Nov 2026 | **Spec**: [spec.md](spec.md)

## Summary

The fact that decides the shape: **almost everything 022 needs already exists.** Sign-up, the bell, Mark all read, acknowledge, Population, alert settings and the
audit helper are all there. The hard Linux pieces were already solved on the unmerged
`021-cloud-trial` branch: the engine serving the built console itself, and browser-playable
clips without a hardware encoder. So 022 is mostly re-arranging what exists, plus four
small engine changes and one bash launcher.

What is genuinely new, smallest form first:

1. **Roles** — three path rules in `auth/deps.py`, one `set_role` with a last-admin guard,
   one `PATCH /users/{id}`.
2. **Settings that really save** — today the site profile *says* it saves and doesn't (a rule-4
   bug). One key/value table, one `PATCH /settings/site`, working days added.
3. **Knife detection gone** — removed from the console, the Ask menu, the alert rows and
   System Health; the engine code stays.
4. **Jetson launcher** — `launch.sh` + a `.desktop` file. The engine serves the console, so
   the Jetson runs one process plus a browser window. Closing that window stops the engine.

## Technical Context

**Language/Version**: Python 3.14 on Windows (dev). The Jetson reached over SSH today is a
**test bench only** — nothing of VisionGuard is installed on it; the deployment board is a new
Jetson the owner will buy. Its figures are the assumption until that board arrives:
**Python 3.10.12**, JetPack 6 (L4T 36.5.2). No 3.11+ syntax in `engine/` (checked with
`ast.parse(feature_version=(3,10))`).
TypeScript/React (Vite) for the console.
**Primary Dependencies**: FastAPI, SQLite (`vg/db.py::connect`), OpenCV, ultralytics/torch.
Jetson has torch 2.8.0 (CUDA), TensorRT, system OpenCV 4.5.4 with FFmpeg + GStreamer.
**Storage**: the existing SQLite databases. One new table: `site_setting`.
**Testing**: `python -m pytest engine`, `npx tsc -b --force` (web and mobile), pyflakes,
`tools/check_parity.py`.
**Target Platform**: NVIDIA Jetson Orin Nano Super, Ubuntu 22.04, 8 GB shared memory, no
hardware video encoder. Windows stays the development machine.
**Performance Goals**: the console opens within a minute of the engine answering (SC-006).
**Constraints**: the camera count is configuration, never a constant. How many cameras one Jetson carries is
still open: the owner decides after the Jetson soak test.
**Scale/Scope**: ~40 cameras at the compound; 2 roles; 9 sidebar destinations.

## Constitution Check

| Gate | Holds? | How |
|---|---|---|
| III Truthful data | Yes, and **fixes a breach** | Settings "edits save on their own" is false today; it now really saves. The dead "Edit" button on Accounts becomes the role change. Badges show nothing when their source is down. |
| III Audit | Yes | `user.role` and `settings.site` audited through `_log` before the write. (The audit trail itself is still in memory, lost on restart. That is an existing gap with its own spec, 018, and is not widened here.) |
| IV Server-side permissions | Yes | All by path in `deps.py`; the console only hides. |
| Rule 2 / 3 (identity) | Yes | Home camera strip passes `detections={false}`. |
| Rule 7 / 8 (degradation) | Yes | System Health unchanged in that respect; memory added as a reading, never a failure. |
| Rule 9 (isolation) | Yes | No page needs another feature on. |
| Rule 10 (weapons wait) | Yes | Knife detection switched off at v2 sites, so nothing waits. |
| Scale | Open, honestly | FR-133 stays open until the soak test reports. |

No violations; no complexity tracking needed.

## Each requirement → the smallest thing that satisfies it

| FR | Mechanism |
|---|---|
| 101 | Sidebar text "VisionGuard" (drop "AI"); site name from the settings table. |
| 102, 129 | Rewrite `NAV` in `app/navigation.ts` (shared with the phone, so copy the bytes to mobile too): Home, Attendance*, People*, Population, Car plates, Restricted zones, Work stations, Cameras; SYSTEM: Health, Settings. Remove weapons, lost-items, track from `NAV` and `HOME_ORDER`. Routes for Work stations and Cameras are placeholders that say "arrives with spec 025 / 027", **not** in the sidebar until those land (no dead links). |
| 103 | `useNavBadges` hook polling existing endpoints every 15 s (attendance summary, vehicle alerts). Zones and stations badges are added by 025. No source = no number. |
| 104 | Bottom card counts `useAttention().items`, the same list as Home. |
| 105 | Top bar as today; the bell and Mark all read already exist (`useAlertFeed`, client-side seen-list). |
| 106, 107 | `TopBar` user block becomes a menu: Health, Settings, Accounts (admin), language chips, theme toggle, Sign out (moved from the sidebar foot). The top bar's order comes from flex order under `[dir=rtl]`, not separate markup. |
| 108 | New `ToastProvider` + `useToast()` (console only); every save/dismiss/ack calls it on success; failures keep their inline notice. |
| 109 | Exists (`Login.tsx`, `POST /auth/register` gives `it`). Restyle only. |
| 110, 111, 115 | `deps.py`: add `/attendance`, `/groups` to `ADMIN_PREFIXES`; move `/people` from write-only to `ADMIN_PREFIXES`; add a recording pattern to the operator allowance (IT may record). Gone's permission goes in with Gone itself (spec 024). |
| 112 | `/ask` reads the session's role; for IT the attendance and people queries answer the fixed sentence. |
| 113 | Settings already disables for non-admins; add the read-only notes. |
| 114 | `UserStore.set_role()` refusing to remove the last admin; `PATCH /users/{id}` `{role}`; `_log` first. "Last active" shows **last signed in** (`last_login_at`), the only real figure; labelled so. |
| 116–118 | Home: add a 4-camera strip (`CameraFrame ... detections={false}`, cameras up only) and three cards from existing calls; chips keep using `ask()`. |
| 119–121 | Counting: labels via i18n (move the hard-coded English), level computed in `format.ts` from count/capacity (Empty / Quiet <70% / Busy <90% / Near capacity ≤100% / Over capacity), nothing when capacity is 0. |
| 122 | Relabel `intrusion` as "Restricted zones" in the watch-for list. **Work stations** is added by spec 025 with the feature itself; offering it before would be a dead choice (rule 4). |
| 123, 125 | `site_setting` table + `PATCH /settings/site`; `LiveStore.hours()` = config seed overlaid by the table; the 5 `self.config.hours` reads and `AlertService.hours` use it. `SCHOOL_WEEKDAYS` becomes the saved working days (default **Saturday–Thursday**). "Term" relabelled Working calendar; wire names `term_from/term_to` kept. |
| 124 | Alert rows: hide `weapon` (engine stops listing it when no camera runs weapons); relabel `intrusion`. "Work station left empty" arrives with 025's alert kind. Remove the Detection-zones card. |
| 126–128 | `tokens.css` gains `--chrome`, `--frame`, design detection colours; load Noto Sans Arabic; one global `[dir=rtl] * { letter-spacing: 0 }`; new shell CSS uses logical properties only. 022's own new strings go into `keys/en/ar.draft`. |
| 130–132 | `launch.sh` (see research R7) + `tools/install-shortcut.sh` writing a `.desktop` file and a PNG icon. |
| 133 | Camera count is already configuration. Number stays open. |
| 134 | System Health adds memory used / total from `psutil.virtual_memory()`, labelled shared on the Jetson. Clips use the `021-cloud-trial` ffmpeg/x264 pipe encoder. |
| 135 | Nothing on Windows changes: `dev.ps1`/`launch.ps1` untouched; the engine serves `web/dist` only when `VG_CONSOLE_DIR` is set. |

## Project Structure

### Documentation

```text
specs/022-console-v2-shell/
├── plan.md  research.md  data-model.md  quickstart.md  context.md
└── contracts/api.md
```

### Source Code (what changes)

```text
engine/vg/auth/deps.py            path rules (110, 111, 115)
engine/vg/auth/store.py           set_role + last-admin guard
engine/vg/settings_store.py       NEW: site_setting key/value table
engine/vg/api/app.py              PATCH /users/{id}, PATCH /settings/site, _serve_console (from 021)
engine/vg/api/live.py             hours(), users() last_active, health() memory + no knife stage
engine/vg/api/schemas.py          UserRoleUpdate, SiteSettings(+working_days), SystemHealth memory
engine/vg/alerts/events.py        working days instead of SCHOOL_WEEKDAYS
engine/vg/alerts/service.py       hours from LiveStore.hours()
engine/vg/ask/menu.py             drop knives; role-aware attendance answer
engine/vg/ingest/encoder.py       PIPE_X264 from 021-cloud-trial
engine/tests/test_shell_v2.py     NEW
web/src/app/{navigation.ts*, routes.tsx, AppShell.tsx, ToastContext.tsx (new), useNavBadges.ts (new)}
web/src/components/{Sidebar, TopBar, ui (Toast), CameraSources, AlertSettings}.tsx
web/src/pages/{Home, Counting, Settings, Users, SystemHealth, Login}.tsx
web/src/services/{api.ts*, wire.ts*, format.ts*}   web/src/i18n/{keys,en,ar.draft}.ts*
web/src/styles/{tokens.css*, app.css}   web/index.html (Noto Sans Arabic)
launch.sh   tools/install-shortcut.sh   (NEW, Linux)
* = byte-shared with mobile/src: copy after editing, check_parity.py must pass.
```

**Structure Decision**: the existing engine + web layout; no new packages. One new engine module, two new hooks, one new context, two new shell scripts.

## Order of work

1. **Engine first, test-first**: deps rules, set_role, settings table + hours(), working days, knife removal, memory, `_serve_console`, encoder. Each with its test in `test_shell_v2.py`.
2. **Console shell**: tokens/fonts/RTL, toast, sidebar, top bar menu, navigation (+ mobile copy), then the pages (Accounts, Settings, Home, Population, Health).
3. **Jetson**: write `launch.sh` and the shortcut now; check them on the **new** Jetson when it
   arrives (SC-006). Never on the SSH test bench — the owner keeps it free of VisionGuard.
   Until then 022 is done on Windows with the Jetson items reported as "waiting for the board".
4. Checks: pytest count not lower, tsc web + mobile, pyflakes, parity, `dev.ps1 up -Clip -DevSignIn admin` by eye, then `-DevSignIn it`.

## What this plan deliberately does not do

- No new role, no per-endpoint decorators, no server-side "unread" store (the client seen-list is enough).
- No rename of `term_from/term_to` on the wire (label only), and no separate "last active" tracking.
- No native window wrapper (Electron etc.): a Chromium `--app` window is the window.
- Work stations watch-for choice, zone/station badges, the station alert row: they arrive with 025, because before then they would be dead controls.
