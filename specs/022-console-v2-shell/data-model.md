# Data model: 022

## site_setting (new table)

| Column | Type | Notes |
|---|---|---|
| key | TEXT PRIMARY KEY | `name`, `hours_from`, `hours_to`, `late_cutoff`, `term_from`, `term_to`, `working_days` |
| value | TEXT | JSON for `working_days` (list of Python weekday ints), ISO text otherwise |
| updated_at | TEXT | ISO instant |
| updated_by | TEXT | account name |

The table holds only the keys someone has saved. Any key not in the table comes from
`engine.yaml`, which is the seed.

**Validation**, the same rules as `HoursConfig.parse`:
- `hours_from` ≤ `late_cutoff` ≤ `hours_to`.
- `term_from` ≤ `term_to`, or both empty.
- `working_days` is a non-empty subset of 0..6.

**Effective hours** = `dataclasses.replace(config.hours, **saved)`, read on every call. A save
therefore takes effect at once, with no restart.

## HoursConfig (existing, extended)

Add `working_days: frozenset[int] = frozenset({5, 6, 0, 1, 2, 3})` (Saturday–Thursday).

## app_user (existing, unchanged)

`role` changes through `UserStore.set_role`. Invariant: at least one enabled admin, always.

## Wire types

- `SchoolProfile` (existing, returned by `GET /settings/school`): add `working_days: list[int]`.
- `SiteSettingsUpdate` (new): every field optional (`name`, `hours_from`, `hours_to`,
  `late_cutoff`, `term_from`, `term_to`, `working_days`); `extra="forbid"`.
- `UserRoleUpdate` (new): `role: Role`.
- `User.last_active`: now filled from `last_login_at` (shown as "Last signed in").
- `SystemHealth`: add `memory_used_mb: int | None` and `memory_total_mb: int | None`.
