"""End-to-end smoke tests: prepare_data -> train -> temporal detector -> eval,
on synthetic data with a fake pose estimator."""

import cv2
import numpy as np
import pytest

import eval as evaluation
from core.features import FALLEN, FALLING, LABELS
from detectors import create_detector
from tests.synth import bbox_of, fall_sequence, persons_from, synthetic_caches
from train import prepare_data, train
from train.datasets import VideoRecord, fall_segments
from train.prepare_data import (
    build_windows, extract_video, load_cache, persons_by_frame, save_cache, stitch_subject,
)


class FakeEstimator:
    """Stands in for PoseEstimator: replays a precomputed list of Persons per frame."""

    def __init__(self, persons):
        self.persons = persons
        self.i = 0

    def reset(self):
        self.i = 0

    def __call__(self, frame):
        out = self.persons[self.i] if self.i < len(self.persons) else []
        self.i += 1
        return out


def write_frames(folder, n):
    folder.mkdir(parents=True)
    for i in range(n):
        cv2.imwrite(str(folder / f"f-{i:03d}.png"), np.zeros((8, 8, 3), np.uint8))
    return folder


def test_stitch_subject_follows_the_person_through_an_id_switch():
    kps, _ = fall_sequence(n_before=20, n_fall=10, n_after=20)
    persons = persons_from(kps)
    for f in range(30, 50):
        persons[f][0].track_id = 7                                # tracker switches ids mid-fall
    bystander = kps[0].copy()
    bystander[:, 0] += 2000                                      # someone far away, bigger box
    bystander[:, 1] *= 1.5
    det_frame, det_bbox, det_conf = [], [], []
    for f, frame in enumerate(persons):
        for p in frame:
            det_frame.append(f), det_bbox.append(p.bbox), det_conf.append(0.9)
        if f >= 25:
            det_frame.append(f), det_bbox.append(bbox_of(bystander)), det_conf.append(0.9)
    subject = stitch_subject(np.array(det_frame), np.array(det_bbox), np.array(det_conf), len(persons))
    chosen = np.array(det_bbox)[subject]
    np.testing.assert_allclose(chosen[:, 0], [persons[f][0].bbox[0] for f in range(len(persons))])


def test_extract_and_cache_round_trip(tmp_path):
    kps, labels = fall_sequence(n_before=30, n_fall=10, n_after=20)
    n = len(kps)
    record = VideoRecord("toy", "toy/v 1", "toy/v 1", write_frames(tmp_path / "frames", n),
                         fall_segments(30, 39), fps=25.0)
    cache = extract_video(record, FakeEstimator(persons_from(kps)))
    assert cache["n_frames"] == n and cache["fps"] == 25.0
    np.testing.assert_array_equal(cache["frame_labels"], labels)
    assert (cache["subject_det"] >= 0).all()
    path = tmp_path / "cache" / prepare_data.cache_filename(record.video_id)
    save_cache(path, cache)
    loaded = load_cache(path)
    assert loaded["video_id"] == "toy/v 1" and loaded["fps"] == 25.0
    np.testing.assert_array_equal(loaded["det_kps"], cache["det_kps"])
    frames = persons_by_frame(loaded)
    assert len(frames) == n and frames[5][0].track_id == 1
    np.testing.assert_allclose(frames[5][0].keypoints, kps[5])


