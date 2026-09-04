# Phase 0 — Research: Camera Onboarding

**Written 2026-09-01 against commit `faab0fd`.** Every claim below was read out of the
code, not remembered.

---

## What is actually there today

The picture matters because five of the six decisions below are "stop doing something",
not "build something new".

| Thing | State | Evidence |
|---|---|---|
| Add one direct RTSP camera | **real** — validated, persisted, starts watching in the same call | `live.py::LiveStore.add_camera` |
| Test a connection | **real** — opens the stream, pulls a frame, reports failure as payload | `live.py::LiveStore.test_connection` |
| Runtime add / remove of a *stream* | **real** — starts and stops one camera, does not touch the other 207 | `registry.py::CameraRegistry.add/remove` |
| Connect a recorder | **fixture** — `LiveStore` never overrides it, so `MockStore` answers | `store.py::MockStore.connect_dvr`, and no override in `live.py` |
| Scan the network | **empty, silently** — returns `[]`, which reads as "nothing out there" | `live.py::LiveStore.scan` |
| Add a discovered device | **fake save** — never calls the engine | `CameraSources.tsx::addFound` |
| Add recorder channels | **fake save** — never calls the engine, invents the address | `CameraSources.tsx::addDvr` |
| Capture service banner | **fabricated** — a ticked device at `192.168.1.10` that does not exist | `CameraSources.tsx`, the `source.captureService` block |
| Channel name and area typed by the operator | **discarded** — `defaultValue`, and a `<select>` with no handler | `CameraSources.tsx`, the `dvrStep === 'channels'` block |
| Channel list from the engine | **discarded** — `api.ts` keeps only `.length` | `api.ts::connectDvr` |
| Feature choice | 3 of 7, and no per-feature settings | `CameraSources.tsx::FEATURES` |
| `faces` / `gate` / `direction` from the console | **not persisted at all** | `ingest/store.py::CameraStore.add` — 8 columns, none of these |
| Editing a camera | **does not exist** | `CameraStore` has `add`, `remove`, `set_enabled` and no `update` |
| A camera added starts being analysed | **no, not until restart** | `features/base.py::FeatureWorker.start` takes `cameras` once |
| `weapons` in a camera's feature list | **ignored** — knives run on every enabled camera | `app.py::_start_weapons`, `watched = [c.id for c in roster if c.enabled]` |
| `intrusion` in a camera's feature list | **ignored** — zones run on every enabled camera | `app.py::_start_zones`, same line |
| Lost items per camera | **ignored** — any camera anybody looks at | `features/lostbag.py::BagWatch`, no camera list |
| Camera add / edit / remove audited | **no** | no `_log` call on any `/sources` endpoint |

---

## D1. How the engine enumerates a recorder's channels

**Decision.** The operator supplies the recorder's stream-URL pattern, with `{channel}` in
it, and the list of channels to try. The engine builds each URL, **opens it for real**,
and reports per channel whether a frame arrived. Only channels that produced a frame are
offered for adding.

**Rationale.**

- The product already has this exact idiom and it already works: `archive.playback_url`
  in `engine.yaml` is an operator-supplied template with `{channel}`, `{start}` and
  `{end}` placeholders, and its comment gives the reason — "every DVR spells that URL
  differently, which is why it is a template rather than code". A second dialect for the
  same problem would be a second thing to learn.
- Proving a channel works is already solved. `LiveStore.test_connection` opens a
  `CameraSource`, reads a frame, and returns the real size and latency, or the real
  failure. A channel probe is that function in a loop.
- Nothing new is depended on. The same capture path, the same timeouts, the same
  redaction.

**Alternatives rejected.**

- **ONVIF.** Ruled out by the owner on 1 Sep 2026. It would also be a new dependency, and
  it does not work on every recorder or every firmware, so it would need the template
  fallback anyway — two paths where one does.
- **Per-brand templates baked into the code.** A new recorder brand would then be a code
  change. The whole point of the template is that it is not.
- **Trusting the recorder's own channel count.** That is what the fixture does today, and
  a recorder reporting sixteen configured channels of which four have cameras plugged in
  is the ordinary case. A count is not evidence.

**Consequences to design for.**

- **Probing sixteen channels serially at an 8-second open timeout is 128 seconds.** The
  probe must run several at a time under one total budget, and a channel the budget never
  reached must read as *not checked*, never as *did not answer*. Those are different
  facts and the spec's edge cases already require them to read differently.
- The console may offer well-known patterns as **fill-in helpers the operator can edit**
  (Hikvision, Dahua), because a pre-filled editable text box makes no claim. It must not
  present them as detection.

---

## D2. How a feature starts on a camera without restarting the engine

