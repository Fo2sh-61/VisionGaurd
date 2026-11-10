# Contract: Local Ask

Permissions are decided by **path** in `auth/deps.py`. On v2, `POST /ask` also
checks per query that the account may run it, and every clip endpoint repeats
that check against the query recorded in the ledger.

## The parser seam (unchanged shape, richer result)

```python
class Parser(Protocol):
    def parse(self, masked_question: str) -> Parsed: ...

class Parsed(BaseModel):
    query: str | None            # None = unsupported
    params: dict[str, str]       # filled by the lexicon, not the model
    missing: str | None
    score: float = 0.0           # NEW: best example's similarity, 0..1
    alternatives: list[str] = [] # NEW: the runner-up when the answer is "choose"
    decision: Literal["answer", "choose", "refuse"] = "answer"   # NEW

class Encoder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...   # (n, 384), L2-normalised
```

- `build_parser()` returns `LocalParser(encoder, examples, thresholds)` or an
  `UnavailableParser(reason)` (no model file, load failure, or switched off).
- **Nothing else in Ask may import `encoder.py`** (P12-FR-022 / P15-FR-004).

## POST /ask (all signed-in roles; v2 checks the role per query)

Request: `{question, choose?, from_audit?}`

- No `choose`: the full path in plan §1.
- `choose` set: `from_audit` must name a recent `choose` answer by the **same
  account** whose two choices include `choose`. Otherwise it returns
  `needs_detail` and is never trusted blindly.
  - The model is skipped and that query runs with the params from that answer.
  - The audit entry is `ask.choice`.
  - A `suggested` example is stored.

Response: `AskAnswer` (data-model §4). It is always 200. Degradation is
payload (rule 7). `sent_off_site` is always `""`.

## POST /ask/clips/{ref} (inherits the query's permission)

1. Look up the ref in the ledger. If it is missing → 200 with
   `cause=expired_ref`.
2. Check the caller may reach the ref's `permission_path`: the query's
   `reads`, or `/path/legs` for a past moment on a named camera. If not → 403.
3. `_log(actor, "ask.clip", camera_name, f"{moment} ±{clip_seconds}s from {audit_id}")`.
   **This is written before anything is fetched or returned.**
4. A saved clip returns `{kind:"saved", url}`. A recorder clip submits a plain
   job on the Ask lane and returns `{kind:"recorder", job_id}`. A refusal (queue
   full, no archive) is a 200 with `cause`, never a 5xx.

`GET /ask/clips/jobs/{id}` → `AskClipJob`. `GET /ask/clips/jobs/{id}/chunks/{n}`
→ the file, or 404 with a reason. A `<video>` tag authenticates with the
`vg_session` cookie, as breach clips do.

## /ask/examples (added to `ADMIN_PREFIXES`; every method is admin-only)

| Method | Path | Does |
|---|---|---|
| GET | `/ask/examples?state=` | the list, newest first |
| POST | `/ask/examples/preview` | body `{question}` → `AskCorrectionPreview` (masked text, possible names) |
| POST | `/ask/examples` | body `AskCorrection` → 201 `AskExample`, or 409 `AskExampleRefused` |
| POST | `/ask/examples/{id}/approve` | suggested → active, or 409 if the guard fails |
| DELETE | `/ask/examples/{id}` | → removed (kept in history) |
| POST | `/ask/examples/reset` | every learned example → removed, back to the owner's set |

Every write: audit first, then the change, then the matrix rebuilt in place.
There is no background rebuild.

## Front end (both apps; the parity files are copied as bytes)

- `services/ask.ts` stops collapsing answers into `route | note | ignore` and
  returns the `AskAnswer` itself.
- The routing decision moves to the `AskAnswer` component, which:
  - always shows the understood line;
  - shows rows with their notes;
  - shows a clip button only where `clipRef` is set;
  - shows two buttons for `choose`;
  - opens live view for `live`;
  - fetches row 0's clip at once when `wantsVideo`;
  - otherwise shows the "want me to fetch the clip?" chip.
- Clip URLs always pass through `assetUrl()`.
- Live view on the console is `/?camera=<id>`, which opens `CameraModal` with
  `detections={false}`. On the phone it is `/cameras/:id`.
