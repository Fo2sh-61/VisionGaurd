#!/usr/bin/env python3
"""
Synthetic Egyptian plate generator.

Two jobs:

  1. Test data. Renders plates onto a fake "car at the gate" scene so the whole
     pipeline can be exercised with no cameras and no trained weights. Each
     image carries a hidden marker strip that the stub OCR backend decodes, so
     tests know the ground truth exactly.

  2. Training bootstrap. With --clean it writes plate crops plus YOLO-format
     character labels. Synthetic data alone will not give you a production
     model, but it gets a character detector off the ground in week one while
     real site images accumulate.

Usage:
    python tools/make_test_plates.py --count 20 --out data/synthetic
    python tools/make_test_plates.py --count 2000 --clean --labels \
        --out data/dataset/synthetic
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from anpr import plate_text                              # noqa: E402
from anpr.ocr import encode_marker, MARKER_ROWS          # noqa: E402

# Must cover Arabic letters AND Arabic-Indic digits. Verified with fontTools:
# DejaVuSans and FreeSerif do, FreeSans does not (renders tofu boxes).
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "/usr/share/fonts/truetype/kacst/KacstOne.ttf",
    "/usr/share/fonts/truetype/fonts-hosny-amiri/Amiri-Bold.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
]


def _font_covers_arabic(path: str) -> bool:
    """Reject fonts that would render Arabic as empty boxes."""
    try:
        from fontTools.ttLib import TTFont

        f = TTFont(path, fontNumber=0)
        cmap: set[int] = set()
        for t in f["cmap"].tables:
            cmap |= set(t.cmap.keys())
        probe = "ابجد" + plate_text.AR_DIGITS
        return all(ord(c) in cmap for c in probe)
    except Exception:
        return True  # fontTools missing - trust the candidate list

# Strip colour by vehicle class (BGR handled later; these are RGB).
STRIP_COLOURS = {
    "private": (140, 190, 235),
    "taxi": (240, 160, 60),
    "truck": (210, 70, 70),
    "government": (150, 150, 150),
    "tourist": (225, 205, 165),
}

PLATE_W, PLATE_H = 700, 340


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists() and _font_covers_arabic(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print("⚠ no Arabic-capable font found — install fonts-dejavu or Amiri",
          file=sys.stderr)
    return ImageFont.load_default()


def random_plate() -> str:
    """A plausible Egyptian plate: 2-3 letters + 3-4 digits (no zero)."""
    letters = random.sample(plate_text.STRICT_LETTERS, random.choice([2, 3]))
    digits = "".join(random.choices("123456789", k=random.choice([3, 4])))
    return plate_text.normalize("".join(letters) + digits)


def render_plate(canonical: str, vclass: str = "private",
                 with_labels: bool = False) -> tuple[np.ndarray, list]:
    """Render one plate face. Returns (BGR image, YOLO char label rows)."""
    letters, _, digits = canonical.partition(" ")
    ar_digits = plate_text.to_arabic_digits(digits)

    img = Image.new("RGB", (PLATE_W, PLATE_H), (247, 247, 244))
    d = ImageDraw.Draw(img)

    strip_h = int(PLATE_H * 0.26)
    d.rectangle([0, 0, PLATE_W, strip_h], fill=STRIP_COLOURS.get(vclass,
                                                                 STRIP_COLOURS["private"]))
    small = find_font(int(strip_h * 0.5))
    d.text((PLATE_W * 0.06, strip_h * 0.22), "EGYPT", font=small, fill=(20, 30, 50))
    for i, ch in enumerate("رصم"):   # م ص ر drawn right-to-left
        d.text((PLATE_W * 0.86 - i * strip_h * 0.42, strip_h * 0.18),
               ch, font=small, fill=(20, 30, 50))

    d.rectangle([2, 2, PLATE_W - 3, PLATE_H - 3], outline=(60, 60, 70), width=5)

    big = find_font(int(PLATE_H * 0.46))
    y = strip_h + (PLATE_H - strip_h) * 0.16
    labels: list = []

    def put(ch: str, cx: float, cls_name: str, max_w: float = 1e9) -> None:
        bb = d.textbbox((0, 0), ch, font=big)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        # Shrink a glyph that would collide with its neighbour. Real plates
        # keep characters clearly separated; overlapping ones teach a detector
        # to expect boxes that never occur in the field.
        if w > max_w:
            scale = max_w / w
            shrunk = find_font(max(int(PLATE_H * 0.46 * scale), 12))
            bb = d.textbbox((0, 0), ch, font=shrunk)
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            d.text((cx - w / 2 - bb[0], y - bb[1]), ch, font=shrunk,
                   fill=(15, 15, 20))
            if with_labels:
                labels.append((cls_name, cx / PLATE_W, (y + h / 2) / PLATE_H,
                               (w * 1.10) / PLATE_W, (h * 1.10) / PLATE_H))
            return
        d.text((cx - w / 2 - bb[0], y - bb[1]), ch, font=big, fill=(15, 15, 20))
        if with_labels:
            # The glyph's ink spans x in [cx - w/2, cx + w/2] and y in [y, y+h]
            # because that is exactly where it was just drawn. Boxes must match
            # the ink: earlier padding of 1.5x/1.45x made every label overlap
            # its neighbours, which teaches a detector the wrong extents and is
            # invisible unless you draw the labels back onto the image.
            pad = 1.10
            labels.append((cls_name,
                           cx / PLATE_W, (y + h / 2) / PLATE_H,
                           (w * pad) / PLATE_W, (h * pad) / PLATE_H))

    # Letters occupy the right half, digits the left half (Arabic reading order).
    n_l, n_d = len(letters), len(ar_digits)
    right0, right1 = PLATE_W * 0.55, PLATE_W * 0.94
    cell_l = (right1 - right0) / max(n_l, 1)
    for i, ch in enumerate(letters):
        cx = right1 - (i + 0.5) * cell_l
        put(ch, cx, ch, max_w=cell_l * 0.82)
    left0, left1 = PLATE_W * 0.06, PLATE_W * 0.46
    cell_d = (left1 - left0) / max(n_d, 1)
    for i, ch in enumerate(ar_digits):
        cx = left1 - (i + 0.5) * cell_d
        put(ch, cx, str(digits[i]), max_w=cell_d * 0.82)

    d.line([(PLATE_W * 0.505, strip_h + 12), (PLATE_W * 0.505, PLATE_H - 14)],
           fill=(90, 90, 100), width=4)

    tiny = find_font(int(PLATE_H * 0.13))
    d.text((PLATE_W * 0.55, PLATE_H * 0.86),
           plate_text.transliterate(canonical), font=tiny, fill=(90, 90, 100))

    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), labels


def make_scene(plate_img: np.ndarray, canonical: str, w: int = 1280,
               h: int = 720, seed: int | None = None) -> np.ndarray:
    """Paste a plate onto a synthetic car/asphalt scene with realistic noise."""
    rng = random.Random(seed)
    # Seed numpy too, or the noise makes generated scenes non-reproducible and
    # the test suite becomes flaky.
    np.random.seed((seed if seed is not None else 0) % (2 ** 32))
    scene = np.zeros((h, w, 3), np.uint8)
    top = rng.randint(60, 120)
    for y in range(h):                                  # asphalt gradient
        scene[y, :] = (top - y * 30 // h,) * 3
    scene += rng.randint(0, 12)

    # crude car body
    bx, by = rng.randint(w // 6, w // 3), rng.randint(h // 5, h // 3)
    bw, bh = rng.randint(w // 2, int(w * 0.62)), rng.randint(h // 3, h // 2)
    body = tuple(rng.randint(30, 200) for _ in range(3))
    cv2.rectangle(scene, (bx, by), (bx + bw, by + bh), body, -1)
    cv2.rectangle(scene, (bx + bw // 8, by + bh // 10),
                  (bx + bw - bw // 8, by + bh // 2),
                  tuple(max(c - 40, 0) for c in body), -1)

    ph = rng.randint(int(h * 0.10), int(h * 0.17))
    pw = int(ph * PLATE_W / PLATE_H)
    plate = cv2.resize(plate_img, (pw, ph), interpolation=cv2.INTER_AREA)

    # mild perspective, as if the camera is off to one side
    skew = rng.uniform(-0.06, 0.06)
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    dst = np.float32([[0, ph * abs(skew) * (skew > 0)],
                      [pw, ph * abs(skew) * (skew < 0)],
                      [pw, ph - ph * abs(skew) * (skew > 0)],
                      [0, ph - ph * abs(skew) * (skew < 0)]])
    plate = cv2.warpPerspective(plate, cv2.getPerspectiveTransform(src, dst),
                                (pw, ph), borderMode=cv2.BORDER_REPLICATE)

    px = bx + bw // 2 - pw // 2 + rng.randint(-20, 20)
    py = by + bh - ph - rng.randint(6, int(bh * 0.18))
    px, py = max(0, min(px, w - pw)), max(0, min(py, h - ph))
    scene[py:py + ph, px:px + pw] = plate

    if rng.random() < 0.5:
        k = rng.choice([3, 5])
        scene = cv2.GaussianBlur(scene, (k, k), 0)
    scene = cv2.add(scene, np.random.randint(0, rng.choice([6, 14]),
                                             scene.shape, dtype=np.uint8))

    # ground-truth marker for the stub OCR backend
    scene[-MARKER_ROWS:, :] = np.dstack([encode_marker(canonical, w)] * 3)
    return scene


def degrade(plate: np.ndarray, rng: random.Random) -> np.ndarray:
    """
    Make a clean render look like a plate seen from far away.

    This is the whole point of the synthetic set. A model trained only on big
    crisp plates learns big crisp plates; at 5 metres it sees 60 pixels of
    blurred, skewed, badly-lit metal and fails. Training on that degradation is
    what buys range.
    """
    h, w = plate.shape[:2]

    # perspective: camera off to one side and above
    sx = rng.uniform(-0.10, 0.10)
    sy = rng.uniform(-0.06, 0.06)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * abs(sx) * (sx < 0), h * abs(sy) * (sy < 0)],
                      [w - w * abs(sx) * (sx > 0), h * abs(sy) * (sy > 0)],
                      [w - w * abs(sx) * (sx < 0), h - h * abs(sy) * (sy < 0)],
                      [w * abs(sx) * (sx > 0), h - h * abs(sy) * (sy > 0)]])
    plate = cv2.warpPerspective(plate, cv2.getPerspectiveTransform(src, dst),
                                (w, h), borderMode=cv2.BORDER_REPLICATE)

    # distance: shrink hard, then blow back up - exactly what a far plate loses
    target = rng.choice([40, 50, 60, 70, 90, 110, 140, 180])
    th = max(int(target * h / w), 8)
    plate = cv2.resize(plate, (target, th), interpolation=cv2.INTER_AREA)

    if rng.random() < 0.6:                      # motion / focus blur
        k = rng.choice([3, 3, 5])
        plate = cv2.GaussianBlur(plate, (k, k), 0)

    # lighting: sun, shade, headlights, dusk
    alpha = rng.uniform(0.55, 1.45)
    beta = rng.randint(-45, 45)
    plate = cv2.convertScaleAbs(plate, alpha=alpha, beta=beta)

    if rng.random() < 0.5:                      # sensor noise at low light
        noise = np.random.randint(0, rng.choice([8, 16, 26]),
                                  plate.shape, dtype=np.uint8)
        plate = cv2.add(plate, noise)

    if rng.random() < 0.25:                     # JPEG artefacts from the camera
        q = rng.randint(35, 70)
        ok, enc = cv2.imencode(".jpg", plate, [cv2.IMWRITE_JPEG_QUALITY, q])
        if ok:
            plate = cv2.imdecode(enc, cv2.IMREAD_COLOR)

    # back up to the size the detector will be trained at
    return cv2.resize(plate, (w, h), interpolation=cv2.INTER_CUBIC)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--clean", action="store_true",
                    help="plate crops only, no scene (for training)")
    ap.add_argument("--labels", action="store_true",
                    help="write YOLO character labels next to each image")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--degrade", action="store_true",
                    help="simulate distance, blur, skew and lighting "
                         "(use this for training data)")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    if args.labels:
        (out / "labels").mkdir(parents=True, exist_ok=True)

    classes: dict[str, int] = {}
    truth = {}
    for i in range(args.count):
        canonical = random_plate()
        vclass = random.choices(list(STRIP_COLOURS),
                                weights=[70, 10, 10, 5, 5])[0]
        plate, labels = render_plate(canonical, vclass, args.labels)
        if args.degrade:
            plate = degrade(plate, random.Random(i))
        img = plate if args.clean else make_scene(plate, canonical, seed=i)
        name = f"plate_{i:05d}"
        cv2.imwrite(str(out / "images" / f"{name}.jpg"), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        truth[f"{name}.jpg"] = canonical
        if args.labels and args.clean:
            lines = []
            for cls_name, cx, cy, bw, bh in labels:
                idx = classes.setdefault(cls_name, len(classes))
                lines.append(f"{idx} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            (out / "labels" / f"{name}.txt").write_text("\n".join(lines))

    (out / "ground_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    if classes:
        (out / "classes.txt").write_text(
            "\n".join(sorted(classes, key=classes.get)), encoding="utf-8")
    print(f"✓ {args.count} plates -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
