"""Generate the sample ATM event log used by the README walkthrough."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 8, 9, 10, 40, 0, tzinfo=timezone.utc)


def at(offset: float) -> str:
    return (BASE + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def presence(rows, track, zone, start, end, step=3.0, conf=0.91):
    t = start
    while t <= end:
        rows.append({"ts": at(t), "kind": "observation", "zone": zone,
                     "track_id": track, "confidence": conf})
        t += step


rows: list[dict] = []

# --- normal customer: arrives, uses the ATM, leaves -------------------------
presence(rows, "track-A", "atm_lobby", 0, 48)
rows.append({"ts": at(12), "kind": "signal", "zone": "atm_lobby",
             "signal": "card_inserted"})
rows.append({"ts": at(40), "kind": "signal", "zone": "atm_lobby",
             "signal": "transaction_complete"})
rows.append({"ts": at(50), "kind": "exit", "zone": "atm_lobby", "track_id": "track-A"})

# --- the loiterer: enters 10:42:31 and never leaves -------------------------
presence(rows, "track-B", "atm_lobby", 151, 900, conf=0.87)

# --- the caser: three short visits inside 5 minutes ------------------------
for start, end in ((420, 440), (550, 575), (700, 725)):
    presence(rows, "track-C", "atm_lobby", start, end, step=2.0, conf=0.78)
    rows.append({"ts": at(end + 1), "kind": "exit", "zone": "atm_lobby",
                 "track_id": "track-C"})

rows.sort(key=lambda r: r["ts"])
with open("examples/atm_events.jsonl", "w", encoding="utf-8") as handle:
    for row in rows:
        handle.write(json.dumps(row) + "\n")
print(f"wrote {len(rows)} events")
