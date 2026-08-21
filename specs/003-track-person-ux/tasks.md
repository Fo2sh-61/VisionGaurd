---

description: "Task list for Track a person — past paths and live catching"
---

# Tasks: Track a person — past paths and live catching

**Input**: Design documents from `/specs/003-track-person-ux/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md), **[context.md](./context.md) — read first, before any source file**

**Tests**: Included and mandatory. Every rule with teeth here — the anchor
gates, the name-on-unbroken-track rule, audit-first, honest estimates — lives
server-side precisely so pytest can hold it; there is no web test runner.

**Organization**: Four increments, each shippable on its own, ordered so the
biggest unknown (the DVR) arrives last and behind a measurement tool. Live
catching first because it needs no new storage and makes the page useful
immediately.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 / US2 / US3 / US4
- Every task names its exact file

## Path Conventions

Engine: `engine/vg/…`, tests `engine/tests/…`, tools `engine/tools/…`.
Console: `web/src/…`. Two new engine modules only (`events/anchors.py`,
`ingest/archive.py`) — everything else edits files that exist
([plan.md](./plan.md) Project Structure).

---

## Phase 1: Setup

**Purpose**: baseline known-green, and the handoff loaded.

- [X] T001 Read [context.md](./context.md), then run `python -m pytest engine` and record the count (expected 602 passed, 6 skipped) for the commit messages, so a dropped test is visible

**Checkpoint**: baseline known-green.

---

## Phase 2: Foundational

**Purpose**: the two things more than one story needs — the config surface and
the evidence accumulator. The accumulator sits here because US1's name gate
and US2's anchors are the same verdict (research D3: one bar for one claim).

- [X] T002 Add `faces: bool = False` and `neighbours: tuple[str, ...] = ()` to `CameraConfig`, a parsed `ArchiveConfig` (backend `dvr|footage`, playback URL template, per-camera channels), and a `tracking:` section (patrol_hz, per-tier anchor-gate numbers with lenient corner defaults) in `engine/vg/config.py` — all with defaults so every existing config keeps loading
- [X] T003 [P] Mirror T002 in `engine/engine.yaml`: `faces: true` on cam-laptop, `track` added to cam-clip's features, an `archive:` section with `backend: footage`, and commented gate-knob defaults
- [X] T004 Create `engine/vg/events/anchors.py` with `AnchorAccumulator` — pure logic, no storage: per (camera, person) rolling window fed one match at a time; verdict `sustained` only when ALL gates pass: score ≥ tier threshold, margin over runner-up ≥ tier margin, face ≥ 80 px (never bent), ≥ N matches spanning ≥ T seconds, with a gap between matches. Unit-test it in `engine/tests/test_track_page.py` first: each gate alone failing blocks the verdict; the 80 px floor cannot be configured lower; corner-tier defaults pass a plausible corner sequence (owner: "don't make it so hard")

**Checkpoint**: config parses, accumulator proven. Stories can start.

---

## Phase 3: User Story 1 — Catch someone live (Priority: P1) 🎯 MVP

**Goal**: area-partitioned live grid → enlarge a camera → click a person →
followed across cameras, named only after a sustained clear face, recordable
with manual/timer/track-loss stop. Covers acceptance scenarios 5, 6, 7 and
TRK-FR-001/008/009/010/011/012.

**Independent test**: `.\dev.ps1 up`, three clicks to follow a person on the
webcam, name appears only after a sustained look, cover-face-and-leave drops
name and follow, recording produces a segment with its stop reason. No anchor
table, no DVR, no skeleton needed.

### Tests for User Story 1 ⚠️ write first, watch them fail

All drive a `TrackingWorker` with a fake detector/appearance (copy the fake
patterns from `test_people_page.py`; see context.md §2).

- [X] T005 [P] [US1] `test_follow_picks_the_body_at_the_click_point` in `engine/tests/test_track_page.py` — POST /tracking/follow with fractions inside body A's box follows A, not B; response carries `stableId` and `auditId`-bearing audit entry exists BEFORE the response (TRK-FR-008)
- [X] T006 [P] [US1] `test_follow_on_empty_ground_404s_and_second_follow_409s` in `engine/tests/test_track_page.py` — click where nothing is → 404 "nobody there"; a second follow while one is open → 409 naming it; tracking absent → 503 with the existing reason
- [X] T007 [P] [US1] `test_name_needs_the_sustained_gate_not_one_frame` in `engine/tests/test_track_page.py` — a single high-confidence face match does NOT name the followed body; a sequence passing the accumulator does (TRK-FR-011, SC-005)
- [X] T008 [P] [US1] `test_name_dies_with_the_track_and_is_never_inherited` in `engine/tests/test_track_page.py` — after track loss the FollowView reports `endedReason: "track lost"` and no name; a new body appearing later carries no name until freshly identified
- [X] T009 [P] [US1] `test_recording_writes_one_segment_per_camera_hop` in `engine/tests/test_track_page.py` — follow with recording on, identity moves cam-A → cam-B: recorder stopped on A, started on B, two segments listed (TRK-FR-012)
- [X] T010 [P] [US1] `test_recording_stops_on_timer_and_on_track_loss_with_reasons` in `engine/tests/test_track_page.py` — timer expiry stops with reason `timer`; track loss stops with reason `track lost`; both server-side with no web call
- [X] T011 [P] [US1] `test_follow_and_record_are_audited_and_open_to_it_role` in `engine/tests/test_track_page.py` — audit entries for `track.follow`, `track.record.start`, `track.record.stop`; an `it` account can do all of it (pins that `/tracking` joins no admin prefix)

### Implementation for User Story 1

- [X] T012 [US1] Add `FollowSession` to `engine/vg/features/tracking.py` — dataclass per data-model §3, advanced inside `analyse()`: hop detection, timer expiry, loss when the stable id is absent longer than `LOST_TRACK_SECONDS`, recorder stop-old-then-start-new on hop (context.md trap: `AlreadyRecording`). Public methods `follow(camera_id, x, y, actor)`, `follow_view()`, `end_follow(reason)`, `record(timer)`, `stop_record(reason)` — no new threads
- [X] T013 [US1] Gate `_name_the_body` in `engine/vg/features/recognition.py` behind an `AnchorAccumulator` verdict — `note_face` fires only on `sustained`; single frames stop naming bodies (the whole D3 change)
- [X] T014 [P] [US1] Add `FollowView`, `TrailHop`, `FollowRecording` to `engine/vg/api/schemas.py` per [data-model.md](./data-model.md) §4
- [X] T015 [US1] Add follow store methods to the `Store` protocol and `MockStore` in `engine/vg/api/store.py` — demo mode follows a fixture body convincingly and audits it
- [X] T016 [US1] Implement follow methods in `engine/vg/api/live.py` — audit BEFORE acting (`track.follow`, `track.record.*`), delegate to the tracking worker's session, `SubsystemUnavailable` when tracking is off
- [X] T017 [US1] Add `POST/GET/DELETE /tracking/follow` and `POST/DELETE /tracking/follow/record` to `engine/vg/api/app.py` per [contracts/api.md](./contracts/api.md) — 404/409/503 semantics exactly as contracted
- [X] T018 [P] [US1] Partition `web/src/components/CamGrid.tsx` by `camera.area` with paging and a search box over camera and area names — page size keeps `tileRefreshMs` scaling honest (context.md §5: read how it picks refresh first)
- [X] T019 [US1] Rebuild the live mode in `web/src/pages/TrackPerson.tsx` — area grid → enlarged `CameraFrame live feature="track"` → click converts to fractions → `postFollow`; then poll `getFollow()` 1 s (keep the old page's `seenNow`/auto-camera-switch pattern, drop the fixture subject picker and `neighboursOf`); follow banner shows name state honestly (amber "not identified" until FACE)
- [X] T020 [US1] Add record controls to the follow view in `web/src/pages/TrackPerson.tsx` — start/stop + timer presets (1/5/10 min), segments list with stop reasons, driven only by `FollowView.recording`
- [X] T021 [US1] Add `postFollow/getFollow/endFollow/startFollowRecording/stopFollowRecording` to `web/src/services/api.ts`, mirrors in `web/src/services/wire.ts`, display shapes in `web/src/types.ts` — sentences built in `format.ts` as ever

**Checkpoint**: live catching works end to end with honest naming and
recording. No DVR, no anchors. **Shippable.**

---

## Phase 4: User Story 2 — The instant past path (Priority: P2)

**Goal**: patrol recognition on every camera writes evidence-bearing anchors;
"where did someone go" answers in ~3 s from the database alone. Covers
acceptance scenario 1 and TRK-FR-002/003/015.

**Independent test**: run the clip camera, let patrol anchor a known face,
ask for the path — anchors appear instantly with evidence; a window with
nothing says so. No DVR needed.

### Tests for User Story 2 ⚠️ write first, watch them fail

- [ ] T022 [P] [US2] `test_anchor_rows_come_from_frames_the_debounce_hides` in `engine/tests/test_track_page.py` — five matches in three seconds produce ONE sighting row (debounce) but a full-evidence anchor row; deriving from stored sightings is impossible by construction (research D6)
- [ ] T023 [P] [US2] `test_anchor_carries_its_evidence` in `engine/tests/test_track_page.py` — matches, span, best/mean, face_px, model all stored and returned on the wire
- [ ] T024 [P] [US2] `test_skeleton_is_anchors_only_audited_and_instant` in `engine/tests/test_track_page.py` — GET /path/{person} returns only anchor-grade stops, `auditId` present, audit written before return; sub-anchor recognitions never appear (SC-003: zero wrong legs by construction)
- [ ] T025 [P] [US2] `test_skeleton_empty_window_is_an_answer_and_unknown_person_404s` in `engine/tests/test_track_page.py` — empty `anchors` with 200; unknown person 404; anchor store absent 503 with reason
- [ ] T026 [P] [US2] `test_patrol_and_identity_tiers_run_as_two_instances` in `engine/tests/test_track_page.py` — cameras split by `faces` flag; each worker reports its own cameras and rate; both share one gallery and pipeline

### Implementation for User Story 2

- [ ] T027 [US2] Add `AnchorStore` to `engine/vg/events/anchors.py` — `anchor` table per [data-model.md](./data-model.md) §1 (SightingStore idioms: `db.connect`, RLock, `_parse`, `local_date`), `record(anchor)`, `skeleton(person_id, date, from, to)` one indexed read, and the `measured_rates` row helpers
- [ ] T028 [US2] Feed the accumulator and write anchors in `engine/vg/features/recognition.py` — every match flows through the per-camera accumulator; a `sustained` verdict writes one anchor row with its evidence; tier gate numbers come from config
- [ ] T029 [US2] Start the patrol instance in `engine/vg/api/app.py`'s lifespan — second `RecognitionWorker` on `faces: false` cameras at `patrol_hz`, sharing gallery/sightings/pipeline; both registered so System Health sees each tier's stats
- [ ] T030 [P] [US2] Add `PathAnchor` and `PathSkeleton` to `engine/vg/api/schemas.py` per [data-model.md](./data-model.md) §4 — evidence travels; no box geometry
- [ ] T031 [US2] Add `path_skeleton` to `Store`/`MockStore` in `engine/vg/api/store.py` and implement in `engine/vg/api/live.py` — audit-first (`path.skeleton`), anchors from `AnchorStore`, blue appearance layer via existing `path_for` (read `_collapse` first — context.md §5), camera names from the roster
- [ ] T032 [US2] Add `GET /path/{person}` to `engine/vg/api/app.py` per [contracts/api.md](./contracts/api.md) — id-or-name resolution like `/people/{person}/history`
- [ ] T033 [US2] Build the past-mode skeleton view in `web/src/pages/TrackPerson.tsx` — person + date + window → instant stop chain, evidence on hover ("6 matches over 4 s · score 0.71"), green anchors / blue appearance rendered distinctly, empty state offering the next moves; calls in `web/src/services/api.ts` + `wire.ts` + `types.ts`

**Checkpoint**: the skeleton answers instantly and honestly. Legs still say
"video arrives in the next increment" — plainly, not as a dead control.
**Shippable.**

---

## Phase 5: User Story 3 — Video behind every leg (Priority: P3)

**Goal**: click a stop, watch the video within 10–15 s, playback never
stalls, the next hop is warm. The DVR unknown arrives here, behind a
measurement tool. Covers acceptance scenario 2 and TRK-FR-004/005/013/014.

**Independent test**: with `backend: footage` and the walk-through clip,
click an anchor — chunk 1 plays inside the budget, chunks advance without
stalls, prefetch makes the next stop near-instant. No DVR hardware needed.

### Tests for User Story 3 ⚠️ write first, watch them fail

- [ ] T034 [P] [US3] `test_footage_backend_slices_by_time` in `engine/tests/test_track_page.py` — a request for [t, t+30s] of the walk-through file returns exactly that span; a span outside any file → honest "footage unavailable" reason
- [ ] T035 [P] [US3] `test_leg_job_grows_chunks_and_serves_them` in `engine/tests/test_track_page.py` — POST /path/legs audits then queues; GET shows `chunkUrls` growing; chunk endpoint returns mp4 bytes; a finished job's chunks survive until retention
- [ ] T036 [P] [US3] `test_leg_retention_keeps_last_n_and_404s_with_reason` in `engine/tests/test_track_page.py` — oldest leg's chunks removed past N; fetching them → 404 whose reason says replaced, offering a re-derive
- [ ] T037 [P] [US3] `test_prefetch_prefers_next_anchor_then_neighbours_then_area` in `engine/tests/test_track_page.py` — the three-step fallback of TRK-FR-005 pinned as a pure function
- [ ] T038 [P] [US3] `test_jobs_refuse_honestly` in `engine/tests/test_track_page.py` — archive backend missing → 503 with reason; runner queue full → 409; estimates without a `measured_rates` row → "unavailable", never a guess (TRK-FR-014)
- [ ] T039 [P] [US3] `test_measure_tool_writes_rates` in `engine/tests/test_track_page.py` — running the measurement against the footage backend stores fetch_x and process_fps; estimates change accordingly

### Implementation for User Story 3

- [ ] T040 [US3] Create `engine/vg/ingest/archive.py` — `ArchiveSource` seam; `footage` backend slicing `footage_dir` files by timestamp; `dvr` backend spawning ffmpeg from the config URL template; bounded 2-thread runner with a bounded queue; 30 s chunk pipeline: fetch → shared person detector + throwaway ByteTrack → highlight burn-in → mp4 under `clips_dir/track/<job>/`; keep-last-N retention; prefetch enqueue at low priority (next anchor camera → `neighbours:` → same area)
- [ ] T041 [P] [US3] Create `engine/tools/measure_track.py` — times a 2-minute fetch (× real-time) and detect+track+encode fps over it; prints the derived chunk-1 wait and sweep budget; writes the `measured_rates` row (quickstart §0)
- [ ] T042 [P] [US3] Add `LegJob` (SearchJob-shaped) to `engine/vg/api/schemas.py` per [data-model.md](./data-model.md) §4
- [ ] T043 [US3] Add leg methods to `Store`/`MockStore` in `engine/vg/api/store.py` and implement in `engine/vg/api/live.py` — audit-first (`path.leg`), job creation/status via the runner, estimates from `measured_rates`
- [ ] T044 [US3] Add `POST /path/legs`, `GET /path/legs/{id}`, `GET /path/legs/{id}/chunks/{n}` to `engine/vg/api/app.py` — chunk serving copies `get_breach_clip` exactly (FileResponse, 404-with-reason, same-origin)
- [ ] T045 [US3] Build the leg player in `web/src/pages/TrackPerson.tsx` — click a stop → job → `<video>` advancing through `chunkUrls` as they land, honest buffering line ("fetching the next 30 seconds…"), prefetch indicator on the next stop; calls + mirrors in `web/src/services/api.ts` / `wire.ts` / `types.ts`

**Checkpoint**: the loved criteria works end to end on recorded footage; the
DVR backend is one config change plus a measurement run away. **Shippable.**

---

## Phase 6: User Story 4 — Strangers and the wide net (Priority: P4)

**Goal**: follow someone who was never enrolled, hop by hop, from a clicked
body in footage; sweep a window with the cost stated first. Covers
acceptance scenarios 3, 4 and TRK-FR-006/007.

**Independent test**: open the clip's footage at a time, click the walker,
follow them one hop; ask for an oversized sweep — refused with arithmetic;
run an allowed one — progress real, cancel works.

### Tests for User Story 4 ⚠️ write first, watch them fail

- [ ] T046 [P] [US4] `test_sweep_estimate_shows_arithmetic_and_caps` in `engine/tests/test_track_page.py` — estimate computed from stored rates; over-budget → `allowed: false` with reason; unmeasured → refused; POST /path/sweep 422s unless the estimate passes (SC-006)
- [ ] T047 [P] [US4] `test_sweep_runs_audits_progresses_and_cancels` in `engine/tests/test_track_page.py` — audit before run; progress advances per segment; hits append; DELETE stops it and says stopped
- [ ] T048 [P] [US4] `test_stranger_hop_carries_a_descriptor_never_a_name` in `engine/tests/test_track_page.py` — a clicked body in a chunk becomes an appearance query; hop results are APPEARANCE/blue and carry no name even if the person is enrolled (rule 1)

### Implementation for User Story 4

- [ ] T049 [US4] Add sweep enumeration + estimate + stranger descriptor query to `engine/vg/ingest/archive.py` — same runner; a sweep is segments × the leg pipeline in scan mode; a stranger hop is a leg job whose query is an appearance descriptor lifted from the clicked chunk box
- [ ] T050 [P] [US4] Add `SweepEstimate`, `SweepJob` to `engine/vg/api/schemas.py`; sweep + stranger store methods in `engine/vg/api/store.py`; implement audit-first in `engine/vg/api/live.py`
- [ ] T051 [US4] Add `POST /path/sweep/estimate`, `POST /path/sweep`, `GET/DELETE /path/sweep/{id}`, and the `descriptorOf` variant of `POST /path/legs` to `engine/vg/api/app.py` per [contracts/api.md](./contracts/api.md)
- [ ] T052 [US4] Build the footage scrub-and-click view and sweep panel in `web/src/pages/TrackPerson.tsx` — open a camera at a date/time (a leg job with no highlight), click a body, follow hop by hop; sweep form shows the estimate before the run button enables; progress and hits stream in; calls + mirrors in `web/src/services/api.ts` / `wire.ts` / `types.ts`

**Checkpoint**: the whole spec is real.

---

## Phase 7: Polish & cross-cutting

- [ ] T053 Run the gates: `python -m pytest engine` (count must be **above** 602), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`
- [ ] T054 [P] Rewrite the Track line in `STATUS.md` — engine real, page real: live catch with honest naming and recording, instant anchor paths, chunked leg playback over the footage/DVR archive, sweeps behind measured estimates. Delete "page part fake"
- [ ] T055 Retire the old `/track` call path: remove `trackPerson` usage from `web/src/pages/TrackPerson.tsx` and `web/src/services/api.ts` once nothing renders from it; the engine endpoint stays serving (additive-only wire rule) with a comment naming its successor
- [ ] T056 Run `python engine/tools/measure_track.py` on the dev machine and confirm the page's estimates match the stored rates (quickstart §0)
- [ ] T057 Ask Mohamed for the by-eye session in [quickstart.md](./quickstart.md) §3 — three-click follow, sustained-look naming, timer recording, instant skeleton, non-stalling leg playback, sweep refusal arithmetic. Only his eyes confirm SC-001 through SC-007
- [ ] T058 Commit per checkpoint with tests in the same commit, stating before/after pytest counts

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: T002 blocks T003; T004 blocks US1's naming gate and US2's anchors
- **US1**: after Phase 2. Engine (T012–T017) and web (T018–T021) can interleave; T012 before T016/T017; T013 needs T004
- **US2**: after Phase 2; independent of US1 in the engine (different files except schemas/store/app additions, which are additive). T027 before T028/T031; T029 needs T002/T003
- **US3**: needs US2's anchors for prefetch-by-next-anchor (T037/T040) and the skeleton page for the click-a-stop entry (T045 after T033)
- **US4**: needs US3's runner and chunk pipeline (T049 builds on T040)
- **Polish**: needs whichever stories shipped

