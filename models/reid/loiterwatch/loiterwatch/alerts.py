"""Alert objects emitted by rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


@dataclass(frozen=True)
class Alert:
    ts: float
    rule_id: str
    rule_type: str
    severity: Severity
    zone: str
    track_id: str | None
    message: str
    #: everything a reviewer needs to judge the alert without re-watching video
    evidence: dict[str, Any] = field(default_factory=dict)
    #: identity used for cooldown/dedup
    dedup_key: str = ""

    @property
    def clock(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%H:%M:%S")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "time": datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat(),
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "severity": self.severity.value,
            "zone": self.zone,
            "track_id": self.track_id,
            "message": self.message,
            "evidence": self.evidence,
        }
