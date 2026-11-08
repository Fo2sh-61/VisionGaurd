CINEMATIC SIMULATED ATTENDANCE DEMOS - ILLUSTRATIONS, NOT RECOGNITION
=====================================================================

How they were made
  Your downloaded airport clips (Pexels, 4K -> 1080p). A pose detector finds people; a face box is drawn
  only for faces turned to the camera. Names are scripted placeholders ("Employee NN"); every 4th person
  after the script is shown as an unenrolled visitor (blurred, "Unknown"). No recognition ran. The demo
  clock runs fast (20-25x) so a 10-second clip covers several minutes of arrivals.
  Every frame, including the intro and the end card, carries: "SIMULATED DEMONSTRATION - illustrative,
  not live system output". Do not crop it out. Do not put accuracy numbers beside these videos.

File                          Quality   Notes
C1_security_checkpoint.mp4    good      12 arrivals, 1 late, visitors blurred
C2_main_concourse.mp4         good      4 arrivals, 1 visitor
C5_glass_walkway.mp4          good      15 arrivals (on time, then late), 9 visitors; busiest, best lock-on shots
C6_after_hours_terminal.mp4   OK        22:30 clock: nobody is counted (outside site hours); the panel stays at
                                        "Present 0" while faces are still boxed. Reads as "seen, not counted"
C3_arrivals_hall.mp4          weak      people walk sideways; boxes sit on turned heads and labels get clipped
C4_terminal_lobby.mp4         weak      people mostly walk away or are far; few boxes
Use C1, C2, C5, C6.

Left out on purpose
  13244548, 11490317 - crowds in face masks: "recognised" labels on masked faces would advertise a capability
  nobody has verified.

Before publishing
  - The people are real, identifiable strangers (some with children). Pexels' terms say a commercial promotion
    showing identifiable people likely needs their consent or a licence, and that deciding is up to you.
    Fake names on strangers' faces in an ad for a face-recognition product raise the bar. Get legal advice
    (including Egypt's Personal Data Protection Law), or replace the footage with a consented shoot and re-run:
      python demo_cinematic.py footage.mp4 --out demo.mp4 --title "Morning arrivals" --clock 07:57:30 --rate 25
  - Put your own claims through the same check you use on the website (VisionGuard specs/017-public-website).
