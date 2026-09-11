---

description: "Task list for 013 — Alert Delivery (WhatsApp, SMS, Email and in-app)"
---

# Tasks: Alert Delivery — WhatsApp, SMS, Email and in-app

**Input**: Design documents from `specs/013-alert-delivery/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/alerts.md](./contracts/alerts.md), [quickstart.md](./quickstart.md), [context.md](./context.md)

**Read [context.md](./context.md) before opening any source file.** It names the anchor
in each file, the shape it has today and its line endings, so the edits below do not
need a re-read.

**Tests**: included, and not optional. The constitution requires test-first for business
rules; SC-007 says the minor-safety rule is "proved by a test, not a review"; AGENTS.md
requires every change to ship with its test. Each story's tests are written first and
must fail before its code exists.

**Starting the implementation.** `.specify/feature.json` currently points at
`specs/014-mobile-ui-parity`, because another session is running spec-kit for feature
014. Do **not** rewrite it, and do not set `SPECIFY_FEATURE_DIRECTORY` while 014 is mid-flow
— `common.ps1` persists that override into the same file. Either run `/speckit-implement`
for 013 once 014's session is done with spec-kit, or give the implementing session this
file by path.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different files, no dependency on an unfinished task
- **[Story]**: US1–US5, each mapping to spec acceptance scenarios (named per phase)
- Every task names its exact file paths; line endings are in context.md §3

---

## Working alongside other sessions

Other Claude sessions edit this same working tree while this feature is built. Two are
known today:

| Session | What it touches that this feature also touches |
|---|---|
| **School profile** ("Make the School profile card on Settings save for real") | `web/src/pages/Settings.tsx` and its phone copy, the `/settings` line in `auth/deps.py`, endpoints under `/settings` in `api/app.py`, likely `api/live.py`, `api/store.py`, `api/schemas.py`, `services/api.ts`, `services/wire.ts`, `types.ts`, `i18n/*`, and `test_api.py::REQUIRED` |
| **014 — mobile UI parity** | the phone's pages (`mobile/src/pages/*.tsx`, including `Settings.tsx` and `Home.tsx`), possibly `tools/check_parity.py`, and anything the phone renders from `useAttention()` |
| **Earlier uncommitted work** (System Health load) | `engine/vg/api/live.py` near `health()` and the workers stage, `engine/vg/features/base.py`, `engine/tests/test_health_load.py` |

**The queue rule** — how every task below starts:

1. Run `git status --short` and `git diff --stat -- <the task's files>`. Changes you did
   not make are another session's live work.
2. If a file the task needs is mid-edit elsewhere, **do not take it over and do not wait
   idle**: pick the next task whose files are free (the dependency list below shows
   which), and come back. Tasks that only create new files — all of `engine/vg/alerts/*`
   and the five new test files — never collide, which is why Phase 2 is almost entirely
   new files.
3. In a shared file, make the smallest anchored edit (the Edit tool, exact strings).
   Never revert, reformat or "tidy" another session's hunks. If the Edit tool says the file
   changed since it was read, re-read and redo the edit: that is the queue working.
4. Add your lines as one block in shared lists (`REQUIRED`, `CODES`, `keys.ts`), not
   interleaved with someone else's, so either side can merge the other.
5. When committing, stage only your own hunks (path-limited `git add`, or `git add -p` in
   an interactive terminal).
6. **A byte copy from `web/` to `mobile/` overwrites the phone's file.** Copy a page only
   if the phone file is still the untouched copy — `git diff --quiet -- mobile/src/pages/<page>`
   succeeds and the file matches `git show HEAD:web/src/pages/<page>` byte for byte.
   Otherwise 014 has given the phone its own page: port the alert change into the
   phone's version by hand, keeping its layout, and queue if 014 has it open.
7. Only one session should implement 013. Parallelism here is between features, not
   inside this one: `api/live.py`, `api/app.py` and `alerts/service.py` are each edited by
   several tasks below, one at a time.

---

## Rules that will break the build if ignored

1. **A note code, the code that emits it, and its wording land in one task** (T034).
   `test_notes.py` scans the source for literal `note("…")` calls and fails a declared
   code with no emitter as well as an emitted code that is not declared; `en.ts` is
   `Record<MessageKey, string>`, so `tsc` fails on a missing English wording.
2. **T012 and T013 go back to back.** Between them `LiveStore` inherits `MockStore`'s new
   alert fixtures, which is the exact bug `TestLiveIsNotMock` exists to catch.
3. **Line endings.** The files listed CRLF in context.md §3 stay CRLF. Use the Edit tool
   or `open(path, newline="")`; never `Path.write_text` on Windows. `git diff --stat`
   shows a whole-file rewrite at once.
4. **Parity-held files** (`types.ts`, `services/api.ts`, `services/wire.ts`,
   `services/notes.ts`, `app/useAttention.ts`, `i18n/*`) are copied byte for byte into
   `mobile/src/` after every edit, then `python tools/check_parity.py` — the checker has
   no copy mode. Rule 6 of the queue applies only to pages, which are not parity-held.

---

## Design corrections made while writing these tasks

The code contradicted the plan in a few places. Each correction is already written into
plan.md, data-model.md, contracts/alerts.md, context.md and, where it changed a
requirement's wording, spec.md. Each is Mohamed's to overturn.

1. **A long incident is one message.** The knife and zone workers cut every incident at
   two minutes and reopen at once. A hook on "scene opened" alone would text the same
   person every two minutes. `open()` gains `continues`; a continuation sends nothing.
2. **Rows are written before any courier call.** The launcher stops the engine with a hard
   kill, so an in-memory queue would lose waiting messages without a trace. `start()` marks
   leftovers `failed: engine_stopped`.
3. **A channel switched off in a rule writes no log rows.** Otherwise every unregistered
   car would write three "skipped: channel off" rows and bury the real sends. The spec
   listed "channel off" as a skip reason; P9-FR-023 now says why it is not one.
4. **A missing key is said on System Health and Settings, not on the `attention`
   capability.** A LIVE capability never carries a reason (a tested rule), and making it
   UNAVAILABLE would empty Home on every install without keys. P9-FR-019 reworded.
5. **Settings states travel as facts, not note codes**; only the Home feed uses note codes.
   `AttentionItem` gains `note`, so the live feed is worded in Arabic too.
6. **The verdict goes to exactly the recipients of the opening message.** A recipient added
   in between hears nothing about that entry. The spec's Assumption said otherwise and
   contradicted itself.
7. **The attendance rule has no In-app chip.** The report has no Home item, so an In-app
   switch there would be a control that does nothing.
8. **The three gate switches apply to every chip on the vehicles row, In-app included** —
   one rule, no hidden exception.
9. **Settings says why the noon report is silent.** The term in `engine/engine.yaml` ended
   on 20 Jun 2026, and the School profile card cannot save yet; without this the report
   would go quietly silent.
10. **The rule update is `PATCH`.** `services/http.ts` has no `put`.
11. **A gate message waits for the final reading** (decided with Mohamed, 11 Sep 2026,
    after the review). The plate reader corrects its first reading as the car comes
    closer, so the hook moved from `record_pass` to `VehicleStore.finish_pass`, which the
    worker's new `on_final` calls when the car has left the camera. A few seconds late
    and right. A person correcting a plate by hand sends nothing.

---

## Phase 1: Setup

**Purpose**: configuration, secrets template, and an empty package. Three different files,
none shared with another session.

- [X] T001 [P] Add `AlertsConfig` to `engine/vg/config.py` (CRLF), copying `AskConfig.parse`: reject unknown keys with `ConfigError`; keys and defaults from data-model.md "Config"; refuse a `report_time` that is not `HH:MM`, `camera_offline_minutes <= 0`, `timeout_seconds <= 0`, `retries` outside 1–5, `queue_size < 10`, `log_retention_days < 1`, and a non-empty `console_url` not starting `http://` or `https://` (strip a trailing `/`). Add `alerts: AlertsConfig = field(default_factory=AlertsConfig)` to `EngineConfig` so nothing that builds one by hand breaks, and parse the `alerts:` block in `load()` beside `ask:`. Add the commented `alerts:` block after `ask:` in `engine/engine.yaml` (CRLF). Add `TestAlertsConfig` to `engine/tests/test_config.py`: defaults load from the real file; an unknown key is refused; `report_time: "25:00"` is refused.
- [X] T002 [P] Append the six variables to `engine/.env.example` (LF), empty, under a comment: secrets live only here; Twilio sees every WhatsApp and SMS body and Google every email body; WhatsApp needs the sandbox join phrase or an approved sender with approved templates (research.md, last section).
- [X] T003 [P] Create `engine/vg/alerts/__init__.py` holding only a module docstring: what the package does, that nothing in it runs on a camera thread beyond one `put_nowait`, and that nothing about a minor may enter an `AlertEvent`.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the engine half every story uses — event shape, wording, couriers, tables, and
the sender thread — built and tested without touching a single existing feature. Every
test in this phase lives in `engine/tests/test_alerts.py`, so T004–T008 run in order.

**⚠️ No user story can start until this phase is complete.**

- [X] T004 Write `TestEvents` in `engine/tests/test_alerts.py` first, then create `engine/vg/alerts/events.py`: `KINDS`, `CHANNELS`, `ALLOWED_FACTS`, `GroupCount`, the frozen `AlertEvent` whose `__post_init__` refuses any fact key outside `ALLOWED_FACTS`, one constructor per event returning the key in data-model.md (`weapon_opened`, `weapon_verdict`, `intrusion_opened`, `gate_alert`, `camera_down`, `camera_up`, `attendance_report`, `test_message`), `offline_cameras(workers, now, minutes, started_at)`, `is_school_day(day, term_from, term_to)` (Sunday–Thursday inside the term; empty dates → False) and `report_state(day, term_from, term_to)` → `scheduled | no_term_dates | before_term | after_term`. Tests: facts named `name`, `person`, `student`, `snapshot`, `clip` each raise; each constructor's key; a worker dark 4 min is absent and 5 min present with `since` = its last frame; no frame since start → `since` = `started_at`; an `ok` worker is never listed; Tue 2026-10-06 in a 2026-09-20..2027-06-15 term is a school day and Fri 2026-10-09 is not; 2026-09-11 against the configured 2025-09-01..2026-06-20 term is `after_term`.
- [X] T005 Write `TestCatalogue` in `engine/tests/test_alerts.py` first, then create `engine/vg/alerts/catalogue.py`: `ARABIC_REVIEWED = False`; English and Arabic templates for `weapon.opened`, `weapon.confirmed`, `weapon.dismissed`, `intrusion.opened`, `vehicles.blacklist`, `vehicles.unknown`, `vehicles.expired`, `camera.down`, `camera.up`, `attendance.report` and `test` (the test message names nobody); `build(event, language, *, clock, console_url, send_draft_arabic=False) -> Message`, shaped per contracts/alerts.md "Messages"; a camera with no roster name shows its id. Tests: every template builds in both languages; `"ar"` gets English while `ARABIC_REVIEWED` is False unless `send_draft_arabic`; the knife opening says "awaiting review — not yet confirmed by a person"; the time is site-local `HH:MM` from `FixedClock(offset_minutes=180)`; a link appears only when `console_url` is set and ends `/weapons`, `/intrusion`, `/vehicles`, `/system` or `/attendance`; event bodies ≤ 320 characters; a report of 40 groups is ≤ 1500 and ends "…and N more groups"; a `weak_read` gate alert says the plate read is uncertain; no body says "delivered" or "read". (after T004)
- [X] T006 Write `TestProviders` in `engine/tests/test_alerts.py` first, then create `engine/vg/alerts/providers.py`: `SendResult`, the `Sender` protocol, `REQUIRED_ENV`, `missing_env(channel)`, `redact(text)` (every non-empty value of the six variables → `•••`), `TwilioSender(channel, timeout, transport=None)` — one form POST to `https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json` with basic auth; `whatsapp:` on both numbers for WhatsApp, not doubled if the variable already has it; `provider_id` = the JSON `sid`; `provider_reason` = `"<message> (Twilio <code>)"` from the JSON error body, else the exception's class name, **never `str(exc)`** — and `GmailSender(timeout, smtp_factory=None)` — `SMTP_SSL("smtp.gmail.com", 465)`, `text/plain`, no attachment, a `Message-ID` from `email.utils.make_msgid()` returned as `provider_id`; `for_channel(channel, timeout)` → None when a variable is missing. Failures are `provider_refused`, `timeout` or `unreachable`. Tests use fake transports only: accepted → the id; 401 with `{"code": 20003, "message": "Authenticate"}` → refused with "Authenticate (Twilio 20003)"; a `URLError` whose text contains the SID → `unreachable` and no SID anywhere in the result; a socket timeout → `timeout`; an SMTP authentication error → refused with the server's words; each missing variable named by `missing_env`.
- [X] T007 Write `TestAlertStore` in `engine/tests/test_alerts.py` first, then create `engine/vg/alerts/store.py`, copying `WeaponSceneStore.__init__`'s lock/connect/schema pattern: `AlertStore(database)` with the four tables and the indexes on `alert_delivery(event_key)` and `(queued_at)`; `INSERT OR IGNORE` seeding of the five rules on every open; `normalise_destination(channel, raw)`; `DuplicateRecipient`; methods `rules()`, `update_rule(kind, **flags)`, `recipients()`, `recipient(id)`, `add_recipient(...)`, `update_recipient(id, **fields)`, `remove_recipient(id)`, `has_rows(event_key)`, `add_row(...)`, `row(id)`, `mark_sent(...)`, `mark_failed(...)`, `fail_unfinished(reason, at)`, `recent(limit)`, `counts_since(when)`, `recipients_of(event_key)` (channel and recipient of the non-skipped rows), `last_camera_events()`, `delete_older_than(when)`, `ack(item_id, by, at)`, `acked()`, `close_db()`. Tests over `tmp_path`, closing the store before the directory goes: the seeded defaults (attendance `in_app` is None; vehicle switches only on `vehicles`); an edit survives closing and reopening (SC-006); a duplicate raises; `" +20 100-123 4567 "` becomes `+201001234567`; `01001234567` and `a@b` are refused; `fail_unfinished` turns every `queued` row `failed: engine_stopped`; a second `ack` returns False; `delete_older_than` removes only older rows.
- [X] T008 Write `TestSenderCore` in `engine/tests/test_alerts.py` first, then create `engine/vg/alerts/service.py`: `AlertService(config, store, registry, clock, *, senders=providers.for_channel, now=None)` with `start()`, `stop()`, `step(timeout)` (one loop pass, so tests need no thread), `enqueue(event)`, `test_send(recipient_id) -> row_id`, `bind(**callables)`, `started_at`, `running` — exactly plan.md design §2: record before sending; per-channel skipped rows; a switched-off channel writes nothing; one courier call per pass; a failed attempt due again 5 s later, up to `retries`; `queue.Full` → the enqueuing thread writes the oldest as `failed: queue_full`; `start()` and `stop()` mark leftover `queued` rows `failed: engine_stopped`; retention once per site day; every `provider_reason` through `redact()`; camera names filled on the sender thread from the bound `camera_name`. No kind-specific handling yet — each story adds its own. Tests with a fake sender and an injected `now`: the row is `queued` in the store before the fake sender runs; accepted → `sent` with the id; three refusals → `failed` with the courier's words after exactly three attempts 5 s apart; no keys → one `skipped: provider_missing`; a channel on with nobody → one `skipped: no_recipients`; a switched-off recipient → `skipped: recipient_off`; a channel off → no rows at all; `queue_size=2` with three events → the oldest `failed: queue_full`; a second `enqueue` of an event whose key already has rows writes nothing; a test send ignores the rules and the recipient's switch; a fresh service over the same database marks the old `queued` row `engine_stopped` and sends nothing. (after T004–T007)
- [X] T009 [P] Add `"/settings"` to `ADMIN_WRITE_PREFIXES` in `engine/vg/auth/deps.py` (LF) with a comment — reading the school profile and the alert settings is anybody's job; changing who is told about a knife is an administrator's. **The School profile session may have added it already**: check the file and `git diff` first, keep theirs if so, and add only the tests. Add cases to `TestAdminPathRule` in `engine/tests/test_authorisation.py`: `PATCH`, `POST`, `DELETE` under `/settings/alerts/...` need an administrator, `GET` does not, and `POST /attention/x/ack` does not.
- [X] T010 Wire the service in, touching nothing else: in `engine/vg/api/live.py` (CRLF, another session's uncommitted edits — read `git diff` first) `LiveStore.__init__` gains `alerts_store=None, alerts=None`, `self.alerts_error = None` and `self._started_at`; in `engine/vg/api/app.py` (CRLF) `lifespan`, just before the `_start_zones` call, build `AlertStore(_database(cfg))` (a failure sets `app.state.alerts_error` and leaves it None) and, when `cfg.alerts.enabled`, `AlertService(cfg.alerts, alert_store, registry, clock_for(cfg.timezone))`; pass both to `LiveStore(`; after it, `alerts.bind(camera_name=store._camera_name)` and `alerts.start()` in a `try` that records `store.alerts_error`; in `finally`, `alerts.stop()` right after `registry.stop()` and `alert_store.close_db()` with the other store closes. No hooks yet. `test_no_fixtures.py` must pass unchanged.

**Checkpoint**: `python -m pytest engine/tests/test_alerts.py engine/tests/test_config.py engine/tests/test_authorisation.py engine/tests/test_no_fixtures.py -q` is green and the full suite count has not dropped. `.\dev.ps1 up -Clip -AllowSystemPython` starts, the four tables exist, and the log says the sender started. Nothing is sent yet: no event reaches the queue.

---

## Phase 3: User Story 1 — An administrator chooses who hears, and proves it with a test message (Priority: P1) 🎯 MVP

**Goal**: the Alerts part of Settings stops pretending. Rules, recipients and a delivery
log live in the engine; every control saves; **Send test** really sends; missing keys,
unreached channels and a silent noon report are each a sentence.

**Independent test**: `python -m pytest engine/tests/test_alerts_api.py engine/tests/test_api.py -q`.
On `-Clip`: add a WhatsApp recipient, reload, restart — it is still there; press Send
test with no keys — the log shows `skipped` with the missing-key sentence; System Health's
"Alert sending" row says the same while a rule uses WhatsApp. With real keys, the message
arrives on Mohamed's phone (SC-001, quickstart half three).

**Covers**: spec scenarios 1, 2, 7, 8 and the refusal half of 9 · SC-001, SC-005, SC-006, SC-008 · P9-FR-011–016, 023–028, 032, 034–037

### Tests for User Story 1 (write first — red until T016)

- [X] T011 [US1] Write `engine/tests/test_alerts_api.py`, copying `live_store()` and `client_for()` from `engine/tests/test_sources.py` and giving the `LiveStore` an `AlertStore` over `tmp_path` and an `AlertService` with a fake sender; restore `MockStore` in `finally` as that file does. Classes: `TestSettingsEndpoints` (every route in contracts/alerts.md, with the 404, 409 and 422 cases, `inApp` refused on attendance); `TestAuditComesFirst` (make the store write raise with `monkeypatch`; the audit entry is still there — for add, edit, remove, rule change and test send); `TestNonAdminRefused` (role `it`, the only non-admin role: 403 on every write under `/settings/alerts`, 200 on both GETs); `TestSecretsNeverLeave` (all six variables set to `SENTINEL…` values; no response body, delivery row, `provider_reason` or audit entry contains one, including after a fake courier error that echoes the request URL); `TestLiveIsNotMock` (`LiveStore.alert_settings is not MockStore.alert_settings`, likewise `update_rule`, `add_recipient`, `edit_recipient`, `remove_recipient`, `test_send`, `deliveries`); `TestHonestStates` (no keys → `channels[].missing` names them; a rule channel on with nobody → `unreached`; a closed database → `DeliveryLog.available` False with a reason and status 200; `alerts.enabled` false → `sending: "off"`; System Health's `alerts` stage unhealthy naming the missing variables when a rule uses that channel, healthy with every external chip off). In `engine/tests/test_api.py` (LF — the School profile session may be editing it; queue if so) remove `("GET", "/settings/delivery")` from `REQUIRED` and add the new routes as one block, spelling path parameters as the routes do (`{kind}`, `{recipient_id}` — the normaliser only rewrites the names it lists).

### Implementation for User Story 1

- [X] T012 [US1] Swap the settings contract in `engine/vg/api/schemas.py` (CRLF) — reshape `AlertRule`; add `AlertRuleUpdate`, `Recipient`, `RecipientCreate`, `RecipientUpdate`, `ChannelStatus`, `Unreached`, `ReportStatus`, `AlertSettings`, `DeliveryRow`, `DeliveryLog` and the `AlertKind`, `AlertChannel`, `DeliveryOutcome`, `DeliveryReason` literals per data-model.md; delete `DeliveryTarget` — and in `engine/vg/api/store.py` (CRLF): the `Store` protocol's seven alert methods replace `alert_rules` / `delivery_targets`; `MockStore` implements them in memory, `_log` first on every write, with placeholder contacts such as `security@school.example` (**not** the real address in today's fixture) and a mock test send that records `skipped: provider_missing`, never a fake `sent`. **Do T013 immediately after.**
- [X] T013 [US1] Replace the `alert_rules` / `delivery_targets` stubs on `LiveStore` in `engine/vg/api/live.py` with `alert_settings()`, `update_rule(kind, update, actor)`, `add_recipient(body, actor)`, `edit_recipient(id, body, actor)`, `remove_recipient(id, actor)` and `deliveries(limit)`. Each write audits first (`alerts.rule`, `alerts.recipient.add|edit|remove`, the destination masked to its last four characters) and raises `SubsystemUnavailable` when `alerts_store` is None. `alert_settings()` builds `sending` from `alerts`, `alerts_error` and `config.alerts.enabled`; `channels` from `providers.missing_env`; `unreached`; `report` from `events.report_state(the site's today, hours.term_from, hours.term_to)`; `console_url_set`; `arabic_reviewed = catalogue.ARABIC_REVIEWED`.
- [X] T014 [US1] Add `test_send(recipient_id, actor)` to `LiveStore` in `engine/vg/api/live.py`: `KeyError` when the recipient is unknown; `self._log(actor, "alerts.test", name, channel and masked destination)` first; `SubsystemUnavailable` with the start error, or "switched off in engine.yaml", when `self.alerts` is None; returns the recorded row as a `DeliveryRow`.
- [X] T015 [US1] Add `_alerts_stage()` to the `pipeline` list in `LiveStore.health()` in `engine/vg/api/live.py`, before `self._workers_stage()`, modelled on `_lost_stage()`, with the four states in contracts/alerts.md: running with 24-hour sent/failed counts; unhealthy naming the missing variables of any channel a rule uses, ending "Detection is unaffected."; switched off in engine.yaml; failed to start. **The uncommitted System Health load work sits in this area** — read `git diff` for `health()` first and queue if it is still moving.
- [X] T016 [US1] Replace `get_alerts` and `get_delivery` at the end of `create_app` in `engine/vg/api/app.py` with the seven endpoints in contracts/alerts.md; map `KeyError` → 404, `DuplicateRecipient` → 409, `ValueError` → 422, `SubsystemUnavailable` → 503; `POST …/test` answers 202. `test_alerts_api.py` and `test_api.py` go green.
- [X] T017 [P] [US1] Console contract: in `web/src/services/wire.ts` the new settings types, `AlertRule` reshaped and `DeliveryTarget` removed; in `web/src/types.ts` delete `AlertChannel`, `AlertRule`, `DeliveryKind`, `DeliveryTarget`; in `web/src/services/api.ts` add `getAlertSettings`, `updateAlertRule` (with `patch`), `addRecipient`, `updateRecipient`, `removeRecipient`, `sendTestAlert`, `getDeliveries`, and delete `getAlertRules`, `getDeliveryTargets`. All three are CRLF and parity-held: copy each to `mobile/src/` as bytes afterwards (rule 4).
- [X] T018 [P] [US1] Settings wording in `web/src/i18n/keys.ts` (`UiKey`), `en.ts` and `ar.draft.ts` (all CRLF, parity-held), as one block: `settings.alerts.*` — the three card titles and leads; the five kind names with a one-line meaning each; the four channel names; the three gate reasons; the report states — scheduled "Sent at {time} on school days, Sunday to Thursday.", `no_term_dates` "No term dates are set, so no day counts as a school day and no report is sent.", `before_term` "The term starts on {date}; the first report goes out that day at {time}.", `after_term` "The term ended on {date}, so no report is sent until the term dates in engine.yaml are updated."; `providerMissing` "No {variables} is set, so {channel} cannot be sent. Detection is unaffected."; `nobodyOnChannel` "{channel} is on for {kind} but nobody receives {channel}."; `sendingOff`, `sendingFailed` with `{error}`, `arabicUnreviewed` "The Arabic wording has not been checked by a native speaker yet, so this person receives English for now.", `noConsoleUrl`, `logUnavailable`; the four outcomes — "Sent" means "the courier accepted it", and no wording ever says delivered or read; the ten reasons under `settings.alerts.reason.*`; `adminOnly`; `saveFailed`. English complete; Arabic drafted. Copy the three files to `mobile/src/i18n/` as bytes.
- [X] T019 [US1] Rebuild the Alerts part of `web/src/pages/Settings.tsx` (LF) into three cards on `useAsync(getAlertSettings, …)`. **Alerts**: a row per kind with In-app · WhatsApp · SMS · Email `chip-btn`s (no In-app chip where `inApp` is null), the three gate switches on the vehicles row, the report-state sentence on the attendance row, and the `unreached` sentences. **Who receives alerts**: the per-channel status sentence; each recipient with name, destination, language, a `Toggle`, **Send test** and Remove; the Arabic-unreviewed note on Arabic recipients; the console-address note; an add form (`Select` channel, destination, name, `Select` language). **What was sent**: `getDeliveries()` newest first — time, kind, channel, recipient, an outcome `Badge`, the reason's words and the courier's own text — a Refresh `linkbtn`, and the unavailable sentence when `available` is false. Every change calls the API and reloads; a failed save shows its error in place. Non-admins (`useAccount().role !== 'admin'` — a hint; the server decides) see the cards read-only with the `adminOnly` line. Delete quiet hours, `DELIVERY_META`, `CHANNELS`, `toggleChannel`, `toggleDelivery`, `delivEdit` and the "Where alerts reach you" card. **Leave the School profile card alone — the School profile session owns it — and keep `fmtTime`, which its rows use.** If that session has the file open, queue.
- [X] T020 [US1] Bring the phone along: apply queue rule 6 to `mobile/src/pages/Settings.tsx` — copy the web page's bytes (`Copy-Item`) only if the phone file is still the untouched copy, otherwise port the three cards into the phone's own version. Then run `node node_modules/typescript/bin/tsc -b --force` in `web/` and in `mobile/`, and `python tools/check_parity.py` — all clean.

**Checkpoint**: US1 stands alone. An administrator can set everything up, prove it with a test message, and read the log; nothing on the Alerts part of Settings is unsaved.

---

## Phase 4: User Story 2 — A knife reaches the phone, marked awaiting review, and its verdict follows (Priority: P1)

**Goal**: a knife entry opening sends one message per recipient per switched-on channel,
marked **awaiting review — not yet confirmed by a person**; the verdict sends exactly one
follow-up to the same people. A two-minute continuation sends nothing; a restart re-sends
nothing.

**Independent test**: `python -m pytest engine/tests/test_alerts_events.py -k Knife -q`. On
`-Clip` with WhatsApp on for knife alerts: the entry opens and rows appear within 10 s;
holding the knife past two minutes adds no rows; False alarm adds exactly one row per
recipient, naming the reviewer.

**Covers**: spec scenarios 3, 4, 10 · SC-002, SC-007 · P9-FR-001, 002, 005, 007–009

### Tests for User Story 2 (write first — red until T025)

- [X] T021 [US2] Write `TestKnifeMessages` in `engine/tests/test_alerts_events.py`: a `WeaponSceneStore` over `tmp_path` hooked to an `AlertService` with a fake sender and two WhatsApp recipients. `open()` → exactly one `weapon:<id>:opened` row per recipient, whose body has the camera name, `HH:MM`, the confidence and "awaiting review — not yet confirmed by a person"; `open(..., continues=True)` → no rows; the knife worker holding a knife 125 s (copy `worker`, `walk`, `FakeDetector`, `FakeKnives` from `test_weapons_live.py::…test_scene_is_cut_at_two_minutes_and_a_knife_still_there_reopens`) → rows for the first entry only; `LiveStore.review_weapon` with False alarm → exactly one verdict row per opening recipient, naming the reviewer; a recipient added after the opening gets nothing; a second review of the same entry → no second verdict; a fresh service over the same database → nothing re-sent.

### Implementation for User Story 2

- [X] T022 [US2] In `engine/vg/events/weapons.py` (CRLF): `self.on_open = None` in `WeaponSceneStore.__init__`; `open(..., continues: bool = False)`; after the `with` block, call the hook inside `try/except Exception: log.exception(...)`; add `pending()` beside `recent()`.
- [X] T023 [US2] In `engine/vg/features/weapons.py` (LF): `_open(..., continues: bool = False)` passes it to `self.scenes.open`, and the `MAX_SCENE_SECONDS` branch passes `continues=True`. Nothing else changes; `test_weapons_live.py` stays green. (after T022)
- [X] T024 [US2] In `engine/vg/alerts/service.py`: `on_weapon_open(scene_id, camera_id, started_at, confidence, continues)` — a continuation sends nothing — and `verdict(scene_id, camera_id, verdict, reviewer, at)`, whose recipients are `store.recipients_of("weapon:<id>:opened")` still present and switched on; no opening rows → no verdict.
- [X] T025 [US2] Hang it up. In `engine/vg/api/live.py` `review_weapon`, once `scene` is fetched, call `self.alerts.verdict(...)` when `self.alerts` is set, and rewrite the docstring's first paragraph: the detector's only fan-out is one message marked awaiting review, the verdict sends the second, and nothing locks or calls. In `engine/vg/api/app.py` `lifespan`, on the line after `_start_weapons` returns: `if alerts and app.state.weapon_scenes: app.state.weapon_scenes.on_open = alerts.on_weapon_open`.
- [X] T026 [P] [US2] Amend `docs/PLAN.md` (CRLF): the §6 row "A weapon alert always waits for a human" becomes "A knife message says *awaiting review*; only a person confirms it", with its new test; FR-06's "no alert fan-out until P9" says what is now sent; a dated note under P9 records the owner's decision of 11 Sep 2026, its cost (false alarms reach phones — one 12.5 s entry per about four loops of clean footage) and that no lock or call hangs from detection.

**Checkpoint**: US1 and US2 both work alone. The knife path — the one the owner decided on — is complete.

---

## Phase 5: User Story 3 — Breaches, gate alerts and dark cameras reach the phone (Priority: P2)

**Goal**: one message per restricted-zone scene (continuations excluded), per gate alert
whose reason is switched on, and per camera dark for the configured minutes plus one when
it returns. Lost bag, tracking and counting cannot send.

**Independent test**: `python -m pytest engine/tests/test_alerts_events.py -k "Zone or Gate or Camera or Minor or OtherFeatures" -q`. On `-Clip`, walk into a restricted zone; register the clip's car as blacklisted; stop a camera for five minutes — each writes its rows once.

**Covers**: spec scenarios 5 and 10 · SC-003, SC-007 · P9-FR-001, 003–006, 008

### Tests for User Story 3 (write first — red until T032)

- [X] T027 [US3] Add to `engine/tests/test_alerts_events.py`, after the knife tests: `TestZoneMessages` (the hook; a continuation; the zone worker's two-minute cut — copy `walk` and the `scenes` fixture from `test_zones_live.py::test_scene_is_cut_at_the_two_minute_limit`); `TestNothingAboutAMinor` (a `LiveStore` built like `test_groups.py::build` with "Layla Ahmed" enrolled and sighted on the zone camera at the scene's instant; the message contains neither her name, her person id nor any `.jpg` path — SC-007); `TestGateMessages` (a `VehicleStore` with a blacklisted, an expired and no register row: one message each with plate text, gate and reason; a `known` pass sends nothing; a reason switched off sends nothing; `needs_review` says the read is uncertain; the owner's name never appears); `TestCameraMessages` (fake workers with settable `status` and `source.health.last_frame_at`, injected `now`: dark 4 min → nothing, 5 → one down, still dark → nothing more, back → one up; a fresh service whose last row for the camera is `down` sends nothing while it stays dark and one `up` when it returns); `TestOtherFeaturesSendNothing` (walk `engine/vg` with `ast`: only `vg/alerts/*`, `vg/api/live.py` and `vg/api/app.py` import `vg.alerts`).

### Implementation for User Story 3

- [X] T028 [US3] In `engine/vg/events/zones.py` (CRLF): the `on_open` hook after commit and `open(..., continues: bool = False)`, exactly as T022.
- [X] T029 [US3] In `engine/vg/features/zones.py` (LF): the `continues` pass-through, `True` in the `MAX_SCENE_SECONDS` branch; `test_zones_live.py` stays green. (after T028)
- [X] T030 [P] [US3] In `engine/vg/events/vehicles.py` (CRLF): `self.on_pass = None` in `VehicleStore.__init__`; call `on_pass(record)` after the `with self._lock:` block in `record_pass`, before `return record`, inside `try/except`.
- [X] T031 [US3] In `engine/vg/alerts/service.py`: `on_zone_open(...)` (a continuation sends nothing); `on_pass(record)` — `known` sends nothing; the event is built from `id, at, camera_id, gate, plate_display, status, confidence, needs_review` only, **never `owner_name`**; the vehicles reason switch is checked when the event is recorded; `_tick_cameras()` using `events.offline_cameras(...)`, with `_announced_down` seeded in `start()` from `store.last_camera_events()`.
- [X] T032 [US3] In `engine/vg/api/app.py` `lifespan`: `app.state.scenes.on_open = alerts.on_zone_open` on the line after `_start_zones` returns, and `app.state.vehicle_store.on_pass = alerts.on_pass` after `_start_vehicles`, each guarded as in T025.

**Checkpoint**: every alert kind except the noon report reaches the phone, once.

---

## Phase 6: User Story 4 — "Needs your attention" on Home is real, and a guard can acknowledge (Priority: P2)

**Goal**: Home's feed shows the real open items — pending knife entries, today's zone
scenes, today's gate alerts, dark cameras — derived on every read, in the reader's
language, and anybody signed in can acknowledge one under their own name.

**Independent test**: `python -m pytest engine/tests/test_alerts_feed.py -q`. On `-Clip`: the
knife entry appears on Home; an `it` account presses Acknowledge; it disappears and Audit
shows `attention.ack` by that account.

**Covers**: the acknowledge half of spec scenario 9 · P9-FR-017, 018, 019, 033

### Tests for User Story 4 (write first — red until T035)

- [X] T033 [US4] Write `engine/tests/test_alerts_feed.py`: a `LiveStore` over `tmp_path` with `WeaponSceneStore`, `SceneStore`, `VehicleStore`, `AlertStore` and fake camera workers holding one pending knife, one reviewed knife, a zone scene that opened and ended today, one from yesterday, a blacklisted and an unregistered pass, and a camera dark 6 minutes → exactly five items (the pending knife, today's scene, both passes, the camera) with their ids, severities and note codes; the unregistered pass goes when `vehicle_unknown` is off; a kind with `in_app` off goes; acknowledging writes `attention.ack` before its row and the item goes; a second acknowledge → 404; `POST /attention/{id}/ack` as role `it` → 200, with the audit naming the session account whatever a body says; capability `attention` is LIVE with no reason while the alert database is open; `LiveStore.attention` and `acknowledge` are not `MockStore`'s.

### Implementation for User Story 4

- [X] T034 [US4] Declare, emit and word the feed together (rule 1). `engine/vg/api/schemas.py`: `AttentionItem.kind` gains `"vehicles"`, and `note: Note | None = None`. `engine/vg/api/notes.py`: the six `attention.*` codes, one comment each. `engine/vg/api/live.py`: `attention()` per contracts/alerts.md "The attention feed, derived" — each code emitted by a literal `note("…")`; `[]` when `alerts_store` is None; rewrite the `vehicle_alerts` docstring sentence about Home. `web/src/i18n/keys.ts`: the six codes in `NoteCode`; `en.ts` and `ar.draft.ts`: `note.attention.weapon` "Possible knife, {confidence}% — not yet confirmed by a person.", `note.attention.intrusion` "Someone entered this restricted area.", `note.attention.vehicles.blacklist` "Blacklisted car at gate {gate}.", `note.attention.vehicles.unknown` "A car not on the register came through gate {gate}.", `note.attention.vehicles.expired` "A car with an expired permit came through gate {gate}.", `note.attention.camera` "No picture for {minutes} minutes, so nothing on this camera is being watched." `web/src/services/wire.ts`: the same two `AttentionItem` changes. Copy the parity-held files to `mobile/src/` as bytes.
- [X] T035 [US4] Acknowledge for real: `LiveStore.acknowledge(item_id, actor)` in `engine/vg/api/live.py` — None when the id is not in the current feed; `self._log(actor, "attention.ack", item_id, None)`, then `alerts_store.ack(...)` — and `_attention_state()` for the capability (copy `_ask_state`'s shape). In `engine/vg/api/app.py`, `ack_attention` drops its body and takes `user: auth_deps.CurrentUser`, passing `user.name`. Delete `Acknowledgement` from `engine/vg/api/schemas.py`.
- [X] T036 [US4] `web/src/services/api.ts`: `acknowledgeAttention(id)` posts with no body. `web/src/app/useAttention.ts`: `vehicles` in `TARGET` (`'vehicles'`) and `ACTION`; take `language` once in the hook and pass it down, removing the `useLanguage()` call inside `toAttentionItem`; `sub` = the time · `noteText(t, item.note) || item.detail`; return `{ items, acknowledge }`, where `acknowledge` posts, drops the item and reloads. Add `attention.action.vehicles` "Open the gate log" and `attention.acknowledge` "Acknowledge" to `keys.ts`, `en.ts`, `ar.draft.ts`. Copy all to `mobile/src/` as bytes. **014 may render `useAttention()` on the phone** — search `mobile/src` for other callers and update them to the new return shape, queueing if 014 has the file open. (after T034)
- [X] T037 [US4] `web/src/pages/Home.tsx` (CRLF): `const { items: attention, acknowledge } = useAttention();` and a second `linkbtn` on each card that acknowledges it. Apply queue rule 6 to `mobile/src/pages/Home.tsx`. Then `tsc -b --force` in `web/` and `mobile/`, and `python tools/check_parity.py`.

**Checkpoint**: Home tells the truth on the live engine for the first time, in English and in dev Arabic.

---

## Phase 7: User Story 5 — The noon attendance report (Priority: P3)

**Goal**: at 12:00 site time on a school day (Sunday–Thursday inside the term), one
message per recipient with present, late and absent counts per group and a link — no
names. Never twice, never late; a missed noon is a logged skip.

**Independent test**: `python -m pytest engine/tests/test_alerts_report.py -q`. On the real
engine today Settings says the term ended on 20 Jun 2026; after Mohamed sets the 2026–27
term, quickstart half three step 4.

**Covers**: spec scenario 6 · SC-004 · P9-FR-010, 020–022

### Tests for User Story 5 (write first — red until T040)

- [X] T038 [US5] Write `engine/tests/test_alerts_report.py`: a config from `vgconfig.load()` with `dataclasses.replace` giving a 2026-09-20..2027-06-15 term; `FixedClock(180)` and an injected `now`; `attendance_counts` stubbed to three groups. Tue 2026-10-06 11:59 → nothing; 12:00 → one report per recipient with the counts per group and not the enrolled name; 12:05 → nothing more; a fresh service at 12:06 → nothing (the ledger); a service that started at 12:30 → one `skipped: engine_down_at_noon` per switched-on channel; a service running since 09:00 whose rule was switched on at 14:00 → nothing (it was not down); Fri 2026-10-09 → nothing; outside the term → nothing; counts `None` → `skipped: attendance_unavailable`.

### Implementation for User Story 5

- [X] T039 [US5] Add `_attendance_counts(date)` to `LiveStore` in `engine/vg/api/live.py` — None when `not self.recognition_live`, else one `GroupCount` per `groups()` entry from `attendance("group", name, date)`, never summed — and extend the `bind(...)` call in `engine/vg/api/app.py` `lifespan` with `attendance_counts=store._attendance_counts`.
- [X] T040 [US5] Add `_tick_report()` to `engine/vg/alerts/service.py` per plan.md design §2: fire in `[report_time, report_time + 10 min)` on a school day when nothing is recorded for `attendance:<date>`; after the window, `skipped: engine_down_at_noon` only if the service started after `report_time` that day; None counts → `skipped: attendance_unavailable`; remember the day in memory.

**Checkpoint**: all five stories stand; FR-14 is met in code.

---

## Phase 8: Polish & cross-cutting

- [X] T041 [P] Update `STATUS.md` (CRLF): the knife row's "No alerts fan out" and the vehicle gate row's "nothing is alerted … no message goes anywhere" say what is sent now and when; the "Users, audit, notifications" row says alerts are real, names the two providers, carries the Arabic caveat and that production WhatsApp needs an approved sender; lost bag's "Nothing is alerted" stays, because it is still true.
- [X] T042 [P] In `docs/PLAN.md` (CRLF): FR-14 → done; the P9 section says what shipped, dated.
- [X] T043 *(11 Sep 2026, after the review fixes: 1793 passed, 6 skipped, 0 failed;
  pyflakes clean; tsc clean in web/ and mobile/; parity 25 of 26, the one wrong being
  `services/format.ts` - pre-existing drift owned by 014, reported, not fixed; no
  fixtures; no whole-file rewrites. The real lifespan was also started and stopped on the
  recorded clip in-process: sender started and stopped, hooks attached, `finished_at`
  migrated, nothing sent with every channel off.)* Run every gate on the tree as it stands: `python -m pytest engine -q` (at least 1564 plus the new tests, no failures — a failure another session caused is reported, not fixed quietly), `python -m pyflakes engine/vg engine/tools engine/tests`, `node node_modules/typescript/bin/tsc -b --force` in `web/` and `mobile/`, `python tools/check_parity.py` and `python tools/check_parity.py --no-fixtures`; `git diff --stat` shows no whole-file rewrites.
- [ ] T044 Walk quickstart.md "Half two" on the recorded clip (`.\dev.ps1 up -Clip -AllowSystemPython`), then ask Mohamed for "Half three" on his own phone and inbox: SC-001, SC-004 and SC-005 are his to confirm, the Arabic wording is his to correct before `ARABIC_REVIEWED` becomes True, and the term dates in `engine/engine.yaml` are his to set.

---

## Dependencies & execution order

### Phase dependencies

- **Setup (Phase 1)**: none — T001–T003 can start at once.
- **Foundational (Phase 2)**: after Setup; blocks every story.
- **US1–US5 (Phases 3–7)**: each after Foundational. In priority order for one implementer: US1 → US2 → US3 → US4 → US5.
- **Polish (Phase 8)**: after the stories you intend to ship.

### Story independence

- **US1** needs only Foundational. It is the MVP: without recipients nothing else is observable on a phone.
- **US2** needs only Foundational; its tests create recipients through the store, so they do not wait for US1. Seeing it on a real phone needs US1.
- **US3** needs only Foundational. Its test file is shared with US2, so T027 comes after T021.
- **US4** needs only Foundational. It never needs the sender: switching sending off leaves Home working.
- **US5** needs Foundational; its Settings sentence (`report.state`) arrives with US1's T013.

### Files edited by more than one task — one at a time

| File | Tasks, in order |
|---|---|
| `engine/tests/test_alerts.py` | T004 → T005 → T006 → T007 → T008 |
| `engine/vg/alerts/service.py` | T008 → T024 → T031 → T040 |
| `engine/vg/api/live.py` | T010 → T013 → T014 → T015 → T025 → T034 → T035 → T039 |
| `engine/vg/api/app.py` | T010 → T016 → T025 → T032 → T035 → T039 |
| `engine/vg/api/schemas.py` | T012 → T034 → T035 |
| `engine/tests/test_alerts_events.py` | T021 → T027 |
| `web/src/i18n/*` | T018 → T034 → T036 |
| `web/src/services/api.ts`, `wire.ts` | T017 → T034 → T036 |
| `docs/PLAN.md` | T026 → T042 |

### Within each story

Tests first, and red → store and worker hooks → service handling → `LiveStore` and endpoints → console → phone copy → gates.

### Parallel opportunities

- T001, T002, T003 together.
- T009 alongside T004–T008 (different files).
- T017 and T018 alongside T012–T016 (console files against engine files).
- T026 alongside T022–T025.
- T030 alongside T028–T029.
- T041 and T042 together.
- Across sessions: whole features run side by side (013, 014, the School profile task) under the queue rule — not two sessions inside 013.

---

## Parallel examples

```text
# Setup — all three at once:
Task: "T001 AlertsConfig in engine/vg/config.py + alerts: in engine/engine.yaml + TestAlertsConfig"
Task: "T002 six variables in engine/.env.example"
Task: "T003 engine/vg/alerts/__init__.py docstring"

# US1 — console contract while the engine half is built:
Task: "T013 LiveStore settings methods in engine/vg/api/live.py"
Task: "T017 wire.ts / types.ts / api.ts in web/src (+ byte copies to mobile/src)"
Task: "T018 settings.alerts.* wording in web/src/i18n (+ byte copies)"

# US2 — the document amendment beside the code:
Task: "T024 on_weapon_open and verdict in engine/vg/alerts/service.py"
Task: "T026 PLAN.md §6 row, FR-06 and the dated P9 note"

# US3 — the gate hook beside the zone hook:
Task: "T028 on_open + continues in engine/vg/events/zones.py"
Task: "T030 on_pass in engine/vg/events/vehicles.py"
```

---

## Implementation strategy

### MVP — stop and look after US1

1. Phase 1 and Phase 2.
2. US1 (T011–T020).
3. **Stop.** Mohamed adds his own number and presses Send test. If the message arrives
   and the log says sent, the wiring is proven end to end; everything after this is
   deciding *when* to send.

### Then, in order

1. US2 — the knife path, which carries the owner's decision and the §6 amendment.
2. US3 — breaches, gate, cameras.
3. US4 — Home becomes real; it can go before US3 if Home matters more that week.
4. US5 — the noon report, once the 2026–27 term dates are in `engine/engine.yaml`.
5. Polish, then quickstart half three with Mohamed.

---

## Notes

- 44 tasks. [P] means a different file and no dependency on an unfinished task — never two sessions inside this feature.
- Every story's tests fail before its code exists; confirm the red before going green.
- Commit after each task or logical group, staging only this feature's hunks.
- Stop at any checkpoint and check the story by itself.
- Out of scope stays out: parents, push notifications, images, inbound replies, per-camera rules, quiet hours, the School profile card, the audit trail's durability (P3).

---

## Implementation notes (11 Sep 2026)

Where the build departed from the text above, and why. The code is the truth.

- **The three alert cards live in `web/src/components/AlertSettings.tsx`**, byte-copied
  to `mobile/src/components/`, like the other feature components. The shared
  Settings page changed by a few lines (8 in, 213 out), because the School
  profile work edits the same page and a small diff is what lets both land.
- **`AlertSettings` carries `camera_offline_minutes`**, so the camera row can say
  how long a camera must be dark before it is a message.
- **Camera names come from the running roster** (`LiveStore._roster_name`, reading
  `registry.configs()`), the same source every page uses, so a camera added in
  Settings is named in messages and on Home. `_camera_name` reads engine.yaml only.
- **`AlertEvent` carries a `template`** naming its catalogue entry, so the
  catalogue never parses a key to decide which sentence to write.
- **`attention_ack.by_who`**, not `by`, which is an SQL keyword.
- **`useAttention.ts` called `useLanguage()` inside a promise callback**, outside
  render. It only went unnoticed because the live feed was always empty; it now
  takes the language once in the hook.
- **Parity**: copying the edited i18n files to the phone also carried across the
  System Health wording the phone had missed on 4 Sep. `services/format.ts` still
  differs from its phone copy; that pre-existing drift is feature 014's to fix.
- **The sender exposes `step()`, `start(run_thread=False)` and `dead`**: one pass
  for the tests, the start-up sweep without a thread, and "started and died",
  which is not the same as never started.
- **`_start_alerts` consults the VG_STRICT guard** like every other starter;
  `test_smoke_start.py` requires it.

### After the review (11 Sep 2026, evening)

A read-only six-angle review, each finding put to skeptics told to refute it. What it
changed, each with its test:

- **An event's rows are written together or not at all** (`AlertStore.add_rows`, one
  transaction). Half an event recorded made `has_rows` true and silenced the other half
  for good - and the verdict, which follows the opening's rows, lost those people too. An
  event whose rows could not be written is tried again on the next passes
  (`RECORD_TRIES`), then given up with a logged error. `TestWhenAWriteFails`.
- **A dark camera is taken as announced only once its row exists.** `_tick_cameras`
  used to mark it first, so one failed write lost that camera's message for good.
- **`stop()` waits as long as a courier call may take** (`timeout_seconds` + 5 s, was a
  fixed 5 s), starts no new courier call once asked to stop, and never marks failed the
  one row a courier is still carrying (`fail_unfinished(keep=...)`). It used to mark a
  message `failed: engine_stopped` that the courier then accepted. A graceful stop can
  now take up to 15 s longer while a message is in flight.
- **The gate message waits for the final reading** - design correction 11. A second,
  smaller review of these fixes found where that left a gap, now closed: a hard kill
  with a recorded car still in view used to lose its message with no row. Each pass now
  carries `finished_at` (a gate already running has its old passes marked done by the
  migration), and each start closes the last run's unfinished passes
  (`VehicleStore.close_unfinished`) and logs their messages `failed: engine_stopped`
  for exactly the people who would have had them (`AlertService.not_sent`) - never sent
  late, because a gate message gives a time and no date. `finish_pass` reads before it
  marks, so a failed read leaves the pass for the next start. `TestACarInViewWhenTheEngineStopped`.
- **`stop()` says whether the sender finished**, and the lifespan leaves the alert
  database open while a courier is still talking, so its late answer is not thrown away.
- **The destination box is `dir="ltr"`**, so a number keeps its digit order in Arabic.
- **Home's feed test pins its clock** (`StoppedClock`): a run across Cairo midnight
  built the items on one day and looked for them on the next.
- **The engine's wiring is pinned** (`TestTheEngineWiresTheSender`): each store's hook,
  the roster names, `start()`, and `stop()` before the store closes. `lifespan` cannot run
  in a test, so its source is read, as `test_smoke_start` does.
- **`test_page_states` knows Settings' lists moved into `AlertSettings`** (`LISTS_IN`).
  The full suite had one failure after US5: Settings no longer mounted `<Empty>` itself.

Refuted and left alone, with the reason: a Twilio error quoting a phone number back
(every signed-in account can already read the full recipient list - kept as built,
Mohamed, 11 Sep); hooks attached a few statements after a worker starts (a new
subscription has no frames, and the first arrives a capture interval later); the config
test pinning `engine.yaml`'s alert values (asked for by T001); no HTTP round-trip against
`MockStore` (checked by hand, all 2xx); audit masking tested only for SMS (one helper,
channel-agnostic).
