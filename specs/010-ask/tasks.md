---

description: "Task list for Ask — natural-language query console"
---

# Tasks: Ask — natural-language query console

**Input**: Design documents from `specs/010-ask/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/ask.md](./contracts/ask.md), [context.md](./context.md)

**Read [context.md](./context.md) before opening any source file.** It names the anchor
in each file and the shape it has today, so the edits below do not need a re-read.

**Tests**: included, and not optional here. The constitution requires test-first for
business rules, and AGENTS.md requires every fix to a known bug to ship with its
regression test in the same commit.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different files, no dependency on an unfinished task
- **[Story]**: US1–US4, mapping to the spec's acceptance scenarios

---

## Three sequencing rules that will break the build if ignored

1. **A note code, the code that emits it, and its English wording must land in the
   same task.** `engine/tests/test_notes.py` fails a declared code with no emitter
   **and** an emitted code that is not declared, and `en.ts` is typed
   `Record<MessageKey, string>` so `tsc` fails on a missing English wording. There is
   no task below that adds a code on its own — that is deliberate.
2. **`ask()` goes on `MockStore` and is never overridden on `LiveStore`.** See
   [research.md §2](./research.md). T012 is the test that holds this.
3. **`api/*.py`, `services/*.ts` and `types.ts` are CRLF**; most other files are LF.
   Edit bytes, or check `b"\r\n" in path.read_bytes()` first. `git diff --stat` catches it.

---

## Phase 1: Setup

**Purpose**: the dependency, the configuration, and an empty package to put things in.

- [ ] T001 [P] Add `google-genai` to `engine/requirements.txt` — the current Gemini SDK, **not** the superseded `google-generativeai` — then `pip install -r engine/requirements.txt`
- [ ] T002 [P] Add the `ask:` block (`enabled`, `model: gemini-3.7-flash`, `timeout_seconds: 8`) to `engine.yaml` and validate it in `engine/vg/config.py`, copying whatever the `vehicles:` block does; the API key comes from `GEMINI_API_KEY` in `.env` and must never reach `engine.yaml`. Confirm the model id against the live model list first — Gemini ids move quickly
- [ ] T003 Create the package `engine/vg/ask/__init__.py` (empty; the four modules arrive below)

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the shapes every story needs. No behaviour yet, and no note codes yet
(rule 1 above).

**⚠️ No user story can start until this phase is complete.**

- [ ] T004 Add `AskOutcome`, `AskUnderstanding`, `AskRow`, `AskAnswer` to `engine/vg/api/schemas.py` per [data-model.md §1](./data-model.md), subclassing `Wire` beside the existing `Note` — **no free-text field on `AskAnswer`**
- [ ] T005 [P] Add `Parsed`, the `Parser` Protocol and `UnavailableParser` to `engine/vg/ask/parser.py` per [contracts/ask.md §2](./contracts/ask.md); `parse()` takes a string and nothing else
- [ ] T006 [P] Add the `AskQuery` shape (`id`, `params`, `required`, `run`, `route`, `reads`) and an empty `QUERIES` tuple to `engine/vg/ask/menu.py`
- [ ] T007 Declare `def ask(self, question: str, actor: str) -> S.AskAnswer: ...` on the `Store` protocol in `engine/vg/api/store.py`
- [ ] T008 Create `engine/tests/test_ask.py` with a stub `Parser` fixture returning fixed answers, and a shape test asserting `AskAnswer` carries no free-text field

**Checkpoint**: shapes exist, `pytest` is green, `tsc` is untouched.

---

## Phase 3: User Story 1 — a question gets the real answer (Priority: P1) 🎯 MVP

**Goal**: a supported question returns the same result the matching page shows, with
its provenance, its "understood as" line and a working deep link. Read-only and
audited from the first commit.

**Independent test**: with the stub parser and no API key, ask each of the thirteen
queries under `.\dev.ps1 up -Mock`; every answer matches what the corresponding page
shows for the same parameters, **every answer contains actual rows or figures rather
than a link**, and every answer carries an `auditId`. "Track Ali" is the one to check
first — it must come back as Ali's stops, not as an invitation to open the Track page.

**Covers**: spec scenarios 1, 2, 8 · SC-001, SC-005

- [ ] T009 [US1] Fill the thirteen `QUERIES` entries in `engine/vg/ask/menu.py` per [plan.md](./plan.md#1-the-menu-is-the-feature) — each `run` calls exactly one `Store` method and flattens it into `headline` + `rows`, using `_instant()` from `api/live.py` for every time. **Every entry returns the data, never a signpost**: "track Ali" comes back as Ali's stops with their cameras, times and confidences, as in [contracts/ask.md](./contracts/ask.md). Lost items is the one entry marked `stores_nothing=True`
- [ ] T010 [P] [US1] Menu invariant tests in `engine/tests/test_ask.py`, all six from [data-model.md §2](./data-model.md#2-the-menu--enginevgaskmenupy): ids unique, every id worded in `en.ts`, exactly one `Store` call per `run` (counting stub), no `reads` under `ADMIN_PREFIXES`, **every entry yields a non-empty `headline` or at least one `AskRow` when the store has a matching record**, and no `run` touches a writing `Store` method (denylist)
- [ ] T011 [US1] Implement `MockStore.ask(question, actor)` in `engine/vg/api/store.py` — `self._log(...)` **first**, then parse, resolve, run, flatten; masking is a no-op hook until T017 replaces it
- [ ] T012 [P] [US1] Tests in `engine/tests/test_ask.py`: the audit row precedes the answer and `auditId` names it; `LiveStore.ask is MockStore.ask`; a full corpus run creates, changes and deletes nothing in any store list
- [ ] T013 [US1] Add `POST /ask` to `engine/vg/api/app.py`, copying the `track_person` idiom — always `200` with an `AskAnswer`, never a 5xx for degradation
- [ ] T014 [P] [US1] Permission tests in `engine/tests/test_ask.py`: no `QUERIES[].reads` value starts with an `ADMIN_PREFIXES` entry, and `/ask` refuses an anonymous caller
- [ ] T015 [US1] Console: `ask()` in `web/src/services/api.ts`, `'ask'` in `ToolId` in `web/src/types.ts`, the row in `web/src/app/navigation.ts` (section `'ask'` already exists), the route, and `web/src/pages/Ask.tsx` rendering the one answer shape with its always-visible "understood as" line and deep link — plus the page's `UiKey`s in `keys.ts` and their wordings in `en.ts` and `ar.draft.ts`

**Checkpoint**: Ask answers real questions end to end, in Arabic and English, with no
API key and no network.

---

## Phase 4: User Story 2 — nothing personal leaves the site (Priority: P1)

**Goal**: every name and plate the system knows is replaced locally before anything
is sent, in every spelling and both digit systems; what did leave is inspectable.

**Independent test**: `python -m pytest engine/tests/test_ask.py -k mask` — for every
entry in the corpus, no directory name and no register plate appears in the masked
text, and unmasking returns the value that was masked.

**Covers**: spec scenarios — the masking edge cases · SC-002

- [ ] T016 [P] [US2] Write `engine/tests/data/ask_questions.yaml`: each entry is a question, its expected menu id and params, and the identifiers it contains — covering MSA, Egyptian dialect, Franco-Arabic, English and mixed, with alef/hamza (`احمد`/`أحمد`), taa marbuta/haa (`سارة`/`ساره`), transliterations (`Sara`/`Sarah`), and plates in both digit systems
- [ ] T017 [US2] Implement `engine/vg/ask/mask.py` — `normalise()`, the `Dictionary` built from `store.people()` and `store.vehicle_register()`, `mask()` and `unmask()`, with opaque positional placeholders (`PERSON_1`, `PLATE_1`) that carry no information about who they stand for; import nothing from the engine
- [ ] T018 [P] [US2] Masking tests in `engine/tests/test_ask.py` driven by the corpus: every spelling matches, both digit systems fold, placeholders round-trip, and **no known name or plate survives into the masked text**
- [ ] T019 [US2] Replace the no-op hook in `MockStore.ask()` with real masking, populate `AskAnswer.sent_off_site` byte for byte, and add the `ask.words_left_site` code to `notes.py` with its emitter and its wordings in `en.ts`/`ar.draft.ts`; surface it under the answer in `Ask.tsx`

**Checkpoint**: SC-002 is provable from a test run, and the accepted limit from the
spec's clarification 2 is visible on screen rather than buried.

---

## Phase 5: User Story 3 — every wrong or unavailable case is honest (Priority: P2)

**Goal**: out of scope, ambiguous, unknown person, lost items, subsystem offline and
cloud unreachable each produce their own message with a reason — and never a figure.

**Independent test**: `python -m pytest engine/tests/test_ask.py -k honest` — six
cases, six distinct notes, no rows and no deep-linked result in any of them.

**Covers**: spec scenarios 3, 4, 5, 6, 7 · SC-004, SC-006

- [ ] T020 [US3] Add the five remaining codes to `CODES` in `engine/vg/api/notes.py` — `ask.unsupported`, `ask.needs_detail`, `ask.unknown_person`, `ask.cloud_unavailable`, `ask.not_recorded` — each with its emitter in `MockStore.ask()` and its wordings in `en.ts` and `ar.draft.ts`, every wording carrying the **consequence** and not only the cause
- [ ] T021 [P] [US3] Honest-state tests in `engine/tests/test_ask.py`: unsupported names what Ask can answer; a missing parameter yields one clarifier and the query does **not** run; an unknown name is not an empty result; a bag question yields `ask.not_recorded` plus a link and never a result; a `SubsystemUnavailable` from a query forwards **that subsystem's own** note unchanged; a parser exception yields `ask.cloud_unavailable` and the audit row still exists
- [ ] T022 [P] [US3] Report Ask's real state and reason in `capabilities()` in `engine/vg/api/live.py` — no key, disabled, or ready — so a subsystem that cannot start says so in the UI
- [ ] T023 [US3] Render the four outcomes distinctly in `web/src/pages/Ask.tsx`; empty, zero and unknown must stay three different things, as everywhere else in the console

**Checkpoint**: with the key removed, Ask degrades to one honest sentence and every
other feature behaves exactly as before (SC-006).

---

## Phase 6: User Story 4 — Arabic, Franco-Arabic, English and mixed all route (Priority: P2)

**Goal**: the cloud parser routes the corpus correctly, measured rather than asserted.

**Independent test**: `python engine/tools/ask_corpus.py` prints the routing score
against `ask_questions.yaml`; **SC-003 is ≥95%**, and every wrong route is listed by
question rather than hidden in a percentage.

**Covers**: SC-003 · the `[NEEDS CLARIFICATION]`-free model decision from research.md §1

- [ ] T024 [US4] Implement `CloudParser` in `engine/vg/ask/parser.py` against Google Gemini (`from google import genai`), passing `Parsed.model_json_schema()` as the `response_format` schema, with the menu in the instructions and the masked question as the input — **fetch `ai.google.dev/gemini-api/docs/structured-output` first and do not write the call from memory; do NOT load the `claude-api` skill**, it produces Anthropic code (see [context.md §2](./context.md#2-things-to-copy-not-invent)); map every SDK exception to `unavailable` with a reason, most-specific-first, and treat HTTP 429 as its own reason since the free tier is rate-limited
- [ ] T025 [US4] Write `engine/tools/ask_corpus.py` — run every corpus question through the configured parser, print the routing score and name each wrong route; it must run without touching the database or any feature
- [ ] T026 [US4] Run the corpus against `gemini-3.7-flash` and `gemini-3.5-flash-lite`, record both routing scores in `specs/010-ask/evidence/routing.md` with the Arabic, Franco-Arabic, English and mixed scores **broken out separately** — a model that is strong on English and weak on Egyptian dialect is a failure for this school — then set `engine.yaml`'s `model` from the result. This is the evidence [research.md §1](./research.md) says does not exist yet

**Checkpoint**: SC-003 has a number behind it, and the model choice is a measurement
rather than a preference.

---

## Phase 7: Polish

- [ ] T027 [P] Add phase **P12** to `docs/PLAN.md` after P11, and update `STATUS.md` with what is real — including that Ask's audit is in RAM until P3, and that unrecognised words are sent as typed
- [ ] T028 Run the four gates and the whole of [quickstart.md](./quickstart.md), including the by-eye checks in §5 and the administrator inspection in §6; the `pytest` count must be above the 1366 baseline in [context.md §4](./context.md#4-baseline), never below

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no dependencies
- **Foundational (P2)** → needs Setup; **blocks every story**
- **US1 (P3)** → needs Foundational
- **US2 (P4)** → needs Foundational. T019 touches `MockStore.ask()`, so it lands after T011
- **US3 (P5)** → needs Foundational. T020 emits from `MockStore.ask()`, so it lands after T011
- **US4 (P6)** → needs Foundational for the seam; needs **US2** before any real question is sent, because the cloud parser is the first thing that sends anything off-site
- **Polish (P7)** → last

### Story independence

| Story | Independent? | Note |
|---|---|---|
| US1 | yes | stub parser, no key, no network |
| US2 | yes | `mask.py` is pure; its tests import only the corpus |
| US3 | mostly | shares `MockStore.ask()` with US1/US2 — same file, so not parallel with T011/T019 |
| US4 | no | **must not run before US2.** Sending an unmasked question is the one ordering mistake in this plan that cannot be undone |

### Parallel opportunities

- **Setup**: T001, T002 together
- **Foundational**: T005, T006 together (different files), after T004
- **US1**: T010, T012, T014 together — all tests, all in `test_ask.py`, so land them as one commit if the same person writes them
- **US2**: T016 can be written at any time, including before Foundational
- **US3**: T021, T022 together
- **Cross-story**: with two people, one takes US1 (T009→T015) and the other takes US2 (T016→T018) as soon as Foundational is done; they meet at T019

---

## Implementation strategy

### MVP — stop and look after US1

Setup → Foundational → US1 is a working Ask: thirteen real queries, real answers, real
audit, in both languages, with no API key and no cloud. That is the honest MVP, and
it is worth demonstrating before any question leaves the building.

### Then, in order

1. **US2** next, not later. It is P1 for a reason: until masking is proved, no real
   question may be sent.
2. **US3** — the honest states. Ask is not shippable without them; a feature that
   answers well and fails badly is worse than no feature.
3. **US4** — the cloud, measured on the corpus.
4. **Polish** — the documents, then the whole quickstart.

### The gate before a school machine

Even with all 28 tasks green, Ask must not run live questions until the provider's
written no-training guarantee is confirmed. That is a commercial term, not a task —
it belongs to the owner and it is recorded in [research.md §1](./research.md).

---

## Notes

- 28 tasks. Every one names its file; every story ends at a checkpoint you can run.
- Commit per task or per checkpoint; a note code, its emitter and its wording always
  go together.
- Verify a test fails before you make it pass — especially in US2, where a passing
  masking test that never ran is a name leaving the site.
