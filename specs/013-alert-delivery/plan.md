# Implementation Plan: Alert Delivery — WhatsApp, SMS, Email and in-app

**Branch**: `013-alert-delivery` | **Date**: 11 Sep 2026 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-alert-delivery/spec.md`

## Summary

The engine grows one small package, `vg/alerts/`, with one queue and one thread. Three
stores that already write the events (`WeaponSceneStore`, `SceneStore`, `VehicleStore`)
each get a one-line listener that drops an event on the queue after the row commits. The
knife and zone workers cut a long incident at two minutes and reopen at once; they pass
one flag so the reopened entry sends nothing. The
sender thread drains it through one Twilio sender and one Gmail sender, writes a row per
attempt to a delivery log, and on its own 15-second tick also watches cameras go dark and
fires the noon attendance report. The console's Alerts section stops pretending: three
cards, every control saving through the engine, quiet hours gone. Home's "Needs your
attention" is derived from the same stores on every read and gains an Acknowledge button.

What is deliberately **not** built: a scheduler, a retry framework, a template engine, a
second provider per channel, a push service, a WebSocket, or a separate events table.

| Already there | What this feature does with it |
|---|---|
| `WeaponSceneStore.open`, `SceneStore.open`, `VehicleStore.finish_pass` | the three events; each gains an `on_*` callback invoked after commit, and `open()` gains `continues`. The gate's fires when the reader is done with the pass, not when it is first written (changed 11 Sep 2026, see §1) |
| `LiveStore.review_weapon` | the verdict event; the docstring that says "hangs nothing" is rewritten |
| `CameraWorker.status` (`ok`/`down`/`auth`) | polled by the sender thread for the camera kind |
| `LiveStore.attendance("group", …)` and `groups()` | the noon counts; the report adds no calculation |
| `SiteClock`, `_instant`, `_start_of_day` | every "today" and "12:00" |
| `MockStore._log` (inherited by `LiveStore`) | audit before the write, as everywhere |
| `notes.py::CODES` + `i18n` | the Home feed's sentences are note codes the console words; Settings states are enums and facts the console words |
| `vehicle_alerts()` + `dismiss_alert()` | the pattern for derived items and for a guard's one write |
| `_ask_state()` | the pattern for "no key set, detection unaffected" |
| `test_sources.py::SENTINEL` | the pattern for proving a secret never leaves |

## Technical Context

**Language/Version**: Python 3.14 (engine), TypeScript 5 / React (console and phone)

**Primary Dependencies**: existing FastAPI, Pydantic v2, sqlite3. **Nothing new.** Twilio
is one HTTPS POST via `urllib.request`; Gmail is `smtplib` + `email.message`. See
[research.md §1](./research.md).

**Storage**: four tables in the existing SQLite database (`alert_recipient`, `alert_rule`,
`alert_delivery`, `attention_ack`), created `IF NOT EXISTS` by `vg/alerts/store.py`. No
migration framework; same pattern as `weapon_scene`.

**Testing**: pytest. Five new files, one per story so each can be run alone:
`test_alerts.py` (events, catalogue, providers, store, sender core), `test_alerts_api.py`
(settings endpoints, permissions, audit order, secrets, mock-vs-live), `test_alerts_events.py`
(knife, verdict, zone, gate, camera), `test_alerts_feed.py` (Home feed, acknowledge) and
`test_alerts_report.py` (noon report). No test touches the network; the senders take an
injectable transport, and the service takes an injectable clock.

**Target Platform**: Windows workstation, same process as the engine.

**Project Type**: web service + browser console + phone app sharing contract files.

**Performance Goals**: a knife entry's message is queued within one store commit and
handed to the courier within 10 s (SC-002); nothing on the frame path grows by more than
one `put_nowait`. The sender thread may block on a courier for `timeout_seconds` × 3 per
message; nothing waits on it.

**Constraints**: no camera-thread I/O beyond the existing store insert; every write
audited first; secrets only in `.env` and never in any response, log row or audit entry;
no student name, face or image in any message, enforced by the event shape.

**Scale/Scope**: five alert kinds, three external channels, any number of recipients,
one sender thread, a 200-event queue. At the school's rate (a handful of events a day) the
queue is never near full; the full-queue path exists for a dead courier.

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 — see the end of this file.*

| Principle | How this feature satisfies it |
|---|---|
| **III — Truthful data** | Every Settings control writes through the engine and reads back what it wrote. `sent` is the courier's acceptance and carries its id; `failed` carries the courier's own text; `skipped` carries a code. The attention feed is derived from the stores that hold the items on every read, minus acknowledgements, so it cannot drift from the Weapons, Zones or Vehicles pages. `LiveStore` overrides every alert method and a test pins `LiveStore.x is not MockStore.x`. |
| **III — no fixtures** | `MockStore` keeps fixtures in the new shapes for `-Mock`; the live path shares none of them. |
| **IV — Secrets** | Six variables read from `os.environ` at send time. `AlertSettings.channels` reports *which variable names* are missing, never values. A `SENTINEL` token in each variable is asserted absent from every response, delivery row and audit entry. |
| **IV — Minors' data** | `AlertEvent.facts` accepts an allow-listed set of keys; the catalogue reads only those; there is no field a student's name or a path could travel in. Email is `text/plain` with no attachment. A test builds a zone message on a camera with a recognised student and greps for the name and any image path. Twilio and Google see every message; the owner accepts that on this basis (spec P9-FR-035), recorded here as Ask recorded Gemini's terms. |
| **IV — The human decision gate — deliberately amended** | PLAN §6 row "No notify/call/lock can be triggered by the detector" and the `review_weapon` docstring both become false and are rewritten in this feature. The detection message is the only thing that hangs from detection, marked awaiting review; the verdict sends the second. Cost stated in the spec: false alarms (one 12.5 s entry per ~four loops of clean footage) will reach phones. No lock, call or other action is added anywhere. |
| **II — A feature must not slow another** | One `put_nowait` on the camera thread. One daemon thread. A dead courier fills the queue, which drops the oldest with a logged reason, and nothing else notices. The service is optional in the lifespan: if it fails to start, System Health's alert row says so and every worker starts as before. |
| **V — No no-op controls** | Quiet hours is deleted. Every remaining control either saves or shows the error. The "Send test" button really sends. The disabled "Notify parent" button and its reason are untouched. |
| **Rule 8 — a subsystem that fails to start says so** | System Health gains an "Alert sending" row: unhealthy with the start error, or with the missing keys of any channel a rule uses. The `attention` capability describes the Home list, which needs only the alert database, so it stays LIVE with no reason while that is open (a LIVE capability never explains itself — pinned by `test_no_fixtures.py`). Settings says the same per channel. |
| **Rule 9 — no feature requires another** | The service starts with no cameras, no models and no keys; every other feature starts without it. |
| **Server-side permissions** | `/settings` joins `ADMIN_WRITE_PREFIXES`. `/attention` stays open to any signed-in account. Pinned in `test_alerts_api.py` and `test_alerts_feed.py`. |
| **Audit before the write** | `self._log(...)` first in every mutating store method, including the test send and the acknowledgement. |
| **Never claim precision the code lacks** | The report carries counts the Attendance page already computes; it does not de-duplicate across groups and says "per group". No delivery or read receipt is ever shown. |

**No violations. Complexity Tracking is therefore omitted.**

## Project Structure

### Documentation (this feature)

```text
specs/013-alert-delivery/
├── plan.md              # this file
├── research.md          # nine decisions, and the Twilio WhatsApp facts
├── data-model.md        # four tables, the event shape, the wire types, the config
├── contracts/
│   └── alerts.md        # the endpoints, the feed derivation, the message shape
├── quickstart.md        # how to prove it, with and without real keys
├── context.md           # handoff for the implementing chat
└── tasks.md             # /speckit-tasks writes this
```

### Source Code (repository root)

```text
engine/vg/alerts/                NEW — the whole engine half, five small files
├── __init__.py
├── events.py                    # AlertEvent (frozen), ALLOWED_FACTS, GroupCount, event constructors, offline_cameras()
├── catalogue.py                 # en + ar templates; build(event, language, …); ARABIC_REVIEWED
├── providers.py                 # Sender, SendResult, TwilioSender, GmailSender, missing_env(), for_channel(), redact()
├── store.py                     # AlertStore: the four tables; normalise_destination()
└── service.py                   # AlertService: hand-off queue, one thread, record-then-send, retries, camera + noon ticks, retention

