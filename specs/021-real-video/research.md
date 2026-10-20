# Research: which program turns camera streams into browser video

20 Oct 2026. Desk research only — nothing downloaded, installed or run. Full notes with every
source: the session notes file `021-video-program-research.md` (outside the repo); the facts
that decide the choice are repeated here. Latest releases and MediaMTX's sign-in hook were
checked again by hand the same day.

## The question

The kit may carry **one** more free, open-source program. It must take each camera's own
H.264 second stream and hand it to Chrome (Windows, Android) as video **without re-making
it**, so the workstation pays almost nothing per viewer and needs no graphics card for it.

## Candidates

| | go2rtc | MediaMTX | No new program (engine makes video) |
|---|---|---|---|
| Licence | MIT | MIT | PyAV BSD-3, but its bundled FFmpeg includes GPL parts (x264, x265); real licence of the wheel **unconfirmed** |
| Windows build | official zip, 7.4 MB | official zip, 28.6 MB | none needed (Python library) |
| Latest release | v1.9.14, **19 Jan 2026** — none in 9 months | v1.21.2, **8 Oct 2026** — 4 releases Aug–Oct 2026 | av 19.0.1, 3 Oct 2026 |
| Maintainers | one main | one main | — |
| Passes H.264 through | yes | yes | yes, if we write the packaging ourselves |
| Browser video | WebRTC; **MSE over WebSocket, which goes through Caddy's 443** | WebRTC (WHEP); low-latency HLS (slower) | whatever we build (MSE over WebSocket) |
| Extra port to open | none for MSE; 8555 for WebRTC | **8189** (UDP, or TCP) for WebRTC | none |
| Who decides who may watch | only one shared password; Caddy must guard it | **asks the engine** (`authMethod: http`), or the engine fronts it | the engine |
| Pulls a camera only while watched | likely, **unconfirmed** in its docs | yes (`sourceOnDemand`, lets go after 10 s) | ours to write |
| Status per camera (codec, size, viewers, bytes) | partly, fields unconfirmed | yes (`/v3/paths/list`) | ours to write |
| Runs as a Windows service | wrapper needed (WinSW, already in the kit) | wrapper needed; its docs give the WinSW recipe | already a service |
| All video bytes pass through Python | no | no | **yes** |

Dismissed: Janus (GPL, no Windows), SRS (no Windows build), OvenMediaEngine (AGPL, Linux),
Ant Media (Linux), ZLMediaKit (no official Windows build, mostly Chinese docs).

## Facts that hold whichever is chosen

- **Bandwidth**: a Hikvision second stream at about 640 px, H.264, 15 a second is usually set
  to 256–512 kbit/s (third-party guides, not Hikvision's own table). Today's tile at 15
  pictures a second is about 1.1 Mbit/s. So video is a half to a quarter of today's cost, at
  a larger picture. **Not measured here** — the plan measures it.
- **H.265 second streams**: Chrome plays H.265 only where the phone or PC has a hardware
  decoder; there is no software fallback. Turning H.265 into H.264 needs FFmpeg, a second
  program. Setting the second stream to H.264 on the camera is free.
- **B-frames**: browsers' WebRTC does not accept them. Camera "smart" codecs (H.264+) may add
  them; camera setup has to check the stream's profile.
- **Graphics card**: not needed when the stream is passed through.
- **Antivirus**: both programs are unsigned and both have had old Windows Defender false
  alarms. Setup must be tried on a clean Windows 11 with Defender on.
- **MediaMTX's example settings let anyone read and publish**: our own settings must allow
  reading from the workstation itself only, and switch off every server we do not use
  (RTSP, RTMP, HLS, SRT).

## Latency

No measured figures were found for either program; guides say WebRTC about half a second,
MSE about the same or a little more, HLS several seconds. The plan measures it with a camera
pointed at a running clock (spec SC-207).

## Recommendation (for the owner to decide)

**MediaMTX**, if one more port (8189) may be opened to the factory network and the private
network. It is actively released, pulls a camera only while someone watches, lets the
engine decide who may watch which camera, and reports each camera's codec, size, viewers
and bytes — which System Health and camera setup need. The cost is one more line in the
NetBird policy and one more firewall rule.

**go2rtc** is the choice if nothing new may be opened: its MSE video runs through the existing
443. It costs weaker protection (Caddy must check every request), an unconfirmed "only while
watched", and a project with no release since January.

**No new program** keeps the kit as it is but puts every video byte through the Python engine
that also runs the AI, means writing and owning the packaging and reconnects ourselves, and
needs the FFmpeg licence question answered first.
