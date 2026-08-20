---

description: "Task list for Restricted Zones — real cameras, full-frame zones, auto-recorded clips"
---

# Tasks: Restricted Zones

**Input**: Design documents from `/specs/001-restricted-zones/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md)

**Tests**: Included and mandatory. `AGENTS.md` requires every fix to ship with its
regression test in the same commit, and the constitution requires test-first for
business rules. The scene state machine is a business rule.

**Organization**: Three increments, each shippable on its own. Stop after any
checkpoint and the page is still honest — that is the point of the ordering.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 / US2 / US3
- Every task names its exact file

## Path Conventions

Engine: `engine/vg/…`, tests `engine/tests/…`. Console: `web/src/…`.
Follows the four-file feature pattern in `AGENTS.md`.

---

## Phase 1: Setup

**Purpose**: nothing to scaffold — this feature adds two files to an existing
structure. One check that the ground is where the plan says it is.

- [X] T001 Confirm the four gates are green before touching anything: run `.\dev.ps1 test` and record the pytest count (expected 490 passed, 6 skipped) in the commit message later, so a dropped test is visible
- [X] T002 [P] Create `engine/data/clips/zones/` handling in `engine/vg/config.py` — confirm `storage.clips_dir` exists and decide the `zones/` subfolder path constant; no new config key

**Checkpoint**: baseline known-green, clip directory decided.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: persistence. Nothing can be toggled, logged or recorded until the
column and the table exist.

**⚠️ CRITICAL**: no user story work begins until this phase is complete.

- [X] T003 Add `restricted INTEGER NOT NULL DEFAULT 0` to the `camera` table in `engine/vg/ingest/store.py` — add it to `SCHEMA`, and add an in-place upgrade guarded by `PRAGMA table_info(camera)` so an existing database gains the column without losing rows
- [X] T004 Add `set_restricted(camera_id, restricted) -> bool` and `restricted_ids() -> set[str]` to `CameraStore` in `engine/vg/ingest/store.py` — `set_restricted` returns False for an unknown camera so the endpoint can 404 truthfully; `restricted_ids()` excludes cameras with `removed_at` set
- [X] T005 [P] Create `engine/vg/events/zones.py` with the `zone_scene` table and `SceneStore`, copying the shape of `engine/vg/events/sightings.py` — columns exactly as [data-model.md](./data-model.md) §2, index on `(camera_id, started_at DESC)`, opened through `vg.db.connect`
- [X] T006 Implement `SceneStore` methods in `engine/vg/events/zones.py`: `open`, `note_people`, `close`, `attach_clip`, `fail_clip`, `recent`, `close_orphans` — `attach_clip` marks the camera's previous `saved` row `replaced` **before** unlinking its file, so a crash between the two leaves an honest row rather than a row pointing at a deleted file
- [X] T007 [P] Write `engine/tests/test_zones_live.py` storage tests first and watch them fail: `test_toggle_persists_across_restart`, `test_new_clip_replaces_the_previous_one_for_that_camera_only`, `test_replaced_entry_stays_listed_with_a_reason`, `test_scene_row_is_never_deleted`, `test_open_scene_is_closed_on_next_start`

**Checkpoint**: the database can hold the toggle and the scenes. Nothing is on screen yet.

---

## Phase 3: User Story 1 — the camera list is real (Priority: P1) 🎯 MVP

**Goal**: the page lists the cameras the system actually has, each with a working
toggle that survives a restart. No invented cameras, no orange rectangle.

**Independent test**: open the page, compare the list against the Home page's
cameras — identical. Switch one on, restart the engine, it is still on.
Covers acceptance scenarios 1 and 5, and P4-FR-001 through 004, 010, 011.

### Tests for User Story 1 ⚠️ write first, watch them fail

- [X] T008 [P] [US1] `test_zones_lists_every_configured_camera` in `engine/tests/test_zones_live.py` — every roster camera appears, restricted or not, and nothing else does
- [X] T009 [P] [US1] `test_no_invented_zone_names_from_live_store` in `engine/tests/test_zones_live.py` — assert no `MockStore` fixture name ("Server room" and friends) can come back from a live store. This is the P0-01 bug class; it gets its own guard
- [X] T010 [P] [US1] `test_toggle_requires_admin` in `engine/tests/test_zones_live.py` — an `it` account gets 403 on `PATCH /zones/{id}` and 200 on `GET /zones`. Pins the existing `ADMIN_WRITE_PREFIXES` rule so nobody loosens it by accident
- [X] T011 [P] [US1] `test_zone_polygon_is_the_whole_frame` in `engine/tests/test_zones_live.py` — the four corners, so the wire stays valid while the rectangle disappears
- [X] T012 [P] [US1] `test_intrusion_cameras_have_no_zone_overlay` in `engine/tests/test_zones_live.py` — `CameraView.zone is None` for every camera from `/intrusion/cameras` (P4-FR-002)

### Implementation for User Story 1

- [X] T013 [US1] Override `zones()` in `engine/vg/api/live.py` — build one `S.Zone` per roster camera: id and `camera_id` = camera id, `name` = camera name, `enabled` = the `restricted` column, `schedule` = ALWAYS, `polygon` = the four frame corners, `breaches_today` = today's scene count for that camera
- [X] T014 [US1] Override `set_zone_enabled()` in `engine/vg/api/live.py` — write through `CameraStore.set_restricted`, return the updated `S.Zone`, return None for an unknown camera so `app.py` 404s. Push the new restricted set into the running worker so the change takes effect without a restart
- [X] T015 [US1] Stop populating `CameraView.zone` for the intrusion page in `engine/vg/api/live.py` — the zone is the frame, so there is no rectangle to draw (P4-FR-002)
- [X] T016 [P] [US1] Update `web/src/types.ts` — `Zone` gains nothing, but drop `hours` usage from the page since every zone is ALWAYS; keep the field or remove it consistently across `types.ts` and `web/src/services/api.ts`
- [X] T017 [US1] Update `web/src/pages/Intrusion.tsx` — reword the card to "Restricted cameras", change the empty state to "No cameras are set as restricted areas. Switch one on above.", and replace the `CamGrid` note that promises an orange outline with one that says the whole camera view is the restricted area
- [X] T018 [US1] Add the "no cameras configured at all" empty state to `web/src/pages/Intrusion.tsx` — a plain sentence, never demo cameras

**Checkpoint**: the list is real and the toggle persists. The log below it is still
empty and honestly says so. **Shippable.**

---

## Phase 4: User Story 2 — a person in a restricted camera is logged (Priority: P2)

**Goal**: when someone appears on a restricted camera, a log entry appears with
the time, the camera, the peak people count and how long they were there. One
walk = one entry, even when detection flickers.

**Independent test**: toggle a camera on, walk through the clip, one entry
appears within 5 seconds and gets a duration when the person leaves. Covers
acceptance scenarios 2, 3, 4, and P4-FR-005, 006, 009, 012.

### Tests for User Story 2 ⚠️ write first, watch them fail

All of these drive the state machine with fake frames and a controlled clock —
no camera, no model, no server.

- [X] T019 [P] [US2] `test_person_opens_a_scene` in `engine/tests/test_zones_live.py` — first frame with a person creates a row (P4-FR-005)
- [X] T020 [P] [US2] `test_flicker_under_one_second_does_not_split_the_scene` in `engine/tests/test_zones_live.py` — a 0.9 s gap yields **one** scene. This is SC-003 and the single most important test in the feature
- [X] T021 [P] [US2] `test_one_full_second_of_nobody_closes_the_scene` in `engine/tests/test_zones_live.py` — a 1.1 s gap closes it with `end_reason = "nobody"`
- [X] T022 [P] [US2] `test_scene_is_cut_at_the_two_minute_limit` in `engine/tests/test_zones_live.py` — `end_reason = "limit"` (P4-FR-009)
- [X] T023 [P] [US2] `test_camera_not_restricted_never_opens_a_scene` in `engine/tests/test_zones_live.py` — and assert the detector was **not** called for it (SC-005)
- [X] T024 [P] [US2] `test_scene_records_peak_people_not_last_count` in `engine/tests/test_zones_live.py` — 1 → 3 → 1 people stores 3 (P4-FR-012)
- [X] T025 [P] [US2] `test_toggling_off_mid_scene_closes_the_scene` in `engine/tests/test_zones_live.py` — `end_reason = "switched_off"`
- [X] T026 [P] [US2] `test_restricted_zones_do_not_change_counting` in `engine/tests/test_zones_live.py` — counting and tracking results are identical with the zones worker on and off (rule 9, P4-FR-011)
- [X] T027 [P] [US2] `test_capabilities_says_why_when_the_worker_is_not_running` in `engine/tests/test_zones_live.py` — UNAVAILABLE carries a specific reason, and LIVE carries none (rules 4, 7, 8)

### Implementation for User Story 2

- [X] T028 [US2] Create `engine/vg/features/zones.py` — `ZonesWorker(FeatureWorker)` holding `SharedDetection`, the restricted-id set and a per-camera scene state. Write **no** threading code; the base class owns it
- [X] T029 [US2] Implement the scene state machine in `analyse(frame)` in `engine/vg/features/zones.py` — return early for a camera that is not restricted (before any detection call); otherwise open / extend / close per [research.md](./research.md) D3. Time comes from `frame.captured_at`, never `time.monotonic()`, so tests control the clock and the gap matches the video
- [X] T030 [US2] Add `set_restricted(ids)` to `engine/vg/features/zones.py` so a toggle takes effect on the next frame — and closes any live scene on a camera just switched off
- [X] T031 [US2] Wire the worker into startup in `engine/vg/api/app.py` — same `SharedDetection` instance the people worker gets (never a second detector), call `SceneStore.close_orphans()` on start, and record a startup failure in a `zones_error` attribute the way `recognition_error` already works
- [X] T032 [US2] Override `breaches(since_days)` in `engine/vg/api/live.py` — map `zone_scene` rows to `S.Breach` per [contracts/api.md](./contracts/api.md): `subject` is always `MatchKind.NONE` named "Unidentified" (**rule 1** — this feature sees bodies, never names), `status` OPEN while running and RESOLVED once ended, `dwell_seconds` = scene length
- [X] T033 [US2] Add the three optional fields to `Breach` in `engine/vg/api/schemas.py` — `people: int = 1`, `clip_state: str = "none"`, `clip_reason: str | None = None`. Additive only, so no client breaks
- [X] T034 [US2] Flip the `breaches` entry in `capabilities()` in `engine/vg/api/live.py` — LIVE when the worker runs with no reason attached, UNAVAILABLE with the specific reason otherwise (worker failed to start, or person detection is not running)
- [X] T035 [P] [US2] Mirror the three new `Breach` fields in `web/src/services/wire.ts` and widen `Breach` in `web/src/types.ts` with `people`, `clipState`, `clipReason`
- [X] T036 [US2] Map the new fields in `getBreaches()` in `web/src/services/api.ts`
- [X] T037 [US2] Show the real log in `web/src/pages/Intrusion.tsx` — camera, site-local time, peak people, duration; and the two distinct empty states from [research.md](./research.md) D9 ("no cameras restricted" vs "nothing detected since the engine started")

**Checkpoint**: detections are logged and visible. **Watch clip is still
disabled**, honestly, because no clip exists yet. **Shippable.**

---

## Phase 5: User Story 3 — the clip records and plays (Priority: P3)

**Goal**: a scene records itself, saves when it ends, and plays from the log
entry. One clip kept per camera; replaced entries say so.

**Independent test**: walk through, press Watch clip on the newest entry, see the
scene. Walk through again, the old entry's button is disabled with a reason and
the other camera's clip is untouched. Covers acceptance scenarios 3 and 6, and
P4-FR-007, 008.

### Tests for User Story 3 ⚠️ write first, watch them fail

- [ ] T038 [P] [US3] `test_scene_start_starts_a_recording` in `engine/tests/test_zones_live.py` — against a fake recorder, so no video is written in tests
- [ ] T039 [P] [US3] `test_recorder_failure_logs_the_scene_without_a_clip` in `engine/tests/test_zones_live.py` — `clip_state = "failed"`, a reason, and **no** `clip` on the wire (rule 4: never a fake save)
- [ ] T040 [P] [US3] `test_already_recording_does_not_steal_the_operators_recording` in `engine/tests/test_zones_live.py` — `AlreadyRecording` is caught, the scene is still logged with a reason
- [ ] T041 [P] [US3] `test_clip_endpoint_serves_a_saved_clip` in `engine/tests/test_zones_live.py` — 200 and `video/mp4`
- [ ] T042 [P] [US3] `test_clip_endpoint_404s_when_the_file_is_missing` in `engine/tests/test_zones_live.py` — a row claiming saved with no file on disk is a 404 with a reason, never a 500 (rule 4)
- [ ] T043 [P] [US3] `test_clip_endpoint_refuses_a_path_outside_the_clips_directory` in `engine/tests/test_zones_live.py` — closes the file-read hole
- [ ] T044 [P] [US3] `test_replaced_clip_is_not_served` in `engine/tests/test_zones_live.py` — 404 with "the clip is no longer kept", never someone else's clip

### Implementation for User Story 3

- [ ] T045 [US3] Start and stop the recorder from the scene machine in `engine/vg/features/zones.py` — actor `"restricted-zones"` (never a person's name, the recorder logs who asked), clips into `clips_dir/zones/`, catching `AlreadyRecording` and recording it as the reason rather than crashing
- [ ] T046 [US3] Enforce the 2-minute cap from the worker in `engine/vg/features/zones.py` — do **not** change `MAX_SECONDS` in `engine/vg/ingest/recorder.py`; the manual record button legitimately wants its 10 minutes
- [ ] T047 [US3] Attach or fail the clip when a scene closes in `engine/vg/features/zones.py` — `attach_clip` on a saved recording, `fail_clip` with the recorder's own reason otherwise
- [ ] T048 [US3] Add `GET /breaches/{scene_id}/clip` to `engine/vg/api/app.py` — `FileResponse`, `media_type="video/mp4"`; the path comes from the row and is verified to be inside the zones clip directory, never from the request; 404 with a plain reason for missing, replaced, failed or absent-file
- [ ] T049 [US3] Populate `Breach.clip` in `engine/vg/api/live.py` — only when `clip_state == "saved"`, with a **same-origin relative** URL built the same way the stream URLs are. `<video src>` cannot send an Authorization header; this is the trap that made the camera streams go black last cycle
- [ ] T050 [US3] Wire the Watch clip button in `web/src/pages/Intrusion.tsx` — plays when a clip exists, disabled with `clipReason` next to it when not. No dead buttons (P0-07, rule 4)

**Checkpoint**: the whole chain works — toggle → detect → record → log → watch.

---

## Phase 6: Polish & cross-cutting

- [ ] T051 Run the four gates: `python -m pytest engine` (count must be **above** 490), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`
- [ ] T052 Run the pipeline check from [quickstart.md](./quickstart.md) §3 — `.\dev.ps1 up -Clip`, walk the labelled clip through, confirm the entry appears and the clip plays
- [ ] T053 [P] Update `STATUS.md` — Restricted zones moves from **Fake** to **Real**, with what was built and what was not (no schedules, one clip per camera)
- [ ] T054 [P] Update `docs/PLAN.md` — mark P4 done, note the two deliberate gaps: no schedules, and clip retention is one per camera pending the storage decision at installation
- [ ] T055 Ask Mohamed for the manual webcam check in [quickstart.md](./quickstart.md) §4 — flicker on a real walk, latency by feel, and that the mp4 actually plays in the browser. Only his eyes can confirm these
- [ ] T056 Commit with the tests in the same commit, stating the before and after pytest counts

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no dependencies
- **Foundational (P2)**: needs Setup — **blocks all three stories**
- **US1 (P3)**: needs Foundational
- **US2 (P4)**: needs Foundational. Independent of US1 in the engine, but the
  page work reads better after US1's rewording
