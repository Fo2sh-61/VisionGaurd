"""Read one plate four ways and print what each one saw.

The question this exists to answer: **our reader disagrees with the project
the weights came from, on the same weights.** Guessing at the cause has
already cost one wrong fix, so this runs both pipelines side by side on the
same pixels and prints every stage, and the difference stops being an
argument.

    # a photo, or a snapshot the gate saved
    python engine/tools/compare_plates.py --image plate.jpg

    # or straight off the webcam - hold the plate up, it grabs 20 frames
    # (stop the engine first; it holds the camera)
    python engine/tools/compare_plates.py --camera 0 --frames 20

    # keep every frame it read, to look at afterwards
    python engine/tools/compare_plates.py --camera 0 --save runs/plates

Four readers, and each pair isolates exactly one difference:

    theirs      models/Gate/gate-anpr - the code that works, unchanged
    ours-fp32   ours, on the .pt, at FP32 - the same as theirs
    ours-fp16   ours, on the .pt, at FP16 - what `half: true` gives us
    ours-trt    ours, exactly as the engine runs it today

Read the four lines top to bottom; the first pair that disagrees names the
cause:

    theirs != ours-fp32    our port, and nothing else
    ours-fp32 != ours-fp16 the precision - `half: true` in engine.yaml
    ours-fp16 != ours-trt  the TensorRT plan, built at FP16 and fixed size

That third one is not a formality. gate-anpr passes no precision argument at
all and gets FP32; this engine asks for FP16 on both models, and a model that
classifies single characters has less room than a person detector does.

Nothing here writes to the database or touches the running engine.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "engine"))

GATE = REPO / "models" / "Gate" / "gate-anpr" / "gate-anpr"

PLATE_WEIGHTS = REPO / "models" / "plate_detector.pt"
CHAR_WEIGHTS = REPO / "models" / "char_detector.pt"


def ascii_plate(text: str) -> str:
    """Transliterated, because the Windows console is cp1252 and Arabic in a
    print() raises UnicodeEncodeError - inside the tool that exists to
    diagnose things."""
    from vg import platetext

    return platetext.transliterate(text) if text else "(nothing)"


# ---------------------------------------------------------------------------
# theirs
# ---------------------------------------------------------------------------

def read_theirs(image):
    """gate-anpr's own detector and reader, imported and called unchanged."""
    if not GATE.is_dir():
        return None, "models/Gate is not present"

    sys.path.insert(0, str(GATE))
    try:
        from anpr.detector import PlateDetector
        from anpr.ocr import PlateReader
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return None, f"could not import gate-anpr: {exc}"

    detector = PlateDetector(backend="yolo", weights=str(PLATE_WEIGHTS),
                             min_conf=0.35)
    reader = PlateReader(backend="yolo_chars", weights=str(CHAR_WEIGHTS))

    out = []
    for box in detector.detect(image):
        result = reader.read(box.crop(image), context=image)
        out.append({
            "box": (box.x1, box.y1, box.x2, box.y2),
            "box_conf": box.confidence,
            "text": result.text,
            "conf": result.confidence,
            "chars": list(result.chars),
            "backend": result.backend,
        })
    return out, None


# ---------------------------------------------------------------------------
# ours
# ---------------------------------------------------------------------------

