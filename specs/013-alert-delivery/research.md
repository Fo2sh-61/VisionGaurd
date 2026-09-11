# Research: Alert Delivery

*Partly superseded on 11 Sep 2026 while writing tasks. §3: missing term dates write no
row, Settings says so instead, and `engine_down_at_noon` is written only when the sender
started after the report time. §4: only channels switched on in
a rule write rows, so the key check is a duplicate guard rather than proof every event
left a row. §5: a failed attempt no longer blocks the sender; it is due again 5 s later.
§6: Settings states travel as facts, not note codes; only the Home feed uses note codes.
§9: a second acknowledgement is a 404, not a 409. The current design is in
data-model.md and contracts/alerts.md; the reasons are in tasks.md, "Design corrections".*

Nine decisions, each with what was rejected. Everything here was checked against the code
on 11 Sep 2026; nothing is assumed from the mock.

## 1. Transport: standard library only, no Twilio SDK

**Decision**: Twilio through one HTTPS POST with basic auth
(`https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json`, form body `From`, `To`,
`Body`), using `urllib.request`. Gmail through `smtplib.SMTP_SSL("smtp.gmail.com", 465)`
with `email.message.EmailMessage`. **No new line in `engine/requirements.txt`.**

**Rationale**: `twilio` is not installed and would be a new package to keep working on
Python 3.14 for one endpoint. `httpx` is present only as a transitive dependency of
`google-genai` and is unpinned, so importing it directly is a dependency nobody declared.
Twilio's error body is JSON with `message` and `code`; that text is the courier's own
reason and goes into the log verbatim (P9-FR-023). SMTP failures raise
`smtplib.SMTPException` subclasses whose message is likewise the courier's words.

**Alternatives**: the Twilio SDK (heavier, async extras, another version to pin); `httpx`
(undeclared); Gmail's REST API (OAuth, which the owner excluded).

## 2. Where an event is raised: a listener on the store, not the worker

**Decision**: `WeaponSceneStore`, `SceneStore` and `VehicleStore` each get one optional
`on_open` / `on_pass` callable, set after construction by the lifespan and invoked **after
commit**, still on the caller's thread, with the row's id and facts. The callback does one
thing: `AlertService.enqueue(event)`, which is a non-blocking queue put.

**Rationale**: the committed row *is* the event, which is what "one message per event"
means (P9-FR-005). Hooking the workers would mean touching `features/weapons.py`,
`features/zones.py` and `features/vehicles.py`, three files whose tests are about frames,
and would make the alert a second definition of "a scene opened". The store already runs
on the camera thread and already does a SQLite insert there; a `put_nowait` is cheaper
than that insert.

**Alternatives**: a bus subscription on `FrameBus` (wrong layer; frames are not events);
polling the tables from the sender thread (adds latency and a second source of truth for
"new"); wrapping the workers' `_open` (three files instead of three one-line hooks).

The verdict has no store hook: `LiveStore.review_weapon` calls the service directly after
`weapon_scenes.review()` returns True. It runs on a request thread, not a camera thread.

## 3. Camera offline and the noon report: the sender thread's own tick

**Decision**: the one sender thread loops on `queue.get(timeout=15)`. On every wake it
also (a) reads `registry.workers[*].status` and raises `camera down` / `camera up` events
on transitions that have lasted `camera_offline_minutes`, and (b) checks whether today's
attendance report is due. No scheduler, no second thread, no timer.

**Rationale**: the spec asks for the smallest mechanism that fires once a day and never
twice after a restart. A 15-second tick on a thread that already exists costs nothing and
needs no new concurrency. "Once" is guaranteed by the delivery log itself (decision 4).

**Noon rule**: on a school day, if site-local time is in `[12:00, 12:10)` and no row exists
for `attendance:<date>`, send. If site-local time is `>= 12:10` and no row exists for
today, write one `skipped` row with reason `engine_down_at_noon` and never send late
(P9-FR-021). Site-local time comes from `SiteClock.local(now)` per instant.

**School day**: weekday in Sunday to Thursday **and** `term_from <= date <= term_to` from
`config.hours`. Both term fields may be empty strings today; empty means "no term set" and
the report is written as `skipped` with reason `no_term_dates`, so the absence is visible.

**Alternatives**: `threading.Timer` (a second thread and its own restart problem);
`sched` (same); a cron entry (outside the engine, invisible to System Health).

## 4. Deduplication and restart safety: the delivery log is the ledger

**Decision**: every alert event has a stable `event_key`:

| Event | Key |
|---|---|
| knife entry opened | `weapon:<scene_id>:opened` |
| knife verdict | `weapon:<scene_id>:verdict` |
| zone scene opened | `intrusion:<scene_id>` |
| gate alert | `vehicles:<pass_id>` |
| camera down | `camera:<camera_id>:down:<since_iso>` |
| camera back | `camera:<camera_id>:up:<at_iso>` |
| attendance report | `attendance:<yyyy-mm-dd>` |
| test send | `test:<recipient_id>:<uuid>` |

Before fanning out, the service asks the log `has_rows(event_key)`. Every event writes at
least one row — a `sent`/`failed` row per recipient and channel, or a `skipped` row per
channel that could not be used — so the check is exact and there is no separate
"events" table.