- **US3 (P5)**: needs **US2** — a clip belongs to a scene, so scenes must exist
- **Polish (P6)**: needs whichever stories you shipped

### The one real cross-story dependency

US3 → US2. US1 stands entirely alone: the list and toggle work with no worker
running at all, and the page says so honestly.

### Within each story

Tests first and failing → storage → worker → API → console. Never the reverse:
a passing test written after the code proves the test, not the code.

### Parallel opportunities

- T005 and T007 while T003/T004 are in progress (different files)
- Every `[P]` test in a phase can be written together — they share one file but
  no logic, so write them in one pass
- T035 (web wire types) alongside T032–T034 (engine) — different languages,
  different files
- US1's console work (T016–T018) alongside US2's engine work (T028–T034) if two
  people are on it

---

## Parallel Example: User Story 2

```bash
# The nine state-machine tests, written together, all failing:
T019 test_person_opens_a_scene
T020 test_flicker_under_one_second_does_not_split_the_scene
T021 test_one_full_second_of_nobody_closes_the_scene
T022 test_scene_is_cut_at_the_two_minute_limit
T023 test_camera_not_restricted_never_opens_a_scene
T024 test_scene_records_peak_people_not_last_count
T025 test_toggling_off_mid_scene_closes_the_scene
T026 test_restricted_zones_do_not_change_counting
T027 test_capabilities_says_why_when_the_worker_is_not_running

# Then one file makes them all pass:
T028 + T029  engine/vg/features/zones.py
```

