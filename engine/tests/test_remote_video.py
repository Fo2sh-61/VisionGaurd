"""Video that fits a remote link (spec 020 US3, T022).

A caller outside the factory network gets camera tiles as still pictures no
wider than `tile_width`, one per `tile_interval_s`, and live views at
`live_width` and at most `live_fps` pictures a second, two at a time per
account. The engine applies all of it, so a screen that ignores the limits
still gets only what they allow. A tile that asks early waits its turn; it is
never refused for being early, because a slowed refresh must not look like a
broken camera. Nothing changes on the factory network, and event clips are
always sent in full.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import replace
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from vg.api import app as app_module
from vg.api import remote
from vg import config as vgconfig
from vg.api.store import MockStore
from vg.config import CameraConfig
from vg.ingest.registry import CameraRegistry
from vg.ingest.source import Frame

from conftest import LAN, NETBIRD


def a_frame(seq: int = 1) -> Frame:
    return Frame("c1", np.zeros((1080, 1920, 3), np.uint8), datetime.now(timezone.utc), seq)


class Clock:
    """Moves only when somebody sleeps, so a wait is recorded, not waited."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def video_app(user_store, clock):
    app_module.set_store(MockStore())
    application = app_module.create_app()
    application.state.users = user_store
    registry = CameraRegistry(
        [CameraConfig.parse({"id": "c1", "name": "C", "source": "webcam:99"}, "c")])
    registry.worker("c1").source._last_good = a_frame()
    application.state.registry = registry
    application.state.snapshot_pacer = remote.SnapshotPacer(clock=clock, sleep=clock.sleep)
    yield application
    app_module.SHUTTING_DOWN.clear()
    app_module.set_store(MockStore())


@pytest.fixture
def session(video_app, user_store, sign_in):
    """(token, user id) for one admin."""
    token = sign_in(video_app, "admin")
    return token, user_store.user_for_token(token).id


def client(app, token, where):
    return TestClient(app, client=where, headers={"Authorization": f"Bearer {token}"})


def width_of(jpeg: bytes) -> int:
    return int(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape[1])


def snapshot_width(response) -> int:
    assert response.status_code == 200, response.text
    return width_of(response.content)


# --- tiles ---------------------------------------------------------------------

class TestRemoteTiles:
    @pytest.mark.parametrize("query", ["", "?width=1280", "?width=640", "?width=480"])
    def test_a_remote_picture_is_never_wider_than_the_limit(self, video_app, session, query):
        token, _ = session
        assert snapshot_width(client(video_app, token, NETBIRD).get(f"/cameras/c1/snapshot{query}")) == 320

    def test_a_site_sets_its_own_tile_width(self, video_app, session):
        token, _ = session
        video_app.state.config = replace(vgconfig.load(), remote=vgconfig.RemoteConfig(tile_width=480))
        assert snapshot_width(client(video_app, token, NETBIRD).get("/cameras/c1/snapshot?width=640")) == 480

    def test_the_rate_a_remote_tile_asks_of_the_camera_is_capped(self, video_app, session):
        token, _ = session
        client(video_app, token, NETBIRD).get("/cameras/c1/snapshot?width=320&fps=15")
        source = video_app.state.registry.worker("c1").source
        # Capped at 1 / 2 s, which `note_tile` rounds up to its floor of one a
        # second: below any camera's own analysis rate, so nothing speeds up.
        assert source._tile_fps(time.monotonic()) == 1

    def test_an_early_refresh_waits_its_turn_and_still_gets_a_picture(self, video_app, session, clock):
        token, _ = session
        far = client(video_app, token, NETBIRD)
        assert snapshot_width(far.get("/cameras/c1/snapshot?width=320")) == 320
        assert snapshot_width(far.get("/cameras/c1/snapshot?width=320")) == 320
        assert clock.slept == [pytest.approx(1.6)]           # 0.8 x 2 s

    def test_too_many_waiting_is_429_with_a_reason(self, video_app, session):
        token, _ = session

        class Full:
            def wait_turn(self, *args):
                return False
        video_app.state.snapshot_pacer = Full()
        answer = client(video_app, token, NETBIRD).get("/cameras/c1/snapshot?width=320")
        assert answer.status_code == 429
        assert "too many" in answer.json()["detail"].lower()

    def test_the_factory_network_is_unchanged(self, video_app, session, clock):
        token, _ = session
        near = client(video_app, token, LAN)
        assert snapshot_width(near.get("/cameras/c1/snapshot")) == 1280
        assert snapshot_width(near.get("/cameras/c1/snapshot?width=1280")) == 1280
        near.get("/cameras/c1/snapshot?width=480&fps=15")
        assert video_app.state.registry.worker("c1").source._tile_fps(time.monotonic()) == 15
        assert clock.slept == []


