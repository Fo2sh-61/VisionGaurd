# Implementation Plan: Ask — natural-language query console

**Branch**: `010-ask` | **Date**: 30 Aug 2026 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/010-ask/spec.md`

## Summary

An operator types a question; Ask decides **which existing query that question is**,
runs it, and shows its real result. The language model reads a masked sentence and
returns a validated object naming one query from a fixed menu, or "unsupported". It
never writes a word the operator reads.

The whole feature is one new package, one store method, one endpoint and one page.
It adds no data, no model, no table and no thread. Three pieces of the system that
already exist do most of the work, which is why this is small:

| Already there | What Ask does with it |
|---|---|
| `Store` — every query, already tested, already permissioned | Ask *calls* them. It never reimplements one. |
| `notes.py` + `i18n/` (P11) | Every refusal and error is a note code the console words. `CODES` is empty today; Ask is its first user. |
| Gemini's JSON-schema response format | `Parsed.model_json_schema()` **is** the contract, so the model physically cannot return prose — and there is no second schema to keep in step. |

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 / React (console)

**Primary Dependencies**: existing — FastAPI, Pydantic v2. **New: `google-genai`** (official Gemini SDK; the only addition to `engine/requirements.txt`)

**Storage**: none added. Ask reads through `Store` and writes only audit entries, which today live in RAM — the same durability every audit entry has until P3. Ask must not claim better.

**Testing**: pytest. One new file, `engine/tests/test_ask.py`, plus the masking corpus it reads.

**Target Platform**: Windows workstation, same process as the engine.

**Project Type**: web service + browser console.

**Performance Goals**: an answer, clarifier or refusal within a few seconds (SC-007). One cloud round trip per question, on a request thread. No per-frame cost, no camera work, no GPU.

**Constraints**: read-only; nothing personal the system knows leaves the site; every question audited before its answer returns; the cloud being down must be invisible to every other feature.

**Scale/Scope**: one question at a time, typed by a human. Thirteen menu entries. No batching, no queue, no cache.

## Constitution Check

*GATE: passed before Phase 0, re-checked after Phase 1 design — see the end of this file.*

| Principle | How this feature satisfies it |
|---|---|
| **III — Truthful data** | Every displayed value comes from a `Store` result. `AskAnswer` has no field the model can write into: `understood` is the menu id plus resolved params, `rows` and `headline` come from the query, `note` is a declared code. There is no free-text field on the wire. |
| **III — no fixtures** | `ask()` lives on `MockStore` and is inherited by `LiveStore`, so it answers from whichever store is mounted. It never chooses a store, and a demo answer carries the demo labelling its own query carries. |
| **IV — Privacy** | Masking runs before the request is built, from the site's own directory and register. Faces, frames and clips are never in scope — the parser is handed a string and nothing else. What left is stored per question and readable by an administrator. The provider is Gemini's **free** tier, whose terms allow submitted content to improve Google's products and to be read by human reviewers; the owner accepted this on 30 Aug 2026 **because** masking reduces what leaves to `"when did PERSON_1 arrive today?"`. Linking billing turns that off with no code change. See [research.md §1](./research.md). |
| **IV — Reliability** | The parser is called from the request thread with a timeout. Every failure becomes `outcome=unavailable` + a note. No background task, no retry storm, nothing shared with a `FeatureWorker`. |
| **IV — Security** | The menu may only contain queries a guard can already read; a test asserts no entry maps under `ADMIN_PREFIXES`. Ask adds no second place where a role is decided. |
| **IV — Audit** | `self._log(...)` before the answer returns, as `track` already does. |
| **Rule 8 — a subsystem that fails to start says so** | Ask appears in `capabilities()` with its real state and reason: no key, disabled, or ready. |
| **Rule 9 — no feature requires another** | Ask requires nothing. Nothing requires Ask. With the key absent it degrades to one honest sentence and every other page is untouched. |
| **Latency** | Not on the frame path. Nothing in `ingest/`, `infer/` or `features/` is touched. |

**No violations. Complexity Tracking is therefore omitted.**

## Project Structure

### Documentation (this feature)

```text
specs/010-ask/
├── plan.md              # this file
├── research.md          # the four decisions and why
├── data-model.md        # the menu, the wire types, the note codes
├── contracts/
│   └── ask.md           # POST /ask, and the parser seam
├── quickstart.md        # how to prove it works
├── context.md           # handoff for the implementing chat
└── tasks.md             # /speckit-tasks writes this
```

### Source Code (repository root)

```text
engine/vg/ask/                  # NEW — the whole feature, four small files
├── __init__.py
├── menu.py                     # the thirteen queries. Add a query = add a row here
├── mask.py                     # Arabic normalisation, mask, unmask. Pure functions
└── parser.py                   # the seam + the cloud implementation

