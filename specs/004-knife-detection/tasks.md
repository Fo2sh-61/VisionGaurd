---

description: "Task list for Knife detection — one video per scene, reviewed by a person"
---

# Tasks: Knife detection

**Input**: Design documents from `/specs/004-knife-detection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md), [context.md](./context.md) — **read context.md before opening any source file**

**Tests**: Included and mandatory. `AGENTS.md` requires every fix to ship with its
regression test in the same commit, and the constitution requires test-first for
business rules. The candidate rule, the scene machine, the human gate and
retention are all business rules.

**Organization**: Three increments, each shippable on its own. Stop after any
checkpoint and the page is still honest — that is the point of the ordering.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 / US2 / US3
- Every task names its exact file

## Path Conventions

Engine: `engine/vg/…`, tests `engine/tests/…`. Console: `web/src/…`.
Follows the four-file feature pattern in `AGENTS.md`. Line endings per
context.md §3 — CRLF files stay CRLF.

---

## Phase 1: Setup

**Purpose**: nothing to scaffold — two new files, one rewrite, edits elsewhere.
Three checks that the ground is where the plan says it is.

- [X] T001 Confirm the four gates are green before touching anything: run `.\dev.ps1 test` from the repo root and record the pytest count (expected 768 passed, 6 skipped) for the commit message; then commit or stash the 26 uncommitted paths (`web/src/…` tweaks, `web/src/services/frame.ts`, the deleted `models/knife detection/` folder) so this feature's diff is its own
- [X] T002 [P] Point the model registry at the owner's knife model in `engine/engine.yaml`: `models.weapons` becomes `weights: models/knifebest.pt`, `imgsz: 640`, `conf: 0.5`, `iou: 0.45`, `half: true`, `version: knife-v3-2026-08-13`; rewrite the comment block above `models:` (it still calls the weapons model zero-shot); drop `weapons` from `cam-rtsp-1`'s `features:` list because every enabled camera is checked and a flag would read as a switch. CRLF file
- [X] T003 [P] Add the `weapon_clips_dir` property to `StorageConfig` in `engine/vg/config.py`, directly below `zone_clips_dir`, returning `self.clips_dir / "weapons"` with the same "a subfolder, not a key" reasoning. CRLF file

**Checkpoint**: baseline known-green, config points at the real model, clip folder decided.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the table, the widened wire and the widened store protocol. Every
story writes, reviews or filters `weapon_scene` rows, and every story goes
through `Store.weapons(since, until)`.

**⚠️ CRITICAL**: no user story work begins until this phase is complete.

- [X] T004 Create `engine/vg/events/weapons.py` by copying `engine/vg/events/zones.py`: table `weapon_scene` with the columns in [data-model.md](./data-model.md) §1, index `(camera_id, started_at DESC)`, frozen dataclass `WeaponScene` (with `running`, `seconds`, `playable` properties), `CLIP_STATES = ("none", "recording", "saved", "expired", "failed")`, `END_REASONS = ("gone", "limit", "shutdown")`, and `WeaponSceneStore` with `open(camera_id, started_at, confidence, model_version) -> str`, `note_confidence`, `close`, `start_clip`, `attach_clip` (**delete** the superseded/replaced block — knife videos have no per-camera cap), `fail_clip`, `get`, `recent(since, until=None, camera_id=None)` with `None` bounds meaning open-ended, `close_orphans` (keep the `recording → failed` rewrite), `close_db`. Leave `review()` for US2 and `expire()` for US3
- [X] T005 [P] Create `engine/tests/test_weapons_live.py` with the doubles copied from `engine/tests/test_zones_live.py` (`START`, `frame()`, `person()`, `FakeDetector`, `FakeRecording`, `FakeRecorder`, `live_store()`) plus `knife(x, y, w, h, confidence)` returning a `DetectedWeapon`, `FakeKnives(hits)` that records every camera it was asked about in `asked`, `worker(scenes, *, people=None, knives=None, recorder=None)` building a `WeaponsWorker` over `NoBus`, and `walk(worker, people, knives, [(seconds, n_people, knife_hits)])`; then write and watch fail: `test_open_scene_is_closed_on_next_start` (a `recording` orphan becomes `failed` with the engine-stopped sentence) and `test_bare_live_store_returns_no_weapons` (`bare_live_store.weapons(None, None) == []` and the capability is UNAVAILABLE with a reason)
- [X] T006 [P] Widen the wire in `engine/vg/api/schemas.py`: `WeaponDetection` gains `ended_at: Instant | None = None`, `seconds: float = 0.0`, `clip_state: str = "none"`, `clip_reason: str | None = None`, `end_reason: str | None = None`; `WeaponReview.actor` becomes `str | None = None`. Additive only. CRLF file
- [X] T007 Widen the store protocol in `engine/vg/api/store.py`: `weapons(self, since: datetime | None, until: datetime | None = None)`, `review_weapon(self, detection_id, review, reviewer: str | None = None)`, new `clip_for_weapon(self, detection_id)`; update `MockStore.weapons` to filter `w.at.utc` against both bounds, `MockStore.review_weapon` to record `reviewer or review.actor`, and add `MockStore.clip_for_weapon` returning `(None, "Demo mode has no video files.")`. CRLF file
- [X] T008 [P] Update the direct call in `engine/tests/test_no_fixtures.py` (`test_nothing_unavailable_still_returns_rows`): `"weapons": lambda: store.weapons(None, None)`
- [X] T009 Thread the new subsystem through construction: in `engine/vg/api/live.py` add `weapons=None, weapon_scenes=None` to `LiveStore.__init__` storing `self.weapons_worker`, `self.weapon_scenes` and `self.weapons_error: str | None = None` (never `self.weapons` — it would shadow the method); in `engine/vg/api/app.py` add `app.state.weapons = None`, `app.state.weapon_scenes = None`, `app.state.weapons_error = None` beside the other defaults, pass `weapons=app.state.weapons, weapon_scenes=app.state.weapon_scenes` into `LiveStore(...)`, and set `store.weapons_error = app.state.weapons_error` after it. CRLF files

**Checkpoint**: the table can hold a scene, the wire carries the new fields,
demo mode still works, and `python -m pytest engine` is green with two more
tests. Nothing on screen has changed.

---

## Phase 3: User Story 1 — a knife becomes one entry with one video (Priority: P1) 🎯 MVP

**Goal**: a knife held on any camera produces one entry and one playable video,
the page says what is being checked, and a detector blink never produces a
second video. Nothing is reviewed yet and nothing is sent to anyone.

**Independent test**: `.\dev.ps1 up -Clip` shows "1 camera being checked", a
Knife detection stage on System Health, and **zero** entries over a full loop of
the clip; with a real knife in front of the webcam, an entry appears within 5 s,
stepping away for ten seconds saves one video, and Watch plays it. Covers
acceptance scenarios 1–4 and 8, and P6-FR-001 through 006, 011 through 013,
015 through 017.

### Tests for User Story 1 ⚠️ write first, watch them fail

All in `engine/tests/test_weapons_live.py`. The state machine is driven with
fake frames, fake people, fake knives and the clock in `frame.captured_at` — no
camera, no model, no server. Only T010 touches the model file, and it skips
without it.

- [X] T010 [P] [US1] `test_model_loads_and_finds_nothing_on_grey_and_noise` in `engine/tests/test_weapons_live.py` — `pytest.skip` unless `models/knifebest.pt` exists; `WeaponDetector().detect(flat grey)` and `.detect(random noise)` both return `[]`; `.version == "knifebest"`; `.device in {"cuda", "cpu"}`
- [X] T011 [P] [US1] `test_knife_model_is_never_called_with_nobody_in_view` in `engine/tests/test_weapons_live.py` — `FakeDetector(people=0)` and a `FakeKnives` full of hits: after five frames `knives.asked == []` and no scene exists (P6-FR-002, the cost claim behind Q1)
- [X] T012 [P] [US1] `test_a_knife_outside_every_person_box_is_ignored` in `engine/tests/test_weapons_live.py` — person at `(0.4, 0.2, 0.2, 0.6)`, knife centred at `(0.8, 0.9)` on every frame for 3 s → no scene, recorder never started (the static corner object from research D2)
- [X] T013 [P] [US1] `test_one_sighting_opens_nothing` in `engine/tests/test_weapons_live.py` — one frame with a knife on a person, then nothing for 5 s → `scenes.recent(None, None) == []`, `recorder.started == []` (P6-FR-003)
- [X] T014 [P] [US1] `test_three_sightings_over_a_second_open_a_scene_and_start_recording` in `engine/tests/test_weapons_live.py` — knife on a person at 0.0, 0.5 and 1.0 s → exactly one scene, `running`, `clip_state == "recording"`, `recorder.started == ["cam-a"]`, `peak_confidence` is the highest of the three (P6-FR-003, P6-FR-004, SC-001)
- [X] T015 [P] [US1] `test_entry_time_is_the_first_sighting_not_the_third` in `engine/tests/test_weapons_live.py` — `started_at == START`, not `START + 1.0 s` (P6-FR-003)
- [X] T016 [P] [US1] `test_flicker_under_ten_seconds_is_one_scene` in `engine/tests/test_weapons_live.py` — open at 0–1 s, nothing until 10.5 s (a 9.5 s gap), knife again at 10.5 → still one scene, still running (**P6-FR-004, SC-002** — the test that decides whether the feature feels solid)
- [X] T017 [P] [US1] `test_ten_seconds_without_a_knife_closes_and_saves` in `engine/tests/test_weapons_live.py` — nothing from 1.0 s to 11.5 s → `running is False`, `end_reason == "gone"`, `clip_state == "saved"`, `recorder.stopped == ["cam-a"]`, the stub file exists
- [X] T018 [P] [US1] `test_scene_is_cut_at_two_minutes_and_a_knife_still_there_reopens` in `engine/tests/test_weapons_live.py` — a knife every 0.5 s for 125 s → two scenes: the first `end_reason == "limit"`, the second open and started at the cut frame
- [X] T019 [P] [US1] `test_the_measured_false_hit_sequences_never_form_a_scene` in `engine/tests/test_weapons_live.py` — replay research D2 at 5 Hz: hit runs of `[1, 5, 1, 1, 1]` frames with the knife **outside** the person box, then two single hits **inside** the box 4 s apart → zero scenes (**SC-003**)
- [X] T020 [P] [US1] `test_recorder_busy_logs_the_scene_without_a_video` in `engine/tests/test_weapons_live.py` — `FakeRecorder(already=True)` → the scene exists, `clip_state == "failed"`, `clip_reason == BUSY_REASON`, and the wire entry has `clip is None` (rule 4)
- [X] T021 [P] [US1] `test_shutdown_closes_the_open_scene` in `engine/tests/test_weapons_live.py` — `worker.close_all("shutdown")` → `end_reason == "shutdown"`, recorder stopped
- [X] T022 [P] [US1] `test_weapons_overlay_carries_no_name_even_when_a_face_is_matched` in `engine/tests/test_weapons_live.py` — a `LiveStore` whose fake `weapons_worker.knives_on("cam-a")` returns one knife and whose fake recogniser reports a named face on the same camera: `store.overlay("cam-a", "weapons")` is one box with `kind == "weapon"`, `label == "Knife"`, `match == MatchKind.NONE`, `severity == CRITICAL`, `track_id is None`; `store.overlay("cam-a", "attendance")` is unchanged (**P6-FR-012, rules 1 and 3**)
- [X] T023 [P] [US1] `test_capabilities_says_why_when_knife_detection_is_not_running` in `engine/tests/test_weapons_live.py` — `bare_live_store` → UNAVAILABLE mentioning person detection; with `weapons_error = "weights not found"` → UNAVAILABLE containing that text; with a fake worker and a store → LIVE and `reason is None`; and `health().pipeline` has a `weapons` stage whose `healthy` matches (P6-FR-011, P6-FR-015)
- [X] T024 [P] [US1] `test_knife_detection_does_not_change_counting` in `engine/tests/test_weapons_live.py` — model on `test_restricted_zones_do_not_change_counting` in `engine/tests/test_zones_live.py`: the people worker's count for a frame is identical with and without a `WeaponsWorker` sharing the same `SharedDetection` (**P6-FR-013, rule 9**)
- [X] T025 [P] [US1] `test_clip_endpoint_404s_with_a_reason_and_refuses_paths_outside_the_folder` in `engine/tests/test_weapons_live.py` — through `authed(app)` with the live store installed: unknown id → 404; a `failed` row → 404 carrying `clip_reason`; a `saved` row whose path is outside `weapon_clips_dir` → 404 "not where it should be"; a `saved` row whose file is gone → 404; a `saved` row with a real stub file → 200 `video/mp4` (P6-FR-006, rule 4)

### Implementation for User Story 1

- [X] T026 [US1] Rewrite `engine/vg/infer/weapons.py` as a copy of `engine/vg/infer/persons.py::PersonDetector`: `YOLO(str(self.weights))`, `_resolve_device`, `half` only off the CPU, `_warm_up`, `predict(image, device=, imgsz=, conf=, iou=, half=, verbose=False)` with no `classes=`, boxes converted to frame fractions and clamped, sorted most-confident first; keep `DetectedWeapon`, `CLASS_NAMES`, the `detect(image, min_confidence=None)` signature, `.version = self.weights.stem`, `.device`; `DEFAULT_WEIGHTS = REPO_DIR / "models" / "knifebest.pt"`; a `threading.Lock` held around `predict` (one instance, many camera threads); copy `export_tensorrt`. Rewrite the module docstring: what the model is, why the ONNX decode and onnxruntime went (research D1), that TensorRT is a build step on the target machine. LF file
- [X] T027 [US1] Create `engine/vg/features/weapons.py` by copying `engine/vg/features/zones.py`: constants `CONFIRM_HITS = 3`, `CONFIRM_SECONDS = 1.0`, `CANDIDATE_GAP_SECONDS = 2.0`, `GAP_SECONDS = 10.0`, `MAX_SCENE_SECONDS = 120.0`, `ACTOR = "knife-detection"`, `BUSY_REASON`; dataclasses `Candidate(first_at, last_at, hits)`, `SceneState(scene_id, started_at, last_knife_at, peak, recording)`, frozen `WeaponsResult(checked, people, knives, scene_id)`; `WeaponsWorker(bus, people: SharedDetection, knives: WeaponDetector, cameras, scenes: WeaponSceneStore, recorder=None, rate_hz=2.0, boost_hz=12.0)` named `"weapons"`; `analyse(frame)`: `people = self.people.detect(frame)`; no people → treat as a no-knife frame (drop a stale candidate, close a scene past `GAP_SECONDS`) and return without calling the knife model; else `hits = [k for k in self.knives.detect(frame.image) if _on_a_person(k, people)]` where the knife box centre lies inside a person box with margin 0; no scene → candidate bookkeeping and `_open` at the third hit when `now - first_at >= CONFIRM_SECONDS`, passing `candidate.first_at` as `started_at`; scene → extend `last_knife_at`, raise peak via `scenes.note_confidence`, close `"gone"` after `GAP_SECONDS`, cut `"limit"` at `MAX_SCENE_SECONDS` and reopen on the same frame; `_open` stores `model_version=self.knives.version`; `_close`, `close_all`, `stop`, `_start_recording`, `_stop_recording` copied; `knives_on(camera_id)` returns `self.payload(camera_id).knives` or `[]`; `scene_on`. All time from `frame.captured_at`. **No threading code.** LF file
- [X] T028 [US1] Wire the worker at startup in `engine/vg/api/app.py`: `_start_weapons(cfg, registry, roster, detector)` copied from `_start_zones` — `watched = [c.id for c in roster if c.enabled]`; `detector is None` → `(None, None, "person detection is not running, so knives cannot be checked")`; `spec = cfg.models.get("weapons")` → `WeaponDetector(weights=spec.weights, device=spec.device, imgsz=spec.imgsz, conf=spec.conf, iou=spec.iou, half=spec.half)` with `FileNotFoundError` becoming the reason; `WeaponSceneStore(_database(cfg))` + `close_orphans()`; own `Recorder(registry.bus, cfg.storage.weapon_clips_dir, clock=cfg.timezone)`; `rate = min(fps)`; `worker.start()`; `_reraise_if_strict` in the except. Call it in `lifespan` right after `_start_zones`, assigning `app.state.weapons, app.state.weapon_scenes, app.state.weapons_error`; put `getattr(app.state, "weapons", None)` first in the shutdown `for worker in (...)` tuple. CRLF file
- [X] T029 [US1] Replace the three stubs in `engine/vg/api/live.py` (`weapons`, `weapon_cameras`, `review_weapon` under "this list IS the to-do list"): `weapons(since, until)` maps `self.weapon_scenes.recent(since, until)` to `S.WeaponDetection` per [contracts/api.md](./contracts/api.md) — `camera_name` from `self.registry.configs()`, `location = self._area_of(camera_id)`, `item = "Knife"`, `confidence = min(1.0, peak)`, `severity` CRITICAL unless dismissed then INFO, `at = _instant(started_at)`, `ended_at`, `seconds`, `clip_state`, `clip_reason = scene.clip_reason or self._no_weapon_clip_reason(scene)`, `clip = self._weapon_clip(scene)` with url `/weapons/{id}/clip`, `end_reason`, `model_version`; `weapon_cameras()` = `camera_view(c.id, feature="weapons")` for roster cameras the worker `serves()`, `[]` without a worker; `clip_for_weapon(detection_id)` copied from `clip_for_breach` with `root = self.config.storage.weapon_clips_dir`; leave `review_weapon` returning `None` for US2. CRLF file
- [X] T030 [US1] Make the page honest in `engine/vg/api/live.py`: insert `if feature == "weapons": return self._knife_boxes(camera_id)` in `_boxes` **above** the face default, with `_knife_boxes` building `S.Box(x, y, w, h, label="Knife", confidence=, kind="weapon", severity=S.Severity.CRITICAL)` from `self.weapons_worker.knives_on(camera_id)` (`[]` without a worker); replace the hard-coded `"weapons"` tuple in `capabilities()` with `self._weapons_state()` copied from `_breaches_state` using the research D10 sentences; replace the hard-coded "demo data" `PipelineStage` in `health()` with `self._weapons_stage()` modelled on `_people_stage` — detail "`{version}` on `{device}` · `{n}` cameras · last inference `{ms}` ms" from `worker.stats`, or the reason. CRLF file
- [X] T031 [US1] Serve the video and boost the worker in `engine/vg/api/app.py`: `get_weapons` passes `(datetime.now(timezone.utc) - timedelta(days=window_days(window)), None)` to `store.weapons` (interim — US3 replaces it with the seven labels); add `GET /weapons/{detection_id}/clip` copied from `get_breach_clip` calling `store.clip_for_weapon` (404 with the reason, `FileResponse(path, media_type="video/mp4")`, tag `weapons`); in `camera_detections` add `weapons = getattr(request.app.state, "weapons", None); if feature == "weapons" and weapons is not None: weapons.note_interest(camera_id)`. CRLF file
- [X] T032 [P] [US1] Mirror the wire in the console: `web/src/services/wire.ts` `WeaponDetection` gains `endedAt?`, `seconds?`, `clipState?`, `clipReason?`, `endReason?`; `web/src/types.ts` `WeaponDetection` becomes `{ id, camera, area, time, duration, confidence, status, tone, verdict, reviewer?, reviewedAt?, running, cut, clipUrl?, clipReason? }` and `WeaponState`, `WeaponStep` are deleted; `web/src/services/content.ts` loses `WEAPON_STEPS`. CRLF files
- [X] T033 [US1] Map the list in `web/src/services/api.ts`: `getWeaponDetections` fills every new field (`duration: formatDuration(d.seconds)`, `confidence: formatPercent(d.confidence)`, `clipUrl: assetUrl(d.clip?.url)`, `clipReason: d.clipReason ?? undefined`, `running: !d.endedAt`, `cut: d.endReason === 'limit'`, `reviewer: d.reviewedBy ?? undefined`, `reviewedAt: d.reviewedAt ? formatEventTime(d.reviewedAt) : undefined`); **delete** `weaponStatus`'s "Confirmed — police notified" — status is "Still in view" / "Awaiting review" / "Confirmed" / "False alarm"; tone `warn` pending, `bad` confirmed, `neutral` dismissed. CRLF file
- [X] T034 [US1] Rebuild `web/src/pages/Weapons.tsx` from `web/src/pages/Intrusion.tsx`: `DataNotice`; `PageHeader` lead "Looks for a knife on every camera, on the people in view. Every entry waits for a person to decide; nothing is sent to anyone by the detector."; a header line "*N* cameras being checked" from `getWeaponCameras()` (or the capability reason when not running — never "No knife detected"); the list polled with `useAsync(..., 3_000)` — columns camera · area · time · duration · confidence · status `Badge` · **Watch** (inline `<video>` toggled, whole entry held in state) and **Open** (`<a href={clipUrl} target="_blank" rel="noopener">`) or the `clipReason` sentence; "cut at two minutes" shown when `cut`; two empty states ("Nothing seen {period}." vs the not-running sentence); `CamGrid title="Cameras being checked" feature="weapons"` with the note "Red boxes mark a possible knife on a person. A knife with nobody near it is not detected."; remove `RecordButton`, `useSite`, `WEAPON_STEPS`, the `WeaponState` walk-through and the "Show a live detection" button. Keep `WINDOWS` at the three existing labels for now (US3 widens it). LF file

**Checkpoint**: knife → entry → video → Watch works end to end, the page says
what is being checked, and the two recorded clips produce nothing. Every entry
reads "Awaiting review" and stays that way. **Shippable.**

---

## Phase 4: User Story 2 — a person decides (Priority: P2)

**Goal**: an operator marks an entry **Confirmed** or **False alarm**; the
server records who and when, writes the audit entry first, never lets a verdict
go back, and never deletes. This is the only point the alert spec may fan out
from.

**Independent test**: on a pending entry press Confirm knife — the entry reads
"Confirmed by *your name*" with the time, a reload shows the same, a second
verdict is refused, and a dismissed entry is still in the list. Covers
acceptance scenario 5 and P6-FR-007, 008, 014. Engine work needs only
Foundational; the page buttons need T034.

### Tests for User Story 2 ⚠️ write first, watch them fail

- [X] T035 [P] [US2] `test_review_records_the_signed_in_user_not_the_body` in `engine/tests/test_weapons_live.py` — a live store with one pending scene: `review_weapon(id, WeaponReview(verdict="confirmed", actor="Mallory"), reviewer="Mohamed Fouad")` → `reviewed_by == "Mohamed Fouad"`, `reviewed_at` set; and through `authed(app, role="admin")` the endpoint passes the session user's name, not the body (P6-FR-007)
- [X] T036 [P] [US2] `test_audit_entry_is_written_before_the_verdict` in `engine/tests/test_weapons_live.py` — a store whose `review()` raises: the audit list already holds a `weapon.confirmed` entry for that id (rule 11 idiom)
- [X] T037 [P] [US2] `test_a_second_review_is_refused_with_404` in `engine/tests/test_weapons_live.py` — confirm, then dismiss the same id → 404; the row still says confirmed by the first reviewer
- [X] T038 [P] [US2] `test_an_it_support_account_can_review` in `engine/tests/test_weapons_live.py` — `authed(app, role="it")` POST `/weapons/{id}/review` is **not** 403 (pins that `/weapons` stays out of `ADMIN_WRITE_PREFIXES` in `engine/vg/auth/deps.py`)
- [X] T039 [P] [US2] `test_dismissed_entries_stay_listed_and_there_is_no_delete_route` in `engine/tests/test_weapons_live.py` — a dismissed scene is in `weapons(None, None)` with `severity == INFO`; `DELETE /weapons/{id}` → 404 or 405 (P6-FR-008)

### Implementation for User Story 2

- [X] T040 [US2] Add `review(scene_id, verdict, reviewer, at, reason) -> bool` to `WeaponSceneStore` in `engine/vg/events/weapons.py` — one `UPDATE … WHERE id = ? AND verdict = 'pending'`, returning `rowcount == 1`; `reviewed_at` stored as ISO UTC
- [X] T041 [US2] Override `review_weapon(detection_id, review, reviewer=None)` in `engine/vg/api/live.py`: `self._log(reviewer or "unknown", f"weapon.{review.verdict.value}", detection_id, review.reason)` **first**, then `self.weapon_scenes.review(...)`; `None` when the id is unknown or already reviewed, else the rebuilt `S.WeaponDetection` (reuse the US1 mapper). CRLF file
- [X] T042 [US2] Give the endpoint its user in `engine/vg/api/app.py`: `review_weapon(detection_id, review, store, user: auth_deps.CurrentUser)` → `store.review_weapon(detection_id, review, reviewer=user.name)`; 404 detail `f"no detection {detection_id!r} awaiting review"`. CRLF file
- [X] T043 [P] [US2] Update `reviewWeapon(id, verdict, reason?)` in `web/src/services/api.ts` to post `{ verdict, reason }` only, returning the mapped entry; status sentences become "Confirmed by *reviewer* · *time*" and "False alarm — *reason*" (or plain "False alarm"). CRLF file
- [X] T044 [US2] Add the verdict controls to `web/src/pages/Weapons.tsx`: on a pending entry two buttons — **Confirm knife** (`btn`, red) and **False alarm** (`btn btn--ghost`) with an optional one-line reason field beside it; call `reviewWeapon`, then `reload()`; a failure shows through `LoadError` ("That verdict was not saved: …"); after a verdict the badge and the reviewer line replace the buttons. LF file

**Checkpoint**: the human gate works and is audited. **Shippable.**

---

## Phase 5: User Story 3 — periods and retention (Priority: P3)

**Goal**: seven periods with real calendar days, and videos that go away after
30 days while their entries stay.

**Independent test**: Yesterday lists only yesterday's entries; All lists
everything; an unknown label is refused; a 31-day-old video is gone from disk
and its entry reads "Video no longer kept". Covers acceptance scenarios 6 and
7, and P6-FR-009, 010. Engine work needs only Foundational; the selector
needs T034.

### Tests for User Story 3 ⚠️ write first, watch them fail

- [X] T045 [P] [US3] `test_windows_today_yesterday_and_all_use_site_local_days` in `engine/tests/test_weapons_live.py` — `weapon_window(label, FixedClock(180), term_from)`: Today → `(local midnight as UTC, None)`; Yesterday → `(midnight − 1 day, midnight)`; Last 7 days → `(now − 7 days, None)`; This school year → `(term_from at local midnight, None)` and `(now − 365 days, None)` when `term_from == ""`; All → `(None, None)` (P6-FR-010)
- [X] T046 [P] [US3] `test_unknown_window_is_422_naming_the_allowed_ones` in `engine/tests/test_weapons_live.py` — `GET /weapons/detections?window=Last century` → 422 whose detail lists all seven labels
- [X] T047 [P] [US3] `test_videos_older_than_retention_expire_but_rows_stay` in `engine/tests/test_weapons_live.py` — a `saved` row 31 days old with a real stub file and one 29 days old: `expire(now − 30 days)` returns 1, the old file is gone, the row is still returned by `recent(None, None)` with `clip_state == "expired"` and the "no longer kept" reason, the young row is untouched; with `_unlink` made to fail the row still says `expired` (mark before unlink) (**P6-FR-009, SC-007**)

### Implementation for User Story 3

- [X] T048 [US3] Add the seven labels to `engine/vg/api/app.py`: `WEAPON_WINDOWS = ("Today", "Yesterday", "Last 7 days", "Last 30 days", "Last 90 days", "This school year", "All")` and `weapon_window(label, clock, term_from) -> tuple[datetime | None, datetime | None]` using `_start_of_today`'s midnight arithmetic (lift it into a small helper if cleaner — context.md §5); `get_weapons` resolves `clock = getattr(store, "clock", None) or clock_for(TZ_OFFSET_MINUTES)` and `term_from = getattr(getattr(store, "config", None), "hours", None)` and calls `store.weapons(since, until)`, replacing the US1 interim line; unknown label → 422 naming the seven. CRLF file
- [X] T049 [US3] Add retention to `WeaponSceneStore` in `engine/vg/events/weapons.py`: `EXPIRED_REASON = "Video no longer kept (older than 30 days)."` (take the number from the caller), `expire(older_than: datetime) -> int` — select `saved` rows with `started_at < older_than`, `UPDATE` them to `expired` with the reason and `clip_path = NULL` **inside the lock, before** unlinking each file outside it; call `self.expire(...)` is **not** done here — the store does not know the retention period
- [X] T050 [US3] Run the sweep at the three points: in `engine/vg/api/app.py::_start_weapons` after `close_orphans()`; in `engine/vg/api/live.py` at the top of `weapons()` and after a successful `attach_clip` (a `_expire_weapon_clips()` helper computing `now − timedelta(days=self.config.storage.clip_retention_days)`); `_no_weapon_clip_reason` returns the stored reason for `expired`. CRLF files
- [X] T051 [P] [US3] Widen the selector in the console: `WeaponWindow` in `web/src/types.ts` becomes the seven-label union; `WINDOWS` in `web/src/pages/Weapons.tsx` lists them with `'Last 30 days'` as the initial value; add the note under the list header: "Videos are kept for 30 days. Entries are never removed." CRLF / LF respectively

**Checkpoint**: all three stories stand on their own. The whole chain works —
detect → record → list → watch → decide — with honest periods and retention.

---

## Phase 6: Polish & cross-cutting

- [X] T052 Add `--model` (default `person`) to `engine/tools/benchmark.py` so `python engine/tools/benchmark.py --model weapons` times `models.weapons` on the labelled clip the same way; run it and put the knife row (p50 / p95 / fps) in `docs/PLAN.md` §7 next to the person row (SC-008)
- [X] T053 [P] Update `models/README.md`: the headline section "the weapons model is prompted, not trained" is no longer true — describe `knifebest.pt` (YOLOv8s, one class, trained 13 Aug 2026, own-validation mAP50 0.90) as the weapons model, note that the ONNX copy and the `knife detection/` folder are gone, and keep the zero-shot and oiv7 models as history; regenerate `models/MODELS.md` and `models/knifebest_pt.yaml` with `python engine/tools/audit_models.py`
- [X] T054 Run the four gates from the repo root: `python -m pytest engine` (count must be **above** 768 — 26 new tests), `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`; `git diff --stat` must show no whole-file line-ending flips
- [X] T055 Run the pipeline check from [quickstart.md](./quickstart.md) §3 — `.\dev.ps1 up -Clip`: "1 camera being checked", zero entries over a full loop, the Knife detection stage on System Health with `cuda` and a real inference time, no name on any box in the enlarged view, clean restart
- [X] T056 [P] Update `STATUS.md`: the "Weapons, lost items — **Fake**" row splits — knife detection **Real** (entry + video + review; no alerts yet), lost items still fake; remove "Trained weapons model" from "Blocked on the owner" and add "a recorded clip with a knife for the regression suite"; bump the gates line with the new count. CRLF file
- [X] T057 [P] Update `docs/PLAN.md`: FR-06 from "missing" to "partial — detection, video and human review real; no alert fan-out until P9"; P6 rewritten to say what was built (knife worker on the shared person pass, centre-in-person rule, review gate) and what was not (model manager, benchmarking UI); M2 marked answered; §7 gains the knife cost row from T052. CRLF file
- [ ] T058 Ask Mohamed for the manual check in [quickstart.md](./quickstart.md) §4 — a real knife in front of the webcam (latency, one scene through a flicker, the video plays in the browser, Confirm shows his name), then record the knife clip and the negative clip with `python engine/tools/record.py` into `engine/data/footage/`, and confirm or change the four defaulted answers in [spec.md](./spec.md) Assumptions. Only his eyes and his kitchen can do these
- [ ] T059 Commit `engine/`, `web/`, `models/README.md`, `STATUS.md`, `docs/PLAN.md` and `specs/004-knife-detection/` together, tests in the same commit, stating the before and after pytest counts (768 → the new number) and the four defaulted answers in the message

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Setup — **blocks all three stories**
- **US1 (Phase 3)**: needs Foundational
- **US2 (Phase 4)**: engine tasks (T035–T042) need only Foundational; the page
  task T044 needs US1's T034
- **US3 (Phase 5)**: engine tasks (T045–T050) need only Foundational; the
  selector task T051 needs US1's T034
- **Polish (Phase 6)**: needs whichever stories you shipped

### The real cross-story dependencies

Only the two page tasks: T044 and T051 edit the page T034 rebuilds. Everything
else in US2 and US3 stands on Foundational alone — a reviewer and a retention
sweep do not care whether the worker exists.

### Within each story

Tests first and failing → model runner → worker → store → API → console. Never
the reverse: a passing test written after the code proves the test, not the
code.

### Parallel opportunities

- T002 and T003 together (two files, no overlap)
- T005, T006 and T008 while T004 is in progress
- Every `[P]` test in a phase is written in one pass — one file, no shared logic
- T032 (console wire) alongside T026–T031 (engine)
- US2's engine tasks (T040–T042) alongside US3's engine tasks (T048–T050) —
  different methods, different files except `live.py`, so one at a time there
- T053, T056, T057 together at the end

---

## Parallel Example: User Story 1

```bash
# The sixteen tests, written together, all failing:
T010 test_model_loads_and_finds_nothing_on_grey_and_noise
T011 test_knife_model_is_never_called_with_nobody_in_view
T012 test_a_knife_outside_every_person_box_is_ignored
T013 test_one_sighting_opens_nothing
T014 test_three_sightings_over_a_second_open_a_scene_and_start_recording
T015 test_entry_time_is_the_first_sighting_not_the_third
T016 test_flicker_under_ten_seconds_is_one_scene
T017 test_ten_seconds_without_a_knife_closes_and_saves
T018 test_scene_is_cut_at_two_minutes_and_a_knife_still_there_reopens
T019 test_the_measured_false_hit_sequences_never_form_a_scene
T020 test_recorder_busy_logs_the_scene_without_a_video
T021 test_shutdown_closes_the_open_scene
T022 test_weapons_overlay_carries_no_name_even_when_a_face_is_matched
T023 test_capabilities_says_why_when_knife_detection_is_not_running
T024 test_knife_detection_does_not_change_counting
T025 test_clip_endpoint_404s_with_a_reason_and_refuses_paths_outside_the_folder

