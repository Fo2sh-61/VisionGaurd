"""Fall detection — the owner's learned temporal model, over body pose.

Two models, run in this order on every analysed frame of a camera:

    pose model (yolov8s-pose, ultralytics)    ->  17 keypoints per person
    ByteTrack, one tracker per camera         ->  the same person across frames
    temporal model (LSTM, 70 k parameters)    ->  normal / falling / fallen,
                                                  from the last 30 poses of
                                                  each person
    the model's own alert rules               ->  "this person just fell"

**Only the pose model and ByteTrack belong to the engine.** Everything from
the 30-pose window onwards is the owner's code, from `models/falling/`
(`core/features.py`, `core/keypoints.py`, `core/boxes.py`,
`detectors/events.py`, `detectors/base.py`, `detectors/temporal_model.py`,
`train/model.py`), copied here line for line and only renamed where a name
would have collided with the engine's. `test_falls_model.py` runs both copies
side by side on the same skeletons and requires the same answer to the bit,
so a later edit to either one that changes behaviour cannot pass quietly.

**Which model.** `models/falling/checkpoints__temporal_model.pt`, the one the
owner's `train.compare --install` picked and installed: the LSTM trained with
CCTV viewpoint augmentation (`runs/lstm_cctv`), byte-identical to
`runs__lstm_cctv__best.pt`. Its alert rules are calibrated on the validation
videos and stored inside the checkpoint — fallen threshold 0.8, the long-fall
rule at 1 s, the lost-while-falling rule at 0.5 s — and they are used as
stored, never retuned here. The rule-based detector in the same folder is not
used.

**What it has been measured on, and what it has not.** Held-out test split of
Le2i and UR Fall, 30 videos, 19 falls: event F1 0.85, precision 0.81, recall
0.89, four false alarms; one false alarm on 1.4 minutes of fall-free CCTV
footage. Those are home and office rooms filmed at 25-30 frames a second.
**Nothing has been measured on a school camera.** That is the same position
the knife model was in, and the reason every fall here is something a person
can mark as not a fall.

**The frame rate the model needs, and the one it gets.** The model was trained
on 25-30 frames a second: a window of 30 poses is one second of movement. The
engine analyses a camera at its configured rate — usually 5 a second — so the
poses in between are filled in here by straight-line interpolation between
two real observations of the same tracked person, and the model is stepped
through every one of them on a 30-a-second timeline built from
`frame.captured_at`. Its alert rules count frames, so a timeline is the only
way their seconds stay seconds. Holding the last pose instead (what the
owner's code does for a short tracking gap) would show the model a person who
freezes and then teleports five times a second, which it never saw in
training. How well the model does on interpolated poses is **unmeasured**; the
floor that config.py enforces (`MIN_ANALYTICS_HZ["falls"]`) keeps the gaps
short enough that a fall still has several real poses in it.

There is no threading in the worker. The pose model and the temporal model are
each shared by every camera and each carries its own lock, here — a caller
cannot forget it.

Every box leaves here as a fraction of the frame, per the geometry rule:
pixels never cross the API.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import warnings
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import numpy as np

log = logging.getLogger(__name__)

# Nothing here should ever install anything mid-run.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_POSE_WEIGHTS = REPO_DIR / "models" / "yolov8s-pose.pt"
DEFAULT_CLASSIFIER = REPO_DIR / "models" / "falling" / "checkpoints__temporal_model.pt"

#: The rate the temporal model was trained at, and so the rate of the timeline
#: the engine's frames are placed on. Le2i is 25 frames a second and UR Fall
#: 30; the owner's README gives the range. 30 makes the 30-pose window exactly
#: one second.
MODEL_FPS = 30.0

#: The longest gap between two real observations that is filled in. Longer
#: than this and the poses in between are a guess about half a second of
#: somebody's movement, so nothing is invented: the owner's `TrackBuffer`
#: then starts that person's window again, as it does after any long gap.
MAX_INTERPOLATE_SECONDS = 0.5

#: The pose model's settings in the owner's pipeline (`core/pose.py`):
#: confidence 0.30, 640 px. The window the temporal model was trained on was
#: made with these, so they are the defaults here too.
POSE_CONF = 0.30
POSE_IMGSZ = 640

#: How long ByteTrack keeps a lost person's id. The owner's pipeline used
#: ultralytics' stock `bytetrack.yaml`: 30 frames at 30 a second, one second.
#: The engine's own tracker keeps six (`infer/tracking.py`), which is right for
#: following somebody down a corridor and wrong here, where the owner's
#: `TrackLinker` already re-joins a person whose id changed within a second.
TRACK_LOST_SECONDS = 1.0


# ===========================================================================
# The owner's code, from models/falling/. Copied, not rewritten.
# ===========================================================================

# -- core/keypoints.py ------------------------------------------------------

NUM_KEYPOINTS = 17

KP_L_SHOULDER, KP_R_SHOULDER = 5, 6
KP_L_HIP, KP_R_HIP = 11, 12

# Ignore keypoints the pose model isn't confident about.
KP_CONF_MIN = 0.30

# -- core/features.py -------------------------------------------------------

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


def to_model_input(norm_windows):
    """(N, T, 17, 3) normalized windows -> (N, T, 51) float32 model input."""
    norm_windows = np.asarray(norm_windows, dtype=np.float32)
    return norm_windows.reshape(*norm_windows.shape[:-2], NUM_FEATURES)


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


# -- core/boxes.py ----------------------------------------------------------

def box_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def center_distance(a, b):
    """Distance between box centers, in units of ``a``'s longer side."""
    dx = (a[0] + a[2] - b[0] - b[2]) / 2
    dy = (a[1] + a[3] - b[1] - b[3]) / 2
    return (dx * dx + dy * dy) ** 0.5 / max(a[2] - a[0], a[3] - a[1], 1e-6)


