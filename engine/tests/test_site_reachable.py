""""Cannot reach the site" means nothing came back for a while, not one lost request.

Found 20 Oct 2026 on the first remote phone: through NetBird's relay on mobile
data a few requests get lost, and the enlarged camera view asks for its boxes
ten times a second, so the red banner flashed on and off while the page worked.
`services/http.ts` (both apps, on the parity list) now says so only after
`UNREACHABLE_AFTER_MS` with no answer; any answer cancels it.

Source checks, like `test_on_screen_tiles.py`: the repo has no browser test
runner. The timing was also run for real under node on 20 Oct 2026 (one lost
request: never said; every request failing: said once, after 5.0 s; first
answer: cleared at once).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def http(app: str) -> str:
    return (ROOT / app / "src" / "services" / "http.ts").read_text(encoding="utf-8")


@pytest.mark.parametrize("app", ["web", "mobile"])
class TestSiteReachable:
    def test_it_waits_five_seconds_of_silence(self, app):
        source = http(app)
        assert re.search(r"export const UNREACHABLE_AFTER_MS = 5_000;", source)
        no_answer = source.split("function gotNoAnswer(): void {", 1)[1].split("\n}", 1)[0]
        assert "setTimeout(" in no_answer and "UNREACHABLE_AFTER_MS" in no_answer
        assert "setSiteReachable(false)" in no_answer
        # a second failure while counting does not start the clock again
        assert "if (unreachableTimer !== null || !siteReachable) return;" in no_answer

    def test_any_answer_cancels_it(self, app):
        answer = http(app).split("function gotAnswer(): void {", 1)[1].split("\n}", 1)[0]
        assert "clearTimeout(unreachableTimer)" in answer
        assert "setSiteReachable(true)" in answer

    def test_a_request_never_says_unreachable_by_itself(self, app):
        body = http(app).split("export async function request<T>", 1)[1]
        body = body.split("\nexport ", 1)[0]
        assert "setSiteReachable(" not in body
        assert body.count("gotNoAnswer()") == 2       # timed out, and no answer at all
        assert body.index("await fetch(") < body.index("gotAnswer();")
