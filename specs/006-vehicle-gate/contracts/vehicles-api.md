# API contract: Vehicle Gate

Every endpoint sits under `/vehicles`. All require a session — the middleware in
`auth/deps.py` refuses anonymous callers on everything except `/healthz`,
`/auth/login` and `/auth/register`.

## Permissions

`/vehicles` goes in **`ADMIN_WRITE_PREFIXES`** (`auth/deps.py:97`), beside
`/cameras`, `/people`, `/zones` — **not** in `ADMIN_PREFIXES`.

That single line decides the whole permission model: `GET` for any signed-in user,
everything else administrator-only. A guard must read the register to do their job; a
guard must not be able to un-blacklist a car. Decided by path in one place, never by a
decorator — the endpoint somebody forgets to decorate is the one that leaks
(`auth/deps.py:106-117`).

**Consequence to accept deliberately**: a new endpoint added under `/vehicles` later
is admin-write by default. That is the right way round.

---

## Reading

| Method | Path | Returns | Notes |
|---|---|---|---|
| `GET` | `/vehicles/summary` | `GateSummary` | The six Live tiles. Fields are **optional ints** — absent when not computable, never `0`. |
| `GET` | `/vehicles/passes` | `list[VehiclePass]` | `?limit=`, `?plate=`, `?gate=`, `?direction=`, `?status=`, `?since=`. Newest first. |
| `GET` | `/vehicles/passes/{id}/snapshot` | image | `404` when the image has aged out; the pass itself still exists. |
| `GET` | `/vehicles/gates` | `list[GateTotals]` | Per gate, per day. `pairingAvailable` is false where no exit camera exists. |
| `GET` | `/vehicles/inside` | `list[VehicleVisit]` | Derived. `leftAt` null. |
| `GET` | `/vehicles/visits` | `list[VehicleVisit]` | Completed today. `inferred` true where the exit was never observed. |
| `GET` | `/vehicles/register` | `list[RegisteredVehicle]` | `?q=` over plate/owner/phone/unit, `?category=`. |
| `GET` | `/vehicles/cameras` | `list[CameraView]` | Gate cameras only, each labelled with its gate and direction. |
| `GET` | `/vehicles/template` | spreadsheet | The blank import template. |

## Writing — administrator only

| Method | Path | Body | Notes |
|---|---|---|---|
| `POST` | `/vehicles/register` | `VehicleRegistration` | `409` when the canonical plate already exists. |
| `PATCH` | `/vehicles/register/{id}` | `VehicleRegistration` | Applies from the next pass. Recorded passes unchanged. |
| `DELETE` | `/vehicles/register/{id}` | — | Passes are kept. `ON DELETE SET NULL`, never `CASCADE`. |
| `POST` | `/vehicles/import` | multipart file | Returns `VehicleImportResult`. Never partial-silent: every rejected row is reported with its reason. |
| `POST` | `/vehicles/export` | filters | CSV. **Writes the audit entry before returning the body** (P6-FR-023). |
| `DELETE` | `/vehicles/passes/{id}` | — | Removes one pass, its photograph and its plate crop. **Permanent**, and audited before the row goes. `404` when there is no such pass. |

The delete is real, not a flag. Visits and "inside now" are computed from
`vehicle_pass` by a window query, so a row kept hidden would need every one of those
queries to remember to exclude it — and the one that forgets is the bug. The audit
entry is written first and names the plate, so the log can lose a row without the
system losing the knowledge that it did. The audit itself has no delete.

The export is a `POST` for one reason: P6-FR-023 requires the audit row to be written
first, and a `GET` that writes is a `GET` that lies about being safe. `SAFE_METHODS`
(`auth/deps.py:103`) is also what decides admin-write, so a `GET` export would have
been readable by a guard *and* unaudited.

---

## Status codes

| Code | When |
|---|---|
| `200` | Including "nothing is running" — degradation is payload |
| `401` | No session |
| `403` | A non-admin attempting a write |
| `404` | No such vehicle, pass, or an image that has aged out |
| `409` | Plate already registered |
| `503` | `SubsystemUnavailable` — "nothing is running" is not "not found" |

**No 5xx for degradation.** A missing plate model, a dead gate camera and a stopped
worker are all `200` with a reason in the body (`AGENTS.md` rule 7). `GateSummary`
with every field absent plus a reason is a valid, useful, honest response.

---

## Capability and health

Two existing mechanisms, no new ones:

- **`capabilities()`** (`live.py:1322`) gains a `"vehicles"` key. `LIVE`, or
  `UNAVAILABLE` with the reason — no camera, no model, worker not started. Built with
  the existing `live(available, reason, detail)` helper so the sentence matches
  everywhere.
- **`_vehicles_stage()`**, copying `_weapons_stage()` (`live.py:1584`), appears in
  System Health. Its detail string reports the loaded **form**:

  ```
  plate-v1 on cuda (TensorRT) - 1 camera(s), 18ms last inference
  plate-v1 on cuda (PyTorch CUDA, no engine built) - 1 camera(s), 47ms last inference
  ```

  That parenthesis is the whole of P6-FR-035, and it costs one f-string. The same
  addition goes on the person, weapons, bag and pose stages — which is how the state
  that has been silently true for months becomes visible.

---

## Overlay

`_boxes(camera_id, "vehicles")` returns plate boxes only.

The branch **must sit above the face default** in `live.py:259-280`. The comment
already in that function about knives explains why in the sharpest possible terms:
falling through to faces would draw a person's **name** over a car. Rule 1.

Boxes carry the plate's status colour — green registered, amber unknown or expired,
red blacklisted — and geometry as fractions, clamped before sending.

The console must pass `detections={false}` to any `CameraFrame` on this page, because
`CameraFrame` with `live` also polls recognition boxes, which carry names
(`AGENTS.md`).
