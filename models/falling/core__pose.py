"""Pose estimator: YOLOv8-pose + ByteTrack, returning per-person keypoints with
stable track ids.

Ported from ``PoseDetector`` in britishnew/dual_camera_fight_detector.py (same
model, confidence, image size and tracker), minus the TensorRT/custom-model
paths. ultralytics is imported lazily so training/tests don't need it.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PERSON_CONF = 0.30      # ByteTrack handles short occlusions; a lower threshold
                        # keeps partially visible people in the track.
INFER_IMGSZ = 640
DEFAULT_POSE_NAME = "yolov8s-pose.pt"

# Searched in order when no weights are given. The britishnew copy avoids a
# second download of the same file.
POSE_WEIGHT_CANDIDATES = (
    PROJECT_ROOT / "models" / DEFAULT_POSE_NAME,
    Path("E:/britishnew/models") / DEFAULT_POSE_NAME,
)


@dataclass
class Person:
    """One detected person in one frame."""
    track_id: int | None                       # None until ByteTrack confirms the track
    bbox: tuple[float, float, float, float]    # x1, y1, x2, y2 in pixels
    conf: float
    keypoints: np.ndarray                      # (17, 3): x, y, confidence


def default_pose_weights():
    """$FALLDET_POSE_WEIGHTS, else a local yolov8s-pose.pt, else the bare name
    (which makes ultralytics download it)."""
    env = os.environ.get("FALLDET_POSE_WEIGHTS")
    if env:
        return env
    for path in POSE_WEIGHT_CANDIDATES:
        if path.is_file():
            return str(path)
    return DEFAULT_POSE_NAME


def _has_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


class PoseEstimator:
    """Callable: ``estimator(frame_bgr) -> list[Person]``. Call ``reset()``
    before each new video so track ids don't leak across videos."""

    def __init__(self, weights=None, conf=PERSON_CONF, imgsz=INFER_IMGSZ, device=None,
                 tracker="bytetrack.yaml"):
        from ultralytics import YOLO
        from ultralytics.cfg import DEFAULT_CFG_DICT

        self.weights = weights or default_pose_weights()
        self.model = YOLO(self.weights, task="pose")
        self.conf = conf
        self.imgsz = imgsz
        cuda = _has_cuda()
        self.device = device if device is not None else (0 if cuda else "cpu")
        self.tracker = tracker
        # FP16 on GPU; newer ultralytics renamed half=True to quantize=16.
        self._precision = {}
        if cuda and str(self.device) != "cpu" and not str(self.weights).endswith(".engine"):
            self._precision = {"quantize": 16} if "quantize" in DEFAULT_CFG_DICT else {"half": True}

    def reset(self):
        """Forget all tracks (new video / new stream)."""
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()

    def __call__(self, frame):
        kwargs = {
            "conf": self.conf,
            "imgsz": self.imgsz,
            "device": self.device,
            "verbose": False,
            "persist": True,
            "tracker": self.tracker,
            "classes": [0],   # person only
            **self._precision,
        }
        result = self.model.track(frame, **kwargs)[0]
        if result.boxes is None:
            return []
        kp_arr = None
        if getattr(result, "keypoints", None) is not None:
            try:
                kp_arr = result.keypoints.data.cpu().numpy()   # (N, 17, 3)
            except Exception:
                kp_arr = None
        out = []
        for i, box in enumerate(result.boxes):
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            tid = None if box.id is None else int(box.id[0])
            kps = (kp_arr[i].astype(np.float32) if kp_arr is not None and i < len(kp_arr)
                   else np.zeros((17, 3), dtype=np.float32))
            out.append(Person(track_id=tid, bbox=(x1, y1, x2, y2), conf=float(box.conf[0]),
                              keypoints=kps))
        return out
