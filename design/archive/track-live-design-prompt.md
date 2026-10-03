# Design prompt — VisionGuard "Track a person" live view

Copy everything below this line into Claude Design.

---

Design a desktop web screen for a school security console called **VisionGuard**.
The screen is called **Track a person**. An operator uses it to follow one
specific person across the school's CCTV cameras, live.

## The product, in one paragraph

VisionGuard watches a school's cameras. It recognises enrolled students and
staff by face, and follows their body between cameras using clothing colour when
their face is not visible. This screen is the investigation tool: pick a person,
watch where they go, and record a clip of it. The audience is a school security
officer or head teacher, not a technical user. Everything must be readable at a
glance and impossible to misinterpret.

## Visual style

Calm, flat, institutional. No gradients, no drop shadows, no glassmorphism, no
neon. It should feel like a serious tool, not a consumer app. Rounded corners
around 12px on cards. Generous whitespace. Sentence case everywhere, never Title
Case.

Use exactly this palette (it is the product's existing design system):

```
page background   #f2f5f2
panel             #e9efe9
card              #ffffff
hairline border   #e0e7e1
text primary      #1f2b26
text secondary    #57655d
text muted        #8a968e
accent green      #33705b
accent dark       #285948
chip background   #dfe9e0
red / danger      #a5372c   on background #f7e3e0
amber / warning   #8a6a14   on background #f3ecd9
card shadow       0 1px 3px rgba(30,42,36,.07)
```

Camera video areas are dark. Use `#1d2420` behind them. Detection box colours,
which sit on top of dark video and must stay fixed in both light and dark themes:

```
green   #3ec776   the person was identified by their FACE
blue    #5b9bd8   matched by CLOTHING only (same body, weaker claim)
amber   #e0b341   an unidentified person
red     #e5564a   alert
```

Also design a dark theme version of the chrome. The video areas stay dark in both.

## Screen states

Design these **three states** as separate frames.

### State 1 — choosing who to follow

Two ways to start, side by side as a segmented control:

- **Find by name** — a dropdown of enrolled people, plus a from/to time range and
  a "Track" button.
- **Pick from a camera** — a row of camera thumbnails; the operator opens one and
  clicks directly on a person in the picture.

Below both, a section titled **Unidentified people seen today**. Each row is a
body the system followed but never matched to a face: an amber ID chip like
`#p7`, the words "Unknown person", when and where they were seen, and two
buttons — "Track" and "Name". This is how an unknown body becomes a real person.

### State 2 — the system is unsure which camera they are in  ← the important one

**This state matters more than any other. Do not skip it.**

After the operator picks a person, the system often cannot tell which camera
they are actually in. It may believe they are in camera 9, or in camera 2 — two
genuinely different possibilities. The operator must resolve this, not the
software.

Show **each possibility as its own candidate block**. A candidate block contains:

- one **large frame** — the camera the system thinks the person is in
- a small **grid of that camera's neighbours** beneath or beside it (typically
  4 cameras, e.g. for camera 9 the neighbours are 7, 8, 10 and 11)
- a confidence value, written as plain words, e.g. "fairly sure" or "not sure"
- a button: **"This is them"**

Stack two or three candidate blocks vertically. Make it obvious these are
alternatives, not a sequence. A short line of instruction at the top:
"The system found more than one possible match. Choose the right one."

When the operator picks one, that candidate becomes State 3.

### State 3 — following them live

This is the main working screen. Layout:

- **One large main frame in the centre.** This is the camera the operator
  confirmed the person is in. It fills most of the width.
  - A **red filled circle with the word "Recording"** sits in the top-left
    corner of this frame. This replaces the "Live" badge used elsewhere in the
    product — on this screen the badge means recording, nothing else.
  - Draw a detection box around the tracked person, using the colours above.
    Inside the box label: **the ID in large text** (e.g. `#p1`) with the
    **person's name in smaller text underneath** (e.g. `Mohamed Fouad`). If they
    are not identified, the name line reads "Unknown person" and the box is amber.
- **Four smaller camera frames** arranged around or below the main one. These are
  the neighbouring cameras, showing plain live video. Keep them simple — a
  border, the camera name, nothing else.
- **The camera the system predicts the person will walk into next** gets a
  **slow, gentle green pulse around its border**. Slow and soft, roughly a two
  second cycle — it should draw the eye without being alarming or distracting.
  Only one camera pulses at a time. Show what this looks like in the frame, and
  include a note describing the animation.
- A **subject bar** showing the tracked person: large ID, name underneath, and a
  **"Stop tracking"** button.
- A **"Not this person"** button near the subject bar, for when the system has
  clearly locked onto the wrong body.
- A **path timeline** below, listing where they have been: time, camera name, and
  a coloured dot — green for a face match, blue for a clothing match. Include a
  small legend spelling out what green and blue mean, in words.

Also design the **after-stopping state**: once the operator presses "Stop
tracking", the recording ends and a panel appears offering to **save the clip**,
showing its length and how many cameras it spans, with "Save clip" and "Discard"
buttons.

### State 4 — camera map setup (a separate screen, in Settings)

A configuration screen where the operator lays out the building.

- A large canvas showing a **top-down floor plan** of the school.
- Camera markers that can be **dragged onto the plan** to place them.
- Each marker shows its camera name and a direction it faces.
- The system predicts where someone will go next based on **which cameras are
  physically nearest on this plan**, so placement accuracy matters. Say this on
  screen in one plain sentence.
- A list of unplaced cameras down one side, waiting to be dragged on.

## Rules

- **Never merge "face match" and "clothing match" into one number.** A face
  identifies a person; clothing only says it is the same body seen earlier. The
  design must keep them visually distinct wherever both can appear.
- **An unidentified person must never look like a confirmed identity.** Amber,
  and the words "Unknown person".
- The operator is always the one who decides. The system proposes; it never
  silently picks.
- No emoji. Use simple outline icons only.
- Text on a coloured chip uses a dark shade of that same colour, never black.

## Deliverables

Four frames — the three tracking states plus the camera map setup — in light
theme, and the State 3 frame again in dark theme. Include the pulse animation
note and the detection box label as a small component spec.
