"""Rule-based fall detector: the spine-angle fall signal from
britishnew/dual_camera_fight_detector.py behind the FallDetector interface.

Each frame a track's spine angle from vertical is mapped to a state:
<= upright_deg is NORMAL, >= fallen_deg is FALLEN, in between FALLING. The
shared EventEmitter turns "upright, then horizontal within transition_s" into
an alert, which is the original "was UPRIGHT within FALL_HISTORY_S" rule.
"""

import json
from pathlib import Path

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN
from core.keypoints import KP_CONF_MIN, spine_angle_deg

from .base import FallDetector
from .events import EmitterConfig
from .registry import register_detector

FALL_SPINE_ANGLE = 60.0         # >= this counts as horizontal-ish
FALL_UPRIGHT_THRESHOLD = 30.0   # <= this counts as upright

# Alert rules calibrated on validation videos by `python -m train.compare --install`.
CALIBRATION = Path(__file__).resolve().parents[1] / "checkpoints" / "rule_based.json"


@register_detector
class RuleBasedFallDetector(FallDetector):
    name = "rule_based"
    display_name = "Rule-based (spine angle)"

    def __init__(self, upright_deg=FALL_UPRIGHT_THRESHOLD, fallen_deg=FALL_SPINE_ANGLE,
                 conf_min=KP_CONF_MIN, emitter_config=None, link_s=1.0):
        """emitter_config: alert rules; default = the calibrated ones in checkpoints/rule_based.json
        if present, else EmitterConfig() defaults."""
        if emitter_config is None and CALIBRATION.is_file():
            emitter_config = EmitterConfig(**json.loads(CALIBRATION.read_text())["emitter"])
        super().__init__(emitter_config, link_s)
        self.upright_deg = upright_deg
        self.fallen_deg = fallen_deg
        self.conf_min = conf_min

    def classify(self, keypoints):
        """(state, confidence) for one person's keypoints."""
        ang = spine_angle_deg(keypoints, self.conf_min)
        if ang is None:
            return UNKNOWN, 0.0
        if ang >= self.fallen_deg:
            # Same magnitude shape as the original fall signal, mapped to [0.5, 1].
            return FALLEN, min(1.0, 0.5 + (ang - self.fallen_deg) / 60.0)
        if ang <= self.upright_deg:
            return NORMAL, 1.0 - 0.5 * ang / self.upright_deg
        return FALLING, 0.5

    def _update(self, frame_idx, persons):
        events = []
        for p in persons:
            if p.track_id is None:
                continue
            state, conf = self.classify(p.keypoints)
            event = self.emitter.observe(p.track_id, frame_idx, state, conf, p.bbox)
            if event is not None:
                events.append(event)
        self.emitter.prune(frame_idx)
        return events
