"""Detectors behind the FallDetector interface (rule-based and temporal model)."""

import numpy as np
import pytest
import torch

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN
from detectors import FallDetector, available_detectors, create_detector, detector_classes
from detectors.rule_based import RuleBasedFallDetector
from detectors.temporal_model import TemporalModelDetector
from train.model import build_model, save_checkpoint
from tests.synth import fall_sequence, lying_sequence, persons_from, walk_sequence


def run(detector, persons, fps=25.0):
    detector.reset(fps)
    return [e for f, frame in enumerate(persons) for e in detector.update(f, frame)]


def test_both_detectors_are_registered_for_the_dropdown():
    names = available_detectors()
    assert list(names)[:2] == ["rule_based", "temporal_model"]
    assert all(issubclass(cls, FallDetector) for cls in detector_classes().values())
    with pytest.raises(ValueError):
        create_detector("nope")


def test_rule_based_detects_a_fall_once():
    kps, labels = fall_sequence(n_before=40, n_fall=15, n_after=50)
    events = run(RuleBasedFallDetector(), persons_from(kps))
    assert len(events) == 1
    impact = int(np.argmax(labels == FALLEN))
    assert impact - 10 <= events[0].frame_idx <= impact + 25
    assert events[0].track_id == 1 and events[0].fall_start_frame < events[0].frame_idx


@pytest.mark.parametrize("seq", [walk_sequence, lying_sequence])
def test_rule_based_ignores_walking_and_lying(seq):
    kps, _ = seq()
    assert run(RuleBasedFallDetector(), persons_from(kps)) == []


def test_rule_based_states():
    det = RuleBasedFallDetector()
    kps, _ = fall_sequence(n_before=5, n_fall=10, n_after=5)
    assert det.classify(kps[0])[0] == NORMAL
    assert det.classify(kps[-1])[0] == FALLEN
    hidden = kps[0].copy()
    hidden[:, 2] = 0
    assert det.classify(hidden) == (UNKNOWN, 0.0)


def id_switch(persons, at, new_id=7):
    """The tracker renames the person from frame ``at`` on (typical mid-fall)."""
    from dataclasses import replace
    return [[replace(p, track_id=new_id) for p in frame] if f >= at else frame
            for f, frame in enumerate(persons)]


def test_rule_based_survives_an_id_switch_during_the_fall():
    kps, labels = fall_sequence(n_before=40, n_fall=15, n_after=50)
    switched = id_switch(persons_from(kps), at=48)      # mid-fall
    det = RuleBasedFallDetector()
    events = run(det, switched)
    assert len(events) == 1 and events[0].track_id == 1
    assert det.status_for(7).track_id == 1 and det.status_for(7).alerted
    assert run(RuleBasedFallDetector(link_s=0), switched) == []     # without linking: missed


def test_linker_does_not_merge_distant_people():
    kps, _ = walk_sequence(n=40)
    far, _ = walk_sequence(n=40, cx=900)
    persons = persons_from(kps[:20], 1) + persons_from(far[20:], 2)   # 1 leaves, 2 appears far away
    det = RuleBasedFallDetector()
    run(det, persons)
    assert det.status_for(2).track_id == 2


def test_untracked_persons_are_skipped():
    kps, _ = fall_sequence()
    persons = persons_from(kps, track_id=None)
    assert run(RuleBasedFallDetector(), persons) == []


class FakeModel(torch.nn.Module):
    """'Model' that reads the hip height in the last frame: low hips => fallen.
    Lets the detector's buffering/smoothing/emission be tested without training."""

    def forward(self, x):
        hip_y = (x[:, -1, 11 * 3 + 1] + x[:, -1, 12 * 3 + 1]) / 2
        hip_start = (x[:, 0, 11 * 3 + 1] + x[:, 0, 12 * 3 + 1]) / 2
        fallen = (hip_y - hip_start) > 0.5
        logits = torch.full((len(x), 3), -5.0)
        logits[~fallen, NORMAL] = 5.0
        logits[fallen, FALLEN] = 5.0
        return logits


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "best.pt"
    save_checkpoint(path, build_model("cnn", channels=8, num_layers=1), "cnn",
                    {"channels": 8, "num_layers": 1}, {"window": 30, "max_gap": 5, "conf_min": 0.3})
    return path


