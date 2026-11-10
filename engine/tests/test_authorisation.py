"""Nobody gets in without signing in, and editing the browser achieves nothing.

P2. `docs/PLAN.md` says the phase is done when "every endpoint except
`/healthz` returns 401 unauthenticated, and editing localStorage achieves
nothing". Both halves are here.

What this replaces. The whole authorisation system was one line in
`web/src/app/AuthContext.tsx`:

    localStorage.setItem('vg.role', 'admin')

Typing that into a browser console made you an administrator of a system
holding face data for children. The engine never knew a user existed: there
was no users table, no password anywhere, and not one endpoint that asked who
was calling. Anyone who could reach the page could read every register, watch
every camera, and enrol a face.

The most valuable test in this file is `test_every_route_refuses_an_anonymous
_caller`, because it is the one that keeps working as the product grows. It
walks the app's own route table, so an endpoint added next year is covered the
day it is written, without anybody remembering to come back here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import deps as auth_deps  # noqa: E402

# Methods that are safe to probe. A route table walk must not POST to
# something that mutates: the point is what the door does, not what is behind
# it, and a 401 arrives before any handler runs.
PROBE_METHOD = "GET"


@pytest.fixture
def app(user_store):
    from vg.api import app as app_module

    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


@pytest.fixture
def anon(app):
    """A caller with no session at all."""
    return TestClient(app)


def routes(app) -> list[str]:
    """Every GET path the app serves, minus the ones taking parameters.

    Parameterised paths are skipped only because a placeholder would 404 or
    422 before the auth check is interesting; the middleware does not read the
    path beyond the public list, so the fixed paths prove the behaviour.
    """
    found = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if PROBE_METHOD in methods and "{" not in path:
            found.append(path)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# the front door
# ---------------------------------------------------------------------------

class TestAnonymousIsRefused:
    def test_there_are_routes_to_check(self, app):
        """Guard the guard: an empty route list must not read as success."""
        assert len(routes(app)) >= 10, routes(app)

    def test_every_route_refuses_an_anonymous_caller(self, app, anon):
        """The rule, over the app's own route table.

        Deliberately not a hand-written list. A list goes stale the first time
        somebody adds an endpoint, and the endpoint nobody remembered is
        exactly the one that leaks.
        """
        allowed = []
        for path in routes(app):
            if auth_deps.is_public(path):
                continue
            response = anon.get(path)
            if response.status_code not in (401, 503):
                allowed.append(f"{path} -> {response.status_code}")

        assert not allowed, (
            "these endpoints answered an anonymous caller: " + ", ".join(allowed)
        )

    def test_healthz_is_public(self, anon):
        """The one exception, and it says nothing about the site."""
        response = anon.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        # No school name, no camera count, no register. A liveness probe that
        # leaks the site is not a liveness probe.
        assert set(body) <= {"ok", "version"}, body

    def test_login_is_reachable_without_a_session(self, anon):
        """Requiring a token to get a token would be a locked door with the
        key inside. It is reachable, and it still refuses bad credentials."""
        response = anon.post("/auth/login",
                             json={"email": "nobody@test.local", "password": "x"})

        assert response.status_code == 401

    def test_a_made_up_token_is_refused(self, anon):
        response = anon.get("/site", headers={"Authorization": "Bearer not-a-real-token"})

        assert response.status_code == 401

    def test_a_made_up_cookie_is_refused(self, anon):
        anon.cookies.set(auth_deps.COOKIE_NAME, "not-a-real-token")
        response = anon.get("/site")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# signing in
# ---------------------------------------------------------------------------

class TestSignIn:
    def test_the_right_password_returns_a_session(self, app, anon, user_store):
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")

        response = anon.post("/auth/login", json={
            "email": "head@test.local", "password": "a-long-enough-test-password"})

        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["user"]["role"] == "admin"
        assert body["user"]["initials"] == "HT"

    def test_the_password_never_comes_back(self, app, anon, user_store):
        """Not in the account, not anywhere in the response."""
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")

        response = anon.post("/auth/login", json={
            "email": "head@test.local", "password": "a-long-enough-test-password"})

        assert "a-long-enough-test-password" not in response.text
        assert "password" not in response.json()["user"]

    def test_a_wrong_password_and_an_unknown_user_look_identical(self, app, anon,
                                                                 user_store):
        """No user enumeration.

        A school's email addresses are guessable. If "no such account" and
        "wrong password" differ, the login form becomes a way to confirm who
        works there.
        """
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")

        wrong = anon.post("/auth/login", json={
            "email": "head@test.local", "password": "wrong-password-entirely"})
        unknown = anon.post("/auth/login", json={
            "email": "ghost@test.local", "password": "wrong-password-entirely"})

        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_a_session_works_after_signing_in(self, app, anon, user_store):
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")
        token = anon.post("/auth/login", json={
            "email": "head@test.local",
            "password": "a-long-enough-test-password"}).json()["token"]

        response = anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["email"] == "head@test.local"

    def test_signing_out_kills_the_session_server_side(self, app, anon, user_store):
        """The row goes, not just the cookie.

        Clearing the cookie alone leaves a token that still works if it was
        ever captured. When a laptop is lost, "that session is dead" has to be
        true on the server.
        """
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")
        token = anon.post("/auth/login", json={
            "email": "head@test.local",
            "password": "a-long-enough-test-password"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert anon.get("/auth/me", headers=headers).status_code == 200
        anon.post("/auth/logout", headers=headers)

        assert anon.get("/auth/me", headers=headers).status_code == 401

    def test_a_disabled_account_cannot_sign_in_or_stay_in(self, app, anon, user_store):
        """Disabling ends the sessions too.

        Otherwise somebody locked out at 9am keeps working until their token
        expires, which is the whole window the action exists to close.
        """
        user = user_store.create_user("leaver@test.local", "A Leaver", "it",
                                      "a-long-enough-test-password")
        token = anon.post("/auth/login", json={
            "email": "leaver@test.local",
            "password": "a-long-enough-test-password"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert anon.get("/auth/me", headers=headers).status_code == 200

        user_store.set_disabled(user.id, True)

        assert anon.get("/auth/me", headers=headers).status_code == 401
        assert anon.post("/auth/login", json={
            "email": "leaver@test.local",
            "password": "a-long-enough-test-password"}).status_code == 401


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

class TestRolesAreServerSide:
    def test_the_role_comes_from_the_server_not_the_client(self, app, anon,
                                                           user_store):
        """The localStorage hole, closed.

        The console used to keep the role in localStorage and believe it.
        Here the client claims admin every way it can; the server reports what
        the account actually is.
        """
        user_store.create_user("it@test.local", "IT Support", "it",
                               "a-long-enough-test-password")
        token = anon.post("/auth/login", json={
            "email": "it@test.local",
            "password": "a-long-enough-test-password"}).json()["token"]

        response = anon.get("/auth/me", headers={
            "Authorization": f"Bearer {token}",
            "X-Role": "admin",          # a client claim
            "X-User-Role": "admin",
        })

        assert response.json()["role"] == "it"

    def test_a_token_cannot_be_edited_into_a_better_one(self, app, anon, user_store):
        """The token carries no claims, so there is nothing in it to forge.

        Its authority is a row in the database. Changing a character makes it
        an unknown token, not an admin one - which is the argument for opaque
        tokens over JWTs on a system like this.
        """
        user_store.create_user("it@test.local", "IT Support", "it",
                               "a-long-enough-test-password")
        token = anon.post("/auth/login", json={
            "email": "it@test.local",
            "password": "a-long-enough-test-password"}).json()["token"]

        tampered = ("A" if token[0] != "A" else "B") + token[1:]

        assert anon.get("/auth/me",
                        headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


class TestPublicListIsTight:
    """The allowlist is the whole attack surface. It should be hard to widen."""

    def test_only_the_three_agreed_paths_are_public(self):
        """Three, and each one was argued for.

        `/healthz` a load balancer cannot authenticate. `/auth/login` is how
        a token is obtained. `/auth/register` is open sign-up - a product
        decision taken knowingly, covered by `test_registration.py`, and the
        only one here that could be removed without breaking anything
        structural.
        """
        assert auth_deps.PUBLIC_PATHS == frozenset({
            "/healthz", "/auth/login", "/auth/register",
        }), (
            "adding a public path is a security decision - if it is deliberate, "
            "update this test and say why in the commit"
        )

    def test_a_trailing_slash_does_not_open_a_route(self):
        """`/site/` routes to `/site`. A check that misses that has a hole."""
        assert not auth_deps.is_public("/site/")
        assert not auth_deps.is_public("/attendance/")
        assert auth_deps.is_public("/healthz/")

    def test_a_lookalike_path_is_not_public(self):
        """Prefix matching must not make `/healthz-internal` public."""
        assert not auth_deps.is_public("/healthzz")
        assert not auth_deps.is_public("/healthz-internal")
        assert not auth_deps.is_public("/auth/login-as-admin")


# ---------------------------------------------------------------------------
# the role x endpoint matrix
# ---------------------------------------------------------------------------

class TestAdminOnlyEndpoints:
    """Enrolment and configuration are administrator-only, server-side.

    Enrolment writes a face into the gallery — the act that decides who the
    system is able to name. Sources decide what it watches at all. An IT
    support account can look at the system; it cannot change who it knows.
    """

    @pytest.fixture
    def it_client(self, app, user_store):
        user = user_store.create_user("it@test.local", "IT Support", "it",
                                      "a-long-enough-test-password")
        token, _ = user_store.start_session(user)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    @pytest.fixture
    def admin_client(self, app, user_store):
        user = user_store.create_user("head@test.local", "Head Teacher", "admin",
                                      "a-long-enough-test-password")
        token, _ = user_store.start_session(user)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    @pytest.mark.parametrize("method, path", [
        ("post", "/enrolment/sessions"),
        ("post", "/sources"),
        ("post", "/sources/scan"),
        ("post", "/sources/dvr"),
        ("delete", "/sources/anything"),
        ("patch", "/zones/z1"),
        # Recording left this list in spec 022: an IT account may start and
        # stop one. Changing the camera itself is still refused:
        ("patch", "/cameras/c1"),
    ])
    def test_it_support_is_refused(self, it_client, method, path):
        """403, not 401. They are signed in; this is simply not theirs."""
        # DELETE takes no body in httpx's client, and none of these need one:
        # the gate answers before the handler ever reads the request.
        call = getattr(it_client, method)
        response = call(path) if method == "delete" else call(path, json={})

        assert response.status_code == 403, (
            f"{method.upper()} {path} let an IT account through "
            f"({response.status_code})"
        )

    @pytest.mark.parametrize("path", [
        "/site", "/system/health", "/cameras", "/zones",
    ])
    def test_it_support_can_still_read(self, it_client, path):
        """Read access is the job. Locking it out would make the role useless."""
        response = it_client.get(path)

        assert response.status_code == 200, f"GET {path} -> {response.status_code}"

    def test_an_admin_is_not_refused_by_the_role_gate(self, admin_client):
        """An admin gets past the gate.

        The status may be anything the handler decides - 201, 404, 422 - but
        it must not be the 403 the gate produces.
        """
        response = admin_client.post("/enrolment/sessions", json={})

        assert response.status_code != 403


class TestAdminPathRule:
    """The rule itself, without HTTP in the way."""

    @pytest.mark.parametrize("path", [
        "/enrolment", "/enrolment/sessions", "/enrolment/sessions/abc/commit",
        "/sources", "/sources/scan", "/users",
    ])
    def test_reading_these_is_admin_only_too(self, path):
        """Not just writing. The enrolment queue names children."""
        assert auth_deps.requires_admin("GET", path)

    @pytest.mark.parametrize("path", ["/cameras", "/zones", "/cameras/c1"])
    def test_reading_cameras_and_zones_is_open_to_any_signed_in_user(self, path):
        assert not auth_deps.requires_admin("GET", path)

    @pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
    def test_changing_cameras_and_zones_is_admin_only(self, method):
        assert auth_deps.requires_admin(method, "/cameras/c1")
        assert auth_deps.requires_admin(method, "/zones/z1")

    @pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
    def test_changing_who_is_alerted_is_admin_only(self, method):
        """Spec 013: recipients, rules and test sends are an administrator's."""
        assert auth_deps.requires_admin(method, "/settings/alerts/rules/weapon")
        assert auth_deps.requires_admin(method, "/settings/alerts/recipients/r1")
        assert auth_deps.requires_admin(method, "/settings/alerts/recipients/r1/test")

    @pytest.mark.parametrize("path", ["/settings/alerts", "/settings/alerts/deliveries",
                                      "/settings/school"])
    def test_reading_the_settings_is_open_to_any_signed_in_user(self, path):
        assert not auth_deps.requires_admin("GET", path)

    def test_acknowledging_a_home_item_is_anybodys(self):
        """The one alert write a guard makes, as clearing a gate alert is."""
        assert not auth_deps.requires_admin("POST", "/attention/weapon:s1/ack")

    def test_a_lookalike_prefix_is_not_caught(self):
        """`/sources` must not make `/sourcesomething` admin-only, and more
        importantly the reverse: a real prefix must not be escapable."""
        assert not auth_deps.requires_admin("GET", "/sourcesomething")
        assert auth_deps.requires_admin("GET", "/sources/x")

    def test_a_trailing_slash_does_not_escape_the_rule(self):
        assert auth_deps.requires_admin("GET", "/enrolment/")
        assert auth_deps.requires_admin("POST", "/sources/")


