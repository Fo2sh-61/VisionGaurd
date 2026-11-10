# API changes: 022

Wire rules are unchanged. Fields are snake_case in Python and camelCase on the wire, and
types use `extra="forbid"`. Who may call what is decided in `auth/deps.py`.

## New

### `PATCH /users/{id}`  (admin only — under `/users`)
Body: `{ "role": "admin" | "it" }` → returns `User`.
- Writes the audit entry `user.role` before anything changes.
- Returns 409 with a plain reason if the change would leave no enabled administrator.
- Returns 404 for an unknown id.

### `PATCH /settings/site`  (admin only — `/settings` write)
Body: `SiteSettingsUpdate` (every field optional) → returns `SchoolProfile`.
- Writes the audit entry `settings.site` before saving.
- Returns 422 with the reason when the values are invalid (cut-off outside the hours,
  calendar dates reversed, no working day chosen).

## Changed

| Endpoint | Change |
|---|---|
| `GET /settings/school` | adds `workingDays: number[]` |
| `GET /users` | `lastActive` is now filled (the last sign-in) |
| `GET /system/health` | adds `memoryUsedMb` and `memoryTotalMb`. The knife stage is absent when no camera runs `weapons` |
| `GET /settings/alerts` | the `weapon` rule is absent when no camera runs `weapons` |
| `POST /ask` | for IT, attendance and people questions answer "Attendance and people records are open to administrators only." The knives question is gone |

## Permission changes (`auth/deps.py`)

| Path | Before | After |
|---|---|---|
| `/attendance`, `/attendance/export` | any signed-in user | admin only |
| `/groups`, `/groups/{name}` | any signed-in user | admin only |
| `/people` (GET), `/people/{p}/history` | any signed-in user | admin only |
| `POST`/`DELETE /cameras/{id}/recording` | admin only | admin and IT |
| `/sources`, `/users`, `/enrolment` | admin only | unchanged |

## Serving the console (Jetson)

When `VG_CONSOLE_DIR` is set, `GET /` and the built files are served from that folder, and a
browser navigation to a console route gets `index.html`. This is copied from
`021-cloud-trial`. When the variable is unset, which is the default on Windows, nothing
changes.
