# VisionGuard

School campus vision system for Greenfield International School — a console that answers questions about campus activity (attendance, headcounts, restricted zones, weapons, lost items, where a person went) with the footage attached.

```
engine/    Python FastAPI + OpenCV/YOLO backend — the vision engine and API
web/       React desktop console — wired to the engine
mobile/    React phone app — still on fixtures
models/    Model weights (untracked) + what each one actually is
design/    Design documents the apps were built from
docs/      Plan, architecture decisions, and archived history
```

## Run it

```powershell
.\dev.ps1 doctor                     # pre-flight checks — run first
.\dev.ps1 up -Mock                   # UI work: instant start, no models, no camera
.\dev.ps1 up -Clip                   # pipeline work: deterministic recorded clip
.\dev.ps1 up -AllowSystemPython      # real cameras
.\dev.ps1 down                       # stop everything, free the ports
```

Console at `http://localhost:5173`, engine at `http://127.0.0.1:8000`, API docs at `/docs`.

There is no `.venv` yet — deliberately, until the re-ID model handover decides the Python version. System Python 3.14 works (torch 2.11.0+cu128, CUDA on an RTX 2080).

## Test it

```powershell
python -m pytest engine
cd web; npx tsc -b --force     # NOT --noEmit: project references make it a silent no-op
```

## Current state

Camera ingest, attendance, browser enrolment, live overlays, the tracking engine, and counting for one area run on **real data**. Restricted zones, weapons, lost items, users, audit and notifications are **still fixtures**, and there is **no authentication yet**.

`STATUS.md` has the honest per-feature breakdown. Do not show this to a school as finished until `docs/PLAN.md` says the release gates are met.

## The documents

| File | What it is |
|---|---|
| `.specify/memory/constitution.md` | The engineering rules. Highest authority |
| `docs/PLAN.md` | What to build and in what order. The only plan |
| `STATUS.md` | What is real today, and what's blocked |
| `AGENTS.md` | Entry point for AI coding agents |
| `docs/archive/` | Superseded documents, kept for history. **Never plan from these** |

## How it works, briefly

Cameras feed a frame bus. One person-detection pass fans out to counting, zones and tracking; face recognition runs separately on entrance cameras only. Workers turn frames into events, events go to SQLite, and the API serves both apps.

Two identity signals are kept deliberately separate: **a face names a person, clothing only says "the same body."** They are never merged — green means identified by face, blue means matched by appearance.

Adding a feature touches four files and nothing else — see `AGENTS.md`.
