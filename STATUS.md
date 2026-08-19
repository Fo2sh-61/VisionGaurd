# VisionGuard — Status

**Updated:** 19 Aug 2026 · **Commit:** `03f1fd7` · Plan: `docs/PLAN.md` · Rules: `.specify/memory/constitution.md`

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

## Next 3 things

1. **P0-01** — stop serving fake data when a subsystem is off (the biggest single risk)
2. **P0-03** — fix the timezone before Egypt's DST change in late October
3. **P0-06** — SQLite WAL + busy-timeout (one hour of work, prevents lost events)

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

Tests: `python -m pytest engine` · `cd web; npx tsc -b --force`
(**not** `tsc --noEmit` — project references make it a silent no-op)

No `.venv` yet — deliberately blocked on the re-ID handover. System Python 3.14 works: torch 2.11.0+cu128, CUDA true on an RTX 2080.

**Test count unverified this cycle.** `HANDOFF.md` reported 270 passing; nobody has re-run it since. P0-10 fixes that.

## Housekeeping

`_to_delete/` at the repo root holds an install zip and git lock litter — safe to delete manually.
