# Feature Specification: Cloud trial

**Feature Branch**: `021-cloud-trial` (from `remote-access`, which carries the falls feature the recorded clip runs)
**Created**: 31 Oct 2026
**Status**: Draft
**Input**: User description: "Test VisionGuard on a free cloud GPU for a few hours at a time,
open the console from my own PC through the internet, and measure how fast it responds
compared with running locally. This is a trial, not production. The Windows workstation path
must keep working exactly as today." Full prompt in the `/speckit-specify` call of 31 Oct 2026.
Owner answers the same day: Kaggle only (Colab later); TensorRT engines are built at the start
of every session as a fixed step; the admin password comes from a Kaggle secret.

## Why this feature *(mandatory)*

VisionGuard has only ever run on Mohamed's Windows laptop. Nobody knows how it feels when the
engine is somewhere else and the console reaches it over the internet: whether the camera
tiles keep up, whether the boxes lag, how long an event takes to show. `docs/PLAN.md` decided
"own the hardware, not cloud" on cost; this trial does not reopen that. It answers a smaller
question with real numbers: what does distance cost the operator, and does the engine run on
Linux at all. After this feature Mohamed can start a free Kaggle GPU session in the morning,
open the console from his PC, and get a local-vs-cloud speed table.

## User Scenarios & Testing *(mandatory)*

### Primary story

Mohamed has uploaded his model files and the recorded walk-through clip once, as a private
Kaggle dataset, and stored a password as a Kaggle secret. At the start of a work day he opens
the trial notebook on Kaggle and runs it. It checks the GPU, the models and the clip, builds
the TensorRT engines for that GPU, starts VisionGuard on the clip with an empty database and
one administrator account, and prints a public https address. He opens that address on his
PC, signs in with his password, and uses the console as he would locally. Then he runs one
measuring command on his PC, once against the cloud address and once against his local
engine on the same clip, and gets a side-by-side table saved in the repository. Before the
session's time runs out, or when he stops it, the console tells him the engine is going away,
and the database, logs and measurements are kept in the notebook's output.

**Acceptance scenarios**

1. **Given** the dataset and secret are in place, **When** Mohamed runs the notebook,
   **Then** within one run it prints a working https address, or stops at the first missing
   piece and names it (no GPU, a missing model, no clip, no secret).
2. **Given** the printed address, **When** he opens it on his PC, **Then** he sees the
   sign-in page, and only his password gets him in. No password-free sign-in exists.
3. **Given** he is signed in, **When** he opens the cameras page, **Then** the clip camera is
   live, with its boxes, and saved clips play in the browser.
4. **Given** he opens System Health, **Then** it shows the cloud GPU's real use and memory,
   and Ask and email say "not configured".
5. **Given** the engine runs on the cloud and on his PC, **When** he runs the measuring
   command against each, **Then** he gets one markdown table with both columns: page-load
   reads, camera pictures per second, box freshness, event-to-screen time, and the server's
   own numbers.
6. **Given** the session is near its time limit or he stops it, **Then** the console shows
   when the engine will stop before it stops, and the database, logs and measurements are in
   the notebook output afterwards.
7. **Given** the Windows laptop, **When** he runs `dev.ps1 up -Clip` as today, **Then**
   nothing has changed.

### Edge cases

- The GPU is not switched on in the notebook, or internet is off (Kaggle needs a
  phone-verified account for internet) → the notebook stops at that step and says so.
- A model or the clip is missing from the dataset → stop and name the file; never download one.
- Building a TensorRT engine fails or is too slow → that model runs from its `.pt`, and
  System Health and the session summary say which.
- No H.264 encoder on the machine → clips still save, and System Health says they will not
  play in the browser (never a silent black player).
- The tunnel drops or its address changes → the notebook says so; the measuring command
  reports failed requests as failures, not as slow successes.
- The session is killed without warning (quota, Kaggle restart) → nothing is promised beyond
  what was already copied; the summary says what was saved and when.
- Someone else finds the public address → they see a sign-in page and nothing else.

## Requirements *(mandatory)*

**Linux readiness**

- **CT-FR-001**: The engine MUST start and run its features on Linux with the Python the
  cloud provides (3.11 or 3.12) and on Python 3.14 on Windows, unchanged.
- **CT-FR-002**: Clips saved on Linux MUST play in the browser, and a test MUST prove it on
  every run of the suite where the machine can encode.
- **CT-FR-003**: System Health MUST show real GPU use and memory on Linux.
- **CT-FR-004**: Nothing Windows-specific (webcam backends, process clean-up, time zones,
  paths) may fail or mislead on Linux; where a Windows-only thing is absent it is skipped and
  said.

**Cloud profile**

- **CT-FR-010**: A cloud profile MUST run the recorded clip only, with a fresh empty database
  and throwaway storage, without editing the main site configuration.
- **CT-FR-011**: In the cloud profile password-free sign-in MUST be impossible: the engine
  refuses to start if it is requested.
- **CT-FR-012**: In the cloud profile Ask and email MUST report "not configured", and no key
  for either may be present in the notebook or the profile.
- **CT-FR-013**: No real enrolment, face, site record or site camera may be used in the cloud.

**One address**

- **CT-FR-020**: The engine MUST serve the built console and its own API from one address, so
  a single tunnel exposes both. The console's pages load without signing in; everything else
  keeps its current permissions.

**Notebook**

