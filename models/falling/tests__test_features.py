"""Windowing and normalization (core/features.py)."""

import numpy as np
import pytest

from core.features import (
    FALLBACK_TORSO_FRACTION, FALLEN, FALLING, NORMAL, UNKNOWN, TrackBuffer, densify, flip_windows, label_lookup,
    make_windows, normalize_window, normalize_windows, sequence_windows, to_model_input,
)
from core.keypoints import FLIP_PERM, KP_L_HIP, KP_L_SHOULDER, KP_R_HIP, KP_R_SHOULDER
from tests.synth import fall_sequence, skeleton, walk_sequence


def hip_center(norm):
    return (norm[..., KP_L_HIP, :2] + norm[..., KP_R_HIP, :2]) / 2


# ------------------------------------------------------------ normalization --

def test_window_is_centered_on_mean_hip_and_scaled_by_torso():
    kps, _ = walk_sequence(n=30)
    norm = normalize_window(kps)
    assert norm.shape == (30, 17, 3) and norm.dtype == np.float32
    np.testing.assert_allclose(hip_center(norm).mean(axis=0), [0, 0], atol=1e-5)
    torso = np.linalg.norm((norm[:, KP_L_SHOULDER, :2] + norm[:, KP_R_SHOULDER, :2]) / 2
                           - hip_center(norm), axis=-1)
    assert np.median(torso) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.parametrize("shift,scale", [((0, 0), 2.5), ((350, -120), 1.0), ((-80, 40), 0.4)])
def test_normalization_is_translation_and_scale_invariant(shift, scale):
    kps, _ = fall_sequence(n_before=10, n_fall=10, n_after=10)
    moved = kps.copy()
    moved[..., :2] = kps[..., :2] * scale + np.array(shift)
    np.testing.assert_allclose(normalize_window(moved), normalize_window(kps), atol=1e-4)


def test_global_motion_within_the_window_is_preserved():
    """Centering per window (not per frame) keeps the body's downward motion."""
    kps = np.stack([skeleton(300, 400 + 6 * t, 200) for t in range(30)])
    hips_y = hip_center(normalize_window(kps))[:, 1]
    assert np.all(np.diff(hips_y) > 0)
    assert hips_y[-1] - hips_y[0] == pytest.approx(29 * 6 / (0.30 * 200), rel=1e-3)


def test_invisible_keypoints_are_zeroed_and_ignored():
    kps, _ = walk_sequence(n=30)
    ref = normalize_window(kps)
    hidden = kps.copy()
    hidden[:, 0, 2] = 0.1            # nose below the confidence threshold
    hidden[5, 9, :] = np.nan         # a NaN wrist
    norm = normalize_window(hidden)
    assert np.isfinite(norm).all()
    assert (norm[:, 0] == 0).all() and (norm[5, 9] == 0).all()
    other = np.ones(17, bool)
    other[0] = False
    np.testing.assert_allclose(norm[:, other][np.arange(30) != 5], ref[:, other][np.arange(30) != 5],
                               atol=1e-5)


def test_one_visible_hip_is_enough_for_the_center():
    kps, _ = walk_sequence(n=30)
    one_hip = kps.copy()
    one_hip[:, KP_R_HIP, 2] = 0.0
    center = (kps[:, KP_L_HIP, :2]).mean(axis=0)
    norm = normalize_window(one_hip)
    torso = np.median(np.linalg.norm(
        (kps[:, KP_L_SHOULDER, :2] + kps[:, KP_R_SHOULDER, :2]) / 2 - kps[:, KP_L_HIP, :2], axis=-1))
    np.testing.assert_allclose(norm[:, KP_L_HIP, :2], (kps[:, KP_L_HIP, :2] - center) / torso, atol=1e-4)


def test_no_hips_falls_back_to_keypoint_mean_and_extent():
    kps, _ = walk_sequence(n=30)
    kps[:, [KP_L_HIP, KP_R_HIP, KP_L_SHOULDER, KP_R_SHOULDER], 2] = 0.0
    norm = normalize_window(kps)
    assert np.isfinite(norm).all()
    visible = norm[..., 2] > 0
    np.testing.assert_allclose(norm[..., :2][visible].mean(axis=0), [0, 0], atol=1e-4)
    # scale = FALLBACK_TORSO_FRACTION x median extent -> normalized extent is its inverse
    vis_xy = np.where(visible[..., None], norm[..., :2], np.nan)
    extent = np.nanmax(np.nanmax(vis_xy, axis=1) - np.nanmin(vis_xy, axis=1), axis=-1)
    assert np.median(extent) == pytest.approx(1 / FALLBACK_TORSO_FRACTION, rel=1e-4)


