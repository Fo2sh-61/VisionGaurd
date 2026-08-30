# Quickstart: proving Ask works

Every check below is runnable. Four of the five need no API key — that is deliberate,
because the parts that can lie about people are the parts that must be provable
without a network.

## Prerequisites

```powershell
.\dev.ps1 doctor
```

`GEMINI_API_KEY` in `.env` is needed **only** for §4. Without it Ask reports
itself unavailable, which is itself one of the things to check (§5).

---

## 1. The gates

```powershell
.\dev.ps1 test
```

pyflakes, pytest, smoke, tsc. The pytest count must be **above** the baseline in
[context.md](./context.md#4-baseline), never below it.

## 2. Masking — no key needed, and the one that matters most

```powershell
python -m pytest engine/tests/test_ask.py -k mask -v
```

Reads `engine/tests/data/ask_questions.yaml`. Proves, for every entry:

- the name is found in **every** spelling — `سارة` / `ساره` / `Sara` / `Sarah`
- both digit systems fold — `٢٠٢٦` and `2026`, `ص ب د ٢٣٤` and the Western form
- the placeholder round-trips: unmasking returns the value that was masked
- **no name from the directory and no plate from the register appears in the
  masked text** — the assertion that is SC-002

If one case fails, that is a name leaving the site. It is not a routing bug and must
not be triaged as one.

## 3. Routing and the honest states — no key needed

```powershell
python -m pytest engine/tests/test_ask.py -k "routing or honest" -v
```

Uses a stub `Parser` returning fixed answers, so it tests **Ask**, not the model:

- each menu id reaches exactly one `Store` method (counting stub)
- unsupported → `ask.unsupported`, no rows, no deep link
- missing parameter → `ask.needs_detail` naming the parameter, and the query does
  **not** run
- unknown person → `ask.unknown_person`, **not** an empty result
- a bag question → `ask.not_recorded` plus a link, never a result
- subsystem down → that subsystem's own note, forwarded unchanged
- parser raises → `ask.cloud_unavailable`, and the audit row still exists

## 4. The real model — needs a key

```powershell
python engine/tools/ask_corpus.py          # writes the SC-003 number
```

Runs every question in the corpus through `CloudParser` and prints the routing
score. **SC-003 is ≥95%.** The report names every question that routed wrongly, so a
failure is a list to read rather than a percentage to argue with.

Run it against `gemini-3.7-flash` and `gemini-3.5-flash-lite` before choosing, and
read the Arabic and Franco-Arabic scores separately from the English one — that
comparison is the evidence [research.md §1](./research.md) says does not exist yet.

The free tier allows 1,500 requests a day and 15 a minute. A corpus of a few hundred
questions run twice fits comfortably, but pace the loop or you will meet a 429.

## 5. By eye, in the console

```powershell
.\dev.ps1 up -Mock
```

Open Ask and check, in order:

1. **Arabic in, Arabic out.** Type `سارة جت امتى النهاردة؟`. The answer, the
   "understood as" line and the link are all Arabic; the person's name is exactly as
   enrolled, untranslated.
2. **The understood line is always there.** It cannot be collapsed or hidden — a
   wrong route has to be visible.
3. **The deep link lands on the same numbers.** Follow it; the page must show what
   Ask showed. If they differ, Ask is wrong, because the page is the source of truth.
4. **An out-of-scope question refuses** and names what Ask can answer about.
5. **Now break the cloud** — remove the key and restart. Ask says it is temporarily
   unavailable, and every other page, the knife review gate and the vehicle register
   behave exactly as before. That is SC-006, and it is the check to do last because
   it is the one that matters if this feature ever misbehaves in production.

## 6. What an administrator can inspect

On the Ask page as an administrator, each answered question shows **the exact text
that was sent off-site**. Check a question containing a name: the name must not be
in it. Check one containing a word the site does not know — a visitor's name: it
**will** be in it, and the answer must say so (`ask.words_left_site`). That is the
accepted limit from the spec, visible rather than buried.