# -- core/pose.py: the Person record the detectors are fed ------------------

@dataclass
class Person:
    """One detected person in one frame."""
    track_id: int | None                       # None until ByteTrack confirms the track
    bbox: tuple[float, float, float, float]    # x1, y1, x2, y2 in pixels
    conf: float
    keypoints: np.ndarray                      # (17, 3): x, y, confidence


# -- detectors/events.py ----------------------------------------------------

@dataclass
class EmitterConfig:
    confirm_s: float = 0.2      # FALLEN must persist this long before alerting
    upright_s: float = 0.3      # uninterrupted NORMAL this long counts as "was upright"
    transition_s: float = 2.0   # max time from last upright frame to the fall starting
    rearm_s: float = 1.0        # upright this long re-arms an alerted track
    cooldown_s: float = 5.0     # min time between two alerts on the same track
    stale_s: float = 3.0        # forget tracks unseen this long
    falling_alert_s: float | None = None   # long FALLING/FALLEN run after upright alerts (None = off)
    lost_alert_s: float | None = None      # vanishing this long mid-fall alerts (None = off)
    min_falling_s: float = 0.2             # minimum fall evidence before a lost track can alert

    def to_dict(self):
        return asdict(self)


class _Track:
    __slots__ = ("last_seen", "last_obs", "last_upright", "normal_since", "run_start", "fallen_since",
                 "alerted", "last_alert", "state", "last_state", "confidence", "bbox")

    def __init__(self):
        self.last_seen = None
        self.last_obs = None        # last frame with a known (non-UNKNOWN) state
        self.last_upright = None    # last frame of a NORMAL streak >= upright_s
        self.normal_since = None    # start of the current uninterrupted NORMAL streak
        self.run_start = None       # first non-NORMAL frame since the track was last upright
        self.fallen_since = None    # first FALLEN frame since the track was last upright
        self.alerted = False
        self.last_alert = None
        self.state = UNKNOWN        # state predicted on the last frame seen
        self.last_state = UNKNOWN   # last known (non-UNKNOWN) state
        self.confidence = 0.0
        self.bbox = None


