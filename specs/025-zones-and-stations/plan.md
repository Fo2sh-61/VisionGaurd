# Implementation Plan: Restricted zones with drawn areas, and Work stations

**Branch**: `console-v2-plans` (planning; spec folder `025-zones-and-stations`) | **Date**: 10 Nov 2026 | **Spec**: [spec.md](spec.md)

## Summary

The fact that decides the shape: **a zone and a station are the same thing seen two ways: a
polygon on a camera, and a rule about who stands in it.** The engine already has the
polygon test (`point_in_polygon` + `feet_point`, `features/people.py:32-58`, with a test
file), the scene log, the clip recorder, the three-clips rule, the alert hook and the shared
person detector. What it does **not** have is anything below camera level: today a zone *is*
a camera (`live.py::zones()`, `_restricted_ids`, table `camera_restricted`). So 025 is: one
table of drawn areas, the zone state machine re-keyed from camera to zone, one new worker for
stations, and one editor component that both pages use.

What is new, smallest form first:

1. **One `area` table** (zones and stations, one row each, soft-deleted so logs survive) in a
   new `engine/vg/areas.py`, with the polygon check, the watched-hours check and a one-time
   import (old whole-camera zones, then `engine.yaml` polygons).
2. **Zones**: `ZonesWorker` keeps its state machine and its constants; only the dictionary key
   changes from camera id to zone id, and "inside" becomes the feet test. `zone_scene` gains
   `zone_id`. The "alert after N seconds" timing is one extra check in the same machine.
3. **Stations**: `features/stations.py` + `events/stations.py`. State changes (rare) are stored
   as **segments** with a heartbeat, so today's times are a sum, a restart leaves a visible
   gap, and nothing is estimated.
4. **Assigned person**: a per-frame face check on the people standing in the area, using the
   *same* `FacePipeline` object enrolment already built (no second model copy). It returns a
   yes/no. It keeps no name, no body, nothing (rule 2).
5. **One shared editor** (`AreaEditor.tsx`) over the existing `CameraFrame`; one polygon overlay
   component; two pages (`Intrusion.tsx` rewritten, `Stations.tsx` new).
6. **Per-area Notify**: `AlertEvent` gets one optional field naming its own channels;
   Settings rows become the default a new area copies.

## Technical Context

**Language/Version**: Python 3.14 on Windows (dev); no 3.11+ syntax in `engine/` (Jetson
test bench: 3.10.12). TypeScript/React (Vite). **Dependencies**: nothing new.
**Storage**: the existing SQLite file. New tables: `area`, `station_segment`, `station_event`;
one new column `zone_scene.zone_id`.
**Testing**: `python -m pytest engine` (baseline 1940 passed, 14 skipped at `5ea8e67`), `npx tsc -b
--force` web and mobile, pyflakes, `tools/check_parity.py`.
**Target**: Jetson Orin Nano (8 GB shared, no hardware encoder). The SSH Jetson is a test bench
with nothing of VisionGuard on it: SC-406, SC-407-on-Jetson, SC-508 and SC-509-on-Jetson wait
for the new board (see quickstart). Person detection runs where the model is configured; the
face check is OpenCV on the processor, like attendance (nobody promised it a GPU path).
**Scale**: ~40 cameras; the number of areas per camera is data, not a constant.

## Constitution Check

| Gate | Holds? | How |
|---|---|---|
| Rule 1 / 2 | Yes | Zones name nobody. The station face check is `bool` per frame; the worker holds no person id, no body, no embedding between frames. A test pins that a stranger after the assignee never reads On station. |
| Rule 3 | Yes | Both pages draw the polygon and no identity: `CameraFrame detections={false}` for stations; zones keep today's nameless `intrusion` overlay. |
| Rule 4 / 5 | Yes | No fixture path. Times are sums of stored segments; gaps are "not watched". "Can faces be read here" is **measured** (a face-width reading), never guessed. |
| Rule 6 | Yes | Polygon stored and sent as fractions; server refuses anything outside 0..1, crossing itself, or nearly a line. |
| Rule 7 / 8 | Yes | `GET /zones`, `/stations` stay 200 with a status per row; a worker that fails to start becomes a Capability and a System Health row with the reason. |
| Rule 9 | Yes | Both workers take the shared `SharedDetection` and nothing else. Saving an area on a camera adds the camera's own `intrusion` / `stations` feature; no other feature is touched. |
| Audit first | Yes | Every create / edit / pause / delete / acknowledge calls `_log` before the write. (The trail is still memory-only until spec 018; unchanged.) |
| Server-side permissions | Yes | By path in `auth/deps.py`: `/stations` joins `ADMIN_WRITE_PREFIXES`; `/zones` already is; acknowledge is one anchored pattern for IT. |

No violations; no complexity tracking needed.

## Each requirement to the smallest mechanism

