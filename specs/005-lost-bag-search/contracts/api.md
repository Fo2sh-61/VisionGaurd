# Contracts: Find a lost bag

Three endpoints under `/lost-items`, one widened query pattern. Any signed-in
user — `/lost-items` is not in `ADMIN_PREFIXES` or `ADMIN_WRITE_PREFIXES`
and must not be added: a search reveals nothing the live camera pages do not.

---

## `POST /lost-items/search` — start, or replace

**Body**: `LostQuery`

```json
{ "cameras": ["cam-laptop", "cam-hall-2"], "colour": "blue" }
```

`colour` is optional; one of `black` · `light` · `red` · `blue` · `green` ·
`yellow`. Anything else → `422` naming the six.

**Behaviour**: cancels any running search, starts this one, returns at once.
Empty `cameras` → `200` with `job.state = "failed"` and
`job.error = "No camera was chosen."` — a search of nothing is not an error
the operator can do anything about except tick a box, so it is payload.

**Returns**: `LostResult` with `job.state = "running"`.

```json
{
  "job": { "id": "7c1e…", "state": "running", "progress": 0.0,
           "submittedAt": { "utc": "2026-08-23T09:14:02Z", "tzOffsetMinutes": 180 },
           "clipsSearched": 0, "clipsTotal": 0, "error": null },
  "query": { "cameras": ["cam-laptop", "cam-hall-2"], "colour": "blue", "item": "bag" },
  "hits": [],
  "cameras": [],
  "camerasChecked": 0,
  "camerasUnavailable": [
    { "cameraId": "cam-hall-2", "cameraName": "Hall 2", "reason": "The camera is offline." }
  ],
  "hiddenByColour": 0,
  "framesChecked": 0,
  "secondsLimit": 60.0,
  "secondsElapsed": 0.0
}
```

**Unavailable** is decided at start for cameras that are unknown or disabled,
and during the search for ones that produce no frame. Never a 404 for a bad
id in the list: the rest of the search still runs, and the bad one is named.

**503** only when the detector never loaded (`SubsystemUnavailable`), with the
capability's sentence.

---

## `GET /lost-items/search` — the current or last search

**Returns**: `LostResult`. While running, `hits` and `cameras` grow as bags
are confirmed; `secondsElapsed` and `job.progress` advance. Once `done`,
`stopped` or `failed`, the same body is returned unchanged until the next
POST.

**404** when no search has been run since the engine started — there is
nothing to describe.

The console polls this once a second while `job.state == "running"`.

A finished search that found nothing:

```json
{ "job": { "state": "done", "progress": 1.0, … },
  "hits": [], "cameras": [],
  "camerasChecked": 2, "camerasUnavailable": [],
  "hiddenByColour": 0, "framesChecked": 317,
  "secondsLimit": 60.0, "secondsElapsed": 60.0 }
```

The page must render *"2 cameras checked over 60 seconds. No bag seen."* from
those numbers — never an empty grid.

A finished search with a hit, colour filter on:

```json
{ "job": { "state": "done", … },
  "hits": [
    { "cameraId": "cam-laptop", "cameraName": "Laptop webcam",
      "at": { "utc": "2026-08-23T09:14:40Z", "tzOffsetMinutes": 180 },
      "confidence": 0.83,
      "note": "Seen 14 times over 38 seconds",
      "box": { "x": 0.41, "y": 0.55, "w": 0.12, "h": 0.15, "label": "Backpack",
               "confidence": 0.83, "kind": "object", "match": "none", "severity": "warn" },
      "clip": null, "colour": "blue", "colours": ["blue", "black"] }
  ],
  "cameras": [ { "id": "cam-laptop", "name": "Laptop webcam", "area": "Main entrance",
                 "boxes": [ …the same box… ], "snapshotUrl": "/cameras/cam-laptop/snapshot", … } ],
  "camerasChecked": 2, "hiddenByColour": 1, … }
```

`hiddenByColour: 1` means a bag was found whose lenient set did not contain
`blue`. The page must say so.

---

## `DELETE /lost-items/search` — stop

**Returns**: `204`. The job moves to `stopped` with its hits intact; `GET`
still returns them. `204` also when nothing is running — stopping nothing is
not a failure.

---

## `GET /cameras/{id}/detections?feature=lost` — the overlay

The existing endpoint; the `feature` pattern becomes
`^(attendance|track|counting|intrusion|weapons|lost)$`.

`feature=lost` returns the running (or just-finished) search's bag boxes for
that camera, each at most `OVERLAY_HOLD_SECONDS` old, via `_bag_boxes`. A
camera not in the search, or with no recent hit, returns `boxes: []`. It
**does not** boost face recognition — the boost list is `attendance` and
`track` only.

---

## `GET /system/capabilities` — `search_lost`

Name becomes **"Lost bag search"**. States per [research D6](../research.md).

## `GET /system/health` — pipeline stage `search_lost`

Healthy: `"bagbest on cuda · idle"` or `"bagbest on cuda · searching 4 cameras"`.
Unhealthy: the capability's sentence.

---

## Demo mode (`VG_MOCK=1`)

`MockStore.search_lost` returns its fixture result immediately as `done`, with
`camerasChecked = 1` and the other new fields at honest zeros; `lost_search`
returns the last one; `stop_lost_search` is a no-op. The fixture `LostHit`
gains `colour: "black"`, `colours: ["black"]`. Demo stays a working demo.
