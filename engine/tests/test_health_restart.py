"""System Health offers no restart, because nothing can perform one.

Five stages used to be marked `restartable` - in eight branches between them -
and the console drew a Restart button for each. No endpoint restarts anything,
so every one of those buttons did nothing, on the one page an operator opens
when something is already wrong. Rule 4: no dead buttons.

If a restart is ever built, these fail on purpose. Wire the console to it
first, then let the stages it can really restart say so.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api.store import MockStore  # noqa: E402


class FakeWorker:
    """Enough of a feature worker for its stage to report it running."""

    def __init__(self, name: str, cameras: int = 2) -> None:
        self.cameras = [f"cam-{i}" for i in range(cameras)]
        self.stats = {
            "name": name, "cameras": cameras, "frames_processed": 1,
            "last_inference_ms": 20.0, "queue_depth": 0, "queue_max": 1,
            "frames_dropped": 0, "behind": False,
        }


def _nothing_running(store) -> None:
    """Camera ingest said it on every call, whatever state it was in."""


def _failed_to_start(store) -> None:
    store.recognition_error = "model missing"
    store.people_error = "model missing"


def _people_loaded_but_idle(store) -> None:
    store.people_worker = FakeWorker("people", cameras=0)


def _people_running(store) -> None:
    store.people_worker = FakeWorker("people")


def _recognition_running(store) -> None:
    store.gallery = SimpleNamespace(size=3, embedding_count=9)
    store.sightings = object()
    store.recogniser = FakeWorker("recognition")


def _knives_running(store) -> None:
    store.people_worker = FakeWorker("people")
    store.weapons_worker = FakeWorker("weapons")
    store.weapon_scenes = object()


def _plates_running(store) -> None:
    store._gate_cameras = lambda: [SimpleNamespace(gate=1)]
    store.vehicles_worker = FakeWorker("vehicles")
    store.vehicle_store = object()


# Between them, every branch that used to say `restartable=True`.
STATES = [
    _nothing_running, _failed_to_start, _people_loaded_but_idle,
    _people_running, _recognition_running, _knives_running, _plates_running,
]


@pytest.mark.parametrize("state", STATES, ids=lambda f: f.__name__.strip("_"))
def test_no_stage_offers_a_restart(bare_live_store, state):
    state(bare_live_store)
    offered = [s.name for s in bare_live_store.health().pipeline
               if s.restartable]
    assert offered == [], f"{offered} offer a restart no endpoint performs"


def test_nor_does_the_mock():
    """`up -Mock` is where console work happens, so a Restart shown there
    is one somebody builds a page around."""
    offered = [s.name for s in MockStore().health().pipeline if s.restartable]
    assert offered == []
