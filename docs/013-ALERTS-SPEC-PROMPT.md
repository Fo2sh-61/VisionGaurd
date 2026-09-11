# Spec Prompt — Alert Delivery (WhatsApp · SMS · Email · in-app)

Use as the feature description for `$speckit-specify`. Suggested branch: `013-alert-delivery`.
This is P9 in `docs/PLAN.md` and closes FR-14. Requirement prefix inside the spec: `P9-FR-xxx`.

---

Create one feature specification named **Alert Delivery — WhatsApp, SMS, Email and in-app**.

Specification only. Do not implement, edit source, install dependencies, run migrations, sign up for any provider, or touch the database. Output only the normal Spec Kit artifacts.

## Read first (authority order)

- `.specify/memory/constitution.md` — especially **III** (Truthful Data), **IV** (Reliability, Security, Privacy — minors' data, secrets, the human decision gate), **II** (a feature must not slow another), **V** (no no-op controls).
- `docs/PLAN.md` — §4 FR-14, §5 P9, and **§6 "A weapon alert always waits for a human"**, which this feature deliberately changes (see the hard rules).
- `STATUS.md` — every row that says "nothing is alerted" or "no message goes anywhere".
- `AGENTS.md` — rules 4, 7, 8, 11; the idioms (`_log` before the write, permissions by path, `SubsystemUnavailable`, wire types).
- `specs/010-ask` — the precedent for a cloud provider: config in `engine.yaml`, secret in `.env`, provider terms recorded, an honest UNAVAILABLE reason when the key is missing (`_ask_state` in `engine/vg/api/live.py`).
- `specs/012-mobile-parity` and `tools/check_parity.py` — `types.ts`, `services/api.ts`, `services/wire.ts`, `i18n/*` and `app/useAttention.ts` are held byte-identical between console and phone by CI, so the wire contract and the attention feed reach the phone through the console's own files. `pages/Settings.tsx` is **not** on that list: the phone has its own byte copy, which must at least compile against the new contract (the mobile `tsc` job is a CI gate).

## What exists today (verified in code — the spec must start from this, not from the mock)

- **The Alerts section of Settings is a fake save.** In `web/src/pages/Settings.tsx`, `toggleChannel`, `toggleDelivery`, the destination edit and the quiet-hours toggle change React state only. Nothing calls the engine, and the screen says "Edits save on their own." This is rule 4 unmet and must be fixed by this feature — either the control saves for real or it goes.
- **The engine has read endpoints only**: `GET /settings/alerts`, `GET /settings/delivery`, `GET /attention`, `POST /attention/{id}/ack` (`engine/vg/api/app.py`). On the live engine `LiveStore.attention()`, `acknowledge()`, `alert_rules()` and `delivery_targets()` all return empty, and the `attention` capability reads UNAVAILABLE: "Alerts are not built yet. Nothing is being sent to anybody." Home's "Needs your attention" is therefore always empty outside `-Mock`.
- **The wire shapes exist but are wrong for this feature**: `AlertRule` has `push / email / sms` booleans and no WhatsApp; `DeliveryTarget` holds **one** destination per channel; `LiveEvent` is a WebSocket frame nobody sends (`engine/vg/api/schemas.py`). The mock rule keys are `weapon`, `intrusion`, `camera`, `attendance` (`engine/vg/api/store.py`).
- **No table, no delivery log.** Audit still lives in RAM (P3 is not done). This feature must not wait for P3: alert rules, recipients and the delivery log get their own tables in the existing SQLite database (WAL is on since P0-06).
- **`/settings` is in no admin prefix** in `engine/vg/auth/deps.py`. A write endpoint there would be open to a guard the day it is written.
- **The points an alert can hang from already exist**: a knife entry opening (`WeaponSceneStore.open`, `engine/vg/events/weapons.py`) and its verdict (`LiveStore.review_weapon` — whose docstring says "today it hangs nothing"); a zone scene opening (`SceneStore.open`, `engine/vg/events/zones.py`); a gate alert (`GateAlert`, derived from passes, never stored); a camera dropping to NO SIGNAL (`engine/vg/ingest/registry.py`); the attendance register.
- **The "Notify parent" button on Attendance is disabled with a reason** (`attendance.notifyParentWhy`). Parents are not recipients of this feature; the button stays disabled and its reason must stay true.

## Why

VisionGuard detects a knife, a breach, a blacklisted car and a dead camera — and then waits for somebody to be looking at the screen. A head of security in another building learns nothing. This feature is the wiring from the engine to a phone or an inbox, with a log that says what was sent, to whom, and whether the courier accepted it.

## Providers — decided

- **WhatsApp and SMS through Twilio** — one account, one key pair, both channels. Numbers are stored in international form (`+20…`).
- **Email through Gmail SMTP** with a Google App Password — no OAuth, no other company.
- Secrets live in `engine/.env` only (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_SMS_FROM`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`), never in `engine.yaml`, and never in a response, a log line or an audit entry — the camera-password test in `specs/011-camera-onboarding` is the pattern. Non-secret settings (`enabled`, timeouts, the camera-offline minutes, the report hour) go in an `alerts:` section of `engine.yaml`.
- **Record the terms accepted, as Ask did**: Twilio and Google see the text of every message. What leaves the site is bounded by the content rule below, and the owner accepts that.
- **Design seam**: one interface per channel — `send(message, recipient) → accepted(provider_id) | failed(reason)` — so a provider can be swapped later without touching rules, recipients or the log. Do not build more than one implementation per channel.

## The hard rules

1. **The engine sends; the console configures and shows the log.** Recipients, rules and the delivery log are engine state. The console never talks to Twilio or Gmail.
2. **Facts only, and nothing about a minor.** A message carries: what happened, the camera, the time, the confidence where there is one, review state, who decided (staff name), and a link that opens the right console page. **Never** a student's name, a face, a snapshot, a clip, or a plate photo. Plates as text and staff names are allowed. Enforce this in the message builder, not by convention — a test asserts a message built from a scene with a recognised student contains neither the name nor any image.
3. **A message is a sentence the engine builds — in the recipient's language.** Each recipient has a language (`ar` / `en`). The catalogue lives in the engine, both columns, with the same caveat Ask carried: Arabic drafted by the agent renders only in dev until Mohamed corrects it. This is a deliberate exception to the P11 "codes + facts, console builds the sentence" contract, because there is no console at the far end of an SMS.
4. **Knife messages go out on detection — a deliberate change to PLAN §6.** The owner decided on 11 Sep 2026 that a knife entry opening sends a message marked **"awaiting review — not yet confirmed by a person"**, and that the verdict (Confirmed / False alarm, with the reviewer's name) sends a **second** message to the same recipients, so nobody is left holding a scare. The spec MUST say this amends the §6 row "No notify/call/lock can be triggered by the detector" and the `review_weapon` docstring, and MUST state the cost plainly: the measured false-alarm rate is not zero (STATUS: one 12.5 s entry per ~four loops of clean footage), so false alarms will reach phones. No locking, calling or any other action hangs from detection — only a message.
5. **One message per event, never per frame.** One knife entry = one detection message + one verdict message. One zone scene = one message. One gate pass = one message. One camera = one message when it has been NO SIGNAL for the configured minutes and one when it is back. Restarting the engine must not re-send anything.
6. **Sending never touches a camera thread.** Events go on a bounded queue; one sender thread drains it. A provider that is slow or down changes nothing about detection, recording or the console (Principle II). A queue that fills drops the oldest and logs the drop as failed with that reason — never silently.
7. **"Sent" means the courier accepted it, nothing more.** The log records `queued`, `sent` (with the provider's id), `failed` (with the provider's reason, retried a bounded number of times), or `skipped` (channel off, no recipients, provider not configured, quiet). The console never says "delivered" or "read" unless the provider reported it. A message that could not be sent is a row in the log, not a missing row.
8. **Every write is audited first and administrator-only by path.** Adding or removing a recipient, changing a rule, and pressing "Send test" write the audit entry before the thing they record. Add `/settings` to the admin-write prefixes. Acknowledging an in-app alert is the one write a guard may make here, exactly as `/vehicles/alerts` dismissal is, and it is audited the same way.
9. **Not configured is a state with a sentence, not a silence.** With no Twilio keys, WhatsApp and SMS rows in Settings and the `attention` capability say "No TWILIO_* is set, so WhatsApp and SMS cannot be sent. Detection is unaffected." Same for Gmail. Wrong keys must surface as a failed test send or a failed row within a minute, with the provider's own reason.
10. **Nothing invented.** `MockStore` keeps its fixtures for `-Mock`; the live path must never borrow them — pin it with the `LiveStore.x is not MockStore.x` assertion pattern from `test_ask.py`. Defaults on a fresh install: every external channel off and no recipients, so nothing is sent until an administrator adds somebody and switches a rule on. In-app is on by default.

## Behaviour

**Recipients** — any number per channel. Each has a channel (`whatsapp` / `sms` / `email`), a destination, a display name, a language, and on/off. A recipient receives **every** alert kind whose rule has that channel switched on; there is no per-recipient filter. Each row has a **Send test** control that really sends, is audited, and lands in the log — the one way an administrator can prove the wiring on a real phone.

**Rules** — one row per alert kind, with a chip per channel: **In-app · WhatsApp · SMS · Email** (rename "Push" to In-app; there is no push service and the spec must not promise one). The kinds, and what each one means:

| Kind | Sends when | Follow-up |
|---|---|---|
| `weapon` | a knife entry opens — "awaiting review" | the verdict, with reviewer |
| `intrusion` | a restricted-zone scene opens | none |
| `vehicles` | a gate pass raises an alert — blacklisted for certain; unregistered / expired permit are **[NEEDS CLARIFICATION: all three, or blacklisted only?]** | none |
| `camera` | a camera has been NO SIGNAL for N minutes (default 5, in `engine.yaml`) | "back online" |
| `attendance` | **12:00 site time** every school day | none |

**In-app channel** — the Home "Needs your attention" feed on console and phone. `LiveStore.attention()` returns the real open items derived from the stores that already hold them — knife entries awaiting review, today's open scenes, today's gate alerts, cameras offline past N minutes — never a second copy. Acknowledging writes one audited row and drops the item from the feed; it deletes nothing. The `attention` capability turns LIVE.

**Daily attendance report** — at 12:00 site time (`Africa/Cairo`, from the site clock, timezone per instant — the F3 lesson) on school days: present, late and absent **counts**, per group, and a link to the Attendance page. No names, per rule 2. The engine has no scheduler; the smallest mechanism that fires once per day and does not fire twice after a restart is enough. A noon missed because the engine was down is logged as skipped with that reason, not sent late. **[NEEDS CLARIFICATION: which days are school days — the term dates in the school profile plus Sunday–Thursday?]**

**Delivery log** — in Settings under the recipients: the last N sends, newest first — time, kind, channel, recipient name, outcome, reason. Every outcome in rule 7 is a visible state. Rows are kept for **[NEEDS CLARIFICATION: how long — 90 days?]**.

**Settings page** — the three cards that exist (rules, recipients, log) become real and save on every change through the engine, with an error shown when a save fails. **Quiet hours is removed** from the page rather than left as a control that does nothing; add it back only as its own small change when somebody asks for it. **[NEEDS CLARIFICATION: confirm removal.]** This is the web console first. The parity-held files carry the contract to the phone on their own; `mobile/src/pages/Settings.tsx` is a byte copy of the console page, so keeping it compiling is one copy task, not mobile work — the spec must not describe any.

**Honest states on the console** — provider not configured (rule 9), no recipients on a channel a rule uses ("WhatsApp is on for knife alerts but nobody receives WhatsApp"), a failed send (the reason, from the log), and the log itself unavailable.

## Out of scope — do not touch

Parents as recipients (the disabled button stays disabled); push notifications to phones; images, clips or snapshots in any message; inbound replies (acknowledging by answering a WhatsApp); per-camera or per-zone rules; delivery or read receipts beyond what the provider returns; Meta's WhatsApp API directly; any detection, review or gate logic; the audit trail's durability (P3); gun detection; escalation chains.

## Keep it minimal

One sender thread, one bounded queue, one table each for recipients, rules and the log, one implementation per channel behind the seam. No retry framework, no template engine, no rule expression language. Prefer the smallest change to `Settings.tsx` that makes what is on screen true. Few tasks, each small, each shipped with its test.

## Success criteria (a non-engineer can check)

- **SC-001**: An administrator adds a WhatsApp number, an SMS number and a Gmail address in Settings, presses Send test on each, and the message arrives on the real phone and in the real inbox; the log shows each as sent with the time.
- **SC-002**: A knife entry opening on the recorded clip produces exactly one message per switched-on channel per recipient within 10 seconds, marked awaiting review; pressing Confirm or False alarm produces exactly one follow-up. Restarting the engine re-sends nothing.
- **SC-003**: A zone scene, a blacklisted car and a camera offline for N minutes each produce their message; lost bag, track and counting produce nothing.
- **SC-004**: At 12:00 site time on a school day the attendance report arrives with counts only — no student name in it.
- **SC-005**: With no provider keys, Settings and System Health say so plainly, detection carries on, and every would-be send is in the log as skipped with the reason. With wrong keys, the failure is visible within a minute with the provider's reason.
- **SC-006**: Every recipient, rule and log row survives a restart; every change and test send is audited before it happens; a guard cannot change recipients or rules and can acknowledge an in-app alert.
- **SC-007**: No message ever contains a student's name, a face or an image — proved by a test, not a review — and an Arabic recipient receives Arabic.
- **SC-008**: The four CI gates, the mobile `tsc` job and `check_parity.py` pass; the Settings page shows nothing it cannot save.

Mark anything uncertain as **[NEEDS CLARIFICATION: question]** rather than guessing. Confirm the Constitution check, naming **III**, **IV** (secrets, minors' data, and the decision-gate change in rule 4), **II** and **V** as the principles under load.