def test_confidence_is_kept_for_visible_keypoints():
    kps, _ = walk_sequence(n=30)
    rng = np.random.default_rng(0)
    kps[..., 2] = rng.uniform(0.0, 1.0, size=kps.shape[:2])
    kps[0, 0, 2] = 0.30                                   # exactly at the threshold counts
    norm = normalize_window(kps, conf_min=0.30)
    visible = kps[..., 2] >= 0.30
    np.testing.assert_allclose(norm[..., 2][visible], kps[..., 2][visible], atol=1e-6)
    assert (norm[..., 2][~visible] == 0).all() and norm[0, 0, 2] == pytest.approx(0.30)


def test_nothing_visible_gives_zeros():
    kps = np.zeros((30, 17, 3), np.float32)
    assert (normalize_window(kps) == 0).all()


def test_foreshortened_torso_cannot_blow_up_the_scale():
    """Torso collapses to almost nothing; the extent guard keeps coordinates bounded."""
    kps = np.stack([skeleton(300, 400, 200) for _ in range(30)])
    sh_mid = (kps[:, KP_L_SHOULDER, :2] + kps[:, KP_R_SHOULDER, :2]) / 2
    hip_mid = (kps[:, KP_L_HIP, :2] + kps[:, KP_R_HIP, :2]) / 2
    kps[:, [KP_L_SHOULDER, KP_R_SHOULDER], :2] -= (sh_mid - hip_mid)[:, None] * 0.97
    assert np.abs(normalize_window(kps)[..., :2]).max() < 5


def test_batch_matches_single_window_normalization():
    kps, _ = fall_sequence(n_before=20, n_fall=10, n_after=20)
    batch = np.stack([kps[i:i + 30] for i in range(0, 20, 5)])
    np.testing.assert_allclose(normalize_windows(batch),
                               np.stack([normalize_window(w) for w in batch]), atol=1e-6)
    assert normalize_windows(np.zeros((0, 30, 17, 3))).shape == (0, 30, 17, 3)


def test_model_input_shape():
    assert to_model_input(np.zeros((4, 30, 17, 3))).shape == (4, 30, 51)


COCO_NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder",
              "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip",
              "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def test_flip_permutation_swaps_left_and_right_names():
    swap = {"left": "right", "right": "left"}
    for i, j in enumerate(FLIP_PERM):
        side, _, part = COCO_NAMES[i].partition("_")
        expected = f"{swap[side]}_{part}" if side in swap else COCO_NAMES[i]
        assert COCO_NAMES[j] == expected


def test_flip_mirrors_left_right_and_is_an_involution():
    kps, _ = walk_sequence(n=30)
    norm = normalize_window(kps)
    norm[3, 7] = 0   # a missing keypoint stays exactly zero
    flipped = flip_windows(norm)
    np.testing.assert_allclose(flipped[..., 0], -norm[..., FLIP_PERM, 0], atol=1e-6)
    np.testing.assert_allclose(flipped[..., 1:], norm[..., FLIP_PERM, 1:])
    assert (flipped[3, FLIP_PERM[7]] == 0).all()
    np.testing.assert_allclose(flip_windows(flipped), norm, atol=1e-6)


# ---------------------------------------------------------------- windowing --

def test_make_windows_counts_labels_and_positions():
    kps = np.arange(50, dtype=np.float32)[:, None, None] * np.ones((50, 17, 3), np.float32)
    labels = np.array([NORMAL] * 30 + [FALLING] * 10 + [FALLEN] * 10)
    x, y, ends = make_windows(kps, labels, window=30, stride=1)
    assert x.shape == (21, 30, 17, 3)
    np.testing.assert_array_equal(ends, np.arange(29, 50))
    np.testing.assert_array_equal(y, labels[29:])                        # labelled by the last frame
    np.testing.assert_array_equal(x[:, -1, 0, 0], ends)                  # last frame is the end frame
    np.testing.assert_array_equal(x[:, 0, 0, 0], ends - 29)              # 30 consecutive frames

    x, y, ends = make_windows(kps, labels, window=30, stride=4)
    np.testing.assert_array_equal(ends, np.arange(29, 50, 4))


