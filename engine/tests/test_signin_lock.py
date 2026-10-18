"""Sign-in lockout (spec 020 P10-FR-118, SC-109; tasks T008-T011).

Five wrong passwords for one account within 15 minutes lock it for 15 minutes.
While locked even the right password is refused, and more attempts do not
extend the lock. The count is per account, with the email matched exactly the
way sign-in matches it, and kept whether or not the account exists, so "locked"
never tells anyone which addresses are real. One address failing on many
accounts is slowed down too. Locks and unlocks are audited, before the answer,
with the address the attempts came from.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.api import app as app_module  # noqa: E402
from vg.api.live import LiveStore  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth.store import UserStore, email_key  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402

PASSWORD = "a-long-enough-test-password"
WRONG = "not-the-password-at-all"
NETBIRD = ("100.81.4.7", 50000)
LAN = ("192.168.1.20", 50000)
T0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def users(tmp_path):
    store = UserStore(tmp_path / "auth.db")
    yield store
    store.close()


@pytest.fixture
def live(users):
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]), users=users)
    app_module.set_store(store)
    yield store
    app_module.set_store(MockStore())


@pytest.fixture
def app(users, live):
    application = app_module.create_app()
    application.state.users = users
    return application


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def audit(live, action):
    return [e for e in live.audit(500) if e.action == action]


# --- the store ---------------------------------------------------------------

class TestTheKey:
    def test_spaces_and_capitals_are_one_account(self):
        assert email_key("  Admin@X.com ") == email_key("admin@x.com") == "admin@x.com"

    def test_only_ascii_is_lower_cased_as_sign_in_does(self):
        # SQLite's NOCASE folds A-Z only, so sign-in treats É and é as
        # different addresses; the lock must count them apart too.
        assert email_key("ÉLodie@X.com") == "Élodie@x.com"

    def test_cut_to_the_longest_address(self):
        assert len(email_key("a" * 400)) == 254


class TestTheLockTable:
    def lock_after(self, users, email, n, start=T0, step=timedelta(seconds=10)):
        result = None
        for i in range(n):
            result = users.record_failure(email, "100.81.4.7", attempts=5,
                                          window=timedelta(minutes=15),
                                          lock_for=timedelta(minutes=15),
                                          now=start + i * step)
        return result

    def test_the_fifth_failure_locks_for_fifteen_minutes(self, users):
        assert self.lock_after(users, "a@x.com", 4) is None
        assert users.locked_until("a@x.com", now=T0 + timedelta(minutes=1)) is None
        until = self.lock_after(users, "a@x.com", 1, start=T0 + timedelta(minutes=1))
        assert until == T0 + timedelta(minutes=16)
        assert users.locked_until(" A@X.COM", now=T0 + timedelta(minutes=2)) == until

    def test_the_lock_lifts_by_itself(self, users):
        until = self.lock_after(users, "a@x.com", 5)
        assert users.locked_until("a@x.com", now=until) is None

    def test_failures_spread_beyond_the_window_never_lock(self, users):
        assert self.lock_after(users, "a@x.com", 12, step=timedelta(minutes=4)) is None

    def test_failures_while_locked_do_not_extend_it(self, users):
        until = self.lock_after(users, "a@x.com", 5)
        assert self.lock_after(users, "a@x.com", 3, start=T0 + timedelta(minutes=5)) is None
        assert users.locked_until("a@x.com", now=T0 + timedelta(minutes=6)) == until

    def test_an_unknown_address_locks_the_same_way(self, users):
        assert self.lock_after(users, "nobody@x.com", 5) is not None

    def test_success_clears_the_count(self, users):
        self.lock_after(users, "a@x.com", 4)
        users.clear_failures(" A@x.com")
        assert self.lock_after(users, "a@x.com", 4, start=T0 + timedelta(minutes=1)) is None

    def test_expired_rows_are_deleted_on_the_next_write(self, users):
        self.lock_after(users, "old@x.com", 5)
        self.lock_after(users, "new@x.com", 1, start=T0 + timedelta(hours=1))
        assert users.lock_rows() == ["new@x.com"]

    def test_unlock_lifts_it_and_says_whether_there_was_one(self, users):
        self.lock_after(users, "a@x.com", 5)
        assert users.unlock("A@x.com") is True
        assert users.locked_until("a@x.com", now=T0 + timedelta(minutes=1)) is None
        assert users.unlock("a@x.com") is False

    def test_active_locks_are_listed_by_key(self, users):
        until = self.lock_after(users, "a@x.com", 5)
        self.lock_after(users, "b@x.com", 2)
        assert users.active_locks(now=T0 + timedelta(minutes=1)) == {"a@x.com": until}


# --- through the API -----------------------------------------------------------

class TestSignIn:
    def test_the_fifth_wrong_password_locks_and_says_until_when(self, app, users, live):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for _ in range(4):
            assert login(client, "admin@x.com", WRONG).status_code == 401
        locked = login(client, "admin@x.com", WRONG)
        assert locked.status_code == 423
        body = locked.json()
        assert body["detail"] == "This account is locked for now."
        assert datetime.fromisoformat(body["lockedUntil"]["utc"]) > datetime.now(timezone.utc)
        assert "tzOffsetMinutes" in body["lockedUntil"]

    def test_the_right_password_is_refused_while_locked(self, app, users):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for _ in range(5):
            login(client, "admin@x.com", WRONG)
        refused = login(client, "admin@x.com", PASSWORD)
        assert refused.status_code == 423
        assert "token" not in refused.json()

    def test_attempts_while_locked_do_not_extend_it(self, app, users):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for _ in range(5):
            first = login(client, "admin@x.com", WRONG)
        again = login(client, "admin@x.com", WRONG)
        assert again.json()["lockedUntil"] == first.json()["lockedUntil"]

    def test_padded_and_capitalised_emails_share_one_count(self, app, users):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for email in ("admin@x.com", " Admin@X.com ", "ADMIN@x.com", "admin@X.COM"):
            assert login(client, email, WRONG).status_code == 401
        assert login(client, " admin@x.com", WRONG).status_code == 423

    def test_an_unknown_email_gets_the_same_answers(self, app):
        client = TestClient(app, client=NETBIRD)
        answers = [login(client, "nobody@x.com", WRONG).status_code for _ in range(5)]
        assert answers == [401, 401, 401, 401, 423]

    def test_success_clears_the_count(self, app, users):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for _ in range(4):
            login(client, "admin@x.com", WRONG)
        assert login(client, "admin@x.com", PASSWORD).status_code == 200
        for _ in range(4):
            assert login(client, "admin@x.com", WRONG).status_code == 401

    def test_one_address_failing_on_many_accounts_waits(self, app):
        client = TestClient(app, client=NETBIRD)
        for i in range(20):
            assert login(client, f"guess{i}@x.com", WRONG).status_code == 401
        slowed = login(client, "another@x.com", WRONG)
        assert slowed.status_code == 429
        assert "Too many failed sign-ins" in slowed.json()["detail"]
        # Another address is not affected.
        assert login(TestClient(app, client=LAN), "another@x.com", WRONG).status_code == 401

    def test_the_lock_is_audited_before_the_answer_with_the_address(self, app, users, live):
        users.create_user(email="admin@x.com", name="Head", role="admin", password=PASSWORD)
        client = TestClient(app, client=NETBIRD)
        for _ in range(5):
            login(client, "admin@x.com", WRONG)
        [entry] = audit(live, "signin.locked")
        assert entry.actor == "admin@x.com"
        assert "from 100.81.4.7 (private network)" in entry.detail


class TestUnlock:
    def locked_user(self, app, users):
        users.create_user(email="head@x.com", name="Head", role="admin", password=PASSWORD)
        target = users.create_user(email="ali@x.com", name="Ali", role="it", password=PASSWORD)
        for _ in range(5):
            login(TestClient(app, client=NETBIRD), "ali@x.com", WRONG)
        return target

    def admin_client(self, app, users, email="head@x.com", client=LAN):
        user = next(u for u in users.users() if u.email == email)
        token, _ = users.start_session(user)
        return TestClient(app, client=client, headers={"Authorization": f"Bearer {token}"})

    def test_users_shows_until_when_an_account_is_locked(self, app, users):
        self.locked_user(app, users)
        rows = {u["email"]: u for u in self.admin_client(app, users).get("/users").json()}
        assert rows["ali@x.com"]["lockedUntil"] is not None
        assert rows["head@x.com"]["lockedUntil"] is None

    def test_an_administrator_lifts_it(self, app, users, live):
        target = self.locked_user(app, users)
        answer = self.admin_client(app, users).post(f"/users/{target.id}/unlock")
        assert answer.status_code == 200
        assert answer.json()["lockedUntil"] is None
        assert login(TestClient(app, client=NETBIRD), "ali@x.com", PASSWORD).status_code == 200
        [entry] = audit(live, "signin.unlock")
        assert entry.actor == "Head" and entry.subject == "ali@x.com"
        assert "from 192.168.1.20 (factory network)" in entry.detail

    def test_an_it_account_may_not(self, app, users):
        target = self.locked_user(app, users)
        users.create_user(email="it@x.com", name="IT", role="it", password=PASSWORD)
        answer = self.admin_client(app, users, "it@x.com").post(f"/users/{target.id}/unlock")
        assert answer.status_code == 403

    def test_unknown_account_is_404(self, app, users):
        self.locked_user(app, users)
        assert self.admin_client(app, users).post("/users/nope/unlock").status_code == 404

    def test_audited_before_the_write(self, app, users, live, monkeypatch):
        target = self.locked_user(app, users)

        def broken(_email):
            raise RuntimeError("disk full")
        monkeypatch.setattr(users, "unlock", broken)
        answer = TestClient(app, client=LAN, raise_server_exceptions=False,
                            headers=self.admin_client(app, users).headers
                            ).post(f"/users/{target.id}/unlock")
        assert answer.status_code == 500
        assert audit(live, "signin.unlock")


class TestUnlockTool:
    """`engine/tools/unlock_account.py`, for the owner at the workstation."""

    def tool(self):
        spec = importlib.util.spec_from_file_location(
            "unlock_account", ENGINE_DIR / "tools" / "unlock_account.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_lifts_a_lock(self, users, capsys):
        for _ in range(5):
            users.record_failure("ali@x.com", "100.81.4.7")
        assert users.locked_until("ali@x.com") is not None
        assert self.tool().main(["ali@x.com"], users=users) == 0
        assert users.locked_until("ali@x.com") is None
        assert "unlocked" in capsys.readouterr().out

    def test_no_lock_says_so_and_changes_nothing(self, users, capsys):
        assert self.tool().main(["ali@x.com"], users=users) == 0
        assert "was not locked" in capsys.readouterr().out


class TestSignInAudit:
    """T016: every sign-in entry says where it came from, truthfully."""

    def test_a_sign_in_is_audited_with_the_factory_network(self, app, users, live):
        users.create_user(email="head@x.com", name="Head", role="admin", password=PASSWORD)
        assert login(TestClient(app, client=LAN), "head@x.com", PASSWORD).status_code == 200
        [entry] = audit(live, "signin")
        assert (entry.actor, entry.subject) == ("Head", "head@x.com")
        assert entry.detail == "from 192.168.1.20 (factory network)"

    def test_a_failed_sign_in_is_audited_with_the_private_network(self, app, live):
        login(TestClient(app, client=NETBIRD), " Who@X.com", WRONG)
        [entry] = audit(live, "signin.failed")
        assert (entry.actor, entry.subject) == ("who@x.com", "who@x.com")
        assert entry.detail == "from 100.81.4.7 (private network)"

    def test_an_address_from_neither_network_says_outside(self, app, live):
        login(TestClient(app, client=("8.8.8.8", 1)), "who@x.com", WRONG)
        [entry] = audit(live, "signin.failed")
        assert entry.detail == "from 8.8.8.8 (outside)"