def test_prepare_data_cli(tmp_path, monkeypatch):
    kps, _ = fall_sequence(n_before=30, n_fall=10, n_after=20)
    root = tmp_path / "data"
    write_frames(root / "clip", len(kps))
    (root / "manifest.csv").write_text("video,group,fall_start,fall_end,fps\nclip,s1,30,39,25\n")
    index = prepare_data.main(["--dataset", "manifest", "--root", str(root), "--out", str(tmp_path / "cache")],
                              estimator=FakeEstimator(persons_from(kps)))
    assert index[0]["has_fall"] and index[0]["n_frames"] == len(kps)
    assert (tmp_path / "cache" / "index.json").exists()
    assert len(list((tmp_path / "cache").glob("*.npz"))) == 1


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("train")
    cache_dir = tmp / "cache"
    for c in synthetic_caches(n_fall=12, n_walk=8, n_lying=2):
        save_cache(cache_dir / prepare_data.cache_filename(c["video_id"]), c)
    config = tmp / "cfg.yaml"
    config.write_text(
        f"data: {{caches: ['{cache_dir.as_posix()}'], stride: 1}}\n"
        "split: {val_frac: 0.25, test_frac: 0.25}\n"
        "model: {arch: cnn, cnn: {channels: 32, num_layers: 2}}\n"
        "train: {epochs: 25, batch_size: 64, patience: 8, lr: 3.0e-3, device: cpu}\n"
        f"out: '{(tmp / 'run').as_posix()}'\n")
    return tmp, train.main(["--config", str(config)])


def test_training_writes_checkpoint_split_and_confusion(trained, capsys):
    tmp, summary = trained
    assert (tmp / "run" / "best.pt").exists()
    assert (tmp / "run" / "split.json").exists() and (tmp / "run" / "metrics.json").exists()
    assert summary["best_epoch"] >= 1
    assert np.asarray(summary["val_confusion"]).shape == (3, 3)
    assert summary["val_macro_f1"] > 0.5        # separable synthetic data


def test_lstm_option_trains(tmp_path):
    cache_dir = tmp_path / "cache"
    for c in synthetic_caches(n_fall=4, n_walk=4, n_lying=0):
        save_cache(cache_dir / prepare_data.cache_filename(c["video_id"]), c)
    summary = train.main(["--cache", str(cache_dir), "--arch", "lstm", "--epochs", "2",
                          "--device", "cpu", "--out", str(tmp_path / "run")])
    from train.model import load_checkpoint
    _, meta = load_checkpoint(summary["checkpoint"])
    assert meta["arch"] == "lstm" and meta["window"] == 30


def test_eval_compares_both_detectors_on_the_same_videos(trained, capsys):
    tmp, summary = trained
    results = evaluation.main(["--cache", str(tmp / "cache"), "--split-file", str(tmp / "run" / "split.json"),
                               "--split", "test", "--checkpoint", summary["checkpoint"], "--device", "cpu"])
    assert set(results) == {"rule_based", "temporal_model"}
    out = capsys.readouterr().out
    assert "rule_based" in out and "temporal_model" in out and "false alarms" in out
    # Exactly the held-out test groups were evaluated, by both detectors.
    from train.splits import load_split
    test_groups = set(load_split(tmp / "run" / "split.json")["test"])
    for res in results.values():
        assert {v["video_id"] for v in res["per_video"]} == test_groups   # synthetic: group == video
    # Both detectors catch the separable synthetic falls without false alarms.
    for name, res in results.items():
        assert res["falls"] > 0 and res["fn"] == 0 and res["fp"] == 0, name


def test_compare_selects_installs_and_calibrates_rules(trained, tmp_path, monkeypatch):
    import train.compare as compare

    tmp, _ = trained
    monkeypatch.setattr(compare, "DEFAULT_CHECKPOINT", tmp_path / "ck" / "temporal_model.pt")
    monkeypatch.setattr(compare, "RULE_CALIBRATION", tmp_path / "ck" / "rule_based.json")
    best, rows = compare.main(["--runs", str(tmp / "run"), "--cache", str(tmp / "cache"),
                               "--split-file", str(tmp / "run" / "split.json"), "--device", "cpu",
                               "--install"])
    assert best == "run" and set(rows) == {"rule_based", "run"}
    assert (tmp_path / "ck" / "temporal_model.pt").exists()
    assert rows["run"]["val_event_f1"] is not None and rows["run"]["test_falls"] > 0
    import json
    rules = json.loads((tmp_path / "ck" / "rule_based.json").read_text())["emitter"]
    import detectors.rule_based as rule_based
    monkeypatch.setattr(rule_based, "CALIBRATION", tmp_path / "ck" / "rule_based.json")
    assert create_detector("rule_based").emitter.config.to_dict() == rules