engine/vg/events/weapons.py      # + on_open hook after commit; open(..., continues=False); + pending()
engine/vg/events/zones.py        # + on_open hook after commit; open(..., continues=False)
engine/vg/events/vehicles.py     # + on_pass hook, fired by finish_pass once the reader is done
engine/vg/features/weapons.py    # the two-minute cut passes continues=True — one argument, nothing else
engine/vg/features/zones.py      # the same

engine/vg/api/schemas.py         # AlertRule changed; DeliveryTarget/Acknowledgement removed; + Recipient*,
                                 #   ChannelStatus, Unreached, ReportStatus, AlertSettings, DeliveryRow,
                                 #   DeliveryLog; AttentionItem.kind + "vehicles", + note
engine/vg/api/notes.py           # + six attention.* codes, emitted by LiveStore.attention()
engine/vg/api/store.py           # Store protocol: seven alert methods replace two; MockStore fixtures in the new shapes
engine/vg/api/live.py            # LiveStore: alerts_store=, alerts=; attention(), acknowledge(), the settings
                                 #   methods; review_weapon calls alerts.verdict(); _attention_state();
                                 #   _alerts_stage() in health(); _attendance_counts() for the report
engine/vg/api/app.py             # the endpoints; lifespan builds AlertStore + AlertService before the workers,
                                 #   attaches each hook as its store appears, starts after LiveStore, stops after the workers
