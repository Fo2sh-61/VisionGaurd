# Phase 1 — Data model: Find a lost bag

Nothing is persisted. The spec forbids saving video or stills and there is
no history to keep: a search is a question asked now, answered now, and gone
when the next one starts. So there is **no table**. What follows is the
in-memory job, the wire, and one config entry.

---

## 1. `BagSearch` — one job in memory

Lives in `engine/vg/features/lostbag.py`. One instance per engine; it holds at
most one running job and the last finished one.

### `Job`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | uuid4 hex |
| `query` | `LostQuery` | what was asked |
| `started_at` | `datetime` | UTC |
| `ends_at` | `datetime` | `started_at + limit_seconds` |
| `state` | `running` \| `done` \| `stopped` \| `failed` | see transitions |
| `cameras` | `list[str]` | the ids asked for, in the order asked |
| `checked` | `set[str]` | ids that produced at least one frame |
| `unavailable` | `list[Unavailable]` | `(camera_id, name, reason)` — offline, unknown, disabled |
| `hits` | `dict[str, list[Hit]]` | camera id → every hit, oldest first |
| `frames_checked` | `int` | total model calls |
| `error` | `str \| None` | set with `failed` |

### `Hit`

| Field | Type | Notes |
|---|---|---|
| `at` | `datetime` | the frame's `captured_at` |
| `box` | `(x, y, w, h)` fractions | clamped 0..1 |
| `label` | `str` | `backpack` \| `handbag` \| `suitcase` |
| `confidence` | `float` | model score |
| `colour` | `str` | the best name, from `name_colour()` |
| `colours` | `frozenset[str]` | the lenient set — what the filter matches against |

### State transitions

```
(none) ──POST──> running ──limit reached──> done
                   │
                   ├──DELETE, or a new POST──> stopped
                   └──detector raised / no camera usable──> failed
```

`done` and `stopped` both keep their hits. `failed` keeps what it had and
carries `error`. A new POST replaces whatever is there, in any state.

### Rules the job enforces (each gets a test)

1. A camera not in `query.cameras` is never handed to the detector.
2. A frame already seen (same `sequence`) is not analysed twice.
3. A camera appears in `hits` only when a bag was seen in ≥ 2 frames — one
   frame is what a false hit looks like (D1). Single-frame sightings are kept
   internally so the second one can confirm them, but not reported.
4. The job ends on its own at `ends_at` whether or not the loop is mid-round.
5. `stop()` returns within a second; the thread is joined, never abandoned.
6. Boxes handed to the overlay are at most `OVERLAY_HOLD_SECONDS` old.

### Constants (`features/lostbag.py`)

| Name | Value | Why |
|---|---|---|
| `LIMIT_SECONDS` | 60 | SC-002; `docs/PLAN.md` §7 budget |
| `CONFIRM_FRAMES` | 2 | D1 — one frame in 240 on no-bag footage |
| `ROUND_PAUSE_SECONDS` | 0.1 | one thread must not spin when every camera's frame is unchanged |
| `OVERLAY_HOLD_SECONDS` | 5 | a box over where a bag *was* is a stale frame wearing a rectangle |
| `MIN_BOX_FRACTION` | 0.01 | ignore a bag box under 1 % of the frame — a distant smudge, not a bag somebody can go and pick up |

---

## 2. `name_colour()` — the colour namer

`engine/vg/infer/colour.py`. Pure NumPy + OpenCV, no model, no GPU, no state.

```
name_colour(crop_bgr, frame_bgr) -> ColourGuess(best: str, lenient: frozenset[str])
```

| Step | What |
|---|---|
| crop | central 60 % of the box — straps and background live at the edges |
| normalise | grey-world against the **frame**: scale channels so the frame mean is neutral |
| summarise | median pixel of the crop |
| classify | Lab; `chroma < ACHROMATIC_CHROMA` → black / light by `L`; else nearest hue among red, yellow, green, blue |
| lenient | every palette name within `HUE_TOLERANCE_DEG` (35°) or the neighbouring lightness band; a dark chromatic also gets `black` |

