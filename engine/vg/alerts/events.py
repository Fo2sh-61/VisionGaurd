"""What happened, as a message may say it - and nothing else.

An `AlertEvent` is the only thing the sender ever reads, and the catalogue
builds every word of every message from one. So the event's shape is where
"nothing about a minor leaves the building" is enforced (constitution IV,
spec P9-FR-008): `facts` accepts a short, fixed vocabulary, and a key outside
it is refused when the event is made. There is no field a student's name, a
face, a snapshot or a file path could travel in. Plate text and a staff
member's name are facts and are allowed by name.

Each event also carries the key the delivery log files it under. The log is
the ledger: an event whose key already has rows is not sent again, which is
what makes a restart harmless.

This module also holds the two rules that more than one caller needs - which
cameras have been dark long enough to say so, and which days are school
days - so that Home and the sender cannot disagree about either.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

#: The five kinds an administrator can switch a channel on for.
KINDS: tuple[str, ...] = ("weapon", "intrusion", "vehicles", "camera", "attendance")

#: The channels that leave the building. In-app is not one: it is Home's list.
#: WhatsApp and SMS were removed on 11 Sep 2026; email is the only courier.
CHANNELS: tuple[str, ...] = ("email",)

#: Why a gate pass is an alert, as `VehicleStore` decides it.
GATE_REASONS: tuple[str, ...] = ("blacklist", "unknown", "expired")

#: Every fact a message may carry. Adding one here is adding something that
#: leaves the site: it needs a reason in the spec, not just a use.
ALLOWED_FACTS: frozenset[str] = frozenset({
    "confidence",   # 0..1 - the knife model's, or the plate reader's
    "verdict",      # confirmed | dismissed
    "reviewer",     # the staff account that decided
    "plate",        # plate text as displayed; a plate is not a person
    "gate",         # gate number
    "reason",       # blacklist | unknown | expired
    "weak_read",    # the plate reader was not sure of its reading
    "since",        # when an entry or an outage began
})


@dataclass(frozen=True)
class GroupCount:
    """One group's line in the noon report. A group, never a person."""

    name: str
    present: int
    late: int
    absent: int


@dataclass(frozen=True, eq=False)
class AlertEvent:
    """One thing that happened, in the only terms a message may use.

    `camera_name` is empty when the event is made - on a camera thread, where
    nothing but the id is at hand - and filled by the sender thread.
    `groups` is the report's counts; `None` means attendance is not being
    recorded, so there are no counts to send.
    """

    kind: str
    template: str
    event_key: str
    at: datetime
    camera_id: str | None = None
    camera_name: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    groups: tuple[GroupCount, ...] | None = ()
    recipient_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS and self.kind != "test":
            raise ValueError(f"unknown alert kind {self.kind!r}")
        stray = sorted(set(self.facts) - ALLOWED_FACTS)
        if stray:
            raise ValueError(
                f"facts {stray} are not allowed in a message; only "
                f"{sorted(ALLOWED_FACTS)} may leave the site")
        # Read-only from here on, so nothing can add a key after the check.
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))
        if self.groups is not None:
            object.__setattr__(self, "groups", tuple(self.groups))


def stamp(when: datetime) -> str:
    """An instant as a compact UTC stamp: no colons, so keys split cleanly."""
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# one constructor per event, so a key is spelled in exactly one place
# ---------------------------------------------------------------------------

def weapon_opened(scene_id: str, camera_id: str, at: datetime,
                  confidence: float) -> AlertEvent:
    return AlertEvent(
        kind="weapon", template="weapon.opened",
        event_key=f"weapon:{scene_id}:opened", at=at, camera_id=camera_id,
        facts={"confidence": float(confidence)},
    )


def weapon_verdict(scene_id: str, camera_id: str, at: datetime, verdict: str,
                   reviewer: str, since: datetime | None = None) -> AlertEvent:
    if verdict not in ("confirmed", "dismissed"):
        raise ValueError(f"a verdict is confirmed or dismissed, not {verdict!r}")
    facts: dict[str, Any] = {"verdict": verdict, "reviewer": reviewer}
    if since is not None:
        facts["since"] = since
    return AlertEvent(
        kind="weapon", template=f"weapon.{verdict}",
        event_key=f"weapon:{scene_id}:verdict", at=at, camera_id=camera_id,
        facts=facts,
    )


