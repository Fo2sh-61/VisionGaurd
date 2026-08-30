# Specification Quality Checklist: Ask — natural-language query console

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 30 Aug 2026
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — all three answered 30 Aug 2026
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

**Answered 30 Aug 2026:**

1. **Cloud allowed.** Ask uses a cloud model; the provider is chosen at plan
   time and a written no-training guarantee is a condition of choosing it.
2. **Unrecognised words are sent as typed.** Masking covers everybody enrolled
   and every plate in the register. A visitor or an unenrolled child typed into
   the box leaves the site as text. Accepted deliberately for routing accuracy;
   P12-FR-007 warns on screen and P12-FR-012 records what left. SC-002 was
   reworded to say this rather than claim more than the design delivers.
3. **Answer first, "understood as" beside it.** No confirmation step.

**Two carried risks the plan must keep visible:**

- The privacy limit in (2) is the one thing in this spec that a school could
  reasonably object to. Revisit before go-live if the consent position changes.
- With (3), a confidently wrong route produces a true answer to a question
  nobody asked. The "understood as" line and its deep-link are the only defence,
  which is why P12-FR-005 makes them mandatory and SC-003 measures wrong routes.

**Two things checked in the code, not assumed, and both changed the spec:**

- **Lost items has no stored history**, so Ask cannot answer "where is the red
  bag". Demoted to a deep-link in the edge cases and the assumptions.
- **Counting is real for one area only.** Answers about the other areas carry
  the demo label the Counting page carries (P12-FR-004).

Ready for `/speckit-plan`.