def test_trained_temporal_detector_runs_on_a_fall(trained):
    _, summary = trained
    det = create_detector("temporal_model", checkpoint=summary["checkpoint"], device="cpu")
    kps, _ = fall_sequence(n_before=45, n_fall=15, n_after=45)
    det.reset(25.0)
    for f, frame in enumerate(persons_from(kps)):
        det.update(f, frame)
    assert det.statuses()[1].state in (FALLING, FALLEN)


def test_match_events():
    fall = (100, 120)
    assert evaluation.match_events([], None, 25) == {"tp": 0, "fp": 0, "fn": 0, "latency_s": None}
    assert evaluation.match_events([10, 300], None, 25)["fp"] == 2
    m = evaluation.match_events([130, 140, 400], fall, 25.0, before_s=1.0, after_s=3.0)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 0) and m["latency_s"] == pytest.approx(0.4)
    assert evaluation.match_events([500], fall, 25.0)["fn"] == 1


@pytest.mark.parametrize("frame,tp", [(90, 1), (89, 0), (140, 1), (141, 0), (110, 1)])
def test_match_window_edges(frame, tp):
    # fps 10, before 1 s, after 2 s: window [100 - 10, 120 + 20] = [90, 140]
    m = evaluation.match_events([frame], (100, 120), 10.0, before_s=1.0, after_s=2.0)
    assert (m["tp"], m["fp"], m["fn"]) == ((1, 0, 0) if tp else (0, 1, 1))
    if tp:
        assert m["latency_s"] == pytest.approx((frame - 120) / 10.0)


def test_ground_truth_fall_with_unknown_frames():
    gt = evaluation.ground_truth_fall
    assert gt(np.array([0, 0, 1, 1, 2, 2])) == (2, 4)
    assert gt(np.zeros(5)) is None
    assert gt(np.array([-1, -1, 0, 0, 1, 2, 2, -1])) == (4, 5)
    assert gt(np.array([0, 0, 2, 2, -1])) == (2, 2)          # no FALLING frames
    assert gt(np.array([0, 1, 1, 1, -1])) == (1, 3)          # no FALLEN frames: impact = last falling
    assert gt(np.full(4, -1)) is None


def test_evaluate_frame_level_on_a_hand_built_cache():
    """Frame confusion only counts known labels and frames with a fresh prediction."""
    from tests.synth import make_cache

    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=40)
    labels = labels.copy()
    labels[-10:] = -1                                         # unannotated tail
    hidden = kps.copy()
    hidden[20:25, :, 2] = 0                                   # no usable pose for 5 frames
    cache = make_cache("v", "g", hidden, labels, fps=25.0)
    det = create_detector("rule_based")
    res = evaluation.evaluate(det, [(cache, persons_by_frame(cache))])
    cm = res["confusion"]
    known = int((labels != -1).sum())
    assert cm.sum() == known - 5                              # 5 frames without a prediction
    assert res["frame_coverage"] == pytest.approx((known - 5) / known)
    assert cm[0, 0] == int(((labels == 0)).sum()) - 5          # standing frames all NORMAL
    assert (res["tp"], res["fp"], res["fn"]) == (1, 0, 0)


def test_eval_split_requires_a_split_file(trained):
    tmp, _ = trained
    with pytest.raises(SystemExit):
        evaluation.main(["--cache", str(tmp / "cache"), "--split", "test", "--detectors", "rule_based"])


def test_eval_json_output(trained, tmp_path):
    tmp, summary = trained
    out = tmp_path / "res.json"
    evaluation.main(["--cache", str(tmp / "cache"), "--detectors", "rule_based", "--json", str(out)])
    import json
    data = json.loads(out.read_text())
    assert data["rule_based"]["videos"] == 22 and len(data["rule_based"]["confusion"]) == 3


