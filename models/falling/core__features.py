"""Windowing and normalization shared by training (train/) and inference (detectors/).

Both sides import from here so the model always sees identically prepared input:

* ``densify`` (offline) and ``TrackBuffer`` (online) bridge short tracking gaps
  the same way -- hold the last pose for up to ``max_gap`` missing frames, start
  over after a longer gap.
* ``normalize_windows`` centers a whole window on ONE hip point (the mean hip
  center over the window) and divides by ONE body scale (median torso length).
  Centering each frame on its own hips would erase the downward motion of the
  body, which is the main fall cue.
"""

import warnings
from collections import deque

import numpy as np

from .keypoints import (
    FLIP_PERM, KP_CONF_MIN, KP_L_HIP, KP_L_SHOULDER, KP_R_HIP, KP_R_SHOULDER, NUM_KEYPOINTS,
)

LABELS = ("normal", "falling", "fallen")
NORMAL, FALLING, FALLEN = 0, 1, 2
UNKNOWN = -1

WINDOW = 30
MAX_GAP = 5             # missing frames bridged by holding the last pose
NUM_FEATURES = NUM_KEYPOINTS * 3
FEATURE_VERSION = 1     # bump when the normalization changes; checkpoints record it

# Body scale guards, as fractions of the keypoint extent (max of width/height of
# the visible keypoints). A standing person's torso is ~0.3 of their extent. When
# the torso is foreshortened (falling toward the camera) its length collapses, so
# the scale is never allowed below MIN_TORSO_FRACTION * extent.
MIN_TORSO_FRACTION = 0.25
FALLBACK_TORSO_FRACTION = 0.30


def _midpoints(xy, vis, a, b):
    """Midpoint of keypoints a and b, falling back to whichever one is visible;
    NaN where neither is."""
    pa, pb = xy[..., a, :], xy[..., b, :]
    va, vb = vis[..., a, None], vis[..., b, None]
    return np.where(va & vb, (pa + pb) / 2,
                    np.where(va, pa, np.where(vb, pb, np.nan)))


def normalize_windows(windows, conf_min=KP_CONF_MIN):
    """Normalize pose windows to hip center and body scale.

    windows: (N, T, 17, 3) or (T, 17, 3) array of pixel (x, y, conf).
    Returns float32 of the same shape: x/y relative to the window's mean hip
    center in torso lengths, conf kept. Keypoints below ``conf_min`` become
    (0, 0, 0) so the model can tell them apart from real detections.
    """
    w = np.asarray(windows, dtype=np.float64)
    single = w.ndim == 3
    if single:
        w = w[None]
    if w.shape[0] == 0:
        return w.astype(np.float32)

    xy, conf = w[..., :2], w[..., 2]
    vis = np.isfinite(conf) & (conf >= conf_min) & np.isfinite(xy).all(axis=-1)
    n = w.shape[0]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN slices are handled below
        hips = _midpoints(xy, vis, KP_L_HIP, KP_R_HIP)                 # (N, T, 2)
        shoulders = _midpoints(xy, vis, KP_L_SHOULDER, KP_R_SHOULDER)  # (N, T, 2)

        # Reference point: mean hip center over the window, else the mean of
        # every visible keypoint, else the origin (nothing visible at all).
        ref = np.nanmean(hips, axis=1)                                 # (N, 2)
        vis_xy = np.where(vis[..., None], xy, np.nan)
        kp_mean = np.nanmean(vis_xy.reshape(n, -1, 2), axis=1)
        ref = np.where(np.isfinite(ref), ref, kp_mean)
        ref = np.where(np.isfinite(ref), ref, 0.0)

        torso = np.nanmedian(np.linalg.norm(shoulders - hips, axis=-1), axis=1)   # (N,)
        extent = np.nanmax(vis_xy, axis=2) - np.nanmin(vis_xy, axis=2)            # (N, T, 2)
        extent = np.where(vis.sum(axis=-1) >= 2, extent.max(axis=-1), np.nan)    # (N, T)
        extent = np.nanmedian(extent, axis=1)                                     # (N,)

    scale = np.where(np.isfinite(torso),
                     np.where(np.isfinite(extent), np.maximum(torso, extent * MIN_TORSO_FRACTION), torso),
                     extent * FALLBACK_TORSO_FRACTION)
    scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, 1.0)

    out_xy = (xy - ref[:, None, None, :]) / scale[:, None, None, None]
    out_xy = np.where(vis[..., None], out_xy, 0.0)
    out_c = np.where(vis, conf, 0.0)
    out = np.concatenate([out_xy, out_c[..., None]], axis=-1).astype(np.float32)
    return out[0] if single else out


def normalize_window(window, conf_min=KP_CONF_MIN):
    """Single-window convenience wrapper around ``normalize_windows``."""
    return normalize_windows(np.asarray(window)[None], conf_min)[0]


def to_model_input(norm_windows):
    """(N, T, 17, 3) normalized windows -> (N, T, 51) float32 model input."""
    norm_windows = np.asarray(norm_windows, dtype=np.float32)
    return norm_windows.reshape(*norm_windows.shape[:-2], NUM_FEATURES)


def flip_windows(norm_windows):
    """Mirror normalized windows left <-> right (x -> -x, swap L/R keypoints)."""
    out = np.array(norm_windows, dtype=np.float32, copy=True)[..., FLIP_PERM, :]
    out[..., 0] = -out[..., 0]
    out[..., 0][out[..., 2] == 0] = 0.0   # keep missing keypoints exactly (0, 0, 0)
    return out