class TestStationPaths:
    """Spec 025: drawing a station is setup; acknowledging an absence is not."""

    @pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
    def test_drawing_editing_and_removing_are_admin_only(self, method):
        assert auth_deps.requires_admin(method, "/stations")
        assert auth_deps.requires_admin(method, "/stations/st1")

    @pytest.mark.parametrize("path", ["/stations", "/stations/face-reach",
                                      "/stations/st1"])
    def test_reading_is_open_to_every_signed_in_user(self, path):
        assert not auth_deps.requires_admin("GET", path)

    def test_acknowledging_is_open_to_it_and_admin(self):
        assert not auth_deps.requires_admin("POST", "/stations/st1/acknowledge")

    @pytest.mark.parametrize("method,path", [
        ("POST", "/stations/st1/acknowledge/extra"),
        ("PATCH", "/stations/st1"),
        ("PATCH", "/stations/st1/acknowledge"),
        ("POST", "/stations/st1/other"),
        ("POST", "/stations"),
    ])
    def test_the_acknowledge_pattern_is_anchored(self, method, path):
        assert auth_deps.requires_admin(method, path)

    def test_zone_writes_stay_admin_only(self):
        for method in ("POST", "PATCH", "DELETE"):
            assert auth_deps.requires_admin(method, "/zones")
            assert auth_deps.requires_admin(method, "/zones/z1")


