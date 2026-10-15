# Feature Specification: Pilot site readiness

**Feature Branch**: `Fo2sh` (spec directory `016-pilot-site-readiness`)
**Created**: 17 Sep 2026
**Status**: Draft
**Input**: User description: "Get VisionGuard ready to be installed and left running at an
organization's site for a real pilot — records survive and can be managed, it installs and
runs by itself, the buttons a client will click work, and someone who isn't the developer
can install and look after it." Full prompt in the `/speckit-specify` call of 17 Sep 2026.
This covers **P3 (Durable events)** in `docs/PLAN.md`, the runbook part of **P10 (Go live)**,
closes FR-13 (retention + erasure), and fixes console defects 1, 2 and 4 from
`specs/015-phone-first-redesign/gaps.md`.

## Why this feature *(mandatory)*

Every feature now works on real data, but VisionGuard cannot be left at a customer's site. The
audit trail disappears on every restart, nothing deletes old records or lets a person be
erased, there is no backup, and an update could damage a site's data. It only starts from
developer scripts on a developer's machine, with a password-free developer sign-in still in
the code. And a client will click a school-profile Edit that saves nothing and an account Edit
that does nothing. After this feature, an installer can set up one Windows 11 workstation,
walk away, and the site's records are kept, cleaned, backed up and erasable on request.

## User Scenarios & Testing *(mandatory)*

### Primary story

An installer who is not the developer takes a clean Windows 11 workstation, follows the
on-site guide, and ends with VisionGuard running as a service over HTTPS, the owner's models
in place, TensorRT engines built on that machine, and a first administrator account. The
administrator signs in from the console or the phone, adds the site's cameras (about 16 to
start), sets the school profile and the alert email keys, and leaves. From then on the
workstation restarts VisionGuard after a crash or a power cut, deletes records past their
retention period, backs up every night, and System Health says when each of those last
happened. When a parent asks for their child's data to be removed, an administrator erases
the person and nothing about them is left except the audit trail. When a new version arrives,
the caretaker follows the update procedure, and if it fails they go back to the previous
version with the site's data intact.

**Acceptance scenarios**

*Records survive and can be managed*

1. **Given** an operator ran a track search and confirmed a knife entry, **When** the
   workstation is restarted, **Then** both audit entries are still listed, with who, what and
   when.
2. **Given** saving an audit entry fails, **When** an operator runs a track search, **Then**
   the search result is not returned and the operator is told the action could not be recorded.
3. **Given** an enrolled person with sightings, attendance, history and a track recording that
   names them, **When** an administrator erases them, **Then** a search of every stored record
   (database, clips, enrolment data) finds nothing about them except audit entries, and a new
   audit entry says who erased whom and when.
4. **Given** a clip 31 days old and a sighting 366 days old, **When** the scheduled clean-up
   runs, **Then** both are gone, and System Health shows the time it ran and how many of each
   kind it removed.
5. **Given** an administrator changes the clip retention to 10 days, **When** the engine
   restarts, **Then** the value is still 10 and the next clean-up uses it.
6. **Given** the backup folder is set, **When** a night passes, **Then** a new backup exists,
   older ones beyond seven are removed, and System Health shows when it ran and how big it is.
7. **Given** no backup has succeeded for 36 hours, or none has ever run, **When** anyone opens
   System Health, **Then** it shows a warning saying so, with the time of the last success
   or "never".
8. **Given** a backup, **When** the caretaker runs the restore command on a clean install,
   **Then** people, enrolments, events, audit, accounts and settings match the backup and
   enrolled faces are recognised again.
9. **Given** a site running the previous version with real data, **When** the new version
   starts, **Then** it brings the database up to date by itself and no record is lost.
10. **Given** a database change that fails part-way, **When** the engine starts, **Then** it
    does not start, the data is left as it was before the change, and the log and the service
    status say which change failed and why.

*Installs and runs by itself*

11. **Given** a clean Windows 11 machine with no Python on it, **When** the installer follows
    the install procedure, **Then** VisionGuard runs from its own environment, the owner's
    models are in place, TensorRT engines are built on that machine, and a first administrator
    exists.
12. **Given** VisionGuard is installed, **When** the machine boots, the engine process is
    killed, or the power is cut and restored, **Then** VisionGuard is running again without
    anyone signing in to Windows.
13. **Given** VisionGuard is running, **When** a browser or the phone on the local network
    opens it, **Then** the connection is HTTPS; plain HTTP carries no pages and no data.
