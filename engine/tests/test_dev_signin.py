"""Developer sign-in: TEMPORARY, development only. DEV-SIGNIN.

Deleted together with `vg/auth/dev_signin.py` when Mohamed removes it.

These tests are the fences. A console of children's faces that opens without
a password is only acceptable on the developer's own computer, so every way it
could get out of there is tried here and has to fail: left switched off, run
under the deployment setting, reached from another machine, reached through a
proxy on this one.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import dev_signin  # noqa: E402

HERE = ("127.0.0.1", 50000)
ELSEWHERE = ("192.168.1.20", 50000)


@pytest.fixture
def make_app(user_store, monkeypatch):
    """`make_app(role)` -> an app built with VG_DEV_SIGNIN set to `role`."""
    from vg.api import app as app_module

    def _make(role: str | None):
        monkeypatch.delenv("VG_STRICT", raising=False)
        if role is None:
            monkeypatch.delenv(dev_signin.ENV, raising=False)
        else:
            monkeypatch.setenv(dev_signin.ENV, role)
        app_module.set_store(MockStore())
        application = create_app()
        application.state.users = user_store
        return application
    return _make


def client(app, *, peer=HERE, host="localhost:5173") -> TestClient:
    """A browser at `host`, connecting from `peer`."""
    return TestClient(app, base_url=f"http://{host}", client=peer)


class TestOffUnlessAskedFor:
    def test_unset_lets_nobody_in(self, make_app):
        assert client(make_app(None)).get("/auth/me").status_code == 401

    @pytest.mark.parametrize("value", ["", "  "])
    def test_blank_is_unset(self, monkeypatch, value):
        monkeypatch.setenv(dev_signin.ENV, value)
        assert dev_signin.role_from_env() is None


class TestRefusesToStart:
    def test_under_the_deployment_setting(self, monkeypatch):
        """VG_STRICT=1 is what CI and the school's machine run under."""
        monkeypatch.setenv(dev_signin.ENV, "admin")
        monkeypatch.setenv("VG_STRICT", "1")
        with pytest.raises(RuntimeError, match="VG_STRICT"):
            create_app()

    @pytest.mark.parametrize("value", ["root", "1", "true", "administrator"])
    def test_with_anything_but_a_role(self, monkeypatch, value):
        """A typo must stop the engine, not guess at a role."""
        monkeypatch.delenv("VG_STRICT", raising=False)
        monkeypatch.setenv(dev_signin.ENV, value)
        with pytest.raises(RuntimeError, match="not a role"):
            create_app()


class TestSwitchedOn:
    def test_the_console_opens_as_the_developer(self, make_app):
        me = client(make_app("admin")).get("/auth/me")
        assert me.status_code == 200
        body = me.json()
        # The name is what every audit entry records, so it must never be
        # mistaken for a real person.
        assert body["name"] == "Developer (dev sign-in)"
        assert body["role"] == "admin"
        assert body["initials"] == "DV"
        assert body["devSignIn"] is True

    def test_it_sees_exactly_what_it_staff_see(self, make_app):
        c = client(make_app("it"))
        assert c.get("/auth/me").json()["role"] == "it"
        assert c.get("/users").status_code == 403

    def test_a_real_session_still_wins(self, make_app, sign_in):
        app = make_app("admin")
        token = sign_in(app, "it")
        me = client(app).get("/auth/me",
                             headers={"Authorization": f"Bearer {token}"})
        assert me.json()["role"] == "it"
        assert me.json()["devSignIn"] is False

    def test_nothing_is_written(self, make_app, user_store):
        """No account row and no session row - nothing left behind to find,
        or to forget to delete, after the feature is gone."""
        c = client(make_app("admin"))
        c.get("/auth/me")
        c.post("/auth/language", json={"language": "ar"})
        assert user_store.count() == 0
        with closing(sqlite3.connect(user_store.database)) as db:
            assert db.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0

    def test_its_language_holds_until_the_engine_stops(self, make_app):
        """It has no row to save a language in. Pretending to save one would
        be the fake save rule 4 forbids, so it is held in memory instead."""
        c = client(make_app("admin"))
        changed = c.post("/auth/language", json={"language": "ar"})
        assert changed.json()["devSignIn"] is True
        assert c.get("/auth/me").json()["language"] == "ar"


class TestThisComputerOnly:
    @pytest.mark.parametrize("peer, host", [
        (HERE, "localhost:5173"),
        (HERE, "127.0.0.1:8000"),
        (("::1", 50000), "[::1]:8000"),
        (("::ffff:127.0.0.1", 50000), "localhost:8000"),
    ])
    def test_in_any_spelling(self, make_app, peer, host):
        # The Host goes in as a header: TestClient cannot parse an IPv6
        # base_url ("[::1]:8000" splits on the first colon).
        c = client(make_app("admin"), peer=peer)
        assert c.get("/auth/me", headers={"host": host}).status_code == 200

    def test_another_machine_still_needs_a_password(self, make_app):
        c = client(make_app("admin"), peer=ELSEWHERE)
        assert c.get("/auth/me").status_code == 401

    def test_a_proxy_forwarding_a_real_hostname_is_refused(self, make_app):
        """nginx in front of the engine connects from 127.0.0.1 too. The
        hostname it passes on is what gives it away."""
        c = client(make_app("admin"), host="school.example")
        assert c.get("/auth/me").status_code == 401

    def test_an_unreadable_host_is_refused_not_a_crash(self, make_app):
        c = client(make_app("admin"))
        assert c.get("/auth/me", headers={"host": "[::1"}).status_code == 401
