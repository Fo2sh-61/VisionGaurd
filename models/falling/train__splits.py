"""Train/val/test splits by group (video or subject), never by frame or window.

Overlapping windows from one video are near-duplicates, so splitting windows
(or frames) would leak the validation set into training. Every group lands in
exactly one split, and fall / no-fall groups are split separately so each
split gets its share of falls.
"""

import json
from pathlib import Path

import numpy as np

SPLITS = ("train", "val", "test")


def group_split(group_has_fall, val_frac=0.15, test_frac=0.15, seed=0):
    """``{group: has_fall}`` -> ``{"train": [...], "val": [...], "test": [...]}``."""
    if val_frac < 0 or test_frac < 0 or val_frac + test_frac >= 1:
        raise ValueError("need 0 <= val_frac, test_frac and val_frac + test_frac < 1")
    rng = np.random.default_rng(seed)
    split = {name: [] for name in SPLITS}
    for bucket in (True, False):
        groups = sorted(g for g, fall in group_has_fall.items() if bool(fall) == bucket)
        rng.shuffle(groups)
        n = len(groups)
        n_test = int(round(n * test_frac))
        n_val = int(round(n * val_frac))
        # With at least 3 groups, every requested split gets at least one.
        if n >= 3:
            n_test = max(n_test, 1 if test_frac > 0 else 0)
            n_val = max(n_val, 1 if val_frac > 0 else 0)
        n_test = min(n_test, n)
        n_val = min(n_val, n - n_test)
        split["test"] += groups[:n_test]
        split["val"] += groups[n_test:n_test + n_val]
        split["train"] += groups[n_test + n_val:]
    for name in SPLITS:
        split[name].sort()
    check_disjoint(split)
    return split


def check_disjoint(split):
    seen = {}
    for name in SPLITS:
        for group in split.get(name, []):
            if group in seen:
                raise ValueError(f"group {group!r} is in both {seen[group]} and {name}")
            seen[group] = name


def save_split(path, split):
    check_disjoint(split)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({name: sorted(split.get(name, [])) for name in SPLITS}, indent=2))


def load_split(path):
    split = json.loads(Path(path).read_text())
    split = {name: list(split.get(name, [])) for name in SPLITS}
    check_disjoint(split)
    return split
