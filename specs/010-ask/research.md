# Phase 0 research: Ask

Four decisions. Each one was a fork where the wrong branch costs a week.

---

## 1. Which cloud model, and how is prose made impossible?

**Decision (owner, 30 Aug 2026).** The **Google Gemini API free tier**, through the
official `google-genai` Python SDK. Model `gemini-3.7-flash`, set in `engine.yaml` so
it is a configuration line, not a constant.

```python
from google import genai                       # package: google-genai

client.interactions.create(
    model=...,                                 # from engine.yaml
    input=masked_question,
    response_format={"type": "text", "mime_type": "application/json",
                     "schema": Parsed.model_json_schema()},
)
```

**Rationale.**

*It makes prose impossible.* The spec's hardest requirement is "strict JSON, never
prose" (P12-FR-002). Gemini takes a JSON schema directly, and `Parsed` is a Pydantic
model, so `Parsed.model_json_schema()` **is** the schema — no second definition to
keep in step. A reply outside the menu fails validation, and a validation failure is
`unsupported`, not something to salvage from a half-parsed string.

*The free tier is far larger than the need.* 1,500 requests a day and 15 a minute, no
credit card. A school realistically asks ~100 questions a day — fifteen times the
headroom. Flash-Lite doubles the per-minute limit if bursts ever matter.

*Arabic.* No public benchmark settles Egyptian dialect plus Franco-Arabic for this
exact task, so SC-003 on our own corpus remains the decider. The prior favours Gemini:
Google's Flash models are trained on far more multilingual web text than the open
models served by the free inference hosts, and published Arabic benchmark work uses
Flash as its *judge* model.

*The privacy upgrade is a billing change, not an engineering one.* Free-tier content
is used to improve Google's products; paid-tier content is not. Linking a card on the
same account flips that with **no code change** — same SDK, same key, same model.

**The accepted limit, decided by the owner on 30 Aug 2026.** Google's free tier may
use submitted content to improve its products, and human reviewers may read it. This
is accepted because masking means what leaves is *"when did PERSON_1 arrive today?"* —
no name, no plate, no face, no footage. The residue is the spec's known exception: a
word the site does not recognise is sent as typed, so an unenrolled visitor's name
could be read by a person. If the school's consent position changes, link billing.

**Alternatives considered.**

- *Anthropic Claude API.* No-training terms on the paid tier by default, and the
  strongest structured-output story — but there is no free tier, so it requires a new
  prepaid API account (a Claude subscription does not cover API use). At ~$3/month on
  Haiku 4.5 this was affordable rather than free; the owner chose free.
- *Groq free tier.* 1,000 requests/day, structured outputs, very fast. Rejected on
  the only axis that decides this feature: it serves open models (Llama, Qwen) that
  are measurably weaker on Egyptian dialect than Google's Flash models.
- *A local open-weight model.* Free per question and nothing would leave the site at
  all, which would make masking unnecessary. Blocked twice: AGENTS.md says the owner
  supplies every model and none is to be sourced or downloaded, and the dev GPU is an
  RTX 2080 Max-Q with 8 GB already carrying YOLO, YuNet/SFace and the plate models.
  Revisit on the deployment hardware.
- *Raw HTTP instead of the SDK.* Rejected: retries, timeouts and typed errors are
  work the SDK has already done, and the project installs through `requirements.txt`.

---

## 2. Where does `ask()` live?

**Decision.** `MockStore.ask(question, actor)`, inherited by `LiveStore`. Not
overridden.

**Rationale.** `ask()` holds no data of its own. It masks, parses, and then calls
`self.attendance(...)` / `self.breaches(...)` / whichever the menu names. Python
resolves `self` to whichever store is mounted, so one implementation answers from
fixtures in demo mode and from live data in production, and the *result* carries
whatever honesty labelling that store already attaches.

