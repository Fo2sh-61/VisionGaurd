"""Measure the plate reader against a dataset, and write down what it found.

**This tool exists because nobody has ever measured this.** The owner reports
plates coming back wrong; the repo has never had a clip with a car in it, so
the accuracy of the whole vehicle gate has been an open question with an
opinion on each side. `compare_plates.py` answers it for *one* photo. This
answers it for two thousand, and writes the answer down with a date on it.

    # is the detector finding the plates at all? (no truth file needed)
    python engine/tools/eval_plates.py --dataset "Egyptian Car Plates dataset/EALPR Vechicles dataset"

    # build the human-confirmed read truth (the owner sits with this one)
    python engine/tools/eval_plates.py --dataset "..." --label

    # how often is the reading exactly right?
    python engine/tools/eval_plates.py --dataset "..." --truth "Egyptian Car Plates dataset/plate_truth.csv"

    # the same question of every configuration, so the pairs can be compared
    python engine/tools/eval_plates.py --dataset "..." --truth "..." --configs theirs,fp32,fp16,trt

**The four configurations, and what each pair tells you.** Same idea as
`compare_plates.py`, whose docstring is the long version:

    theirs    models/Gate/gate-anpr, unchanged - the code that works
    fp32      ours, on the .pt, at FP32       - what engine.yaml now asks for
    fp16      ours, on the .pt, at FP16       - what it asked for until 24 Aug
    trt       ours, on the TensorRT plan      - built FP16, fixed input size

    theirs != fp32   our port, and nothing else
    fp32   != fp16   the precision
    fp16   != trt    the TensorRT plan

**Read the first disagreeing pair, not the best score.** As of 27 Aug the
calling convention has already been matched to gate-anpr (`half: false`,
`accelerate: false`, `iou: 0.7`), so `theirs` against `fp32` is the live
question: is our port faithful? A tie there means the software is right and
any remaining gap is the model or the camera.

**What a score here does and does not mean.** This dataset is what the
supplied models were TRAINED on. A number from it measures whether our
pipeline reproduces the source project on its own data. It is not a
prediction about the school's gate, and every report this writes says so.

Nothing here touches the database, the running engine, or a camera.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "models" / "Gate" / "gate-anpr" / "gate-anpr"
PLATE_WEIGHTS = REPO / "models" / "plate_detector.pt"
CHAR_WEIGHTS = REPO / "models" / "char_detector.pt"

sys.path.insert(0, str(REPO / "engine"))

#: Image files in the dataset. `.JPG` and `.jpeg` are not decoration: 56 of
#: the owner's 2,087 images use them, so globbing `*.jpg` alone drops 2.7% of
#: the set and quietly changes the denominator of every number below.
IMAGE_SUFFIXES = (".jpg", ".JPG", ".jpeg", ".JPEG", ".png", ".PNG")

#: Overlap at which a found box is the labelled plate.
FOUND_AT_IOU = 0.5

#: The width P6-FR-037 states its target at: at least 95% exact reads on
#: plates at least this wide. Below it, measured and reported with no target —
#: that regime is decided by where the camera is pointed, not by software.
READABLE_WIDTH_PX = 100

CONFIGS = ("theirs", "fp32", "fp16", "trt")

Box = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# the pure half — no model, no GPU. `tests/test_eval_plates.py` pins all of it
# ---------------------------------------------------------------------------

def is_label_file(path: Path) -> bool:
    """`classes.txt` sits beside the labels and is not one."""
    return path.suffix.lower() == ".txt" and path.stem != "classes"


def parse_label(text: str, width: int, height: int) -> list[Box]:
    """YOLO's `class cx cy w h`, all fractions, into pixel corners.

    Raises on a malformed line rather than skipping it. A skipped line shrinks
    the denominator, and the score goes up for a reason that has nothing to do
    with the reader.
    """
    boxes: list[Box] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"not a YOLO label line: {line!r}")
        _, cx, cy, w, h = (float(p) for p in parts)
        boxes.append((
            (cx - w / 2) * width, (cy - h / 2) * height,
            (cx + w / 2) * width, (cy + h / 2) * height,
        ))
    return boxes


def iou(a: Box, b: Box) -> float:
    ix = max(min(a[2], b[2]) - max(a[0], b[0]), 0.0)
    iy = max(min(a[3], b[3]) - max(a[1], b[1]), 0.0)
    overlap = ix * iy
    area_a = max(a[2] - a[0], 0.0) * max(a[3] - a[1], 0.0)
    area_b = max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)
    union = area_a + area_b - overlap
    return overlap / union if union > 0 else 0.0


def match_boxes(truth: list[Box], found: list[Box],
                min_iou: float = FOUND_AT_IOU
                ) -> tuple[list[tuple[Box, Box]], int, int]:
    """Pair each labelled plate with at most one found box, best first.

    Returns `(pairs, missed, extra)`. **One claim per plate**: two boxes on one
    plate is one hit and one false alarm, because a detector that sprayed
    boxes over the image would otherwise score perfectly.
    """
    pairs: list[tuple[Box, Box]] = []
    unclaimed = list(found)
    for want in truth:
        best, score = None, min_iou
        for candidate in unclaimed:
            overlap = iou(want, candidate)
            if overlap >= score:
                best, score = candidate, overlap
        if best is None:
            continue
        pairs.append((want, best))
        unclaimed.remove(best)
    return pairs, len(truth) - len(pairs), len(unclaimed)


def exact_read(read_text: str, true_text: str) -> bool:
    """Is this reading the right plate, exactly?

    Canonicalised on both sides first, because the same car arrives as
    `ب ج د ١٢٣٤` from a model and `بجد 1234` from a person typing truth. A raw
    `==` would score a perfect reader at zero.

    **Exact means exact.** `platetext.same_plate`'s one-edit tolerance exists
    to stop two spellings splitting a vote; using it to grade would mark a
    misread plate correct, which is the failure this whole tool is about.
    """
    from vg import platetext

    left, right = platetext.normalize(read_text), platetext.normalize(true_text)
    return bool(left) and bool(right) and left == right


def counts_towards_target(box: Box) -> bool:
    return (box[2] - box[0]) >= READABLE_WIDTH_PX


# ---------------------------------------------------------------------------
# the readers — built ONCE per configuration, never per image
# ---------------------------------------------------------------------------

def _purge_vg_inference_modules() -> None:
    """Drop every module that cached a decision about which weights to open.

    Without this the second configuration answers with the first one's model
    and the whole comparison is a tautology.
    """
    for name in [n for n in list(sys.modules)
                 if n.startswith("vg.infer") or n.startswith("vg.features")]:
        del sys.modules[name]


def build_reader(config: str):
    """A `read(image) -> list[(box, text, confidence)]`, or an error string.

    **Built once and reused for every image**, which is the whole difference
    between this and `compare_plates.py`. That tool rebuilds per call, which
    is right for one photo and would add hours over two thousand.
    """
    if config == "theirs":
        if not GATE.is_dir():
            return None, f"models/Gate is not present at {GATE}"
        sys.path.insert(0, str(GATE))
        try:
            from anpr.detector import PlateDetector
            from anpr.ocr import PlateReader as TheirReader
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return None, f"could not import gate-anpr: {exc}"

        detector = PlateDetector(backend="yolo", weights=str(PLATE_WEIGHTS),
                                 min_conf=0.35)
        reader = TheirReader(backend="yolo_chars", weights=str(CHAR_WEIGHTS))

        def read(image):
            out = []
            for box in detector.detect(image):
                result = reader.read(box.crop(image), context=image)
                out.append(((box.x1, box.y1, box.x2, box.y2),
                            result.text, result.confidence))
            return out

        return read, None

    accelerated = config == "trt"
    half = config in ("fp16", "trt")

    before = os.environ.get("VG_NO_TENSORRT")
    os.environ["VG_NO_TENSORRT"] = "0" if accelerated else "1"
    _purge_vg_inference_modules()
    try:
        from vg.infer.plates import PlateReader

        reader = PlateReader(plate_weights=PLATE_WEIGHTS,
                             char_weights=CHAR_WEIGHTS, half=half,
                             accelerate=accelerated)

        def read(image):
            return [((r.box.x1, r.box.y1, r.box.x2, r.box.y2),
                     r.text, r.confidence)
                    for r in reader.read_frame(image)]

        return read, None
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if before is None:
            os.environ.pop("VG_NO_TENSORRT", None)
        else:
            os.environ["VG_NO_TENSORRT"] = before


# ---------------------------------------------------------------------------
# the dataset
# ---------------------------------------------------------------------------

def find_pairs(dataset: Path) -> list[tuple[Path, Path]]:
    """Every image with its label file. Reports what it could not pair."""
    images_dir = dataset / "Vehicles"
    labels_dir = dataset / "Vehicles Labeling"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise SystemExit(
            f"expected '{images_dir.name}' and '{labels_dir.name}' under "
            f"{dataset} - see specs/007-vehicle-gate-tuning/evidence/"
            "dataset-inventory.md for the layout this reads")

    labels = {p.stem: p for p in labels_dir.iterdir() if is_label_file(p)}
    pairs, orphans = [], []
    for image in sorted(images_dir.iterdir()):
        if image.suffix not in IMAGE_SUFFIXES:
            continue
        label = labels.get(image.stem)
        (pairs.append((image, label)) if label else orphans.append(image.name))

    if orphans:
        print(f"  {len(orphans)} image(s) have no label and are skipped: "
              f"{', '.join(orphans[:5])}{' ...' if len(orphans) > 5 else ''}")
    return pairs


def load_truth(path: Path) -> dict[str, str]:
    """`image -> confirmed plate text`, from the human-confirmed CSV."""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["image"]: row["text"]
                for row in csv.DictReader(handle) if row.get("text")}


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------

class Score:
    """What one configuration did over the whole dataset."""

    def __init__(self, config: str) -> None:
        self.config = config
        self.images = 0
        self.plates = 0
        self.found = 0
        self.missed = 0
        self.extra = 0
        self.widths: list[float] = []
        # Reading, over the plates that have confirmed truth.
        self.judged = 0
        self.exact = 0
        self.judged_wide = 0
        self.exact_wide = 0
        self.failures: list[tuple[str, str, str]] = []

    @property
    def recall(self) -> float:
        return self.found / self.plates if self.plates else 0.0

    @property
    def precision(self) -> float:
        total = self.found + self.extra
        return self.found / total if total else 0.0

    @property
    def exact_rate(self) -> float:
        return self.exact / self.judged if self.judged else 0.0

    @property
    def exact_rate_wide(self) -> float:
        return self.exact_wide / self.judged_wide if self.judged_wide else 0.0


def evaluate(read, pairs, truth: dict[str, str], config: str,
             limit: int | None = None) -> Score:
    import cv2

    score = Score(config)
    for index, (image_path, label_path) in enumerate(pairs):
        if limit is not None and index >= limit:
            break
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"  could not open {image_path.name}, skipped")
            continue

        height, width = image.shape[:2]
        want = parse_label(label_path.read_text(encoding="utf-8"), width, height)
        got = read(image)

        matched, missed, extra = match_boxes(want, [b for b, _, _ in got])
        score.images += 1
        score.plates += len(want)
        score.found += len(matched)
        score.missed += missed
        score.extra += extra
        score.widths.extend(b[2] - b[0] for b in want)

        true_text = truth.get(image_path.name)
        if not true_text:
            continue
        # One plate per truth row, so score the best-matched box only.
        for want_box, found_box in matched:
            text = next((t for b, t, _ in got if b == found_box), "")
            correct = exact_read(text, true_text)
            wide = counts_towards_target(want_box)
            score.judged += 1
            score.exact += int(correct)
            if wide:
                score.judged_wide += 1
                score.exact_wide += int(correct)
            if not correct:
                from vg import platetext
                score.failures.append((
                    image_path.name,
                    platetext.transliterate(platetext.normalize(true_text)),
                    platetext.transliterate(platetext.normalize(text)) or "(nothing)",
                ))
            break
        else:
            # The plate was never found, so the reader was never asked. That
            # is still a failure to read this car, and hiding it would let a
            # detector that finds nothing score 100% on what it did read.
            if want:
                score.judged += 1
                if counts_towards_target(want[0]):
                    score.judged_wide += 1
                score.failures.append(
                    (image_path.name, "(truth)", "(plate not found)"))
    return score


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

HONESTY = (
    "**What this number is not.** This dataset is what the supplied models "
    "were trained on, so a score here measures whether our pipeline "
    "reproduces the source project on its own data - pipeline fidelity. It "
    "is not a prediction about the school's gate. Only site captures "
    "(`engine/tools/record.py`) or a hand test with real plates can answer "
    "that."
)


def report(scores: list[Score], dataset: Path, truth_path: Path | None,
           out_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    names = "-".join(s.config for s in scores)
    path = out_dir / f"eval-{stamp}-{names}.md"

    lines = [
        f"# Plate reader evaluation - {stamp}",
        "",
        f"Dataset: `{dataset}`",
        f"Truth: `{truth_path}`" if truth_path else "Truth: none (detection only)",
        "",
        HONESTY,
        "",
        "## Finding the plate",
        "",
        "| Config | Images | Plates | Found | Missed | False | Recall | Precision |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.config} | {s.images} | {s.plates} | {s.found} | {s.missed} "
            f"| {s.extra} | {s.recall:.1%} | {s.precision:.1%} |")

    if any(s.judged for s in scores):
        lines += [
            "",
            "## Reading the plate",
            "",
            f"Target (P6-FR-037): at least 95% exact on plates at least "
            f"{READABLE_WIDTH_PX}px wide.",
            "",
            "| Config | Judged | Exact | Rate | Judged >=100px | Exact >=100px | "
            "Rate >=100px | Meets target |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in scores:
            met = "yes" if s.judged_wide and s.exact_rate_wide >= 0.95 else "no"
            lines.append(
                f"| {s.config} | {s.judged} | {s.exact} | {s.exact_rate:.1%} "
                f"| {s.judged_wide} | {s.exact_wide} "
                f"| {s.exact_rate_wide:.1%} | {met} |")

        for s in scores:
            if not s.failures:
                continue
            lines += ["", f"### Misreads - {s.config}", "",
                      "| Image | Truth | Read |", "|---|---|---|"]
            for name, want, got in s.failures[:60]:
                lines.append(f"| {name} | {want} | {got} |")
            if len(s.failures) > 60:
                lines.append(f"| ... | {len(s.failures) - 60} more | |")
    else:
        lines += [
            "",
            "## Reading the plate",
            "",
            "Not measured: no confirmed-truth file. The dataset carries plate "
            "**boxes** only, so the 95% target needs `--label` first (task "
            "T014, and it needs the owner).",
        ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_summary(scores: list[Score]) -> None:
    print()
    print(f"{'config':10} {'recall':>8} {'precision':>10} "
          f"{'exact':>8} {'exact>=100px':>13}")
    for s in scores:
        exact = f"{s.exact_rate:.1%}" if s.judged else "-"
        wide = f"{s.exact_rate_wide:.1%}" if s.judged_wide else "-"
        print(f"{s.config:10} {s.recall:>8.1%} {s.precision:>10.1%} "
              f"{exact:>8} {wide:>13}")


# ---------------------------------------------------------------------------
# assisted labelling
# ---------------------------------------------------------------------------

def label(dataset: Path, truth_path: Path, config: str,
          limit: int | None) -> int:
    """Build the confirmed-truth CSV, one plate at a time, with a person.

    **A proposal is never truth until a human confirms it.** The model
    grading its own homework would be circular, so every row here is
    something Mohamed looked at - including the ones the reader got right.

    Resumable: images already in the CSV are skipped, so this can be done in
    sittings.
    """
    import cv2

    read, error = build_reader(config)
    if error:
        print(f"cannot build the '{config}' reader: {error}")
        return 1

    pairs = find_pairs(dataset)
    done = load_truth(truth_path)
    todo = [(i, l) for i, l in pairs if i.name not in done]
    print(f"{len(done)} already confirmed, {len(todo)} to go.")
    print("Enter = the proposal is right · type the plate = correct it · "
          "s = skip · q = stop and save\n")

    fresh = 0
    new_file = not truth_path.exists()
    with truth_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["image", "x1", "y1", "x2", "y2", "text",
                             "width_px", "confirmed_by", "confirmed_at"])
        for image_path, label_path in (todo[:limit] if limit else todo):
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            height, width = image.shape[:2]
            want = parse_label(label_path.read_text(encoding="utf-8"),
                               width, height)
            if len(want) != 1:
                continue          # multi-plate photos need a decision per box
            box = want[0]

            got = read(image)
            matched, _, _ = match_boxes(want, [b for b, _, _ in got])
            proposal = ""
            if matched:
                proposal = next(
                    (t for b, t, _ in got if b == matched[0][1]), "")

            from vg import platetext
            crop = image[int(box[1]):int(box[3]), int(box[0]):int(box[2])]
            cv2.imshow("plate - confirm or correct", crop)
            cv2.waitKey(1)

            shown = platetext.transliterate(proposal) or "(read nothing)"
            answer = input(
                f"{image_path.name}  [{int(box[2] - box[0])}px]  "
                f"proposal: {shown}  > ").strip()

            if answer.lower() == "q":
                break
            if answer.lower() == "s" or (not answer and not proposal):
                continue
            text = platetext.normalize(answer or proposal)
            if not text:
                continue

            writer.writerow([
                image_path.name, f"{box[0]:.1f}", f"{box[1]:.1f}",
                f"{box[2]:.1f}", f"{box[3]:.1f}", text,
                int(box[2] - box[0]), os.getenv("USERNAME", "owner"),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ])
            handle.flush()
            fresh += 1

    cv2.destroyAllWindows()
    print(f"\n{fresh} newly confirmed. {len(done) + fresh} in {truth_path}.")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset",
        default=str(REPO / "Egyptian Car Plates dataset"
                    / "EALPR Vechicles dataset"),
        help="folder holding 'Vehicles' and 'Vehicles Labeling'")
    parser.add_argument(
        "--truth",
        default=str(REPO / "Egyptian Car Plates dataset" / "plate_truth.csv"),
        help="the human-confirmed read truth")
    parser.add_argument("--configs", default="fp32",
                        help=f"comma separated, any of: {', '.join(CONFIGS)}")
    parser.add_argument("--label", action="store_true",
                        help="build the truth file instead of measuring")
    parser.add_argument("--limit", type=int,
                        help="stop after this many images (a quick look)")
    parser.add_argument(
        "--out", default=str(REPO / "specs" / "007-vehicle-gate-tuning"
                             / "evidence"),
        help="where the dated evidence file is written")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    truth_path = Path(args.truth)

    if args.label:
        return label(dataset, truth_path, args.configs.split(",")[0].strip(),
                     args.limit)

    wanted = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in CONFIGS]
    if unknown:
        print(f"unknown config(s): {', '.join(unknown)}. "
              f"Known: {', '.join(CONFIGS)}")
        return 2

    pairs = find_pairs(dataset)
    print(f"{len(pairs)} image/label pairs in {dataset}")
    truth = load_truth(truth_path)
    print(f"{len(truth)} confirmed plate texts in {truth_path}"
          if truth else
          f"no confirmed truth at {truth_path} - measuring detection only")

    scores = []
    for config in wanted:
        print(f"\n--- {config} ---")
        read, error = build_reader(config)
        if error:
            print(f"  skipped: {error}")
            continue
        scores.append(evaluate(read, pairs, truth, config, args.limit))

    if not scores:
        print("\nnothing ran.")
        return 1

    print_summary(scores)
    written = report(scores, dataset, truth_path if truth else None,
                     Path(args.out))
    print(f"\nwritten: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
