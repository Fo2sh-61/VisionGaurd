# Contract: choosing a language

Three wire changes and one endpoint.

---

## `Account.language`

`engine/vg/api/schemas.py`, `class Account` (line ~1408).

```
class Account(Wire):
    id: str
    name: str
    email: str
    role: str
    initials: str
    language: Literal["en", "ar"] = "en"      # NEW
```

Reaches the console through `LoginResult.user` and whatever serves the current
account. `web/src/app/AuthContext.tsx`'s `Account` interface gains the same
field, and `LanguageContext` reads it.

The class docstring already says *"No password hash, and no permissions list.
The console asks the server what it may do rather than deciding from a role it
holds locally."* Language does not weaken that: it is a preference, and
`auth/deps.py` must never read it. A language that could change what a caller
may do would be a second permission system hiding behind a display setting.

---

## `POST /auth/language`

The only new endpoint.

| | |
|---|---|
| Request | `{ "language": "ar" }` |
| Response | `200` with the updated `Account` |
| Auth | any signed-in user, for **their own** account only |
| Errors | `422` `note(language.unknown, {value})` for anything outside the enum |

No `user_id` parameter. A caller changes their own language and nobody else's;
an administrator who wants to change a colleague's language asks the colleague.
That keeps this endpoint out of `ADMIN_PREFIXES` entirely and out of the
permission surface.

**Not audited.** The audit trail records decisions about people and evidence —
a track search, a dismissed alert, a deleted pass. A display preference is not
one of those, and filling the trail with them makes the entries that matter
harder to find. (`P11-FR-019` covers exports, which *are* audited, and is
unaffected.)

---

## `SiteInfo.digits`

`engine/vg/api/schemas.py`, `class SiteInfo` (line ~966).

```
digits: Literal["western", "arabic"] = "western"     # NEW
```

Site-wide typography, from site configuration. It selects the `Intl` numbering
extension — `-u-nu-latn` or `-u-nu-arab` — and nothing else. It does not change
what any number *means*, and it must not be applied to:

- **plate text** — `VehiclePass.plate_display` is already "as it appears on the
  car" and has its own digit handling in `engine/vg/platetext.py`. Running it
  through `Intl` a second time would transliterate a plate that was already
  correct.
- **identifiers** — camera ids, person ids, tokens.

**Unverified**: `engine.yaml` has no site typography section today and the
config plumbing was not read at plan time. See `context.md` §5.

---

## Where the language comes from, in order

| Order | Source | When it applies |
|---|---|---|
| 1 | `Account.language` | signed in — the authority |
| 2 | `localStorage['vg.lang']` | the sign-in page, before any account exists (`P11-FR-016`) |
| 3 | `navigator.language` starts with `ar` | first visit on a new browser |
| 4 | `'en'` | otherwise |

Writing an account language also writes `localStorage`, so the next visit's
sign-in page opens in the right language before anyone types a password.

`localStorage` is used here and only here. `web/src/services/http.ts` explains
at line 37 why the session token is deliberately **not** in `localStorage`; a
display preference carries none of that risk, and `ThemeContext.tsx` already
sets the precedent with `vg.dark`.

---

## What the document element carries

```html
<html lang="ar" dir="rtl">
```

Set by `LanguageContext`, the same way `ThemeContext` sets `document.body`'s
`dark` class. `lang` matters for screen readers and for the browser's own text
handling; `dir` is what mirrors the layout.

**One element opts out**, and it is not negotiable: the `CameraFrame` picture
container is `dir="ltr"`. Overlay geometry is in physical `left`/`top`
percentages and must stay that way, so a box always sits over the thing it
describes (`P11-FR-009`).
