# Quickstart: proving Workload Placement

How to check each claim by hand. Every command runs from the repository root.
See `contracts/config.md` for the keys and `data-model.md` for the wire shape.

## 0. Before anything

```powershell
.\dev.ps1 doctor
python -m pytest engine -q
python engine/tools/benchmark.py
python engine/tools/benchmark.py --model bags
```

Record the pass/skip count and the two throughput figures. **Two failures are expected
today** on this branch — `test_api.py::TestWireShape::test_everything_is_camel_case` and
`::test_time_is_utc_plus_an_explicit_site_offset` — and are not caused by this feature
(research, "Open"). If anything else fails, stop: the baseline is not clean.

## 1. The before/after number (SC-001)

```powershell
python engine/tools/benchmark.py --site 100
```

Prints, for a stated camera count and feature mix: site seconds of processor time per
second, the same figure per camera, and how many cameras of that mix fit on one 8-core
machine and one GPU. Run it before the first change and after the last.

**Pass:** site demand falls from ~25 s/s to ≤ ~5 s/s; per camera ~0.25 → ~0.05.
**Read the output honestly:** measured per-model timings and the projected site
arithmetic are printed in separate blocks (P8-FR-031). The projection is arithmetic on
this machine's timings, not an observation of a hundred cameras.

Camera count is an argument, not a constant — `--site 40`, `--site 208` all answer.

## 2. Detections are identical (SC-002) — the gate

```powershell
python engine/tools/compare_detections.py --record before.json
# apply one change
python engine/tools/compare_detections.py --record after.json
python engine/tools/compare_detections.py --diff before.json after.json
```

Replays `engine/data/footage/walk-through_*.mp4` and records, per frame: person boxes,
face boxes with identities and scores, and plate reads. Then diffs the two.

**Pass:** `identical`. Any difference on any of the 21 ground-truth marks fails, and
P8-FR-002 says the change is rejected rather than shipped behind a flag.

It drives the models directly over clip frames in order — **not** through the live
worker threads. Threads rate-limit independently, so a live run does not sample the
same frames twice and the diff would report scheduling noise as a regression.

**Run this around change 2 above all.** It is the only change that can move a result.

## 3. Each change, one at a time

### Change 1 — patrol off
Set `tracking.patrol_hz: 0`, restart, watch the log for
`patrol recognition is switched off (tracking.patrol_hz: 0)`.

```powershell
.\dev.ps1 up -Clip
```

**Pass:** attendance still names people on `faces: true` cameras. Track a Person still
works and **says plainly** that names come only from identity-tier cameras (P8-FR-008).
It must not just quietly return fewer named stops.

### Change 5 — bag acceleration
Set `models.bags.accelerate: false`, then:

```powershell
python engine/tools/benchmark.py --model bags
```

**Pass:** System Health shows the bag model as `PyTorch CUDA`, not `TensorRT`, and the
throughput figure moves. Do **not** rebuild any `.engine` until the GPU driver is
current (P8-FR-018). Until FP16 is actually re-measured, it reads as not measured — never
estimated (P8-FR-019).

### Change 3 — batching
Set `models.person.batch: true`, restart with several cameras enabled.

**Pass:** `python engine/tools/benchmark.py --site 100` improves; `compare_detections`
says identical; person-detect p95 still ≤ 250 ms. A single camera must be no slower than
before — that is P8-FR-011, no waiting for company.

### Change 2 — face gating
Set `face_gate: person` on `cam-laptop`. **Run §2 before and after.**

**Pass:** `identical`, on faces *and* on the identities attached to them. Then set
`face_gate: frame` and confirm the old behaviour returns.

Watch for the crop-origin bug: if face boxes are drawn in the wrong place on the live
overlay, the crop offset was not added back before converting to fractions (research D3).

### Change 4 — capture rate
Set `live_capture: watched`, restart.

**Pass, by eye — ask Mohamed:**
- Open a camera that nobody has been watching. Picture is current and smooth **within 1
  second** (P8-FR-014).
- Leave the page; within seconds the camera drops back (P8-FR-015).
- Reopen it. Still within 1 second — no accumulated lag, because grabbing never stopped.
- Analysis is unchanged while unwatched: zone breaches, knife entries, counting and
  plate reads all still happen with nobody looking (P8-FR-013).
- A disconnected camera still shows NO SIGNAL within its budget and is never labelled
  LIVE (P8-FR-016).

## 4. Honest load (SC-003)

Open **System Health** with the engine under load.

**Pass:** each running worker shows frames processed, last inference ms, queue depth and
dropped frames. A worker that is behind is **named**, and the stage severity rises to
warn. A stopped worker is absent from the list, not shown with zeros. If process CPU or
GPU cannot be read, it says so with a reason — never `0%`.

```powershell
curl.exe -s http://127.0.0.1:8000/system/health
```

**Pass:** 200, always — even with every subsystem down (`bare_live_store` covers this in
test).

## 5. Latency budgets still met (SC-006)

```powershell
python engine/tools/benchmark.py
python engine/tools/benchmark.py --model weapons
python engine/tools/measure_latency.py
```

**Pass:** person ≤ 250 ms p95 (22.3 ms on 22–23 Aug 2026), knife ≤ 250 ms p95 (17.4 ms).
Re-check after **every** change, not once at the end (P8-FR-024).

## 6. Reversal (SC-004)

For each of the five keys in `contracts/config.md`: set it back, restart, confirm the old
behaviour returns. **No code edit, no rebuild, no migration, no re-enrolment.**

Then reverse one and leave the other four applied — confirm the four are unaffected
(P8-FR-003). Deleting `models/bagsearch-640.engine` is *not* the mechanism for change 5;
`accelerate: false` is, precisely so this test can pass.

## 7. The four gates before calling anything done

```powershell
python -m pytest engine
cd web; npx tsc -b --force
python -m pyflakes engine/vg engine/tools engine/tests
```

Plus `.\dev.ps1 up -Clip` and confirm the behaviour on the recorded clip. Test count must
not drop.
