"""Measure what remote video costs: the link, and the workstation (spec 020, T025).

    python engine/tools/measure_remote_video.py --email you@site --camera cam-clip

Run on the workstation against a running engine (the recorded clip is the
repeatable one: `dev.ps1 up -Clip`). The password is asked for, never an
argument; `--password-from-env NAME` reads it from that variable instead. It acts as a phone away from the site by sending the address a
NetBird device would have in `X-Forwarded-For`, which the engine believes only
from this machine (`serve.py`), exactly as it believes Caddy.

It prints, measured over `--seconds` each:

* one remote live view, in Mbit/s (plan: at most 1.5);
* one remote camera tile, in Mbit/s, and twelve of them (plan: at most 0.5);
* the engine's extra processor use while 2 viewers keep 2 live views each
  open, in cores kept busy flat out.

Nothing is written anywhere; the numbers go into plan.md by hand.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import threading
import time

import httpx

REMOTE = {"X-Forwarded-For": "100.64.0.9"}


def sign_in(base: str, email: str, password: str) -> str:
    answer = httpx.post(f"{base}/auth/login", json={"email": email, "password": password},
                        headers=REMOTE, timeout=15)
    answer.raise_for_status()
    return answer.json()["token"]


def stream_bytes(base: str, token: str, camera: str, seconds: float, out: list[int]) -> None:
    got = 0
    deadline = time.monotonic() + seconds
    headers = {**REMOTE, "Authorization": f"Bearer {token}"}
    with httpx.stream("GET", f"{base}/cameras/{camera}/stream", headers=headers,
                      timeout=httpx.Timeout(10, read=10)) as answer:
        answer.raise_for_status()
        for chunk in answer.iter_bytes():
            got += len(chunk)
            if time.monotonic() >= deadline:
                break
    out.append(got)


def tile_bytes(base: str, token: str, camera: str, seconds: float, interval: float) -> int:
    got = 0
    deadline = time.monotonic() + seconds
    headers = {**REMOTE, "Authorization": f"Bearer {token}"}
    with httpx.Client(headers=headers, timeout=15) as client:
        while time.monotonic() < deadline:
            asked = time.monotonic()
            answer = client.get(f"{base}/cameras/{camera}/snapshot",
                                params={"width": 320, "fps": 1})
            answer.raise_for_status()
            got += len(answer.content)
            time.sleep(max(0.0, interval - (time.monotonic() - asked)))
    return got


def engine_cpu_seconds(port: int) -> tuple[object, float] | None:
    try:
        import psutil
    except ImportError:
        return None
    for conn in psutil.net_connections("tcp"):
        if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN" and conn.pid:
            proc = psutil.Process(conn.pid)
            times = proc.cpu_times()
            return proc, times.user + times.system
    return None


def mbit(n_bytes: int, seconds: float) -> float:
    return n_bytes * 8 / seconds / 1_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--email", required=True)
    parser.add_argument("--camera", default="cam-clip")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--password-from-env", metavar="NAME")
    parser.add_argument("--second-email", default="",
                        help="a second account, so two viewers hold two live views each")
    parser.add_argument("--second-password-from-env", metavar="NAME")
    args = parser.parse_args(argv)
    port = int(args.base.rsplit(":", 1)[1].split("/")[0])

    def password(env: str | None, prompt: str) -> str:
        return os.environ[env] if env else getpass.getpass(prompt)

    token = sign_in(args.base, args.email, password(args.password_from_env, "  password  "))
    limits = httpx.get(f"{args.base}/connection", timeout=15,
                       headers={**REMOTE, "Authorization": f"Bearer {token}"}).json()
    if not limits.get("remote"):
        print("  the engine does not see this as a remote caller; nothing measured")
        return 1
    print(f"  remote limits: a tile every {limits['tileIntervalSeconds']} s, live view "
          f"{limits['liveWidth']} px at {limits['liveFps']} a second, {limits['liveViews']} at once")

    out: list[int] = []
    stream_bytes(args.base, token, args.camera, args.seconds, out)
    live = mbit(out[0], args.seconds)
    print(f"  one remote live view:   {live:.2f} Mbit/s   (plan: at most 1.5)")

    tile = mbit(tile_bytes(args.base, token, args.camera, args.seconds,
                           limits["tileIntervalSeconds"]), args.seconds)
    print(f"  one remote tile:        {tile:.3f} Mbit/s; twelve: {12 * tile:.2f} Mbit/s   "
          f"(plan: twelve at most 0.5)")

    # Two viewers with two live views each. Places are per account, so the
    # second viewer is a second account (`--second-email`); without one only
    # the first viewer's two views run.
    before = engine_cpu_seconds(port)
    if before is None:
        print("  engine processor use: not measured (psutil missing, or no engine on that port)")
        return 0
    proc, cpu0 = before
    idle_start = time.monotonic()
    time.sleep(min(20.0, args.seconds / 3))
    t = proc.cpu_times()
    idle = (t.user + t.system - cpu0) / (time.monotonic() - idle_start)

    tokens = [token]
    if args.second_email:
        tokens.append(sign_in(args.base, args.second_email,
                              password(args.second_password_from_env, "  its password  ")))
    threads, out = [], []
    for viewer in tokens:
        for _ in range(2):
            threads.append(threading.Thread(target=stream_bytes,
                                            args=(args.base, viewer, args.camera, args.seconds, out)))
    t = proc.cpu_times()
    cpu1, start = t.user + t.system, time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    t = proc.cpu_times()
    busy = (t.user + t.system - cpu1) / (time.monotonic() - start)
    print(f"  engine processor use with {len(tokens)} viewer(s) x 2 live views: "
          f"{busy - idle:+.2f} cores kept busy flat out beyond its own {idle:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
