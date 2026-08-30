# Feature Specification: People page & enrolment — professional, live, and complete

**Feature Branch**: `002-people-enrolment-ux`
**Created**: 2026-08-21
**Status**: Draft
**Input**: User description: "Finish the people page. Enrolment: after typing the person's details the camera feed shows a static photo instead of a live stream; the face model already finds facial feature points — enrolment should look and feel like enrolling a face on a phone. The system needs a way to discard someone. The Enrol page has no back button. In the people list, 'Photo on file' and the '—' column are not understandable; a person cannot be clicked to see their history; a few more professional details would help, without adding personal data. Keep it simple — this is mostly reorganisation."

## Why this feature

Enrolment and the People page work, but they read like internal tools. The
enrolment "camera view" is a frozen snapshot, so the person being enrolled
cannot position themselves and the operator cannot tell the camera is even
live. The people list shows a permanently empty guardian column ("—") and a
"Photo on file" badge nobody understands, a person cannot be opened to see
their history, and once somebody is enrolled there is no way to ever remove
them — which for a system holding face data is not a missing nicety, it is a
privacy obligation.

## User Scenarios & Testing

### Primary story

An operator opens People, finds a person by name, and clicks the row to see
their history. Back on the page they press "Enrol a face", fill in the name,
and see a **live, moving** camera view with the detected face outlined and its
feature points drawn on it — the same feel as enrolling a face on a phone.
Guidance tells them what is still needed ("look straight", "turn slightly
left") as photos are captured. When a staff member leaves the school, an
administrator removes them from the system and they stop being recognised.

**Acceptance scenarios**

1. **Given** an enrolment in progress, **When** the person stands in front of
   the selected camera, **Then** the page shows a live moving view (not a
   frozen frame) with the detected face outlined and feature points visible,
   updating as they move.
2. **Given** photos being captured, **When** the operator looks at the page,
   **Then** it says in plain words what is still missing (how many photos, and
   what kind — e.g. a different angle), and when the set is good enough.
3. **Given** the People list, **When** the operator clicks a person's row,
   **Then** that person's history opens — for staff and visitors as well as
   students.
4. **Given** the People list, **When** the operator reads a row, **Then**
   every piece of information is self-explanatory: no bare "—", and the
   recognition state is worded so a non-technical reader understands it
   (whether the cameras can recognise this person, and from how many photos).
5. **Given** an administrator on a person's entry, **When** they remove that
   person and confirm, **Then** the person disappears from the directory, is
   never recognised again, and the action is recorded with who did it. A
   non-administrator does not get the option, and the server refuses them
   even if they craft the request by hand.
6. **Given** the Enrol page, **When** the operator wants to go back, **Then**
   a visible back control returns them to People — including mid-enrolment,
   in which case unsaved photos are discarded after a confirmation.

### Edge cases

- The selected camera is offline: the live view says NO SIGNAL plainly; the
  page never shows a stale frame as if it were live.
- No face is in front of the camera: the view shows no outline and the page
  says nobody is detected — that is information, not an error.
- Two faces in view: the page says so and asks for one person at a time,
  rather than silently picking one.
- Removing a person who is on screen right now: the name stops being drawn
  and no new recognitions are recorded from the next frame on.
- Face recognition subsystem is down: People still lists everyone (the
  directory is data, not inference), with the existing capability notice.

## Requirements

- **PPL-FR-001**: During enrolment the camera view MUST be live and moving,
  never a static frame presented as live.
- **PPL-FR-002**: The live view MUST outline the detected face and draw its
  facial feature points, updating continuously while the person moves.
- **PPL-FR-003**: The enrolment flow MUST guide the operator in plain words:
  what is still needed, when a photo is unusable and why, and when the set is
  complete. Capture stays a deliberate button press by the operator; the
  guidance and the live overlay provide the phone-style feel. (Owner decision
  2026-08-21 — automatic hands-free capture is explicitly not wanted now.)
- **PPL-FR-004**: The Enrol page MUST have a visible way back to People at
  every step; leaving mid-enrolment asks for confirmation and discards the
  staged photos.
- **PPL-FR-005**: An administrator MUST be able to remove a person from the
  system, with a confirmation step that states what removal means. Removal
  MUST be server-enforced admin-only and MUST be written to the audit trail.
  Removal covers the person's face data and directory entry (owner decision
  2026-08-21). Past sightings stay stored but stop being reachable from any
  page; full every-table erasure arrives with P3.
- **PPL-FR-006**: After removal the person MUST no longer appear in the
  directory and MUST never be recognised or named again, effective without a
  restart.
- **PPL-FR-007**: Every column in the People list MUST be self-explanatory or
  absent. A field for which no data exists is not shown as "—"; the guardian
  column disappears unless guardian data actually exists.
- **PPL-FR-008**: The recognition state MUST be worded professionally and
  concretely (e.g. whether this person can be recognised, from how many
  photos) instead of "Photo on file".
- **PPL-FR-009**: Clicking a person's row MUST open their history, for every
  person type. The row must look clickable.
- **PPL-FR-010**: Each person's entry MUST show, from data the system already
  holds: when they were enrolled, where and when they were last seen (camera
  and time), and today's attendance state (owner decision 2026-08-21). A value
  the system does not have is stated in words ("Not seen yet"), never "—".
- **PPL-FR-011**: All existing enrolment guarantees survive unchanged:
  nothing saved until Save, no images stored, admin-only enrolment. The photo
  floor moved from three to **five** (owner decision, 2026-08-21) and nobody
  is enrolled below it — a refused enrolment creates no directory row at all.
  Already-enrolled people keep the photos they have and stay recognisable.

## Success Criteria

- **SC-001**: A person being enrolled can position themselves using the live
  view alone, without the operator relaying instructions from another screen.
- **SC-002**: Within 2 seconds of stepping in front of the enrolment camera,
  the face outline and feature points appear on the live view.
- **SC-003**: A first-time operator can read any People row and explain every
  element of it without training.
- **SC-004**: Opening a person's history from the list takes one click.
- **SC-005**: A removed person is unrecognisable by the system within 5
  seconds of confirmation, with an audit entry naming the administrator.
- **SC-006**: An operator can leave the Enrol page from any step in one
  obvious click (plus one confirmation if photos would be lost).

## Out of scope

- Storing guardian or any new personal data — this feature adds no fields to
  what enrolment collects.
- Editing an enrolled person's name, type or group (re-enrol to change).
- Bulk import/removal of people.
- Full every-table erasure and durable audit — P3 owns durable storage; this
  feature removes what the running system holds and audits the action with
  the audit trail that exists today.
- Changing the face model or recognition thresholds.

## Constitution check

- **No fake data (rule 4)**: the live view is a real stream or an honest NO
  SIGNAL; feature points are drawn only when a face is genuinely detected.
- **Face names a person (rule 1)**: untouched — enrolment already feeds the
  face gallery only.
- **Honest degradation (rules 7, 8)**: recognition down leaves the directory
  readable with the existing notice; an offline camera says so.
- **Server-side permissions**: removal is admin-only on the server, like
  enrolment already is. A person's data leaving the system is exactly the
  kind of action the constitution wants gated and audited.
- **No delete of events**: removing a person is about the person's face data
  and directory entry; it must not silently delete audit entries.

## Assumptions

- The people list is the enrolled directory (it is today); "more details" come
  from data the system already holds — nothing new is collected.
- Removal is rare and deliberate, so a typed or two-step confirmation is
  acceptable friction.
- The existing history page is the destination for a clicked row; it works by
  person and needs no redesign here.
- The enrolment camera list stays as it is (any configured camera can be the
  enrolment camera).
