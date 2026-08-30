# Phase 1 — Data model: People page & enrolment UX

No new tables. One dormant column surfaced, one new query, one new wire type,
four additive wire fields. Nothing existing changes shape.

---

## 1. Storage — read-only surfaces

### `person.created_at` (exists, unread)

Already written on every enrolment (`gallery.py:147`); the `Person` dataclass
just never carried it. Add `created_at: datetime | None` to the dataclass and
the SELECT that builds it. No schema change.

### Latest sighting per person (new query, existing table)

`SightingStore.last_seen() -> dict[str, tuple[datetime, str]]` — person_id →
(seen_at, camera_id) of their most recent sighting. One `GROUP BY person_id`
with `MAX(seen_at)`, fetched **once per directory load**. Uses the existing
`idx_sighting_seen` index.

### Removal (existing mechanism, new caller)

`FaceGallery.remove_person(person_id)` already deletes the `person` row, and
`face_embedding` cascades because every connection enforces `foreign_keys=ON`.
`reload()` refreshes the in-memory match index shared with the recognition
worker. **Sightings rows are untouched** — stored, unreachable from any page,
awaiting P3 erasure.

Removal ordering rule: the audit entry is written **before** the delete runs,
so a crash in between leaves an audited intent, never an unexplained absence.

---

## 2. Wire changes — all additive

### `EnrolmentPreview` (new)

What the enrolment page polls to draw the live overlay.

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `str` | echo of the request |
| `at` | `Instant \| null` | when the analysed frame was captured; null when the camera has no frame |
| `offline` | `bool` | true when the camera is not delivering — the page shows NO SIGNAL, never an empty overlay pretending to have looked |
| `faces` | `list[PreviewFace]` | empty = looked and found nobody (different claim from `offline`) |

`PreviewFace`:

| Field | Type | Notes |
|---|---|---|
| `x, y, w, h` | fractions | face box, origin top-left — geometry crosses the API as fractions, never pixels (constitution rule 6) |
| `points` | `list[Point]` (5) | right eye, left eye, nose, mouth corners — same order YuNet emits |
| `confidence` | `float` | detector confidence |

Deliberately **no name and no match** — an enrolment preview must never claim
to know who it is looking at.

### `DirectoryPerson` — four new optional fields

| Field | Type | Why |
|---|---|---|
| `photos` | `int = 0` | "Recognised from N photos" (PPL-FR-008) |
| `enrolled_at` | `Instant \| null` | when they were added (PPL-FR-010) |
| `last_seen` | `Instant \| null` | most recent sighting; null = never seen |
| `last_camera` | `str \| null` | camera **name** (resolved from the roster), not id |

Existing fields unchanged. The guardian fields stay on the wire (always null —
enrolment never collects them); only the console stops rendering them.
Additive-only keeps every older client parsing.

---

## 3. Auth

`ADMIN_WRITE_PREFIXES` gains `"/people"`: GET stays open to any signed-in
role, `DELETE /people/{id}` (and any future write) becomes admin-only in the
one place path permissions are decided. Pinned by a test, like `/zones` is.

---

## 4. Entity summary

| Entity | Lives in | Change |
|---|---|---|
| Person (directory) | `person` table | none — `created_at` surfaced |
| Face vectors | `face_embedding` | none — cascade already deletes on removal |
| Sightings | `sighting` | none — one new read-only query |
| Enrolment session | in-memory (existing) | none |
| Preview | computed per request | never stored |
