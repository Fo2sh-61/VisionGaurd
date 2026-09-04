# Phase 0 — Research

Everything here was checked against the code on 3 September 2026, not assumed.

---

## 1. Can the console's pages run inside a different shell?

**Decision**: Yes, without editing a single page body.

**Evidence**: `grep -rn "Sidebar\|TopBar\|AppShell" web/src/pages/ web/src/components/`
returns **nothing** outside the two shell files themselves. A page imports only:

- `@/app/*` — contexts and hooks (auth, camera, capability, site, language, `useAsync`)
- `@/components/ui` and `@/components/CamGrid`
- `@/services/api` and `@/types`
- `@/i18n`

None of that knows a sidebar exists. `Attendance.tsx` and `Weapons.tsx` were read
in full to confirm the pattern holds in practice and not just in imports.

**Why it matters**: the phone does not need re-implemented pages. It needs a
different **vocabulary** underneath the same pages.

**Alternative considered**: re-writing each of the 16 pages for the phone.
Rejected — 6,151 lines of business rules re-typed is 16 chances to get attendance,
role checks or the late cutoff subtly different from the console, and no way to
tell that it happened.

---

## 2. Copy, share, or merge?

**Decision**: Copy. `mobile/` stays an independent project with its own package,
build and design. **Chosen by Mohamed on 3 September 2026** when the three
options were put to him with their costs.

**Alternatives considered and rejected by him**:

- *Phone as a second entry point of `web/`* — one install, one typecheck, one
  proxy, no duplication. Rejected: he wants two genuinely parallel apps.
- *`mobile/` imports `web/src` across the folder boundary* — no duplication, but
  two `node_modules` means two copies of React and an invalid-hook crash unless
  deduped. Rejected for the same reason, and it carried a trap.

**The cost he accepted, and what this plan does about it**: two copies drift.
This is not hypothetical — `web/src/styles/tokens.css` says in its own opening
comment that it is "kept byte-identical to `mobile/src/styles/tokens.css`", and
`diff` shows it is not: comments differ and the web file has a `@keyframes
vg-nextcam` block the phone lacks.

So drift is treated as a build error, not a discipline problem. See
`contracts/parity.md`. The checker costs one small script and turns the one real
weakness of his choice into something that cannot happen quietly.

---

## 3. What actually has to be written, rather than copied?

**Decision**: the phone ships its own **vocabulary** — the same export names with
phone bodies — and copies everything that calls it.

Every console page renders through the same small set of things:

| Vocabulary | Where | Phone action |
|---|---|---|
| `Badge` `Card` `CardHeader` `PageHeader` `Stats` `Field` `Select` `Toggle` `DataNotice` `Empty` `LoadError` `StatusDot` `toneColors` `toneGlyph` | `components/ui.tsx`, 278 lines | Rewritten — same 14 exports, phone bodies |
| `.row` `.row--head` `.row--click` `.stats` `.stat` `.page` `.card` | `styles/app.css`, 848 lines | Rewritten for a narrow screen |
| `CamGrid`, `CameraFrame`, `CameraModal` | 915 lines | Grid and modal rewritten; `CameraFrame` copied — 450 of its 481 lines are overlay maths and polling, only 28 lines carry layout |

Because the names and props match, a copied page compiles against the phone's
vocabulary unchanged. That is what keeps ~10,300 lines a copy rather than a
rewrite.

**Measured sizes** (`wc -l`, 3 Sep 2026):

| | Lines |
|---|---|
| services (8 files) | 3,881 |
| i18n (5 files) | 2,431 |
| app contexts + hooks (10 files) | 926 |
| types.ts | 625 |
| tokens.css | 89 |
| **Verbatim total** | **7,952** |
| pages (16 files) | 6,151 |
| components minus Sidebar/TopBar | 4,918 |
| **Copied-and-recompiled total** | **11,069** |
| ui.tsx + app.css + shell + tiles | **~1,600 written** |

---

## 4. Wide tables on a 375 px screen

**Decision**: a row becomes a headline plus one summary line, and the rest of its
detail moves one tap away. Nothing is dropped.

**The problem**: 28 places set `gridTemplateColumns` inline, e.g.
`'1.5fr .7fr 1.4fr 1.5fr .9fr .9fr'` in `People.tsx` and `'64px 1fr 1fr 44px'` in
`CameraSources.tsx`. Six columns at 375 px is roughly 50 px each.

**The trap**: those are **inline styles**, so a media query in a stylesheet
cannot override `grid-template-columns` by ordinary specificity. This is the one
place the vocabulary trick leaks, and it must be handled deliberately.

