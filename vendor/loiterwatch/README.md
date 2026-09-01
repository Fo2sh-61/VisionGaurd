# loiterwatch

A temporal rules engine for suspicious-loitering detection. It does **not** do
computer vision — it consumes track events from whatever detector you already
have (YOLO+ByteTrack, Frigate, an NVR, a commercial VMS) and decides when
behaviour over time becomes an alert.

That split is deliberate. Detection is a solved, swappable commodity; the part
that determines whether your operators trust the system is the temporal logic,
and that part should be declarative, testable, and replayable.

```
detector ──► tracker ──► zone events ──► [ loiterwatch ] ──► alerts
                          (JSONL/stream)     rules + state
```

## Quick start

```bash
pip install -e .
python -m loiterwatch replay examples/atm_events.jsonl -c examples/atm.yaml -v
```

Output on the bundled ATM scenario:

```
10:43:16  [!] WARNING  atm_no_card    UNEXPLAINED PRESENCE: track track-B at 'atm_lobby' for 45s
                                      with no card_inserted/transaction_complete
10:45:31  [!] WARNING  atm_dwell      LOITERING: track track-B present in 'atm_lobby' for 3m00s
               dwell=3m00s | since=10:42:31
10:51:45  [!] WARNING  atm_casing     REPEAT ENTRY: track track-C entered 'atm_lobby' 3x in 280s
10:52:31 [!!] CRITICAL atm_dwell      LOITERING: track track-B present in 'atm_lobby' for 10m00s
```

`track-A` — who walked up, inserted a card, and left — produces nothing. That is
the whole point: presence alone is not suspicious.

Other commands: `loiterwatch validate -c rules.yaml`, `loiterwatch types`.
Add `--speed 1` to replay in real time, `--json` for machine-readable alerts.

## Whole camera view as the restricted area

If there is no meaningful sub-zone to draw — anyone visible to the camera is
already somewhere they should not be — omit zones entirely. Events need no
`zone` field: each detection lands in a zone named after its `camera`, or in
`frame` if there is no camera either, and rules with no `zones:` list apply to
every camera.

```bash
python -m loiterwatch replay examples/restricted_events.jsonl -c examples/restricted_area.yaml
```

```
22:14:06 [!!] CRITICAL intrusion_night     INTRUSION: track track-A in restricted area 'cam_07' for 3s
22:14:33 [!!] CRITICAL intrusion_night     INTRUSION: track track-A in restricted area 'cam_07' for 30s
22:19:03 [!!] CRITICAL intrusion_night     INTRUSION: track track-A in restricted area 'cam_07' for 5m00s
22:30:43  [!] WARNING  perimeter_probing   REPEAT ENTRY: track track-C entered 'cam_07' 3x in 180s
```

A one-frame reflection and an engineer whose badge was granted both produce
nothing. Those two cases are what `confirm_s` and `cleared_by` exist for, and
they are the difference between a system operators trust and one they mute.

## Live camera view

```bash
pip install ultralytics opencv-python          # first run downloads yolov8n.pt
python -m loiterwatch live -c examples/live.yaml
```

![overlay preview](examples/overlay_preview.png)

Each person gets a box labelled with their identity, and nothing else. Alert
state is carried by colour: green → amber at halfway to the next threshold → red
on alert, with the frame border lit while any alert is active. Pass
`--show-timer` if you also want the dwell clock and progress bar above each
person. `q` or `Esc` quits, `s` saves a snapshot, `m` mutes/unmutes the alarm
without restarting.

**One number, one person.** Several cameras may show the same identity at
once — that is one person seen from two angles, and it is what you want. What
cannot happen is a number landing on two different people. Four rules enforce
it: a single counter issues every ID so no number is ever reused, even after an
identity is forgotten; an identity another camera is showing *right now* can
only be adopted on an undiscounted score, never from a truncated crop, and only
after `--concurrent-confirm` observations in a row agree; and within one camera
an identity is held by at most one live track. `holders(id, now)` reports which
cameras are showing an identity at a given moment.

### Tuning the cross-camera trade-off

The two failures are opposites, and which dial fixes yours depends on *how
many* wrong candidates there are — which is not obvious until you look:

| what `--debug-reid` shows | what is happening | dial |
| --- | --- | --- |
| the right person scores below the bar | one person scores lower through a second lens than the first | `--cross-similarity` **down** |
| one wrong candidate, scoring clearly ahead of everyone | a stranger genuinely resembles them | `--cross-similarity` **up** |
| two candidates within a few points of each other | a coin-toss recorded as a decision | `--cross-margin` **up** |

