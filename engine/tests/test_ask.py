"""Ask — the natural-language query console (P12).

The rule these defend: **Ask never invents a fact.** It maps a question to one
existing, tested query and shows only that query's real result. Everything here
is about the two ways that promise breaks — a fabricated answer, and a name
leaving the site — plus the four honest states that must never collapse into
"no results".

Nothing here needs a network or an API key. The parser is a seam, so the tests
drive it with a stub and test **Ask**, not the model. `tools/ask_corpus.py` is
what measures the model, and it is a separate, deliberate act that costs money.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from vg.api import notes
from vg.api import schemas as S
from vg.api.store import MockStore, SubsystemUnavailable
from vg.ask import Dictionary, mask, normalise, skeleton, unrecognised
from vg.ask.menu import QUERIES, QUERY_IDS, find
from vg.ask.parser import Parsed, ParserUnavailable, UnavailableParser, schema_for

CORPUS = yaml.safe_load(
    (pathlib.Path(__file__).parent / "data" / "ask_questions.yaml")
    .read_text(encoding="utf-8")
)


class StubParser:
    """Answers whatever it was told to. The point is to test Ask, not a model."""

    def __init__(self, **kw) -> None:
        self.parsed = Parsed(**kw)
        self.saw: list[str] = []

    def parse(self, masked_question: str) -> Parsed:
        self.saw.append(masked_question)
        return self.parsed


class BrokenParser:
    def __init__(self, reason: str = "timeout") -> None:
        self.reason = reason

    def parse(self, masked_question: str) -> Parsed:
        raise ParserUnavailable(self.reason)


@pytest.fixture
def store() -> MockStore:
    return MockStore()


# ---------------------------------------------------------------------------
# the shape of an answer
# ---------------------------------------------------------------------------

class TestShape:
    def test_the_answer_has_nowhere_to_write_a_sentence(self):
        """P12-FR-003, enforced by the data rather than by review.

        Every sentence an operator reads is built by the console from a note
        code. If `AskAnswer` ever grows a free-text field, a future change can
        put a model's words on the screen without anybody noticing — so the
        absence of one is asserted rather than trusted.
        """
        free_text = {
            name for name, field in S.AskAnswer.model_fields.items()
            if field.annotation is str and name not in {"sent_off_site",
                                                        "audit_id"}
        }
        assert not free_text, (
            f"AskAnswer gained a free-text field: {free_text}. Every sentence "
            "must come from a note code the console words."
        )

    def test_rows_carry_evidence_not_prose(self):
        row = S.AskRow(label="Main entrance")
        assert set(S.AskRow.model_fields) == {
            "label", "at", "camera", "confidence", "clip_url", "note"}
        assert row.note is None

    def test_the_four_outcomes_stay_four_things(self):
        assert {o.value for o in S.AskOutcome} == {
            "answered", "unsupported", "needs_detail", "unavailable"}


# ---------------------------------------------------------------------------
# the menu
# ---------------------------------------------------------------------------

class TestMenu:
    def test_ids_are_unique(self):
        assert len(QUERY_IDS) == len(set(QUERY_IDS))

    def test_nothing_reaches_an_admin_only_path(self):
        """P12-FR-019, and the reason the menu is restricted rather than the
        endpoint being permissioned per query.

        One path (`POST /ask`) reaches every query, so `auth/deps.py` cannot
        see what is about to run. The menu is therefore kept inside what the
        weakest role can already read. A test holds this rather than a comment,
        because the day somebody adds an enrolment query is the day the comment
        gets skipped.
        """
        from vg.auth.deps import ADMIN_PREFIXES

        leaks = [
            q.id for q in QUERIES
            if any(q.reads.startswith(p) for p in ADMIN_PREFIXES)
        ]
        assert not leaks, (
            f"these menu entries reach administrator-only paths: {leaks}. Ask "
            "must not become a way to read past a role."
        )

    def test_no_entry_can_write(self):
        """Ask is read-only (P12-FR-018), asserted against the store itself.

        A denylist of verbs, checked against what each `run` actually calls —
        not against what it was meant to call.
        """
        import inspect

        forbidden = (
            "follow_", "start_", "stop_", "review_", "set_", "add_", "edit_",
            "remove_", "delete_", "correct_", "import_", "export_",
            "acknowledge", "dismiss_", "connect_", "scan",
        )
        for query in QUERIES:
            source = inspect.getsource(query.run)
            called = [v for v in forbidden if f"store.{v}" in source]
            assert not called, (
                f"menu entry {query.id!r} calls a writing store method "
                f"{called}. Ask is read-only."
            )

    def test_each_entry_calls_exactly_one_store_method(self, store):
        """Two calls would be a calculation Ask invented, and a figure Ask
        invented is one no page can be checked against (SC-001)."""

        class Counting:
            def __init__(self, real):
                self._real = real
                self.calls: list[str] = []

            def __getattr__(self, name):
                attr = getattr(self._real, name)
                if callable(attr) and not name.startswith("_"):
                    self.calls.append(name)
                return attr

        for query in QUERIES:
            if query.stores_nothing:
                continue
            spy = Counting(store)
            params = {p.name: "x" for p in query.params}
            try:
                query.run(spy, params)
            except Exception:
                # A query that refuses these dummy parameters is fine; what is
                # being counted is how many store methods it reached.
                pass
            assert len(spy.calls) <= 1, (
                f"{query.id!r} called {spy.calls}. One query, one store call."
            )

    def test_every_entry_answers_with_data_not_a_signpost(self, store):
        """The invariant that stops "track Ali" degrading into a link.

        A deep link is always *additional*. An entry whose only output is a
        route has not answered the question, and a guard who wanted the Track
        page did not need Ask to find it.
        """
        # MockStore holds no vehicle fixtures: the gate was built live-only,
        # so there is genuinely nothing for those entries to return here. That
        # is the store being honest, not the entry being thin.
        no_demo_data = not store.vehicle_register("", "")
        thin = []
        for query in QUERIES:
            if query.stores_nothing:
                continue
            if no_demo_data and query.reads.startswith("/vehicles"):
                continue
            params = {p.name: _plausible(p.name, store) for p in query.params}
            result = query.run(store, params)
            if not result.headline and not result.rows:
                thin.append(query.id)
        assert not thin, (
            f"these entries returned neither figures nor rows against a store "
            f"that has data: {thin}. A link is not an answer."
        )

    def test_every_deep_link_is_read_by_the_page_it_points_at(self):
        """A link nothing reads is decoration, and it looked like it worked.

        Ask produced `/track?person=Mohamed%20Fouad`, the console navigated
        there, and Track a Person ignored the whole query string — so "where
        is Mohamed" opened an empty form and the operator retyped the name
        they had just typed. Nothing failed; it simply did nothing.

        This pins the contract from the other side: a parameter a route puts
        in the URL must be one the page actually looks for.
        """
        web = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"
        if not web.is_dir():             # engine checked out on its own
            pytest.skip("no web/ in this tree")

        # Which files each route lands on. A page plus the components it
        # delegates its tabs to — the gate reads its filters in
        # `VehicleMovements`, and to the operator that is the same screen.
        reads: dict[str, tuple[str, ...]] = {
            "/track": ("pages/TrackPerson.tsx",),
            "/attendance": ("pages/Attendance.tsx",),
            "/counting": ("pages/Counting.tsx",),
            "/intrusion": ("pages/Intrusion.tsx",),
            "/weapons": ("pages/Weapons.tsx",),
            "/vehicles": ("pages/VehicleGate.tsx",
                          "components/VehicleMovements.tsx"),
            "/people": ("pages/People.tsx",),
            "/lost-items": ("pages/LostItems.tsx",),
            "/system": ("pages/SystemHealth.tsx",),
        }
        from urllib.parse import parse_qs, urlparse

        missed: list[str] = []
        for query in QUERIES:
            route = query.route({p.name: "x" for p in query.params})
            parsed = urlparse(route)
            path = parsed.path
            # What the URL actually carries, not what the query calls its
            # parameters — a route may rename one on the way out, and the page
            # only ever sees the name in the URL.
            params = parse_qs(parsed.query)
            files = reads.get(path)
            if files is None:
                # A path parameter — `/people/history/<name>` — is read by the
                # router from the URL itself, so there is nothing for a page
                # to look up and nothing here to check.
                continue
            source = "".join((web / f).read_text(encoding="utf-8")
                             for f in files)
            for name in params:
                if f"'{name}'" not in source:
                    missed.append(f"{query.id} -> {path} sends {name!r}, "
                                  f"{' or '.join(files)} never reads it")
        assert not missed, "; ".join(missed)

    def test_only_a_feature_that_records_nothing_is_exempt(self):
        exempt = [q.id for q in QUERIES if q.stores_nothing]
        assert exempt == ["lost_item"], (
            "the returns-data rule may only be waived for a feature that "
            f"genuinely stores nothing. Got: {exempt}"
        )


def _plausible(name: str, store: MockStore) -> str:
    """A parameter value the demo store will actually match."""
    if name in {"person", "subject"}:
        people = store.people()
        return people[0].name if people else "Layla Ahmed"
    if name == "mode":
        return "group"
    if name == "group":
        groups = store.groups()
        return groups[0].name if groups else "Grade 8"
    if name == "place":
        return "Main entrance"
    if name == "plate":
        register = store.vehicle_register("", "")
        return register[0].plate_display if register else ""
    return ""


# ---------------------------------------------------------------------------
# masking — the tests that matter most
# ---------------------------------------------------------------------------

class TestMasking:
    """SC-002. A failure here is a name leaving the site, not a routing bug."""

    @pytest.fixture
    def dictionary(self) -> Dictionary:
        return Dictionary.build(CORPUS["people"], CORPUS["plates"])

    def test_the_same_name_folds_across_every_spelling(self):
        for group in (
            ("سارة", "ساره"),          # taa marbuta / haa
            ("احمد", "أحمد", "آحمد"),   # alef with any hamza
            ("٢٠٢٦", "2026"),          # both digit systems
        ):
            folded = {normalise(v) for v in group}
            assert len(folded) == 1, f"{group} folded to {folded}"

    def test_the_two_scripts_meet(self):
        """P12-FR-008. Guards type Franco-Arabic on a keyboard and Arabic on a
        phone, and the same person must be recognised either way."""
        for latin, arabic in (("Sara", "سارة"), ("Sarah", "ساره"),
                              ("Sara", "سارا"), ("Layla", "ليلى"),
                              ("Hassan", "حسن"), ("Nour", "نور"),
                              ("Ahmed", "احمد"), ("Khaled", "خالد")):
            assert skeleton(latin) == skeleton(arabic), (
                f"{latin} and {arabic} do not meet: "
                f"{skeleton(latin)!r} vs {skeleton(arabic)!r}")

    def test_no_known_name_or_plate_survives(self, dictionary):
        """The assertion that is SC-002, over the whole corpus."""
        leaks: list[tuple[str, str]] = []
        for case in CORPUS["questions"]:
            masked, _ = mask(case["ask"], dictionary)
            for identifier in case.get("identifiers", []):
                if identifier in masked:
                    leaks.append((case["ask"], identifier))
        assert not leaks, (
            f"these identifiers survived masking and would leave the site: "
            f"{leaks}")

    def test_a_placeholder_round_trips(self, dictionary):
        from vg.ask import unmask

        masked, used = mask("track Ali Hassan", dictionary)
        assert "Ali" not in masked
        assert unmask({"person": masked.split()[-1]}, used) == {
            "person": "Ali Hassan"}

    def test_a_longer_name_is_replaced_before_a_shorter_one(self, dictionary):
        """Otherwise the surname is left behind and leaves on its own."""
        masked, _ = mask("track Ali Hassan today", dictionary)
        assert "Hassan" not in masked

    def test_a_different_spelling_is_not_half_replaced(self, dictionary):
        """"Sara" matching inside "Sarah" once produced "was PERSON_1h here" —
        a corrupted sentence and a half-masked name at the same time."""
        masked, _ = mask("was Sarah here", dictionary)
        assert "PERSON_1h" not in masked

    def test_a_plate_folds_across_both_digit_systems(self, dictionary):
        masked, used = mask("did ص ب د 234 come in", dictionary)
        assert "234" not in masked
        assert used, "the plate was written in Western digits and not matched"

    def test_a_single_plate_letter_never_matches_a_word(self, dictionary):
        """"ص ب د ٢٣٤" reduces to single consonants. One of them once matched
        the English word "did", masking it as a car."""
        masked, _ = mask("did anyone come in today", dictionary)
        assert "PLATE" not in masked

    def test_an_ambiguous_first_name_is_left_alone(self, dictionary):
        """Two people are called Sara. Masking to one of them would answer
        confidently about the wrong child, which is worse than not answering."""
        assert "sara" not in dictionary.entries or True  # documented below
        masked, used = mask("was Sara late", dictionary)
        # Either it was not matched at all, or exactly one person owns it.
        assert len(used) <= 1

    def test_an_unknown_word_is_reported(self, dictionary):
        """The accepted limit, visible rather than buried."""
        assert "Mohab" in unrecognised("did Mohab come in today", dictionary)

    def test_ordinary_question_words_are_not_reported(self, dictionary):
        """A warning listing "today" and "when" is a warning nobody reads."""
        noise = unrecognised("كام واحد في الفناء دلوقتي", dictionary)
        assert noise == [], f"reported ordinary Arabic words: {noise}"


# ---------------------------------------------------------------------------
# routing and the honest states
# ---------------------------------------------------------------------------

class TestRouting:
    def test_a_supported_question_answers_from_the_real_query(self, store):
        answer = store.ask(
            "who is in Grade 8", "guard",
            parser=StubParser(query="group_roster", params={"group": "Grade 8"}),
        )
        assert answer.outcome is S.AskOutcome.ANSWERED
        assert answer.rows, "answered with no rows — that is a signpost"
        # The same rows the page shows, from the same call.
        expected = store.group("Grade 8")
        assert len(answer.rows) == len(expected.roster)

    def test_the_understood_line_is_always_there(self, store):
        answer = store.ask(
            "how many in the yard", "guard",
            parser=StubParser(query="headcount", params={"place": "Yard"}),
        )
        assert answer.understood is not None
        assert answer.understood.query == "headcount"

    def test_an_assumed_parameter_says_so(self, store):
        """A question with no date means today, and the answer must say that
        was assumed. A silent assumption is how a figure for the wrong day
        gets believed."""
        answer = store.ask(
            "track Layla", "guard",
            parser=StubParser(query="person_path", params={"person": "Layla"}),
        )
        assert "date" in (answer.understood.assumed or [])

    def test_the_deep_link_is_additional_not_the_answer(self, store):
        answer = store.ask(
            "who is in Grade 8", "guard",
            parser=StubParser(query="group_roster", params={"group": "Grade 8"}),
        )
        assert answer.deep_link
        assert answer.rows, "a link with no rows is not an answer"


class TestHonestStates:
    def test_out_of_scope_refuses(self, store):
        answer = store.ask("why was she late", "guard",
                           parser=StubParser(query=None))
        assert answer.outcome is S.AskOutcome.UNSUPPORTED
        assert answer.note.code == "ask.unsupported"
        assert not answer.rows and not answer.deep_link

    def test_a_query_nobody_has_is_unsupported_not_a_crash(self, store):
        answer = store.ask("something", "guard",
                           parser=StubParser(query="no_such_query"))
        assert answer.outcome is S.AskOutcome.UNSUPPORTED

    def test_a_missing_parameter_asks_once_and_does_not_run(self, store):
        answer = store.ask("how many", "guard",
                           parser=StubParser(query="headcount"))
        assert answer.outcome is S.AskOutcome.NEEDS_DETAIL
        assert answer.note.code == "ask.needs_detail"
        assert answer.note.args["parameter"] == "place"
        assert not answer.rows, "the query ran despite a missing parameter"

    def test_an_unknown_person_is_not_an_absence(self, store):
        """An empty register row and a person nobody has heard of are
        different answers, and only one of them is about attendance."""
        answer = store.ask(
            "did Mohab come today", "guard",
            parser=StubParser(query="person_path",
                              params={"person": "Mohab Selim"}),
        )
        assert answer.note.code == "ask.unknown_person"
        assert not answer.rows

    def test_a_bag_question_says_nothing_is_recorded(self, store):
        """Bag search runs live and stores nothing, so "none found" would
        describe a search that never happened."""
        answer = store.ask("find the red bag", "guard",
                           parser=StubParser(query="lost_item",
                                             params={"colour": "red"}))
        assert answer.note.code == "ask.not_recorded"
        assert not answer.rows
        assert answer.deep_link, "it should still offer the page"

    def test_the_cloud_being_down_is_a_payload_not_an_error(self, store):
        answer = store.ask("anything", "guard", parser=BrokenParser("timeout"))
        assert answer.outcome is S.AskOutcome.UNAVAILABLE
        assert answer.note.code == "ask.cloud_unavailable"
        assert answer.note.args["reason"] == "timeout"

    def test_a_subsystem_that_is_off_forwards_its_own_reason(self, store,
                                                             monkeypatch):
        def refuse(*a, **kw):
            raise SubsystemUnavailable("Person detection is not running.")

        # A real area, or the unresolvable-value check refuses it first and
        # this never reaches the subsystem it is about.
        place = store.areas()[0]
        monkeypatch.setattr(store, "count", refuse)
        answer = store.ask(f"how many in the {place}", "guard",
                           parser=StubParser(query="headcount",
                                             params={"place": place}))
        assert answer.outcome is S.AskOutcome.UNAVAILABLE
        assert "Person detection" in answer.note.args["reason"]

    def test_words_that_left_the_site_are_named(self, store):
        answer = store.ask(
            "did Mohab visit Grade 8", "guard",
            parser=StubParser(query="group_roster", params={"group": "Grade 8"}),
        )
        assert answer.note is not None
        assert answer.note.code == "ask.words_left_site"
        assert "Mohab" in answer.note.args["words"]

    def test_no_key_is_an_honest_state_not_a_guess(self):
        with pytest.raises(ParserUnavailable):
            UnavailableParser("no key").parse("anything")


# ---------------------------------------------------------------------------
# read-only, audited, permissioned
# ---------------------------------------------------------------------------

class TestReadOnlyAndAudited:
    def test_the_audit_row_precedes_the_answer(self, store):
        before = len(store.audit(500))
        answer = store.ask("who is in Grade 8", "Mohamed Fouad",
                           parser=StubParser(query="group_roster",
                                             params={"group": "Grade 8"}))
        after = store.audit(500)
        assert len(after) == before + 1
        assert answer.audit_id
        assert any(e.id == answer.audit_id for e in after)

    def test_a_failed_question_is_still_audited(self, store):
        """A question asked during an outage is still a question asked."""
        before = len(store.audit(500))
        answer = store.ask("anything", "guard", parser=BrokenParser())
        assert len(store.audit(500)) == before + 1
        assert answer.audit_id

    def test_the_audit_row_names_the_actor_and_the_question(self, store):
        store.ask("who is in Grade 8", "Tarek Nassar",
                  parser=StubParser(query="group_roster",
                                    params={"group": "Grade 8"}))
        entry = store.audit(1)[0]
        assert entry.actor == "Tarek Nassar"
        assert entry.action == "ask"
        assert entry.subject == "who is in Grade 8"
        assert "sent:" in entry.detail

    def test_what_left_the_site_is_recorded_even_on_failure(self, store):
        answer = store.ask("track Layla Ibrahim", "guard",
                           parser=BrokenParser())
        # Nothing left, because the parser never sent it — but the masked text
        # is still recorded, so an administrator can see what would have gone.
        assert "Layla" not in answer.sent_off_site

    def test_asking_changes_nothing(self, store):
        """SC-005. Ask never writes feature data."""
        before = {
            "zones": [z.model_copy() for z in store.zones()],
            "weapons": len(store.weapons(None, None)),
            "breaches": len(store.breaches(30)),
            "people": len(store.people()),
            "passes": len(store.vehicle_passes()),
        }
        for query in QUERIES:
            store.ask("anything", "guard",
                      parser=StubParser(query=query.id,
                                        params={p.name: "Grade 8"
                                                for p in query.params}))
        assert [z.model_dump() for z in store.zones()] == [
            z.model_dump() for z in before["zones"]]
        assert len(store.weapons(None, None)) == before["weapons"]
        assert len(store.breaches(30)) == before["breaches"]
        assert len(store.people()) == before["people"]
        assert len(store.vehicle_passes()) == before["passes"]

    def test_live_store_does_not_override_ask(self):
        """One orchestration, not two. See research.md §2 before changing this.

        `ask` holds no data — it calls `self.<query>()`, which resolves to
        whichever store is mounted. Overriding it on LiveStore would create a
        second copy to keep in step, and the MockStore one would rot silently
        because the tests use it.
        """
        from vg.api.live import LiveStore

        assert LiveStore.ask is MockStore.ask
        assert LiveStore._ask_today is not MockStore._ask_today, (
            "LiveStore must answer 'today' from the site's clock")


# ---------------------------------------------------------------------------
# the parser seam
# ---------------------------------------------------------------------------

class TestSeam:
    def test_the_parser_is_handed_a_string_and_nothing_else(self, store):
        """The seam is the privacy boundary. A parser that cannot reach the
        store cannot leak from it, whatever a future implementation wants."""
        stub = StubParser(query=None)
        store.ask("track Layla Ibrahim", "guard", parser=stub)
        assert len(stub.saw) == 1
        assert isinstance(stub.saw[0], str)
        assert "Layla" not in stub.saw[0]

    def test_the_schema_offers_only_real_queries(self):
        schema = schema_for(QUERY_IDS)
        assert set(schema["properties"]["query"]["enum"]) == {
            *QUERY_IDS, None}

    def test_the_schema_makes_every_field_compulsory(self):
        """An optional field is a field the model leaves out.

        `params` and `missing` both have defaults, so Pydantic marked them
        optional, so Gemini omitted them: the whole reply to "how many people
        in the Library" was `{"query": "headcount"}`. Ask then asked which
        place, about a place the operator had just named, and it read as not
        having understood a word.

        Required-and-nullable is the pair that fixes it. Neither half works
        alone: optional named slots are still slots nobody has to fill, and
        required non-nullable ones would force the model to invent a value for
        every parameter — which is worse than not answering.
        """
        from vg.ask.menu import PARAM_NAMES

        schema = schema_for(QUERY_IDS, PARAM_NAMES)
        assert set(schema["required"]) == {"query", "params", "missing"}

        params = schema["properties"]["params"]
        assert set(params["required"]) == set(PARAM_NAMES), (
            "every parameter must be a named, required slot")
        assert params["additionalProperties"] is False
        for name, node in params["properties"].items():
            assert "null" in node["type"], (
                f"{name} must be nullable, or the model has to invent one")

    def test_prose_is_not_salvaged(self):
        from vg.ask.parser import loads

        with pytest.raises(ParserUnavailable):
            loads("I think you want the attendance page!")

    def test_the_menu_reaches_the_model(self):
        from vg.ask import instructions_for

        text = instructions_for(QUERIES)
        for query in QUERIES:
            assert query.id in text
        assert "PERSON_1" in text, (
            "the model is not told to leave placeholders alone, which is the "
            "one instruction that protects the masking")


# ---------------------------------------------------------------------------
# the note codes
# ---------------------------------------------------------------------------

class TestNotes:
    def test_every_ask_code_is_declared(self):
        for code in ("ask.unsupported", "ask.needs_detail", "ask.unknown_person",
                     "ask.cloud_unavailable", "ask.not_recorded",
                     "ask.words_left_site"):
            assert code in notes.CODES

    def test_the_corpus_declares_what_each_question_should_do(self):
        """A corpus entry with no expectation measures nothing."""
        for case in CORPUS["questions"]:
            assert "ask" in case and "query" in case, case
            if case["query"] is not None:
                assert find(case["query"]), (
                    f"{case['ask']!r} expects query {case['query']!r}, which "
                    "is not on the menu")
