"""YAML configuration loading and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from .engine import Engine
from .rules.base import RULE_TYPES, Rule, build_rule


@dataclass
class Config:
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    exit_grace_s: float = 3.0
    tick_s: float = 1.0

    def engine(self, **kw: Any) -> Engine:
        return Engine(
            self.rules, exit_grace=self.exit_grace_s, tick_s=self.tick_s, **kw
        )


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> Config:
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")

    zones_raw = raw.get("zones", {}) or {}
    if isinstance(zones_raw, list):  # allow a plain list of zone names
        zones = {str(z): {} for z in zones_raw}
    else:
        zones = {str(k): (v or {}) for k, v in zones_raw.items()}

    defaults = raw.get("defaults", {}) or {}
    rule_specs = raw.get("rules", []) or []
    if not rule_specs:
        raise ValueError("config defines no rules")

    seen_ids: set[str] = set()
    rules: list[Rule] = []
    for spec in rule_specs:
        if not isinstance(spec, dict):
            raise ValueError(f"each rule must be a mapping, got {spec!r}")
        merged = {**defaults, **spec}
        rule_id = merged.get("id", merged.get("type"))
        if rule_id in seen_ids:
            raise ValueError(f"duplicate rule id {rule_id!r}")
        seen_ids.add(rule_id)
        for zone in merged.get("zones", []) or []:
            if zones and zone not in zones:
                raise ValueError(
                    f"rule {rule_id!r} targets unknown zone {zone!r}; "
                    f"declared zones: {sorted(zones)}"
                )
        try:
            rules.append(build_rule(merged))
        except TypeError as exc:
            allowed = ", ".join(sorted(RULE_TYPES))
            raise ValueError(f"bad config for rule {rule_id!r}: {exc} (types: {allowed})") from exc

    return Config(
        zones=zones,
        defaults=defaults,
        rules=rules,
        exit_grace_s=float(raw.get("exit_grace_s", 3.0)),
        tick_s=float(raw.get("tick_s", 1.0)),
    )
