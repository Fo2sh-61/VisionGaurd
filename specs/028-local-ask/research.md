# Research: Local Ask

**10 Nov 2026.** The facts below come from reading the code on `Fo2sh`
(`76644ef`) and `origin/console-v2-jetson` (`ce6f8ec`). Line numbers drift;
search for the symbol.

---

## 1. Where to run the meaning model: processor, not TensorRT (decision D2, pending)

**Decision**: onnxruntime, CPU build, loading Mohamed's `onnx/model.onnx` as
it is. Pending his approval.

**Rationale**
- The cost is tiny and happens only when someone asks. About 96M of the
  model's ~118M numbers are the vocabulary table (250k words × 384). The real
  compute is about 21M weights, roughly 1–2 billion operations for a short
  question: tens of milliseconds on a processor. This is an estimate; SC-004
  measures it.
- The GPU stays the cameras'. SC-006 is easiest to meet by not touching it at
  all.
- The repo has no TensorRT code for anything but YOLO. `tools/build_engines.py`
  exports through ultralytics only, and a `models:` entry for Ask would be
  wrongly exported as YOLO unless it went into `NOT_ULTRALYTICS`. A raw
  TensorRT runtime (optimisation profiles, buffers) would be new code with
  new failure modes.
- The repo has measured half precision changing answers (plates: TensorRT
  changed 26.6% of readings, FP16 changed 6.7%, `docs/PLAN.md`). An embedding
  that moves can move the top match.

