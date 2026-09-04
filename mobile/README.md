# VisionGuard AI — mobile app

The phone app. A **parallel, independent app** to the web console (`../web/`),
against the same engine: the same product, all of it, in a shape made for a
hand.

Not a responsive view of the console, and not a subset of it. Its own package,
its own build, its own design — and every screen the console has.

Until 3 September 2026 this was a prototype made entirely of fixtures, in which
any password signed you in and some of the campus figures were regenerated at
random on each visit. All of that is gone. If the engine cannot be reached, the
phone says so and shows nothing.

See `../README.md` for the repository overview.

```bash
npm install
npm run dev      # http://localhost:5174
npm run build    # typecheck + production build
```

Or, from the repository root, both front ends and the engine at once:

```powershell
.\dev.ps1 up -Clip -Mobile -AllowSystemPython
```

Sign in with a real account. If nobody has one yet, nothing can sign in on
either app:

```bash
python engine/tools/create_user.py
```

## How it relates to the console

Three piles, and knowing which one a file is in is most of what you need.

**Pile 1 — copied byte-for-byte, and held that way.** Everything that decides
*what is true*: `types.ts`, `services/`, `i18n/`, the contexts and hooks in
`app/`, `styles/tokens.css`, and `app/navigation.ts`. 26 files. They are
identical to `web/src`, and `tools/check_parity.py` fails the build if they
ever stop being.

Editing one of these here without editing the same file in `web/` is the one
mistake this layout makes easy, which is why it is the one mistake that is
checked on every push. Change both, in the same commit.

**Pile 2 — copied, and not edited.** All 16 pages and the 13 feature
components. They are byte copies of the console's. They compile here because
Pile 3 gives them the same vocabulary under a different skin.

If a page looks wrong on a phone, the fix is in Pile 3. Editing a page body to
change a **rule** is a defect: the rules are in Pile 1.

**Pile 3 — written for the phone.** `components/ui.tsx`, `styles/app.css`, the
shell (`app/AppShell.tsx`, `app/tabs.ts`, `app/routes.tsx`, `main.tsx`), and
the two screens the console has no need of (`pages/Tools.tsx`,
`pages/Account.tsx` — the console's sidebar already is them). About 1,600
lines. This is where the phone is allowed to look like a phone.

## Layout

```
src/
  app/
    navigation.ts     COPY — which tools exist. Never retyped: the fixture app
                        kept its own list of six and silently had no vehicle gate
    AuthContext.tsx   COPY — the session. Stores no role, no token
    CameraContext.tsx CapabilityContext.tsx SiteContext.tsx
    LanguageContext.tsx ThemeContext.tsx    COPY
    useAsync.ts useAttention.ts useAutoRun.ts useOptions.ts   COPY
    tabs.ts           the five bottom tabs, and which one owns a path
    AppShell.tsx      scrolling screen + tab bar. Renders <Outlet/> and nothing else
    routes.tsx        the console's paths, the console's guards
  components/
    ui.tsx            the phone's vocabulary — the console's 14 exports
    CameraFrame.tsx CamGrid.tsx CameraModal.tsx CameraSources.tsx
    Vehicle*.tsx Plate*.tsx RecordButton.tsx Logo.tsx          COPY
  pages/              all 16 console pages, COPY, plus Tools and Account
  services/           COPY — the only place the phone talks to the engine
  i18n/               COPY — every word, both languages, and which way each reads
  styles/
    tokens.css        COPY — the palette
    app.css           the phone's stylesheet
```

## Five tabs, sixteen screens

| Tab | Reaches |
|---|---|
| **Ask** | Home — question box, attention, campus figures |
| **Tools** | Attendance · Counting · Lost bag · Track · Restricted zones · Knives · Vehicle gate |
| **People** | The directory → a person's history, a group roster, and enrolment |
| **System** | System health, and camera setup (inside that page, as on the console) |
| **Account** | Settings, Accounts for an administrator, sign out |

The tool list is built from `app/navigation.ts`, the same table the console
renders its sidebar from. A tool added to the console appears here too.

## Things that are easy to get wrong

- **`.row` is not a grid here.** The console renders table rows as a grid and
  sets the columns inline, at 28 call sites. On a phone that is six unreadable
  slivers, and an inline style cannot be overridden by a stylesheet. So the
  phone's `.row` is a wrapping flex: the inline `grid-template-columns` becomes
  a property nothing reads, and no page is edited. First cell is the headline,
  the rest fold onto one line separated by `·`. Nothing is dropped.
- **The proxy is not optional.** `vite.config.ts` proxies every engine path.
  Camera streams are `<img src>`, an `<img>` cannot send an `Authorization`
  header, and the session cookie is `SameSite=Strict` — so without the proxy
  every tile is a black rectangle while detection carries on working perfectly
  on the server. It looks like a video bug and is an auth one.
- **`DataNotice` and `LoadError` must never quietly render nothing.** They are
  how a screen says "this is demo data" or "this failed". A version that
  returned `null` would compile and remove every honesty warning in the app at
  once.
- **Never override a page's `detections={false}`.** A live `CameraFrame` also
  polls recognition boxes, which carry names. Some pages must not show an
  identity, and they already say so.
- **The phone decides no permissions.** It stores no role and no token. A tab
  hidden from a guard is a courtesy; the engine is what refuses the request.
- **Arabic is one `dir` flip.** `LanguageContext` sets `documentElement.dir`,
  so `app.css` uses logical properties (`padding-inline-start`, never
  `padding-left`) and there is no mirrored second stylesheet to keep in step.
  The Arabic wording is the same unproofread draft as the console's, and shows
  in development only.

## Gates

```powershell
.\dev.ps1 test          # from the repository root — runs all of these
```

```bash
node node_modules/typescript/bin/tsc -b --force   # in mobile/, never --noEmit
python tools/check_parity.py                      # the 26 shared files
python tools/check_parity.py --no-fixtures        # nothing invented
```

There is no JavaScript test runner in this repository, so nothing here proves a
screen *looks* right. That is confirmed by eye, on a phone —
`specs/012-mobile-parity/quickstart.md` lists exactly what to check.
