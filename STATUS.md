# VisionGuard — Status

**Updated:** 20 Aug 2026 · **Commit:** `a4a5ea8` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

## Feature state

| Feature | State |
|---|---|
| Camera ingest, stream, snapshot | **Real** — reconnect, NO SIGNAL, stale flagging all work |
| Attendance | **Real** — register, late cutoff, CSV export. Owner considers it done |
| Enrolment Studio | **Real** — `/people/enrol`, quality scoring, 3-photo floor. *Unauthenticated* |
| Live overlays | **Real** — each feature draws its own (faces / bodies / appearance IDs) |
| Tracking engine | **Real** — ByteTrack + appearance IDs, stable across frames and cameras. Shares one detection pass with counting (P1-01) |
| People counting | **Real for "Main entrance"** only (the laptop webcam). Over-counts — reads 4–6 for one person. Other areas are demo and labelled |
| System health | **Real** — honest per-subsystem, including startup failure reasons |
| Track a person | **Engine real, page part fake** — badge bug, clip save writes nothing |
| Restricted zones | **Fake** — occupancy computed every frame, then thrown away |
| Weapons, lost items | **Fake** — models present, no worker, no tables. The pages now say so instead of showing an all-clear (P0-08) |
| Users, audit, notifications | **Fake** — no auth of any kind; audit lives in RAM |
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

## Next 3 things

1. **P1-02** — overlay freshness, so a stale box degrades honestly
2. **P1-04** — latency and drop metrics on System Health (the benchmark tool already measures the hard part)
3. **P2** — login and roles. Still nothing stops anyone opening the console

## Blocked on the owner

- **Re-ID model** + architecture + how it loads + Python version → blocks `.venv` and track
- **Trained weapons model** → blocks honest weapon scoring
- **Consent / lawful basis for biometrics of minors** → blocks deployment entirely
- **Target hardware** → blocks the 208-camera plan
- **Rotate the Kaggle key** in `models/knife detection/kaggle.json`

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

**Gates verified 20 Aug 2026, all four green:** 436 passed, 6 skipped (44s) · pyflakes clean over `vg`, `tools` and `tests` · smoke start exit 0 · tsc clean.

Also verified on a **fresh clone with no `engine/data/` and no model weights** — the condition CI runs in: 374 passed, 7 skipped. The extra skip is the model-weights check, which has nothing to check on a machine that has no weights.

`.github/workflows/ci.yml` is committed and the repo now has a remote (`Fo2sh-61/VisionGaurd`, private), so it runs on push. **It has not been observed passing yet** — nobody has checked the first run.

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.

## Measured, not assumed

Person detection on the RTX 2080 Max-Q, `python engine/tools/benchmark.py`:
**p95 18 ms**, 57.5 frames/sec, against a 250 ms budget. Re-run it on the
deployment machine — this is a power-limited laptop GPU without TensorRT.

Throughput, not latency, is what sizes the hardware. See `docs/PLAN.md` §7.
