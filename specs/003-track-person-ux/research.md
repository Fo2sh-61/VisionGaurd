# Phase 0 — Research: Track a person

Verified against the code at the current tree (602 passed, 6 skipped). Theme:
**every requirement maps to the smallest mechanism, and every number is
measured before it is promised.**

---

## D1 — The live grid is CamGrid plus the areas that already exist

**Decision**: the live-catch view is the existing `CamGrid` reorganised into
area partitions with paging and a search box over camera and area names.
Clicking a tile enlarges it (`CameraFrame size="lg" live feature="track"`),
clicking a person in the enlarged view starts a follow.

**Rationale**: cameras already carry `area:` (config-required), `useCameras`
already serves the roster, and `CameraFrame` already does live streams,
NO SIGNAL, and the track overlay. 208 tiles is purely a layout problem —
partition + page + search, no new data.

**Rejected**: a map/floor-plan view (no floor-plan data exists); a bespoke
grid component (CamGrid is the grid).

## D2 — Click-to-track is a server-side pick, and the follow session lives in the tracking worker's loop

**Decision**: `POST /tracking/follow {cameraId, x, y}` — the engine finds the
tracked body whose box contains the click point on that camera's latest
tracking result, notes interest (boost), writes the audit entry, and opens a
**FollowSession** held by `TrackingWorker`. The session is advanced inside the
worker's existing per-frame `analyse()` pass — camera handoff, timer expiry
and track-loss detection are all checked there. **No new threads.**

**Rationale**: the old page picked the stable id client-side from polled
boxes, which cannot be audited and races the overlay. The worker already sees
every frame of every tracked camera; hanging session state off it makes the
follow logic exactly as current as the tracker itself. The stable-id machinery
(ByteTrack + appearance stitching, `LOST_TRACK_SECONDS = 6.0`) already defines
"unbroken track".

**Tracking on all cameras**: the `track` feature goes onto every camera at a
low idle rate; the followed/watched camera runs at boost (existing
`note_interest`). Decode cost is already paid — ingest reads every enabled
camera for the live view regardless. Detection cost at idle is the patrol-rate
knob, measured in D8's tool.

**Rejected**: a client-side follow (unaudited, racy); a dedicated follow
worker thread (state without a loop of its own is simpler and cannot drift
from the tracker).

## D3 — The name rule needs one gate added, not a new mechanism

**Decision**: `RecognitionWorker._name_the_body` (→ `TrackingWorker.note_face`)
stops firing on a single-frame match. It fires only when the same
**AnchorAccumulator** used for path anchors (D6) reports a sustained,
high-confidence identification of that body's face. Name-drop on track loss
already works: the name annotates a stable id, and a stable id dies with its
track and is never re-issued.

**Rationale**: today any one lucky frame names a body — exactly the "insurance
of identity" gap the owner called out. The unbroken-track semantics the spec
demands are already the stable-id lifecycle; only the entry bar changes. One
gate, shared with anchors, keeps live naming and path anchoring the same
strictness — the two claims mean the same thing, so they must cost the same
evidence.

**Rejected**: separate thresholds for naming vs anchoring (two bars for one
claim drift apart); persisting names across track loss (the constitution's
forbidden stored binding).

## D4 — Follow-recording drives the existing Recorder from the session

**Decision**: `FollowSession` optionally records: on open (or on demand) it
calls `Recorder.start(camera)`; when the followed identity's camera changes it
stops the old camera's recording and starts the new one — one segment per
camera, exactly the spec's shape. Timer expiry and track loss stop it
server-side with a reason. Segments land under the session and are served like
any recording.

**Rationale**: `Recorder` already handles per-camera capture, encoder warmup,
`AlreadyRecording`, and honest failure states. The session already learns of
camera changes in the worker loop (D2), so the hop logic is three lines where
the state already lives. Server-side stop conditions mean a closed browser tab
cannot leave a recording running.

**Rejected**: web-driven start/stop per hop (dies with the tab); a new
multi-camera recorder (the per-camera one composes).

## D5 — Patrol recognition is a second worker instance, tiered by a `faces` flag

**Decision**: `CameraConfig` gains `faces: bool = False`. At startup two
`RecognitionWorker` instances run: the existing one on `faces: true` cameras
(main stream, ~2 Hz idle as today), and a **patrol** instance on the rest at a
low rate (~0.5 Hz initial, a config knob sized by measurement). Both share the
gallery, sighting store, and `FacePipeline` — the pipeline is already used
concurrently by per-camera threads inside one worker, so a second instance
adds no new sharing class.

**Rationale**: per-camera rates inside one worker would mean touching
`base.py`, which every feature inherits; two instances need zero base-class
changes and keep the tiers independently observable (each reports its own
stats). The substream question (decode cost at 208) is real but belongs to the
scale-up phase; on current hardware the enabled-camera count makes main-stream
patrol fine, and the tier boundary is already expressed in config.

**Rejected**: per-camera rate maps in `FeatureWorker` (base-class churn for
one consumer); a new PatrolWorker subclass (it would be RecognitionWorker with
a different constructor argument).

## D6 — Anchors are decided at recognition time and stored with evidence

**Decision**: new `engine/vg/events/anchors.py` — `AnchorStore` (own table in
the sightings database file, same idioms as `SightingStore`) and
`AnchorAccumulator`, which the recognition worker feeds every match. The
accumulator keeps a short rolling window per (camera, person) and emits an
anchor when **all gates pass**: score ≥ per-tier anchor threshold; margin over
runner-up ≥ per-tier margin; face ≥ 80 px (the measured floor — never bent);
≥ N matches spanning ≥ T seconds; with at least one gap between matches
("recognised twice"). Gate numbers are per-tier config with lenient corner-cam
defaults (owner: "don't make it so hard"), calibrated on recorded footage.
An anchor row stores its evidence: matches, span, best/mean score, face px.

