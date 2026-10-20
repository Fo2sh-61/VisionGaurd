# Tasks: Real video for camera views

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/video-api.md](contracts/video-api.md),
[quickstart.md](quickstart.md), [context.md](context.md) (read it before opening any file).

**Tests**: required. Every change ships with its test in the same commit (AGENTS.md).

**User stories** (the spec groups its scenarios; these labels map them):

| Story | Priority | Spec scenarios | Requirements |
|---|---|---|---|
| US1 Tiles move as video | P1 🎯 MVP | 1, 2, 4, 5, 6, 12, 13 | P10-FR-201–204, 206, 209, 213, 214 |
| US2 Opened camera, Smooth / Clear | P1 | 3, 7 | P10-FR-205 |
| US3 Light enough away from site | P2 | 8, 9, 14, 15 | P10-FR-207, 208, 215, 216 |
| US4 Honest when video cannot play | P2 | 10, 11 | P10-FR-210, 211, 212 |

Kit, service and firewall (P10-FR-217–220) are Phase 1, because every story needs them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, nothing unfinished in between)
- Both apps have their own `CameraFrame.tsx` and `CameraSources.tsx`: a task naming
  `web|mobile` means **both copies**, checked in both.

---

## Phase 0: Gate 0 — owner steps and a one-camera trial (blocks everything)

**Purpose**: prove a phone on mobile data plays MediaMTX video through NetBird before
any code is written. If the phone cannot play it, stop and re-plan (plan.md, Fallbacks).

- [ ] T001 Merge spec 020's branch `claude/remote-access-020-eb54ac` into this branch, **only
  on Mohamed's OK**; re-run `python -m pytest engine` and record the new baseline in
  `specs/021-real-video/context.md` §4
