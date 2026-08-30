# Implementation context: Ask — natural-language query console

**Written by `/speckit-plan` on 30 Aug 2026, against commit `781ac8b`.**

Everything here was read during planning. Read this **before** opening any source
file, then open only the named anchors.

> Verify before trusting. If this disagrees with the code, the code wins and this
> file is wrong. Search for the symbol; do not trust a line number.

---

## 1. Anchors — where each edit lands

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `api/schemas.py` | `class Wire` | `alias_generator` snake→camel, `populate_by_name=True`, `extra="forbid"`. `class Note` is at ~line 155 with `code` + `args`. `Instant`, `Metric`, `Confidence`, `Fraction` all already exist | add `AskOutcome`, `AskUnderstanding`, `AskRow`, `AskAnswer` |
| `api/notes.py` | `CODES` | `frozenset()` — **literally empty**. `note(code, **args)` raises `KeyError` on an undeclared code | add the six `ask.*` codes |
| `api/store.py` | `class Store(Protocol)` (~line 103) | one `def name(...) -> T: ...` line per method, grouped by feature | add `def ask(self, question: str, actor: str) -> S.AskAnswer: ...` |
| `api/store.py` | `MockStore._log` (~line 1200) | `_log(actor, action, subject, detail) -> S.AuditEntry`; appends to `self._audit`, returns the entry with its `id`. `audit()` returns `reversed(self._audit)[:limit]` | add `ask()` **on MockStore**, calling `self._log(...)` first |
| `api/store.py` | `TODAY` (~line 31) | now `date.today()` — was a fixed date; fixed on this branch in `781ac8b` | nothing; just know it moved |
| `api/app.py` | `@app.post("/track", ...)` (~line 2303) | endpoint style: `async def`, `store: StoreDep`, `actor: Annotated[str, Query(...)] = "unknown"`, returns the wire model directly. Docstring states the audit-first rule | copy it for `POST /ask` |
| `api/app.py` | `except SubsystemUnavailable` (~2515 onwards) | six existing handlers → 503 | Ask does **not** use this; it catches and returns `outcome=unavailable` in the payload |
| `api/live.py` | `_instant(when, clock)` (~line 49) | `datetime -> S.Instant`, offset taken **at that instant** | use it for every `AskRow.at`. Never build an `Instant` by hand |
| `auth/deps.py` | `ADMIN_PREFIXES` (~line 83) | `("/enrolment", "/sources", "/users")`. `ADMIN_WRITE_PREFIXES` = `("/cameras", "/people", "/zones", "/vehicles")` — read is fine for a guard, write is admin | `/ask` goes in **neither**. The permission test reads `ADMIN_PREFIXES` |
| `vg/config.py` | the loader | reads `engine.yaml` + `.env`, validates everything | add the `ask:` block; key comes from `.env` |
| `web/src/types.ts` | `ToolId` (~line 336) | union of 11 ids, no `'ask'` | add `'ask'` |
| `web/src/app/navigation.ts` | the entries array (~line 40) | `{ id, path, section, icon }`; `section: 'ask'` already exists and already holds attendance/counting/lost-items/track | add `{ id: 'ask', path: '/ask', section: 'ask', icon: ICON.ask }` |
| `web/src/i18n/keys.ts` | `UiKey`, `NoteCode` | `NoteCode = never` today. `nav.section.'ask'` is **already** in the union. `en.ts` is `Record<MessageKey, string>` so a missing English wording fails `tsc` | add the six note codes to `NoteCode` and the page's `UiKey`s |
| `web/src/services/api.ts` | any exported function | every call goes through `get`/`post` from `./http`; several take `lang: Language` and render through `format.ts` | add `ask(question)`; return the wire object **unrendered** |

---

## 2. Things to copy, not invent

- **An endpoint that audits before returning** → copy `api/app.py::track_person` and
  `MockStore.track`. `TrackResult.audit_id` is the receipt pattern `AskAnswer.audit_id` copies.
- **A store method that fans out to other store methods** → `MockStore.group()`
  (~line 1084) already calls `self.attendance("group", name, str(TODAY))`. That is
  the exact `self.<query>()` shape `ask()` uses, and proof the inheritance works.
- **Note-code discipline** → `api/notes.py` docstring. Read it before writing a
  wording; it is where the "carry the consequence, not only the cause" rule lives.
- **A test with a real store** → the `store` fixture in `engine/tests/test_groups.py`:
  throwaway `FaceGallery` + `SightingStore` in a `TemporaryDirectory`. **Close the
  gallery before the tempdir** or Windows fails teardown.
