# Phase 1 — API contract: People page & enrolment UX

Two new endpoints, one enriched response, one auth rule. No breaking change to
any wire type — every added field is optional with a default.

---

## `GET /enrolment/preview/{camera_id}` — **new** — the live overlay

**Returns**: `EnrolmentPreview` — the faces in the camera's latest frame, as
fractions, with five feature points each. See [data-model.md](../data-model.md) §2.

```json
{
  "cameraId": "cam-entrance",
  "at": { "utc": "2026-08-21T09:14:02Z", "tzOffsetMinutes": 180 },
  "offline": false,
  "faces": [
    {
      "x": 0.41, "y": 0.22, "w": 0.14, "h": 0.19,
      "confidence": 0.97,
      "points": [
        {"x": 0.45, "y": 0.28}, {"x": 0.51, "y": 0.28},
        {"x": 0.48, "y": 0.32}, {"x": 0.45, "y": 0.36}, {"x": 0.51, "y": 0.36}
      ]
    }
  ]
}
```

**Rules**
- Detection runs **in the request** on the camera's latest frame — no worker,
  no thread, nothing runs when nobody is enrolling.
- `faces: []` with `offline: false` means "looked, nobody there". `offline:
  true` means "could not look" — the page renders NO SIGNAL, never an empty
  overlay (rule 4).
- No name, no match, no identity of any kind in the payload.
- Unknown camera → `404` with the camera id in the reason.
- Enrolment not running (face model failed to load) → `503` with the same
  reason `/enrolment/sessions` already gives — this endpoint appears and
  disappears with the rest of enrolment, never independently.

**Auth**: admin-only — `/enrolment` is already in `ADMIN_PREFIXES`.

**Polling**: the console polls a few times a second while an enrolment
session is open, and stops when the page is left. Same idiom as the enlarged
camera view's detection poll.

---

## `DELETE /people/{person_id}` — **new** — remove a person

**Returns**: `204` on success.

**Effects, in order**:
1. Audit entry written (who removed whom, when) — before anything is deleted.
2. `person` row deleted; `face_embedding` rows cascade.
3. In-memory match index reloaded — the person is unrecognisable from the
   next frame, no restart (PPL-FR-006).

**Errors**:

| Status | When |
|---|---|
| `404` | no such person |
| `403` | caller is not an administrator (server-enforced, path-based) |
| `503` | gallery not loaded — nothing to remove from, and the reason says so |

**Rules**
- Sightings are **not** deleted (owner decision 2026-08-21) — stored,
  unreachable from any page, awaiting P3 erasure.
- Audit entries are never deleted by removal (constitution: no delete).

**Auth**: **admin only** — `/people` joins `ADMIN_WRITE_PREFIXES`; GET stays
open to every signed-in role. A test pins both directions.

---

## `GET /people` — enriched

`DirectoryPerson` gains `photos`, `enrolledAt`, `lastSeen`, `lastCamera`
(additive, defaulted — see [data-model.md](../data-model.md) §2). Guardian
fields keep being sent (always null) so no client breaks; the console stops
rendering them.

```json
{
  "id": "p-ahmed-hassan",
  "name": "Ahmed Hassan",
  "type": "Student",
  "group": "Grade 8",
  "photoOnFile": true,
  "photos": 3,
  "enrolledAt": { "utc": "2026-08-15T10:03:00Z", "tzOffsetMinutes": 180 },
  "lastSeen": { "utc": "2026-08-21T07:42:11Z", "tzOffsetMinutes": 180 },
  "lastCamera": "Main entrance",
  "attendanceToday": "on_time"
}
```

**Rules**
- `lastSeen`/`lastCamera` null = never sighted; the console says "Not seen
  yet" in words, never "—" (PPL-FR-007/010).
- `lastCamera` is the camera's display name resolved from the roster.
- Recognition down does not empty the directory — the directory is data, not
  inference (existing behaviour, kept).

---

## Not changing

Every enrolment session endpooint keeps its exact contract: start, add photo,
capture, remove photo, commit, cancel. The three-photo floor, staged
sessions, and no-image-storage guarantees are untouched (PPL-FR-011).
`GET /people/history/...` (the history page's data) is untouched — the People
page simply links to it for every person type.