14. **Given** a fresh install, **When** a subsystem fails to start, **Then** the engine does not
    carry on half-working without saying so (strict mode is on by default), and the reason is
    in the log folder and the service status.
15. **Given** this feature is done, **When** anyone runs `git grep -niE "dev.?sign.?in"`,
    **Then** it finds nothing.
16. **Given** an update fails its check after starting, **When** the caretaker follows the way
    back in the update procedure, **Then** the previous version runs on the backup taken just
    before the update.

*Buttons a client will click*

17. **Given** an administrator, **When** they change the school name, school hours, term dates
    or attendance cut-off in Settings and save, on the console or the phone, **Then** the
    values survive a restart, attendance marks late against the saved cut-off, term dates
    follow the saved values, and an audit entry was written before the save.
18. **Given** a guard, **When** they try to save the school profile or edit an account, by the
    screen or by calling the engine directly, **Then** the engine refuses.
19. **Given** an administrator, **When** they change another user's name or role, or disable or
    re-enable their account, on the console or the phone, **Then** the change is saved and
    audited, and a disabled user's open sessions stop working on their very next request.
20. **Given** one active administrator, **When** anyone tries to demote or disable them,
    **Then** the engine refuses and says an active administrator must remain.
21. **Given** System Health's camera grid on the console, **When** a known face is in view,
    **Then** no name and no face box is drawn on it.

*Looked after by someone who isn't the developer*

22. **Given** the on-site guide, **When** someone who has never seen the code follows it,
    **Then** they can install, create accounts, add cameras, set the alert email keys, back up
    and restore, update, and act when the engine will not start or a camera goes dark.

### Edge cases

- **Backup folder missing, full, or disk unplugged**: the backup fails, nothing half-written
  counts as a backup, and System Health names the reason. The older good backups are kept.
- **Clean-up has never run**: System Health says "not run yet", never a zero.
- **Clean-up fails part-way** (a clip file locked): what could be removed is removed, the rest
  is retried next time, and System Health says the last run was incomplete and why.
- **Erasing a person someone is following live** on Track: the follow stops showing their
  name and no recording that names them is kept.
- **Erasing a name two people share**: the administrator erases one exact person from the
  directory, never "everyone with this name".
- **Erasure interrupted** (power cut part-way): it is finished or clearly reported as
  unfinished and can be run again to completion; it never leaves a half-erased person looking
  complete.
- **The last administrator disables or demotes themselves**: refused, same as anyone else.
- **Two administrators edit the school profile at once**: the later save wins and both saves
  are audited; no merge.
- **Term dates entered backwards, or cut-off outside school hours**: refused with a plain
  reason; nothing is saved.
- **Engine unreachable from the phone or console**: the edit forms say the save did not
  happen; nothing is shown as saved.
- **Service restarts over and over** because a subsystem fails at every start: the log keeps
  every reason, the service stops trying after a bounded number of attempts, and the guide's
  "engine won't start" section says what to look at.
- **Certificate not yet trusted on a phone or PC**: the guide says how to trust it once; the
  engine never falls back to plain HTTP.
- **Restore onto a machine with a different GPU**: the data restores; TensorRT engines are
  rebuilt on that machine, never copied.

## Requirements *(mandatory)*

### P3 — Records survive and can be managed

> **27 Sep 2026: the audit trail moved to spec 018** (`specs/018-persistent-audit`), by
> Mohamed's decision. P3-FR-001 and P3-FR-002 are carried there unchanged; P3-FR-003 is
> replaced there, because administrators may now remove chosen entries, each removal leaving
> a note that can never be removed. SC-001 moved with them. Everything else in P3 stays here.

- ~~**P3-FR-001**~~ *(moved to 018)*: Every audit entry MUST be saved to the database before the result it records
  is returned or the change it records is made. If the save fails, the action MUST NOT
  complete and the caller MUST be told it could not be recorded.
- ~~**P3-FR-002**~~ *(moved to 018)*: Audit entries MUST survive a restart. Track searches, knife verdicts,
  removals and erasures, settings changes, account changes, and sign-ins (successful and
  failed, never with the password typed) MUST all be audited.
- ~~**P3-FR-003**~~ *(replaced by 018)*: Audit entries MUST be append-only: no screen, endpoint, clean-up or erasure
  changes or deletes one.
- **P3-FR-004**: An administrator MUST be able to erase one person. Erasure MUST remove them
  from every place a record about them is kept: face measurements, directory entry and group
  membership, sightings, attendance, person history, track stops, and recordings and clips
  that name them.
