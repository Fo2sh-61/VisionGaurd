# VisionGuard AI — mobile app

The mobile companion to the web console (`../web/`), built from
`VisionGuard Mobile.dc.html` in `../design/`. Same demo school, same fixtures,
same front-end-only scope — this is a **separate app**, not a responsive view of
the web console, because the mobile design collapses the sidebar's tool list
into a bottom tab bar and a single generic "tool" screen, which is a genuinely
different shell than the desktop one.

See `../README.md` for the repository overview.

```bash
npm install
npm run dev      # http://localhost:5174
npm run build    # typecheck + production build
```

Sign in with any password — there's no role picker on mobile (the design
doesn't have one); you're always Mohamed Fouad, Admin.

## Layout

```
src/
  app/          providers, routing, shell
    routes.tsx        route table
    AppShell.tsx      scrollable content area + bottom tab bar
    AuthContext.tsx   the signed-in account
    ThemeContext.tsx  light / dark, persisted
    navigation.ts     the five tabs (Ask, Tools, People, System, Account)
  components/   ui.tsx, CamGrid, CameraFrame, CameraModal
  pages/
    Home.tsx          the "Ask" tab — question box, attention, campus stats, recent
    Tools.tsx          the seven-tool list
    ToolPage.tsx        one generic screen that renders any tool's fields/answer —
                         mirrors the design's single `ans` object instead of a
                         bespoke result type per tool (see services/api.ts::runTool)
    People.tsx / PeopleGroup.tsx / PersonHistory.tsx
    SystemPage.tsx      camera sources + the DVR/RTSP/IP onboarding flow
    Account.tsx         school profile, alerts, delivery channels, appearance
  services/     THE SEAM — services/api.ts (runTool + everything else),
                services/ask.ts (question router), services/mockData.ts (fixtures)
  types.ts      shapes the UI renders — ToolAnswer is the load-bearing one
  styles/       tokens.css (shared palette with the web app) + app.css
```

## Wiring the AI later

Same seam as the web app: replace the bodies in `src/services/api.ts` with
real calls. `runTool(id, values)` is the one function every tool screen goes
through — a real backend can keep that signature and swap the body for a
fetch.

## Deliberate honesty in the UI

Carried over from the design, same as the web console: cameras say NO SIGNAL
rather than freezing a fake "live" frame, the weapon workflow always waits for
a person to confirm or dismiss, "Track a person" says the search is logged
before showing the result, and the camera-onboarding forms are here so IT can
add sources from a phone, not just the desk.
