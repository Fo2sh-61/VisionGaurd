# Feature Specification: Real video for camera views

**Feature Branch**: `claude/angry-engelbart-324ed2` (spec directory `021-real-video`)
**Created**: 20 Oct 2026
**Status**: Draft — spec and plan only, nothing built, nothing downloaded
**Input**: Owner brief of 20 Oct 2026, after first using spec 020's remote access from an
Android phone on mobile data: camera pictures must move like the Hikvision app does. Any
camera picture he can see runs at least 15 pictures a second — grid tiles and an opened
camera, on the site's Wi-Fi and away over the private network, on the PC console and the
phone app. Tiles off screen run slowly or not at all and speed up as soon as they are
scrolled into view. It must be light enough for mobile data through the private network's
relay. The kit may carry **one** more free, open-source program that turns the camera
streams into video a browser plays; the owner picks it from researched candidates.

## Clarifications

### Session 2026-10-20 (Mohamed)

- Q: Which program does the kit carry? → A: **MediaMTX** — "if it's a new added free app but in
  the VisionGuard project or on the workstation, do the recommendation". It is free (MIT) and
  is installed on the workstation by Setup, inside VisionGuard. See [research.md](research.md).
- Q: What does an opened camera show? → A: a **Smooth / Clear switch** like the Hikvision app
  (P10-FR-205).
- Q: What does a tile do when video cannot play? → A: **today's pictures, labelled** with the
  reason, and back to video by itself (P10-FR-210).
- Q: A camera whose second stream is H.265? → A: **the installer sets it to H.264** on the
  camera; camera setup checks and says so. VisionGuard never converts video (P10-FR-212).

## Why this feature *(mandatory)*

Today every camera picture is a separate full photo. On site a grid tile reaches 15 a second
only while eight or fewer tiles are on screen, and drops to 10, 5 or 2 as more appear. Away
from site a tile is one photo every half second and an opened camera 10 a second, because
photos cost about ten times what video costs for the same motion. The owner compared this
with the Hikvision app, which plays 15+ a second on the same phone and network. After this
feature, every camera picture on screen is real moving video, on site and away, at a cost
mobile data can carry.

## User Scenarios & Testing *(mandatory)*

### Primary story

Mohamed is away from the factory with his phone on mobile data. He opens the VisionGuard app
and the Cameras page: every tile he can see moves smoothly, like the Hikvision app. He
scrolls down and the next tiles start moving within a couple of seconds; the ones he
scrolled past stop and cost him nothing. He opens one camera and it plays smoothly, with
that page's boxes drawn over the people as today. Back in the office, the console's wall of
cameras moves at full speed on every tile. When video cannot play for a camera, the tile
says why and shows moving pictures as today, never pretending.

**Acceptance scenarios**

*Moving pictures everywhere*

1. **Given** a phone on mobile data connected through the private network, **When** the
   operator opens the Cameras page, **Then** every tile on screen plays at 15 or more
   pictures a second and is marked LIVE.
2. **Given** a PC on the factory network with 16 camera tiles on screen, **When** the
   operator watches the wall, **Then** every tile plays at 15 or more pictures a second.
3. **Given** any page with an opened camera (Cameras, Track, enrolment, a feature page), on
   either app, on site or away, **When** it is open, **Then** it plays at 15 or more
   pictures a second with that feature's own boxes drawn over it.
4. **Given** tiles below the fold, **When** the operator scrolls them into view, **Then**
   each starts moving within 1 second on site and 2 seconds away. Until it moves it shows
   "Starting", or its last picture marked with that picture's time, never LIVE.
5. **Given** a tile scrolled away, covered by an opened camera, in a background tab, or on a
   phone whose screen is off, **When** time passes, **Then** that tile receives no video.
6. **Given** nobody is watching a camera any more, **When** 30 seconds have passed, **Then**
   the workstation no longer fetches video from it.
7. **Given** an opened camera on Smooth, **When** the operator taps Clear, **Then** within 2
   seconds the camera's main stream plays, marked Clear; if this device or camera cannot
   play it, the switch says why and the view stays on Smooth. The next camera opened on that
   device opens on Clear.

*Light enough for mobile data*

8. **Given** a phone away from site showing four moving tiles, **When** it plays for an
   hour, **Then** it uses no more than 2 Mbit/s and under 1 GB in total.
9. **Given** a phone on a slow connection, **When** the video cannot keep up, **Then** the
   tile drops LIVE and shows the time of its last picture; a slow connection is never shown
   as a broken camera.

*Honest when video is not possible*

10. **Given** the video program on the workstation is stopped or missing, **When** any
    camera page is open, **Then** within 5 seconds every tile shows moving pictures as
    today, labelled with their real pace; the opened camera and System Health say plainly
    that video is not running and why; detection, recording and alerts carry on. When the
    program is back, the tiles return to video by themselves.
11. **Given** a camera whose second stream is missing or H.265, **When** it is added or
    edited in camera setup, **Then** setup says so in plain words and what to change on the
    camera, and its tiles fall back to pictures with that reason.
12. **Given** a camera that is down, **When** its tile is on screen, **Then** it shows NO
    SIGNAL with the time of the last picture, as today.