- **P3-FR-005**: Erasure MUST be audited before it runs, recording who erased whom and when,
  and how many records of each kind were removed. The entry MUST NOT copy any erased data
  (no measurements, sightings or times).
- **P3-FR-006**: Existing audit entries that mention the erased person MUST be left unchanged
  (owner decision, 17 Sep 2026).
- **P3-FR-007**: An erased person MUST stop being recognised immediately, without a restart.
- **P3-FR-008**: Retention periods MUST be stored in the database, editable by administrators
  only, audited before the write, and MUST survive a restart. There MUST be one period for
  clips, one for event rows, and one for sightings.
- **P3-FR-009**: A fresh install MUST start with clips kept 30 days, event rows 365 days and
  sightings 365 days (owner decision, 17 Sep 2026).
- **P3-FR-010**: A scheduled clean-up MUST delete clips, event rows and sightings older than
  their period, at least once a day.
- **P3-FR-011**: System Health MUST show when the clean-up last ran, whether it finished, and
  how many of each kind it removed; "not run yet" when it has never run.
- **P3-FR-012**: A backup of the database and the enrolment data MUST run every night to a
  folder or disk the administrator chooses. A backup that did not finish MUST NOT be counted
  as one. The seven most recent good backups MUST be kept and older ones removed
  (owner decision, 17 Sep 2026).
- **P3-FR-013**: System Health MUST show the time and size of the last good backup and MUST
  warn when there has been no good backup for 36 hours, when none has ever run, or when no
  backup folder is set, naming the reason for the last failure if there was one.
- **P3-FR-014**: A restore command MUST bring a clean install back to the state of a chosen
  backup — people, enrolments, events, audit, accounts and settings — and MUST be proved by an
  automated end-to-end test.
- **P3-FR-015**: Database changes MUST be versioned and applied by the engine at start. An
  update MUST bring a site's existing data forward without losing records.
- **P3-FR-016**: If a database change fails, the engine MUST NOT start, the data MUST be left as
  it was before that change, and the log and service status MUST say which change failed and
  why.

### P10 — Installs and runs by itself

- **P10-FR-001**: There MUST be one written, repeatable install procedure for a clean Windows 11
  machine that uses its own Python environment and never the system Python.
- **P10-FR-002**: The install MUST set up what today's tracking needs (the appearance matcher);
  the neural re-ID model MUST NOT be required.
- **P10-FR-003**: The install MUST place the owner-supplied models and build their TensorRT
  engines on that machine. It MUST NOT download or source any model; a missing model MUST stop
  the install with the model's name and where it goes.
- **P10-FR-004**: The install MUST create the first administrator account, asking the installer
  for the name, email and password. No default password may exist.
- **P10-FR-005**: VisionGuard MUST run as a Windows service that starts at boot with nobody
  signed in, restarts after a crash or power cut, and stops retrying after a bounded number of
  failed starts in a row.
- **P10-FR-006**: The engine MUST keep rotating logs in one known folder, named in the guide,
  with a size or age limit so logs cannot fill the disk.
- **P10-FR-007**: The console, the phone app and every engine call MUST be served over HTTPS on
  the local network. The install MUST make the site certificate and a file each PC and phone
  can trust once (owner decision, 17 Sep 2026). Plain HTTP MUST NOT serve pages or data.
- **P10-FR-008**: Strict mode MUST be on by default in an installed site.
- **P10-FR-009**: The developer sign-in MUST be removed completely — code, tests, launcher flags,
  shortcuts and documentation — so that `git grep -niE "dev.?sign.?in"` finds nothing.
- **P10-FR-010**: There MUST be a written update procedure — stop, back up, update, apply
  database changes, start, verify — with a way back to the previous version and its backup if
  the check fails.

### P10 — Buttons a client will click

- **P10-FR-011**: Administrators MUST be able to save the school name, school hours, term dates
  and attendance cut-off from both the console and the phone app. Saves MUST be audited before
  the write and MUST survive a restart.
- **P10-FR-012**: Attendance's late cut-off and term dates MUST use the saved values, never the
  bootstrap file's, once a value has been saved.
- **P10-FR-013**: The engine MUST refuse school-profile and account edits from anyone who is not
  an administrator, whatever the screen shows.
- **P10-FR-014**: Administrators MUST be able to change a user's name and role and disable or
  re-enable their account from both the console and the phone app, each change audited before
  the write.
- **P10-FR-015**: The engine MUST refuse any change that would leave no active administrator.
- **P10-FR-016**: A disabled user's sessions MUST stop working on their next request. A role
  change MUST take effect on the user's next request.
