"""Who is asking, and are they allowed. Deny by default.

The rule P2 sets: **every endpoint except `/healthz` returns 401 to an
unauthenticated caller.** Not "every endpoint we remembered to decorate" —
that is the same rule stated as a hope, and the one endpoint somebody forgets
is the one that leaks. So the check runs in middleware, over everything, and
the allowlist of public paths is short enough to read in one glance.

**Two ways to present a token, for one unavoidable reason.**

    Authorization: Bearer <token>    every normal API call
    vg_session cookie                the MJPEG camera streams

A camera stream is consumed by `<img src="/cameras/x/stream">`. A browser
cannot attach an Authorization header to an image tag, so a header-only design
would leave every live view either broken or public. The cookie is
HttpOnly + SameSite=Strict so page scripts cannot read it and another site
cannot ride it.

**Roles are checked on the server, always.** The console used to keep the role
in `localStorage`, where the user could edit it. Whatever the front end thinks
it is has no bearing on what the engine allows.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from vg.auth.store import User

log = logging.getLogger(__name__)

#: The name of the session cookie. HttpOnly, so JavaScript cannot read it.
COOKIE_NAME = "vg_session"

#: Paths reachable without signing in. Deliberately tiny.
#:
#: `/healthz` is the liveness probe: a load balancer cannot authenticate, and
#: it must be able to tell a running engine from a dead one. It returns
#: nothing about the site.
#:
#: `/auth/login` is how a token is obtained, so requiring one is circular.
#:
#: `/auth/register` is open sign-up, and it is the one entry here that is a
#: product decision rather than a structural necessity. It creates a working
#: account for anyone who can reach the console, always at `SELF_SIGNUP_ROLE`
#: ("it") and never at "admin". Everything an administrator can do stays
#: behind `ADMIN_PREFIXES`, so the worst a stranger gets is the read-only
#: half of the product - which on this system still includes camera views.
#: Closing it again is one line: delete it from this set.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/auth/login",
    "/auth/register",
})

#: Prefixes that are public. Kept separate from exact paths so a new route
#: cannot become public by accident through a loose prefix match.
PUBLIC_PREFIXES: tuple[str, ...] = ()


def is_public(path: str) -> bool:
    """Is this path reachable without a session?

    Exact match first. A trailing slash is normalised because FastAPI will
    happily route `/healthz/` to the same endpoint, and a check that misses
    that is a check with a hole in it.
    """
    normalised = path.rstrip("/") or "/"
    if normalised in PUBLIC_PATHS or path in PUBLIC_PATHS:
        return True
    return any(normalised.startswith(prefix) for prefix in PUBLIC_PREFIXES)


#: Path prefixes where **every** method is administrator-only.
#:
#: Enrolment writes a face into the gallery, which is the act that decides who
#: the system is able to name. Sources decide what it watches at all. The
#: constitution names both as admin-only, and neither is an IT-support task.
ADMIN_PREFIXES: tuple[str, ...] = (
    "/enrolment",
    "/sources",
    "/users",
)

#: Prefixes where reading is fine but changing anything is administrator-only.
#: An operator may look at the cameras and the zones; rearranging them is a
#: configuration change.
#:
#: `/people` is here rather than in ADMIN_PREFIXES because the directory is
#: data — an operator who cannot see who is enrolled cannot do their job.
#: Removing somebody is the opposite: their face data leaves the system, which
#: is precisely the kind of act the constitution wants gated and audited.
ADMIN_WRITE_PREFIXES: tuple[str, ...] = (
    "/cameras",
    "/people",
    "/zones",
    # A guard has to read the vehicle register to do their job — that is the
    # whole point of the gate log. A guard must not be able to un-blacklist a
    # car. One line decides both.
    "/vehicles",
    # Reading the school profile and the alert settings is anybody's job - a
    # guard should be able to see who is told about a knife, and the delivery
    # log. Changing who is told, or sending a test to somebody's phone, is an
    # administrator's (spec 013, P9-FR-032). Acknowledging a Home item lives
    # under /attention, which no prefix here touches.
    "/settings",
)

#: Narrower than `ADMIN_WRITE_PREFIXES`, and checked first.
#:
#: **The only writes on this system a guard may make.** Everything under
#: `/vehicles` is administrator-only to write, which is right for the register
#: — a guard must not be able to un-blacklist a car. But clearing an alert is
#: not changing the register: it is the person on duty saying "I have dealt
#: with this", which is the entire purpose of an alert that waits for a human.
#: Requiring an administrator would mean alerts pile up all shift at a gate
#: staffed by guards, and an alert nobody can clear stops being read.
#:
#: The dismissal is audited and names the account, so "a guard did this" is
#: recoverable. What a guard still cannot do is act on the alert: registering
#: a car or renewing a permit are register writes and stay admin-only.
#:
#: Keep this list tiny, and never widen a prefix here to cover a sibling.
OPERATOR_WRITE_PREFIXES: tuple[str, ...] = (
    "/vehicles/alerts",
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def requires_admin(method: str, path: str) -> bool:
    """Does this request need an administrator?

    Decided from the path, in one place, rather than from a decorator on each
    endpoint. A decorator is the same rule written as a hope: the endpoint
    somebody forgets is the one that lets an IT account enrol a face, and
    nothing about the code would look wrong.

    The cost is that a new endpoint under one of these prefixes is admin-only
    by default. That is the right way round: a new enrolment endpoint being
    accidentally locked is a bug report, and a new one being accidentally open
    is an incident.
    """
    normalised = path.rstrip("/") or "/"
    if any(normalised == p or normalised.startswith(p + "/")
           for p in ADMIN_PREFIXES):
        return True
    if method.upper() in SAFE_METHODS:
        return False
    # Checked BEFORE the admin-write rule, so the narrower prefix wins. The
    # order is the whole mechanism: `/vehicles/alerts/...` also matches
    # `/vehicles`, and testing the broader rule first would make this
    # unreachable while still looking correct.
    if any(normalised == p or normalised.startswith(p + "/")
           for p in OPERATOR_WRITE_PREFIXES):
        return False
    return any(normalised == p or normalised.startswith(p + "/")
               for p in ADMIN_WRITE_PREFIXES)


def token_from(request: Request) -> str | None:
    """The bearer token, from the header or the stream cookie."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    return request.cookies.get(COOKIE_NAME)


def user_from(request: Request) -> User | None:
    """Resolve the caller, or None. Never raises."""
    store = getattr(request.app.state, "users", None)
    if store is None:
        return None
    try:
        return store.user_for_token(token_from(request))
    except Exception:
        # A broken session table must not turn every request into a 500. It
        # turns them into 401s, which is the safe direction to fail.
        log.exception("session lookup failed")
        return None


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------

def current_user(request: Request) -> User:
    """The signed-in user, or 401.

    Reads what the middleware already resolved rather than looking the token
    up a second time — one database read per request, not two.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to use this.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Admin only.

    Enrolment and camera changes live behind this. Enrolment writes a face
    into the gallery, which is the act that decides who the system can name;
    camera changes decide what it watches at all. Neither is an IT-support
    task, and the constitution names both as admin-only.

    403, not 404: the caller is authenticated, so hiding the endpoint's
    existence buys nothing and an honest refusal is easier to support.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This needs an administrator account.",
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
