# Contract — the phone's vocabulary

A copied page is not edited. It compiles because the phone provides the same
names it asks for. This page is that promise, written down.

**The rule**: the phone's `components/ui.tsx` exports every name the console's
does, with the same props and the same *meaning*. The body may look completely
different. `Badge tone="bad"` may be a different shape on a phone; it may not be
a different tone, and it may not be absent.

## The 14 exports

From `web/src/components/ui.tsx`, which every page imports from:

| Export | Props | Meaning that must not change |
|---|---|---|
| `toneColors` | `Record<Tone, {bg, fg}>` | Which colour a tone is |
| `toneGlyph` | `Record<Tone, string>` | The character that stands for a tone where colour alone would not carry |
| `Badge` | `{tone, children, icon?}` | A state, coloured by severity |
| `Card` | `{children, tight?}` | A grouping boundary |
| `CardHeader` | `{title, sub?}` | What the card is |
| `PageHeader` | `{title, lead}` | What the screen is |
| `Stats` | `{items, columns?}` | Headline figures. `columns` is a **hint** — the phone may ignore it and choose its own, because 4 across at 375 px is unreadable |
| `Field` | label + control | A labelled input |
| `Select` | options + value + onChange | A choice among named options |
| `Toggle` | `{on, onToggle, label}` | An on/off setting |
| `DataNotice` | `{capability}` | **Load-bearing.** Says a feature is demo, degraded or absent. The phone must never omit it — the whole honesty rule runs through this component |
| `Empty` | `{children}` | Nothing to show, and why |
| `LoadError` | error + retry | The request failed, with the reason and a way to try again |
| `StatusDot` | `{tone, children}` | A small state marker |

**`DataNotice` deserves the emphasis.** It is how a screen says "this is demo
data" or "this subsystem is not running". A phone `ui.tsx` that quietly rendered
`null` for it would satisfy the compiler and break constitution principle III on
every screen at once. It is the first thing to check.

## The CSS classes a copied page uses

The phone's `app.css` must define these, whatever it makes them look like:

| Class | Console | Phone |
|---|---|---|
| `.page` | Padded content column | Same idea, phone padding, bottom room for the tab bar |
| `.card` | Panel with a border | Same |
| `.row` | **A grid**; each call site sets `gridTemplateColumns` inline | **A flex column.** First child is the headline; the rest render as one muted line joined by `·`; detail opens on tap. The inline `gridTemplateColumns` becomes inert rather than fought — see `research.md` §4 |
| `.row--head` | Column headings | `display: none` — a header over stacked rows means nothing |
| `.row--click` | Hover and focus states | Tap state and a chevron |
| `.list-row` | Full-width button | Same |
| `.stats` / `.stat` | Grid of figures | Two across, not four |
| `.chip-btn` `.chip-btn--on` `.chip-btn--off` `.linkbtn` | Buttons | Same names, thumb-sized targets |
| `.grid-2` `.grid-3` `.grid-4` | Multi-column | All single-column |

**Write it with logical properties** — `padding-inline-start`, not
`padding-left`; `margin-inline-end`, not `margin-right`. Arabic flips the whole
document via `documentElement.dir`, and logical properties mean one stylesheet
serves both directions instead of two that drift.

## What the shell must provide

A copied page assumes it is inside these providers, in this order — the console's
`main.tsx` order, which is not arbitrary: `LanguageContext` reads the account, so
`AuthProvider` must be outside it.

```
ThemeProvider
  AuthProvider
    LanguageProvider
      SiteProvider
        CameraProvider
          CapabilityProvider
            <routes>
```

And these router facts, because pages use them directly:

- `useSearchParams` — Ask deep-links land on a page with its question already
  applied (`?window=last7`, `?person=…`). The phone must keep the same query
  parameter names or every Ask answer stops opening the right screen.
- `useNavigate` and `useParams` — person history and group rosters are routed
  by name.

## What the shell must not do

- **Must not store a role, an account or a token.** The console has a test
  asserting this. The phone copies `AuthContext` and `http.ts` unchanged; the
  shell must not add a convenience cache on top.
- **Must not decide permissions.** `RequireRole` hides a tab. The engine
  refuses the request. Those are different jobs and the second is the real one.
- **Must not pass `detections` to a `CameraFrame` on a page that must not name
  anybody.** `AGENTS.md`: a live `CameraFrame` also polls recognition boxes,
  which carry names. Pages already pass `detections={false}` where required —
  copying the page body preserves that, and the phone's `CamGrid` must not
  override it.
