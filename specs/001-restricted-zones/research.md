# Phase 0 — Research: Restricted Zones

Everything here is verified against the code at commit `6fef8e3`, not assumed.
The theme is: **reuse what exists, add two files.**

---

## D1 — A zone is a camera, not a polygon

**Decision**: keep the `/zones` endpoint and the `Zone` wire type, but every
zone is now exactly one camera covering the full frame. Zone id = camera id.

**Rationale**: the whole page, the API and the console already speak "zone".
Deleting that vocabulary would touch the endpoint, both wire files, `api.ts`,
the page and every test. Redefining what a zone *is* touches almost nothing —
the wire keeps its shape, the polygon becomes the full frame, and the UI simply
stops drawing it.

`Zone.polygon` is `list[Point] = Field(min_length=3)`, so it cannot be omitted
without a wire change. It is filled with the four frame corners
`(0,0) (1,0) (1,1) (0,1)`. That is literally true — the zone is the frame — and
it keeps every existing consumer valid.

**Alternatives rejected**:
- New `/restricted-cameras` endpoint — a second vocabulary for the same idea,
  and `/zones` would still need deleting.
- Make `polygon` optional — a wire change rippling to mobile and both front
  ends, for no gain.

**Consequence for the UI**: `CamGrid` renders `zone` from `CameraView.zone`.
The live path must stop populating it for this page so no orange rectangle is
drawn (P4-FR-002). The note under the grid changes too — it currently promises
an orange outline.

---

## D2 — Where the toggle is stored

**Decision**: a `restricted INTEGER NOT NULL DEFAULT 0` column on the existing
`camera` table in `ingest/store.py`.

**Rationale**: the camera roster is already persisted there, already the source
of truth over `engine.yaml`, and already opened through `vg.db.connect`. One
column, added with `ALTER TABLE` guarded by a `PRAGMA table_info` check — the
same pattern the file's `CREATE TABLE IF NOT EXISTS` already implies. This
satisfies P4-FR-003 with no migration tooling, which P3 will bring later.

**Alternatives rejected**:
- `engine.yaml` — the constitution says the database is the source of truth and
  the seed file is bootstrap only. It also could not be written at runtime.
- A separate `restricted_camera` table — a join for one boolean.

**Default is off.** A camera that appears in the roster is not watched until
somebody says so. Defaulting on would start recording the day a camera is
added, which nobody asked for.

---

## D3 — The scene state machine

**Decision**: one small state machine per camera, inside `ZonesWorker`, driven
by each `analyse(frame)` call:

```
idle    --person seen-->        recording        (open a scene, start recorder)
recording --person seen-->      recording        (extend, update peak count)
recording --nobody, <1 s-->     recording        (flicker — do nothing)
recording --nobody, >=1 s-->    idle             (close scene, stop recorder)
recording --2 min elapsed-->    idle             (close, reason: "cut at limit")
recording --toggled off-->      idle             (close, reason: "camera switched off")
```

**Rationale**: this is the entire feature. It is ~40 lines, has no threading
(FeatureWorker owns that), and is directly unit-testable by feeding it fake
frames with fake detections — no camera, no model, no server.

**The one-second rule is measured from the last frame that had a person**, not
from a count of empty frames. Frame counting would mean the rule changes with
the camera's rate, so a 2 Hz camera and a 12 Hz boosted camera would behave
differently. Wall-clock is the same everywhere. This is what makes P4-FR-006
and SC-003 testable with a fake clock.

**Timing source**: `frame.captured_at`, not `time.monotonic()`. The tests then
control time by controlling the frames, and the recorded gap matches the video
rather than the wall clock while the machine was busy.

---

## D4 — Recording: reuse `Recorder`, do not write a new one

**Decision**: use the existing `vg.ingest.recorder.Recorder`, which already
starts/stops per camera, drops frames rather than stalling ingest, measures the
real frame rate, enforces a maximum, and refuses to claim a file it did not
write.

**Rationale**: that file's docstring lists exactly the three failure modes this
feature would otherwise reinvent. Building a second recorder would duplicate
them and get them wrong.