---

## Implementation Strategy

### MVP: Phase 1 → 2 → 3 (US1), then stop and look

18 tasks. The page stops lying — real cameras, working toggle that survives a
restart, no invented "Server room", no orange rectangle. The log is empty and
says exactly why. That alone is worth shipping, and it is the half of the
feature with no moving parts.

### Then US2 — the useful half

19 tasks. Detections get logged. This is where the flicker rule lives, and T020
is the test that decides whether the feature feels solid or broken.

### Then US3 — the evidence

13 tasks. Recording and playback. Kept last deliberately: it is the only part
that touches the disk, and if it has to be dropped or deferred, everything
above it still works and the button stays honestly disabled.

### Rules that hold throughout

- Every task's file path is exact. No task says "update the API".
- No task changes `engine/vg/ingest/recorder.py` or `engine/vg/features/people.py`.
  Reusing them unmodified is why this is fast.
- No task adds threading. `FeatureWorker` owns it.
- No task adds a second detection pass. P1-01 exists to prevent that.
- A test written after its code is a test of the code's opinion of itself.

---

## Notes

- 56 tasks: 2 setup, 5 foundational, 11 US1, 19 US2, 13 US3, 6 polish
- 20 of them are tests, matching the 20 named in [quickstart.md](./quickstart.md)
- Commit after each checkpoint, not each task
- If the pytest count does not rise, the new tests are not being collected —
  that is a failure, not a pass
