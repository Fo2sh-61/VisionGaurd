# Feature Specification: Find a lost bag

**Feature Branch**: `005-lost-bag-search`
**Created**: 2026-08-23
**Status**: Built (every task done), then parked on 10 November 2026 — not part of console v2, may return in later work.
**Input**: User description: "now I will start finishing the lost bag page. it will not track bags in the organization. but instead when user lost a bag he will run the system to find lost bag in a desired area or multi areas as desired like check boxes he will check to search in them. make it simple and easy ux and easy to be implemented"

## Why this feature

A child comes to the office and says they have lost their bag. Today the only
answer is to walk the building. The Lost Items page exists but is entirely
fixtures: it offers a search that never ran and results nobody measured.

Nothing watches for bags the rest of the time, and it should not — a system
that logged every bag in the school all day would cost far more than it is
worth and would be a record nobody asked for. Instead the search happens
**when somebody asks for it**: tick the areas worth checking, press Search,
and the cameras that can currently see a bag come to the front of the grid
with the bag outlined. The operator looks, recognises the bag or does not, and
walks to one camera instead of forty.

## User Scenarios & Testing

### Primary story

A pupil reports a lost backpack. The office opens **Lost items**, ticks
*Main entrance* and *Ground floor* — or expands an area and ticks two cameras
inside it — optionally picks a colour, and presses **Search**. For up to a
minute the system looks at those cameras live. Cameras that can see a bag move
to the top of the grid, marked, with a box drawn round each bag. The operator
opens the most likely one, sees the bag, and sends someone to fetch it. If no
camera sees a bag, the page says so plainly and says how many cameras it
actually looked at.

**Acceptance scenarios**

1. **Given** three areas with cameras, **When** the operator ticks two areas and
   presses Search, **Then** only cameras in those two areas are looked at, and
   the page says how many cameras that was.
2. **Given** a bag visible on one camera, **When** the search runs, **Then** that
   camera appears first in the grid, marked as having found something, with a
   box drawn round the bag.
3. **Given** no bag visible on any chosen camera, **When** the search finishes,
   **Then** the page says nothing was found **and** how many cameras were
   checked — never a bare empty grid.
4. **Given** the operator picked a colour, **When** the search finishes, **Then**
   only bags matching that colour are marked, and the page says a colour filter
   was applied and how many bags it excluded.
5. **Given** a search is running, **When** the operator presses Search again or
   changes the ticks, **Then** the running search stops and the new one starts —
   results never mix.
6. **Given** the bag detector is not running, **When** the operator opens the
   page, **Then** the reason is on screen and Search is unavailable rather than
   a button that silently finds nothing.

### Edge cases

- **A chosen camera is offline.** It is not silently dropped: the result says
  which cameras could not be looked at, because "we found no bag" and "we could
  not look" are different answers and only one means keep searching elsewhere.
- **No camera has an area set.** Every camera in this deployment currently reads
  *Unassigned*. That must appear as a real group, not an empty page.
- **The operator ticks nothing.** Search is unavailable until at least one area
  or camera is ticked.
- **A bag is found the moment the search starts, and gone before it ends.** It
  stays in the results with the time it was seen, because that is still where
  the bag was.
- **The search finds thirty bags in a busy entrance.** The page must stay usable
  — the operator is scanning for one bag they will recognise.

## Requirements

- **P7-FR-001**: Users MUST be able to choose which cameras to search by ticking
  **areas**, with the cameras in each area expandable and individually tickable.
- **P7-FR-002**: A camera with no area set MUST still be reachable, grouped under
  a plainly named group rather than hidden.
- **P7-FR-003**: The system MUST look only at the chosen cameras. A camera nobody
  ticked MUST NOT be analysed.
- **P7-FR-004**: The system MUST look at the **live** cameras. It MUST NOT claim
  to search recorded video, and MUST NOT record or save any video or still image
  as part of a search.
- **P7-FR-005**: A search MUST find bags of any kind, without the user naming a
  type.
- **P7-FR-006**: Users MUST be able to optionally restrict results to one colour,
  and MUST be able to clear that choice.
- **P7-FR-007**: When a colour is chosen, the system MUST state that a filter was
  applied and how many bags it hid, so a filtered-out bag is never invisible.
