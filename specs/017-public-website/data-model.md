# Data model: The VisionGuard website

The website keeps no data. The only thing it handles is one contact message, from
the moment it is typed until the visitor leaves the page.

## Contact message

| Field | Required | Rule |
|---|---|---|
| Full name | yes | not blank |
| Work email | yes | a valid email address (browser's own check); also the reply-to address |
| Company | yes | not blank |
| Phone | no | free text |
| Type of site | yes | one of: Office, Factory, Warehouse & logistics, Hospital & healthcare, School, Supermarket, Retail & malls, Other (School and Supermarket added 27 Sep 2026). Starts on Office |
| Number of cameras | yes | exactly one of: Under 25, 25–100, 100–500, 500+. Starts on 25–100 |
| How can we help? | no | free text, as designed (no `required` on the design's textarea) |
| `_honey` | hidden | must stay empty; if it has anything in it, the message is not sent |

## Send state

```text
editing ──Send, fields valid──▶ sending ──FormSubmit "success":"true"──▶ sent (thank-you)
   ▲                              │
   └──────── failed ◀─────────────┘  any other answer, network error, or 15 s timeout
```

- **editing**: the form, as designed.
- **sending**: the button reads "Sending…" and is disabled. The fields keep their text.
- **sent**: the design's thank-you replaces the form. This is the only way to reach it.
- **failed**: the form stays with everything typed. Under the button, a plain line
  says the message was not sent, and gives sales@vision-guard.org and
  +20 100 253 5081 as links. Pressing Send again goes back to **sending**.
