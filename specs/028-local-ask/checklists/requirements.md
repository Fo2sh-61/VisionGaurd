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

- [x] No [NEEDS CLARIFICATION] markers remain. Both were answered on
      10 Nov 2026
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

**Answered 10 Nov 2026:**

1. **Ask learns from use** (P15-FR-012, P15-FR-022 to P15-FR-026). An
   administrator's correction takes effect straight away. An operator's
   "did you mean" pick waits for an administrator to approve it. Examples are
   stored masked, any example that breaks a test question is refused, and
   removing the learned examples returns Ask to its measured start. The
   approval step is an assumption, open to challenge.
2. **"Show me the gate camera now" opens the live view** (P15-FR-020). It is
   one new menu entry that reads no data. With a past time, the same
   question gets a clip.

**Checked in the code, not assumed:**

- The menu has 14 entries (`engine/vg/ask/menu.py`). `lost_item` is a
  deep-link only.
- Only breach and weapon rows carry a saved clip today (`clip_url`).
- The archive (`engine/vg/ingest/archive.py`) fetches by camera and time span
  already, but only through tracking legs. P15-FR-015 opens it up.
- `ask:` in `engine.yaml` names a Gemini model and an 8 s timeout. Both go
  away with this spec.

Ready for `/speckit-plan`.