13. **Given** video that is live while the AI is not analysing that camera, **When** the
    tile is on screen, **Then** the picture is marked LIVE and the page says the camera is
    not being analysed, with the reason — two separate facts, never merged.

*Safe*

14. **Given** a request for any camera video with no session, **When** it reaches the
    workstation from the factory network or from outside, **Then** it is refused.
15. **Given** a device that is not enrolled in the private network, **When** it tries to
    reach the video from outside, **Then** it gets no answer at all.

### Edge cases

- **The second stream has a different shape** (for example 4:3 while the main stream is
  16:9): boxes still land on the people they belong to.
- **Many people watch one camera**: the workstation fetches its video once, so a camera or
  recorder is never asked for more connections because more people are looking.
- **A recorder with a connection limit**: watching adds at most one connection per camera
  watched, only while someone watches.
- **The camera sends fewer than 15 pictures a second**: the tile plays at the camera's real
  rate and does not claim more; camera setup warns that the second stream is set too slow.
- **The workstation's own webcam and the recorded test clip** have no second stream: they
  play as video if the plan finds a way, otherwise they use pictures, labelled.
- **Video arrives faster than the boxes**: boxes keep their own pace (they move when the AI
  runs) and may trail a fast-moving person slightly; they are never drawn from an older
  camera or another feature.
- **The phone loses signal mid-video**: the tile shows the time of its last picture; the
  workstation lets that viewer go within 15 seconds.
- **Everything on the remote account at once**: a runaway screen cannot open unlimited
  videos; one too many is refused with a plain reason.

## Requirements *(mandatory)*

Numbered **P10-FR-201…**: this continues the go-live phase after spec 016 (P10-FR-0xx) and
spec 020 (P10-FR-1xx).

### Moving pictures

- **P10-FR-201**: Every camera picture on screen — grid tiles and opened cameras, in the
  console and the phone app, on the factory network and from outside over the private
  network — MUST play as video at 15 or more pictures a second whenever the camera sends at
  least that many.
- **P10-FR-202**: A tile not on screen (scrolled away, covered, background tab, screen off)
  MUST receive no video. Back on screen, it MUST move within 1 second on site and 2 seconds
  from outside.
- **P10-FR-203**: The workstation MUST fetch a camera's video only while someone is
  watching it, once however many people watch, and MUST let go within 30 seconds of the
  last viewer leaving.
- **P10-FR-204**: Tiles MUST use the camera's own smaller second stream ("Smooth").
- **P10-FR-205**: An opened camera MUST offer a **Smooth / Clear** switch, like the Hikvision
  app: Smooth is the second stream, Clear the camera's main stream. It opens on Smooth the
  first time on each device, then on whatever that device last chose. When Clear cannot play
  on this device or for this camera, the switch MUST say why and stay on Smooth. From
  outside, Clear MUST say it uses more data.
- **P10-FR-206**: Watching video MUST NOT slow the AI's analysis, and 16 cameras watched at
  once MUST cost the workstation no more than one processor core kept busy flat out.

### Light enough for mobile data

- **P10-FR-207**: From outside, a moving tile MUST use no more than 0.5 Mbit/s on average,
  and an opened camera on Smooth no more than 1.5 Mbit/s. Clear costs what the camera's main
  stream costs; it is the operator's choice and is labelled so.
- **P10-FR-208**: The workstation MUST decide what a remote viewer gets, as spec 020 does
  (P10-FR-113): a screen that ignores the rules still gets only what they allow. A remote
  account MUST have at most 8 videos open at once (a setting, default 8); one more is
  refused with a plain reason. This replaces spec 020's limit of 2 live views. A video whose
  viewer vanished MUST free its place within 15 seconds.

### Honest

- **P10-FR-209**: LIVE MUST be shown only while new pictures are actually arriving. A video
  that has shown no new picture for 2 seconds MUST drop LIVE and show the time of its last
  picture.
- **P10-FR-210**: When video cannot play for a camera — the video program is stopped or
  missing, the camera has no usable second stream, or the browser cannot play its format —
  its tiles and opened view MUST fall back to today's moving pictures with today's labels,
  and say why video is not available. The fallback MUST be automatic, both ways, without a
  page reload.
- **P10-FR-211**: System Health MUST show the video service as running, not running or not
  set up, with the reason and when it was checked, and per camera whether video is
  available and why not. It MUST stay a normal answer when the program is missing or broken
  (AGENTS rule 7), and a program that fails to start MUST show in the UI (rule 8).
- **P10-FR-212**: Camera setup MUST check a camera's second stream when the camera is added
  or edited, and say in plain words whether it can play as video and, if not, what to change
  on the camera — for example "Set the sub-stream to H.264 on the camera's own page". The
  same check MUST say whether the main stream can play as Clear.

### Overlays

- **P10-FR-213**: Each feature MUST still draw its own boxes over the video, from its own
  analysis, as fractions of the picture (AGENTS rules 3 and 6). They MUST land where they
  land on today's pictures, whatever the second stream's size or shape.
- **P10-FR-214**: A page that shows no identities today MUST show none with video.

