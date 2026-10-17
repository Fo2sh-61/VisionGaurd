# Data model: Pilot site readiness

All three tables are created by migration step 1 in `visionguard.db`.

## `site_setting`

One row per setting. The database is the source of truth; `engine.yaml` seeds a key the
first time it is read.

| Column | Type | Rule |
|---|---|---|
| `key` | TEXT PK | one of the keys below |
| `value` | TEXT | JSON |
| `updated_at` | TEXT | ISO time, UTC |
| `updated_by` | TEXT | account id, or `seed` |

| Key | Seeded from | Validation |
|---|---|---|
| `school.name` | `site_name` | 1–120 characters |
| `school.hours_from`, `school.hours_to` | `hours.from`, `hours.to` | `HH:MM`, from before to |
| `school.late_cutoff` | `hours.late_cutoff` | `HH:MM`, inside the hours |
| `school.term_from`, `school.term_to` | `hours.term_from`, `hours.term_to` | dates, from before to |
| `retention.clips_days` | `storage.clip_retention_days` (30) | whole number 1–3650 |
| `retention.events_days` | 365 | whole number 1–3650 |
| `retention.sightings_days` | 365 | whole number 1–3650 |
| `backup.folder` | none (unset) | an existing folder outside `C:\VisionGuard\data` |

The time zone stays in `engine.yaml`. It cannot be edited.

## `maintenance_run`

| Column | Type | Rule |
|---|---|---|
| `id` | INTEGER PK | |
| `kind` | TEXT | `cleanup` or `backup` |
| `started_at` | TEXT | ISO UTC |
| `finished_at` | TEXT NULL | NULL while running or if it died |
| `ok` | INTEGER | 1 finished cleanly; 0 failed or incomplete |
| `detail` | TEXT | JSON: clean-up counts per kind, or backup folder name and bytes; `reason` when not ok |

- System Health reads the newest row of each kind, and for backups the newest `ok = 1` row.
- These rows are kept for 365 days; the clean-up removes older ones.

## `erasure`

| Column | Type | Rule |
|---|---|---|
| `id` | INTEGER PK | |
| `person_id` | TEXT | the erased directory id. No name, no data |
| `started_at` | TEXT | ISO UTC |
| `files_left` | TEXT | JSON list of paths still to delete; emptied as they go |
| `finished_at` | TEXT NULL | NULL until every file is gone |

- It is written in the same transaction that deletes the rows.
- The maintenance thread finishes any unfinished row at start.

## Changes to existing shapes

- **Wire `User`** gains `disabled: bool`.
- **Config**:
  - new `tls:` block: `names: list[str]` (addresses or `localhost`), `cert_dir: path`.
    Validated: each name is an IP address or `localhost`;
  - `VG_HOME` (environment) moves `engine.yaml` and `.env` out of the release folder.
- **Retired**:
  - `alerts.log_retention_days`: the delivery log follows `retention.events_days`;
  - the alert sender's own daily delete.
- **Health**: three new `PipelineStage` keys: `cleanup`, `backup`, `certificate`.
