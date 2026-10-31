"""Stop the cloud trial when nobody is using it. specs/021-cloud-trial.

Kaggle counts GPU hours for as long as a session is open, used or not, and
the owner wants them counted only while he is using it (31 Oct 2026). So this
watches the engine's request log, and when no signed-in request has arrived
for `--idle-minutes`, it runs stop.sh: the engine stops and saves, the
notebook's wait cell sees it and ends, and a background (Save & Run All) run
gives the GPU back.

What counts as use: a request that got through with a session. Not the
health probe (the notebook itself asks it every 5 minutes), not the public
page and its files, and not a refusal (401/403/404): a stranger who finds the
address must not keep the GPU running.

Two clocks. Until the first use there are `--first-use-minutes` (default 15)
to find the address and sign in; after that, `--idle-minutes` (default 1, the
owner's choice) after the last use it stops. While the console tab is open it
keeps polling the engine, which is use: closing the tab is what stops it.

    python tools/cloud/idle_watch.py --log /tmp/vg-trial/engine.log --stop tools/cloud/stop.sh
"""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path

#: uvicorn's access line: `INFO:     127.0.0.1:60984 - "GET /cameras HTTP/1.1" 200 OK`
ACCESS = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3})')

#: Paths that say nothing about anyone using the console.
NOT_USE_PREFIXES = ("/healthz", "/assets/", "/favicon", "/manifest")
REFUSED = {"401", "403", "404"}


def is_use(line: str) -> bool:
    """True when this log line is somebody signed in using the console."""
    match = ACCESS.search(line)
    if not match:
        return False
    path = match["path"].split("?", 1)[0]
    if path == "/" or path.startswith(NOT_USE_PREFIXES):
        return False
    return match["status"] not in REFUSED


def watch(log: Path, stop: Path, idle_minutes: float, first_use_minutes: float = 15.0,
          poll_seconds: float = 10.0, clock=time.monotonic, sleep=time.sleep) -> str:
    """Block until idle, then run stop.sh. Returns why it stopped."""
    started = clock()
    last_use: float | None = None
    position = 0
    while True:
        if log.exists():
            with log.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(position)
                fresh = f.read()
                position = f.tell()
            if any(is_use(line) for line in fresh.splitlines()):
                last_use = clock()
        if last_use is None:
            waited = clock() - started
            reason = (f"nobody signed in within {first_use_minutes:g} minutes"
                      if waited >= first_use_minutes * 60 else "")
        else:
            idle = clock() - last_use
            reason = (f"no use for {idle / 60:.1f} minutes"
                      if idle >= idle_minutes * 60 else "")
        if reason:
            print(f"idle-watch: {reason}; stopping", flush=True)
            subprocess.run(["bash", str(stop)], check=False)
            return reason
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stop the trial when nobody uses it.")
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--stop", type=Path, required=True)
    p.add_argument("--idle-minutes", type=float, default=1.0)
    p.add_argument("--first-use-minutes", type=float, default=15.0)
    args = p.parse_args(argv)
    watch(args.log, args.stop, args.idle_minutes, args.first_use_minutes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