def test_temporal_detector_loads_and_buffers_per_track(checkpoint):
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu")
    kps, _ = walk_sequence(n=40)
    other, _ = walk_sequence(n=40, cx=500)
    det.reset(25.0)
    for f in range(40):
        persons = persons_from(kps[f:f + 1], 1)[0] + persons_from(other[f:f + 1], 2)[0]
        det.update(f, persons)
        statuses = det.statuses()
        if f < 29:
            assert statuses[1].state == UNKNOWN          # buffer not full yet
        else:
            assert statuses[1].state != UNKNOWN and statuses[2].state != UNKNOWN
    probs = det.probabilities()
    assert set(probs) == {1, 2} and abs(sum(probs[1].values()) - 1) < 1e-5


def test_temporal_detector_emits_with_shared_logic(checkpoint):
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu", smoothing=0.3)
    det.model = FakeModel()
    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=40)
    events = run(det, persons_from(kps))
    assert len(events) == 1
    impact = int(np.argmax(labels == FALLEN))
    assert impact - 10 <= events[0].frame_idx <= impact + 20

    kps, _ = lying_sequence()
    assert run(det, persons_from(kps)) == []

    kps, _ = fall_sequence(n_before=40, n_fall=10, n_after=40)
    events = run(det, id_switch(persons_from(kps), at=45))           # same buffer continues
    assert len(events) == 1


@pytest.mark.parametrize("window,max_gap,conf_min,min_frames",
                         [(30, 5, 0.3, None), (20, 2, 0.6, None), (30, 5, 0.3, 10)])
def test_serving_input_matches_training_windows(tmp_path, window, max_gap, conf_min, min_frames):
    """Train/serve parity through the real detector: the windows it feeds the model
    equal sequence_windows() with the checkpoint's settings."""
    from core.features import sequence_windows, to_model_input

    path = tmp_path / "m.pt"
    save_checkpoint(path, build_model("cnn", channels=8, num_layers=1), "cnn",
                    {"channels": 8, "num_layers": 1},
                    {"window": window, "max_gap": max_gap, "conf_min": conf_min,
                     "min_frames": min_frames})
    det = TemporalModelDetector(checkpoint=path, device="cpu", smoothing=0.0)
    seen = []

    class Recorder(torch.nn.Module):
        def forward(self, x):
            seen.append(x.numpy().copy())
            return torch.zeros(len(x), 3)

    det.model = Recorder()
    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=30)
    kps[::7, 3, 2] = 0.5                                  # conf between the two thresholds
    frames = np.delete(np.arange(len(kps)), [33, 34, 60, 61, 62])
    det.reset(25.0)
    for f in frames:
        det.update(int(f), persons_from(kps[f:f + 1])[0])
    x_train, _, ends = sequence_windows(frames, kps[frames], labels, window, 1, max_gap, conf_min,
                                        min_frames)
    keep = np.isin(ends, frames)              # online windows end on observed frames only
    served = np.concatenate(seen)
    assert served.shape == (keep.sum(), window, 51)
    np.testing.assert_allclose(served, to_model_input(x_train[keep]), atol=1e-5)


class SequenceModel(torch.nn.Module):
    """Returns the given logits rows, one per call."""

    def __init__(self, rows):
        super().__init__()
        self.rows = [torch.tensor(r, dtype=torch.float32) for r in rows]

    def forward(self, x):
        return self.rows.pop(0).expand(len(x), -1)


def test_temporal_detector_smooths_probabilities(checkpoint):
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu", smoothing=0.75)
    first, second = [5.0, 0.0, 0.0], [0.0, 0.0, 5.0]
    det.model = SequenceModel([first, second])
    kps, _ = walk_sequence(n=31)
    det.reset(25.0)
    for f in range(31):
        det.update(f, persons_from(kps[f:f + 1])[0])
    p1, p2 = torch.softmax(torch.tensor(first), 0).numpy(), torch.softmax(torch.tensor(second), 0).numpy()
    expected = 0.75 * p1 + 0.25 * p2
    np.testing.assert_allclose(list(det.probabilities()[1].values()), expected, atol=1e-6)
    assert det.statuses()[1].state == NORMAL          # one fallen-looking frame doesn't flip the state


