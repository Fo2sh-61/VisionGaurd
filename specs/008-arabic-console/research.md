# Phase 0 — Research: Arabic console

The specification carried no `[NEEDS CLARIFICATION]` markers, so this file
records the technical decisions instead, and what was measured to reach them.

---

## What was measured

Run against `988a140` on 28 Aug 2026. These numbers size every task.

| Thing | Count | How |
|---|---|---|
| Engine prose strings assigned to wire fields | **69** | AST walk over `engine/vg/**/*.py` for keyword arguments named `detail`, `reason`, `note`, `label`, `title`, `period_label`, `*_reason` whose value is a literal, f-string or concatenation ≥12 characters |
| — of those, production paths | **37** | `live.py` 26, `app.py` 7, `auth/deps.py` 2, `ingest/archive.py` 2 |
| — of those, demo store | **28** | `api/store.py` (`MockStore`) |
| — of those, excluded | **4** | 1 FastAPI app title, 3 in `identity/gallery.py` that sit on an internal `Match` dataclass and never cross the wire |
| Console user-visible strings | **~400** | regex scan found 644 candidates across 43 files; the surplus is enum values and fixture data. The exact set falls out of extraction |
| Physical direction properties in CSS | **10** | in 809 lines of `app.css`; **0** logical properties in use |
| Inline directional styles in TSX | **42** | 17 `textAlign`, 16 `left:`, 5 `marginLeft`, 2 `paddingLeft`, 1 `right:`, 1 `borderLeft`. Most of the `left:` are `CameraFrame` overlay geometry |
| `Intl` usage today | **0** | `format.ts` builds every date by hand. `formatCount` calls `toLocaleString()` with no locale, so it silently follows the browser |
| Web test framework | **none** | no vitest, no jest, no testing-library in `web/package.json` |

The largest single files by string count: `TrackPerson.tsx` (72),
`format.ts` (53), `Settings.tsx` (40), `VehicleRegister.tsx` (39),
`CameraSources.tsx` (35), `navigation.ts` (33).

---

## Decision 1 — Hand-rolled catalogue, no i18n library

**Decision**: a `MessageKey` union type, one complete English record, two partial
Arabic records, and a `t(key, args?)` function. No dependency.

**Rationale**: typing English as `Record<MessageKey, string>` makes the type
checker prove the catalogue is complete — a key with no English wording is a
build error. No library offers that, because their catalogues are runtime JSON.
For 400 strings and one plural language pair, an extraction toolchain and a
plural engine are cost without return.

**Alternatives considered**:
- *react-i18next* — the default choice, and genuinely better above a few thousand
  strings or five languages. Here it adds a runtime, a provider, a namespace
  concept and a JSON build step to solve a problem the type system already
  solves. Rejected on weight.
- *FormatJS / react-intl* — ICU MessageFormat is the right answer for complex
  plural and gender rules. Arabic has six plural forms, which sounds decisive
  until you look at the actual strings: the counted nouns in this console are
  almost all rendered as "N cameras" style labels next to a figure, not as
  grammatical sentences. Where a real plural is needed the catalogue can hold
  the handful of forms explicitly. Rejected as over-engineering, with the note
  that if plural rules ever get complicated, this is the thing to reconsider.
- *Browser-native `Intl.MessageFormat`* — not shipping in the target browsers.

---

## Decision 2 — Three Arabic files, so "reviewed" is a state the build can see

**Decision**: `ar.ts` holds approved wordings, `ar.draft.ts` holds drafted ones.
Lookup is `ar` → `ar.draft` (development builds only) → `en`. A release build
skips drafts and falls back to English.

**Rationale**: `P11-FR-004` says nothing unreviewed may ship and `SC-005` says
100% must be approved before release. Without a mechanism both are wishes. With
this split, "how much is still unreviewed" is a number the Settings page can
show, and a release that skipped the review is visibly half English rather than
invisibly wrong. Falling back to English is honest; shipping Arabic nobody has
read into a security console is not.

**Alternatives considered**:
- *One file with an `approved: true` flag per entry* — same effect, twice the
  noise per line, and it makes the diff of a review unreadable.
- *Review tracked outside the code, in a spreadsheet* — nothing enforces it, and
  the state goes stale the first time a string is edited.
- *Ship drafts and mark them visually* — puts unreviewed Arabic in front of a
  guard, which is the thing the requirement exists to prevent.

---

## Decision 3 — Two mechanisms for engine text, not one

**Decision**: explanations become `Note { code, args }`. Labels that already
carry a key (`Metric.label`, chart `title`, `period_label`) lose their prose
field entirely and the console maps the existing key.

**Rationale**: `Metric(key="capacity", label="Safe capacity")` already sends the
identity of the thing *and* a sentence for it. Wrapping the sentence in a Note
would keep the redundancy and just make it typed. Deleting it is smaller, and it
removes the failure mode where key and label disagree.

For genuine explanations there is no existing key, so a code has to be invented,
and it needs to carry facts — *which* camera is offline, *how many* minutes over
the limit. That is what `args` is for.

**Alternatives considered**:
- *One `Note` for everything* — uniform, but keeps a redundant field on every
  metric and chart forever.
