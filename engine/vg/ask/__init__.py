"""Ask — turning a question into one existing query (P12).

**Ask does not answer questions.** It works out which query the system already
has for a question, runs that query, and shows its real result. The language
model is a translator between a sentence and a menu id; it never sees a face, a
frame or a record, and it never writes a word an operator reads.

Four modules, and the split is the design:

    menu.py    the thirteen queries. Adding a query is one row here
    mask.py    names and plates out before anything leaves the site. Pure
    parser.py  the seam: a masked question in, a menu choice or "unsupported"
    (ask lives on the store, because it needs every other query)

Why this is not under `features/`: a `FeatureWorker` analyses frames on its own
thread with rate limiting and boost. Ask analyses one sentence on the request
thread that asked. Putting it there would inherit concurrency it must not have
and imply it belongs to a camera.
"""

from vg.ask.mask import (
    Dictionary,
    mask,
    normalise,
    skeleton,
    unmask,
    unrecognised,
)
from vg.ask.menu import QUERIES, QUERY_IDS, AskQuery, find
from vg.ask.parser import (
    CloudParser,
    Parsed,
    Parser,
    ParserUnavailable,
    UnavailableParser,
    build_parser,
    instructions_for,
)

__all__ = [
    "QUERIES",
    "QUERY_IDS",
    "AskQuery",
    "CloudParser",
    "Dictionary",
    "Parsed",
    "Parser",
    "ParserUnavailable",
    "UnavailableParser",
    "build_parser",
    "find",
    "instructions_for",
    "mask",
    "normalise",
    "skeleton",
    "unmask",
    "unrecognised",
]
