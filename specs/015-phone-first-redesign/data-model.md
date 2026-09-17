# Data model: phone view models

No engine data changes. These are the shapes the phone's new frame and screens
hold in memory, all derived from types that already exist in `types.ts` and
`services/wire.ts`.

## TabDef (`mobile/src/app/tabs.ts`)

| Field | Type | Rule |
|---|---|---|
| `id` | `'home' \| 'cameras' \| 'tools' \| 'people' \| 'more'` | exactly five |
| `label` | `MessageKey` (`nav.tab.<id>`) | never literal English |
| `path` | `string` | `/`, `/cameras`, `/tools`, `/people`, `/more` |
| `icon` | SVG path, 18×18 viewBox | stroked |

## ScreenDef (`mobile/src/app/tabs.ts`)

| Field | Type | Rule |
|---|---|---|
| `prefix` | `string` | longest prefix wins; `/people/enrol` before `/people` |
| `tab` | `TabId` | which tab lights |
| `title` | `MessageKey` | shown in `ScreenHeader`; reuses `nav.<tool>.label` where one exists |
| `parent` | `string` | where back goes with no history |

`isTabRoot(path)` is true for the five tab paths only.

## AlertFeed (`app/useAlertFeed.ts`, shared)

| Field | Type | From |
|---|---|---|
| `feed` | `'down' \| 'failed' \| 'checking' \| 'off' \| 'ready'` | `useSite().error`, attention capability, request state |
| `line` | `{ color, glyph, title }` | `statusLine()` |
| `items` | `AttentionItem[]` | `getAttention()` minus acknowledged, worded by `toAttentionItem` |
| `unread` | `AttentionItem[]` | items whose id is not in the seen-list |
| `marker` | `{ text, color } \| null` | number, `9+`, `!`, or nothing while checking |
| `label` | `string` | `bell.titleNew` / `bell.title` |
| `rings` | `number` | increments when a new unread id arrives after the first answer |
| `capability` | `Capability \| null` | for `offLead`, reason, demo notice |
| `open()` | `() => string[]` | marks all current items seen; returns the ids that were unread (the "new" group) |
| `markSeen(ids)` | `(ids: string[]) => void` | while the list is showing |

Polls every 15 s. The seen-list is `localStorage['vg.alerts.seen.<accountId>']`,
capped at 500 ids.

## TodayFigure (`mobile/src/app/useTodayFigures.ts`, phone only)

| Field | Type | Rule |
|---|---|---|
| `id` | `'arrived' \| 'inView' \| 'carsIn' \| 'restricted'` | |
| `state` | `'checking' \| 'ready' \| 'off' \| 'failed'` | `off` when the feature's capability is `unavailable` |
| `value` | `string \| null` | the engine's figure as formatted text; `null` renders "—" |
| `detail` | `string` | engine wording (`result.sub`, late count, paused zones) or the capability reason |
| `to` | `string` | the tool path with the query the figure used |

Refresh: 30 s each. One failure never blanks the other three.

## CameraFilter (`mobile/src/pages/Cameras.tsx`)

`'all' | 'live' | 'offline'`. Counts are computed from `Camera.offline` over the
roster, and the groups keep first-appearance area order.

## Gap (`specs/015-phone-first-redesign/gaps.md`)

| Field | Rule |
|---|---|
| design part | as named on the canvas |
| reason | what the engine does not send, or why it was left out |
| instead | what the phone shows |
