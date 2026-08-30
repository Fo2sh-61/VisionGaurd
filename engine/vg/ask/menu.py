"""The thirteen queries Ask can run, and how each one becomes an answer.

**This file is the feature.** Adding a fourteenth query is one row here plus
its wording; nothing else in Ask changes, and nothing outside Ask changes at
all. That is the whole reason the menu is a table rather than a chain of `if`s.

Three rules hold every row, and each has a test in `test_ask.py`:

**One store call.** A `run` calls exactly one `Store` method. Two would be a
new calculation, and a calculation Ask invented is a figure no page can be
checked against.

**Data, never a signpost.** `run` returns figures or rows. "Track Ali" comes
back as Ali's stops with their cameras and times — not a link to the Track
page, which is the thing an operator can already do and the reason Ask exists.
The deep link is always *additional*. The single exemption is `stores_nothing`,
for a feature that records nothing at all, which today is lost items alone.

**No writes.** Nothing here may reach a store method that changes anything.
Ask is read-only (P12-FR-018) and a denylist test holds the line rather than a
comment asking people to be careful.

**Headline metrics are forwarded, never written.** Where the underlying query
already returns `metrics`, those are passed through unchanged — so Ask shows
what the page shows, and no new English sentence is born in the engine (P11).
Where it does not, the headline is empty and the rows speak for themselves;
the console counts them in its own language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote

from vg.api import schemas as S

#: A parameter default meaning "the site's today", resolved by the caller,
#: which is the only place that holds a clock. A literal date here would be
#: the fixed-anchor bug that emptied /breaches on 29 Aug 2026.
TODAY = "@today"


@dataclass(frozen=True)
class Param:
    """One parameter a query needs.

    `describe` is not decoration — it is what the model is told the parameter
    means, and it is the difference between "Grade 8" landing in `subject` and
    landing in `place`.
    """

    name: str
    describe: str
    required: bool = False
    default: str = ""


@dataclass(frozen=True)
class Answer:
    """What a `run` gives back: the figures and the evidence, nothing else."""

    headline: list[S.Metric] = field(default_factory=list)
    rows: list[S.AskRow] = field(default_factory=list)


@dataclass(frozen=True)
class AskQuery:
    id: str
    describe: str
    params: tuple[Param, ...]
    #: The API path this stands for. The permission test reads this: no menu
    #: entry may map under `auth/deps.py::ADMIN_PREFIXES`, because one path
    #: (`POST /ask`) cannot be permissioned per-query and Ask must not become
    #: a second place where a role is decided.
    reads: str
    run: Callable[[Any, dict[str, str]], Answer]
    route: Callable[[dict[str, str]], str]
    #: True only for a feature that records nothing, so there is no stored
    #: answer to return in any shape. Exempts the entry from the
    #: returns-data invariant, and it must emit `ask.not_recorded`.
    stores_nothing: bool = False

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.required)


# ---------------------------------------------------------------------------
# helpers — small, shared, and none of them build a sentence
# ---------------------------------------------------------------------------

def _q(params: dict[str, str], *names: str) -> str:
    """`?a=1&b=2` from the params that are actually set."""
    from urllib.parse import urlencode

    pairs = [(n, params[n]) for n in names if params.get(n)]
    return f"?{urlencode(pairs)}" if pairs else ""


def _person_row(name: str, at: S.Instant | None, camera: str | None,
                confidence: float | None = None,
                clip: S.Clip | None = None) -> S.AskRow:
    return S.AskRow(
        label=name,
        at=at,
        camera=camera,
        confidence=confidence,
        clip_url=clip.url if clip else None,
    )


# ---------------------------------------------------------------------------
# attendance
# ---------------------------------------------------------------------------

def _run_attendance(store: Any, p: dict[str, str]) -> Answer:
    result = store.attendance(p.get("mode", "group"), p.get("subject", ""),
                              p.get("date", ""))
    if result.mode == "person":
        rows = [
            S.AskRow(label=d.date, at=d.seen_at, camera=d.location)
            for d in result.days
        ]
    else:
        rows = [
            _person_row(r.person.name or "", r.seen_at, r.location,
                        r.person.confidence)
            for r in result.records
        ]
    return Answer(headline=list(result.metrics), rows=rows)


# ---------------------------------------------------------------------------
# counting
# ---------------------------------------------------------------------------

def _run_headcount(store: Any, p: dict[str, str]) -> Answer:
    result = store.count(p.get("place", ""), p.get("when", "Today by hour"))
    rows = [
        S.AskRow(label=a.name, at=result.measured_at, camera=None)
        for a in result.areas
    ]
    return Answer(headline=list(result.metrics), rows=rows)


# ---------------------------------------------------------------------------
# restricted zones
# ---------------------------------------------------------------------------

def _run_breaches(store: Any, p: dict[str, str]) -> Answer:
    days = WINDOWS.get(p.get("window", "last7"), 7)
    rows = [
        S.AskRow(
            label=b.zone_name,
            at=b.at,
            camera=b.camera_name,
            confidence=b.confidence,
            clip_url=b.clip.url if b.clip else None,
        )
        for b in store.breaches(days)
    ]
    return Answer(rows=rows)


# ---------------------------------------------------------------------------
# weapons
# ---------------------------------------------------------------------------

#: Period names the Weapons and Restricted-zones pages already use, and how
#: many days back each one means. Ask must pick from this list rather than
#: invent its own, or the page it links to would show a different period from
#: the answer above it — the one thing SC-001 forbids.
WINDOWS: dict[str, int] = {
    "today": 1, "yesterday": 2, "last7": 7, "last30": 30, "last90": 90,
}


def _since(window: str) -> Any:
    """The window's start as an instant, or None for "everything"."""
    from datetime import datetime, timedelta, timezone

    days = WINDOWS.get(window)
    return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)


