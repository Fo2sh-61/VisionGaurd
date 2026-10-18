"""Every picture, stream and clip needs a session (spec 020 P10-FR-119, T014).

`test_authorisation.py` walks the fixed GET paths. Every media route takes a
parameter (a camera, a clip id), so it was skipped there. This walks those too,
from the factory network and from outside, because remote access makes "only
people on the LAN can reach it" no longer true of any route.

It should pass on the day it was written; it guards the future. A new media
route is found by its shape, so it is checked the day it is added.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from vg.api import app as app_module
from vg.api.app import create_app
from vg.api.store import MockStore
from vg.auth import deps as auth_deps

LAN = ("192.168.1.20", 50000)
NETBIRD = ("100.81.4.7", 50000)
MEDIA = re.compile(r"/(snapshot|stream|clip|crop)$|/chunks/")


@pytest.fixture
def app(user_store):
    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


def get_routes(app):
    out = []
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        if "GET" in methods:
            out.append(route.path)
    return sorted(set(out))


def filled(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_the_media_routes_are_found():
    """Guard the guard: an empty list must not read as success."""
    media = [p for p in get_routes(create_app()) if MEDIA.search(p)]
    assert {"/cameras/{camera_id}/snapshot", "/cameras/{camera_id}/stream",
            "/weapons/{detection_id}/clip", "/falls/{fall_id}/clip",
            "/breaches/{breach_id}/clip", "/path/legs/{job_id}/chunks/{index}",
            "/vehicles/passes/{pass_id}/snapshot",
            "/vehicles/cameras/{camera_id}/crop"} <= set(media), media


@pytest.mark.parametrize("where", [LAN, NETBIRD], ids=["lan", "remote"])
def test_every_media_route_refuses_a_caller_with_no_session(app, where):
    anon = TestClient(app, client=where)
    answered = [f"{p} -> {code}" for p in get_routes(app) if MEDIA.search(p)
                if (code := anon.get(filled(p)).status_code) != 401]
    assert not answered, answered


@pytest.mark.parametrize("where", [LAN, NETBIRD], ids=["lan", "remote"])
def test_every_route_with_a_parameter_refuses_one_too(app, where):
    """Wider than media: nothing parameterised answers a stranger."""
    anon = TestClient(app, client=where)
    answered = [f"{p} -> {code}" for p in get_routes(app) if "{" in p
                if (code := anon.get(filled(p)).status_code) != 401]
    assert not answered, answered


def test_a_media_request_with_a_session_cookie_gets_past_the_door(app, sign_in):
    token = sign_in(app, "it")
    app.state.registry = None           # what the lifespan sets with no cameras
    client = TestClient(app, client=NETBIRD, cookies={auth_deps.COOKIE_NAME: token})
    # No camera capture in a test app: 404 from the handler, not 401 at the door.
    assert client.get("/cameras/cam-1/snapshot").status_code == 404


def test_the_public_paths_are_exactly_three():
    assert auth_deps.PUBLIC_PATHS == frozenset({"/healthz", "/auth/login", "/auth/register"})
    assert auth_deps.PUBLIC_PREFIXES == ()
