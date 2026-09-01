"""Generate the sample restricted-area log (whole camera view, night shift)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 8, 9, 22, 14, 0, tzinfo=timezone.utc)


def at(offset: float) -> str:
    return (BASE + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def presence(rows, track, start, end, step=1.0, conf=0.88):
    t = start
    while t <= end:
        # note: no "zone" field -- the whole view of cam_07 is the restricted area
        rows.append({"ts": at(t), "camera": "cam_07", "track_id": track,
                     "confidence": conf})
        t += step


rows: list[dict] = []

# --- one-frame reflection: must NOT alert (min_observations) ---------------
rows.append({"ts": at(30), "camera": "cam_07", "track_id": "noise-1", "confidence": 0.71})

# --- the intruder: appears 22:14:03 and stays ------------------------------
presence(rows, "track-A", 3, 400)

# --- authorized engineer: badge granted on arrival, no alert ---------------
presence(rows, "track-B", 600, 780, conf=0.93)
rows.append({"ts": at(601), "camera": "cam_07", "kind": "signal",
             "signal": "badge_granted"})

# --- someone probing: three short looks inside 10 minutes ------------------
for start, end in ((820, 828), (900, 910), (1000, 1010)):
    presence(rows, "track-C", start, end, conf=0.74)
    rows.append({"ts": at(end + 1), "camera": "cam_07", "kind": "exit",
                 "track_id": "track-C"})

rows.sort(key=lambda r: r["ts"])
with open("examples/restricted_events.jsonl", "w", encoding="utf-8") as handle:
    for row in rows:
        handle.write(json.dumps(row) + "\n")
print(f"wrote {len(rows)} events")
