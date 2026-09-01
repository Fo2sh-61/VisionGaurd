"""Audible alarm for live alerts.

Deliberately uses the OS's own notification sounds rather than bundling an
audio file to maintain. On Windows this is `winsound` (stdlib) played with
`SND_ASYNC`, so it fires-and-forgets instead of blocking the video loop for
the duration of the tone. Everywhere else it falls back to the terminal bell,
which most terminal emulators also route to the system sound if you have not
muted it.
"""
from __future__ import annotations

import sys

from .alerts import Severity

_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def play(severity: Severity) -> None:
    if not _enabled:
        return
    try:
        if sys.platform == "win32":
            import winsound

            # SND_ASYNC returns immediately -- required, or every alert would
            # freeze the camera feed for the length of the sound.
            alias = "SystemHand" if severity is Severity.CRITICAL else "SystemAsterisk"
            winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
        else:
            print("\a", end="", flush=True)  # terminal bell
    except Exception:
        pass  # a missing sound driver should never take down the alert loop
