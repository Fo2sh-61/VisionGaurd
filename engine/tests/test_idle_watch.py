"""tools/cloud/idle_watch.py — the cloud trial stops when nobody uses it.

The owner wants Kaggle's GPU hours counted only while he is using the
engine (31 Oct 2026): 15 minutes to sign in, then one idle minute and it
stops. These pin what counts as use, so a stranger who finds the public
address cannot keep the GPU running, and the notebook's own health probe
cannot either.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "cloud"))

import idle_watch as iw  # noqa: E402


def line(method: str, path: str, status: int) -> str:
    return f'INFO:     127.0.0.1:60984 - "{method} {path} HTTP/1.1" {status} OK\n'


class TestWhatCountsAsUse:
    @pytest.mark.parametrize("method,path,status", [
        ("GET", "/cameras", 200),
        ("GET", "/cameras/cam-clip/snapshot?t=3&width=640&fps=15", 200),
        ("POST", "/auth/login", 200),
        ("PATCH", "/zones/cam-clip", 200),
    ])
    def test_signed_in_requests_are_use(self, method, path, status):
        assert iw.is_use(line(method, path, status))

    @pytest.mark.parametrize("method,path,status", [
        ("GET", "/healthz", 200),            # the notebook asks every 5 minutes
        ("GET", "/", 200),                   # the public page
        ("GET", "/assets/index-abc.js", 200),
        ("GET", "/cameras", 401),            # a stranger, refused
        ("POST", "/auth/login", 401),        # a wrong password
        ("GET", "/nope", 404),
    ])
    def test_everything_else_is_not(self, method, path, status):
        assert not iw.is_use(line(method, path, status))

    def test_other_log_lines_are_not(self):
        assert not iw.is_use("Loading /tmp/vg/models/yolov8s-640.engine\n")


class Clock:
    """A clock the test moves; `sleep` moves it and lets the test write log lines."""

    def __init__(self, log: Path, script: dict[float, str]):
        self.now = 0.0
        self.log = log
        self.script = script

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        for at in sorted(self.script):
            if at <= self.now:
                with self.log.open("a") as f:
                    f.write(self.script.pop(at))
        if self.now > 6 * 3600:
            raise AssertionError("never stopped")


def run(tmp_path, script, monkeypatch, idle=1.0, first=15.0):
    log = tmp_path / "engine.log"
    log.write_text("")
    stops = []
    monkeypatch.setattr(iw.subprocess, "run", lambda cmd, **_: stops.append(cmd))
    clock = Clock(log, dict(script))
    reason = iw.watch(log, tmp_path / "stop.sh", idle, first,
                      poll_seconds=10, clock=clock, sleep=clock.sleep)
    assert len(stops) == 1
    return reason, clock.now


class TestWhenItStops:
    def test_nobody_signs_in_within_15_minutes(self, tmp_path, monkeypatch):
        reason, at = run(tmp_path, {}, monkeypatch)
        assert "nobody signed in" in reason
        assert 15 * 60 <= at < 15 * 60 + 20

    def test_one_minute_after_the_last_use(self, tmp_path, monkeypatch):
        use = line("GET", "/cameras", 200)
        script = {60: use, 120: use, 180: use}  # used for three minutes, then gone
        reason, at = run(tmp_path, script, monkeypatch)
        assert "no use" in reason
        assert 180 + 60 <= at < 180 + 60 + 20

    def test_a_stranger_does_not_keep_it_running(self, tmp_path, monkeypatch):
        refused = line("GET", "/cameras", 401)
        script = {t: refused for t in range(30, 3600, 30)}
        reason, at = run(tmp_path, script, monkeypatch)
        assert "nobody signed in" in reason and at < 16 * 60

    def test_the_health_probe_does_not_keep_it_running(self, tmp_path, monkeypatch):
        probe = line("GET", "/healthz", 200)
        use = line("GET", "/cameras", 200)
        script = {60: use, **{t: probe for t in range(90, 3600, 30)}}
        reason, at = run(tmp_path, script, monkeypatch)
        assert "no use" in reason and at < 60 + 60 + 20

    def test_steady_use_keeps_it_running(self, tmp_path, monkeypatch):
        use = line("GET", "/cameras", 200)
        script = {t: use for t in range(30, 2 * 3600, 30)}
        _, at = run(tmp_path, script, monkeypatch)
        assert at >= 2 * 3600
