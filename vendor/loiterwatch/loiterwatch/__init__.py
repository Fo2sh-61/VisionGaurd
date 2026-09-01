"""loiterwatch -- a detector-agnostic temporal rules engine for loitering."""
from .alerts import Alert, Severity
from .config import Config, load_config, parse_config
from .engine import Engine
from .events import DEFAULT_ZONE, Event, EventKind, read_jsonl, synth_observations
from .rules import (RULE_TYPES, CumulativeDwellRule, DwellRule, IntrusionRule,
                    NoTransactionRule, RepeatEntryRule, Rule, register)
from .state import Visit, WorldState, ZoneState

__version__ = "0.1.0"
__all__ = [
    "Alert", "Severity", "Config", "load_config", "parse_config", "Engine",
    "DEFAULT_ZONE", "Event", "EventKind", "read_jsonl", "synth_observations", "RULE_TYPES",
    "CumulativeDwellRule", "DwellRule", "IntrusionRule", "NoTransactionRule", "RepeatEntryRule", "Rule", "register",
    "Visit", "WorldState", "ZoneState",
]
