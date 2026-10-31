# Contract: `GET /healthz` (public, additive)

Today: `{"ok": true, "version": "<x>"}`. After this feature:

```json
{ "ok": true, "version": "0.x", "now": 1793500000123,
  "endsAt": "2026-11-01T18:40:00+00:00", "stopping": false }
```

- `now` — server time, epoch milliseconds. Always present. Used only for clock-offset
  estimation; it says nothing about the site.
- `endsAt`, `stopping` — present **only** when `VG_SESSION_ENDS_AT` is set. On the laptop
  they are absent, and the console shows no banner.
- `stopping` turns true once shutdown starts (`SHUTTING_DOWN` is set), for the few seconds
  uvicorn still answers.
- Still public, still 200 in every state (AGENTS.md rule 7).

Old clients ignore the new keys; nothing else changes.
