# Contract — parity between the two apps

Mohamed chose two independent apps with the code copied across. The known cost
is drift. This contract is how drift is made loud instead of silent.

## The promise

**Every file listed below is byte-identical in `web/src` and `mobile/src`.**

Not "kept in sync", not "should match" — identical, checked on every push, and a
difference fails the build.

This is not a hypothetical worry. `web/src/styles/tokens.css` opens with:

> Kept byte-identical to `mobile/src/styles/tokens.css` so both apps share one
> palette.

It is not. `diff` shows differing comments and a `@keyframes vg-nextcam` block
present in one and absent in the other. A comment asking people to be careful is
what we have today, and it already failed.

## The list

| `web/src/…` → `mobile/src/…` |
|---|
| `types.ts` |
| `services/api.ts` |
| `services/wire.ts` |
| `services/http.ts` |
| `services/format.ts` |
| `services/frame.ts` |
| `services/content.ts` |
| `services/notes.ts` |
| `services/ask.ts` |
| `i18n/index.ts` |
| `i18n/keys.ts` |
| `i18n/en.ts` |
| `i18n/ar.ts` |
| `i18n/ar.draft.ts` |
| `app/AuthContext.tsx` |
| `app/CameraContext.tsx` |
| `app/CapabilityContext.tsx` |
| `app/LanguageContext.tsx` |
| `app/SiteContext.tsx` |
| `app/ThemeContext.tsx` |
| `app/useAsync.ts` |
| `app/useAttention.ts` |
| `app/useAutoRun.ts` |
| `app/useOptions.ts` |
| `styles/tokens.css` |

25 files, ~7,952 lines.

The list lives in `tools/check_parity.py` itself, not in this document. A list in
prose is a list that goes stale; the checker is the source of truth and this page
describes it.

## The checker

`tools/check_parity.py`

- Compares the two files **as bytes**, not as text.
- Reports every file that differs, with a unified diff, then exits non-zero.
- Says plainly which side is which, because "they differ" without "here is how"
  is a gate people learn to route around.

**Read bytes, never text.** `AGENTS.md` records why: this repo has mixed line
endings and no `.gitattributes`. `services/*.ts` and `types.ts` are CRLF; most
other files are LF. A checker that reads with Python's text mode normalises
endings and would call a CRLF file and an LF file identical — which is exactly
the difference that makes a diff unreadable later. Compare `read_bytes()`.

The same rule binds the implementation: **copying these files must preserve their
line endings.** A copy done by reading and re-writing text turns a 25-file copy
into 25 whole-file diffs. Copy bytes.

## Adding to the list

A new file joins the list when it decides *what is true* and carries no layout.
A new file stays off the list when it decides *how something looks*.

If a file needs to be on the list but genuinely must differ between the two apps,
that is a design problem, not an exception to grant: the differing part belongs in
Pile 3 and the rest stays identical. Say so rather than removing it from the list.

## Where it runs

| | |
|---|---|
| `.\dev.ps1 test` | Alongside the existing four gates, so a developer sees it before pushing |
| `.github/workflows/ci.yml` | In the `web` job, which already has a checkout and needs no Node for this |

## The second checker

`tools/check_parity.py --no-fixtures` (same script, separate job)

Asserts that the phone ships no fake data:

- No file named `mockData.ts` exists anywhere under `mobile/src`.
- No file under `mobile/src` contains `Math.random(` — the fixture app used it to
  regenerate campus figures on each visit, which is the single most misleading
  thing a security console can do.

Deleting the fixture modules already makes a stale import fail `tsc`. This adds
the case `tsc` cannot see: somebody writing *new* invented numbers inline.

Both checks are cheap and neither needs the app to run.
