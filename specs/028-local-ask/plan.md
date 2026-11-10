# Implementation Plan: Local Ask on the Jetson, with clips

**Branch**: `spec/028-local-ask` | **Date**: 10 Nov 2026 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/028-local-ask/spec.md`

## Summary

Ask still never answers a question itself. It works out which existing query
the question is, runs it, and shows the real result. What changes is **who
works out the query**. Gemini is removed, and the work happens on the site's
own hardware in three cheap steps, each one only when the step before has not
settled it:

1. **Word lists** find every detail: names and plates (existing masking), plus
   places, groups, gates, cameras, dates, directions, colours, and video and
   live words. Each one is replaced by a placeholder, so the sentence the
   model sees is `وريني PERSON دخل امتى WHEN`. That sentence fits every
   student, not just Sara.
2. **A small meaning model** turns that sentence into 384 numbers and compares
   it with the stored example sentences, which are masked the same way. The
   nearest example's query wins. There is no training and no network.
3. **Two thresholds** decide what happens next: answer, "did you mean A or B?",
   or refuse.

Clips are a second, smaller change. A query can now say its rows have clips.
Each such row carries an opaque reference to a moment Ask itself offered.
Pressing "watch clip" is audited, then either plays the saved clip (breaches,
weapons) or fetches about 10 s either side of the moment from the recorder.
The recorder fetch uses its own small lane, so it can never hold up tracking.

**The answer view does not exist yet, and building it is part of this plan.**
Spec 010's tasks T015 and T023 are ticked, but no Ask page was ever committed.
Today Home's Ask bar either jumps to a page or shows one amber note. The
"understood as" line, the rows, the clip buttons, "did you mean" and live view
are all built here, in both apps.

## Decisions waiting for Mohamed

Each of these is planned with the recommended answer, so work can start, but
he decides.

| # | Question | Recommended | Why |
|---|---|---|---|
| D1 | Build 028 on top of console v2 (`console-v2-jetson`), not on `Fo2sh`? | **Yes. Implement after v2 merges.** | v2 already rewrites Ask's foundations: 13 menu entries (knife removed), role checks per query, the signed-in account as the audit actor, and new admin paths. Building 028 on Fo2sh rebuilds all of that and then conflicts with it. v2 is 7 commits and 126 files ahead. |
| D2 | Run the meaning model with **onnxruntime on the processor** instead of a TensorRT half-precision engine? | **Yes, as an int8 copy made on the board.** | One question costs about 1–2 billion operations, which takes tens of milliseconds on the processor, and the processor is only busy when someone asks. The GPU stays fully with the cameras (SC-006). The repo has no TensorRT code for anything except YOLO, and its own plate measurements showed half precision changing answers. **The 448 MiB file plus runtime overhead will almost certainly break the 500 MB budget**, so the planned default is an int8 copy (about 120 MB) made *on the board from his file*, with nothing downloaded. It is kept only if it routes the tuning set identically to his FP32 file, which stays the reference. TensorRT stays a later option behind the same seam. This changes one spec assumption, now marked pending in the spec. |
| D3 | Knife questions under v2: plain refusal (P14-FR-129) instead of "switched off"? | **Yes.** Already written into P15-FR-021. | v2 says knife has no Ask answer at all. Lost bag and tracking keep their engines, so "switched off" applies to them only when no camera runs them. |

## Technical Context

**Language/Version**: Python 3.14 on the dev PC. On the Jetson, whatever Python
the engine runs on there. The engine's own TensorRT recipe is x86-only, so
check this on the board. TypeScript 5 / React for both apps.

**Primary Dependencies**: **add `onnxruntime`** (CPU build; wheels exist for
aarch64 and x86) and **`tokenizers`** (Hugging Face's tokenizer, with no torch
and aarch64 wheels). **Remove `google-genai`.** numpy is already present.

**Storage**: one new SQLite file, `ask.db`, opened with the same `db.connect`
as the other event stores. It holds suggested and learned examples and their
history. The owner's examples and the test set are YAML files in git. The
model is `models/ask/model.onnx` + `tokenizer.json`, supplied by the owner and
ignored by git.

**Testing**: pytest. A fake encoder (a fixed table of vectors) keeps every
routing test fast and model-free. The real-model accuracy run is a tool plus
one test marked `@pytest.mark.model`, skipped when the model file is absent,
the same way `camera` tests are skipped.

**Target Platform**: Jetson Orin Nano 8 GB (shared with about 40 cameras), and
the Windows dev PC with the same code path.

**Project Type**: web service + two browser apps (console and phone).

**Performance Goals**: "understood as" within 1 s on the Jetson under full
camera load (SC-004). Clip visible within 10 s on a reachable recorder
(SC-007).

**Constraints**:
- No network.
- No work between questions.
- No GPU use by Ask.
- Extra resident memory under 500 MB (SC-005).
- Camera analysis rate within 5% while Ask answers (SC-006).
- Every clip and every example change is audited before it takes effect.

**Scale/Scope**:
- 14 menu entries on Fo2sh, 13 on v2, plus live view.
- About 15 owner examples each, so about 225 example sentences.
- A test set of at least 200 questions.
- One question at a time, typed by a person.

## Constitution Check

*GATE: checked before research, re-checked after design (bottom of this file).*

| Principle | How this plan satisfies it |
|---|---|
| **I. Real-time** | Ask is not on the frame path. Its model is on the processor, never the GPU. Recorder clips use their own single worker and short queue, so a dead recorder cannot stall tracking's two workers. |
| **II. Isolation** | Ask needs nothing switched on, and nothing needs Ask. A missing model takes only Ask down, and Ask says so (rule 8). |
| **III. Truthful** | The model still only picks a menu id. "Did you mean" replaces a confident guess. Switched off, not recorded, and recorder down are each a distinct note, never an empty list. System Health shows the last *measured* accuracy, or "not measured". |
| **III. Provenance** | A learned example records who added it, who approved it, when, and which question it came from. |
| **IV. Privacy** | Nothing leaves the site. Examples are stored masked, so they hold no names, plates or dates. Clips are footage: audited before they play and gated by the permission of the query that produced the row. |
| **IV. Security** | Admin-only example paths go under `ADMIN_PREFIXES` (by path, never a decorator). A clip can only be fetched for a moment Ask itself offered (an opaque reference held by the engine), so `/ask/clips` is not a back door to any camera at any time. |
| **IV. Audit** | `_log(...)` before every clip, choice and example change. The actor is the signed-in account, not a client string (v2 already does this). |
| **V. Complete** | The answer view is built end to end in both apps. No button is shown for a clip that cannot exist. |

**No violations.** Two P12 lines are narrowed in the spec itself, not
violated: read-only becomes P15-FR-027, and "no new query" gets the live-view
exception in P15-FR-020.

## Project Structure

### Documentation (this feature)

```text
specs/028-local-ask/
├── spec.md
├── plan.md              # this file
├── research.md          # the decisions and why
├── data-model.md        # examples, lexicon, ledger, wire changes, note codes
├── contracts/
│   └── ask-local.md     # POST /ask changes, /ask/clips, /ask/examples, the parser seam
├── quickstart.md        # how to prove it works
├── context.md           # handoff for the implementing chat
└── tasks.md             # /speckit-tasks writes this
```

### Source Code (repository root)

```text
engine/vg/ask/
├── lexicon.py          # NEW: word lists → typed slots + placeholders. Pure
├── when.py             # NEW: date words, four ways → the windows queries accept. Pure
├── encoder.py          # NEW: Encoder protocol + OnnxEncoder (onnxruntime + tokenizers)
├── local.py            # NEW: LocalParser: nearest example, thresholds, did-you-mean
├── examples.py         # NEW: owner examples (YAML) + ExampleStore (ask.db)
├── ledger.py           # NEW: recent answers by audit id → clip refs. Bounded, in memory
├── parser.py           # Gemini removed. Parsed gains score + alternatives
├── menu.py             # + clips= per entry, + live_view entry, + feature= per entry
└── mask.py             # unchanged except the place/group fold reused by lexicon

