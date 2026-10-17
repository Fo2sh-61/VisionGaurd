"""The engine's log file and its start-failure line (spec 016, plan C).

Under the Windows service nobody watches a console. `VG_LOGS` names the logs
folder; serve.py then writes `engine.log` there, rolled by size, and when the
engine cannot start it leaves one plain line in `start-failure.txt` saying what
failed and why. Unset, serve.py behaves exactly as it does for development.
"""

from __future__ import annotations

import logging
import logging.config
import logging.handlers
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR / "tools"))

import serve  # noqa: E402

NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture(autouse=True)
def clean_logging():
    """dictConfig is process-wide. Put every touched logger back."""
    saved = {n: (logging.getLogger(n).handlers[:], logging.getLogger(n).level,
                 logging.getLogger(n).propagate) for n in NAMES}
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        for h in logger.handlers:
            if h not in handlers:
                h.close()
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def _file_handlers(name: str) -> list[logging.handlers.RotatingFileHandler]:
    return [h for h in logging.getLogger(name).handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)]


class TestLogFile:
    def test_set_adds_exactly_one_rotating_engine_log(self, tmp_path):
        logging.config.dictConfig(serve.log_config(tmp_path, serve.FirstError()))
        root = _file_handlers("")
        assert len(root) == 1
        handler = root[0]
        assert Path(handler.baseFilename) == tmp_path / "engine.log"
        # 10 MB x 10 files: the live one plus nine rolled.
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 9
        # uvicorn's loggers do not propagate, so they carry the same handler.
        assert _file_handlers("uvicorn") == [handler]
        assert _file_handlers("uvicorn.access") == [handler]

    def test_engine_lines_reach_the_file(self, tmp_path):
        logging.config.dictConfig(serve.log_config(tmp_path, serve.FirstError()))
        logging.getLogger("vg.api.app").info("recognition: ready")
        for h in _file_handlers(""):
            h.flush()
        assert "recognition: ready" in (tmp_path / "engine.log").read_text(encoding="utf-8")

    def test_unset_adds_none(self):
        logging.config.dictConfig(serve.log_config(None, serve.FirstError()))
        for name in NAMES:
            assert not _file_handlers(name)


def _run(monkeypatch, fake):
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake)
    monkeypatch.setattr(serve, "_release_children", lambda: None)
    return serve.main([])


class TestStartFailure:
    TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 1, in lifespan\n'
        "RuntimeError: recognition failed to start and VG_STRICT=1 is set: "
        "models/face/sface.onnx is missing\n"
    )

    def test_a_strict_stop_leaves_one_plain_line(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VG_LOGS", str(tmp_path))

        def fake(*_, **kw):
            # What uvicorn does when the app's startup raises.
            logging.config.dictConfig(kw["log_config"])
            logging.getLogger("uvicorn.error").error(self.TRACEBACK)
            logging.getLogger("uvicorn.error").error("Application startup failed. Exiting.")
            sys.exit(3)

        with pytest.raises(SystemExit):
            _run(monkeypatch, fake)
        text = (tmp_path / "start-failure.txt").read_text(encoding="utf-8")
        assert text.count("\n") == 1
        assert "recognition failed to start" in text
        assert "sface.onnx is missing" in text

    def test_an_exception_out_of_uvicorn_is_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VG_LOGS", str(tmp_path))

        def fake(*_, **kw):
            raise ValueError("engine.yaml: tls.names[0] is not an IP address")

        with pytest.raises(ValueError):
            _run(monkeypatch, fake)
        text = (tmp_path / "start-failure.txt").read_text(encoding="utf-8")
        assert "ValueError: engine.yaml: tls.names[0]" in text

    def test_a_good_start_clears_an_old_line(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VG_LOGS", str(tmp_path))
        (tmp_path / "start-failure.txt").write_text("old\n", encoding="utf-8")
        assert _run(monkeypatch, lambda *a, **k: None) == 0
        assert not (tmp_path / "start-failure.txt").exists()

    def test_unset_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VG_LOGS", raising=False)
        monkeypatch.chdir(tmp_path)

        def fake(*_, **kw):
            raise ValueError("x")

        with pytest.raises(ValueError):
            _run(monkeypatch, fake)
        assert not list(tmp_path.iterdir())
