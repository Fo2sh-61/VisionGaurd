"""Train the temporal fall classifier on cached pose windows.

    python -m train.train --config configs/cnn.yaml
    python -m train.train --config configs/cnn.yaml --arch lstm --out runs/lstm

* Videos are split by group (train/splits.py); the split is saved next to the
  checkpoint and reused on later runs and by eval.py.
* Cross-entropy is weighted by inverse class frequency (falls are rare).
* Early stopping on validation macro-F1; the best epoch is saved as best.pt.
* The validation (and test, if any) confusion matrix is printed at the end.
"""

import argparse
import copy
import json
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from torch import nn

from core.features import FEATURE_VERSION, LABELS, flip_windows, normalize_windows, to_model_input
from core.keypoints import KP_CONF_MIN, KP_L_ANKLE, KP_L_KNEE, KP_R_ANKLE, KP_R_KNEE

from .model import build_model, save_checkpoint
from .prepare_data import build_windows, find_caches, has_fall, load_cache
from .splits import SPLITS, group_split, load_split, save_split

DEFAULT_CONFIG = {
    "data": {
        "caches": ["data/cache"],   # cache folders or .npz files from prepare_data.py
        "window": 30,
        "stride": 2,                # training windows
        "eval_stride": 1,           # validation/test windows
        "max_gap": 5,
        "min_frames": 10,           # warm-up: predict from 10 frames on (window left-padded)
        "conf_min": 0.30,
    },
    "split": {
        "file": None,               # default: <out>/split.json (created if missing)
        "val_frac": 0.15,
        "test_frac": 0.15,
        "seed": 0,
    },
    "model": {
        "arch": "cnn",              # cnn | lstm
        "cnn": {"channels": 64, "num_layers": 3, "kernel_size": 5, "dropout": 0.2},
        "lstm": {"hidden": 64, "num_layers": 2, "dropout": 0.2},
    },
    "train": {
        "epochs": 100,
        "batch_size": 256,
        "lr": 1.0e-3,
        "weight_decay": 1.0e-4,
        "patience": 10,             # epochs without val macro-F1 improvement
        "class_weighting": "inverse",   # inverse | sqrt_inverse | none
        "grad_clip": 1.0,
        "device": "auto",
        "seed": 0,
        "augment": {"flip_p": 0.5, "scale": [0.9, 1.1], "jitter_std": 0.02, "kp_dropout": 0.05,
                    # viewpoint augmentation for CCTV-style cameras (see augment())
                    "rotate_deg": 0.0, "squash": [1.0, 1.0], "shear": 0.0, "occlude_lower_p": 0.0},
        "calibrate": True,          # pick the alert threshold on the val videos (train/calibrate.py)
    },
    "out": "runs/cnn",
}


# ------------------------------------------------------------------- config --

def deep_merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def coerce_config(cfg, defaults=DEFAULT_CONFIG, where=""):
    """Cast values to the type of their default, in place. YAML reads `1e-3`
    (no dot) as a string, and a single cache folder may be given as a scalar."""
    for key, default in defaults.items():
        if key not in cfg or cfg[key] is None:
            continue
        value, name = cfg[key], f"{where}{key}"
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ValueError(f"config {name}: expected a mapping, got {value!r}")
            coerce_config(value, default, name + ".")
        elif isinstance(default, list) and isinstance(value, str):
            cfg[key] = [value]
        elif (isinstance(default, list) and isinstance(value, list) and default
              and all(isinstance(d, (int, float)) for d in default)):
            try:
                cfg[key] = [float(v) for v in value]
            except (TypeError, ValueError):
                raise ValueError(f"config {name}: expected numbers, got {value!r}") from None
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            try:
                cfg[key] = type(default)(value) if isinstance(value, str) else value
            except ValueError:
                raise ValueError(f"config {name}: expected a number, got {value!r}") from None
            if isinstance(default, int) and isinstance(cfg[key], float) and cfg[key].is_integer():
                cfg[key] = int(cfg[key])
    return cfg