### The one cross-story seam

`AnchorAccumulator` (T004, Foundational) serves both US1's name gate (T013)
and US2's anchor writes (T028) — one bar for one claim. It is pure logic with
its own tests, so neither story blocks the other through it.

### Parallel opportunities

- All [P] tests within a phase — one file, write them in one pass
- T014 (schemas) alongside T012 (worker); T018 (web grid) alongside all US1 engine work
- T030 alongside T027; T033 alongside T029–T032 (different languages)
- T041 (tool) and T042 (schemas) alongside T040 (archive module)
- US2 engine work can start while US1's web work is in flight

---

## Implementation Strategy

### MVP: Phase 3 (US1), then stop and look

The live-catch loop is the demo-defining half and touches no storage and no
DVR. Ship it, use it, let the name gate prove itself on a real webcam before
anchors multiply its verdicts.

### Then US2 — the promise-keeper

Anchors and the instant skeleton make the past mode real. Everything is
database reads; the increment is fast to verify against the clip camera.

### Then US3 — the unknown, contained

The archive layer lands entirely behind the `footage` backend first; the DVR
is a config change plus `measure_track.py` on real hardware. If the real DVR
is slow, the estimates say so — the increment cannot over-promise.

### Then US4 — reach

Sweeps and strangers reuse the runner; nothing new moves concurrently.

### Rules that hold throughout

- Every task's file path is exact. No task says "update the API".
- No new threads outside the archive runner (plan Complexity Tracking).
- Additive wire changes only; `/track` and `/tracking/live` keep serving.
- Geometry crosses the API as fractions, always (rule 6).
- A name is never attached below the sustained bar, never survives track
  loss, and never comes from appearance matching (rules 1, 2).
- If the pytest count does not rise, the new tests are not being collected —
  that is a failure, not a pass.

---

## Notes

- 58 tasks: 1 setup, 3 foundational, 17 US1, 12 US2, 12 US3, 7 US4, 6 polish
- 22 of them are tests, matching the table in [quickstart.md](./quickstart.md) §2
- Commit after each checkpoint, not each task
- context.md carries the anchors and traps — the implementing chat reads it
  before opening any source file
