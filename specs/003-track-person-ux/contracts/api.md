# Phase 1 — API contract: Track a person

All additive. `/track` and `/tracking/live` keep their exact contracts until
the rebuilt page stops calling them; nothing existing breaks.

Auth note: everything here requires a signed-in user (global middleware).
Nothing goes under an admin prefix — following and searching are operator
work — but **every** action below is audited (constitution rule 11). `/path`
and `/tracking` stay outside `ADMIN_PREFIXES`/`ADMIN_WRITE_PREFIXES`; a test
pins that reads and operator actions stay open to the `it` role.

---

## Past — the skeleton

### `GET /path/{person}?date&from&to` — **new**

Audit entry first (`path.skeleton`, actor, subject), then:

```json
{
  "subject": {"id": "p-layla", "name": "Layla Ahmed", "type": "Student", "match": "face"},
  "date": "2026-08-21",
  "auditId": "a41",
  "anchors": [
    {"cameraId": "cam-caf", "cameraName": "Cafeteria door", "place": "Cafeteria",
     "at": {...}, "until": {...}, "matches": 6, "score": 0.71, "facePx": 96}
  ],
  "appearance": [ /* TrackStop[], blue layer, never named */ ]
}
```

- `person` accepts id or display name (the `/people/{person}/history` rule).
- Unknown person → 404. Anchor store absent → 503 with reason.
- Empty `anchors` is an answer, not an error — the page offers hop-by-hop or
  a sweep.

## Past — legs

### `POST /path/legs` — **new**

Body: `{"cameraId": "...", "from": "...", "to": "...", "personId": null}`
(`personId` set → highlight that person; null → highlight the clicked body of
a stranger flow, passed as `descriptorOf: {jobId, chunk, x, y}`).

Audit entry first (`path.leg`). Returns a `LegJob` (SearchJob-shaped).
- 503 with reason when the archive backend or measured rates are missing.
- 409 when the runner's queue is full — honest refusal, retry later.

### `GET /path/legs/{id}` — **new**

State + `chunkUrls` grown as chunks complete + `nextPrefetched`.

### `GET /path/legs/{id}/chunks/{n}` — **new**

`FileResponse` mp4, same-origin, 404-with-reason (breach-clip idiom). The
highlight is burnt in; the chunk is self-contained evidence.

## Past — sweep

### `POST /path/sweep/estimate` — **new**

Body: window + camera set (ids or `area`). Returns `SweepEstimate` —
`allowed: false` carries the reason ("estimated 42 min exceeds the 15 min
budget — narrow the window or cameras", or "rates not measured yet").
Nothing runs.

### `POST /path/sweep` — **new**

Audit first (`path.sweep`). Refuses (`422`) unless the same estimate passes.
Returns a SweepJob; `GET /path/sweep/{id}` reports progress and hits;
`DELETE /path/sweep/{id}` cancels — cancelled means stopped.

## Live — follow

### `POST /tracking/follow` — **new**

Body: `{"cameraId": "...", "x": 0.41, "y": 0.63}` (fractions, rule 6). The
engine picks the tracked body containing that point in the camera's current
tracking result, audits (`track.follow`), boosts the camera, and returns
`FollowView`.
- 409 when a follow is already open (one at a time; the reply names it).
- 404 when no tracked body contains the point ("nobody there to follow" —
  retryable, the person may have moved).
- 503 when tracking is not running, with the existing reason.

### `GET /tracking/follow` — **new**

Current `FollowView`; 404 when none. The page polls this instead of filtering
`/tracking/live` client-side. `name` appears only after the sustained gate
(D3) and vanishes the poll after track loss, with `endedReason: "track lost"`.

### `DELETE /tracking/follow` — **new**

Stops the follow (audited). Stops any recording with reason `manual`.

## Live — recording the follow

### `POST /tracking/follow/record` — **new**

Body: `{"timerSeconds": 300}` (null → manual stop). Audited
(`track.record.start`). One segment per camera the person crosses; segments
appear in `FollowView.recording.segments` with the existing `Recording`
shape. 409 if already recording.

### `DELETE /tracking/follow/record` — **new**

Manual stop, audited. Timer expiry and track loss stop it server-side with
their reasons — a closed tab never leaves a recording running.

## Cameras

`CameraView` gains `faces: bool` (additive). The sources/settings surface may
set it; the Track page only reads names, areas, and streams.

## Not changing

`/track` (until retired), `/tracking/live`, `/tracking/{id}/correct`, all
recording endpoints under `/cameras`, every enrolment and people contract.