engine/vg/auth/deps.py           # + "/settings" in ADMIN_WRITE_PREFIXES
engine/vg/config.py              # + AlertsConfig; EngineConfig.alerts
engine/engine.yaml               # + alerts: block
engine/.env.example              # + the six variables, empty

engine/tests/test_alerts.py         # NEW — foundational units
engine/tests/test_alerts_api.py     # NEW — US1
engine/tests/test_alerts_events.py  # NEW — US2 + US3
engine/tests/test_alerts_feed.py    # NEW — US4
engine/tests/test_alerts_report.py  # NEW — US5
engine/tests/test_api.py            # REQUIRED route list: − /settings/delivery, + the new routes

web/src/services/wire.ts         # the new wire types                                   (parity → mobile)
web/src/types.ts                 # AlertChannel/AlertRule/DeliveryKind/DeliveryTarget removed (parity → mobile)
web/src/services/api.ts          # getAlertSettings, updateAlertRule, addRecipient, updateRecipient,
                                 #   removeRecipient, sendTestAlert, getDeliveries, acknowledgeAttention(id) (parity → mobile)
web/src/app/useAttention.ts      # + vehicles; renders item.note; returns { items, acknowledge } (parity → mobile)
web/src/i18n/keys.ts, en.ts, ar.draft.ts   # settings.alerts.*, attention.*, note.attention.* (parity → mobile)
web/src/pages/Settings.tsx       # three real cards; quiet hours removed   (byte copy → mobile/src/pages/Settings.tsx)
web/src/pages/Home.tsx           # Acknowledge on each attention card      (byte copy → mobile/src/pages/Home.tsx)

