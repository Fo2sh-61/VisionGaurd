# datasets/

Owner-supplied evaluation data. Large, so **not tracked** — see `.gitignore`.
This file is the record of what is supposed to be here.

## `egyptian-car-plates/`

~200 MB of Egyptian plate photographs (EALPR), supplied by the owner to answer
one question with a number instead of an opinion: *how often does the vehicle
gate read a plate correctly?*

```
egyptian-car-plates/
  EALPR Vechicles dataset/      (sic - the supplier's spelling)
    Vehicles/                   the photographs
    Vehicles Labeling/          the supplier's labels
  plate_truth.csv               human-confirmed read truth  <- NOT YET BUILT
```

`plate_truth.csv` is the exception to the ignore rule: it is evidence, so it
must be versioned when it exists. It does not exist yet — the labelling pass
below has not been run.

```powershell
# is the detector finding plates at all? (no truth file needed)
python engine/tools/eval_plates.py

# build the read truth - the owner sits with this one
python engine/tools/eval_plates.py --label

# how often is the reading exactly right?
python engine/tools/eval_plates.py --configs theirs,fp32,fp16,trt
```

Results from these runs are written up in
`specs/007-vehicle-gate-tuning/evidence/`. Those write-ups are dated records
and still name this folder's old location, `Egyptian Car Plates dataset/` at
the repository root; it moved here on 1 Sep 2026.