**Start with `--cross-similarity`, and suspect the discount.** By default the
cross-camera bar sits 0.10 *below* the same-camera one, on the reasoning that a
lens change costs you some score. That discount is also the single biggest
source of numbers landing on two people. Try `--cross-similarity` equal to your
`--stitch-similarity` first; on the synthetic two-camera footage in
`examples/benchmark_crosscam.py`, closing the discount cut stolen numbers by
roughly a quarter for a few points of linking.

`--cross-margin` is a narrower tool than it looks. It only fires when two
stored people both resemble the newcomer, so it catches uniforms and crowds —
"which of these two is it?" — and is blind to the commoner case of a single
confident wrong answer. Raise it when the debug output shows a cluster of
close scores, not as a general-purpose precision knob.

Remaining dials, in the order worth trying:

- `--concurrent-similarity` — the undiscounted bar for taking an identity
  another camera is showing right now. If your bad merges are specifically
  between two people visible at the same moment, this is the one.
- `--cross-evidence` — observations an identity needs before another camera may
  claim it at all. Raise it to stop half-formed galleries being matched
  against; costs a fraction of a second of delay on genuine handovers.
- `--concurrent-confirm` (default 3) — agreeing observations before a track may
  take an identity another camera holds. This filters frame-to-frame *noise*,
  not systematic resemblance: it will not help against two people who really do
  look alike, because a lookalike wins every frame just as a true match does.
  At 30fps it costs a tenth of a second. `1` disables it.
- `--holder-window` (default 2.0s) — how recently a camera must have shown an
  identity to still count as holding it. Raise it if your feeds run at very
  different frame rates, so a slow camera still counts as live between frames.

**Measure on your own footage.** The rates above come from synthetic frames
with an exaggerated colour cast, so they show the direction each dial moves and
not much else. Run `--debug-reid`, which prints the winning score, the
runner-up, and the gap between them for every new identity, and set the bars
from what you actually see.

**The ceiling.** All of these move you along a curve set by the descriptor,
which is an HSV histogram of the torso and legs. Two people in dark jackets and
jeans are genuinely the same vector to it, and no threshold recovers
information that was never measured. Moving the whole curve means a learned
ReID embedding — the `Appearance` protocol takes any object with
`signature(frame, box)`, and `similarity` already compares plain unit vectors,
so an OSNet-style model drops in without touching the matcher. Start from
`examples/botsort_reid.yaml`.

**Two cameras giving one person two IDs.** Press `j`, type both numbers
separated by a space, Enter — `j` `1` `space` `2` `Enter` merges `#p1` and
`#p2`. Two things happen: the surviving gallery now holds views from *both*
cameras, so each camera can match against its own angle in future; and the
system measures how far short the score fell and records that slack for that
specific camera pair. Confirm one person and the next one is shared
automatically. Overlapping cameras see a person from different angles, so the
torso band samples different parts of the clothing — a global threshold drop
would merge strangers everywhere, while a per-pair offset only loosens the
comparison that is actually miscalibrated.

**Correcting a wrong ID.** When someone re-enters and gets handed the wrong
identity, press `n`, type the wrong number, and press Enter — `n` `4` `Enter`
for `#p4`. The person on screen is split onto a fresh ID, and that pair is
banned from merging for the rest of the session.

The ban is the part that matters. Simply re-running the matcher would reproduce
the same answer: it already considered that the best candidate and was
confident. Recording "these two are different people" is the only thing that
changes the outcome, and it is information only you have. The split-off track
keeps the views it contributed, so it starts with a real description rather
than a blank one, and it stays eligible to find its *true* match — a correction
says "not that one", not "never match anything".

An alert also plays a system sound (Windows: `SystemHand` for critical,
`SystemAsterisk` for warning; other platforms: terminal bell) so you do not
have to be looking at the screen to notice a loiterer. Disable it with
`--no-alarm`, or turn your speakers up if the sound didn't play — it uses your
system volume, not a separate one.

If the camera disconnects or a video file ends, the window does **not**
disappear — it holds the last frame with a "press any key to close" banner
until you dismiss it. Only `q`/`Esc` closes it immediately. The terminal
likewise waits for Enter after the session ends, so it does not vanish out
from under you.

