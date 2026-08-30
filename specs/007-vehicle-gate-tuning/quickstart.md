# Quickstart: Vehicle Gate Accuracy & Redesign

How to prove each strand works. Prerequisites: the repo, model weights in
`models/`, the dataset at `Egyptian Car Plates dataset/`, and for live checks a
webcam. `python engine/tools/create_user.py` once if no account exists.

## 1. Accuracy — measure, then judge

```powershell
# Baseline every configuration over the dataset (detection vs the YOLO labels):
python engine/tools/eval_plates.py --dataset "Egyptian Car Plates dataset/EALPR Vechicles dataset" --configs trt,fp16,fp32,theirs

# Build the human-confirmed text subset (the owner confirms/corrects proposals):
python engine/tools/eval_plates.py --label --dataset "Egyptian Car Plates dataset/EALPR Vechicles dataset"

# Read accuracy against confirmed truth:
python engine/tools/eval_plates.py --truth "Egyptian Car Plates dataset/plate_truth.csv" --configs trt,fp16,fp32,theirs
```

**Expected**: each run prints per-config detection recall/precision and exact-read
rate (overall and ≥100 px), writes a dated file under
`specs/007-vehicle-gate-tuning/evidence/`, and the same command run twice gives
the same numbers. **Pass line** (P6-FR-037): the deployed config reads ≥95%
exactly right on confirmed plates ≥100 px. The first config pair that disagrees
names the cause — the decision ladder is research.md §3.

## 2. The live box — the thing that was invisible

```powershell
python -m pytest engine/tests/test_vehicle_overlay.py -q   # full-path regression
.\dev.ps1 up -Clip                                          # then open /vehicle-gate
```

**Expected**: the new test proves a stub read becomes a wire-valid box with
`kind="plate"` and `plateWidthPx`. Live: load `/` in the browser, sign in, click
through to Vehicle gate (dev deep-links hit the proxy — navigate from `/`).
Manual check (Mohamed, webcam): hold a plate (or a phone photo of one) in front
of the camera — a box appears around it while it is in view, with the width
readout, amber when small/far, green when close; the reader table underneath
fills with attempts and the votes column climbs to 3/3.

## 3. The redesign

```powershell
.\dev.ps1 up -Mock    # every new endpoint has a MockStore answer — UI work without models
```

**Expected on Live**: alerts strip (dismiss writes an audit row — check
`/audit` as admin; blacklisted example still raises its Home item), six tiles
including "Cameras reading", gate tiles with the aiming-aid note, the reader
card, no "Passing now" list anywhere.

**Expected on Movements**: day picker + plate/owner search + gate filter;
hourly chart; gate-by-gate with totals and honesty notes; Inside now /
Completed visits rows with snapshot thumbnails that open the photograph;
"Export this day" downloads that day only. With no exit camera (clip/webcam
reality) the paired sections say why instead of rendering empty tables.

**Expected on Registered vehicles**: Latin line under each plate chip; "last
import" line shows a real run (import the template via the UI, see the line
update) or is absent on a fresh database.

## 4. The gates — before calling any of it done

```powershell
python -m pytest engine                    # count must not drop; new tests green
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force                 # clean
.\dev.ps1 up -Clip                         # behaviour on the recorded clip
```

Baseline and the three pre-existing `test_track_page.py` failures are recorded in
[context.md](./context.md) §4 — they are not this feature's to fix, and they must
not grow.

## 5. What cannot be validated without the owner

- The 95% verdict itself — needs the confirmed-truth subset (§1, `--label`).
- Real-gate generalisation: the dataset is the models' training set; the final
  word on the school's own camera is Mohamed holding real plates (§2) and, when
  available, site recordings via `python engine/tools/record.py`.
