# Contract: alert settings, delivery log and the attention feed

Every path here is served by `engine/vg/api/app.py` and consumed only through
`web/src/services/api.ts` (byte-copied to the phone). Wire shapes are in
[data-model.md](../data-model.md). All bodies are camelCase on the wire, `extra="forbid"`.

*Revised 11 Sep 2026 while writing tasks — see [tasks.md](../tasks.md), "Design
corrections".*

## Permissions (decided by path in `auth/deps.py`)

| Prefix | Read | Write |
|---|---|---|
| `/settings` | any signed-in account | **administrator** (new: `/settings` joins `ADMIN_WRITE_PREFIXES`) |
| `/attention` | any signed-in account | any signed-in account (unchanged: under no admin prefix) |

A guard can read the rules and the log, cannot change them, and can acknowledge.

## Endpoints

### `GET /settings/alerts` → `AlertSettings`

Rules, recipients, channel statuses, rule channels nobody receives on, the report status,
whether sending is running, `consoleUrlSet`, `arabicReviewed`. Replaces the old
`list[AlertRule]` body. **`GET /settings/delivery` is removed.** Never a 5xx: with the
alert database unavailable it is `SubsystemUnavailable` → 503 with the reason.

### `PATCH /settings/alerts/rules/{kind}` → `AlertRule`

Body `AlertRuleUpdate`. PATCH, not PUT: it is a partial update, and `services/http.ts` has
no `put`. Unknown `kind` → 404. Setting `inApp` on `attendance`, or a vehicle switch on
any other kind → 422. Audit `alerts.rule` (subject: kind; detail: the flags that changed)
**before** the write.

### `POST /settings/alerts/recipients` → `Recipient` (201)

Body `RecipientCreate`. Destination normalised and validated (data-model.md) → 422 on
failure. Duplicate `(channel, destination)` → 409. Audit `alerts.recipient.add` (subject:
name; detail: channel and the destination masked to its last four characters) before the
insert.

### `PATCH /settings/alerts/recipients/{id}` → `Recipient`

Body `RecipientUpdate`. 404 if unknown. Audit `alerts.recipient.edit` before the write.

### `DELETE /settings/alerts/recipients/{id}` → 204

404 if unknown. Audit `alerts.recipient.remove` before the delete. Log rows keep
`recipient_name`, so history survives the removal.

### `POST /settings/alerts/recipients/{id}/test` → `DeliveryRow` (202)

Audit `alerts.test` before anything is recorded. Sends whatever the recipient's on/off
switch and the rules say — a test is the administrator proving the wiring. Returns the
row as recorded: `queued`, or `skipped: provider_missing`. The console re-reads the log to
see the outcome. 404 if unknown; 503 `SubsystemUnavailable` when the sender is not
running, with its reason.

### `GET /settings/alerts/deliveries?limit=50` → `DeliveryLog`

Newest first, `limit` capped at 200. `available=false` with `reason` when the table cannot
be read — status 200, never a 5xx (AGENTS rule 7).

### `GET /attention` → `list[AttentionItem]` (unchanged path, real data)

Derived on each read (below). Never a fixture on `LiveStore`.

### `POST /attention/{id}/ack` → `AttentionItem`

**No body.** The actor is the session account, as `POST /vehicles/alerts/{id}/dismiss`
does; the old body-supplied actor let anybody acknowledge under any name. 404 when the
id is not in the current feed, which includes an item already acknowledged. Audit
`attention.ack` before the row is written.

## The attention feed, derived

Built by `LiveStore.attention()` from the stores that hold the items, each kind filtered
by its rule's `in_app` flag, minus `attention_ack` rows, newest first.

| Item id | Source | Present while |
|---|---|---|
| `weapon:<scene_id>` | `weapon_scenes.pending()` — every entry still awaiting a verdict, any day | pending and not acknowledged |
| `intrusion:<scene_id>` | `scenes.recent(since_days=1)` with `started_at >= _start_of_day()` — running **or ended**; a breach that lasted ten seconds must not vanish before anybody looked | today, not acknowledged |
| `vehicles:<pass_id>` | `vehicle_alerts()` filtered by the rule's three reason switches | today, not dismissed on Vehicles, not acknowledged here (two surfaces, acknowledged independently) |
| `camera:<camera_id>:<since_iso>` | `events.offline_cameras(registry.workers, …)` | dark for `camera_offline_minutes` and not acknowledged; a new outage is a new item |

`title` is the subject — the camera name, or the plate as displayed. `detail` is empty.
`note` says what happened, worded by the console. `severity`: `critical` for a knife and
a blacklisted plate, `warn` for the rest. `useAttention.ts` gains `vehicles` in `TARGET`
and `ACTION`.

## Capability `attention` and the System Health row

| Where | State | Says |
|---|---|---|
| capability `attention` | LIVE, no reason | whenever the alert database is open |
| capability `attention` | UNAVAILABLE | "The alert database could not be opened (<error>), so nothing can be listed or sent." — and `attention()` returns `[]` |
| System Health stage `alerts` "Alert sending" | healthy | running, and every channel a rule uses has its keys — detail counts the last 24 h: sent, failed |
| System Health stage `alerts` | unhealthy, warn | a rule uses a channel whose keys are missing: "No TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM is set, so SMS cannot be sent. Detection is unaffected." |
| System Health stage `alerts` | healthy, info | `alerts.enabled: false`: "Switched off in engine.yaml - nothing is sent by WhatsApp, SMS or email. The Home list still works." |
| System Health stage `alerts` | unhealthy, warn | the sender failed to start: the error, and "Detection is unaffected." |

A LIVE capability carries no reason — `test_no_fixtures.py::test_a_live_capability_offers_no_excuse`
pins it — so a missing key is said on System Health and Settings, not on the capability.
Pipeline stage details are English sentences today, as every other stage's are.

## Messages (the one place the engine writes sentences, P9-FR-009)

Plain text, no markup. Event messages at most 320 characters; the report at most 1500.
In the recipient's language:

```
VisionGuard · <kind label>
<what happened>, <camera name>, <HH:MM site-local>
[confidence <n>%] [plate <text>, gate <n>] [plate read uncertain]
[awaiting review — not yet confirmed by a person | Confirmed by <name> | False alarm — <name>]
<console_url>/<page>                                 (only when console_url is set)
```

Pages: `weapons`, `intrusion`, `vehicles`, `system` (camera), `attendance`, and the root
for a test. Email is `text/plain` with no attachment. Forbidden by construction: any fact
outside `ALLOWED_FACTS`.

## Audit actions added

`alerts.rule`, `alerts.recipient.add`, `alerts.recipient.edit`, `alerts.recipient.remove`,
`alerts.test`, `attention.ack`. A destination appears in `detail` masked to its last four
characters. A secret never appears anywhere.