# ---------------------------------------------------------------------------
# "editing localStorage achieves nothing"
# ---------------------------------------------------------------------------

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


class TestTheConsoleStoresNoRole:
    """The second half of P2's done criterion, checked in the source.

    The console used to keep the role in localStorage and believe it on the
    next load. The engine now decides, but the front end could quietly
    reintroduce the habit — a cached role "to avoid a flash of the login
    form" would look like a performance fix and would restore the hole.

    A source check, because there is no runtime state that reveals it: a
    console reading a cached role behaves identically to one asking the
    server, right up until somebody edits the cache.
    """

    def test_no_role_is_written_to_browser_storage(self):
        offenders = []
        for path in sorted(WEB.rglob("*.ts")) + sorted(WEB.rglob("*.tsx")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("*") or stripped.startswith("//"):
                    continue  # a comment describing the old bug is fine
                if "localStorage" not in line and "sessionStorage" not in line:
                    continue
                if any(word in line for word in ("role", "Role", "account", "Account",
                                                 "token", "Token", "auth", "Auth")):
                    offenders.append(f"{path.name}:{number} {stripped}")

        assert not offenders, (
            "the console is storing identity in the browser again: " + "; ".join(offenders)
        )

    def test_sign_in_takes_credentials_not_a_role(self):
        """`signIn('admin')` was the bug. It must take an email and password."""
        source = (WEB / "app" / "AuthContext.tsx").read_text(encoding="utf-8")

        assert "signIn: (email: string, password: string)" in source, (
            "AuthContext.signIn must take credentials, not a role"
        )

    def test_the_login_form_has_no_credentials_in_it(self):
        """A real address and password were typed into this file."""
        source = (WEB / "pages" / "Login.tsx").read_text(encoding="utf-8")

        assert "demo1234" not in source
        assert "@gmail.com" not in source
        assert "any password is accepted" not in source

    def test_the_console_requires_a_session_before_rendering(self):
        source = (WEB / "app" / "routes.tsx").read_text(encoding="utf-8")

        assert "RequireSignIn" in source, (
            "the app shell must be behind a sign-in guard"
        )


# ---------------------------------------------------------------------------
# the camera streams
# ---------------------------------------------------------------------------

class TestStreamsAreReachableFromAnImgTag:
    """A live view is `<img src=...>`, and an image tag cannot send a header.

    P2 put every endpoint behind sign-in, which was right, and quietly turned
    every camera tile black. The stream request arrived with no credentials,
    came back 401, and the browser drew nothing. Detection carried on working
    the whole time — it happens on the server and never touches the browser —
    so it looked like a video fault rather than an auth one.

    The cookie is the only credential an image tag can carry, and it is
    `SameSite=Strict`, so it is only sent when the engine and the page share an
    origin. The dev server proxies the engine to make that true; production
    serves both from one origin for the same reason.
    """

    def test_a_cookie_alone_is_enough(self, app, anon, user_store):
        """No Authorization header anywhere in this request."""
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")
        login = anon.post("/auth/login", json={
            "email": "head@test.local", "password": "a-long-enough-test-password"})

        assert auth_deps.COOKIE_NAME in login.cookies, (
            "sign-in must set the session cookie, or the camera streams cannot "
            "authenticate at all"
        )
        # The TestClient keeps the cookie; this request carries nothing else.
        response = anon.get("/site")

        assert response.status_code == 200

    def test_the_cookie_is_not_readable_by_page_scripts(self, app, anon, user_store):
        """HttpOnly. A token a script can read is a token a script can steal."""
        user_store.create_user("head@test.local", "Head Teacher", "admin",
                               "a-long-enough-test-password")
        login = anon.post("/auth/login", json={
            "email": "head@test.local", "password": "a-long-enough-test-password"})

        header = login.headers.get("set-cookie", "").lower()
        assert "httponly" in header, header
        assert "samesite=strict" in header, header

    def test_the_web_app_talks_to_one_origin_by_default(self):
        """Same-origin is what makes SameSite=Strict workable.

        A default pointing at another origin makes JSON work and live views
        black — the most confusing possible half-failure, because everything
        looks fine except the pictures.
        """
        http_ts = (Path(__file__).resolve().parents[2] / "web" / "src"
                   / "services" / "http.ts").read_text(encoding="utf-8")

        assert "import.meta.env.VITE_API_BASE ?? ''" in http_ts, (
            "the API base must default to same-origin; pointing it at the "
            "engine directly stops the camera streams authenticating"
        )

    def test_the_dev_server_proxies_the_camera_paths(self):
        config = (Path(__file__).resolve().parents[2] / "web"
                  / "vite.config.ts").read_text(encoding="utf-8")

        for path in ("'/cameras'", "'/auth'", "'/site'"):
            assert path in config, f"vite proxy is missing {path}"


class TestRequestsAreActuallySent:
    """A relative API base must still produce a usable URL.

    Making the API base empty (so requests are same-origin and the session
    cookie reaches the camera streams) turned `BASE + path` into a relative
    path like "/auth/login". `new URL()` throws a TypeError on a relative URL
    with no base to resolve it against.

    That throw happened inside the request's try block, was neither an
    ApiError nor an AbortError, and fell through to the branch that reports
    "Cannot reach the engine. Is it running?". The engine was running and
    answering; no request was ever made. Every call in the app failed this
    way, and the message sent the reader to inspect the one healthy part.

    The lesson worth keeping: an error handler that names a probable cause is
    only helpful while that cause is the real one. This one was confidently
    wrong, which is worse than a generic message would have been.
    """

    def test_the_url_builder_resolves_relative_paths(self):
        http_ts = (Path(__file__).resolve().parents[2] / "web" / "src"
                   / "services" / "http.ts").read_text(encoding="utf-8")

        assert "new URL(BASE + path, window.location.origin)" in http_ts, (
            "buildUrl must pass a base to new URL(). With a same-origin API "
            "base, `new URL('/auth/login')` throws and every request dies "
            "before it is sent."
        )

    def test_a_bare_new_url_is_not_reintroduced(self):
        http_ts = (Path(__file__).resolve().parents[2] / "web" / "src"
                   / "services" / "http.ts").read_text(encoding="utf-8")

        assert "new URL(BASE + path)" not in http_ts, (
            "new URL() without a base throws on a relative path"
        )