def validate_augment(aug):
    """Fail at startup (not at the first batch) on bad augmentation settings."""
    known = set(DEFAULT_CONFIG["train"]["augment"])
    unknown = set(aug) - known
    if unknown:
        raise ValueError(f"config train.augment: unknown keys {sorted(unknown)}; known: {sorted(known)}")
    for key in ("scale", "squash"):
        lo_hi = aug.get(key, [1.0, 1.0])
        if len(lo_hi) != 2 or not 0 < lo_hi[0] <= lo_hi[1]:
            raise ValueError(f"config train.augment.{key}: expected [low, high] with 0 < low <= high")
    for key in ("rotate_deg", "shear", "jitter_std"):
        if aug.get(key, 0) < 0:
            raise ValueError(f"config train.augment.{key} must be >= 0")
    for key in ("flip_p", "kp_dropout", "occlude_lower_p"):
        if not 0 <= aug.get(key, 0) <= 1:
            raise ValueError(f"config train.augment.{key} must be in [0, 1]")


def load_config(path=None, overrides=None):
    user = yaml.safe_load(Path(path).read_text()) if path else {}
    cfg = coerce_config(deep_merge(deep_merge(DEFAULT_CONFIG, user or {}), overrides))
    if cfg["train"].get("augment"):
        validate_augment(cfg["train"]["augment"])
    return cfg


