#!/usr/bin/env python3
"""
Fast labelling of the plate crops the system collected at your gate.

The system already guessed a plate for every crop, and the guess is usually
close. This tool shows you each crop with its guess: press Enter to accept, or
type the correction. That turns labelling from "type 3000 plates" into "press
Enter 2500 times and fix 500", which is the difference between a dataset you
actually build and one you never get around to.

Output is a labels.csv the training script and the character-crop exporter both
read.

    python tools/label_helper.py --dir data/dataset/plates --out data/dataset/labels.csv
    python tools/label_helper.py --export-chars data/dataset/labels.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from anpr import plate_text  # noqa: E402


def guess_from_filename(p: Path) -> str:
    """Crops are saved as <camera>_<timestamp>_<plate>.jpg by the pipeline."""
    stem = p.stem
    parts = stem.split("_")
    if len(parts) >= 3:
        return plate_text.normalize(" ".join(parts[2:]))
    return ""


def label(folder: Path, out: Path, show: bool) -> int:
    images = sorted([p for p in folder.rglob("*.jpg")])
    if not images:
        print(f"no images under {folder}")
        return 1

    done: dict[str, str] = {}
    if out.exists():
        with out.open(encoding="utf-8") as f:
            done = {r["image"]: r["plate"] for r in csv.DictReader(f)}
        print(f"resuming — {len(done)} already labelled")

    todo = [p for p in images if str(p) not in done]
    print(f"{len(todo)} crops to label. Enter = accept, 's' = skip, 'q' = save+quit\n")

    for i, p in enumerate(todo, 1):
        guess = guess_from_filename(p)
        if show:
            try:
                import cv2

                img = cv2.imread(str(p))
                if img is not None:
                    h = 160
                    img = cv2.resize(img, (int(img.shape[1] * h / img.shape[0]), h))
                    cv2.imshow("plate", img)
                    cv2.waitKey(1)
            except Exception:
                pass
        print(f"[{i}/{len(todo)}] {p.name}")
        print(f"    guess: {plate_text.display(guess) or '(none)'}   "
              f"{plate_text.transliterate(guess)}")
        raw = input("    plate > ").strip()
        if raw.lower() == "q":
            break
        if raw.lower() == "s":
            continue
        value = plate_text.normalize(raw) if raw else guess
        if not value:
            continue
        if not plate_text.is_wellformed(value):
            print(f"    ⚠ unusual plate '{value}' — kept anyway")
        done[str(p)] = value

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image", "plate", "latin"])
        for img, plate in sorted(done.items()):
            w.writerow([img, plate, plate_text.transliterate(plate)])
    print(f"\n✓ {len(done)} labels -> {out}")
    try:
        import cv2

        cv2.destroyAllWindows()
    except Exception:
        pass
    return 0


def export_chars(labels_csv: Path, out_dir: Path) -> int:
    """
    Segment each labelled plate into character crops for a CNN classifier.

    Uses connected components on the binarised plate body. Anything whose
    component count does not match the label length is written to
    review/ instead of the class folders, so bad segmentations never
    silently poison the training set.
    """
    import cv2
    import numpy as np

    from anpr.detector import strip_blue_band

    rows = list(csv.DictReader(labels_csv.open(encoding="utf-8")))
    ok = bad = 0
    for r in rows:
        img = cv2.imread(r["image"])
        if img is None:
            continue
        body = strip_blue_band(img)
        gray = cv2.cvtColor(body, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (int(gray.shape[1] * 96 / gray.shape[0]), 96))
        th = cv2.threshold(gray, 0, 255,
                           cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        n, _, stats, _ = cv2.connectedComponentsWithStats(th, 8)
        boxes = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if h < 30 or h > 92 or w < 6 or area < 90:
                continue
            boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: -b[0])          # right to left
        chars = r["plate"].replace(" ", "")
        if len(boxes) != len(chars):
            bad += 1
            d = out_dir / "review"
            d.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(d / Path(r["image"]).name), body)
            continue
        for (x, y, w, h), ch in zip(boxes, chars):
            d = out_dir / ("digit_" + ch if ch.isdigit() else "letter_" + ch)
            d.mkdir(parents=True, exist_ok=True)
            crop = gray[max(y - 3, 0):y + h + 3, max(x - 3, 0):x + w + 3]
            cv2.imwrite(str(d / f"{Path(r['image']).stem}_{x}.png"),
                        cv2.resize(crop, (32, 48)))
            ok += 1
    print(f"✓ {ok} character crops -> {out_dir}")
    print(f"  {bad} plates needed manual review -> {out_dir / 'review'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/dataset/plates")
    ap.add_argument("--out", default="data/dataset/labels.csv")
    ap.add_argument("--no-show", action="store_true",
                    help="do not open an image window (headless server)")
    ap.add_argument("--export-chars", default="",
                    help="labels.csv to slice into per-character crops")
    ap.add_argument("--chars-out", default="data/dataset/chars")
    args = ap.parse_args()

    if args.export_chars:
        return export_chars(Path(args.export_chars), Path(args.chars_out))
    return label(Path(args.dir), Path(args.out), not args.no_show)


if __name__ == "__main__":
    raise SystemExit(main())
