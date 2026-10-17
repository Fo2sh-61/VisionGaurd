"""Changing an account: name, role, and whether it can sign in (spec 016, US4).

The one rule that must never break: there is always at least one active
administrator. Without one, nobody can make or fix accounts from the console,
and the only way back is a shell on the workstation.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.api import app as app_module  # noqa: E402
from vg.api.live import LiveStore  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth.store import LastAdminError, UserStore  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402

PASSWORD = "a-long-enough-test-password"


@pytest.fixture
def users(tmp_path):
    store = UserStore(tmp_path / "auth.db")
    yield store
    store.close()


@pytest.fixture
def live(users):
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]), users=users)
    app_module.set_store(store)
    yield store
    app_module.set_store(MockStore())


def client(users, email, role="admin", name=None):
    """A signed-in client for a fresh account. Returns (client, user)."""
    user = users.create_user(email=email, name=name or email.split("@")[0],
                             role=role, password=PASSWORD)
    token, _ = users.start_session(user)
    app = app_module.create_app()
    app.state.users = users
    return TestClient(app, headers={"Authorization": f"Bearer {token}"}), user


class TestTheStore:
    def test_saves_each_field(self, users):
        users.create_user(email="a@x", name="Head", role="admin", password=PASSWORD)
        u = users.create_user(email="b@x", name="Tarek", role="it", password=PASSWORD)
        got = users.update_user(u.id, name="Tarek N.", role="admin")
        assert (got.name, got.role, got.disabled) == ("Tarek N.", "admin", False)
        got = users.update_user(u.id, disabled=True)
        assert got.disabled is True and got.name == "Tarek N."

    def test_unknown_id_is_none(self, users):
        assert users.update_user("nobody", name="x") is None

    def test_the_last_admin_cannot_be_demoted_or_disabled(self, users):
        a = users.create_user(email="a@x", name="Head", role="admin", password=PASSWORD)
        for change in ({"role": "it"}, {"disabled": True}):
            with pytest.raises(LastAdminError):
                users.update_user(a.id, **change)
        assert users.update_user(a.id, name="Head teacher").role == "admin"

    def test_a_disabled_admin_does_not_count(self, users):
        a = users.create_user(email="a@x", name="A", role="admin", password=PASSWORD)
        b = users.create_user(email="b@x", name="B", role="admin", password=PASSWORD)
        users.update_user(b.id, disabled=True)
        with pytest.raises(LastAdminError):
            users.update_user(a.id, role="it")

    def test_disabling_ends_every_session(self, users):
        users.create_user(email="a@x", name="A", role="admin", password=PASSWORD)
        b = users.create_user(email="b@x", name="B", role="it", password=PASSWORD)
        token, _ = users.start_session(b)
        users.update_user(b.id, disabled=True)
        assert users.user_for_token(token) is None
        users.update_user(b.id, disabled=False)
        assert users.user_for_token(token) is None, "a session came back"

    def test_an_unknown_role_is_refused(self, users):
        u = users.create_user(email="a@x", name="A", role="admin", password=PASSWORD)
        with pytest.raises(ValueError):
            users.update_user(u.id, role="guard")


class TestTheRoute:
    def test_saves_name_role_and_disabled(self, users, live):
        c, _ = client(users, "head@x")
        other = users.create_user(email="t@x", name="Tarek", role="it", password=PASSWORD)
        r = c.patch(f"/users/{other.id}", json={"name": "Tarek Nassar", "role": "admin"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Tarek Nassar" and r.json()["role"] == "admin"
        r = c.patch(f"/users/{other.id}", json={"disabled": True})
        assert r.status_code == 200 and r.json()["disabled"] is True

    def test_get_users_shows_disabled_accounts_too(self, users, live):
        c, _ = client(users, "head@x")
        other = users.create_user(email="t@x", name="Tarek", role="it", password=PASSWORD)
        c.patch(f"/users/{other.id}", json={"disabled": True})
        listed = {u["id"]: u for u in c.get("/users").json()}
        assert listed[other.id]["disabled"] is True

    def test_the_audit_entry_comes_before_the_write(self, users, live, monkeypatch):
        c, _ = client(users, "head@x")
        other = users.create_user(email="t@x", name="Tarek", role="it", password=PASSWORD)

        def broken(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(users, "update_user", broken)
        with pytest.raises(sqlite3.OperationalError):
            c.patch(f"/users/{other.id}", json={"name": "x"})
        assert "user.edit" in [e.action for e in live.audit(20)]

    def test_an_it_account_is_refused(self, users, live):
        client(users, "head@x")
        c, _ = client(users, "it@x", role="it")
        other = users.create_user(email="t@x", name="Tarek", role="it", password=PASSWORD)
        assert c.patch(f"/users/{other.id}", json={"name": "x"}).status_code == 403

    def test_unknown_id_is_404(self, users, live):
        c, _ = client(users, "head@x")
        assert c.patch("/users/nobody", json={"name": "x"}).status_code == 404

    @pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"role": "guard"},
                                      {"disabled": "maybe"}, {"email": "x@y"}])
    def test_a_bad_body_is_422(self, users, live, body):
        c, me = client(users, "head@x")
        assert c.patch(f"/users/{me.id}", json=body).status_code == 422

    @pytest.mark.parametrize("change", [{"role": "it"}, {"disabled": True}])
    def test_the_last_admin_is_kept_every_way(self, users, live, change):
        # By themselves...
        c, me = client(users, "head@x")
        r = c.patch(f"/users/{me.id}", json=change)
        assert r.status_code == 409 and "administrator" in r.json()["detail"]
        # ...and by another account, once the only other admin is disabled.
        c2, two = client(users, "deputy@x")
        assert c.patch(f"/users/{two.id}", json={"disabled": True}).status_code == 200
        r = c2.patch(f"/users/{me.id}", json=change)
        assert r.status_code in (401, 409)
        assert users.update_user(me.id).role == "admin"

    def test_with_two_admins_one_can_be_disabled(self, users, live):
        c, _ = client(users, "head@x")
        _, two = client(users, "deputy@x")
        assert c.patch(f"/users/{two.id}", json={"disabled": True}).status_code == 200

    def test_a_disabled_account_is_signed_out_on_its_next_click(self, users, live):
        c, _ = client(users, "head@x")
        c2, two = client(users, "t@x", role="it")
        assert c2.get("/site").status_code == 200
        c.patch(f"/users/{two.id}", json={"disabled": True})
        assert c2.get("/site").status_code == 401

    def test_a_role_change_applies_on_the_next_request(self, users, live):
        c, _ = client(users, "head@x")
        c2, two = client(users, "t@x", role="it")
        assert c2.get("/users").status_code == 403
        c.patch(f"/users/{two.id}", json={"role": "admin"})
        assert c2.get("/users").status_code == 200

    def test_the_demo_store_never_pretends_to_save(self, users):
        app_module.set_store(MockStore())
        c, me = client(users, "head@x")
        assert c.patch(f"/users/{me.id}", json={"name": "x"}).status_code == 503