def test_image_folders_are_read_in_natural_order(tmp_path):
    from core.video import FrameSource

    folder = tmp_path / "seq"
    folder.mkdir()
    for i in (1, 2, 10, 100, 1000, 999):
        img = np.zeros((4, 4, 3), np.uint8)
        img[0, 0] = [i % 256, i // 256, 0]
        cv2.imwrite(str(folder / f"adl-01-cam0-rgb-{i:03d}.png"), img)
    order = [int(f[0, 0, 0]) + 256 * int(f[0, 0, 1]) for _, f in FrameSource(folder)]
    assert order == [1, 2, 10, 100, 999, 1000]


def test_frame_source_crop(tmp_path):
    from core.video import FrameSource

    folder = tmp_path / "seq"
    folder.mkdir()
    img = np.zeros((4, 8, 3), np.uint8)
    img[:, 4:] = 200                                         # right half bright
    cv2.imwrite(str(folder / "f-1.png"), img)
    (_, right), = FrameSource(folder, crop="right_half")
    (_, left), = FrameSource(folder, crop="left_half")
    (_, box), = FrameSource(folder, crop=[1, 0, 3, 2])
    assert right.shape == (4, 4, 3) and right.min() == 200 and left.max() == 0 and box.shape == (2, 2, 3)


def test_cache_reuse_refreshes_labels_and_recovers_from_corruption(tmp_path):
    kps, _ = fall_sequence(n_before=30, n_fall=10, n_after=20)
    frames = write_frames(tmp_path / "frames", len(kps))
    settings = prepare_data.extraction_settings("w.pt")
    calls = []

    def get_estimator():
        calls.append(1)
        return FakeEstimator(persons_from(kps))

    path = tmp_path / "c.npz"
    rec = VideoRecord("toy", "toy/v", "toy/v", frames, fall_segments(30, 39), fps=25.0)
    prepare_data.cached_extract(rec, path, settings, get_estimator)
    assert len(calls) == 1 and not list(tmp_path.glob("*.part"))

    # New labels/group from the loader: reused without pose, and written back for train.py.
    rec2 = VideoRecord("toy", "toy/v", "toy/scene", frames, fall_segments(31, 40), fps=25.0)
    cache = prepare_data.cached_extract(rec2, path, settings, get_estimator)
    assert len(calls) == 1 and cache["group_id"] == "toy/scene"
    assert load_cache(path)["frame_labels"][30] == 0 and load_cache(path)["group_id"] == "toy/scene"

    # Different pose settings (e.g. --max-frames) -> re-extracted.
    prepare_data.cached_extract(rec2, path, prepare_data.extraction_settings("w.pt", max_frames=10),
                                get_estimator)
    assert len(calls) == 2 and load_cache(path)["n_frames"] == 10

    # Truncated file -> re-extracted instead of silently dropped.
    path.write_bytes(path.read_bytes()[:100])
    cache = prepare_data.cached_extract(rec2, path, settings, get_estimator)
    assert len(calls) == 3 and cache["n_frames"] == len(kps)


def test_config_values_are_coerced(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("data: {caches: some/dir}\ntrain: {lr: 1e-3, epochs: '7', weight_decay: 0}\n")
    loaded = train.load_config(cfg)
    assert loaded["train"]["lr"] == pytest.approx(1e-3) and isinstance(loaded["train"]["lr"], float)
    assert loaded["train"]["epochs"] == 7 and loaded["data"]["caches"] == ["some/dir"]
    cfg.write_text("train: {lr: fast}\n")
    with pytest.raises(ValueError, match="train.lr"):
        train.load_config(cfg)


def test_arch_override_does_not_overwrite_the_config_run(tmp_path):
    cache_dir = tmp_path / "cache"
    for c in synthetic_caches(n_fall=4, n_walk=4, n_lying=0):
        save_cache(cache_dir / prepare_data.cache_filename(c["video_id"]), c)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"data: {{caches: ['{cache_dir.as_posix()}']}}\nout: '{(tmp_path / 'runs' / 'cnn').as_posix()}'\n")
    summary = train.main(["--config", str(cfg), "--arch", "lstm", "--epochs", "1", "--device", "cpu"])
    assert summary["checkpoint"] == str(tmp_path / "runs" / "lstm" / "best.pt")
    assert not (tmp_path / "runs" / "cnn").exists()


def test_unconfirmed_track_frames_are_excluded_like_serving(tmp_path):
    """Training windows (subject_sequence) skip detections the tracker hadn't confirmed
    (track_id None), exactly as the live detector does -- including warm-up windows."""
    import torch
    from tests.synth import make_cache
    from train.model import build_model, save_checkpoint
    from core.features import sequence_windows, to_model_input
    from detectors.temporal_model import TemporalModelDetector
    from train.prepare_data import subject_sequence

    kps, labels = fall_sequence(n_before=40, n_fall=10, n_after=40)
    cache = make_cache("v", "g", kps, labels)
    cache["det_track"][[0, 1, 2, 50, 51]] = -1                # unconfirmed at the start and mid-way
    frames, sub_kps = subject_sequence(cache)
    assert 0 not in frames and 50 not in frames and len(frames) == len(kps) - 5

    path = tmp_path / "m.pt"
    save_checkpoint(path, build_model("cnn", channels=8, num_layers=1), "cnn",
                    {"channels": 8, "num_layers": 1},
                    {"window": 30, "max_gap": 5, "conf_min": 0.3, "min_frames": 10})
    det = TemporalModelDetector(checkpoint=path, device="cpu", min_visible_kps=0)
    seen = []

    class Recorder(torch.nn.Module):
        def forward(self, x):
            seen.append(x.numpy().copy())
            return torch.zeros(len(x), 3)

    det.model = Recorder()
    evaluation.replay(det, cache, persons_by_frame(cache))
    x_train, _, ends = sequence_windows(frames, sub_kps, cache["frame_labels"], 30, 1, 5, 0.3, 10)
    keep = np.isin(ends, frames)
    np.testing.assert_allclose(np.concatenate(seen), to_model_input(x_train[keep]), atol=1e-5)


def test_min_frames_zero_is_stored_as_effective_value(tmp_path):
    cache_dir = tmp_path / "cache"
    for c in synthetic_caches(n_fall=4, n_walk=4, n_lying=0):
        save_cache(cache_dir / prepare_data.cache_filename(c["video_id"]), c)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"data: {{caches: ['{cache_dir.as_posix()}'], min_frames: 0}}\n"
                   f"train: {{epochs: 1, device: cpu, calibrate: false}}\nout: '{(tmp_path / 'r').as_posix()}'\n")
    summary = train.main(["--config", str(cfg)])
    det = create_detector("temporal_model", checkpoint=summary["checkpoint"], device="cpu")
    assert det.min_frames == 1


def test_bad_augment_config_fails_at_startup(tmp_path):
    cfg = tmp_path / "c.yaml"
    for bad in ("{squash: [0.9, 0.5]}", "{rotate_deg: -10}", "{occlude_lower_p: 2}", "{rotate: 10}",
                "{squash: [0.5]}"):
        cfg.write_text(f"train: {{augment: {bad}}}\n")
        with pytest.raises(ValueError):
            train.load_config(cfg)
    cfg.write_text("train: {augment: {squash: [0.6, 1e0]}}\n")       # YAML reads 1e0 as a string
    assert train.load_config(cfg)["train"]["augment"]["squash"] == [0.6, 1.0]


def test_windows_cover_every_label():
    ws = build_windows(synthetic_caches())
    assert set(np.unique(ws.y)) == set(range(len(LABELS)))
    assert ws.x.shape[1:] == (30, 17, 3) and len(ws.groups) == len(ws.y)
