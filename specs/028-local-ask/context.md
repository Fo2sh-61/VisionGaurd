# Implementation context: Local Ask

**Written by `/speckit-plan` on 10 Nov 2026, against `Fo2sh` `76644ef`, with
`origin/console-v2-jetson` `ce6f8ec` read alongside.**

Read this **before** opening any source file, then open only the named anchors.

> Verify before trusting. If decision D1 holds, the build happens on top of
> console v2, and v2 has already changed `store.py`, `menu.py`, `deps.py` and
> `test_ask.py`. Search for symbols; never trust a line number here.

---

## 1. Anchors

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `vg/ask/parser.py` | `class Parsed`, `class Parser`, `build_parser` | `Parsed{query, params, missing}`. The class gives all three defaults; only Gemini's `schema_for` marks them required. No score. `Parser.parse(masked) -> Parsed`. `build_parser(vocabulary)` is rebuilt **every call** from `vgconfig.load()`; it returns `UnavailableParser("no configuration" / "switched off" / "no key")` or a `CloudParser`. `CloudParser` stores a timeout it never uses. | Delete `CloudParser`, `schema_for`, `loads`, `instructions_for`, `_reason`. Add `score`, `alternatives`, `decision`. `build_parser` returns a **cached** `LocalParser`; rebuilding per call would re-embed 225 examples per question. |
| `vg/ask/__init__.py` | `__all__` | re-exports `CloudParser`, `instructions_for`, `build_parser` **and `unrecognised`**, which `MockStore.ask` imports | drop the cloud names; export `LocalParser`, `Encoder`; **keep `unrecognised`**, now the possible-name check for learned examples |
| `vg/ask/menu.py` | `class AskQuery`, `QUERIES` | `AskQuery{id, describe, params, reads, run, route, stores_nothing}`. 14 entries on Fo2sh, 13 on v2 (no `weapons`). `TODAY="@today"`. `WINDOWS={today:1, yesterday:2, last7, last30, last90}`, where yesterday is **rolling 2 days**. Rows set `camera=` to a display name, **except `_run_inside`, which sets `str(v.entry_gate)` (an int)**. `_run_passes` does `int(p["gate"])`, so gate must be a number. | add `clips`, `feature`, `opens_live` fields; add a `live_view` entry; set `clips="saved"` on `zone_breaches`/`weapons` and `"recorder"` on `attendance`, `person_path`, `vehicle_passes`. **`person_history` rows have no camera or time, so they get no clips.** `AttendanceDay` (only `location`) and `VehiclePass` (only `gate`/`gate_name`) **gain `camera_id`** in their stores. Rows must carry the camera **id** internally (to the ledger, not the wire). Docstrings saying "thirteen" are wrong on Fo2sh. |
| `vg/ask/mask.py` | `normalise`, `skeleton`, `Dictionary.build(people, plates)`, `mask`, `_COMMON` | `Dictionary` covers names and plates only, with `PERSON_n`/`PLATE_n`/`PERSON_UNCLEAR_n`. `_COMMON` lists date words **only to hide them from the stray-word warning**. | reuse `normalise`/`skeleton` in `lexicon.py`; **keep `unrecognised()` and `_COMMON`**. They stop driving `words_left_site` and become the possible-name check for learned examples (P15-FR-012) |
| `vg/api/store.py` | `MockStore.ask` | 1. builds the Dictionary, masks; 2. `entry=self._log(actor,"ask",question,f"sent: {masked}")`; 3. parse; 4. `find`; 5. unmask + defaults → `AskUnderstanding`; 6. needs_detail; 7. `stores_nothing` → `ask.not_recorded`; 8. `_ask_unresolvable`; 9. run. `SubsystemUnavailable` → **`ask.cloud_unavailable`** (wrong code). `sent_off_site=masked` on every outcome. `entry.detail` is mutated after the fact. | insert the lexicon after the mask; add the CHOOSE / LIVE / switched-off branches; `sent_off_site=""`; new subsystem code; register clip refs in the ledger. **Keep it on MockStore**: `test_live_store_does_not_override_ask` asserts `LiveStore.ask is MockStore.ask`. |
| `vg/api/store.py` | `_ask_places`, `_ask_groups`, `_ask_names`, `_ask_plates`, `_ask_unresolvable`, `_ask_parser` | places come from `areas()`, groups from `groups()`. They are used three ways: as `site_words`, as the Gemini vocabulary via `_ask_parser`, and by `_ask_unresolvable`, which calls `areas()`/`groups()` directly and matches by exact casefold | they become lexicon inputs (the vocabulary use goes away); add `_ask_gates` (numbers) and `_ask_cameras`; the lexicon must emit the exact canonical spelling |
| `vg/api/live.py` | `_ask_state`, `capabilities` (`"ask"`), `_weapons_stage` | `_ask_state` checks `config.ask.enabled`, then the env `GEMINI_API_KEY`. Ask has no `PipelineStage`. | `_ask_state` reports model-loaded / reason / last accuracy; add `_ask_stage` copying `_weapons_stage`; wire `ExampleStore` and the Ask archive lane |
| `vg/api/app.py` | `def ask(` (POST `/ask`), `_start_archive`, `app.state.archive_error` | `/ask` takes `actor: Query="unknown"`, **so every Ask audit row says "unknown"** on Fo2sh (v2 already uses `CurrentUser`). `archive_error` is set and never read. | use `CurrentUser`; add the `/ask/clips…` and `/ask/examples…` routes; pass `archive_error` into the clip `no_archive` reason |
| `vg/auth/deps.py` | `ADMIN_PREFIXES` | `("/enrolment","/sources","/users")`; v2 adds more | append `"/ask/examples"`. `/ask` and `/ask/clips` stay outside it. |
| `vg/ingest/archive.py` | `ArchiveRunner.submit`, `_process`, `_retain`, `DvrBackend.fetch`, `FootageBackend.fetch`, `ArchiveUnavailable` | `submit(camera_id,start,end,person_id=None,descriptor=None,prefetch=False)` → `LegJob`. `_process` outlines people **whenever a detector is loaded**. `_retain` keeps `keep_legs` per camera. `workers=2, queue_size=8`. `FETCH_TIMEOUT_SECONDS=120.0` is a constant. Footage fetch matches only if `start` is inside one file. Failures raise `ArchiveUnavailable` (free text) or `QueueFull` from `submit`; `NotMeasured` is unused. | `plain=True` → move with no detector; `lane="ask"` with its own worker, queue, folder, retention and timeout; `ArchiveUnavailable.cause`, with `QueueFull` → `busy`; 5 s pieces on the Ask lane; clamp the footage span to the containing file |
| `vg/config.py` | `AskConfig.parse`, `ArchiveConfig.parse` | both reject unknown keys (a `known` set). `AskConfig(enabled, model, timeout_seconds)`, where model must be non-empty. | new keys per data-model §6; old Gemini `model:` values tolerated with a warning |
| `vg/api/schemas.py` | `AskOutcome`, `AskRow`, `AskAnswer`, `AskRequest` | `AskRow.camera: str` (a name), `clip_url`. `AskAnswer` has no free-text field, by design. | per data-model §4 |
| `vg/api/notes.py` | `CODES` | the Ask codes are listed together | per data-model §5 |
| `tools/ask_corpus.py` | `main`, the line `ok = got == want or got in case["accept"]` | builds a `CloudParser` directly, scores the query id only, and has Gemini retry/429 handling | rewrite: `build_parser()`, offline, score query + params + decision, per language, scoring part only; write the evidence file |
| `requirements.txt` | `google-genai` | present; no onnxruntime or tokenizers | swap |
| `web/src/pages/Home.tsx`, `mobile/src/pages/Home.tsx` | `submit()` | its only state is `question` + `note`; it calls `ask(text, role)` from `services/ask.ts`, which collapses the answer to `route | note | ignore` and **throws away** understood, rows, clipUrl and auditId | render `<AskAnswer>` under the bar. Home is **not** a parity file, so edit both by hand. |
| `services/ask.ts` | `ask()` | keeps the whole `answer` only in the `route` variant, and **any note wins**, so an answered result that also carries a note loses its rows. It is `Home.submit` that throws the rest away, by navigating with `outcome.to` only | return the answer as it is; parity file (LF in both apps) |
| `web/src/components/CameraModal.tsx` | `CameraModal` | props `camera, onClose, feature, colour`; **no `detections` prop**. It always renders `<CameraFrame live …>`, where detections default to true, so names show. Opened from `CamGrid` click state only; there is no URL | add a `detections` prop passed through to `CameraFrame`; open from `?camera=` on Home with `detections={false}` |

