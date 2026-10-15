"""Step 1 of training: run the pose estimator over a fall dataset once, cache
the results, and build normalized sliding windows from the cache.

    python -m train.prepare_data --dataset le2i --root D:/data/le2i --out data/cache/le2i
    python -m train.prepare_data --dataset urfd --root D:/data/urfd --out data/cache/urfd --opt cams=[0,1]

One ``.npz`` per video holds every detection (frame, track id, keypoints,
bbox) so eval.py can replay the exact same pose stream into every detector,
plus the per-frame labels and which detection is the annotated subject in each
frame. Windows are built from the cache at training time, so changing the
window length or stride never requires re-running pose estimation.
"""

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from core.boxes import box_iou
from core.features import FALLEN, FALLING, LABELS, MAX_GAP, UNKNOWN, WINDOW, sequence_windows
from core.keypoints import KP_CONF_MIN, NUM_KEYPOINTS
from core.pose import INFER_IMGSZ, PERSON_CONF, Person, default_pose_weights
from core.video import FrameSource

from .datasets import LOADERS, load_dataset

log = logging.getLogger(__name__)

CACHE_VERSION = 1
META_KEYS = ("dataset", "video_id", "group_id", "source", "settings")


# ------------------------------------------------------------------ subject --

def stitch_subject(det_frame, det_bbox, det_conf, n_frames, max_gap=MAX_GAP, min_iou=0.1):
    """Index of the annotated subject's detection in every frame (-1 if none).

    Dataset labels describe one person, but ByteTrack often switches ids during
    the fall itself, which would cut the labelled sequence exactly where it
    matters. So the subject is followed by box overlap with its previous box;
    if nothing overlaps the frame is skipped, and after more than ``max_gap``
    skipped frames the subject is re-acquired as the largest confident person.
    """
    subject = np.full(n_frames, -1, dtype=np.int64)
    by_frame = {}
    for i, f in enumerate(np.asarray(det_frame)):
        by_frame.setdefault(int(f), []).append(i)
    prev_box, prev_frame = None, None
    for f in range(n_frames):
        cands = by_frame.get(f)
        if not cands:
            continue
        if prev_box is not None and f - prev_frame - 1 <= max_gap:
            ious = [box_iou(prev_box, det_bbox[i]) for i in cands]
            best = int(np.argmax(ious))
            if ious[best] < min_iou:
                continue
            chosen = cands[best]
        else:
            scores = [(det_bbox[i][2] - det_bbox[i][0]) * (det_bbox[i][3] - det_bbox[i][1]) * det_conf[i]
                      for i in cands]
            chosen = cands[int(np.argmax(scores))]
        subject[f] = chosen
        prev_box, prev_frame = det_bbox[chosen], f
    return subject


# -------------------------------------------------------------------- cache --

def extraction_settings(pose_weights=None, conf=PERSON_CONF, imgsz=INFER_IMGSZ, max_frames=None):
    """Everything that changes the pose stream; caches made with other settings are redone."""
    return {"pose_weights": str(pose_weights or default_pose_weights()), "conf": conf,
            "imgsz": imgsz, "max_frames": max_frames}


def lazy_estimator(settings, device=None, estimator=None):
    """Callable returning one shared PoseEstimator, built on first use (loading
    YOLO is skipped entirely when every video is already cached)."""
    holder = [estimator]

    def get():
        if holder[0] is None:
            from core.pose import PoseEstimator
            holder[0] = PoseEstimator(settings["pose_weights"], conf=settings["conf"],
                                      imgsz=settings["imgsz"], device=device)
        return holder[0]
    return get


def extract_video(record, estimator, max_frames=None, settings=None):
    """Run ``estimator`` (callable frame -> list[Person], with ``reset()``) over
    one VideoRecord and return the cache dict."""
    source = FrameSource(record.source, fps=record.fps, crop=record.crop)
    estimator.reset()
    det_frame, det_track, det_kps, det_bbox, det_conf = [], [], [], [], []
    n_frames = 0
    for idx, frame in source:
        if max_frames is not None and idx >= max_frames:
            break
        for p in estimator(frame):
            det_frame.append(idx)
            det_track.append(-1 if p.track_id is None else p.track_id)
            det_kps.append(np.asarray(p.keypoints, dtype=np.float32))
            det_bbox.append(p.bbox)
            det_conf.append(p.conf)
        n_frames = idx + 1
    det_bbox = np.asarray(det_bbox, dtype=np.float32).reshape(-1, 4)
    det_conf = np.asarray(det_conf, dtype=np.float32)
    return {
        "cache_version": CACHE_VERSION,
        "dataset": record.dataset,
        "video_id": record.video_id,
        "group_id": record.group_id,
        "source": str(record.source),
        "settings": json.dumps(settings or {}, sort_keys=True),
        "fps": float(source.fps),
        "n_frames": n_frames,
        "frame_labels": record.labels_for(n_frames),
        "det_frame": np.asarray(det_frame, dtype=np.int32),
        "det_track": np.asarray(det_track, dtype=np.int32),
        "det_kps": np.asarray(det_kps, dtype=np.float32).reshape(-1, NUM_KEYPOINTS, 3),
        "det_bbox": det_bbox,
        "det_conf": det_conf,
        "subject_det": stitch_subject(det_frame, det_bbox, det_conf, n_frames).astype(np.int32),
    }