docs/PLAN.md                     # §6 row rewritten; FR-14 → done; P9 text
STATUS.md                        # the "nothing is alerted" rows
```

**Structure Decision**: a new `vg/alerts/` package beside `vg/ask/`, not inside
`vg/features/`. `features/` is for `FeatureWorker` subclasses that analyse frames on a
camera thread; the alert sender analyses nothing and must never sit on a camera thread.
Putting it there would inherit rate limiting and boost it must not have. The three
one-line store hooks live in `vg/events/` because the committed row is the event.

## The design, in one page

### 1. An event is a committed row

`WeaponSceneStore.open`, `SceneStore.open` and `VehicleStore.record_pass` each gain an
attribute `on_open` / `on_pass` (default `None`), called **after** the `with self._lock:`
block has committed, with the id and the facts already in hand.

**Changed 11 Sep 2026, after review, with Mohamed:** the gate's `on_pass` fires from
`VehicleStore.finish_pass`, not `record_pass`. The plate reader corrects its first reading
(`amend_pass`) while the car comes closer, so a message sent at `record_pass` states the
first three frames' guess - an unregistered car that is really blacklisted never got its
blacklist message. `VehiclesWorker` now calls `on_final(camera_id, pass_id)` when a
recorded car's track ends (it left the camera, or the camera closed), and the lifespan's
closure hands that to `finish_pass`. A person's `set_plate` sends nothing. A pass carries
`finished_at`; a hard kill leaves it NULL, and the next start closes such passes
(`close_unfinished`) and logs their messages as not sent (`AlertService.not_sent`). `open()` also takes
`continues: bool = False`, passed straight to the hook: the two workers' two-minute cut
(`_close(camera_id, now, "limit")` then `_open(...)`) passes `True`, and the service sends
nothing for a continuation. A listener that raises is caught and logged; a store must
never fail its write because a message could not be queued.

The lifespan builds the alert store and the service **before** `_start_zones` and attaches
each hook the moment its store is returned, so no scene can open unheard between a worker
starting and its hook arriving. Events queue before the thread starts; `start()` runs after
`LiveStore` exists and `bind()` has given the service the camera names and the attendance
figures.

### 2. One queue, one thread, rows before couriers

The launcher stops the engine by killing its job object — no `finally` runs — so anything
held only in memory at stop is lost. The design therefore records before it sends:

```
start(): mark every row still `queued` as failed: engine_stopped; seed the dark cameras
loop until stopped:
    wait on the hand-off queue up to 15 s (less if a retry falls due sooner)
    record every event waiting             # rows written; no network
    send the one pending row that is due   # at most one courier call
    tick cameras; tick the report; once a day, delete rows past retention