**Why at recognition time**: the sighting table is debounced — after the first
row, repeats are thinned to one per 60 s — so "five matches in three seconds"
is *invisible* in stored rows. The evidence only exists in the worker's frame
stream, so the decision must be made there.

**Rejected**: deriving anchors from stored sightings (blinded by debounce);
loosening the debounce (the table exists to stay small); a second sightings
table variant (an anchor is a span with evidence — a different shape, its own
store).

## D7 — The skeleton is one indexed read of the anchor table

**Decision**: `GET /path/{person}?date&from&to` → audit entry first, then
anchors for that person and window, each with camera name, area, span, and
evidence. Face anchors are the skeleton (green). The existing appearance
stitching (`AppearanceStore.path_for`) remains available as the blue
"same body" layer exactly as `/track` renders today — never named, never
merged.

**Rationale**: instant-skeleton is then a `SELECT` — SC-001's 3 seconds is met
by construction. `/track` stays serving until the new page fully replaces it,
then retires; its audit-first idiom (`_log` before result, `audit_id` in the
response) is copied, not reinvented.

## D8 — The archive layer: fetch on demand, measured before promised

**Decision**: new `engine/vg/ingest/archive.py` with a small
`ArchiveSource` seam:

- `dvr` backend — ffmpeg subprocess pulling the DVR channel's playback
  stream/URL for `[start, end]` into a local mp4. URL template per DVR in a
  new `archive:` section of `engine.yaml` (`{channel}`, `{start}`, `{end}`
  placeholders — every mainstream DVR/NVR exposes one of RTSP playback,
  ONVIF replay, or an HTTP cutout; the template covers all three).
- `footage` backend — slices local files in `footage_dir` by timestamp. This
  is the dev/test backend: the walk-through clip and recorder output make the
  whole leg pipeline runnable and testable with **no DVR at all**.

**`tools/measure_track.py`** fetches a 2-minute segment and times it
(× real-time), then times detection+tracking over it (fps). Results are
stored (a small `measured_rates` row in the sightings db) and every estimate
and cap is computed from them. Unmeasured system → the page says estimates
are unavailable and sweeps are disabled, honestly.

**Rejected**: continuous recording into our own storage (the owner's explicit
non-goal — 208 cameras of disk for questions nobody asked); per-DVR SDKs
(the URL template + ffmpeg covers the field until a real DVR proves
otherwise).

## D9 — Legs are chunked jobs with burn-in overlays, served like breach clips

**Decision**: `POST /path/legs {cameraId, from, to, personId?}` creates a job
on a **bounded runner (2 threads)** in `archive.py`. The job fetches the leg
in ~30-second chunks; each chunk runs the shared person detector + a
throwaway ByteTrack instance + (when a person is given) highlight selection,
**burns** the highlight box into the frames, and writes an mp4 chunk under
`clips_dir/track/`. `GET /path/legs/{id}` reports state and ready chunks;
chunks stream through a `FileResponse` endpoint exactly like breach clips
(same-origin, 404-with-reason). The player advances chunk to chunk; chunk 1
readiness is the 10–15 s promise, and processing runs faster than watching so
the buffer only grows. On chunk-1 completion the runner enqueues the likely
next leg at low priority: the next anchor's camera when known, else
`neighbours:` from config when present, else the same area.

**Why burn-in**: an overlay-sync player (boxes as JSON timed against
`video.currentTime`) is a second synchronisation contract to get wrong; a
burnt box cannot drift, and the chunk is then a self-contained piece of
evidence. The cost — re-encode — is already being paid to normalise DVR
output.

**Retention**: keep the last N legs' chunks per camera (the zones keep-3
idiom); a leg can always be re-derived from the DVR.

## D10 — Sweeps and strangers ride the same job runner

**Decision**: a sweep enumerates (camera × window) segments, prices them with
the measured rates, refuses over the cap (wall-clock budget ≈15 min,
recomputed from measurements), then runs as a background job appending hits.
A stranger follow starts from a clicked box in a viewed chunk: the appearance
descriptor of the clicked body becomes the query, and hop jobs search
adjacent cameras' segments for it — same machinery, appearance query instead
of person id. ReID quality note: the appearance matcher is classical and CPU
(settled — no neural ReID until the owner supplies the model; the `reid:`
slot in engine.yaml stays deliberately unset). Stranger stitching is
therefore honest about being "same body" evidence, blue, never named.

**Capacity sanity (to validate by measurement, not to promise)**: at ~2 fps
sampled processing and 10× fetch, one camera-hour ≈ 1–2 min end-to-end; a
15-min budget covers roughly 8–15 camera-hours — an hour's window over an
area, not the whole site. The estimate endpoint makes this arithmetic visible
per request.

---

## Open risks

| Risk | Mitigation |
|---|---|
| The real DVR's playback is slower than 10× or hostile to ffmpeg | `measure_track.py` runs before any promise; estimates and caps derive from it; worst case the page says legs take longer — honestly |
| Patrol decode cost at 208 cameras | Out of current hardware scope; tier boundary already in config; substream URLs slot into `source`-style config when scale-up comes |
| Anchor gates too strict on corner cameras → empty skeletons | Per-tier gate numbers with lenient corner defaults; calibrated against the walk-through clip's labelled ground truth |
| Burn-in re-encode too slow on the laptop | Measured by the same tool; chunk size can drop to 15 s; the promise is "no stall once started", which smaller chunks preserve |
| Restart loses in-flight jobs | Jobs are minutes-long; the page re-offers the leg; stated in capabilities |
