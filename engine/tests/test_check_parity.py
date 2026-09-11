"""The parity checker always reaches its verdict.

`tools/check_parity.py` holds `web/` and `mobile/` to one copy of the truth,
and on 11 Sep 2026 it could not report the drift it exists to catch. The
phone's System Health still printed a share of the graphics card that the
console had withdrawn a week earlier. The checker found the drift, started
printing the diff, reached the first `→` in it and died:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u2192'

Git Bash, and any piped output on Windows, hands Python a cp1252 stdout.
cp1252 has no arrow, and no Arabic either — `ar.draft.ts` is on the list. A
gate that crashes halfway through its report says neither pass nor fail. It
says "something broke", which reads as the checker's fault, not the drift's.

These tests run the real script — loaded by path, the way `test_track_page.py`
loads `engine/tools/measure_track.py` — against a throwaway `web/` and
`mobile/`, with stdout swapped for exactly what Git Bash gives it.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "check_parity.py"

# The line that killed it: the console's copy has the arrow, the phone's not.
ARROW_LINE = "  'health.capacityAsks': 'asks {hz} a second → {ms} ms/s',\r\n"


@pytest.fixture
def checker(tmp_path, monkeypatch):
    """The real script, pointed at a throwaway repo instead of this one."""
    spec = importlib.util.spec_from_file_location("check_parity", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.REPO = tmp_path
    module.WEB = tmp_path / "web" / "src"
    module.MOBILE = tmp_path / "mobile" / "src"
    module.PARITY_FILES = ["i18n/en.ts"]
    monkeypatch.setattr(sys, "argv", ["check_parity.py"])
    return module


def plant(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def run_like_git_bash(checker, monkeypatch) -> tuple[int, str]:
    """Run it with the stdout Python gets under Git Bash or a pipe.

    cp1252 and strict: a character it cannot spell raises rather than
    degrading, which is what stopped the report.
    """
    raw = io.BytesIO()
    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", errors="strict"))
    code = checker.main()
    sys.stdout.flush()
    return code, raw.getvalue().decode("utf-8")


class TestItAlwaysReachesAVerdict:
    def test_a_diff_cp1252_cannot_spell_still_ends_in_fail(self, checker, monkeypatch):
        plant(checker.WEB, "i18n/en.ts", ARROW_LINE)
        plant(checker.MOBILE, "i18n/en.ts", "  'health.capacityAsks': 'asks {hz} a second',\r\n")

        code, out = run_like_git_bash(checker, monkeypatch)

        assert code == 1
        assert "1 of 1 parity files are wrong." in out, "the report never finished"
        assert "→" in out, "the diff shows the arrow itself, not a question mark"

    def test_identical_files_still_end_in_pass(self, checker, monkeypatch):
        plant(checker.WEB, "i18n/en.ts", ARROW_LINE)
        plant(checker.MOBILE, "i18n/en.ts", ARROW_LINE)

        code, out = run_like_git_bash(checker, monkeypatch)

        assert code == 0
        assert out.startswith("parity: "), out
