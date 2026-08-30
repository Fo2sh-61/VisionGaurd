"""Every explanation the engine can give, as a code the console translates.

The engine says *what happened*. The console says it *in a language*. That
split is the whole reason this module exists: before it, sentences like

    "No exit camera is configured, so no car can be matched to its exit.
     Cars leaving are not being counted."

were written in Python and shipped to the screen, which made them permanently
English and made a copy change a backend deploy.

Rules
-----

**Every code is declared here.** `note()` refuses an undeclared one, and
`engine/tests/test_notes.py` catches it by reading the source, so an
unregistered code in a branch nobody exercises still fails the build.

**`args` are facts, never phrases.** A camera name, a count, a number of
minutes. An English phrase passed through `args` is untranslatable; if
something needs saying, it needs its own code.

**A wording must carry the consequence, not only the cause.** `gate.no_exit_camera`
is not "there is no exit camera" — it is "there is no exit camera, *so cars
leaving are not being counted*". Dropping the second half in translation is a
new bug, not a shorter sentence.

**Codes are dotted and stable.** `web/src/i18n/keys.ts` mirrors this set as
`NoteCode`, and the English wording for each lives in `web/src/i18n/en.ts`.
Renaming one is a coordinated change on both sides.
"""

from __future__ import annotations

from vg.api import schemas as S

#: Every code the engine may emit.
#:
#: Grouped by what is being explained. Add a code here in the same commit as
#: the `note()` call that emits it and the wording that renders it — a code
#: with no emitter and a code with no wording are both caught by tests.
CODES: frozenset[str] = frozenset()


def note(code: str, **args: str | int | float) -> S.Note:
    """Build a `Note`, refusing a code nobody declared.

    Failing here rather than on the screen is deliberate: an unknown code
    reaching the console renders as "unavailable, and the console does not
    recognise the reason", which is honest but useless to the operator. The
    engine should never be the one that produces it.
    """
    if code not in CODES:
        raise KeyError(
            f"{code!r} is not a declared note code. Add it to CODES in "
            f"vg/api/notes.py and give it a wording in web/src/i18n/en.ts."
        )
    return S.Note(code=code, args=dict(args))
