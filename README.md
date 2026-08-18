# VisionGuard AI

School campus vision system for Greenfield International School — a console that
answers questions about campus activity (attendance, headcounts, lost items,
intrusion, fights, weapons) with the footage attached.

This repository holds **two front-end apps and the design source they were built
from**. Both apps are front end only: every number, camera frame and detection on
screen comes from fixtures. Nothing talks to a model yet.

```
VisionGuard/
  web/       desktop console — sidebar shell, 960px content column
  mobile/    phone app — bottom tab bar, one generic tool screen
  design/    the design documents both apps were built from
```

## Running them

The two apps are independent installs with independent dependencies. Run either
on its own, or both at once in separate terminals.

```bash
cd web      && npm install && npm run dev    # http://localhost:5173
cd mobile   && npm install && npm run dev    # http://localhost:5174
```

Sign in with any password — it's a demo build.

## Why two apps rather than one responsive app

The mobile design isn't a narrower version of the console; it's a different
shell. The console has a sidebar of eleven destinations grouped ASK / WATCH /
MANAGE, and one page per tool. The phone app has five bottom tabs, collapses all
seven tools into a single screen driven by one answer object, and adds an Account
tab that the console keeps in Settings. Sharing a codebase would have meant
branching on viewport at nearly every level, so they're separate.

They do share the palette (`styles/tokens.css` is the same file in both) and the
same demo school, so the two read as one product.

## Where the design lives

`design/` holds the source documents. `VisionGuard.dc.html` and
`VisionGuard Mobile.dc.html` are the two specs the apps implement — open them in
a browser to see the intended behaviour, including states the screenshots don't
cover. `design/shots/` are screenshots of an **earlier** build and no longer
match the current design (notably the sidebar and the sign-in screen); trust the
`.dc.html` files over the images.

## Wiring the AI later

Each app has the same seam: `src/services/api.ts`. Every function there is
already `async` and returns a type from `types.ts`, so replacing the bodies with
`fetch` calls leaves the screens untouched. `src/services/mockData.ts` is the
fixture file and goes away when a backend exists.

Detection overlays are described in percentages of the frame (`DetectionBox`,
`CameraZone`), so a real detector's normalised coordinates drop straight in.

## Deliberate honesty in the UI

Carried over from the design in both apps, because they're product decisions
rather than decoration:

- Camera tiles say **LIVE** only when the camera is up. An offline camera is
  labelled **NO SIGNAL — showing last received frame**, never a frozen image
  passed off as live.
- A weapon detection always waits for a person to confirm or dismiss it. The
  system never calls anyone, locks anything, or notifies a parent on its own.
- Weapons and fights show false alarms in their history rather than hiding them,
  so the counts stay honest.
- Every "Track a person" search writes an audit entry *before* the result
  renders, and the screen says so.
- Paused intrusion zones stay visible in the list and on the camera grid.
- Both apps state plainly that live streaming isn't connected in this build.
