# Changelog

What changed, when, and what it means for somebody using the console.
Reconstructed from the git history on 1 September 2026; maintained by hand
from here.

The project has no released versions yet. `docs/PLAN.md` holds the release
gates, and `STATUS.md` says which of them are met. Dates are commit dates.

---

## Unreleased

### 1 Sep 2026 — repository organised

No behaviour changed. Files moved.

- `models/` now holds model weights and nothing else. The three whole projects
  living inside it moved to `vendor/`: `loiterwatch` (a live dependency the
  engine imports), `gate-anpr` (the reference `infer/plates.py` was ported
  from, still executed as the `theirs` evaluation baseline), and `bag-tracker`.
- The plate photographs moved off the repository root into
  `datasets/egyptian-car-plates/`.
- `design/` held three generations of the same deck nested inside each other,
  oldest outermost. Only two files ever differed between them; the current
  revisions are now at the top and the older two sit in `design/archive/`.
- The one-off spec prompts moved to `docs/prompts/`.
- Removed: thirteen stray shell-redirect files at the root, an empty
  `index.html`, an orphan `MEMORY.md` whose one idea is already in
  `docs/PLAN.md`, and the build caches.
- Added: `LICENSE`, `CONTRIBUTING.md`, this file, `.gitattributes`, and a
  `README.md` in each folder that needed one.

### 30 Aug 2026 — Ask: the console answers a typed question (spec 010)

A guard types a question in plain language and lands on the page that answers
it, already filled in.

- The model picks the query from a fixed menu; **it never writes the answer.**
  Names never leave the building.
- Runs on a free tier: twenty requests a day, not fifteen hundred.
- Fixed: a dead quota and a live one looked identical, so the tool waited an
  hour for nothing.
- Fixed: "today" began at 23:00 the previous day.

### 30 Aug 2026 — Arabic console (spec 008)

A guard who reads no English can now read the console.

### 30 Aug 2026 — workload placement (spec 009)

Twenty-five seconds of processing work per second of video, with nothing
reading most of it. Removed.

### 27–28 Aug 2026 — vehicle gate (specs 006, 007)

The gate existed only on disk; now it is in the repository and on the screen.

- Plates are read, shown, and measured against two thousand photographs.
- Gate tiles had never once drawn a plate box — one missing word was why.
- Alerts wait for a person. The pass list shows any day, with the photograph
  that proves it.
- A wrong character takes one keystroke to fix.
- The first three frames of an approach were deciding the read, and they are
  the worst three. They no longer do.

### 23 Aug 2026 — lost bag search (spec 005)

Tick the cameras, press Search, and the ones that saw a bag come first. Or skip
the search: tick cameras, pick a colour, and bags are outlined live.

Nine ways of saying "bag" beat three trained classes.

### 22–23 Aug 2026 — knife detection (spec 004)

A knife in someone's hand becomes one entry that a person must judge — never an
automatic action. The box stays on screen long enough to be seen, draws on the
tiles without waking the face model, and does not require People Counting to be
switched on.

### 21–22 Aug 2026 — track a person (spec 003), people and enrolment (spec 002)

Click a body and the engine keeps hold of it. Video behind every stop, in
pieces, with the wait measured.

- Sweeps state their price before they run, and strangers never get a name.
- A sweep that looked at nothing must not say it found nobody.
- The followed body is marked out; nothing is ever marked green by tracking
  alone.

### 20–21 Aug 2026 — restricted zones (spec 001)

The camera list is real, the toggle sticks, a person on a restricted camera is
logged, and the clip records, saves and plays. Each camera keeps its last
three.

### 20 Aug 2026 — P2: the console has a lock on it

The engine asks who you are. The console signs in and stores no identity.
Permissions are decided by path, not by decorator — the one endpoint somebody
forgets to decorate is the one that leaks.

### 20 Aug 2026 — P1: one detection pass per frame

One person-detection pass fans out to counting, zones and tracking instead of
each running its own. The detection budget is measured rather than asserted.

### 19–20 Aug 2026 — P0: stop showing things that are not true

The foundation the rest of the project stands on.

- Pages no longer switch to invented data when a request fails; a failed
  request stopped looking like an empty one.
- Four pages had been asserting things they had not measured.
- The clock is asked per timestamp, not once at startup.
- One SQLite connection factory, with WAL.
- Recording is real; the remaining dead buttons say why they are dead.
- A Track badge reads the name, not the match kind. A face-named body draws
  green.
- Fight detection removed — it was never real.
- Roboflow removed, and footage of real people is no longer tracked in git.
- The constitution ratified, and four quality gates now run on every push.

### 18 Aug 2026 — initial commit

Engine, web console, mobile app and the spec-kit scaffold.
