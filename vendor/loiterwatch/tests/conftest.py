from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loiterwatch import Engine, Event, EventKind  # noqa: E402

T0 = 1_770_000_000.0  # arbitrary fixed epoch; keeps tests deterministic


@pytest.fixture
def t0() -> float:
    return T0


def obs(track: str, zone: str, ts: float, conf: float = 0.9) -> Event:
    return Event(ts=ts, kind=EventKind.OBSERVATION, zone=zone, track_id=track,
                 confidence=conf)


def exit_event(track: str, zone: str, ts: float) -> Event:
    return Event(ts=ts, kind=EventKind.EXIT, zone=zone, track_id=track)


def signal(zone: str, name: str, ts: float, track: str | None = None) -> Event:
    return Event(ts=ts, kind=EventKind.SIGNAL, zone=zone, signal=name, track_id=track)


def stay(engine: Engine, track: str, zone: str, start: float, end: float,
         step: float = 2.0, conf: float = 0.9) -> list:
    """Feed continuous observations for a track and return all alerts raised."""
    alerts = []
    ts = start
    while ts <= end:
        alerts += engine.ingest(obs(track, zone, ts, conf))
        ts += step
    return alerts