- **P7-FR-008**: Cameras where a bag was found MUST be shown **before** cameras
  where none was, and MUST be visibly marked as having found something.
- **P7-FR-009**: Each found bag MUST be outlined on its camera's picture.
- **P7-FR-010**: A search MUST end on its own within a stated time limit, and the
  page MUST show that it is running until it does.
- **P7-FR-011**: Starting a new search MUST discard the previous one's results
  entirely.
- **P7-FR-012**: A finished search that found nothing MUST say how many cameras
  were checked and over what period.
- **P7-FR-013**: The result MUST name any chosen camera that could not be looked
  at, and why.
- **P7-FR-014**: Searching MUST NOT require any other feature to be switched on,
  and MUST NOT change what any other page reports.
- **P7-FR-015**: No result MUST ever carry a person's name or identity. This
  feature finds objects, not people.
- **P7-FR-016**: When bag detection is unavailable, the page MUST say why and
  MUST NOT offer a Search control that cannot work.

## Success Criteria

- **SC-001**: An operator who has never used the page can start a search in under
  30 seconds without being told how.
- **SC-002**: A search over ten cameras finishes, or reports its own timeout,
  within 60 seconds.
- **SC-003**: A bag placed in view of a chosen camera is marked on that camera in
  at least 9 of 10 attempts.
- **SC-004**: A camera the operator did not tick is never analysed — provable,
  not assumed.
- **SC-005**: After a search that finds nothing, an operator can state from the
  screen alone how many cameras were checked.
- **SC-006**: Running a search changes no number on any other page.

## Out of scope

- **Watching for bags continuously.** Nothing looks for bags except during a
  search somebody started.
- **Searching recorded video.** There is no continuous recording in this system
  yet; a search sees only what the cameras can see now.
- **Saving or exporting anything** — no clips, no stills, no report.
- **Telling anyone whose bag it is**, or who left it.
- **Alerting.** A search has a person in front of it already.
- **Items other than bags**, even where the model can name them.
- **Tracking a bag between cameras**, or saying where it came from.

## Constitution check

- **Rule 1 and 15 (identity).** This feature finds objects. No result carries a
  name, a face match or an appearance id, and its overlay must not fall through
  to the recognition boxes — the same trap knife detection hit.
- **Rule 3 (own overlay).** Bag boxes are this feature's overlay and belong only
  to this page.
- **Rule 4 (nothing untrue).** The two dangerous states are an empty grid that
  reads as "no bag here" when nothing was searched, and a Search button that
  works when the detector is not loaded. Both are covered by FR-012 and FR-016.
- **Rule 5 (no false precision).** Colour is judged from pixels under whatever
  lighting the corridor has. The page must present it as a filter that can be
  wrong, never as a fact about the bag.
- **Rule 7 (degradation is payload).** An unavailable detector, an offline
  camera and a timed-out search are all answers, not errors.
- **Rule 9 (no feature depends on another).** Searching must work with
  attendance, counting and knife detection all switched off.
- **Cost.** Only ticked cameras are analysed, and only while a search runs. This
  is the whole reason the feature is affordable at 208 cameras.

## Assumptions

- **Live only, decided by the owner on 23 Aug 2026.** Continuous recording does
  not exist (P7 in `docs/PLAN.md`), so a search over past footage would be a
  2–3 week foundation before this page could do anything. A bag left behind is
  usually still sitting there, so looking now answers the real question.
- **Any bag, no type chosen** — owner decision, same date. The operator
  recognises their own bag far better than a filter does. A bag is a backpack, a
  handbag or a suitcase.
- **Colour is optional and approximate.** Nothing in the system judges colour
  today, so this is new. It is a filter over bags already found, never a way to
  find more, and the page must say so.
- **Areas with cameras grouped under them** — owner decision, same date. Only
  one area is configured today, so most cameras will appear under *Unassigned*
  until areas are filled in. That is a configuration task, not a blocker.
- **60 seconds is the search limit**, matching the existing latency budget in
  `docs/PLAN.md` §7. Tunable.
- **The owner's `bagbest.pt` is the intended model.** It is the only trained bag
  model supplied, dated 7 Aug 2026. Confirming that, and measuring it, is
  planning work — a model file being present is not acceptance.
- **No new permission.** Any signed-in user may run a search; it reveals nothing
  the live camera pages do not already show.
