# Implementation Plan: Car plates in console v2

**Branch**: `console-v2-plans` (spec folder `024-console-v2-plates`) | **Date**: 10 Nov 2026 | **Spec**: [spec.md](spec.md) | **Code read at**: `5ea8e67`

## Summary

The fact that decides the shape: **the engine and nearly every component for this page already exist.**
Alerts, summary, passes, fix, remove, traffic, inside now, visits, export, register, import and
"Exit estimated" are all in `app.py` and `components/Vehicle*.tsx` today. So 024 is a reorganised
page plus **six small engine changes**, one of which the spec did not name:

1. **Gone**: a small table `vehicle_gone`, one endpoint, one path rule for IT.
2. **Plate width stored** on each new pass: one column.
3. **Owner search** and **a week of passes for one plate**: two query options on `GET /vehicles/passes`.
4. **Fix keeps the original reading** (FR-307). Today `set_plate` overwrites it. One column. *(not in the spec's list)*
5. **Fix on a car still in view sends no message** (scenario 5). Today `finish_pass` would still send one for the corrected plate. One condition. *(not in the spec's list)*
6. **A failing plate reader says so** (FR-317, FR-319). Today a frame that throws, for example out of memory, is only logged, and the page keeps saying "running". One counter in `FeatureWorker`, read by the page.

Plus one pin: the plate models always run as the `.pt` at full precision, whatever `engine.yaml` says (FR-318).

Found while reading, fixed here because the page cannot be true without it: **the alert is dismissed as "acted on" the moment
Add is clicked, before anything is saved** (`VehicleAlerts.tsx` `onResolve`). It must wait for the save.

## Technical Context

Same as 022 (Python 3.10-safe engine, React/Vite console, SQLite). Storage: the existing
`vehicle.db` (`VehicleStore`): two new columns on `vehicle_pass` plus one new table. No new package,
no new model, no new store file. The Jetson reached over SSH is a test bench only: nothing is
installed on it, and every Jetson check (FR-318 to 320, SC-006, SC-007) waits for the new board.

## Constitution Check

| Gate | Holds? | How |
|---|---|---|
| Rule 4 never untrue | Yes, and fixes one | Dismiss-on-click recorded "acted on" for nothing; "running" shown over a failing reader. Both fixed. |
| Rule 5 no false precision | Yes | Gone is counted apart from observed exits and from "Exit estimated". "Last 7 days" is labelled so. |
| Rule 7/8 degradation | Yes | A failing reader becomes payload (`reason`, `camerasNote`), never a 5xx. |
| Rule 9/FR-322 isolation | Yes | Nothing here reads another feature. The strip stays `feature="vehicles"`. |
| Audit before action | Yes | Gone, fix, remove, export all `_log` first. |
| IT enforced by the engine | Yes | By path in `deps.py`; Gone is the one new IT write. |
| Settled: SFace, owner models, `.pt` | Yes | Plates pinned to `.pt` FP32 in code. |

No violations; no complexity tracking.

## Each requirement to the smallest thing that satisfies it

| FR | Mechanism |
|---|---|
| 301, 316 | Existing `Plate.tsx`; add `dir="ltr"` on the Latin line. Tab page keeps `?tab=`, `?plate=`, `?date=`, `?gate=`, `?pass=` (Ask and the bell use them). |
| 302 | `VehicleAlerts` stays. Relabel dismissals (blacklist: one button; expired: "I have dealt with it"). Add/Renew open the register form and **dismiss only after the save succeeds**. |
| 303 | Tiles filter the already-loaded rows in the browser. No endpoint. Inside now switches to the Movements tab. |
| 304 | Existing `CamGrid feature="vehicles" only`. Unchanged. |
| 305 | **The Live table is the old `VehiclePassesCard` moved to Live**, loaded with `days=1, limit=1000` so it is today only and equals the tiles (SC-003). Weak read = `needsReview` badge. Status is frozen by the engine already (changes only when the plate itself changes). |
| 306 | Detail panel reads the row: confidence, votes, new `plateWidth`. Vehicle make/colour come from the existing `GET /vehicles/register?q=plate`. |
| 307 | Existing `PlateEditor` + `PATCH .../plate`; add `read_plate` column (original) and the no-message condition. |
| 308 | Existing `DELETE`; page adds an inline confirm. |
| 309 | `q` on `/vehicles/passes` and `/vehicles/export`. Export follows day, gate and search. |
| 310, 311 | Existing Movements; Gone button; completed-visits line counts observed, estimated and by-hand apart. |
| 312, 315 | `POST /vehicles/visits/{entryPassId}/gone` + `vehicle_gone` table; path rule next to 022's recording rule. |
| 313, 314 | Existing register tab. Plate as two inputs (letters, number) joined on save. Prefill becomes `{plate, category?}` and opens **edit** when the plate is already registered. |
| 317, 319 | `FeatureWorker` counts consecutive failed frames per camera (`failing_on`); `_vehicles_state`, `_cameras_reading`, `_vehicles_stage` read it. |
| 318 | `_start_vehicles` passes `half=False, accelerate=False` and warns if the yaml asks otherwise. |
| 320 | Page identical code on both. One real risk: the plate font. See "For the owner". |
| 321, 322 | Nothing in the voting or alert text changes. |

**Rejected as too complex:** a stored visits table (visits stay derived; Gone is one mark row);
a pause-for-memory mechanism (the failing counter says the true thing with no scheduler);
a memory budget allocator across features (one process shares one CUDA context; the 022
memory reading plus SC-007 on the board is the check); a new `/vehicles/week` endpoint (two
options on the list endpoint do it); a server-side tile filter; a shared "reads" store in the page.

## For the owner (decisions made here, easy to reverse)

- **"This week" is the last 7 days**, labelled so. A calendar week would need a first-day rule.
- **Export this day follows the search and gate** shown on screen, so the file matches the screen. Say if it should always be the whole day.
- **Owner search matches the car's current register entry.** A pass of a car later removed from the register no longer matches by owner (it already shows no owner).
- **The plate font on the Jetson.** The console loads Noto Sans Arabic from Google. A compound with no internet shows tofu boxes in the plate chip and the plate no longer looks like the Windows one (FR-320). Ask 022 to ship the font file in `web/public/fonts` (the font is free, one download). I did not download it.
- **Phone app:** its Inside list gets no Gone (the spec is the console only).

## Source Code (what changes)

```text
engine/vg/events/vehicles.py     columns plate_width, read_plate; table vehicle_gone; end_visit; q/exact in passes(); visits() joins gone; finish_pass no-send when corrected
engine/vg/features/base.py       consecutive-failure counter, stats["failing_on"]
engine/vg/api/app.py             POST /vehicles/visits/{id}/gone; q, days, exact on passes; q on export; plate width in record(); _start_vehicles pins FP32 .pt
engine/vg/api/live.py            mark_gone, wire fields, _plate_trouble, _vehicles_state/_cameras_reading/_vehicles_stage
engine/vg/api/store.py           Protocol + MockStore.mark_gone
engine/vg/api/schemas.py         VehiclePass(+plate_width, read_plate_display), VehicleVisit(+ended_by)
engine/vg/auth/deps.py           one anchored IT pattern for Gone (beside 022's recording pattern)
engine/tests/test_plates_v2.py   NEW
web/src/pages/VehicleGate.tsx    three tabs, tiles, filter, prefill object
web/src/components/{VehicleLive (new), VehiclePasses, VehicleAlerts, VehicleMovements, VehicleRegister, Plate}.tsx
web/src/services/{api.ts*, wire.ts*, format.ts*}   web/src/i18n/{keys,en,ar.draft}.ts*
* = byte-shared with mobile/src: copy after editing, check_parity.py green.
```

## Order of work

1. Engine, test first: columns and table, Gone, `q`/`days`/`exact`, original reading, no-message, failing counter, FP32 pin, path rule.
2. Wire and `api.ts`, copy to mobile, mobile `tsc`.
3. Console: Live (table, tiles, panel), alert flow, Movements Gone, register prefill.
4. Checks (see quickstart). Jetson items wait for the board.

## Shared files this plan edits (beyond 024's own)

`engine/vg/auth/deps.py` (022 also), `engine/vg/api/{app,live,store,schemas}.py` (022 also),
`web/src/services/{api,wire,format}.ts`, `web/src/i18n/{keys,en,ar.draft}.ts` (022 also; add only 024 keys), and their `mobile/src` copies.

## Build order and shared pieces (cross-check, 10 Nov 2026)

Order: **022 first**, then **023, 024 and 025 in parallel**, then **027** (its wall readings use 024's plate-trouble state and 025's per-zone status and `alerted` flag).

Shared pieces have one owner, so no spec re-plans them:
- `auth/deps.py`: 022 built `OPERATOR_WRITE_PATTERNS` (a tuple of compiled regexes, POST/DELETE only, checked right after `OPERATOR_WRITE_PREFIXES`) and moved `/track` and `/tracking` into `ADMIN_PREFIXES`. 024 (Gone) and 025 (station acknowledge) each **add one line** to `OPERATOR_WRITE_PATTERNS`; if Gone or acknowledge is not POST/DELETE, widen the method check there. 027 creates `ADMIN_PATTERNS` (checked before the safe-method return) for `/cameras/{id}/faces`.
- `ToolId` and `NAV`: 022 did **not** add placeholders. 025 adds `stations` (`ToolId`, `NAV` after Restricted zones, `nav.stations.*` keys); 027 adds `cameras` (`ToolId`, `NAV` last in the main section, `nav.cameras.*` keys). Each touches only its own entry, so they do not collide.
- `useNavBadges` (`web/src/app/useNavBadges.ts`, fetching through `web/src/services/navBadges.ts`): 022 built the vehicle-alerts slot and an attendance slot counting not-arrived. 023 replaces the attendance rule with its own (late plus not arrived, after the cut-off); 025 adds zones and stations.
- `useAttention`: 022's sidebar card uses `useAlertFeed`, which already has a status. 027 adds the additive `status` field to `useAttention` itself for the wall.
- `LiveStore._register` (`live.py`, around 3921): 022 swaps its hours read for `self.hours()`. 023 then rewrites the function on top of that.
- The audit-first example is `live.py::delete_pass` (~L1828). There is no `delete_vehicle_pass`. `dismiss_alert` is at ~L1946.
