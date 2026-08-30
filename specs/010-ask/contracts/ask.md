# Contract: Ask

Two contracts. One crosses the network (`POST /ask`); one is internal but is the
whole point of the design (`Parser`).

---

## 1. `POST /ask`

**Request**

```json
{ "question": "سارة جت امتى النهاردة؟" }
```

One field. No language hint — the parser reads mixed script, and guessing a language
in order to help it is a way to be wrong.

**Response — always `200`, always an `AskAnswer`.**

Degradation is payload, never a 5xx (constitution rule 7). "The cloud is down" and
"the counting subsystem is off" are answers about the system's state, not failures
of this endpoint.

The three status codes that *can* come back are the ones already true of every
endpoint: `401` unauthenticated, `422` malformed body, `503` only if the store
itself is absent.

### Worked responses

**Answered**

```json
{
  "outcome": "answered",
  "understood": {
    "query": "attendance",
    "params": { "mode": "person", "subject": "Sara Ahmed", "date": "2026-08-30" },
    "assumed": ["date"]
  },
  "headline": [{ "label": "Arrived", "value": "07:42" }],
  "rows": [{
    "label": "Sara Ahmed", "camera": "Main entrance",
    "at": { "utc": "2026-08-30T04:42:00Z", "tzOffsetMinutes": 180 },
    "confidence": 0.91, "clipUrl": null, "note": null
  }],
  "note": null,
  "deepLink": "/attendance?mode=person&subject=Sara%20Ahmed&date=2026-08-30",
  "sentOffSite": "when did PERSON_1 arrive today?",
  "auditId": "a184"
}
```

`assumed: ["date"]` is the honesty. The question said "today"; Ask says it read that
as today rather than leaving the operator to assume.

**"Track Ali" — the shape every entry is held to**

```json
{
  "outcome": "answered",
  "understood": {
    "query": "person_path",
    "params": { "person": "Ali Hassan", "date": "2026-08-30" },
    "assumed": ["date"]
  },
  "headline": [
    { "label": "Stops", "value": "4" },
    { "label": "Last seen", "value": "09:15 · Corridor B" }
  ],
  "rows": [
    { "label": "Main entrance", "at": { "utc": "2026-08-30T04:42:00Z", "tzOffsetMinutes": 180 },
      "camera": "Main entrance", "confidence": 0.91, "clipUrl": "/clips/…", "note": null },
    { "label": "Corridor B", "at": { "utc": "2026-08-30T06:15:00Z", "tzOffsetMinutes": 180 },
      "camera": "Corridor B", "confidence": 0.74, "clipUrl": null, "note": null }
  ],
  "note": null,
  "deepLink": "/track?person=Ali%20Hassan&date=2026-08-30",
  "sentOffSite": "track PERSON_1",
  "auditId": "a187"
}
```

This is the contract's most important example. **The rows are the answer**; the deep
link is somewhere to go afterwards. A response to "track Ali" carrying a `deepLink`
and no rows is a defect, not a degraded answer — invariant 5 in
[data-model.md §2](../data-model.md#2-the-menu--enginevgaskmenupy) is the test.

Note what the rows carry: the confidence drops to 0.74 on the second stop and it is
shown. Ask forwards the evidence's own strength; it never rounds an appearance match
up into a named certainty.

**Unsupported**

```json
{
  "outcome": "unsupported",
  "understood": null, "headline": [], "rows": [],
  "note": { "code": "ask.unsupported", "args": {} },
  "deepLink": null,
  "sentOffSite": "why was PERSON_1 late?",
  "auditId": "a185"
}
```

The list of what Ask *can* answer lives in the wording, not in this payload. It is a
sentence, so the console owns it (P11).

**Cloud unreachable**

```json
{
  "outcome": "unavailable",
  "understood": null, "headline": [], "rows": [],
  "note": { "code": "ask.cloud_unavailable", "args": { "reason": "timeout" } },
  "deepLink": null,
  "sentOffSite": "",
  "auditId": "a186"
}
```

`sentOffSite` is `""` because nothing left. Still audited — a question asked during
an outage is still a question asked.

**Subsystem behind the query is down**

`outcome: "unavailable"`, and the `note` is **the subsystem's own** existing code and
reason, not an Ask-specific one. Ask must not paraphrase another feature's
explanation; it forwards it.

### Rules this endpoint must satisfy

| | Rule | Test |
|---|---|---|
| 1 | The audit entry is written **before** the response is built | `auditId` is present on every outcome, including failures |
| 2 | Nothing is created, changed or deleted in any feature | run the corpus, snapshot every store list before and after |
| 3 | `sentOffSite` records exactly what left, byte for byte | assert no directory name or register plate appears in it |
| 4 | The response contains no field the model wrote | assert `AskAnswer` has no free-text field (a shape test) |
| 5 | Read-only for permissions: no menu entry under `ADMIN_PREFIXES` | assert over `QUERIES[].reads` |

---

## 2. The parser seam

```python
class Parser(Protocol):
    def parse(self, masked_question: str) -> Parsed: ...
```

`Parsed` is defined in [data-model.md](../data-model.md#3--parser-types--enginevgaskparserpy).

**What the implementation is handed:** a string. Not the store, not a camera, not a
frame, not the account. It cannot reach data even if a future implementation wanted
to — the seam is the privacy boundary, not just a tidiness boundary.

**What it may return:** a `Parsed`. Anything else — prose, an unknown id, malformed
output, an exception — is `unsupported` or `unavailable` at the call site. The
implementation never decides how a failure is shown.

**Cloud implementation.** Google Gemini, through the `google-genai` SDK:

```python
from google import genai

client.interactions.create(
    model=config.ask.model,                    # gemini-3.7-flash
    input=masked_question,
    response_format={"type": "text", "mime_type": "application/json",
                     "schema": Parsed.model_json_schema()},
)
```

The menu goes in the instructions (stable across every question) and the masked
question is the input (varies). That split is also the shape prompt caching wants if
this ever runs at volume, and on Groq-style free tiers cached tokens do not count
against the limit.

`Parsed.model_json_schema()` means there is exactly one definition of what the model
may return — the Pydantic class. No hand-written JSON schema to drift from it.

**Swapping it** must require no change outside `parser.py`: that is P12-FR-022, and
the test for it is that `ask()` names only the Protocol.

---

## 3. Console contract

One function in `services/api.ts`:

```ts
export async function ask(question: string): Promise<W.AskAnswer>
```

It returns the wire object unchanged. Every sentence is built in the page from
`note` and `understood.query` via `translate()`; `format.ts` renders the instants,
confidences and durations, as it does everywhere else.

**`CameraFrame` is not used on this page.** With `live`, it also polls recognition
boxes, which carry names — the trap AGENTS.md names explicitly. Ask shows the clip a
query already has, never a live tile.
