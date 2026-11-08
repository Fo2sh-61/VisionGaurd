"""Learned temporal fall detector (1D-CNN or LSTM trained by train/train.py).

Per track: a rolling buffer of the last ``window`` poses (same gap handling as
training), one batched forward pass per frame for every track whose buffer is
full, an exponential moving average over the class probabilities as light
temporal smoothing, then the shared EventEmitter -- the same alert logic as
the rule-based detector.
"""

import os
from pathlib import Path

import numpy as np

from core.features import FALLEN, FALLING, LABELS, UNKNOWN, TrackBuffer, normalize_windows, to_model_input

from .base import FallDetector
from .events import EmitterConfig
from .registry import register_detector

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = PROJECT_ROOT / "checkpoints" / "temporal_model.pt"
DEFAULT_MIN_VISIBLE_KPS = 6


def default_checkpoint():
    """$FALLDET_CHECKPOINT, else checkpoints/temporal_model.pt, else the newest
    runs/*/best.pt, else None."""
    env = os.environ.get("FALLDET_CHECKPOINT")
    if env:
        return Path(env)
    if DEFAULT_CHECKPOINT.is_file():
        return DEFAULT_CHECKPOINT
    runs = sorted((PROJECT_ROOT / "runs").glob("*/best.pt"), key=lambda p: p.stat().st_mtime)
    return runs[-1] if runs else None


@register_detector
class TemporalModelDetector(FallDetector):
    name = "temporal_model"
    display_name = "Learned temporal model (1D-CNN / LSTM)"

    def __init__(self, checkpoint=None, device=None, smoothing=0.5, emitter_config=None, link_s=1.0,
                 fallen_threshold="auto", min_visible_kps="auto"):
        """smoothing: EMA weight of the previous probabilities (0 = none).
        fallen_threshold: smoothed P(fallen) needed to call a track FALLEN (below it, a
            "fallen" argmax counts as FALLING). "auto" uses the value calibrated on the
            validation videos and stored in the checkpoint; None means plain argmax.
        min_visible_kps: on frames where fewer keypoints are visible (person mostly hidden
            or cut off by the frame edge) the track keeps its previous prediction instead of
            getting a new one. "auto" uses the calibrated value from the checkpoint
            (default 6); 0 disables the gate.
        emitter_config: alert rules; default = the calibrated ones stored in the checkpoint."""
        import torch

        from train.model import load_checkpoint

        path = Path(checkpoint) if checkpoint else default_checkpoint()
        if path is None or not path.is_file():
            raise FileNotFoundError(
                f"no temporal model checkpoint ({path or DEFAULT_CHECKPOINT}); "
                "train one with `python -m train.train` or pass checkpoint=...")
        if not 0.0 <= smoothing < 1.0:
            raise ValueError("smoothing must be in [0, 1)")
        self.checkpoint = path
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model, self.meta = load_checkpoint(path, self.device)
        if emitter_config is None and self.meta.get("emitter"):
            emitter_config = EmitterConfig(**self.meta["emitter"])
        super().__init__(emitter_config, link_s)
        self.window = int(self.meta["window"])
        self.max_gap = int(self.meta["max_gap"])
        m = self.meta.get("min_frames")
        self.min_frames = self.window if m is None else int(m)
        self.conf_min = float(self.meta["conf_min"])
        self.smoothing = smoothing
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
        self._states: dict[int, tuple[int, float]] = {}   # last (state, confidence) per track
        self._torch = torch
        self._buffers: dict[int, TrackBuffer] = {}
        self._probs: dict[int, np.ndarray] = {}

    @classmethod
    def unavailable_reason(cls):
        path = default_checkpoint()
        if path is None or not path.is_file():
            return "no trained checkpoint found (train one with python -m train.train)"
        return None

    def reset(self, fps=30.0):
        super().reset(fps)
        self._buffers.clear()
        self._probs.clear()
        self._states.clear()

    def predict_proba(self, raw_windows):
        """Class probabilities for raw pixel windows (N, window, 17, 3)."""
        x = to_model_input(normalize_windows(raw_windows, self.conf_min))
        with self._torch.no_grad():
            logits = self.model(self._torch.from_numpy(x).to(self.device))
            return self._torch.softmax(logits.float(), dim=1).cpu().numpy()

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
