# Feature Specification: The phone looks like the console, fits one hand, and keeps in step with it

**Feature Branch**: `014-mobile-ui-parity`
**Created**: 11 September 2026
**Status**: Superseded on 17 September 2026 by `specs/015-phone-first-redesign` (phone-first design; never built)
**Input**: User description: "I see the mobile app has many alignment and UI issues u can use the recently installed front end plugin to enhance this UI/UX to be close to the web app. also I see a lot of un-similarities between the 2 apps I need them deliver same functionality even if they don't have the exact same shape"

## Why this feature

The phone app has shown real figures since 3 September, but nobody has looked at
it on a phone since, and it shows. It displays the console's screens unchanged
and squeezes them to fit. Every table folds into a bold line over a grey line of
values separated by dots, with its buttons and badges mixed into the grey line.
Other layouts wrap unevenly.

It also lacks what the console gives you on every screen: the date, how many
cameras are up or that the engine cannot be reached, and who is signed in.
Inside a tool there is no way back. And it has already fallen behind: the
phone's System Health still shows a percentage of the graphics card that the
console stopped showing on 4 September, because the engine never measured it.
A guard cannot trust a screen that looks broken, or act quickly when the buttons
are buried in a line of text.

After this change, the phone looks like the console and is laid out for one hand
on a 360-pixel screen. It offers every fact and action the console does, easy to
reach, and the two cannot quietly drift apart again. The console itself does not
change.

## User Scenarios & Testing

### Primary story

A guard on patrol opens the phone. The top of every screen shows what the
console always shows: the school, today's date, "All 12 cameras up" (or "Engine
unreachable" in the console's warning colour), and their own name. They open
Knife alerts from the Tools tab. The entry, its clip and the two decision buttons
fit the screen, with nothing to zoom and nothing sliding sideways, and the
buttons are full-size and set apart from the text. When they are done, the back
control at the top returns them to where they were. Later an administrator opens
the vehicle register on the same phone. Each row reads like a small card: the
plate, the name and the status, each saying what it is, with its actions as real
buttons. On the desk, the console looks and works exactly as it did.

**Acceptance scenarios**

1. **Given** any signed-in phone screen, **When** it opens, **Then** it shows the
   school, the date, the camera status in the console's words and colours
   (checking, all up, some up, or engine unreachable), and who is signed in.
2. **Given** a screen that is a table on the console, **When** it is shown on a
   phone 360 pixels wide, **Then** every column the console shows is there, each
   value says what it is, badges look like badges, actions are proper buttons,
   and nothing scrolls sideways.
3. **Given** a screen below the top of a tab (a tool, a person's history, a
   group, enrolment, Settings, Accounts), **When** the back control at the top is
   pressed, **Then** the phone returns to the screen it came from.
4. **Given** the same screen open on the console and on the phone, **When** they
   are compared side by side, **Then** the colours, typefaces, badges, buttons and
   wording are the same, and only the arrangement differs.
5. **Given** a control the console disables and explains only on hover, **When**
   it is shown on the phone, **Then** the reason is on the screen or one tap away.
6. **Given** a screen the two apps share, **When** it changes, **Then** both apps
   get the change in the same release, or the release is refused while they
   differ.
7. **Given** the console after this work, **When** each screen is compared with
   how it looked before, at desktop width, **Then** nothing looks or behaves
   differently.
8. **Given** Arabic or the dark theme, **When** any phone screen is opened,
   **Then** the new status line, the back control and every phone layout mirror
   or recolour with the rest of the screen.

### Edge cases

- The engine stops while the phone is open. Within 30 seconds the status line says
  "Engine unreachable" in the console's words, and it never shows a zero that
  reads as every camera being down. Before the first answer arrives, it says it
  is checking.
- A long name, plate, camera name or stream address on a 360-pixel screen wraps,
  or shortens with the full value one tap away. It never pushes the screen
  sideways.
- A screen opened with nothing before it, such as after the browser reloads a
  discarded tab: the back control goes to the top of the tab the screen belongs
  to.
- The on-screen keyboard is open on a form (sign-in, Ask, a plate, a camera
  address). The field being typed in and its button stay visible.
- The phone is turned sideways. Every screen stays usable, and the status line
  and tab bar do not take over the screen.
- A notch or a home indicator never covers anything that must be read or pressed.
- A "demo data", "could not load" or "not running" notice must stay in view in
  every new layout. A notice squeezed off the screen is a notice removed.
- The console's sidebar always says "Campus is calm — Nothing urgent right now",
  whatever is happening. The phone must not copy that line.

## Requirements

Numbering continues P13 after `011` and `012`, which used 001–028.

**Look**

- **P13-FR-029**: The phone MUST use the console's visual language: the same
  colours, typefaces, card, badge, button, form and notice styles, and the same
  wording. The arrangement may differ for a narrow screen; the style may not.
- **P13-FR-030**: Every screen MUST keep consistent margins and spacing. Nothing
  may overlap or stick out of its card, and things that belong together, such as
  a label and its value or a set of buttons, MUST line up.

**Fit**

- **P13-FR-031**: Every screen MUST work on a phone 360 pixels wide with no
  sideways scrolling and no zooming, in both languages and both themes, held
  upright or sideways.
- **P13-FR-032**: Every control pressed with a finger MUST be at least 44 pixels
  in each direction, and far enough from its neighbours that the wrong one is not
  pressed.
- **P13-FR-033**: Tables MUST take a phone shape that keeps every fact the
  console's table shows. With the column headings gone, each value MUST still say
  what it is wherever the bare value would be ambiguous. Actions MUST appear as
  buttons, never as text inside a line of values. A row with more detail than
  fits MAY open it on tap, but nothing may be dropped.