**Decision.** `FeatureWorker` gains `watch(camera_id)` and `unwatch(camera_id)`.
`LiveStore` gains one private method that maps a camera's feature list onto the workers it
already holds, called on add, on edit and on remove.

**Rationale.**

- The hard part is already done. `CameraRegistry.add` and `.remove` start and stop one
  camera's capture thread at runtime, without disturbing any other camera, and are used
  today. Nothing tells the *feature* workers, and that is the entire gap.
- `FeatureWorker` is already one thread per camera, subscribing per camera, keying every
  piece of state by camera id. Adding a camera is starting one more of the threads
  `start()` already starts. The shape does not have to change; the list does.
- `LiveStore` already holds a reference to every worker — `people_worker`, `recogniser`,
  `patrol`, `tracking`, `zones_worker`, `weapons_worker`, `lost_watch`,
  `vehicles_worker`. There is no new wiring, no registry of registries, no event bus.
- Every worker's per-camera state is created lazily (`dict.setdefault`, `dict.get`), so a
  camera appearing mid-run needs no construction step. Verified in `tracking.py`,
  `vehicles.py`, `weapons.py`, `zones.py`.
- There is a proven precedent for changing what a running worker watches:
  `ZonesWorker.set_restricted` is a live setter whose docstring is a warning about
  exactly the mistake to avoid (below).

**Alternatives rejected.**

- **Restart the engine on every change.** Interrupts all 208 cameras to add one, and
  turns "correct a typo in a camera name" into a site-wide outage. This is the fallback
  the spec's Assumptions section already offers the owner, not the default.
- **Rebuild all workers on change.** Same interruption, plus it throws away every open
  scene, every tracker and every de-duplication window.
- **A supervisor thread polling the roster.** Adds a delay nobody can name, a race
  nobody can test, and indirection between the write and its effect.

**The trap this turned up — recorded here because it is a design decision, not a note.**

`ZonesWorker.set_restricted` says, at length, why it does **not** close a running scene
itself: it runs on the API thread while the camera's own thread may be mid-`analyse`
holding a scene it is about to write to. Closing underneath it made that thread open a
second scene, whose clip then replaced the first one's — so switching a camera off
destroyed the recording of the scene that was running.

`unwatch` has the same shape and must not repeat it. So: `unwatch` sets a per-camera
drop flag and returns. The camera's **own thread** sees the flag, calls an overridable
`_closing(camera_id)` hook before it unsubscribes, and exits. Zones and weapons override
that hook to close any open scene with a reason. Nothing is closed across threads.

Three further facts in `features/base.py` that the design has to accommodate:

- `self._stop` is one Event for the whole worker, so it cannot express "stop this one
  camera". A per-camera Event is needed alongside it.
- `self._threads` is a `list`, so there is no way to find the thread for one camera. It
  becomes a `dict[str, Thread]`.
- `self.cameras` is read without the lock in `serves()` and in `stats`. That is safe only
  because it never mutates today. Once it does, both reads take the lock.

---

## D3. Which switch actually governs each feature

**Decision.** The camera's `features:` list is the single answer for all seven, and an
unknown feature name is refused at parse time instead of silently doing nothing.

**What has to change to make that true:**

| Feature | Governed today by | Governed after |
|---|---|---|
| counting | `counting` in features (via `BODY_FEATURES`) | unchanged |
| track | `track` in features | unchanged |
| attendance | `faces` or `attendance` in features | unchanged, and `faces` becomes settable from the console |
| vehicles | `is_gate` — `vehicles` + gate + direction | unchanged, and gate/direction become settable and persisted |
| **intrusion** | **nothing.** `ZonesWorker` runs on every enabled camera | `intrusion` in features |
| **weapons** | **nothing.** `WeaponsWorker` runs on every enabled camera | `weapons` in features |
| **lost items** | **nothing.** Any camera anybody opens | `lostitems` in features |

**This is a behaviour change and must be shipped as one.** Two notes on how it lands:

- **Zones cost little today and knives cost a lot.** `ZonesWorker.analyse` returns before
  any detection call when a camera is not marked restricted, so the waste there is a
  thread and a bus subscription per camera. `WeaponsWorker.analyse` runs the shared person
  detector on **every** frame it processes on **every** enabled camera, and the knife
  model on top wherever a person is found. At 208 cameras that is the largest unasked-for
  cost in the engine, and it is also a correctness problem: a camera nobody asked to watch
  for knives raises knife entries that a human then has to review.
- **`cam-laptop` lists `intrusion` but not `weapons`.** So after this change, knife
  detection stops on the only enabled camera in this repository until the feature is
  ticked. That is the configuration file already saying what it wants, and the current
  behaviour is the bug — but it is still a change somebody must be told about, in
  `STATUS.md` and on System Health.

