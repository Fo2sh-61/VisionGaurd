"""Every page that loads something must say when the load failed.

P0-08. The bug this locks down was the same on nine pages:

    useEffect(() => { void getUsers().then(setUsers); }, []);

`get()` throws when the engine is unreachable. With no catch that became an
unhandled rejection nobody sees, the state stayed at its initial `[]`, and the
page rendered a confident "0 people can sign in" built from no data at all. An
operator cannot tell that from a genuinely empty table, and the constitution is
explicit that they must be able to: never show anything untrue, and if
something is unavailable, say so plainly with a reason.

Two pages did something worse and returned `null` until their data arrived, so
a failed request drew a completely blank page — no title, no error, no way
back.

This test is a source check, deliberately. The failure is an *absent* line,
and there is no runtime state that reveals one: a page that forgot its error
branch renders exactly like a page whose data is genuinely empty. Only the
source says which. It lives in pytest rather than a JS runner because `web/`
has no test runner, and adding one is the owner's call, not a side effect of
fixing this.

It checks that the wiring is present, not that the words are right. Whether an
empty state reads well is a question for a person looking at the screen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "web" / "src" / "pages"

# Pages that legitimately load nothing from the engine, so they have no
# failure to report. Kept as an explicit list rather than inferred, so adding
# a fetch to one of them trips the test rather than silently exempting it.
NO_DATA = {
    "Login",       # a form; the sign-in call reports its own failure inline
    "Home",        # navigation and static copy only
}

# Pages whose lists live in a component they mount, which must then say
# "nothing here" for them. Explicit, like NO_DATA: moving a list into a
# component moves the duty with it, it does not drop it.
COMPONENTS = REPO / "web" / "src" / "components"
LISTS_IN = {
    "Settings": "AlertSettings",   # recipients, rules, the delivery log (spec 013)
}


def _pages() -> list[Path]:
    return sorted(PAGES.glob("*.tsx"))


def _fetches(source: str) -> bool:
    """Does this page ask the engine for anything?"""
    return "@/services/api" in source


def _reports_failure(source: str) -> bool:
    """Is there any path that tells the operator a load failed?

    `useAsync` + `LoadError` is the intended pair, but a page that catches and
    renders its own message is equally honest, so both count.

    The check is for `<LoadError`, the mounted element — not the bare name,
    which also matches the import line. An earlier version of this test looked
    for the name and so passed a page whose import was intact but whose
    element had been deleted: it proved only that somebody had once intended
    to handle the error.
    """
    return (
        "<LoadError" in source
        or ".catch(" in source
        or re.search(r"\bcatch\s*\(", source) is not None
    )


def _has_empty_state(source: str) -> bool:
    """Does it say something when there is nothing to show?"""
    return "<Empty" in source or "className=\"empty\"" in source


class TestPagesReportFailure:
    def test_there_are_pages_to_check(self):
        """Guard the guard: a moved directory must not silently pass."""
        assert len(_pages()) >= 10, f"expected the console's pages, found {_pages()}"

    @pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
    def test_a_page_that_loads_data_can_report_a_failure(self, page: Path):
        source = page.read_text(encoding="utf-8")

        if page.stem in NO_DATA:
            assert not _fetches(source), (
                f"{page.stem} is listed as loading nothing, but it imports from "
                f"@/services/api. Remove it from NO_DATA and give it the states."
            )
            return

        if not _fetches(source):
            return

        assert _reports_failure(source), (
            f"{page.stem} loads from the engine but has no failure path. A "
            f"request that throws will leave the page rendering its initial "
            f"empty state as though that were the answer. Use `useAsync` and "
            f"mount `<LoadError>`."
        )

    @pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
    def test_a_page_that_loads_a_list_says_when_it_is_empty(self, page: Path):
        source = page.read_text(encoding="utf-8")
        if page.stem in NO_DATA or not _fetches(source):
            return

        mounted = ""
        if page.stem in LISTS_IN:
            module = LISTS_IN[page.stem]
            assert f"from '@/components/{module}'" in source, (
                f"{page.stem} is listed as keeping its lists in {module}, but no "
                f"longer mounts it. Remove it from LISTS_IN."
            )
            mounted = (COMPONENTS / f"{module}.tsx").read_text(encoding="utf-8")

        assert _has_empty_state(source) or _has_empty_state(mounted), (
            f"{page.stem} loads from the engine but never says 'nothing here'. "
            f"A page with no rows and no message reads as broken. Mount "
            f"`<Empty>` for the no-rows case."
        )


class TestNoBlankPageOnFailure:
    """`if (!data) return null` draws nothing at all — the worst failure.

    No title, no error, no navigation. The operator cannot tell a broken
    engine from a page that has nothing to say, and on a detail page reached
    by a link there is not even a way back.
    """

    @pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
    def test_no_page_returns_null_instead_of_rendering(self, page: Path):
        source = page.read_text(encoding="utf-8")

        offenders = [
            line.strip()
            for line in source.splitlines()
            if re.match(r"^\s*if\s*\(!\w+\)\s*return\s+null\s*;?\s*$", line)
        ]

        assert not offenders, (
            f"{page.stem} renders nothing while its data is missing: "
            f"{offenders}. A failed request leaves that condition true "
            f"forever, so the page stays blank with no way to tell why. "
            f"Render the frame, and put the reason inside it."
        )
