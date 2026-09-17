# Feature Specification: The phone is built for a phone, and still does everything the console does

**Feature Branch**: `015-phone-first-redesign` (work lands on `Fo2sh`)
**Created**: 17 September 2026
**Status**: Draft
**Supersedes**: `specs/014-mobile-ui-parity` (planned, never built)
**Input**: User description: "the mobile app ui/ux design need a lot of enhancement, the web app is very good for me. I don't mind if the mobile differs a bit in the design but it should provides a perfect experience and satisfy the same functionality." Then, after approving the clickable design: "now implement what you made and insure that all is functioning honestly as the web app do. replace [SCHOOL NAME] with Vision Guard and its icon"

**Approved design**: the canvas "VisionGuard Mobile Redesign", 17 phone screens,
https://claude.ai/artifact/VXoNnkdpGzGnQaxhuGVYnb

## Why this feature

The phone shows the console's screens squeezed onto a narrow screen. Forms stack
into long columns of dropdowns, and a tool's result is below the fold. Buttons are
buried in lines of text, and grey text is hard to read. A tool has no way back,
there is no alert bell, and five tabs give System and Account the same weight as
the tools a guard needs.

Spec 014 planned to fix this by keeping the console's screens and rearranging them.
Mohamed chose differently on 17 September: the phone may look different, as long as
it is a good phone app and does everything the console does. He approved a
clickable design. This feature builds that design on real data. The console does
not change.

## User Scenarios & Testing

### Primary story

A guard opens the phone on patrol. The top shows the VisionGuard logo and name,
the camera status in the console's words, a bell with the number of new alerts,
and their initials. Home opens on what needs attention now. A waiting knife entry
comes first, with a large "Review now" button. Under it are today's figures, each
of which opens its tool, then a live camera. The guard taps "Review now", watches
the clip, and presses "Confirm knife" or "False alarm". Both are large buttons
directly under the clip. The back arrow returns to Home. Later an administrator
opens Tools, then Attendance. They pick the group and date from chips that open a
short list from the bottom of the screen, not from stacked dropdowns. The result is
on screen without scrolling past a form.

**Acceptance scenarios**

1. **Given** any signed-in screen at the top of a tab, **When** it opens, **Then**
   it shows the VisionGuard logo and name, the camera status in the console's
   states and words (checking, all up, some up, engine unreachable), the alert
   bell with its count, and who is signed in.
2. **Given** the phone, **When** the bottom tabs are read, **Then** they are
   Home, Cameras, Tools, People and More. System health, Settings and Accounts
   are reached from More, and Accounts appears only for an administrator.
3. **Given** a screen below the top of a tab, **When** the back arrow is pressed,
   **Then** the phone returns to the screen it came from, or to the top of that
   tab when there is none.
4. **Given** something the console lists as needing attention, **When** Home
   opens, **Then** it is first on the screen, and tapping it opens the exact item,
   as the console's bell does.
5. **Given** a tool that the console fills in with a form (group, date, place,
   time, period), **When** it opens on the phone, **Then** each choice is a chip
   that opens a list from the bottom of the screen, and the result is visible
   without scrolling past the form.
6. **Given** a waiting knife entry, **When** it is opened on a 360-pixel screen,
   **Then** the clip and both decision buttons are on screen together, and a
   decision is saved exactly as the console saves it.
7. **Given** any console screen, **When** its phone screen is compared with it,
   **Then** every fact and action the console offers is on the phone, one tap
   away at most, with the same wording.
8. **Given** a part of the approved design, **When** the engine does not already
   send the data it needs, **Then** that part is absent from the phone. It is
   never filled with a placeholder or an invented figure, and it is named in the
   final report.
9. **Given** Arabic or the light theme, **When** any phone screen is opened,
   **Then** the layout mirrors or recolours with it, including the top bar, the
   back arrow, the bottom sheets and the tabs.

### Edge cases

- **The engine stops.** Within 30 seconds the top bar says "Engine unreachable".
  Home shows no figure, not a zero. Before the first answer arrives it says it is
  checking.
- **Alerts are not running, or cannot be checked.** The bell says so in the
  console's words ("Alerts not running", "Could not check alerts"). It never
  shows a zero that reads as "all calm".
- **Nothing needs attention.** Home says so plainly. The console sidebar's
  permanent "Campus is calm" line is not copied.
