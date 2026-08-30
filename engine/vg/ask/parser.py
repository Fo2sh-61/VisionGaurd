"""The seam: a masked question in, a menu choice out.

**This module is the privacy boundary, not just a tidiness boundary.** A parser
is handed a `str` and nothing else — not the store, not a camera, not a frame,
not the signed-in account. An implementation cannot reach data even if a future
one wanted to, and that is enforced by the signature rather than by a rule
somebody has to remember.

It is also the swap point (P12-FR-022). Two implementations ship today:

    UnavailableParser   no key configured. Says so. What every test and every
                        keyless developer runs against, so the honest path is
                        the well-trodden one rather than an afterthought.
    CloudParser         Google Gemini, constrained to a JSON schema.

A local model later is a third, and nothing outside this file changes.

Note what this module does **not** import: `vg.ask.menu`, `vg.api.store`, or
anything else in the engine. The menu arrives as an argument.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class ParserUnavailable(RuntimeError):
    """The parser could not be reached, or refused.

    Carries a **reason**, because "Ask is temporarily unavailable" on its own
    tells an operator nothing about whether to try again in ten seconds or to
    go and find the page themselves.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Parsed(BaseModel):
    """Everything a parser is allowed to say. Nothing else is representable.

    This is the JSON schema handed to the model, so the shape here *is* the
    contract — there is no second definition to drift out of step with it.

    Three states, and they are mutually exclusive in practice:

        query set, missing None    a query to run
        query set, missing set     the right query, one parameter short
        query None                 not something Ask can answer

    A `query` outside the menu is treated as "unsupported" by the caller. That
    is not a retry: a model that named a query nobody has is guessing, and
    asking it again would only get a different guess.
    """

    query: str | None = Field(
        default=None,
        description=(
            "The id of the single supported query this question is asking for, "
            "exactly as spelled in the menu. Null if the question is not one of "
            "them."
        ),
    )
    params: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "The parameters for that query, copied from the question. Leave "
            "placeholders such as PERSON_1 or PLATE_1 exactly as they appear — "
            "they are resolved after you answer and must not be altered, "
            "translated or guessed at."
        ),
    )
    missing: str | None = Field(
        default=None,
        description=(
            "The name of the one parameter the query needs and the question "
            "does not give. Null when nothing is missing. Never invent a value "
            "for it."
        ),
    )


def schema_for(query_ids: tuple[str, ...]) -> dict[str, Any]:
    """`Parsed`'s JSON schema, with `query` narrowed to the real menu.

    One Pydantic class, one schema, and the menu injected at the point of use
    so `menu.py` stays the single place a query is declared. Constraining the
    enum server-side means an id that does not exist is rejected by the
    provider before it ever reaches us — cheaper than validating it here, and
    it means the model is told what its options are in the only place it
    cannot ignore.
    """
    schema = Parsed.model_json_schema()
    node = schema.get("properties", {}).get("query", {})
    # Pydantic renders `str | None` as anyOf; replace the whole node rather
    # than trying to reach into one branch of it.
    node.pop("anyOf", None)
    node.update({"type": ["string", "null"], "enum": [*query_ids, None]})
    return schema


class Parser(Protocol):
    """Turn a masked question into a menu choice.

    Raise `ParserUnavailable` when the answer cannot be obtained at all. Do
    **not** decide how that is shown — the caller owns every sentence.
    """

    def parse(self, masked_question: str) -> Parsed: ...


