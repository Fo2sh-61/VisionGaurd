# API changes: 024

Wire rules unchanged: snake_case in Python, camelCase on the wire, `extra="forbid"`. Who may call
what is decided in `auth/deps.py`. Degradation is payload, never a 5xx.

## New

### `POST /vehicles/visits/{entryPassId}/gone`   (admin and IT)
Ends a visit by hand. No body. Returns `{ "ok": true, "changed": true|false }`.
- Writes audit `vehicle.visit.gone` (plate, entry time and gate) **before** the mark.
- `changed:false`, status 200: the visit was no longer open (the car left meanwhile). The page reloads.
- 404: no such pass, or the pass is an exit. 503 (`SubsystemUnavailable`): no vehicle log.
- Path rule: anchored pattern `^/vehicles/visits/[^/]+/gone$` in the operator allowance.

## Changed

| Endpoint | Change |
|---|---|
| `GET /vehicles/passes` | new options `q` (plate in either digit system, or owner), `days` (1..31, window of that many days ending at the end of `day`, or of today), `exact` (bool: plate equals `plate`). Without `days` nothing changes. |
| `POST /vehicles/export` | accepts `q` too, so the file follows the search shown. Still audit first; admin only. |
| `VehiclePass` | adds `plateWidth` (int or null) and `readPlateDisplay` (string or null) |
| `VehicleVisit` | adds `endedBy` (string or null) |
| `GET /vehicles/summary` | `reason` and `camerasNote` now also say when a gate camera's plate reader died or keeps failing (for example out of memory). When every gate camera is in that state the counts are absent. |
| `GET /system/health` | the Plate reading stage reports a failing reader as unhealthy with the reason |
| `PATCH /vehicles/passes/{id}/plate` | keeps the original reading; no alert message is sent for a pass corrected before its car left |

Everything else under `/vehicles` is unchanged.

## Permission table (IT)

| Action | Admin | IT | By |
|---|---|---|---|
| Read all tabs, dismiss alert | yes | yes | unchanged |
| Gone | yes | **yes (new)** | anchored pattern, `deps.py` |
| Fix a plate, remove a pass, register/edit/remove vehicle, import, export | yes | no (403) | `/vehicles` admin-write prefix, unchanged |

## Not changed (FR-321)

How a pass is voted in, what an alert message says, the 30-day photo retention, the 3-frame agreement.
