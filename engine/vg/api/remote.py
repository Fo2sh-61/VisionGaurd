"""Telling a remote request apart, and the limits it gets (spec 020).

**Local only when the address is on the factory network** (`remote.lan_networks`
in engine.yaml). Everything else is remote: NetBird's 100.64.x.x, IPv6, a second
adapter, an address that cannot be read. A mistake here costs video quality and
self sign-up, never exposure, which is the direction to fail.

**The address is the real one.** Caddy replaces `X-Forwarded-For` with the
address it saw, and `serve.py` believes that header only from 127.0.0.1, so a
device cannot claim to be on the factory network by sending one.

Two limits live here, both applied by the engine itself so a screen that ignores
them still gets only what they allow:

* `SnapshotPacer`: a remote camera tile gets one picture per interval. One that
  asks early **waits its turn** and then gets a new picture, so the screen never
  sees a slowed refresh as a fault.
* `StreamSlots`: each remote account may hold a few live views at once. A view
  whose viewer vanished (the phone lost signal without closing) frees its place
  once it has sent nothing for 15 seconds.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from fastapi import Request

from vg import config as vgconfig

#: NetBird's range. Only used to say where a request came from, in words.
PRIVATE_NETWORK = ipaddress.ip_network("100.64.0.0/10")

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse(address: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(str(address or "").strip())
    except ValueError:
        return None
    # An IPv4 caller on a dual-stack socket arrives as ::ffff:a.b.c.d.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_local_address(address: str | None, networks: Sequence[Network]) -> bool:
    """On the factory network? Anything unreadable is not."""
    ip = _parse(address)
    return ip is not None and any(
        ip.version == n.version and ip in n for n in networks)


def network_label(address: str | None, networks: Sequence[Network]) -> str:
    """Where a request came from, for the audit: never a guess."""
    if is_local_address(address, networks):
        return "factory network"
    ip = _parse(address)
    if ip is not None and ip.version == 4 and ip in PRIVATE_NETWORK:
        return "private network"
    return "outside"


def client_address(request: Request) -> str | None:
    return request.client.host if request.client else None


def remote_config(request: Request) -> vgconfig.RemoteConfig:
    """The site's limits; the defaults when the config failed to load."""
    cfg = getattr(request.app.state, "config", None)
    return cfg.remote if cfg is not None else vgconfig.RemoteConfig()


def is_remote(request: Request) -> bool:
    return not is_local_address(client_address(request), remote_config(request).lan_networks)


def where_from(request: Request) -> str:
    """`from 100.81.4.7 (private network)`, for audit entries."""
    address = client_address(request)
    label = network_label(address, remote_config(request).lan_networks)
    return f"from {address or 'an unknown address'} ({label})"


class SnapshotPacer:
    """One remote picture per interval per (session, camera, width).

    A request sooner than `EARLY` x the interval after the last one waits until
    its turn, then gets a new picture. It never gets an error for being early:
    a tile whose refresh was slowed must not look like a broken camera.

    The waits run on FastAPI's worker threads (the snapshot route is a plain
    `def`), so more than `max_waiting` on one session is refused: a runaway
    screen cannot tie up the server's threads.
    """

    EARLY = 0.8

    def __init__(self, max_waiting: int = 4,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], object] = time.sleep):
        self._max_waiting = max_waiting
        self._clock = clock
        self._sleep = sleep
        self._next: dict[tuple[str, str, int], float] = {}
        self._waiting: dict[str, int] = {}
        self._lock = threading.Lock()

    def waiting(self, session: str) -> int:
        with self._lock:
            return self._waiting.get(session, 0)

    def wait_turn(self, session: str, camera: str, width: int, interval: float) -> bool:
        """Block until this request's turn. False: too many already waiting."""
        key = (session, camera, width)
        with self._lock:
            now = self._clock()
            self._forget_before(now - 60)
            due = self._next.get(key, now)
            if due <= now:
                self._next[key] = now + interval * self.EARLY
                return True
            if self._waiting.get(session, 0) >= self._max_waiting:
                return False
            self._waiting[session] = self._waiting.get(session, 0) + 1
            # The turn after this one, so two early requests queue in order.
            self._next[key] = due + interval * self.EARLY
        try:
            self._sleep(due - now)
        finally:
            with self._lock:
                left = self._waiting.get(session, 1) - 1
                if left:
                    self._waiting[session] = left
                else:
                    self._waiting.pop(session, None)
        return True

    def _forget_before(self, cutoff: float) -> None:
        for key in [k for k, due in self._next.items() if due < cutoff]:
            del self._next[key]


@dataclass(eq=False)
class Slot:
    account: str
    last_sent: float
    open: bool = field(default=True)


class StreamSlots:
    """Each remote account's open live views, so a limit can be held."""

    IDLE_S = 15.0

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._slots: list[Slot] = []
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = self._clock() - self.IDLE_S
        for slot in [s for s in self._slots if s.last_sent < cutoff]:
            slot.open = False
            self._slots.remove(slot)

    def open(self, account: str, limit: int) -> Slot | None:
        """A place for one more live view, or None when the account is full."""
        with self._lock:
            self._prune()
            if sum(1 for s in self._slots if s.account == account) >= limit:
                return None
            slot = Slot(account=account, last_sent=self._clock())
            self._slots.append(slot)
            return slot

    def touch(self, slot: Slot) -> bool:
        """A frame went out. False: this view was freed and must stop."""
        with self._lock:
            self._prune()
            if not slot.open:
                return False
            slot.last_sent = self._clock()
            return True

    def close(self, slot: Slot) -> None:
        with self._lock:
            slot.open = False
            if slot in self._slots:
                self._slots.remove(slot)

    def count(self, account: str) -> int:
        with self._lock:
            self._prune()
            return sum(1 for s in self._slots if s.account == account)
