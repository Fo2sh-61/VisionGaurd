# Phase 1 — API contract: Restricted Zones

Four endpoints. Three already exist and change behaviour only; one is new.
No breaking change to any wire type — every field added is optional with a
default.

---

## `GET /zones` — the camera list with toggles

**Changes**: served by `LiveStore` from the real camera roster instead of
falling through to `MockStore` fixtures.

**Returns**: `list[Zone]` — one entry per configured, non-removed camera, in
roster order.

```json
[
  {
    "id": "cam-entrance",
    "name": "Main entrance",
    "cameraId": "cam-entrance",
    "enabled": true,
    "schedule": { "mode": "always" },
    "polygon": [
      {"x": 0, "y": 0}, {"x": 1, "y": 0},
      {"x": 1, "y": 1}, {"x": 0, "y": 1}
    ],
    "breachesToday": 3
  }
]
```

**Rules**
- Every camera appears, restricted or not — the toggle is how you tell
  (P4-FR-001, P4-FR-010).
- No camera that is not in the roster ever appears (P4-FR-001).
- `polygon` is always the four frame corners.
- Empty roster returns `[]`, never demo cameras.

**Auth**: any signed-in user (GET is not in `ADMIN_WRITE_PREFIXES`).

---

## `PATCH /zones/{id}` — flip the toggle

**Changes**: `LiveStore.set_zone_enabled()` writes `camera.restricted` instead
of mutating a fixture list.

**Body**: `{"enabled": true}` (existing `ZoneUpdate`)

**Returns**: the updated `Zone`.

**Rules**
- Unknown id → `404` with `no zone '<id>'` (already the behaviour).
- Switching **off** during a live scene closes it with
  `end_reason = "switched_off"`; whatever was recorded is saved.
- Persisted immediately — a restart keeps the setting (P4-FR-003).

**Auth**: **admin only.** Already enforced — `/zones` is in
`ADMIN_WRITE_PREFIXES` and PATCH is not a safe method (P4-FR-004). No new code;
a test pins it.

---

## `GET /breaches?window=...` — the detection log

**Changes**: `LiveStore.breaches()` reads `zone_scene` instead of returning
`[]`.

**Returns**: `list[Breach]`, newest first.

```json
[
  {
    "id": "9f2c…",
    "zoneId": "cam-entrance",
    "zoneName": "Main entrance",
    "cameraId": "cam-entrance",
    "cameraName": "Main entrance",
    "at": { "utc": "2026-08-20T09:14:02Z", "tzOffsetMinutes": 180 },
    "subject": { "name": "Unidentified", "match": "none", "type": "unknown" },
    "status": "resolved",
    "severity": "warn",
    "confidence": 0.0,
    "dwellSeconds": 12.4,
    "people": 2,
    "clipState": "saved",
    "clipReason": null,
    "clip": {
      "id": "9f2c…",
      "url": "/breaches/9f2c…/clip",
      "durationSeconds": 12.4,
      "startsAt": { "utc": "2026-08-20T09:14:02Z", "tzOffsetMinutes": 180 }
    }
  }
]
```

**Rules**
- `subject.match` is always `"none"` and the name is never a person's
  (**rule 1** — this feature sees bodies, not identities).
- `clip` is present only when `clipState == "saved"`. Otherwise `null`, and
  `clipReason` says why (P4-FR-008).
- A running scene has `status: "open"` and no `clip` yet.
- Nothing detected yet → `[]`, and the page's wording distinguishes that from
  "unavailable" via `/system/capabilities`.

---

## `GET /breaches/{id}/clip` — **new** — play the clip

**Returns**: `200` `FileResponse`, `Content-Type: video/mp4`.

**Errors** (all with a plain reason, never a 500):

| Status | When |
|---|---|
| `404` | no such scene |
| `404` | `clip_state != "saved"` — includes replaced and failed |
| `404` | the row says saved but the file is missing (rule 4: never claim a file that is not there) |

**Rules**
- The path is **never** taken from the request. It is read from the row and
  verified to be inside the zones clip directory before serving.
- Same-origin relative URL, because `<video src>` cannot send an
  Authorization header — the same trap that made camera streams go black
  (`docs/HANDOFF.md`).

**Auth**: any signed-in user.

---

## `GET /system/capabilities` — the honesty channel

The `breaches` entry changes from permanently UNAVAILABLE to:

| State | When | Reason shown |
|---|---|---|
| `live` | zones worker running | *(none — a reason on a working feature reads as a fault)* |
| `unavailable` | worker failed to start | the startup error |
| `unavailable` | person detection is not running | "Person detection is not running, so nothing is watching the restricted areas." |

---

## `GET /intrusion/cameras` — the tiles

**Changes**: `zone` is `None` for every camera, so no orange rectangle is
drawn (P4-FR-002). Boxes remain the zones feature's own overlay
(`_boxes(camera_id, "intrusion")`) — **rule 3**, each feature draws its own.

---

## Not changing

`Zone`, `ZoneUpdate`, `Breach`, `Clip`, `Point`, `Instant` keep their shapes.
`Breach` gains three optional fields with defaults, so an older client keeps
parsing. No endpoint is removed or renamed. Mobile is untouched.
