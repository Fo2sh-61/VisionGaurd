# VisionGuard — for AI agents

Read this first. It is the short version; the full rules are in `.specify/memory/constitution.md`.

## What to read, in order

1. `.specify/memory/constitution.md` — the rules. Highest authority.
2. `docs/PLAN.md` — what to build, in what order.
3. `STATUS.md` — what is real today.
4. `docs/archive/` — history only. **Never plan from it.**

If a document disagrees with the code, the code wins and the document gets fixed.

## Rules that must never break

1. **A face names a person; clothing only says "same body."** Never merge them into one number or colour. Green = face, blue = clothing, amber = unidentified.
2. **Tracking never uses recognition to track.** A name is a live annotation on a body, never a stored binding carried forward. A leaked binding is what once made every person read as "Mohamed Fouad".
3. **Each feature draws its own overlay** — `_boxes(camera_id, feature)`. Tracking IDs on the attendance page was a real bug.
4. **Never show anything untrue.** No fixtures, random values, fake saves, or dead buttons in a production path. If something is unavailable, say so plainly with a reason.
5. **Never claim precision the code lacks.** Counting sums across cameras with no de-duplication. No capacity set means no percentage shown.
6. **Geometry crosses the API as fractions of the frame, never pixels.**
7. **Degradation is payload, never a 5xx.** System Health stays 200 even when everything it describes is broken.
8. **A subsystem that fails to start must say so in the UI**, not only in the log.
9. **A feature must never require another feature to be switched on.**
10. **Weapon detections always wait for a human.** False alarms stay in history; there is no delete.
11. **Track searches write the audit entry before returning the result.**

## Settled — do not reopen

- SFace is the permanent face model. Changing it invalidates every enrolment.
- The owner supplies all models. Never source, train, or download one.
- Database is the source of truth; `engine.yaml` is only the bootstrap seed.
- Ship `.pt`; build `.engine` on the target machine.
- ByteTrack and the appearance matcher are **not** neural nets and have **no GPU path**. Do not promise one.

## Adding a feature — four files, nothing else

| Step | File | What |
|---|---|---|
| 1 | `engine/vg/infer/<model>.py` | Load weights, return typed detections. Copy `infer/persons.py` |
| 2 | `engine/vg/features/<feature>.py` | Subclass `FeatureWorker`, implement `analyse(frame)`. Threading, rate limiting and boost are inherited — **write no concurrency code** |
| 3 | `engine/vg/events/<feature>.py` | Persist events. Copy `events/sightings.py` |
| 4 | `engine/vg/api/live.py` | Override the store method that currently returns fixtures |

Then add a `models:` entry in `engine.yaml` and the feature name to the camera's `features:` list. The API contract and both front ends stay untouched.

## Where things live

| Path | What |
|---|---|
| `engine/vg/config.py` | Reads `engine.yaml` + `.env`, validates everything |
| `engine/vg/ingest/` | Camera capture, reconnect, frame bus |
| `engine/vg/infer/` | Model runners — one file per model |
| `engine/vg/features/` | One file per product feature |
| `engine/vg/events/` | Database writes |
| `engine/vg/api/app.py` | Every endpoint |
| `engine/vg/api/store.py` | `MockStore` — the fixtures |
| `engine/vg/api/live.py` | `LiveStore` — **what it doesn't override is the to-do list** |
| `web/src/services/api.ts` | The only place the UI talks to the engine |
| `models/README.md` | What each model actually is. **Read before touching weapons** |
| `engine/data/footage/` | Recorded clips + 21 labelled ground-truth marks — the regression suite |

## How to work

```powershell
.\dev.ps1 doctor          # pre-flight
.\dev.ps1 up -Mock        # UI work — starts in under a second, no models
.\dev.ps1 up -Clip        # pipeline work — deterministic, uses the labelled clip
.\dev.ps1 down            # frees ports 8000 / 5173
```

- **Debug against the recorded clip, not the webcam.** It is identical every run, locks no device, and has 21 labelled ground-truth points. Use the webcam only for final confirmation.
- **Tests beat hot reload.** Write a test and run `pytest` — milliseconds, no server. Do not enable `--reload` on the engine; it orphans processes on Windows.
- Check types with `npx tsc -b --force`, never `tsc --noEmit` (project references make it a silent no-op).
- Every fix to a known bug ships **with its regression test in the same commit**.

## Verify your own work

You have a terminal. Use it — never hand back a change you have not run.

Before calling any task done:

1. `python -m pytest engine` — must be green, and the count must not drop.
2. `cd web; npx tsc -b --force` — must be clean.
3. `python -m pyflakes engine/vg engine/tools engine/tests` — catches the exact bug class that once silently killed face recognition.
4. For anything touching the pipeline: `.\dev.ps1 up -Clip` and confirm the behaviour on the recorded clip.

If a test fails and you did not cause it, say so plainly rather than fixing it quietly — a pre-existing failure is information.

Ask Mohamed for a manual check when something can only be confirmed by eye: camera latency, overlay correctness, a real face being recognised, or anything needing a live webcam.

## Working with Mohamed

- Ask about four short questions before acting on a non-trivial request. Surface the choices; don't decide for him.
- He prefers simple, plain language over jargon.
- Specs should be short. Fill the template's sections and stop.
- Report honestly. "Two of five tasks done, one blocked because X" is worth more than a claim of completion.

## Spec Kit

`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
Optional: `/speckit-clarify` before planning, `/speckit-analyze` before implementing.

Keep specs short — the template in `.specify/templates/spec-template.md` is deliberately lean. Fill its sections and stop.

Requirement numbering: `FR-xx` belongs to `docs/PLAN.md` (product level). Inside a spec, prefix with the phase — `P0-FR-001`. Never mix the two.