engine/vg/api/
├── schemas.py                  # + AskAnswer, AskUnderstanding, AskRow, AskOutcome
├── notes.py                    # + six codes in CODES (currently empty)
├── store.py                    # + ask() on MockStore, + ask() on the Store protocol
└── app.py                      # + POST /ask

engine/vg/config.py             # + the `ask:` block
engine/tests/test_ask.py        # NEW — the only new test file
engine/tests/data/ask_questions.yaml  # NEW — the routing + masking corpus

web/src/pages/Ask.tsx           # NEW — one page, one answer shape
web/src/services/api.ts         # + ask()
web/src/app/navigation.ts       # + one row
web/src/types.ts                # + 'ask' to ToolId
web/src/i18n/{keys,en,ar.draft}.ts   # + the wordings

engine.yaml                     # + ask: block
engine/requirements.txt         # + google-genai
```

**Structure Decision**: a new `vg/ask/` package beside `vg/features/`, not inside it.
`features/` is for `FeatureWorker` subclasses that analyse frames on a thread. Ask
analyses a sentence on a request. Putting it there would inherit threading and rate
limiting it must not have, and would suggest it belongs on a camera.

## The design, in one page

### 1. The menu is the feature

`menu.py` holds one tuple. Each entry is a query the console already exposes:

| id | Store call | A question it answers |
|---|---|---|
| `attendance` | `attendance(mode, subject, on)` | "was Sara late today?" |
| `headcount` | `count(place, when)` | "how many people are in the yard?" |
| `zone_breaches` | `breaches(since_days)` | "did anyone go into the lab this week?" |
| `weapons` | `weapons(since, until)` | "any knife alerts today?" |
| `vehicle_passes` | `vehicle_passes(**filters)` | "did car ص ب د ٢٣٤ come in today?" |
| `vehicles_inside` | `vehicles_inside()` | "which cars are inside now?" |
| `gate_totals` | `vehicle_gates(day)` | "how many cars through gate 1 today?" |
| `vehicle_registered` | `vehicle_register(query, category)` | "is ص ب د ٢٣٤ registered?" |
| `person_path` | `path_skeleton(person, on, actor)` | **"track Ali"** — where he went, stop by stop |
| `person_history` | `history(person)` | "how many days has Ali been present?" |
| `person_directory` | `people()`, filtered | "is Ali enrolled?" · "when was Ali last seen?" |
| `group_roster` | `group(name)` | "who is in Grade 8?" |
| `system_state` | `health()` | "is the gate camera working?" |

Thirteen entries, one per thing the system actually stores. Adding a fourteenth is
one row plus its wording — nothing else changes, which is what makes this cheap to
extend and cheap to review.

**"Track Ali" is the shape to hold every entry to.** It resolves `Ali` against the
directory, runs `path_skeleton`, and returns his stops with each camera, time and
piece of evidence — the same rows the Track page shows. Not a link, not a summary,
not "Ali was seen on three cameras". If an entry cannot do that for its feature, it
is not finished.

**Live following is deliberately absent.** `follow_start()` opens a session, refuses
with 409 when one is already open, and can start a recording — it is a write, and
Ask is read-only (P12-FR-018). "Track Ali" therefore answers from the anchor table,
which is where the Track page's own past-mode answers come from and is indexed to
return immediately. Watching Ali live stays a deliberate act on the Track page.

**Lost items is deliberately not a row.** It stores nothing, so there is no result
to return. Asking about a bag produces the `ask.not_recorded` note and a link to the
Lost items page with the colour and cameras pre-filled. Claiming otherwise would be
the exact lie the constitution forbids.

### 2. One answer shape, one renderer

Every query returns different data, and building thirteen result views would be most of
the work in this feature. It would also be thirteen chances to render something the
query did not say. So the menu entry flattens its result into one shape:

- `headline` — the metrics the page shows, through the existing `Metric` type
- `rows` — time, camera, confidence, clip, label; the evidence, one row each
- `understood` — the menu id and the resolved parameters
- `note` — a code, when there is something to explain
- `deepLink` — the page, with the same parameters

One page renders that, using components that already exist.

**The deep link is never the answer.** It is always *additional* — somewhere to go
after the answer, not instead of it. "Track Ali" must return where Ali went: the
stops, the cameras, the times, the evidence. A link to the Track page is what Ask
exists to replace, so a menu entry that returns only a link has not been written yet.

There is exactly one case where a link stands alone, and it is not an escape hatch:
**when the system genuinely stores no answer.** Lost items is the only one — it runs
live on the tiles somebody is watching and records nothing, so a bag taken this
morning has no stored trace to return. That is honest absence, and Ask says so in
those words. "Awkward to flatten" is never a reason; if a result does not fit the
shape, the shape is wrong, not the requirement.

### 3. The seam is a Protocol with two implementations

```
parse(masked_question, menu) -> Parsed(query | None, params, missing | None)
```

`CloudParser` hands Gemini `Parsed.model_json_schema()`, so the return value is
a validated object or an exception — never prose to be salvaged. `UnavailableParser`
is what you get with no key configured; it returns the unavailable state so every
test, and every developer without a key, exercises the real code path.

### 4. Masking is pure, and tested hardest

`mask.py` imports nothing from the engine. `normalise()` folds alef/hamza, taa
marbuta/haa, and both digit systems; the dictionary is built from `store.people()`
and `store.vehicle_register()`. Because it is pure, the Arabic corpus can be a data
file and the test is a loop.

Per the spec's answered clarification, a word the site does not recognise **is sent
as typed**. That is a real limit, so it is visible: `ask.words_left_site` names them
under the answer, and every outbound string is recorded.

## Work order

Seven slices. Each ends green, and the first three are pure functions with no I/O —
which is where the quality is bought.

| # | Slice | Done when |
|---|---|---|
| 1 | Wire types + note codes + menu skeleton | `test_notes.py` still passes with six new codes; `en.ts` compiles |
| 2 | `mask.py` + the Arabic corpus | Every name in the corpus masks and round-trips, in both digit systems |
| 3 | `parser.py` seam + `UnavailableParser` | `parse()` returns unsupported/unavailable without a network |
| 4 | `MockStore.ask()` + `POST /ask` + audit | Answers in mock mode; audit row precedes the answer; read-only asserted |
| 5 | `CloudParser` | Routes the corpus; a forced timeout gives `ask.cloud_unavailable` |
| 6 | `Ask.tsx` + nav + wordings | A question typed in Arabic returns an answer with its "understood as" line |
| 7 | `docs/PLAN.md` P12, `STATUS.md`, `engine.yaml` | The plan names the phase; STATUS says what is real |

## Constitution re-check after design

Nothing in the design needed a waiver. Two things the design had to be shaped
around, recorded because they are the parts most likely to be got wrong later:

1. **`ask()` on `MockStore`, inherited by `LiveStore`.** This looks like fixture
   code serving a production path — the thing P0-01 killed. It is the opposite:
   `ask()` holds no data, it calls `self.<query>()`, and Python resolves that to
   whichever store is mounted. Writing it twice would be two orchestrations to keep
   in step, and the mock one would rot. A test asserts `LiveStore` does not override it.
2. **Permissions cannot be decided by path here**, because one path runs thirteen
   queries. The menu is therefore restricted to what a guard may already read, and a
   test — not a comment — holds that line.

## Assumptions carried from the spec

- P11 shipped, so the console owns its sentences and `nav.section.ask` already exists.
- Audit is in RAM until P3. Ask inherits that and must not imply otherwise.
- The provider's no-training guarantee is confirmed before the key is put on a school
  machine. Until then Ask runs against the recorded corpus, not live questions.