def test_fallen_threshold_and_visibility_gate(checkpoint):
    row = [0.0, 0.2, 0.6]                       # softmax -> P(fallen) ~ 0.48, the argmax
    p_fallen = float(torch.softmax(torch.tensor(row), 0)[2])
    kps, _ = walk_sequence(n=12)

    def final_state(**kwargs):
        det = TemporalModelDetector(checkpoint=checkpoint, device="cpu", smoothing=0.0, **kwargs)
        det.min_frames = 10
        det.model = SequenceModel([row] * 50)
        det.reset(25.0)
        for f in range(12):
            det.update(f, persons_from(kps[f:f + 1])[0])
        return det.statuses()[1].state

    assert final_state(fallen_threshold=None) == FALLEN
    assert final_state(fallen_threshold=p_fallen + 0.05) == FALLING
    assert final_state(fallen_threshold=p_fallen - 0.05) == FALLEN
    hidden = kps.copy()
    hidden[:, 4:, 2] = 0.0                      # only 4 keypoints visible from the start
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu", min_visible_kps=6)
    det.reset(25.0)
    for f in range(40):
        det.update(f, persons_from(hidden[f % 12:f % 12 + 1])[0])
    assert det.statuses()[1].state == UNKNOWN   # never judged: nothing to hold


def test_gated_frames_hold_the_last_prediction(checkpoint):
    """A track whose keypoints flicker below the gate keeps its state: the upright
    streak survives and the fall is still alerted."""
    kps, _ = fall_sequence(n_before=40, n_fall=10, n_after=40)
    flicker = kps.copy()
    flicker[::4, 5:, 2] = 0.0                   # every 4th frame: only 5 keypoints visible
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu", smoothing=0.3, min_visible_kps=6)
    det.model = FakeModel()
    assert len(run(det, persons_from(flicker))) == 1


def test_calibration_stores_settings_in_checkpoint(checkpoint):
    from train.calibrate import calibrate
    from tests.synth import synthetic_caches

    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu")
    assert det.fallen_threshold is None and det.min_visible_kps == 6     # uncalibrated defaults
    best, rows = calibrate(checkpoint, synthetic_caches(n_fall=2, n_walk=1, n_lying=0),
                           thresholds=(None, 0.7), gates=(0, 6), device="cpu")
    assert [name for name, _ in rows][:4] == ["threshold=argmax gate=0", "threshold=argmax gate=6",
                                              "threshold=0.7 gate=0", "threshold=0.7 gate=6"]
    if best is not None:
        det = TemporalModelDetector(checkpoint=checkpoint, device="cpu")
        assert (det.fallen_threshold, det.min_visible_kps) == (best["fallen_threshold"], best["min_visible_kps"])
        assert det.emitter.config.to_dict() == best["emitter"]


def test_lost_while_falling_rule_through_a_detector():
    from detectors import EmitterConfig

    kps, _ = fall_sequence(n_before=40, n_fall=15, n_after=0)
    persons = persons_from(kps)[:50] + [[] for _ in range(40)]     # pose lost once on the way down
    assert len(run(RuleBasedFallDetector(emitter_config=EmitterConfig(lost_alert_s=0.5)), persons)) == 1
    assert run(RuleBasedFallDetector(), persons) == []


def test_calibration_without_falls_leaves_checkpoint_unchanged(checkpoint):
    from train.calibrate import calibrate
    from tests.synth import synthetic_caches

    before = checkpoint.read_bytes()
    best, _ = calibrate(checkpoint, synthetic_caches(n_fall=0, n_walk=2, n_lying=0), device="cpu")
    assert best is None and checkpoint.read_bytes() == before


@pytest.mark.parametrize("bad", ["Auto", 0.0, 1.5, True])
def test_bad_fallen_threshold_is_rejected(checkpoint, bad):
    with pytest.raises(ValueError):
        TemporalModelDetector(checkpoint=checkpoint, device="cpu", fallen_threshold=bad)


def test_temporal_detector_resets_buffer_after_long_gap(checkpoint):
    det = TemporalModelDetector(checkpoint=checkpoint, device="cpu")
    kps, _ = walk_sequence(n=80)
    det.reset(25.0)
    for f in list(range(35)) + list(range(60, 80)):         # 24 missing frames
        det.update(f, persons_from(kps[f:f + 1])[0])
    assert len(det._buffers[1]) == 20 and 1 not in det._probs


def test_temporal_detector_needs_a_checkpoint(tmp_path):
    with pytest.raises(FileNotFoundError):
        TemporalModelDetector(checkpoint=tmp_path / "missing.pt")
