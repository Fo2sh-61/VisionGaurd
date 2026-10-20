# Contract: video routes

Both need a session (any role). Neither is under `/cameras`, whose writes are admin-only.
Both go through Caddy's `@api` list and the Vite `API_PATHS` of both apps.

## `POST /video/{camera_id}?quality=smooth|clear`

Start one video. `quality` defaults to `smooth`.

**Request**: `Content-Type: application/sdp`, body = the browser's WebRTC offer (receive-only
video, candidates included, no trickle).

| Answer | When | Body |
|---|---|---|
| `201` `application/sdp` + header `X-Video-Session: <id>` | started | MediaMTX's answer |
| `401` | no session | — |
| `404` | no such camera, or it has no stream for this quality | `{detail}` |
| `409` | the camera's `video` says this quality cannot play (`reason`) | `{detail, reason}` |
| `429` | a remote account already has `remote_per_account` videos open | `{detail: "Close another camera first."}` |
| `503` | MediaMTX not running (`SubsystemUnavailable`) | `{detail, reason}` |

The engine never passes a `5xx` from MediaMTX through as its own failure: it answers `503`
with the reason, and the app falls back to pictures.

## `DELETE /video/{camera_id}/{session_id}`

Close one video. `204`. `404` when the session is not this account's or is already gone —
so one account cannot close another's.

## `GET /cameras` (existing) — `CameraView.video`

See [data-model.md](../data-model.md). Read by `CameraFrame` to decide video or pictures.

## System Health (existing) — new pipeline stage

`key: "video"`, `name: "Video"`. `detail` says: not set up · running, N cameras watched, M
viewers, checked at … · not running: reason, checked at …; and lists cameras whose video is
unavailable with their reason. `healthy` false only for `not_running`. The page stays `200`
in every case.
