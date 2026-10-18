"""create_user.py --password-from-env: the mode the Setup wizard drives."""

from __future__ import annotations

import builtins
import getpass
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR / "tools"))

import create_user  # noqa: E402

GOOD = "a-long-enough-test-password"
ARGS = ["--email", "head@school.edu", "--name", "Head Teacher", "--role", "admin",
        "--password-from-env", "VG_TEST_PW"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    from vg.auth.store import UserStore

    path = tmp_path / "auth.db"
    monkeypatch.setattr(create_user, "_database", lambda: path)

    def refuse(*_a, **_k):
        raise AssertionError("asked for keyboard input in --password-from-env mode")
    monkeypatch.setattr(builtins, "input", refuse)
    monkeypatch.setattr(getpass, "getpass", refuse)
    monkeypatch.delenv("VG_TEST_PW", raising=False)
    return lambda: UserStore(path)


def test_creates_the_account_from_the_variable(db, monkeypatch, capsys):
    monkeypatch.setenv("VG_TEST_PW", GOOD)
    assert create_user.main(ARGS) == 0
    users = db().users()
    assert [(u.email, u.name, u.role) for u in users] == [
        ("head@school.edu", "Head Teacher", "admin")]
    assert GOOD not in capsys.readouterr().out


@pytest.mark.parametrize("value", [None, ""])
def test_missing_or_empty_variable_creates_nothing(db, monkeypatch, capsys, value):
    if value is not None:
        monkeypatch.setenv("VG_TEST_PW", value)
    assert create_user.main(ARGS) == 1
    assert "VG_TEST_PW" in capsys.readouterr().err
    assert db().count() == 0


def test_weak_password_fails_and_creates_nothing(db, monkeypatch, capsys):
    monkeypatch.setenv("VG_TEST_PW", "short")
    assert create_user.main(ARGS) == 1
    assert "at least" in capsys.readouterr().err
    assert db().count() == 0


def test_duplicate_email_fails_plainly(db, monkeypatch, capsys):
    monkeypatch.setenv("VG_TEST_PW", GOOD)
    assert create_user.main(ARGS) == 0
    assert create_user.main(ARGS) == 1
    assert "could not create" in capsys.readouterr().err
    assert db().count() == 1


@pytest.mark.parametrize("drop", ["--email", "--name", "--role"])
def test_the_mode_requires_email_name_and_role(db, monkeypatch, capsys, drop):
    monkeypatch.setenv("VG_TEST_PW", GOOD)
    argv = list(ARGS)
    i = argv.index(drop)
    del argv[i:i + 2]
    assert create_user.main(argv) == 1
    assert drop in capsys.readouterr().err
    assert db().count() == 0
