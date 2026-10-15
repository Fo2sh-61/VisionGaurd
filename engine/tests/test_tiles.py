"""Grid tiles: a picture sized to the tile, at the rate the tile shows it.

A tile used to be stuck at the camera's analytics rate - 5 new pictures a
second at best - however often it asked, because a camera nobody had opened
only decoded at that rate. And it was sent a 1280 px picture to show in a
tile 128 px tall. Measured at 1080p, compressing that picture was most of
what a tile cost; sized to the tile, 15 a second costs about what 5 did.
"""

from __future__ import annotations

import inspect
import time
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from vg.ingest.source import MAX_TILE_FPS, TILE_VIEW_SECONDS, CameraSource, Frame


def a_frame(seq: int = 1, width: int = 1920, height: int = 1080) -> Frame:
    return Frame("c1", np.zeros((height, width, 3), np.uint8),
                 datetime.now(timezone.utc), seq)


def camera(**kw) -> CameraSource:
    return CameraSource("c1", "file:nothing.mp4", **{"target_fps": 5.0, **kw})


# ---------------------------------------------------------------------------
# the decode rate a tile asks for
# ---------------------------------------------------------------------------

class TestTileRate:
    def test_a_tile_raises_the_decode_rate_to_its_own(self):
        cam = camera()
        cam.note_tile(15, now=0.0)
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.05) is False
        # 70 ms later: due at 15 a second, and 130 ms early at the camera's 5.
        assert cam.wants_decode(now=0.07) is True

    def test_without_a_tile_the_analytics_rate_is_untouched(self):
        cam = camera()
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.07) is False
        assert cam.wants_decode(now=0.21) is True

    def test_a_tile_view_lapses_on_its_own(self):
        """Nothing to release, so a closed tab cannot leak a fast camera."""
        cam = camera()
        cam.note_tile(15, now=0.0)
        later = TILE_VIEW_SECONDS + 0.5
        assert cam.wants_decode(now=later) is True
        assert cam.wants_decode(now=later + 0.1) is False  # back to 5 a second

    def test_a_tile_cannot_ask_for_more_than_the_cap(self):
        """Full rate is what opening the camera is for."""
        cam = camera()
        cam.note_tile(60, now=0.0)
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.03) is False  # due at 60, not at 15
        assert cam.wants_decode(now=1 / MAX_TILE_FPS + 0.001) is True

    def test_a_slow_tile_never_lowers_the_analytics_rate(self):
        """A big grid's 2 a second must not starve the camera's own features."""
        cam = camera()
        cam.note_tile(2, now=0.0)
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.21) is True

    def test_a_slower_tile_cannot_keep_a_closed_faster_one_alive(self):
        """Keyed by rate: the phone at 5 renews its own ask, not the console's 15."""
        cam = camera()
        cam.note_tile(15, now=0.0)
        cam.note_tile(5, now=1.9)
        cam.note_tile(5, now=3.0)
        assert cam.wants_decode(now=3.0) is True
        assert cam.wants_decode(now=3.1) is False

    @pytest.mark.parametrize("nonsense", [0, -3, float("nan")])
    def test_a_nonsense_rate_is_ignored(self, nonsense):
        cam = camera()
        cam.note_tile(nonsense, now=0.0)
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.07) is False

    def test_an_infinite_rate_is_capped_not_raised(self):
        cam = camera()
        cam.note_tile(float("inf"), now=0.0)
        assert cam.wants_decode(now=0.0) is True
        assert cam.wants_decode(now=0.07) is True

    def test_an_open_camera_still_decodes_every_frame(self):
        cam = camera()
        cam.note_tile(15, now=0.0)
        with cam.watched():
            assert cam.wants_decode(now=0.0) is True
            assert cam.wants_decode(now=0.01) is True


# ---------------------------------------------------------------------------
# one encode per size per frame
# ---------------------------------------------------------------------------

class TestPictureCache:
    def _worker(self, monkeypatch):
        from vg.config import CameraConfig
        from vg.ingest.framebus import FrameBus
        from vg.ingest.registry import CameraWorker

        worker = CameraWorker(
            CameraConfig.parse({"id": "c1", "name": "C", "source": "webcam:99"}, "c"),
            FrameBus(),
        )
        encodes: list[tuple[int, int]] = []
        real = CameraWorker.encode_jpeg

        def counting(frame, quality=80, max_width=1280):
            encodes.append((quality, max_width))
            return real(frame, quality, max_width)

        monkeypatch.setattr(worker, "encode_jpeg", counting)
        return worker, encodes

    def test_two_sizes_of_one_frame_are_encoded_once_each(self, monkeypatch):
        """A single slot threw each size away for the other.

        Console tiles at 480 and the phone at 1280 polling one camera would
        have encoded the same frame again on every single request.
        """
        worker, encodes = self._worker(monkeypatch)
        worker.source._last_good = a_frame(seq=1)

        for _ in range(3):
            worker.snapshot_jpeg()
            worker.snapshot_jpeg(quality=70, max_width=480)
        assert sorted(encodes) == [(70, 480), (80, 1280)]

    def test_a_new_frame_is_encoded_again(self, monkeypatch):
        worker, encodes = self._worker(monkeypatch)
        worker.source._last_good = a_frame(seq=1)
        worker.snapshot_jpeg(quality=70, max_width=480)
        worker.source._last_good = a_frame(seq=2)
        worker.snapshot_jpeg(quality=70, max_width=480)
        assert encodes == [(70, 480), (70, 480)]


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def snapshot_app(user_store):
    """An app whose one camera has a 1920x1080 frame and no capture thread."""
    from vg.api import app as app_module
    from vg.api.store import MockStore
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    app_module.set_store(MockStore())
    application = app_module.create_app()
    application.state.users = user_store
    registry = CameraRegistry(
        [CameraConfig.parse({"id": "c1", "name": "C", "source": "webcam:99"}, "c")])
    registry.worker("c1").source._last_good = a_frame()
    application.state.registry = registry
    yield application
    app_module.set_store(MockStore())


def picture_width(response) -> int:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    return int(image.shape[1])


class TestSnapshotEndpoint:
    def test_left_alone_it_is_the_full_picture_as_before(self, snapshot_app, authed):
        """A caller that sends neither parameter sees no change."""
        client = authed(snapshot_app)
        assert picture_width(client.get("/cameras/c1/snapshot?t=1")) == 1280
        source = snapshot_app.state.registry.worker("c1").source
        assert source._tile_fps(time.monotonic()) == 0

    @pytest.mark.parametrize("asked, sent", [
        (300, 320), (320, 320), (321, 480), (700, 960), (5000, 1280),
    ])
    def test_a_width_rounds_up_to_a_tile_size(self, snapshot_app, authed, asked, sent):
        client = authed(snapshot_app)
        assert picture_width(client.get(f"/cameras/c1/snapshot?width={asked}")) == sent

    def test_the_tile_rate_reaches_the_camera(self, snapshot_app, authed):
        client = authed(snapshot_app)
        client.get("/cameras/c1/snapshot?width=480&fps=15")
        source = snapshot_app.state.registry.worker("c1").source
        assert source._tile_fps(time.monotonic()) == 15

    def test_the_encode_does_not_run_on_the_event_loop(self, snapshot_app):
        """Inside `async def` every encode held up every other request."""
        route = next(r for r in snapshot_app.routes
                     if getattr(r, "path", "") == "/cameras/{camera_id}/snapshot")
        assert not inspect.iscoroutinefunction(route.endpoint)
