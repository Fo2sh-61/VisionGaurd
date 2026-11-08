"""Training helpers: class weighting, metrics, augmentation, config merging."""

import numpy as np
import pytest

from core.features import FLIP_PERM, normalize_window
from tests.synth import walk_sequence
from train.train import (
    DEFAULT_CONFIG, augment, class_weights, classification_report, confusion_matrix, deep_merge,
)


def test_inverse_class_weights():
    w = class_weights([800, 50, 150], "inverse")
    np.testing.assert_allclose(w * [800, 50, 150], (w * [800, 50, 150])[0])   # weight x count is equal
    assert w.mean() == pytest.approx(1.0)
    assert w[1] > w[2] > w[0]


def test_sqrt_none_and_absent_classes():
    sq = class_weights([400, 100, 0], "sqrt_inverse")
    assert sq[2] == 0 and sq[1] / sq[0] == pytest.approx(2.0) and sq[:2].mean() == pytest.approx(1.0)
    np.testing.assert_array_equal(class_weights([5, 0, 5], "none"), [1, 0, 1])
    with pytest.raises(ValueError):
        class_weights([1, 1, 1], "bogus")


def test_confusion_and_macro_f1():
    cm = confusion_matrix([0, 0, 1, 2, 2], [0, 1, 1, 2, 0])
    np.testing.assert_array_equal(cm, [[1, 1, 0], [0, 1, 0], [1, 0, 1]])   # rows = true
    rep = classification_report(cm)
    assert rep["accuracy"] == pytest.approx(3 / 5)
    assert rep["f1"][1] == pytest.approx(2 / 3)
    # A class that never occurs (neither true nor predicted) doesn't drag macro-F1 down.
    assert classification_report(confusion_matrix([0, 1], [0, 1]))["macro_f1"] == 1.0


def test_augment_flip_keeps_missing_keypoints_zero():
    kps, _ = walk_sequence(n=30)
    x = normalize_window(kps)[None]
    x[0, :, 3] = 0
    out = augment(x, np.random.default_rng(0), {"flip_p": 1.0})
    np.testing.assert_allclose(out[0, ..., 0], -x[0][:, FLIP_PERM, 0], atol=1e-6)
    assert (out[0, :, FLIP_PERM[3]] == 0).all()
    jit = augment(x, np.random.default_rng(0), {"jitter_std": 0.5, "kp_dropout": 0.0})
    assert (jit[0, :, 3] == 0).all() and not np.allclose(jit, x)          # jitter only where visible
    assert augment(x, np.random.default_rng(0), None) is not x


def test_viewpoint_augmentation_renormalizes_and_hides_legs():
    kps, _ = walk_sequence(n=30)
    x = normalize_window(kps)[None].repeat(200, 0)
    cfg = {"rotate_deg": 30, "squash": [0.6, 1.0], "shear": 0.2, "occlude_lower_p": 0.5}
    out = augment(x, np.random.default_rng(0), cfg)
    assert np.isfinite(out).all() and out.shape == x.shape
    hidden = (out[:, :, 13:17, 2] == 0).all(axis=(1, 2))
    assert 0.35 < hidden.mean() < 0.65
    assert (out[hidden][:, :, 13:17] == 0).all()                       # fully zeroed, not just conf
    # windows are re-normalized: hip center of the window at the origin again
    hips = (out[..., 11, :2] + out[..., 12, :2]) / 2
    np.testing.assert_allclose(hips.mean(axis=1), 0, atol=1e-4)
    # squash really compresses the body vertically relative to its width
    squashed = augment(x[:1], np.random.default_rng(0), {"squash": [0.5, 0.5]})
    height = lambda w: np.ptp(w[0, 0, :, 1]) / np.ptp(w[0, 0, :, 0])
    assert height(squashed) == pytest.approx(0.5 * height(x[:1]), rel=1e-3)


class FixedRng:
    """rng stand-in: uniform() returns its upper bound, random() returns 0."""

    def uniform(self, lo, hi, size=None):
        return np.full(size, hi, dtype=float)

    def random(self, size=None):
        return np.zeros(size)


@pytest.mark.parametrize("cfg,matrix", [
    ({"rotate_deg": 90}, [[0, -1], [1, 0]]),        # x' = -y, y' = x
    ({"shear": 0.5}, [[1, 0.5], [0, 1]]),            # x' = x + 0.5 y
    ({"squash": [0.5, 0.5]}, [[1, 0], [0, 0.5]]),    # y' = 0.5 y
])
def test_viewpoint_transform_equals_transforming_raw_pixels(cfg, matrix):
    """augment(normalized window) == normalize(transformed raw window): the geometry
    is applied correctly AND the result is re-normalized like the detector would."""
    kps, _ = walk_sequence(n=30)
    raw = kps.copy()
    raw[..., :2] = kps[..., :2] @ np.array(matrix, dtype=np.float32).T
    expected = normalize_window(raw)
    out = augment(normalize_window(kps)[None], FixedRng(), {"flip_p": 0.0, **cfg})[0]
    np.testing.assert_allclose(out, expected, atol=1e-4)
    if "squash" in cfg:   # re-normalized: torso length is 1 torso unit again
        torso = np.linalg.norm((out[:, 5, :2] + out[:, 6, :2]) / 2 - (out[:, 11, :2] + out[:, 12, :2]) / 2, axis=-1)
        assert np.median(torso) == pytest.approx(1.0, abs=1e-4)


def test_config_merge_keeps_defaults():
    cfg = deep_merge(DEFAULT_CONFIG, {"model": {"arch": "lstm"}, "train": {"epochs": 3}})
    assert cfg["model"]["arch"] == "lstm" and cfg["model"]["lstm"]["hidden"] == 64
    assert cfg["train"]["epochs"] == 3 and cfg["train"]["patience"] == 10
    assert DEFAULT_CONFIG["model"]["arch"] == "cnn"
