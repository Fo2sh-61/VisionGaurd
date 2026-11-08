DRAFT DEMO VIDEOS - INTERNAL REVIEW ONLY, NOT CLEARED FOR PUBLICATION
======================================================================

All five clips are rendered from public research datasets:
  - Le2i fall dataset (Univ. Bourgogne Europe)  licence: CC BY-NC-SA  -> NON-COMMERCIAL only
  - UR Fall Detection dataset (Univ. of Rzeszow) published for research use
Marketing is commercial use. Do not publish these as they are. Use them to review the look
and the story, then re-shoot the same scenarios with your own footage (see below).

What the overlay shows (nothing is scripted; it is the model's own output):
  green box "OK"            person classified as normal
  orange box "Possible fall" model sees a fall in progress (can happen briefly, e.g. while bending)
  blue box "On the floor"   person is down but no alert has been raised
  red box + banner          FALL DETECTED: the alert the system would send
  bottom-left chip          "Monitoring - no alert" until an alert is raised, then "ALERT RAISED at m:ss"

File                                    Source (all from the held-out TEST split)        Result
01_fall_coffee_room.mp4                 Le2i Coffee_room_01 / video (10)                 alert at 9.4 s, as the person hits the floor
02_fall_living_room.mp4                 Le2i Home_01 / video (7)                         alert at 7.1 s, ~1 s after the fall
03_not_a_fall_sitting_down.mp4          UR Fall adl-08                                   no alert
04_not_a_fall_bending_to_search.mp4     UR Fall adl-04                                   no alert (brief "Possible fall" mid-bend)
05_not_a_fall_crawling_on_floor.mp4     UR Fall adl-32                                   no alert

Model: LSTM + CCTV augmentation (checkpoints/temporal_model.pt).
Source footage is 320x240, so the 960x720 output is upscaled and soft.

These are hand-picked examples of correct behaviour. Measured over all 30 held-out test videos the
model caught 17 of 19 falls with 4 false alarms. It is NOT reliable for someone lying down on a
bed or sofa (sleeping): it raised a false alarm in all 3 such clips in the data. Do not claim
that scenario in marketing until it is fixed and re-measured.

Make more with your own footage:
  python demo.py my_clip.mp4 --out demo.mp4 --title "Fall: person trips in a corridor"