- *Engine returns Arabic* — would need the caller's language on every request,
  put wording in two languages inside Python, and make a copy change a backend
  deploy. `web/src/services/content.ts` already argues against this in its own
  header comment, written before this feature existed.
- *Engine returns an English sentence and the console translates it* — a lookup
  keyed on prose. Any wording change silently breaks the Arabic.

---

## Decision 4 — Window labels become tokens

**Decision**: `WINDOW_DAYS` and `WEAPON_WINDOWS` key on `today`, `last7`,
`last30`, `last90`, `schoolYear`, `all`. Both front ends send tokens. Clean
break, no compatibility shim.

**Rationale**: `?window=Last 30 days` makes an English UI label a protocol
value. An Arabic console would have to send English behind the user's back, and
any rewording of the label would break the API. This is the same disease as the
prose `reason` fields, on the input side, and it is cheaper to fix now than to
work around in every page.

**Alternatives considered**:
- *Accept both tokens and old labels for a release* — this is an internal API
  between components that ship together. A shim would be permanent in practice
  and would keep the English strings alive in Python.
- *Leave it and map in the console* — the label lives in two places and drifts.

**Noted while investigating**: the two pre-existing test failures both index
`/breaches?window=Last 30 days` and are caused by `store.py:31`'s hardcoded
`TODAY = date(2026, 7, 29)` ageing out of a 30-day window on 26 Aug 2026. It is
demo-fixture rot, unrelated to windows or to Arabic, and out of scope here.

---

## Decision 5 — Locale as an explicit parameter

**Decision**: `format.ts` functions take the active language as a parameter.
Components read it from `useT()` / `useLanguage()`.

**Rationale**: the alternative — a module-level "current language" that `t()`
reads — is smaller to write and wrong in two ways. It misbehaves under React's
StrictMode double-render, and it makes every formatter depend on hidden state,
so none of them can be reasoned about alone. Every page is being edited for its
strings anyway, so threading the parameter costs almost nothing extra.

**Alternatives considered**:
- *Module global set by the provider* — rejected above.
- *A formatter object built once and passed down through context* — equivalent,
  but adds an indirection for no gain at this size.

---

## Decision 6 — `Intl` for dates and numbers

**Decision**: introduce `Intl.DateTimeFormat` and `Intl.NumberFormat` in
`format.ts`, keyed on the active language plus the site's digit system.

**Rationale**: today `format.ts` builds dates by hand and calls
`toLocaleString()` with no locale, so counts already silently follow whatever
the browser is set to — a latent inconsistency this feature removes rather than
adds. `Intl` gives Arabic month and day names for free.

Arabic-Indic versus Western digits is a locale extension:
`ar-EG-u-nu-arab` against `ar-EG-u-nu-latn`. That is what `SiteInfo.digits`
selects (`P11-FR-013`).

**What must not change**: `Instant` carries `utc` plus `tzOffsetMinutes` and the
console adds the offset itself. That arithmetic stays exactly as it is —
`Intl` formats the resulting wall-clock, it does not get told a timezone.
Handing `Intl` a timezone would reintroduce the bug P0-03 fixed.

---

## Decision 7 — Right-to-left by attribute, and never on the picture

**Decision**: `dir="rtl"` on `<html>`. Ten CSS properties become logical. The
`CameraFrame` picture container is pinned `dir="ltr"` and its overlay geometry
stays physical `left`/`top`.

**Rationale**: flex and grid mirror themselves under `direction`, which is why
809 lines of CSS only contain 10 properties that need touching. `left` is a
physical property and is *not* affected by `direction`, so the overlay boxes are
already safe — but only by accident. Pinning the container makes it deliberate,
so a later edit that reaches for a logical property cannot silently move every
box to the wrong side of the frame.

A mirrored camera picture would be a fabricated picture. Principle III forbids
it, and it is the one thing in this feature that would be a safety bug rather
than a cosmetic one.

---

## Decision 8 — No web test framework

**Decision**: do not add vitest. Prove what can be proved by the type checker
and by `pytest`.

**Rationale**: three things need proving, and each has a cheaper proof.

| Claim | Proof |
|---|---|
| The English catalogue is complete | `tsc` — `Record<MessageKey, string>` will not compile with a key missing |
| Every note code the engine can emit is known | `pytest` — `engine/tests/test_notes.py` walks the AST for `note(...)` calls and asserts each code is in the registry |
| No registered code is unreachable | same test, in reverse |
| How much Arabic is still unreviewed | computed at runtime from the catalogues and shown on the Settings page |

**Alternative considered**: adding vitest to assert that every `MessageKey` has
an Arabic entry. Rejected because that assertion is *wrong* — a partial Arabic
catalogue is the designed state during review, and the number that matters
(how many remain) is more useful on screen than as a test that fails until the
last string is done.

---

## Open risk, carried into implementation

**`SiteInfo.digits` needs somewhere to come from.** `SiteInfo` is built from
config, and `engine.yaml` has no site typography section today. The field is a
small addition with a `western` default, but the exact config plumbing was not
read during planning and is recorded in `context.md` as unverified.
