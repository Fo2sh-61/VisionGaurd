"""Group-level splits never leak a video/subject across train/val/test."""

import pytest

from train.splits import check_disjoint, group_split, load_split, save_split


def groups(n_fall=20, n_normal=20):
    out = {f"fall{i}": True for i in range(n_fall)}
    out.update({f"adl{i}": False for i in range(n_normal)})
    return out


def test_split_is_a_disjoint_cover():
    g = groups()
    split = group_split(g, val_frac=0.2, test_frac=0.2, seed=1)
    all_assigned = split["train"] + split["val"] + split["test"]
    assert sorted(all_assigned) == sorted(g)
    assert len(all_assigned) == len(set(all_assigned))


def test_split_is_stratified_and_deterministic():
    g = groups()
    split = group_split(g, val_frac=0.2, test_frac=0.2, seed=3)
    for name in ("train", "val", "test"):
        assert any(g[x] for x in split[name]) and any(not g[x] for x in split[name])
    assert split == group_split(g, val_frac=0.2, test_frac=0.2, seed=3)
    assert split != group_split(g, val_frac=0.2, test_frac=0.2, seed=4)


def test_small_buckets_still_reach_every_split():
    split = group_split(groups(n_fall=3, n_normal=3), val_frac=0.1, test_frac=0.1)
    assert all(len(split[name]) == 2 for name in ("train", "val", "test"))


def test_windows_of_one_video_never_cross_splits():
    """All windows inherit their video's group, so membership is per video."""
    from train.prepare_data import build_windows
    from tests.synth import synthetic_caches

    caches = synthetic_caches()
    split = group_split({c["group_id"]: True for c in caches}, 0.25, 0.25, seed=0)
    seen = {}
    for name in ("train", "val", "test"):
        ws = build_windows([c for c in caches if c["group_id"] in set(split[name])])
        for v in set(ws.videos):
            assert seen.setdefault(v, name) == name


def test_overlap_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        check_disjoint({"train": ["a", "b"], "val": ["b"], "test": []})
    split = {"train": ["a"], "val": ["b"], "test": ["c"]}
    save_split(tmp_path / "s.json", split)
    assert load_split(tmp_path / "s.json") == split
    (tmp_path / "bad.json").write_text('{"train": ["a"], "val": ["a"], "test": []}')
    with pytest.raises(ValueError):
        load_split(tmp_path / "bad.json")


def test_bad_fractions():
    with pytest.raises(ValueError):
        group_split(groups(), val_frac=0.5, test_frac=0.5)