**Camera state after a restart**: the service seeds its in-memory camera state from the
newest `camera:<id>:*` row per camera. A camera still down whose last row is `down` is not
re-announced; a camera that is up now whose last row is `down` gets one `up` message.

**Rationale**: one table answers "was this sent" and "what happened", and a restart cannot
disagree with it. P9-FR-005, SC-002.

**Alternatives**: an `alert_event` table (a fifth table whose only job is a uniqueness
check the log already provides); an in-memory `seen` set (lost on restart, which is the
exact failure the spec names).

## 5. Bounded queue and the full-queue rule

**Decision**: `queue.Queue(maxsize=alerts.queue_size)` (default 200). On `Full`, the
enqueuing thread pops the oldest, writes it to the log as `failed` with reason
`queue_full` (one insert, the same cost as the store insert that just happened), then
puts the new event. Retries: 3 attempts, 5 s apart, blocking the sender thread only.
Provider timeout `alerts.timeout_seconds` (default 10).

**Rationale**: P9-FR-029/030. Two hundred events is a week of alerts at this school; if it
fills, the courier is down and the log must say so per event. Dropping the newest would
lose the knife that just opened, which is the wrong end.

## 6. Recipients, rules and the honest states cross the wire as facts plus codes

**Decision**: `GET /settings/alerts` returns one `AlertSettings` object: the rules, the
recipients, a `channels` list with each external channel's `configured` flag and, when
unconfigured, a note code naming the missing variables, plus `console_url_set` and
`arabic_reviewed` flags. The console words every state through `i18n` from those codes
(P11). Delivery log rows carry `outcome`, a `reason_code`, and `provider_reason` (the
courier's own text, shown verbatim because it is a fact from outside, not a sentence the
engine wrote).

The old `GET /settings/delivery` is removed; `DeliveryTarget` (one destination per
channel) is replaced by `Recipient` (many per channel). `AlertRule` loses `push/email/sms`
and gains `in_app/whatsapp/sms/email` plus, on the `vehicles` row only, three reason
switches.

**Rationale**: the spec's honest states (P9-FR-026/027) are exactly the kind of sentence
P11 moved to the console. The exception for message bodies (P9-FR-009) does not extend to
the Settings page, which has a console at the far end.

## 7. Arabic: drafted in the engine, sent only when reviewed

**Decision**: `vg/alerts/catalogue.py` holds every template in both languages. A module
constant `ARABIC_REVIEWED = False` gates sending. While False, a recipient whose language
is `ar` receives English, the Settings row shows note `alerts.arabic_unreviewed`, and the
`arabic_reviewed` flag on `AlertSettings` is false. Setting `alerts.send_draft_arabic: true`
in `engine.yaml` sends the draft anyway, which is how Mohamed reviews it on a real phone.
Flipping the constant to True after review is the whole release step, mirroring the move
from `ar.draft.ts` to `ar.ts`.

**Rationale**: the same caveat Ask carried. SC-007's Arabic half is met when the constant
flips; until then the page says so rather than sending unreviewed text to a head of
security.

## 8. The console link

**Decision**: `alerts.console_url` in `engine.yaml` (default empty). The message builder
appends `<console_url>/<page>` when set. When empty, no link is sent and Settings shows
note `alerts.no_console_url`. The engine cannot know the console's origin from a request
that came through the dev proxy or a reverse proxy, so guessing would send a dead link.

## 9. Acknowledging in-app items

**Decision**: attention item ids are the event keys above without the suffix
(`weapon:<id>`, `intrusion:<id>`, `vehicles:<pass_id>`, `camera:<id>:<since_iso>`).
`attention_ack(item_id, by, at)` is the one new row an acknowledgement writes. The feed is
derived on every read from the live stores minus today's acks. `POST /attention/{id}/ack`
takes the actor from the session (`CurrentUser`), not from the body; the body-supplied
`Acknowledgement.actor` is dropped, for the same reason `review_weapon` ignores
`review.actor`. `/attention` is under no admin prefix, so a guard can already POST it; a
test pins that this stays true and that `/settings` writes do not.

**Rationale**: P9-FR-017/018/033, and the existing `vehicle_alerts` docstring: two
surfaces, one record, acknowledged independently. A blacklist pass dismissed on the
Vehicles page still shows on Home until acknowledged there, as today's code intends.

## Facts about Twilio WhatsApp the owner must know before SC-001 can pass

- A WhatsApp sender on Twilio is either the **sandbox** (each recipient must first send
  the join phrase to the sandbox number, and it is for testing only) or an **approved
  WhatsApp Business sender**, which takes Meta approval.
- Business-initiated WhatsApp messages outside a 24-hour customer window must use an
  **approved message template**; a free-form body is rejected by Meta with a Twilio error
  such as 63016. Alerts are business-initiated by definition.
- So: SC-001 can be proved on the sandbox with free-form text today. Production WhatsApp
  needs Mohamed to register a sender and get the alert templates approved. The code path
  is the same; only `TWILIO_WHATSAPP_FROM` and the body's compliance change. When Twilio
  refuses, the log row carries its reason, which is the spec's intended behaviour.
- SMS to Egyptian numbers from a Twilio number works without templates, subject to
  Twilio's country rules for the sender.
- Gmail App Passwords require 2-step verification on the Google account.

These are provider facts, not code decisions; they go in `quickstart.md` as prerequisites.