This is the single largest simplification available in the feature, and it is also
the one most likely to be "corrected" by a future reader who sees orchestration on
`MockStore` and remembers P0-01. It is not that bug: P0-01 was a live path silently
*falling back* to fixtures. Here nothing falls back — the store never changes.

**Alternatives considered.**

- *Implement on `LiveStore` only.* Then Ask does not work under `dev.ps1 up -Mock`,
  which is the fast loop the whole console is developed in, and the page cannot be
  built without models loaded.
- *Implement in both.* Two orchestrations to keep in step. The mock one rots, and
  it rots silently because the tests would use it.
- *A service object outside `Store`.* It would need the store injected anyway, and
  every endpoint in this codebase reaches its data through `Store`. A second pattern
  for one feature is a tax on every future reader.

A test asserts `LiveStore.ask is MockStore.ask`, so the day somebody overrides it,
that is a decision rather than an accident.

---

## 3. How are thirteen different results rendered honestly, without thirteen views?

**Decision.** One flat `AskAnswer`: `headline` (existing `Metric` list), `rows`
(time, camera, confidence, clip, label), `understood`, `note`, `deepLink`. The menu
entry flattens; one page renders.

**Rationale.** Thirteen bespoke result views would be most of the implementation cost and
thirteen separate opportunities to render something the query did not return. The flat
shape is small enough to audit in one sitting: it has **no free-text field**, so
there is nowhere for an invented sentence to live even by mistake.

**What the flat shape must not become is a way to avoid answering.** An earlier draft
of this said that where a result does not fit, the deep link is the answer. That is
wrong, and it would have hollowed the feature out: "track Ali" would have returned a
link to the Track page, which is precisely the thing an operator can already do and
the reason Ask exists. Every entry returns the data — Ali's stops, with their cameras,
times and evidence. If a result will not fit the shape, the shape gets another field;
the requirement does not get smaller.

The one honest exception is a feature that **stores nothing** — lost items — where
there is no answer to return in any shape. That is absence, and Ask names it.

Richer views that genuinely cannot be a list of rows — the counting chart over time,
the path drawn on a map — are reached through the deep link *after* the answer, never
in place of it.

**Alternatives considered.**

- *Return the raw wire object per query and switch on the id in React.* Honest, but
  it is the thirteen views again, plus a discriminated union that grows every time the
  menu does.
- *Let the model summarise the result.* Rejected outright — P12-FR-003. This is the
  requirement the whole feature exists to protect.

---

## 4. Permissions, when one path runs thirteen queries

**Decision.** Restrict the menu to queries a guard may already read, and assert it
with a test that checks no menu entry maps to a path under `ADMIN_PREFIXES`.

**Rationale.** Permissions in this codebase are decided by **path**, in
`auth/deps.py`, deliberately — "the one endpoint somebody forgets to decorate is the
one that leaks". `POST /ask` is one path that can reach thirteen queries, so path rules
cannot see what it is about to run. Rather than invent a second permission system
inside Ask (exactly what the constitution warns against), the menu is kept inside
what the weakest role can already read. Every read query Ask exposes is already
readable by a guard today; `/enrolment`, `/sources` and `/users` are not in the menu
and a test stops them being added.

**Alternatives considered.**

- *Per-entry role checks in `ask()`.* A second place where roles are decided, and
  the first place a future query gets it wrong.
- *Make `/ask` admin-only.* Defeats the feature. The guard at the gate is the person
  who cannot find the right page.

---

## Things that turned out not to need research

- **Arabic wording.** P11 shipped. `i18n/keys.ts`, `en.ts`, `ar.draft.ts` and the
  `Note` mechanism all exist, and `nav.section.ask` is already in the key union.
- **The audit helper.** `MockStore._log(actor, action, subject, detail)` is the
  idiom, written before the result returns. `track` already does exactly this.
- **`notes.py`.** Built in P11 with `CODES = frozenset()` — empty. Ask is its first
  user, and `test_notes.py` already enforces both directions of the contract
  (a code with no emitter, an emitter with no code).
