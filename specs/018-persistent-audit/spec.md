# Feature Specification: An audit trail that survives restarts, with removal that leaves a trace

**Feature Branch**: `Fo2sh` (spec directory `018-persistent-audit`)
**Created**: 27 September 2026
**Status**: Draft
**Input**: User description: "fix it so that every restart audit not lost but make the
capability to remove desired audits if needed" (Mohamed, 27 Sep 2026), expanded in the
`/speckit-specify` call of the same day.

**Settled with Mohamed on 27 Sep 2026**: this spec takes over the whole audit trail from
spec 016 (its P3-FR-001 and P3-FR-002 are carried here unchanged, P3-FR-003 is replaced,
SC-001 moves here). Only administrators remove entries. They choose entries one by one. Any
entry except a removal note may be removed. Every removal leaves a note that can never be
removed. The audit list is on both the console and the phone. Spec first.

This closes **FR-12 (Durable audit trail)** in `docs/PLAN.md`. Requirements carried from 016
keep their numbers; new ones start at P3-FR-101 so the two specs never share a number.

## Why this feature *(mandatory)*

Every search, verdict and change VisionGuard records disappears when the engine restarts, so
nobody can later see who tracked whom or who confirmed a knife. And there is no screen to read
the audit at all. Administrators also need to remove entries now and then, for example one
logged by mistake, but removing proof must never be silent: the audit has to show that
something was taken out, by whom and why.

## User Scenarios & Testing *(mandatory)*

### Primary story

An administrator opens **Audit** in the console, or under More on the phone. They see what was
done, newest first: when, who, what and about what. The list goes back as far as the records
go. They tick two entries that were logged by mistake, press Remove, type why, and confirm. The
two entries are gone for good. At the top of the list, a note now says that two entries were
removed, by whom, when, and the reason they typed. Nobody can remove that note. An IT
account sees the same list, notes included, but has no way to remove anything.

**Acceptance scenarios**

1. **Given** an operator ran a track search and an administrator confirmed a knife, **When** the
   engine is restarted, **Then** both entries are still listed, with who, what and when.
2. **Given** saving an audit entry fails, **When** an operator runs a track search, **Then** no
   result is returned, and the operator is told the search could not be recorded.
3. **Given** a sign-in attempt, successful or failed, **When** the audit is opened, **Then** it
   lists the email typed and the outcome, and never the password.
4. **Given** an administrator has ticked two entries, **When** they press Remove, type a reason
   and confirm, **Then** both entries disappear, a removal note appears at the top with "2
   entries", their name, the time and the reason, and after a restart the entries are still gone
   and the note is still there.
5. **Given** an administrator presses Remove, **When** the reason is left blank, **Then** nothing
   is removed and they are asked for a reason.
6. **Given** an IT account, **When** it opens Audit, **Then** it sees every entry and note but no
   way to tick or remove, and a removal request sent to the engine directly is refused.
7. **Given** a removal note, **When** anyone, administrator included, tries to remove it,
   **Then** there is no control for it, and a direct request is refused.
8. **Given** the site's clock reads 14:05, **When** an action is audited, **Then** its entry
   shows 14:05 in the site's time.

### Edge cases

- **The audit's store cannot start**: the Audit page and System Health say it is unavailable and
  why, and never show an empty list as if nothing had happened. Audited actions refuse, as in
  scenario 2.
- **Nothing recorded yet** reads differently from **everything removed**: the first says no
  actions have been recorded; the second still shows the removal notes.
- **Two administrators remove the same entry at once**: it is removed once, with one note; the
  second is told it was already removed.
- **An entry removed while someone is reading the list**: their next refresh no longer shows it.
- **A reason that names a person**: the note is permanent, so the reason box says so before
  confirming, and asks not to write personal details.
- **A very long audit**: the newest page loads quickly, and older entries are reached by paging
  back, never by loading everything.
- **Demo mode** (`-Mock`): the audit stays as it is today, in memory and labelled demo.

## Requirements *(mandatory)*

Carried from spec 016:

- **P3-FR-001**: Every audit entry MUST be saved to the database before the result it records
  is returned or the change it records is made. If the save fails, the action MUST NOT
  complete and the caller MUST be told it could not be recorded.
- **P3-FR-002**: Audit entries MUST survive a restart. Track searches, knife verdicts,
  removals and erasures, settings changes, account changes, and sign-ins (successful and
  failed, never with the password typed) MUST all be audited. Every action audited today MUST
  stay audited.