- **A subsystem is off.** A tool whose subsystem is not running (knife detection,
  lost bag, no exit camera) shows the console's "Not running" or "Not available"
  notice at the top, in view. A notice pushed off the screen counts as removed.
- **Unknown versus zero.** A figure the engine cannot compute (cars inside with no
  exit camera, an area no camera counts, a capacity that is not set) shows a dash
  or "Not counted" with its reason, never 0 or a percentage.
- **A camera is offline.** Its tile says "No signal" with the time of its last
  picture. It is never shown as live.
- **Long values.** Long names, plates, camera names and stream addresses wrap or
  shorten with the full value one tap away. Nothing scrolls sideways.
- **The keyboard is open.** The field being typed in and its button stay visible.
- **Held sideways, or on a phone with a notch.** The top bar and tabs do not take
  over the screen, and nothing that must be read or pressed is covered.
- **Opened with no history.** A screen opened after a reload or from a link has a
  back arrow that goes to the top of its tab.
- **Not an administrator.** Administrator-only actions are hidden as a courtesy.
  The engine still decides, and a refusal is shown in plain words.

## Requirements

Numbering continues P13 after `014`, which used up to 041 but was never built.

**Frame and navigation**

- **P13-FR-042**: The phone MUST have five bottom tabs: Home, Cameras, Tools,
  People and More. More MUST hold System health, Settings, Accounts
  (administrators only), appearance and language, and sign out.
- **P13-FR-043**: Every screen at the top of a tab MUST show a top bar with the
  VisionGuard logo and name, the camera status in the console's states and words,
  the alert bell, and the signed-in person's initials, which open More.
- **P13-FR-044**: Every screen below the top of a tab MUST show a back arrow and
  the screen's title. The arrow MUST return to the previous screen, or to the top
  of the tab when there is none, and MUST point the way the account's language
  reads.
- **P13-FR-045**: The alert bell MUST behave as the console's does: the same
  items, the same count of what is new since the account last opened it, the same
  "not running" and "could not check" states, and each item MUST open the exact
  thing it is about.

**Screens**

- **P13-FR-046**: Home MUST put what needs attention first. Next come today's
  figures, each opening its tool, then a live camera. Every figure MUST come from
  the engine. A figure the engine does not already provide MUST be left out, not
  shown empty.
- **P13-FR-047**: Cameras MUST list every camera, grouped by area, with a filter
  for live and no-signal cameras. Opening a camera MUST show its live picture and
  let the viewer choose which feature's boxes are drawn, with only that feature's
  boxes on the picture.
- **P13-FR-048**: Tools MUST list the seven tools in the console's two groups,
  Ask and Watch. Each tool shows a one-line current state only where the engine
  already provides it.
- **P13-FR-049**: Each of the console's screens MUST have a phone screen offering
  every fact and action the console screen offers, at most one tap away. That
  covers Attendance, People counting, Lost bag, Track a person, Restricted zones,
  Knife detection, Vehicle gate, People, a group, a person's history, Enrol,
  System health, Settings, Accounts and Sign-in.
- **P13-FR-050**: Where the console asks for choices in a form, the phone MUST
  offer each choice as a chip that opens a list from the bottom of the screen. A
  result MUST appear above anything the viewer no longer needs to change.
- **P13-FR-051**: Where the console shows a table, the phone MUST show each row as
  a card that keeps every fact, labels any value that would be ambiguous on its
  own, and shows actions as real buttons.
- **P13-FR-052**: The knife review MUST show the clip and both decision buttons on
  one screen at 360 pixels wide, with the optional reason, and MUST keep every
  entry in history, including false alarms.

**Fit and legibility**

- **P13-FR-053**: Every screen MUST work at 360 pixels wide with no sideways
  scrolling and no zooming, in English and Arabic, light and dark, upright or
  sideways.
- **P13-FR-054**: Every control pressed with a finger MUST be at least 44 pixels
  in each direction.
- **P13-FR-055**: All text MUST reach a contrast of at least 4.5:1 against what it
  sits on (3:1 for text 24 pixels or larger), and no text may be smaller than 12
  pixels.
- **P13-FR-056**: The phone MUST use the console's colours, typeface, badge colours
  and wording. The arrangement is the phone's own.

**Honesty**

- **P13-FR-057**: Every value, status and notice on the phone MUST come from the
  engine, exactly as the console receives it. The phone MUST invent nothing. That
  means no placeholder figures, no example entries and no permanent "calm" line.
