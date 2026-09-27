# Feature Specification: The website in its new design, on PC and phone, in English and Arabic

**Feature Branch**: `Fo2sh` (spec directory `019-website-v3`)
**Created**: 27 September 2026
**Status**: Draft
**Input**: User description: "it's an enhancing spec in the website in both pc and mobile sides, I updated the design of the website in "Visionguard website full design" folder, I updated in the web view and in the mobile web view you should full implement it as it's" — then: "use the latest designs made".

**The design** (folder `design/Visionguard website full design/`):

| Screen | English | Arabic |
|---|---|---|
| PC | `VisionGuard Website v3.dc.html` | `VisionGuard Website v3 AR.dc.html` |
| Phone | `VisionGuard Mobile.dc.html` | `VisionGuard Mobile AR.dc.html` |

The older `VisionGuard Website v2.dc.html` and `VisionGuard Website.dc.html` in the same
folder are not built.

**Settled with Mohamed on 27 Sep 2026**:
1. Use the **design's words exactly**, including the sentences that were rewritten this
   morning (see the Constitution check).
2. Build **English and Arabic** now. The العربية switch works.
3. About us, Security and Help centre get the **new look and an Arabic version**. Their
   English words stay as they are.
4. The **phone design is for phones only**. Tablets and anything wider get the PC design.

## Why this feature

The website at www.vision-guard.org is built from the v2 design. Mohamed has redesigned
it: new fonts, a new hero with a phone showing the product, a separate layout made for
phones with its own menu, and a full Arabic version. Today a visitor sees the old look,
a phone visitor sees a squeezed version of the PC page, and an Arabic reader has nothing
in their language. This feature makes the site the new design, on both screens, in both
languages.

## User Scenarios & Testing

### Primary story

A school manager in Cairo opens the website on a laptop. They see the new design: a
centred menu, a العربية switch and a "Contact us" button at the top; a hero whose
question box types example questions next to a phone showing a live camera and floating
cards around it. They click العربية and the same page opens in Arabic, reading right to
left, moving the same way. Later they open the site on their phone. They get the phone
design: a menu button that opens a full-screen list of sections, a compact hero with the
phone picture on the first screen, and every section laid out for a thumb. They send a
message from the Arabic contact form, and it reaches the sales inbox.

**Acceptance scenarios**

1. **Given** a PC browser 1024 pixels wide or more, **When** the English home page
   loads, **Then** it matches `Website v3`: every section in order, with the design's
   words, colours, fonts, spacing, pictures and animations.
2. **Given** the same PC, **When** the visitor clicks العربية, **Then** the Arabic home
   page opens, matching `Website v3 AR`, laid out right to left. Its English switch
   returns to the English page.
3. **Given** a phone (360 to 430 pixels wide), **When** the home page loads, **Then** it
   matches `Mobile` (or `Mobile AR` in Arabic), not a squeezed PC page.
4. **Given** the phone design, **When** the visitor taps the menu button, **Then** the
   full-screen menu opens with its numbered section links, "Talk to our team" and the
   language switch. **When** they tap a section, **Then** the menu closes and the page
   scrolls to that section with its heading visible.
5. **Given** a tablet (768 pixels wide, upright), **When** the page loads, **Then** it
   shows the PC design, with nothing overlapping and no sideways scrolling.
6. **Given** About us, Security or Help centre, **When** it opens, **Then** it has the
   new header, fonts and footer, and its language switch opens the same page in the
   other language.
7. **Given** the contact form or the Help centre question form, in either language,
   **When** it is filled and sent, **Then** it delivers exactly as today (sales@ and
   support@ respectively), and every message it shows (errors, "not sent", thank-you)
   is in the page's language.

### Edge cases

- **The message cannot be delivered**: same as today. The form keeps what was typed,
  says it was not sent, and gives the email and phone to use instead, in the page's
  language. It never shows the thank-you.
- **Reduced motion is asked for**: nothing moves and everything is shown, on every page
  and in both languages.
- **No scroll-linked effects in the browser**: sections still appear; nothing stays
  hidden.
- **The design's fonts do not load**: text falls back to a readable font. Arabic falls
  back to a font that has Arabic letters.
- **The phone menu is open and the visitor rotates the phone or widens the window past
  the phone width**: the menu closes and the PC design shows correctly.
- **A link in the design goes nowhere** (`#`): it is marked "Soon" as today, in both
  languages, and does nothing.

## Requirements

Numbering continues spec 017 (working label P14, the website). Spec 017's requirements
still hold unless this list replaces them.

**Replaced from spec 017**

- **P14-FR-018** (replaces 001 and 005): The home page MUST reproduce `Website v3` on
  PC and `Mobile` on phones: sections, order, words, colours, fonts, spacing, logo,
  pictures, hover effects and every animation each design has.
- **P14-FR-019** (replaces 016): Footer items MUST go where they can. How it works,
  Tools, Honest by design, Mobile app, Contact sales and the logo scroll to their
  section. About us, Security and Help centre open their pages. The language switch
  works. Only these stay marked "Soon" and do nothing: the seven Solutions links,
  Careers, Partners, Privacy policy, Terms of service, LinkedIn, X, YouTube, and the
  "privacy policy" link in the form's note.

**Two languages**

