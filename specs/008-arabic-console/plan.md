# Implementation Plan: Arabic console

**Branch**: `008-arabic-console` | **Date**: 28 Aug 2026 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-arabic-console/spec.md`

## Summary

Two piles of work, and only one of them is translation.

The small pile is a message catalogue and a direction switch in the console:
about 400 strings move out of the markup into one typed table with an English
column and an Arabic column, `<html>` gains `lang` and `dir`, ten physical CSS
properties become logical ones, and dates and numbers start going through
`Intl` instead of being assembled by hand.

The load-bearing pile is a **contract change**. The engine writes 65 English
sentences and ships them to the screen in `reason`, `detail`, `note`,
`period_label` and `label` fields — 37 in production paths, 28 more in the demo
store that shares the same schemas. Those become a code plus its facts, and the
console builds the sentence. A third symptom of the same disease goes with them:
`?window=Last 30 days` uses an English UI label as a protocol value, so today
the console cannot change its own wording without breaking the API.

Nothing about the pipeline, the models, or the overlays changes. The camera
picture is explicitly excluded from mirroring.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 + React 19 (console)

**Primary Dependencies**: FastAPI + pydantic v2 on the engine; Vite + React on
the console. **No new runtime dependency.** `Intl` is in the platform.

**Storage**: SQLite. One new column, `app_user.language`, added with the
`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` guard already used in
`engine/vg/events/vehicles.py`.

**Testing**: `pytest` on the engine (baseline **1299 passed, 2 failed,
6 skipped** at `988a140` — see *Pre-existing failures* below); `tsc -b --force`
on the console. **No web test framework exists and none is added** — the
completeness of the English catalogue is proved by the type checker instead.

**Target Platform**: On-premise Windows workstation, Chrome/Edge console.

**Project Type**: Web application — Python engine, React console, React mobile
shell (fixtures only).

**Performance Goals**: No per-frame cost. Language is resolved once per render,
not per row. The engine does *less* string work than it does today.

**Constraints**: Right-to-left must never reach the camera picture or its
overlay geometry. The instant a timestamp names must not change with language.

**Scale/Scope**: ~400 console strings across 43 files, 65 engine prose sites,
10 CSS properties, 2 wire additions, 1 new endpoint, 1 new column.

## Constitution Check

*GATE: passed before Phase 0, re-checked after Phase 1.*

| Principle | How this feature satisfies it |
|---|---|
| **I. Real-time** | No pipeline change. The console resolves a language at render, and the engine stops building strings, so both do marginally less work. |
| **II. Feature isolation** | Language is chrome, not a feature. Nothing may be gated on it (`P11-FR-017`). Each feature page keeps drawing its own overlay. |
| **III. Truthful data** | The whole point. A missing Arabic wording falls back to visible English, never a blank and never a key (`P11-FR-002`); an unrecognised note code renders as a named unavailability rather than an empty space (`P11-FR-007`). Every note code must preserve the *consequence*, not just the cause (`P11-FR-006`). |
| **IV. Reliability & privacy** | No new data about a person is stored. `app_user.language` is a preference and is explicitly **not** consulted by any permission decision — `auth/deps.py` keeps deciding by path. |
| **V. Complete UX** | Error, empty, degraded and loading states are named in the acceptance scenarios precisely because they are the states usually left in English. |

**Re-check after Phase 1**: no violation introduced. The one thing that needed
care and got it: `CameraFrame`'s overlay container is pinned `dir="ltr"` so that
right-to-left can never move a box off the thing it describes. A mirrored
picture would be a fabricated picture, and Principle III forbids it.

## Pre-existing failures — not caused by this feature

`python -m pytest engine` is **already red** at `988a140`, before any change:

```
FAILED engine/tests/test_api.py::TestWireShape::test_everything_is_camel_case
FAILED engine/tests/test_api.py::TestWireShape::test_time_is_utc_plus_an_explicit_site_offset
```

Both are the same cause. `engine/vg/api/store.py:31` hardcodes
`TODAY = date(2026, 7, 29)`. The demo breaches are dated `TODAY - 2/3/9` days,
so on **26 Aug 2026** the newest of them fell out of a 30-day window and
`/breaches?window=Last 30 days` started returning `[]`. Both tests then index
`[0]` of an empty list.

This is demo-fixture rot, not an Arabic problem, and it is **out of scope
here**. It is recorded so the implementing chat does not think it broke
something, and so "pytest must be green" is understood to mean *1299 passed and
these same 2 failing* until it is fixed separately. If it is fixed first, the
baseline becomes 1301 passed.

## Design decisions

### 1. No i18n library

A typed catalogue and a `t()` function. `react-i18next` and FormatJS both add a
runtime, a plural engine this product barely needs, and an extraction toolchain,
in exchange for solving a problem 400 strings do not have.

The payoff for hand-rolling is specific: `en.ts` is typed
`Record<MessageKey, string>`, so **the type checker proves the English
catalogue is complete**. A key with no English wording will not compile. That is
a stronger guarantee than any library gives, and it costs one type annotation.

### 2. Three Arabic files, so "reviewed" is a real state

| File | Type | Meaning |
|---|---|---|
| `en.ts` | `Record<MessageKey, string>` | complete, compiler-enforced |
| `ar.ts` | `Partial<Record<MessageKey, string>>` | **approved by Mohamed** |
| `ar.draft.ts` | `Partial<Record<MessageKey, string>>` | drafted, awaiting review |

Lookup order is `ar` → `ar.draft` (**development builds only**) → `en`.

A release build never renders an unreviewed wording — it falls back to English,
which is honest, rather than to Arabic nobody has read, which is not. That makes
`P11-FR-004` a mechanism instead of a promise, and it makes `SC-005`
("100% approved before release") a thing that can actually be checked: the
count of remaining drafts, shown on screen, must be zero.

### 3. Messages take parameters; sentences are never concatenated

`t('attendance.late', { minutes: 7, cutoff: '08:15' })`, never
`t('attendance.arrived') + n + t('attendance.afterCutoff')`. Arabic does not
order the fragments the way English does, and a joined sentence cannot be
reordered. This is `P11-FR-001` and it is the requirement most likely to be
violated by accident.

### 4. The engine sends codes, in two different shapes

Not everything needs the same mechanism, and using one for both would be worse.

**(a) Explanations become a `Note`.** `{ code, args }`. This is for the
sentences that say why something is unavailable — the vehicle gate with no exit
camera, the subsystem that failed to start, the sweep that would take too long,
the camera that is already recording. 37 production sites, 28 demo sites.

**(b) Labels that already have a key lose their prose entirely.**
`Metric(key="capacity", label="Safe capacity")` already carries `key`. The
`label` field is deleted from the wire and the console maps `key` → wording.
Same for chart `title` and `period_label`. Sending both a key and a sentence for
the same thing was always redundant; it is the redundancy that made it English.

### 5. Window labels stop being English

`WINDOW_DAYS` and `WEAPON_WINDOWS` in `engine/vg/api/app.py` key on
`"Last 30 days"`, `"This school year"`, `"All"`. The console sends those
strings as query parameters.

That means the console does not own its own wording — an Arabic label is
impossible without either sending English behind the user's back forever, or
duplicating each label in two places and hoping they stay in step. The keys
become stable tokens (`today`, `last7`, `last30`, `last90`, `schoolYear`,
`all`), the English moves into the catalogue, and both front ends send tokens.

This is a clean break with no compatibility shim: the engine and both front ends
ship together, and the tests move with them.

### 6. Locale is an explicit parameter, not a module global

`format.ts` gains a language parameter on each exported function rather than
reading a module-level "current language". A hidden global would be smaller to
write and would misbehave under React's double-render, and it would make every
formatter untestable in isolation. Every page is being edited anyway, so the
marginal cost of threading the parameter is close to zero.

### 7. Right-to-left is an attribute, not a stylesheet

`dir="rtl"` on `<html>`. The layout is flex and grid, which mirror on their own.
Only **10 physical properties** exist in 809 lines of `app.css` and they become
logical (`margin-inline-start` and friends). The 16 inline `left:` values are
almost all `CameraFrame` overlay geometry and **stay physical** — `left` is
unaffected by `direction`, and the container is pinned `dir="ltr"` so no future
edit can flip them.

### 8. Where the language lives

Per account, server-held (`P11-FR-014`), because the gate station is shared and
theme-style per-browser storage would show one guard the other guard's language.
`ThemeContext.tsx` is the shape to copy for the provider; the persistence is
different on purpose.

Before sign-in there is no account, so the login page falls back to a browser
preference in `localStorage` — the only place per-browser storage is correct.

## Project Structure

### Documentation (this feature)

```text
specs/008-arabic-console/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions and what was rejected
├── data-model.md        # Phase 1 — Note, MessageKey, language column
├── contracts/
│   ├── notes.md         # the note-code contract and the full code inventory
│   └── language.md      # Account.language, SiteInfo.digits, the endpoint
├── quickstart.md        # Phase 1 — how to prove it works
├── context.md           # Phase 1 — implementation handoff
└── tasks.md             # /speckit-tasks — not created here
```

### Source Code (repository root)

```text
engine/vg/
├── api/
│   ├── notes.py         # NEW — the code registry and note() helper
│   ├── schemas.py       # + class Note; prose fields retyped; label/title removed
│   ├── live.py          # 26 prose sites → note()
│   ├── store.py         # 28 demo prose sites → note()  (MockStore)
│   └── app.py           # 7 HTTPException details → codes; window tokens;
│                        #   POST /auth/language
├── auth/
│   ├── store.py         # + app_user.language column, User.language, set_language()
│   └── deps.py          # 2 details → codes
└── ingest/archive.py    # 2 sweep-estimate reasons → note()