- **P13-FR-058**: Green, blue and amber MUST keep their meanings on every picture
  and badge: a face names a person, clothing only says "same body", and amber is
  unidentified. A screen that must not name anybody MUST NOT show recognition
  boxes.
- **P13-FR-059**: A part of the approved design that the engine cannot back with
  data it already sends MUST be left out, and MUST be listed in a gaps section of
  this feature's closing report.
- **P13-FR-060**: The console MUST look and behave exactly as it does today, and
  the files the two apps share MUST stay identical.

## Success Criteria

- **SC-001**: On a phone 360 pixels wide, every phone screen can be used with no
  zooming and no sideways scrolling, in English and Arabic, light and dark.
  Measured: the widest element on every screen fits inside the screen.
- **SC-002**: Every control pressed with a finger measures at least 44 × 44
  pixels. Measured on every screen, none fails.
- **SC-003**: No text on any screen measures below 4.5:1 contrast (3:1 at 24
  pixels or larger), or below 12 pixels in size.
- **SC-004**: A guard can go from opening the app to a recorded knife decision in
  under 30 seconds, without scrolling past the clip to find the buttons.
- **SC-005**: From Home, any of the seven tools is at most two taps away, and any
  alert opens its exact item in one tap.
- **SC-006**: With the engine stopped, every phone screen says so within 30
  seconds and shows no figure.
- **SC-007**: Side by side with the console, every figure on the phone matches it
  at the same moment, and walking each console screen finds no fact or action
  missing from the phone.
- **SC-008**: The console, compared screen by screen at desktop width, shows no
  difference before and after, and the shared-files check passes.
- **SC-009**: The closing report lists every part of the approved design that was
  left out, each with the reason.

## Out of scope

- Any change to the engine or its data. Parts it cannot back are left out and
  reported, not built.
- Any change to what the console looks like or does.
- Features the console does not have. The approved design is the ceiling, and the
  console's functions are the floor.
- A tablet layout, an app-store build, working offline, and push notifications.
- Proofreading the Arabic. New wording gets a draft Arabic line, like the rest.

## Constitution check

- **Never show anything untrue.** Every value and status comes from the engine.
  Placeholders from the design are not carried over. That covers the school-name
  placeholder, the example knife entry and any figure that exists only in the
  mockup. Parts the engine cannot back are left out and reported.
- **Face versus clothing.** The three colours keep their meanings. The design's
  "in view" list may only name a person the engine names by face, and a
  clothing-only match never carries a name.
- **Each feature draws its own overlay.** Choosing a feature on a camera shows
  only that feature's boxes. Attendance and other screens that must not name
  anybody keep that rule.
- **No false precision.** Counting keeps its "added across cameras, no
  de-duplication" note. With no capacity set there is no percentage, and an area
  no camera counts shows "Not counted", not zero.
- **Honest degradation.** "Not running", "Not available", "No signal" and "Engine
  unreachable" stay in view on every new layout.
- **Knife detections wait for a human.** Both decisions stay one tap each, and
  there is no delete.
- **Track searches.** Searches go through the same engine path as the console's,
  so the audit entry is written first.
- **Server-side permissions.** Hiding an administrator's action is a courtesy; the
  engine decides.

## Assumptions

- Mohamed's answers on 17 September 2026:
  - Phone-first design, not 014's rearranged console screens.
  - A clickable design first. It was approved with "nice work".
  - Home serves both guards and administrators: attention first, then an
    overview.
  - The tabs change to Home, Cameras, Tools, People and More.
  - Design parts the engine cannot back are left out, with no engine changes, and
    reported at the end.
  - The full Spec Kit loop is followed.
  - The earlier uncommitted work in the tree is finished and may be built on.
  - Commits go to `Fo2sh` in steps. Nothing is pushed.
- "Vision Guard and its icon" means the brand as the console's sidebar shows it:
  the VisionGuard logo mark beside the product name.
- The date and time come from the engine's site clock, as on the console, not
  from the phone's own clock.
- The phone stays a separate app from the console. The files that decide what is
  true (what the engine is asked, what comes back, and the words) stay shared
  and identical. New wording is added to both apps.
- The design's figures were taken from screenshots. Only the layout was
  approved, not the numbers.
- Screens the design did not draw (Enrol, a group, Accounts, Sign-in) follow the
  same parts and patterns as the drawn screens.
- By-eye checks use the temporary developer sign-in on the recorded clip. What
  only a real phone can confirm goes to Mohamed.
