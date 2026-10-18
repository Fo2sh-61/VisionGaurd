"""Lift a sign-in lock, at the workstation itself (spec 020).

    python engine/tools/unlock_account.py head@school.edu

Five wrong passwords lock an account for fifteen minutes. An administrator can
lift a lock from the Users page; this is for when no administrator can sign in
- the only administrator is the one locked out. It needs a shell on the
workstation, the same barrier as `create_user.py`.

The lock lifts at once; the engine reads the same table on the next sign-in.
The audit lives in the engine's memory until spec 018 saves it, so a command
run outside the engine cannot add to it: this prints what it did instead, and
the Users page's unlock (which is audited) is the way when one is possible.
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None, users=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email", help="the address the account signs in with")
    args = parser.parse_args(argv)

    from vg.auth.store import UserStore, email_key

    store = users
    if store is None:
        database = _database()
        print(f"\n  database  {database}")
        store = UserStore(database)

    key = email_key(args.email)
    if store.unlock(args.email):
        print(f"  unlocked  {key} (workstation). It can sign in again now.\n")
    else:
        print(f"  {key} was not locked. Nothing changed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