- [ ] T002 Mohamed downloads `mediamtx_v1.21.2_windows_amd64.zip` (28.6 MB) from
  github.com/bluenviron/mediamtx releases into `deploy\bin\`, and checks its SHA-256 against
  the release's checksum file
- [ ] T003 Mohamed adds **UDP 8189** to the site's NetBird policy (next to TCP 443/8443)
- [ ] T004 Read the downloaded release's own `mediamtx.yml`; write `deploy/mediamtx.yml` from
  plan.md §A with every key name checked against it (unused servers off, API and WHEP on
  127.0.0.1, read and api only from 127.0.0.1)
- [ ] T005 Gate 0 trial per `specs/021-real-video/quickstart.md`: MediaMTX by hand, one real
  camera's sub-stream, office PC and phone on mobile data; record plays / pictures a second /
  delay / Mbit/s / time to first picture in `specs/021-real-video/drills.md`

**Checkpoint**: Gate 0 passes → build. Fails → re-plan with Mohamed.

---

## Phase 1: Setup — kit, service, firewall, front door

- [ ] T006 Add the MediaMTX line to `deploy/versions.txt` (Mohamed's OK to commit the hash)
- [ ] T007 [P] `tools/make_release.ps1`: unzip each zip by name (`caddy_*` → `caddy.exe`,
  `mediamtx_*` → `mediamtx.exe` + `LICENSE`) and require `bin\mediamtx.exe`
- [ ] T008 [P] `deploy/service/visionguard-video.xml` (copy of `visionguard-front.xml`:
  WinSW, LocalService, restart ×3, logs) and a check in `engine/tests/test_deploy.py`
- [ ] T009 [P] `engine/tests/test_deploy.py`: `deploy/mediamtx.yml` keeps API and WHEP on
  127.0.0.1, every unused server off, no `publish` permission, no path in the file
- [ ] T010 `deploy/install.ps1`: `visionguard-video` in `$Services`; firewall rule UDP 8189 on
  Private/Domain and on NetBird's adapter from 100.64.0.0/10; NetBird address into
  `webrtcAdditionalHosts`. `deploy/uninstall.ps1`: remove both
- [ ] T011 [P] `deploy/control/VisionGuardControl.cs`: start and stop the third service with
  the other two, show it on its own line, never let it decide "running"
- [ ] T012 [P] `deploy/Caddyfile` `@api`: add `/video /video/*`; `engine/tests/test_front.py`
  checks it; `web/vite.config.ts` and `mobile/vite.config.ts` `API_PATHS`: add `/video`
- [ ] T013 [P] `specs/020-private-remote-access/owner-checklist.md` B4: the policy gains UDP 8189

---

## Phase 2: Foundational — engine pieces every story uses

- [ ] T014 [P] `engine/vg/config.py` + `engine/engine.yaml`: the `video:` block (data-model.md),
  validated, defaults when absent; tests in `engine/tests/test_video.py`
- [ ] T015 [P] `video_source` on `CameraConfig` (`engine/vg/config.py`), the `camera` table and
  `_migrate` (`engine/vg/ingest/store.py`), masked like `source`; derivation Hikvision
  `NN1→NN2`, Dahua `subtype=0→1`, none otherwise; tests for each make, webcam and file
- [ ] T016 `engine/vg/video.py` `VideoService`: urllib client to MediaMTX's API, 5 s thread,
  paths `vg-<n>-smooth` / `vg-<n>-clear` kept equal to the camera roster and restored after a
  MediaMTX restart, `offer()`, `state()`; "not set up" when disabled or absent. Tests with a
  fake MediaMTX (stdlib HTTP server fixture): add, change, remove, restore; **no password in
  any log line or file**
- [ ] T017 `engine/vg/api/app.py`: create and stop `app.state.video`; `POST /video/{camera_id}`
  and `DELETE /video/{camera_id}/{session_id}` per contracts/video-api.md; 503 with the reason
  when MediaMTX is down. Tests: no session refused; an operator (non-admin) account allowed;
  unknown camera 404; another account's `DELETE` 404
- [ ] T018 [P] `engine/tests/test_media_auth.py`: walk POST/DELETE too, include `/video`, and
  add it to `test_the_media_routes_are_found`
- [ ] T019 [P] `engine/vg/api/schemas.py` `VideoState`; `CameraView.video` filled in
  `engine/vg/api/live.py` from `VideoService.state()`; `MockStore` (`engine/vg/api/store.py`)
  sends `video` null; mirror the type in `web|mobile/src/types.ts`
- [ ] T020 [P] `web/src/services/video.ts` (copied byte-for-byte to `mobile/src/services/`):
  `openVideo(cameraId, quality)` → `{stream, close}`, receive-only, no ICE servers, ≤ 1 s
  candidate wait, `DELETE` on close; `lastFrameAt(video)` via `requestVideoFrameCallback`;
  `python tools/check_parity.py` passes

**Checkpoint**: the engine answers `/video` against a running MediaMTX; nothing on screen yet.

---

## Phase 3: US1 — Tiles move as video (P1) 🎯 MVP

**Goal**: every tile on screen plays its second stream at the camera's rate, on site and
away, and stops when off screen.

**Independent test**: quickstart V1, V3, V4, V6, V9 on a real camera.

- [ ] T021 [US1] `web|mobile/src/components/CameraFrame.tsx`: when `camera.video.smooth` and
  `showing`, a `<video muted playsInline autoplay>` inside `pictureRect` with
  `object-fit: fill`; the last snapshot under it with its own time and "Starting" until the
  first frame; `close()` when not `showing`
- [ ] T022 [US1] Same files: LIVE only while a frame arrived in the last 2 s, else
  "No picture since <time>"; NO SIGNAL from `camera.offline` as today; "not analysed" stays
  its own line
- [ ] T023 [US1] Same files: 5 s without a frame, or a refused offer → `close()`, today's
  polling, reason shown; retry video every 15 s while on screen
- [ ] T024 [P] [US1] `web/src/services/frame.ts` (shared): `tileRefreshMs` counts picture tiles
  only; callers in both `CameraFrame.tsx` pass that count
- [ ] T025 [P] [US1] Words in `web|mobile/src/i18n/*` (English + draft Arabic) and
  `web|mobile/src/services/format.ts` (shared): Starting, No picture since, video reasons
- [ ] T026 [US1] Gates (both `tsc -b --force`, parity, pytest, pyflakes); then drills V1, V3,
  V4, V6, V9 into `specs/021-real-video/drills.md`

**Checkpoint**: tiles move; boxes land on people; LIVE never on a frozen picture.

---

## Phase 4: US2 — Opened camera with Smooth / Clear (P1)

**Goal**: the opened view plays video, with a Clear switch for the main stream.

**Independent test**: quickstart V8.

- [ ] T027 [US2] `engine/vg/video.py` + `engine/vg/api/live.py`: `clear` and `codec_clear` in
  `VideoState` from the main stream's probe and MediaMTX's track info; tests
- [ ] T028 [US2] `web|mobile/src/components/CameraFrame.tsx` (`live`): Smooth / Clear
  `chip-btn` switch; choice in `localStorage` (try/catch, Smooth when unreadable); Clear
  disabled with its reason when `video.clear` is false or
  `RTCRtpReceiver.getCapabilities('video')` lacks the codec; "uses more data" when remote;
  MJPEG stays the fallback
- [ ] T029 [US2] Gates; drill V8 into `drills.md`

---

## Phase 5: US3 — Light enough away from site (P2)

**Goal**: the workstation, not the screen, holds remote viewing to its limits.

**Independent test**: quickstart V2 and V11.

- [ ] T030 [US3] `engine/vg/video.py` + `/video` route: per-account count of remote sessions
  (`remote.is_remote`), 9th → 429 "Close another camera first."; tests
- [ ] T031 [US3] `engine/vg/video.py`: kick a session whose bytes have not moved for
  `idle_kick_s`, freeing its place; tests with the fake MediaMTX
- [ ] T032 [P] [US3] `S.Connection` (`engine/vg/api/schemas.py`, `app.py` `connection`) gains
  the video limit and open count; `web|mobile` `CameraFrame.tsx` shows the 429 reason
- [ ] T033 [US3] `engine/vg/video.py`: Smooth Mbit/s from MediaMTX byte counts; above 0.5 →
  a warning in the System Health detail and camera setup; tests
- [ ] T034 [US3] Drills V2 (pictures a second and Mbit/s for 10 minutes) and V11

---

## Phase 6: US4 — Honest when video cannot play (P2)

**Goal**: every reason video is missing is said plainly, in the tile, System Health and
camera setup.

**Independent test**: quickstart V5 and V7.

- [ ] T035 [US4] `engine/vg/api/live.py`: `video` pipeline stage (copy `_remote_access_stage`):
  not set up / running / not running, with when checked; per-camera reasons in its detail.
  Tests: all three states, and the page stays 200
- [ ] T036 [US4] `engine/vg/api/live.py` `_probe_channel` and the edit-form test: also probe
  the second stream (FOURCC, size, rate) and the main stream's codec; plain-language result
  ("Set the sub-stream to H.264 on the camera's own page", "…15 frames a second",
  "No sub-stream at this address"); tests
- [ ] T037 [P] [US4] `web|mobile/src/components/CameraSources.tsx`: second-stream field (derived
  value shown, editable) and its check result; `video_source` on the add/edit requests
- [ ] T038 [US4] Drills V5 and V7

---

## Phase 7: Polish

- [ ] T039 Drill V10: new Setup.exe on a clean Windows 11, Defender on
- [ ] T040 [P] `STATUS.md` (CRLF — keep it) and `docs/PLAN.md`: what is real, with the measured
  figures from `drills.md`
- [ ] T041 Final gates: `python -m pytest engine` (count up from the T001 baseline), both
  `npx.cmd tsc -b --force`, `python tools/check_parity.py`, pyflakes

---

## Dependencies & order

- **Phase 0 blocks everything.** T001–T003 are Mohamed's; T004 needs T002; T005 needs T002–T004.
- **Phase 1** after Gate 0. T006 needs T002. The rest are independent files ([P]).
- **Phase 2** after Phase 1's T012 (route reachable). T016 needs T014–T015; T017 needs T016.
- **US1** needs Phase 2. **US2** needs US1's `CameraFrame` video branch (T021). **US3** and
  **US4** need only Phase 2 and can run beside US1/US2.
- **Polish** last.

## Parallel examples

- Phase 1: T007, T008, T009, T011, T012, T013 together.
- Phase 2: T014, T015, T018, T019, T020 together; then T016 → T017.
- After Phase 2: US1 (apps) beside US3 + US4 (engine), one person each — never two people
  in the same `CameraFrame.tsx`.

## Implementation strategy

1. Gate 0. Nothing is built until a phone has played one camera.
2. Phase 1 + 2, then **US1 alone** → drills → show Mohamed tiles moving (MVP).
3. US2, then US3 + US4, then Polish.
