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
CODES: frozenset[str] = frozenset({
    # -- Ask, the natural-language query console (P12) ----------------------
    #
    # Every one of these is a refusal or a limit. Ask has no code for a
    # successful answer, because a successful answer is figures and rows and
    # needs no sentence from the engine at all.

    #: Not something Ask can answer. The wording must also say what it CAN
    #: answer about, or the operator is left guessing at the boundary.
    "ask.unsupported",

    #: The right query, one parameter short. `parameter` names which.
    #: Exactly one clarifier — a dialogue is a different feature.
    "ask.needs_detail",

    #: `name` is not in the directory. This must NOT read as "they were
    #: absent": an empty register row and a person the system has never heard
    #: of are different answers, and only one of them is about attendance.
    "ask.unknown_person",

    #: The parser could not be reached. `reason` distinguishes a timeout from
    #: a refusal from no key at all. The wording must say that detection and
    #: the safety features are unaffected — otherwise "Ask is unavailable"
    #: reads as "the system is down" to a guard at a gate.
    "ask.cloud_unavailable",

    #: Asked about something the system does not record. `subject` names it.
    #: Today that is lost items only: bag search runs live on the tiles
    #: somebody is watching and stores nothing, so there is no history to
    #: search. Saying "nothing found" would describe a search that never ran.
    "ask.not_recorded",

    #: Words the site did not recognise, sent as typed. `words` lists them.
    #: The accepted limit from the spec, on screen rather than buried: a
    #: visitor's name typed into the box does leave the site, and the person
    #: who typed it is the person who should know.
    "ask.words_left_site",

    # -- Home's "Needs your attention" (spec 013) ---------------------------
    #
    # The item's title is its subject - a camera or a plate - and these say
    # what happened to it. Each wording carries the consequence, not only
    # the cause, like every code here.

    #: A knife entry nobody has decided on yet. `confidence` is 0-100. The
    #: wording must say nobody has confirmed it.
    "attention.weapon",

    #: Somebody entered a restricted area on this camera today.
    "attention.intrusion",

    #: A blacklisted car came through `gate` (the gate's name).
    "attention.vehicles.blacklist",

    #: A car that is not on the register came through `gate`.
    "attention.vehicles.unknown",

    #: A car whose permit has run out came through `gate`.
    "attention.vehicles.expired",

    #: No picture for `minutes` minutes. The wording must say that nothing on
    #: the camera is being watched, which is what makes it urgent.
    "attention.camera",

    #: Somebody went down on this camera and has not got up. The wording must
    #: say they are still on the ground - that is why it is on Home at all.
    "attention.fall",
})


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