def densify(frames, kps, max_gap=MAX_GAP):
    """Turn one track's sparse observations into gap-free segments.

    Gaps of up to ``max_gap`` missing frames are filled by holding the last
    pose; longer gaps split the track. Duplicate frame indices keep the first
    observation. Returns a list of (dense_frames (T,), dense_kps (T, 17, 3)).
    Mirrors ``TrackBuffer.push`` exactly.
    """
    frames = np.asarray(frames, dtype=np.int64)
    kps = np.asarray(kps)
    if frames.size == 0:
        return []
    frames, first = np.unique(frames, return_index=True)   # sorted, first of duplicates
    kps = kps[first]
    breaks = np.where(np.diff(frames) - 1 > max_gap)[0]
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks + 1, len(frames)]
    segments = []
    for s, e in zip(starts, ends):
        f = frames[s:e]
        dense = np.arange(f[0], f[-1] + 1)
        src = np.searchsorted(f, dense, side="right") - 1   # last observation at or before each frame
        segments.append((dense, kps[s:e][src]))
    return segments


def label_lookup(frame_labels, frames):
    """Per-frame labels for ``frames``; UNKNOWN outside the annotated range."""
    frame_labels = np.asarray(frame_labels)
    frames = np.asarray(frames, dtype=np.int64)
    out = np.full(frames.shape, UNKNOWN, dtype=np.int64)
    ok = (frames >= 0) & (frames < len(frame_labels))
    out[ok] = frame_labels[frames[ok]]
    return out


def make_windows(kps, labels, window=WINDOW, stride=1, min_frames=None):
    """Sliding windows over one gap-free sequence.

    kps: (T, 17, 3), labels: (T,). Each window is labelled by its LAST frame,
    which is what the online detector predicts (the current state given the
    past ``window`` frames). Windows whose last frame is UNKNOWN are dropped.

    Warm-up: with ``min_frames < window``, windows also end at positions
    ``min_frames - 1 .. window - 2``; they are left-padded by repeating the
    sequence's first pose, exactly like ``TrackBuffer.window_array``.
    Returns raw windows (N, window, 17, 3), labels (N,), end positions (N,).
    """
    kps = np.asarray(kps)
    labels = np.asarray(labels, dtype=np.int64)
    min_frames = window if min_frames is None else min(max(int(min_frames), 1), window)
    if len(kps) < min_frames:
        return (np.zeros((0, window) + kps.shape[1:], dtype=kps.dtype),
                np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64))
    ends = np.arange(min_frames - 1, len(kps), stride)
    ends = ends[labels[ends] != UNKNOWN]
    idx = np.maximum(ends[:, None] + np.arange(-window + 1, 1)[None, :], 0)
    return kps[idx], labels[ends], ends


def sequence_windows(frames, kps, frame_labels, window=WINDOW, stride=1,
                     max_gap=MAX_GAP, conf_min=KP_CONF_MIN, min_frames=None):
    """Normalized, labelled windows for one track.

    frames: (T,) frame indices the track was observed at, kps: (T, 17, 3),
    frame_labels: per-video-frame labels indexed by frame number.
    Returns (X (N, window, 17, 3) float32 normalized, y (N,), end_frames (N,)).
    """
    xs, ys, end_frames = [], [], []
    for dense_frames, dense_kps in densify(frames, kps, max_gap):
        labels = label_lookup(frame_labels, dense_frames)
        x, y, ends = make_windows(dense_kps, labels, window, stride, min_frames)
        if len(y):
            xs.append(x)
            ys.append(y)
            end_frames.append(dense_frames[ends])
    if not xs:
        return (np.zeros((0, window, NUM_KEYPOINTS, 3), dtype=np.float32),
                np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64))
    return (normalize_windows(np.concatenate(xs), conf_min),
            np.concatenate(ys), np.concatenate(end_frames))


class TrackBuffer:
    """Rolling per-track keypoint buffer for online inference.

    Gap handling matches ``densify``: up to ``max_gap`` missing frames are
    filled by repeating the last pose, a longer gap clears the buffer. It is
    ``ready`` after ``min_frames`` poses; until it holds ``window`` of them,
    ``window_array`` left-pads with the oldest pose (as ``make_windows`` does).
    """

    def __init__(self, window=WINDOW, max_gap=MAX_GAP, min_frames=None):
        self.window = window
        self.max_gap = max_gap
        self.min_frames = window if min_frames is None else min(max(int(min_frames), 1), window)
        self._kps = deque(maxlen=window)
        self.last_frame = None

    def push(self, frame_idx, kps):
        """Add one observation. Returns True if a long gap reset the buffer."""
        kps = np.asarray(kps, dtype=np.float32)
        was_reset = False
        if self.last_frame is not None:
            missing = frame_idx - self.last_frame - 1
            if missing < 0:
                return False   # duplicate / out-of-order frame: keep the first
            if missing > self.max_gap:
                self._kps.clear()
                was_reset = True
            else:
                for _ in range(min(missing, self.window)):
                    self._kps.append(self._kps[-1])
        self._kps.append(kps)
        self.last_frame = frame_idx
        return was_reset

    @property
    def ready(self):
        return len(self._kps) >= self.min_frames

    def __len__(self):
        return len(self._kps)

    def window_array(self):
        """(window, 17, 3) raw pixel keypoints, oldest first (left-padded during warm-up)."""
        kps = list(self._kps)
        return np.stack([kps[0]] * (self.window - len(kps)) + kps)

    def reset(self):
        self._kps.clear()
        self.last_frame = None