- **Client + auth in tests** → `authed(app, role="admin")` and `sign_in(app, role)`
  in `engine/tests/conftest.py`; `bare_live_store` and `live_ish_store` fixtures.
- **The Gemini call** → the provider is **Google Gemini**, package `google-genai`,
  `from google import genai`. **Do not load the `claude-api` skill** — it produces
  Anthropic SDK code and is written to stop when it sees another provider. Fetch
  `ai.google.dev/gemini-api/docs/structured-output` instead and confirm the shape;
  it was verified on 30 Aug 2026 as:

  ```python
  client.interactions.create(
      model=config.ask.model,
      input=masked_question,
      response_format={"type": "text", "mime_type": "application/json",
                       "schema": Parsed.model_json_schema()},
  )
  ```

  Note it is `client.interactions.create`, not the older `generate_content` shape a
  model trained before 2026 will reach for, and not `google-generativeai`, which is
  the superseded package. **Confirm the model id too** — `gemini-3.7-flash` was
  current on 30 Aug 2026 and Gemini ids move quickly.

---

## 3. Traps

- **`CODES` is empty, and `test_notes.py` polices both directions.** It reads the
  source with `ast` to find a `note()` call with an undeclared code, **and** fails a
  declared code nobody emits. So a code, its emitter and its `en.ts` wording must
  land in the **same commit**. Add them one at a time and the build breaks.
- **`en.ts` is `Record<MessageKey, string>`; `ar.ts` is `Partial`.** A missing English
  wording fails `tsc`; a missing Arabic one is the designed state and falls back.
  Draft Arabic goes in `ar.draft.ts` and is visible only in dev.
- **`CameraFrame` with `live` also polls recognition boxes, which carry names.** The
  Ask page must not use it. Show the clip a query already has.
- **Mixed line endings, no `.gitattributes`.** `api/*.py`, `services/*.ts`,
  `types.ts` and `STATUS.md` are **CRLF**; most other files are LF. A script that
  reads and writes text rewrites every ending and turns a six-line change into a
  whole-file diff. Check `b"\r\n" in path.read_bytes()` first; `git diff --stat`
  catches it.
- **Do not write files with shell redirection (`> file`).** A hook's log output was
  captured into `.specify/feature.json` that way during this very planning session
  and destroyed it. Use the Write tool.
- **`_instant()` per instant, never per startup.** F3/P0-03 was exactly this bug.
- **`Fraction` and `Confidence` are validated 0..1** — clamp before sending or the
  response 500s.
- **Permissions are decided by path and there is only one path here.** Resist adding
  a role check inside `ask()`; keep the menu inside what a guard can already read
  and let the test hold the line. See [research.md §4](./research.md).
- **`ask()` belongs on `MockStore` and must not be overridden on `LiveStore`.** It
  will look wrong to a reader who remembers P0-01. It is not that bug —
  [research.md §2](./research.md) explains why, and a test asserts
  `LiveStore.ask is MockStore.ask`.
- **Egypt changes its clocks at midnight**, so local midnight can fail to exist. If
  Ask ever computes a day boundary, use `app.py::_local_midnight` — do not write a
  second one. It was fixed on this branch in `781ac8b`.

---

## 4. Baseline

- `python -m pytest engine` → **1366 passed, 7 skipped** at commit `781ac8b`
  (3m08s locally). CI skips more; `@pytest.mark.camera` needs `--camera`.
- New test file: `engine/tests/test_ask.py`; new data file
  `engine/tests/data/ask_questions.yaml`; new tool `engine/tools/ask_corpus.py`.
- **Nothing is failing at this baseline.** Three failures existed earlier on this
  branch and were fixed in `781ac8b`: a fixed demo date that aged out of its own
  window, `_local_midnight` returning an instant on the wrong side of a DST change,
  and twelve tests needing `loiterwatch`, which CI now installs.

---

## 5. Still unknown

- **`ICON.ask` does not exist yet.** `navigation.ts` uses an `ICON` map; check its
  shape and add an icon, or reuse one. Not read during planning.
- **How `config.py` validates a new block** — the `ask:` shape here is asserted, not
  verified. Copy whatever `vehicles:` does.
- **Whether `Metric` is exactly the right type for `headline`.** `formatMetrics` is
  used by attendance, counting and history, so it is very likely; confirm the field
  names before writing `AskAnswer`.
- **The provider's no-training guarantee is not confirmed.** It is a commercial term
  the owner must read. Until then, run the corpus, not live questions from a school
  machine.
- **`vehicle_register(query, category)` takes a query string** — check what it
  returns for an empty query before using it to build the plate dictionary; it may
  need a different call to enumerate everything.