def _run_weapons(store: Any, p: dict[str, str]) -> Answer:
    rows = [
        S.AskRow(
            label=d.item,
            at=d.at,
            camera=d.camera_name,
            confidence=d.confidence,
            clip_url=d.clip.url if d.clip else None,
        )
        for d in store.weapons(_since(p.get("window", "last30")), None)
    ]
    return Answer(rows=rows)


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def _run_passes(store: Any, p: dict[str, str]) -> Answer:
    filters: dict[str, Any] = {}
    if p.get("plate"):
        filters["plate"] = p["plate"]
    if p.get("gate"):
        filters["gate"] = int(p["gate"])
    if p.get("direction"):
        filters["direction"] = p["direction"]
    if p.get("date"):
        filters["day"] = p["date"]
    rows = [
        S.AskRow(
            # The plate as it appears on the car, never the canonical form —
            # the operator is looking at a car, not at a matching key.
            label=v.plate_display,
            at=v.at,
            camera=v.gate_name,
            confidence=v.confidence,
        )
        for v in store.vehicle_passes(**filters)
    ]
    return Answer(rows=rows)


def _run_inside(store: Any, p: dict[str, str]) -> Answer:
    rows = [
        S.AskRow(label=v.plate_display, at=v.entered, camera=str(v.entry_gate))
        for v in store.vehicles_inside()
    ]
    return Answer(rows=rows)


def _run_gate_totals(store: Any, p: dict[str, str]) -> Answer:
    rows = [
        S.AskRow(label=g.name, camera=g.name)
        for g in store.vehicle_gates(p.get("date", ""))
    ]
    return Answer(rows=rows)


def _run_registered(store: Any, p: dict[str, str]) -> Answer:
    rows = [
        S.AskRow(label=v.plate_display, at=v.last_seen)
        for v in store.vehicle_register(p.get("plate", ""), "")
    ]
    return Answer(rows=rows)


# ---------------------------------------------------------------------------
# people
# ---------------------------------------------------------------------------

def _run_path(store: Any, p: dict[str, str]) -> Answer:
    """Where somebody went. **This is the shape every entry is held to.**

    "Track Ali" returns Ali's stops — each camera, when he arrived, how long,
    and how strong the evidence was. Not a summary and not a link.

    Only `anchors` are used. `appearance` stops say "the same body", never
    "this person": promoting them here would put a name on a stranger's
    movements, which is the bug that once made everybody read as one person.
    """
    skeleton = store.path_skeleton(p.get("person", ""), p.get("date", ""),
                                   p.get("actor", "ask"))
    rows = [
        S.AskRow(
            label=a.place or a.camera_name,
            at=a.at,
            camera=a.camera_name,
            confidence=a.score,
        )
        for a in skeleton.anchors
    ]
    return Answer(rows=rows)