## 2. Copy, do not invent

- Example store → `events/sightings.py::SightingStore.__init__` (`db.connect`,
  `RLock`, `executescript(SCHEMA)`).
- Health stage → `api/live.py::_weapons_stage` and `_running_on`.
- Audit before the result → `api/live.py::start_leg` (it logs before
  `runner.submit`) and `path_skeleton` (it returns `audit_id=entry.id`).
- Recorder-clip player → `TrackPerson.tsx::LegPlayer` (polls every 1.5 s,
  plays `chunkUrls` in turn, shows `job.error`). It is private in both apps:
  extract it, do not duplicate it.
- Any-camera fetch from the UI → `TrackPerson.tsx::BrowseFootage`
  (`startLeg({cameraId,start,end,personId:null})`).
- Saved clip → `Intrusion.tsx` `<video key src={assetUrl(clipUrl)} controls autoPlay>`.
- Approve and remove UI → `Weapons.tsx` pending verdict buttons; the two-step
  remove in `People.tsx`.
- Date windows → `app.py::weapon_window` (site-local midnights).
- "No camera runs it" → `app.py::_feature_cameras`.
- Wording → note code in `notes.CODES` + `keys.ts` + `en.ts` + `ar.draft.ts`,
  in both apps, copied as **bytes**.

