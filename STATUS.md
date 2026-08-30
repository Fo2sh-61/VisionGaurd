# VisionGuard — Status

**Updated:** 24 Aug 2026 · **Commit:** `e9ba8dd` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

## Feature state

| Feature | State |
|---|---|
| Camera ingest, stream, snapshot | **Real** — reconnect, NO SIGNAL, stale flagging all work |
| Attendance | **Real** — register, late cutoff, CSV export. Owner considers it done |
| Enrolment Studio | **Real** — `/people/enrol`, quality scoring, 5-photo floor (nobody is enrolled without them). Admin-only (P2). Live moving view with the detected face outlined and its five feature points tracking it, plain-language guidance, and a way back at every step |
| People page | **Real** — every column explains itself: recognition state with photo count, enrolled date, last seen (camera and time) or "Not seen yet", today's attendance. Any row opens that person's history. Administrators can remove somebody: face data and directory entry go and they stop being recognised without a restart, audited first. Their past sightings are kept, unreachable from any page, until P3's erasure |
| Live overlays | **Real** — each feature draws its own (faces / bodies / appearance IDs) |
| Tracking engine | **Real** — ByteTrack + appearance IDs, stable across frames and cameras. Shares one detection pass with counting (P1-01) |
| People counting | **Real for "Main entrance"** only (the laptop webcam). Over-counts — reads 4–6 for one person. Other areas are demo and labelled |
| System health | **Real** — honest per-subsystem, including startup failure reasons |
| Track a person | **Real** — live: click a body and it is followed across cameras, named only after a sustained face, recorded one file per camera with the stop reason. Past: stops answer instantly from the anchor table, each with its evidence, and play back as 30s chunks off the footage/DVR archive. Sweeps refuse over a measured budget |
| Restricted zones | **Real** — any camera can be marked restricted; its whole frame is the zone. Scenes are logged and recorded, last three clips kept per camera, log refreshes itself. No schedules |
| Knife detection | **Real** (P6) — the owner's trained knife model runs on every enabled camera, but only on frames with a person in them and only for knives held by one. Three sightings over a second open one entry with one video; two seconds without a knife closes it and ends the video (owner set this, down from ten, after testing with a real knife — the cost is that a blink longer than two seconds splits one incident into two entries). Every entry waits for a person to press Confirm or False alarm, recorded against the signed-in account and audited before the write. Videos are kept 30 days, entries for ever. **No alerts fan out** — nothing is sent to anybody. **False-alarm rate is not zero**: a live loop of the recorded clip raised one 12.5 s entry at 0.76 on footage with no knife (roughly one per four loops). Accuracy on a real knife is unmeasured |
| Lost bag | **Real** (P7) — tick cameras, pick a colour, and any bag of that colour is outlined live on the tiles. There is no search and no job: the tile's own overlay poll is what makes the model run, so it works only on cameras somebody is looking at and stops within seconds of them leaving the page. Idle cost is zero. **Nothing is recorded** — no clip, no still, no history, so a bag taken before you opened the page cannot be found. **Nothing is alerted.** **Accuracy on real bags is unmeasured** — there is no clip with a bag in it. On footage with *no* bag it is now quiet: 1 false bag across 399 sampled frames, after switching from the fine-tuned `bagbest.pt` (17, including a black office chair read as a suitcase at 0.88) to `bagsearch.pt`, a YOLO-World prompted with nine words for "bag". A box still means *possible bag*, in amber, over a live picture the operator judges themselves |
| Vehicle gate | **Real** — a camera with a gate number and a direction reads plates. Nothing is recorded from one frame: frames vote (confidence × plausibility × plate size), near-identical readings merge, and a pass is written only when three agree; the same plate at the same camera inside a minute is one pass. Each pass keeps a photograph and a plate crop, deleted at 30 days, row kept for ever. A weak read is kept and flagged, never discarded. The register imports from Excel or CSV in English or Arabic and collapses both digit systems onto one row; a pass reads as registered, not registered, blacklisted or expired, frozen at the moment it happened and never rewritten. A guard reads, an administrator writes and exports, and the export is audited before the file is built. **Nothing is blocked and nothing is alerted** — a blacklisted car raises an item on Home and no message goes anywhere. **"Inside now" needs an exit camera**: with only `cam-laptop` as gate 1 entry, the page says no exit camera is configured rather than printing a paired figure, and a visit closed by the car re-entering is marked an estimated exit. An administrator can **delete one pass** — the row, the photograph and the plate crop go for good, and the audit entry that names the plate stays. **Accuracy: measured for the first time on 27 Aug** against the owner's EALPR set (2,086 photos, 2,142 plates), and the news is good and bad. Our port reproduces the project it came from **exactly** - 2086/2086 identical readings, so the software is not the bug. Plate detection is 99.8%. But the two accelerations that were reverted on 24 Aug are worse than anyone guessed: FP16 changes 6.7% of readings and the TensorRT plan changes **26.6%** - one reading in four on a model that classifies single characters. Both stay off for good; the plate models run the `.pt` at FP32 and no `--fp32` engine experiment is worth building. **What is still unmeasured is the thing that matters**: that dataset is what the models were trained on, so it proves pipeline fidelity and says nothing about the school's gate. Read accuracy on real plates needs a human-confirmed truth file (`python engine/tools/eval_plates.py --label`, waiting on Mohamed) and site captures. See `specs/007-vehicle-gate-tuning/evidence/`. **Two older fixes stand**: the band-stripped greyscale crop bug (fixed 24 Aug, pinned by a test), and three found the same day - the overlay poll refused by request validation, plate reading never boosting while somebody watched, and the repeat window being hardcoded rather than `vehicles.dedupe_seconds`. **And one more, found 27 Aug**: gate tiles had *still* never drawn a plate box, because the 24 Aug fix repaired the request while the response failed one layer down - `kind="plate"` was missing from the wire contract's `Box.kind`, so a plate in view took the whole overlay down. Fixed, and pinned by a test that ends at a validated `CameraView` rather than at the box. Boxes now also carry the plate's width in pixels as an aiming aid |
| Users, audit, notifications | **Auth is real** (P2) — argon2 accounts, server-enforced roles, sessions revocable. Audit still lives in RAM |
| Ask | **Real** (P12) — type a question in Arabic, Franco-Arabic, English or a mixture and it runs one of **fourteen existing queries** and shows that query's real result: figures, rows, camera, time, confidence, and the clip where the query already has one. "Track Ali" comes back as Ali's stops, not a link to the Track page. Every answer carries an **"understood as" line** naming the query and its parameters, and marks any parameter it assumed (a question with no date means today, and says so). Names and plates are **masked locally before anything leaves the site**, across both scripts and both digit systems — سارة, ساره, Sara and Sarah are one person, and a plate in Arabic-Indic digits matches the register's Western ones. A first name two children share is masked to a placeholder that resolves to nobody, and Ask asks which one rather than guessing. **A word the site does not recognise is sent as typed** — a visitor's name does leave — and the answer names those words; administrators see the exact text that left. Read-only, and every question is audited **before** the answer is built, including questions asked while the cloud is down. Four honest states, each with its own message and reason: out of scope, one detail missing, an unknown person (which is *not* an absence), and unavailable. **Lost items cannot be asked about** — bag search runs live on watched tiles and stores nothing, so Ask says there is no history to search and offers the page. **The provider is Gemini's free tier**, whose terms allow Google to use submitted content and human reviewers to read it; accepted on 30 Aug 2026 because masking reduces what leaves to "when did PERSON_1 arrive today?". Linking billing turns that off with no code change. **Routing accuracy measured 30 Aug 2026: 91.9%, against an SC-003 bar of 95% — so SC-003 is NOT met.** 34 of 37 corpus questions, on `gemini-3.5-flash-lite`. Egyptian dialect is the weak side at 83% against 94% for English, which matters because dialect is what the guards type; Franco-Arabic, mixed script and MSA all scored 100%. The configured `gemini-3.7-flash` is **unmeasurable on the free tier** — Google's API returns `limit: 20` requests, not the 1,500/day the published guides claim, and one corpus run is 37 questions. Full figures and every wrong route in `specs/010-ask/evidence/routing.md`. `--dry-run` proves the masking with no key and no network: **0 identifiers leak across 37 questions**. **The Arabic wording is drafted by me and not yet read by a native speaker**, so it renders only in dev until Mohamed corrects it |
| Mobile app | **Fake** — entirely fixtures, including random numbers |
| Fights | **Removed from scope** — no model. Page, endpoints and mock methods all gone (P0-05) |

