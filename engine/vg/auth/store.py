"""Users and sessions, in the database. The first real access control here.

Before this, `web/src/app/AuthContext.tsx` did:

    localStorage.setItem('vg.role', 'admin')

That was the entire authorisation system. Typing that line into a browser
console made you an administrator of a system holding face data for children,
and the engine never knew a user existed at all.

**Sessions are opaque tokens in this table, not JWTs.** A JWT cannot be
withdrawn before it expires — you can only wait it out or rotate a global
secret and sign everybody out. When a laptop is lost or a member of staff
leaves, "that session is dead now" has to be true immediately, so the token is
a random string whose authority comes from a row that can be deleted.

Only the token's **hash** is stored. The database then holds nothing that can
be replayed if it is copied, which matters because the database is also the
backup, and the backup goes somewhere else.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from vg.auth.passwords import hash_password, needs_rehash, verify_password
from vg.db import connect

log = logging.getLogger(__name__)

ROLES = ("admin", "it")

#: The languages the console speaks. A **preference**, never a permission —
#: `auth/deps.py` decides what a caller may do by path and must not learn that
#: this exists. A display setting that could change access would be a second
#: permission system hiding behind an appearance control.
LANGUAGES = ("en", "ar")

#: The role an account gets when nobody chose one for it - self-registration
#: through `POST /auth/register`. Never taken from the request body: a
#: sign-up form that accepts a role is a sign-up form that hands out admin.
SELF_SIGNUP_ROLE = "it"

#: How long a session lasts without use. Short enough that an unattended
#: console in a school office is not a standing door; long enough that an
#: operator is not signing in during an incident.
SESSION_HOURS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login_at TEXT,
    disabled      INTEGER NOT NULL DEFAULT 0,
    language      TEXT NOT NULL DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);
"""


class EmailTaken(ValueError):
    """That address already has an account.

    A distinct type because the caller has to tell it apart from a typo in a
    role name, and because the sign-up endpoint must answer it differently
    from every other failure. The message is safe to show a user.
    """


@dataclass(frozen=True)
class User:
    """A person who can sign in. Never carries the password hash outward."""

    id: str
    email: str
    name: str
    role: str
    disabled: bool = False
    #: Which language this person reads the console in. Theirs alone — the
    #: gate station is shared, and a browser-wide setting would hand the next
    #: guard on shift the previous guard's language.
    language: str = "en"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    """SHA-256, not argon2, and on purpose.

    A session token is 256 bits of `secrets` output, so there is no dictionary
    to attack and no work factor worth paying. argon2 here would add ~50 ms to
    every authenticated request in the product for no security gain.
    """
    return sha256(token.encode("utf-8")).hexdigest()


