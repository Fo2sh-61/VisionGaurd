ATTENDANCE DEMO VIDEOS - STAGED, INTERNAL REVIEW
=================================================

What these are
  Real recognition, staged scenarios. VisionGuard's own face models (YuNet + SFace) and its matching
  rule ran over the owner's own webcam clips, against the owner's real enrolment (read from the
  VisionGuard database, read-only). A name appears only when the engine genuinely recognised the face.
  Two things are staged and are labelled on screen: the "Site clock (demo)" (set per video so arrival
  can be on time or late) and, in video 03, the person is deliberately NOT enrolled.

File                                   Shows                                         Result
01_arrives_on_time.mp4                 Recognised at the door, marked present        07:52:10  On time
02_arrives_late_head_turned.mp4        Recognised even with the head turned          08:14:20  Late +15 min
03_visitor_not_enrolled.mp4            A face that is not enrolled                   "Unknown", blurred, nobody marked present
04_after_hours_not_an_arrival.mp4      Recognised at 22:40, outside site hours       "Seen outside hours - not counted"
05_busy_room_only_enrolled_named.mp4   Enrolled person named among bystanders        bystanders stay Unknown and blurred

Limits - read before using in advertising
  - Only ONE person is enrolled, so there is no multi-person scene. Do not fake one: showing names on
    people the system did not recognise would be a false product claim.
  - Naming uses the strict bar VisionGuard uses to name a body (score 0.60, margin 0.10). The looser
    gallery bar (0.363) is too permissive with a small gallery: strangers scored up to ~0.4 against the
    enrolled face in VisionGuard's own clips.
  - Arrival is marked after 2 matching looks (about 0.03 s). VisionGuard's body-naming gate asks for
    3 looks over 1.5 s; do not describe the on-screen delay as the product's timing.
  - Your own face and your colleagues' faces are biometric data. For anything published, get written
    consent from everyone shown, blur everyone else (--blur-unknown), and have your lawyer check the
    use under Egypt's Personal Data Protection Law. Not legal advice.
  - Check your marketing claims against specs/017-public-website/claims.md in VisionGuard: its status
    notes say the site currently makes no claim about face-based attendance at schools.

Shoot checklist for the real footage (3-5 volunteers, one entrance camera)
  1. Written consent from every volunteer, including that the clip will be used in advertising.
  2. Enrol each person from 4-5 photos taken separately from the shoot (straight, left, right, up, down),
     one folder per person: people/Layla_Ahmed/1.jpg ... Do not enrol from frames of the shoot itself.
  3. Camera at the real entrance at face height or slightly above; faces at least 80 px wide as they
     pass (about arm's length on a 640x480 camera); lit from the front, not backlit.
  4. Cases to film: each person arrives alone; two arrive together; one arrives after the cutoff; one
     wearing glasses or a cap; one turns away; one person who is NOT enrolled walks through; someone
     arrives outside hours. Keep every take, including the failures.
  5. Render:  python demo_attendance.py take1.mp4 --people people/ --out take1_demo.mp4 \
                 --title "Arrives on time" --clock 07:52:00 --cutoff 08:00 --blur-unknown \
                 --expect "Layla Ahmed,Omar Khaled"
     --expect checks that everyone who walked through was recognised and nobody else was named; it exits
     non-zero otherwise. Publish only takes that pass, and report the failures honestly.
