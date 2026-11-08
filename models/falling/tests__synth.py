"""Synthetic skeletons and pose caches, so tests need neither YOLO weights nor a dataset."""

import numpy as np

from core.features import FALLEN, FALLING, NORMAL
from core.pose import Person
from train.prepare_data import CACHE_VERSION, stitch_subject

# Upright COCO-17 pose relative to the point between the feet, for a person
# 1 unit tall facing the camera (image y points down, so "up" is negative).
UPRIGHT = np.array([
    [0.00, -0.93],                   # nose
    [0.02, -0.95], [-0.02, -0.95],   # eyes (L, R)
    [0.05, -0.93], [-0.05, -0.93],   # ears
    [0.12, -0.80], [-0.12, -0.80],   # shoulders
    [0.15, -0.62], [-0.15, -0.62],   # elbows
    [0.16, -0.47], [-0.16, -0.47],   # wrists
    [0.08, -0.50], [-0.08, -0.50],   # hips
    [0.08, -0.27], [-0.08, -0.27],   # knees
    [0.08, -0.03], [-0.08, -0.03],   # ankles
])


def skeleton(cx, feet_y, height, angle_deg=0.0, conf=0.9, sway=0.0):
    """(17, 3) keypoints of a person tipped ``angle_deg`` sideways about their feet."""
    th = np.radians(angle_deg)
    off = UPRIGHT * height
    off = off + np.array([sway, 0.0]) * height * (off[:, 1:2] < -0.4 * height)   # arms/upper body sway
    rot = np.stack([off[:, 0] * np.cos(th) - off[:, 1] * np.sin(th),
                    off[:, 0] * np.sin(th) + off[:, 1] * np.cos(th)], axis=1)
    kps = np.empty((17, 3), dtype=np.float32)
    kps[:, :2] = rot + np.array([cx, feet_y])
    kps[:, 2] = conf
    return kps


def fall_sequence(n_before=45, n_fall=15, n_after=45, cx=300.0, feet_y=400.0, height=220.0,
                  walk_speed=1.5, rng=None):
    """Walk, tip over during ``n_fall`` frames, lie still. Returns (kps (T,17,3), labels (T,))."""
    rng = rng or np.random.default_rng(0)
    kps, labels = [], []
    for t in range(n_before):
        kps.append(skeleton(cx + walk_speed * t, feet_y, height, sway=0.03 * np.sin(t / 3)))
        labels.append(NORMAL)
    x = cx + walk_speed * n_before
    for t in range(n_fall):
        kps.append(skeleton(x, feet_y, height, angle_deg=90.0 * (t + 1) / n_fall))
        labels.append(FALLING)
    for _ in range(n_after):
        kps.append(skeleton(x, feet_y, height, angle_deg=90.0))
        labels.append(FALLEN)
    kps = np.stack(kps)
    kps[..., :2] += rng.normal(0, 1.0, size=kps[..., :2].shape)
    return kps.astype(np.float32), np.array(labels, dtype=np.int8)


def walk_sequence(n=105, cx=100.0, feet_y=400.0, height=220.0, walk_speed=2.0, rng=None):
    rng = rng or np.random.default_rng(1)
    kps = np.stack([skeleton(cx + walk_speed * t, feet_y, height, sway=0.03 * np.sin(t / 3))
                    for t in range(n)])
    kps[..., :2] += rng.normal(0, 1.0, size=kps[..., :2].shape)
    return kps.astype(np.float32), np.full(n, NORMAL, dtype=np.int8)


def lying_sequence(n=105, cx=300.0, feet_y=400.0, height=220.0):
    """Someone lying the whole time (e.g. on a sofa): no fall should be reported."""
    kps = np.stack([skeleton(cx, feet_y, height, angle_deg=90.0) for _ in range(n)])
    return kps.astype(np.float32), np.full(n, NORMAL, dtype=np.int8)


def bbox_of(kps):
    return (float(kps[:, 0].min()), float(kps[:, 1].min()), float(kps[:, 0].max()), float(kps[:, 1].max()))


def persons_from(kps, track_id=1):
    """One Person per frame for a single synthetic track."""
    return [[Person(track_id=track_id, bbox=bbox_of(k), conf=0.9, keypoints=k)] for k in kps]


def make_cache(video_id, group_id, kps, labels, fps=25.0, track_id=1, drop=()):
    """A prepare_data-style cache for one synthetic single-person video.
    ``drop``: frame indices with no detection (tracking gaps)."""
    n = len(kps)
    frames = np.array([f for f in range(n) if f not in set(drop)], dtype=np.int32)
    det_bbox = np.array([bbox_of(kps[f]) for f in frames], dtype=np.float32).reshape(-1, 4)
    det_conf = np.full(len(frames), 0.9, dtype=np.float32)
    return {
        "cache_version": CACHE_VERSION, "dataset": "synthetic", "video_id": video_id,
        "group_id": group_id, "source": "", "settings": "{}", "fps": fps, "n_frames": n,
        "frame_labels": np.asarray(labels, dtype=np.int8),
        "det_frame": frames, "det_track": np.full(len(frames), track_id, dtype=np.int32),
        "det_kps": kps[frames].astype(np.float32), "det_bbox": det_bbox, "det_conf": det_conf,
        "subject_det": stitch_subject(frames, det_bbox, det_conf, n).astype(np.int32),
    }


def synthetic_caches(n_fall=8, n_walk=6, n_lying=2, seed=0):
    """A small mixed dataset of caches, one group per video."""
    rng = np.random.default_rng(seed)
    caches = []
    for i in range(n_fall):
        kps, labels = fall_sequence(n_before=int(rng.integers(35, 60)), n_fall=int(rng.integers(10, 20)),
                                    cx=float(rng.uniform(100, 400)), height=float(rng.uniform(150, 280)),
                                    rng=rng)
        caches.append(make_cache(f"syn/fall{i}", f"syn/fall{i}", kps, labels))
    for i in range(n_walk):
        kps, labels = walk_sequence(cx=float(rng.uniform(50, 300)), height=float(rng.uniform(150, 280)), rng=rng)
        caches.append(make_cache(f"syn/walk{i}", f"syn/walk{i}", kps, labels))
    for i in range(n_lying):
        kps, labels = lying_sequence(cx=float(rng.uniform(100, 400)))
        caches.append(make_cache(f"syn/lying{i}", f"syn/lying{i}", kps, labels))
    return caches
