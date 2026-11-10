# Data model: 024

All in the existing `VehicleStore` database. Added with `CREATE TABLE IF NOT EXISTS` and the
`_add_missing_columns` loop, so a running gate keeps its data and needs no migration step.

## vehicle_pass (two new columns)

| Column | Type | Notes |
|---|---|---|
| plate_width | INTEGER NULL | Pixels across the plate in the frame the photograph was taken from. `NULL` on rows written before this ships: the page says "not recorded". Refreshed by `amend_pass` only when a better photograph replaces the old one. |
| read_plate | TEXT NULL | The reader's own canonical plate, kept the first time a person corrects it. `read_plate = COALESCE(read_plate, plate)` so a second fix keeps the first original. `NULL` means never corrected. |

`corrected_by` / `corrected_at` already exist and still say who and when.

## vehicle_gone (new table)

| Column | Type | Notes |
|---|---|---|
| entry_pass_id | TEXT PRIMARY KEY | The entry pass that opened the visit. `REFERENCES vehicle_pass(id) ON DELETE CASCADE`, like `vehicle_alert_ack`: removing the pass removes the mark. |
| by_who | TEXT NOT NULL | Account name. |
| at | TEXT NOT NULL | ISO instant the button was pressed. |

No delete path: a Gone cannot be taken back. The audit entry `vehicle.visit.gone` is written before the row.

**Derived rule** (inside `visits()`): a visit with a mark is closed at `at`, `ended_by = by_who`,
`inferred = false`. The mark wins over a later exit or re-entry, because it was made while the
visit was open.

## Wire types

- `VehiclePass`: add `plate_width: int | None`, `read_plate_display: str | None` (set only when corrected and different from the current plate).
- `VehicleVisit`: add `ended_by: str | None`. Non-null means closed by hand. `inferred` keeps its meaning.
- New body/response: `GoneResult { ok: bool, changed: bool }`.
- No new type for the week or for search: both reuse `VehiclePass`.