| flag | purpose |
|---|---|
| `--source` | webcam index, video file, or RTSP URL (default `0`) |
| `--camera` | zone name for this feed (default `cam_live`) |
| `--weights` | any YOLO weights; `yolov8s.pt` is more accurate and slower |
| `--conf` | detector confidence floor, separate from the rules' `min_confidence` |
| `--device` | `cpu`, `0`, `cuda:0` |
| `--no-alarm` | disable the audible alarm |
| `--show-timer` | also draw the dwell clock above each person |
| `--identity-db` | JSON file to remember people across restarts |
| `--stitch-quality` | minimum crop quality used to identify someone (default 0.55) |
| `--stitch-margin` | how far the best ReID candidate must beat the runner-up |
| `--log` | append alerts to a JSONL file |
| `--record` | write the annotated video to mp4 |
| `--no-window` | headless, for a box with no display |

`examples/live.yaml` uses deliberately short thresholds (3s / 15s / 60s) so you
can test it at your desk. Raise them a long way before real use.

**Timestamps default to wall clock**, which is right for a camera and wrong for
a recorded file; pass a frame-derived `clock` to `live.run()` when processing
video offline, or the timings will describe your decode speed.

## When someone leaves and comes back with a new ID

Trackers retire an ID once a person is gone, so a re-entry arrives as a stranger:
the dwell clock restarts and `repeat_entry` never counts past one. There are
three separate fixes and you probably want all of them, because they address
different lengths of absence.

**1. Give the tracker a longer memory.** BoT-SORT keeps an appearance model per
track, which covers most short exits with no code at all:

```bash
python -m loiterwatch live -c examples/live.yaml --tracker examples/botsort_reid.yaml
```

That config sets `with_reid: true` and `track_buffer: 900` (~30s at 30fps).
Needs ultralytics >= 8.3.

**2. Stitch identities in loiterwatch.** On by default in `live`. Each person is
remembered by what they wore and how they were built:

| cue | starting weight | what it does |
|---|---|---|
| upper-body colour | 0.45 | shirt or jacket — the strongest single cue |
| lower-body colour | 0.35 | trousers — separates people in the same uniform top |
| body shape | 0.20 | height:width ratio — separates build |

**Those weights are starting points, not constants.** A uniform defeats any
fixed weighting: if every member of staff wears the same apron, the upper-body
cue agrees for all of them — contributing 0.45 of apparent similarity while
distinguishing nobody — and the trousers that actually tell them apart are
outvoted. Measured, two colleagues in one apron score **0.822** against each
other, above any threshold that still permits a real re-entry. One then takes
the other's ID.

So each cue is re-weighted by how well it separates the people actually seen:
a cue that is near-identical across the population is scaled toward zero.
Build gets the same treatment and needs it most, since almost everyone is
person-shaped and `shape_similarity` returns ~1.0 for nearly every pair —
left fixed it becomes a floor of agreement between strangers, and that floor
*rises* when another cue collapses, because the score is renormalised over
whatever remains.

The sample is drawn from raw observations, never from confirmed identities.
That distinction is load-bearing: a uniform merges everyone into one identity,
so an identity-derived population would never reach the size that triggers the
fix — the statistic would depend on the matching it exists to correct.

Measured on five staff in one apron walking past in turn: **1 distinct
identity with fixed weights, 4 of 5 with adaptive**, and no change on varied
clothing (5 of 5 either way). The first two people ever seen still merge —
until the sample holds a few people there is no statistic to draw on.

Each body half is described by a hue/saturation histogram over the colourful
pixels *plus* a brightness histogram over all of them. The second part matters
more than it sounds: hue is meaningless for black, white and grey clothing, and
a lot of jackets are dark. Colour alone rates a black coat and a white one as
equally featureless.

**Accuracy comes mostly from refusing to answer.** Three guards, all of which
trade recall for precision on purpose:

- **Weak crops are weak evidence, not no evidence.** Someone walking in from the
  side is a vertical sliver for their first few frames. Re-entering the frame
  *guarantees* this, so discarding those frames meant refusing to look at the
  exact moment identification matters most. Crops are scored for quality
  (truncation, size, detector confidence); below `--stitch-quality` they can
  still match, but only against a threshold raised by `low_quality_penalty`,
  and they are never added to the gallery where they would teach a wrong
  description. Below `quality_floor` they are ignored entirely.
- **Ambiguity is declined.** If the best and second-best candidates are within
  `--stitch-margin` of each other, no match is made. Two similar-looking people
  are precisely the case that otherwise produces a confident wrong answer.
