# Feature Specification: The VisionGuard website, built from the approved design

**Feature Branch**: `Fo2sh` (spec directory `017-public-website`)
**Created**: 27 September 2026
**Status**: Draft
**Input**: User description: "I need to implement the given website design in "Visionguard website design" folder with the animated parts and I need it working as much fast as possible no problem if some options in footer not functioning yet the more important is to have website working with the animation and of course mandatory parts"

**Approved design**: `design/Visionguard website design/VisionGuard Website v2.dc.html`.
The older `VisionGuard Website.dc.html` is not built.

**Settled with Mohamed on 27 Sep 2026**: build v2. The contact form sends to
sales@vision-guard.org. Phone and WhatsApp are both +20 100 253 5081. The site stands
on its own, apart from the product.

## Why this feature

VisionGuard has no public website. Someone who runs an office, factory, warehouse,
hospital or mall has nowhere to see what the product does, or to get in touch. There
is an approved one-page design, full of motion. This feature turns it into a real
website that opens in any browser, moves the way the design moves, and has a contact
form whose messages really reach the sales inbox.

## User Scenarios & Testing

### Primary story

A facilities manager opens the website on a laptop. The header stays at the top as
they scroll, and a thin bar under it shows how far down the page they are. In the
hero, a question box types example questions in English, Arabic and Franco, one after
another, next to a tilted wall of four camera tiles with moving coloured boxes. As
they scroll, sections fade and rise into place, the numbers count up, the radar
sweeps, and two phones float. They click "Talk to our team" and land on the contact
form. They fill in their name, work email, company, type of site and camera count,
and press "Send message". A thank-you appears, and the sales inbox receives
everything they typed. Later they open the same page on their phone. Everything is
there in one column, with no sideways scrolling.

**Acceptance scenarios**

1. **Given** the site in a current desktop browser, **When** the page loads, **Then**
   every section of the design appears, in order: header, hero, numbers strip,
   site-types strip, How it works, Tools, Honest by design, On your phone, Trust,
   Contact and footer. Each has the design's words, colours and fonts.
2. **Given** the hero on screen, **When** the visitor watches it, **Then** the
   question box types and erases the design's seven example questions in turn. The
   language tag beside it changes with each one, and Arabic questions run right to
   left.
3. **Given** the visitor scrolls down, **When** each section comes into view,
   **Then** it plays the entrance the design gives it. The header turns solid and the
   progress bar fills.
4. **Given** a link to a section ("How it works", "Tools", "Honest by design",
   "Mobile", "Contact us", "Talk to our team", "See how it works"), **When** it is
   clicked, **Then** the page scrolls smoothly to that section, with its heading not
   hidden under the header.
5. **Given** the contact form with its required fields filled, **When** "Send
   message" is pressed, **Then** sales@vision-guard.org receives the message with
   every field, and only after that does the thank-you appear.
6. **Given** a required field left empty, or an email that is not an email, **When**
   "Send message" is pressed, **Then** nothing is sent and the field says what is
   wrong.
7. **Given** the three contact cards, **When** each is tapped, **Then** Email opens a
   new message to sales@vision-guard.org, Call us dials +20 100 253 5081, and
   WhatsApp opens a chat with +20 100 253 5081.
8. **Given** a phone 360 pixels wide, **When** the page is scrolled top to bottom,
   **Then** nothing runs off the side and there is no sideways scrolling.
9. **Given** a footer link that has no page yet, **When** the visitor looks at it,
   **Then** it is plainly marked as not available yet and does not pretend to go
   anywhere.

### Edge cases

- **The message cannot be delivered** (no connection, or the sending service is down
  or not set up yet): the form keeps what was typed and says plainly that the message
  was not sent. It shows the email address and phone number to use instead. It never
  shows the thank-you.
- **Send is pressed twice quickly**: one message arrives, not two.
- **The device asks for reduced motion**: nothing moves, and all content is shown.
- **The browser cannot run scroll-linked effects**: sections simply appear without
  their scroll entrance. Motion that does not depend on scrolling (typing, radar,
  strips, floating) still plays. Nothing stays hidden waiting for an effect that
  never runs.
- **The design's fonts do not load**: text falls back to a similar font and stays
  readable.
- **Automated spam**: basic protection that asks nothing extra of a real visitor.

## Requirements

Numbered P14. The website is not yet a phase in `docs/PLAN.md` (see Assumptions).

