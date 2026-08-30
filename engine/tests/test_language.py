"""A person's language belongs to their account, not to the browser.

The gate station is shared. If the language lived in the browser, the second
guard on shift would get the first guard's language, and would have to change
it back every time. So it is a column on `app_user`, and this is the test that
it round-trips and cannot be used to reach anybody else's account.

It is a **preference**, deliberately not a permission. `auth/deps.py` decides
what a caller may do by path and must never learn that `language` exists —
a display setting that could change access would be a second, hidden
permission system.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vg.api.app import create_app
from vg.api.store import MockStore


@pytest.fixture
def client(authed) -> TestClient:
    from vg.api import app as app_module

    app_module.set_store(MockStore())
    return authed(create_app())


class TestTheColumn:
    def test_a_new_account_reads_english(self, user_store):
        user = user_store.create_user(
            email="new@test.local", name="New Person", role="it",
            password="a-long-enough-test-password",
        )
        assert user.language == "en"

    def test_a_choice_survives_a_new_session(self, user_store):
        user = user_store.create_user(
            email="guard@test.local", name="Gate Guard", role="it",
            password="a-long-enough-test-password",
        )
        user_store.set_language(user.id, "ar")

        # Everything that rebuilds a User from a row has to carry it, or the
        # choice silently reverts on the next page load.
        token, _ = user_store.start_session(user)
        assert user_store.user_for_token(token).language == "ar"
        assert user_store.authenticate(
            "guard@test.local", "a-long-enough-test-password").language == "ar"
        assert [u.language for u in user_store.users()
                if u.id == user.id] == ["ar"]

    def test_an_unknown_language_is_refused(self, user_store):
        user = user_store.create_user(
            email="x@test.local", name="X", role="it",
            password="a-long-enough-test-password",
        )
        with pytest.raises(ValueError):
            user_store.set_language(user.id, "fr")


class TestTheEndpoint:
    def test_the_account_carries_its_language(self, client):
        assert client.get("/auth/me").json()["language"] == "en"

    def test_changing_it_returns_the_updated_account(self, client):
        body = client.post("/auth/language", json={"language": "ar"}).json()
        assert body["language"] == "ar"
        assert client.get("/auth/me").json()["language"] == "ar"

    def test_an_unknown_language_is_a_422(self, client):
        assert client.post(
            "/auth/language", json={"language": "fr"}).status_code == 422

    def test_it_changes_nobody_else(self, client, user_store):
        # No user_id parameter exists, and none may be smuggled in: `Wire`
        # forbids extras, so this is a 422 rather than a quiet write to
        # somebody else's row.
        other = user_store.create_user(
            email="other@test.local", name="Other", role="it",
            password="a-long-enough-test-password",
        )
        response = client.post(
            "/auth/language", json={"language": "ar", "userId": other.id})
        assert response.status_code == 422
        assert user_store.users() and all(
            u.language == "en" for u in user_store.users() if u.id == other.id)

    def test_it_needs_a_session(self, user_store):
        # A preference is still somebody's preference. With a working user
        # store and no token, that is a 401.
        from vg.api import app as app_module

        app_module.set_store(MockStore())
        app = create_app()
        app.state.users = user_store
        assert TestClient(app).post(
            "/auth/language", json={"language": "ar"}).status_code == 401

    def test_no_auth_at_all_is_a_503_not_a_401(self):
        # Different answer to a different question. An engine that cannot
        # check who you are must not guess, so the middleware refuses
        # everything and System Health says why — see app.py's auth gate.
        # 401 here would invite the console to show a sign-in form that
        # could never succeed.
        from vg.api import app as app_module

        app_module.set_store(MockStore())
        bare = TestClient(create_app())
        assert bare.post(
            "/auth/language", json={"language": "ar"}).status_code == 503