**Memory is the risk, not speed.** The FP32 file is 448 MiB (measured on
Mohamed's download), and runtime overhead comes on top, so 500 MB is tight.
The fallback, in order:
1. Measure resident memory on the board.
2. If it is over budget, make an int8 copy *on the board from his file*
   (`onnxruntime.quantization.quantize_dynamic`). The vocabulary table becomes
   1 byte per number: about 120 MB. This is a build output, like an
   `.engine`, never a downloaded model.
3. Keep the int8 copy only if it routes every tuning question identically
   to FP32.

**Alternatives considered**
- *TensorRT FP16 on the board.* Rejected for the first step because it needs
  new runtime code and competes for the GPU. It remains possible behind the
  same `Encoder` seam if the processor measurement fails SC-004.
- *onnxruntime-gpu.* There is no PyPI wheel for JetPack, and the repo already
  removed it once (`infer/weapons.py` header).
- *Keyword rules only.* Cheapest of all, but this is spec 010's measured
  weakness. Egyptian phrasing varies too much for a rule per query.

## 2. Tokenizer: `tokenizers` package

**Decision**: `tokenizers` (Rust, no torch, aarch64 wheels), loading
`tokenizer.json` directly.

**Rationale**: e5-small uses XLM-R's SentencePiece Unigram tokenizer with a
"Precompiled" normaliser. A pure-Python copy is about 150 lines, but matching
that normaliser byte for byte is the hard part, and a near-miss silently
changes ids.

**Alternative**: pure Python. Kept in reserve if the package will not install
on the board. Either way, a test compares ids on the whole test set.

## 3. The model picks the query; word lists pick every detail

**Decision**: the lexicon fills every parameter. The model only ranks queries.

**Rationale**: Gemini used to fill `mode`, `direction`, `gate`, `colour`,
`when` and dates itself. With Gemini gone, nothing fills them, so word lists
take over:

| Detail | Source |
|---|---|
| `person` / `subject`, `plate` | existing masking |
| `place` | areas (`LiveStore.areas()`, from `camera.area`) |
| `group` | groups (`LiveStore.groups()`, from `person.grp`) |
| `gate` | gate names from the vehicle feature's cameras |
| `camera` | camera names; a place with exactly one camera |
| `date`, `window`, `when` | `when.py` (below) |
| `direction` | `دخل/داخل/in/entered` → in; `خرج/طالع/out/left` → out |
| `colour` | a colour list in four scripts |
| `mode` | person when there is a PERSON token, group when there is a GROUP token |

**Masking the details also generalises the examples.** "سارة دخلت امتى
النهاردة" and "علي جه امتى امبارح" both become `PERSON دخل امتى WHEN`, so 15
examples cover every student and every day.

## 4. Date words

**Decision**: `when.py` maps words in all four scripts to the windows the app
already uses, with site-local midnights from the same clock as
`weapon_window()` (`app.py`).

**Trap found**: `menu.WINDOWS["yesterday"] = 2` is a rolling two days, but
`weapon_window` uses the calendar day. "Yesterday" must mean the calendar day
everywhere, and the fix lands in one place.

An unknown date word ("أول امبارح العصر") produces needs_detail asking which
day. It never silently falls back to today.

## 5. Thresholds and the held-out split

**Decision**: the test set is marked `set: tune | score` once, before any
tuning. `ask_calibrate.py` picks `floor`, `margin` and `refuse_floor` on the
tuning part only. SC-001 and SC-002 are measured on the scoring part only.
The learning guard (P15-FR-024) uses the tuning part.

**Rationale**: the critic noticed that the first draft used one set three
times (thresholds, guard and score), which makes 95% an overfitted number.

## 6. Clips: their own lane in the existing archive

**Decision**: reuse `ArchiveRunner` and its backends with `plain=True` and
`lane="ask"`.

**Facts that shaped it**
- `submit()` always builds a tracking `LegJob`, and `_process` runs the person
  detector on every frame whenever one is loaded. That is GPU work, so it must
  be skipped (`plain`).
- `_retain` keeps `keep_legs` jobs per camera, so Ask clips would evict
  tracking legs. They get their own folder and limit.
- Two workers and a queue of 8 are shared with sweeps, and the DVR timeout is
  a 120 s constant. One dead recorder could hold a worker for two minutes.
  The Ask lane gets one worker, a queue of 2 and a 15 s timeout.
- `FootageBackend.fetch` only matches when `start` is inside one file, so a
  moment near a file's start fails. The span is clamped to the containing file.
- `app.state.archive_error` is set and never read, so an archive that failed
  to start shows generic text. Ask's `no_archive` note carries the real
  reason (rule 8).
- `AskRow.camera` is a display name, not an id. Fetching needs the id, which
  lives in the ledger, never on the wire as something the client can change.

## 7. Clip permission: inherit the query's

**Decision**: a clip may be fetched by anyone allowed to run the query that
produced the row. v2's per-query role check is reused.

**Rationale**: there is no per-camera permission anywhere today; "allowed to
see the camera" means signed in. Inheriting the query's gate is stricter and
already exists on v2. For example, IT cannot run attendance on v2, so IT cannot
fetch an attendance row's footage.

## 8. Learned examples persist in their own table

**Decision**: `ask.db` with an `ExampleStore`, copying `events/sightings.py`
(`db.connect`, `RLock`, schema on open).

**Rationale**: the audit trail is still in memory (spec 018 not built), so
"who added it and when" cannot come from the audit. The audit still gets an
entry for every change, written first.

## 9. Things removed

- `CloudParser`, `schema_for`, `loads`, `instructions_for` and `_reason` in
  `parser.py`.
- `google-genai` in requirements, and `GEMINI_API_KEY` in `_ask_state`.
- The note codes `ask.cloud_unavailable` and `ask.words_left_site`, plus their
  wording in en, ar.draft and keys.
- The `sent_off_site` **field stays on the wire and is always `""`**. Removing
  it would be a schema change for no gain, and P15-FR-002 asks it to read
  empty.
- `AskConfig.model` and `timeout_seconds`: an old `engine.yaml` that still has
  them must load with a clear warning, not a crash. They are accepted and
  ignored for one release.

## 10. Open, to be measured on the board (not decidable by reading)

- Which JetPack and Python the engine runs on there, and whether
  `onnxruntime` and `tokenizers` wheels install on it.
- Resident memory with the FP32 model, and whether int8 is needed.
- p50 and p95 embedding time while all cameras run.
- Whether NVML works on the Jetson. System Health's GPU numbers may read "no
  reading" there.
- Whether the target recorder's RTSP errors tell expired from never recorded.
