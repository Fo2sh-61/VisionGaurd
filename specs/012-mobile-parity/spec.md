# Feature Specification: The phone does everything the console does

**Feature Branch**: `012-mobile-parity`
**Created**: 3 September 2026
**Status**: Draft
**Input**: User description: "now what I need is to copy all what I made to the mobile app I need everything in the web app be in it just clone our work in it"

## Why this feature

The mobile app is entirely made up. Every number on it is a fixture, several are
regenerated at random on each visit, and any password signs you in as the same
person with full rights. A guard holding that phone is looking at a school that
does not exist, and cannot tell.

Meanwhile the console does all of it for real — attendance, counting, knives,
the gate, tracking, enrolment, camera setup, health, Ask — against live cameras
and a real sign-in.

Two things change. The phone stops inventing and starts showing what the engine
actually knows. And the person carrying it can act on what they see — confirm a
knife alert while standing in the corridor it was raised in, rather than walking
back to a desk. Today the walk back is the whole delay.

## User Scenarios & Testing

### Primary story

A guard on patrol unlocks their phone, signs in with their own account, and sees
what is happening on campus right now: who has not arrived, how full the
cafeteria is, whether anything needs their attention. An alert says a knife was
seen at Gate 3. They open it, watch the clip, decide it is a boy holding a ruler,
and press "False alarm" — recorded against their name, from where they are
standing. An administrator signing in on the same phone can also enrol a face,
add a camera, and change a setting, because their account is allowed to; a guard
opening those same screens is refused by the engine and told why.

**Acceptance scenarios**

1. **Given** a guard account, **When** they sign in on the phone, **Then** they
   see the same figures as the console showed at that moment, and no
   administrator-only action appears anywhere.
2. **Given** a knife entry waiting for a decision, **When** the guard presses
   "False alarm" on the phone, **Then** the entry is recorded against their
   account, the console shows the same decision, and the entry stays in history.
3. **Given** the engine is not running, **When** any screen is opened, **Then**
   it says the system could not be reached and gives the reason — and shows no
   figure at all, rather than a stale or invented one.
4. **Given** a camera with no signal, **When** its tile is shown, **Then** it
   reads NO SIGNAL instead of holding the last frame.
5. **Given** an administrator on the phone, **When** they enrol somebody using
   the phone's own camera, **Then** the same five-photo floor and quality scoring
   apply, and the person is recognised afterwards without a restart.
6. **Given** the language is switched to Arabic, **When** any screen is opened,
   **Then** the whole screen reads right-to-left in Arabic, including the tab bar
   and every date, count and label.
7. **Given** a guard opens an administrator-only screen by typing its address,
   **When** the screen loads, **Then** the engine refuses it and the phone says
   the account is not allowed — the refusal comes from the engine, not from the
   phone deciding.
8. **Given** the phone loses its network in the middle of an action, **When**
   the action fails, **Then** the phone says it did not go through and offers to
   try again — it never reports a save that did not happen.

### Edge cases

- A camera is offline, or its feature is switched off: the tile says which,
  plainly, and the rest of the screen keeps working.
- A subsystem is not running at all — this is a different answer from "nothing
  found", and reads differently.
- Nothing to show: "no passes yet today" and "0 passes today" are different
  sentences and both are different from "we do not know".
- A table with eight columns on a 375-pixel screen — it must be readable
  without scrolling sideways.
- A session expires or is revoked while the phone is in a pocket: the next
  screen sends the person back to sign in, and does not show what was on screen
  before.
- Arabic reverses the layout but never the plate digits or a person's name.
- Two people press "Confirm" on the same knife entry at once — the second is
  told it was already decided, and by whom.
- The phone is held in landscape.

## Requirements

- **P13-FR-001**: Every screen in the phone app MUST take its figures from the
  engine. No fixture, no placeholder, no random value may remain in the shipped
  app.
- **P13-FR-002**: Signing in MUST use a real account and password, checked by the
  engine. The phone MUST NOT offer a role picker and MUST NOT accept any
  password.
- **P13-FR-003**: The phone MUST reach every capability the console has:
  attendance, counting, restricted zones, knives, the vehicle gate, lost bag,
  track a person, people and their history and groups, enrolment, camera setup,
  system health, settings, user accounts, and Ask.
- **P13-FR-004**: Every action the console allows MUST work on the phone —
  including confirming or dismissing a knife entry, enrolling a face, removing a
  person, deleting a vehicle pass, importing and exporting the register, adding
  and editing cameras, changing settings, and managing accounts.
- **P13-FR-005**: What an account may do MUST be decided by the engine, exactly
  as it is for the console. Hiding a screen on the phone is a convenience, never
  the boundary.
- **P13-FR-006**: Every action that the console audits MUST be audited
  identically from the phone, written before the thing it records, and naming the
  signed-in account.
