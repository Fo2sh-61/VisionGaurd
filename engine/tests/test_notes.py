"""The note-code registry stays in step with the code that emits it.

`vg/api/notes.py` declares every explanation the engine can give. Two ways for
that to rot, and one test for each:

- a `note()` call with a code nobody declared. `note()` raises, but only if the
  branch runs — and the branches that explain failures are exactly the ones a
  test suite rarely reaches. So this reads the source instead, and catches it
  without executing anything.
- a declared code nobody emits. That is a wording somebody will translate into
  Arabic and no operator will ever see, and it will still be there in a year.

The console half of the contract is proved by the type checker: `en.ts` is
typed `Record<MessageKey, string>` and will not compile with a wording missing.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from vg.api.notes import CODES, note

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "vg"


def _emitted() -> dict[str, list[str]]:
    """Every literal code passed to `note(...)`, and where from."""
    found: dict[str, list[str]] = {}
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else (
                n.func.id if isinstance(n.func, ast.Name) else None)
            if name != "note" or not n.args:
                continue
            first = n.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                where = f"{path.relative_to(ENGINE.parent)}:{n.lineno}"
                found.setdefault(first.value, []).append(where)
    return found


class TestRegistry:
    def test_every_emitted_code_is_declared(self):
        emitted = _emitted()
        undeclared = {
            code: where for code, where in emitted.items() if code not in CODES
        }
        assert not undeclared, (
            "these codes are emitted but not in notes.CODES, so the console "
            f"has no wording for them: {undeclared}"
        )

    def test_every_declared_code_is_emitted(self):
        emitted = set(_emitted())
        orphans = sorted(CODES - emitted)
        assert not orphans, (
            "these codes are declared but nothing emits them. A wording "
            f"nobody can reach will rot: {orphans}"
        )

    def test_an_undeclared_code_is_refused(self):
        # Better to fail here than to put "the console does not recognise this
        # reason" in front of an operator.
        with pytest.raises(KeyError):
            note("nothing.declares.this")

    def test_args_travel_as_data(self):
        if not CODES:
            pytest.skip("no codes declared yet")
        code = sorted(CODES)[0]
        built = note(code, camera="cam-hall", minutes=7)
        assert built.code == code
        assert built.args == {"camera": "cam-hall", "minutes": 7}
