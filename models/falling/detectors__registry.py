"""Detector registry: every registered FallDetector shows up in the GUI dropdown
and can be selected by name in eval.py."""

_REGISTRY = {}


def register_detector(cls):
    """Class decorator: make a FallDetector selectable by ``cls.name``."""
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"detector name {cls.name!r} already registered")
    _REGISTRY[cls.name] = cls
    return cls


def detector_classes():
    """name -> class, in registration order."""
    return dict(_REGISTRY)


def available_detectors():
    """name -> display name, in registration order (the GUI dropdown)."""
    return {name: cls.display_name for name, cls in _REGISTRY.items()}


def create_detector(name, **kwargs):
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown detector {name!r}; choose from {sorted(_REGISTRY)}") from None
    return cls(**kwargs)
