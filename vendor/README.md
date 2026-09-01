# vendor/

Code that VisionGuard did not write, kept in the repository because the engine
either **runs it** or **was ported from it**. It used to live under `models/`,
which made three whole projects look like model weights.

Nothing in here is edited. If one of these needs to change, the change belongs
in `engine/`, and the reason belongs in a spec.

| Folder | What it is | Does the engine need it? |
|---|---|---|
| `loiterwatch/` | Appearance matcher — decides that two sightings are the same body | **Yes. Installed and imported.** |
| `gate-anpr/` | Egyptian number-plate reader; the project `engine/vg/infer/plates.py` was ported from | **Yes, for evaluation.** |
| `bag-tracker/` | Prior bag/item search project; the source of `models/bagsearch.pt` | No. Reference only. |

## `loiterwatch/` — a live dependency

This is the one that breaks the build if it goes missing. It is a Python
package, not a folder of scripts:

```powershell
pip install -e vendor/loiterwatch
```

`engine/vg/identity/appearance.py` imports `loiterwatch.IdentityStitcher`,
`engine/vg/ingest/archive.py` imports `BodySignature` and `similarity`, and
`engine/vg/infer/tracking.py` builds the detection tuple its API expects.
Twelve appearance and track tests need it importable.

CI installs it explicitly (`.github/workflows/ci.yml`) because it once did
not: those twelve tests passed on developer machines — where somebody had run
the install by hand months earlier — and failed in CI. That is the worst shape
a test can have, so the install is now a named step rather than folklore.

Its only dependency is PyYAML.

## `gate-anpr/` — the reference the plate reader was ported from

The working Egyptian ANPR system. Two engine modules are ports of it, and both
say so in their docstrings:

- `engine/vg/platetext.py` ← `vendor/gate-anpr/anpr/plate_text.py`
- `engine/vg/infer/plates.py` ← `vendor/gate-anpr/anpr/{detector,ocr}.py`

It is also still **executed**, not just read. `engine/tools/compare_plates.py`
and `engine/tools/eval_plates.py` load it as the `theirs` configuration and run
it against our port on the same photos. That comparison is the only thing that
can tell a porting mistake apart from a precision loss, so the folder has to
stay importable:

```powershell
python engine/tools/eval_plates.py --configs theirs,fp32,fp16,trt
```

Its own copies of the two plate weights are **not** tracked — they are the same
files as `models/plate_detector.pt` and `models/char_detector.pt`.

This folder was `models/Gate/gate-anpr/gate-anpr/` — three levels deep for no
reason. The outer launcher `.bat` existed only to `cd` through that nesting and
was deleted; `START-GATE-ANPR.bat` inside this folder is the real one.

## `bag-tracker/` — source material, not tracked

2.2 GB of a prior bag and item search project. Not in git; it lives on disk
only. `models/bagsearch.pt` was produced from one of its checkpoints:

```powershell
python engine/tools/strip_clip.py "vendor/bag-tracker/models/yolov8m-worldv2-search-12ac1b92.pt" models/bagsearch.pt
```

Nothing imports it. It is kept because it is the provenance of a weight file
the engine does load — see `models/README.md`.
