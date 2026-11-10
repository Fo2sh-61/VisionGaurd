# Implementation Plan: Cameras page, single camera and full-window wall

**Branch**: `console-v2-jetson` (spec folder `027-camera-wall`) | **Date**: 10 Nov 2026 | **Spec**: [spec.md](spec.md)
**Builds on**: [022 plan](../022-console-v2-shell/plan.md). Roles, `useAttention`, toasts, tokens, RTL rules, the IT recording rule: **from 022**.

## Summary

The fact that decides the shape: **today's tiles already cost the engine too much and leak names.** A tile that draws an overlay polls `/cameras/{id}/detections`, and that poll renews the camera's analysis boost (`app.py` `detections()` → `note_interest`). Sixteen tiles would raise sixteen cameras at once. The same endpoint, and the `GET /cameras` list, also hand IT the name-carrying face boxes (`live.py::camera_view` default → `_face_boxes`). So the plan is mostly *taking things away*, plus one small read.

1. **One new read, `GET /cameras/wall`**: every camera, one request, polled every 2 s however many tiles exist. It carries state, picture age, features, one reading per feature and a ring. Its type has no name or attendance field, so it is safe for IT by construction.
2. **Names closed by path.** The name-carrying overlay moves to `GET /cameras/{id}/faces`, admin-only by one pattern in `auth/deps.py`. `/detections` becomes identity-free for everyone. The attendance reading lives under `/attendance/cameras`, already admin-only after 022.
3. **A `boost=false` flag** on both overlay reads. Grid tiles send it; the wall draws no overlay at all.
4. **Stale is console-side**, worked out from the picture age the new read sends. The engine keeps its two words (up, down).
5. **The wall is a route outside the shell** (`/wall`), with a lower picture budget than the grid.

## Technical Context

Python 3.10-safe engine code (no 3.11+ syntax). React/TypeScript console. SQLite untouched: **no new table**. New engine code is one store method and its schema. Test bench Jetson: nothing installed; Jetson figures wait for the new board.
**Scale**: camera count is an input (1 to about 40, 208 target). Tile pictures are the existing JPEG snapshot, never MJPEG, except the single camera.

## Constitution Check

| Gate | Holds? | How |
|---|---|---|
| I Stale never Live | Yes | Four states from age: Live, Stale, No signal, Switched off. A down tile shows its last picture marked old. |
| III Truthful | Yes | Every reading is a real read or says why not (`unavailable` + reason code). No capacity set means a count only. |
| Rule 1, 3 | Yes | A tile asks for its own feature's overlay; none falls back to faces. |
| Rule 4 | Yes | No fixture in the live path (`MockStore` only serves `-Mock`). |
| Rule 7 | Yes | `/cameras/wall` answers 200 with `unavailable` readings when a subsystem is missing. |
| Rule 9 | Yes | A reading needs only its own feature. |
| IV Server-side permissions | Yes | By path: `/faces` and `/attendance/cameras` admin-only. IT never receives a name from any camera read. |
| Scale / Jetson | Open, honestly | Picture budget is a console constant until the soak test (FR-624, the open question). |

## Each requirement → the smallest thing that satisfies it

