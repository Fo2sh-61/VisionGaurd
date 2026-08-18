"""Rule base class, shared gating, and the rule-type registry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..alerts import Alert, Severity
from ..state import WorldState, ZoneState

_WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


@dataclass
class RuleContext:
    world: WorldState
    now: float


def _minutes(hhmm: str) -> int:
    hh, mm = hhmm.strip().split(":")
    return int(hh) * 60 + int(mm)


class Rule:
    """Base class. Subclasses implement `check()`.

    Common config handled here: zone targeting, severity, cooldown, minimum
    detector confidence, and time-of-day / weekday gating (loitering at 03:00
    means something different than loitering at 13:00).
    """

    type_name = "base"

    def __init__(
        self,
        rule_id: str,
        zones: Iterable[str] | None = None,
        severity: str = "warning",
        cooldown_s: float = 300.0,
        min_confidence: float = 0.0,
        active_hours: dict[str, str] | None = None,
        weekdays: Iterable[str] | None = None,
        enabled: bool = True,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        self.rule_id = rule_id
        self.zones = list(zones) if zones else None  # None == all zones
        self.severity = Severity(severity)
        self.cooldown_s = float(cooldown_s)
        self.min_confidence = float(min_confidence)
        self.enabled = bool(enabled)
        self.message_template = message
        self.weekdays = (
            {_WEEKDAYS[d.lower()[:3]] for d in weekdays} if weekdays else None
        )
        self._hours: tuple[int, int] | None = None
        if active_hours:
            self._hours = (_minutes(active_hours["start"]), _minutes(active_hours["end"]))
        self.extra = extra

    # -- gating ------------------------------------------------------------
    def in_schedule(self, ts: float) -> bool:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if self.weekdays is not None and dt.weekday() not in self.weekdays:
            return False
        if self._hours is None:
            return True
        start, end = self._hours
        cur = dt.hour * 60 + dt.minute
        return start <= cur < end if start <= end else (cur >= start or cur < end)

    def target_zones(self, world: WorldState) -> list[ZoneState]:
        if self.zones is None:
            return list(world.zones.values())
        return [world.zone(name) for name in self.zones if name in world.zones]

    # -- api ---------------------------------------------------------------
    def evaluate(self, ctx: RuleContext) -> list[Alert]:
        if not self.enabled or not self.in_schedule(ctx.now):
            return []
        return self.check(ctx)

    def check(self, ctx: RuleContext) -> list[Alert]:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------
    def alert(
        self,
        ctx: RuleContext,
        zone: str,
        track_id: str | None,
        message: str,
        evidence: dict[str, Any],
        dedup_key: str,
        severity: Severity | None = None,
    ) -> Alert:
        if self.message_template:
            try:
                message = self.message_template.format(
                    zone=zone, track_id=track_id, **evidence
                )
            except (KeyError, IndexError):
                pass
        return Alert(
            ts=ctx.now,
            rule_id=self.rule_id,
            rule_type=self.type_name,
            severity=severity or self.severity,
            zone=zone,
            track_id=track_id,
            message=message,
            evidence=evidence,
            dedup_key=dedup_key,
        )


RULE_TYPES: dict[str, type[Rule]] = {}


def register(cls: type[Rule]) -> type[Rule]:
    RULE_TYPES[cls.type_name] = cls
    return cls


def build_rule(spec: dict[str, Any]) -> Rule:
    spec = dict(spec)
    type_name = spec.pop("type", None)
    if type_name is None:
        raise ValueError(f"rule {spec.get('id')!r} is missing a 'type'")
    if type_name not in RULE_TYPES:
        known = ", ".join(sorted(RULE_TYPES))
        raise ValueError(f"unknown rule type {type_name!r}; known types: {known}")
    rule_id = spec.pop("id", type_name)
    return RULE_TYPES[type_name](rule_id=rule_id, **spec)