def cache_filename(video_id):
    return video_id.replace("/", "__").replace("\\", "__").replace(" ", "_") + ".npz"


def save_cache(path, cache):
    """Write atomically, so an interrupted run never leaves a truncated cache."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as f:
        np.savez_compressed(f, **{k: np.asarray(v) for k, v in cache.items()})
    os.replace(tmp, path)


def cached_extract(record, path, settings, get_estimator, overwrite=False):
    """The cache for ``record``: reused from ``path`` if it was made with the
    same pose settings, otherwise (missing, unreadable, stale, or
    ``overwrite``) extracted again and saved. Labels and group always come from
    ``record``, so loader options like frame_offset or group_by apply without
    re-running pose. ``path`` may be None (don't cache)."""
    if record.crop is not None:   # only then: crop-less caches stay valid
        settings = {**settings, "crop": record.crop}
    settings_json = json.dumps(settings, sort_keys=True)
    cache = None
    if path is not None and Path(path).exists() and not overwrite:
        try:
            cache = load_cache(path)
        except Exception as e:
            log.warning("re-extracting %s (%s)", Path(path).name, str(e))
        else:
            if cache["settings"] != settings_json:
                log.info("re-extracting %s (pose settings changed)", Path(path).name)
                cache = None
    if cache is None:
        cache = extract_video(record, get_estimator(), settings.get("max_frames"), settings)
        if path is not None:
            save_cache(path, cache)
    else:
        fresh = {"dataset": record.dataset, "video_id": record.video_id, "group_id": record.group_id,
                 "frame_labels": record.labels_for(cache["n_frames"])}
        changed = any(not np.array_equal(cache[k], v) for k, v in fresh.items())
        cache.update(fresh)
        if changed:   # train.py reads the file, so keep it in sync with the current loader
            save_cache(path, cache)
    return cache


def load_cache(path):
    # Own the file handle: if np.load fails on a corrupt file, its traceback
    # would otherwise keep the file open (and locked, on Windows).
    with open(path, "rb") as f, np.load(f, allow_pickle=False) as data:
        cache = {k: data[k] for k in data.files}
    for key in META_KEYS:
        cache[key] = str(cache[key])
    cache["fps"] = float(cache["fps"])
    cache["n_frames"] = int(cache["n_frames"])
    cache["cache_version"] = int(cache["cache_version"])
    if cache["cache_version"] != CACHE_VERSION:
        raise ValueError(f"{path}: cache version {cache['cache_version']} != {CACHE_VERSION}; "
                         "re-run prepare_data")
    return cache


def find_caches(paths):
    """Expand cache directories into their .npz files (missing paths are skipped with a warning)."""
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(p.glob("*.npz")))
        elif p.is_file():
            files.append(p)
        else:
            log.warning("cache path %s does not exist; skipping", p)
            print(f"warning: cache path {p} does not exist; skipping")
    return files


def persons_by_frame(cache):
    """Replay helper: list (one per frame) of the Persons detected in it."""
    frames = [[] for _ in range(cache["n_frames"])]
    for i, f in enumerate(cache["det_frame"]):
        tid = int(cache["det_track"][i])
        frames[int(f)].append(Person(track_id=None if tid < 0 else tid,
                                     bbox=tuple(float(v) for v in cache["det_bbox"][i]),
                                     conf=float(cache["det_conf"][i]),
                                     keypoints=cache["det_kps"][i]))
    return frames


def subject_sequence(cache):
    """(frames, keypoints) of the annotated subject on frames where the tracker had
    confirmed an id. The live detector ignores unconfirmed (track_id None)
    detections, so training must too or the warm-up windows would differ."""
    det = cache["subject_det"]
    frames = np.flatnonzero(det >= 0)
    frames = frames[cache["det_track"][det[frames]] >= 0]
    return frames, cache["det_kps"][det[frames]]


def has_fall(cache):
    return bool(np.isin(cache["frame_labels"], (FALLING, FALLEN)).any())


# ------------------------------------------------------------------ windows --

