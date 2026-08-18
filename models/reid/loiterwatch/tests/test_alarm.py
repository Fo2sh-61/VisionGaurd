"""The alarm module must never crash the alert loop, on any platform."""
from __future__ import annotations

from loiterwatch import Severity
from loiterwatch import alarm


def test_play_does_not_raise_regardless_of_platform():
    alarm.set_enabled(True)
    alarm.play(Severity.CRITICAL)
    alarm.play(Severity.WARNING)
    alarm.play(Severity.INFO)


def test_disabled_alarm_is_a_no_op(monkeypatch):
    calls = []
    monkeypatch.setattr(alarm, "_enabled", False)
    # even if the platform sound call would explode, disabled short-circuits first
    monkeypatch.setattr("sys.platform", "win32")
    alarm.play(Severity.CRITICAL)
    assert calls == []


def test_set_enabled_toggles_state():
    alarm.set_enabled(False)
    assert alarm._enabled is False
    alarm.set_enabled(True)
    assert alarm._enabled is True


def test_play_survives_a_broken_sound_backend(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "win32")

    class ExplodingWinsound:
        SND_ALIAS = 0
        SND_ASYNC = 0

        @staticmethod
        def PlaySound(*a, **kw):
            raise OSError("no audio device")

    monkeypatch.setitem(sys.modules, "winsound", ExplodingWinsound)
    alarm.set_enabled(True)
    alarm.play(Severity.CRITICAL)  # must not raise
