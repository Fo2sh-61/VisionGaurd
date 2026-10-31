"""TEMPORARY - development only. DEV-SIGNIN.

Mohamed will remove this before VisionGuard goes to a school (his call,
2026-09-11). To remove it, `git grep -niE "dev.?sign.?in"` lists every file
and line that belongs to it - every spelling, `DevSignIn` to `VG_DEV_SIGNIN`.

**Developer sign-in.** With `VG_DEV_SIGNIN=admin` (or `it`), a request from
this computer that carries no session is served as a built-in account,
"Developer (dev sign-in)", so the console opens without a password. It exists
so Claude - which will not type anybody's password - can open the console in
a browser and check a page by eye instead of handing every check to a person.

A console of children's faces with no password is the worst thing this engine
could serve, so it is fenced:

* **Off unless asked for.** Unset, nothing here does anything.
* **Refuses to start** with `VG_STRICT=1` - the setting CI and the deployment
  machine run under - under the cloud trial's `profile: cloud`, which has a
  public address, and with any value but `admin` or `it`.
* **This computer only.** The connection must come from a loopback address
  *and* name a loopback host. The second check is what stops a proxy: nginx in
  front of the engine connects from 127.0.0.1 too, but it forwards the
  school's hostname. What still gets through is a proxy on this computer that
  is itself open to the network and passes a faked Host header on -
  `vite --host` is one. Never combine the two.
* **Nothing written.** No account row, no session row. The account is built
  in memory per request, and the audit names it, never a real person. Its
  language lives in memory until the engine stops.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request

from vg.auth.store import ROLES, User

log = logging.getLogger(__name__)

ENV = "VG_DEV_SIGNIN"

NAME = "Developer (dev sign-in)"


@dataclass(frozen=True)
class DevUser(User):
    """The built-in account. A type of its own, so nothing compares ids."""

    @property
    def initials(self) -> str:
        # "Developer (dev sign-in)" would otherwise come out as "D(".
        return "DV"


def role_from_env(profile: str = "") -> str | None:
    """The role to sign callers in as, or None when this is off.

    Raises rather than degrading. An engine asked for a password-less console
    somewhere that is not safe must not start at all - a refusal is noticed at
    once, and a console that quietly let everyone in would not be.
    """
    raw = os.getenv(ENV, "").strip().lower()
    if not raw:
        return None
    if raw not in ROLES:
        raise RuntimeError(
            f"{ENV}={raw!r} is not a role. Use one of {', '.join(ROLES)}, "
            "or leave it unset.")
    if os.getenv("VG_STRICT") == "1":
        raise RuntimeError(
            f"{ENV} is set together with VG_STRICT=1, the CI and deployment "
            "setting. Developer sign-in is for a developer's own computer, so "
            "the engine will not start like this.")
    if profile == "cloud":
        raise RuntimeError(
            f"{ENV} is set under the cloud profile, which is reached through "
            "a public address. Developer sign-in is for a developer's own "
            "computer, so the engine will not start like this.")
    log.warning(
        "DEVELOPER SIGN-IN IS ON (%s): anyone using this computer is signed "
        "in as %r without a password. Development only.", raw, NAME)
    return raw


def user_for(request: Request) -> DevUser | None:
    """The built-in account for this request, or None."""
    role = getattr(request.app.state, "dev_signin", None)
    if role is None or not _from_this_computer(request):
        return None
    return DevUser(
        id="dev-signin", email="dev-signin@localhost", name=NAME, role=role,
        language=getattr(request.app.state, "dev_signin_language", "en"),
    )


def is_dev(user: User) -> bool:
    return isinstance(user, DevUser)


def remember_language(request: Request, user: User, language: str) -> None:
    """Keep the built-in account's language, which has no row to live in."""
    if is_dev(user):
        request.app.state.dev_signin_language = language


def _from_this_computer(request: Request) -> bool:
    """A loopback connection naming a loopback host. Both, every time."""
    client = request.client.host if request.client else ""
    try:
        host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
    except ValueError:
        # "[::1" and friends. A header nobody can parse proves nothing.
        return False
    return _is_loopback(client) and (host == "localhost" or _is_loopback(host))


def _is_loopback(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback
