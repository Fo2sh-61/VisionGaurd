"""Start the API server.

    python engine/tools/serve.py                 # mock data, reload on save
    python engine/tools/serve.py --port 9000
    python engine/tools/serve.py --no-reload

Then point the front end at it:

    web/.env.local     VITE_API_BASE=http://127.0.0.1:8000
    npm run dev

http://127.0.0.1:8000/docs is the generated OpenAPI page. That page is the
frozen contract — if the front end and the engine ever disagree, it decides.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))


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

    try:
        uvicorn.run(
            "vg.api.app:app",
            host=args.host,
            port=args.port,
            reload=reload,
            reload_dirs=[str(ENGINE_DIR / "vg")] if reload else None,
            log_level=args.log_level,
            app_dir=str(ENGINE_DIR),
            # Belt and braces with the SHUTTING_DOWN event in app.py. That
            # releases open MJPEG streams cooperatively; this force-closes
            # anything still holding on after 5s. Ctrl-C must always mean
            # "stopped", never "stopped unless a tab is open".
            timeout_graceful_shutdown=5,
        )
    except KeyboardInterrupt:
        # uvicorn normally handles this, but a Ctrl-C arriving during startup
        # (while models load) escapes it and would print a bare traceback.
        pass
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
