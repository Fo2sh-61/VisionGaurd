# VisionGuard — Status

**Updated:** 23 Aug 2026 · **Commit:** `e101db1` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

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
| Users, audit, notifications | **Auth is real** (P2) — argon2 accounts, server-enforced roles, sessions revocable. Audit still lives in RAM |
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
| P1-04 | latency / queue / drop metrics on System Health | not started |
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

**Gates verified 23 Aug 2026, all four green:** 839 passed, 6 skipped · pyflakes clean over `vg`, `tools` and `tests` · smoke start exit 0 · tsc clean. (Was 811 passed before lost bag search; it added 28 tests.)

Also verified on a **fresh clone with no `engine/data/` and no model weights** — the condition CI runs in: 374 passed, 7 skipped. The extra skip is the model-weights check, which has nothing to check on a machine that has no weights.

`.github/workflows/ci.yml` is committed and the repo now has a remote (`Fo2sh-61/VisionGaurd`, private), so it runs on push. **It has not been observed passing yet** — nobody has checked the first run.

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.

## Measured, not assumed

Person detection on the RTX 2080 Max-Q, `python engine/tools/benchmark.py`:
**p95 18 ms**, 57.5 frames/sec, against a 250 ms budget. Re-run it on the
deployment machine — this is a power-limited laptop GPU without TensorRT.

Throughput, not latency, is what sizes the hardware. See `docs/PLAN.md` §7.