engine/data/ask/
├── examples.yaml       # NEW: about 15 masked examples per query, plus refuse examples
└── questions.yaml      # NEW: the 200+ test set, each marked tune | score

engine/vg/ingest/archive.py   # + plain jobs, an "ask" lane, typed causes, span clamp
engine/vg/api/
├── schemas.py          # + AskChoice, AskClip*, AskExample*. AskRow + clip_ref
├── notes.py            # − cloud_unavailable, words_left_site. + new codes
├── store.py            # MockStore.ask: local parser, choose, live, switched-off
├── live.py             # _ask_state/_ask_stage, ask clip lane, example store wiring
└── app.py              # POST /ask (choose), /ask/clips…, /ask/examples…
engine/vg/auth/deps.py  # + "/ask/examples" in ADMIN_PREFIXES
engine/vg/config.py     # AskConfig: model paths, thresholds; archive: ask-lane keys
engine/tools/ask_corpus.py    # rewritten: local, offline, scores params + both parts
engine/tools/ask_calibrate.py # NEW: prints thresholds from the tuning part
engine/tools/ask_quantize.py  # NEW: makes the int8 copy on the board, checks it routes identically
engine/tools/measure_ask.py   # NEW: SC-004/005/006 on the board, writes evidence
docs/PLAN.md                  # + the P15 phase (after P14 lands with console v2)
engine/tests/test_ask.py      # updated (Gemini tests out, local seam in)
engine/tests/test_ask_local.py   # NEW: lexicon, when, matcher, examples, clips
engine/requirements.txt       # + onnxruntime, tokenizers; − google-genai

