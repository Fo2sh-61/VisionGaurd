# Quickstart: Find a lost bag

How to prove it works, in the order that costs least. §1–§3 need no bag and no
camera. §4 needs Mohamed, a bag, and his webcam.

## 1. Before touching anything

```powershell
python -m pytest engine -q          # 811 passed, 6 skipped at e101db1
python -m pyflakes engine/vg engine/tools engine/tests
cd web; npx tsc -b --force; cd ..
```

Confirm the model is where the plan says and loads in this runtime:

```powershell
python -c "import os; os.environ['YOLO_AUTOINSTALL']='false'; from ultralytics import YOLO; m=YOLO('models/bagbest.pt'); print(type(m.model).__name__, m.names)"
```

Expected: `WorldModel {0: 'backpack', 1: 'laptop', …, 10: 'glasses'}` and no
attempt to install anything.

## 2. The tests — no camera, no model

All in `engine/tests/test_lost_bag.py`, driven with a fake registry that hands
out scripted frames and a fake detector that returns scripted boxes.

```powershell
python -m pytest engine/tests/test_lost_bag.py -q
```

What must be green, and what each proves:

| Test | Proves |
|---|---|
| `only_chosen_cameras_are_ever_analysed` | SC-004 — the detector's call log names no other camera |
| `a_single_frame_is_not_a_result` | the ≥ 2 frames rule |
| `a_bag_seen_twice_pins_its_camera_with_a_box` | the happy path, box in fractions, `kind=object`, no name |
| `the_search_ends_at_the_limit` | SC-002 with a fake clock |
| `a_new_search_replaces_the_running_one` | results never mix; old thread joined |
| `stop_keeps_the_hits` | DELETE semantics |
| `an_offline_camera_is_named_not_dropped` | P7-FR-013 |
| `an_unknown_camera_is_named_not_404` | the list still runs |
| `a_search_of_nothing_fails_with_a_sentence` | P7-FR-016's cousin — the empty tick case |
| `colour_filter_hides_with_a_count` | P7-FR-007, hidden count exact |
| `colour_under_seven_lights` | D3's table: lenient set contains the true name in every row |
| `the_overlay_carries_no_name_and_drops_after_the_hold` | rule 1 and D5's hold |
| `a_lost_poll_does_not_wake_face_recognition` | the knife-page lesson |
| `works_with_every_other_feature_off` | rule 9 |
| `capabilities_say_why` | D6's sentences; health stage agrees |
| `demo_mode_still_searches` | `VG_MOCK=1` unchanged for the console |

`python -m pytest engine` must then count **above 811**.

## 3. Pipeline check on the recorded clip

Deterministic, no webcam. The clip has **no bag**, so this is D1 running
live: a full search over it must find nothing and say so.

```powershell
.\dev.ps1 up -Clip
```

1. Sign in. Open **Lost bag**.
2. The area tree shows *Unassigned* (or *Main entrance*) with `cam-clip` under
   it. **Search is disabled** until something is ticked.
3. Tick the clip camera. Press **Search**. The status line counts up; the
   button reads **Stop**.
4. Let it finish. Expected: **"1 camera checked over 60 seconds. No bag
   seen."** — never a bare grid. The grid shows the camera, unpinned.
5. **System health** → *Lost bag search* reads `bagbest on cuda · idle` with
   a model version.
6. Tick nothing else, choose a colour, Search again: the same answer, plus
   *"Colour filter: blue — 0 bags hidden."*
7. Press Search, then **Stop** after five seconds: the status says stopped,
   the count of frames checked is small and non-zero.
8. Open **People counting** during a search: its numbers do not change
   (SC-006 by eye; the test proves it).
9. `.\dev.ps1 down`

## 4. Manual check — needs Mohamed, a bag, and the webcam

Only your eyes can confirm these. Please do them in this order and say what
you saw for each.

```powershell
.\dev.ps1 up
```

1. **A bag on a chair, nobody near it.** Tick the webcam, Search. The camera
   should pin to the top with a badge within a few seconds and show an amber
   box round the bag on the tile. Open it: the box is on the bag, not beside
   it.
2. **Move the bag out of view mid-search.** The camera stays pinned with
   *"seen at HH:MM"*; the box disappears within about five seconds. It must
   not sit on the empty chair.
3. **Colour.** Pick the bag's actual colour: still found. Pick a colour it is
   not: *"1 bag hidden by colour"* and the camera unpinned. Now dim the room
   or switch the lamps — this is the check that matters for D3. Does a black
   bag stay black? Does a dark blue one still pass *blue*? Tell me which
   colours failed under which light.
4. **Nothing there.** Empty chair, Search: the sentence with the counts, no
   pin.
5. **Press Search twice quickly.** One search, not two; the status line does
   not flicker between them.
6. Restart the engine. The page comes back with no search and no stale
   result.

Things I cannot measure and you can: how long from pressing Search to the pin
appearing; whether amber reads as "bag" or as "warning" to you; whether the
area tree is the thing you pictured when you said checkboxes.

## 5. The accuracy you do not have yet

There is no footage with a bag in it. Everything above proves the machinery;
nothing proves the model finds *your* bags on *your* cameras. When you have
done §4, record thirty seconds with the bag in shot:

```powershell
python engine/tools/record.py --camera cam-laptop --label bag-on-chair --seconds 30
```

and it joins `engine/data/footage/` as the regression clip the knife feature
is also still waiting for.
