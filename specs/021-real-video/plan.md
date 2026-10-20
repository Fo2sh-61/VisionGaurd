# Implementation Plan: Real video for camera views

**Branch**: `claude/angry-engelbart-324ed2` | **Date**: 20 Oct 2026 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), [research.md](research.md), and a read of the code on spec 020's
branch `claude/remote-access-020-eb54ac` at `bc4311a` (020 is not merged; this plan builds on
it). Where a document disagreed with the code, the code is reported.

## Summary

**The fact that decides it**: MediaMTX hands the camera's own H.264 second stream to the
browser as WebRTC video **without re-making it**. Watching costs the workstation almost
nothing, needs no graphics card, and is two to four times lighter on the network than
today's pictures at a larger size and a true 15 a second.

The engine stays the only door. A browser asks the **engine** for video; the engine checks
the session and the remote limits, then passes the request to MediaMTX, which listens on
the workstation itself only. The video then flows straight from MediaMTX to the browser on
one new port, **UDP 8189**, open to the factory network and the NetBird network only. Boxes
are drawn exactly as today, over the video. When video cannot play, the tile goes back to
today's pictures by itself and says why.

## What exists today (020 branch, `bc4311a`)

- **Tiles** poll `GET /cameras/{id}/snapshot?width=&fps=` (`app.py` `snapshot`): a JPEG per
  request, widths 320–1280, quality 70. The screen shares 120 pictures a second
  (`frame.ts` `SCREEN_PICTURES_PER_SECOND`), at most 15 a tile (`TILE_MAX_FPS`). Remote: one
  320 px picture every 0.5 s, paced by `remote.SnapshotPacer`.
- **Opened camera** is MJPEG, `GET /cameras/{id}/stream`: 960 px on site; remote 720 px at
  10/s, at most 2 per account (`remote_streams`).
- **Off-screen tiles ask for nothing**: `useOnScreen` (IntersectionObserver) plus page
  visibility and `paused` make `showing` in `CameraFrame.tsx` (two copies, web and mobile).
- **One address per camera**: `CameraConfig.source` (`config.py`), stored in the `camera`
  table (`ingest/store.py`). Camera setup builds it from a template, Hikvision
  `/Streaming/Channels/{channel}` (channel `101` = main), Dahua `subtype=0`
  (`CameraSources.tsx`). No second stream anywhere. PLAN §9 D3: site cameras have one.
- **The AI reads the main stream** through OpenCV in `ingest/source.py`; it decodes every
  frame whether watched or not. This plan does not touch it.
- **Permissions by path** (`auth/deps.py`): **`/cameras` is admin-only for writes**
  (`ADMIN_WRITE_PREFIXES`), so a POST under `/cameras` would lock operators out of video.
- **Kit**: `deploy/versions.txt` pins caddy (zip), WinSW, NetBird (msi);
  `tools/make_release.ps1` **assumes the only zip is Caddy's** (copies `unzip\caddy.exe`).
  Services are WinSW XMLs in `deploy/service/`, listed in `$Services` in `install.ps1` and
  `uninstall.ps1`; the VisionGuard Control app hard-codes the two service names.

## Data flow

| Flow | Path |
|---|---|
| Watching a tile | camera second stream (RTSP, H.264) → MediaMTX path, pulled only while someone watches, let go 30 s after → WebRTC over UDP 8189 (LAN, or inside the NetBird tunnel) → `<video>` in `CameraFrame`; boxes from `/cameras/{id}/detections` drawn over it, as today |
| Starting video | `CameraFrame` → `POST /video/{camera}?quality=smooth` with the browser's offer → Caddy → engine: session, remote limit, camera has video? → MediaMTX `127.0.0.1:8889/<path>/whep` → answer → browser. `DELETE /video/{camera}/{session}` when the tile leaves the screen |
| Fallback | video refused, failed, or stalled 5 s → today's snapshot polling, labelled with the reason; video is tried again every 15 s while the tile is on screen |
| Status | engine thread polls MediaMTX's API every 5 s → System Health "Video" row and each camera's `video` field |

## Requirement → mechanism