stop(): mark whatever is still queued as failed: engine_stopped
```

`record(event)`: an event whose key already has rows is ignored — the duplicate guard,
and for the derived events (camera, report) the restart guarantee. Test sends are never
duplicates: each carries its own key. For each external channel the kind's rule has
on: no keys → one `skipped: provider_missing`; each recipient switched off → one
`skipped: recipient_off`; nobody enabled → one `skipped: no_recipients`; otherwise one
`queued` row per enabled recipient, remembered in `_pending`. A channel switched off
writes nothing. The verdict is the exception: it goes to exactly the recipients of the
opening's non-skipped rows, and if there were none it sends nothing.

`enqueue` is `put_nowait`. On `queue.Full` the enqueuing thread pops the oldest and
writes one `failed: queue_full` row for it — the only store write a camera thread ever
makes here, and only when the courier has been stuck long enough to back up 200 events.

A send attempt that fails is due again 5 s later; after `retries` it is `failed` with the
courier's words, redacted of every secret value. In-app is not a send and writes no rows.

### 3. The message cannot carry a name

`AlertEvent.facts` is checked against `ALLOWED_FACTS` in `events.py`; the catalogue
formats templates that reference only those keys; camera names are filled on the sender
thread. The recognised-student test proves it end to end. Plate text and staff names are
facts and allowed by name (`plate`, `reviewer`).

### 4. Arabic is drafted, not sent

`ARABIC_REVIEWED = False` in `catalogue.py`. Until True, `ar` recipients get English and
Settings says so; `alerts.send_draft_arabic: true` sends the draft for review on a real
phone. Flipping the constant is the release step.

### 5. Settings tells the truth in facts

`AlertSettings` carries `sending` (running, off, failed + error), `channels[]` with the
names of any missing variables, `unreached[]` (a rule channel on with nobody enabled on it),
`report` (scheduled, no term dates, before term, after term — **the configured term ended
on 20 Jun 2026, so today the report is silent, and this is how Settings says so**),
`consoleUrlSet` and `arabicReviewed`. `DeliveryLog.available=false` with a reason replaces
an empty list when the table cannot be read. The console words every one of these; the
engine adds no note code for Settings.

### 6. The feed is derived and acknowledged

`LiveStore.attention()` = pending knife entries + today's zone scenes, running or ended +
gate alerts filtered by the rule's reason switches + cameras dark past N minutes (the same
`offline_cameras()` the sender uses), each filtered by its kind's `in_app`, minus
`attention_ack`. It needs the alert database and nothing else — not the sender, so
switching sending off never empties Home. `acknowledge()` finds the item in the current
feed, audits, then inserts. The endpoint takes the actor from the session.

### 7. What changes on the phone

Only byte copies. `types.ts`, `wire.ts`, `api.ts`, `useAttention.ts`, `i18n/*` are
parity-held and reach the phone through `check_parity.py`. `pages/Settings.tsx` and
`pages/Home.tsx` are byte-identical today and are copied again after the edit, so the
mobile `tsc` job compiles against the new contract with no phone-specific work.

### 8. Documents that become untrue

- `docs/PLAN.md` §6: the row "A weapon alert always waits for a human" becomes "A knife
  message says *awaiting review*; only a person can confirm it", with its test: the
  detection message carries the awaiting-review marker, the verdict message carries the
  reviewer, and no other action hangs from detection.
- `docs/PLAN.md` §4 FR-14 → done; §5 P9 → done, with the amendment noted and dated.
- `STATUS.md`: Knife detection "No alerts fan out" → what is sent; Vehicle gate "no
  message goes anywhere" → what is sent; the users/audit/notifications row. Lost bag's
  "Nothing is alerted" stays true.
- `LiveStore.review_weapon` docstring, and the `vehicle_alerts` docstring's sentence
  about which gate alerts reach Home — the rule's switches now decide.

## Known adjacent untruth, not fixed here

The **School profile** card on the same page also says "edits save on their own" and also
saves nothing (`setProfile` only; there is no write endpoint under `/settings/school`).
It is outside this spec's three cards. It is flagged as its own small follow-up rather than
widened into this feature; the plan does not touch it.

## Post-design Constitution re-check

Re-read after Phase 1 with the data model and contract in place:

- **III**: the delivery log stores no message body, so a body can never disagree with
  the catalogue that would rebuild it; `has_rows(event_key)` is the one restart check.
- **IV**: the `facts` allow-list is the structural guarantee; the redaction test is the
  proof. The Twilio WhatsApp template requirement (research §Facts) means production
  WhatsApp may refuse free-form bodies — that refusal lands in the log with Twilio's
  reason, which is the honest outcome, and it is an owner prerequisite, not a code gap.
- **II**: the only new work on a camera thread is `put_nowait` plus, on a full queue, one
  insert of the same size as the store insert that just ran.
- **V**: every control on the three cards maps to an endpoint in the contract; quiet
  hours has none and is removed.

Re-checked again on 11 Sep 2026 while writing tasks, after the corrections the code
forced (listed in tasks.md). None weakens a principle; two of them — rows before
couriers, and continuations sending nothing — close gaps in III and in "one message
per event".

**Still passes. No waiver needed.**
