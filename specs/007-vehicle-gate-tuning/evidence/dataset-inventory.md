# Dataset inventory — EALPR Vehicles

**Taken 2026-08-27** against the owner-supplied `Egyptian Car Plates dataset/`,
by T003. Facts only; no model was run.

## What is there

| | |
|---|---|
| Images | **2,087** — `.jpg` 2,031 · `.JPG` 54 · `.jpeg` 2 |
| Label files | 2,088 `.txt`, of which **2,087 are labels** and one is `classes.txt` |
| Paired image ↔ label | **2,087 (100%)** — no orphans in either direction |
| Plate boxes | **2,143** across 2,087 images |
| Images with more than one plate | **51** |
| Malformed label lines | **0** — every line is `0 cx cy w h`, all values within 0..1 |
| Classes present | `0` only (`classes.txt` names it `car_plate`) |
| Size on disk | 204 MB (git-ignored; see `.gitignore`) |

## Corrections to the plan

The plan and `context.md` were written from a rough `find` count and said
"2,085 images vs 2,088 labels — skip unmatched pairs and report the count".
That was wrong in the reassuring direction: there are **2,087 of each and
nothing to skip**. The apparent surplus label is `classes.txt`, the labelImg
class-name sidecar, which the eval tool must **exclude by name** rather than
treat as an orphan.

## What the eval tool must handle

1. **Case-sensitive extensions.** 56 of the images are not lowercase `.jpg`.
   Globbing `*.jpg` alone silently drops 2.7% of the set.
2. **Multiple plates per image** in 51 cases — detection scoring must match
   boxes as a set (greedy by IoU), not assume one plate per photo.
3. **`classes.txt` is not a label file.** Filter it out explicitly.
4. **Paths contain spaces**, and two folder names are misspelled upstream:
   `EALPR Vechicles dataset` and `Vehicles Labeling`. Quote every path; do not
   "correct" the spelling.

## What this dataset cannot tell us

These are the images the supplied models were **trained on**. A score here
measures whether our port reproduces the source project on its own data —
pipeline fidelity — and says nothing about how the reader behaves on the
school's gate camera. Every evidence file must repeat this, and the site
answer comes only from real captures (`engine/tools/record.py`) or Mohamed's
hand test.

## Read truth

Boxes only. There is **no plate text** in this dataset, so the 95% exact-read
target (P6-FR-037) needs the human-confirmed `plate_truth.csv` built by
`eval_plates.py --label` (task T014, blocked on the owner).
