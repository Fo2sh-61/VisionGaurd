# Phase 0 — Research: Find a lost bag

Every decision below was either measured on this machine on 23 Aug 2026 or is
copied from something already working in the repo. Where a number is
synthetic it says so.

---

## D1 — The model: `bagbest.pt` loads, runs, and is quiet on the clips

**What it is** (read from the checkpoint): a **YOLO-World v2 medium,
fine-tuned** from `yolov8m-worldv2.pt` on the owner's merged dataset, 7 Aug
2026, 50 epochs, 28.4 M parameters. Eleven classes with the text features baked
in (`txt_feats (1, 11, 512)`) and the CLIP encoder stripped (`clip_model:
NoneType`). Own-validation mAP50 0.89, precision 0.90, recall 0.82 — across
all eleven classes, not bags alone.

The architecture is the one `infer/persons.py` guards against with
`YOLO_AUTOINSTALL=false`: loading a World checkpoint can try to pip-install
CLIP. With that guard set, measured in the pinned runtime (ultralytics 8.4.7,
torch cu128):

| | |
|---|---|
| load | 157 ms, `WorldModel`, task `detect`, names as documented |
| flat grey, random noise | **0** boxes each |
| per frame, RTX 2080 Max-Q, FP16, imgsz 640 | **p50 28.1 ms · p95 30.9 ms** |
| 240 sampled frames of the two no-bag clips, conf ≥ 0.25 | bag classes: **1** hit (`suitcase`, once). Non-bag classes fired freely — `laptop` ×16, `cup` ×8, `cap` ×6 — on a desk that has a laptop on it |

**Decisions**

- Keep only the three bag classes, **in the model call**: `classes=[0, 4, 5]`
  (`backpack`, `handbag`, `suitcase`). The other eight never leave the
  detector. Out of scope per spec.
- Confidence **0.4** to start, and a camera is a result only when a bag was
  seen in **at least two frames** of the search. One frame in 240 is what a
  false hit looks like; a bag sitting on a bench is seen dozens of times in a
  minute.
- **No person gate.** The opposite of knives: a lost bag is precisely the one
  with nobody near it. The detector runs on the whole frame.
- Cost is roughly twice the knife model. Affordable because it runs only while
  somebody is searching — see D9.

**Rejected**: `yolov8m-worldv2-search.pt` (the 35-prompt zero-shot model the
page was designed around; open-vocabulary, never trained on bags, 343 MB, and
the owner supplied a trained replacement). `yolov8n-oiv7.pt` (601 classes,
unmeasured; model-manager work).

---

## D2 — On demand means one thread, started by the button, gone in a minute

Nothing runs until Search is pressed. A search is a single `BagSearch` job
with **one thread** that loops over the chosen cameras until the time limit,
the operator stops it, or a new search replaces it. On each pass it asks
`registry.worker(id).last_frame()` — the frame the snapshot endpoint already
serves, cached per sequence — skips a frame it has already seen, runs the bag
detector, and records hits.

| Rejected | Why |
|---|---|
| `FeatureWorker` subclass | one permanent thread per camera, whether or not anyone is searching — finding F5, and exactly what "on demand" must not cost |
| subscribe to the frame bus | the recorder needs every frame to write video; a search wants one look a few times a second and `last_frame()` already provides it with no subscription to leak |
| the archive runner | searches recorded video, which does not exist (P7) |
| one thread **per chosen camera** | ten cameras would start ten threads to run one model behind one lock; the single loop is simpler and finishes the same work |

Replace, never queue: a second search cancels the first (stop event, join
briefly) and starts. The spec says results must never mix, and a queue of
searches for a bag is a queue nobody wants to wait in. `AlreadyBusy` is
therefore not raised here.

---

## D3 — Colour, and how far "independent of lighting" can honestly go

The owner asked for the best way to catch a bag's colour regardless of light.
The honest answer has two halves.

**What can be made light-invariant.** Hue — whether a thing is red, blue,
green or yellow — survives dimming and brightening, because intensity scales
all three channels together. A colour *cast* (warm lamps, cool daylight) does
shift hue, and **grey-world normalisation** cancels most of it: scale the
crop's channels so the surrounding frame's mean is neutral, then read the
colour. Both are a few lines of NumPy.

**What cannot.** Black, grey and white differ only in *lightness*, and
lightness is exactly what lighting changes. A grey bag in a dim corridor is
black to the camera; a white one in shadow is grey. No measurement fixes this
without knowing the light, which the camera does not.