def test_make_windows_warm_up_pads_with_the_first_pose():
    kps = np.arange(40, dtype=np.float32)[:, None, None] * np.ones((40, 17, 3), np.float32)
    labels = np.zeros(40, dtype=np.int64)
    x, y, ends = make_windows(kps, labels, window=30, min_frames=10)
    np.testing.assert_array_equal(ends, np.arange(9, 40))
    np.testing.assert_array_equal(x[0, :, 0, 0], [0] * 20 + list(range(10)))   # 20 padded copies of frame 0
    np.testing.assert_array_equal(x[-1, :, 0, 0], np.arange(10, 40))           # full windows unchanged
    assert make_windows(kps[:9], labels[:9], window=30, min_frames=10)[0].shape[0] == 0


def test_make_windows_drops_unknown_and_short_sequences():
    kps = np.zeros((40, 17, 3), np.float32)
    labels = np.full(40, NORMAL)
    labels[35:] = UNKNOWN
    _, y, ends = make_windows(kps, labels, window=30)
    assert ends.max() == 34 and len(y) == 6
    x, y, ends = make_windows(kps[:29], labels[:29], window=30)
    assert x.shape == (0, 30, 17, 3) and len(y) == 0


def test_densify_fills_short_gaps_and_splits_long_ones():
    frames = np.array([0, 1, 2, 5, 6, 20, 21, 21])
    kps = np.arange(len(frames), dtype=np.float32)[:, None, None] * np.ones((1, 17, 3), np.float32)
    segments = densify(frames, kps, max_gap=2)
    assert len(segments) == 2
    f0, k0 = segments[0]
    np.testing.assert_array_equal(f0, [0, 1, 2, 3, 4, 5, 6])
    np.testing.assert_array_equal(k0[:, 0, 0], [0, 1, 2, 2, 2, 3, 4])   # gap held at the last pose
    f1, k1 = segments[1]
    np.testing.assert_array_equal(f1, [20, 21])
    np.testing.assert_array_equal(k1[:, 0, 0], [5, 6])                   # duplicate frame keeps the first
    assert densify([], np.zeros((0, 17, 3))) == []


def test_label_lookup_outside_range_is_unknown():
    np.testing.assert_array_equal(label_lookup([0, 1, 2], [-1, 0, 2, 3]), [UNKNOWN, 0, 2, UNKNOWN])


def test_sequence_windows_use_true_labels_of_filled_frames():
    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=30)
    frames = np.delete(np.arange(len(kps)), [44, 45])            # 2-frame tracking gap
    x, y, ends = sequence_windows(frames, kps[frames], labels, window=30, stride=1, max_gap=5)
    np.testing.assert_array_equal(ends, np.arange(29, len(kps)))
    np.testing.assert_array_equal(y, labels[29:])
    assert x.dtype == np.float32 and np.isfinite(x).all()


@pytest.mark.parametrize("window,max_gap,conf_min,min_frames",
                         [(30, 5, 0.3, None), (20, 2, 0.6, None), (30, 5, 0.3, 10), (20, 2, 0.6, 1)])
def test_online_buffer_matches_offline_windows(window, max_gap, conf_min, min_frames):
    """Train/serve parity: TrackBuffer yields exactly the windows training uses."""
    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=40)
    kps[::5, 9, 2] = 0.5
    frames = np.delete(np.arange(len(kps)), [10, 11, 50, 60, 61, 62, 63, 64, 65, 66])  # short + long gaps
    offline_x, _, offline_ends = sequence_windows(frames, kps[frames], labels, window=window,
                                                  max_gap=max_gap, conf_min=conf_min,
                                                  min_frames=min_frames)

    buf = TrackBuffer(window=window, max_gap=max_gap, min_frames=min_frames)
    online_x, online_ends = [], []
    for f in frames:
        buf.push(int(f), kps[f])
        if buf.ready:
            online_x.append(normalize_window(buf.window_array(), conf_min))
            online_ends.append(f)
    # Offline windows also end on filled-in frames; online only on observed ones.
    keep = np.isin(offline_ends, online_ends)
    np.testing.assert_array_equal(offline_ends[keep], online_ends)
    np.testing.assert_allclose(offline_x[keep], np.stack(online_x), atol=1e-6)


def test_track_buffer_resets_after_long_gap_and_ignores_duplicates():
    buf = TrackBuffer(window=3, max_gap=1)
    k = np.zeros((17, 3))
    assert buf.push(0, k) is False
    buf.push(1, k)
    buf.push(1, k + 5)                 # duplicate frame ignored
    assert len(buf) == 2 and buf.window_array()[-1, 0, 0] == 0
    buf.push(3, k)                     # 1 missing frame: filled
    assert buf.ready
    assert buf.push(10, k) is True     # 6 missing frames: reset
    assert len(buf) == 1 and not buf.ready