class EventEmitter:
    def __init__(self, config: EmitterConfig | None = None, fps: float = 30.0):
        self.config = config or EmitterConfig()
        self.reset(fps)

    def reset(self, fps: float = 30.0):
        self.fps = fps
        self._tracks: dict[int, _Track] = {}

    def _frames(self, seconds):
        return max(1, round(seconds * self.fps))

    def _fall_started_upright(self, t):
        """The current non-NORMAL run began within transition_s of being upright."""
        return (t.last_upright is not None and t.run_start is not None
                and t.run_start - t.last_upright <= self._frames(self.config.transition_s))

    def _fire(self, track_id, t, frame_idx):
        if t.last_alert is not None and frame_idx - t.last_alert < self._frames(self.config.cooldown_s):
            return None
        t.alerted = True
        t.last_alert = frame_idx
        return FallEvent(track_id=track_id, frame_idx=frame_idx, confidence=t.confidence,
                         bbox=t.bbox, fall_start_frame=t.run_start)

    def observe(self, track_id, frame_idx, state, confidence=0.0, bbox=None):
        """Feed one track's state for one frame; returns a FallEvent or None."""
        t = self._tracks.get(track_id)
        if t is None:
            t = self._tracks[track_id] = _Track()
        t.last_seen = frame_idx
        if bbox is not None:
            t.bbox = tuple(float(v) for v in bbox)
        if state is None or state == UNKNOWN:
            t.state, t.confidence = UNKNOWN, 0.0
            t.normal_since = None
            return None
        contiguous = t.last_obs == frame_idx - 1
        t.last_obs = frame_idx
        t.state = t.last_state = int(state)
        t.confidence = float(confidence)

        if state == NORMAL:
            if t.normal_since is None or not contiguous:
                t.normal_since = frame_idx
            streak = frame_idx - t.normal_since + 1
            if streak >= self._frames(self.config.upright_s):
                t.last_upright = frame_idx
                t.run_start = None
                t.fallen_since = None
            if t.alerted and streak >= self._frames(self.config.rearm_s):
                t.alerted = False
            return None

        t.normal_since = None
        if t.run_start is None:
            t.run_start = frame_idx
        if state == FALLEN and t.fallen_since is None:
            t.fallen_since = frame_idx
        if t.alerted:
            return None

        confirmed_fallen = (
            state == FALLEN
            and frame_idx - t.fallen_since + 1 >= self._frames(self.config.confirm_s)
            and t.last_upright is not None
            and t.fallen_since - t.last_upright <= self._frames(self.config.transition_s))
        long_fall = (
            self.config.falling_alert_s is not None
            and frame_idx - t.run_start + 1 >= self._frames(self.config.falling_alert_s)
            and self._fall_started_upright(t))
        if confirmed_fallen or long_fall:
            return self._fire(track_id, t, frame_idx)
        return None

    def sweep(self, frame_idx):
        """Alerts for tracks that vanished mid-fall (``lost_alert_s``); call once per frame."""
        if self.config.lost_alert_s is None:
            return []
        lost = self._frames(self.config.lost_alert_s)
        min_run = self._frames(self.config.min_falling_s)
        events = []
        for tid, t in self._tracks.items():
            if (not t.alerted and frame_idx - t.last_seen >= lost
                    and t.last_state in (FALLING, FALLEN) and t.last_obs is not None
                    and self._fall_started_upright(t) and t.last_obs - t.run_start + 1 >= min_run):
                event = self._fire(tid, t, frame_idx)
                if event is not None:
                    events.append(event)
        return events

    def prune(self, frame_idx):
        """Drop tracks not seen for ``stale_s``; returns the dropped ids."""
        limit = self._frames(self.config.stale_s)
        stale = [tid for tid, t in self._tracks.items() if frame_idx - t.last_seen > limit]
        for tid in stale:
            del self._tracks[tid]
        return stale

    def status(self, track_id):
        t = self._tracks.get(track_id)
        if t is None:
            return None
        return TrackStatus(track_id=track_id, state=t.state, confidence=t.confidence,
                           alerted=t.alerted, last_seen=t.last_seen, bbox=t.bbox)

    def statuses(self):
        return {tid: self.status(tid) for tid in self._tracks}


# -- detectors/base.py ------------------------------------------------------

@dataclass(frozen=True)
class FallEvent:
    track_id: int                      # stable identity (see TrackLinker)
    frame_idx: int                     # frame the alert was raised on
    confidence: float
    bbox: tuple[float, float, float, float] | None = None
    fall_start_frame: int | None = None   # first non-normal frame of the run that led here


@dataclass
class TrackStatus:
    """Latest per-track state, for drawing overlays and frame-level evaluation."""
    track_id: int
    state: int                         # NORMAL / FALLING / FALLEN / UNKNOWN
    confidence: float
    alerted: bool
    last_seen: int
    bbox: tuple[float, float, float, float] | None = None


class TrackLinker:
    """Maps tracker ids to stable identities across id switches.

    A tracker id seen for the first time is linked to an identity that went
    missing at most ``max_lost_s`` ago if their boxes overlap (IoU >=
    ``min_iou``) or their centers are close (within ``max_center_dist`` of the
    lost box's longer side); otherwise it starts a new identity.
    """

    def __init__(self, max_lost_s=1.0, min_iou=0.1, max_center_dist=0.5):
        self.max_lost_s = max_lost_s
        self.min_iou = min_iou
        self.max_center_dist = max_center_dist
        self.reset()

    def reset(self, fps=30.0):
        self.fps = fps
        self.alias: dict[int, int] = {}                 # tracker id -> stable id
        self._last: dict[int, tuple[int, tuple]] = {}   # stable id -> (frame, bbox)

    def stable_id(self, track_id):
        return self.alias.get(track_id, track_id)

    def link(self, frame_idx, persons):
        if self.max_lost_s <= 0:
            return list(persons)
        max_lost = max(1, round(self.max_lost_s * self.fps))
        out, fresh, present = list(persons), [], set()
        for i, p in enumerate(persons):
            if p.track_id is None:
                continue
            if p.track_id in self.alias:
                present.add(self.alias[p.track_id])
            else:
                fresh.append(i)
        for i in fresh:
            p = persons[i]
            best, best_d = p.track_id, float("inf")
            for sid, (f, box) in self._last.items():
                if sid in present or not 1 <= frame_idx - f <= max_lost:
                    continue
                d = center_distance(box, p.bbox)
                if (box_iou(box, p.bbox) >= self.min_iou or d <= self.max_center_dist) and d < best_d:
                    best, best_d = sid, d
            self.alias[p.track_id] = best
            present.add(best)
        for i, p in enumerate(persons):
            if p.track_id is None:
                continue
            sid = self.alias[p.track_id]
            if sid != p.track_id:
                out[i] = replace(p, track_id=sid)
            self._last[sid] = (frame_idx, tuple(p.bbox))
        for sid in [s for s, (f, _) in self._last.items() if frame_idx - f > max_lost]:
            del self._last[sid]
            for tid in [t for t, s in self.alias.items() if s == sid]:
                del self.alias[tid]
        return out


