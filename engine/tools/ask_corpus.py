"""Measure the parser against the Arabic corpus. This is SC-003.

    python engine/tools/ask_corpus.py                 # the configured model
    python engine/tools/ask_corpus.py --model gemini-3.5-flash-lite
    python engine/tools/ask_corpus.py --dry-run       # no network, no key

**This costs money and it sends text off-site**, which is why it is a tool you
run rather than a test that runs itself. Everything the tests need about Ask is
provable without it; what only this can measure is whether a real model routes
a real guard's Arabic to the right query.

The score is broken out by language on purpose. A model that scores 100% on
English and 60% on Egyptian dialect has failed for this school, and one blended
percentage would hide exactly that.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ENGINE = pathlib.Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import yaml                                                    # noqa: E402

from vg.ask import Dictionary, QUERIES, QUERY_IDS, mask        # noqa: E402
from vg.ask.parser import (                                    # noqa: E402
    CloudParser,
    ParserUnavailable,
    instructions_for,
)

CORPUS = ENGINE / "tests" / "data" / "ask_questions.yaml"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=None,
                    help="override engine.yaml's ask.model")
    ap.add_argument("--dry-run", action="store_true",
                    help="mask and report only — no key, no network, no cost")
    args = ap.parse_args()

    corpus = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    dictionary = Dictionary.build(corpus["people"], corpus["plates"])
    cases = corpus["questions"]

    print(f"{len(cases)} questions, {len(QUERY_IDS)} queries on the menu\n")

    if args.dry_run:
        return _dry_run(cases, dictionary)

    import os

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("No GEMINI_API_KEY set. Use --dry-run to check the masking "
              "without sending anything.")
        return 2

    from vg import config as vgconfig

    cfg = vgconfig.load()
    parser = CloudParser(
        model=args.model or cfg.ask.model,
        api_key=key,
        query_ids=QUERY_IDS,
        instructions=instructions_for(QUERIES),
        timeout_seconds=cfg.ask.timeout_seconds,
    )
    print(f"model: {args.model or cfg.ask.model}\n")

    by_lang: dict[str, list[bool]] = {}
    wrong: list[str] = []
    for case in cases:
        masked, _ = mask(case["ask"], dictionary)
        try:
            parsed = parser.parse(masked)
            got = parsed.query
        except ParserUnavailable as exc:
            got = f"<unavailable: {exc.reason}>"
        want = case["query"]
        ok = got == want
        by_lang.setdefault(case.get("lang", "?"), []).append(ok)
        if not ok:
            wrong.append(f"  {case['ask']}\n      wanted {want!r}, got {got!r}")

    print("Routing accuracy, by language:")
    for lang in sorted(by_lang):
        results = by_lang[lang]
        hit = sum(results)
        print(f"  {lang:8} {hit}/{len(results)}  "
              f"{100 * hit / len(results):5.1f}%")

    total = [ok for results in by_lang.values() for ok in results]
    score = 100 * sum(total) / len(total)
    print(f"\n  overall  {sum(total)}/{len(total)}  {score:5.1f}%   "
          f"(SC-003 needs >= 95%)")

    if wrong:
        # Named, not counted. A percentage is something to argue with; a list
        # of the actual questions is something to fix.
        print(f"\nWrongly routed ({len(wrong)}):")
        print("\n".join(wrong))

    return 0 if score >= 95 else 1


def _dry_run(cases, dictionary) -> int:
    """Masking only. Free, offline, and the half that matters most."""
    leaks = 0
    for case in cases:
        masked, used = mask(case["ask"], dictionary)
        bad = [i for i in case.get("identifiers", []) if i in masked]
        leaks += len(bad)
        flag = "  LEAK " + ", ".join(bad) if bad else ""
        print(f"{case['ask']}\n  -> {masked}   {sorted(used)}{flag}")
    print(f"\n{leaks} identifier(s) would have left the site.")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
