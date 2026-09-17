# Contract: the phone's shell

What surrounds every signed-in phone screen. It lives only in the phone's
`app/AppShell.tsx` and `styles/phone.css`, and nothing here is shared with the
console.

```
┌──────────────────────────────────────┐  ← pinned. Never scrolls.
│ Thu 11 Sep · Greenfield Int…  ✓ All 12 cameras up  (MF) │  status line
├──────────────────────────────────────┤
│ ‹ Back                               │  back row (not on a tab's top)
│ Knife alerts                         │  the shared screen, from its PageHeader
│ …                                    │  scrolls
├──────────────────────────────────────┤
│  Ask   Tools   People   System   Account │  pinned tab bar (unchanged)
└──────────────────────────────────────┘
```

## Status line (P13-FR-035, FR-041, SC-004)

| | Rule |
|---|---|
| Shown | on every signed-in screen, pinned above the scrolling content |
| Height | one slim line; less padding when held sideways (`max-height: 500px`) |
| Order | date and school (one block, shortening from its end) · camera status · initials. It follows the document's `dir`, so Arabic reverses it with no extra code |
| Camera status | the shared `CameraStatus` helper (data-model): the console's words, colour and glyph. **Never shortened** |
| School | `useSiteName()`. It is the first thing to shorten at 360 px |
| Date | the short form of `useSite().todayLabel`: the school's date as the engine reports it |
| Initials | the console's `.avatar` with `useAccount().initials` |
| Tap | opens a small panel with the school, date and time, the camera sentence, the name and the role (`role.admin` / `role.it`), plus a link to the Account tab. Tapping outside or pressing back closes it |
| Before the first answer | "Checking cameras…", no count, no zero |
| Engine unreachable | `topbar.engineUnreachable` within one 30 s refresh |
| Requests added | none. `SiteProvider` already fetches `/site` every 30 s on the phone |
| Not shown | the console sidebar's permanent "Campus is calm", or anything else not from the engine |
| Accessibility | the line is a `button` whose name is the full camera sentence plus the school; at least 44 px tall |

## Back row (P13-FR-036, SC-005)

| | Rule |
|---|---|
| Shown | on every path that is not a tab's top. Tab tops: `/`, `/tools`, `/people`, `/system`, `/account` |
| Where | the top of the scrolling content, above the shared screen's own heading. It scrolls with the page, and the shell already scrolls to the top on each new screen |
| Label | `‹` (with `mirror-rtl`) plus `t('action.back')` |
| Target | `location.key !== 'default'` → `navigate(-1)`; otherwise → `navigate(TABS[tabFor(pathname)].path)` |
| Size | at least 44 px tall, with padding so its tap area reaches the screen's start edge |
| Duplicates | shared screens that carry their own back link wrap it in `ConsoleOnly`, so the phone never shows two |

## The frame

| | Rule |
|---|---|
| Structure | `.app` (full dynamic viewport height) → status line (pinned) → `.app__content` (the only thing that scrolls) → tab bar (pinned) |
| Notches | status line padding includes `env(safe-area-inset-top)`, and the tab bar keeps `env(safe-area-inset-bottom)` |
| Keyboard | only `.app__content` scrolls, so the field being typed in scrolls into view normally |
| Scroll reset | on a path change `.app__content` scrolls to the top, as now |

## Tab bar

Unchanged: five tabs, labels from `nav.tab.*`, and the icons it has today.
Sideways, the labels hide behind their icons. Every tab stays at least
44 × 44 px.