**Traps found, and how each is handled:**

**Corrected during implementation: zones gets its own `Recorder` instance**,
pointed at `clips_dir/zones/`, rather than sharing the one behind the
operator's record button. This section assumed one shared recorder, and that
would have made the two features fight over a camera: an automatic scene in
progress would refuse an operator pressing Record, and the retention rule here
(one clip per camera) would be deleting files out of a folder somebody else
records into. Two instances each take their own frame subscription, so both can
run at once and neither can stop the other's file. The "one recording per
camera" rule the recorder enforces is about its own dictionary, and each
instance has its own.

| Trap | Handling |
|---|---|
| `Recorder.start()` raises `AlreadyRecording` | Catch it. The scene is still logged, with `clip: None` and reason "a recording was already running on this camera". With a dedicated recorder this can only mean an internal double-start, so the reason deliberately does **not** name an operator — blaming a person for it would be a guess printed as fact. Never a crash, never a stolen file. |
| `MAX_SECONDS` is 600 (10 min); the spec wants 2 min | Do not change the module constant — the manual button legitimately wants 10 minutes. Stop the scene from the worker at 120 s. |
| A dark camera produces no file at all | `state == "failed"` comes back with a reason; the scene stores that reason and the entry says the clip is unavailable. |
| Recording writes to `clips_dir` | Zone clips go to `clips_dir/zones/` so the retention rule (one per camera) can be applied without touching operator recordings. |

**Actor string**: `"restricted-zones"`, not a person. The recorder logs who
asked, and pretending an operator pressed record would be a lie in the log.

---

## D5 — "One clip per camera" — when the old file is deleted

**Decision**: when a scene closes and its clip is saved, delete the previous
scene's clip file **for that camera only**, then mark the old row
`clip_state = 'replaced'`. Order matters: mark first, then unlink, so a crash
between the two leaves a row that honestly says the clip is gone rather than a
row pointing at a deleted file.

**Rationale**: P4-FR-008 as answered by the owner (2026-08-20: per camera).
Deleting on *close of the next scene* rather than on *open* means the previous
clip stays watchable right up until a replacement genuinely exists — there is
never a window where a camera has no clip at all.

**Log entries are never deleted** (constitution: false alarms stay in history,
there is no delete). Only files are replaced. The row survives with its peak
count, duration and time.

**Interim, and marked as such.** The spec's Out of scope records the real
target — roughly a working day of clips, sized to the deployment machine.

---

## D6 — Serving the clip to the browser

**Decision**: new endpoint `GET /breaches/{scene_id}/clip` returning a
`FileResponse` with `media_type="video/mp4"`. `Breach.clip.url` points at it.

**Rationale**: `Clip` already exists on `Breach` with a `url` field, so the
wire needs no new type. There is currently **no** endpoint that serves a saved
video — `Recording.file` is a filesystem path for an operator to open by hand.
A path is useless to a browser, so this endpoint is genuinely new work.

**Trap — must not become a file-read hole.** The path is never taken from the
request. The scene id is looked up in the database, and the stored path is
checked to be inside the zones clip directory before it is served. A missing
file returns 404 with a reason, not a 500.

**Trap — same-origin.** `docs/HANDOFF.md` records that `<img src>` for camera
streams cannot send an Authorization header, which is why the dev server
proxies the engine. `<video src>` has the identical problem, so the clip URL
must be a same-origin relative path exactly like the stream URLs. Reusing the
existing URL-building helper is required, not optional.

---

## D7 — Does the worker need its own detection pass?

**Decision**: no. `ZonesWorker` takes the same `SharedDetection` instance the
people and tracking workers take.

**Rationale**: P1-01 exists precisely to stop a second pass. `SharedDetection`
caches on `(camera_id, frame.sequence)`, so when the zones worker and the
people worker land on the same frame, the model runs once. When they land on
different frames each gets a correct answer for its own frame. Either way no
two threads enter the model.