- **P3-FR-003** *(replaces 016's append-only rule)*: An audit entry MUST never be changed. It
  can be removed only by an administrator as P3-FR-104 to P3-FR-107 describe; no clean-up,
  retention, erasure or other path may remove one.

New:

- **P3-FR-101**: Each entry MUST show when it happened in the site's own time, who did it,
  what they did, and what it was about.
- **P3-FR-102**: The audit MUST be listed in the console and in the phone app, newest first,
  with every older entry reachable by paging back.
- **P3-FR-103**: Administrators and IT accounts MUST be able to read the audit. Only
  administrators may remove entries, and the engine MUST decide this, refusing a removal
  request from any other account.
- **P3-FR-104**: An administrator MUST be able to tick one or more entries individually and
  remove them. A reason MUST be typed; a blank reason is refused. Before confirming, the
  screen MUST say how many entries will go and that the note left behind is permanent.
- **P3-FR-105**: Every removal MUST first save one removal note: how many entries were removed,
  who removed them, when, and the reason typed. The note MUST NOT copy anything from the
  removed entries. If the note cannot be saved, nothing is removed.
- **P3-FR-106**: A removal note MUST never be changed or removed, by anyone. No screen offers
  it, and the engine refuses such a request.
- **P3-FR-107**: A removed entry MUST be gone for good: not listed, not returned by any request,
  and not back after a restart.
- **P3-FR-108**: An entry's number MUST be unique for ever: removing entries never causes a
  number to be used twice.
- **P3-FR-109**: If the audit's store is not available, the Audit page and System Health MUST
  say so with the reason, and audited actions MUST refuse (P3-FR-001).
- **P3-FR-110**: Anything in the product or its documents that says audit entries are never
  removed, or that the audit is lost on restart, MUST be corrected to say what this spec does.

## Success Criteria *(mandatory)*

- **SC-001** *(from 016)*: After a restart, 100% of audit entries written before it are still
  listed, apart from those an administrator removed.
- **SC-002**: With saving the audit made to fail, 5 track searches out of 5 are refused, and none
  returns a result.
- **SC-003**: An administrator can find an entry, remove it with a reason, and see the note, in
  under one minute, on the console and on the phone.
- **SC-004**: From an IT account there are 0 ways to remove an entry or a note, on screen or by
  a direct request.
- **SC-005**: 0 removal notes can be removed or changed, by anyone.
- **SC-006**: A removed entry is returned by 0 requests, before and after a restart.
- **SC-007**: Every entry's time matches the site's clock to the minute.

## Out of scope

- Removing by filter (a person, a date range) or automatically after some days.
- Undoing a removal. Removed entries cannot be brought back.
- Exporting the audit.
- Retention, erasure, backup and installing: these stay in spec 016. Erasure (016 P3-FR-006)
  leaves audit entries that mention the erased person unchanged; an administrator may remove
  such entries under this spec.
- The website's Trust card wording (spec 017). It can say more once this is built.

## Constitution check *(mandatory)*

- **Server-side permissions**: removal is decided by the engine by path, administrators only;
  the screen hiding the control is only a hint.
- **Nothing untrue**: the audit reports itself live only once entries really survive a restart.
  A removal is never silent; the note says it happened.
- **Honest degradation**: a store that cannot start says so on the page and in System Health,
  and audited actions refuse rather than run unrecorded.
- **Provenance: departs from the constitution's wording, by owner decision.** The constitution
  says safety- or identity-relevant results keep their provenance, "including … relevant audit
  records". Mohamed decided on 27 Sep 2026 that any entry except a removal note may be removed,
  including the entries behind knife verdicts and track searches. What still stands: the knife
  verdict itself stays on the detection record (verdict, reviewer, reason), and the removal
  note shows that entries were taken out, by whom and why. **The constitution's wording should
  be amended to match (`/speckit-constitution`) before this is implemented.**
- **`docs/PLAN.md` P3** calls the audit "append-only". This spec amends that: entries are never
  changed, and removal is allowed only with a permanent note.
- **AGENTS.md rule 11** still holds: a track search's entry is saved before its result returns.

## Assumptions

- A removal note is shown in the same list as the entries, newest first, and looks different
  from them. One note covers everything removed in one go.
- The reason is free text, required, and a few hundred characters at most.
- Entries still held in memory at the moment this ships are lost at that restart; they were
  never saved.
- Nothing trims the audit automatically. Entries are small, so years of them fit.
- The only roles are administrator and IT; "guard" and "operator" in older text mean the IT
  role.
- A failed sign-in is recorded under the email that was typed.
- The Arabic wording for the new screens is drafted and shows only in development, as for
  every screen, until Mohamed approves it.