- **P14-FR-020**: Every page MUST exist in English and Arabic. The Arabic home page
  MUST match the `AR` designs; the Arabic pages read right to left.
- **P14-FR-021**: The language switch MUST open the same page in the other language, in
  one tap or click, on every page and on both screen sizes.
- **P14-FR-022**: Every text the site shows by itself MUST be in the page's language:
  form errors, "sending", "not sent", the thank-you, the "Soon" marks and the browser
  tab title.
- **P14-FR-023**: The Arabic About us, Security and Help centre MUST say the same facts
  as their English pages, no more and no fewer. Mohamed reads them before they are
  published.

**Phone and PC**

- **P14-FR-024**: Phone widths MUST get the phone design; tablets and wider MUST get the
  PC design. No width from 360 pixels up may scroll sideways.
- **P14-FR-025**: On phones, the menu button MUST open and close the full-screen menu
  as the design animates it. Tapping any link inside it MUST close it.
- **P14-FR-026**: About us, Security and Help centre MUST take the new look on both
  screen sizes: the new header (with the phone menu on phones), fonts and footer.

**Kept from today, not the design**

- **P14-FR-027**: Contact details MUST stay the real ones: sales@vision-guard.org, and
  +20 100 253 5081 for Call us and WhatsApp. The design's placeholders
  (sales@visionguard.ai, +20 2 0000 0000, a WhatsApp link to nowhere) MUST NOT appear.
- **P14-FR-028**: Both forms MUST keep delivering as today, from both languages.

## Success Criteria

- **SC-001**: Side by side with the four designs (PC at 1440 pixels, phone at 390), a
  reviewer finds every section, heading, card, word and animation. None is missing and
  none is added, apart from what this spec lists.
- **SC-002**: At 360, 390, 430, 768, 1024 and 1440 pixels, in both languages, no page
  scrolls sideways and nothing overlaps.
- **SC-003**: From any page, in either language, the other language is one tap away and
  lands on the same page.
- **SC-004**: On a phone, any section is two taps away: the menu, then the link.
- **SC-005**: The header and the typing hero are on screen within 2 seconds on an
  ordinary home connection, on PC and phone.
- **SC-006**: A test message from the Arabic contact form reaches sales@vision-guard.org
  with every field correct (sent only with Mohamed's OK, as in spec 017).
- **SC-007**: With reduced motion switched on, nothing moves on any page and everything
  can be read.
- **SC-008**: Every clickable thing, in both languages and on both screens, either does
  what it says or is marked "Soon".

## Out of scope

- Pages with no design or no content yet: the seven Solutions, Careers, Partners, and
  Privacy policy and Terms of service (their drafts still wait for Mohamed).
- Social media accounts.
- A third layout for tablets. They get the PC design.
- Any change to the engine, the console or the phone app.
- Replacing the drawn product scenes with live data.
- Visitor analytics and cookies.

## Constitution check

The constitution governs the product. The website shares nothing with it, so it cannot
break the product (spec 017, P14-FR-002). Its honesty rules are where this spec needs
care:

- **Words (III, "never show anything untrue"; and "claims of scale MUST be backed by
  measurements")**: at Mohamed's choice on 27 Sep 2026, the site uses the design's
  words. That brings back the 19 sentences that were checked and rewritten earlier the
  same day (`specs/017-public-website/claims.md`): 8 were found untrue and 11
  overclaimed. Examples: "208 cameras on a single site" (a plan, not measured), "every
  detection is checked by a person before anyone is alerted" (the alert goes out first,
  marked unconfirmed), "Right to be forgotten — every trace goes with them" (past
  sightings are kept), "Full audit trail" (the audit is lost on restart), "Amber —
  waiting for human review" (amber means not identified). This is recorded as his
  decision, not as checked facts.
- **The site will disagree with itself**: the Security page states the real limits (for
  example, the audit is lost on restart), while the home page's Trust section says
  otherwise. Security's words stay as they are (decision 3).
- **Consequence for the records**: `STATUS.md` and `claims.md` today say every claim on
  the site was checked. Once this ships they MUST say the home page uses the design's
  words and that those 19 sentences are not backed.
- **Nothing fake in the wiring**: forms still show the thank-you only when delivery is
  confirmed; links that cannot work are marked "Soon"; the "All systems operational"
  pill stays gone (the new design dropped it too).
- **Privacy (IV)**: unchanged. Form fields go to the two inboxes and nowhere else.

## Assumptions

- "Phones" means widths below about 600 pixels; the exact point is set in the plan,
  where the PC design stops fitting. The acceptance checks use 360–430 (phone) and 768+
  (PC).
- The PC design is drawn at full width. Between 600 and 1024 pixels it folds the way
  the design already folds (for example, the hero's floating cards hide below 1080
  pixels), plus whatever the plan finds is needed to stop overlap. That is the only
  place the PC layout may differ from the drawing.
- The Arabic words on the home page are the design's Arabic, used as they are. The
  Arabic for About us, Security, Help centre, form messages and "Soon" marks is written
  new, in the same style, and checked by Mohamed.
- Each language has its own web address, so a visitor can share or bookmark the Arabic
  page. The language is chosen by the switch, not guessed from the browser.
- The phone picture and icon come from the design folder's `assets/`.
- Publishing to www.vision-guard.org stays the existing copy-and-push step, done once
  Mohamed has looked at the result.
