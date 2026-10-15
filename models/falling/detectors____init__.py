"""Fall detectors. Importing this package registers every built-in detector."""

from .base import FallDetector, FallEvent, TrackStatus
from .events import EmitterConfig, EventEmitter
from .registry import available_detectors, create_detector, detector_classes, register_detector

# Imported for their @register_detector side effect (dropdown order = import order).
from . import rule_based, temporal_model  # noqa: E402,F401

__all__ = [
    "FallDetector", "FallEvent", "TrackStatus", "EmitterConfig", "EventEmitter",
    "available_detectors", "create_detector", "detector_classes", "register_detector",
]