- **Evidence accumulates.** The decision is revisited over a short probation
  window as better views arrive, instead of being frozen by whatever the first
  frame looked like. Someone who enters truncated and then becomes fully visible
  still gets re-linked, just a few frames later.

When an unknown tracker ID appears it is scored against everyone who left within
`--stitch-gap` seconds (default 900), and on a match the original ID comes back.
The overlay shows `RE-ID` on the label for a few seconds and counts re-links in
the HUD.

Each person is stored as a **gallery of up to 12 distinct views**, not one
averaged vector. Someone facing away looks nothing like the same person facing
forward, and averaging the two produces a signature that matches neither; keeping
both means a returning person matches whichever view they show you.

```bash
python -m loiterwatch live -c examples/live.yaml --stitch-gap 1800 --stitch-similarity 0.8
--no-stitch          # turn it off entirely
```

**Two cameras, one command.** `multi` runs every feed in a single process with
one shared identity pool, so a person keeps their ID walking from one camera to
the other — instantly, with no file to sync:

```bash
python -m loiterwatch multi -c examples/live.yaml \
  --camera laptop=0 \
  --camera ipcam="rtsp://user:pass@192.168.1.50:554/stream1"
```

One window per camera, one alert stream, one alarm. `--camera NAME=SOURCE` is
repeatable; names become the zone names your rules see, so `zones: [ipcam]` in
the YAML scopes a rule to that feed. Add `--identity-db people.json` if you also
want the identities to survive a restart.

Each camera gets its own capture thread and its own YOLO model — tracker state
lives on the model and cannot be shared. Capture threads keep only the newest
frame, which is not optional for RTSP: network cameras push at their own rate,
and a loop that reads every frame in order falls further behind on each slow
detection pass until the "live" view is minutes stale.

Subtleties this handles that are easy to get wrong. Tracker IDs are only unique
*within* a camera — every tracker numbers its own people from 1 — so they are
namespaced per feed before matching. And the "same person cannot be in two
places at once" guard is relaxed across cameras, because with overlapping views
they legitimately can; without that, anyone straddling both feeds becomes two
people.

**Matching across cameras is a harder problem than matching one camera against
itself**, and is scored differently:

- **Build is not compared.** Height:width depends on how the camera is mounted.
  The same person filmed head-on and from a ceiling corner measures 5.0 and
  1.25 — scoring that as a mismatch costs 0.20 of similarity for no reason.
  Measured on a synthetic pair: 0.80 with build scored, 1.00 without.
- **The threshold is lower.** Different white balance and exposure shift the
  colour descriptor for one unchanged person; a warmer camera measured 0.56
  against a neutral one. `--cross-similarity` defaults to
  `--stitch-similarity` minus 0.10 and can be set outright.

If people still get separate IDs per camera, run with `--debug-reid`. It prints
the closest candidate and its score every time a new identity is created, which
turns threshold tuning into reading a number instead of guessing:

```
[ipcam] new #p4: closest was #p2 at 0.47 (need 0.50 cross-camera)
```

Set `--cross-similarity` just under the scores you see for people you know are
the same — and no lower, because the gap between "same person, different
camera" and "different person, similar clothes" is exactly what you are trading
away.

**Cameras on separate machines.** When one process cannot see both cameras, run
`live` per camera and point them all at the same `--identity-db` file:

```bash
python -m loiterwatch live -c examples/live.yaml --identity-db people.json --camera front_door
python -m loiterwatch live -c examples/live.yaml --identity-db people.json --camera atm_lobby --source rtsp://192.168.1.50:554/stream1
```

Run two (or more) of these at once, each in its own terminal, each with a
distinct `--camera` name and its own `--source`. Someone who gets ID `p3` at
the front door keeps `p3` when they walk in front of the ATM camera a minute
later — the console prints `identities: adopted N from other cameras` when
that happens.

Mechanically: `SharedIdentityStore` (`loiterwatch/shared_identity.py`) mints
every ID from a counter kept in the JSON file itself, under a short-lived lock,
so two cameras can never hand out the same ID to two different people. Each
process pulls the file on startup, pushes and pulls again every `poll_interval`
(2s) while running, and force-syncs one last time on exit — including on a
crash, since that sync runs in a `finally` block. The lock is a plain
exclusive-create file, reclaimed automatically if a process dies holding it, so
it needs no database and works identically on Windows and Linux.

This is eventually consistent, not instant: a person can take up to
`poll_interval` seconds to become recognisable on a second camera after first
being seen. For loitering alerts that is the right trade — availability over
strict ordering.