| Requirement | Smallest mechanism |
|---|---|
| FR-201 15+/s everywhere | camera's own stream passed through; WebRTC plays at the camera's rate |
| FR-202 off screen gets nothing | existing `showing` flag closes the video; reopened when back |
| FR-203 fetched once, let go after 30 s | MediaMTX `sourceOnDemand`, `sourceOnDemandCloseAfter: 30s`; one path per camera and quality |
| FR-204 tiles use the second stream | new `video_source` on the camera, derived from `source` by default |
| FR-205 Smooth / Clear | two paths per camera: second stream and main stream; a two-button switch on the opened view; choice in `localStorage` |
| FR-206 no AI slowdown, ≤ 1 core for 16 | pass-through; nothing in the engine's capture changes |
| FR-207 ≤ 0.5 Mbit/s a tile | set on the camera by the installer; the engine measures it from MediaMTX's byte counts and warns |
| FR-208 workstation decides, 8 per remote account | the engine is the only way in to MediaMTX; it counts sessions per account and reaps silent ones |
| FR-209 LIVE only while frames arrive | `requestVideoFrameCallback` time of last frame; 2 s without one drops LIVE |
| FR-210 fallback both ways | `CameraFrame` keeps today's polling path and switches to it |
| FR-211 System Health | one pipeline stage from the 5 s poll, never raises |
| FR-212 setup checks the stream | the existing channel probe opens the second stream too and reads its codec, size, rate |
| FR-213/214 own boxes, no identities | `CameraFrame` overlay code unchanged; video drawn with `object-fit: fill` inside `pictureRect` |
| FR-215 session on every video request | new prefix `/video`, covered by the default "every route needs a session"; media-auth test extended |
| FR-216 private network only | MediaMTX API and WHEP on 127.0.0.1; UDP 8189 open on Private/Domain and on NetBird's adapter from 100.64.0.0/10 only |
| FR-217 passwords stay home | camera addresses go to MediaMTX through its local API at runtime; never written to its file, never in a wire type |
| FR-218 program fails alone | its own WinSW service with restart-on-failure; the engine treats it as optional |
| FR-219 pinned, installed by Setup | `versions.txt` line; `make_release.ps1` unzips by name; third service in `install.ps1` |
| FR-220 nothing else changes | no edit to `ingest/source.py`, recording, clips or snapshots |

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React + Vite (web/, mobile/), PowerShell
(deploy), C# (VisionGuard Control).

**Primary Dependencies**: **MediaMTX v1.21.2** (MIT, `mediamtx_v1.21.2_windows_amd64.zip`,
28.6 MB), owner's pick; Mohamed downloads it into `deploy\bin`. No new Python or npm package:
the engine talks to MediaMTX with the standard library; browsers use their own WebRTC.

**Storage**: one new column, `camera.video_source TEXT NOT NULL DEFAULT ''` (empty = derive
from `source`), added by `CameraStore._migrate`. Everything else is in memory.

**Testing**: pytest with a fake MediaMTX (a stdlib HTTP server in a fixture); both
`npx.cmd tsc -b --force`; `tools/check_parity.py`; pyflakes; drills on a real camera and
phone (quickstart.md).

**Target Platform**: the site's Windows 11 workstation; Chrome/Edge on Windows, Chrome on
Android.

**Performance Goals**: spec SC-201 to SC-212 — 15+/s on every visible tile and opened camera;
moving within 1 s on site, 2 s away; ≤ 1 s behind the camera on site, 1.5 s away; ≤ 0.5 Mbit/s
a tile; ≤ 1 core for 16 watched cameras.

**Constraints**: one extra program; no conversion between video formats; no public address;
camera passwords never leave the workstation; LAN and remote behave the same except for the
remote limit.

**Scale/Scope**: up to 16 tiles moving on a PC, 4–6 on a phone; 1–5 remote people per
factory; pilot-size camera counts (the 208-camera load is phase P8).

## Constitution Check

| Principle | How this plan keeps it |
|---|---|
| I. Real-time | LIVE only while frames arrive (2 s rule); delay measured against a clock; no queue anywhere — WebRTC drops late frames |
| II. Isolation | boxes per feature, unchanged; video needs no feature; a stopped video service touches nothing else |
| III. Truthful | fallback names its reason (enum, worded in `format.ts`); System Health row from a real poll with its time; a tile never shows a starting or stalled video as LIVE |
| IV. Security | `/video` needs a session like every route; MediaMTX reachable only from the workstation except its media port; passwords only in memory and the existing database |
| V. Complete | Setup installs, starts, restarts and removes it; camera setup checks the stream; the owner checklist gains the one NetBird policy change |
| Workflow | regression tests for both traps found (admin-write prefix, media-auth regex) ship with the change |

