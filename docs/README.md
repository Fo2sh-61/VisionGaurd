# docs/

Five documents, in the order a newcomer should read them.

| # | Read | For |
|---|---|---|
| 1 | `../AGENTS.md` | How the codebase is shaped, and the four files a feature touches |
| 2 | `../STATUS.md` | What is real today and what is still a fixture. **The honest one** |
| 3 | `PLAN.md` | What to build and in what order. **The only plan** |
| 4 | `HANDOFF.md` | Where the last session stopped and what to pick up |
| 5 | `MANUAL-TEST.md` | Fifteen minutes of clicking that proves the console works |

`architecture.png` is the diagram from the root `README.md`, rendered — for
reading the repository somewhere that does not draw Mermaid.

Above all of these sits `../.specify/memory/constitution.md` — the engineering
rules, and the highest authority in the repository. When a document here
disagrees with the constitution, the constitution wins.

## The rest

- `prompts/` — the feature descriptions specs were generated from. Provenance,
  not plans.
- `archive/` — superseded documents, kept because the reasoning in them is
  sometimes still worth reading. **Never plan from these.** `PLAN.md` names
  the five it replaced.

## Where documents live, and why there

| | |
|---|---|
| `docs/` | Prose a human reads to understand or run the project |
| `specs/` | One folder per feature: spec, plan, tasks, contracts, evidence |
| `.specify/` | The spec-kit machinery — templates, scripts, the constitution |
| `design/` | The visual designs the apps were built from |

A document that is true of the whole project goes in `docs/`. A document that
is true of one feature goes in that feature's folder under `specs/`.
