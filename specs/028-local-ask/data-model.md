# Data model: Local Ask

Wire types subclass `Wire` (snake_case in, camelCase out, `extra="forbid"`).
Scores sent to the console are clamped to 0..1, or the response returns a 500.

## 1. Lexicon output (in memory, per question)

```
Slot(kind, value, token, span)
  kind: person | plate | place | group | gate | camera | when | direction | colour
  value: canonical value the query accepts ("Library", "Grade 8", "2026-11-10", "in")
  token: placeholder in the masked text (PLACE_1, WHEN, DIR …)
Flags: wants_video: bool, wants_live: bool, past_time: bool
```

Rules:
- Longest match first. Matching uses `normalise()`, plus `skeleton()` for
  transliterations, exactly as names do.
- `value` is the canonical spelling, because `_ask_unresolvable` matches
  places and groups by exact casefold.
- Two places matched in one question: needs_detail. The lexicon never picks one.
- Video and live words are removed from the model's text, so "وريني" does not
  pull every question towards the same examples.

## 2. Example (owner file, and `ask.db`)

Owner file `engine/data/ask/examples.yaml`:

```yaml
attendance:
  - "PERSON جه امتى WHEN"
  - "was PERSON late WHEN"
  …                                  # about 15 per query, already masked
__refuse__:
  - "ليه PERSON اتأخر"
  - "الجو عامل ايه"
```

`ask.db` table `ask_example`:

| Column | Type | Note |
|---|---|---|
| id | TEXT PK | |
| query | TEXT | a menu id or `__refuse__` |
| text | TEXT | **masked**; never a name, plate or date |
| state | TEXT | `suggested` → `active` → `removed`; `suggested` → `removed` |
| source | TEXT | `admin` (correction) or `choice` (operator's did-you-mean) |
| added_by, added_at | TEXT | the account; site-local instant |
| approved_by, approved_at | TEXT NULL | set when suggested becomes active |
| removed_by, removed_at | TEXT NULL | |
| from_audit | TEXT NULL | the audit id of the question it came from |

State changes:
- `admin` correction → `active` at once. It is refused if the guard fails.
- `choice` → `suggested` → (admin approves, guard passes) `active`.
- Any → `removed` (admin). It is never deleted, so the history stays.
- The same masked text and query as an existing active example is a no-op.
  It returns the existing id and writes no duplicate.

## 3. Ledger (in memory, bounded)

```
LedgerEntry(audit_id, actor, role, query_id, at, refs: {clip_ref: ClipTarget})
ClipTarget(camera_id, camera_name, moment, saved_url | None)
```

It holds the last 500 entries, oldest dropped first. It is lost on restart, and
an unknown ref gives an honest note (`ask.clip.expired_ref`), never a 500.

## 4. Wire changes

`AskOutcome` gains `choose` and `live`. The existing values are `answered`,
`needs_detail`, `unsupported` and `unavailable`.

```
AskChoice      { query: str, params: dict[str,str] }               # one button
AskRow         + clip_ref: str | None                             # only where the query declares clips
AskAnswer      + choices: list[AskChoice] = []                    # exactly 2 when outcome=choose
               + live_camera_id: str | None                       # set when outcome=live
               + wants_video: bool = False                        # client fetches row 0 at once
               sent_off_site: str = ""                            # kept; always ""
AskRequest     question: str (1..500)
               + choose: str | None                                # a query id from a CHOOSE answer
               + from_audit: str | None                            # the audit id of that CHOOSE answer

AskClipStart   { kind: "saved" | "recorder", url: str | None, job_id: str | None }
AskClipJob     { id, state: queued|running|done|failed, chunk_urls: list[str],
                 cause: AskClipCause | None, reason: str | None }
AskClipCause   no_archive | unreachable | not_yet | expired | not_recorded | no_video | busy

AskExample     { id, query, text, state, source, added_by, added_at,
                 approved_by?, approved_at?, removed_by?, removed_at? }
AskCorrection  { question: str, query: str }
AskExampleRefused { breaks: str, wanted: str, would_get: str }    # 409 body
```

`AskState` (System Health) adds `accuracy: Fraction | None` and
`measured_on: date | None`, read from the evidence file the corpus tool writes.
None means "not measured on this site yet".

## 5. Note codes

| Removed | Added |
|---|---|
| `ask.cloud_unavailable` | `ask.model_unavailable{reason}`: model missing or failed to load |
| `ask.words_left_site` | `ask.subsystem_unavailable{reason}`: replaces the misuse of cloud_unavailable for a query's subsystem |
| | `ask.switched_off{feature}` |
| | `ask.which_day`: an unknown date word |
| | `ask.which_place{options}`: two places, or a place with several cameras |
| | `ask.clip.{no_archive,unreachable,not_yet,expired,not_recorded,no_video,busy,expired_ref}` |
| | `ask.example.breaks{question}` |

Each code goes into `notes.CODES`, `keys.ts`, `en.ts` and `ar.draft.ts`, in
both apps (the parity files). `test_notes.py` checks every code both ways.

## 6. Config

```yaml
ask:
  enabled: true
  model: models/ask/model.onnx          # path now, not a Gemini id
  tokenizer: models/ask/tokenizer.json
  examples: engine/data/ask/examples.yaml
  floor: 0.0          # set by ask_calibrate.py from the tuning part
  margin: 0.0
  refuse_floor: 0.0
  clip_seconds: 10    # each side of the moment
archive:
  # existing keys unchanged, plus:
  keep_ask_clips: 20
  ask_clip_timeout_seconds: 15
  recorder_lag_seconds: 60
  retention_days: null   # when unset, "expired" and "never recorded" are one honest cause
```

An old `ask: model: gemini-…` is recognised by its value (no path separator,
no `.onnx`), logged once as "ignored, Gemini is gone", and replaced with the
default path. `timeout_seconds` is accepted and ignored for one release.
