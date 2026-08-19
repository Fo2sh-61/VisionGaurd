# Feature Specification: [FEATURE NAME]

**Feature Branch**: `[###-feature-name]`
**Created**: [DATE]
**Status**: Draft
**Input**: User description: "$ARGUMENTS"

> Keep this short. Describe **what** the user needs and **why** — never how to build it.
> No frameworks, file names, class names, or database choices. Delete any section that
> genuinely does not apply rather than padding it.

## Why this feature *(mandatory)*

[2–4 sentences. What problem does an operator have today, and what changes for them?]

## User Scenarios & Testing *(mandatory)*

### Primary story

[One paragraph in plain language: who does what, and what they get.]

**Acceptance scenarios**

1. **Given** [starting state], **When** [action], **Then** [what the user sees]
2. **Given** [starting state], **When** [action], **Then** [what the user sees]

### Edge cases

- What happens when the camera is offline or the subsystem is not running?
- What happens when there is genuinely nothing to show (empty vs zero vs unknown)?
- [Any others specific to this feature]

## Requirements *(mandatory)*

Numbered `[PHASE]-FR-001` — e.g. `P0-FR-001`. Product-level `FR-xx` numbers belong to
`docs/PLAN.md` and must not be reused here.

- **[PHASE]-FR-001**: System MUST [specific, testable capability]
- **[PHASE]-FR-002**: System MUST [specific, testable capability]
- **[PHASE]-FR-003**: Users MUST be able to [key interaction]

Mark anything uncertain as **[NEEDS CLARIFICATION: question]** rather than guessing.

## Success Criteria *(mandatory)*

Measurable, and written so a non-engineer could check them.

- **SC-001**: [e.g. "An operator can tell within 2 seconds whether a page is showing real or demo data"]
- **SC-002**: [e.g. "A breach appears with its clip within 5 seconds of someone entering the zone"]

## Out of scope

- [What this feature explicitly does not cover, so nobody assumes it]

## Constitution check *(mandatory)*

Confirm this feature does not break the rules in `.specify/memory/constitution.md`. Note any
principle that needs special care here — most often: no fake data, face vs clothing kept
distinct, honest degradation, server-side permissions, latency budget.

## Assumptions

- [Anything you decided without being told, so it can be challenged]
