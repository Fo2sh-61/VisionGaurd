# Specification Quality Checklist: Vehicle Gate

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-24
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

Seven decisions were taken with Mohamed before writing, so nothing was guessed on the
points that would have changed the shape of the feature:

1. **Port the plate-reading technique into VisionGuard's own structure**, rather than
   running the Gate project as a second service or copying all 5,000 lines in.
2. **The laptop webcam is the first gate**, configured as Gate 1 entry; real RTSP/DVR
   cameras come later and the page must not change when they do.
3. **The register starts empty** and is filled from unregistered passes; the
   spreadsheet importer is built but there is no list to load yet.
4. **A blacklisted pass raises a Home attention item** that waits for a person.
   An expired permit does not.
5. **Accelerated inference is restored repo-wide**, not just for the plate models —
   `P6-FR-029` to `P6-FR-035`. Doing it plate-only would have left a cold path beside
   a warm one.
6. **A missing or stale accelerated build falls back to the GPU form of the supplied
   weights and says so on screen** — never to the processor, and never silently.
7. **The accelerated build is produced on this machine now**, so the plan can quote
   measured timings rather than estimates.

### Why the acceleration requirements are in this spec at all

They read like an implementation concern, and they were nearly left out. They are here
because of what an audit of the repo actually found:

- Five accelerated builds sit in `models/`. **Not one is referenced by the
  configuration** — every configured model points at the supplied weights instead.
- The library that loads them is no longer importable by the interpreter that runs the
  engine, so none of them could load even if referenced.
- The person build is 480px while the configuration asks for 640, and these builds have
  static shapes, so it could not have served that configuration regardless.
- `models/README.md` already warned they were produced by a newer version of the
  inference library than the one installed.

None of that was visible on any screen. The product was running slower than it was
built to and nothing said so. That is a truthfulness problem, not a performance one,
which is why `P6-FR-033` and `P6-FR-035` are requirements rather than plan notes.

Two items were checked with particular care because the design would otherwise make
the page lie:

- **The design's numbers are placeholders.** "2,140 on record", "148 entered today",
  "27 inside now", "Last import: 2,140 rows · 6 skipped" are invented figures in the
  mock. P6-FR-025 and SC-010 exist to make sure none of them survives into the build.
- **"Inside now" is not computable with one camera.** Pairing an exit to an entry
  needs an exit camera. P6-FR-012 forbids showing a paired figure that has nothing to
  pair against, and the edge-case list says what the page shows instead.

Two requirements deliberately restate constitution rules rather than assuming them,
because both have been broken before in this codebase: P6-FR-027 (each feature draws
its own overlay — tracking IDs once appeared on the attendance page) and P6-FR-028
(no feature may require another).
