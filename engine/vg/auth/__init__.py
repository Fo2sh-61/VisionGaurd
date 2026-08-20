"""Authentication and authorisation.

`passwords` hashes, `store` holds users and sessions, `deps` is what endpoints
depend on. Nothing outside this package may decide who somebody is.
"""

from vg.auth.store import ROLES, SESSION_HOURS, User, UserStore

__all__ = ["ROLES", "SESSION_HOURS", "User", "UserStore"]
