# Implementation Plan: People page & enrolment — professional, live, and complete

**Branch**: `plan/final-production-roadmap` | **Date**: 2026-08-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-people-enrolment-ux/spec.md`

## Summary

Make enrolment feel like enrolling a face on a phone and make the People page
read professionally — with the least new machinery. The frozen snapshot
becomes the existing live `CameraFrame`; the face outline and feature points
come from one small on-demand endpoint that reuses the face detector the
enrolment service already owns; removal is one DELETE guarded by the existing
path-based auth rule and the gallery's existing cascade; and the People rows
are reorganised around data the system already holds (photo count, enrolled
date, last sighting, today's attendance). No new models, no new workers, no
new wire types beyond one preview payload, no breaking wire changes.

Every functional requirement maps to a decision in [research.md](./research.md)
(D1–D8); nothing in this plan exists that an FR does not ask for.

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript + React (web console)

**Primary Dependencies**: FastAPI; existing `FacePipeline` (YuNet detector —
already returns the five landmarks; SFace embedder untouched); existing
`FaceGallery`, `SightingStore`, `CameraFrame` component

**Storage**: existing SQLite tables only. One column surfaced
(`person.created_at`), one new query (latest sighting per person), zero new
tables

**Testing**: pytest (engine — the listing, preview, and removal rules all live
server-side so pytest can hold them; there is no web test runner), `tsc -b
--force`, pyflakes, recorded clip + webcam for the by-eye checks

**Target Platform**: Windows dev laptop now, single workstation later

**Project Type**: web service (engine) + web console — existing structure

**Performance Goals**: face outline appears ≤ 2 s after stepping in front of
the camera (SC-002); preview poll is one 227 KB-model CPU detection a few
times a second, only while the enrolment page is open; removal effective
≤ 5 s (SC-005 — in practice immediate, via the gallery's in-memory reload)

**Constraints**: no new concurrency (no worker, no thread — the preview is
request/response); additive wire changes only; enrolment guarantees untouched
(3 photos, staged sessions, no images stored, admin-only)

**Scale/Scope**: directory of ~2,000 people at target; the last-seen query is
one GROUP BY per directory load, not per person

## Constitution Check

*GATE — evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | How this plan satisfies it |
|---|---|
| I. Real-time | Live view is the existing stream; overlay polls the latest frame like the enlarged camera view already does; no page shows a frozen frame as live |
| II. Isolation, efficient inference | No new worker. Preview detection runs on demand in the request, only while enrolling, on a 227 KB CPU model the enrolment service already loads. Recognition, counting, tracking untouched |
| III. Truthful data | NO SIGNAL for an offline camera (CameraFrame's existing contract); "nobody detected" when no face; feature points drawn only from a real detection; "Not seen yet" in words, never "—" |
| IV. Reliability, security, privacy | Removal is server-enforced admin-only via the existing path rule, audited before the result returns, and cascades face vectors via the FK that `db.connect` already enforces. No new personal data collected; guardian fields go dormant, not repurposed |
| V. Complete UX | Back control at every step; every column self-explanatory; every row clickable to history; remove has a stated-consequence confirmation; no dead controls |

**Gate result: PASS.** No violations to justify; Complexity Tracking left empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-people-enrolment-ux/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions D1–D8
├── data-model.md        # Phase 1 — wire deltas + one query
├── quickstart.md        # Phase 1 — how to prove it works
├── contracts/api.md     # Phase 1 — endpoint contract deltas
└── tasks.md             # Phase 2 (/speckit-tasks — not this command)
```

### Source Code (repository root)

No new engine modules. Two pages and the service layer change; the engine
edits are all in files that already exist.

```text
engine/vg/
├── identity/enrolment.py    # EDIT — preview(): detect on latest frame, return fractions
├── identity/gallery.py      # EDIT — Person gains created_at (read-only surface)
├── events/sightings.py      # EDIT — last_seen(): latest sighting per person, one query
├── auth/deps.py             # EDIT — "/people" added to ADMIN_WRITE_PREFIXES
├── api/schemas.py           # EDIT — EnrolmentPreview (new), DirectoryPerson +4 additive fields
├── api/app.py               # EDIT — GET /enrolment/preview/{camera_id}, DELETE /people/{id}
└── api/live.py              # EDIT — people() fills new fields; remove_person() with audit-first

engine/tests/
└── test_people_page.py      # NEW — preview, removal, directory fields, auth pins

web/src/
├── pages/Enrol.tsx          # EDIT — CameraFrame + landmark overlay + guidance + back control
├── pages/People.tsx         # EDIT — reorganised rows, clickable, remove control
├── services/api.ts          # EDIT — preview poll, removePerson, new fields; guardianLine deleted
├── services/wire.ts         # EDIT — additive mirrors
└── types.ts                 # EDIT — DirectoryPerson gains the new display fields
```

**Structure Decision**: existing engine + web layout; zero new directories,
one new test file.

## Requirement → design trace

| Requirement | Design | Research |
|---|---|---|
| PPL-FR-001 live view | `CameraFrame` replaces the one-shot `<img>` | D1 |
| PPL-FR-002 outline + points | `GET /enrolment/preview/{camera_id}`, polled | D2 |
| PPL-FR-003 guidance | existing session `advice` + preview face count on screen | D2 |
| PPL-FR-004 back control | "← People" + existing `discard()` | D8 |
| PPL-FR-005 removal, admin, audit | `DELETE /people/{id}`, `ADMIN_WRITE_PREFIXES`, audit-first | D3 |
| PPL-FR-006 effective immediately | `gallery.remove_person()` → `reload()` shared index | D3 |
| PPL-FR-007 no "—" columns | guardian column deleted; absent values in words | D5 |
| PPL-FR-008 recognition wording | "Recognised from N photos" from `photos` field | D6 |
| PPL-FR-009 rows open history | row click → existing history page, all types | D7 |
| PPL-FR-010 three details | `enrolled_at`, `last_seen`+`last_camera`, `attendance_today` | D4 |
| PPL-FR-011 guarantees survive | enrolment service logic untouched; pinned by existing tests | — |

## Complexity Tracking

None — the gate passed without exceptions. Deliberately avoided: a new
streaming transport (D1), landmarks on the shared overlay wire (D2),
client-side face detection (D2), a delete decorator (D3), any new table (D4).
