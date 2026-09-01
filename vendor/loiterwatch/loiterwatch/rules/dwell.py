"""Dwell-time rule: continuous presence in a zone beyond a threshold."""
from __future__ import annotations

from typing import Any

from ..alerts import Alert, Severity
from .base import Rule, RuleContext, register


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


@register
class DwellRule(Rule):
    """Fires when a track stays in a zone longer than `threshold_s`.

    Supports escalation: `thresholds: [{after_s: 180, severity: warning},
    {after_s: 600, severity: critical}]`. Only the highest newly-crossed level
    fires on any given evaluation.
    """

    type_name = "dwell"
    headline = "LOITERING"
    phrase = "present in"

    def __init__(
        self,
        rule_id: str,
        threshold_s: float | None = None,
        thresholds: list[dict[str, Any]] | None = None,
        min_observations: int = 2,
        repeat_every_s: float | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(rule_id, **kw)
        levels: list[tuple[float, Severity, str | None]] = []
        if thresholds:
            for lvl in thresholds:
                levels.append(
                    (
                        float(lvl["after_s"]),
                        Severity(lvl.get("severity", self.severity.value)),
                        lvl.get("message"),
                    )
                )
        if threshold_s is not None:
            levels.append((float(threshold_s), self.severity, None))
        if not levels:
            raise ValueError(f"dwell rule {rule_id!r} needs threshold_s or thresholds")
        self.levels = sorted(levels, key=lambda t: t[0])
        self.min_observations = int(min_observations)
        self.repeat_every_s = float(repeat_every_s) if repeat_every_s else None
        # (zone, track, entered_at) -> (highest level index fired, last alert ts)
        self._fired: dict[tuple[str, str, float], tuple[int, float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - 3600
        for key in [k for k in self._fired if k[2] < cutoff]:
            del self._fired[key]

    def check(self, ctx: RuleContext) -> list[Alert]:
        self._prune(ctx.now)
        out: list[Alert] = []
        for zone in self.target_zones(ctx.world):
            for track_id, visit in list(zone.active.items()):
                if visit.observations < self.min_observations:
                    continue
                if visit.max_confidence < self.min_confidence:
                    continue
                dwell = visit.dwell(ctx.now)
                crossed = [i for i, lvl in enumerate(self.levels) if dwell >= lvl[0]]
                if not crossed:
                    continue
                top = crossed[-1]
                key = (zone.zone, track_id, visit.entered_at)
                prev_idx, prev_ts = self._fired.get(key, (-1, 0.0))
                repeat_due = (
                    self.repeat_every_s is not None
                    and prev_idx >= 0
                    and ctx.now - prev_ts >= self.repeat_every_s
                )
                if top <= prev_idx and not repeat_due:
                    continue
                after_s, severity, template = self.levels[top]
                self._fired[key] = (max(top, prev_idx), ctx.now)
                evidence = {
                    "entered_at": visit.entered_at,
                    "dwell_s": round(dwell, 1),
                    "dwell_human": _fmt(dwell),
                    "threshold_s": after_s,
                    "observations": visit.observations,
                    "confidence": round(visit.max_confidence, 3),
                    "level": top,
                }
                msg = template or (
                    f"{self.headline}: track {track_id} {self.phrase} "
                    f"'{zone.zone}' for {_fmt(dwell)} (threshold {_fmt(after_s)})"
                )
                if template:
                    try:
                        msg = template.format(zone=zone.zone, track_id=track_id, **evidence)
                    except (KeyError, IndexError):
                        pass
                out.append(
                    self.alert(
                        ctx, zone.zone, track_id, msg, evidence,
                        dedup_key=f"{self.rule_id}:{zone.zone}:{track_id}:{visit.entered_at}:{top}",
                        severity=severity,
                    )
                )
        return out
