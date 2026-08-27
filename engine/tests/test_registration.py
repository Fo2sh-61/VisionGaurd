"""Open sign-up: anyone who reaches the console can make a working account.

`POST /auth/register` is the second public endpoint in the product, after
`/auth/login`. It exists because the console needed a "Create an account"
form; the decision to leave it open was made deliberately, with the trade
written down in the endpoint's own docstring.

What these tests exist to hold still is the boundary around that decision:

* the role is **always** "it", whatever the request says or tries to say;
* the password rules are the same ones every other account gets;
* one caller cannot turn the form into a million rows;
* a duplicate address is refused rather than quietly succeeding.

The third one matters most. `test_a_registered_account_cannot_reach_admin_
routes` is what keeps this endpoint from becoming a way to enrol a face.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import app as app_module  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import deps as auth_deps  # noqa: E402
from vg.auth.passwords import MIN_LENGTH  # noqa: E402
from vg.auth.store import EmailTaken  # noqa: E402

GOOD_PASSWORD = "a-long-enough-test-password"


@pytest.fixture
def app(user_store):
    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


@pytest.fixture
def anon(app):
    """No session at all — the state a person signing up is actually in."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_throttle():
    """A clean rate limiter per test.

    The throttle is module state on purpose (it has to outlive a request), so
    without this the sixth test in the file starts failing for reasons that
    have nothing to do with what it is checking.
    """
    from vg.api.app import _SignupThrottle

    app_module._signups = _SignupThrottle()
    yield
    app_module._signups = _SignupThrottle()


def register(client, **overrides):
    body = {"name": "New Person", "email": "new@test.local",
            "password": GOOD_PASSWORD}
    body.update(overrides)
    return client.post("/auth/register", json=body)


# ---------------------------------------------------------------------------
# it works
# ---------------------------------------------------------------------------

class TestSigningUp:
    def test_the_form_is_reachable_without_a_session(self, anon):
        """Requiring an account to make an account would be circular."""
        assert auth_deps.is_public("/auth/register")
        assert register(anon).status_code == 200

    def test_a_new_account_is_signed_in_immediately(self, anon):
        """"Works immediately" is the product decision, so prove it: the
        response carries a session, and that session is already good."""
        token = register(anon).json()["token"]

        me = anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert me.status_code == 200
        assert me.json()["email"] == "new@test.local"

    def test_the_cookie_is_set_too(self, anon):
        """The MJPEG camera streams are `<img src=...>` and cannot send a
        header. A sign-up that skipped the cookie would look like it worked
        and then draw black cameras."""
        response = register(anon)

        assert auth_deps.COOKIE_NAME in response.cookies

    def test_the_password_never_comes_back(self, anon):
        assert GOOD_PASSWORD not in register(anon).text

    def test_the_account_can_sign_in_again_afterwards(self, anon):
        """The row is real, not just a session handed out on the spot."""
        register(anon)

        again = anon.post("/auth/login", json={
            "email": "new@test.local", "password": GOOD_PASSWORD})

        assert again.status_code == 200

    def test_the_email_is_matched_without_case(self, anon, user_store):
        """`COLLATE NOCASE` on the column. Signing up as New@ and in as new@
        has to be one account, or a school gets two of everybody."""
        register(anon, email="New@Test.Local")

        again = anon.post("/auth/login", json={
            "email": "new@test.local", "password": GOOD_PASSWORD})

        assert again.status_code == 200
        assert user_store.count() == 1


# ---------------------------------------------------------------------------
# the boundary — this is the part that must never soften
# ---------------------------------------------------------------------------

