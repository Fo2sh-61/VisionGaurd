"""A camera whose frames are pushed to the engine: the laptop webcam in the
cloud trial (specs/021-cloud-trial, owner's choice, 31 Oct 2026).

The engine on Kaggle cannot reach a laptop, so the laptop POSTs each frame.
What must hold: pushed frames reach the camera's stream; a camera that stops
receiving goes stale and then NO SIGNAL, like any dropped camera, and never
serves an old picture as live; only a camera that names itself as pushed
takes frames, so nobody can feed pictures into a real camera; and it is an
administrator's write, like every other change under /cameras.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as vgconfig  # noqa: E402
from vg.api import app as app_module  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.ingest import push  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402
from vg.ingest.source import CameraSource, SourceKind, parse_source  # noqa: E402


def jpeg(value: int = 128, size=(64, 48)) -> bytes:
    image = np.full((size[1], size[0], 3), value, dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


@pytest.fixture(autouse=True)
def _fresh_slots():
    push._reset_for_tests()
    yield
    push._reset_for_tests()


def camera(cid: str, source: str) -> vgconfig.CameraConfig:
    return vgconfig.CameraConfig.parse(
        {"id": cid, "name": cid, "source": source, "kind": "Webcam", "fps": 5,
         "features": [], "enabled": True}, cid)


class TestParsing:
    def test_push_names_its_camera(self):
        assert parse_source("push:cam-webcam") == (SourceKind.PUSH, "cam-webcam")

    def test_push_needs_a_name(self):
        with pytest.raises(ValueError, match="own id"):
            parse_source("push:")

    def test_a_push_source_must_name_its_own_camera(self):
        with pytest.raises(vgconfig.ConfigError, match="its own camera"):
            camera("cam-webcam", "push:cam-gate")


class TestPushCapture:
    def test_a_pushed_frame_comes_out_as_pixels(self):
        cap = push.PushCapture("cam-x", timeout_seconds=1)
        push.put("cam-x", jpeg(200))
        ok, image = cap.read()
        assert ok and image.shape == (48, 64, 3)
        assert abs(int(image.mean()) - 200) < 5

    def test_no_new_frame_is_a_failed_grab_not_the_old_picture(self):
        cap = push.PushCapture("cam-x", timeout_seconds=0.2)
        push.put("cam-x", jpeg())
        assert cap.grab()
        started = time.monotonic()
        assert not cap.grab()  # nothing newer arrived
        assert time.monotonic() - started >= 0.2

    def test_a_frame_from_before_it_opened_is_old_news(self):
        push.put("cam-x", jpeg())
        cap = push.PushCapture("cam-x", timeout_seconds=0.2)
        assert not cap.grab()

    def test_only_the_newest_frame_is_kept(self):
        cap = push.PushCapture("cam-x", timeout_seconds=1)
        for value in (10, 120, 240):
            push.put("cam-x", jpeg(value))
        ok, image = cap.read()
        assert ok and abs(int(image.mean()) - 240) < 5
        assert not push.PushCapture("cam-x", timeout_seconds=0.1).grab()

    def test_a_grab_wakes_as_soon_as_a_frame_arrives(self):
        cap = push.PushCapture("cam-x", timeout_seconds=5)
        threading.Timer(0.1, lambda: push.put("cam-x", jpeg())).start()
        started = time.monotonic()
        assert cap.grab()
        assert time.monotonic() - started < 2

    @pytest.mark.parametrize("body", [b"", b"not a picture", b"\x89PNG\r\n"])
    def test_only_jpegs(self, body):
        with pytest.raises(push.NotAJpeg):
            push.put("cam-x", body)

    def test_not_a_whole_file(self):
        with pytest.raises(push.NotAJpeg):
            push.put("cam-x", b"\xff\xd8" + bytes(push.MAX_BYTES))


class TestTheCameraSource:
    def test_frames_flow_and_stop_means_stale(self):
        source = CameraSource("cam-webcam", "push:cam-webcam", read_timeout_ms=300,
                              live_capture="always")
        assert source.open()
        push.put("cam-webcam", jpeg(90))
        fresh = source.read()
        assert fresh is not None and not fresh.is_stale
        # The sender stops: the next read times out and is served as stale.
        later = source.read()
        assert later is None or later.is_stale
        source.close()


@pytest.fixture
def app_with(user_store, monkeypatch):
    """An app whose registry holds the given cameras (not started)."""
    def _make(*cameras):
        monkeypatch.delenv("VG_DEV_SIGNIN", raising=False)
        monkeypatch.delenv("VG_CONFIG_OVERLAY", raising=False)
        app_module.set_store(MockStore())
        application = create_app()
        application.state.users = user_store
        application.state.registry = CameraRegistry(list(cameras))
        return application
    return _make


class TestTheEndpoint:
    PATH = "/cameras/cam-webcam/push"

    def test_an_admin_pushes_a_frame(self, app_with, sign_in):
        app = app_with(camera("cam-webcam", "push:cam-webcam"))
        token = sign_in(app, "admin")
        cap = push.PushCapture("cam-webcam", timeout_seconds=1)
        response = TestClient(app).post(
            self.PATH, content=jpeg(), headers={"Authorization": f"Bearer {token}",
                                                "Content-Type": "image/jpeg"})
        assert response.status_code == 204
        assert cap.grab()

    def test_nobody_signed_in_is_refused(self, app_with):
        app = app_with(camera("cam-webcam", "push:cam-webcam"))
        assert TestClient(app).post(self.PATH, content=jpeg()).status_code == 401

    def test_it_is_an_admin_write(self, app_with, sign_in):
        app = app_with(camera("cam-webcam", "push:cam-webcam"))
        token = sign_in(app, "it")
        response = TestClient(app).post(
            self.PATH, content=jpeg(), headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_real_camera_never_takes_pushed_frames(self, app_with, sign_in):
        app = app_with(camera("cam-gate", "rtsp://10.0.0.5/stream"))
        token = sign_in(app, "admin")
        response = TestClient(app).post(
            "/cameras/cam-gate/push", content=jpeg(),
            headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 409

    def test_an_unknown_camera_is_404(self, app_with, sign_in):
        app = app_with(camera("cam-webcam", "push:cam-webcam"))
        token = sign_in(app, "admin")
        response = TestClient(app).post(
            "/cameras/cam-nope/push", content=jpeg(),
            headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 404

    def test_not_a_picture_is_415(self, app_with, sign_in):
        app = app_with(camera("cam-webcam", "push:cam-webcam"))
        token = sign_in(app, "admin")
        response = TestClient(app).post(
            self.PATH, content=b"hello", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 415


class TestTheCloudProfile:
    def test_the_webcam_joins_the_clip_without_replacing_the_sites_cameras(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv("VG_CONFIG_OVERLAY", "engine/profiles/cloud.yaml")
        monkeypatch.setenv("VG_CAMERAS", "cam-clip,cam-webcam")
        monkeypatch.setenv("VG_TRIAL_DIR", str(tmp_path))
        monkeypatch.setenv("VG_PUBLIC_URL", "https://x.example")
        cfg = vgconfig.load()
        running = {c.id: c for c in cfg.cameras if c.enabled}
        assert set(running) == {"cam-clip", "cam-webcam"}
        assert running["cam-webcam"].source == "push:cam-webcam"
        # engine.yaml's cameras are all still defined, just not running.
        assert cfg.camera("cam-laptop") is not None

    def test_the_webcam_runs_what_the_laptop_camera_runs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VG_CONFIG_OVERLAY", "engine/profiles/cloud.yaml")
        monkeypatch.setenv("VG_TRIAL_DIR", str(tmp_path))
        monkeypatch.setenv("VG_PUBLIC_URL", "https://x.example")
        monkeypatch.delenv("VG_CAMERAS", raising=False)
        cfg = vgconfig.load()
        assert set(cfg.camera("cam-webcam").features) == set(cfg.camera("cam-laptop").features)

    def test_add_cameras_must_be_a_list(self, monkeypatch, tmp_path):
        bad = tmp_path / "o.yaml"
        bad.write_text("add_cameras: nope\n")
        monkeypatch.setenv("VG_CONFIG_OVERLAY", str(bad))
        with pytest.raises(vgconfig.ConfigError, match="add_cameras"):
            vgconfig.load()


class TestTheSender:
    """tools/cloud/webcam_sender.py: the address as Mohamed pastes it."""

    @pytest.fixture(autouse=True)
    def _path(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "cloud"))

    @pytest.mark.parametrize("pasted,expected", [
        ("https://plasma-nebraska.trycloudflare.com", ("https", "plasma-nebraska.trycloudflare.com", 443)),
        ("https://plasma-nebraska.trycloudflare.com/", ("https", "plasma-nebraska.trycloudflare.com", 443)),
        ("  plasma-nebraska.trycloudflare.com  ", ("https", "plasma-nebraska.trycloudflare.com", 443)),
        ("http://127.0.0.1:8000", ("http", "127.0.0.1", 8000)),
    ])
    def test_the_address_is_read_as_pasted(self, pasted, expected):
        import webcam_sender
        assert webcam_sender.normalise(pasted) == expected

    def test_a_non_address_is_refused(self):
        import webcam_sender
        with pytest.raises(ValueError):
            webcam_sender.normalise("ftp://x")

    def test_it_sends_to_the_pushed_camera_the_profile_defines(self):
        import webcam_sender
        assert webcam_sender.CAMERA_ID == "cam-webcam"
