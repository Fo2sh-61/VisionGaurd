"""Dataset loaders: turn a dataset folder into VideoRecords (video source +
per-frame normal/falling/fallen labels + the group used for splitting).

Loaders are pluggable: decorate a function ``(root: Path, **options) ->
list[VideoRecord]`` with ``@register_loader("name")`` and it becomes available
as ``--dataset name`` in prepare_data.py and eval.py. Built in:

* ``le2i``      Le2i / ImViA fall dataset
* ``urfd``      UR Fall Detection dataset (University of Rzeszow)
* ``manifest``  any dataset described by a small CSV (see ``load_manifest``)

All frame numbers inside a VideoRecord are 0-based.
"""

import csv
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN
from core.video import VIDEO_EXTS

log = logging.getLogger(__name__)

TO_END = sys.maxsize    # segment end meaning "until the last frame"


@dataclass
class VideoRecord:
    dataset: str
    video_id: str                     # unique across datasets, e.g. "le2i/Home_01/video (3)"
    group_id: str                     # videos sharing a group always land in the same split
    source: Path                      # video file or image-sequence folder
    segments: list = field(default_factory=list)   # [(first, last, label)] inclusive, 0-based
    default_label: int = UNKNOWN      # label of frames no segment covers
    fps: float | None = None          # override when the container lies or has none
    crop: object = None               # passed to FrameSource, e.g. "right_half"

    def labels_for(self, n_frames):
        labels = np.full(n_frames, self.default_label, dtype=np.int8)
        for first, last, label in self.segments:
            labels[max(first, 0):min(last, n_frames - 1) + 1] = label
        return labels

    @property
    def has_fall(self):
        return any(label in (FALLING, FALLEN) for _, _, label in self.segments)


def fall_segments(start, end):
    """Segments for one fall: NORMAL before ``start``, FALLING from ``start`` to
    ``end`` (inclusive), FALLEN afterwards. 0-based frames."""
    segments = [(start, end, FALLING), (end + 1, TO_END, FALLEN)]
    if start > 0:
        segments.insert(0, (0, start - 1, NORMAL))
    return segments


def runs_to_segments(frame_labels):
    """{frame: label} -> run-length segments [(first, last, label)]."""
    segments = []
    for frame in sorted(frame_labels):
        label = frame_labels[frame]
        if segments and segments[-1][2] == label and segments[-1][1] == frame - 1:
            segments[-1] = (segments[-1][0], frame, label)
        else:
            segments.append((frame, frame, label))
    return segments


# ---------------------------------------------------------------- registry --

LOADERS = {}


def register_loader(name):
    def deco(fn):
        LOADERS[name] = fn
        return fn
    return deco


def load_dataset(name, root, **options):
    try:
        loader = LOADERS[name]
    except KeyError:
        raise ValueError(f"unknown dataset {name!r}; choose from {sorted(LOADERS)}") from None
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"dataset root not found: {root}")
    records = loader(root, **options)
    ids = [r.video_id for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name}: duplicate video ids")
    return records


# -------------------------------------------------------------------- Le2i --