class TestSignUpCannotHandOutAdmin:
    def test_a_new_account_is_always_it(self, anon):
        response = register(anon)

        assert response.json()["user"]["role"] == "it"

    def test_asking_for_admin_is_refused_outright(self, anon, user_store):
        """`extra="forbid"` on the wire type. Not ignored — rejected, so a
        body that tries this never reaches the handler at all."""
        response = anon.post("/auth/register", json={
            "name": "Chancer", "email": "chancer@test.local",
            "password": GOOD_PASSWORD, "role": "admin"})

        assert response.status_code == 422
        assert user_store.count() == 0

    def test_a_registered_account_cannot_reach_admin_routes(self, anon):
        """The one that matters.

        Enrolment decides whose face the system can name. If open sign-up
        reached it, a stranger could add a child to the gallery from the
        login page.
        """
        token = register(anon).json()["token"]
        signed_up = {"Authorization": f"Bearer {token}"}

        for path in ("/enrolment", "/sources", "/users"):
            response = anon.get(path, headers=signed_up)
            assert response.status_code in (403, 404, 503), (
                f"{path} answered a self-registered account: {response.status_code}"
            )


# ---------------------------------------------------------------------------
# what it refuses
# ---------------------------------------------------------------------------

class TestSignUpRefuses:
    def test_a_short_password(self, anon, user_store):
        response = register(anon, password="short")

        assert response.status_code == 400
        assert str(MIN_LENGTH) in response.json()["detail"]
        assert user_store.count() == 0

    def test_an_address_that_is_already_registered(self, anon, user_store):
        """409, and not a second row.

        This is the honest cost of an open form: unlike `/auth/login`, it
        admits an address exists. Saying "done" and creating nothing would be
        showing something untrue, which is the worse of the two.
        """
        register(anon)

        second = register(anon, name="Someone Else")

        assert second.status_code == 409
        assert user_store.count() == 1

    def test_a_blank_name(self, anon, user_store):
        response = register(anon, name="   ")

        assert response.status_code == 400
        assert user_store.count() == 0

    @pytest.mark.parametrize("bad", ["", "not-an-email", "no@domain",
                                     "has space@test.local", "@test.local",
                                     "trailing@dot."])
    def test_an_address_that_is_not_one(self, anon, user_store, bad):
        assert register(anon, email=bad).status_code == 400
        assert user_store.count() == 0

    def test_a_name_longer_than_the_column_should_hold(self, anon, user_store):
        """An unauthenticated endpoint must not be a way to write megabytes
        into the database one field at a time."""
        assert register(anon, name="x" * 5000).status_code == 400
        assert user_store.count() == 0

    def test_one_caller_cannot_make_accounts_without_end(self, anon, user_store):
        """The throttle. It forgets on restart and a botnet walks around it;
        neither is what it is for."""
        from vg.api.app import SIGNUP_LIMIT

        for i in range(SIGNUP_LIMIT):
            assert register(anon, email=f"p{i}@test.local").status_code == 200

        blocked = register(anon, email="one-too-many@test.local")

        assert blocked.status_code == 429
        assert user_store.count() == SIGNUP_LIMIT

    def test_it_says_so_when_there_is_no_user_store(self, app):
        """Rule 4: unavailable is stated plainly, with a reason. A sign-up
        form that spins forever teaches an operator to distrust the page."""
        app.state.users = None

        response = register(TestClient(app))

        assert response.status_code == 503
        assert "System Health" in response.json()["detail"]


# ---------------------------------------------------------------------------
# the store, directly
# ---------------------------------------------------------------------------

class TestUserStoreDuplicates:
    def test_a_duplicate_email_raises_its_own_type(self, user_store):
        """A distinct exception because the endpoint has to answer it
        differently from a typo in a role name."""
        user_store.create_user("head@test.local", "Head", "admin", GOOD_PASSWORD)

        with pytest.raises(EmailTaken):
            user_store.create_user("HEAD@test.local", "Impostor", "it",
                                   GOOD_PASSWORD)

    def test_an_unknown_role_is_still_a_plain_value_error(self, user_store):
        with pytest.raises(ValueError) as caught:
            user_store.create_user("x@test.local", "X", "superuser", GOOD_PASSWORD)

        assert not isinstance(caught.value, EmailTaken)