**Decision — measure in a space that separates the two, and be lenient where
the measurement is weak:**

1. Take the bag's crop, keep the central 60 % (straps and background live at
   the edges), grey-world normalise against the frame, and take the **median**
   pixel (a logo or zip cannot drag it).
2. Convert to CIE **Lab**. `chroma = √(a² + b²)` says whether the bag has a
   colour at all. Below the threshold it is achromatic; above, its hue angle
   picks red / yellow / green / blue.
3. Name it **and** produce a *lenient set*: every palette colour within the
   tolerance (hue within 35°, or the neighbouring lightness band). A dark blue
   bag's set is `{blue, black}`; a grey one's in dim light is `{black, grey}`.
4. **The filter matches against the lenient set.** Hiding the right bag is the
   expensive error; showing one extra is nearly free.
5. The page's palette merges the distinction the camera cannot make:
   **Black · Grey or white · Red · Blue · Green · Yellow**, plus *Any*.

**Measured**, on synthetic bag patches (colour + texture noise + a dark strap)
under seven lighting conditions — normal, dim, very dim, bright, warm lamps,
cool daylight, dim and warm:

| | right |
|---|---|
| strict nearest colour | 42 / 49 = 86 % |
| lenient set contains the true colour | 46 / 49 = 94 % |
| with grey and white as one band | every miss recovered — all three were `white` read as `grey`, and `grey` was in the set |

Synthetic. Real corridor cameras — JPEG, auto-exposure, colour-bleed from a
red coat next to the bag — will be worse, and nothing here is calibrated on
the school's cameras. That is why the spec makes colour a filter over bags
already found and puts the hidden count on screen: the design absorbs the
error rather than pretending it is not there.

**Rejected**: CLIP zero-shot ("a photo of a red backpack") — the encoder is
stripped from the model and installing one is forbidden; a trained colour
classifier — no labelled data; HSV alone — its value channel has the same
lightness problem and its hue is unstable near grey. A dedicated colour
module (`infer/colour.py`) with no model and no GPU, unit-tested on exactly
the seven lighting cases above.

---

## D4 — The wire: keep the job shape, change the question

`SearchJob`, `LostResult` and `LostHit` already exist and already describe a
job that runs and finishes — designed for a footage search that was never
built, but the shape fits a live one. Kept. `LostQuery` changes: it asked for
`item / colour / area / since`; the spec's question is *which cameras* and
*optionally which colour*. It becomes `cameras: list[str]` + `colour`. `item`
stays with a default for demo mode; `area` and `since` go. Additive fields on
`LostResult` carry what the spec requires on screen: cameras checked, cameras
that could not be looked at and why, bags hidden by colour, frames checked.

`POST` starts (or replaces) a search and returns it `running`; the page polls
`GET /lost-items/search` once a second until `done`; `DELETE` stops it. The
console owns the area → camera resolution: the roster already carries
`Camera.area`, and the server should not have to know what was ticked.

---

## D5 — The overlay, and the knife trap again

`_boxes(camera_id, feature)` falls through to **faces** for any feature it
does not recognise. Knife detection shipped with its branch missing and would
have drawn a name next to a knife. `lost` gets its branch above the default,
drawing `_bag_boxes` from the running search's recent hits. `kind="object"`,
`severity=WARN` → amber in `boxColor()`: never green (a face), never blue (a
body), and never a label that is a name.

A bag box is held for a few seconds after its hit and then dropped; after
that the camera stays pinned with the time it was seen. A box drawn over a
live picture of where a bag *was* is the same lie as a stale frame.

The grid draws the overlay on the tiles (`tileOverlay`, as the Knife page
does) — the owner asked for the bag to be visible without opening a camera.
A `lost` poll does not wake face recognition: `camera_detections` already
boosts the recogniser only for `attendance` and `track`.

---

## D6 — Honest states

| Situation | `capabilities().search_lost` | Page |
|---|---|---|
| detector loaded, idle or searching | LIVE | form + grid |
| weights missing / failed to load | UNAVAILABLE "Lost bag search failed to start (*reason*)" | banner, no Search |
| no enabled camera | UNAVAILABLE "No camera is running, so there is nothing to search." | banner |
| search finished, nothing found | LIVE; result says *N cameras checked over M seconds, no bag seen* | stated, never a bare grid |
| a chosen camera offline | listed in `camerasUnavailable` with the reason | named on screen |

