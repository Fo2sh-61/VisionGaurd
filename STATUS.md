# VisionGuard — Status

**Updated:** 20 Aug 2026 · **Commit:** `d6ce423` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

## Feature state

| Feature | State |
|---|---|
| Camera ingest, stream, snapshot | **Real** — reconnect, NO SIGNAL, stale flagging all work |
| Attendance | **Real** — register, late cutoff, CSV export. Owner considers it done |
| Enrolment Studio | **Real** — `/people/enrol`, quality scoring, 3-photo floor. *Unauthenticated* |
| Live overlays | **Real** — each feature draws its own (faces / bodies / appearance IDs) |
| Tracking engine | **Real** — ByteTrack + appearance IDs, stable across frames and cameras |
| People counting | **Real for "Main entrance"** only (the laptop webcam). Over-counts — reads 4–6 for one person. Other areas are demo and labelled |
| System health | **Real** — honest per-subsystem, including startup failure reasons |
| Track a person | **Engine real, page part fake** — badge bug, clip save writes nothing |
| Restricted zones | **Fake** — occupancy computed every frame, then thrown away |
| Weapons, lost items | **Fake** — models present, no worker, no tables |
| Users, audit, notifications | **Fake** — no auth of any kind; audit lives in RAM |
| Mobile app | **Fake** — entirely fixtures, including random numbers |
| Fights | **Removed from scope** — no model; remnants still in code (P0-05 removes them) |

## P0 progress

Nine of ten done. Each shipped with its regression test.

| | | |
|---|---|---|
| P0-01 | fixture fallback killed | done |
| P0-02 | track badge reads the name | done |
| P0-03 | timezone per timestamp | done |
| P0-04 | person-mode late cutoff | done |
| P0-05 | fights removed | done |
| P0-06 | SQLite WAL + busy-timeout | done |
| P0-07 | dead buttons | done |
| P0-08 | error / empty / degraded states on every page | **not started** |
| P0-09 | person history + groups wired | done |
| P0-10 | CI: the four gates | done |

## Next 3 things

1. **P0-08** — the last P0. Error, empty and degraded states on every page
2. **Add a git remote** — the CI workflow is committed but nothing runs it yet
3. **P1-01** — one detection pass per camera per tick (F2: the detector runs twice per frame today)

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

**Gates verified 20 Aug 2026, all four green:** 375 passed, 6 skipped (46s) · pyflakes clean over `vg`, `tools` and `tests` · smoke start exit 0 · tsc clean.

Also verified on a **fresh clone with no `engine/data/` and no model weights** — the condition CI runs in: 374 passed, 7 skipped. The extra skip is the model-weights check, which has nothing to check on a machine that has no weights.

`.github/workflows/ci.yml` is committed but **has never run** — the repository has no git remote. Adding one is what turns it on.

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.
