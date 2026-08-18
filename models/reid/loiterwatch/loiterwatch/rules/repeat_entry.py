"""Repeat entry/exit rule: casing behaviour -- same track circling back."""
from __future__ import annotations

from typing import Any

from ..alerts import Alert
from ..state import Visit
from .base import Rule, RuleContext, register


@register
class RepeatEntryRule(Rule):
    """Fires when one track enters a zone `count` times within `window_s`.

    `min_visit_s` drops drive-by blips, `min_gap_s` requires the person to have
    actually been away between visits (guards against tracker flicker that the
    exit grace period did not absorb).
    """

    type_name = "repeat_entry"

    def __init__(
        self,
        rule_id: str,
        count: int = 3,
        window_s: float = 600.0,
        min_visit_s: float = 0.0,
        min_gap_s: float = 0.0,
        **kw: Any,
    ) -> None:
        super().__init__(rule_id, **kw)
        self.count = int(count)
        self.window_s = float(window_s)
        self.min_visit_s = float(min_visit_s)
        self.min_gap_s = float(min_gap_s)
        self._fired: dict[tuple[str, str], float] = {}

    def _qualifying(self, visits: list[Visit], now: float) -> list[Visit]:
        window_start = now - self.window_s
        kept: list[Visit] = []
        for visit in visits:
            if visit.entered_at < window_start:
                continue
            if visit.dwell(now) < self.min_visit_s:
                continue
            if kept and self.min_gap_s > 0:
                prev = kept[-1]
                gap = visit.entered_at - (prev.exited_at or prev.last_seen)
                if gap < self.min_gap_s:
                    continue
            kept.append(visit)
        return kept

    def check(self, ctx: RuleContext) -> list[Alert]:
        out: list[Alert] = []
        for zone in self.target_zones(ctx.world):
            track_ids = set(zone.history) | set(zone.active)
            for track_id in track_ids:
                visits = self._qualifying(zone.visits(track_id), ctx.now)
                if len(visits) < self.count:
                    continue
                latest = visits[-1]
                key = (zone.zone, track_id)
                if self._fired.get(key) == latest.entered_at:
                    continue
                self._fired[key] = latest.entered_at
                span = latest.entered_at - visits[0].entered_at
                evidence = {
                    "entries": len(visits),
                    "count_threshold": self.count,
                    "window_s": self.window_s,
                    "span_s": round(span, 1),
                    "entry_times": [round(v.entered_at, 1) for v in visits],
                    "total_dwell_s": round(sum(v.dwell(ctx.now) for v in visits), 1),
                }
                msg = (
                    f"REPEAT ENTRY: track {track_id} entered '{zone.zone}' "
                    f"{len(visits)}x in {int(span)}s (threshold {self.count} "
                    f"in {int(self.window_s)}s)"
                )
                out.append(
                    self.alert(
                        ctx, zone.zone, track_id, msg, evidence,
                        dedup_key=f"{self.rule_id}:{zone.zone}:{track_id}:{latest.entered_at}",
                    )
                )
        return out