Note the honest limit here regardless of how many cameras share the store: it
matches on *clothes*. The same person in a different jacket tomorrow is a
different person to this system. It is re-identification within an outfit
across cameras and restarts, not across days.

Three guards keep it from inventing links: it never merges someone with an
identity **visible in the same frame**, it refuses matches under `min_absence_s`
(leaving sub-second flicker to `exit_grace_s`, where it belongs), and **shape
alone can never trigger a merge** — plenty of people are the same build, so at
least one colour cue must agree.

Tune `--stitch-similarity` in the direction of *missing* re-links. A false merge
invents dwell time for a person who was not standing there, and colour
histograms genuinely cannot separate two people dressed alike with a similar
build. If your site needs better, swap `BodySignature` for a deep ReID embedder —
`IdentityStitcher` takes any object with a `signature(frame, box)` method.

**3. Add up the visits instead of requiring one long stay.** Stitching restores
the *identity*, but `dwell` still measures a single continuous presence, so a
two-minute absence resets it however well you matched the person. If the
stepping-out is itself the behaviour you care about, use `cumulative_dwell`:

```yaml
- id: total_time
  type: cumulative_dwell
  threshold_s: 180        # total across visits...
  window_s: 900           # ...within this rolling window
  min_visit_s: 2
```

That is the rule that actually catches someone cycling in and out to keep any
single timer from maturing — and it only works if identities are stable, which
is why the three fixes belong together.

## Input format

One JSON object per line. The only required field is `ts`.

```json
{"ts": "2026-08-09T10:42:31Z", "kind": "observation", "zone": "atm_lobby", "track_id": "track-B", "confidence": 0.87}
{"ts": 1770000012.0,           "kind": "signal",      "zone": "atm_lobby", "signal": "card_inserted"}
{"ts": "2026-08-09T10:40:50Z", "kind": "exit",        "zone": "atm_lobby", "track_id": "track-A"}
{"ts": "2026-08-09T22:14:03Z", "camera": "cam_07", "track_id": "track-A", "confidence": 0.88}
```

The last line has no `zone`: the whole view of `cam_07` is the area of interest.

| kind | meaning |
|---|---|
| `observation` | track was seen inside the zone at `ts` — emit one per frame or per sample |
| `enter` / `exit` | explicit transitions, if your upstream already computes them |
| `signal` | non-vision business event: `card_inserted`, `transaction_complete`, `door_unlocked` |

`ts` accepts ISO-8601, epoch seconds, or epoch milliseconds. You only need
`observation` events — the engine derives entries and exits itself.

For live use, skip the CLI and drive the engine directly:

```python
from loiterwatch import Event, EventKind, load_config

engine = load_config("rules.yaml").engine(sinks=[my_notifier])
for track in tracker.stream():
    engine.ingest(Event(ts=track.ts, kind=EventKind.OBSERVATION,
                        zone=track.zone, track_id=track.id,
                        confidence=track.score))
```

## Rules

Rules are declared in YAML. Every rule accepts `id`, `type`, `zones`,
`severity`, `cooldown_s`, `min_confidence`, `active_hours`, `weekdays`,
`enabled`, and an optional `message` template.

### `dwell` — continuous presence past a threshold

```yaml
- id: atm_dwell
  type: dwell
  zones: [atm_lobby]
  min_observations: 3        # ignore one-frame phantoms
  thresholds:                # escalation; only the highest new level fires
    - {after_s: 180, severity: warning}
    - {after_s: 600, severity: critical}
```

Also: `threshold_s` for the single-level case, `repeat_every_s` to keep
re-alerting while the person is still there.

### `intrusion` — presence anywhere in view

```yaml
- id: intrusion_night
  type: intrusion
  confirm_s: 3               # reject single-frame detector noise
  min_observations: 3
  severity: critical
  cleared_by: [badge_granted]     # authorized entry cancels the alert
  active_hours: {start: "20:00", end: "06:00"}
  escalate:
    - {after_s: 30,  severity: critical}
    - {after_s: 300, severity: critical}
```

`confirm_s` is not a loitering threshold — it is only how long you wait before
believing the detector. Two or three seconds of consistent detections rejects
reflections, headlights, and blowing debris without meaningfully delaying a real
alert. Set `zones:` only when one camera needs a different policy.

### `cumulative_dwell` — total time across visits

```yaml
- id: total_time
  type: cumulative_dwell
  threshold_s: 180
  window_s: 900
  min_visit_s: 2
```

