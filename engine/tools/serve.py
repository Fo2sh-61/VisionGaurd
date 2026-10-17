"""Start the API server.

    python engine/tools/serve.py                 # real cameras, no reload
    python engine/tools/serve.py --port 9000
    python engine/tools/serve.py --reload        # opt-in; orphans on Windows

It reads engine.yaml and brings up whatever is configured there. It does NOT
serve fixtures — the startup log says what actually loaded, and that is the
line to trust.

Then, in another terminal:

    cd web
    npm run dev

Leave `VITE_API_BASE` unset. The dev server proxies the engine, so the browser
talks to one origin and the session cookie reaches the camera streams; setting
it makes the browser call the engine directly and every live view goes black.

http://127.0.0.1:8000/docs is the generated OpenAPI page. That page is the
frozen contract — if the front end and the engine ever disagree, it decides.

**Under the Windows service** nobody reads the console. `VG_LOGS` names the
logs folder: every line also goes to `engine.log` there (10 MB x 10 files),
and a start that fails leaves one plain line in `start-failure.txt` saying
what failed and why. Unset, nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))


LOG_BYTES = 10 * 1024 * 1024
LOG_FILES = 10          # the live file plus nine rolled ones
START_FAILURE = "start-failure.txt"


def logs_dir() -> Path | None:
    """`VG_LOGS`, set by the service. None for development."""
    raw = os.environ.get("VG_LOGS", "").strip()
    return Path(raw) if raw else None


class FirstError(logging.Handler):
    """Remembers the first error uvicorn logs, which is why it stopped.

    uvicorn never lets a startup exception reach this file: it logs the
    traceback, then "Application startup failed. Exiting.", then exits. The
    first line is the one that says what failed; the second never does.
    """

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.reason: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if self.reason is not None:
            return
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            self.reason = f"{type(exc).__name__}: {exc}"
            return
        lines = [ln.strip() for ln in record.getMessage().splitlines() if ln.strip()]
        self.reason = lines[-1] if lines else None


def log_config(logs: Path | None, watch: FirstError) -> dict:
    """uvicorn's own logging set-up, plus the file and the failure watch.

    Passed to uvicorn rather than added afterwards, because uvicorn applies
    its config inside `run()` and would drop a handler added before.
    """
    from uvicorn.config import LOGGING_CONFIG

    cfg = copy.deepcopy(LOGGING_CONFIG)
    cfg["handlers"]["first_error"] = {"()": lambda: watch}
    cfg["loggers"]["uvicorn.error"]["handlers"] = ["first_error"]
    if logs is None:
        return cfg

    logs.mkdir(parents=True, exist_ok=True)
    cfg["formatters"]["file"] = {
        "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
    }
    cfg["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(logs / "engine.log"),
        "maxBytes": LOG_BYTES,
        "backupCount": LOG_FILES - 1,
        "encoding": "utf-8",
        "formatter": "file",
    }
    # uvicorn's loggers do not propagate to the root, so each carries it.
    cfg["loggers"]["uvicorn"]["handlers"].append("file")
    cfg["loggers"]["uvicorn.access"]["handlers"].append("file")
    # The engine's own lines (`vg.*`) go to the root logger.
    cfg["root"] = {"handlers": ["file"], "level": "INFO"}
    return cfg


def write_start_failure(logs: Path, reason: str) -> None:
    """One line: when, what failed and why. Overwritten by the next try."""
    reason = " ".join(reason.split())
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / START_FAILURE).write_text(f"{stamp} {reason}\n", encoding="utf-8")


def warn_if_cpu_only() -> None:
    """Say plainly when the models are about to run on the CPU.

    The difference is roughly 7x on person detection, and it is invisible
    otherwise — the system works, just slowly, and it is easy to spend a long
    time tuning around a problem that is really "wrong Python interpreter".
    """
    try:
        import torch

        if torch.cuda.is_available():
            print(f"  gpu   {torch.cuda.get_device_name(0)}")
            return
    except ImportError:
        pass

    print("  gpu   NONE - models will run on the CPU (~7x slower)")
    print("        Use the project venv, not a bare `python`:")
    print("        .\\.venv\\Scripts\\python.exe engine\\tools\\serve.py")


def main(argv: list[str] | None = None) -> int:
    from vg import config as vgconfig

    try:
        cfg = vgconfig.load()
        host_default, port_default = cfg.api.host, cfg.api.port
        site = cfg.site_name
    except vgconfig.ConfigError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        host_default, port_default, site = "127.0.0.1", 8000, "VisionGuard"

    p = argparse.ArgumentParser(description="Run the VisionGuard API.")
    p.add_argument("--host", default=host_default)
    p.add_argument("--port", type=int, default=port_default)
    # Reload is OPT-IN, not the default.
    #
    # uvicorn's reloader runs the app in a child process. On Windows, Ctrl-C
    # reaches the parent but frequently not the child, which then survives
    # holding the camera and port 8000 — the next start fails with WinError
    # 10013 and nothing obvious is listening. Reload is a convenience; a
    # server you cannot stop is not.
    p.add_argument("--reload", action="store_true",
                   help="restart on code changes (leaves an orphan if force-killed)")
    p.add_argument("--no-reload", action="store_true",
                   help=argparse.SUPPRESS)  # accepted for compatibility; now the default
    p.add_argument("--log-level", default="info")
    args = p.parse_args(argv)

    print(f"\n  {site}")
    print(f"  api   http://{args.host}:{args.port}")
    print(f"  docs  http://{args.host}:{args.port}/docs")
    # Don't claim a data mode here — cameras and recognition come up during
    # app startup, seconds after this prints. Saying "mock fixtures" before
    # that happens was simply untrue. The startup log reports what actually
    # loaded; that is the line to trust.
    warn_if_cpu_only()
    print("  mode  see the startup log below\n")

    import uvicorn

    reload = args.reload and not args.no_reload
    if reload:
        print("  note  --reload runs a child process; if Ctrl-C leaves it")
        print("        behind, see the cleanup command in engine/README.md\n")

    logs = logs_dir()
    watch = FirstError()
    if logs is not None:
        # A line from an earlier try would describe a start that is over.
        (logs / START_FAILURE).unlink(missing_ok=True)

    try:
        uvicorn.run(
            "vg.api.app:app",
            host=args.host,
            port=args.port,
            reload=reload,
            reload_dirs=[str(ENGINE_DIR / "vg")] if reload else None,
            log_level=args.log_level,
            log_config=log_config(logs, watch),
            app_dir=str(ENGINE_DIR),
            # Belt and braces with the SHUTTING_DOWN event in app.py. That
            # releases open MJPEG streams cooperatively; this force-closes
            # anything still holding on after 5s. Ctrl-C must always mean
            # "stopped", never "stopped unless a tab is open".
            timeout_graceful_shutdown=5,
            # Behind the HTTPS front, the client's address arrives in
            # X-Forwarded-For. Only the front, on this machine, is believed:
            # anything else that sends the header is ignored.
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    except KeyboardInterrupt:
        # uvicorn normally handles this, but a Ctrl-C arriving during startup
        # (while models load) escapes it and would print a bare traceback.
        pass
    except SystemExit as exc:
        # uvicorn exits this way when the app's startup fails.
        if logs is not None and exc.code not in (0, None):
            write_start_failure(
                logs, watch.reason or f"the engine stopped with code {exc.code}")
        raise
    except Exception as exc:
        if logs is not None:
            write_start_failure(logs, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _release_children()

    print("\n  stopped")
    return 0


def _release_children() -> None:
    """Make sure nothing is left holding the camera or the port.

    Belt and braces: capture threads are daemons and uvicorn shuts itself
    down, but a reload child or a stuck OpenCV read has been observed
    surviving and keeping port 8000 bound. Cleaning up here means Ctrl-C
    always leaves a usable machine.
    """
    try:
        import psutil
    except ImportError:
        return

    me = psutil.Process()
    for child in me.children(recursive=True):
        try:
            child.terminate()
        except psutil.Error:
            pass

    _, alive = psutil.wait_procs(me.children(recursive=True), timeout=3)
    for survivor in alive:
        try:
            survivor.kill()
        except psutil.Error:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