| FR | Mechanism |
|---|---|
| 601, 604 | Page state in the URL (`?n=3&f=plates&q=gate`); grid size also kept in `sessionStorage` (try/catch). Search is a console-side filter over name and area. |
| 602, 603, 605 | Chips and counts computed from `GET /cameras/wall` entries (`features`, `signal`). No Signal = `signal === 'down'` and enabled. Switched off = `signal === 'off'`. |
| 606, 609, 610 | `readings[]` on each entry: `count`, `plate`, `zone` or `unavailable` + reason code. Console writes the sentences in `format.ts`. |
| 607, 615 | `ageSeconds` + `lastPictureAt`; `pictureState()` in `format.ts`. Stale when age > max(3 s, 2 × the camera's own picture gap). A down tile loads one still picture (new `still` prop on `CameraFrame`), marked old with its age. |
| 608 | Tile feature = chip feature; under All the first identity-free feature. `/detections` only. Admin Attendance tiles use `/faces`. |
| 611–614 | New `CameraView` component (route `cameras/:id`, and a layer over the wall). Reuses `CameraFrame live` and `RecordButton`. Address from existing `GET /sources` for admins only, through a stronger `redact_source()`. |
| 616–621 | `pages/CameraWall.tsx` on route `/wall`, no sidebar. Dark tokens from 022. Counts from the wall read, alerts from 022's `useAttention`. Rings from `ring` on the entry, named in text. |
| 622, 623 | `boost=false`; wall draws no overlay; only mounted (on-page) tiles ask; unmounting a tile stops it. |
| 624, 625 | Wall picture budget constant (lower than grid) in `frame.ts`; tile says "slower picture". A fixed low budget, not live load sensing (rejected, below). |
| 626 | Existing `RecordButton`; one added sentence that recording uses processor time. |
| 627 | Paths above, plus `/cameras` list stops sending boxes with names. |
| 628 | Wall and top bar use `useAttention().items.length` from 022: same list as Home. The hook gets one additive `status` field, because today a failed poll and "none" both read as zero. |
| 629, 630 | i18n keys (en + ar.draft); each part (grid, readings, alerts) has its own `LoadError`. |

## Rejected as too complex

- **A request per tile** (`/cameras/{id}`): demand grows with tiles. One read for all.
- **A server-built mosaic, WebRTC, HLS**: new encoding on a board with no hardware encoder.
- **A role check inside the handler**: the pattern AGENTS.md forbids. Path rules instead.
- **Live resource sensing to slow the wall (FR-625 read literally)**: needs a trusted load figure and a feedback loop. A fixed low budget, labelled on the tile, is true and simple. Reported as a gap against the wording.
- **Browser Fullscreen API**: its own Escape would swallow ours. "Full-window" is a route without the shell.
- **A new table** for rings: they are derived from events that exist (open gate alert, running zone scene).

## Structure

```text
engine/vg/api/schemas.py     CameraWall, CameraWallEntry, WallReading, WallRing; split OVERLAY_FEATURES
engine/vg/api/app.py         GET /cameras/wall, GET /cameras/{id}/faces, boost flag, GET /attendance/cameras
engine/vg/api/live.py        camera_wall(), attendance_cameras(); camera_view default boxes off; _open_gate_passes()
engine/vg/api/store.py       MockStore.camera_wall (fixtures, for -Mock only)
engine/vg/auth/deps.py       one admin pattern for /cameras/{id}/faces
engine/vg/config.py          redact_source() (one function)
engine/tests/test_camera_wall.py   NEW
web/src/pages/{Cameras,CameraWall}.tsx   NEW      web/src/components/CameraView.tsx   NEW
web/src/app/useCameraBoard.ts            NEW      web/src/components/CameraFrame.tsx  still, quiet
web/src/app/{routes.tsx,navigation.ts*}  web/src/services/{api.ts*,wire.ts*,format.ts*,frame.ts*}  i18n*
* byte-shared with mobile/src: edit, copy, run tools/check_parity.py
```

## Order of work

1. Engine, test first: `redact_source`; `/faces` + `/detections` split and the path rule; `boost`; `camera_wall`; `/attendance/cameras`.
2. Console: api/wire/format/frame (+ mobile copy), `useCameraBoard`, `CameraFrame` props, Cameras page, `CameraView`, wall, route and nav.
3. Checks: pytest count not lower, tsc web and mobile, pyflakes, parity, `dev.ps1 up -Clip -DevSignIn admin` then `it`. Jetson soak waits for the board.

## Still open (kept open; the design fits either answer)

- **FR-625 floor**: lowest wall picture rate before showing fewer cameras per page. One constant, `WALL_MIN_FPS`, `null` today (never auto-shrinks). The owner's answer sets it.
- Stale threshold (3 s floor) and the wall budget are provisional until measured on the new Jetson.

## Build order and shared pieces (cross-check, 10 Nov 2026)

Order: **022 first**, then **023, 024 and 025 in parallel**, then **027** (its wall readings use 024's plate-trouble state and 025's per-zone status and `alerted` flag).

Shared pieces have one owner, so no spec re-plans them:
- `auth/deps.py`: 022 defines `OPERATOR_WRITE_PATTERNS` (tuple of compiled regexes, checked right after `OPERATOR_WRITE_PREFIXES`) and an empty `ADMIN_PATTERNS` (checked before the safe-method return). 022 also adds `/track` and `/tracking` to `ADMIN_PREFIXES`. 024 (Gone), 025 (station acknowledge) and 027 (`/cameras/{id}/faces`) each **add one line** to those tuples.
- `ToolId` gains `stations` and `cameras` in 022, together with their `NAV` entries hidden by a flag and the i18n key names `nav.stations.*` and `nav.cameras.*`. 025 and 027 only remove the flag.
- `useNavBadges`: 022 builds the hook and the vehicle-alerts slot, and leaves the attendance, zones and stations slots empty. 023 fills attendance (its rule: late plus not arrived, after the cut-off), and 025 fills zones and stations.
- `useAttention` gains an additive `status` field in 022 (a failed poll is not zero). 027 uses it.
- `LiveStore._register` (`live.py`, around 3921): 022 swaps its hours read for `self.hours()`. 023 then rewrites the function on top of that.
- The audit-first example is `live.py::delete_pass` (~L1828). There is no `delete_vehicle_pass`. `dismiss_alert` is at ~L1946.
