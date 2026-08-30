# Quickstart: Vehicle Gate

How to prove each slice works. Four sections matching the four slices in
[plan.md](./plan.md); each leaves the repo green, so you can stop after any of them.

## Prerequisites

```bash
.\dev.ps1 doctor
```

Two dependencies are new to this feature:

```bash
python -m pip install openpyxl
```

TensorRT is **already installed on this machine** — `tensorrt 11.2.1.2`, verified
importable alongside `torch 2.11.0+cu128`. On a fresh machine:

```bash
python -m pip install tensorrt
```

> Two things worth knowing before you think it is broken. It takes about **20 minutes
> and prints nothing**, because it builds a 1.96 GB wheel at install time — it is not
> hung. And it resolves to the **cu13** line against a **cu128** torch, which looks
> like a mismatch and is not: TensorRT ships its own CUDA runtime. Do not pin.

---

## Slice A — acceleration

Nothing to do with vehicles. Run it first: it fixes something already broken.

```bash
python -m pytest engine/tests/test_engine_selection.py -q
```

Then build the engines and read what it says:

```bash
python engine/tools/build_engines.py
```

Expect one line per configured model — succeeded, or the reason it did not.
`bagsearch.pt` is the one to watch: it is a YOLO-World stripped of its CLIP encoder,
and is the export most likely to fail. **A failure there is information, not a
blocker** — P6-FR-033 says that model keeps running on `.pt` over CUDA and System
Health says so.

Then confirm the console tells the truth about it:

```bash
.\dev.ps1 up -Mock
```

Open **System health**. Every model row should name its form:

```
coco-yolov8s on cuda (TensorRT) - 2 camera(s), 11ms last inference
bagsearch-worldv2 on cuda (PyTorch CUDA, no engine built) - 1 camera(s), 38ms
```

**Record the before/after milliseconds here.** They are the numbers the plan
deliberately refuses to guess:

| Model | `.pt` on CUDA (p50) | TensorRT FP32 (p50) | Built? |
|---|---|---|---|
| person `yolov8s` @640 | **18.3 ms** | **12.0 ms** | ✅ 24 Aug 2026 |
| weapons | | | |
| bags | | | |
| pose | | | |
| plate detector | | | |
| char detector | | | |

Measure with 100 iterations after a 10-frame warm-up. A 20-iteration run on this
throttling Max-Q part swung the same model between 12.7 and 18.2 ms — do not trust a
short run, and do not quote the flattering end of one.

Delete an `.engine` and restart. The row must flip to `PyTorch CUDA` and say so.
That is P6-FR-033, and it is the check that would have caught the state this repo has
been in for months.

---

## Slice B — plate reading

No database, no console, no camera:

```bash
python -m pytest engine/tests/test_platetext.py engine/tests/test_vehicle_voting.py -q
```

What these prove:

- `١٢٣٤` and `1234` normalise to the same canonical plate — the guarantee the
  `UNIQUE` constraint depends on
- confusable readings (`ه/٥`, `و/٦`, `ب/ت`) **merge** their votes rather than
  splitting them
- fewer than three agreeing frames records nothing
- a weak read is kept and flagged, not discarded

Then against a real image, before wiring anything:

```bash
python engine/tools/measure_latency.py --model plates --image <a photo of a plate>
```

---

## Slice C — register and passes

```bash
python -m pytest engine/tests/test_vehicles_store.py engine/tests/test_vehicles_api.py -q
```

The checks worth naming, because each maps to a rule that has been broken before:

| Check | Rule |
|---|---|
| A guard (`role="it"`) gets `200` on `GET /vehicles/register` and `403` on `POST` | path-based permissions |
| The audit row exists **before** the export body is returned | P6-FR-023 |
| Removing a vehicle keeps its passes | P6-FR-020 — `SET NULL`, never `CASCADE` |
| Blacklisting a car does not change yesterday's pass | P6-FR-019 |
| Blacklist outranks expiry | data-model status order |
| An import reports every rejected row with a reason | P6-FR-017 |
| A store with no worker returns `200` with a reason, not `503` or `0` | rule 7 + SC-010 |

Build a store with real data by hand — copy the `store` fixture in `test_groups.py`.
**Close the store before the tempdir** or Windows fails the teardown.

---

## Slice D — the page

```bash
cd web; npx tsc -b --force
```

Then, with the webcam configured as gate 1 entry:

```bash
.\dev.ps1 up -Mock
```

Walk the three tabs and check the **empty** states first, because that is where the
design lies and the build must not:

1. **Live** — with no plate model, tiles show reasons, not zeros. The design's
   `148 / 121 / 27 / 6 / 1 / 4` must appear nowhere.
2. **Registered vehicles** — empty register says it is empty and how to fill it. The
   design's "2,140 on record" and "Last import: 2,140 rows · 6 skipped · 12 Aug" must
   appear nowhere.
3. **Movements** — with only an entry camera, "Inside now" must not print a paired
   figure. It says no exit camera is configured.

Then the real thing, which needs Mohamed:

```bash
.\dev.ps1 up
```

**Ask Mohamed to hold a plate up to the webcam.** This is the one thing no test can
confirm — that a real plate, at real distance, under real light, reads correctly and
lands as one pass. Watch for:

- a box round the plate, in the right place, in the status colour
- **exactly one** pass appearing, not one per frame
- the plate rendering right-to-left in Arabic
- clicking **Register** on that unregistered pass opening the form with the plate
  already filled in
- adding it to the register, then a second pass reading as "Registered" **with no
  restart**

---

## Before calling any of it done

```bash
python -m pytest engine
```

**868 passed** is the baseline at `e9ba8dd`. The count must go up, never down.

```bash
cd web; npx tsc -b --force
python -m pyflakes engine/vg engine/tools engine/tests
```

`pyflakes` catches the exact bug class that once silently killed face recognition, so
it is not optional.