- **P10-FR-017**: System Health's camera grid on the console MUST NOT draw face boxes or names.
- **P10-FR-018**: Every new sentence MUST go into the shared wording catalogue used by both
  apps, in English and Arabic (Arabic as an unproofread draft, as today).

### P10 — On-site guide

- **P10-FR-019**: The repository MUST contain a short on-site guide covering: install, create
  accounts, add cameras, set the alert email keys, back up and restore, update and go back,
  trust the site certificate, and what to do when the engine will not start or a camera goes
  dark.

## Success Criteria *(mandatory)*

- ~~**SC-001**~~ *(moved to 018)*: After a restart, 100% of audit entries written before it are still listed.
- **SC-002**: After erasing a person, a search of every stored record for that person finds zero
  results outside the audit trail.
- **SC-003**: A restore from backup on a clean install recovers every person, enrolment, event,
  audit entry, account and setting in the backup, and a previously enrolled face is recognised
  again.
- **SC-004**: A database created by the version before this feature, with records in every
  table, is brought up to date with zero records lost.
- **SC-005**: Within 5 minutes of a power cut ending and the machine booting, VisionGuard is
  answering over HTTPS without anyone signing in.
- **SC-006**: A person who is not the developer installs VisionGuard on a clean Windows 11
  machine using only the guide and the owner's model files, in one working day.
- **SC-007**: `git grep -niE "dev.?sign.?in"` returns nothing.
- **SC-008**: Every change to the school profile or an account, made on either app, is still
  there after a restart and has an audit entry.
- **SC-009**: With one active administrator, 0 of the ways to demote or disable them succeed.
- **SC-010**: System Health shows the last clean-up and the last backup, and warns within one
  page load when the last good backup is older than 36 hours.

## Out of scope

- Legal consent work (the owner's).
- On-site accuracy measurements and failure drills (next spec).
- More than one machine.
- Continuous recording and footage search.
- The neural re-ID model (OSNet), the model manager, and gun detection.
- Hardware video decoding.
- Arabic proofreading.
- Editing retention periods for kinds of record other than clips, event rows and sightings.
- Password reset by email, and creating accounts from the phone if the phone cannot today.

## Constitution check *(mandatory)*

- **III. Truthful data**: the two fake controls (school-profile save, account Edit) become real;
  System Health reports clean-up and backup from what actually happened, "never" and "not run
  yet" rather than zeros.
- **IV. Reliability, security, privacy**: this feature is where retention, erasure, backup,
  tested restore, migrations, TLS and the removal of the password-free sign-in land. Audit is
  written before the result (AGENTS rule 11).
- **Rule 10, weapons have no delete**: no person can delete a knife entry. Retention removing
  entries older than their period is the site's policy, set by an administrator and audited,
  not an operator's delete.
- **Rule 7, degradation is payload**: a failed backup, failed clean-up or missing backup folder
  is shown on System Health, which stays a 200.
- **Rule 8, failures in the UI**: strict mode turns a startup failure into the engine not
  starting at all, so there is no UI to show it in. The reason goes to the log folder and the
  service status, and the guide says where to look. This is a deliberate trade for an unattended
  site: a half-working engine that looks healthy is worse. Needs care in the plan.
- **Owner supplies all models**: the install places and builds what the owner hands over and
  never downloads a model.
- **Database is the source of truth**: school profile and retention move out of `engine.yaml`
  into the database; the file only seeds a fresh install.
- **Rule 1 / identity**: System Health's console grid stops showing names.

## Assumptions

- The event rows retention covers knife entries, restricted-zone entries, vehicle passes and the
  alert delivery log; the existing 30-day clip period and 90-day delivery-log period in
  `engine.yaml` become database settings seeded from those values (event rows: 365).
- The audit trail itself is not cleaned by retention.
- Backup includes the database and enrolment data; clips are not backed up (they expire anyway).
- A nightly backup runs at a fixed quiet hour, site time; the time is not a setting.
- A sign-in audit entry records the email typed and the outcome, never the password.
- Role changes need no sign-out: the engine already decides permissions per request.
- Strict mode stops the engine only for startup failures of the engine's own subsystems; a
  camera going dark stays a camera state and never stops the engine.
- Retries of a failing service are bounded (a few attempts with a pause); the exact numbers are
  a plan decision.
- The phone app is served by the same workstation, so one certificate covers both apps.
- Camera count is read from the database; nothing in install, backup or clean-up assumes 16.