def _run_history(store: Any, p: dict[str, str]) -> Answer:
    history = store.history(p.get("person", ""))
    if history is None:
        return Answer()
    rows = [
        S.AskRow(label=t.date, confidence=t.present_ratio)
        for t in history.trend
    ]
    return Answer(headline=list(history.metrics), rows=rows)


def _run_directory(store: Any, p: dict[str, str]) -> Answer:
    wanted = (p.get("person") or "").strip().casefold()
    people = [
        person for person in store.people()
        if not wanted or wanted in person.name.casefold()
    ]
    rows = [
        S.AskRow(label=person.name, at=person.last_seen,
                 camera=person.last_camera)
        for person in people
    ]
    return Answer(rows=rows)


def _run_group(store: Any, p: dict[str, str]) -> Answer:
    detail = store.group(p.get("group", ""))
    if detail is None:
        return Answer()
    rows = [
        _person_row(r.person.name or "", r.seen_at, r.location,
                    r.person.confidence)
        for r in detail.roster
    ]
    return Answer(rows=rows)


# ---------------------------------------------------------------------------
# the system itself
# ---------------------------------------------------------------------------

def _run_health(store: Any, p: dict[str, str]) -> Answer:
    health = store.health()
    rows = [
        S.AskRow(label=c.name, at=c.captured_at, camera=c.name)
        for c in health.cameras
    ]
    return Answer(headline=list(health.metrics), rows=rows)


# ---------------------------------------------------------------------------
# the menu
# ---------------------------------------------------------------------------