### Safe and separate

- **P10-FR-215**: Every video request MUST need a signed-in session, from the factory network
  and from outside. Spec 020's automated test that proves this for every picture route
  (P10-FR-119) MUST cover video too.
- **P10-FR-216**: Video MUST reach outside devices only through the private network: no
  public address, no router port. Anything newly opened on the workstation MUST be open to
  the factory network and the private network only.
- **P10-FR-217**: Camera passwords MUST never reach a browser, and MUST be kept on the
  workstation no less safely than today.
- **P10-FR-218**: If the video program stops, crashes or is missing, detection, recording,
  alerts and the console MUST carry on, and the program MUST be restarted automatically.
  Video MUST need no feature switched on, and no feature may need video (AGENTS rule 9).
- **P10-FR-219**: The program MUST be pinned by version and checksum in the installer's list
  like the others, installed, upgraded and removed by Setup, and run as a service that
  starts with nobody signed in.
- **P10-FR-220**: Event snapshots and clips, recording, and the AI's own reading of the
  cameras MUST NOT change.

## Success Criteria *(mandatory)*

Each is checked on a real site camera, not only the recorded clip.

- **SC-201**: On a phone on mobile data through the private network, every tile on screen
  shows 15 or more new pictures a second, counted over one minute.
- **SC-202**: On a PC on site with 16 tiles on screen, every tile shows 15 or more new
  pictures a second.
- **SC-203**: An opened camera shows 15 or more new pictures a second in both apps, on site
  and away.
- **SC-204**: A tile scrolled into view is moving within 1 second on site and 2 seconds
  away.
- **SC-205**: A tile off screen receives no video after 2 seconds; a camera nobody watches
  is let go within 30 seconds.
- **SC-206**: Away from site, four moving tiles use no more than 2 Mbit/s together, and an
  opened camera on Smooth no more than 1.5 Mbit/s.
- **SC-207**: Video is no more than 1 second behind the camera on site and 1.5 seconds away,
  measured by pointing a camera at a running clock.
- **SC-208**: With 16 cameras watched as video, the workstation uses no more than one extra
  processor core, and the AI's measured rates and delays are unchanged.
- **SC-209**: With the video program stopped, every tile is back on pictures with the reason
  within 5 seconds, System Health says so, detection and recording are unaffected, and the
  program is running again by itself within 1 minute.
- **SC-210**: When the video freezes, LIVE disappears within 2 seconds.
- **SC-211**: Boxes land on the same people on video as on pictures, checked side by side on
  a real camera.
- **SC-212**: Switching an opened camera between Smooth and Clear shows the other stream
  moving within 2 seconds on site.

## Out of scope

- The AI reading the second stream instead of the main one (phase P8).
- Sound, pan-tilt-zoom control, and playing back recorded footage on a timeline.
- iPhones and Macs (as spec 020).
- Changing a camera's own settings from VisionGuard: the installer sets the second stream on
  the camera's own page; VisionGuard checks it and says what to change.
- More than one extra program in the kit.
- Converting video from one format to another (for example H.265 to H.264) on the
  workstation.
- A screen for editing the video settings.

## Constitution check *(mandatory)*

- **I. Real-time camera experience**: this is the feature the principle asks for. LIVE only
  while pictures arrive (P10-FR-209); delay budgets in SC-207; stale video is never shown as
  live.
- **II. Feature isolation**: boxes stay per feature (P10-FR-213); video needs no feature and
  no feature needs video (P10-FR-218).
- **III. Truthful data**: the fallback says it is a fallback and why; System Health reports
  the video service with its reason (P10-FR-210, -211). Live video and "not analysed" are
  two separate facts (scenario 12).
- **IV. Reliability, security, privacy**: a session on every video request, private network
  only, camera passwords never sent to a browser, the program restarted on failure without
  touching detection (P10-FR-215 to -218).
- **AGENTS rules**: 3 and 6 (own overlay, fractions), 4 (nothing untrue), 7 (System Health
  stays a 200), 8 (a failed program shows in the UI), 9 (no feature needs another).
- **Owner supplies all models**: no model is involved.

## Assumptions

- Site cameras have a second stream (PLAN §9 D3, answered 20 Aug 2026). The installer sets it
  on each camera to H.264, about 640 pixels wide, 15 pictures a second, no more than 0.5
  Mbit/s, as the camera makers' own apps expect.
- The limits (8 videos per remote account, 0.5 Mbit/s a tile, 1.5 Mbit/s an opened camera)
  are defaults the owner can change in configuration.
- Each remote viewer watching four tiles needs about 2 Mbit/s of the factory's upload. The
  owner checks the factory's upload speed; a slow upload shows as slow video, labelled.
- This builds on spec 020 (remote access, not yet merged) and spec 016 (Setup, HTTPS front,
  services). Spec 020's remote picture limits stay for the fallback only.
- The Smooth / Clear choice is remembered per device (the office PC can stay on Clear, the
  phone on Smooth). Tiles are always Smooth.
- The program (MediaMTX, owner's choice) is a plan decision; the requirements above would
  hold for any program that meets them.