## P0 progress

**All ten done.** Each shipped with its regression test.

| | | |
|---|---|---|
| P0-01 | fixture fallback killed | done |
| P0-02 | track badge reads the name | done |
| P0-03 | timezone per timestamp | done |
| P0-04 | person-mode late cutoff | done |
| P0-05 | fights removed | done |
| P0-06 | SQLite WAL + busy-timeout | done |
| P0-07 | dead buttons | done |
| P0-08 | error / empty / degraded states on every page | done |
| P0-09 | person history + groups wired | done |
| P0-10 | CI: the four gates | done |

## P1 progress

| | | |
|---|---|---|
| P1-01 | one detection pass per frame, one thread in the model | done |
| P1-02 | overlay freshness (`age_ms`) in API and UI | not started |
| P1-03 | private `_tracked_boxes` reach-in removed | done |
| P1-04 | latency / queue / drop metrics on System Health | **done** (P8, 30 Aug 2026) |
| P1-05 | isolation test: kill one feature, prove the other survives | not started |
| P1-06 | measure and publish the latency budgets | done |

## P2 — security · **done**

Every endpoint except `/healthz` and `/auth/login` refuses an anonymous caller.
Roles are enforced server-side from the path, so a new endpoint under
`/enrolment`, `/sources` or `/users` is admin-only the day it is written.
Editing the browser achieves nothing — a test asserts the console stores no
role, account or token.

