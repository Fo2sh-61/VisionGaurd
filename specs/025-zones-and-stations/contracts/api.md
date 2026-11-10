# API changes: 025

Wire rules are unchanged: snake_case in Python, camelCase on the wire, `extra="forbid"`,
geometry as fractions 0..1, `Instant` for every time, enums not sentences (the console words them).
Who may call what is decided by path in `auth/deps.py`. Every write calls `_log` first.
Degradation is payload: `GET /zones` and `GET /stations` stay 200 with a `status` / `state` per
row, and the capability list says why a subsystem is down (rule 7, 8).

## Shared shapes (new)

```text
Point         { x, y }                                   existing
WatchedHours  { mode, from?, to? }                       mode: zone  always | outsideWorking | custom
                                                               station working | custom
                                                         from/to "HH:MM", only for custom
```

## Zones

### `GET /zones[?includeDeleted=true]` (everyone signed in) -> `Zone[]`
Existing fields stay (`id, name, cameraId, enabled, polygon, breachesToday`; `schedule` stays
but is always `{mode: "always", days: []}` and is documented as retired, so the phone keeps
parsing). New, additive:

| Field | Type | Meaning |
|---|---|---|
| `status` | `personInZone` \| `clear` \| `paused` \| `outsideHours` \| `cameraOffline` \| `detectorStopped` | built from the worker's last result, never defaulted to `clear` |
| `inZoneNow` | int \| null | people with feet inside; null when `status` is not `personInZone`/`clear` |
| `watched` | `WatchedHours` | |
| `alertAfterSeconds` | number | 0 = once confirmed |
| `notifyInApp`, `notifyEmail` | bool | |
| `pausedBy`, `pausedAt` | string \| null, Instant \| null | |
| `importNote` | string \| null | what an old schedule could not say |
| `deletedAt` | Instant \| null | only present with `includeDeleted` |

### `POST /zones` (admin) body `ZoneCreate` -> `Zone` (201)
`{ name, cameraId, polygon[], watched, alertAfterSeconds?, notifyInApp?, notifyEmail? }`.
Notify defaults to the Settings row "Restricted area entered" when omitted. Audit `zone.create`.
Adds `intrusion` to the camera's features if missing (audit `camera.edit`).
422 with a plain reason: fewer than 3 points, a point outside 0..1, edges cross, almost a line,
empty name, custom hours without both times, unknown camera.

### `PATCH /zones/{id}` (admin) body `ZoneUpdate` -> `Zone`
Every field optional: `enabled` (existing; false = pause, true = resume), `name`, `cameraId`,
`polygon`, `watched`, `alertAfterSeconds`, `notifyInApp`, `notifyEmail`. Audit `zone.pause` /
`zone.resume` for `enabled`, `zone.edit` for the rest, written before the change. 404 unknown id.
An old client sending only `{enabled}` keeps working.

### `DELETE /zones/{id}` (admin) -> 204
Soft delete. Audit `zone.delete`. The camera stops watching that area on the next frame; the log
and totals stay (see `breaches`).

### `GET /breaches?window=today|last7|last30[&zoneId=]` (everyone) -> `Breach[]`
Existing. Changes: optional `zoneId` filter; **entries whose clip was replaced are now listed**
(`clipState: "replaced"`, `clip` null, `clipReason` the existing sentence) so the log is complete;
`zoneId` and `zoneName` come from the zone row (deleted ones included, name unchanged);
`clipReason` for an entry that shared a camera with another zone's recording is "No clip -
recorded under the other zone's entry".

### Unchanged
`GET /breaches/{id}/clip`, `GET /intrusion/cameras`.

## Stations (all new)

### `GET /stations[?includeDeleted=true]` (everyone signed in) -> `Station[]`
```text
Station {
  id, name, cameraId, cameraName,
  polygon: Point[],
  watched: WatchedHours,
  assigneeId?, assigneeName?,          assigneeMissing: bool   (id set but gone from the directory)
  limitMinutes,
  notifyInApp, notifyEmail,
  faceCheck: "anyone" | "face" | "facesTooSmall",
  facePx?: number,                     widest face measured in the last 10 min, if any
  state: "on" | "away" | "absent" | "notStarted" | "closed" | "unknown",
  stateSince?: Instant,
  unknownReason?: "cameraOffline" | "detectorStopped" | "notRunning",
  presentNotRecognised: bool,          somebody is inside and nobody matched (live, not stored)
  opensAt?: "HH:MM",                   when state is notStarted
  workSeconds, absentSeconds, notWatchedSeconds, rate: number | null,
  timeline: { state: "on"|"away"|"absent"|"notWatched", from: Instant, to: Instant }[],
  unacknowledgedAlert?: { eventId, at: Instant },
  deletedAt?: Instant
}
```
All figures are for today at the site. `rate` is null when no time was watched yet. Nothing in
this payload names a person except `assigneeName`, which is the assignment, not a detection.