System Health gains a real `search_lost` stage: model version, device, and
*idle* or *searching N cameras*.

---

## D7 — The page

Rebuilt from the present `LostItems.tsx`, keeping its chip style and its
"query readable before it runs" summary line. Gone: the four bag types, the
"missing since" period, the ranked list with *Watch clip* / *This is it*, the
fixture sentence "Checking 42 cameras", and `useAutoRun` — a page that starts
a live search on arrival with nothing ticked would search nothing and say so,
which is noise. Home's suggested question still lands here; it lands on the
form.

New: an **area tree** built from the roster — one checkbox per area, expandable
to its cameras, with *Unassigned* as a real group; a **Search / Stop** button;
a status line that counts down; and the camera grid with found cameras
**pinned first and marked**. `CamGrid` gains one prop, `pinned: string[]`,
which orders those ids first and badges them. Everything else on the grid is
already there.

---

## D8 — Cost

Idle: **zero**. No thread, no model call, nothing subscribed.

Searching: one full-frame pass per camera per loop. At ~28 ms a pass:

| cameras ticked | one round takes | each camera checked, per minute |
|---|---|---|
| 10 | 0.3 s | ~200 times |
| 40 | 1.1 s | ~50 times |
| 208 (everything) | 5.8 s | ~10 times |

Ten looks at every camera in the school, in a minute, from one thread. It
shares the GPU with the live features but not their locks or their cache — a
bag search cannot change a headcount. Measured on a laptop GPU; re-run on the
workstation.

---

## D9 — Areas

From the live roster's `area` field, which the console already offers in every
area dropdown. A camera with no area is *Unassigned*, shown as a group. Today
that is every camera but one; filling areas in is a settings task that makes
the page look as designed, not code.

---

## D10 - Measured at implementation (23 Aug 2026): D1's false-positive rate was optimistic

D1 sampled 240 frames and found one bag-class hit. Re-measured over **706**
sampled frames of the same two no-bag clips, through `classes=[0, 4, 5]` at the
configured `conf 0.4`, there are **19**, and **two distinct false-positive
modes** that the planned defences do not catch:

| Mode | What | Confidence | Caught by `CONFIRM_FRAMES=2`? | Caught by `MIN_BOX_FRACTION`? |
|---|---|---|---|---|
| Motion blur | a bumped, blurred frame reads as one `suitcase` box covering **99.7 %** of the picture | up to 0.88 | no (recurs) | no - it is the largest possible box |
| Dark furniture | a **black office chair back** at (0.70, 0.66), area 0.10, held for 13 consecutive sampled frames (2+ s of real time) | 0.55 - 0.88 | **no** - the two-frame rule assumes false hits are isolated | no |

Both were confirmed by eye on the rendered frames.

**The two-frame rule defends against flicker, not against a wrong thing that
stays still.** A lost bag is by definition a stationary object, so any
stationary false positive is indistinguishable from a true hit by persistence
alone. No threshold fixes this; only a person looking does.

**Decisions**

- Add `MAX_BOX_FRACTION = 0.6`. A box covering most of the frame is a blur
  artefact, never a bag somebody can go and collect. This kills the first mode
  outright and costs nothing real.
- Keep `CONFIRM_FRAMES = 2` and `conf 0.4`. Raising either does not touch the
  chair (0.88, sustained) and would start losing real bags.
- **Do not call a hit a bag.** The page says *possible bag*, the box is amber,
  and the operator opens the camera and judges. The design already absorbs this
  error the way the colour filter does - what changes is that the wording must
  be honest rather than incidental.
- The two modes sit on **different clips**, and it matters which. All 17 of the
  surviving false positives are on `baseline-empty`; the walk-through clip that
  `-Clip` mode actually serves produced two, both under `MIN_BOX_FRACTION` and
  both correctly dropped. Verified end to end on 23 Aug 2026: a full 60-second
  search over `cam-clip` checked **949 frames** and reported **no bag**, which is
  the right answer. The quickstart check stands as written.

Accuracy on real bags remains unmeasured - there is no clip with a bag in it.

**Measured end to end, 23 Aug 2026** (real model, real clip camera, in process):
949 frames in 60 s on one camera - about 16 looks a second, well above D8's
estimate. The job ended itself at 60 s, `Stop` ended it at 5 s, people counting
kept answering throughout, and System Health read *bagbest on cuda - idle* before
and *searching 3 cameras* during.
