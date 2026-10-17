"""Which model files the configured site needs, before the service starts.

Under strict mode a missing model stops the engine, which on a site means the
whole system is down. The installer runs this first, so a missing file stops
the install instead, with its name and where it goes.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR / "tools"))

import check_models  # noqa: E402
from vg import config as vgconfig  # noqa: E402

FACES = {"face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"}


def cam(cid="c1", **extra):
    return vgconfig.CameraConfig.parse(
        {"id": cid, "name": cid, "source": "rtsp://x/1", **extra}, "cameras[0]")


@pytest.fixture
def site(tmp_path):
    """The shipped models block, pointed at a temporary folder."""
    base = vgconfig.load()
    models = {name: replace(m, weights=tmp_path / m.weights.name)
              for name, m in base.models.items()}
    return replace(base, cameras=(), models=models), tmp_path


def names(needs):
    return {n.path.name for n in needs}


class TestWhatIsNeeded:
    def test_enrolment_always_needs_the_face_models(self, site):
        cfg, _ = site
        assert names(check_models.needed(cfg, [cam(enabled=False)])) == FACES

    def test_any_enabled_camera_needs_person_pose_and_falls(self, site):
        cfg, _ = site
        got = names(check_models.needed(cfg, [cam(features=[])]))
        assert got == FACES | {"yolov8s.pt", "yolov8s-pose.pt",
                               "checkpoints__temporal_model.pt"}

    @pytest.mark.parametrize("extra, file", [
        ({"features": ["weapons"]}, "knifebest.pt"),
        ({"features": ["lostitems"]}, "bagsearch.pt"),
        ({"features": ["vehicles"], "gate": 1, "direction": "entry"}, "plate_detector.pt"),
        ({"features": ["vehicles"], "gate": 1, "direction": "entry"}, "char_detector.pt"),
    ])
    def test_each_feature_adds_its_own(self, site, extra, file):
        cfg, _ = site
        assert file not in names(check_models.needed(cfg, [cam(features=[])]))
        assert file in names(check_models.needed(cfg, [cam(**extra)]))

    def test_a_disabled_camera_adds_nothing(self, site):
        cfg, _ = site
        got = names(check_models.needed(cfg, [cam(enabled=False, features=["weapons"])]))
        assert got == FACES

    def test_each_need_says_which_feature_and_cameras(self, site):
        cfg, _ = site
        knife = [n for n in check_models.needed(cfg, [cam("gate-a", features=["weapons"])])
                 if n.path.name == "knifebest.pt"]
        assert knife and "knife" in knife[0].why and "gate-a" in knife[0].why

    def test_a_model_missing_from_engine_yaml_is_named(self, site):
        cfg, _ = site
        models = {k: v for k, v in cfg.models.items() if k != "weapons"}
        needs = check_models.needed(replace(cfg, models=models),
                                    [cam(features=["weapons"])])
        bad = [n for n in needs if n.config_key == "weapons"]
        assert bad and bad[0].path is None


class TestTheCommand:
    def test_missing_files_are_listed_and_it_exits_1(self, site, capsys):
        cfg, folder = site
        code = check_models.report(cfg, [cam(features=["weapons"])])
        out = capsys.readouterr().out
        assert code == 1
        assert f"missing: knifebest.pt → {folder / 'knifebest.pt'}" in out

    def test_all_present_exits_0(self, site, capsys, monkeypatch):
        cfg, folder = site
        # Before needed(): the face models' folder must be the temporary one.
        monkeypatch.setattr(check_models, "FACE_DIR", folder)
        needs = check_models.needed(cfg, [cam(features=["weapons"])])
        for n in needs:
            assert folder in n.path.parents
            n.path.write_bytes(b"x")
        assert check_models.report(cfg, [cam(features=["weapons"])]) == 0

    def test_it_never_downloads(self):
        text = (ENGINE_DIR / "tools" / "check_models.py").read_text(encoding="utf-8")
        for word in ("urllib", "requests", "http.client", "ultralytics", "hf_hub",
                     "download("):
            assert word not in text
