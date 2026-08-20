"""Password hashing. Argon2id, and nothing else, ever.

Three rules this module exists to make unbreakable:

1. **A plaintext password is never stored, logged, or returned.** It exists
   only as an argument to `hash_password` and `verify_password`.
2. **Verification is constant-time.** argon2's own `verify` handles that; the
   wrapper must not add a short-circuit that leaks whether a user exists.
3. **A wrong password and an unknown user look identical from outside**, and
   take the same time. `DUMMY_HASH` is what makes the second half true —
   without it, "no such user" returns instantly and "wrong password" takes
   ~50 ms, which is a free user-enumeration oracle on the login form.

Argon2id is settled for this project. bcrypt and PBKDF2 are not alternatives
to reopen: this is a system holding biometric data about children, and the
password store is the first thing an attacker reaches for.
"""

from __future__ import annotations

import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

log = logging.getLogger(__name__)

# Defaults are the argon2-cffi maintained profile, which tracks the OWASP
# guidance. Deliberately not tuned down: hashing is meant to be slow, and the
# only thing a faster setting buys is a faster offline crack.
_hasher = PasswordHasher()

#: A real argon2 hash of a value nobody can log in with. Verified against when
#: the username is unknown, so an attacker cannot tell "no such account" from
#: "wrong password" by timing the response.
DUMMY_HASH = _hasher.hash("vg-no-such-user-constant-time-padding")

#: Shortest password accepted. Not a strength policy — length is the only
#: property that reliably survives contact with real users, and a policy that
#: demands symbols mostly produces `Password1!`.
MIN_LENGTH = 12


class WeakPassword(ValueError):
    """Rejected before hashing. The message is safe to show a user."""


def hash_password(password: str) -> str:
    """Hash a new password. Raises `WeakPassword` if it is too short."""
    if password is None or len(password) < MIN_LENGTH:
        raise WeakPassword(
            f"Password must be at least {MIN_LENGTH} characters."
        )
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Is this the right password? Same cost whether the user exists or not.

    `stored_hash=None` means "no such user". It still runs a full verify
    against `DUMMY_HASH` before returning False, so the timing is
    indistinguishable from a wrong password on a real account.
    """
    candidate = stored_hash or DUMMY_HASH
    try:
        _hasher.verify(candidate, password or "")
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # A corrupted or hand-edited row. Refuse the login rather than
        # crashing the endpoint, and say so loudly - it is a data fault, not
        # a user mistake.
        log.error("stored password hash is not a valid argon2 hash; login refused")
        return False
    except Exception:
        log.exception("password verification failed")
        return False

    # A real hash matched, but the caller had no user. Never a successful login.
    return stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with weaker parameters than today's.

    Argon2's cost settings go up over time as hardware gets faster. A password
    hashed three years ago is still valid but under-protected; the login path
    is the only place the plaintext is available to upgrade it.
    """
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except Exception:
        return False
