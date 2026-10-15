"""demo.py: annotated video rendering is driven by the detector's real output."""

import cv2
import numpy as np

import demo
from core.render import auto_scale
from detectors import create_detector
from tests.synth import fall_sequence, persons_from, walk_sequence


class FakeEstimator:
    def __init__(self, persons):
        self.persons, self.i = persons, 0

    def reset(self):
        self.i = 0

    def __call__(self, frame):
        out = self.persons[self.i] if self.i < len(self.persons) else []
        self.i += 1
        return out


def make_frames(folder, n, size=(240, 320)):
    folder.mkdir(parents=True)
    for i in range(n):
        cv2.imwrite(str(folder / f"f-{i:04d}.png"), np.full((*size, 3), 120, np.uint8))
    return folder


def banner_frames(path):
    """Number of output frames containing the red alert banner (pixel check)."""
    cap, hits = cv2.VideoCapture(str(path)), 0
    while True:
        ok, f = cap.read()
        if not ok:
            return hits
        h, w = f.shape[:2]
        edge = f[h // 2 - 85:h // 2 - 40, 10:60].reshape(-1, 3).mean(axis=0)   # banner's left edge, clear of text
        hits += int(edge[2] > 150 and edge[0] < 120)           # BGR: strong red, little blue


def test_alert_banner_appears_only_for_a_real_fall(tmp_path):
    kps, _ = fall_sequence(n_before=40, n_fall=12, n_after=40)
    folder = make_frames(tmp_path / "fall", len(kps))
    det = create_detector("rule_based")
    res = demo.render_demo(folder, tmp_path / "fall.mp4", det, FakeEstimator(persons_from(kps)),
                           title="Fall", end_hold_s=0)
    assert len(res["alerts"]) == 1 and res["frames"] == len(kps)
    assert res["size"] == (320 * 3, 240 * 3)                       # upscaled to 720p
    assert banner_frames(tmp_path / "fall.mp4") > 0

    kps, _ = walk_sequence(n=90)
    folder = make_frames(tmp_path / "walk", len(kps))
    res = demo.render_demo(folder, tmp_path / "walk.mp4", create_detector("rule_based"),
                           FakeEstimator(persons_from(kps)), end_hold_s=0)
    assert res["alerts"] == [] and banner_frames(tmp_path / "walk.mp4") == 0


def test_end_hold_and_scale(tmp_path):
    kps, _ = walk_sequence(n=20)
    folder = make_frames(tmp_path / "w", len(kps), size=(480, 640))
    res = demo.render_demo(folder, tmp_path / "w.mp4", create_detector("rule_based"),
                           FakeEstimator(persons_from(kps)), end_hold_s=1.0, scale=1)
    cap = cv2.VideoCapture(str(tmp_path / "w.mp4"))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 20 + 30      # 1 s hold at the default 30 fps
    assert res["size"] == (640, 480) and auto_scale(240) == 3 and auto_scale(720) == 1 and auto_scale(480) == 2