# -- train/model.py ---------------------------------------------------------

CHECKPOINT_FORMAT = 1


def _architectures():
    """{"cnn": TemporalCNN, "lstm": TemporalLSTM}, defined on first use.

    Inside a function only so that importing this module does not import
    torch: the engine's tests of the alert rules and the window maths run on a
    machine without it. The two classes are the owner's, unchanged.
    """
    global _ARCHS
    if _ARCHS is not None:
        return _ARCHS

    import torch
    from torch import nn

    class TemporalCNN(nn.Module):
        """Residual stack of dilated 1D convolutions; pools the whole window and
        also reads the last time step (the frame being classified)."""

        def __init__(self, in_features=NUM_FEATURES, num_classes=len(LABELS), channels=64,
                     num_layers=3, kernel_size=5, dropout=0.2):
            super().__init__()
            if kernel_size % 2 == 0:
                raise ValueError("kernel_size must be odd")
            self.input = nn.Sequential(nn.Conv1d(in_features, channels, 1),
                                       nn.BatchNorm1d(channels), nn.ReLU())
            self.blocks = nn.ModuleList()
            for i in range(num_layers):
                dilation = 2 ** i
                self.blocks.append(nn.Sequential(
                    nn.Conv1d(channels, channels, kernel_size,
                              padding=dilation * (kernel_size - 1) // 2, dilation=dilation),
                    nn.BatchNorm1d(channels), nn.ReLU(), nn.Dropout(dropout)))
            self.head = nn.Linear(2 * channels, num_classes)

        def forward(self, x):
            h = self.input(x.transpose(1, 2))          # (B, C, T)
            for block in self.blocks:
                h = h + block(h)
            return self.head(torch.cat([h.mean(dim=2), h[:, :, -1]], dim=1))

    class TemporalLSTM(nn.Module):
        """Per-frame projection followed by an LSTM; classifies from the last hidden state."""

        def __init__(self, in_features=NUM_FEATURES, num_classes=len(LABELS), hidden=64,
                     num_layers=2, dropout=0.2):
            super().__init__()
            self.proj = nn.Sequential(nn.Linear(in_features, hidden), nn.ReLU())
            self.lstm = nn.LSTM(hidden, hidden, num_layers=num_layers, batch_first=True,
                                dropout=dropout if num_layers > 1 else 0.0)
            self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, num_classes))

        def forward(self, x):
            # cuDNN's RNN kernels make this PyTorch build crash at interpreter exit on
            # Windows (exit code 127); the native kernel is plenty fast for a 2x64 LSTM.
            with torch.backends.cudnn.flags(enabled=False):
                out, _ = self.lstm(self.proj(x))
            return self.head(out[:, -1])

    _ARCHS = {"cnn": TemporalCNN, "lstm": TemporalLSTM}
    return _ARCHS


_ARCHS = None


def build_model(arch, **kwargs):
    archs = _architectures()
    try:
        cls = archs[arch]
    except KeyError:
        raise ValueError(f"unknown arch {arch!r}; choose from {sorted(archs)}") from None
    return cls(**kwargs)


def load_checkpoint(path, device="cpu"):
    """Returns (model in eval mode on ``device``, checkpoint dict without weights)."""
    import torch

    ckpt = torch.load(Path(path), map_location="cpu", weights_only=True)
    if ckpt.get("feature_version") != FEATURE_VERSION:
        raise ValueError(f"{path}: trained with feature version {ckpt.get('feature_version')}, "
                         f"this code uses {FEATURE_VERSION}; retrain the model")
    if list(ckpt.get("labels", [])) != list(LABELS):
        raise ValueError(f"{path}: labels {ckpt.get('labels')} != {list(LABELS)}")
    model = build_model(ckpt["arch"], **ckpt["model_kwargs"])
    model.load_state_dict(ckpt["state_dict"])
    model.to(device).eval()
    meta = {k: v for k, v in ckpt.items() if k != "state_dict"}
    return model, meta


# -- detectors/temporal_model.py, split in two ------------------------------
#
# The owner's `TemporalModelDetector` holds the network AND one video's worth
# of per-person state. The engine has many cameras and one network, so the
# network (`TemporalClassifier`) is loaded once and shared, and the state
# (`FallTracker`) is one per camera. The arithmetic in between is unchanged.