### `GET /stations/{id}[?day=YYYY-MM-DD]` -> `StationDetail`
`Station` plus `events: StationEvent[]` for that day (newest first) and the figures and timeline
for that day. `StationEvent { id, at, kind: "atStation"|"leftStation"|"absenceAlert"|"acknowledged",
limitMinutes?, byWho? }`. Works for a deleted station (`deletedAt` set). 404 unknown id.

### `GET /stations/face-reach?cameraId=` -> `FaceReach`
`{ facePx: number | null, needed: 80 }`: one face-detector pass on the camera's last picture. Null
when nobody is in view or the camera is down. Declared before `/stations/{id}` so it is not read as
an id. Everyone signed in (it returns a number, never an identity).

### `POST /stations` (admin) body `StationCreate` -> `Station` (201)
`{ name, cameraId, polygon[], watched, assigneeId?, limitMinutes, notifyInApp?, notifyEmail? }`.
Notify defaults to the Settings row "Work station left empty". Audit `station.create`; adds
`stations` to the camera's features if missing. 422 as for zones, plus: `limitMinutes` 1 to 480,
custom `from` must be before `to`, unknown assignee.

### `PATCH /stations/{id}` (admin) body `StationUpdate` -> `Station`
Every field optional, including `assigneeId: null` to clear. Audit `station.edit`.

### `DELETE /stations/{id}` (admin) -> 204
Soft delete, audit `station.delete`. Events, segments and totals stay readable.

### `POST /stations/{id}/acknowledge` (admin and IT) -> `StationDetail`
No body. Acts on the station's current unacknowledged absence alert; 404 if there is none or the
station is unknown. The actor is the session's account, never the body. Audit `station.ack`
**before** the row is written. Does not change `state` and removes nothing.

## Alerts

- `AlertKind`, `AttentionItem.kind`, `DeliveryRow.kind` gain `"station"`. `GET /settings/alerts`
  returns a `station` rule (In-app on, Email off by default, no vehicle options).
  `PATCH /settings/alerts/rules/{kind}` accepts it.
- Home's `attention()` lists, for a station, each **unacknowledged** `absenceAlert` of today as
  `{ id: "station:<eventId>", kind: "station", target: "stations", targetId: <stationId>,
  note: attention.station }`. `POST /attention/{id}/ack` with such an id acknowledges the station
  alert (same audit and same row as above).
- A zone item is shown when the zone's own `notifyInApp` is on (the Settings row is only the
  default) and its alert has been raised.
- Message (en): "Reception (Ahmed) at Front desk camera has been empty for more than 5 min, as at
  11:25." The name in brackets appears only when the station has an assignee. No picture. Arabic is
  drafted in `catalogue.TEMPLATES` and `ar.draft.ts` and not yet read by a native speaker.

## Capabilities and System Health

- New capability `{ key: "stations", name: "Work stations" }`: unavailable with the same three
  reasons as breaches (failed to start with the reason; person detection not running; log not
  available).
- New pipeline stage `stations` beside the vehicles stage, with the same rule-8 sentence.

## Permission changes (`auth/deps.py`)

| Path | Before | After |
|---|---|---|
| `/zones` GET | any signed-in | unchanged |
| `/zones` POST/PATCH/DELETE | admin (`ADMIN_WRITE_PREFIXES`) | unchanged |
| `/stations` GET | (no route) | any signed-in |
| `/stations` POST/PATCH/DELETE | (no route) | admin: add `"/stations"` to `ADMIN_WRITE_PREFIXES` |
| `POST /stations/{id}/acknowledge` | (no route) | admin and IT: one anchored pattern in the operator allowance 022 adds, `^/stations/[^/]+/acknowledge$` |

## Not changed

`/cameras`, `/cameras/{id}/snapshot|stream|detections`, `/intrusion/cameras`, the camera edit
endpoint (it is only *called* when an area needs the feature).
