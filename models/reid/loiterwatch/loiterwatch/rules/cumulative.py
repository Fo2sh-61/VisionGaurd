"""Total time in a zone, summed across separate visits.

Stitching identities is only half the fix for someone stepping out and back.
The other half is this rule: `dwell` measures one continuous stay, so a person
who leaves for longer than `exit_grace_s` restarts it no matter how stable their
ID is. Cumulative dwell adds their visits up instead, which is what you want
when the absences are the behaviour rather than an interruption to it.
"""
from __future__ import annotations

from typing import Any

from ..alerts import Alert
from .base import Rule, RuleContext, register
from .dwell import _fmt


@register
class CumulativeDwellRule(Rule):
    type_name = "cumulative_dwell"

    def __init__(
        self,
        rule_id: str,
        threshold_s: float = 180.0,
        window_s: float = 900.0,
        min_visit_s: float = 0.0,
        **kw: Any,
    ) -> None:
        super().__init__(rule_id, **kw)
        self.threshold_s = float(threshold_s)
        self.window_s = float(window_s)
        self.min_visit_s = float(min_visit_s)
        self._armed: dict[tuple[str, str], bool] = {}

    def check(self, ctx: RuleContext) -> list[Alert]:
        out: list[Alert] = []
        window_start = ctx.now - self.window_s
        for zone in self.target_zones(ctx.world):
            for track_id in set(zone.history) | set(zone.active):
                visits = [
                    v for v in zone.visits(track_id)
                    if v.entered_at >= window_start
                    and v.dwell(ctx.now) >= self.min_visit_s
                ]
                if not visits:
                    continue
                total = sum(v.dwell(ctx.now) for v in visits)
                key = (zone.zone, track_id)
                if total < self.threshold_s:
                    self._armed[key] = True     # re-arm as old visits age out
                    continue
                if not self._armed.get(key, True):
                    continue
                self._armed[key] = False
                evidence = {
                    "total_dwell_s": round(total, 1),
                    "total_human": _fmt(total),
                    "threshold_s": self.threshold_s,
                    "window_s": self.window_s,
                    "visits": len(visits),
                    "entered_at": visits[0].entered_at,
                }
                msg = (
                    f"CUMULATIVE LOITERING: track {track_id} spent {_fmt(total)} "
                    f"in '{zone.zone}' across {len(visits)} visit(s) "
                    f"(threshold {_fmt(self.threshold_s)} in {int(self.window_s)}s)"
                )
                out.append(self.alert(
                    ctx, zone.zone, track_id, msg, evidence,
                    dedup_key=f"{self.rule_id}:{zone.zone}:{track_id}",
                ))
        return out
