# Data model: Alert Delivery

Four tables in the existing SQLite database (`_database(cfg)`, WAL on), created with
`CREATE TABLE IF NOT EXISTS` in a `SCHEMA` string exactly as `events/weapons.py` does.
One store class, `vg/alerts/store.py::AlertStore`, owns all four with one `RLock`.

*Revised 11 Sep 2026 while writing tasks: the reason codes travel as an enum rather than
as note codes, the settings honest states travel as facts, rows are written before any
courier call, and a two-minute continuation sends nothing. The reasons are in
[tasks.md](./tasks.md), "Design corrections".*

## Tables

### `alert_recipient`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `uuid4().hex` |
| `channel` | TEXT | `whatsapp` \| `sms` \| `email`. Fixed after creation |
| `destination` | TEXT | E.164 (`+201001234567`) for phone channels, an address for email. Normalised and validated on write |
| `name` | TEXT | display name, shown in the log |
| `language` | TEXT | `en` \| `ar` |
| `enabled` | INTEGER | 1/0 |
| `created_at` | TEXT | ISO UTC |

`UNIQUE (channel, destination)`: the same number twice on one channel is one row.

**Validation** (`store.py::normalise_destination(channel, raw)`): phone channels drop
spaces, dashes and brackets, then must match `^\+[1-9]\d{7,14}$`; email must match
`^[^@\s]+@[^@\s]+\.[^@\s]+$` and is lower-cased. Anything else is a `ValueError` whose
message is the field name, and the endpoint answers 422.

### `alert_rule`

| Column | Type | Notes |
|---|---|---|
| `kind` | TEXT PK | `weapon` \| `intrusion` \| `vehicles` \| `camera` \| `attendance` |
| `in_app` | INTEGER NULL | default 1. **NULL for `attendance`**: the report has no Home item, so the chip is not offered |
| `whatsapp` | INTEGER | default 0 |
| `sms` | INTEGER | default 0 |
| `email` | INTEGER | default 0 |
| `vehicle_blacklist` | INTEGER NULL | default 1 on `vehicles`, NULL on every other row |
| `vehicle_unknown` | INTEGER NULL | default 1 on `vehicles`, NULL elsewhere |
| `vehicle_expired` | INTEGER NULL | default 1 on `vehicles`, NULL elsewhere |

Five rows are seeded with `INSERT OR IGNORE` on every open (P9-FR-015). A rule is never
deleted. The three vehicle switches decide which gate alerts count **on every channel of
the row, In-app included**: a switch that silently skipped one chip would be a hidden rule.

### `alert_delivery`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | |
| `event_key` | TEXT | see below; indexed |
| `kind` | TEXT | alert kind, or `test` |
| `channel` | TEXT NULL | `whatsapp` \| `sms` \| `email`; NULL only on a `queue_full` row |
| `recipient_id` | TEXT NULL | NULL on a row that had no recipient |
| `recipient_name` | TEXT NULL | copied at write time, so a removed recipient still reads |
| `language` | TEXT NULL | the language the message was built in |
| `outcome` | TEXT | `queued` \| `sent` \| `failed` \| `skipped` |
| `reason` | TEXT NULL | one of the reason codes below |
| `provider_reason` | TEXT NULL | the courier's own words, redacted of every secret value |
| `provider_id` | TEXT NULL | Twilio message SID or the email's Message-ID, for `sent` |
| `attempts` | INTEGER | 0..`retries` |
| `queued_at` | TEXT | ISO UTC |
| `finished_at` | TEXT NULL | ISO UTC |

Rows older than `alerts.log_retention_days` (default 90) are deleted by the sender thread
once a day. Nothing else deletes here. **The message body is never stored**: the event
plus the catalogue rebuilds it, and a stored body is one more place a name could leak.

**Event keys** — one per thing that happened:

| Event | Key |
|---|---|
| knife entry opened | `weapon:<scene_id>:opened` |
| knife verdict | `weapon:<scene_id>:verdict` |
| zone scene opened | `intrusion:<scene_id>` |
| gate alert | `vehicles:<pass_id>` |
| camera dark for N minutes | `camera:<camera_id>:down:<since_iso>` |
| camera back | `camera:<camera_id>:up:<at_iso>` |
| attendance report | `attendance:<yyyy-mm-dd>` |
| test send | `test:<recipient_id>:<uuid4 hex>` |

