# Phase 0 — Research: People page & enrolment UX

Everything here is verified against the code at commit `5694420`, not assumed.
The theme is: **every requirement maps to the smallest mechanism that
satisfies it, reusing what exists.**

---

## D1 — The live view is the existing stream, not a new one

**Decision**: replace the Enrol page's one-shot `<img src={snapshotUrl}>` with
the `CameraFrame` component every other page already uses.

**Rationale**: the "static photo" is a plain `<img>` that fetches the snapshot
once and never again (`Enrol.tsx:336`). `CameraFrame` already does everything
the spec asks: MJPEG stream through the same-origin proxy, snapshot-polling
fallback, and an honest NO SIGNAL state for an offline camera. Zero new
streaming machinery; PPL-FR-001 and the offline edge case come free.

**Alternative rejected**: WebRTC or a dedicated enrolment stream — pure
complexity; the MJPEG stream is already on screen elsewhere at acceptable
latency.

---

## D2 — Face outline + feature points come from a tiny on-demand endpoint

**Decision**: new endpoint `GET /enrolment/preview/{camera_id}` — the
enrolment service runs its own face detector on the camera's **latest frame**
and returns each face's box and five landmark points (eyes, nose, mouth
corners) as fractions of the frame. The page polls it a few times a second
while a session is open and draws the points over the live view.

**Rationale, piece by piece**:

- The detector and the five landmarks already exist: YuNet returns
  `landmarks: (5, 2)` per face (`infer/faces.py:76`), and the enrolment
  service already owns a `FacePipeline` (`identity/enrolment.py:187`). The
  capture endpoint already reads `worker.last_frame()` (`app.py:1562`) — the
  preview endpoint is the same read plus one detector call and no embedding.
- **Why not reuse the recognition worker's boxes**: it only serves cameras
  with the `attendance` feature, and enrolment must work from *any* camera
  (rule 9 — no feature may require another). It also carries names, which an
  enrolment preview must not display.
- **Why polling, not a new stream**: the enlarged camera view already polls
  detections several times a second (`CameraFrame.tsx`, `DETECTION_REFRESH_MS`)
  and the boxes visibly track a moving face. Same idiom, no new transport.
- **Cost**: YuNet is a 227 KB CPU model; one detection per poll, only while
  somebody is actually on the enrolment page. Nothing runs when the page is
  closed, and no worker or thread is added.
- **Auth**: `/enrolment` is already in `ADMIN_PREFIXES`, so the preview is
  admin-only like every other enrolment call. Correct, and free.

**Two faces / no face**: the endpoint returns all faces it found. The page
shows "nobody detected" for zero and "one person at a time, please" for more
than one — both are data, not errors (spec edge cases).

**Alternatives rejected**:
- Landmarks on the recognition `Box` wire type — touches every overlay
  consumer for one page's need, and mixes enrolment into recognition's wire.
- Client-side face detection in the browser — a second face model to ship and
  keep consistent with the engine's; the constitution says the owner supplies
  models and SFace/YuNet decisions are settled.

---

## D3 — Removal is one DELETE, guarded by the existing auth rule

**Decision**: `DELETE /people/{person_id}`. Add `/people` to
`ADMIN_WRITE_PREFIXES` so reads stay open to any signed-in role and every
write method becomes admin-only server-side. The store writes the audit entry
**before** deleting, then calls the gallery's existing `remove_person`.

**Rationale**:
- `FaceGallery.remove_person` already exists (`gallery.py:190`): one DELETE on
  `person`, and `face_embedding` cascades because every connection goes
  through `vg.db.connect`, which sets `foreign_keys=ON` — the exact hole
  `db.py`'s docstring warns about (names deleted, biometric vectors silently
  kept) is already closed.
- It ends with `self.reload()`, which rebuilds the in-memory match index. The
  recognition worker holds **the same gallery object**, so the person stops
  being matched on the next frame — PPL-FR-006's "no restart" comes free.
- Audit before result, like track searches (constitution rule 11): the entry
  says who removed whom. Today's audit is in-memory and lost on restart;
  `capabilities()` already says so, and P3 owns durability (spec Out of scope).
