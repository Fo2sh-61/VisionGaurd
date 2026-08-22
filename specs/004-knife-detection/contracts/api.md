# Phase 1 — API contract: Knife detection

Five endpoints. Four already exist and change behaviour only; one is new.
No breaking change: every added field is optional with a default, and the
one request field that changes (`WeaponReview.actor`) becomes optional.

---

## `GET /weapons/detections?window=...` — the list

**Changes**: served by `LiveStore` from `weapon_scene` instead of `[]`;
`window` accepts seven labels instead of five.

**`window`**: `Today` · `Yesterday` · `Last 7 days` · `Last 30 days`
(default) · `Last 90 days` · `This school year` · `All`. Today and Yesterday
are the site's calendar days (`engine.yaml` timezone); "Last N days" is
rolling; "This school year" starts at `hours.term_from`, or 365 days back if
unset; "All" has no bound. Anything else → `422` naming the allowed labels.

**Returns**: `list[WeaponDetection]`, newest first — pending, confirmed and
dismissed alike.

```json
[
  {
    "id": "3b9e…",
    "at": { "utc": "2026-08-22T09:14:02Z", "tzOffsetMinutes": 180 },
    "cameraId": "cam-laptop",
    "cameraName": "Laptop webcam",
    "location": "Main entrance",
    "item": "Knife",
    "confidence": 0.81,
    "severity": "critical",
    "verdict": "pending",
    "reviewedBy": null,
    "reviewedAt": null,
    "dismissalReason": null,
    "box": null,
    "clip": {
      "id": "3b9e…",
      "url": "/weapons/3b9e…/clip",
      "durationSeconds": 14.2,
      "startsAt": { "utc": "2026-08-22T09:14:03Z", "tzOffsetMinutes": 180 }
    },
    "modelVersion": "knifebest",
    "endedAt": { "utc": "2026-08-22T09:14:16Z", "tzOffsetMinutes": 180 },
    "seconds": 14.2,
    "clipState": "saved",
    "clipReason": null,
    "endReason": "gone"
  }
]
```

**Rules**
- `clip` is present only when `clipState == "saved"`; otherwise `null` and
  `clipReason` says why — still recording, failed (with the recorder's
  sentence), or "Video no longer kept (older than 30 days)".
- `endedAt: null` means the knife is still in view; `seconds` then counts up.
- `endReason: "limit"` means the scene was cut at two minutes.
- `severity` is `critical` while pending or confirmed, `info` once dismissed.
- Nothing is ever removed from this list by time, verdict or video state —
  only `window` narrows it.
- The console polls this every 3 s (P6-FR-016).

**Auth**: any signed-in user.

---

## `POST /weapons/{id}/review` — the human gate

**Changes**: the reviewer is the **signed-in account** (`CurrentUser`), never
the body. `actor` in the body is now optional and ignored by the live store.
The audit entry (`weapon.confirmed` / `weapon.dismissed`) is written **before**
the verdict is stored.

**Body**: `{"verdict": "confirmed" | "dismissed", "reason": "…"?}`

**Returns**: the updated `WeaponDetection`.

**Errors**

| Status | When |
|---|---|
| `404` | no such scene |
| `404` | already reviewed — "That detection was already reviewed by *name*." |
| `422` | `verdict: "pending"` (unchanged — the wire refuses it) |

**Auth**: any signed-in user. `/weapons` is deliberately **not** added to
`ADMIN_WRITE_PREFIXES`; a test pins that an IT-support account can review.

---

## `GET /weapons/{id}/clip` — **new** — play the video

A copy of `GET /breaches/{id}/clip`.

**Returns**: `200` `FileResponse`, `Content-Type: video/mp4`.

**Errors** (all `404` with a plain reason, never a `500`): no such scene ·
`clipState != "saved"` (still recording, failed, expired) · the row says saved
but the file is gone.

**Rules**: the path is never taken from the request — it is read from the
row and checked to be inside `clips_dir/weapons/` before anything is opened.
Same-origin relative URL, because `<video src>` and a new-tab link cannot
send an Authorization header.

**Auth**: any signed-in user.

---

## `GET /weapons/cameras` — the tiles

**Changes**: `LiveStore.weapon_cameras()` returns every camera the worker
serves (enabled cameras, roster order) built with `feature="weapons"`, instead
of `[]`. Empty when the worker is not running — never demo cameras.

---

## `GET /cameras/{id}/detections?feature=weapons` — the overlay

**Changes**: `_boxes(camera, "weapons")` returns the worker's current knife
boxes — `kind: "weapon"`, `label: "Knife"`, `confidence`, `severity:
"critical"` — and **never** a face, a name or a `trackId`. Today this feature
falls through to the face overlay, which is the rule-1/rule-3 bug this fixes.
Polling it boosts the knife worker on that camera, as every other feature's
poll boosts its own worker.

---

## `GET /system/capabilities` and `GET /system/health`

`weapons` changes from a permanent "not built yet" to:

| State | When | Reason |
|---|---|---|
| `live` | worker running, store open | *(none)* |
| `unavailable` | worker failed to start | "Knife detection failed to start (*reason*)." |
| `unavailable` | person model absent | "Person detection is not running, so knives cannot be checked — knives are looked for on people." |
| `unavailable` | no enabled camera | "No camera is running, so nothing is being checked for knives." |
| `unavailable` | store failed | "The knife log is not available, so nothing can be shown even though the cameras are being checked." |

The health `weapons` stage becomes real: `healthy: true` with detail
"*version* on *cuda/cpu* · *N* cameras · last inference *X* ms", or
`healthy: false` with the reason above.

---

## Not changing

`Breach`, `/breaches/*`, `/zones/*`, `Clip`, `Box`, `Instant`, `Capability`,
`PipelineStage` keep their shapes. `WeaponDetection` gains five optional
fields; `WeaponReview.actor` becomes optional. No endpoint is removed or
renamed. Mobile is untouched.
