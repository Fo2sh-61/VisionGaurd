---

description: "Task list for People page & enrolment — professional, live, and complete"
---

# Tasks: People page & enrolment UX

**Input**: Design documents from `/specs/002-people-enrolment-ux/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md)

**Tests**: Included and mandatory. `AGENTS.md` requires every fix to ship with
its regression test in the same commit, and everything with a rule in it here
(preview honesty, removal auth, directory fields) lives server-side precisely
so pytest can hold it — there is no web test runner.

**Organization**: Three increments, each shippable on its own. The People page
first because it is pure reorganisation over data that exists; the enrolment
experience second; removal last because it is the only destructive action and
deserves landing on a page that is already settled.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 / US2 / US3
- Every task names its exact file

## Path Conventions

Engine: `engine/vg/…`, tests `engine/tests/…`. Console: `web/src/…`.
No new engine modules — every edit is in a file that already exists
([plan.md](./plan.md) Project Structure).

---

## Phase 1: Setup

**Purpose**: nothing to scaffold — one check that the ground is where the
plan says it is.

- [X] T001 Confirm the four gates are green before touching anything: run `python -m pytest engine` and record the count (expected 560 passed, 6 skipped) for the commit messages, so a dropped test is visible

**Checkpoint**: baseline known-green.

---

## Phase 2: Foundational

**Purpose**: none needed. The three stories share no new infrastructure — the
plan's whole point is that everything each story needs already exists. US1
starts immediately.

---

## Phase 3: User Story 1 — the People page reads professionally (Priority: P1) 🎯 MVP

**Goal**: every element of a People row is self-explanatory; rows are
clickable to history for everyone; the permanently empty guardian column is
gone; enrolled date, last seen and today's attendance appear.

**Independent test**: open People, read any row aloud — every element
explains itself; click a staff member's row and their history opens. Covers
acceptance scenarios 3 and 4, and PPL-FR-007 through 010.

### Tests for User Story 1 ⚠️ write first, watch them fail

- [X] T002 [P] [US1] Create `engine/tests/test_people_page.py` with `test_directory_carries_photos_enrolled_and_last_seen` — enrol a person into a throwaway gallery, write a sighting, assert `photos`, `enrolled_at`, `last_seen`, `last_camera` come back filled and `last_camera` is the camera's display **name** from the roster, not its id
- [X] T003 [P] [US1] `test_never_sighted_person_has_null_last_seen` in `engine/tests/test_people_page.py` — no sighting rows → `last_seen` and `last_camera` are null on the wire, never a placeholder string
- [X] T004 [P] [US1] `test_last_seen_is_one_query_not_one_per_person` in `engine/tests/test_people_page.py` — `SightingStore.last_seen()` returns the whole mapping in one call; `people()` calls it once (assert via a counting wrapper). The directory is ~2,000 people at target; N+1 here is how a cheap page becomes an expensive one
- [X] T005 [P] [US1] `test_guardian_fields_still_on_the_wire_and_always_null` in `engine/tests/test_people_page.py` — additive-only wire rule: the fields survive, the engine sends null, no client breaks

### Implementation for User Story 1

- [X] T006 [US1] Add `created_at: datetime | None` to the `Person` dataclass and the SELECTs that build it in `engine/vg/identity/gallery.py` — read-only surface of a column every enrolment already writes
- [X] T007 [US1] Add `last_seen() -> dict[str, tuple[datetime, str]]` to `SightingStore` in `engine/vg/events/sightings.py` — one `GROUP BY person_id` with `MAX(seen_at)`, returning (seen_at, camera_id) per person
- [X] T008 [US1] Add `photos: int = 0`, `enrolled_at: Instant | None`, `last_seen: Instant | None`, `last_camera: str | None` to `DirectoryPerson` in `engine/vg/api/schemas.py` — additive with defaults, per [data-model.md](./data-model.md) §2
- [X] T009 [US1] Fill the new fields in `people()` in `engine/vg/api/live.py` — `photo_count` and `created_at` from the gallery, one `last_seen()` call mapped through a roster-names dict (the same idiom `breaches()` uses), `_instant()` for both timestamps
- [X] T010 [P] [US1] Mirror the four fields in `web/src/services/wire.ts` (`photos`, `enrolledAt`, `lastSeen`, `lastCamera`, optional with null)
- [X] T011 [US1] Rework `DirectoryPerson` in `web/src/types.ts` and its mapping in `getPeople()`/`toDirectoryPerson` in `web/src/services/api.ts` — carry the new display fields; delete the `guardianLine` helper and the `guardian` display field; absent values become words at the mapping layer ("Not seen yet", "Not enrolled long enough to say") never "—"
- [X] T012 [US1] Reorganise the list in `web/src/pages/People.tsx` — columns: name+group/detail · type badge · recognition state ("Recognised · N photos" / "Cannot be recognised — no face on file") · last seen (camera · time / "Not seen yet") · today's attendance in words; guardian column deleted
- [X] T013 [US1] Make the whole row a clickable control in `web/src/pages/People.tsx` navigating to `/people/history/{name}` for **every** person type (the `list-row` button idiom the groups list already uses); keep "Track today" as a secondary action; drop the now-redundant "Attendance history" button

**Checkpoint**: the page is professional and complete. Enrolment and removal
untouched. **Shippable.**

---

## Phase 4: User Story 2 — enrolment is live and guided (Priority: P2)

**Goal**: the camera view moves, the detected face is outlined with its five
feature points following the person, guidance says what is still needed, and
there is a way back at every step.

**Independent test**: start an enrolment, step in front of the camera — the
outline and points appear within 2 s and track movement; step out — "nobody
detected"; press ← People mid-session — one confirmation, nothing half-saved.
Covers acceptance scenarios 1, 2, 6 and PPL-FR-001 through 004.

### Tests for User Story 2 ⚠️ write first, watch them fail

All driven with a fake frame and a fake/real YuNet result — no camera, no
model download, no server thread.

- [X] T014 [P] [US2] `test_preview_returns_faces_as_fractions_with_five_points` in `engine/tests/test_people_page.py` — box and all five points within [0,1], converted from the detector's pixels (rule 6)
- [X] T015 [P] [US2] `test_preview_carries_no_name_or_identity` in `engine/tests/test_people_page.py` — the payload has no name, person, or match field even when the face is enrolled; an enrolment preview must never claim to know who it sees
- [X] T016 [P] [US2] `test_preview_empty_frame_is_no_faces_not_an_error` in `engine/tests/test_people_page.py` — nobody in frame → 200, `faces: []`, `offline: false`
- [X] T017 [P] [US2] `test_preview_offline_camera_says_offline` in `engine/tests/test_people_page.py` — no frame available → `offline: true` and no faces; never an empty overlay pretending to have looked (rule 4)
- [X] T018 [P] [US2] `test_preview_unknown_camera_404s_and_no_enrolment_503s` in `engine/tests/test_people_page.py` — unknown id → 404 naming it; enrolment service absent → 503 with the same reason `/enrolment/sessions` gives
- [X] T019 [P] [US2] `test_preview_is_admin_only` in `engine/tests/test_people_page.py` — an `it` account gets 403; pins that the endpoint lives under the `/enrolment` prefix

### Implementation for User Story 2

- [X] T020 [US2] Add `preview(frame) -> list[PreviewFace-shaped dicts]` to `EnrolmentService` in `engine/vg/identity/enrolment.py` — run `self.pipeline.detector.detect` on the frame, convert boxes and the five landmarks to fractions via `frame.to_normalised`; no embedding, no matching
- [X] T021 [P] [US2] Add `EnrolmentPreview` and `PreviewFace` to `engine/vg/api/schemas.py` per [data-model.md](./data-model.md) §2
- [X] T022 [US2] Add `GET /enrolment/preview/{camera_id}` to `engine/vg/api/app.py` — `_enrolment(request)` for the 503 path, `registry.worker(camera_id)` + `last_frame()` exactly like the capture endpoint, `offline: true` when there is no frame
- [X] T023 [P] [US2] Add `getEnrolmentPreview(cameraId)` to `web/src/services/api.ts` and the `EnrolmentPreview`/`PreviewFace` shapes to `web/src/services/wire.ts`
- [X] T024 [US2] Replace the one-shot `<img src={snapshotUrl}>` in `web/src/pages/Enrol.tsx` with the `CameraFrame` component (live stream, NO SIGNAL for free), and overlay the preview faces — box outline plus five dots positioned by fraction, polled every ~300 ms only while a session is open, cleared when the poll stops
- [X] T025 [US2] Add the guidance line to `web/src/pages/Enrol.tsx` — driven by the preview and the session: "Nobody detected — step in front of the camera", "One person at a time, please" (>1 face), else the session's existing `advice`; capture stays the deliberate button press (owner decision — no auto-capture)
- [X] T026 [US2] Add the back control to `web/src/pages/Enrol.tsx` — "← People" visible at every step; with a session open it asks one confirmation and calls the existing `discard()` before navigating; without one it just navigates

**Checkpoint**: enrolment feels like a phone. Removal still absent, honestly.
**Shippable.**

---

## Phase 5: User Story 3 — a person can be removed (Priority: P3)

**Goal**: an administrator removes a person; they vanish from the directory,
are never recognised again without a restart, and the action is audited.
Non-admins get neither the control nor the ability.

**Independent test**: remove an enrolled test person as admin — row gone,
recognition stops naming them within 5 s, audit names the administrator; an
IT account gets 403 crafting the request by hand. Covers acceptance scenario
5 and PPL-FR-005/006.

### Tests for User Story 3 ⚠️ write first, watch them fail

- [X] T027 [P] [US3] `test_removal_requires_admin` in `engine/tests/test_people_page.py` — IT gets 403 on `DELETE /people/{id}`, admin gets 204; pins the new `/people` entry in `ADMIN_WRITE_PREFIXES`
- [X] T028 [P] [US3] `test_people_get_stays_open_to_non_admins` in `engine/tests/test_people_page.py` — the other half of the rule: reads did not become admin-only by accident
- [X] T029 [P] [US3] `test_removal_deletes_person_and_embeddings` in `engine/tests/test_people_page.py` — after removal the `person` row and every `face_embedding` row are gone (the cascade actually fired)
- [X] T030 [P] [US3] `test_removed_person_is_never_matched_again` in `engine/tests/test_people_page.py` — enrol, match successfully, remove, the same embedding now returns no match from the same gallery object (the index the worker shares)
- [X] T031 [P] [US3] `test_removal_writes_audit_before_returning` in `engine/tests/test_people_page.py` — the audit entry exists and names actor and person; on a gallery made to fail mid-delete the entry still exists (audit-first ordering)
- [X] T032 [P] [US3] `test_removing_unknown_person_404s` in `engine/tests/test_people_page.py` — honest refusal, nothing written except nothing

### Implementation for User Story 3

- [X] T033 [US3] Add `"/people"` to `ADMIN_WRITE_PREFIXES` in `engine/vg/auth/deps.py` — one tuple entry; reads stay open, writes become admin-only in the one place path permissions are decided
- [X] T034 [US3] Add `remove_person(person_id, actor) -> bool` to the `Store` protocol and `MockStore` in `engine/vg/api/store.py` (demo mode removes from its fixture list — demo stays a working demo)
- [X] T035 [US3] Implement `remove_person` in `engine/vg/api/live.py` — 404-truthfully when unknown or gallery absent; write the audit entry (actor, person name) **before** calling `gallery.remove_person()`, mirroring the track-search rule
- [X] T036 [US3] Add `DELETE /people/{person_id}` (204 / 404 / 503) to `engine/vg/api/app.py` per [contracts/api.md](./contracts/api.md)
- [X] T037 [P] [US3] Add `removePerson(id)` to `web/src/services/api.ts`
- [X] T038 [US3] Add the remove control to `web/src/pages/People.tsx` — visible to admins only (role from `AuthContext`; the server enforces regardless), inline two-step confirmation stating "This deletes their face data; they will no longer be recognised", then reload the list; errors surface via the existing `LoadError` idiom
- [X] T039 [US3] Ensure the row id travels: `getPeople()` mapping in `web/src/services/api.ts` and `DirectoryPerson` in `web/src/types.ts` carry `id` (the wire already sends it; the console currently drops it)

**Checkpoint**: the whole spec is real — professional page, live guided
enrolment, audited removal.

---

## Phase 6: Polish & cross-cutting

- [X] T040 Run the four gates: `python -m pytest engine` (count must be **above** 560), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`
- [X] T041 [P] Update `STATUS.md` — the People/enrolment line gains: live guided enrolment, row details, admin removal (sightings retained until P3 erasure)
- [ ] T042 Ask Mohamed for the by-eye session in [quickstart.md](./quickstart.md) §3 — overlay tracking a real face, guidance wording, row readability, removal end-to-end. Only his eyes can confirm SC-001 through SC-006
- [ ] T043 Commit per checkpoint with the tests in the same commit, stating before/after pytest counts

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: none
- **Foundational**: empty — nothing blocks the stories
- **US1**: starts immediately
- **US2**: independent of US1 in the engine; the page work is on a different
  page entirely