def plain(obj):
    """numpy -> plain Python, so checkpoints load with torch weights_only=True."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return plain(obj.tolist())
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


# ------------------------------------------------------------------ metrics --

def confusion_matrix(y_true, y_pred, n_classes=len(LABELS)):
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    np.add.at(cm, (np.asarray(y_true), np.asarray(y_pred)), 1)
    return cm


def classification_report(cm):
    """Per-class precision/recall/F1 and macro-F1 over classes that occur."""
    tp = np.diag(cm).astype(float)
    support = cm.sum(axis=1)
    predicted = cm.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.where(predicted > 0, tp / predicted, 0.0)
        recall = np.where(support > 0, tp / support, 0.0)
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), 0.0)
    present = (support > 0) | (predicted > 0)
    return {
        "precision": precision, "recall": recall, "f1": f1, "support": support,
        "macro_f1": float(f1[present].mean()) if present.any() else 0.0,
        "accuracy": float(tp.sum() / cm.sum()) if cm.sum() else 0.0,
    }


def format_confusion(cm, labels=LABELS):
    rep = classification_report(cm)
    width = max(9, max(len(l) for l in labels) + 2)
    lines = ["confusion matrix (rows = true, columns = predicted)",
             " " * width + "".join(f"{l:>{width}}" for l in labels)]
    for name, row in zip(labels, cm):
        lines.append(f"{name:<{width}}" + "".join(f"{v:>{width}d}" for v in row))
    for i, name in enumerate(labels):
        lines.append(f"  {name:<8} precision {rep['precision'][i]:.3f}  recall {rep['recall'][i]:.3f}"
                     f"  F1 {rep['f1'][i]:.3f}  (n={rep['support'][i]})")
    lines.append(f"  macro F1 {rep['macro_f1']:.3f}   accuracy {rep['accuracy']:.3f}")
    return "\n".join(lines)


def class_weights(counts, mode="inverse"):
    """Loss weights from training class counts, normalized to mean 1 over the
    classes present. Absent classes get weight 0 (they never occur as targets)."""
    counts = np.asarray(counts, dtype=float)
    present = counts > 0
    w = np.zeros_like(counts)
    if mode == "none":
        w[present] = 1.0
    elif mode in ("inverse", "sqrt_inverse"):
        w[present] = counts[present].sum() / (present.sum() * counts[present])
        if mode == "sqrt_inverse":
            w[present] = np.sqrt(w[present])
    else:
        raise ValueError(f"unknown class_weighting {mode!r}")
    if present.any():
        w[present] /= w[present].mean()
    return w


# ------------------------------------------------------------- augmentation --

LOWER_BODY = [KP_L_KNEE, KP_R_KNEE, KP_L_ANKLE, KP_R_ANKLE]


def augment(x, rng, cfg, conf_min=KP_CONF_MIN):
    """Augment a batch of normalized windows (N, T, 17, 3); returns a copy.

    Viewpoint augmentation (CCTV cameras look down at people, often through
    wide-angle lenses, and counters/furniture hide legs): per window a random
    rotation (``rotate_deg``), vertical squash (``squash`` y-scale range) and
    shear (``shear``), and with probability ``occlude_lower_p`` the knees and
    ankles are hidden. The window is then normalized again, exactly as the
    detector would normalize such a view. Then light noise: ``scale``,
    ``jitter_std`` and per-keypoint ``kp_dropout``.
    """
    x = np.array(x, dtype=np.float32, copy=True)
    if not cfg:
        return x
    n = len(x)
    flip = rng.random(n) < cfg.get("flip_p", 0.0)
    if flip.any():
        x[flip] = flip_windows(x[flip])

    rot = np.radians(cfg.get("rotate_deg", 0.0))
    sq_lo, sq_hi = cfg.get("squash", [1.0, 1.0])
    shear = cfg.get("shear", 0.0)
    occlude_p = cfg.get("occlude_lower_p", 0.0)
    if rot > 0 or (sq_lo, sq_hi) != (1.0, 1.0) or shear > 0 or occlude_p > 0:
        theta = rng.uniform(-rot, rot, n)
        sy = rng.uniform(sq_lo, sq_hi, n)
        sh = rng.uniform(-shear, shear, n)
        c, s_ = np.cos(theta), np.sin(theta)
        # M = R(theta) @ [[1, sh], [0, sy]]
        m = np.stack([np.stack([c, c * sh - s_ * sy], -1), np.stack([s_, s_ * sh + c * sy], -1)], 1)
        x[..., :2] = np.einsum("nij,ntkj->ntki", m.astype(np.float32), x[..., :2])
        hide = rng.random(n) < occlude_p
        if hide.any():
            x[np.ix_(hide, np.arange(x.shape[1]), LOWER_BODY)] = 0.0
        x[x[..., 2] <= 0] = 0.0
        x = normalize_windows(x, conf_min)

    vis = x[..., 2] > 0
    lo, hi = cfg.get("scale", [1.0, 1.0])
    if (lo, hi) != (1.0, 1.0):
        x[..., :2] *= rng.uniform(lo, hi, size=(n, 1, 1, 1)).astype(np.float32)
    std = cfg.get("jitter_std", 0.0)
    if std > 0:
        x[..., :2] += (rng.normal(0, std, size=x[..., :2].shape) * vis[..., None]).astype(np.float32)
    p = cfg.get("kp_dropout", 0.0)
    if p > 0:
        x[(rng.random(vis.shape) < p) & vis] = 0.0
    return x


# --------------------------------------------------------------------- loop --

def resolve_device(name):
    if name in (None, "auto"):
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


@torch.no_grad()
def predict(model, x, device, batch_size=1024):
    """(logits (N, C) on CPU) for normalized windows x (N, T, 17, 3)."""
    model.eval()
    out = []
    for i in range(0, len(x), batch_size):
        xb = torch.from_numpy(to_model_input(x[i:i + batch_size])).to(device)
        out.append(model(xb).float().cpu())
    return torch.cat(out) if out else torch.zeros(0, len(LABELS))


def evaluate(model, windows, device, loss_fn, batch_size=1024):
    logits = predict(model, windows.x, device, batch_size)
    y = torch.from_numpy(windows.y)
    loss = float(loss_fn(logits, y)) if len(y) else float("nan")
    cm = confusion_matrix(windows.y, logits.argmax(1).numpy())
    return loss, cm


def make_split(cfg, caches, out_dir):
    split_path = Path(cfg["split"]["file"] or out_dir / "split.json")
    groups = {}
    for c in caches:
        groups[c["group_id"]] = groups.get(c["group_id"], False) or has_fall(c)
    if split_path.exists():
        split = load_split(split_path)
        known = {g for name in SPLITS for g in split[name]}
        unknown = sorted(set(groups) - known)
        if unknown:
            print(f"warning: {len(unknown)} groups are not in {split_path} and are ignored "
                  f"(delete the file to re-split): {unknown[:5]}")
        print(f"using split {split_path}")
    else:
        split = group_split(groups, cfg["split"]["val_frac"], cfg["split"]["test_frac"],
                            cfg["split"]["seed"])
        save_split(split_path, split)
        print(f"wrote split {split_path}")
    if split_path.resolve() != (out_dir / "split.json").resolve():
        save_split(out_dir / "split.json", split)
    return split


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="YAML config (see DEFAULT_CONFIG for every key)")
    ap.add_argument("--arch", choices=["cnn", "lstm"], help="override model.arch")
    ap.add_argument("--cache", action="append", help="override data.caches (repeatable)")
    ap.add_argument("--out", help="override the output folder")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--device", help="cuda, cpu, cuda:1 ... (default auto)")
    args = ap.parse_args(argv)

    overrides = {"model": {}, "train": {}, "data": {}}
    if args.arch:
        overrides["model"]["arch"] = args.arch
        base = load_config(args.config)
        if args.arch != base["model"]["arch"] and not args.out:
            # Don't let `--arch lstm` overwrite the config's (cnn) run: runs/cnn -> runs/lstm.
            out = Path(base["out"])
            overrides["out"] = str(out.with_name(args.arch if out.name == base["model"]["arch"]
                                                 else f"{out.name}_{args.arch}"))
    if args.cache:
        overrides["data"]["caches"] = args.cache
    if args.out:
        overrides["out"] = args.out
    if args.epochs:
        overrides["train"]["epochs"] = args.epochs
    if args.device:
        overrides["train"]["device"] = args.device
    cfg = load_config(args.config, overrides)
    dcfg, tcfg, arch = cfg["data"], cfg["train"], cfg["model"]["arch"]

    out_dir = Path(cfg["out"])
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"output: {out_dir}")
    (out_dir / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    rng = np.random.default_rng(tcfg["seed"])
    torch.manual_seed(tcfg["seed"])
    device = resolve_device(tcfg["device"])

    cache_files = find_caches(dcfg["caches"])
    if not cache_files:
        raise SystemExit(f"no caches found in {dcfg['caches']}; run train/prepare_data.py first")
    caches = [load_cache(p) for p in cache_files]
    split = make_split(cfg, caches, out_dir)

    sets = {}
    for name in SPLITS:
        members = set(split[name])
        stride = dcfg["stride"] if name == "train" else dcfg["eval_stride"]
        sets[name] = build_windows([c for c in caches if c["group_id"] in members],
                                   dcfg["window"], stride, dcfg["max_gap"], dcfg["conf_min"],
                                   dcfg["min_frames"])
        counts = sets[name].class_counts()
        print(f"{name:<5} {len(members):4d} groups  {len(sets[name]):7d} windows  " +
              "  ".join(f"{l}={n}" for l, n in zip(LABELS, counts)))
    train_set, val_set, test_set = sets["train"], sets["val"], sets["test"]
    if not len(train_set) or not len(val_set):
        raise SystemExit("train and val splits both need windows; add data or change split fractions")

    weights = class_weights(train_set.class_counts(), tcfg["class_weighting"])
    print("class weights: " + "  ".join(f"{l}={w:.2f}" for l, w in zip(LABELS, weights)))
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32))
    model_kwargs = dict(cfg["model"][arch])
    model = build_model(arch, **model_kwargs).to(device)
    loss_fn = loss_fn.to(device)
    cpu_loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32))
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=tcfg["weight_decay"])
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode="max", factor=0.5,
                                                       patience=max(1, tcfg["patience"] // 3))
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model {arch}: {n_params:,} parameters on {device}")

    best = {"f1": -1.0, "loss": float("inf"), "epoch": 0, "state": None}
    ckpt_path = out_dir / "best.pt"
    bad_epochs = 0
    for epoch in range(1, tcfg["epochs"] + 1):
        t0 = time.time()
        model.train()
        perm = rng.permutation(len(train_set))
        total, seen = 0.0, 0
        for i in range(0, len(perm), tcfg["batch_size"]):
            idx = perm[i:i + tcfg["batch_size"]]
            xb = augment(train_set.x[idx], rng, tcfg.get("augment"), dcfg["conf_min"])
            xb = torch.from_numpy(to_model_input(xb)).to(device)
            yb = torch.from_numpy(train_set.y[idx]).to(device)
            loss = loss_fn(model(xb), yb)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            if tcfg.get("grad_clip"):
                nn.utils.clip_grad_norm_(model.parameters(), tcfg["grad_clip"])
            opt.step()
            total += loss.item() * len(idx)
            seen += len(idx)

        val_loss, val_cm = evaluate(model, val_set, device, cpu_loss_fn)
        val_f1 = classification_report(val_cm)["macro_f1"]
        sched.step(val_f1)
        improved = val_f1 > best["f1"] + 1e-4 or (abs(val_f1 - best["f1"]) <= 1e-4 and val_loss < best["loss"])
        if improved:
            best.update(f1=val_f1, loss=val_loss, epoch=epoch,
                        state={k: v.detach().cpu().clone() for k, v in model.state_dict().items()})
            bad_epochs = 0
            save_checkpoint(ckpt_path, model, arch, model_kwargs, plain({
                "epoch": epoch, "window": dcfg["window"], "max_gap": dcfg["max_gap"],
                "min_frames": (dcfg["window"] if dcfg["min_frames"] is None
                               else min(max(int(dcfg["min_frames"]), 1), dcfg["window"])),
                "conf_min": dcfg["conf_min"], "val_macro_f1": val_f1, "val_loss": val_loss,
                "val_confusion": val_cm, "train_class_counts": train_set.class_counts(),
                "class_weights": weights, "config": cfg,
            }))
        else:
            bad_epochs += 1
        print(f"epoch {epoch:3d}  train_loss {total / max(seen, 1):.4f}  val_loss {val_loss:.4f}  "
              f"val_macro_f1 {val_f1:.4f}  {time.time() - t0:.1f}s{'  *' if improved else ''}")
        if bad_epochs >= tcfg["patience"]:
            print(f"early stopping: no val macro-F1 improvement for {bad_epochs} epochs")
            break

    model.load_state_dict(best["state"])
    print(f"\nbest epoch {best['epoch']}  ->  {ckpt_path}")
    _, val_cm = evaluate(model, val_set, device, cpu_loss_fn)
    print("\n[validation]\n" + format_confusion(val_cm))
    summary = {"checkpoint": str(ckpt_path), "best_epoch": best["epoch"],
               "val_macro_f1": classification_report(val_cm)["macro_f1"],
               "val_confusion": val_cm, "feature_version": FEATURE_VERSION}
    if len(test_set):
        _, test_cm = evaluate(model, test_set, device, cpu_loss_fn)
        print("\n[test]\n" + format_confusion(test_cm))
        summary.update(test_macro_f1=classification_report(test_cm)["macro_f1"],
                       test_confusion=test_cm)
    if tcfg.get("calibrate"):
        from .calibrate import calibrate, format_rows   # lazy: calibrate imports this module

        val_caches = [c for c in caches if c["group_id"] in set(split["val"])]
        best, rows = calibrate(ckpt_path, val_caches, device=str(device))
        print("\n[alert settings on validation videos]\n" + format_rows(rows, best))
        if best is not None:
            chosen = best["result"]
            summary.update(fallen_threshold=best["fallen_threshold"], min_visible_kps=best["min_visible_kps"],
                           emitter=best["emitter"], val_event_f1=chosen["f1"],
                           val_event_precision=chosen["precision"], val_event_recall=chosen["recall"],
                           val_false_alarms=chosen["fp"], val_falls=chosen["falls"])
    (out_dir / "metrics.json").write_text(json.dumps(plain(summary), indent=2))
    return summary


if __name__ == "__main__":
    main()
