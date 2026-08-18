"""Canonical event types consumed by the rules engine.

The engine is detector-agnostic: whatever produces your tracks (YOLO+ByteTrack,
an NVR, Frigate, a commercial VMS) only needs to emit these events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping


class EventKind(str, Enum):
    #: track was seen inside `zone` at `ts` (the normal case -- one per frame/sample)
    OBSERVATION = "observation"
    #: explicit zone entry, if your upstream already computes it
    ENTER = "enter"
    #: explicit zone exit
    EXIT = "exit"
    #: non-vision business event: card_inserted, transaction_complete, door_unlocked...
    SIGNAL = "signal"


def _parse_ts(value: Any) -> float:
    """Accept epoch seconds, epoch millis, or an ISO-8601 string."""
    if isinstance(value, (int, float)):
        # heuristics: anything past year 2286 in seconds is really millis
        return float(value) / 1000.0 if value > 1e11 else float(value)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise TypeError(f"unparseable timestamp: {value!r}")


#: used when an event carries no zone -- the whole camera view is the area
DEFAULT_ZONE = "frame"


@dataclass(frozen=True)
class Event:
    ts: float
    kind: EventKind
    zone: str = DEFAULT_ZONE
    track_id: str | None = None
    camera: str | None = None
    label: str = "person"
    confidence: float = 1.0
    signal: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Event":
        kind = EventKind(raw.get("kind", "observation"))
        track = raw.get("track_id")
        camera = raw.get("camera")
        # No zone? Then the whole camera view is the area of interest. Multiple
        # cameras stay separate because the camera id becomes the zone.
        zone = raw.get("zone") or camera or DEFAULT_ZONE
        return cls(
            ts=_parse_ts(raw["ts"]),
            kind=kind,
            zone=str(zone),
            track_id=None if track is None else str(track),
            camera=None if camera is None else str(camera),
            label=str(raw.get("label", "person")),
            confidence=float(raw.get("confidence", 1.0)),
            signal=raw.get("signal"),
            meta=dict(raw.get("meta", {})),
        )

    @property
    def clock(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%H:%M:%S")


def read_jsonl(path: str) -> Iterator[Event]:
    """Read newline-delimited JSON events, sorted defensively by timestamp."""
    events: list[Event] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                events.append(Event.from_dict(json.loads(line)))
            except Exception as exc:  # noqa: BLE001 - want the line number
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    yield from sorted(events, key=lambda e: e.ts)


def synth_observations(
    track_id: str, zone: str = DEFAULT_ZONE, start: float = 0.0, end: float = 0.0,
    step: float = 1.0,
) -> Iterable[Event]:
    """Helper for tests/demos: a track continuously present over a span."""
    ts = start
    while ts <= end:
        yield Event(ts=ts, kind=EventKind.OBSERVATION, zone=zone, track_id=track_id)
        ts += step