Sums every visit a track made inside the window. Re-arms once old visits age
out. Pair it with identity stitching or it will undercount badly.

### `repeat_entry` — casing

```yaml
- id: atm_casing
  type: repeat_entry
  zones: [atm_lobby]
  count: 3
  window_s: 900
  min_visit_s: 5             # a walk-past is not a visit
  min_gap_s: 20              # must actually leave in between
```

### `no_transaction` — presence with no business event to explain it

```yaml
- id: atm_no_card
  type: no_transaction
  zones: [atm_lobby]
  dwell_s: 45
  expects: [card_inserted, transaction_complete]
  scope: track               # or 'zone': any use of the machine clears everyone
```

In practice this is the strongest ATM signal available, because a card reader
gives you ground truth that no amount of video analysis can.

### Time-of-day gating

Loitering at 03:00 is not loitering at 13:00. Any rule can be scheduled:

```yaml
- id: atm_dwell_overnight
  type: dwell
  threshold_s: 90            # much lower bar at night
  severity: critical
  active_hours: {start: "23:00", end: "05:00"}
  weekdays: [fri, sat]       # optional
```

### Custom rules

```python
from loiterwatch import Rule, register

@register
class GroupApproachRule(Rule):
    type_name = "group_approach"
    def check(self, ctx):
        ...  # return a list of Alert
```

Any registered type is immediately usable from YAML.

## Design notes

**Exit grace is the load-bearing parameter.** Detectors drop frames and trackers
briefly lose people. Without `exit_grace_s`, a person standing perfectly still
at an ATM registers as twenty short visits and no dwell rule ever fires. The
engine holds a visit open for `exit_grace_s` after the last observation. Set it
above your worst observed tracking gap and below your shortest meaningful
absence — 3–8s is typical.

**The clock advances between events.** A threshold at 180s fires at exactly
T+180, not whenever the next frame happens to arrive. The engine steps its clock
forward in `tick_s` increments and evaluates at each step, which is also what
makes replay deterministic: the same log always yields the same alerts, so you
can tune thresholds against recorded incidents instead of guessing.

**Cooldowns are per-alert-identity**, keyed on rule + zone + track + visit, so a
single loiterer produces one alert per escalation level rather than one per
frame.

## Known limitations

- **Track ID switching is the dominant real-world failure mode.** If your
  tracker assigns a new ID after an occlusion, a 10-minute loiter looks like two
  5-minute visits. Fix this upstream (better re-ID, higher-FPS tracking) — no
  rule tuning compensates for it. A generous `exit_grace_s` helps only with
  short gaps.
- **Unattributed signals credit everyone in the zone.** A card reader cannot say
  *which* track inserted the card, so `scope: track` credits every person
  present at that moment. Use `scope: zone` if you would rather any machine use
  suppress alerts entirely.
- **Zone geometry is your problem.** The engine takes zone membership as given.
  Whether a foot-point falls inside the polygon, and how you handle perspective,
  is a detector-side concern.
- **Whole-frame mode inherits the camera's field of view.** With no polygon, the
  alert boundary is wherever the lens happens to point, so anything visible past
  the actual perimeter — a public footpath, a neighbouring property, a road —
  generates alerts you cannot tune away in the rules layer. Fix it by aiming or
  masking the camera, not by raising thresholds.
- **Timestamps are treated as UTC** when no offset is given, including in
  `active_hours`. Feed local-time offsets explicitly if your site cares.

## Tuning and deployment

Threshold choice is an operational decision, not a technical one. Every dwell
threshold trades missed incidents against operator alert fatigue, and an
alerting system that operators learn to ignore is worse than none. Replay a few
weeks of recorded events with `--json` and count what each candidate threshold
would have produced before you deploy it.

Worth stating plainly: "loitering" is a behavioural inference, not a fact. These
alerts should route a human to look at video, never trigger an automated
consequence on their own. Dwell time correlates with plenty of innocent
behaviour — waiting for someone, reading a phone, a person with limited
mobility, someone who needed three tries with the keypad. Keep alerts advisory,
log enough evidence for a reviewer to overrule the system quickly, and audit
false positives by location and time of day.

## Tests

```bash
pytest -q     # 255 tests
```

Coverage focuses on the temporal edge cases: exact threshold boundaries, grace
periods bridging dropouts, gaps that should reset the clock, out-of-order
events, cooldown suppression, replay determinism, single-frame noise rejection,
and authorization signals arriving before vs. after an alert. The live overlay
is covered too, driven by synthetic frames and a fake clock so no camera is
needed.