**The page**

- **P14-FR-001**: The website MUST reproduce the v2 design as one page: its sections
  in order, words, colours, fonts, spacing, logo and pictures. It changes only what
  this spec lists.
- **P14-FR-002**: The website MUST stand on its own. It opens and works without the
  VisionGuard engine, console or phone app, and can be put on any ordinary web host.
- **P14-FR-003**: The page MUST fit every width from a 360-pixel phone to a wide
  desktop without sideways scrolling, dropping to fewer columns as the design does.
- **P14-FR-004**: The browser tab MUST show the VisionGuard icon and the title
  "VisionGuard AI".

**Motion — every animation in the design**

- **P14-FR-005**: The page MUST play every animation in the design:

  | Section | Motion |
  |---|---|
  | Header | Stays at the top. Turns solid with a soft shadow once scrolling starts. A bar along its bottom fills as the page is read. |
  | Hero | Headline rises into focus; the second line shimmers green. Badge dot pulses. A soft glow breathes in the background and follows the mouse. The question box types and erases seven questions, with a blinking cursor and a changing language tag. Four camera tiles, each with a drifting coloured box and label, a passing scan light and a pulsing LIVE dot. The camera wall tilts flat as the page scrolls. The "Next camera" label floats. The "34 employees not yet arrived" note appears and fades in a loop. "Talk to our team" has a passing shine. |
  | Numbers strip | 208, 3 and 7 count up from zero when they come into view. |
  | Site types | The names slide sideways in an endless loop, fading at both edges. |
  | How it works | The dashed line moves and a light travels along it. Step numbers send out rings. Cards appear one after another and lift on hover. |
  | Tools | Cards appear one after another. On hover a card lifts, a glow appears in its corner and a green line sweeps along its bottom. |
  | Honest by design | The radar sweeps, ripples spread, and blips (Person, Vehicle, Zone clear) flash and fade. The text zooms into focus. Source cards slide right on hover. |
  | On your phone | Two phones float at different speeds and drift as the page scrolls; glare passes over their screens. Inside the right phone: the question types, the chips slide, the alert card's border pulses, the bell badge bounces, "People in view" changes and the counts count up. "Knife spotted" and "142 of 160 arrived" pop in and out. Each tile draws its top line and grows its dot on hover. |
  | Trust | A green light runs around the card's border. The activity log scrolls in an endless loop. Icons send out rings. Cards lift on hover. |
  | Contact | A soft light drifts and a thin ring turns behind the green panel. "Send message" has a passing shine. Fields glow green when chosen. Cards slide on hover. |
  | Footer | The glow breathes and the big "VisionGuard" word shimmers. |

- **P14-FR-006**: A scroll entrance MUST NOT leave content hidden. If the effect
  cannot run, the content is shown still.
- **P14-FR-007**: When the device asks for reduced motion, the page MUST stop all
  animation and still show everything.

**Links**

- **P14-FR-008**: Every link to a section of the page, in the header, hero and
  footer, MUST scroll smoothly to that section. The logo returns to the top.

**Contact**

- **P14-FR-009**: The form MUST ask for full name, work email and company (all
  required), phone (optional), type of site (Office, Factory, Warehouse & logistics,
  Hospital & healthcare, Retail & malls, Other), number of cameras (Under 25, 25–100,
  100–500, 500+; exactly one chosen, 25–100 to start) and a message.
- **P14-FR-010**: "Send message" with valid fields MUST deliver everything entered to
  sales@vision-guard.org. Pressing Reply in the inbox MUST answer the visitor.
- **P14-FR-011**: The thank-you MUST appear only once delivery is confirmed. On
  failure the form MUST keep what was typed, say the message was not sent, and show
  the email address and phone number to use instead.
- **P14-FR-012**: While sending, the button MUST show that it is working, and MUST
  NOT send the same message twice.
- **P14-FR-013**: The Email card MUST show sales@vision-guard.org and open a new
  message to it. The Call us card MUST show +20 100 253 5081 and dial it. The
  WhatsApp card MUST open a chat with +20 100 253 5081.
- **P14-FR-014**: The form MUST have basic protection against automated spam that
  asks nothing extra of a real visitor.

**Footer**

- **P14-FR-015**: Footer links to page sections (How it works, Tools, Honest by
  design, Mobile app, Contact sales, Contact us, the logo) MUST work.