def read_ours(image, accelerated: bool, half: bool = True):
    """Our `PlateReader`, on the engine or forced onto the .pt.

    `half` is the other axis. We pass `quantize=16` to both models because
    `half: true` is set in `engine.yaml`; gate-anpr passes nothing and gets
    FP32. On a model classifying single characters that is worth measuring.
    """
    before = os.environ.get("VG_NO_TENSORRT")
    os.environ["VG_NO_TENSORRT"] = "0" if accelerated else "1"

    # Every module that cached a decision about which weights to open has to
    # go, or the second run answers with the first run's model.
    for name in [n for n in list(sys.modules)
                 if n.startswith("vg.infer") or n.startswith("vg.features")]:
        del sys.modules[name]

    try:
        from vg.infer.plates import PlateReader

        reader = PlateReader(plate_weights=PLATE_WEIGHTS,
                             char_weights=CHAR_WEIGHTS, half=half)
        out = []
        for read in reader.read_frame(image):
            out.append({
                "box": (read.box.x1, read.box.y1, read.box.x2, read.box.y2),
                "box_conf": read.box.confidence,
                "text": read.text,
                "conf": read.confidence,
                "chars": list(read.chars),
                "backend": reader.form,
            })
        return out, None
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if before is None:
            os.environ.pop("VG_NO_TENSORRT", None)
        else:
            os.environ["VG_NO_TENSORRT"] = before


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def show(label: str, reads, error, verbose: bool) -> str:
    """One reader's answer. Returns the plate text, for the verdict line."""
    if error:
        print(f"  {label:10} !! {error}")
        return ""
    if not reads:
        print(f"  {label:10} -- no plate found")
        return ""

    best = max(reads, key=lambda r: r["conf"])
    for read in reads:
        marker = "*" if read is best else " "
        print(f"  {label:10} {marker} {ascii_plate(read['text']):22}"
              f" conf={read['conf']:.3f} box={read['box']}"
              f" ({read['backend']})")
        if verbose and read["chars"]:
            glyphs = "  ".join(f"{ascii_plate(g)}:{c:.2f}"
                               for g, c in read["chars"])
            print(f"  {'':10}   chars: {glyphs}")
    return best["text"]


def compare(image, index: int, verbose: bool) -> None:
    print(f"\nframe {index}  {image.shape[1]}x{image.shape[0]}")

    theirs, theirs_err = read_theirs(image)
    fp32, fp32_err = read_ours(image, accelerated=False, half=False)
    fp16, fp16_err = read_ours(image, accelerated=False, half=True)
    trt, trt_err = read_ours(image, accelerated=True)

    a = show("theirs", theirs, theirs_err, verbose)
    b = show("ours-fp32", fp32, fp32_err, verbose)
    c = show("ours-fp16", fp16, fp16_err, verbose)
    d = show("ours-trt", trt, trt_err, verbose)

    # Read top to bottom: the first pair that disagrees names the cause.
    # `theirs` and `ours-fp32` run the same weights at the same precision, so
    # a difference there is our port and nothing else.
    if a and b and a != b:
        print("  VERDICT   our PORT differs - same weights, same precision")
    elif b and c and b != c:
        print("  VERDICT   FP16 costs accuracy - set half: false in engine.yaml")
    elif c and d and c != d:
        print("  VERDICT   TensorRT differs from the .pt it was built from")
    elif a and a == b == c == d:
        print("  VERDICT   all four agree")


def frames_from(args):
    import cv2

    if args.image:
        path = Path(args.image)
        image = cv2.imread(str(path))
        if image is None:
            sys.exit(f"could not read {path}")
        yield 0, image
        return

    capture = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not capture.isOpened():
        sys.exit(f"could not open camera {args.camera}. Is the engine still "
                 f"running? It holds the webcam.")
    try:
        for i in range(args.frames):
            ok, image = capture.read()
            if not ok:
                break
            yield i, image
    finally:
        capture.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="a photo, or a snapshot the gate saved")
    source.add_argument("--camera", type=int, help="webcam index, usually 0")
    parser.add_argument("--frames", type=int, default=10,
                        help="how many frames to grab from the camera")
    parser.add_argument("--save", help="write every frame read into this folder")
    parser.add_argument("--chars", action="store_true",
                        help="print every character and its confidence")
    args = parser.parse_args()

    import cv2

    for name, path in (("plate", PLATE_WEIGHTS), ("char", CHAR_WEIGHTS)):
        if not path.is_file():
            sys.exit(f"{name} weights not found: {path}")

    saved = Path(args.save) if args.save else None
    if saved:
        saved.mkdir(parents=True, exist_ok=True)

    for index, image in frames_from(args):
        if saved is not None:
            ok, buffer = cv2.imencode(".jpg", image,
                                      [cv2.IMWRITE_JPEG_QUALITY, 95])
            if ok:
                (saved / f"frame-{index:03d}.jpg").write_bytes(buffer.tobytes())
        compare(image, index, verbose=args.chars)

    if saved:
        print(f"\nframes written to {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
