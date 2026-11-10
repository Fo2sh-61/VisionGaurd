# API changes: 027

Wire rules are unchanged. Who may call what is decided in `auth/deps.py`, by path. Degradation is payload: none of these returns 5xx because a subsystem is missing.

## New

### `GET /cameras/wall`  (any signed-in user)
Returns `CameraWall` (see data-model.md). One request for every camera, any number of tiles.
- Contains **no name, attendance value or identity-based count**, by type. A test walks the model fields.
- A missing subsystem gives `readings[].kind = "unavailable"` with a `reason` and `detail`, still 200.
- With no registry running: `cameras: []`, `up: 0`, `total: 0`. The console tells "no cameras" from "engine not reachable" by the HTTP result.
- Performance: built from in-memory state; the vehicle-pass lookup runs once per second at most (cached), however many viewers poll.

### `GET /cameras/{id}/faces`  (admin only)
Query: `feature` one of `attendance`, `track` (omitted = faces); `colour` as today; `boost` (below).
Returns `CameraDetections`, exactly what `/detections` returned for those features before. **This is the only camera read that carries a person's name.**

### `GET /attendance/cameras`  (admin only, through 022's `/attendance` prefix)
Returns `dict[str, int | None]`: faces identified right now per camera. Used only for Attendance tiles shown to administrators.

## Changed

| Endpoint | Change |
|---|---|
| `GET /cameras/{id}/detections` | `feature` is now **required** and limited to `counting`, `intrusion`, `weapons`, `lost`, `vehicles`. `attendance`, `track` or none answer 422 with "Face overlays are at /faces (administrators)". New query `boost` (bool, default `true`): when `false`, nothing here calls `note_interest`. |
| `GET /cameras` | `boxes` is always `[]` (the list never carried a box the console drew; it carried names to IT). |
| `GET /sources`, `PATCH /sources/{id}` etc. | `ip` and `lastError` pass through the new `redact_source()`: userinfo of any shape, and secret-looking query values, are `****`. |

## Permission changes (`auth/deps.py`)

| Path | Before | After |
|---|---|---|
| `GET /cameras/{id}/faces` | (did not exist) | admin only: one anchored pattern `^/cameras/[^/]+/faces$`, checked in `requires_admin` before the safe-method return, in the same place 022 puts its recording pattern |
| `GET /cameras/wall` | (did not exist) | any signed-in user (a read under `/cameras`) |
| `GET /attendance/cameras` | (did not exist) | admin only (022's `/attendance` prefix) |
| `POST`/`DELETE /cameras/{id}/recording` | admin only | admin and IT: **022's change**, only tested here |

## Behaviour that is not an endpoint

- **`boost=false` guarantee**: with it set, a call changes no worker's `_boost_until` (a test reads each worker's boost state before and after 20 calls on 20 cameras).
- **Snapshot is unchanged**: `/cameras/{id}/snapshot?width=&fps=` keeps `note_tile` (picture rate, not analysis). The wall sends a lower `fps` (console constant).
- **Audit**: `recording.start` must be written before the recorder starts (today it is written after). Done together with 022's actor change.