# --- live views ------------------------------------------------------------------

def run_stream(app, token, where, seconds=1.2):
    """Open the live view with a camera making 30 pictures a second, and stop
    the server after `seconds`. Returns (status, [(arrival, width), ...])."""
    source = app.state.registry.worker("c1").source
    start = time.monotonic()
    seq = itertools.count(1)

    def thirty_a_second(last, timeout):
        time.sleep(1 / 30)
        if time.monotonic() - start > seconds:
            app_module.SHUTTING_DOWN.set()
        return a_frame(next(seq))
    source.wait_for_frame = thirty_a_second
    try:
        response = client(app, token, where).get("/cameras/c1/stream")
    finally:
        app_module.SHUTTING_DOWN.clear()
    if response.status_code != 200:
        return response.status_code, response, []
    parts = [p for p in response.content.split(b"--vgframe\r\n") if p]
    jpegs = [p.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n") for p in parts]
    return response.status_code, response, [width_of(j) for j in jpegs]


class TestRemoteLiveView:
    def test_reduced_in_size_and_rate(self, video_app, session):
        token, _ = session
        status, _, widths = run_stream(video_app, token, NETBIRD, seconds=1.2)
        assert status == 200
        assert widths and set(widths) == {480}
        assert len(widths) <= 5 * 1.2 + 2                  # 5 a second, never queued

    def test_the_factory_network_gets_every_picture_at_full_size(self, video_app, session):
        token, _ = session
        status, _, widths = run_stream(video_app, token, LAN, seconds=1.2)
        assert status == 200 and set(widths) == {960}
        assert len(widths) >= 20

    def test_a_third_live_view_is_refused_with_a_reason(self, video_app, session):
        token, user_id = session
        slots = video_app.state.remote_streams
        assert slots.open(user_id, 2) and slots.open(user_id, 2)
        status, response, _ = run_stream(video_app, token, NETBIRD, seconds=0.2)
        assert status == 429
        assert response.json()["detail"] == "Close another live view first."

    def test_the_factory_network_has_no_live_view_limit(self, video_app, session):
        token, user_id = session
        slots = video_app.state.remote_streams
        slots.open(user_id, 2), slots.open(user_id, 2)
        status, _, _ = run_stream(video_app, token, LAN, seconds=0.2)
        assert status == 200

    def test_a_closed_view_frees_its_place(self, video_app, session):
        token, user_id = session
        run_stream(video_app, token, NETBIRD, seconds=0.3)
        assert video_app.state.remote_streams.count(user_id) == 0

    def test_a_view_whose_place_was_freed_stops_sending(self, video_app, session):
        """The phone lost signal, its place went to another view: if this one
        wakes up again it must not be a third live view."""
        token, user_id = session
        slots = video_app.state.remote_streams
        source = video_app.state.registry.worker("c1").source
        seq = itertools.count(1)
        calls = itertools.count(1)

        def frames(last, timeout):
            time.sleep(1 / 30)
            if next(calls) == 10:
                for slot in list(slots._slots):
                    slots.close(slot)               # what 15 s of silence does
            if next(seq) > 400:
                app_module.SHUTTING_DOWN.set()      # a backstop, never reached
            return a_frame(next(seq))
        source.wait_for_frame = frames
        try:
            started = time.monotonic()
            response = client(video_app, token, NETBIRD).get("/cameras/c1/stream")
        finally:
            app_module.SHUTTING_DOWN.clear()
        assert response.status_code == 200
        assert time.monotonic() - started < 3
        assert slots.count(user_id) == 0
