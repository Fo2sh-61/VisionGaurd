"""Telling a remote request apart (spec 020, T004 and T013).

A request is local only when its address is on the factory network
(`remote.lan_networks`). Everything else is remote: NetBird's 100.64/10, IPv6,
an unreadable address. Getting this wrong must cost video quality and self
sign-up, never exposure, so every doubtful case lands on "remote".

Starlette's TestClient sends from the made-up host "testclient", which is not
an address at all, so it is remote too. A test about the factory network says
so with `client=LAN`.

The real address reaching the engine (serve.py trusts X-Forwarded-For only from
127.0.0.1, and Caddy replaces the header) is pinned in `test_front.py`.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from vg import config as vgconfig
from vg.api import remote
from vg.api.app import create_app

LAN = ("192.168.1.20", 50000)
NETBIRD = ("100.81.4.7", 50000)
NETWORKS = vgconfig.RemoteConfig().lan_networks


class TestWhoIsLocal:
    @pytest.mark.parametrize("address", [
        "192.168.1.20", "10.1.2.3", "172.20.0.1", "127.0.0.1", "::1",
        "::ffff:192.168.1.20",      # an IPv4 caller on a dual-stack socket
    ])
    def test_the_factory_network_is_local(self, address):
        assert remote.is_local_address(address, NETWORKS)

    @pytest.mark.parametrize("address", [
        "100.81.4.7",               # NetBird
        "100.64.0.1",
        "8.8.8.8",
        "2001:db8::1",
        "fe80::1",
        "172.32.0.1",               # just outside 172.16/12
        "testclient", "?", "", None,
    ])
    def test_everything_else_is_remote(self, address):
        assert not remote.is_local_address(address, NETWORKS)

    def test_a_site_list_replaces_the_defaults(self):
        own = vgconfig.RemoteConfig.parse({"lan_networks": ["10.20.0.0/16"]}, "remote")
        assert remote.is_local_address("10.20.3.4", own.lan_networks)
        assert not remote.is_local_address("192.168.1.20", own.lan_networks)

    @pytest.mark.parametrize("address,label", [
        ("192.168.1.20", "factory network"),
        ("100.81.4.7", "private network"),
        ("8.8.8.8", "outside"),
        (None, "outside"),
    ])
    def test_where_a_request_came_from_in_words(self, address, label):
        assert remote.network_label(address, NETWORKS) == label


class TestConnection:
    """`GET /connection`: what this caller gets, so both apps can say so."""

    @staticmethod
    def _client(sign_in, address):
        app = create_app()
        token = sign_in(app, "admin")
        return TestClient(app, client=address,
                          headers={"Authorization": f"Bearer {token}"})

    def test_a_lan_caller_is_not_remote(self, sign_in):
        body = self._client(sign_in, LAN).get("/connection").json()
        assert body == {
            "remote": False, "tileIntervalSeconds": 2.0, "liveWidth": 480,
            "liveFps": 5.0, "liveViews": 2, "liveViewsOpen": 0,
        }

    def test_a_netbird_caller_is_remote_with_the_limits(self, sign_in):
        body = self._client(sign_in, NETBIRD).get("/connection").json()
        assert body["remote"] is True
        assert body["tileIntervalSeconds"] == 2.0 and body["liveViews"] == 2

    def test_no_session_is_401(self, user_store):
        app = create_app()
        app.state.users = user_store
        assert TestClient(app, client=LAN).get("/connection").status_code == 401


# --- the pacer and the stream slots, on an injected clock --------------------

class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class TestSnapshotPacer:
    def test_the_first_request_goes_straight_through(self):
        clock = Clock()
        pacer = remote.SnapshotPacer(clock=clock, sleep=clock.sleep)
        assert pacer.wait_turn("tok", "cam-1", 320, 2.0)
        assert clock.slept == []

    def test_an_early_request_waits_its_turn_rather_than_failing(self):
        clock = Clock()
        pacer = remote.SnapshotPacer(clock=clock, sleep=clock.sleep)
        pacer.wait_turn("tok", "cam-1", 320, 2.0)
        clock.now += 0.5
        assert pacer.wait_turn("tok", "cam-1", 320, 2.0)
        assert clock.slept == [pytest.approx(1.1)]      # 0.8 x 2 s after the first

    def test_a_request_on_time_does_not_wait(self):
        clock = Clock()
        pacer = remote.SnapshotPacer(clock=clock, sleep=clock.sleep)
        pacer.wait_turn("tok", "cam-1", 320, 2.0)
        clock.now += 2.0
        pacer.wait_turn("tok", "cam-1", 320, 2.0)
        assert clock.slept == []

    def test_each_camera_and_width_has_its_own_pace(self):
        clock = Clock()
        pacer = remote.SnapshotPacer(clock=clock, sleep=clock.sleep)
        pacer.wait_turn("tok", "cam-1", 320, 2.0)
        pacer.wait_turn("tok", "cam-2", 320, 2.0)
        pacer.wait_turn("tok", "cam-1", 480, 2.0)
        pacer.wait_turn("other", "cam-1", 320, 2.0)
        assert clock.slept == []

    def test_more_than_four_waiting_on_one_session_is_refused(self):
        clock = Clock()
        release = threading.Event()
        pacer = remote.SnapshotPacer(clock=clock, sleep=lambda s: release.wait(5))
        pacer.wait_turn("tok", "cam-1", 320, 2.0)
        answers: list[bool] = []
        waiters = [threading.Thread(target=lambda: answers.append(
            pacer.wait_turn("tok", "cam-1", 320, 2.0))) for _ in range(4)]
        for w in waiters:
            w.start()
        deadline = time.monotonic() + 2
        while pacer.waiting("tok") < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            assert pacer.waiting("tok") == 4
            assert not pacer.wait_turn("tok", "cam-1", 320, 2.0)
            assert pacer.wait_turn("tok", "cam-2", 320, 2.0)    # on time: no wait
        finally:
            release.set()
            for w in waiters:
                w.join(5)
        assert answers == [True] * 4
        assert pacer.waiting("tok") == 0


class TestStreamSlots:
    def test_two_open_then_the_third_is_refused(self):
        slots = remote.StreamSlots(clock=Clock())
        a, b = slots.open("u1", 2), slots.open("u1", 2)
        assert a and b
        assert slots.open("u1", 2) is None
        assert slots.open("u2", 2) is not None          # per account
        assert slots.count("u1") == 2

    def test_closing_one_frees_its_place(self):
        slots = remote.StreamSlots(clock=Clock())
        a = slots.open("u1", 2)
        slots.open("u1", 2)
        slots.close(a)
        assert slots.open("u1", 2) is not None

    def test_a_viewer_that_vanished_frees_its_place_within_15_seconds(self):
        clock = Clock()
        slots = remote.StreamSlots(clock=clock)
        a = slots.open("u1", 2)
        b = slots.open("u1", 2)
        clock.now += 10
        assert slots.touch(b)                           # b is still sending
        clock.now += 5.1
        assert slots.open("u1", 2) is not None          # a's place is free
        assert not slots.touch(a)                       # and a must stop
        assert slots.count("u1") == 2

    def test_closing_twice_is_harmless(self):
        slots = remote.StreamSlots(clock=Clock())
        a = slots.open("u1", 2)
        slots.close(a)
        slots.close(a)
        assert slots.count("u1") == 0