@dataclass
class WindowSet:
    x: np.ndarray        # (N, window, 17, 3) normalized
    y: np.ndarray        # (N,) label of each window's last frame
    groups: np.ndarray   # (N,) split group of the source video
    videos: np.ndarray   # (N,) video id
    end_frames: np.ndarray

    def __len__(self):
        return len(self.y)

    def class_counts(self):
        return np.bincount(self.y, minlength=len(LABELS))


def build_windows(caches, window=WINDOW, stride=1, max_gap=MAX_GAP, conf_min=KP_CONF_MIN,
                  min_frames=None):
    """Normalized sliding windows over the subject track of every cache."""
    xs, ys, groups, videos, ends = [], [], [], [], []
    for cache in caches:
        frames, kps = subject_sequence(cache)
        x, y, end = sequence_windows(frames, kps, cache["frame_labels"], window, stride,
                                     max_gap, conf_min, min_frames)
        xs.append(x)
        ys.append(y)
        ends.append(end)
        groups.append(np.full(len(y), cache["group_id"], dtype=object))
        videos.append(np.full(len(y), cache["video_id"], dtype=object))
    if not xs:
        return WindowSet(np.zeros((0, window, NUM_KEYPOINTS, 3), np.float32), np.zeros(0, np.int64),
                         np.zeros(0, object), np.zeros(0, object), np.zeros(0, np.int64))
    return WindowSet(np.concatenate(xs), np.concatenate(ys), np.concatenate(groups),
                     np.concatenate(videos), np.concatenate(ends))


# ---------------------------------------------------------------------- CLI --

def parse_options(pairs):
    """``["cams=[0,1]", "group_by=scene"]`` -> {"cams": [0, 1], "group_by": "scene"}."""
    out = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"--opt expects key=value, got {pair!r}")
        out[key.strip()] = yaml.safe_load(value)
    return out


def main(argv=None, estimator=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, choices=sorted(LOADERS))
    ap.add_argument("--root", required=True, help="dataset root folder")
    ap.add_argument("--out", required=True, help="cache folder for the .npz files")
    ap.add_argument("--opt", action="append", metavar="KEY=VALUE",
                    help="loader option, e.g. group_by=scene (le2i) or cams=[0,1] (urfd)")
    ap.add_argument("--pose-weights", help="YOLOv8-pose weights (default: see core.pose)")
    ap.add_argument("--device", help="e.g. 0 or cpu")
    ap.add_argument("--imgsz", type=int, default=INFER_IMGSZ)
    ap.add_argument("--conf", type=float, default=PERSON_CONF)
    ap.add_argument("--max-frames", type=int, help="only process the first N frames per video")
    ap.add_argument("--limit", type=int, help="only process the first N videos")
    ap.add_argument("--overwrite", action="store_true", help="re-extract videos already cached")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    records = load_dataset(args.dataset, args.root, **parse_options(args.opt))
    if args.limit:
        records = records[:args.limit]
    if not records:
        raise SystemExit(f"no annotated videos found under {args.root}")
    log.info("%d videos (%d with a fall)", len(records), sum(r.has_fall for r in records))

    settings = extraction_settings(args.pose_weights, args.conf, args.imgsz, args.max_frames)
    get_estimator = lazy_estimator(settings, args.device, estimator)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        from tqdm import tqdm
    except ImportError:
        def tqdm(it, **_):
            return it

    index, caches, failed = [], [], []
    for record in tqdm(records, desc="pose"):
        path = out / cache_filename(record.video_id)
        try:
            cache = cached_extract(record, path, settings, get_estimator, args.overwrite)
        except Exception as e:   # one unreadable video shouldn't stop the run
            log.error("failed on %s: %s", record.source, e)
            failed.append(record.video_id)
            continue
        caches.append(cache)
        index.append({"video_id": cache["video_id"], "group_id": cache["group_id"],
                      "file": path.name, "n_frames": cache["n_frames"], "fps": cache["fps"],
                      "has_fall": has_fall(cache),
                      "subject_frames": int((cache["subject_det"] >= 0).sum())})
    (out / "index.json").write_text(json.dumps(index, indent=2))

    windows = build_windows(caches)
    counts = windows.class_counts()
    print(f"\ncached {len(caches)} videos in {out}")
    print(f"{WINDOW}-frame windows (stride 1): " +
          ", ".join(f"{name}={n}" for name, n in zip(LABELS, counts)))
    unlabelled = sum(int((c["frame_labels"] == UNKNOWN).sum()) for c in caches)
    if unlabelled:
        print(f"{unlabelled} frames have no label and are not used for training")
    if failed:
        print(f"WARNING: {len(failed)} videos failed and are missing from the cache: {failed[:5]}")
    return index


if __name__ == "__main__":
    main()