**How it is made visible rather than silent.** The vehicle gate already has the right
sentence shape for this and it is proven: *"No camera is set up as a gate, so no plates
are being read."* Knives and restricted areas get the same treatment — when no camera
carries the feature, System Health says so with the reason, rather than the feature
appearing healthy over nothing.

**Alternatives rejected.**

- **Migrate every existing camera to carry `weapons`, to preserve behaviour.** The
  baseline roster lives in `engine.yaml`, and writing back into that file is out of scope
  and forbidden by the settled decisions. A migration that could only touch the database
  half of the roster would make two cameras behave differently for reasons nobody could
  see.
- **A top-level `weapons: cameras: all` switch.** New configuration surface to express
  something the per-camera list already expresses, and it would let the two disagree.

---

## D4. Where the missing per-camera settings are stored

**Decision.** Add the missing columns to the existing `camera` table with the project's
existing `ALTER TABLE` idiom, and add `CameraStore.update`.

**Rationale.**

- `CameraConfig` already carries `faces`, `gate`, `direction`, `face_gate`,
  `live_capture` and `neighbours`, and `CameraConfig.parse` already validates every one
  of them, including refusing the half-configured gate states. The dataclass is complete;
  only the six columns that persist it are missing.
- The project already migrates SQLite this way twice, and both are the same six lines:
  `PRAGMA table_info(...)`, then `ALTER TABLE ... ADD COLUMN` for anything absent — see
  `events/vehicles.py` and `auth/store.py`. Copy it, do not invent a migration framework.
- `merge_cameras` already documents that a stored row wins over the YAML one, and gives
  the reason: "if YAML won, the edit would appear to work and then silently revert on
  restart". Editing a YAML-seeded camera is therefore *already* defined — it writes a
  stored row that shadows the file. What is missing is telling the operator that, which
  is what `P13-FR-020` asks for.

**Alternatives rejected.**

- **A second table for the new fields.** Two rows per camera, two places to keep in step,
  and a join for every read. The `camera_restricted` table is separate for a stated
  reason — most cameras have no `camera` row at all — and that reason does not apply
  here, because these fields only ever exist for a camera somebody configured.
- **A JSON blob column.** Unqueryable, and it would let an invalid config be stored that
  `CameraConfig.parse` would then refuse at the next start.

---

## D5. Adding many cameras in one action

**Decision.** One endpoint that takes a list and returns one outcome per camera, always
200.

**Rationale.** A recorder with sixteen working channels is sixteen `POST /sources` calls
today, and the fourth failing tells the operator nothing about the other twelve. The
constitution's rule that degradation is payload rather than a status code applies exactly
here: "camera 7 was refused because its id is taken" is information, not an error.

**Alternatives rejected.**

- **Sixteen calls from the console, gathered client-side.** Works, but the outcome
  summary then exists only in the browser, cannot be audited as one act, and a page
  closed mid-way leaves a half-added recorder with nothing recording what happened.
- **All-or-nothing.** One bad channel would refuse fifteen good ones.

---

## D6. What the engine says and what the console says

**Decision.** Where the engine knows the shape of a reason, it sends a state plus the
facts, and the console builds the sentence. Where the reason is a driver's own text, it
is passed through as a detail, exactly as `last_error` already is.

**Rationale.** This is the contract P11 established and the console already follows it:
`format.ts` owns every rendered string, and `i18n/keys.ts` holds the catalogue. A channel
that did not answer is a state (`down`) plus a detail (whatever ffmpeg said); the sentence
around it is a translated key. Inventing English sentences in the engine for a
newly-Arabic console would be moving backwards.

**Consequence.** `SourceStatus` (`ok` / `down` / `auth`) is reused for a channel rather
than a new enum, plus one boolean for "we never got to this one". Three states and a flag
cover every case the spec's edge cases name, and add nothing to the vocabulary.

---

## Open — to check in code during implementation, not assumed

- **Whether `RecognitionWorker` and the patrol worker can share `watch()` unchanged.**
  Both are `FeatureWorker` subclasses and both key their state per camera, but the patrol
  tier is constructed from `identity_cameras` in `_start_patrol` and the two lists are
  complements of each other. Moving a camera into the identity tier must both `watch` it
  on the recogniser and `unwatch` it on patrol, in that order, or a frame could be
  analysed by neither.
- **Whether `SharedDetection` caches on `(camera_id, frame.sequence)` in a dict that
  grows per camera**, and therefore whether unwatching a camera leaks its cache entry.
- **Whether `TrackerPool.for_camera` allocates lazily** — the same question for tracking.