class UserStore:
    """Users and sessions. One connection, guarded, like the other stores."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        self._conn: sqlite3.Connection = connect(self.database)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._ensure_columns()
            self._conn.commit()

    def _ensure_columns(self) -> None:
        """Add columns that arrived after a database was first created.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
        exists, so a school that has been running since before a column
        existed would never get it. Same approach as `events/vehicles.py`:
        ask what is there and add what is not. No version number to go stale.
        """
        for table, column, ddl in (
            ("app_user", "language", "TEXT NOT NULL DEFAULT 'en'"),
        ):
            existing = {r["name"] for r in
                        self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- users --------------------------------------------------------------

    def create_user(self, email: str, name: str, role: str, password: str) -> User:
        """Add an account.

        Raises `EmailTaken` for a duplicate address, `ValueError` for an
        unknown role, and `WeakPassword` for one that is too short. The
        password is hashed before the row is written and is never held
        anywhere else.
        """
        if role not in ROLES:
            raise ValueError(f"unknown role: {role!r}; expected one of {ROLES}")

        user = User(id=secrets.token_hex(8), email=email.strip(), name=name.strip(),
                    role=role)
        # Hash first. It is the slow, throwing step, and doing it outside the
        # lock keeps a sign-up storm from queueing behind ~50 ms of argon2
        # each while holding the only connection.
        password_hash = hash_password(password)
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO app_user (id, email, name, role, password_hash,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user.id, user.email, user.name, user.role,
                     password_hash, _now().isoformat()),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            # UNIQUE COLLATE NOCASE on email. Checking first and inserting
            # second would still race two simultaneous sign-ups; the
            # constraint is the only answer that cannot be interleaved.
            raise EmailTaken("That email already has an account.") from exc
        log.info("created %s account for %s", role, user.email)
        return user

    def users(self) -> list[User]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, email, name, role, disabled, language FROM app_user"
                " ORDER BY name"
            ).fetchall()
        return [
            User(id=r["id"], email=r["email"], name=r["name"], role=r["role"],
                 disabled=bool(r["disabled"]), language=r["language"])
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) AS n FROM app_user").fetchone()["n"])

    def set_disabled(self, user_id: str, disabled: bool) -> None:
        """Disable an account and drop its sessions in the same breath.

        Disabling somebody while leaving their session alive would let them
        keep working for up to SESSION_HOURS after being locked out, which is
        exactly the window the action exists to close.
        """
        with self._lock:
            self._conn.execute("UPDATE app_user SET disabled = ? WHERE id = ?",
                               (1 if disabled else 0, user_id))
            if disabled:
                self._conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
            self._conn.commit()

    # -- authentication -----------------------------------------------------

    def authenticate(self, email: str, password: str) -> User | None:
        """Check an email and password. None means no, without saying why.

        The caller gets one bit. Which half failed - unknown account, wrong
        password, disabled account - is deliberately not distinguishable, from
        the response or from its timing.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, name, role, password_hash, disabled, language"
                " FROM app_user WHERE email = ? COLLATE NOCASE",
                (email.strip(),),
            ).fetchone()

        stored = row["password_hash"] if row else None
        # Always run a verify, even with no row, so the timing does not say
        # whether the account exists.
        if not verify_password(stored, password):
            return None
        if row["disabled"]:
            return None

        if needs_rehash(stored):
            # The only moment the plaintext is in hand to upgrade the cost.
            with self._lock:
                self._conn.execute(
                    "UPDATE app_user SET password_hash = ? WHERE id = ?",
                    (hash_password(password), row["id"]),
                )
                self._conn.commit()
            log.info("upgraded password hash cost for %s", row["email"])

        with self._lock:
            self._conn.execute(
                "UPDATE app_user SET last_login_at = ? WHERE id = ?",
                (_now().isoformat(), row["id"]),
            )
            self._conn.commit()

        return User(id=row["id"], email=row["email"], name=row["name"],
                    role=row["role"], disabled=False, language=row["language"])

    def set_language(self, user_id: str, language: str) -> None:
        """Change one person's language. Theirs only.

        No caller may pass somebody else's id from the outside — the endpoint
        does not accept one. This takes an id because the store has no idea
        who is asking; the API layer is where "yourself" is decided.
        """
        if language not in LANGUAGES:
            raise ValueError(
                f"unknown language: {language!r}; expected one of {LANGUAGES}")
        with self._lock:
            self._conn.execute(
                "UPDATE app_user SET language = ? WHERE id = ?",
                (language, user_id),
            )
            self._conn.commit()

    # -- sessions -----------------------------------------------------------

    def start_session(self, user: User) -> tuple[str, datetime]:
        """Issue a token. Returned once, in plaintext, and never again.

        The row keeps only the hash, so a copy of the database cannot be
        turned back into a working session.
        """
        token = secrets.token_urlsafe(32)
        expires = _now() + timedelta(hours=SESSION_HOURS)
        with self._lock:
            self._conn.execute(
                "INSERT INTO session (token_hash, user_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (_token_hash(token), user.id, _now().isoformat(), expires.isoformat()),
            )
            self._conn.commit()
        return token, expires

    def user_for_token(self, token: str | None) -> User | None:
        """Who is this, if anyone. Expired and disabled both mean nobody."""
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT u.id, u.email, u.name, u.role, u.disabled, u.language,"
                " s.expires_at"
                " FROM session s JOIN app_user u ON u.id = s.user_id"
                " WHERE s.token_hash = ?",
                (_token_hash(token),),
            ).fetchone()
        if row is None:
            return None

        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires <= _now():
            # Tidy on read: an expired token proves nothing and the row is
            # only taking up space.
            self.end_session(token)
            return None
        if row["disabled"]:
            return None

        return User(id=row["id"], email=row["email"], name=row["name"],
                    role=row["role"], disabled=False, language=row["language"])

    def end_session(self, token: str | None) -> None:
        """Sign out. Idempotent — an unknown token is already signed out."""
        if not token:
            return
        with self._lock:
            self._conn.execute("DELETE FROM session WHERE token_hash = ?",
                               (_token_hash(token),))
            self._conn.commit()

    def end_all_sessions(self, user_id: str) -> int:
        """Sign a user out everywhere. For a lost laptop, or a leaver."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM session WHERE user_id = ?",
                                        (user_id,))
            self._conn.commit()
            return cursor.rowcount

    def purge_expired(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM session WHERE expires_at <= ?",
                                        (_now().isoformat(),))
            self._conn.commit()
            return cursor.rowcount