DEFAULT_MIN_VISIBLE_KPS = 6


class TemporalClassifier:
    """The trained network and the settings stored beside it. One per engine."""

    def __init__(self, checkpoint: Path | str | None = None, device: str = "auto",
                 fallen_threshold="auto", min_visible_kps="auto") -> None:
        import torch

        path = Path(checkpoint or DEFAULT_CLASSIFIER)
        if not path.is_file():
            raise FileNotFoundError(f"fall model not found: {path}")
        self.checkpoint = path
        self.device = _resolve_device(device)
        self.model, self.meta = load_checkpoint(path, self.device)
        self.window = int(self.meta["window"])
        self.max_gap = int(self.meta["max_gap"])
        m = self.meta.get("min_frames")
        self.min_frames = self.window if m is None else int(m)
        self.conf_min = float(self.meta["conf_min"])
        if fallen_threshold == "auto":
            fallen_threshold = self.meta.get("fallen_threshold")
        if fallen_threshold is not None and (isinstance(fallen_threshold, (bool, str))
                                             or not 0 < float(fallen_threshold) <= 1):
            raise ValueError(f"fallen_threshold must be 'auto', None or in (0, 1], got {fallen_threshold!r}")
        self.fallen_threshold = None if fallen_threshold is None else float(fallen_threshold)
        if min_visible_kps == "auto":
            min_visible_kps = self.meta.get("min_visible_kps", DEFAULT_MIN_VISIBLE_KPS)
        if isinstance(min_visible_kps, (bool, str)) or not 0 <= int(min_visible_kps) <= 17:
            raise ValueError(f"min_visible_kps must be 'auto' or 0..17, got {min_visible_kps!r}")
        self.min_visible_kps = int(min_visible_kps)
        self.emitter_config = (EmitterConfig(**self.meta["emitter"])
                               if self.meta.get("emitter") else EmitterConfig())
        self.arch = str(self.meta.get("arch", ""))
        # What System Health and every entry print as the model that decided.
        out = str((self.meta.get("config") or {}).get("out", "")).replace("\\", "/")
        self.version = out.rsplit("/", 1)[-1] or path.stem
        self._torch = torch
        # One network, every camera thread. Held around the forward pass only.
        self._lock = threading.Lock()
        self.last_ms = 0.0

    def predict_proba(self, raw_windows):
        """Class probabilities for raw pixel windows (N, window, 17, 3)."""
        x = to_model_input(normalize_windows(raw_windows, self.conf_min))
        started = time.perf_counter()
        with self._lock, self._torch.no_grad():
            logits = self.model(self._torch.from_numpy(x).to(self.device))
            probs = self._torch.softmax(logits.float(), dim=1).cpu().numpy()
        self.last_ms = (time.perf_counter() - started) * 1000
        return probs