**Mechanism**: in the phone's `app.css`, `.row` is not a grid at all. It is a
flex column: the first child is the headline, the remaining children render as a
single muted line separated by `·`, and `.row--head` is hidden because a header
over stacked rows means nothing. The inline `gridTemplateColumns` is then inert —
it sets a property that `display: flex` ignores — so **no page is edited** and
nothing has to fight specificity with `!important`.

Where that reads badly — the vehicle register, the camera channel list, system
health's worker table — the page gets a phone-specific presentation of its own,
listed as its own task rather than absorbed silently. Mohamed's instruction was
explicit: the design may differ, the functionality may not, and the UX must be
the best one available.

**Alternatives considered**:

- *Every column stacked with its own label* — nothing hidden, but a 20-row table
  becomes an enormous scroll and each row needs a label it does not currently
  carry.
- *Keep the columns, scroll sideways inside the card* — least work, but the spec
  forbids sideways scrolling (P13-FR-016, SC-005) and a table you must drag to
  read is not "best UX".

---

## 5. Why the phone gets no data at all today

**Decision**: `mobile/vite.config.ts` must gain the console's API proxy. This is
not a nicety; without it the feature cannot work.

`web/vite.config.ts` carries a long comment explaining it, and the reasoning
applies identically to the phone: camera streams are `<img src="/cameras/x/stream">`,
an `<img>` cannot carry an `Authorization` header, and the session cookie is
`SameSite=Strict` — so a page on `:5174` calling an engine on `:8000` gets no
credential, a 401, and a black rectangle, **while detection carries on working
server-side**. It looks like a video bug and is an auth one.

`mobile/vite.config.ts` today has `server: { port: 5174 }` and nothing else. It
gains the same `API_PATHS` list and the same proxy options, including
`changeOrigin: false` and the zero timeouts that let MJPEG stream rather than
buffer forever.

---

## 6. Arabic and right-to-left

**Decision**: free with the copy, except the tab bar.

`LanguageContext.tsx` line 63 sets `document.documentElement.dir = DIRECTION[language]`.
Copy it and the whole phone flips. Language is a property of the **account**, not
the browser, so a guard signing in on a shared phone gets their own language —
the reason is already written in that file's header and copies with it.

What is *not* free: the bottom tab bar is new code and must order itself by
`dir`, and the phone's `app.css` must use logical properties
(`padding-inline-start`, not `padding-left`) so a mirrored layout does not need a
second stylesheet.

The Arabic wording remains the same unproofread draft as the console's, on the
same dev-only footing. This feature does not touch it.

---

## 7. Five tabs, sixteen destinations

**Decision**: keep five tabs; two of them are lists.

| Tab | Reaches |
|---|---|
| **Ask** | Home — question box, attention, campus figures, recent |
| **Tools** | Attendance · Counting · Lost items · Track · Intrusion · Weapons · Vehicles — the console's `ask` and `watch` sections, all 7 |
| **People** | People → person history, group roster, and **Enrol** |
| **System** | System health, and camera setup |
| **Account** | Settings, language, theme, sign out, and **Users** for an admin |

The console's `navigation.ts` already groups its ten entries into `ask` / `watch`
/ `manage`; the phone's Tools tab is `ask` + `watch`, and `manage` splits across
the last three tabs. Every one of the 16 routes is reachable.

**Note**: the fixture app's tool list has **six** tools and is missing the vehicle
gate entirely. The phone list is built from the copied `navigation.ts`, so it has
ten and cannot silently miss one again.

---

## 8. What can actually be proved, and what cannot

**Decision**: state the gap rather than paper over it.

There is **no JavaScript test runner in this repository**. `web/` has
`scripts/check-format.ts`, a hand-rolled assertion file whose own header says
"There is no test runner in this app yet." CI runs `pytest`, `pyflakes`, a smoke
boot, and `tsc -b --force` for `web/` — and **nothing at all for `mobile/`**. The
fake app has never been typechecked in CI.

What this feature can prove automatically:

| Gate | Proves |
|---|---|
| `tsc -b --force` in `mobile/` (new CI job) | Every copied page compiles against the phone's vocabulary — a missing or wrong-shaped component is caught |
| `tools/check_parity.py` (new) | The 7,952 verbatim lines are identical in both apps |
| The fixture checker (new) | No fixture module exists and nothing imports one |
| `npm run check:format` in `mobile/` | The phone renders times, dates and percentages identically — it inherits the console's format assertions **because parity guarantees the same file** |

What it cannot: that a screen looks right, that a tap target is reachable
one-handed, that Arabic reads naturally. Those are confirmed by eye, on a phone,
by Mohamed — and `quickstart.md` lists exactly what to look at.

**Not proposed**: adding Vitest or Playwright. It would be a bigger change than
the feature and belongs in its own decision.
