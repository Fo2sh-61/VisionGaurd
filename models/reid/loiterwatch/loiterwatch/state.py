"""Occupancy state derived from the raw event stream.

The important real-world detail here is `exit_grace`: detectors drop frames and
trackers briefly lose people. Without a grace period a person standing still at
an ATM looks like twenty short visits instead of one long one, and no dwell rule
would ever fire.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Iterable


@dataclass
class Visit:
    """A completed (or in-progress) stay by one track inside one zone."""

    track_id: str
    zone: str
    entered_at: float
    last_seen: float
    exited_at: float | None = None
    observations: int = 1
    max_confidence: float = 1.0
    #: signals attributed to this track while it was inside the zone
    signals: set[str] = field(default_factory=set)

    def dwell(self, now: float | None = None) -> float:
        end = self.exited_at if self.exited_at is not None else (now or self.last_seen)
        return max(0.0, end - self.entered_at)

    @property
    def open(self) -> bool:
        return self.exited_at is None


@dataclass
class ZoneState:
    zone: str
    #: track_id -> in-progress visit
    active: dict[str, Visit] = field(default_factory=dict)
    #: track_id -> recent closed visits (newest last)
    history: dict[str, Deque[Visit]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=64))
    )
    #: (ts, signal_name, track_id|None), newest last
    signals: Deque[tuple[float, str, str | None]] = field(
        default_factory=lambda: deque(maxlen=512)
    )

    def visits(self, track_id: str) -> list[Visit]:
        """All known visits by a track, oldest first, including the open one."""
        out = list(self.history.get(track_id, ()))
        if track_id in self.active:
            out.append(self.active[track_id])
        return out

    def signals_between(
        self, start: float, end: float, names: Iterable[str], track_id: str | None = None
    ) -> list[tuple[float, str, str | None]]:
        wanted = set(names)
        return [
            s
            for s in self.signals
            if start <= s[0] <= end
            and s[1] in wanted
            and (track_id is None or s[2] is None or s[2] == track_id)
        ]


class WorldState:
    """All zones, plus the engine clock."""

    def __init__(self, exit_grace: float = 3.0, min_confidence: float = 0.0) -> None:
        self.exit_grace = exit_grace
        self.min_confidence = min_confidence
        self.zones: dict[str, ZoneState] = {}
        self.now: float = 0.0

    def zone(self, name: str) -> ZoneState:
        if name not in self.zones:
            self.zones[name] = ZoneState(zone=name)
        return self.zones[name]

    # -- ingestion ---------------------------------------------------------
    def observe(self, zone: str, track_id: str, ts: float, confidence: float = 1.0) -> Visit:
        z = self.zone(zone)
        visit = z.active.get(track_id)
        if visit is None:
            visit = Visit(
                track_id=track_id, zone=zone, entered_at=ts, last_seen=ts,
                max_confidence=confidence,
            )
            z.active[track_id] = visit
        else:
            visit.last_seen = ts
            visit.observations += 1
            visit.max_confidence = max(visit.max_confidence, confidence)
        return visit

    def force_enter(self, zone: str, track_id: str, ts: float) -> Visit:
        self.close(zone, track_id, ts)
        return self.observe(zone, track_id, ts)

    def close(self, zone: str, track_id: str, ts: float) -> Visit | None:
        z = self.zone(zone)
        visit = z.active.pop(track_id, None)
        if visit is not None:
            visit.exited_at = max(ts, visit.last_seen)
            z.history[track_id].append(visit)
        return visit

    def add_signal(self, zone: str, name: str, ts: float, track_id: str | None) -> None:
        z = self.zone(zone)
        z.signals.append((ts, name, track_id))
        if track_id and track_id in z.active:
            z.active[track_id].signals.add(name)
        elif track_id is None:
            # unattributed signal (e.g. card reader): credit everyone in the zone
            for visit in z.active.values():
                visit.signals.add(name)

    def expire(self, now: float) -> list[Visit]:
        """Close visits whose track has not been seen within the grace period."""
        closed: list[Visit] = []
        for z in self.zones.values():
            stale = [
                tid for tid, v in z.active.items() if now - v.last_seen > self.exit_grace
            ]
            for tid in stale:
                visit = self.close(z.zone, tid, z.active[tid].last_seen)
                if visit:
                    closed.append(visit)
        return closed
