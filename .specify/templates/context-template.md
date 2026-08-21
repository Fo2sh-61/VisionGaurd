# Implementation context: [FEATURE NAME]

**Written by `/speckit-plan` on [DATE], against commit `[SHA]`.**

The point of this file: the planning chat has just read every file the plan
names. The implementing chat has not, and rebuilding that by opening whole
files is the single largest avoidable cost in the whole loop. So write down
here what the next chat would otherwise go and re-read.

Read this **before** opening any source file. Then open the named anchors
only — not the files around them.

> Verify before trusting. This is a snapshot; if it disagrees with the code,
> the code wins and this file is wrong. Anchors drift — search for the symbol,
> do not trust the line number.

---

## 1. Anchors — where each edit lands

One row per file in the plan's Source Code section. `Anchor` is the symbol to
search for. `Shape today` is what is actually there right now.

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `engine/vg/…` | `class Foo` | `field: type` … the two or three facts needed to write the change | what the task adds |

Example of the level of detail that pays for itself:

| File | Anchor | Shape today | The edit |
|---|---|---|---|
| `identity/gallery.py` | `class Person` | frozen dataclass: `id, name, type, group, detail, photo_count`; `photo_on_file` is a property. Built in `reload()` from `SELECT * FROM person` | add `created_at: datetime \| None`, read it in `reload()` |
| `events/sightings.py` | `SightingStore.recent` | every read takes `with self._lock`, returns rows through `_parse(row["seen_at"])`. Module already has `_parse` | insert `last_seen()` above `recent()`, reuse `_parse` |

## 2. Things to copy, not invent

The existing code that already does the nearest thing. Name the file and the
symbol; the implementing chat opens that one function.

- Pattern: … → copy `path.py::symbol`

## 3. Traps

What the code does that the plan does not say and a reader would not guess.
Anything found here at plan time is a design problem caught before it is built.

- …

## 4. Baseline

- `python -m pytest engine` → **N passed, M skipped** at commit `[SHA]`
- New test file(s) this feature adds: `engine/tests/test_[x].py`
- Anything already failing before this feature starts, and why

## 5. Still unknown

Questions the plan could not settle from reading alone — the implementing chat
must check these in code rather than assume.

- …