## 3. Traps

- **Live view:** `test_every_entry_answers_with_data_not_a_signpost` passes
  only if `live_view.run` really reads the camera list. Never reuse
  `stores_nothing`: it emits `ask.not_recorded`, and
  `test_only_a_feature_that_records_nothing_is_exempt` pins the exempt list
  to `["lost_item"]`. Give live view its own flag.
- `test_what_left_the_site_is_recorded_even_on_failure` only asserts that a
  name is not in `sent_off_site`, so it already passes with `""`. Tighten it
  to `== ""`, so it guards P15-FR-002.
- **Audit ids restart.** `_log` makes ids as `f"a{len(self._audit)+1}"` in
  memory, so they start again at `a1` after every restart. Never store one as
  a lasting link (`ask.db` keeps `asked_at` instead). The ledger is in memory
  too, so its links are only valid for the same process.
- `test_no_entry_can_write` scans every menu `run` for write verbs. Example
  writes must live in the store and endpoints, never in a menu `run`.
- `_run_path` passes `p.get("actor","ask")`, so the nested `path.skeleton`
  audit row names "ask". Pass the real actor through.
- `person_path` does **not** need tracking: it is built from face anchors.
  Tracking only adds appearance stops. Its `feature` is face recognition, not
  `track`.
- **A missing store reads as "nothing found".** `LiveStore.weapons`,
  `breaches`, `vehicle_passes`, `vehicles_inside` and `vehicle_register` all
  return `[]` when their store is None; `vehicle_register` then reads as "not
  registered". A camera-feature check does not catch this. Ask checks the
  store first → `ask.subsystem_unavailable`.
- **Windows are rolling, not calendar.** `WINDOWS["today"]=1` and
  `["yesterday"]=2` are rolling periods, but `weapon_window` uses calendar
  days. Ask keeps them as they are, so it matches the pages. Do not "fix" this
  inside Ask.
- `AskRow.camera` is a name. Never put a camera id or a time on the wire as a
  clip request; use `clip_ref` only.
- `FootageBackend` treats an mp4 still being written as absent
  (`_duration_of` returns 0). That case is `not_yet`, not `not_recorded`.
- e5 needs the `"query: "` prefix on **both** examples and questions. Without
  it, similarities shift and the thresholds are wrong.
- Thresholds go stale when examples change a lot. `ask_calibrate.py` must
  re-run after a bulk edit of `examples.yaml`, never after single admin
  corrections (the guard covers those).
- **Line endings**: check `b"\r\n" in path.read_bytes()` for **every** file
  before scripting an edit.

  | Line ending | Files (as checked at plan time) |
  |---|---|
  | CRLF | `api/*.py`; `vg/ask/menu.py`, `mask.py`, `parser.py`; `config.py`; `test_ask.py`; web `api.ts`, `wire.ts`, `en.ts`, `keys.ts`, `ar.draft.ts`, `content.ts`, `routes.tsx`, `Home.tsx` |
  | LF | `vg/ask/__init__.py`; `auth/deps.py`; `ingest/archive.py`; both apps' `services/ask.ts`, `notes.ts`, `frame.ts`, `http.ts`; mobile `Home.tsx`; both apps' `TrackPerson.tsx` |
- `tools/audit_models.py` scans only the top level of `models/`, so
  `models/ask/` is invisible to it. Add a check, or say so in
  `models/MODELS.md`.

## 4. Baseline

In this cloud container (Python 3.13, no torch, no ultralytics, no vendored
loiterwatch):
- `python -m pytest engine` gives **1954 collected: 1917 passed, 21 failed,
  16 skipped**.
- All 21 failures are `ModuleNotFoundError`: 13 for `loiterwatch` and 8 for
  `ultralytics`. They are pre-existing and environmental, not caused by this
  feature.
- On Mohamed's PC, expect 0 failures. Take the baseline there before starting.

New test file: `engine/tests/test_ask_local.py`. The 47 tests in `test_ask.py`
are updated, not removed.

## 5. Still unknown

- D1, D2 and D3 in the plan wait for Mohamed.
- On the board: JetPack and Python version; whether the `onnxruntime` and
  `tokenizers` wheels install; resident memory; p95 time; whether NVML reads.
- Whether the site's recorder distinguishes expired from never recorded.
- Where gate names live for the lexicon (vehicle feature config or the camera
  table). Check `LiveStore.vehicle_gates`.
- The 200+ questions do not exist yet. Mohamed writes or corrects them. Until
  then, SC-001 cannot be measured and System Health says "not measured".
