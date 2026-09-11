# Quickstart: proving Alert Delivery

Two halves. The first needs no keys and no network and is what CI runs. The second needs
Mohamed's phone and inbox and is the only way SC-001 is met.

## Prerequisites

- `.\dev.ps1 doctor` clean. There is still no `.venv`, so engine commands need
  `-AllowSystemPython` (or use `.\launch.ps1`).
- For the real-phone half only:
  - A Twilio account with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, an SMS-capable
    number in `TWILIO_SMS_FROM`, and for WhatsApp either the **sandbox** number in
    `TWILIO_WHATSAPP_FROM` (the receiving phone must first send the sandbox join phrase) or
    an approved WhatsApp sender with approved templates. See
    [research.md](./research.md), last section.
  - A Google account with 2-step verification and an App Password, in `GMAIL_USER` and
    `GMAIL_APP_PASSWORD`.
  - All six in `engine/.env`, never in `engine.yaml`.
- For the noon report: **the term in `engine.yaml` ended on 20 Jun 2026**, and the
  School profile card on Settings does not save. Put the 2026–27 term into
  `hours.term_from` / `hours.term_to` in `engine/engine.yaml` first, or the report is
  correctly silent and Settings says the term has ended.

## Half one: without keys (CI)

```powershell
python -m pytest engine -q
```

Must be green and the count must not drop below the baseline in `context.md`. The five new
files are `test_alerts.py`, `test_alerts_api.py`, `test_alerts_events.py`,
`test_alerts_feed.py` and `test_alerts_report.py`; `tasks.md` names which test lives in
which. What they prove, mapped to the spec:

| Test class | Proves |
|---|---|
| `TestNothingAboutAMinor` | a zone message built on a camera with a recognised student contains neither the name, the id nor any image path (SC-007, P9-FR-008) |
| `TestOneMessagePerEvent` | a knife open produces one row per recipient-channel; a second `enqueue` of the same key produces nothing; a fresh service over the same database re-sends nothing (SC-002, P9-FR-005) |
| `TestVerdictFollowUp` | `review_weapon` enqueues exactly one `weapon:<id>:verdict` carrying the reviewer (P9-FR-002) |
| `TestCameraKind` | a worker reporting `down` for `camera_offline_minutes` raises one `down`; back to `ok` raises one `up`; a restart with the last row `down` and the camera still down raises nothing (P9-FR-003) |
| `TestNoonReport` | with a `FixedClock` stepped through 11:59 → 12:00 → 12:11 on a Tuesday inside term: one report, counts only; stepped straight to 12:11: one `skipped: engine_down_at_noon`; on a Friday: nothing (P9-FR-020/021/022) |
| `TestQueueFull` | `queue_size=2`, three events: the oldest is `failed: queue_full` and the newest is queued (P9-FR-030) |
| `TestProviders` | `TwilioSender`/`GmailSender` with a fake transport: accepted → `sent` with the id; refused → `failed` with the courier's text after 3 attempts; missing variables → `for_channel()` is None → `skipped: provider_missing` (P9-FR-023/026) |
| `TestSettingsEndpoints` | add/edit/remove recipient, update rule, test send: each audited **before** the write; guard gets 403 on every one (P9-FR-032, SC-006) |
| `TestSecretsNeverLeave` | with every variable set to `SENTINEL…`, no response body, delivery row or audit entry contains it (P9-FR-034) |
| `TestLiveIsNotMock` | `LiveStore.attention is not MockStore.attention`, and the same for `acknowledge`, `alert_settings`, `deliveries`, `test_send` (P9-FR-037) |
| `TestAttentionFeed` | pending knife + today's scene + blacklist pass + camera down = four items; ack removes one and writes one audit row; a guard may ack; the `vehicles` reason switches filter the pass (P9-FR-017/018/033) |
| `TestHonestStates` | no keys → `channels[].missing` names the variables and System Health's alert row is unhealthy with the sentence; a rule on with nobody → `unreached[]` names it; a closed database → `DeliveryLog.available=false` with a reason, status 200 (P9-FR-026/027) |

Then the other three gates:

```powershell
python -m pyflakes engine/vg engine/tools engine/tests
```

```powershell
cd web; npx tsc -b --force; cd ..
```

```powershell
cd mobile; npx tsc -b --force; cd ..
```

```powershell
python tools/check_parity.py
```

## Half two: on the recorded clip, no keys

```powershell
.\dev.ps1 up -Clip -AllowSystemPython
```

Open Settings as an administrator. Expected:

- The Alerts card shows five rules with In-app · WhatsApp · SMS · Email chips; the
  `vehicles` row shows three reason switches. No quiet hours.
- The "Who receives alerts" card says, per channel, which variables are missing and that
  detection is unaffected. The attendance row says the term has ended (until the term
  dates are updated).
- Toggle a chip, reload the page: it stays. Add a recipient, reload: it stays. Restart
  the engine: both stay.
- Switch WhatsApp on for knife alerts with no WhatsApp recipient: the warning sentence
  appears on the card.
- Let the clip run until the knife entry opens (STATUS: three sightings over a second).
  The delivery log shows one `skipped` row per switched-on channel with the missing-key
  reason, within 10 s of the entry appearing on Weapons. Home shows the entry under
  "Needs your attention". Keep the knife in view past two minutes: the entry is cut and a
  new one opens, and **no** new rows appear. Press Confirm on the first entry: a second set
  of rows appears, and its Home item is gone.
- Press Acknowledge on a Home item as a guard: it disappears, and Audit shows
  `attention.ack` by that guard.
- System Health: the "Alert sending" row is unhealthy and names the missing variables
  while a rule uses WhatsApp, SMS or Email with no keys; with every external chip off it
  reads healthy.

## Half three: the real phone (SC-001, SC-004, SC-005)

With the six variables filled in `engine/.env`, restart the engine.

1. Add a WhatsApp recipient (your number, `+20…`, language `ar`), an SMS recipient and a
   Gmail recipient. Press **Send test** on each. Expected within a minute: the message on
   the phone and in the inbox, and three `sent` rows with Twilio SIDs / an SMTP id. An
   Arabic recipient receives English and the row shows the Arabic-unreviewed note until
   `ARABIC_REVIEWED` is flipped; set `alerts.send_draft_arabic: true` to read the draft.
2. Put a wrong `TWILIO_AUTH_TOKEN`, restart, Send test: a `failed` row with Twilio's own
   reason (`Authenticate`, code 20003) within a minute. Same with a wrong App Password
   (`Username and Password not accepted`).
3. Switch WhatsApp on for knife alerts and run the clip: the awaiting-review message
   arrives; press False alarm: the follow-up arrives naming you.
4. Set `alerts.report_time` to two minutes from now on a weekday inside term and wait:
   the counts arrive, per group, no names. Set it back to `12:00`.
5. Confirm on the phone that no message ever contained a name, a picture or a link to a
   clip.

**Ask Mohamed for this half.** It cannot be automated and it is the acceptance.