**Reason codes** (`schemas.py::DeliveryReason`, worded by the console under
`settings.alerts.reason.*`):

| Code | Outcome | Meaning |
|---|---|---|
| `no_recipients` | skipped | the channel is on for this kind and nobody enabled receives on it |
| `provider_missing` | skipped | the `.env` variables for this channel are not set |
| `recipient_off` | skipped | this recipient is switched off |
| `engine_down_at_noon` | skipped | the report window passed while the sender was not running |
| `attendance_unavailable` | skipped | face recognition is not running, so the counts would be invented |
| `queue_full` | failed | dropped as the oldest when the hand-off queue filled |
| `engine_stopped` | failed | still `queued` when the engine stopped; marked on the next start |
| `provider_refused` | failed | the courier answered with an error; `provider_reason` set |
| `timeout` | failed | no answer within `alerts.timeout_seconds` |
| `unreachable` | failed | connection error; `provider_reason` set |

A channel switched **off** in the kind's rule writes no row at all: it is not an attempt.

### `attention_ack`

| Column | Type | Notes |
|---|---|---|
| `item_id` | TEXT PK | `weapon:<id>`, `intrusion:<id>`, `vehicles:<pass_id>`, `camera:<id>:<since_iso>` |
| `by_who` | TEXT | account name (`by` is an SQL keyword) |
| `at` | TEXT | ISO UTC |

An acknowledged item stays acknowledged. There is no undo, as with gate dismissals.

## In-memory shapes (engine)

### `AlertEvent` (`vg/alerts/events.py`, frozen dataclass)

`kind`, `template` (the catalogue entry, e.g. `vehicles.expired`), `event_key`, `at: datetime`, `camera_id: str | None`, `camera_name: str | None`
(filled on the sender thread, never on a camera thread), `facts: Mapping[str, str | int |
float]`, `groups: tuple[GroupCount, ...] | None` (report only; `None` means attendance is
not being recorded), `recipient_id: str | None` (test sends only).

