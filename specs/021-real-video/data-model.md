# Data model: Real video for camera views

Small on purpose: one stored field, the rest lives in memory and is rebuilt from MediaMTX
every 5 seconds.

## Stored

**Camera** (existing `camera` table, `CameraConfig`) — one new field:

| Field | Type | Rule |
|---|---|---|
| `video_source` | text, default `''` | The camera's second stream (RTSP). Empty = derived from `source`: Hikvision `/Streaming/Channels/NN1` → `NN2`; Dahua `subtype=0` → `subtype=1`; any other source has none. May hold a password exactly as `source` does, and is masked the same way whenever shown. |

Clear always uses the existing `source` (the main stream the AI reads). No column for it.

**engine.yaml** — a `video:` block (seed only; defaults hold when absent):

| Key | Default | Rule |
|---|---|---|
| `enabled` | `true` | `false` = video not set up; every camera uses pictures |
| `api` | `http://127.0.0.1:9997` | must be a loopback address |
| `whep` | `http://127.0.0.1:8889` | must be a loopback address |
| `remote_per_account` | `8` | 1–32 |
| `idle_kick_s` | `10` | 5–60; a session whose bytes have not moved this long is closed |

## In memory (engine, `VideoService`)

**Video path** — one per camera and quality, mirrored into MediaMTX.

| Field | Meaning |
|---|---|
| `name` | `vg-<n>-smooth` or `vg-<n>-clear`; `<n>` is a stable number per camera id, so ids with any characters are safe |
| `camera_id`, `quality` | `smooth` or `clear` |
| `source` | the RTSP address, sent only to MediaMTX's local API |
| `codec`, `width`, `height` | from the setup probe, then from MediaMTX while watched |
| `bytes_per_s` | measured from MediaMTX's byte counts while watched |

**Video session** — one per open video in a browser.

| Field | Meaning |
|---|---|
| `id` | MediaMTX's WebRTC session id |
| `user_id` | the account that opened it |
| `remote` | from `remote.is_remote(request)` at opening |
| `camera_id`, `quality` | what it shows |
| `last_bytes`, `last_moved_at` | for the idle kick |

States: opened by `POST /video/…` → open → closed by `DELETE`, by the idle kick, or by
MediaMTX (viewer gone). A remote account's count is its open sessions with `remote` true.

**Service state** — `not_set_up` (disabled, or MediaMTX not installed) · `running` · `not_running`
(with the reason: refused, timed out, bad answer) · `checked_at`.

## On the wire

**`CameraView.video`** (`VideoState`):

| Field | Type |
|---|---|
| `smooth` | bool — a tile may try video |
| `clear` | bool — the opened view may offer Clear |
| `codec_clear` | `h264` · `h265` · null — the app checks its own decoder before offering Clear |
| `reason` | enum or null: `not_set_up`, `not_running`, `no_second_stream`, `h265`, `unreachable` |

`reason` describes why `smooth` is false. Words for it live in `format.ts` and `i18n/*`.

**Camera setup wire types** (`CameraSource`, `AddCameraRequest`, the edit request): gain
`video_source` — masked in `CameraSource`, raw only in requests an administrator sends.
