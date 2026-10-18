"""Reading an Egyptian number plate: two models, in a fixed order.

    plate pass (YOLO, 1 class)  ->  no plate?  ->  stop. The reader never runs.
                                    a plate?   ->  crop it, strip the coloured
                                                   band, and read the crop
                                                   character by character.

**The character model only ever sees a crop.** That gate is the whole cost
argument, and it is the same one `features/weapons.py` makes: a frame with no
car pays for one model, not two, and the second runs on a plate-sized image
rather than a full frame. Two YOLO11m models at a gate is only affordable
because of this.

**Why per-character detection rather than OCR.** An Egyptian plate is Arabic
letters plus Indic digits in a plate-specific font, under a coloured "مصر /
EGYPT" band. Every published study of Egyptian ANPR reaches the same
conclusion: treat each character as its own object-detection class and you get
~99%; use general OCR and you get ~94%. On a four-character number that
difference compounds.

**Three things about this reader that are not obvious**, each of which was a
real bug in the project it came from:

1. **Reading order is not uniform.** The letters are Arabic and run
   right-to-left; the number is a numeral and runs left-to-right, exactly as
   printed. Sorting the whole plate one way silently reverses the digits — so
   `ط ن ٧١٢٦` comes back as `طن 6217`, a plate that looks well formed, scores
   well, and matches nothing. Only palindromes hide it.

2. **One glyph can produce several boxes.** YOLO suppresses overlaps *per
   class*, so two different classes firing on one character both survive. That
   is where `مجببع` came from for a plate reading `مجب`. Grouping by position
   is what makes one glyph yield one character.

3. **`٤/ع`, `٥/ه`, `٦/و` are the same shape** and confidence cannot separate
   them. Position can: the plate keeps its number and its letters in separate
   blocks, so a glyph standing among the digits is a digit whatever the model
   preferred.

Ported from `models/Gate/gate-anpr/anpr/{detector,ocr}.py`. The class names in
`char_detector.pt` are Latin transliterations (`alif`, `baa`, `7aa`), not
Arabic glyphs — `CHAR_GLYPHS` is the map, and it must track the weights rather
than any general transliteration scheme.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from vg import platetext
from vg.infer.shared import load_model

log = logging.getLogger(__name__)

os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO_DIR = Path(__file__).resolve().parents[3]

#: `char_detector.pt`'s 38 classes, as Arabic. Capitalisation is the trained
#: convention for the emphatic pairs — `Taa`=ط against `taa`=ت, `Thaa`=ظ
#: against `thaa`=ث — and `7aa` is chat-alphabet ح. Keep this in step with the
#: weights, not with any general transliteration scheme: a mismatch does not
#: error, it returns `"alifbaajeem123"` and `normalize` discards all of it.
CHAR_GLYPHS = {
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "alif": "ا", "baa": "ب", "taa": "ت", "thaa": "ث", "jeem": "ج",
    "7aa": "ح", "khaa": "خ", "daal": "د", "zaal": "ذ", "raa": "ر",
    "zay": "ز", "seen": "س", "sheen": "ش", "saad": "ص", "daad": "ض",
    "Taa": "ط", "Thaa": "ظ", "ain": "ع", "ghayn": "غ", "faa": "ف",
    "qaaf": "ق", "kaaf": "ك", "laam": "ل", "meem": "م", "noon": "ن",
    "haa": "ه", "waw": "و", "yaa": "ى",
}

#: Every crop is read at this width, whatever size it arrived at.
#:
#: The highest-leverage number in the file. Accuracy is flat and correct from
#: ~240px upward and falls away below it — 6/6 at 320px against 3/6 at 80px —
#: because a distant plate reaches the model as a handful of pixels per glyph
#: unless it is scaled first. Normalising here is what lets one camera cover a
#: range of distances rather than only the one it is framed for. Larger is not
#: better, merely flat, so this sits at the low end of the good range.
READ_WIDTH = 320

#: A glyph must reach this to be part of the plate at all.
DETECT_CONF = 0.25

#: Weaker boxes are still collected, but only as **alternative readings of a
#: character already found** — never as extra characters. That is what makes
#: the low floor safe: it adds nothing, it only gives the letter/digit
#: disambiguation something to choose between.
ALT_CONF = 0.10

#: Below this width a plate will not read, whatever the software does. Camera
#: placement decides this, not code. Reported rather than silently attempted.
MIN_PLATE_WIDTH_PX = 60


@dataclass(frozen=True)
class PlateBox:
    """Where a plate is, in PIXELS. Converted to fractions at the API edge."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float

    @property
    def w(self) -> int:
        return self.x2 - self.x1

    @property
    def h(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return max(self.w, 0) * max(self.h, 0)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    def crop(self, frame: np.ndarray, pad: float = 0.06) -> np.ndarray:
        """The plate, with a little margin — the band strip needs the edges."""
        pad_h, pad_w = int(self.h * pad), int(self.w * pad)
        y1 = max(self.y1 - pad_h, 0)
        y2 = min(self.y2 + pad_h, frame.shape[0])
        x1 = max(self.x1 - pad_w, 0)
        x2 = min(self.x2 + pad_w, frame.shape[1])
        return frame[y1:y2, x1:x2]


@dataclass
class PlateRead:
    """One plate, found and read, from one frame."""

    box: PlateBox
    text: str = ""                 # canonical, from platetext.normalize
    confidence: float = 0.0        # the reader's own, 0..1
    chars: list[tuple[str, float]] = field(default_factory=list)

    @property
    def plausibility(self) -> float:
        return platetext.plausibility(self.text)

    @property
    def score(self) -> float:
        """Confidence tempered by how much this looks like a plate at all."""
        return round(self.confidence * self.plausibility, 4)

    @property
    def readable(self) -> bool:
        """Was the plate physically big enough to have a chance?

        Separated from "did it read" so the console can tell an operator their
        camera is too far away rather than that the software is broken.
        """
        return self.box.w >= MIN_PLATE_WIDTH_PX

    def __bool__(self) -> bool:
        return bool(self.text)


@dataclass
class _Det:
    """One character box the model proposed."""

    x1: float
    y1: float
    x2: float
    y2: float
    glyph: str
    conf: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def area(self) -> float:
        return max(self.x2 - self.x1, 0.0) * max(self.y2 - self.y1, 0.0)


# --- image preparation -----------------------------------------------------

def strip_band(plate: np.ndarray) -> np.ndarray:
    """Remove the coloured "مصر / EGYPT" strip above the registration.

    The band carries no registration information and reliably confuses the
    reader, which returns `مصر` as three extra letters.

    **Found by saturation, not by cropping a fixed percentage.** A fixed crop
    works on a white private plate and fails on an orange taxi, a red haulage
    plate or a grey government one. Measuring how coloured each row is finds
    the band wherever it sits and whatever colour it happens to be.
    """
    if plate is None or plate.size == 0 or plate.ndim != 3:
        return plate
    height = plate.shape[0]
    if height < 20:
        return plate

    hsv = cv2.cvtColor(plate, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].mean(axis=1)
    value = hsv[:, :, 2].mean(axis=1)

    limit = int(height * 0.55)
    body = float(np.median(saturation[limit:])) if height > limit else float(
        saturation.mean())

    cut = 0
    for y in range(limit):
        coloured = saturation[y] > max(body * 1.8, 55)
        dark = value[y] < 90
        if coloured or dark:
            cut = y + 1
        elif cut and y - cut > 3:
            break

    if 0 < cut < int(height * 0.5):
        return plate[cut:, :]
    return plate


def deskew(plate: np.ndarray) -> np.ndarray:
    """Straighten a plate photographed at an angle."""
    if plate is None or plate.size == 0:
        return plate
    gray = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY) if plate.ndim == 3 else plate
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60,
                            minLineLength=gray.shape[1] // 3, maxLineGap=12)
    if lines is None:
        return plate

    # OpenCV 4 returns (N, 1, 4); OpenCV 5 returns (N, 4). Indexing `[:, 0]`
    # is right on one and silently wrong on the other, so reshape instead of
    # assuming. This repo pins <5, but the trap outlives the pin.
    try:
        segments = np.asarray(lines).reshape(-1, 4)
    except ValueError:
        return plate

    angles = [
        angle for angle in (
            float(np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1))))
            for x1, y1, x2, y2 in segments
        ) if abs(angle) < 30
    ]
    if not angles:
        return plate

    angle = float(np.median(angles))
    if abs(angle) < 0.7:
        return plate

    height, width = plate.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(plate, matrix, (width, height),
                          flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def enhance(plate: np.ndarray, target_height: int = 96) -> np.ndarray:
    """Straighten, upscale, equalise and sharpen a crop before reading it."""
    if plate is None or plate.size == 0:
        return plate
    img = deskew(plate)
    height, width = img.shape[:2]
    if 0 < height < target_height:
        scale = target_height / height
        img = cv2.resize(img, (int(width * scale), target_height),
                         interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(gray, (0, 0), 3)
    return cv2.addWeighted(gray, 1.6, blurred, -0.6, 0)


# --- character assembly ----------------------------------------------------

def _covers(a: _Det, b: _Det) -> float:
    """Overlap as a fraction of the smaller box — deliberately not IoU.

    Two readings of one glyph often differ in height: one tight on the
    numeral, one including the frame beneath it. IoU punishes that enough to
    let both through as separate characters. What actually identifies "same
    character" is that one box sits on top of the other, whatever their sizes.
    """
    ix = max(min(a.x2, b.x2) - max(a.x1, b.x1), 0.0)
    iy = max(min(a.y2, b.y2) - max(a.y1, b.y1), 0.0)
    smaller = min(a.area, b.area)
    return (ix * iy) / smaller if smaller else 0.0


def group_by_position(dets: list[_Det], overlap: float = 0.5) -> list[list[_Det]]:
    """One group per physical character, best reading first.

    YOLO suppresses overlaps class by class, so two different classes firing
    on one glyph both survive the model's own filtering. Grouping by where the
    boxes are, rather than trusting the list, is what turns one glyph into one
    character.
    """
    groups: list[list[_Det]] = []
    for det in sorted(dets, key=lambda d: -d.conf):
        for group in groups:
            if _covers(group[0], det) >= overlap:
                group.append(det)
                break
        else:
            groups.append([det])
    return sorted(groups, key=lambda g: g[0].cx)


def settle_letter_or_digit(slots: list[list[_Det]]) -> None:
    """Decide the letter/digit toss-ups by where they sit. In place.

    `٤/ع`, `٥/ه`, `٦/و` are the same shape and the model returns both readings
    with little between them. Confidence cannot settle it; the plate's layout
    can, because the number and the letters occupy separate blocks.

    Getting this wrong is expensive: a digit misfiled as a letter corrupts the
    letter block **and** shortens the number, so one bad glyph changes the
    whole plate.

    Only genuinely ambiguous slots move, and only when there is a block to
    move them into. Slots the model was sure about define where the blocks are.
    """
    digit_x = [s[0].cx for s in slots if all(d.glyph.isdigit() for d in s)]
    letter_x = [s[0].cx for s in slots if all(not d.glyph.isdigit() for d in s)]
    if not digit_x or not letter_x:
        return

    for slot in slots:
        kinds = {d.glyph.isdigit() for d in slot}
        if len(kinds) < 2:
            continue                                    # not torn
        x = slot[0].cx
        want_digit = (min(abs(x - dx) for dx in digit_x)
                      <= min(abs(x - lx) for lx in letter_x))
        if slot[0].glyph.isdigit() == want_digit:
            continue
        pick = next((d for d in slot if d.glyph.isdigit() == want_digit), None)
        if pick is not None:
            slot.insert(0, slot.pop(slot.index(pick)))


def read_order(items: list[tuple[float, str, float]]) -> tuple[list, list]:
    """Split into (letters right-to-left, digits left-to-right).

    **The bug this prevents is silent.** The letters are Arabic and read
    right-to-left; the number is a numeral and reads left-to-right, exactly as
    printed on the plate. Sorting everything one way reverses the digits, so
    `ط ن ٧١٢٦` returns as `طن 6217` — well formed, confidently scored, and
    matching nothing in the register. Only a palindromic number hides it.
    """
    letters = [i for i in items if not i[1].isdigit()]
    digits = [i for i in items if i[1].isdigit()]
    letters.sort(key=lambda t: -t[0])
    digits.sort(key=lambda t: t[0])
    return letters, digits


class PlateReader:
    """Both plate models, and the order they run in.

    Holds its own lock-free state: the models are called from one worker
    thread per camera, and `FeatureWorker` owns that threading.
    """

    def __init__(
        self,
        plate_weights: Path | str | None = None,
        char_weights: Path | str | None = None,
        device: str = "auto",
        imgsz: int = 640,
        conf: float = 0.35,
        iou: float = 0.45,
        half: bool = True,
        accelerate: bool = True,
    ) -> None:
        from vg.infer.persons import _resolve_device

        self.plate_weights = Path(
            plate_weights or REPO_DIR / "models" / "plate_detector.pt")
        self.char_weights = Path(
            char_weights or REPO_DIR / "models" / "char_detector.pt")
        for path, what in ((self.plate_weights, "plate"), (self.char_weights, "character")):
            if not path.is_file():
                raise FileNotFoundError(f"{what} weights not found: {path}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = _resolve_device(device)
        self.half = half and self.device != "cpu"

        self.accelerate = accelerate
        self.plates, self.plates_loaded, plate_form = load_model(
            self.plate_weights, imgsz, accelerate=accelerate, device=self.device)
        self.chars, self.chars_loaded, char_form = load_model(
            self.char_weights, imgsz, accelerate=accelerate, device=self.device)

        # One form for the pair. A half-accelerated reader is still limited by
        # its slower half, and System Health has one row to say it in.
        self.form = plate_form if plate_form == char_form else (
            f"{plate_form} + {char_form}")
        self.version = f"{self.plate_weights.stem}+{self.char_weights.stem}"

        # A model whose labels are already Arabic passes through untouched, so
        # a locally fine-tuned replacement need not adopt this scheme.
        names = getattr(self.chars, "names", {}) or {}
        self._needs_map = any(
            len(str(n)) > 1 and not str(n).isdigit() for n in names.values())
        self._names = names

        self._warm_up()

    def _warm_up(self) -> None:
        """First inference allocates and compiles. Do it now, not mid-stream."""
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        started = time.perf_counter()
        self.read_frame(blank)
        log.info(
            "plate reader ready on %s (%s, %s, warm-up %.0f ms)",
            self.device, self.plates_loaded.name, self.form,
            (time.perf_counter() - started) * 1000,
        )

    # -- the two passes -----------------------------------------------------

    def find(self, frame: np.ndarray) -> list[PlateBox]:
        """Plates in a BGR frame, largest first. At most five."""
        if frame is None or frame.size == 0:
            return []
        results = self.plates.predict(
            frame, device=self.device, imgsz=self.imgsz, conf=self.conf,
            iou=self.iou, quantize=16 if self.half else 32, verbose=False,
        )
        if not results:
            return []

        boxes = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            boxes.append(PlateBox(x1, y1, x2, y2, float(box.conf[0])))
        return sorted(boxes, key=lambda b: b.area, reverse=True)[:5]

    def _glyph(self, label: str) -> str:
        return label if not self._needs_map else CHAR_GLYPHS.get(label, "")

    def _fit(self, img: np.ndarray) -> np.ndarray:
        height, width = img.shape[:2]
        if width <= 0 or height <= 0 or width == READ_WIDTH:
            return img
        scale = READ_WIDTH / width
        return cv2.resize(
            img, (READ_WIDTH, max(int(height * scale), 8)),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )

    def read_plate(self, crop: np.ndarray) -> tuple[str, float, list]:
        """Read one prepared crop. Returns (canonical text, confidence, chars)."""
        if crop is None or crop.size == 0:
            return "", 0.0, []

        results = self.chars.predict(
            self._fit(crop), device=self.device, conf=ALT_CONF,
            quantize=16 if self.half else 32, verbose=False,
        )
        if not results:
            return "", 0.0, []

        dets: list[_Det] = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            glyph = self._glyph(str(self._names.get(int(box.cls[0]), "")))
            if not glyph:
                continue                    # a class this build does not know
            dets.append(_Det(x1, y1, x2, y2, glyph, float(box.conf[0])))
        if not dets:
            return "", 0.0, []

        slots = [s for s in group_by_position(dets) if s[0].conf >= DETECT_CONF]
        if not slots:
            return "", 0.0, []
        settle_letter_or_digit(slots)

        items = [(s[0].cx, s[0].glyph, s[0].conf) for s in slots]
        letters, digits = read_order(items)

        raw = ("".join(g for _, g, _ in letters) + " "
               + "".join(g for _, g, _ in digits)).strip()
        chars = [(g, c) for _, g, c in letters + digits]
        confidence = float(np.mean([c for _, c in chars])) if chars else 0.0
        return platetext.normalize(raw), confidence, chars

    def read_frame(self, frame: np.ndarray) -> list[PlateRead]:
        """Every plate in this frame, found and read. The whole feature.

        The character model runs **only** on crops the plate model returned,
        so an empty gate costs one pass rather than two.
        """
        reads: list[PlateRead] = []
        for box in self.find(frame):
            # **The raw colour crop, untouched.** This shipped stripping the
            # band and running `enhance()` over it, and read plates that were
            # close but wrong - a character or two off, on weights that read
            # the same plates correctly standalone.
            #
            # Both steps are for a text reader, and this is not one. A
            # character detector has no class for `مصر` and ignores the band
            # anyway, but it does use the whole plate for geometry, and on a
            # faded band the saturation scan eats into the digits above it -
            # the source project measured that at two lost reads in six.
            # `enhance()` is worse: it returns a single-channel CLAHE'd and
            # sharpened image, so a model trained on colour crops was reading
            # greyscale ones.
            #
            # `strip_band`, `deskew` and `enhance` are kept in this module
            # because they are correct for the reader they were written for.
            # Nothing in the plate path may call them. `test_platetext.py`
            # pins that.
            text, confidence, chars = self.read_plate(box.crop(frame))
            reads.append(PlateRead(box=box, text=text,
                                   confidence=confidence, chars=chars))
        return reads
