"""Small temporal classifiers over normalized pose windows.

Input: (batch, T, 51) -- 17 keypoints x (x, y, conf) per frame.
Output: (batch, 3) logits over core.features.LABELS for the window's last frame.
"""

from pathlib import Path

import torch
from torch import nn

from core.features import FEATURE_VERSION, LABELS, NUM_FEATURES

CHECKPOINT_FORMAT = 1


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


ARCHS = {"cnn": TemporalCNN, "lstm": TemporalLSTM}


def build_model(arch, **kwargs):
    try:
        cls = ARCHS[arch]
    except KeyError:
        raise ValueError(f"unknown arch {arch!r}; choose from {sorted(ARCHS)}") from None
    return cls(**kwargs)


def save_checkpoint(path, model, arch, model_kwargs, meta):
    """Everything needed to rebuild the model and prepare its input.
    Only tensors and plain Python types, so it loads with weights_only=True."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "format": CHECKPOINT_FORMAT,
        "feature_version": FEATURE_VERSION,
        "labels": list(LABELS),
        "arch": arch,
        "model_kwargs": dict(model_kwargs),
        "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        **meta,
    }, path)


def load_checkpoint(path, device="cpu"):
    """Returns (model in eval mode on ``device``, checkpoint dict without weights)."""
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
