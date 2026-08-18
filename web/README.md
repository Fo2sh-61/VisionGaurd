# VisionGuard AI — web console

School campus vision system, built from `VisionGuard.dc.html` in `../design/`.
This is the **front end only**: every number, camera frame and detection on
screen comes from fixtures. Nothing talks to a model yet.

There's also a separate mobile app in `../mobile/` — its own build, its own
shell, see `../mobile/README.md`. The two apps share the same design tokens and
demo data but are deliberately not one responsive codebase, because the
mobile design (bottom tabs, one generic tool screen, an Account tab) is a
genuinely different shell from this sidebar console.

See `../README.md` for the repository overview.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # typecheck + production build
```

Sign in with any password. The role picker (Admin / IT) is what changes the app:
Admin sees Users and can notify parents; IT sees System health and can restart
recorders.

## Layout

```
src/
  app/          providers, routing, shell
    routes.tsx        route table + role guards
    AppShell.tsx      sidebar + topbar frame for signed-in routes
    AuthContext.tsx   the signed-in account (role lives here)
    ThemeContext.tsx  light / dark, persisted
    navigation.ts     one nav list; sidebar, Home tools and the ask-router share it
  components/   presentational pieces (ui.tsx, CamGrid, CameraFrame, CameraModal)
  pages/        one file per tool
  services/     THE SEAM — see below
  styles/       tokens.css (design tokens) + app.css (component classes)
  types.ts      the shapes the UI renders
```

## Wiring the AI later

Two files are the entire boundary:

- **`src/services/api.ts`** — every data call the UI makes. Each function is
  already `async` and returns a type from `types.ts`. Replace the bodies with
  `fetch` calls and the pages don't change.
- **`src/services/ask.ts`** — the "ask in plain words" router. It maps a
  question to a tool. Today it's keyword matching; swapping in an LLM intent
  call means keeping the `(question, role) => AskOutcome` signature.

`src/services/mockData.ts` is the fixture file. When the backend is real, it
goes away.

Detection overlays are described in percentages of the frame
(`DetectionBox`, `CameraZone` in `types.ts`), so a real detector's normalised
box coordinates drop straight in.

## Deliberate honesty in the UI

Carried over from the design, because they're product decisions, not decoration:

- Camera tiles say **LIVE** only when the camera is up; an offline camera is
  labelled **NO SIGNAL — showing last received frame**, never a frozen image
  passed off as live.
- The camera modal states that live streaming isn't connected in this build.
- Weapons shows false alarms in the history rather than hiding them.
- Every "Track a person" search writes an audit entry *before* the result
  renders, and the page says so.
- Paused intrusion zones stay visible in the list and on the camera grid.
- Weapons has a full review workflow (`src/pages/Weapons.tsx`): a live
  detection waits for a person to confirm or dismiss it — the system never
  calls anyone or notifies a parent on its own.
- System health includes the camera-onboarding flow
  (`src/components/CameraSources.tsx`): scan the network, add a DVR/NVR, add
  one IP camera, or paste an RTSP URL — each with the same honest "not
  connected yet" note about live streaming.
- People (`src/pages/People.tsx`) is the student/staff/visitor directory,
  distinct from Users (`src/pages/Users.tsx`, admin-only sign-in accounts).
  Settings (`src/pages/Settings.tsx`) covers the school profile, alert
  routing, quiet hours and appearance.
