# Spec Prompt — Ask (Natural-Language Query Console)

Use as the feature description for `$speckit-specify`. Suggested branch: `010-ask`.

---

Create one feature specification named **Ask — Natural-Language Query Console**.

Specification only. Do not implement, edit source, install dependencies, run migrations, or touch the database. Output only the normal Spec Kit artifacts.

**Read first:** `.specify/memory/constitution.md` (especially III Truthful Data, IV Reliability & Privacy), `docs/PLAN.md`, `STATUS.md`, `AGENTS.md`, `specs/008-arabic-console`, and `web/src/services/api.ts` (the queries Ask can answer).

**Why:** VisionGuard's promise is a console that answers questions about site activity with the footage attached. Today an operator must know which page to open. Ask lets them type a question in plain language and get a grounded answer.

**Core rule — the answer is never invented.** Ask maps a question to ONE existing, tested query and answers only from its real result. The language model is a translator, never the source of a fact.

**Behaviour:**

- The operator types free text in Arabic (MSA, Egyptian dialect, or Franco-Arabic), English, or a mix.
- **Before anything leaves the site,** names, plates, and other personal identifiers are replaced locally with placeholders — Arabic-normalised (alef/hamza/taa-marbuta variants, Arabic-Indic vs Western digits, and transliterations like سارة/Sara). Faces and footage never leave the site.
- The **masked** question plus a fixed menu of supported queries is sent to a cloud model, which MUST return one supported query with its parameters, or "unsupported" — as **strict JSON, never prose**.
- The engine resolves the placeholders locally, runs the trusted query, and shows the real result with its provenance (camera, time, confidence), the footage, a small "understood as …" line, and a deep-link into the feature page.
- **Scope = every query the system already exposes.** Anything else is answered honestly ("I can't answer that — I can answer about attendance, headcounts, zones, weapons, lost items, plates, and where a person went"). Ambiguous → one clarifier. Subsystem offline → the API's real unavailable state, never a guess. Cloud unreachable → "Ask is temporarily unavailable"; detection and the safety features are unaffected.
- Ask is **read-only**; every question, resolved query, and answer is audited.

**Design seam:** the parser is a single interface — `parse(question) → query + params | unsupported` — so the cloud model can be swapped for a local one later without changing the rest of Ask.

**Out of scope / do not touch:** any detection or feature logic; no new data. The model must not answer from footage, faces, or its own knowledge. For production, the cloud provider MUST offer a no-training / data-privacy guarantee.

**Success criteria:**

- **SC-001**: A supported question returns the same result the matching page shows — never a fabricated one.
- **SC-002**: No name, plate, face, or footage is sent off-site (masking verified on an Arabic test set).
- **SC-003**: Arabic, Franco-Arabic, English, and mixed questions all route to the correct query on a test set.
- **SC-004**: Out-of-scope, ambiguous, subsystem-offline, and cloud-unreachable each produce the honest state above — no guessed answer.
- **SC-005**: Every question is audited; Ask never writes feature data.

Mark uncertainties as **[NEEDS CLARIFICATION: question]**. Confirm the Constitution check (III and IV especially).