- **P13-FR-007**: The phone MUST keep its own shape — a bottom tab bar and
  screens sized for one hand. It MUST NOT be the desktop sidebar shrunk.
- **P13-FR-008**: Camera pictures on the phone MUST be live, and each feature
  MUST draw only its own overlay. A screen that must not name anybody MUST NOT
  show a recognition box.
- **P13-FR-009**: Face and clothing MUST stay visually distinct on the phone as
  they are on the console — green names a person, blue says only "same body",
  amber says unidentified.
- **P13-FR-010**: When something is unavailable the phone MUST say so with the
  reason, and MUST NOT substitute a number. A subsystem that failed to start MUST
  be visible on the phone, not only in a log.
- **P13-FR-011**: An action that fails MUST be reported as failed. The phone MUST
  NOT show a saved state it has not been told about.
- **P13-FR-012**: The phone MUST offer English and Arabic with the same wording
  source as the console, and MUST lay the whole screen out right-to-left in
  Arabic, tab bar included.
- **P13-FR-013**: No screen may require another feature to be switched on. A
  camera without the gate feature simply has no gate screen; it does not break
  attendance.
- **P13-FR-014**: The phone MUST NOT claim precision the engine lacks — no
  percentage without a capacity, no de-duplicated total where the engine sums
  across cameras.
- **P13-FR-015**: Users MUST be able to switch between light and dark, and the
  choice MUST survive closing the app.
- **P13-FR-016**: The phone MUST work on a screen 375 pixels wide without
  sideways scrolling on any screen.
- **P13-FR-017**: A change made on the phone MUST be visible on the console, and
  the reverse, without either being restarted.

## Success Criteria

- **SC-001**: Every one of the console's screens can be reached and used on the
  phone — checked by walking the list, with none missing and none read-only that
  is not read-only on the desk.
- **SC-002**: With the engine stopped, every screen says the system cannot be
  reached and shows no figure. Nobody can find a number anywhere in the app that
  did not come from the engine.
- **SC-003**: From an unlocked phone, a guard can open a waiting knife entry,
  watch the clip and record a decision in under 30 seconds.
- **SC-004**: A guard account never sees an administrator-only action, and never
  succeeds at one when it is reached by typing the address.
- **SC-005**: Every screen is readable and usable one-handed on a 375-pixel-wide
  phone, in both light and dark.
- **SC-006**: Switching to Arabic flips every screen right-to-left with no
  untranslated English left except names, plates and camera identifiers.
- **SC-007**: A decision recorded on the phone appears on the console within one
  refresh, named to the same account, and the reverse.

## Out of scope

- Push notifications and alert delivery — that stays P9, and nothing is sent to
  anybody from this feature.
- An app-store build. This stays a web app opened in the phone's browser.
- Working with no network. The phone shows what the engine says; with no engine
  it says so and stops.
- Any capability the console does not have. Parity is the ceiling as well as the
  floor — this feature adds nothing new to the product.
- Correcting the Arabic wording. It is still the same draft, unproofread, and
  stays dev-only on the phone exactly as on the console.

## Constitution check

- **No fake data** — this feature is mostly the deletion of fake data. The
  fixtures module goes; nothing replaces it.
- **Face vs clothing** — kept distinct in colour and meaning on every phone
  screen, same as the console.
- **Each feature draws its own overlay** — carried over; a phone screen showing
  bodies must not show names.
- **Honest degradation** — offline cameras, absent subsystems and empty results
  each read differently, and a failed action is never drawn as a success.
- **Server-side permissions** — the phone stores no role and decides nothing.
  Every refusal comes from the engine.
- **Audit before the act** — track searches, exports and deletions write their
  entry before returning, from the phone as from the desk.
- **Weapons wait for a human** — a decision on the phone is still a human
  decision, recorded against a named account, and history is never deleted.
- **Latency** — a phone on school Wi-Fi is slower than a desk. Live pictures must
  degrade in quality rather than in truth.

## Assumptions

- This supersedes the mobile half of P9 in `docs/PLAN.md`, which said the phone
  would be wired read-only. Mohamed asked for the phone to do everything, and
  confirmed it when the plan's position was put to him. Notifications stay in P9
  and are untouched here.
- The phone remains a separate app in `mobile/`, keeping its own shell, rather
  than the console becoming responsive. This was chosen over merging the two.
- All four screens that are awkward on a phone are included: enrolment, camera
  setup, track a person, and user accounts. Enrolment on a phone camera may in
  fact be better than on a laptop; that is worth measuring but not assumed here.
- The phone talks to the same engine on the same origin as the console, so a
  session works the same way and camera pictures carry the same credential.
- "Everything in the web app" means the product capabilities, not the desktop
  layout. Where a console screen is a wide table, the phone shows the same facts
  in a shape that fits a hand.
- Nothing about the engine changes. If a phone screen needs something the engine
  does not expose, that is a finding for planning, not a licence to invent it.
