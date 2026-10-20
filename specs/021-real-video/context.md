# Implementation context: Real video for camera views

**Written by `/speckit-plan` on 20 Oct 2026, against spec 020's branch
`claude/remote-access-020-eb54ac` at `bc4311a`** (this spec's own branch is at `ced3b63` +
the 021 docs; 020 must be merged first — it owns `remote.py`, `/connection`, the remote limits
and the Caddyfile entries this builds on).

Read this **before** opening any source file. Then open the named anchors only.

> Verify before trusting. If this disagrees with the code, the code wins. Search for the
> symbol; do not trust a line number.

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/api/app.py` | `def snapshot(` | plain `def` (runs on a thread). `width` rounds up via `_tile_width` to `TILE_WIDTHS = (320, 480, 640, 960, 1280)`, `TILE_QUALITY = 70`. Remote: `remote.is_remote(request)`, `remote.remote_config(request)`, `app.state.snapshot_pacer.wait_turn(...)` → 429. `worker.source.note_tile(fps)`; `worker.snapshot_jpeg(...)`; header `X-Frame-Stale` | unchanged — it is the fallback |
| `engine/vg/api/app.py` | `async def stream(` | MJPEG `multipart/x-mixed-replace; boundary=vgframe`; 960 px local, `limits.live_width`/`live_fps` remote; `app.state.remote_streams.open/touch/close` slots, 429 "Close another live view first."; `with worker.source.watched()`; exits on `SHUTTING_DOWN` | unchanged — opened-view fallback |
| `engine/vg/api/app.py` | `async def connection(` | returns `S.Connection(remote, tile_interval_seconds, live_width, live_fps, live_views, live_views_open)` | optionally add `video_per_account` / `video_open` so the app can say "Close another camera first" without guessing |
| `engine/vg/api/app.py` | `app.state.snapshot_pacer = remote.SnapshotPacer()` | where per-app state is created in `create_app` | create `app.state.video = VideoService(...)`; start its thread with the app, stop it on shutdown |
| `engine/vg/auth/deps.py` | `ADMIN_WRITE_PREFIXES` | contains `"/cameras"`: **any POST under `/cameras` is admin-only**. `OPERATOR_WRITE_PREFIXES = ("/vehicles/alerts",)` — "keep this list tiny". `PUBLIC_PATHS` = healthz, login, register | **no edit**: put the routes under the new top-level `/video`, which no list names, so any signed-in role may use them |
| `engine/vg/api/schemas.py` | `class CameraView(Wire)` | `id, name, area, offline, captured_at, stale, people_count, boxes, zone, count_line, snapshot_url, stream_url, faces` | add `video: VideoState \| None = None` |
| `engine/vg/api/schemas.py` | `class CameraSource(Wire)` | `ip` is the **masked** source, built only by `CameraConfig.redacted_source()`; `features, faces, enabled, gate, direction, fps, rotate, from_config` | add masked `video_source`; add raw `video_source` to `AddCameraRequest` and the edit request |
| `engine/vg/api/schemas.py` | `class Connection(Wire)` | spec 020's remote facts | see `connection` above |
| `engine/vg/config.py` | `class CameraConfig` | `source: str`; validated in a loader that raises `ConfigError(f"{where}.source: …")`; `${VAR}` expansion from `.env` (`_ENV_PATTERN`) | add `video_source: str = ""`; same expansion and masking; add the `video:` block and its validation |
| `engine/vg/ingest/store.py` | `CameraStore._migrate` | loop over `(table, column, ddl)` tuples doing `ALTER TABLE … ADD COLUMN` when missing; `SCHEMA` string has the `camera` table | add `("camera", "video_source", "TEXT NOT NULL DEFAULT ''")` to both |
| `engine/vg/api/live.py` | `_probe_channel` | per recorder channel: fills `{channel}` into a template, `CameraSource(f"probe-{channel}", source, target_fps=1)`, returns `S.DvrChannel(...)`; `PROBE_CONCURRENCY = 8` | also probe the derived second stream; read FOURCC/size/fps; report the plain-language result |
| `engine/vg/api/live.py` | `_remote_access_stage` (020) | builds one `S.PipelineStage(key="remote_access", name="Remote access", detail=..., ...)` from a background reader; listed in `health()` | copy it for `key="video"`, add next to it in `health()` |
| `engine/vg/video.py` | (new) | — | `VideoService`: urllib client, 5 s thread, path sync, session counts and idle kick, `offer()`, `state()` |
| `deploy/Caddyfile` | `@api path …` | one long line of first path parts, ends `… /connection /connection/* /push /push/*`; `@page` excludes `*/clip */snapshot */stream …` by Accept `text/html` | append `/video /video/*` |
| `web/vite.config.ts`, `mobile/vite.config.ts` | `API_PATHS` | fixed list of proxied first path parts | add `/video` |
| `web|mobile/src/components/CameraFrame.tsx` | `const useStream = live && …`, `usePolling`, `showing`, `refreshMs`, `chipIsLive`, `StreamImage` | `showing = onScreen && pageVisible && !paused`. `useConnection()` gives `remote`. Remote tile label via `tilePaceLabel`; stale via `remoteFailed`/`siteReachable`. `aspect` state comes from the loaded image. Overlay boxes positioned inside `pictureRect(frameSize…, aspect)`. Picture `onError` decides remote stale vs camera fault | add the video branch before `useStream`/`usePolling`; keep both as fallback; video `<video>` sits in `pictureRect` with `object-fit: fill` |
| `web|mobile/src/services/frame.ts` | `tileRefreshMs(onScreen)` | `SCREEN_PICTURES_PER_SECOND = 120`, `TILE_MAX_FPS = 15`, `TILE_MIN_FPS = 2` | callers pass the count of **picture** tiles only (video tiles leave the budget) |
| `web|mobile/src/services/video.ts` | (new, shared) | — | `openVideo`, `lastFrameAt` |
| `web|mobile/src/components/CameraSources.tsx` | `template: 'rtsp://{host}:{port}/Streaming/Channels/{channel}'`, Dahua `subtype=0` | channel templates per make; `.replace('{channel}', c.channel)` | show the derived second stream, editable, with its check result |
| `tools/make_release.ps1` | `if ($file -like '*.zip')` | **unzips any zip and copies `unzip\caddy.exe`** — a second zip breaks it; then `foreach ($need in 'caddy.exe', 'WinSW-x64.exe', 'netbird_installer_*…')` | unzip by name; add `mediamtx.exe` to the required list |
| `deploy/install.ps1` | `$Services = @('visionguard-engine', 'visionguard-front')` | step 6 copies WinSW per service, `sc.exe sdset`, startup task; firewall rules TCP 443/8443 Private/Domain; remote rule on NetBird's alias from `100.64.0.0/10`; `$netbirdIp` known in step 5 | add the service, a UDP 8189 rule beside each, write `$netbirdIp` into `webrtcAdditionalHosts` |
| `deploy/uninstall.ps1` | `$Services = @(…)`, `Step 3 'Firewall'` | removes rules by display name | add both |
| `deploy/control/VisionGuardControl.cs` | `const string FrontService = "visionguard-front";`, `Read(…)` | status computed from engine + front only | add `VideoService` name, start/stop it, show its own line; do not let it change "running" |
| `engine/tests/test_media_auth.py` | `MEDIA = re.compile(r"/(snapshot|stream|clip|crop)$|/chunks/")`; `get_routes` keeps **GET only** | a POST route is invisible to it today | include `/video` and its POST/DELETE methods; add it to `test_the_media_routes_are_found` |

## 2. Things to copy, not invent

- A WinSW service → copy `deploy/service/visionguard-front.xml`.
- A background status reader feeding System Health → copy spec 020's NetBird reader and
  `_remote_access_stage`.
- Remote decision → `remote.is_remote(request)`; never re-implement the address check.
- Counting a remote account's open views, freeing silent ones → `app.state.remote_streams`
  (`open`, `touch`, `close`) in spec 020.
- Camera table column → `CameraStore._migrate` tuple list.
- Probing a stream → `_probe_channel` with `CameraSource(...)`.
- Stopping a stream when its element leaves the page → `StreamImage` in `CameraFrame.tsx`
  (removes `src`; the same lesson applies to closing a peer connection).
- Tests with a session → `authed(app, role=...)` in `conftest.py`; a real-data store by hand
  like `test_groups.py`'s `store` fixture.

## 3. Traps

- **`/cameras` writes are admin-only** (above). The video POST must not live there.
- **The media-auth test only walks GET routes** matching its regex; a new POST route would
  pass unnoticed.
- **`make_release.ps1` treats every zip as Caddy.**
- **MediaMTX's own defaults (v1.21.2, read 20 Oct 2026)**: `authInternalUsers` lets
  `any` user from any address `publish`, `read` and `playback`; RTSP, RTMP, HLS, SRT, WebRTC
  and **MoQ** are on (`moq: true`, ports 8892/8893, writes `auto.key` in the working folder);
  the RTSP server's `rtpAddress` is **`:8000`, the engine's port**. Our `mediamtx.yml` must
  replace `authInternalUsers` entirely and switch every one of those off. All key names in
  plan.md §A exist in that file; `ips` takes addresses or networks.
- **The exe is unsigned** (`Get-AuthenticodeSignature`: NotSigned), 57 MB, file version 1.21.2.
- **Camera passwords**: `source` may carry `user:pass@`. Add paths through the API only; never
  write them to `mediamtx.yml`, a log line or a wire type. Confirm that MediaMTX's API does not
  write its config back to disk.
- **Key pictures**: a new viewer sees nothing until the camera's next I-frame. Hikvision
  defaults can be 2–4 s apart; the 1 s/2 s start targets need the installer's setting.
- **`requestVideoFrameCallback`** exists in Chrome on Windows and Android; the 2 s stall rule
  depends on it.
- **CRLF**: `api/*.py`, `services/*.ts`, `types.ts` and `STATUS.md` are CRLF. A new shared file
  in `services/` should match its neighbours; `check_parity.py` compares bytes.
- **Two `CameraFrame.tsx` copies already differ**; edit and check each.
- **Dev has no second stream**: the clip and the webcam stay on pictures. Video needs a real
  camera (quickstart Gate 0).

## 4. Baseline

- `python -m pytest engine` on this branch (`ced3b63` + 021 docs, before 020 is merged):
  **2205 passed, 14 skipped** (20 Oct 2026, 7 min 07 s), matching 020's starting figure.
- Spec 020's own note, on its branch after `565dade`: 2467 passed / 14 skipped.
- New test file: `engine/tests/test_video.py`. Extended: `test_media_auth.py`,
  `test_front.py`, `test_deploy.py`.

## 5. Still unknown

- The JSON shape of `/v3/paths/list` and `/v3/webrtcsessions/list` (the zip carries no API
  description; read it off the running program during Gate 0). Config key names are settled.
- Whether MediaMTX lists NetBird's adapter address on its own (`webrtcIPsFromInterfaces`), or
  needs `webrtcAdditionalHosts` — Gate 0 shows it.
- Whether the site's cameras use B-frames or H.264+ on the second stream.
- How long MediaMTX keeps a WebRTC session after a phone vanishes; the 10 s idle kick covers
  it either way.
