#!/usr/bin/env python3
"""
Fine-tune the plate detector and the Arabic character detector on your own data.

This is the step that takes the system from "works most of the time" to
"works". Public datasets are shot at other angles, other lighting and other
cameras; three weeks of crops from YOUR gate are worth more than all of them.

Workflow
--------
1. Run the system in log-only mode. Every plate crop is banked automatically in
   data/dataset/plates/<date>/ (config: collect_dataset: true).

2. Label them. Two options:
     a) tools/label_helper.py — review the crops the system already read and
        just confirm or fix the text. Much faster than labelling from scratch,
        because the reader is usually close.
     b) Any YOLO labelling tool (Label Studio, CVAT, Roboflow) if you want
        per-character boxes.

3. Train:
     python tools/train_char_detector.py --task plate --data data/yolo/plate.yaml
     python tools/train_char_detector.py --task chars --data data/yolo/chars.yaml

4. Deploy: the script writes models/plate_detector.pt and
   models/char_detector.pt, which the pipeline picks up on next start.

5. On a Jetson, export to TensorRT for roughly 3-4x throughput:
     python tools/train_char_detector.py --export models/char_detector.pt

Dataset layout expected (standard Ultralytics):
    data/yolo/chars/
        images/train/*.jpg   labels/train/*.txt
        images/val/*.jpg     labels/val/*.txt
    data/yolo/chars.yaml     <- written by --init if missing
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from anpr import plate_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# One class per character the detector may output.
CHAR_CLASSES = list(plate_text.STRICT_LETTERS) + list("0123456789")


def write_yaml(task: str, root: Path) -> Path:
    names = (["plate"] if task == "plate" else CHAR_CLASSES)
    ds = root / "data" / "yolo" / task
    (ds / "images" / "train").mkdir(parents=True, exist_ok=True)
    (ds / "images" / "val").mkdir(parents=True, exist_ok=True)
    (ds / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (ds / "labels" / "val").mkdir(parents=True, exist_ok=True)
    yaml_path = root / "data" / "yolo" / f"{task}.yaml"
    lines = [f"path: {ds}", "train: images/train", "val: images/val", "names:"]
    lines += [f"  {i}: {n}" for i, n in enumerate(names)]
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ wrote {yaml_path}  ({len(names)} classes)")
    print(f"  put images in {ds / 'images' / 'train'}")
    return yaml_path


def train(task: str, data: str, epochs: int, imgsz: int, batch: int,
          base: str, device: str) -> int:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Install ultralytics first:  pip install ultralytics")
        return 2

    out_name = "plate_detector" if task == "plate" else "char_detector"
    model = YOLO(base)
    model.train(data=data, epochs=epochs, imgsz=imgsz, batch=batch,
                device=None if device == "auto" else device,
                project=str(ROOT / "runs"), name=out_name, exist_ok=True,
                patience=25, seed=0,
                # Plates are rigid rectangles: no vertical flips, no mosaic
                # late in training, mild rotation only.
                fliplr=0.0, flipud=0.0, degrees=4.0, shear=2.0,
                perspective=0.0004, hsv_v=0.5, close_mosaic=10)
    best = ROOT / "runs" / out_name / "weights" / "best.pt"
    dest = ROOT / "models" / f"{out_name}.pt"
    if best.exists():
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(best, dest)
        print(f"\n✓ deployed {dest}")
        print("  restart the system to use it:  python run.py start")
    else:
        print("⚠ training finished but best.pt not found", file=sys.stderr)
        return 1
    return 0


def export_trt(weights: str, half: bool = True) -> int:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("pip install ultralytics")
        return 2
    m = YOLO(weights)
    path = m.export(format="engine", half=half, device=0)
    print(f"✓ TensorRT engine: {path}")
    print("  point the config at this .engine file for full Jetson speed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", choices=["plate", "chars"], default="chars")
    ap.add_argument("--data", default="", help="path to dataset yaml")
    ap.add_argument("--init", action="store_true",
                    help="create the dataset folders and yaml, then exit")
    ap.add_argument("--epochs", type=int, default=120)
    ap.add_argument("--imgsz", type=int, default=0,
                    help="default 640 for plate, 320 for chars")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--base", default="yolo11n.pt",
                    help="starting weights; n=nano is right for Jetson")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--export", default="",
                    help="export these weights to TensorRT and exit")
    args = ap.parse_args()

    if args.export:
        return export_trt(args.export)
    if args.init or not args.data:
        y = write_yaml(args.task, ROOT)
        if args.init:
            return 0
        args.data = str(y)

    imgsz = args.imgsz or (640 if args.task == "plate" else 320)
    return train(args.task, args.data, args.epochs, imgsz, args.batch,
                 args.base, args.device)


if __name__ == "__main__":
    raise SystemExit(main())