- **Why `ADMIN_WRITE_PREFIXES` and not a decorator**: `auth/deps.py` decides
  permissions by path in one place, deliberately. Adding the prefix is one
  tuple entry plus a pinned test; a decorator is the pattern that file's
  docstring argues against.

**Confirmation UI**: an inline two-step on the person's row — the Remove
control flips to "This deletes their face data; they will no longer be
recognised. [Remove] [Cancel]". No modal library, no typed-name friction
(assumption in the spec: removal is rare and deliberate; two clicks with an
explicit statement is enough).

**Sightings are untouched** (owner decision 2026-08-21): rows keyed by the
removed `person_id` stay in the database, unreachable from any page. Full
erasure is P3.

---

## D4 — The new person details are three reads the system already has

**Decision**: `DirectoryPerson` gains four additive wire fields —
`photos`, `enrolled_at`, `last_seen`, `last_camera` — filled from:

| Field | Source | Change needed |
|---|---|---|
| `photos` | `Person.photo_count` — already loaded by the gallery | expose only |
| `enrolled_at` | `person.created_at` — already in the table | add to the gallery's `Person` dataclass + SELECT |
| `last_seen` / `last_camera` | latest sighting per person | one new `SightingStore.last_seen()` — a single `GROUP BY person_id` query |

**Rationale**: the owner picked enrolled date, last seen (camera + time) and
today's attendance. `attendance_today` is already on the wire. Nothing new is
collected (PPL-FR-010, privacy note in the spec); everything is one SELECT
away. The last-seen query is one pass over `sighting` using the existing
`idx_sighting_seen` index, fetched once per directory load — not per person.

**Camera names**: resolved from the roster in the store (same `names` map the
breach log already builds), so a camera renamed in config renames everywhere.

---

## D5 — The guardian column disappears; the wire keeps its fields

**Decision**: the front end stops rendering guardian data; the engine keeps
sending the (always-null) wire fields.

**Rationale**: enrolment never collects a guardian, so the column is
permanently "—" — that is the unexplained dash the owner hit (PPL-FR-007).
Removing wire fields would be a breaking change for any older client for zero
gain; additive-only is the house wire rule. The `guardianLine` helper and its
column go; the fields stay dormant on the wire.

---

## D6 — "Photo on file" becomes a sentence about capability

**Decision**: the recognition column reads **"Recognised from N photos"**
(good tone) or **"Cannot be recognised — no face on file"** (warn tone).

**Rationale**: `photo_on_file` was always a capability statement
(`gallery.py:78` says so); the words just never made it to the screen. With
`photos` on the wire (D4) the count is free, satisfying PPL-FR-008 with a
format string.

---

## D7 — Every row opens history; the page already handles everyone

**Decision**: the whole row becomes a clickable control navigating to the
existing history page, for all person types. "Track today" stays as a
secondary action; "Attendance history" as a labelled button disappears (the
row IS the link).

**Rationale**: `LiveStore.history()` looks a person up in the gallery and
builds from sightings — nothing in it is student-specific, and it already
renders honestly when recognition is down. The People page was the only thing
gating history to students (`People.tsx:127`). One conditional removed, one
row-level click added, PPL-FR-009 done.

---

## D8 — Back is a link, plus the discard that already exists

**Decision**: a "← People" control at the top of the Enrol page at every step.
Mid-session it asks one confirmation and calls the existing `discard()`
(which cancels the staged session server-side); outside a session it just
navigates.

**Rationale**: `discard()` and server-side session expiry already guarantee an
abandoned enrolment leaves nothing behind (PPL-FR-011); the page was only
missing the visible way out (PPL-FR-004).

---

## Open risks

| Risk | Mitigation |
|---|---|
| MJPEG stream latency makes the overlay lag the video slightly | The overlay tracks the same latest-frame source the stream serves; the enlarged camera view already lives with this and reads fine. Verified by eye in the manual check |
| Removing a person mid-recognition races the worker | `reload()` swaps the index under a lock the gallery already holds; the worker's next `match()` sees the new index. No new locking |
| An admin removes the wrong person | The confirmation states the name and what removal means; re-enrolment is three photos away. Undo is deliberately out of scope |