class FallTracker:
    """One camera's people, as the owner's `TemporalModelDetector` tracks them.

    `update` is the owner's `FallDetector.update` and `_update` is the owner's
    `TemporalModelDetector._update`, with the network call going to the shared
    `TemporalClassifier`. Feed it every frame of the 30-a-second timeline, in
    order; it returns the falls it decided to raise on that frame.
    """

    def __init__(self, classifier: TemporalClassifier, smoothing: float = 0.5,
                 link_s: float = 1.0, fps: float = MODEL_FPS) -> None:
        if not 0.0 <= smoothing < 1.0:
            raise ValueError("smoothing must be in [0, 1)")
        self.classifier = classifier
        self.emitter = EventEmitter(classifier.emitter_config)
        self.linker = TrackLinker(max_lost_s=link_s)
        self.smoothing = smoothing
        self.window = classifier.window
        self.max_gap = classifier.max_gap
        self.min_frames = classifier.min_frames
        self.conf_min = classifier.conf_min
        self.fallen_threshold = classifier.fallen_threshold
        self.min_visible_kps = classifier.min_visible_kps
        self._states: dict[int, tuple[int, float]] = {}   # last (state, confidence) per track
        self._buffers: dict[int, TrackBuffer] = {}
        self._probs: dict[int, np.ndarray] = {}
        self.reset(fps)

    # -- detectors/base.py FallDetector ----------------------------------

    def reset(self, fps: float = MODEL_FPS) -> None:
        """Forget all tracks; call at the start of every video or stream."""
        self.fps = fps
        self.emitter.reset(fps)
        self.linker.reset(fps)
        self._buffers.clear()
        self._probs.clear()
        self._states.clear()

    def update(self, frame_idx: int, persons: Sequence[Person]) -> list[FallEvent]:
        """Process one frame's detections and return newly raised fall events."""
        events = self._update(frame_idx, self.linker.link(frame_idx, persons))
        return events + self.emitter.sweep(frame_idx)   # people who vanished mid-fall

    def statuses(self) -> dict[int, TrackStatus]:
        """Stable identity -> status."""
        return self.emitter.statuses()

    def status_for(self, track_id: int | None) -> TrackStatus | None:
        """Status of the person the tracker currently calls ``track_id``."""
        if track_id is None:
            return None
        return self.emitter.status(self.linker.stable_id(track_id))

    # -- detectors/temporal_model.py TemporalModelDetector ---------------

    def predict_proba(self, raw_windows):
        return self.classifier.predict_proba(raw_windows)

    def _update(self, frame_idx, persons):
        ready, bboxes, events = [], {}, []
        for p in persons:
            tid = p.track_id
            if tid is None:
                continue
            buf = self._buffers.get(tid)
            if buf is None:
                buf = self._buffers[tid] = TrackBuffer(self.window, self.max_gap, self.min_frames)
            if buf.push(frame_idx, p.keypoints):
                self._probs.pop(tid, None)   # long gap: smoothing restarts with the buffer
                self._states.pop(tid, None)
            bboxes[tid] = p.bbox
            visible = int((np.asarray(p.keypoints)[:, 2] >= self.conf_min).sum())
            if buf.ready and visible >= self.min_visible_kps:
                ready.append(tid)
            elif buf.ready and tid in self._states:
                # Too little of the person is visible to judge: keep the last prediction
                # (no new FALLEN from a few keypoints, no broken upright/fallen streaks).
                state, conf = self._states[tid]
                event = self.emitter.observe(tid, frame_idx, state, conf, p.bbox)
                if event is not None:
                    events.append(event)
            else:
                self.emitter.observe(tid, frame_idx, UNKNOWN, 0.0, p.bbox)

        if ready:
            probs = self.predict_proba(np.stack([self._buffers[t].window_array() for t in ready]))
            for tid, pr in zip(ready, probs):
                prev = self._probs.get(tid)
                smoothed = pr if prev is None else self.smoothing * prev + (1 - self.smoothing) * pr
                self._probs[tid] = smoothed
                state = int(np.argmax(smoothed))
                if (state == FALLEN and self.fallen_threshold is not None
                        and smoothed[FALLEN] < self.fallen_threshold):
                    state = FALLING   # leaning towards fallen, but not confident enough
                self._states[tid] = (state, float(smoothed[state]))
                event = self.emitter.observe(tid, frame_idx, state, float(smoothed[state]), bboxes[tid])
                if event is not None:
                    events.append(event)

        for tid in self.emitter.prune(frame_idx):
            self._buffers.pop(tid, None)
            self._probs.pop(tid, None)
            self._states.pop(tid, None)
        return events

    def probabilities(self):
        """track id -> smoothed class probabilities (for overlays/debugging)."""
        return {tid: dict(zip(LABELS, map(float, p))) for tid, p in self._probs.items()}


# ===========================================================================
# The engine's half: frames in, falls out.
# ===========================================================================

#: The state names that leave this file. The engine sends enums; the console
#: builds the sentences.
STATE_NAMES = {NORMAL: "normal", FALLING: "falling", FALLEN: "fallen", UNKNOWN: "unknown"}


@dataclass(frozen=True)
class FallingPerson:
    """One tracked person on one camera, as the fall model last judged them.

    `person_id` numbers a body on this camera for as long as it stays in view.
    It is never a name, never stored, and never compared with any other
    feature's numbers — recognition is not consulted, by design (rule 2).
    """

    person_id: int
    x: float
    y: float
    w: float
    h: float
    state: str               # STATE_NAMES
    confidence: float
    seen_at: datetime        # the last frame this person was actually in


@dataclass(frozen=True)
class FallAlert:
    """The model decided that a person fell."""

    person_id: int
    at: datetime                     # when the model decided
    fell_at: datetime                # first non-normal frame of the run (or `at`)
    confidence: float
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class FallReading:
    """What the fall model made of one real frame."""

    people: tuple[FallingPerson, ...] = ()
    alerts: tuple[FallAlert, ...] = ()
    #: Every identity the model is still following on this camera, including
    #: people not in this frame — lying on the floor is where pose models lose
    #: people most. Keyed by `person_id`.
    known: dict | None = None


