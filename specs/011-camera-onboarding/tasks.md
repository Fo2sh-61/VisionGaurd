---
description: "Task list for Camera Onboarding — Real, Complete, Editable"
---

# Tasks: Camera Onboarding — Real, Complete, Editable

**Input**: Design documents from `/specs/011-camera-onboarding/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/sources-api.md](./contracts/sources-api.md),
[quickstart.md](./quickstart.md)

**Read [context.md](./context.md) before opening any source file.** It holds the anchor for every
edit below, what each anchor looks like today, and thirteen traps. It exists so this list does not
have to repeat them.

**Tests are included and are not optional here.** The constitution requires test-first for business
rules and regression fixes, and `AGENTS.md` requires every fix to a known bug to ship with its
regression test *in the same commit*. Six of the items below are fixes to known bugs.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different file, no dependency on an incomplete task
- **[Story]**: which slice this belongs to (US1…US5)

## Path conventions

Engine is `engine/vg/`, tests are `engine/tests/`, console is `web/src/`. Run pytest from the
**repo root** as `python -m pytest engine`.

> **The line-ending trap applies to four of the files below.** `engine/vg/api/*.py`,
> `web/src/services/api.ts`, `web/src/types.ts` and `STATUS.md` are **CRLF**; almost everything
> else is LF, and there is no `.gitattributes`. Editing any of them with a tool that reads and
> writes text rewrites every ending and turns a six-line change into a whole-file diff. Check
> `git diff --stat` after touching `schemas.py`, `app.py`, `live.py`, `store.py`, `api.ts`,
> `types.ts` or `STATUS.md`.

---

## Phase 1: Setup

**Purpose**: a trustworthy starting line and somewhere to put the tests.

- [X] T001 Record the real pytest baseline into `specs/011-camera-onboarding/evidence/pytest-baseline.txt` by running `python -m pytest engine -q --color=no 2>/dev/null | tail -3` — **stderr must be redirected away**, because OpenCV writes `open VIDEOIO/FFMPEG: Failed to initialize VideoWriter` mid-progress and under `2>&1` it corrupts the progress line and loses the summary. Record the exact `N passed, M skipped` line; 1,420 tests are collected today
- [X] T002 [P] Create `engine/tests/test_sources.py` with the module docstring and imports only, using the `authed` and `bare_live_store` fixtures from `engine/tests/conftest.py`
- [X] T003 [P] Create `engine/tests/test_feature_assignment.py` with the module docstring and imports only
- [X] T004 Confirm all four gates are green before changing anything: `python -m pytest engine`, `python -m pyflakes engine/vg engine/tools engine/tests`, `cd web; npx tsc -b --force`, `.\dev.ps1 doctor`

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the closed feature vocabulary, the six missing columns, the wire types, and audit on
the two endpoints that already exist. Every user story below needs some part of this.

**⚠️ No user story may begin until this phase is complete.**

### Closed feature vocabulary

- [X] T005 Write the failing test in `engine/tests/test_config.py`: a camera whose `features` names something not in the vocabulary is refused by `CameraConfig.parse`, and the message contains the unknown name
- [X] T006 Add a `FEATURES` frozenset — `attendance, counting, intrusion, track, vehicles, weapons, lostitems` — to `engine/vg/config.py` beside the existing `PERSON_FEATURES`, and make `CameraConfig.parse` refuse any name outside it. Verify both cameras in `engine/engine.yaml` still load (they use only valid names)

### The six missing columns

- [X] T007 Write the failing tests in `engine/tests/test_ingest.py`: `faces`, `gate`, `direction`, `face_gate`, `live_capture` and `neighbours` survive an `add()` → `all()` round trip; and opening a database that already has the columns is a no-op
- [X] T008 Add the six columns to `SCHEMA` in `engine/vg/ingest/store.py` and migrate an existing database with the project's proven idiom — `PRAGMA table_info(camera)` then `ALTER TABLE camera ADD COLUMN …` for each absent name. **Copy `engine/vg/events/vehicles.py`**, the `for table, column, ddl in (...)` loop. Do not add a migration framework
- [X] T009 Extend `CameraStore.add` in `engine/vg/ingest/store.py` to take and persist the six new fields, still building a `CameraConfig.parse(...)` and letting it be the only validator
- [X] T010 Extend `CameraStore.all` in `engine/vg/ingest/store.py` to read the six new columns back into `CameraConfig`

### Wire types

- [X] T011 [P] In `engine/vg/api/schemas.py` (**CRLF**) extend `CameraSource` with `features`, `faces`, `enabled`, `gate`, `direction`, `fps`, `rotate`, `from_config`, and `AddCameraRequest` with `faces`, `gate`, `direction`, `neighbours`, per `contracts/sources-api.md`
- [X] T012 [P] In `engine/vg/api/schemas.py` (**CRLF**) reshape `DvrConnectRequest` (add `template`, `channels`, `budget`), `DvrChannel` (add `source`, `checked`, `status`, `latency_ms`, `error`; make `resolution` real) and `DvrConnectResult` (add `reachable`, `reason`, `checked`; make `source_id` nullable)
- [X] T013 [P] In `engine/vg/api/schemas.py` (**CRLF**) add `ScanResult`, `FeatureNote`, `EditCameraRequest`, `EditCameraResult`, `BulkAddRequest` and `AddCameraOutcome`. All subclass `Wire` — snake_case in, camelCase out, `extra="forbid"`
- [X] T014 Update the `Store` protocol in `engine/vg/api/store.py` (**CRLF**): `scan` returns `ScanResult`, and add `edit_camera` and `bulk_add`

### Audit on what already exists

- [X] T015 Write the failing test in `engine/tests/test_sources.py`: adding and removing a camera each write an audit entry, and the entry is written **before** the change takes effect
- [X] T016 Add `user: auth_deps.AdminUser` to `add_source` and `remove_source` in `engine/vg/api/app.py` (**CRLF**) and call `self._log(actor, "camera.add"|"camera.remove", camera_id, detail)` before the write. `detail` is built from the **redacted** source — copy the `remove_person` endpoint for the shape. Do **not** add an authorization decorator; `/sources` is already in `ADMIN_PREFIXES`
- [X] T017 [P] Write the test in `engine/tests/test_sources.py`: signing in as `it` rather than `admin` gets 403 from every write under `/sources`, decided by path and not by the console hiding a button

**Checkpoint**: the vocabulary is closed, the roster can hold every field a camera has, the wire can
carry them, and nothing under `/sources` changes without an audit entry.

---

## Phase 3: User Story 1 — The recorder stops lying (Priority: P1) 🎯 MVP

**Goal**: what the console says about a recorder is what the recorder said. `LiveStore` has never
overridden `connect_dvr`, so the live engine answers from `MockStore` — sixteen channels, `ok`,
`704x576`, whatever the recorder is and whether or not it answered. And `LiveStore.scan` returns
`[]`, which the console renders as "0 devices found".

**Independent test**: `POST /sources/dvr` at a host that does not exist returns 200,
`reachable: false`, a reason and **zero** channels. Needs no recorder and no other slice.

### Tests for User Story 1 ⚠️ write first, watch them fail

- [X] T018 [P] [US1] In `engine/tests/test_sources.py`, the guard test: `assert LiveStore.connect_dvr is not MockStore.connect_dvr`. Copy the shape of the existing `LiveStore.ask is MockStore.ask` assertion in `test_ask.py` — it exists for exactly this bug class, and this is the cheapest possible guard on the bug that caused this whole feature
- [X] T019 [P] [US1] Test in `engine/tests/test_sources.py`: an unreachable recorder returns **200** with `reachable: false`, a reason, and `channels: []`. Never a 5xx, and never a channel list
- [X] T020 [P] [US1] Test in `engine/tests/test_sources.py`: against a source that does answer, only channels that returned a frame come back `status: ok`, each carrying a **real** resolution read off that frame
- [X] T021 [P] [US1] Test in `engine/tests/test_sources.py`: with a budget too small for the channel count, the channels never reached come back `checked: false` — asserted to be a **different** answer from `checked: true, status: down`
- [X] T022 [P] [US1] Test in `engine/tests/test_sources.py`: a `template` with no `{channel}` placeholder is refused **422**
- [X] T023 [P] [US1] Test in `engine/tests/test_sources.py`: `POST /sources/scan` returns `available: false` with a reason, still 200 — "we cannot look" and "your network is empty" must not be the same answer
- [X] T024 [P] [US1] Test in `engine/tests/test_sources.py`: a probe of `rtsp://admin:SENTINELPW@host/s` returns no field anywhere containing `SENTINELPW`

### Implementation for User Story 1

- [X] T025 [US1] Add a `_probe_channel` helper to `engine/vg/api/live.py` by **copying `LiveStore.test_connection` whole** — it already folds credentials, handles `open()` failure, the stale-frame case, latency and `finally: probe.close()`. Do not write a second prober
- [X] T026 [US1] Write `LiveStore.connect_dvr` in `engine/vg/api/live.py` — **the override that was never written**. Build each channel URL from the template, probe with bounded concurrency under one **total** budget, and return every channel with what actually happened. Redact `source` on every channel
- [X] T027 [US1] Replace `LiveStore.scan` in `engine/vg/api/live.py` — `return []` becomes a `ScanResult` with `available: false` and a reason naming why discovery is unavailable
- [X] T028 [P] [US1] Move `MockStore.connect_dvr` and `MockStore.scan` in `engine/vg/api/store.py` (**CRLF**) onto the new shapes. They stay fixtures — demo mode is fixtures and says so — but must not have a shape the live store cannot produce
- [X] T029 [US1] Update the `/sources/dvr` and `/sources/scan` endpoints in `engine/vg/api/app.py` (**CRLF**) for the new request and response types
- [X] T030 [US1] Fix `connectDvr` in `web/src/services/api.ts` (**CRLF**) — it returns `{ channels: result.channels.length }` and **throws the channel list away**, so even a truthful engine response would be discarded. Return the channels. Update `scanNetwork` to return the `ScanResult`
- [X] T031 [P] [US1] Update `web/src/types.ts` (**CRLF**) for `DvrChannel`, `ScanResult` and the new `CameraSource` fields
- [X] T032 [US1] In `web/src/components/CameraSources.tsx`: render the channels the **engine** returned rather than regenerating `CH 1…N` / `Camera 1…N` in `startDvrConnect`; set the `dvrChannels` initial state to `[]` instead of eight invented rows; show `checked: false` differently from `status: down`; render the scan-unavailable reason instead of "0 devices found"; delete the hardcoded `192.168.1.0/24` range text. Add a `template` and channel-list field to the recorder form
- [X] T033 [P] [US1] Add the new `source.*` keys to `web/src/i18n/keys.ts`, `en.ts` and `ar.draft.ts` — one per state the engine can report, so the engine sends a state and the console builds the sentence

**Checkpoint**: a recorder that is switched off says so. Every channel offered was opened and
returned a frame. This is shippable on its own and is the MVP.

---

## Phase 4: User Story 2 — Nothing appears that was not saved (Priority: P2)

**Goal**: `addFound()` and `addDvr()` in `CameraSources.tsx` push rows into local state and **call
nothing** — `addDvr` even invents the address from a counter. A ticked "Capture service" at
`192.168.1.10` does not exist. And the name and area typed against a channel are discarded before
the fake save even gets to them, because the input is uncontrolled and the `<select>` has no
handler.

**Independent test**: tick channels, type names and areas, press Add, refresh the page. Everything
is still there with the names you typed. Then restart the engine; still there.

### Tests for User Story 2 ⚠️ write first

- [X] T034 [P] [US2] In `engine/tests/test_sources.py`: `POST /sources/bulk` with 16 cameras returns **200** and 16 outcomes, positionally aligned by `index`
- [X] T035 [P] [US2] Test in `engine/tests/test_sources.py`: when the 4th camera is refused (duplicate id), the other 15 are still added and its outcome carries the reason. One bad channel must not refuse fifteen good ones
- [X] T036 [P] [US2] Test in `engine/tests/test_sources.py`: every `AddCameraOutcome.source` is redacted
- [X] T037 [P] [US2] Test in `engine/tests/test_sources.py`: a bulk add does not stop or restart any camera already in `registry.workers`

### Implementation for User Story 2

- [X] T038 [US2] Add `LiveStore.bulk_add` to `engine/vg/api/live.py` — loop `add_camera`, catch per item, audit each **before** its own write, never abandon the rest on a failure
- [X] T039 [US2] Add `POST /sources/bulk` to `engine/vg/api/app.py` (**CRLF**) with `user: auth_deps.AdminUser`. Always 200 — a refused camera is payload, not a request failure
- [X] T040 [P] [US2] Add `addCameras` to `web/src/services/api.ts` (**CRLF**)
- [X] T041 [US2] Delete the `source.captureService` block from `web/src/components/CameraSources.tsx` — a ✓ badge on a device at `192.168.1.10` that does not exist — and remove `source.captureService` and `source.captureServiceLead` from `web/src/i18n/keys.ts`, `en.ts` and `ar.draft.ts`
- [X] T042 [US2] Rewrite `addDvr()` in `web/src/components/CameraSources.tsx` to call the bulk endpoint with the ticked channels, their typed names and their chosen areas, and to render the per-camera outcomes. Delete the invented `dvr-${n}` / `192.168.1.${50+n}` row
- [X] T043 [US2] Rewrite `addFound()` in `web/src/components/CameraSources.tsx` to call the engine instead of pushing a `found-${ip}` row with `status: 'ok'`
- [X] T044 [US2] Make the channel rows controlled in `web/src/components/CameraSources.tsx`: the name input uses `value`/`onChange` instead of `defaultValue`, and the area `<select>` gains both — **today what the operator types against a channel is discarded**
- [X] T045 [US2] Show the per-camera outcome for a bulk add inline in `web/src/components/CameraSources.tsx`, with new i18n keys in `keys.ts`, `en.ts` and `ar.draft.ts`

**Checkpoint**: everything on the screen was written, and survives a refresh and a restart.

---

## Phase 5: User Story 3 — The feature list governs (Priority: P3)

**Goal**: `_start_weapons` and `_start_zones` both use `[c.id for c in roster if c.enabled]` —
**every enabled camera** — and `BagWatch` takes no camera list at all, so any camera anybody opens
gets bag detection. The `features:` list is decorative for three of seven features.

**This slice changes behaviour and must ship loudly.** `cam-laptop` lists
`attendance, counting, intrusion, track, vehicles` and not `weapons`, so knife detection stops on
the only enabled camera in this repository; under `-Clip` it is zero cameras. That is the config
file already saying what it wants, and the current behaviour is the bug — but it is still a change
somebody must be told about.

**Independent test**: with `weapons` absent from a camera's list, no knife detection runs on it and
System Health says why. Pure engine; needs no console work and no other slice.

### Tests for User Story 3 ⚠️ write first

- [X] T046 [P] [US3] In `engine/tests/test_feature_assignment.py`: `WeaponsWorker` is constructed with only the cameras listing `weapons`, and a camera without it is not in `worker.cameras`
- [X] T047 [P] [US3] Test in `engine/tests/test_feature_assignment.py`: `ZonesWorker` is constructed with only the cameras listing `intrusion`
- [X] T048 [P] [US3] Test in `engine/tests/test_feature_assignment.py`: `BagWatch` ignores `note_interest` for a camera not listing `lostitems`, and its overlay returns no boxes for that camera
- [X] T049 [P] [US3] Test in `engine/tests/test_feature_assignment.py`: with no camera listing `weapons`, System Health reports knife detection as unavailable **with a reason naming what to do**, and stays a 200

### Implementation for User Story 3

- [X] T050 [US3] Change `_start_weapons` in `engine/vg/api/app.py` (**CRLF**) to `[c.id for c in roster if c.enabled and "weapons" in c.features]`, and add the honest sentence for "no camera is set to check for knives" — **copy the shape already in `_start_vehicles`**: *"No camera is set up as a gate, so no plates are being read. A gate camera needs a gate number and a direction."* A state, a consequence, and what to do
- [X] T051 [US3] Change `_start_zones` in `engine/vg/api/app.py` (**CRLF**) to `"intrusion" in c.features`, with the same honest sentence treatment
- [X] T052 [US3] Pass the `lostitems` cameras from `_start_lost` in `engine/vg/api/app.py` (**CRLF**) into `BagWatch`
- [X] T053 [US3] Add a `cameras: set[str]` to `BagWatch` in `engine/vg/features/lostbag.py` and refuse interest outside it. `BagWatch` is **not** a `FeatureWorker` — it is one thread driven entirely by the overlay poll, so this is a check in `note_interest`, not a camera list on a base class
- [X] T054 [US3] Log at startup how many cameras are checked for knives and for restricted areas, in `engine/vg/api/app.py` (**CRLF**), so the change is visible in the log as well as on the page
- [X] T055 [US3] Record the behaviour change in `STATUS.md` (**CRLF**): knife detection and restricted-area watching now follow the camera's feature list, `cam-laptop` does not list `weapons`, and what an operator does about it

**Checkpoint**: a feature not assigned to a camera does not run on that camera — for all seven.

---

## Phase 6: User Story 4 — Assignment takes effect without a restart (Priority: P4)

**Goal**: `FeatureWorker.start()` takes its camera list once, at construction, so a camera added at
runtime streams and appears in the grid and **nothing analyses it until the engine restarts**.

**Independent test**: add `weapons` to a running camera from the console; knife detection starts on
it within 10 seconds, and no other camera is disturbed.

> **The trap this slice exists around.** `ZonesWorker.set_restricted`'s docstring is the record of a
> bug already paid for: closing a scene from the API thread while the camera's own thread was
> mid-`analyse` made that thread open a *second* scene, whose clip then replaced the first one's —
> so switching a camera off destroyed the recording of the scene that was running. `unwatch` has the
> same shape. It must set a flag and return; the camera's **own thread** does the closing.

### Tests for User Story 4 ⚠️ write first

- [X] T056 [P] [US4] In `engine/tests/test_feature_assignment.py`: `watch()` on a running worker starts analysing that camera, and `stats["cameras"]` reflects it
- [X] T057 [P] [US4] Test in `engine/tests/test_feature_assignment.py`: `unwatch()` stops analysis on that camera and **the same feature keeps running on another camera without a gap** — the isolation assertion, and the most important test in this slice
- [X] T058 [P] [US4] Test in `engine/tests/test_feature_assignment.py`: `unwatch()` on a camera with an open zone scene closes that scene with a reason **on the camera's own thread**, and the scene's clip still exists afterwards. This is the regression test for the bug named above
- [X] T059 [P] [US4] Test in `engine/tests/test_feature_assignment.py`: changing `faces` moves a camera between `recogniser` and `patrol` with **no instant where neither serves it** — assert watch-before-unwatch ordering
- [X] T060 [P] [US4] Test in `engine/tests/test_feature_assignment.py`: assigning a feature whose worker is `None` (use `bare_live_store`) still adds the camera and returns a `FeatureNote` with `running: false` and the subsystem's own reason. It must neither refuse the camera nor accept silently
- [X] T061 [P] [US4] Test in `engine/tests/test_feature_assignment.py`: unwatching one feature on a camera leaves every other feature on that same camera running

### Implementation for User Story 4

- [X] T062 [US4] In `engine/vg/features/base.py`: change `self._threads` from `list` to `dict[str, Thread]`, add `self._drop: dict[str, threading.Event]`, and take `self._lock` in `serves()` and `stats` — both read `self.cameras` without it today, safe only because it never mutates
- [X] T063 [US4] Add `FeatureWorker.watch(camera_id)` and `unwatch(camera_id)` to `engine/vg/features/base.py`. `watch` appends and starts one thread; `unwatch` sets that camera's drop event and **returns immediately**. `stop()` still sets the worker-wide `_stop`
- [X] T064 [US4] Add an overridable `_closing(camera_id)` hook to `engine/vg/features/base.py`, called from `_run`'s `finally` **before** `bus.unsubscribe` — so it always runs on the camera's own thread. Base implementation drops `_results` and `_boost_until`
- [X] T065 [P] [US4] Override `_closing` in `engine/vg/features/zones.py` to close any open scene via the existing `self._close(camera_id, at, reason)`
- [X] T066 [P] [US4] Override `_closing` in `engine/vg/features/weapons.py` to close any open scene and end its video, and drop `_last_frame_at` and `_seen`
- [X] T067 [P] [US4] Override `_closing` in `engine/vg/features/vehicles.py` to drop `_tracks`, `_recent`, `_attempts` and `_read_ms`
- [X] T068 [P] [US4] Override `_closing` in `engine/vg/features/tracking.py` to drop `_seen` **without disturbing a running follow**
- [X] T069 [US4] Add `LiveStore._apply_features(config, previous=None)` to `engine/vg/api/live.py`, implementing the feature→worker table in `data-model.md` across the eight workers `LiveStore` already holds. Skip an absent worker and collect its reason from the matching `*_error` field. Watch the new identity tier **before** unwatching the old
- [X] T070 [US4] Add `LiveStore._unwatch_everywhere(camera_id)` to `engine/vg/api/live.py`, and call it from `remove_camera`
- [X] T071 [US4] Call `_apply_features` from `LiveStore.add_camera` in `engine/vg/api/live.py`, and return `feature_notes` on the response
- [X] T072 [US4] Show the feature notes in `web/src/components/CameraSources.tsx` — a chosen feature that is not running says so at the moment it is chosen, with new i18n keys in `keys.ts`, `en.ts` and `ar.draft.ts`

**Checkpoint**: a camera added or changed is analysed by its chosen features within 10 seconds,
with no restart and no other camera disturbed.

---

## Phase 7: User Story 5 — A camera can be corrected (Priority: P5)

**Goal**: `CameraStore` has `add`, `remove` and `set_enabled` and no `update`. A wrong area, a wrong
frame rate or a mistyped address means deleting the camera and adding it again — losing the link
between it and everything recorded against it.

**Independent test**: add a camera with a typo, edit it, confirm its `id` did not change and its
recorded events are still attached.

### Tests for User Story 5 ⚠️ write first

- [X] T073 [P] [US5] In `engine/tests/test_sources.py`: a `PATCH` changing only name, area or features returns `restarted: false` — **reopening an RTSP stream to add a tickbox is a visible stutter for nothing**
- [X] T074 [P] [US5] Test in `engine/tests/test_sources.py`: a `PATCH` changing `source`, `fps`, `rotate` or `enabled` returns `restarted: true`
- [X] T075 [P] [US5] Test in `engine/tests/test_sources.py`: a `PATCH` on `cam-laptop`, which comes from `engine.yaml`, returns `shadows_config: true`
- [X] T076 [P] [US5] Test in `engine/tests/test_sources.py`: the camera's `id` is unchanged by an edit, and events recorded against it before the edit are still reachable after it
- [X] T077 [P] [US5] Test in `engine/tests/test_sources.py`: `PATCH` audits **before** it writes; and a `PATCH` carrying a password puts no password in the audit detail
- [X] T078 [P] [US5] Test in `engine/tests/test_sources.py`: `PATCH` on an unknown id is **404**, and on a store with no runtime roster is **503** — "nothing is running" is not the same answer as "not found"

### Implementation for User Story 5

- [X] T079 [US5] Add `CameraStore.update(camera_id, **changes)` to `engine/vg/ingest/store.py` — merge onto the current config, validate through `CameraConfig.parse`, write. For a YAML-seeded camera with no stored row it **inserts** one, which is what makes `merge_cameras`' stored-wins shadow the file
- [X] T080 [US5] Add `LiveStore.edit_camera` to `engine/vg/api/live.py`: audit first, validate, persist, touch `registry.add` **only when the stream changed**, then `_apply_features(config, previous)`. Return `shadows_config`, `restarted` and `feature_notes`
- [X] T081 [US5] Add `PATCH /sources/{id}` to `engine/vg/api/app.py` (**CRLF**) with `user: auth_deps.AdminUser`; `ValueError` → 422, missing camera → 404, `SubsystemUnavailable` → 503
- [X] T082 [P] [US5] Add `editCamera` to `web/src/services/api.ts` (**CRLF**)
- [X] T083 [US5] Add an edit form to `web/src/components/CameraSources.tsx` — a camera row opens the same form prefilled, and saving sends the `PATCH`. Show what editing a `fromConfig` camera means, using `shadowsConfig`
- [X] T084 [US5] Expand `FEATURES` in `web/src/components/CameraSources.tsx` from three entries to **seven**, each with its cost line, and reveal each feature's settings when it is picked: identity tier for attendance, gate number and direction for vehicles, restricted for intrusion. Add the keys to `web/src/i18n/keys.ts`, `en.ts` and `ar.draft.ts`

**Checkpoint**: a camera can be set up, corrected and retired from the console alone, with no config
file editing and no restart.

---

## Phase 8: Polish & cross-cutting

- [X] T085 [P] Write the credential sweep test in `engine/tests/test_sources.py`: add a camera whose source contains a sentinel password, then assert it appears in **no** `/sources` response, no probe result, no bulk outcome, no edit response, no `/audit` entry and no log record. One test, every path
- [X] T086 [P] Add a search box to the camera list in `web/src/components/CameraSources.tsx` filtering by name, area and status, so one camera stays findable among many. **No pagination and no camera-count claim** — that is P8 and out of scope here
- [X] T087 [P] Document the seven feature names in `engine/engine.yaml`'s `cameras:` comment block, where the current comment lists only three
- [X] T088 [P] Update `STATUS.md` (**CRLF**) with the state of camera onboarding after this feature, including what is now real that was a fixture
- [X] T089 Run `python -m pyflakes engine/vg engine/tools engine/tests` — clean. This catches the exact bug class that once silently killed face recognition
- [X] T090 Run `cd web; npx tsc -b --force` — clean. **Never `tsc --noEmit`**; project references make it a silent no-op
- [X] T091 Run `python -m pytest engine` from the repo root — green, and the count must not have dropped below the T001 baseline
- [X] T092 Run `.\dev.ps1 up -Clip` and confirm the pipeline behaviour on the recorded clip, including that knife detection reports zero cameras and says so
- [X] T093 Walked `quickstart.md` sections 1-7 against the real app with its full startup — 42 checks, 0 failures. Repeatable as `evidence/walk_quickstart.py`; output in `evidence/quickstart-walk.txt`. Runs on a throwaway database, so it never touches `engine/data`. The one part not covered is the visual half of section 2 (the console rendering), which needs a signed-in browser and therefore an account — see T094
- [ ] T094 **For Mohamed — three things only a person on the machine can settle.** (a) A real recorder: give the console its address, credentials and channel pattern, and confirm the channels it lists match what is actually plugged in. (b) Adding a camera on a busy site makes no other camera stutter. (c) The console screen itself — there is no account on this machine (`python engine/tools/create_user.py` prompts for a password, so it was not run), which is why the browser half of quickstart section 2 is unwalked

---

## Dependencies & execution order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**
- **US1 (Phase 3)**: needs T012, T013, T014 (the DVR and scan wire types)
- **US2 (Phase 4)**: needs T013 (`BulkAddRequest`), T016 (audit); benefits from US1 but is testable without it
- **US3 (Phase 5)**: needs T005–T006 (the closed vocabulary) only. **Independent of US1, US2, US4, US5**
- **US4 (Phase 6)**: needs T005–T010; uses the feature→worker table US3 establishes, so land US3 first
- **US5 (Phase 7)**: needs T007–T010 (columns) and US4 (`_apply_features`)
- **Polish (Phase 8)**: after every story you intend to ship

### Story dependency graph

```
Setup ─► Foundational ─┬─► US1 (recorder truth)      ── independent
                       ├─► US2 (nothing unsaved)     ── independent
                       ├─► US3 (list governs)        ── independent
                       │      └─► US4 (no restart)
                       │             └─► US5 (edit)
                       └────────────────────► Polish
```

### Parallel opportunities

- **Phase 2**: T011, T012, T013 are three separate additions to `schemas.py` — same file, so land them in sequence, but T017 runs alongside any of them
- **Phase 3**: T018–T024 are seven independent tests, all parallel. T028, T031, T033 are parallel with each other
- **Phase 4**: T034–T037 parallel; T040 parallel with the console work
- **Phase 5**: T046–T049 parallel; T050–T052 all touch `app.py` so they are sequential
- **Phase 6**: T056–T061 parallel; T065–T068 are four different feature files and fully parallel
- **Phase 7**: T073–T078 parallel
- **Across stories**: once Phase 2 is done, US1, US2 and US3 can be worked by three people at once

### Within each story

- Tests are written first and must **fail** before the implementation lands
- Engine before console — the console cannot render a field the wire does not carry
- `schemas.py` before `live.py` before `app.py` before `api.ts` before the component

---

## Parallel example: User Story 1

```bash
# All seven US1 tests can be written at once — different assertions, one new file:
Task: "Guard test: LiveStore.connect_dvr is not MockStore.connect_dvr"
Task: "Unreachable recorder returns 200, reachable false, zero channels"
Task: "Only channels that returned a frame come back ok, with a real resolution"
Task: "Budget exhausted gives checked:false, distinct from status:down"
Task: "Template without {channel} is refused 422"
Task: "Scan returns available:false with a reason, still 200"
Task: "A probe leaks no password"
```

---

## Implementation strategy

### MVP — User Story 1 only

1. Phase 1 Setup
2. Phase 2 Foundational
3. Phase 3 US1
4. **Stop and validate**: `POST /sources/dvr` at a dead host returns a reason and zero channels
5. Ship it

That alone removes the largest untruth in the product and satisfies the constitution's Principle
III for this screen. Everything after it is completeness rather than honesty.

### Incremental delivery

| Increment | What the operator gains |
|---|---|
| Setup + Foundational | nothing visible; the roster can hold a whole camera and every write is audited |
| **+ US1** | the recorder tells the truth, and so does the scan |
| **+ US2** | what they add is saved, and stays saved |
| **+ US3** | a feature runs only where it was asked for |
| **+ US4** | changes take effect without restarting the site |
| **+ US5** | mistakes can be corrected instead of re-created |

### Parallel team strategy

Two people after Phase 2: one takes US1 → US2 (truth and persistence, engine + console), the other
takes US3 → US4 (the engine's feature wiring). They meet at US5, which needs both.

---

## Notes

- **Read `context.md` first.** The anchor for every task above, what it looks like today, and the
  traps are all there.
- **`AGENTS.md`'s four-file recipe does not apply.** This is not a new product feature; it is the
  configuration surface the seven existing features share.
- **Do not add an authorization decorator anywhere.** `/sources` is already in `ADMIN_PREFIXES`, and
  permissions are decided by path precisely so that the one endpoint somebody forgets to decorate
  cannot leak.
- **Never write back into `engine.yaml`.** The database is the source of truth; the file is the
  bootstrap seed. This is settled and not reopened here.
- Commit after each task or logical group, and every fix to a known bug ships with its regression
  test in the same commit.
- Three open questions are listed in `context.md` §5 — check them in code, do not assume.