Palette, and the only names the wire ever carries:
`black` · `light` (grey or white) · `red` · `blue` · `green` · `yellow`.

The page shows `light` as **Grey or white**. The distinction the camera cannot
make is not offered as a choice (D3).

Tested on exactly the seven lighting conditions in D3, as a table-driven
unit test. The numbers there are the acceptance bar: the lenient set must
contain the true name in every case.

---

## 3. Wire — `engine/vg/api/schemas.py`

### `LostQuery` — reshaped

| Field | Type | Notes |
|---|---|---|
| `cameras` | `list[str]` (default `[]`) | camera ids to search. Empty → `failed` with a sentence, never a search of nothing |
| `colour` | `str \| None` | one palette name, or `None` for any. Unknown name → 422 naming the palette |
| `item` | `str` (default `"bag"`) | kept so demo mode and `test_no_fixtures` still construct one; the live engine ignores it |

`area` and `since` are removed. The console resolves areas to cameras; there
is no footage for `since` to mean anything.

### `LostHit` — two additive fields

| Field | Type | Notes |
|---|---|---|
| `colour` | `str \| None` | the best name |
| `colours` | `list[str]` | the lenient set, so the page can say "looked black or blue" |

Existing fields: `camera_id`, `camera_name`, `at` (the **last** frame that saw
it), `confidence` (the best), `note` ("Seen 14 times over 38 s"), `box`
(`kind="object"`, `severity=WARN`, label = the class name, **never a name**),
`clip` (always `None` — nothing is recorded).

### `LostResult` — additive fields

| Field | Type | Notes |
|---|---|---|
| `cameras_checked` | `int` | produced at least one frame |
| `cameras_unavailable` | `list[UnavailableCamera]` | `camera_id`, `camera_name`, `reason` |
| `hidden_by_colour` | `int` | bags found whose lenient set lacks the chosen colour |
| `frames_checked` | `int` | |
| `seconds_limit` | `float` | so the page can count down honestly |
| `seconds_elapsed` | `float` | |

Existing: `job` (`SearchJob` — `state`, `progress` = elapsed / limit,
`submitted_at`; `clips_searched` / `clips_total` stay `0`, because no clips
exist and saying otherwise would be the precision rule broken), `query`,
`hits` (one per camera with ≥ 2 frames, **after** the colour filter, best
confidence first), `cameras` (a `CameraView` per hit camera, with its box).

`SearchJob.state` gains `"stopped"`.

### `UnavailableCamera` — new

`camera_id: str`, `camera_name: str`, `reason: str`.

### `Box` on the bag overlay

`kind="object"`, `label` = `Backpack` / `Handbag` / `Suitcase`,
`confidence`, `severity=WARN` (amber in `boxColor()`), `match=NONE`, no
`track_id`. Amber is what the console already uses for "something to look
at" that is not an identity.

---

## 4. Configuration

| Where | Change |
|---|---|
| `engine/engine.yaml::models.bags` | `weights: models/bagbest.pt`, `imgsz: 640`, `conf: 0.4`, `iou: 0.45`, `half: true`, `version: bags-v1-2026-08-07`; comment says what it is and that only three of its classes are used |
| `engine/engine.yaml::models.search` | left as history, not loaded by anything |
| `engine/vg/config.py` | nothing — `ModelSpec` already carries every field above |

---

## 5. Entity summary

| Entity | Lives in | Survives restart |
|---|---|---|
| Running search + hits | `BagSearch` memory | **no** — by design, nothing to save |
| Last finished search | `BagSearch` memory, until the next POST | no |
| Colour palette | `infer/colour.py` constants | n/a |
| Which cameras are in which area | the live roster (`Camera.area`) | yes — already does |
