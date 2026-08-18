"""Intrusion rule: the whole camera view is the restricted area.

Use this when there is no meaningful sub-zone to draw -- anyone visible to the
camera is already somewhere they should not be. Presence itself is the event, so
the only real question is how long you wait before believing the detector.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..alerts import Alert
from .base import register
from .dwell import DwellRule


@register
class IntrusionRule(DwellRule):
    """Fires once presence is confirmed, then optionally escalates.

    `confirm_s` exists purely to reject detector noise -- a single frame of a
    reflection or a blowing bag should not page anyone. Two or three seconds of
    consistent detections is usually enough.

    `cleared_by` lets an authorization signal (badge swipe, disarm code) cancel
    the alert for people who are supposed to be there.
    """

    type_name = "intrusion"
    headline = "INTRUSION"
    phrase = "in restricted area"

    def __init__(
        self,
        rule_id: str,
        confirm_s: float = 3.0,
        escalate: list[dict[str, Any]] | None = None,
        cleared_by: Iterable[str] = (),
        min_observations: int = 3,
        **kw: Any,
    ) -> None:
        kw.setdefault("severity", "critical")
        kw.setdefault("min_confidence", 0.5)
        levels = [{"after_s": float(confirm_s), "severity": kw["severity"]}]
        levels += list(escalate or [])
        super().__init__(
            rule_id, thresholds=levels, min_observations=min_observations, **kw
        )
        self.confirm_s = float(confirm_s)
        self.cleared_by = set(cleared_by)

    def check(self, ctx) -> list[Alert]:
        alerts = super().check(ctx)
        if not self.cleared_by:
            return alerts
        kept: list[Alert] = []
        for alert in alerts:
            zone = ctx.world.zone(alert.zone)
            visit = zone.active.get(alert.track_id or "")
            if visit is not None and visit.signals & self.cleared_by:
                continue  # authorized presence
            kept.append(alert)
        return kept