`ALLOWED_FACTS = {"confidence", "verdict", "reviewer", "plate", "gate", "reason",
"weak_read", "since"}`. `__post_init__` raises `ValueError` on any other key. **This is
the structural guarantee that nothing about a minor leaves**: there is no field a
student's name, a face or a file path can travel in. `GroupCount` is `(name, present,
late, absent)` — a group name such as "Grade 8", never a person.

`offline_cameras(workers, now, minutes, started_at) -> dict[camera_id, since]` lives here
too, so the Home feed and the sender use one rule: a worker whose `status` is not `ok`
and whose `source.health.last_frame_at` (or `started_at`, if no frame has arrived since
the engine started) is at least `minutes` old.

### `Message` (`vg/alerts/catalogue.py`)

`subject` (email only), `body`, `language`. Built by `build(event, language, *, clock,
console_url, send_draft_arabic) -> Message`. Pure function, no I/O. Event messages are at
most 320 characters; the attendance report is capped at 1500 and ends "…and N more
groups" when cut.

### `Sender` (`vg/alerts/providers.py`)

`send(message, destination) -> SendResult(ok, provider_id, reason, provider_reason)`.
One implementation per channel: `TwilioSender(channel)` for `whatsapp` and `sms` (same
class; WhatsApp prefixes `whatsapp:` to both numbers), and `GmailSender()`. Each takes an
injectable transport so no test touches the network. `missing_env(channel) -> list[str]`
names the unset variables; `for_channel(channel)` returns `None` when any is missing.

### `AlertService` (`vg/alerts/service.py`)

Holds the hand-off queue, one daemon thread, `_pending` (row id → event, recipient,
channel, attempts, due time) and `_announced_down` (camera ids already reported dark).
Public surface: `start()`, `stop()`, `enqueue(event)`, the three store hooks
`on_weapon_open`, `on_zone_open`, `on_pass`, `verdict(...)` for `review_weapon`,
`test_send(recipient_id) -> row_id`, `bind(camera_name, attendance_counts)`, `started_at`,
`running`.

## Wire types (engine `schemas.py` → `web/src/services/wire.ts`, byte-copied to mobile)

| Type | Fields |
|---|---|
| `AlertRule` (changed) | `kind`, `in_app: bool \| None`, `whatsapp`, `sms`, `email`, `vehicle_blacklist \| None`, `vehicle_unknown \| None`, `vehicle_expired \| None`. No `title`/`detail`: the console words the kind |
| `AlertRuleUpdate` | the same flags, all optional |
| `Recipient` (new) | `id`, `channel`, `destination`, `name`, `language`, `enabled`, `created_at: Instant` |
| `RecipientCreate` | `channel`, `destination`, `name`, `language = "en"`, `enabled = True` |
| `RecipientUpdate` | `destination?`, `name?`, `language?`, `enabled?` |
| `ChannelStatus` (new) | `channel`, `configured: bool`, `missing: list[str]` (variable names, never values) |
| `Unreached` (new) | `kind`, `channel` — a rule channel that is on with nobody enabled on it |
| `ReportStatus` (new) | `time: "12:00"`, `state: scheduled \| no_term_dates \| before_term \| after_term`, `term_from`, `term_to` |
| `AlertSettings` (new) | `sending: running \| off \| failed`, `sending_error: str \| None`, `rules`, `recipients`, `channels`, `unreached`, `report`, `camera_offline_minutes`, `console_url_set`, `arabic_reviewed` |
| `DeliveryRow` (new) | `id`, `at: Instant`, `kind`, `channel \| None`, `recipient_name \| None`, `outcome`, `reason \| None`, `provider_reason \| None`, `provider_id \| None`, `attempts` |
| `DeliveryLog` (new) | `available: bool`, `reason: str \| None`, `rows: list[DeliveryRow]` |
| `AttentionItem` (changed) | `kind` literal gains `vehicles`; new `note: Note \| None` — the live feed puts the subject (camera name or plate) in `title`, leaves `detail` empty, and says what happened in `note` |
| `Acknowledgement` (removed) | the actor comes from the session |
| `DeliveryTarget` (removed) | replaced by `Recipient` |

`Note` is the existing P11 shape, `{code, args}`. Six new codes in `notes.py::CODES`, each
emitted by a literal `note("…")` call in `LiveStore.attention()`: `attention.weapon`
(`confidence`), `attention.intrusion`, `attention.vehicles.blacklist` (`gate`),
`attention.vehicles.unknown` (`gate`), `attention.vehicles.expired` (`gate`),
`attention.camera` (`minutes`). **Settings uses no note codes**: every state there is an
enum or a fact the console words, which keeps `test_notes.py`'s literal-code scan simple.

## State transitions

```
event arrives on the hand-off queue
  └─ sender thread records it, before any courier call:
       one `queued` row per enabled recipient on each channel the rule has on
       one `skipped` row per recipient switched off
       one `skipped` row per on-channel with no provider or nobody to receive
[queued] ── courier accepted ─────────────────────────────▶ [sent: provider_id]
[queued] ── refused / timeout / unreachable, attempts < 3 ──▶ [queued] (due again in 5 s)
[queued] ── refused / timeout / unreachable, attempts = 3 ──▶ [failed: reason, provider_reason]
[queued] ── engine stops before it is sent ──────────────────▶ [failed: engine_stopped]
hand-off queue full: the oldest event ───────────────────────▶ one [failed: queue_full] row
```

`skipped` is terminal. The sender records everything waiting on the queue before each
courier call, so an event is unrecorded for at most one call (`timeout_seconds`).

## Config (`engine/vg/config.py::AlertsConfig`, `engine.yaml` `alerts:`)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false`: the sender does not start, nothing is sent by WhatsApp, SMS or email, and Settings and System Health say so. The Home list still works |
| `camera_offline_minutes` | `5` | NO SIGNAL for this long raises `camera` |
| `report_time` | `"12:00"` | site-local time of the attendance report |
| `timeout_seconds` | `10.0` | per courier call |
| `queue_size` | `200` | the hand-off queue |
| `retries` | `3` | attempts per message, 5 s apart |
| `log_retention_days` | `90` | |
| `send_draft_arabic` | `false` | send the unreviewed Arabic column, for review on a real phone |
| `console_url` | `""` | origin the message link is built from; empty means no link |

Secrets, never in yaml: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
`TWILIO_SMS_FROM`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, read from `os.environ` at send time
(`config._load_dotenv` already fills it at load).
