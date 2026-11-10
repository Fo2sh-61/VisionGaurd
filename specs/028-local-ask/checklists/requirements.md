# Specification Quality Checklist: Local Ask, on the Jetson with clips

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 10 Nov 2026
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs). The model name,
      file paths and archive backends appear only under Assumptions, because
      Mohamed chose them and they belong to the owner-supplies-models rule
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [ ] No [NEEDS CLARIFICATION] markers remain. Two are open (P15-FR-012,
      P15-FR-020)
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

**Open, for Mohamed:**

1. **P15-FR-012**: may an administrator correct a misunderstood question so it
   becomes a new example? If yes, it is a write path and must be audited and
   limited to admins. If no, only the owner edits the examples.
2. **P15-FR-020**: should "show me the gate camera now" open the live view?
   That would be one new menu entry. It adds no new calculation, but P12 allows
   no new queries, so it needs his decision.

**Checked in the code, not assumed:**

- The menu has 14 entries (`engine/vg/ask/menu.py`). `lost_item` is a
  deep-link only.
- Only breach and weapon rows carry a saved clip today (`clip_url`).
- The archive (`engine/vg/ingest/archive.py`) fetches by camera and time span
  already, but only through tracking legs. P15-FR-015 opens it up.
- `ask:` in `engine.yaml` names a Gemini model and an 8 s timeout. Both go
  away with this spec.

Two clarifications are open. Ready for `/speckit-clarify`, or for
`/speckit-plan` once Mohamed answers them.