**Gate result**: passes. The extra program and port are allowed by the owner (Complexity
Tracking).

## Design

### A. The program (Setup)

- `deploy/versions.txt`: one line for the MediaMTX zip, hash from the release's checksum file,
  after Mohamed downloads it and agrees to the line.
- `tools/make_release.ps1`: unzip by name — `caddy_*.zip` gives `caddy.exe`,
  `mediamtx_*.zip` gives `mediamtx.exe` (and its `LICENSE`) — and require `bin\mediamtx.exe`.
- `deploy/mediamtx.yml` (new, committed, no camera in it). Everything not used is off, and
  only the workstation itself may read or use the API:

  ```yaml
  logLevel: warn
  logDestinations: [file]
  logFile: C:/VisionGuard/logs/video.log
  api: yes
  apiAddress: 127.0.0.1:9997
  rtsp: no
  rtmp: no
  hls: no
  srt: no
  playback: no
  metrics: no
  pprof: no
  webrtc: yes
  webrtcAddress: 127.0.0.1:8889
  webrtcLocalUDPAddress: :8189
  webrtcLocalTCPAddress: ''
  webrtcIPsFromInterfaces: yes
  webrtcAdditionalHosts: []      # install.ps1 writes the NetBird address here
  webrtcICEServers2: []
  authInternalUsers:
    - user: any
      ips: ['127.0.0.1/32', '::1/128']
      permissions: [{action: read}, {action: api}]
  pathDefaults:
    sourceOnDemand: yes
    sourceOnDemandStartTimeout: 10s
    sourceOnDemandCloseAfter: 30s
    rtspTransport: tcp
  paths: {}                      # the engine adds them through the API
  ```

- `deploy/service/visionguard-video.xml` (new): copy of `visionguard-front.xml` — WinSW,
  LocalService, restart after 10 s three times, logs in `C:\VisionGuard\logs`.
- `deploy/install.ps1`: `visionguard-video` joins `$Services` (installed, rights, startup
  task, started); firewall rule **UDP 8189** on Private/Domain, and on NetBird's adapter from
  100.64.0.0/10 only, next to the TCP 443/8443 rules; the NetBird address goes into
  `webrtcAdditionalHosts` the same way it goes into `tls.names`. `deploy/uninstall.ps1`
  removes both.
- VisionGuard Control (`deploy/control/VisionGuardControl.cs`): the third service is started
  and stopped with the other two and shown on its own line. A stopped video service never
  makes VisionGuard read as stopped: the engine and the front still decide that.