class UnavailableParser:
    """What you get with no key configured, or with Ask switched off.

    Deliberately not a silent no-op and deliberately not a guess. Ask says it
    is unavailable and says why, which is the honest state the spec asks for
    and the one a developer without a key exercises all day.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def parse(self, masked_question: str) -> Parsed:
        raise ParserUnavailable(self._reason)


def loads(raw: str) -> Parsed:
    """Validate a provider's JSON reply into a `Parsed`.

    Shared by every cloud implementation, and the reason a malformed reply is
    never a crash: a provider that returns prose, truncated JSON or a field we
    did not ask for fails validation here, and the caller turns that into
    "unsupported" rather than trying to salvage a sentence.
    """
    try:
        return Parsed.model_validate(json.loads(raw))
    except Exception as exc:                       # noqa: BLE001 — see below
        # Broad on purpose: json raises ValueError, pydantic raises
        # ValidationError, and a provider returning None raises TypeError.
        # They all mean the same thing to us — the model did not answer in the
        # shape it was given — and they all lead to the same honest outcome.
        log.warning("ask: unparseable reply from the parser: %s", exc)
        raise ParserUnavailable("malformed") from exc


class CloudParser:
    """Google Gemini, constrained to a JSON schema.

    The model is given two things and nothing else: the menu, and one masked
    sentence. It answers with a `Parsed` or it fails — there is no path here
    that turns prose into a query, because a model that replied with prose did
    not understand the contract and its guess is worth nothing.

    **The schema is the menu.** `query` is an enum of the real ids, so an id
    nobody has is rejected by the provider before it reaches us.
    """

    def __init__(self, model: str, api_key: str, query_ids: tuple[str, ...],
                 instructions: str, timeout_seconds: float = 8.0) -> None:
        self._model = model
        self._api_key = api_key
        self._schema = schema_for(query_ids)
        self._instructions = instructions
        self._timeout = timeout_seconds

    def parse(self, masked_question: str) -> Parsed:
        # Imported here, not at module scope: a site with no key never installs
        # a reason to import it, and `vg.ask` is imported by the store on every
        # question whether or not Ask is switched on.
        try:
            from google import genai
        except ImportError as exc:                 # pragma: no cover
            raise ParserUnavailable("the Gemini SDK is not installed") from exc

        client = genai.Client(api_key=self._api_key)
        try:
            reply = client.interactions.create(
                model=self._model,
                input=f"{self._instructions}\n\nQuestion: {masked_question}",
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": self._schema,
                },
            )
        except Exception as exc:                   # noqa: BLE001
            # Every provider failure is the same answer to an operator — Ask
            # cannot read the question right now — and they differ only in the
            # reason, which travels through to the screen. Narrowing this to
            # the SDK's exception classes would let one unlisted class escape
            # as a 500, and a 500 on this endpoint is the one thing the
            # contract forbids.
            raise ParserUnavailable(_reason(exc)) from exc

        text = getattr(reply, "output_text", None) or str(reply)
        return loads(text)


def _reason(exc: Exception) -> str:
    """A short, honest word for what went wrong. Never the raw exception.

    The reason reaches a guard's screen through a note argument, so it must
    not carry a stack trace, a URL or an API key — and "429" means nothing to
    anybody standing at a gate.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text or "deadline" in text:
        return "timeout"
    if "429" in text or "quota" in text or "rate" in text:
        return "busy"
    if "401" in text or "403" in text or "api key" in text or "permission" in text:
        return "refused"
    if "connect" in name or "connection" in text or "network" in text:
        return "offline"
    return "error"


def build_parser() -> Parser:
    """The parser this site can actually use right now.

    Reads the config and the environment on every call rather than caching:
    an operator who switches Ask off, or a key that is removed, must change
    the answer immediately. A cached parser would go on claiming to work.
    """
    try:
        from vg import config as vgconfig

        cfg = vgconfig.load()
    except Exception as exc:                       # noqa: BLE001
        # No readable engine.yaml — a bare test process, usually. Ask is not
        # the feature that should shout about it.
        log.debug("ask: no config, parser unavailable (%s)", exc)
        return UnavailableParser("no configuration")

    if not cfg.ask.enabled:
        return UnavailableParser("switched off")

    import os

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return UnavailableParser("no key")

    from vg.ask.menu import QUERIES, QUERY_IDS

    return CloudParser(
        model=cfg.ask.model,
        api_key=key,
        query_ids=QUERY_IDS,
        instructions=instructions_for(QUERIES),
        timeout_seconds=cfg.ask.timeout_seconds,
    )


def instructions_for(queries) -> str:
    """The menu, written out for the model. Stable across every question.

    Kept separate from the question so the two can be cached separately by any
    provider that supports it — the menu never changes, and the question
    always does.

    It says what to do and, more importantly, what not to: no prose, no
    inventing a value, and placeholders left exactly as they are. A model that
    "helpfully" expands PERSON_1 into a guessed name would defeat the masking
    entirely.
    """
    lines = [
        "You route a security operator's question to exactly one supported "
        "query. You never answer the question yourself and you never see any "
        "data — something else runs the query and shows the real result.",
        "",
        "The question may be in Arabic (Modern Standard or Egyptian dialect), "
        "Franco-Arabic written in Latin letters, English, or a mixture.",
        "",
        "Rules:",
        "- Choose exactly one query id from the list, or null if the question "
        "is not one of them. Never invent an id.",
        "- The system records WHAT happened, never WHY, and never what will "
        "happen. Answer null for any question asking for a reason, a cause, a "
        "motive, an opinion, a judgement or a prediction — 'why was she late', "
        "'is he a good student', 'what will happen tomorrow'. These look like "
        "supported questions because they name a person and a day, and "
        "answering one with the register would give a true answer to a "
        "question nobody asked.",
        "- If the question clearly means one of the queries but leaves out "
        "something it needs, still choose that query and name the missing "
        "parameter in `missing`. Do NOT answer null. 'How many?' with no place "
        "is a headcount missing its place, not an unsupported question.",
        "- Copy parameter values from the question. Never invent one.",
        "- Tokens like PERSON_1 and PLATE_1 are placeholders for real names "
        "and plates. Copy them EXACTLY. Never translate, expand or guess what "
        "they stand for.",
        "- If the query needs a parameter the question does not give, name it "
        "in `missing` and leave it out of `params`.",
        "",
        "The queries:",
    ]
    for q in queries:
        params = ", ".join(
            f"{p.name} ({p.describe}){' [required]' if p.required else ''}"
            for p in q.params
        ) or "no parameters"
        lines.append(f"- {q.id}: {q.describe}\n    parameters: {params}")
    return "\n".join(lines)