- **US3**: engine work independent; its console work (T038) lands on the
  People page and reads better after US1's reorganisation — do T012/T013 first
- **Polish**: needs whichever stories shipped

### The one soft cross-story dependency

US3's remove control (T038) sits on the row layout US1 builds (T012). Engine
sides of all three stories are fully independent.

### Within each story

Tests first and failing → engine storage/service → API → console. A test
written after its code proves the test, not the code.

### Parallel opportunities

- All `[P]` tests within a phase — one file, no shared logic; write them in
  one pass
- T010 (web wire) alongside T006–T009 (engine) — different languages
- T021 (schemas) alongside T020 (service) — different files
- US2's engine work (T020–T022) alongside US1's console work (T011–T013) if
  two people are on it

---

## Parallel Example: User Story 2

```bash
# The six preview tests, written together, all failing:
T014 test_preview_returns_faces_as_fractions_with_five_points
T015 test_preview_carries_no_name_or_identity
T016 test_preview_empty_frame_is_no_faces_not_an_error
T017 test_preview_offline_camera_says_offline
T018 test_preview_unknown_camera_404s_and_no_enrolment_503s
T019 test_preview_is_admin_only

# Then the engine makes them pass:
T020 + T021 + T022
```

---

## Implementation Strategy

### MVP: Phase 3 (US1), then stop and look

13 tasks. The page stops confusing people — no unexplained dash, no jargon
badge, every row opens history. Pure reorganisation over data that exists;
zero risk to enrolment or recognition.

### Then US2 — the headline

13 tasks. The live view with the tracking points is the thing that will feel
different in a demo. One new endpoint, no new workers.

### Then US3 — the obligation

13 tasks. Removal is last deliberately: it is the only destructive action in
the feature, and it lands on a settled page with the auth rule and audit
pinned by tests before the button exists.

### Rules that hold throughout

- Every task's file path is exact. No task says "update the API".
- No task touches the enrolment session logic (start/add/capture/commit/
  cancel) — PPL-FR-011 is satisfied by not going near it.
- No task adds a worker, a thread, or a table.
- Additive wire changes only; the guardian fields stay dormant, not deleted.
- A test written after its code is a test of the code's opinion of itself.

---

## Notes

- 43 tasks: 1 setup, 0 foundational, 12 US1, 13 US2, 13 US3, 4 polish
- 15 of them are tests, matching the table in [quickstart.md](./quickstart.md) §2
- Commit after each checkpoint, not each task
- If the pytest count does not rise, the new tests are not being collected —
  that is a failure, not a pass