engine/tests/
├── test_notes.py        # NEW — every emitted code is registered, and reachable
└── test_api.py          # window tokens; note shape on the wire

web/src/
├── i18n/
│   ├── keys.ts          # NEW — the MessageKey union
│   ├── en.ts            # NEW — complete, compiler-enforced
│   ├── ar.ts            # NEW — approved wordings
│   ├── ar.draft.ts      # NEW — drafted, dev-only
│   └── index.ts         # NEW — t(), useT(), coverage counts
├── app/
│   ├── LanguageContext.tsx  # NEW — copy ThemeContext.tsx's shape
│   └── navigation.ts    # 33 nav labels → keys
├── services/
│   ├── notes.ts         # NEW — Note → sentence
│   ├── format.ts        # + language parameter; Intl for dates and numbers
│   ├── content.ts       # copy lists → keys
│   ├── http.ts          # parse an error detail as a Note
│   ├── api.ts           # window tokens
│   └── wire.ts          # + Note type
├── components/
│   ├── CameraFrame.tsx  # dir="ltr" on the picture container
│   └── *.tsx            # strings → keys
├── pages/
│   ├── Login.tsx        # + language toggle (pre-sign-in)
│   ├── Settings.tsx     # + language selector; + translation coverage card
│   └── *.tsx            # strings → keys
├── styles/app.css       # 10 physical properties → logical
└── types.ts             # + Language, Note

mobile/src/              # types only — keeps compiling, stays English
```

**Structure Decision**: the existing engine/console/mobile split is unchanged.
The one new directory is `web/src/i18n/`, which holds the catalogue and nothing
else. `services/notes.ts` is deliberately *outside* it: rendering a wire type is
a service concern, and putting it in `i18n/` would invite the catalogue to start
importing wire types.

## Complexity Tracking

No constitution violations to justify. Two design choices are worth recording
because they look like scope creep and are not:

| Choice | Why it is not optional |
|---|---|
| Window labels become tokens | Without it the console cannot own its own wording, which is `P11-FR-001`. Leaving it means the Arabic label and the English protocol value must be kept in step by hand forever. |
| `MockStore`'s 28 prose sites move too | Both stores implement the same schemas. If the contract changes for one it changes for both, or the demo store stops type-checking. Their *Arabic wordings* are low priority — English fallback covers them — but their *codes* are not optional. |