**Create the first account before starting the engine, or nobody can sign in:**

```powershell
python engine/tools/create_user.py
```

## Workload placement (30 Aug 2026) — `specs/009-workload-placement`

Removing processor work nothing reads. Measured before and after with
`benchmark.py --site`; full figures in `specs/009-workload-placement/measurements.md`.

| | |
|---|---|
| Before, 100 cameras | **23.03 s** of processor time per second — 3 boxes |
| After | **9.17 s/s** — 2 boxes; one 8-core box carries 87 cameras, up from 34 |

23.03 corroborates the Workload Plan's ~25 figure, which matters because that
document is not in this repository.

**Decode was 65% of the bill** — frames pulled off cameras nobody was watching
and thrown away. Unwatched cameras now grab every frame (so no lag builds up)
and decode only at the analytics rate. That one change is most of the saving.

| Change | State |
|---|---|
| Patrol face recognition off | **on** — `patrol_hz: 0` is now the default |
| Capture unwatched at the analytics rate | **on** — `live_capture: watched` |
| Batch the shared person pass | shipped, **off**, and buys nothing yet — see below |
| Face detection gated to person crops | shipped, **off** by default — see below |
| Bag TensorRT removal | **rejected on measurement** |

**Face gating is off because it cannot prove it is safe.** `compare_detections.py
--gate-check` finds every face either way — 60 of 60 — but boxes land up to 11px
apart, because YuNet on a crop is a different computation from YuNet on a frame.
That moves the landmarks, and the landmarks decide which patch gets embedded. It
waits on a measurement against a real enrolled roll.

**Batching cannot work on TensorRT.** The compiled engines have a fixed batch size of 1 and raise when handed several frames. That exception lands where `FeatureWorker` catches it per frame, so switching batching on would have made detection **quietly stop** — a log line nobody reads and boxes silently missing. It now detects this once, says so, and runs one frame at a time. Rebuilding the engines with a dynamic batch would unlock it; P8-FR-018 says not before the GPU driver is current.

**The capture change nearly cost more than it saved.** Skipping the decode only helps if grabbing a frame WAITS for one. On RTSP it does; on a webcam it returns instantly, and the loop spun at 658,000 grabs a second - a whole core per camera, which would have looked like a busy machine rather than a bug. It now paces itself: 653 grabs where there were 1.3 million, same 5 Hz decoded.