class FallTimeline:
    """One camera's people on the model's 30-a-second timeline.

    Takes the people in each REAL frame, keyed by their ByteTrack id, fills in
    the frames between two real ones, and steps the owner's `FallTracker`
    through every one of them in order. Needs no pose model and no camera, so
    a test can drive the real network with skeletons and a clock of its own.
    """

    def __init__(self, classifier: TemporalClassifier) -> None:
        self.tracker = FallTracker(classifier)
        self.origin: datetime | None = None
        self.last_index: int | None = None
        # ByteTrack id -> Person at `last_index`, for filling in the gap
        # before the next real frame.
        self.last_people: dict[int, Person] = {}
        self.width = 1
        self.height = 1

    def step(self, captured_at: datetime, people: dict[int, Person],
             width: int | None = None, height: int | None = None) -> FallReading:
        """Place one real frame's people on the timeline and run the model."""
        if width and height:
            self.width, self.height = max(1, int(width)), max(1, int(height))
        if self.origin is None:
            self.origin = captured_at
        index = int(round((captured_at - self.origin).total_seconds() * MODEL_FPS))

        if self.last_index is not None and index < self.last_index:
            # The clock went backwards — a clip looped, the machine's time was
            # corrected. Nothing remembered is about the same timeline any
            # more, so start again rather than feed the model a frame from
            # before its own last one.
            self.tracker.reset(MODEL_FPS)
            self.origin, self.last_index, self.last_people = captured_at, None, {}
            index = 0
        if self.last_index is not None and index == self.last_index:
            # Two real frames inside one thirtieth of a second: the timeline
            # already has this frame, and the owner's buffer would drop the
            # second one as a duplicate anyway.
            return self._reading(people, ())

        events: list[FallEvent] = []
        if self.last_index is not None:
            missing = index - self.last_index - 1
            if 0 < missing <= MAX_INTERPOLATE_SECONDS * MODEL_FPS:
                for step in range(1, missing + 1):
                    alpha = step / (missing + 1)
                    between = [
                        _between(self.last_people[tid], person, alpha)
                        for tid, person in people.items() if tid in self.last_people
                    ]
                    events.extend(self.tracker.update(self.last_index + step, between))

        events.extend(self.tracker.update(index, list(people.values())))
        self.last_index = index
        self.last_people = dict(people)
        return self._reading(people, events)

    def _reading(self, people: dict[int, Person], events) -> FallReading:
        known = {}
        for sid, status in self.tracker.statuses().items():
            if status.bbox is None:
                continue
            known[sid] = FallingPerson(
                person_id=sid,
                **_fractions(status.bbox, self.width, self.height),
                state=STATE_NAMES.get(status.state, "unknown"),
                confidence=_unit(status.confidence),
                seen_at=self.time_of(status.last_seen),
            )
        here = []
        for tid in people:
            sid = self.tracker.linker.stable_id(tid)
            if sid in known:
                here.append(known[sid])
        alerts = tuple(
            FallAlert(
                person_id=e.track_id,
                at=self.time_of(e.frame_idx),
                fell_at=self.time_of(e.fall_start_frame
                                     if e.fall_start_frame is not None else e.frame_idx),
                confidence=_unit(e.confidence),
                **_fractions(e.bbox or (0.0, 0.0, 0.0, 0.0), self.width, self.height),
            )
            for e in events
        )
        return FallReading(people=tuple(here), alerts=alerts, known=known)

    def time_of(self, index: int) -> datetime:
        return self.origin + timedelta(seconds=index / MODEL_FPS)