- **P14-FR-016**: Items with nowhere to go yet MUST stay where the design puts them,
  be plainly marked as not available yet, and do nothing when clicked. They are: the
  five Solutions links, About us, Careers, Partners, Security, Privacy policy, Terms
  of service, Help centre, LinkedIn, X, YouTube, and the English / العربية switch.
  The "privacy policy" link in the form's note is treated the same way.
- **P14-FR-017**: The footer's green "All systems operational" pill MUST NOT be
  shown. Nothing on the website checks any system, so it would be untrue.

## Success Criteria

- **SC-001**: Compared side by side with the design at 1440 and 390 pixels wide, a
  reviewer finds every section, heading, card and animation from the design. None is
  missing.
- **SC-002**: The header and the typing hero are on screen within 2 seconds on an
  ordinary home connection.
- **SC-003**: Scrolling the whole page on an ordinary laptop and a mid-range phone
  shows no visible stutter.
- **SC-004**: Five test messages sent through the form all reach
  sales@vision-guard.org within one minute, with every field correct.
- **SC-005**: With delivery deliberately broken, five sends out of five say "not
  sent", and none shows the thank-you.
- **SC-006**: At 360 pixels wide, no part of the page needs sideways scrolling.
- **SC-007**: With reduced motion switched on in the device's settings, nothing on
  the page moves and all content can be read.
- **SC-008**: Every clickable thing on the page either does what it says or is
  plainly marked not available. No click silently goes nowhere.
- **SC-009**: The page works in current Chrome, Edge, Safari (Mac and iPhone) and
  Firefox.

## Out of scope

- The pages the footer points to: Solutions, About, Careers, Partners, Security,
  Privacy policy, Terms, Help centre.
- An Arabic version of the website. The switch is shown, marked not available.
- Social media accounts.
- Putting the site on the internet under a domain name. It is delivered ready to
  upload; publishing it is a separate step.
- The v1 design.
- Any change to the engine, the console or the phone app.
- Replacing the illustrated product scenes with live data.
- Visitor analytics and cookies.

## Constitution check

The constitution governs the product. The website is not part of it and shares
nothing with it, so it cannot break the product (P14-FR-002). Its honesty rules still
apply here:

- **Nothing untrue (III)**: the form never shows a thank-you it has not earned
  (P14-FR-011). Links that cannot work yet are marked, not dead (P14-FR-016; V says
  "remove or clearly disable"). The "All systems operational" pill is dropped
  (P14-FR-017).
- **Illustrations**: the camera wall, the phone screens, the activity log and their
  figures (Layla A., 34 employees, 142 of 160) are drawn pictures of the product, not
  anyone's live data. They are kept as the design draws them.
- **Claims the page makes** — kept as designed, but three do not match `STATUS.md`
  today, and Mohamed should confirm them before the site goes public:
  - "208 cameras on a single site" states a scale that is not measured yet. The
    208-camera plan waits on target hardware.
  - "Amber — waiting for human review". In the product, amber means an unidentified
    person (AGENTS.md rule 1).
  - "Arabic & English, full right-to-left layout". The product's Arabic is an
    unproofread draft that shows only in development.
- **Privacy (IV)**: the form collects a name, email, company and phone. They pass
  through the form-to-email helper to the sales inbox, and nowhere else. The website
  stores nothing and tracks nobody.

## Assumptions

- "Mandatory parts" means everything outside the footer: all sections, all
  animations, the section links and a contact form that really delivers. The footer's
  section links work too.
- A page on its own cannot send mail, so a free helper that turns a form into an
  email sits in the middle (chosen in the plan: FormSubmit, which needs no account).
  The very first message makes it email sales@vision-guard.org an "Activate" link,
  which Mohamed clicks once. Until then the form says the message was not sent and
  shows the email and phone instead, so the site can go up before that click.
- The email card changes from the design's sales@visionguard.ai to
  sales@vision-guard.org, to match the form. The phone shows as +20 100 253 5081.
  The hours "Sun – Thu, 9:00 – 18:00" and "within one business day" are kept as
  designed.
- Scroll entrances may be missing in a browser that lacks scroll-linked effects. The
  content still shows (P14-FR-006), and all other motion still plays.
- The phone picture (`assets/mobile-2.png`) and the icon (`assets/visionguard.ico`)
  from the design folder are the ones used.
- P14 is a working label. `docs/PLAN.md` has no website phase. Adding one is
  Mohamed's call.
