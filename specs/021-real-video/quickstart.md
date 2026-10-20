# Quickstart: proving real video works

Everything here needs a **real camera** with a second stream set to H.264, about 640 px,
15 frames a second, I-frame interval 15, H.264+ off, at most 512 kbit/s — the recorded clip
and the laptop webcam have no second stream and stay on pictures.

## Gate 0 — before any code is written

Needs: `mediamtx_v1.21.2_windows_amd64.zip` in `deploy\bin` (downloaded and checked
20 Oct 2026, see research.md); the NetBird policy allows UDP 8189 to the workstation; Windows
may ask to allow `mediamtx.exe` through the firewall on first run — allow it on **Private**
networks only; a real camera with its sub-stream set as above.

1. Unzip to a scratch folder. Run `mediamtx.exe` with `deploy\mediamtx.yml`, plus one path for
   the camera's sub-stream and, for this trial only, the WHEP page on the LAN address.
2. Office PC: open the WHEP page. Phone, mobile data, Wi-Fi off, NetBird on: open it through
   the NetBird address.
3. Record for each: plays yes/no · pictures a second (`chrome://webrtc-internals`,
   `framesPerSecond`) · seconds behind a running clock · Mbit/s (`bytesReceived` over 60 s) ·
   seconds from open to first picture.

**Pass**: plays on both, 15/s, ≤ 1.5 s behind, ≤ 0.5 Mbit/s, first picture ≤ 2 s. If the
phone cannot play it, stop and re-plan (plan.md, Fallbacks).

## Automated checks (every task)

```powershell
python -m pytest engine
cd web; npx.cmd tsc -b --force; cd ..\mobile; npx.cmd tsc -b --force; cd ..
python tools/check_parity.py
python -m pyflakes engine/vg engine/tools engine/tests
```

## Drills (built kit, real camera and phone)

| | Do | Expect (spec) |
|---|---|---|
| V1 | PC on site, 16 tiles on screen | each 15+/s (SC-202) |
| V2 | phone on mobile data, Cameras page, 4 tiles on screen, 10 minutes; then one camera opened on Smooth, 5 minutes | each tile 15+/s; ≤ 2 Mbit/s together; the opened camera ≤ 1.5 Mbit/s (SC-201, SC-206) |
| V3 | scroll a tile into view | moving within 1 s on site, 2 s away (SC-204) |
| V4 | camera pointed at a running clock, compare with the screen | ≤ 1 s behind on site, 1.5 s away (SC-207) |
| V5 | stop the `visionguard-video` service | pictures with the reason within 5 s; System Health says so; detection and recording carry on; video back by itself within 1 minute (SC-209) |
| V6 | pull the camera's cable while watching | LIVE gone within 2 s; NO SIGNAL as today (SC-210) |
| V7 | 16 cameras watched; Task Manager on `mediamtx.exe` and the engine | ≤ 1 extra core; AI rates on System Health unchanged (SC-208) |
| V8 | opened camera in **both apps**, on site and away: count pictures a second on Smooth and Clear; then Smooth → Clear → Smooth | 15+/s each time (SC-203); switches within 2 s (SC-212); Clear on the phone says it uses more data |
| V9 | a feature page (Track or Counting) side by side with the same camera on pictures | boxes on the same people (SC-211) |
| V10 | install the new Setup.exe on a clean Windows 11 with Defender on | installs; three services running; nothing quarantined |
| V11 | no session: `curl -X POST https://<address>/video/<camera>` from LAN and from a NetBird device | refused both times (P10-FR-215) |
| V12 | scroll a moving tile off screen and watch its `bytesReceived` in `chrome://webrtc-internals`; then close every page showing that camera and watch MediaMTX's path list | the tile's video is closed within 2 s; the camera is let go within 30 s (SC-205) |
| V13 | the enrolment page's live view with video playing | no recognition boxes and no names, exactly as with pictures (P10-FR-214) |

Record results in `specs/021-real-video/drills.md` with the date, devices and figures.