- **P13-FR-034**: The screens where arrangement matters most MUST put their main
  job on screen without scrolling past it. That means the knife alert's clip and
  its two decision buttons, the camera channel list, the vehicle register and
  movements, and System Health's per-worker figures, where frames deliberately
  skipped stay separate from frames dropped.

**Same functionality**

- **P13-FR-035**: Every signed-in phone screen MUST show what the console shows
  on every screen: the school's name, the date, the camera status in the same
  states and wording (checking, all up, some up, engine unreachable), and who is
  signed in, with their role.
- **P13-FR-036**: Every screen below the top of a tab MUST have a visible back
  control. It MUST return to the previous screen, or to the top of the tab when
  there is none, and MUST read in the account's language and point the way that
  language reads.
- **P13-FR-037**: Anything the console explains only on hover, such as why a
  control is disabled or that a figure is demo data, MUST be on the screen or one
  tap away on the phone.
- **P13-FR-038**: Every fact and action on a console screen MUST be on the
  matching phone screen, in its current version. System Health MUST be brought
  level with the console's as part of this work.
- **P13-FR-039**: A screen the two apps share MUST be the same screen in both.
  A release in which a shared screen differs between the two apps MUST be
  refused.
- **P13-FR-040**: The console MUST look and behave exactly as it does today at
  desktop widths. Any shared screen changed for the phone MUST be re-checked on
  the console.

**Honesty**

- **P13-FR-041**: The phone MUST NOT show any status that does not come from the
  engine. The console's permanent "Campus is calm" line MUST NOT be copied.

## Success Criteria

- **SC-001**: On a phone 360 pixels wide, all 16 of the console's screens plus
  Tools and Account can be used with no zooming and no sideways scrolling, in
  English and Arabic, light and dark. Checked by walking the list: on no screen
  does anything overlap, stick out of its card, or sit out of line with its
  neighbours.
- **SC-002**: Side by side with the console, someone who knows the console
  recognises every element on every phone screen, with the same colours, badges,
  buttons and words, and never has to ask what something is.
- **SC-003**: Every control pressed with a finger measures at least 44 × 44
  pixels, and none fails the check.
- **SC-004**: With the engine stopped, every phone screen reads "Engine
  unreachable" within 30 seconds, as the console does.
- **SC-005**: From any screen below the top of a tab, one press of the back
  control returns to the screen before it.
- **SC-006**: A guard can open a waiting knife alert from Home, watch the clip
  and record a decision in under 30 seconds, without scrolling past the clip to
  find the buttons.
- **SC-007**: At release, no screen the two apps share differs between them, and
  a deliberate difference planted in one shared screen stops the release.
- **SC-008**: Compared screen by screen at desktop width, the console shows no
  difference before and after this work.

## Out of scope

- A new visual style for either app. The look is the console's; Mohamed chose
  that over a refresh.
- Any change to what the console looks like or does.
- New capabilities. Parity is the ceiling as well as the floor.
- A tablet-specific layout, an app-store build, working with no network, and
  notifications (P9, spec `013`).
- Proofreading the Arabic. It stays the same dev-only draft.
- Correcting the console's own "Campus is calm" line. That is its own piece of
  work; this spec only keeps it off the phone.

## Constitution check

- **Never show anything untrue.** The status line comes from the engine and has
  honest "checking" and "unreachable" states. The console's permanent "Campus is
  calm" line is not copied. Demo, error and not-running notices stay in view in
  every new layout.
- **Face vs clothing.** The three overlay colours keep their meanings: green
  names a person, blue says only "same body", amber is unidentified. No layout
  merges or recolours them.
- **Each feature draws its own overlay.** A layout change never changes which
  boxes a screen draws. Screens that must not name anybody still do not.
- **No false precision.** Layouts keep "no capacity set, no percentage" and the
  note that counting adds up across cameras. The phone breaks this rule today:
  its System Health still shows the graphics-card percentage the console
  withdrew on 4 September. Bringing it level removes that figure.
- **A failed subsystem says so in the UI.** A notice pushed off the screen counts
  as removed, so it must stay in view.
- **Server-side permissions.** Hiding an administrator's action on the phone
  stays a courtesy; the engine still decides.
- **Latency.** The status line adds no load on the engine beyond what the
  console's top bar already costs. The phone already asks for the same figures.

## Assumptions

- Mohamed's answers on 11 Sep 2026:
  - All four differences are confirmed: no status bar, squashed tables, no back
    control in a tool, and System Health out of date.
  - The phone takes the console's look, not a new one.
  - Shared screens may change, as long as the console looks and works exactly as
    it does now.
  - The narrowest phone is 360 px, stricter than 012's 375 px.
- The front-end design plugin installed on 11 Sep (`frontend-design`) is used for
  quality: alignment, spacing, touch sizes, and checking its own work by
  screenshot. "Same look as the console" overrides its usual push toward a new,
  distinctive style.
- This absorbs the 12 tasks `012-mobile-parity` left undone, and they are ticked
  off against this spec, not 012:
  - the phone arrangements of the knife alert, the vehicle tables, the camera
    channel list and System Health's workers
  - every by-eye check
- The phone stays a separate app with its own five tabs, as chosen in 012. This
  spec does not merge the two apps.
- "The console stays the same" means what a person sees and does at desktop
  width. Changes underneath that leave every screen identical are allowed.
- The date on the status line is the school's date and time as the engine
  reports it, exactly as on the console, not the phone's own clock.
- The existing check that the shared screens match does catch today's System
  Health difference. On this machine, though, it stopped with an error while
  printing that difference, so planning should not assume the check is reliable
  yet.
- Every acceptance check here is by eye on a signed-in phone screen. Each one
  needs either a real phone in Mohamed's hand or a sign-in Claude is allowed to
  use.
