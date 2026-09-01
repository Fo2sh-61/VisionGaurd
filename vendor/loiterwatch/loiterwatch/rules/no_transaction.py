"""Presence without the business event that would explain it.

The strongest ATM signal in practice: someone standing at the machine who never
inserts a card. Requires the ATM/POS/door controller to emit SIGNAL events.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..alerts import Alert
from .base import Rule, RuleContext, register
from .dwell import _fmt


@register
class NoTransactionRule(Rule):
    type_name = "no_transaction"

    def __init__(
        self,
        rule_id: str,
        dwell_s: float = 45.0,
        expects: Iterable[str] = ("transaction_complete",),
        scope: str = "track",
        lead_in_s: float = 5.0,
        **kw: Any,
    ) -> None:
        super().__init__(rule_id, **kw)
        self.dwell_s = float(dwell_s)
        self.expects = set(expects)
        if scope not in ("track", "zone"):
            raise ValueError("scope must be 'track' or 'zone'")
        self.scope = scope
        #: signals landing slightly before the track was first seen still count
        self.lead_in_s = float(lead_in_s)
        self._fired: dict[tuple[str, str, float], bool] = {}

    def check(self, ctx: RuleContext) -> list[Alert]:
        out: list[Alert] = []
        for zone in self.target_zones(ctx.world):
            for track_id, visit in list(zone.active.items()):
                dwell = visit.dwell(ctx.now)
                if dwell < self.dwell_s:
                    continue
                key = (zone.zone, track_id, visit.entered_at)
                if self._fired.get(key):
                    continue
                if self.scope == "track":
                    satisfied = bool(visit.signals & self.expects)
                else:
                    satisfied = bool(
                        zone.signals_between(
                            visit.entered_at - self.lead_in_s, ctx.now, self.expects
                        )
                    )
                if satisfied:
                    self._fired[key] = True  # explained; stop checking this visit
                    continue
                self._fired[key] = True
                evidence = {
                    "entered_at": visit.entered_at,
                    "dwell_s": round(dwell, 1),
                    "dwell_human": _fmt(dwell),
                    "threshold_s": self.dwell_s,
                    "expected_signals": sorted(self.expects),
                    "observed_signals": sorted(visit.signals),
                    "scope": self.scope,
                }
                msg = (
                    f"UNEXPLAINED PRESENCE: track {track_id} at '{zone.zone}' for "
                    f"{_fmt(dwell)} with no {'/'.join(sorted(self.expects))}"
                )
                out.append(
                    self.alert(
                        ctx, zone.zone, track_id, msg, evidence,
                        dedup_key=f"{self.rule_id}:{zone.zone}:{track_id}:{visit.entered_at}",
                    )
                )
        return out