**The bag TensorRT claim was wrong.** Deleting the engine was supposed to be "a
free ~31%". Measured: TensorRT 23.3 ms p95, PyTorch 29.0 ms. No saving, and
TensorRT is better where it counts. Reverted.

**SC-001 is not met.** The target was ≤5 s/s and the result is 9.17. The gap is
face gating, which is off for the reason above. 60% of the waste is gone, not 80%.

**Patrol off is visible, not silent.** Track a Person now says when only the
entrance cameras were looking for faces, so a thinner path cannot read as a
person who was not there.

**System Health shows real load** — per worker: frames processed, last inference
ms, queue depth, dropped frames, and whether it is behind. Frames deliberately
not decoded are counted separately from frames dropped; they are not the same
thing. Per-worker processor share is **not** shown: workers are threads in one
process, so that number could only be invented.

Found and not fixed: **`accelerate: false` is silently ignored for the bag and
person models** — neither passes it to `load_model`. It works for plates only.

## Next 3 things

1. **P1-02** — overlay freshness, so a stale box degrades honestly
2. **P1-04** — latency and drop metrics on System Health
3. **P3** — durable events: alerts and audit still vanish on restart

## Blocked on the owner

- **Re-ID model** + architecture + how it loads + Python version → blocks `.venv` and track
- **A recorded clip with a knife in it** → the regression suite has 21 labelled ground-truth marks and not one knife, so knife accuracy on real footage is still unmeasured
- **A recorded clip with a bag in it** → same gap on the other side: bag detection is proved not to fire on furniture-only footage but has never been shown to find a real bag. `python engine/tools/record.py` writes one
- **Consent / lawful basis for biometrics of minors** → blocks deployment entirely
- **Target hardware** → blocks the 208-camera plan
- **Rotate the Kaggle key** that was in `models/knife detection/kaggle.json`. The folder and the file are gone from disk and were never in git, but a key that once sat in a working tree is a key to rotate

## Run it

```powershell
.\dev.ps1 doctor                     # pre-flight, run each morning
.\dev.ps1 up -Mock                   # UI work — instant, no models
.\dev.ps1 up -Clip                   # pipeline work — deterministic
.\dev.ps1 up -AllowSystemPython      # real cameras — final check only
.\dev.ps1 down                       # panic button, frees 8000/5173
```

Tests: `.\dev.ps1 test` runs all four gates — pyflakes, pytest, smoke start, tsc.
(tsc is **not** `--noEmit` — project references make it a silent no-op)

No `.venv` yet — deliberately blocked on the re-ID handover. System Python 3.14 works: torch 2.11.0+cu128, CUDA true on an RTX 2080.

**Gates verified 27 Aug 2026, all four green:** 1,246 passed, 6 skipped · pyflakes clean over `vg`, `tools` and `tests` · tsc clean. (Was 1,128 before the vehicle-gate second pass; it added 118 tests.)

**Run pytest from the repo root**, as `python -m pytest engine`. Three tests in `test_track_page.py` read `web/vite.config.ts` and `engine/tools/measure_track.py` by relative path, so running from inside `engine/` fails them on a missing file — nothing is wrong with the product, and they pass from the root. Worth fixing the paths one day; `tests/test_eval_plates.py` shows the pattern (derive from `__file__`).

Also verified on a **fresh clone with no `engine/data/` and no model weights** — the condition CI runs in: 374 passed, 7 skipped. The extra skip is the model-weights check, which has nothing to check on a machine that has no weights.

`.github/workflows/ci.yml` is committed and the repo now has a remote (`Fo2sh-61/VisionGaurd`, private), so it runs on push. **It has not been observed passing yet** — nobody has checked the first run.

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.

## Measured, not assumed

Person detection on the RTX 2080 Max-Q, `python engine/tools/benchmark.py`:
**p95 18 ms**, 57.5 frames/sec, against a 250 ms budget. Re-run it on the
deployment machine — this is a power-limited laptop GPU without TensorRT.

Throughput, not latency, is what sizes the hardware. See `docs/PLAN.md` §7.
