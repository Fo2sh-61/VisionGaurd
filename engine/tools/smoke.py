"""Boot the real engine, ask it one question, stop it. Exit 0 or 1.

    python engine/tools/smoke.py

The pytest suite starts the *app* through `TestClient`. This starts the
*process*, the same way an operator does, through `serve.py` and uvicorn. The
difference has caught things pytest structurally cannot:

  - an argparse or uvicorn argument that no longer exists
  - a module that imports fine under pytest's sys.path but not under
    `app_dir=engine`
  - a port the process cannot bind
  - a startup that raises after the app object is built
  - a process that starts but never becomes reachable

It runs with `VG_MOCK=1` and `VG_STRICT=1`:

  VG_MOCK   skips camera capture, so this opens no device and needs no model
            weights. It runs on a laptop with the webcam already busy and on a
            CI box that has neither camera nor GPU.
  VG_STRICT turns any subsystem failure into a refusal to start instead of a
            quiet degrade to fixtures. Under mock there is nothing to fail, so
            this is belt and braces — but it is free, and it means the flag is
            exercised on the same path CI uses.

A non-default port keeps this from colliding with an engine the developer
already has running on 8001.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ENGINE_DIR.parent
SERVE = ENGINE_DIR / "tools" / "serve.py"

HOST = "127.0.0.1"
PORT = 8099            # not 8000: a running dev engine must not fail this
BOOT_SECONDS = 90.0    # generous; a cold CI import of cv2 is not fast
POLL_SECONDS = 0.25


def _wait_for_healthz(proc: subprocess.Popen, deadline: float) -> str | None:
    """Poll until the engine answers, it dies, or we run out of patience.

    Returns None on success, or a one-line reason to print.
    """
    url = f"http://{HOST}:{PORT}/healthz"

    while time.monotonic() < deadline:
        # Check the process first. If it has already exited, polling the port
        # for another 90 seconds only delays a failure we can report now.
        if proc.poll() is not None:
            return f"the process exited with code {proc.returncode} before answering"

        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return None
                return f"/healthz returned HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            # It answered, just not with a 200. That is a real failure and
            # retrying will not change it.
            return f"/healthz returned HTTP {exc.code}"
        except (urllib.error.URLError, ConnectionError, OSError):
            # Not listening yet. Expected for the first few seconds.
            time.sleep(POLL_SECONDS)

    return f"no answer from {url} within {BOOT_SECONDS:.0f}s"


def _stop(proc: subprocess.Popen) -> None:
    """Ask, then insist. Never leave the port held behind us."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def main() -> int:
    env = {**os.environ, "VG_MOCK": "1", "VG_STRICT": "1"}
    # Unbuffered, so a traceback from the child is not lost in a pipe buffer
    # when we terminate it. A smoke failure with no output is barely a signal.
    env["PYTHONUNBUFFERED"] = "1"

    print(f"  smoke  {sys.executable}")
    print(f"  smoke  starting {SERVE.name} on {HOST}:{PORT} "
          f"(VG_MOCK=1, VG_STRICT=1)")

    proc = subprocess.Popen(
        [sys.executable, str(SERVE), "--host", HOST, "--port", str(PORT),
         "--log-level", "warning"],
        cwd=str(REPO_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    started = time.monotonic()
    reason: str | None = "interrupted before the engine was reached"
    try:
        reason = _wait_for_healthz(proc, started + BOOT_SECONDS)
    finally:
        # Always, including on Ctrl-C. Leaving the child holding the port is
        # exactly the failure `dev.ps1 down` exists to clean up after.
        _stop(proc)

    output = ""
    if proc.stdout is not None:
        try:
            output = proc.stdout.read() or ""
        except Exception:
            output = ""

    if reason is not None:
        print(f"  smoke  FAILED - {reason}", file=sys.stderr)
        if output.strip():
            print("\n--- engine output ------------------------------------",
                  file=sys.stderr)
            print(output.strip(), file=sys.stderr)
            print("------------------------------------------------------",
                  file=sys.stderr)
        return 1

    print(f"  smoke  ok - engine answered /healthz in "
          f"{time.monotonic() - started:.1f}s, stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
