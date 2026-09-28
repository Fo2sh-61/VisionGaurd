# Data model: the website in its new design

The website stores nothing. The "data" is the set of pages, what each is built from, and
the fixed list of places where the site differs from the design.

## 1. Pages

Eight pages, four in each language, plus three forwarding pages in each. Each holds the PC and phone copies of the header and
footer. The home pages hold the PC and phone copies of the whole page.

| Page | English | Arabic | Middle comes from | Header and footer come from |
|---|---|---|---|---|
| Home | `website/index.html` | `website/ar/index.html` | `Website v3` (+`AR`) and `Mobile` (+`AR`), whole | same (generated) |
| About us | `website/about.html` | `website/ar/about.html` | hand-written, `.pg-*` | stamped by the converter |
| Trust & privacy | `website/trust.html` | `website/ar/trust.html` | hand-written: Security, Privacy and Terms in short, one part each (`#security`, `#privacy`, `#terms`) | stamped |
| Help centre | `website/help.html` | `website/ar/help.html` | hand-written, with the question form | stamped |

Forwarding pages (28 Sep 2026, when Security, Privacy policy and Terms of service became one page): `security.html`, `privacy.html` and `terms.html` in each language send the visitor to the matching part of `trust.html`. They carry no header or footer and are not in the converter's `INNER` list. The footer's Trust column has two links, Trust & privacy and Help centre (site edit E5, `DROP`).