- Owner checklist (020's `owner-checklist.md` B4): the NetBird policy gains **UDP 8189**.

### B. The engine

- **`engine/vg/video.py` (new, one file)** — `VideoService`:
  - talks to MediaMTX's API at `127.0.0.1:9997` with `urllib`;
  - a background thread every 5 s: lists paths and WebRTC sessions; makes MediaMTX's paths
    match the camera roster (`vg-<n>-smooth` from `video_source`, `vg-<n>-clear` from
    `source`; added, changed or removed), which also restores them after MediaMTX restarts;
    kicks sessions whose bytes have not moved for 10 s; keeps the per-account count; keeps
    what System Health and `CameraView.video` read;
  - `offer(camera_id, quality, sdp, user, remote)` → `(answer_sdp, session_id)`, or raises
    `SubsystemUnavailable` (not running) or a refusal (limit, no such stream).
  - A missing MediaMTX is **not set up**, never an error at engine start.
- **Config** (`config.py`, `engine.yaml`): a `video:` block — `enabled: true`,
  `api: http://127.0.0.1:9997`, `whep: http://127.0.0.1:8889`, `remote_per_account: 8`,
  `idle_kick_s: 10`. Validated like every block; defaults hold when absent.
- **Second stream**: `CameraConfig.video_source: str = ""`; `engine.yaml` key of the same name;
  the new column. Empty means derived: Hikvision `/Streaming/Channels/NN1` → `NN2`, Dahua
  `subtype=0` → `subtype=1`; anything else (webcam, file, other makes) has none. Editable on
  the camera form.
- **Routes** (`api/app.py`): `POST /video/{camera_id}?quality=smooth|clear` (body
  `application/sdp`, answer `201 application/sdp` with `X-Video-Session`), and
  `DELETE /video/{camera_id}/{session_id}` (own sessions only). A new top-level prefix
  **`/video`**, deliberately outside `/cameras`, so any signed-in role may watch while
  camera settings stay admin-only. Added to the Caddyfile's `@api` list and both Vite
  `API_PATHS`.
- **Remote** (`remote.is_remote`, spec 020): a remote account may hold `remote_per_account`
  videos; one more is `429` "Close another camera first". Clear is allowed remotely.
- **`CameraView.video`** (`schemas.py`): `{smooth: bool, clear: bool, codec_clear, reason}` where
  `reason` is an enum — `not_set_up`, `not_running`, `no_second_stream`, `h265`,
  `unreachable` — worded in `format.ts`. A second stream slower than 15 a second still plays
  (at its real rate); that is a camera-setup warning, not a reason.
- **System Health**: a `video` pipeline stage: not set up / running (cameras being watched,
  viewers, when checked) / not running (reason); per-camera problems in its detail. Built
  from the poll; cannot raise (AGENTS rule 7).
- **Camera setup check**: `_probe_channel` (and the edit form's test) also opens the second
  stream with the existing `CameraSource` probe and reads codec (FOURCC), size and rate. It
  reports "Set the sub-stream to H.264 on the camera's own page", "…to 15 frames a second",
  or "No sub-stream at this address". The result is kept in memory for `CameraView.video`;
  MediaMTX's track info overwrites it whenever someone watches.

### C. Both apps

- **`services/video.ts` (new, shared, parity-checked)**: `openVideo(cameraId, quality)` makes a
  receive-only `RTCPeerConnection` with no ICE servers, waits for local candidates (at most
  1 s), posts the offer, applies the answer, returns `{stream, close}`; `close` sends the
  `DELETE`. Plus `lastFrameAt(video)` using `requestVideoFrameCallback`.
- **`CameraFrame.tsx` (each copy)**:
  - when `camera.video.smooth` and `showing`: a `<video muted playsInline autoplay>` laid
    over `pictureRect` with `object-fit: fill`, so a 4:3 second stream of a 16:9 camera
    lands where the boxes expect;
  - while starting, the last snapshot under it with its own time and "Starting";
  - not `showing` → `close()`;
  - LIVE only while a frame came in the last 2 s, else "No picture since 14:05:31";
  - 5 s without a frame, or a refusal → `close()`, today's polling, the reason shown, a
    retry every 15 s;
  - video tiles leave the 120/s picture budget, so picture tiles share it among themselves.
- **Opened view (`live`)**: a Smooth / Clear switch (`chip-btn`). The choice is kept in
  `localStorage` (try/catch; Smooth when unreadable). Clear is disabled with its reason when
  `camera.video.clear` is false or the browser cannot decode the main stream's codec
  (`RTCRtpReceiver.getCapabilities`). Away from site, Clear says "uses more data". MJPEG stays
  as the opened view's fallback.
- **Words**: `i18n/*` (shared) in English and draft Arabic; sentences in `format.ts`.

### D. Not changed

Capture and AI (`ingest/source.py`), recording, event clips and snapshots, the snapshot and
MJPEG routes (now the fallback), spec 020's remote picture limits (fallback only).

## Test plan

**Gate 0 — before any code** (needs the download and one NetBird policy line): MediaMTX run by
hand with `deploy/mediamtx.yml` and one real camera's sub-stream; its own WHEP page opened on
the office PC and on the phone over mobile data. Record: does it play, pictures a second,
seconds behind a clock, Mbit/s, seconds to first picture. If the phone cannot play it, stop
and re-plan (Fallbacks) before building anything.

**Automated** (each with its regression test in the same commit):
- `video_source` derivation: Hikvision, Dahua, webcam, file, unknown.
- Path sync with a fake MediaMTX: added, changed, removed, restored after a restart; no
  password in any log line, wire type or file.
- `POST /video`: no session refused (LAN and NetBird); an `it`/operator account allowed
  (guards the `/cameras` admin-write trap); unknown camera 404; service down 503 with the
  reason; 9th remote video 429; `DELETE` of another account's session 404.
- Silent session kicked after 10 s and its place freed.
- System Health `video` stage: not set up, running, not running; always 200.
- `test_media_auth.py` covers `/video` POST and DELETE; `test_front.py` covers `/video` in
  the Caddyfile; `test_deploy.py` covers the new service XML and `mediamtx.yml` (API and
  WHEP on 127.0.0.1, every unused server off, no `publish` permission).
- Gates: `python -m pytest engine` (count must rise), both `tsc -b --force`,
  `tools/check_parity.py`, pyflakes.

**Drills** (real camera and phone, owner present): [quickstart.md](quickstart.md) V1–V10.

## Risks (biggest first)

1. **The phone cannot reach UDP 8189 through NetBird** on some network. Gate 0 finds out. Then:
   TCP on the same port (one line, one firewall rule).
2. **Slow start**: a new viewer waits for the camera's next key picture. With Hikvision's
   default interval (often 2–4 s) SC-204 fails. The installer sets the I-frame interval to
   the frame rate (one a second); the drill measures it.
3. **"Smart" codecs (H.264+) or B-frames** make browsers' WebRTC stutter. The installer turns
   H.264+ off on the second stream; Gate 0 and V1 check by eye.
4. **Defender flags the unsigned exe**. V10 installs on a clean Windows 11; if flagged, the
   owner reports a false positive to Microsoft before the pilot.
5. **Recorders' connection limits**: Clear adds a second pull of the main stream while
   watched. Two pulls per watched camera at most; drill on the real recorder.
6. **Boxes trail fast movement** slightly, because video now runs faster than the AI. The AI
   is unchanged; V9 checks they still land on the person.
7. **One maintainer**: the version is pinned and the kit carries its own copy.

## Fallbacks (in order)

1. TCP 8189 instead of UDP (config + firewall).
2. Today's pictures — always there, by design (P10-FR-210).
3. go2rtc's MSE through 443 (research.md), if WebRTC cannot work on the site's networks.

## Project Structure

### Documentation (this feature)

```text
specs/021-real-video/
├── spec.md
├── research.md
├── plan.md            # this file
├── data-model.md
├── contracts/video-api.md
├── quickstart.md      # Gate 0 and the drills
├── context.md         # hand-over for the implementing chat
└── checklists/requirements.md
```

### Source Code (repository root)

```text
deploy/versions.txt                  + MediaMTX line (owner's OK)
deploy/mediamtx.yml                  new
deploy/service/visionguard-video.xml new
deploy/install.ps1, uninstall.ps1    third service, UDP 8189 rule, NetBird address
deploy/Caddyfile                     /video in @api
deploy/control/VisionGuardControl.cs third service
tools/make_release.ps1               unzip by name, require mediamtx.exe
engine/engine.yaml, engine/vg/config.py   video: block; camera video_source
engine/vg/ingest/store.py            video_source column
engine/vg/video.py                   new — VideoService
engine/vg/api/app.py                 /video routes; health stage wiring; probe
engine/vg/api/live.py                CameraView.video; health stage; probe of the second stream
engine/vg/api/schemas.py             VideoState on CameraView; video_source on camera wire types
engine/tests/test_video.py           new
engine/tests/test_media_auth.py, test_front.py, test_deploy.py   extended
web|mobile/src/services/video.ts     new, shared
web|mobile/src/components/CameraFrame.tsx   each copy
web|mobile/src/components/CameraSources.tsx second-stream field and check (each copy)
web|mobile/src/services/format.ts, i18n/*   words (shared)
web|mobile/vite.config.ts            /video in API_PATHS
specs/020-private-remote-access/owner-checklist.md   B4: UDP 8189
```

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| One more program (MediaMTX) | turns camera streams into browser video without re-making them | the engine making video itself puts every byte through the Python process that runs the AI, and its bundled FFmpeg licence is unclear (research.md) |
| One more port (UDP 8189) | WebRTC media cannot go through Caddy's 443 | go2rtc's MSE through 443 has weaker protection and no release since Jan 2026; kept as fallback 3 |
