"""Test setup: import path, and keeping hardware tests opt-in."""

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))


def pytest_addoption(parser):
    parser.addoption(
        "--camera",
        action="store_true",
        default=False,
        help="run tests that need a real camera attached",
    )


def pytest_collection_modifyitems(config, items):
    """Skip `@pytest.mark.camera` tests unless they are asked for.

    They need hardware that may not be present, they are slow, and they fail
    confusingly when something else already holds the device — a running engine
    grabbing webcam:0 makes them look like a code regression when they are not.

        python -m pytest --camera        run them
        python -m pytest -m camera       run only them
    """
    if config.getoption("--camera") or "camera" in (config.getoption("-m") or ""):
        return

    skip = pytest.mark.skip(reason="needs a camera; run with --camera")
    for item in items:
        if "camera" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def bare_live_store():
    """A `LiveStore` with cameras configured and every subsystem absent.

    This is the state that used to make pages lie: real enough to be serving
    an operator, with nothing behind the features they are looking at. A
    freshly installed engine, or a running one after a model failed to load.
    """
    from vg.api.live import LiveStore
    from vg import config as vgconfig
    from vg.ingest.registry import CameraRegistry

    cfg = vgconfig.load()
    # No workers started, so nothing is online and nothing has a frame.
    registry = CameraRegistry([])
    return LiveStore(config=cfg, registry=registry)


@pytest.fixture
def live_ish_store():
    """A `LiveStore` with its cameras actually configured.

    Enough for the capability list to report something as live, so the
    "a live capability offers no excuse" rule has something to check.
    """
    from vg.api.live import LiveStore
    from vg import config as vgconfig
    from vg.ingest.registry import CameraRegistry

    cfg = vgconfig.load()
    registry = CameraRegistry(cfg.cameras)
    return LiveStore(config=cfg, registry=registry)


# ---------------------------------------------------------------------------
# authentication, for tests that need to get past the front door
#
# Every endpoint except /healthz and /auth/login now refuses an unauthenticated
# caller (P2). That is the product working, but it means an API test has to
# sign in like anything else. These fixtures make that one line.
#
# Tests that check the refusal itself deliberately do NOT use them - see
# test_authorisation.py, which uses a bare client on purpose.
# ---------------------------------------------------------------------------

@pytest.fixture
def user_store(tmp_path):
    """A real UserStore on a throwaway database."""
    from vg.auth.store import UserStore

    store = UserStore(tmp_path / "auth.db")
    yield store
    store.close()


@pytest.fixture
def sign_in(user_store):
    """Give an app a working session, and hand back the bearer token.

    Attaches the store to `app.state.users` the way the lifespan would, so a
    TestClient built without `with` still has authentication available.
    """
    def _sign_in(app, role: str = "admin", email: str | None = None) -> str:
        email = email or f"{role}@test.local"
        user = user_store.create_user(
            email=email, name=f"Test {role.title()}", role=role,
            password="a-long-enough-test-password",
        )
        token, _expires = user_store.start_session(user)
        app.state.users = user_store
        return token
    return _sign_in


@pytest.fixture
def authed(sign_in):
    """`client(app)` -> a TestClient already carrying an admin session."""
    from fastapi.testclient import TestClient

    def _client(app, role: str = "admin"):
        token = sign_in(app, role)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})
    return _client
