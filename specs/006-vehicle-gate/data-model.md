# Phase 1 data model: Vehicle Gate

Two tables. The Gate project uses five (`vehicles`, `events`, `visits`, `alerts`,
`camera_status`); three of those describe things VisionGuard already records.

| Gate table | Here | Why |
|---|---|---|
| `vehicles` | `vehicle` | kept |
| `events` | `vehicle_pass` | kept, renamed — "event" already means something else in this repo |
| `visits` | **derived** | a window function over `vehicle_pass`, see research §3 |
| `alerts` | **dropped** | `attention()` / `acknowledge()` already exist |
| `camera_status` | **dropped** | `CameraRegistry` already tracks this |

Both live in `engine/data/visionguard.db` — the same file as every other feature.
Created by `VehicleStore.__init__` executing `SCHEMA`, the pattern in
`events/weapons.py:127-137`.

---

## `vehicle` — the register

```sql
CREATE TABLE IF NOT EXISTS vehicle (
    id            TEXT PRIMARY KEY,
    plate         TEXT NOT NULL UNIQUE,   -- canonical, from platetext.normalize
    plate_display TEXT NOT NULL,          -- as shown, Arabic digits, RTL
    owner_name    TEXT,
    phone         TEXT,
    unit          TEXT,
    category      TEXT NOT NULL,          -- staff | visitor | vip | blacklist
    car_make      TEXT,
    car_colour    TEXT,
    valid_until   TEXT,                   -- ISO date; NULL = no expiry
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicle_category ON vehicle(category);
```

**`plate` is canonical and `UNIQUE`.** This is the whole reason `platetext.normalize`
exists: a plate typed in English digits, one imported from a spreadsheet in Arabic
digits, and one read off a camera must collide on this column or the school ends up
with three rows per car. The constraint is what makes that a guarantee rather than an
intention — checking first and inserting second still races two simultaneous imports.
Same reasoning as `app_user.email` in `auth/store.py:50`.

**`plate_display` is kept separately** because normalising is lossy. The console shows
the plate as it appears on the car; the database matches on the canonical form.

**Categories are exactly four** — `staff`, `visitor`, `vip`, `blacklist`. `resident`
from the Gate project is dropped (P6-FR-014). Enforced in Python against a
`CATEGORIES` tuple, mirroring `ROLES` in `auth/store.py:38`, so an unknown value
raises rather than silently storing.

**`valid_until` is a date, not a status.** "Expired" is computed at read time by
comparing against the site's today. Storing a status would need a nightly job to keep
it true, and would be wrong between midnight and whenever that job ran.

---

## `vehicle_pass` — one row per car that passed

```sql
CREATE TABLE IF NOT EXISTS vehicle_pass (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,          -- UTC ISO8601
    camera_id     TEXT NOT NULL,
    gate          INTEGER NOT NULL,
    direction     TEXT NOT NULL,          -- entry | exit
    plate         TEXT NOT NULL,          -- canonical
    plate_display TEXT NOT NULL,
    status        TEXT NOT NULL,          -- known | unknown | blacklist | expired
    vehicle_id    TEXT REFERENCES vehicle(id) ON DELETE SET NULL,
    confidence    REAL NOT NULL,
    votes         INTEGER NOT NULL,       -- frames that agreed
    needs_review  INTEGER NOT NULL DEFAULT 0,
    snapshot      TEXT,                   -- relative path, may become dangling
    plate_crop    TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pass_at    ON vehicle_pass(at DESC);
CREATE INDEX IF NOT EXISTS ix_pass_plate ON vehicle_pass(plate, at DESC);
CREATE INDEX IF NOT EXISTS ix_pass_gate  ON vehicle_pass(gate, at DESC);
```

**`ON DELETE SET NULL`, never `CASCADE`.** P6-FR-020: removing a car from the register
must keep its passes. `CASCADE` here would delete the history that a removal exists to
preserve.

**`status` is frozen at the moment of the pass.** It is not recomputed later. If a car
is blacklisted today, yesterday's pass still reads as it read yesterday — P6-FR-019
says a register change applies from the next pass and does not alter recorded ones.