class FallDetector:
    """Pose, tracking and the temporal model, for every camera.

    One instance per engine. The pose model and the network are each loaded
    once; everything that remembers a person is kept per camera, because
    feeding one camera's people into another's tracker is how boxes from one
    room end up on another.
    """

    def __init__(
        self,
        weights: Path | str | None = None,
        classifier: Path | str | None = None,
        device: str = "auto",
        imgsz: int = POSE_IMGSZ,
        conf: float = POSE_CONF,
        half: bool = True,
        accelerate: bool = True,
        warm_up: bool = True,
    ) -> None:
        self.weights = Path(weights or DEFAULT_POSE_WEIGHTS)
        if not self.weights.is_file():
            raise FileNotFoundError(f"pose weights not found: {self.weights}")
        self.imgsz = imgsz
        self.conf = conf
        self.device = _resolve_device(device)
        self.half = half and self.device != "cpu"

        # The network first: it is small and its failure says more (a wrong
        # feature version, a corrupt file) than the pose model's would.
        self.classifier = TemporalClassifier(classifier, self.device)

        from vg.infer.shared import load_model

        self.model, self.loaded, self.form = load_model(
            self.weights, imgsz, task="pose", accelerate=accelerate)
        self.version = self.classifier.version
        self.pose_version = self.weights.stem

        # One pose model, every camera thread. ultralytics is not re-entrant
        # on one model instance.
        self._lock = threading.Lock()
        # camera id -> (its timeline, its ByteTrack)
        self._cameras: dict[str, tuple] = {}
        self._cameras_lock = threading.Lock()
        self.last_pose_ms = 0.0

        if self.device == "cpu":
            log.warning(
                "fall detection is running on the CPU. "
                "Install a CUDA build of torch for the pose model to keep up.")
        if warm_up:
            self._warm_up()

    def _warm_up(self) -> None:
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        started = time.perf_counter()
        self.poses(blank)
        self.classifier.predict_proba(np.zeros((1, self.classifier.window, NUM_KEYPOINTS, 3),
                                               dtype=np.float32))
        log.info(
            "fall detector ready on %s (pose %s, %s; temporal model %s; warm-up %.0f ms)",
            self.device, self.loaded.name, self.form, self.version,
            (time.perf_counter() - started) * 1000,
        )

    # -- the pose model ---------------------------------------------------

    def poses(self, image: np.ndarray):
        """(ultralytics Boxes, keypoints (N, 17, 3) in pixels) for one frame."""
        started = time.perf_counter()
        with self._lock:
            results = self.model.predict(
                image,
                device=self.device,
                imgsz=self.imgsz,
                conf=self.conf,
                classes=[0],
                quantize=16 if self.half else 32,
                verbose=False,
            )
        self.last_pose_ms = (time.perf_counter() - started) * 1000
        if not results:
            return None, np.zeros((0, NUM_KEYPOINTS, 3), dtype=np.float32)
        result = results[0]
        boxes = result.boxes.cpu() if result.boxes is not None else None
        keypoints = getattr(result, "keypoints", None)
        try:
            kps = (keypoints.data.cpu().numpy().astype(np.float32)
                   if keypoints is not None else None)
        except Exception:  # noqa: BLE001 - a frame without keypoints is not fatal
            kps = None
        n = 0 if boxes is None else len(boxes)
        if kps is None or len(kps) != n:
            kps = np.zeros((n, NUM_KEYPOINTS, 3), dtype=np.float32)
        return boxes, kps

    # -- per camera -------------------------------------------------------

    def _camera(self, camera_id: str, frame_rate: float):
        with self._cameras_lock:
            cam = self._cameras.get(camera_id)
            if cam is None:
                from vg.infer.tracking import PersonTracker

                bytetrack = PersonTracker(
                    frame_rate,
                    track_buffer=max(1, int(round(frame_rate * TRACK_LOST_SECONDS))))
                cam = self._cameras[camera_id] = (FallTimeline(self.classifier), bytetrack)
            return cam

    def forget(self, camera_id: str) -> None:
        """Drop everything kept about one camera's people."""
        with self._cameras_lock:
            self._cameras.pop(camera_id, None)

    def observe(self, camera_id: str, image: np.ndarray, captured_at: datetime,
                frame_rate: float = 5.0) -> FallReading:
        """Run one real frame through pose, tracking and the fall model."""
        timeline, bytetrack = self._camera(camera_id, frame_rate)
        boxes, kps = self.poses(image)
        height, width = image.shape[:2]

        # Called on EVERY frame, empty ones included: that is how a lost
        # track ages out (`infer/tracking.py`). ByteTrack wants an empty set
        # of boxes, not None, or it logs a fault and ages nothing.
        tracks = bytetrack.update(
            boxes if boxes is not None else _no_boxes(height, width), image)
        people: dict[int, Person] = {}
        for track in tracks:
            if not 0 <= track.index < len(kps):
                continue   # ByteTrack did not say which detection this was
            people[track.track_id] = Person(
                track_id=track.track_id,
                bbox=(float(track.x1), float(track.y1), float(track.x2), float(track.y2)),
                conf=track.confidence,
                keypoints=kps[track.index],
            )
        return timeline.step(captured_at, people, width, height)


def _between(a: Person, b: Person, alpha: float) -> Person:
    """The pose `alpha` of the way from `a` to `b`, for a frame never seen.

    Positions move in a straight line. A keypoint's confidence is the lower of
    its two ends, so a joint that was hidden at either end stays below the
    model's visibility threshold in between rather than being invented.
    """
    ka = np.asarray(a.keypoints, dtype=np.float32)
    kb = np.asarray(b.keypoints, dtype=np.float32)
    kps = np.empty_like(kb)
    kps[:, :2] = ka[:, :2] + (kb[:, :2] - ka[:, :2]) * alpha
    kps[:, 2] = np.minimum(ka[:, 2], kb[:, 2])
    bbox = tuple(float(x + (y - x) * alpha) for x, y in zip(a.bbox, b.bbox))
    return Person(track_id=b.track_id, bbox=bbox, conf=min(a.conf, b.conf), keypoints=kps)


def _fractions(bbox, width: int, height: int) -> dict:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    fx = max(0.0, min(1.0, x1 / width))
    fy = max(0.0, min(1.0, y1 / height))
    return {
        "x": fx,
        "y": fy,
        "w": max(0.0, min(1.0 - fx, (x2 - x1) / width)),
        "h": max(0.0, min(1.0 - fy, (y2 - y1) / height)),
    }


def _unit(value: float) -> float:
    """Clamped to 0..1 — a Confidence outside it would 500 the response."""
    return max(0.0, min(1.0, float(value)))


def _no_boxes(height: int, width: int):
    """An empty ultralytics `Boxes`, for a frame the pose model found nobody in."""
    from ultralytics.engine.results import Boxes

    return Boxes(np.zeros((0, 6), dtype=np.float32), (height, width))


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