web/src/  and  mobile/src/    # both apps
├── components/AskAnswer.tsx  # NEW: understood line, rows, clip, did-you-mean, live,
│                             #      and (admin) "understood wrong → pick the right query"
├── components/AskClip.tsx    # NEW: plays a saved URL or polls a recorder job
├── pages/Home.tsx            # renders AskAnswer under the bar
├── pages/Settings.tsx        # + admin card: learned and suggested examples
├── services/ask.ts, api.ts, wire.ts, i18n/*   # parity files, copied as bytes
├── (web) components/CameraModal.tsx  # + a detections prop, passed to CameraFrame
└── (web) Home ?camera=<id> opens CameraModal with detections={false}
```

**Structure Decision**: everything new for understanding a question stays in
`vg/ask/`, as spec 010 decided: Ask analyses a sentence on a request, not
frames on a thread. The only change outside Ask on the engine side is the
archive lane, because clips are archive work.

## The design, in one page

### 1. One question, step by step (request thread, no new threads)

```
question
 → normalise (existing)
 → mask names, plates (existing)              PERSON_1, PLATE_1
 → lexicon: places, groups, gates, cameras    PLACE_1, GROUP_1, GATE_1, CAMERA_1
            when, direction, colour           WHEN, DIR, COLOUR
            video words, live words           flags, removed from the text
 → audit entry written                        (before anything else can fail)
 → LocalParser.parse(masked)                  query + score + runner-up
      thresholds not calibrated      → UNAVAILABLE ("not calibrated yet")
      top is __refuse__              → UNSUPPORTED (P12-FR-013)
      score < refuse_floor           → UNSUPPORTED
      score < floor or gap < margin  → CHOOSE (two buttons; __refuse__ is never a button,
                                        and if it is the runner-up the next real query is)
      else                           → that query
 → slots → that query's params                (lexicon decides; the model never does)
 → existing path: unmask, defaults, needs_detail, unknown person, switched off, run
 → rows get clip_ref if the query declares clips
 → video word and a clip-able row → client fetches row 0 at once
```

### 2. What the model is and is not

- It is `multilingual-e5-small` (MIT licence, supplied by Mohamed). Input is
  prefixed `"query: "` on both examples and questions. Pooling is a mean
  weighted by the attention mask (padding excluded), then L2-normalised to
  384 numbers.
- Examples are embedded **once when the engine starts** (about 225 sentences, a
  few seconds) and again only when an example is added. That is "nothing
  runs between questions" (P15-FR-010). Loading lazily on the first question
  would break SC-004.
- A query's score is its best example's cosine similarity. A pseudo-query
  `__refuse__` holds examples of things Ask must not answer ("why was Sara
  late", "the weather", "a knife in the yard" on v2), so that near-misses are
  refused instead of sent to a neighbouring query. This is the measured
  failure in spec 010's run 1.

### 3. Learning (P15-FR-012, 022–026)

- An admin correction comes straight from the answer view: "understood
  wrong", then pick the right query. It sends `POST /ask/examples {question,
  query}`. The server masks the question and shows any word that could be an
  unknown name (the existing `unrecognised()` check). Those words become
  `NAME` unless the admin confirms they are ordinary. The server refuses the
  example if it breaks any tuning question, then stores it as active.
- The tuning questions are masked with **their own made-up roster** from the
  test file, never the site's people. The check works on any site, and no
  real name is in git.
- An operator's "did you mean" pick is stored inside `POST /ask` as
  *suggested*, with every possible-name word already replaced by `NAME`.
  The admin may edit the text before `POST /ask/examples/{id}/approve` makes
  it active. The pick must match a `choose` answer the ledger holds for the
  same account.
- Remove sets the state to `removed`. History is kept and the example is
  dropped from the matrix.
- Owner examples are a YAML file and are never touched by any of this.
  "Remove all learned" restores the measured starting point exactly.

### 4. Clips (P15-FR-013–019)

- `AskQuery.clips = "saved" | "recorder" | None`, **declared per query, never
  inferred** from a row having a time and a camera. Health rows have both and
  must not get a button.
- Clips are declared on `attendance`, `person_path`, `vehicle_passes`
  (recorder), `zone_breaches` and `weapons` (saved), and on `live_view` with a
  past time (recorder). Attendance and vehicle passes **gain a `camera_id`**
  in their store results, because today they carry only a location or gate
  name.
- Each clip-able row gets `clip_ref`: an opaque id in the ledger, mapping to
  `(audit_id, query_id, camera_id, moment, saved_url)`. The ledger keeps the
  last 500 refs in memory. An unknown or old ref returns an honest "ask the
  question again".
- `POST /ask/clips/{ref}` re-checks that the caller may run that query, writes
  `ask.clip` to the audit, then returns either `{url}` (saved) or `{job}`
  (recorder). `GET /ask/clips/jobs/{id}` is polled; `…/chunks/{n}` serves the
  file.
- The archive gets a `lane="ask"` with **1 worker, a queue of 2, plain copy (no
  detector), its own retention (`keep_ask_clips`), 5 s pieces and its own
  timeout**. Tracking's two workers, queue and `keep_legs` are untouched.
- Recorders usually play back in real time, so a 20 s span takes at least
  20 s to fetch. The clip therefore arrives as four 5 s pieces and plays from
  the first one, which keeps SC-007's 10 s within reach. The timeout covers
  *connecting and the first piece* (default 15 s). After that, each piece
  gets its own length plus a margin. Both figures are measured on the site's
  recorder before SC-007 is claimed.
- Failure causes are typed on `ArchiveUnavailable.cause`:

  | Cause | When |
  |---|---|
  | `no_archive` | no recorder configured |
  | `unreachable` | refused, or timed out connecting |
  | `not_yet` | the moment + 10 s is newer than now − `recorder_lag_seconds` |
  | `expired` | older than `retention_days`, when that is set |
  | `not_recorded` | the recorder answered but holds nothing |
  | `no_video` | without `retention_days` the DVR cannot tell expired from never recorded, and the wording says exactly that (P15-FR-018 as amended) |
  | `busy` | the queue is full (`QueueFull`) |

- The footage backend clamps the span to the file that holds the moment, so a
  moment near a file's start still plays.

### 5. Live view (P15-FR-020)

- New entry `live_view(camera*)`. The lexicon fills `camera` from camera names,
  or from a place that holds exactly one camera. A place with several cameras
  gets needs_detail.
- Its `run` reads the camera list (one store call, real data: the name and
  whether it is online), so it still "answers with data".
- New outcome `live`. The console opens `CameraModal` via `?camera=<id>` on
  Home with **`detections={false}`**; the phone navigates to `/cameras/:id`.
- A past time ("الساعة ٨") turns the same question into one row (camera,
  moment) with a recorder `clip_ref`, and `wants_video` set. That clip is
  gated like Track's footage browsing (P15-FR-019): the ledger records
  `/path/legs` as the permission to check, not `/cameras`.

### 6. Switched off (P15-FR-021)

- `AskQuery.feature` names the camera feature it needs. If no enabled camera
  has it (the existing `_feature_cameras` test), the answer is the new note
  `ask.switched_off` and the query is not run.
- **A missing store is a different answer.** Several LiveStore reads return
  `[]` when their store is None: `weapons`, `breaches`, `vehicle_passes`,
  `vehicles_inside` and `vehicle_register`. For `vehicle_registered` that
  reads as "not registered". Ask checks the store first and answers
  `ask.subsystem_unavailable` with the real reason.
- On v2, knife has no entry and its phrasings are `__refuse__` examples.

## Complexity Tracking

Not needed: no constitution violations.

## Constitution re-check after design

Passed. Three things were checked specifically:

- **Clip back door.** The client never sends a camera and a time, only a
  reference the engine minted, so P15-FR-019 holds without a per-camera
  permission model that does not exist.
- **Learning cannot lower accuracy quietly.** The guard runs on the tuning
  part, the score on the scoring part, and the owner's file is the floor.
- **SC-006.** Ask touches neither the GPU nor tracking's archive workers.
  Embedding happens on the request thread, only while someone is asking.
