"""Strict start under the service: what stops the engine, and what never does.

`VG_STRICT=1` is set by the Windows service. A subsystem that fails to start
then stops the engine, so a site never runs on fixtures. A camera that is
offline must never be one of those: cameras drop and come back all day.

A full strict start needs every model file, which a development machine or CI
does not have; the first model-backed subsystem then stops it, correctly. So
the camera test checks the part that matters: startup got past the cameras,
and whatever stopped it was not a camera. Drill D5 covers a full start on the
workstation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg.api import app as app_module  # noqa: E402


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setenv("VG_STRICT", "1")
    monkeypatch.delenv("VG_MOCK", raising=False)
    monkeypatch.delenv("VG_CAMERAS", raising=False)


def _start(app):
    try:
        with TestClient(app):
            return None
    except RuntimeError as exc:
        return exc
    finally:
        registry = getattr(app.state, "registry", None)
        if registry is not None:
            registry.stop(timeout=2.0)


def test_a_config_that_will_not_load_stops_a_strict_start(strict, tmp_path, monkeypatch):
    # It used to log the error and serve fixtures, under strict too: a site
    # whose engine.yaml had a typo showed a healthy console of invented numbers.
    monkeypatch.setenv("VG_HOME", str(tmp_path))
    exc = _start(app_module.create_app())
    assert exc is not None and "config failed to start" in str(exc)


def test_without_strict_a_bad_config_still_serves_system_health(tmp_path, monkeypatch):
    # Development keeps the old behaviour: the API comes up and says why.
    monkeypatch.delenv("VG_STRICT", raising=False)
    monkeypatch.setenv("VG_HOME", str(tmp_path))
    assert _start(app_module.create_app()) is None


@pytest.mark.slow
def test_an_offline_camera_is_never_a_start_failure(strict, tmp_path, monkeypatch):
    (tmp_path / "engine.yaml").write_text(
        "timezone: Africa/Cairo\n"
        "storage:\n"
        f"  database_url: sqlite:///{(tmp_path / 'vg.db').as_posix()}\n"
        f"  clips_dir: {(tmp_path / 'clips').as_posix()}\n"
        "cameras:\n"
        "  - id: cam-off\n"
        "    name: Offline\n"
        "    source: rtsp://127.0.0.1:9/nothing-listens-here\n"
        "    features: []\n"
        "models: {}\n",
        encoding="utf-8")
    monkeypatch.setenv("VG_HOME", str(tmp_path))

    app = app_module.create_app()
    exc = _start(app)

    assert app.state.registry is not None, "startup never got past the cameras"
    assert app.state.registry.worker("cam-off") is not None
    if exc is not None:
        assert "camera" not in str(exc).split(" failed to start")[0].lower(), exc
