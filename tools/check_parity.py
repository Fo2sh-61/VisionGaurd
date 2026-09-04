"""The console and the phone are two apps holding one copy of the truth.

`web/` and `mobile/` are deliberately separate projects. Everything that
decides *what is true* — what the engine is asked, what comes back, what a
value means, what words describe it — exists once and is copied byte-for-byte
into both. Everything that decides *how it looks* is written twice, on purpose.

This script is what stops the first list quietly becoming the second.

**It is not a theoretical worry.** Before this existed,
`web/src/styles/tokens.css` opened with a comment saying it was "kept
byte-identical to mobile/src/styles/tokens.css", and it was not: the comments
had diverged and the web file had gained a `@keyframes` block the phone never
got. A comment asking people to be careful is what we had, and it had already
failed.

Run it:

    python tools/check_parity.py                # the 25 files must match
    python tools/check_parity.py --no-fixtures  # the phone must invent nothing

Both are gates in `.\\dev.ps1 test` and in CI.

The list below is the source of truth for `specs/012-mobile-parity/contracts/parity.md`,
not the other way round. A list in prose is a list that goes stale.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web" / "src"
MOBILE = REPO / "mobile" / "src"

# Paths relative to each app's `src/`. A file belongs here when it decides what
# is true and carries no layout. A file stays off it when it decides how
# something looks.
#
# If a file needs to be here but genuinely must differ between the two apps,
# that is a design problem rather than an exception to grant: split the
# differing part out into the phone's own presentation layer and keep the rest
# identical. Removing a line from this list to make the gate pass is the one
# thing this script cannot stop you doing, so don't.
PARITY_FILES = [
    # The shapes both apps render.
    "types.ts",

    # Every call to the engine, and everything that turns its answers into
    # values and words. `format.ts` in particular: if the phone were allowed
    # its own copy, one event could read `7:42am` on the desk and `07:42` in a
    # hand. It is also the only file with real assertions behind it
    # (`web/scripts/check-format.ts`), which the phone inherits for free —
    # but only while the file is identical.
    "services/api.ts",
    "services/wire.ts",
    "services/http.ts",
    "services/format.ts",
    "services/frame.ts",
    "services/content.ts",
    "services/notes.ts",
    "services/ask.ts",

    # Every word, in both languages, plus which way each one reads.
    "i18n/index.ts",
    "i18n/keys.ts",
    "i18n/en.ts",
    "i18n/ar.ts",
    "i18n/ar.draft.ts",

    # Which tools exist, where each one lives, and which section it belongs
    # to. A data table, not a sidebar: the console renders it down the left,
    # the phone renders it as a list behind a tab, and neither is allowed its
    # own idea of what the product contains. The phone app kept a hand-written
    # list of six tools until 3 Sep 2026 and had never included the vehicle
    # gate — an entire feature missing because two lists existed and only one
    # was maintained.
    "app/navigation.ts",

    # Who is signed in, what exists, what is running, what language, what
    # theme — and the four hooks that decide how a screen loads, fails and
    # refreshes. None of them draw anything.
    "app/AuthContext.tsx",
    "app/CameraContext.tsx",
    "app/CapabilityContext.tsx",
    "app/LanguageContext.tsx",
    "app/SiteContext.tsx",
    "app/ThemeContext.tsx",
    "app/useAsync.ts",
    "app/useAttention.ts",
    "app/useAutoRun.ts",
    "app/useOptions.ts",

    # The palette. Where the drift already happened once.
    "styles/tokens.css",
]


def _read(path: Path) -> bytes | None:
    """Bytes, never text.

    This repository has mixed line endings and no `.gitattributes`:
    `services/*.ts` and `types.ts` are CRLF, most other files are LF. Reading
    in text mode normalises them, which would call a CRLF file and an LF file
    identical — and a CRLF/LF difference is exactly the drift that makes every
    later diff unreadable. So the comparison is on bytes, and the copy that
    feeds it must preserve endings too.
    """
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def check_parity() -> int:
    """Report every file that differs, with enough detail to act on."""
    problems = 0

    for rel in PARITY_FILES:
        web_path, mobile_path = WEB / rel, MOBILE / rel
        web_bytes, mobile_bytes = _read(web_path), _read(mobile_path)

        if web_bytes is None:
            print(f"MISSING  web/src/{rel}")
            print("         On the parity list but not in the console. Either")
            print("         it moved and the list is stale, or it was deleted")
            print("         from one app only.")
            problems += 1
            continue

        if mobile_bytes is None:
            print(f"MISSING  mobile/src/{rel}")
            print("         The console has it and the phone does not. Copy it.")
            problems += 1
            continue

        if web_bytes == mobile_bytes:
            continue

        problems += 1
        print(f"DIFFERS  {rel}")

        # Line endings are invisible in a diff, so say so outright rather than
        # printing what looks like an identical file with an angry header.
        web_crlf, mobile_crlf = b"\r\n" in web_bytes, b"\r\n" in mobile_bytes
        if web_crlf != mobile_crlf:
            web_kind = "CRLF" if web_crlf else "LF"
            mobile_kind = "CRLF" if mobile_crlf else "LF"
            print(f"         Line endings differ: web is {web_kind}, mobile is {mobile_kind}.")
            print("         The copy was made through text mode. Copy bytes.")

        diff = difflib.unified_diff(
            web_bytes.decode("utf-8", "replace").splitlines(keepends=True),
            mobile_bytes.decode("utf-8", "replace").splitlines(keepends=True),
            fromfile=f"web/src/{rel}",
            tofile=f"mobile/src/{rel}",
            n=2,
        )
        # A whole-file diff means the copy went wrong rather than the content,
        # and printing 1,400 lines of it helps nobody find that out.
        shown = list(diff)[:60]
        for line in shown:
            print("    " + line.rstrip("\n"))
        if len(shown) == 60:
            print("    … truncated. A diff this long usually means the whole")
            print("      file was rewritten — check line endings first.")
        print()

    if problems:
        print(f"{problems} of {len(PARITY_FILES)} parity files are wrong.")
        print("The console and the phone must hold the same copy. Fix both in")
        print("the same commit — see specs/012-mobile-parity/contracts/parity.md.")
        return 1

    print(f"parity: {len(PARITY_FILES)} files identical in web/ and mobile/.")
    return 0


def check_no_fixtures() -> int:
    """The phone must show nothing it was not told.

    Deleting the fixture modules already makes a stale import fail `tsc`. This
    catches the case the compiler cannot see: somebody writing *new* invented
    numbers inline. `Math.random(` is named specifically because that is what
    the old phone app did — campus figures regenerated on every visit, which is
    the single most misleading thing a security console can do.
    """
    problems = 0

    strays = sorted(MOBILE.rglob("mockData.ts"))
    for stray in strays:
        print(f"FIXTURE  {stray.relative_to(REPO).as_posix()}")
        print("         A fixture module. The phone shows the engine or says it")
        print("         cannot reach it; there is no third option.")
        problems += 1

    for path in sorted(MOBILE.rglob("*")):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if "Math.random(" in line:
                rel = path.relative_to(REPO).as_posix()
                print(f"INVENTED {rel}:{number}")
                print(f"         {line.strip()}")
                print("         A value nobody measured. Constitution III.")
                problems += 1

    if problems:
        print(f"{problems} fixture problem(s) in mobile/src.")
        return 1

    print("fixtures: none. Every figure on the phone comes from the engine.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hold web/ and mobile/ to one copy of the truth.",
    )
    parser.add_argument(
        "--no-fixtures",
        action="store_true",
        help="Instead of comparing, assert the phone invents nothing.",
    )
    args = parser.parse_args()

    return check_no_fixtures() if args.no_fixtures else check_parity()


if __name__ == "__main__":
    sys.exit(main())
