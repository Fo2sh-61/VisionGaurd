# VisionGuard — handoff

**Updated:** 18 Aug 2026 · Read `DEV_PLAN.md` Part 0 for settled decisions.

## How to work with Mohamed

- **Ask 4 questions** (AskUserQuestion) before acting on any request. Simple,
  plain language. He wants choices surfaced, not decided for him.
- **TensorRT everywhere** is a stated goal. Not installed yet; version 10.15.1.29
  exists only in the severed British School venv, so `pip install tensorrt` fresh.
  ByteTrack and loiterwatch's appearance matching are NOT neural nets and have no
  GPU path — say so rather than promising one.
- He supplies all models. Never source or train them.

## Run it

```powershell
.\dev.ps1 doctor          # pre-flight
.\dev.ps1 up              # engine + web
.\dev.ps1 down            # panic button — frees 8000/5173
```

No `.venv` yet (blocked on the re-ID handover). System Python 3.14 works:
torch 2.11.0+cu128, CUDA True on an RTX 2080. Use `-AllowSystemPython`.

**Checks:** `python -m pytest engine` (270 pass) · `cd web && npx tsc -b --force`
(NOT `tsc --noEmit` — project references make that a silent no-op).

## What is REAL

| Feature | State |
|---|---|
| Attendance | Real. Done, per Mohamed. |
| Enrolment Studio | Real — `/people/enrol`, staged photos, quality scoring, 3-photo floor. |
| Live cameras | Real, with per-feature overlays. |
| **People counting** | **Real for "Main entrance" (= the laptop webcam).** Polls 1s, live stream + YOLO boxes, capacity 40 from `engine.yaml` `areas:`, history recording to `area_count` every 60s, bars split per zone. Other areas are demo, visibly labelled. |
| Tracking (engine) | Real. ByteTrack + loiterwatch appearance IDs, stable across frames/cameras. `/tracking/live` returns real IDs. |

## What is still FAKE

- **Track a person UI** — badges, confidence, past-path fallback. Clip "save"
  writes nothing.
- Weapons / Lost bag / Ask page — fixtures.
- Counting areas other than Main entrance.

## Immediate next steps

1. **Track badge bug (small).** The box correctly shows the name, but the subject
   bar says "Not identified by face" — because the page derives `identified` from
   `match`, and `_tracked_boxes` sets `match=APPEARANCE` *always* (the box exists
   because of clothing). Derive it from whether a **name** is present instead.
2. **Clear Track's remaining fake data** — show only real sightings.
3. **Clip recording.** Agreed design: continuous export of whatever was on the
   *main view*, stitched into one video across the camera sequence the operator
   (or auto-follow) produced. Nothing is written today.
4. **Counting accuracy.** Reads 4–6 with one person present. `person.conf` is
   0.35 in `engine.yaml` and `PeopleWorker` ignores the `min_area` gate that
   `PersonDetector.detect()` already supports. Needs tuning against his scene.

## Rules that must not break

1. **A face names a person; clothing only says "same body".** Never merge them
   into one number or colour. Green = face, blue = clothing, amber = unidentified.
2. **Tracking never uses recognition to track.** Names are a live annotation on
   top. A stored name-binding leaking across identities is what made every person
   read as "Mohamed Fouad".
3. **Each feature draws its own camera overlay.** `_boxes(camera_id, feature)` —
   `attendance` gets faces, `track` gets appearance IDs, `counting` gets unlabelled
   bodies. Putting tracking IDs on the attendance page was a real bug.
4. **Never claim precision the code lacks.** Counting SUMS across cameras with no
   de-duplication (`deduplicated: False`). No capacity set = no percentage shown.
5. Geometry crosses the API as **fractions**, never pixels.
6. Degradation is **payload, not 5xx**.

## Design

`design/18-8 design/VisionGuard.dc.html` is current and implemented. Fights was
removed entirely; Home→Ask, Lost items→Lost bag, Intrusion→Restricted zones,
Weapons→Knife detection. `Fights.tsx` and `/fights` endpoints still exist but are
unreachable.

Claude Design imports failed (project 404s / public-artifact reads not enabled).
Working route: he downloads the design into `design/<date> design/` and I diff it.
