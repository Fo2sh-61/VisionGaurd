# Data Model: Vehicle Gate Accuracy & Redesign

Phase 1 output. Only what this feature adds or changes; the 006 model (vehicle,
vehicle_pass, derived visits) is unchanged.

## Database (SQLite, `engine/data/visionguard.db`)

### New: `vehicle_alert_ack` — a dismissal is a record

| Column | Type | Notes |
|---|---|---|
| `pass_id` | TEXT PRIMARY KEY | The pass whose alert was dismissed, `REFERENCES vehicle_pass(id) ON DELETE CASCADE`. One alert per pass, so one row per dismissal. |
| `by_who` | TEXT NOT NULL | Account name. "Recorded under your name." |
| `at` | TEXT NOT NULL | ISO instant of the dismissal. |
| `action_taken` | INTEGER NOT NULL | 1 when the resolving action was used (register / renew), 0 for a bare dismissal. |

**As built (27 Aug), two deviations from the above as first drafted:** the
column is `by_who`, not `by` — `by` sits close enough to `GROUP BY` / `ORDER BY`
to be worth not finding out about later. And the foreign key CASCADEs, unlike
`vehicle_pass.vehicle_id` which is `SET NULL`: that column exists to *preserve*
history when a car leaves the register, whereas this row only *describes* a
pass, so when an administrator deletes a pass its dismissal has nothing left to
be about.

Rules: the audit entry is written **before** this row (the `_log`-first idiom).
No delete path — a dismissal cannot be undone, matching acknowledgements
elsewhere. An alert *exists* iff a today's pass has status `unknown`,
`blacklist` or `expired` and no row here — alerts themselves are never stored.

### New: `vehicle_import_run` — the source of the "last import" line

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PRIMARY KEY | |
| `at` | TEXT NOT NULL | When the import ran. |
| `added` / `updated` / `skipped` / `rejected` | INTEGER NOT NULL | Exactly the numbers the importer already reports. |
| `by_who` | TEXT NOT NULL | The administrator who ran it. |

**As built**: `updated` was added after checking `VehicleImportResult`, which
already reports `added`, `updated`, `skipped_duplicates` and `problems` — the
table records what the importer actually produces rather than a subset of it.
`by_who` for the same reason as above.

Inserted in the same transaction as the import. The register card reads the
newest row; no row → no line.

### Changed: visits window query

The derived-visits SQL additionally selects the entry pass id and (when paired)
the exit pass id. No schema change — `vehicle_pass` already holds everything.

## Files

### `Egyptian Car Plates dataset/plate_truth.csv` — human-confirmed read truth

| Column | Notes |
|---|---|
| `image` | Filename under `EALPR Vechicles dataset/Vehicles/`. |
| `x`,`y`,`w`,`h` | The labelled plate box (normalised, from the matching `.txt`). |
| `text` | Canonical plate text (`platetext.normalize` form: Arabic letters, ASCII digits). |
| `width_px` | Plate width in source pixels — the ≥100 px filter for the target. |
| `confirmed_by`, `confirmed_at` | The human and the date. Model proposals are never truth until confirmed. |

### `specs/007-vehicle-gate-tuning/evidence/eval-<date>-<config>.md` — dated evidence

One file per evaluation run: config (theirs / fp32 / fp16 / trt / candidate),
dataset + subset used, detection recall/precision, exact-read rate overall and at
≥100 px, per-plate failures, and the honesty note that this dataset is the
models' own training set (pipeline fidelity, not site generalisation).

## Wire types (`engine/vg/api/schemas.py` ↔ `web/src/services/wire.ts`)

### Changed

| Type | Change |
|---|---|
| `Box` | `kind` literal gains `"plate"` (the invisible-box fix). New optional `plate_width_px: int \| None` — source-frame pixels, plate boxes only. |
| `GateSummary` | New optional `cameras_reading: int \| None`, `cameras_total: int \| None`, `cameras_note: str \| None`. `needs_review` stays on the wire (mock + export uses) but no tile renders it. |
| `VehicleVisit` | New `entry_pass_id: str \| None`, `exit_pass_id: str \| None`, `entry_has_snapshot: bool = False`, `exit_has_snapshot: bool = False`. |

### New

**`ReaderAttempt`** — one row of "What the reader is seeing now":
`at: Instant`, `camera_id: str`, `camera_name: str`, `display: str` (empty =
read nothing), `confidence: Confidence | None`, `plausibility: Confidence | None`,
`width_px: int`, `leader_display: str | None`, `votes: int`, `votes_needed: int`.

**`GateReaderCamera`** — the transparency line, one per gate camera:
`camera_id`, `camera_name`, `gate: int`, `direction: str`,
`finder: str` (weights name actually loaded), `reader: str`, `form: str`
(TensorRT / PyTorch CUDA), `read_ms: float | None` (rolling; None until first
read).

**`GateReaderNow`** — the one-poll payload: `cameras: list[GateReaderCamera]`,
`attempts: list[ReaderAttempt]` (newest first, bounded), `votes_needed: int`,
`reason: str | None` (set when nothing is reading — the card renders it instead).

**`GateAlert`** — `pass_id: str`, `kind: str` (`unknown | blacklist | expired`),
`at: Instant`, `plate: str`, `plate_display: str`, `gate_name: str`,
`owner: str | None`, `message-bearing fields` kept structured (the console builds
sentences — `format.ts` owns rendered strings): `permit_expired_on: str | None`,
`near_match_display: str | None`, `near_match_owner: str | None`,
`inside: bool` (blacklist copy says "still inside" only when true and pairing
exists). `dismissable: bool = True`.

**`TrafficHour`** — `hour: int`, `entered: int`, `left: int`.

## Entity rules

- **Alert**: derived, keyed by pass id. Kind from pass status. Near-match only
  for `unknown`, only when exactly one register plate is within one edit
  (`platetext.same_plate`), phrased by the console as a question.
- **Attempt**: exists only in the worker's per-camera `deque(maxlen=12)`;
  never persisted; timestamps from `frame.captured_at`.
- **Evaluation run**: append-only evidence files; never overwritten, dated.

## State transitions

Alert: *(pass recorded with qualifying status)* → visible → **dismissed**
(audit first, then `vehicle_alert_ack` row; terminal) or **resolved by action**
(register / renew — the action's own audited write, then the same ack row with
`action_taken=1`). A later pass of the same car raises a new alert (new pass id).
