# Implementation Plan: Track a person — past paths and live catching

**Branch**: `plan/final-production-roadmap` | **Date**: 2026-08-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-track-person-ux/spec.md`

## Summary

Rebuild the Track page around its two real questions, assembling almost
everything from machinery that already runs. Live catching is the existing
tracking worker plus a server-side "follow" session that lives inside the
worker's own loop — no new threads; recording rides the existing `Recorder`.
Past paths come from a new anchor store filled by the recognition worker at
recognition time, so the skeleton is a database read. The only genuinely new
machinery is the archive layer: fetching DVR footage on demand, processing it
in 30-second chunks on a small bounded job runner, and serving the chunks the
way breach clips are already served. Every timing promise is gated behind a
measurement tool that runs before the numbers are believed.

Every requirement maps to a decision in [research.md](./research.md) (D1–D10).

**Four increments, each shippable**: live catch → anchors & instant skeleton →
DVR legs → strangers & sweep. The page is useful after the first one.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React (console)

**Primary Dependencies**: existing `TrackingWorker` (ByteTrack + appearance,
CPU), `RecognitionWorker` (YuNet + SFace, CPU), shared YOLO person detector
(GPU, TensorRT on target), `Recorder`, `FrameBus`; **new**: ffmpeg subprocess
for DVR playback fetch (already a runtime dependency via OpenCV video IO)

**Storage**: sightings SQLite db gains one `anchor` table; leg chunks are mp4
files under `clips_dir/track/` with a keep-last-N rule like zone clips; follow
sessions and leg jobs are in-memory (lost on restart, stated honestly)

**Testing**: pytest (anchor gates, follow lifecycle, name rules, job states,
auth — all server-side); `tsc -b --force`; pyflakes; the walk-through clip is
the archive backend in dev, so leg processing is testable with no DVR

**Target Platform**: Windows dev laptop now; single workstation with GPU later

**Performance Goals**: skeleton ≤3 s (database read — trivially met); leg
first-frames ≤10–15 s (gated on measured DVR fetch speed); playback never
stalls once started (chunk processing ~2–5× faster than real time); sweep cap
≈15 min wall-clock, derived from measured rates

**Constraints**: no new always-on inference beyond the low-rate patrol tier;
one bounded job runner (2 threads) is the only new concurrency, justified in
Complexity Tracking; additive wire changes only; geometry as fractions;
audit before results everywhere

**Scale/Scope**: 208 cameras at target. Live grid is display-only (streams are
already decoded by ingest); patrol recognition rates are per-tier config knobs
sized by measurement; archive work is on-demand only — idle system does zero
archive work

## Constitution Check

*GATE — evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | How this plan satisfies it |
|---|---|
| I. Real-time | Live tiles are the existing streams with NO SIGNAL honesty; follow view boosts the followed camera (existing idiom); stale results dropped by `RESULT_TTL_SECONDS`; leg playback is explicitly *not* live and never dressed as live |
| II. Isolation, efficient inference | Patrol is a second `RecognitionWorker` instance — zero base-class changes, shares the loaded pipeline (allowed: shared immutable models). Tracking on all cameras shares the one YOLO pass as counting/intrusion already do. Archive jobs reuse the loaded person model, bounded to 2 workers. No feature requires another |
| III. Truthful data | Anchors carry evidence (matches, span, scores) and nothing below the bar is drawn; face anchors stay green, appearance stitching stays blue, never merged; estimates come from stored measurements, never guessed; follow name drops with the track |
| IV. Reliability, security, privacy | Audit before result for skeleton, legs, sweeps, follow start, record start/stop; follow recording stops server-side on timer or track loss (a closed tab cannot leave one running); leg chunks respect keep-last-N retention; in-memory job state degrades honestly on restart |
| V. Complete UX | The dead clip-save on the old page is replaced by real recording segments; every wait shows real progress; empty windows say so and offer next steps; the rebuilt page has no dead controls |
| Scale constraints | Patrol rates, fetch speed and process rate are measured on the target machine by `tools/measure_track.py`; the sweep cap derives from them; capacity table lives in research D10 |

**Gate result: PASS.** One justified addition in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/003-track-person-ux/
├── plan.md              # This file
├── research.md          # D1–D10
├── data-model.md        # anchor table, follow session, jobs, wire deltas
├── quickstart.md        # gates + by-eye script
├── contracts/api.md     # endpoint contract deltas
├── context.md           # implementation handoff (anchors + shapes)
└── tasks.md             # Phase 2 (/speckit-tasks — not this command)
```

### Source Code (repository root)

