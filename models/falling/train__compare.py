"""Compare trained runs (and the rule-based baseline) and pick the model to deploy.

    python -m train.compare --runs runs/cnn runs/lstm runs/cnn_cctv runs/lstm_cctv \
        --cache data/cache/le2i data/cache/urfd --split-file runs/split.json \
        --negatives data/cache/cctv --install

Selection uses only data the models were not trained on and never the test
split: highest validation event-F1 (computed during calibration), then fewest
false alarms on the ``--negatives`` videos (fall-free footage from the target
cameras, e.g. store CCTV). Test-split results are reported for every candidate
so the choice can be sanity-checked. ``--install`` copies the winner to
checkpoints/temporal_model.pt, which the GUI and eval.py use by default.
"""

import argparse
import json
import shutil
from pathlib import Path

from detectors import create_detector
from detectors.rule_based import CALIBRATION as RULE_CALIBRATION
from detectors.temporal_model import DEFAULT_CHECKPOINT

from .calibrate import calibrate_alert_rules
from .evaluation import evaluate
from .prepare_data import find_caches, load_cache, persons_by_frame
from .splits import load_split


def load_videos(paths, groups=None):
    caches = [load_cache(p) for p in find_caches(paths)]
    if groups is not None:
        caches = [c for c in caches if c["group_id"] in groups]
    return [(c, persons_by_frame(c)) for c in caches]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, help="run folders containing best.pt + metrics.json")
    ap.add_argument("--cache", nargs="+", required=True)
    ap.add_argument("--split-file", required=True)
    ap.add_argument("--negatives", nargs="*", default=[], help="caches of fall-free target footage")
    ap.add_argument("--device")
    ap.add_argument("--install", action="store_true", help="copy the winner to " + str(DEFAULT_CHECKPOINT))
    ap.add_argument("--json", help="write the comparison here")
    args = ap.parse_args(argv)

    split = load_split(args.split_file)
    test = load_videos(args.cache, set(split["test"]))
    negatives = load_videos(args.negatives) if args.negatives else []
    # Same treatment as the learned models: the rule-based detector's alert rules
    # are calibrated on the validation videos too.
    val_videos = load_videos(args.cache, set(split["val"]))
    rule_cfg, _ = calibrate_alert_rules(lambda cfg: create_detector("rule_based", emitter_config=cfg),
                                        val_videos)
    rows = {}
    candidates = [("rule_based", None)] + [(Path(r).name, Path(r)) for r in args.runs]
    for name, run in candidates:
        if run is None:
            det = create_detector("rule_based", emitter_config=rule_cfg)
            val = {"emitter": det.emitter.config.to_dict()}
        else:
            det = create_detector("temporal_model", checkpoint=run / "best.pt", device=args.device)
            val = json.loads((run / "metrics.json").read_text())
            val.update(fallen_threshold=det.fallen_threshold, emitter=det.emitter.config.to_dict())
        val["val_event_f1"] = evaluate(det, val_videos)["f1"]   # with the current calibrated settings
        res = evaluate(det, test)
        neg = evaluate(det, negatives) if negatives else None
        rows[name] = {
            "run": str(run) if run else None,
            "arch": det.meta["arch"] if run else "rules",
            "threshold": val.get("fallen_threshold"),
            "alert_rules": {k: (val.get("emitter") or {}).get(k) for k in ("falling_alert_s", "lost_alert_s")},
            "val_event_f1": val.get("val_event_f1"),
            "val_frame_macro_f1": val.get("val_macro_f1"),
            "test_falls": res["falls"], "test_tp": res["tp"], "test_fp": res["fp"],
            "test_precision": res["precision"], "test_recall": res["recall"], "test_f1": res["f1"],
            "test_latency_s": res["latency_s"], "test_frame_macro_f1": res["frame_macro_f1"],
            "negatives_false_alarms": neg["fp"] if neg else None,
            "negatives_minutes": (sum(c["n_frames"] / c["fps"] for c, _ in negatives) / 60) if neg else None,
        }

    learned = [n for n, r in rows.items() if r["run"]]
    best = max(learned, key=lambda n: (round(rows[n]["val_event_f1"] or 0, 6),
                                       -(rows[n]["negatives_false_alarms"] or 0),
                                       rows[n]["val_frame_macro_f1"] or 0))

    cols = [("model", None), ("val event F1", "val_event_f1"), ("val frame F1", "val_frame_macro_f1"),
            ("threshold", "threshold"), ("test F1", "test_f1"), ("test P", "test_precision"),
            ("test R", "test_recall"), ("test FP", "test_fp"), ("test frame F1", "test_frame_macro_f1"),
            ("CCTV FP", "negatives_false_alarms")]
    print(f"\n{len(test)} test videos ({rows['rule_based']['test_falls']} falls)"
          + (f", {len(negatives)} fall-free target videos "
             f"({rows['rule_based']['negatives_minutes']:.1f} min)" if negatives else ""))
    print("".join(f"{t:>14}" for t, _ in cols))
    for name, r in rows.items():
        cells = [f"{name + (' *' if name == best else ''):>14}"]
        for _, key in cols[1:]:
            v = r[key]
            cells.append(f"{'-' if v is None else (f'{v:.3f}' if isinstance(v, float) else str(v)):>14}")
        print("".join(cells))
    print(f"\nselected: {best}  (highest validation event-F1, then fewest CCTV false alarms)")

    if args.install:
        DEFAULT_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(rows[best]["run"]) / "best.pt", DEFAULT_CHECKPOINT)
        print(f"installed {rows[best]['run']}/best.pt -> {DEFAULT_CHECKPOINT}")
        if rule_cfg is not None:   # the rule-based detector's calibrated alert rules
            RULE_CALIBRATION.write_text(json.dumps({"emitter": rule_cfg.to_dict(),
                                                    "split_file": str(args.split_file)}, indent=2))
            print(f"installed rule-based alert rules -> {RULE_CALIBRATION}")
    if args.json:
        Path(args.json).write_text(json.dumps({"selected": best, "models": rows}, indent=2))
    return best, rows


if __name__ == "__main__":
    main()
