# API Contract Changes: Vehicle Gate Accuracy & Redesign

Delta against `specs/006-vehicle-gate/contracts/vehicles-api.md`. Everything not
listed here is unchanged. All geometry stays fractions; all degradation stays
payload (`reason` fields), never a 5xx; permissions stay path-decided.

## Changed responses

### `GET /cameras/{id}/detections?feature=vehicles` (and gate tiles via `/vehicles/cameras`)

Boxes for plates now actually validate. Plate boxes are:

```json
{
  "x": 0.36, "y": 0.70, "w": 0.22, "h": 0.10,
  "label": "ب ج د  ١٢٣٤",
  "confidence": 0.97,
  "kind": "plate",
  "severity": "info",
  "plateWidthPx": 134
}
```

- `kind: "plate"` — newly legal on the wire (the invisible-box fix).
- `severity` carries the register verdict: `info` = registered (green),
  `warn` = unknown / expired (amber), `critical` = blacklisted (red) —
  unchanged mapping, now deliverable.
- `plateWidthPx` — source-frame pixels; console colours it green ≥ 100, amber
  below. Absent on non-plate boxes.
- `label` is the display plate once read; `"Plate"` until then.

### `GET /vehicles/summary`

```json
{
  "...existing fields...": "unchanged",
  "camerasReading": 1, "camerasTotal": 1, "camerasNote": null
}
```

`camerasNote` names the camera not being read and why ("Gate 3 — exit is
offline since 7:12"). All three absent (null) when plate reading is not running
— `reason` already covers that state.

### `GET /vehicles/inside` · `GET /vehicles/visits`

Visit rows gain their evidence links:

```json
{
  "...existing fields...": "unchanged",
  "entryPassId": "vp_01…", "entryHasSnapshot": true,
  "exitPassId": null, "exitHasSnapshot": false
}
```

Thumbnails are `GET /vehicles/passes/{entryPassId}/snapshot` — the existing
endpoint, existing retention semantics (404 after 30 days, pass row kept).

## Changed parameters

### `GET /vehicles/gates` · `GET /vehicles/visits` — new `day` (ISO date, optional)

Empty = today (site timezone). Any recorded day may be asked for. Malformed →
422. `GET /vehicles/inside` takes **no** day — "inside now" is only ever now;
the console's scope line says so.

### `POST /vehicles/export` — new `day` (ISO date, optional)

Bounds the export to that day. Audit entry before the file, as today.

## New endpoints

### `GET /vehicles/reader` — the "What the reader is seeing now" card, one poll

Any signed-in user. Boosts the vehicles worker for the cameras it reports
(same `note_interest` semantics as tile overlay polls).

```json
{
  "votesNeeded": 3,
  "reason": null,
  "cameras": [{
    "cameraId": "cam-laptop", "cameraName": "Main entrance",
    "gate": 1, "direction": "entry",
    "finder": "plate_detector-640", "reader": "char_detector-640",
    "form": "TensorRT", "readMs": 41.3
  }],
  "attempts": [{
    "at": {"...": "Instant"}, "cameraId": "cam-laptop",
    "cameraName": "Main entrance",
    "display": "ب ج د  ١٢٣٤", "confidence": 0.97, "plausibility": 1.0,
    "widthPx": 134, "leaderDisplay": "ب ج د  ١٢٣٤",
    "votes": 2, "votesNeeded": 3
  }]
}
```

- `display: ""` = the reader saw a plate and read nothing; the console renders
  the words, never a blank.
- `attempts` newest first, bounded (≤ 12 per camera); a live window, not a log.
- `reason` set (and lists empty) when plate reading is not running — same
  wording source as the summary.

### `GET /vehicles/traffic?day=` — the hourly chart

Any signed-in user. `[{"hour": 8, "entered": 31, "left": 2}, …]` — only hours
with data, entries and exits counted from passes. Empty list = nothing that day.

### `GET /vehicles/alerts` — the strip

Any signed-in user. Today's undismissed qualifying passes, newest first:

```json
[{
  "passId": "vp_01…", "kind": "unknown", "at": {"...": "Instant"},
  "plate": "سنر 582", "plateDisplay": "س ن ر  ٥٨٢", "gateName": "Gate 2 — staff",
  "owner": null, "permitExpiredOn": null,
  "nearMatchDisplay": "ب ج د  ١٢٣٤", "nearMatchOwner": "Mohamed Fouad",
  "inside": false, "dismissable": true
}]
```

- `kind`: `unknown | blacklist | expired`. Blacklist alerts also still raise
  the Home attention item exactly as before — two surfaces, one security
  record, independent acknowledgement.
- `nearMatch*` only on `unknown`, only when exactly one register plate is
  within one edit; the console phrases it as a question.
- Sentences are built in `format.ts` from these fields; the engine sends facts.

### `POST /vehicles/alerts/{pass_id}/dismiss` — clear one alert

**Any signed-in user** — the one deliberate exception to the `/vehicles`
admin-write rule, carved out by path (`OPERATOR_WRITE_PREFIXES`), because the
person at the gate is a guard. Audit entry (`vehicle.alert.dismiss`, the plate,
whether the action was taken) is written **before** the ack row. Repeat dismiss
→ 409. Unknown pass id → 404. Body: `{"actionTaken": false}` optional, default
false; the register/renew flows pass true when they complete.

## Explicitly unchanged

`GET /vehicles/passes`, `DELETE /vehicles/passes/{id}`, snapshot, register CRUD,
import, template — all keep their contracts. The console stops rendering the
pass list, but the API surface stays; contract tests continue to cover it.