QUERIES: tuple[AskQuery, ...] = (
    AskQuery(
        id="attendance",
        describe="Whether a person or a group arrived, and when. Register data.",
        params=(
            Param("mode", "'person' for one named person, 'group' for a class "
                          "or year group", required=True),
            Param("subject", "the person's name or the group's name",
                  required=True),
            Param("date", "the day being asked about, as YYYY-MM-DD",
                  default=TODAY),
        ),
        reads="/attendance",
        run=_run_attendance,
        route=lambda p: "/attendance" + _q(p, "mode", "subject", "date"),
    ),
    AskQuery(
        id="headcount",
        describe="How many people are in a named place right now or over a "
                 "period.",
        params=(
            Param("place", "the area's name, e.g. 'Main entrance'",
                  required=True),
            Param("when", "'Today by hour' or 'This week by day'",
                  default="Today by hour"),
        ),
        reads="/count",
        run=_run_headcount,
        route=lambda p: "/counting" + _q(p, "place", "when"),
    ),
    AskQuery(
        id="zone_breaches",
        describe="Who entered a restricted area, and when.",
        params=(Param("window", "the period: today, last7 or last30",
                      default="last7"),),
        reads="/breaches",
        run=_run_breaches,
        route=lambda p: "/intrusion" + _q(p, "window"),
    ),
    AskQuery(
        id="weapons",
        describe="Knife detections and whether a person has reviewed them.",
        params=(Param("window", "the period: today, yesterday, last7, last30 "
                                "or last90", default="last30"),),
        reads="/weapons/detections",
        run=_run_weapons,
        route=lambda p: "/weapons" + _q(p, "window"),
    ),
    AskQuery(
        id="vehicle_passes",
        describe="Cars that passed a gate — by plate, gate, direction or day.",
        params=(
            Param("plate", "the number plate, in either digit system"),
            Param("gate", "the gate number"),
            Param("direction", "'entry' or 'exit'"),
            Param("date", "the day, as YYYY-MM-DD", default=TODAY),
        ),
        reads="/vehicles/passes",
        run=_run_passes,
        # `direction` is deliberately absent: the movements tab has no
        # direction filter, and a parameter nothing reads is the decoration
        # this whole exercise was about removing.
        route=lambda p: "/vehicles" + _q(
            {**p, "tab": "movements"}, "tab", "plate", "gate", "date"),
    ),
    AskQuery(
        id="vehicles_inside",
        describe="Which cars are inside the site now and have not left.",
        params=(),
        reads="/vehicles/inside",
        run=_run_inside,
        route=lambda p: "/vehicles?tab=movements",
    ),
    AskQuery(
        id="gate_totals",
        describe="How many cars entered and left each gate on a day.",
        params=(Param("date", "the day, as YYYY-MM-DD", default=TODAY),),
        reads="/vehicles/gates",
        run=_run_gate_totals,
        route=lambda p: "/vehicles?tab=movements",
    ),
    AskQuery(
        id="vehicle_registered",
        describe="Whether a plate is in the register, and what it is allowed.",
        params=(Param("plate", "the number plate", required=True),),
        reads="/vehicles/register",
        run=_run_registered,
        route=lambda p: "/vehicles" + _q({**p, "tab": "register"},
                                         "tab", "plate"),
    ),
    AskQuery(
        id="person_path",
        describe="Where a named person is or was — every camera that "
                 "identified them, in order, most recent last. Use this for "
                 "ANY question about a person's location or movement: "
                 "'where is X', 'where is X now', 'track X', 'where did X "
                 "go', 'find X', 'which camera saw X'. Present tense counts: "
                 "the most recent stop is where they are.",
        params=(
            Param("person", "the person's name", required=True),
            Param("date", "the day, as YYYY-MM-DD", default=TODAY),
        ),
        reads="/path",
        run=_run_path,
        route=lambda p: "/track" + _q(p, "person", "date"),
    ),
    AskQuery(
        id="person_history",
        describe="One person's attendance over time — days present, days "
                 "absent, the pattern.",
        params=(Param("person", "the person's name", required=True),),
        reads="/people",
        run=_run_history,
        # The page for one person's history already exists and already reads
        # the name out of its own path. Nothing to teach it.
        route=lambda p: f"/people/history/{quote(p.get('person', ''))}",
    ),
    AskQuery(
        id="person_directory",
        describe="Whether somebody is enrolled, and when they were last seen.",
        params=(Param("person", "the person's name"),),
        reads="/people",
        run=_run_directory,
        route=lambda p: "/people" + _q({"query": p.get("person", "")}, "query"),
    ),
    AskQuery(
        id="group_roster",
        describe="Who is in a class or year group, and who is present today.",
        params=(Param("group", "the group's name, e.g. 'Grade 8'",
                      required=True),),
        reads="/people",
        run=_run_group,
        route=lambda p: f"/people/groups/{quote(p.get('group', ''))}",
    ),
    AskQuery(
        id="lost_item",
        describe="A lost bag or item. Use this for any question about finding "
                 "a bag, a case or a left item.",
        params=(Param("colour", "the item's colour, if the question says one"),),
        reads="/lost",
        # Nothing to run. Bag search happens live on the tiles somebody is
        # watching and records nothing at all — no clip, no still, no history —
        # so a bag taken this morning has left no trace to search. Returning an
        # empty result would read as "no bag was found", which is a lie about a
        # search that never happened. The caller sees `stores_nothing` and says
        # so, then offers the page with the colour filled in.
        run=lambda store, p: Answer(),
        route=lambda p: "/lost-items" + _q(p, "colour"),
        stores_nothing=True,
    ),
    AskQuery(
        id="system_state",
        describe="What the system itself is doing — cameras online, what is "
                 "degraded and why.",
        params=(),
        reads="/system/health",
        run=_run_health,
        route=lambda p: "/system",
    ),
)

#: Every id, for the parser's schema. A model constrained to this list cannot
#: name a query nobody has.
QUERY_IDS: tuple[str, ...] = tuple(q.id for q in QUERIES)

#: Every parameter name any query takes, for the parser's schema.
#:
#: One flat set rather than a shape per query, because the schema is fixed
#: before the query is chosen. Twelve optional slots is a small price for the
#: thing it buys: a model given a NAMED field fills it, and a model given an
#: open dictionary very often does not. Measured — "how many people in the
#: Library" returned `{}` about half the time with an open `params` object and
#: `{"place": "Library"}` reliably once the slots existed.
PARAM_NAMES: tuple[str, ...] = tuple(sorted(
    {p.name for q in QUERIES for p in q.params}))


def find(query_id: str | None) -> AskQuery | None:
    """The entry with that id, or None. None is "unsupported", not an error."""
    if not query_id:
        return None
    return next((q for q in QUERIES if q.id == query_id), None)