def opening_key(verdict: AlertEvent) -> str:
    """The key of the "awaiting review" message a verdict follows."""
    return verdict.event_key.rsplit(":", 1)[0] + ":opened"


def intrusion_opened(scene_id: str, camera_id: str, at: datetime) -> AlertEvent:
    return AlertEvent(
        kind="intrusion", template="intrusion.opened",
        event_key=f"intrusion:{scene_id}", at=at, camera_id=camera_id,
    )


def gate_alert(pass_id: str, camera_id: str, at: datetime, plate: str,
               gate: int, reason: str, confidence: float,
               weak_read: bool) -> AlertEvent:
    if reason not in GATE_REASONS:
        raise ValueError(f"a gate alert is one of {GATE_REASONS}, not {reason!r}")
    return AlertEvent(
        kind="vehicles", template=f"vehicles.{reason}",
        event_key=f"vehicles:{pass_id}", at=at, camera_id=camera_id,
        facts={"plate": plate, "gate": int(gate), "reason": reason,
               "confidence": float(confidence), "weak_read": bool(weak_read)},
    )


def camera_down(camera_id: str, since: datetime) -> AlertEvent:
    return AlertEvent(
        kind="camera", template="camera.down",
        event_key=f"camera:{camera_id}:down:{stamp(since)}", at=since,
        camera_id=camera_id, facts={"since": since},
    )


def camera_up(camera_id: str, at: datetime) -> AlertEvent:
    return AlertEvent(
        kind="camera", template="camera.up",
        event_key=f"camera:{camera_id}:up:{stamp(at)}", at=at, camera_id=camera_id,
    )


def camera_item_id(camera_id: str, since: datetime) -> str:
    """Home's id for one outage. A new outage is a new item."""
    return f"camera:{camera_id}:{stamp(since)}"


def attendance_report(day: str, at: datetime,
                      groups: tuple[GroupCount, ...] | None) -> AlertEvent:
    return AlertEvent(
        kind="attendance", template="attendance.report",
        event_key=f"attendance:{day}", at=at, groups=groups,
    )


def test_message(recipient_id: str, at: datetime) -> AlertEvent:
    return AlertEvent(
        kind="test", template="test",
        event_key=f"test:{recipient_id}:{uuid.uuid4().hex}", at=at,
        recipient_id=recipient_id,
    )


# ---------------------------------------------------------------------------
# rules more than one caller needs
# ---------------------------------------------------------------------------

def offline_cameras(workers: Mapping[str, Any], now: datetime, minutes: float,
                    started_at: datetime) -> dict[str, datetime]:
    """Cameras showing NO SIGNAL for at least `minutes`, and since when.

    `status` is the camera's own word; anything but `ok` is dark. The outage
    is timed from the last frame that arrived - or from `started_at` when none
    has since the engine started - so `since` stays put while the camera stays
    dark. A `since` that moved would make every tick a new outage.
    """
    out: dict[str, datetime] = {}
    for camera_id, worker in workers.items():
        try:
            if worker.status == "ok":
                continue
            health = getattr(getattr(worker, "source", None), "health", None)
            last = getattr(health, "last_frame_at", None) or started_at
        except Exception:     # a worker being torn down mid-read is not an outage
            continue
        if (now - last).total_seconds() >= minutes * 60:
            out[camera_id] = last
    return out


def _term(term_from: str, term_to: str) -> tuple[date, date] | None:
    try:
        start = date.fromisoformat(str(term_from).strip()) if term_from else None
        end = date.fromisoformat(str(term_to).strip()) if term_to else None
    except ValueError:
        return None
    if start is None or end is None:
        return None
    return start, end


def report_state(day: date, term_from: str, term_to: str) -> str:
    """Why the noon report will or will not go out, in one word Settings words.

    `scheduled` | `no_term_dates` | `before_term` | `after_term`.
    """
    term = _term(term_from, term_to)
    if term is None:
        return "no_term_dates"
    if day < term[0]:
        return "before_term"
    if day > term[1]:
        return "after_term"
    return "scheduled"


def is_school_day(day: date, term_from: str, term_to: str,
                  working_days: frozenset[int]) -> bool:
    """One of the working days, inside the term. No term dates: no school day.

    The days are Settings' (`HoursConfig.working_days`), not a constant here.
    """
    return (report_state(day, term_from, term_to) == "scheduled"
            and day.weekday() in working_days)