- **CT-FR-030**: One notebook and one start script MUST take a fresh Kaggle GPU session to a
  printed https address: check GPU, models, clip and secret; install what is missing without
  replacing the preinstalled GPU libraries; build the console if needed; build TensorRT
  engines; create the administrator; start the engine; wait until it answers; open the tunnel.
- **CT-FR-031**: The script MUST read models only from the owner's private dataset. It MUST
  NOT download, source or train any model.
- **CT-FR-032**: Each step MUST print how long it took, so the start-of-day cost is known.

**Measurement**

- **CT-FR-040**: A measuring command run on Mohamed's PC MUST sign in and record p50/p95 for:
  the health check and the reads the console makes on page load; camera pictures actually
  received per second; how old the boxes are when they arrive; and time from an event on the
  clip to it being visible through the API, matched against the clip's labelled marks.
- **CT-FR-041**: It MUST run identically against the local engine and the cloud address and
  write one markdown table comparing them into `specs/021-cloud-trial/evidence/`, with the
  server's own readings (System Health and the site benchmark) beside the client numbers.
- **CT-FR-042**: A failed or timed-out request MUST be counted and shown as a failure, never
  folded into the timings.

**Session end**

- **CT-FR-050**: The engine MUST know when the session will end, and the console MUST show a
  plain notice before it stops (time left; "stopping now").
- **CT-FR-051**: On a planned stop, or before the session's time limit, the engine MUST shut
  down cleanly and the database, logs and measurement files MUST be copied to the notebook's
  output folder.

## Success Criteria *(mandatory)*

- **SC-001**: From "Run all" on a fresh session to a working sign-in page takes under 20
  minutes, and the notebook prints the time each step took.
- **SC-002**: Mohamed has a saved table with local and cloud columns for every measure in
  CT-FR-040, from at least 5 minutes of measuring each.
- **SC-003**: A clip saved in the cloud plays in his browser.
- **SC-004**: Opening the public address without the password shows nothing but a sign-in
  page; a password-free sign-in attempt in the cloud profile stops the engine at start.
- **SC-005**: All four gates are green on Windows with no fewer tests than before, and
  `dev.ps1 up -Clip` behaves as today.
- **SC-006**: After a session ends, its database, logs and measurements can be downloaded
  from the notebook output.

## Out of scope

Later phase, not this spec:

- Live cameras from the site into the cloud (needs a tunnel from site to cloud, and real
  faces leaving the building, which `docs/PLAN.md` rules against).
- Hosting several customers, paid servers, a fixed address, or keeping the engine up 24/7.
- Google Colab: its free tier forbids using a web UI instead of the notebook and connecting
  to remote proxies, and may end such sessions without warning. Revisit only on a paid plan.
- The phone app over the tunnel (the console is enough to measure).
- Changing the hardware decision in `docs/PLAN.md`.

## Constitution check *(mandatory)*

- **III, truthful data**: the measuring command reports failures as failures and states the
  sample size; System Health says which models run as TensorRT and which as `.pt`; a clip that
  will not play in a browser is said, not hidden. Measurements are labelled "Kaggle T4,
  recorded clip, one camera", never generalised to a site.
- **IV, security and privacy**: a public address is the most exposed this engine has ever
  been. Real password only, dev sign-in refused at start, recorded clip only, empty database,
  no keys in the notebook. The clip shows only Mohamed; no enrolments go to the cloud.
- **I, real-time**: the trial exists to measure the latency budget honestly at a distance.
- **No model sourcing**: the owner's own files, read from his private dataset.
- **Windows path unchanged**: every change is either cross-platform or chosen by the profile.

## Assumptions

- Kaggle's free tier as of Oct 2026: one or two T4 GPUs, sessions up to 12 h, roughly 30 GPU
  hours a week, no fixed public address, disk wiped at the end. The notebook prints the GPU,
  Python and driver it actually got, rather than relying on this.
- Kaggle has no written rule against a tunnel to a web app; this is common practice. If
  Kaggle ends sessions for it, the trial stops and says so.
- A Cloudflare quick tunnel needs no account; its address changes every session.
- Mohamed uploads the `.pt` files and the walk-through clip with its marks file; neither is
  in git.
- The engine listens on the notebook machine only; the tunnel is the one way in.
- The clip-to-API event time is measured from the moment the engine records the event to the
  moment the PC sees it, plus the engine's own frame-to-event time, because the PC and the
  cloud machine do not share a clock precisely enough to compare frames directly.

## Addendum, 31 Oct 2026: the laptop webcam in the cloud

Owner's decision, the same day, after the first Kaggle session. It changes
CT-FR-013 and the first "Out of scope" line for this trial only.

- **CT-FR-060**: The laptop webcam MUST be usable as a camera of the cloud engine
  (`cam-webcam`), with the same features as the laptop camera, so the cloud console
  is the desktop's experience. The laptop sends; the engine never reaches into the
  laptop, and nothing on the laptop is opened to the internet.
- **CT-FR-061**: Only an administrator may send frames, and only to a camera whose
  source names itself as pushed. A real camera can never receive pushed frames.
- **CT-FR-062**: When frames stop arriving the camera MUST go stale and then NO SIGNAL
  within seconds, never showing an old picture as live.
- **CT-FR-063**: Mohamed's own face may be on the webcam and he may enrol himself in
  the cloud console to test attendance by name. The photos live only in that
  session's throwaway database. Still no other person's enrolment, face or site data.
- Live site cameras (many cameras, a site tunnel, someone else's faces) stay a later
  phase.