```text
engine/
├── engine.yaml                  # EDIT — `faces:` flag per camera, `archive:` section, patrol rates
├── vg/config.py                 # EDIT — CameraConfig.faces, ArchiveConfig, optional neighbours
├── vg/features/recognition.py   # EDIT — AnchorAccumulator hook; sustained gate before note_face
├── vg/events/anchors.py         # NEW  — AnchorStore: table, write, skeleton query (copy sightings.py idioms)
├── vg/features/tracking.py      # EDIT — FollowSession: follow/record/timer/loss inside analyse()
├── vg/ingest/archive.py         # NEW  — fetch abstraction (dvr|footage backends), chunked leg jobs, bounded runner
├── vg/api/schemas.py            # EDIT — PathAnchor, PathSkeleton, FollowView, LegJob, SweepEstimate, +Camera.faces
├── vg/api/app.py                # EDIT — /path/*, /tracking/follow*, chunk serving, sweep endpoints
├── vg/api/live.py               # EDIT — store methods; skeleton audit-first; estimates from measured rates
├── vg/api/store.py              # EDIT — protocol + MockStore demo behaviour
├── tools/measure_track.py       # NEW  — measures DVR fetch × and process fps; stores rates
└── tests/test_track_page.py     # NEW  — anchors, gates, follow, names, jobs, auth pins

web/src/
├── pages/TrackPerson.tsx        # REBUILD — two modes; grid → camera → click; skeleton → legs
├── components/CamGrid.tsx       # EDIT — area partitions, paging, search
├── services/api.ts              # EDIT — new calls
├── services/wire.ts             # EDIT — mirrors
└── types.ts                     # EDIT — display shapes
```

**Structure Decision**: two new engine modules (`events/anchors.py`,
`ingest/archive.py`), one new tool, one new test file; everything else edits
files that exist.

## Requirement → design trace

| Requirement | Design | Research |
|---|---|---|
| TRK-FR-001 two modes | one page, two panels; mode is a UI state | D1 |
| TRK-FR-002 patrol + anchor bar | second RecognitionWorker instance; AnchorAccumulator at recognition time | D5, D6 |
| TRK-FR-003 instant skeleton | `GET /path/{person}` reads anchor table only | D7 |
| TRK-FR-004 chunked leg playback | archive fetch → 30 s chunks → burn-in → served like breach clips | D8, D9 |
| TRK-FR-005 prefetch next | job runner priority queue; next anchor's camera, else same area / `neighbours:` | D9 |
| TRK-FR-006 stranger hop-by-hop | leg job with appearance query instead of person | D10 |
| TRK-FR-007 sweep estimate + cap | estimate from stored measured rates; refuse over budget | D10 |
| TRK-FR-008 audit everywhere | `_log` before result: skeleton, leg, sweep, follow, record | D2, D7 |
| TRK-FR-009 live grid | CamGrid + areas, paged, searched | D1 |
| TRK-FR-010 click-to-track | `POST /tracking/follow` picks the body at the click point; boost | D2 |
| TRK-FR-011 name on unbroken track | stable-id lifecycle already dies with the track; `note_face` gains the sustained gate | D3 |
| TRK-FR-012 recording follows | FollowSession drives existing Recorder per camera hop | D4 |
| TRK-FR-013 fetch on demand | archive layer only ever runs inside a job | D8 |
| TRK-FR-014 honest waits | measured rates stored by `measure_track.py`; estimates computed, never typed | D8, D10 |
| TRK-FR-015 faces flag | `CameraConfig.faces` drives patrol tier | D5 |

## Complexity Tracking

| Addition | Why it is justified | Simpler alternative rejected because |
|---|---|---|
| Bounded job runner (2 threads) in `ingest/archive.py` | A leg fetch+process takes 5–15 s; a request thread cannot hold it and the UI needs progress polling. Two workers cap GPU/disk contention; queue is bounded and refuses over-cap work honestly | Doing it in-request blocks FastAPI's pool and makes every wait a spinner with no progress — the exact dishonesty the spec forbids |
| ffmpeg subprocess for DVR playback fetch | DVR playback is an RTSP/stream pull for a time range; ffmpeg is already shipped with the OpenCV stack and handles every DVR dialect we will meet | Re-implementing stream demux in Python is strictly worse on every axis |

Deliberately avoided: any new FeatureWorker subclass beyond what exists (patrol
is a second instance, not a new class); overlay-sync video players (burn-in
instead); a persistent job table (jobs are minutes-long and restart-honest);
WebRTC or HLS (chunked mp4 over the existing clip-serving idiom).
