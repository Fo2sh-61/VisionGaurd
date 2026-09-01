# Contributing to VisionGuard

`AGENTS.md` is the real guide — the codebase's shape, the rules that must never
break, the idioms to copy. Read it first. This file is the shorter human
version: how to get running, and what a change has to satisfy before it lands.

## Get running

```powershell
.\dev.ps1 doctor              # pre-flight checks. Run this first
.\dev.ps1 up -Mock            # UI work: starts in under a second, no models
.\dev.ps1 up -Clip            # pipeline work: the deterministic recorded clip
.\dev.ps1 up -AllowSystemPython   # real cameras
.\dev.ps1 down                # stop everything, free ports 8000 and 5173
```

Console at `http://localhost:5173`, engine at `http://127.0.0.1:8000`,
API reference at `/docs`.

There is no `.venv` yet, deliberately, until the re-ID model handover settles
the Python version. System Python 3.14 works.

One extra install the first time — the appearance matcher is a package in this
repository, not something on the path:

```powershell
pip install -e vendor/loiterwatch
```

## Debug against the clip, not the webcam

The recorded clip is identical every run, locks no device, and carries 21
labelled ground-truth points. Use a real camera only for final confirmation.

Tests beat hot reload: write a test and run pytest — milliseconds, no server.
Do not enable `--reload` on the engine; it orphans processes on Windows.

## The four gates

Every change runs all four before it is handed over. Not a formality — each one
exists because something got through.

```powershell
python -m pytest engine                        # green, and the count must not drop
cd web; npx tsc -b --force                     # NOT --noEmit: project references
                                               # make that a silent no-op
python -m pyflakes engine/vg engine/tools engine/tests
.\dev.ps1 up -Clip                             # anything touching the pipeline
```

If a test fails and you did not cause it, **say so** rather than fixing it
quietly. A pre-existing failure is information.

## What a change must satisfy

- **Every fix to a known bug ships with its regression test in the same
  commit.** Not the next one.
- **Never show anything untrue.** No fixtures, random values, fake saves or
  dead buttons on a production path. If something is unavailable, the interface
  says so, with a reason.
- **A face names a person; clothing only says "the same body."** These two
  signals are never merged. Green means identified by face, blue means matched
  by appearance, amber means unidentified.
- **Line endings.** The repository is deliberately mixed and `.gitattributes`
  freezes it. Editing with a script that reads and writes *text* rewrites every
  ending and turns a six-line change into a whole-file diff. Read and write
  bytes. `git diff --stat` catches it.

`AGENTS.md` has the full list of eleven rules and the settled decisions that
are not to be reopened.

## Adding a feature — four files

A new detector touches four files and nothing else. The API contract and both
front ends stay untouched.

| # | File | What |
|---|---|---|
| 1 | `engine/vg/infer/<model>.py` | Load weights, return typed detections. Copy `infer/persons.py` |
| 2 | `engine/vg/features/<feature>.py` | Subclass `FeatureWorker`, implement `analyse(frame)`. **Write no concurrency code** — threading, rate limiting and boost are inherited |
| 3 | `engine/vg/events/<feature>.py` | Persist events. Copy `events/sightings.py` |
| 4 | `engine/vg/api/live.py` | Override the store method that currently returns fixtures |

Then add a `models:` entry in `engine/engine.yaml` and the feature name to the
camera's `features:` list.

`LiveStore` in `api/live.py` is worth knowing by heart: **what it does not
override is the to-do list.**

## Branches and commits

Feature work happens on a branch named after its spec — `010-ask`,
`007-vehicle-gate-tuning`. `.specify/scripts/powershell/create-new-feature.ps1`
opens both the branch and the spec folder together.

Commit subjects here describe **what changed for the user**, not which files
moved. The existing log is the style guide:

> The gate recorded nine cars and showed none of them
> A guard who reads no English can now read the console
> One character wrong, one keystroke to fix

## Specs

`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
Optional: `/speckit-clarify` before planning, `/speckit-analyze` before
implementing.

Keep specs short. The template in `.specify/templates/spec-template.md` is
deliberately lean — fill its sections and stop.

Requirement numbering: `FR-xx` belongs to `docs/PLAN.md` at the product level.
Inside a spec, prefix with the phase: `P0-FR-001`. Never mix the two.

## The authorities, in order

1. `.specify/memory/constitution.md` — the engineering rules. Highest authority
2. `docs/PLAN.md` — what to build, in what order. The only plan
3. `STATUS.md` — what is real today
4. `AGENTS.md` — how to work in this codebase

If a document disagrees with the code, **the code wins and the document gets
fixed** in the same change.