Shared files: `styles.css` (the site's own rules, always loaded), `design-pc.css`
(`media="(width >= 600px)"`), `design-phone.css` (`media="(width < 600px)"`),
`main.js`, `assets/`. Arabic pages link them with `../`.

**Rules**
- A page and its twin have the same file name. The language switch links one to the
  other.
- Home pages are fully generated. Editing them by hand is lost on the next build. The
  file's first comment says so.
- Inner pages are hand-written except between the `vg:header` and `vg:footer` markers.

## 2. The two copies on a page

| | PC copy | Phone copy |
|---|---|---|
| Wrapper | `<div class="vg-pc">` | `<div class="vg-ph">` |
| Shown at | 600 px and wider | below 600 px |
| Section ids | `top how tools honest mobile contact` | `m-top m-how m-tools m-honest m-mobile m-contact` |
| Stylesheet | `design-pc.css` | `design-phone.css` |
| Contact form | one | one (its own) |

## 3. Site edits: every place the site differs from the design

The converter applies these after writing out the design, in this order. Each one names
how many times it must match; any other count stops the build.

| # | Where | Design has | Site has | Why | Matches |
|---|---|---|---|---|---|
| E1 | all | `sales@visionguard.ai` | `sales@vision-guard.org` | P14-FR-027 | ≥1 |
| E2 | all | `tel:+20200000000` | `tel:+201002535081` | P14-FR-027 | ≥1 |
| E3 | all | shown number `+20 2 0000 0000` (as written in each design) | `+20 100 253 5081` | P14-FR-027 | ≥1 |
| E4 | contact | the WhatsApp card's `href="#"` | `https://wa.me/201002535081` (new tab) | P14-FR-013 | 1 |
| E5 | footer | `href="#"` on About us / من نحن, Security / الأمان, Help centre / مركز المساعدة | `about.html`, `security.html`, `help.html` | P14-FR-019 | 1 each |
| E6 | all | every other `<a href="#">…</a>` | `<span class="soon" aria-disabled="true">… <small>Soon</small></span>` (Arabic: `قريبًا`) | P14-FR-019 | ≥1 |
| E7 | switch | `VisionGuard%20Website%20v3%20AR.dc.html`, `…Mobile%20AR…`, and the English twins | the twin page (`ar/`, `../`, `ar/about.html`, …) | P14-FR-021 | ≥1 |
| E8 | wrapper | `overflow-x:hidden` on the outer `<div>` | `overflow-x:clip` | a sticky header dies inside `hidden` (017 R8) | 1 per copy |
| E9 | phone wrapper | `max-width:430px;margin:0 auto;…box-shadow:…` | full width, no side shadow | R7, Mohamed's "stretch" | 1 |
| E10 | phone CTA bar | `max-width:430px` | none | R7 | 1 |
| E11 | phone copy | `id="how"`, `href="#how"`, … | `id="m-how"`, `href="#m-how"`, … | R6 | all |
| E12 | form | fields without `name` | `name`, in order: `name email company phone site_type message` (exactly 6 fields) | the send path | 1 per form |
| E13 | form | no anti-spam field, no "not sent" block | `_honey` field; the "not sent" block with email and phone, in the page's language | P14-FR-011/014 | 1 per form |
| E14 | thank-you | no way back to the form | "Send another" button (built 27 Sep, commit c0b1720) | keeps today's behaviour | 1 per form |
| E15 | form | no `action` | `action="https://formsubmit.co/sales@vision-guard.org" method="POST"` | still sends if the script fails | 1 per form |
| E16 | Arabic pages | `./assets/` | `../assets/` | Arabic pages sit one folder down | ≥1 |
| E17 | any box holding a scroll effect | `overflow:hidden` on a box that contains `data-reveal`, `data-count`, `data-line`, `data-tilt` or `data-par` | `overflow:clip` | a hidden-overflow box is a scroll container, so every scroll-linked effect inside it measured against a box that never scrolls and sat frozen (28 Sep: the counting numbers, the Honest zoom, the phone drift, the card lines — 23 of 45 effects on PC). Clip cuts the same way; layout measured identical | 13 per PC copy, 5 per phone copy |
| E18 | home page claims | the 18 sentences the 27 Sep check found untrue or overclaiming (017 `claims.md`), in each design's language | their checked wording; the Arabic is Claude's draft (`arabic-review.md`, last section) | Mohamed, 28 Sep 2026, after a council review named them the first thing to fix | 1 per copy (the hero's "Next camera" / "الكاميرا التالية": PC only) |
| E19 | stats strip, console pictures | `208` — "cameras on a single site"; "All 208 cameras up", "across 208 cameras" (Arabic: "208 كاميرا تعمل", "عبر 208 كاميرا") | the design's count-up, to `500` with a `+` (`data-plus`, `styles.css`), over "cameras — the scale we're building for" (Arabic: "كاميرا — الحجم الذي نسعى إليه"); the pictures read "All cameras up", "across all cameras" | Mohamed, 28 Sep 2026: 500+ as a goal, not a claim. Nothing is signed and nothing that size has run | 1 per copy each |

**After the edits, the output must contain none of**: `visionguard.ai`, `0000 0000`,
`.dc.html`, `href="#"`, `{{`, `<sc-`, `style-hover`, `style-focus`, or an `on…=`
attribute. The converter checks this and stops if any is found.

## 4. Behaviour hooks

Named after the design's own handlers. See `contracts/page-hooks.md`.

## 5. Texts the site adds

The design shows none of these. Each exists in both languages.

| Text | English | Arabic | Lives in |
|---|---|---|---|
| Soon tag | Soon | قريبًا | converter (E6) |
| Sending | Sending… | جارٍ الإرسال… | `main.js` |
| Empty required field | Please fill in this field. | من فضلك املأ هذا الحقل. | `main.js` |
| Bad email | Please enter an email address, like name@company.com. | من فضلك اكتب بريدًا إلكترونيًا صحيحًا، مثل name@company.com. | `main.js` |
| Not sent (contact) | Your message was not sent. Please email sales@vision-guard.org or call +20 100 253 5081. | لم تُرسَل رسالتك. من فضلك راسلنا على sales@vision-guard.org أو اتصل على ‎+20 100 253 5081. | converter (E13) |
| Send another | Send another message | أرسل رسالة أخرى | converter (E14) |
| Tab titles | as today | «من نحن — VisionGuard» and so on | page `<head>` |

Mohamed reads the Arabic ones with the Arabic inner pages (P14-FR-023).

## 6. The contact message

The same as spec 017's `data-model.md` and `contracts/contact-form.md`: fields, send
states (idle → sending → sent | not sent) and the FormSubmit answer. Nothing changes.
Phone numbers inside Arabic text are wrapped left-to-right so the digits keep their
order.