| FR | Mechanism |
|---|---|
| 401-403, 411 | `areas.validate_polygon` (server) and the same three checks in `AreaEditor` (client); feet test reused, not rewritten. |
| 404, 405 | `GET /zones` returns a `status` per zone (person in zone, clear, paused, outside hours, camera offline, detector stopped) built from the worker's last result (3 s freshness, `base.py:RESULT_TTL_SECONDS`). The four tiles are sums over that list; "entries today" is the row count of today's log. No summary endpoint. |
| 406, 416 | `PATCH /zones/{id}` `{enabled}` already exists; add `paused_by/paused_at` columns and `_log` first. `/zones` is already admin-write. |
| 407, 507, 508 | One function `areas.watching_at(area, local_dt, hours)`; working hours come from 022's `LiveStore.hours()` (so a Settings save applies at once, no restart). |
| 408 | Zone machine: scene opens as today (2 s confirm); the alert goes at open when N = 0, else when the same scene has stayed N seconds. Reuses the one `SceneStore.on_open` hook. |
| 409, 410, 413 | The log stops hiding replaced entries (`breaches()` passes `include_replaced=True`); the console says "No clip kept". Delete is a soft delete; its scenes keep `zone_id`. |
| 415 | One-time import inside `AreaStore`: `camera_restricted` rows + cameras with scene history become full-frame zones with `id = camera id` (so old scenes already match); `engine.yaml` polygons become drawn zones; each row carries `import_note` for anything its schedule could not express. |
| 417 | The existing constants (`CONFIRM_SECONDS`, `GAP_SECONDS`, `ALERT_AGAIN_AFTER_SECONDS`) stay as they are. |
| 418, 419 | The workers re-read areas from `AreaStore` on every save (`set_areas`); a start that cannot read the table sets `zones_error` / `stations_error` and the page says so. |
| 420 | Clips already use the zone recorder's own thread; 022 supplies the x264 pipe. Nothing added; measured on the board (SC-406). |
| 422, 521 | `AlertEvent.channels` (optional): when set, `_record` uses it instead of the Settings row. Zone and station rows store the choice; Home's in-app list reads it per area. |
| 501-503, 506 | `/stations` CRUD, one form in the shared editor. |
| 510-514 | `StationsWorker._present()` returns a bool per frame; the face check runs only when a station has an assignee and someone stands in the area. |
| 513, 531 | Face reach: the worker keeps the largest face width seen in the area over 10 minutes; below 80 px (config) the station counts anyone and says so. At edit time `GET /stations/face-reach` reads one YuNet pass of the camera's last picture. |
| 515-517 | One small state machine (see research R4); thresholds in `engine.yaml` under `stations:`. |
| 518-520, 522 | Segments table (`on`, `away`, `absent`); "not watched" = watched time with no segment. Events table for the log. |
| 521, 523, 524 | `StationStore.on_alert` hook, like `scenes.on_open`; new alert kind `station`; facts `station`, `assignee`, `limit` added to the allowed list. Acknowledge writes an event row (and Home's item leaves because Home reads the same events). |
| 525-529 | `Stations.tsx` over `GET /stations`; badge source added to 022's `useNavBadges`. |
| 532, 534 | No fixture; the `stations` feature is added to the camera form's list (`CameraSources.tsx FEATURES`), which is what the rate recommendation reads. |

## Project Structure

### Documentation

```text
specs/025-zones-and-stations/
├── plan.md  research.md  data-model.md  quickstart.md  context.md
└── contracts/api.md
```

### Source Code (what changes)

```text
engine/vg/areas.py                NEW  Area, AreaStore, validate_polygon, watching_at, one-time import
engine/vg/events/zones.py         zone_id column, per-zone counts, delayed alert, "hours" end reason
engine/vg/features/zones.py       state keyed by zone; feet test; alert-after; per-zone recording owner
engine/vg/features/stations.py    NEW  StationsWorker (subclass FeatureWorker)
engine/vg/events/stations.py      NEW  StationStore: segments, events, acknowledge, orphans
engine/vg/config.py               FEATURES += "stations"; StationsConfig (confirm seconds, face px)
engine/vg/alerts/{events,store,catalogue,service}.py   kind "station", AlertEvent.channels, facts, templates
engine/vg/auth/deps.py            "/stations" admin-write; acknowledge pattern for IT
engine/vg/api/app.py              /zones POST/PATCH/DELETE, /stations*, _start_stations, wiring
engine/vg/api/live.py             zones(), breaches(), stations(), attention(), health stage, capability
engine/vg/api/schemas.py          Zone (richer), ZoneCreate/Update, Station*, AlertKind += station
engine/vg/api/store.py            MockStore: demo stations (demo mode only)
engine/tests/test_areas.py  test_zones_areas.py  test_stations.py   NEW
web/src/pages/{Intrusion,Stations}.tsx   web/src/components/{AreaEditor,AreaPicture}.tsx  (new: last two, Stations)
web/src/components/{CameraSources,AlertSettings}.tsx   web/src/app/{routes,useAttention,useNavBadges*}.ts(x)
web/src/services/{api,wire,format}.ts*   web/src/types.ts*   web/src/i18n/{keys,en,ar.draft}.ts*
web/src/app/navigation.ts*        add the stations entry
engine/engine.yaml                stations: block; remove the two polygon zones after import ships
* = byte-shared with mobile/src: edit, copy, run tools/check_parity.py.
```

**Structure Decision**: existing layout, four-files rule for stations (the model file is "reuse
`infer/persons.py` and `infer/faces.py`", so there is no new `infer/` file). One shared module
`areas.py` exists only because zones and stations share the same row, polygon rules and hours rule.

## Order of work

1. `areas.py` + tests (polygon, hours, import). 2. Zones machine re-keyed, tests updated, old
whole-camera behaviour proven identical on the recorded clip with a full-frame polygon (SC-404).
3. Alert kind + per-area channels. 4. Stations worker + store + tests. 5. API + permissions.
6. Console: editor, Zones page, Stations page, nav, badges, strings. 7. Checks; by eye with
`.\dev.ps1 up -Clip -DevSignIn admin`, then `-DevSignIn it`. 8. Jetson items wait for the board.

## What this plan deliberately does not do

- No shared "areas" API: `/zones` and `/stations` stay separate (different fields, different
  permissions, and 022 already points the phone at `/zones`).
- No per-person tracking inside a station, no "who was there" record, no name cache (rule 2).
- No second face model, no GPU path promised for the face check.
- No overnight stations (see open question), no per-weekday schedules, no multi-assignee.
- No phone page for stations. The phone's Zones page keeps working through the unchanged
  `getZones`/`setZoneEnabled` fields; its "whole camera" wording becomes untrue for drawn zones
  and is a follow-up for the phone spec.
- No rename of `/intrusion`, `ToolId 'intrusion'` or the `intrusion` alert kind (wire names stay).

## Open (no `[NEEDS CLARIFICATION]` in the spec; these are plan choices to confirm)

1. **Night stations.** Stations use `from < to` on one day (the spec only grants midnight crossing
   to zones). A night booth 22:00 to 06:00 needs one more rule; either answer fits the tables.
2. **Starting values** `leave_confirm_seconds: 8`, `return_confirm_seconds: 3`,
   `min_face_px: 80` are tuned on the recorded clip (SC-502), as the spec's Assumptions say.
3. **Old whole-camera zones** import only for cameras that were ever switched (a row in
   `camera_restricted`) or have scene history; cameras that never were become nothing.

## Build order and shared pieces (cross-check, 10 Nov 2026)

Order: **022 first**, then **023, 024 and 025 in parallel**, then **027** (its wall readings use 024's plate-trouble state and 025's per-zone status and `alerted` flag).

Shared pieces have one owner, so no spec re-plans them:
- `auth/deps.py`: 022 built `OPERATOR_WRITE_PATTERNS` (a tuple of compiled regexes, POST/DELETE only, checked right after `OPERATOR_WRITE_PREFIXES`) and moved `/track` and `/tracking` into `ADMIN_PREFIXES`. 024 (Gone) and 025 (station acknowledge) each **add one line** to `OPERATOR_WRITE_PATTERNS`; if Gone or acknowledge is not POST/DELETE, widen the method check there. 027 creates `ADMIN_PATTERNS` (checked before the safe-method return) for `/cameras/{id}/faces`.
- `ToolId` and `NAV`: 022 did **not** add placeholders. 025 adds `stations` (`ToolId`, `NAV` after Restricted zones, `nav.stations.*` keys); 027 adds `cameras` (`ToolId`, `NAV` last in the main section, `nav.cameras.*` keys). Each touches only its own entry, so they do not collide.
- `useNavBadges` (`web/src/app/useNavBadges.ts`, fetching through `web/src/services/navBadges.ts`): 022 built the vehicle-alerts slot and an attendance slot counting not-arrived. 023 replaces the attendance rule with its own (late plus not arrived, after the cut-off); 025 adds zones and stations.
- `useAttention`: 022's sidebar card uses `useAlertFeed`, which already has a status. 027 adds the additive `status` field to `useAttention` itself for the wall.
- `LiveStore._register` (`live.py`, around 3921): 022 swaps its hours read for `self.hours()`. 023 then rewrites the function on top of that.
- The audit-first example is `live.py::delete_pass` (~L1828). There is no `delete_vehicle_pass`. `dismiss_alert` is at ~L1946.
- **Assigned-person names and IT** (cross-check #1). Reads under `/stations` are open to IT, and 022 keeps people's names from IT. So `GET /stations` sends `assigneeId` only, and the admin console looks the name up through `/people`, which is admin-only. An IT user sees "Assigned to a person". The outgoing alert still names the person, as the owner decided on 10 Nov 2026. Whether IT recipients get that alert is set by the recipients list.