def parse_le2i_annotation(path):
    """Fall interval from a Le2i annotation file, or None if it has none.

    The first two lines hold the fall's start and end frame (1-based; "0" and
    "0" when the video has no fall); bounding-box rows follow.
    Returns (start, end) as written in the file, or None if the header is missing.
    """
    lines = [ln.strip() for ln in Path(path).read_text(errors="replace").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    try:
        return int(lines[0]), int(lines[1])
    except ValueError:
        return None


def _find_le2i_annotation(scene_dir, stem):
    for ann_dir in scene_dir.iterdir():
        if ann_dir.is_dir() and ann_dir.name.lower().startswith("annotation"):
            for candidate in ann_dir.iterdir():
                if candidate.suffix.lower() == ".txt" and candidate.stem.lower() == stem.lower():
                    return candidate
    return None


@register_loader("le2i")
def load_le2i(root, group_by="video", frame_offset=1):
    """Le2i layout: ``<scene>/Videos/<name>.avi`` with
    ``<scene>/Annotation_files/<name>.txt`` (also accepts ``Annotations_files``
    and the doubly nested ``Coffee_room_01/Coffee_room_01/...`` layout).

    Le2i has no subject ids, so the split group is the video by default;
    ``group_by="scene"`` keeps whole scenes (same room and actors) together
    for a stricter split. Videos without a usable annotation are skipped.
    """
    if group_by not in ("video", "scene"):
        raise ValueError("group_by must be 'video' or 'scene'")
    records = []
    videos = sorted(p for p in root.rglob("*")
                    if p.suffix.lower() in VIDEO_EXTS and p.parent.name.lower() == "videos")
    for video in videos:
        scene_dir = video.parent.parent
        ann = _find_le2i_annotation(scene_dir, video.stem)
        interval = parse_le2i_annotation(ann) if ann else None
        if interval is None:
            log.warning("le2i: skipping %s (no fall annotation found)", video)
            continue
        start, end = interval
        if start <= 0 and end <= 0:
            segments = [(0, TO_END, NORMAL)]
        else:
            if end < start:
                log.warning("le2i: skipping %s (fall end %d < start %d)", video, end, start)
                continue
            segments = fall_segments(start - frame_offset, end - frame_offset)
        video_id = f"le2i/{scene_dir.name}/{video.stem}"
        group_id = video_id if group_by == "video" else f"le2i/{scene_dir.name}"
        records.append(VideoRecord("le2i", video_id, group_id, video, segments))
    return records


# -------------------------------------------------------------------- URFD --

URFD_NAME = re.compile(r"^(fall|adl)-(\d+)-cam(\d)(-rgb)?$", re.IGNORECASE)
URFD_SEQ = re.compile(r"(fall|adl)-(\d+)", re.IGNORECASE)
# urfall-cam0-*.csv labels: -1 = not lying, 0 = temporary (falling), 1 = lying on the ground
URFD_LABELS = {-1: NORMAL, 0: FALLING, 1: FALLEN}


def parse_urfd_csv(path):
    """{("fall", 1): {frame0: label}} from a urfall-cam0-*.csv file
    (columns: sequence, 1-based frame, label, features...)."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            m = URFD_SEQ.search(row[0])
            if not m:
                continue   # header or junk
            try:
                frame, label = int(float(row[1])), int(float(row[2]))
            except ValueError:
                continue
            if label not in URFD_LABELS:
                continue
            key = (m.group(1).lower(), int(m.group(2)))
            out.setdefault(key, {})[frame - 1] = URFD_LABELS[label]
    return out


@register_loader("urfd")
def load_urfd(root, cams=(0,), video_crop="right_half"):
    """UR Fall layout: ``fall-NN-camC-rgb/`` PNG folders (preferred) or
    ``fall-NN-camC.mp4`` videos, ``adl-NN-...`` likewise, plus
    ``urfall-cam0-falls.csv`` with per-frame labels.

    * The .mp4 files show depth (left) and RGB (right) side by side, one frame
      per labelled frame; ``video_crop`` keeps the RGB half for pose estimation.
    * ADL sequences are all NORMAL (lying on a bed/sofa is not a fall).
    * Fall sequences are labelled from the CSV; frames it doesn't cover are UNKNOWN.
    * cam1 recordings show the same fall as cam0, so both share the group
      ``urfd/fall-NN`` and can never be split apart. cam1 frames reuse the cam0
      labels (the dataset only annotates cam0), so cam1 is opt-in via ``cams``.
    """
    cams = {int(c) for c in cams}
    labels = {}
    for csv_path in sorted(root.rglob("urfall-cam0-*.csv")):
        labels.update(parse_urfd_csv(csv_path))

    sources = {}
    for path in sorted(root.rglob("*")):
        is_video = path.is_file() and path.suffix.lower() in VIDEO_EXTS
        name = path.stem if is_video else path.name
        m = URFD_NAME.match(name)
        if not m or not (is_video or (path.is_dir() and m.group(4))):
            continue
        key = (m.group(1).lower(), int(m.group(2)), int(m.group(3)))
        # Prefer the RGB image folders: they are the dataset's canonical frames.
        if key not in sources or (path.is_dir() and not sources[key].is_dir()):
            sources[key] = path

    records = []
    for (kind, num, cam), source in sorted(sources.items()):
        if cam not in cams:
            continue
        seq = f"{kind}-{num:02d}"
        if kind == "adl":
            segments, default = [(0, TO_END, NORMAL)], NORMAL
        elif (kind, num) in labels:
            segments, default = runs_to_segments(labels[(kind, num)]), UNKNOWN
        else:
            log.warning("urfd: skipping %s (no labels in urfall-cam0-falls.csv)", source)
            continue
        records.append(VideoRecord("urfd", f"urfd/{seq}-cam{cam}", f"urfd/{seq}", source,
                                   segments, default, fps=30.0,
                                   crop=None if source.is_dir() else video_crop))
    return records


# ---------------------------------------------------------------- manifest --

@register_loader("manifest")
def load_manifest(root, manifest="manifest.csv"):
    """Generic loader for other datasets. ``<root>/<manifest>`` is a CSV with a
    header and columns:

        video        path relative to root (video file or image folder)
        group        split group (e.g. subject id); defaults to the video
        fall_start   first falling frame, 0-based; empty or -1 if no fall
        fall_end     last falling frame (lying from the next frame on)
        fps          optional
    """
    records = []
    with open(root / manifest, newline="") as f:
        for row in csv.DictReader(f):
            video = row["video"].strip()
            start = int(row.get("fall_start") or -1)
            end = int(row.get("fall_end") or -1)
            if start >= 0 and end < start:
                raise ValueError(f"{manifest}: {video} has fall_end < fall_start")
            segments = fall_segments(start, end) if start >= 0 else [(0, TO_END, NORMAL)]
            fps = float(row["fps"]) if row.get("fps") else None
            records.append(VideoRecord("manifest", f"manifest/{video}",
                                       row.get("group") or f"manifest/{video}",
                                       root / video, segments, fps=fps))
    return records
