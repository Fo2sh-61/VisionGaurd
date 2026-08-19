"""Fights is out of scope, and staying out.

There is no fight model and none is coming, so the feature was cut. The code
outlived the decision by some months, which is the usual way a removed feature
comes back: nobody deletes the endpoints, the next person finds them, and the
UI gets rebuilt against something that was never going to work.

`/fights/{id}/feedback` was the reason this could not simply be left alone. It
accepted "not a fight" from an operator, called it a training label, wrote a
line to an in-memory audit list and dropped it. Somebody correcting the system
in good faith was told their correction had been kept. Nothing was kept, and
there was no model for it to teach.

These tests fail if any of it comes back without a decision to bring it back.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vg.api import app as app_module
from vg.api.app import create_app
from vg.api.store import MockStore


@pytest.fixture
def client() -> TestClient:
    app_module.set_store(MockStore())
    return TestClient(create_app())


@pytest.mark.parametrize("method, path", [
    ("get", "/fights"),
    ("get", "/fights/cameras"),
    ("post", "/fights/f1/feedback"),
])
def test_the_endpoints_are_gone(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 404, (
        f"{method.upper()} {path} still answers with {response.status_code}"
    )


def test_no_route_mentions_fights(client):
    """Catches a renamed or re-prefixed revival, which the 404s above would miss."""
    paths = [r.path for r in create_app().routes]
    assert not [p for p in paths if "fight" in p.lower()], paths


def test_the_store_has_no_fight_methods():
    store = MockStore()
    for name in ("fights", "flag_fight", "fight_cameras"):
        assert not hasattr(store, name), f"MockStore.{name} is still here"


def test_the_wire_has_no_fight_types():
    from vg.api import schemas as S

    for name in ("FightIncident", "FightFeedback"):
        assert not hasattr(S, name), f"schemas.{name} is still here"


def test_no_pipeline_stage_claims_fight_detection(client):
    """System Health listed a permanently-broken stage for a feature we cut.

    A red row for something nobody intends to fix trains an operator to ignore
    red rows, which is the opposite of what that page is for.
    """
    stages = client.get("/system/health").json()["pipeline"]
    assert not [s for s in stages if "fight" in s["key"].lower()
                or "fight" in s["name"].lower()], stages


def test_no_event_type_announces_a_fight(client):
    """`fight.detected` on the event union would let one be pushed to a phone."""
    from vg.api import schemas as S

    assert "fight" not in str(S.LiveEvent.model_fields["type"]).lower()
