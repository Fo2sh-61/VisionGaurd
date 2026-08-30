# Quickstart — proving the Arabic console works

Every check below maps to a requirement or a success criterion. Run them in
order; the first three catch most regressions in seconds.

---

## Prerequisites

```powershell
.\dev.ps1 doctor
```

An account to sign in with. Nothing else — no models are needed for any check
except the overlay one.

---

## 1. The catalogue is complete (SC-005, P11-FR-002)

```bash
cd web; npx tsc -b --force
```

Must be clean. `en.ts` is typed `Record<MessageKey, string>`, so a key with no
English wording fails here. This is the whole English-completeness proof — there
is no separate test.

A missing **Arabic** wording is *not* an error. It is the designed state during
review, and it falls back to English.

---

## 2. Every note code is known (P11-FR-005, P11-FR-007)

```bash
python -m pytest engine/tests/test_notes.py -q
```

Two assertions:

- every `note(...)` call in `engine/vg/**` uses a code declared in
  `engine/vg/api/notes.py`
- every declared code is emitted somewhere — a code nobody sends is a wording
  nobody will ever see, and it will rot

---

## 3. Nothing else broke

```bash
python -m pytest engine -q
```

**Baseline at `988a140` is `1299 passed, 2 failed, 6 skipped`.** The two
failures are pre-existing and unrelated — `store.py:31` hardcodes
`TODAY = date(2026, 7, 29)` and the demo breaches aged out of a 30-day window on
26 Aug 2026. Passing count must go **up**, never down, and no new failure may
appear. If those two are fixed separately, the baseline becomes 1301.

```bash
python -m pyflakes engine/vg engine/tools engine/tests
```

---

## 4. Read the console in Arabic

```powershell
.\dev.ps1 up -Mock
```

Sign in, open Settings, switch to Arabic. Then walk every page.

| Check | Requirement |
|---|---|
| Words are Arabic on every page, including navigation and buttons | P11-FR-001, SC-001 |
| The page reads right to left | P11-FR-008 |
| Nothing overflows, overlaps or is clipped — at 1280px and at phone width | P11-FR-010, SC-004 |
| It changed without signing out | P11-FR-015 |
| Sign out, sign back in — still Arabic | P11-FR-014, SC-003 |
| Sign in as a *different* account — that account's own language | P11-FR-014 |
| The sign-in page itself offers both | P11-FR-016 |

Deep links do not work in dev — a page URL returns JSON through the proxy. Load
`/` and click through.

---

## 5. The messages that matter most

These are the reason the feature exists. Each needs a degraded state to look at,
so `-Mock` is the fastest way to see several of them.

| To see | Do this | Check |
|---|---|---|
| `gate.noExitCamera` | open Vehicle Gate with no exit camera configured | Arabic, and it still says **cars leaving are not being counted** — not just "no exit camera" (P11-FR-006) |
| `health.*` | open System Health | every subsystem's state and failure reason is Arabic; the `{why}` exception text stays English and is visibly a technical detail |
| `attendance.late` | a person who arrived after the cut-off | the minutes and the cut-off time appear in the Arabic sentence in Arabic order, not English order with Arabic words |
| `auth.badCredentials` | sign in with a wrong password | the error is Arabic — this comes through `http.ts`, the path most likely to be forgotten |
| `sweep.overLimit` | ask for a sweep over the limit | Arabic, with both numbers |
| `note.unknown` | temporarily send a made-up code from the engine | shows a named unavailability, never a blank (P11-FR-007) |

---

## 6. Empty, loading, failed, degraded

The four states usually left in English. On any list page:

- with no data → Arabic empty state
- with the engine stopped (`.\dev.ps1 down`, leave the browser open) → Arabic
  load error
- mid-load → Arabic loading state
- with a subsystem down → Arabic degradation notice **with its reason**

---

## 7. The camera picture is not mirrored (P11-FR-009, SC-006)

The one check that is a safety check rather than a cosmetic one.

```powershell
.\dev.ps1 up -Clip
```

Open a camera page in English, screenshot it. Switch to Arabic, screenshot the
same frame.

- the picture is pixel-identical
- every box sits over the same thing
- a box labelled with a person's name is on the same body

If a box moved, `dir="rtl"` reached the overlay container. That is a fabricated
picture, and it is the one failure in this feature that would be a lie rather
than an inconvenience.

---

## 8. Numbers, dates and plates

| Check | Requirement |
|---|---|
| Dates and month names are Arabic | P11-FR-011 |
| The **instant** is unchanged — the same event shows the same clock time in both languages | P11-FR-012 |
| Digits follow the site setting, not the language | P11-FR-013 |
| A plate renders exactly as it does in English — it is **not** transliterated again | data-model.md §5 |
| A person's name, a camera name, an area name are unchanged | spec, Edge cases |

---

## 9. What is still unreviewed (P11-FR-003, P11-FR-004)

Settings shows approved / draft / missing counts.

- in a dev build, drafted Arabic renders, so Mohamed can review it in place
- in a release build, drafts do **not** render — unapproved keys fall back to
  English

Release gate: the draft count must be **zero** (SC-005). A release that skipped
the review is visibly half English, which is the honest failure.

---

## 10. Ask Mohamed to look

Things only a native Arabic speaker can confirm, and the reason `P11-FR-004`
exists:

- the wording is right, not merely grammatical
- a sentence with a Latin camera name or a plate inside it is not scrambled
- the tone matches how the school actually talks about these things