**`plate` is denormalised onto the row on purpose.** A pass by an unregistered car has
no `vehicle_id` at all, and must still be searchable by plate. This is also what lets
the derived-visit query run without a join.

**`needs_review` keeps a weak read rather than discarding it** (P6-FR-005). The
confidence and the vote count travel with it so a guard can judge.

**`snapshot` / `plate_crop` may point at deleted files.** The row outlives its images
by design — same as `WeaponScene.playable` (`events/weapons.py:123`). Any reader must
check existence, never assume.

---

## Visits — derived, not stored

```sql
WITH ordered AS (
  SELECT plate, at, direction, gate,
         LEAD(at)        OVER w AS next_at,
         LEAD(direction) OVER w AS next_direction,
         LEAD(gate)      OVER w AS next_gate
  FROM vehicle_pass
  WINDOW w AS (PARTITION BY plate ORDER BY at)
)
SELECT plate, at AS entered, gate AS entry_gate,
       CASE WHEN next_direction = 'exit' THEN next_at  END AS left_at,
       CASE WHEN next_direction = 'exit' THEN next_gate END AS exit_gate
FROM ordered
WHERE direction = 'entry';
```

- `left_at IS NULL` → still inside. Duration is now minus `entered`.
- `left_at IS NOT NULL` → a completed visit, duration is the difference.
- Two consecutive entries → the first visit closed without an observed exit. It is
  reported as **inferred**, never as observed (P6-FR-011 edge case).

**With only an entry camera every row has `left_at IS NULL`.** That is the truth, and
the store must return a flag saying "no exit camera is configured" so the page can say
it rather than print a zero (P6-FR-012).

SQLite has had window functions since 3.25; Python 3.14 ships far newer.

---

## Status, decided at pass time

```
plate not in vehicle                          -> unknown
category == 'blacklist'                       -> blacklist    -> attention item
valid_until is set and < site today           -> expired
otherwise                                     -> known
```

Order matters: **blacklist outranks expiry.** A withdrawn contractor whose permit also
lapsed is a blacklist alert, not a quiet amber row.

Only `blacklist` raises an attention item (P6-FR-021). `expired` does not — Mohamed's
call, and the right one: an expired parent pass is not a security event.

---

## Wire types (`api/schemas.py`)

All subclass `Wire` — snake_case in, camelCase out, `extra="forbid"`. Fractions
validated 0..1, so plate box geometry must be clamped before sending or the response
500s (`AGENTS.md`).

| Type | Carries |
|---|---|
| `VehiclePass` | id, at (`Instant`), plate, plateDisplay, owner, unit, gate, direction, status, confidence, votes, needsReview, hasSnapshot |
| `RegisteredVehicle` | id, plate, plateDisplay, owner, phone, unit, category, carMake, carColour, validUntil, notes, lastSeen |
| `VehicleRegistration` | the write body — plate required, everything else optional |
| `GateTotals` | gate, name, entered, left, inside, `pairingAvailable: bool` |
| `VehicleVisit` | plate, owner, entered, leftAt, entryGate, exitGate, minutes, `inferred: bool` |
| `VehicleImportResult` | added, updated, skippedDuplicates, rejected, `problems: list[str]` |
| `GateSummary` | the six Live-tab tiles, each an optional int — **absent, not zero, when unknown** |

`GateSummary`'s optional ints are the mechanism behind SC-010. A tile with no number
renders as a reason, not as `0`. `Fraction`/`Confidence` clamping applies to every
plate box.

---

## Configuration

`CameraConfig` (`config.py:179`) gains two optional fields:

```yaml
- id: cam-laptop
  gate: 1              # int | None
  direction: entry     # "entry" | "exit" | None — "both" is rejected
  features: [attendance, counting, intrusion, track, vehicles]
```

Both default `None`, so every existing camera parses unchanged. A camera is a gate
camera only when it has **both fields and `vehicles` in `features`** — one without the
other is a configuration error worth reporting, not a silent half-state.

`engine.yaml` gains one model entry pointing at the two supplied weights in
`models/Gate/gate-anpr/gate-anpr/models/`.
