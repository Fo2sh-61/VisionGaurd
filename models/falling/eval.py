"""Compare fall detectors side by side on the same videos.

Pose estimation runs once per video and the identical detections are replayed
into every detector, so differences come from the detectors alone.

    # cached pose from train/prepare_data.py, restricted to the held-out test split
    python eval.py --cache data/cache/le2i --split-file runs/cnn/split.json --split test

    # straight from a dataset folder (runs pose; --save-cache to reuse it next time)
    python eval.py --dataset le2i --root D:/data/le2i --save-cache data/cache/le2i

Event level (per video, one annotated fall at most): the first alert in
[fall start - before_s, impact + after_s] is a true positive, alerts outside it
are false alarms, a fall without one is a miss. "Impact" is the first FALLEN
frame. Frame level: the subject's per-frame state vs. the labels.
"""

import argparse
import json
import logging
from pathlib import Path

from detectors import create_detector, detector_classes
from train.prepare_data import (
    cache_filename, cached_extract, extraction_settings, find_caches, lazy_estimator, load_cache,
    parse_options, persons_by_frame,
)
from train.splits import load_split
from train.evaluation import evaluate, ground_truth_fall, match_events, replay  # noqa: F401
from train.train import format_confusion, plain

log = logging.getLogger("eval")


ROWS = [
    ("videos", "videos", "{:d}"), ("falls", "falls", "{:d}"),
    ("true positives", "tp", "{:d}"), ("false alarms", "fp", "{:d}"), ("missed falls", "fn", "{:d}"),
    ("precision", "precision", "{:.3f}"), ("recall", "recall", "{:.3f}"), ("F1", "f1", "{:.3f}"),
    ("false alarms / min", "false_alarms_per_min", "{:.3f}"),
    ("mean latency after impact (s)", "latency_s", "{:+.2f}"),
    ("frame macro-F1 (subject)", "frame_macro_f1", "{:.3f}"),
    ("frame accuracy (subject)", "frame_accuracy", "{:.3f}"),
    ("frames with a prediction", "frame_coverage", "{:.1%}"),
    ("detector ms / frame", "ms_per_frame", "{:.2f}"),
]


def format_table(results):
    names = list(results)
    width = max(14, *(len(n) + 2 for n in names))
    lines = [f"{'metric':<32}" + "".join(f"{n:>{width}}" for n in names)]
    for title, key, fmt in ROWS:
        cells = []
        for n in names:
            v = results[n][key]
            cells.append(f"{'-' if v is None else fmt.format(v):>{width}}")
        lines.append(f"{title:<32}" + "".join(cells))
    return "\n".join(lines)


def load_videos(args):
    """[(cache, persons_by_frame)] from --cache or --dataset."""
    if args.cache:
        caches = [load_cache(p) for p in find_caches(args.cache)]
    else:
        from train.datasets import load_dataset

        records = load_dataset(args.dataset, args.root, **parse_options(args.opt))
        settings = extraction_settings(args.pose_weights)
        get_estimator = lazy_estimator(settings, args.device)
        caches = []
        for record in records:
            path = Path(args.save_cache) / cache_filename(record.video_id) if args.save_cache else None
            log.info("pose: %s", record.video_id)
            caches.append(cached_extract(record, path, settings, get_estimator))
    if args.split_file:
        members = set(load_split(args.split_file)[args.split])
        caches = [c for c in caches if c["group_id"] in members]
    if not caches:
        raise SystemExit("no videos to evaluate")
    return [(c, persons_by_frame(c)) for c in caches]


def build_detectors(names, checkpoint=None, device=None):
    classes = detector_classes()
    explicit = names is not None
    detectors = {}
    for name in names or classes:
        if name not in classes:
            raise SystemExit(f"unknown detector {name!r}; choose from {sorted(classes)}")
        kwargs = {}
        if name == "temporal_model":
            kwargs = {"checkpoint": checkpoint, "device": device}
            if not explicit and checkpoint is None and classes[name].unavailable_reason():
                print(f"skipping {name}: {classes[name].unavailable_reason()}")
                continue
        detectors[name] = create_detector(name, **kwargs)
    return detectors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--cache", nargs="+", help="cache folders / .npz files from prepare_data.py")
    src.add_argument("--dataset", help="dataset loader name (le2i, urfd, manifest, ...)")
    ap.add_argument("--root", help="dataset root (with --dataset)")
    ap.add_argument("--opt", action="append", metavar="KEY=VALUE", help="dataset loader option")
    ap.add_argument("--save-cache", help="with --dataset: store/reuse pose caches here")
    ap.add_argument("--pose-weights")
    ap.add_argument("--split-file", help="split.json written by train.py")
    ap.add_argument("--split", choices=["train", "val", "test"],
                    help="which split of --split-file to evaluate (default test)")
    ap.add_argument("--detectors", nargs="+", help="default: every registered detector")
    ap.add_argument("--checkpoint", help="temporal model checkpoint (default: newest)")
    ap.add_argument("--device", help="torch device for pose and the temporal model")
    ap.add_argument("--before-s", type=float, default=1.0, help="alert window start before the fall")
    ap.add_argument("--after-s", type=float, default=3.0, help="alert window end after impact")
    ap.add_argument("--per-video", action="store_true", help="print each video's result")
    ap.add_argument("--json", help="write all results to this file")
    args = ap.parse_args(argv)
    if args.dataset and not args.root:
        ap.error("--dataset needs --root")
    if args.split and not args.split_file:
        ap.error("--split needs --split-file (the split.json written by train.py)")
    args.split = args.split or "test"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    videos = load_videos(args)
    detectors = build_detectors(args.detectors, args.checkpoint, args.device)
    if not detectors:
        raise SystemExit("no detectors to evaluate")
    results = {name: evaluate(det, videos, args.before_s, args.after_s) for name, det in detectors.items()}

    print(f"\n{len(videos)} videos " + (f"({args.split} split of {args.split_file})" if args.split_file
                                         else "(ALL videos: no --split-file, may include training data)"))
    print(format_table(results))
    for name, res in results.items():
        print(f"\n[{name}] frame level, subject track\n" + format_confusion(res["confusion"]))
        if args.per_video:
            for v in res["per_video"]:
                print(f"  {v['video_id']:<50} fall={v['fall']} alerts={v['events']} "
                      f"tp={v['tp']} fp={v['fp']} fn={v['fn']}")
    if args.json:
        Path(args.json).write_text(json.dumps(plain(results), indent=2))
    return results


if __name__ == "__main__":
    main()
