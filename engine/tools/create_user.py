"""Create an account. The only way the first administrator comes to exist.

    python engine/tools/create_user.py
    python engine/tools/create_user.py --email head@school.edu --role admin

**Why a command and not a setup page.** A "create the first admin" endpoint has
to be reachable by someone with no account, which means it is reachable by
anyone until it is used. On a system holding face data for children, a window
like that is not worth the convenience — and it is exactly the window that gets
left open on a machine somebody set up months ago and forgot.

Running this needs a shell on the engine's own machine, which is a meaningful
barrier and one nobody can reach across the network.

The password is read without echoing and is never written to the shell history,
the log, or the database — only its argon2 hash is stored.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))


def _database() -> Path:
    from vg import config as vgconfig

    try:
        cfg = vgconfig.load()
        raw = str(cfg.storage.database_url).replace("sqlite:///", "")
        path = Path(raw)
        return path if path.is_absolute() else vgconfig.REPO_DIR / path
    except Exception:
        return vgconfig.REPO_DIR / "engine" / "data" / "visionguard.db"


def main(argv: list[str] | None = None) -> int:
    from vg.auth.passwords import MIN_LENGTH, WeakPassword
    from vg.auth.store import ROLES, UserStore

    parser = argparse.ArgumentParser(description="Create a VisionGuard account.")
    parser.add_argument("--email")
    parser.add_argument("--name")
    parser.add_argument("--role", choices=ROLES)
    parser.add_argument("--list", action="store_true", help="show existing accounts")
    # For a start script with no one at the keyboard (the cloud trial reads
    # it from a Kaggle secret). The NAME of a variable, never the password:
    # an argument would sit in the process list and the shell history.
    parser.add_argument("--password-env", metavar="NAME",
                        help="read the password from this environment variable")
    args = parser.parse_args(argv)

    database = _database()
    print(f"\n  database  {database}")
    store = UserStore(database)

    if args.list:
        users = store.users()
        if not users:
            print("  no accounts yet\n")
            return 0
        print(f"\n  {len(users)} account(s):\n")
        for user in users:
            state = " (disabled)" if user.disabled else ""
            print(f"    {user.role:<6} {user.email:<32} {user.name}{state}")
        print()
        return 0

    existing = store.count()
    print(f"  accounts  {existing}")
    if existing == 0:
        print("\n  This will be the first account, so it should be an administrator.")

    email = args.email or input("\n  email     ").strip()
    if not email or "@" not in email:
        print("  that does not look like an email address", file=sys.stderr)
        return 1

    name = args.name or input("  full name ").strip()
    if not name:
        print("  a name is required", file=sys.stderr)
        return 1

    role = args.role
    if not role:
        default = "admin" if existing == 0 else "it"
        answer = input(f"  role {ROLES} [{default}] ").strip() or default
        role = answer
    if role not in ROLES:
        print(f"  unknown role {role!r}; expected one of {ROLES}", file=sys.stderr)
        return 1

    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            print(f"\n  {args.password_env} is not set or is empty", file=sys.stderr)
            return 1
    else:
        print(f"\n  Password must be at least {MIN_LENGTH} characters. It is not echoed.")
        password = getpass.getpass("  password  ")
        if password != getpass.getpass("  again     "):
            print("\n  those did not match", file=sys.stderr)
            return 1

    try:
        user = store.create_user(email=email, name=name, role=role, password=password)
    except WeakPassword as exc:
        print(f"\n  {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # A duplicate email lands here, which is the common case and worth
        # saying plainly rather than as a UNIQUE constraint error.
        print(f"\n  could not create the account: {exc}", file=sys.stderr)
        return 1

    print(f"\n  created {user.role} account for {user.email}")
    print("  restart the engine if it is running, then sign in.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
