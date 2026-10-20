"""Is this workstation on the site's private network? (spec 020, US6)

NetBird's own client says so: `netbird status --json`. It is run on a
background thread every 30 seconds with a 3-second limit, and System Health
only reads the last answer, so a slow, hung or missing client never holds up a
request (AGENTS rule 7). The row is then never much more than half a minute
old, and it says when it was checked.

Four answers, never a guess:

* `not_set_up`   - NetBird is not installed on this machine;
* `unreadable`   - it is installed but cannot be run or will not answer
                   (its background service stopped, a permission, a timeout);
* `not_connected`- it answers, but is not connected to NetBird's service;
* `connected`    - with the workstation's NetBird address.

The JSON fields come from the client's source (`client/status/status.go`:
`management.connected`, `management.error`, `daemonStatus`, `netbirdIp`) and
are not a documented promise, so the parsing is tested against the client this
was written for, **NetBird 0.81.2**, with the plain-text status as a fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

State = Literal["not_set_up", "unreadable", "not_connected", "connected"]

#: How long the client may take to answer.
TIMEOUT_S = 3
#: How often it is asked.
INTERVAL_S = 30.0


@dataclass(frozen=True)
class RemoteStatus:
    state: State
    checked_at: datetime
    address: str | None = None
    reason: str = ""


def find_client() -> Path | None:
    """NetBird's command-line client, where its installer puts it."""
    found = shutil.which("netbird")
    if found:
        return Path(found)
    default = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NetBird" / "netbird.exe"
    return default if default.is_file() else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _address(text: str | None) -> str | None:
    text = (text or "").strip()
    return text.split("/", 1)[0] or None


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _from_json(data: dict, now: datetime) -> RemoteStatus:
    management = data.get("management") or {}
    address = _address(data.get("netbirdIp"))
    if management.get("connected"):
        return RemoteStatus("connected", now, address)
    reason = (management.get("error") or "").strip()
    daemon = (data.get("daemonStatus") or "").strip()
    if not reason:
        reason = (f"NetBird says {daemon}" if daemon
                  else "not connected to NetBird's service")
    return RemoteStatus("not_connected", now, address, reason)


def _from_text(text: str, now: datetime) -> RemoteStatus | None:
    management = re.search(r"^Management:\s*(.+)$", text, re.MULTILINE)
    if not management:
        return None
    ip = re.search(r"^NetBird IP:\s*(\S+)", text, re.MULTILINE)
    address = _address(ip.group(1)) if ip else None
    said = management.group(1).strip()
    if said.lower().startswith("connected"):
        return RemoteStatus("connected", now, address)
    reason = said.split("reason:", 1)[1].strip() if "reason:" in said else said
    return RemoteStatus("not_connected", now, address, reason)


def read_status(client: Path | None | Literal["find"] = "find",
                run: Callable = subprocess.run,
                now: Callable[[], datetime] = _now) -> RemoteStatus:
    """Ask the client once. Never raises."""
    if client == "find":
        client = find_client()
    if client is None:
        return RemoteStatus("not_set_up", now())
    try:
        done = run([str(client), "status", "--json"], capture_output=True, text=True,
                   timeout=TIMEOUT_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return RemoteStatus("unreadable", now(), None,
                            f"it did not answer within {TIMEOUT_S} seconds")
    except OSError as exc:
        return RemoteStatus("unreadable", now(), None, str(exc))
    if done.returncode != 0:
        why = _last_line(done.stderr or "") or _last_line(done.stdout or "")
        return RemoteStatus("unreadable", now(), None, why or f"exit code {done.returncode}")
    try:
        data = json.loads(done.stdout)
    except ValueError:
        parsed = _from_text(done.stdout or "", now())
        if parsed is None:
            return RemoteStatus("unreadable", now(), None,
                                "its answer was not one this engine can read")
        return parsed
    if not isinstance(data, dict):
        return RemoteStatus("unreadable", now(), None, "its answer was not one this engine can read")
    return _from_json(data, now())


class StatusReader:
    """Reads the client now and every `interval` seconds, on its own thread."""

    def __init__(self, read: Callable[[], RemoteStatus | None] = read_status,
                 interval: float = INTERVAL_S):
        self._read = read
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.latest: RemoteStatus | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="remote-status", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=TIMEOUT_S + 2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.latest = self._read()
            except Exception as exc:  # the row must say so, and the thread must live
                log.exception("reading the NetBird client failed")
                self.latest = RemoteStatus("unreadable", _now(), None, str(exc))
            self._stop.wait(self._interval)
