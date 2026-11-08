"""Pick a detector's alert settings on validation videos.

Training optimizes per-window classification; whether a fall becomes an alert
also depends on settings this module chooses by replaying the validation
videos through the real detector:

1. (temporal model) ``fallen_threshold`` -- how confident the model must be
   before a track counts as FALLEN -- and ``min_visible_kps`` -- frames with
   fewer visible keypoints keep the previous prediction;
2. (any detector) the optional alert rules of detectors/events.py:
   ``falling_alert_s`` (a long fall that never looks "fallen") and
   ``lost_alert_s`` (the person vanishes mid-fall).

Each stage keeps the best event-level F1 (ties: fewer false alarms, then the
less strict / simpler setting). For the temporal model the result is stored
in the checkpoint, where the detector picks it up by default; train.py runs
this automatically. Nothing is written when the validation videos give no
evidence (no falls, or no setting detects any).

    python -m train.calibrate --checkpoint runs/cnn/best.pt --cache data/cache/le2i data/cache/urfd \
                              --split-file runs/split.json
"""

import argparse
import os
from pathlib import Path

import torch

from .evaluation import evaluate
from .prepare_data import find_caches, load_cache, persons_by_frame
from .splits import load_split

THRESHOLDS = (None, 0.6, 0.8)        # None = plain argmax
GATES = (0, 6)                       # min_visible_kps (0 = judge every frame)
FALLING_ALERT_S = (None, 1.0, 1.5)   # None = rule off
LOST_ALERT_S = (None, 0.5)


def _best(rows, n_active):
    """Highest F1, then fewest false alarms, then the simplest setting."""
    return max(rows, key=lambda r: (round(r[1]["f1"], 6), -r[1]["fp"], -n_active(r[0])))


def _no_evidence(rows):
    return not rows or rows[0][1]["falls"] == 0 or all(r["f1"] == 0 for _, r in rows)


def calibrate_alert_rules(make_detector, videos, falling=FALLING_ALERT_S, lost=LOST_ALERT_S):
    """make_detector(EmitterConfig) -> detector. Returns (best EmitterConfig or None, rows)."""
    from detectors.events import EmitterConfig

    rows = []
    for fa in falling:
        for la in lost:
            rows.append(((fa, la), evaluate(make_detector(EmitterConfig(falling_alert_s=fa, lost_alert_s=la)),
                                            videos)))
    if _no_evidence(rows):
        return None, rows
    (fa, la), _ = _best(rows, lambda s: (s[0] is not None) + (s[1] is not None))
    return EmitterConfig(falling_alert_s=fa, lost_alert_s=la), rows


def calibrate(checkpoint, caches, thresholds=THRESHOLDS, gates=GATES, device=None, write=True):
    """Calibrate a temporal-model checkpoint on ``caches``. Returns (best, rows) where best is
    None (no evidence; nothing written) or a dict of the chosen settings plus their result."""
    from detectors.temporal_model import TemporalModelDetector

    videos = [(c, persons_by_frame(c)) for c in caches]
    stage1 = []
    for t in thresholds:
        for g in gates:
            det = TemporalModelDetector(checkpoint=checkpoint, device=device, fallen_threshold=t,
                                        min_visible_kps=g, emitter_config=_default_emitter())
            stage1.append(((t, g), evaluate(det, videos)))
    if _no_evidence(stage1):
        print("calibration skipped: the validation videos contain no detectable falls; "
              "checkpoint left unchanged")
        return None, [(f"threshold={'argmax' if t_ is None else t_} gate={g_}", r) for (t_, g_), r in stage1]
    (t, g), _ = _best(stage1, lambda s: (s[0] or 0.0) + s[1] / 100)

    emitter, stage2 = calibrate_alert_rules(
        lambda cfg: TemporalModelDetector(checkpoint=checkpoint, device=device, fallen_threshold=t,
                                          min_visible_kps=g, emitter_config=cfg), videos)
    emitter = emitter or _default_emitter()
    result = dict(stage2)[(emitter.falling_alert_s, emitter.lost_alert_s)]
    best = {"fallen_threshold": None if t is None else float(t), "min_visible_kps": int(g),
            "emitter": emitter.to_dict(), "result": result}
    if write:
        path = Path(checkpoint)
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        ckpt.update(fallen_threshold=best["fallen_threshold"], min_visible_kps=best["min_visible_kps"],
                    emitter=best["emitter"])
        tmp = path.with_name(path.name + ".part")
        torch.save(ckpt, tmp)
        os.replace(tmp, path)
    labelled = ([(f"threshold={'argmax' if t_ is None else t_} gate={g_}", r) for (t_, g_), r in stage1]
                + [(f"long_fall={fa} lost_while_falling={la}", r) for (fa, la), r in stage2])
    return best, labelled


def _default_emitter():
    from detectors.events import EmitterConfig
    return EmitterConfig()


def format_rows(rows, best=None):
    lines = ["setting                                F1     precision  recall  false alarms"]
    for name, r in rows:
        lines.append(f"{name:<38} {r['f1']:.3f}   {r['precision']:.3f}     {r['recall']:.3f}   {r['fp']:4d}")
    if best:
        lines.append(f"chosen: threshold={best['fallen_threshold']} gate={best['min_visible_kps']} "
                     f"long_fall={best['emitter']['falling_alert_s']} "
                     f"lost_while_falling={best['emitter']['lost_alert_s']}  ->  F1 {best['result']['f1']:.3f}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--cache", nargs="+", required=True)
    ap.add_argument("--split-file", required=True)
    ap.add_argument("--split", default="val", choices=["train", "val", "test"])
    ap.add_argument("--device")
    args = ap.parse_args(argv)
    members = set(load_split(args.split_file)[args.split])
    caches = [c for c in map(load_cache, find_caches(args.cache)) if c["group_id"] in members]
    if not caches:
        raise SystemExit(f"no cached videos belong to the {args.split} split of {args.split_file}")
    best, rows = calibrate(args.checkpoint, caches, device=args.device)
    print(format_rows(rows, best))
    return best


if __name__ == "__main__":
    main()
