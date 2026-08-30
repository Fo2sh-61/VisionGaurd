# Phase 1 data model: Ask

**Ask adds no table, no file and no persistent record.** Everything below is either
a wire type that lives for one request, or a registry that lives in code.

---

## 1. Wire types — `engine/vg/api/schemas.py`

All subclass `Wire`: snake_case in Python, camelCase out, `extra="forbid"`.

### `AskOutcome` (enum)

| Value | Means | Has `understood`? | Has rows? |
|---|---|---|---|
| `answered` | A query ran and returned | yes | yes |
| `unsupported` | Not something Ask can answer | no | no |
| `needs_detail` | Matched a query, a parameter is missing | partial | no |
| `unavailable` | Cloud down, or subsystem behind the query is down | maybe | no |

Four outcomes, four distinct screens. They must never collapse into "no results" —
that is the empty/zero/unknown rule the console already keeps everywhere else.

### `AskUnderstanding`

| Field | Type | Notes |
|---|---|---|
| `query` | `str` | a menu id, e.g. `attendance`. Never free text |
| `params` | `dict[str, str]` | resolved, real values — after unmasking |
| `assumed` | `list[str]` | parameters Ask filled in itself, e.g. `date` when the question had no time in it |

`assumed` is what makes a wrong assumption visible rather than silent. A question
with no date says so on screen.

### `AskRow`

| Field | Type | Notes |
|---|---|---|
| `label` | `str` | a name, a plate, a zone — a value from the result, never a sentence |
| `at` | `Instant \| None` | through `_instant()`. Never built by hand |
| `camera` | `str \| None` | display name, not an id |
| `confidence` | `Confidence \| None` | 0..1, clamped before sending |
| `clip_url` | `str \| None` | only where the query already has one |
| `note` | `Note \| None` | per-row honesty: demo, estimated, weak read |

### `AskAnswer`

| Field | Type | Notes |
|---|---|---|
| `outcome` | `AskOutcome` | |
| `understood` | `AskUnderstanding \| None` | |
| `headline` | `list[Metric]` | the same metrics the page shows |
| `rows` | `list[AskRow]` | |
| `note` | `Note \| None` | the honest state, when there is one |
| `deep_link` | `str \| None` | console route + query string |
| `sent_off_site` | `str` | the exact masked text that left. Always present, even on failure |
| `audit_id` | `str` | the receipt. Proof the entry preceded the answer |

**There is no free-text field on this type.** Every sentence the operator reads is
built by the console from `note` and the menu id. That is P12-FR-003 enforced by
the shape of the data rather than by review.

---

## 2. The menu — `engine/vg/ask/menu.py`

One tuple, `QUERIES`. Each entry:

| Field | What |
|---|---|
| `id` | stable string; the contract with the parser and the wordings |
| `params` | a Pydantic model — the parameters this query needs, and their types |
| `required` | which of them cannot be assumed |
| `run(store, params)` | calls **one** `Store` method and flattens it |
| `route(params)` | the deep link |
| `reads` | the API path this stands for, e.g. `/attendance` — the permission test reads this |

The thirteen entries are listed in [plan.md](./plan.md#1-the-menu-is-the-feature).

**Invariants, each with a test:**

1. Every `id` has a wording in `en.ts`.
2. No `reads` value starts with an `ADMIN_PREFIXES` entry.
3. Every `run` calls exactly one `Store` method — asserted with a counting stub.
4. `QUERIES` ids are unique and stable; renaming one is a coordinated change.
5. **Every entry returns data, not a signpost.** Given a store with a matching
   record, `run()` must produce a non-empty `headline` **or** at least one `AskRow`.
   An entry whose only output is a `deep_link` fails this test. The single exemption
   is an entry declared `stores_nothing=True`, which today is lost items alone and
   which must emit `ask.not_recorded`.
6. **`run()` never calls a `Store` method that writes.** Asserted against a
   denylist — `follow_*`, `start_*`, `stop_*`, `review_*`, `set_*`, `add_*`,
   `edit_*`, `remove_*`, `delete_*`, `correct_*`, `import_*`, `export_*`,
   `acknowledge`, `dismiss_*`, `connect_*`, `scan`.

---

## 3. Parser types — `engine/vg/ask/parser.py`

### `Parsed` — what the model is allowed to say

```
query:   str | None      # a menu id, or None for unsupported
params:  dict[str, str]  # placeholders still in place
missing: str | None      # the one parameter it could not find
```

This is the Pydantic model whose `model_json_schema()` is handed to Gemini as the
response schema — one definition, not two. The model cannot return anything else: a
value outside the menu fails validation, and a validation failure is `unsupported`,
not a retry.

### `Parser` — the seam (P12-FR-022)

```
parse(masked_question: str) -> Parsed
```

Two implementations ship: `CloudParser` and `UnavailableParser` (no key configured —
returns the unavailable state, and is what every test and every keyless developer
runs against). A future local parser is a third; nothing else in Ask changes.

---

## 4. Masking — `engine/vg/ask/mask.py`

No types persist. Two pure functions and a dictionary built per request:

| Thing | Shape |
|---|---|
| `normalise(text)` | folds alef/hamza (`ا أ إ آ`), taa marbuta/haa (`ة/ه`), Arabic-Indic ↔ Western digits, case, and diacritics |
| `Dictionary` | `normalised form -> (placeholder, real value)`, built from `store.people()` names and `store.vehicle_register()` plates |
| `mask(question, dictionary)` | `(masked_text, {placeholder: real value})` |
| `unmask(params, tokens)` | params with real values put back |

Placeholders are opaque and positional — `PERSON_1`, `PLATE_1`. They carry no
information about who the person is, which is the point: what leaves the site must
be useless to whoever receives it.

**The known limit** (spec clarification 2, decided 30 Aug 2026): a word not in the
dictionary is sent as typed. `ask.words_left_site` names those words under the
answer so the operator knows.

---

## 5. Note codes — `engine/vg/api/notes.py`

`CODES` is empty today. Ask adds six, each with a wording in `en.ts` and `ar.draft.ts`:

| Code | Args | Must say |
|---|---|---|
| `ask.unsupported` | — | that Ask cannot answer it, **and** what it can answer about |
| `ask.needs_detail` | `parameter` | which detail is missing |
| `ask.unknown_person` | `name` | that name is not in the directory — **not** that they were absent |
| `ask.cloud_unavailable` | `reason` | Ask is temporarily unavailable, **and** that detection is unaffected |
| `ask.not_recorded` | `subject` | lost items are live-only, so there is nothing recorded to search |
| `ask.words_left_site` | `words` | these words were not recognised and were sent as typed |

Each wording must carry the consequence, not only the cause — the rule `notes.py`
states in its own docstring, and the one a shorter Arabic sentence quietly breaks.

---

## 6. Configuration — `engine.yaml`

```yaml
ask:
  enabled: true
  model: gemini-3.7-flash   # one line; see research.md §1 before changing
  timeout_seconds: 8
```

The API key is `GEMINI_API_KEY` in `.env`, never in `engine.yaml` and never in git —
the same rule the camera credentials already follow. Key absent ⇒ `UnavailableParser`
⇒ Ask reports itself unavailable in `capabilities()` with that reason, which is
constitution rule 8 satisfied by construction.

**Confirm the model id against the live model list before shipping.** Gemini's ids
move faster than this document does; `gemini-3.7-flash` was current on 30 Aug 2026,
with `gemini-3.5-flash-lite` as the higher-rate-limit alternative. A wrong id is a
startup error, not a wrong answer, so it fails loudly — but it should not fail at all.