# Then two files make most of them pass:
T026  engine/vg/infer/weapons.py
T027  engine/vg/features/weapons.py
# and the wiring makes the rest:
T028–T031  app.py, live.py
```

---

## Implementation Strategy

### MVP: Phase 1 → 2 → 3 (US1), then stop and look

34 tasks. A knife becomes one entry with one playable video; the page stops
lying about what is checked; the two recorded clips produce nothing. Every
entry says "Awaiting review" and that is true — nobody has reviewed it and
nothing has been sent. Shippable, and it is the half with the moving parts.

### Then US2 — the gate

10 tasks. Confirm / False alarm by the signed-in account, audited first. Small,
because the endpoint, the wire and the tests already existed for the fixture
page; what changes is who the reviewer is and where the verdict lands.

### Then US3 — time

7 tasks. Seven periods and the 30-day sweep. Last deliberately: if it has to
be deferred, the page still works with three periods and videos simply stay.

### Rules that hold throughout

- Every task's file path is exact. No task says "update the API".
- No task changes `engine/vg/ingest/recorder.py`, `engine/vg/infer/shared.py`,
  `engine/vg/features/base.py` or `engine/vg/features/zones.py`. Reusing them
  unmodified is why this is fast.
- No task adds threading. `FeatureWorker` owns it; the one lock lives in the
  model runner.
- No task adds a second person-detection pass. The knife worker asks
  `SharedDetection`, never a `PersonDetector`.
- No task sends anything to anyone. The alert spec comes next.
- A test written after its code is a test of the code's opinion of itself.

---

## Notes

- 59 tasks: 3 setup, 6 foundational, 25 US1, 10 US2, 7 US3, 8 polish
- 26 of them are tests, matching the 26 named in [quickstart.md](./quickstart.md) §2
- Commit after each checkpoint, not each task
- If the pytest count does not rise, the new tests are not being collected —
  that is a failure, not a pass
- The four defaulted owner answers (spec.md Assumptions) are confirmed or
  changed at T058; changing Q1 or Q3 is a spec amendment before US1 / US3
