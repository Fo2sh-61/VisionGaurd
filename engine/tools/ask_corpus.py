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
from vg.ask.menu import PARAM_NAMES                            # noqa: E402
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
    ap.add_argument("--delay", type=float, default=4.0,
                    help="seconds between questions (default 4). The free "
                         "tier is far tighter than the blogs claim — measured "
                         "at 20 requests for gemini-3.7-flash — so firing the "
                         "corpus off in one go just spends the quota on 429s")
    ap.add_argument("--retries", type=int, default=2,
                    help="how many times to wait out a 429 per question")
    args = ap.parse_args()

    corpus = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    dictionary = Dictionary.build(corpus["people"], corpus["plates"])
    cases = corpus["questions"]

    print(f"{len(cases)} questions, {len(QUERY_IDS)} queries on the menu\n")

    if args.dry_run:
        return _dry_run(cases, dictionary)

    import os

    # Config FIRST, because loading it is what reads engine/.env — and .env is
    # where the key belongs, since engine.yaml is in git and a key in git is a
    # key to rotate. Reading the environment before this looked correct and
    # quietly ignored a key that was sitting right there.
    from vg import config as vgconfig

    cfg = vgconfig.load()

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("No GEMINI_API_KEY found in the environment or in engine/.env.\n"
              "Use --dry-run to check the masking without sending anything.")
        return 2
    parser = CloudParser(
        model=args.model or cfg.ask.model,
        api_key=key,
        query_ids=QUERY_IDS,
        param_names=PARAM_NAMES,
        # The same vocabulary production sends, or the score measures a
        # parser nobody runs.
        instructions=instructions_for(QUERIES, {
            "areas": [str(a) for a in corpus.get("areas", [])],
            "groups": [str(g) for g in corpus.get("groups", [])],
        }),
        timeout_seconds=cfg.ask.timeout_seconds,
    )
    print(f"model: {args.model or cfg.ask.model}\n")

    by_lang: dict[str, list[bool]] = {}
    wrong: list[str] = []
    dead = 0
    for index, case in enumerate(cases):
        masked, _ = mask(case["ask"], dictionary)
        got = _route(parser, masked, args.retries, args.delay)
        print(f"  [{index + 1}/{len(cases)}] {got}", flush=True)

        # Give up rather than grind. A per-minute limit clears while you wait;
        # a DAILY one does not, and the two look identical from here. Retrying
        # a spent daily quota for every remaining question means an hour of
        # waiting for 37 answers that will never come — which is exactly what
        # this did to `gemini-3.7-flash`, whose free allowance is 20 requests
        # against a corpus of 37.
        dead = dead + 1 if got.startswith("<unavailable: busy") else 0
        if dead >= 3:
            print(f"\nGiving up after {dead} in a row. The quota for "
                  f"{args.model or cfg.ask.model} looks spent for today — a "
                  f"per-minute limit would have cleared by now.\n"
                  f"Try a model with its own allowance:\n"
                  f"  python engine/tools/ask_corpus.py "
                  f"--model gemini-3.5-flash-lite\n"
                  f"or --dry-run to check the masking, which costs nothing.")
            return 2
        want = case["query"]
        # Some questions have more than one correct route. Scoring a right
        # answer as wrong would make the model look worse than it is and hide
        # the failures that matter.
        ok = got == want or got in (case.get("accept") or [])
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


def _route(parser, masked: str, retries: int, delay: float) -> str:
    """One question, waiting out the free tier's rate limit rather than
    counting a 429 as a wrong answer.

    A rate limit is not a routing failure. Scoring it as one would report 0%
    and blame the model for something that is entirely about the plan the key
    is on — which is exactly what the first run of this tool did.
    """
    import time

    for attempt in range(retries + 1):
        try:
            return parser.parse(masked).query
        except ParserUnavailable as exc:
            # "offline" and "timeout" are transient too. Counting a dropped
            # connection as a wrong route is how the second run of this tool
            # reported 83.8% when the model had actually answered 31 of the
            # 34 questions that reached it.
            transient = exc.reason in {"busy", "offline", "timeout"}
            if not transient or attempt == retries:
                return f"<unavailable: {exc.reason}>"
            # Short waits. A per-minute window clears inside a minute; if it
            # does not, waiting longer is not going to help and the caller
            # gives up after three of these in a row.
            wait = 20.0 if exc.reason == "busy" else 5.0
            print(f"      {exc.reason}, waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
        finally:
            time.sleep(delay)
    return "<unavailable: busy>"


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
