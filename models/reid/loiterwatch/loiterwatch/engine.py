"""The evaluation loop: events in, alerts out."""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from .alerts import Alert
from .events import Event, EventKind
from .rules.base import Rule, RuleContext
from .state import WorldState

AlertSink = Callable[[Alert], None]


class Engine:
    """Stateful, single-threaded, deterministic.

    Deterministic matters: replaying the same event log always produces the same
    alerts, which is what makes rule tuning and incident review possible.
    """

    def __init__(
        self,
        rules: Sequence[Rule],
        exit_grace: float = 3.0,
        tick_s: float = 1.0,
        max_steps_per_event: int = 5000,
        sinks: Iterable[AlertSink] = (),
    ) -> None:
        self.rules = list(rules)
        self.world = WorldState(exit_grace=exit_grace)
        self.tick_s = float(tick_s)
        self.max_steps_per_event = int(max_steps_per_event)
        self.sinks = list(sinks)
        self.alerts: list[Alert] = []
        self._cooldowns: dict[str, float] = {}

    # -- public api --------------------------------------------------------
    def ingest(self, event: Event) -> list[Alert]:
        """Advance the clock to the event, apply it, then re-evaluate."""
        alerts = self.advance(event.ts)
        self._apply(event)
        alerts += self._evaluate(event.ts)
        return alerts

    def ingest_all(self, events: Iterable[Event]) -> list[Alert]:
        out: list[Alert] = []
        for event in events:
            out += self.ingest(event)
        return out

    def advance(self, now: float) -> list[Alert]:
        """Step the clock forward in `tick_s` increments, evaluating as we go.

        Without this, a dwell threshold would only fire on the next incoming
        event rather than at the moment it is actually crossed.
        """
        out: list[Alert] = []
        if self.world.now == 0.0:
            self.world.now = now
        gap = now - self.world.now
        if gap <= 0:
            return out
        step = self.tick_s
        steps = int(gap // step)
        if steps > self.max_steps_per_event:  # long idle period; coarsen
            step = gap / self.max_steps_per_event
            steps = self.max_steps_per_event
        t = self.world.now
        for _ in range(steps):
            t += step
            out += self._evaluate(t)
        if t < now:
            out += self._evaluate(now)
        return out

    def close(self, now: float | None = None) -> list[Alert]:
        """Flush: expire everything still open and do a final evaluation."""
        t = now if now is not None else self.world.now
        alerts = self.advance(t) if now is not None else []
        alerts += self._evaluate(t)
        return alerts

    # -- internals ---------------------------------------------------------
    def _apply(self, event: Event) -> None:
        world = self.world
        world.now = max(world.now, event.ts)
        if event.kind is EventKind.SIGNAL:
            world.add_signal(event.zone, event.signal or "signal", event.ts, event.track_id)
            return
        if event.track_id is None:
            return
        if event.kind is EventKind.EXIT:
            world.close(event.zone, event.track_id, event.ts)
        elif event.kind is EventKind.ENTER:
            world.force_enter(event.zone, event.track_id, event.ts)
        else:
            world.observe(event.zone, event.track_id, event.ts, event.confidence)

    def _evaluate(self, now: float) -> list[Alert]:
        # the clock never rewinds: a late-arriving event must not un-expire
        # visits that already closed at a later wall time
        now = max(now, self.world.now)
        self.world.now = now
        self.world.expire(now)
        ctx = RuleContext(world=self.world, now=now)
        fired: list[Alert] = []
        for rule in self.rules:
            for alert in rule.evaluate(ctx):
                if self._suppressed(alert, rule):
                    continue
                self._cooldowns[alert.dedup_key or alert.rule_id] = now
                self.alerts.append(alert)
                fired.append(alert)
                for sink in self.sinks:
                    sink(alert)
        return fired

    def _suppressed(self, alert: Alert, rule: Rule) -> bool:
        key = alert.dedup_key or alert.rule_id
        last = self._cooldowns.get(key)
        return last is not None and (alert.ts - last) < rule.cooldown_s

    # -- introspection -----------------------------------------------------
    def occupancy(self) -> dict[str, list[str]]:
        return {name: sorted(z.active) for name, z in self.world.zones.items()}
