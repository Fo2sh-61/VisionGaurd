# Data model: 027

**No new table, no new stored field.** Everything below is built on each request from what the engine already holds. Wire types subclass `Wire` (snake_case in Python, camelCase on the wire, `extra="forbid"`). `Fraction` and `Confidence` are not used here.

## CameraWall (response of `GET /cameras/wall`)

| Field | Type | Notes |
|---|---|---|
| `cameras` | `CameraWallEntry[]` | Every configured camera: running, down and switched off. Order = roster order. |
| `up` | int | Entries with `signal == "ok"`. |
| `total` | int | Entries that are enabled (`signal != "off"`). Equals `site().cameras_total`. |
| `at` | `Instant` | When the engine built it, via `_instant(now, clock)`. |

## CameraWallEntry

| Field | Type | Notes |
|---|---|---|
| `id`, `name`, `area` | str | From config. `area` may be empty. |
| `features` | `Literal[...]` list | Configured features that have a tile meaning: `attendance`, `counting`, `vehicles`, `intrusion` (and `stations` after 025). Knife, lost-items and track are left out. |
| `signal` | `"ok" \| "down" \| "off"` | `ok` / `down` is `CameraWorker.status == "ok"` (the 10 s rule). `off` is in `registry.disabled`. `auth` maps to `down`. |
| `age_seconds` | float \| None | Seconds since `source.health.last_frame_at`. None = never a picture. None for `off`. |
| `last_picture_at` | `Instant \| None` | `last_frame().captured_at`. |
| `picture_every_seconds` | float | `1 / config.fps`. Lets the console avoid calling a slow camera Stale. |
| `readings` | `WallReading[]` | One per feature in `features` **except** `attendance`. |
| `ring` | `WallRing \| None` | See below. |

## WallReading

| Field | Type | Notes |
|---|---|---|
| `feature` | str | One of the four above. |
| `kind` | `"count" \| "plate" \| "zone" \| "unavailable"` | |
| `count` | int \| None | `kind == "count"`: people in frame now (person detector). |
| `plate` | `WallPlate \| None` | `kind == "plate"`: `plate_display`, `at: Instant`, `status` (`known`/`unknown`/`blacklist`/`expired`). No owner name. |
| `zone_active` | bool \| None | `kind == "zone"`: a scene is running now. |
| `reason` | `"camera_down" \| "subsystem_off" \| "not_measured" \| "none_today" \| None` | Set for `unavailable`; a coded reason, never a sentence. |
| `detail` | str \| None | The subsystem's own start-up error (`people_error`, `vehicles_error`, `zones_error`), already plain text. |

`none_today` is a fact (no plate read yet today), not a zero, and the console words it that way.

## WallRing

`level: "amber" | "red"`, `cause: "unknown_plate" | "zone_breach" | "station_away" | "station_absent"`, `since: Instant`.
`unknown_plate` is amber, `zone_breach` is red. Station causes are filled by 025.

## Attendance reading (admin only)

`GET /attendance/cameras` returns `dict[str, int | None]`: faces identified right now per camera, `None` = no recent measurement (not zero). Same shape as `/cameras/counts`.

## Changed existing types

- `CameraView.boxes`: filled only when `camera_view(..., feature=...)` names a feature. The default is now empty, so `/cameras` carries no names.
- `S.OVERLAY_FEATURES` is split: `IDENTITY_FREE_OVERLAYS = ("counting", "intrusion", "weapons", "lost", "vehicles")` for `/detections`, `FACE_OVERLAYS = ("attendance", "track")` for `/faces`. `OVERLAY_FEATURES` stays as their union so `test_api.py`'s pin against `_boxes` still holds.
- `GateAlert`: unchanged. The camera link is made in `_open_gate_passes()`.

## Console-only state (never sent to the engine)

| State | Where | Notes |
|---|---|---|
| grid size 2, 3, 4 | URL `n` + `sessionStorage` | try/catch; page works without storage |
| chip, search, page | URL `f`, `q`, `p` | the wall opens with the same values |
| `PictureState` | `format.ts::pictureState()` | `live \| stale \| noSignal \| off`. Stale = `ageSeconds > max(3, 2 × pictureEverySeconds)` while `signal == "ok"` |