**A camera that is not restricted is skipped before any detection call**, so
switching the feature on costs nothing on cameras nobody restricted.

**Alternative rejected**: extend `PeopleWorker` with scene logic. It would
merge two features into one worker, which principle II forbids, and would make
restricted zones depend on counting being enabled — breaking rule 9.

---

## D8 — What "person detected" means here

**Decision**: one or more people anywhere in the frame, using the existing
person detections at the configured confidence. No polygon test, no feet point.

**Rationale**: the zone is the whole frame, so `point_in_polygon` and
`feet_point` are irrelevant here — every detection is inside by definition.
`features/people.py` keeps them for real polygon zones if they ever return.

**Peak count, not last count.** An entry says how many people were seen at
peak during the scene. The last frame's count would report 0 for a scene that
just ended, which reads as "nobody was there".

---

## D9 — Honest states on the page

**Decision**: `capabilities()` reports `breaches` as LIVE only when the zones
worker is running; otherwise UNAVAILABLE with the specific reason (worker
failed to start, or person detection is not running). The page keeps its
existing `DataNotice`.

Three different empty states, worded differently, because they mean different
things:

| Situation | What the page says |
|---|---|
| Worker running, no camera toggled on | "No cameras are set as restricted areas. Switch one on above." |
| Worker running, cameras on, nothing seen | "Nothing has been detected since the engine started." |
| Worker not running | The reason, via `DataNotice` — never an empty list that reads as "all clear" |

**Rationale**: constitution III, and directly the P0-08 lesson — a green tick
over a feature that is not running is how a school ends up trusting nothing.

---

## D10 — What must be deleted, not left behind

`api/store.py` (`MockStore`) keeps its `_build_zones()` and `_build_breaches()`
fixtures — that is what demo mode is for, and P0-01 established fixtures live
there and only there. `LiveStore` must **override** `zones()`,
`set_zone_enabled()` and `breaches()` so nothing falls through to `super()`.

A test asserts no invented zone name (`"Server room"` etc.) can appear from a
live store. This is the F1/P0-01 bug class and it deserves its own regression
test in this feature's commit.

---

## Open risks

| Risk | Mitigation |
|---|---|
| mp4v clips may not play in every browser | Verify by eye on the dev laptop during the manual check; it is the format the existing recorder already produces, so this is a pre-existing condition, not new |
| A busy camera rewrites its clip often, so a watched entry can be replaced mid-viewing | Acceptable at this scale and stated on the entry; the working-day retention target in Out of scope is the real fix |
| Recording every scene on 208 cameras is real disk churn | Out of scope now; sizing happens at installation. The per-camera cap bounds it at cameras × 2 min |

---

## D11 — The toggle must not close a scene from the API thread

**Found by the recorded-clip run, not by any test.** Switching a camera off
destroyed the recording of the scene that was running: the entry read "clip no
longer kept" seconds after it was made.

`set_zone_enabled` runs on the API thread and called `ZonesWorker.set_restricted`,
which closed the live scene. Meanwhile that camera's own worker thread was
inside `analyse`, past the restricted check and part-way through a detection
call. When it resumed, the scene it held had been popped, so it opened a
**second** scene and started a second recording — and when that one saved, it
replaced the first one's clip. The feature deleted the evidence of the very
event it had just recorded.

**Decision**: `set_restricted` is one assignment and nothing else. Each camera
closes its own scene on its next frame, at the top of `analyse`, which already
had that branch. `stop()` joins the threads before calling `close_all` for the
same reason.

**Why not a lock**: it would work, and it would be the third thing in this
file that has to be reasoned about across threads. `FeatureWorker` gives each
camera exactly one thread; keeping every mutation of a camera's scene on that
thread means there is nothing to lock. A test asserts the file contains no
`threading`, no `Lock(` and no `Thread(`, so the shortcut cannot be taken back.

**Cost**: the scene closes on the next frame rather than that instant — under
a second at 2 Hz, and the extra fraction of a second is in the clip, which is
the harmless direction. The page is correct immediately either way: it reads
the toggle from the database, not from the worker.
