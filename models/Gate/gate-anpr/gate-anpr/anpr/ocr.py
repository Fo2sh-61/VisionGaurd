"""
Reading the characters off a plate crop.

Egyptian plates are the hard case: Arabic script, Arabic-Indic digits, and a
character set whose glyphs differ from ordinary printed Arabic. Generic OCR
does badly. The published work on Egyptian ANPR consistently lands on the same
answer: treat each character as an object-detection class rather than running
text OCR, and a small CNN/YOLO trained on plate glyphs beats general OCR by a
wide margin (~99% vs ~94% in the literature).

So there are three backends:

  yolo_chars  Production. A YOLO model with one class per allowed character.
              Boxes are sorted right-to-left (Arabic reading order) and the
              class labels concatenated. Train it on your own site images with
              tools/train_char_detector.py.

  easyocr     Zero-training fallback so the system does something useful on day
              one. Slower and less accurate; fine while you collect data.

  stub        Deterministic reader used by the test suite and by the synthetic
              plate generator, so pipeline logic can be tested without weights.

All backends return a ReadResult; the pipeline never cares which ran.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import plate_text
from .detector import enhance, strip_blue_band

log = logging.getLogger(__name__)


@dataclass
class ReadResult:
    text: str = ""                                  # canonical plate key
    confidence: float = 0.0                         # 0-1, OCR only
    chars: list[tuple[str, float]] = field(default_factory=list)
    backend: str = ""

    @property
    def plausibility(self) -> float:
        return plate_text.plausibility(self.text)

    @property
    def score(self) -> float:
        """Confidence adjusted by how plausible the plate looks."""
        return round(self.confidence * self.plausibility, 4)

    def __bool__(self) -> bool:
        return bool(self.text)


class PlateReader:
    """Facade over whichever backend is available."""

    def __init__(self, backend: str = "auto", weights: str = "",
                 device: str = "auto", lang: str = "ar") -> None:
        self.backend = backend
        self._impl = None
        self._device = device
        if backend in ("auto", "yolo_chars") and weights and Path(weights).exists():
            try:
                self._impl = _YoloCharReader(weights, device)
                self.backend = "yolo_chars"
            except Exception as exc:  # pragma: no cover
                log.warning("char detector failed to load: %s", exc)
        if self._impl is None and backend in ("auto", "easyocr"):
            try:
                self._impl = _EasyOcrReader(lang)
                self.backend = "easyocr"
            except Exception as exc:
                if backend == "easyocr":
                    raise
                log.info("easyocr not installed (%s)", exc)
        if self._impl is None:
            self._impl = _StubReader()
            self.backend = "stub"
            log.warning(
                "No OCR backend available - running in STUB mode. "
                "Install easyocr, or train models/char_detector.pt, "
                "before using this at a real gate."
            )

    def read(self, plate_img: np.ndarray,
             context: np.ndarray | None = None) -> ReadResult:
        """
        `context` is the full frame the crop came from. Real backends ignore it;
        the stub reader uses it to find the synthetic ground-truth marker.
        """
        if plate_img is None or getattr(plate_img, "size", 0) == 0:
            return ReadResult(backend=self.backend)
        # Cutting the "مصر / EGYPT" strip helps a general text reader, which
        # would otherwise try to read it as part of the registration. It hurts
        # a character-detection model, which has no class for those glyphs and
        # ignores them anyway, but does use the whole plate for geometry — and
        # on a faded or damaged band the row scan eats into the digits above.
        # Measured on the sample plates: stripping costs two of six reads.
        body = (plate_img if getattr(self._impl, "wants_full_plate", False)
                else strip_blue_band(plate_img))
        res = self._impl.read(body, context)
        res.backend = self.backend
        res.text = plate_text.normalize(res.text)
        return res


# --- backends -----------------------------------------------------------------

# Character models are trained with ASCII class names — a model cannot carry
# Arabic labels through a YOLO .yaml safely — so the weights emit transliterated
# names like "alif", "baa", "7aa". Mapping them back is not cosmetic: without
# it the reader returns "alifbaajeem123" and normalize() throws all of it away.
#
# The map covers all 28 Arabic letters plus the ten digits (38 classes), which
# is exactly what models/char_detector.pt declares. Capitalisation is the
# trained convention for the emphatic pair: Taa=ط vs taa=ت, Thaa=ظ vs thaa=ث,
# and "7aa" is chat-alphabet ح. Keep this in sync with the weights, not with
# any general Arabic transliteration scheme.
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


class _YoloCharReader:  # pragma: no cover - needs trained weights
    """One YOLO class per plate character; sort boxes into reading order."""

    wants_full_plate = True

    def __init__(self, weights: str, device: str = "auto") -> None:
        from ultralytics import YOLO  # noqa: PLC0415

        self.model = YOLO(weights)
        if device and device != "auto":
            self.model.to(device)
        self.names = self.model.names
        # A model whose labels are already Arabic passes through untouched, so
        # a locally fine-tuned replacement does not have to adopt this scheme.
        self._needs_map = any(len(str(n)) > 1 and not str(n).isdigit()
                              for n in self.names.values())

    def _glyph(self, label: str) -> str:
        if not self._needs_map:
            return label
        return CHAR_GLYPHS.get(label, "")

    # Every crop is read at one fixed width, whatever size it arrived at.
    #
    # This is the highest-leverage line in the reader. Accuracy on the sample
    # plates is flat and correct from ~240px upward and falls off steadily
    # below it — 6/6 at 320px against 3/6 at 80px — because a distant plate
    # reaches the model as a handful of pixels per glyph unless it is scaled
    # up first. Normalising here is what lets one camera cover a range of
    # distances instead of only the one it happens to be framed for: at 720p a
    # plate is ~176px at 2m and ~117px at 3m, and both are upscaled to the
    # size the model reads best.
    #
    # Larger is not better without limit — it is simply flat — so this stays
    # at the low end of the good range to keep inference cheap.
    READ_WIDTH = 320

    def _fit(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w <= 0 or h <= 0 or w == self.READ_WIDTH:
            return img
        scale = self.READ_WIDTH / w
        return cv2.resize(img, (self.READ_WIDTH, max(int(h * scale), 8)),
                          interpolation=cv2.INTER_AREA if scale < 1
                          else cv2.INTER_CUBIC)

    # A glyph must reach DETECT_CONF to be part of the plate at all. Weaker
    # boxes are still collected, but only as *alternative readings of a
    # character that was already found* - never as extra characters. That is
    # what makes the low floor safe: it adds nothing to the plate, it only
    # gives the disambiguation below something to choose from.
    DETECT_CONF = 0.25
    ALT_CONF = 0.10

    def read(self, img: np.ndarray, context=None) -> ReadResult:
        res = self.model.predict(self._fit(img), conf=self.ALT_CONF,
                                 verbose=False)[0]
        dets = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            glyph = self._glyph(str(self.names[int(b.cls[0])]))
            if not glyph:                 # class this build does not know
                continue
            dets.append(_Det(x1, y1, x2, y2, glyph, float(b.conf[0])))
        if not dets:
            return ReadResult()

        # One physical character can come back as several boxes. YOLO removes
        # overlaps class by class, so two *different* classes firing on the
        # same glyph both survive - which is where "مجببع" came from for a
        # plate reading مجب. Grouping by position instead of trusting the
        # box list is what makes one glyph produce one character.
        slots = _group_by_position(dets)
        slots = [s for s in slots if s[0].conf >= self.DETECT_CONF]
        if not slots:
            return ReadResult()
        _settle_letter_or_digit(slots)

        items = [(s[0].cx, s[0].glyph, s[0].conf) for s in slots]

        # Reading order is NOT uniform across the plate, and getting it wrong is
        # silent: the letters are Arabic and run right-to-left, but the number
        # is a numeral and runs left-to-right, exactly as printed. Sorting every
        # glyph right-to-left reverses the digits, so ط ن ٧١٢٦ comes back as
        # "طن 6217" - a plate that looks well-formed, scores well, and matches
        # nothing in the registry. Only palindromic numbers hide the bug.
        letters = [i for i in items if not i[1].isdigit()]
        digits = [i for i in items if i[1].isdigit()]
        letters.sort(key=lambda t: -t[0])          # right -> left
        digits.sort(key=lambda t: t[0])            # left  -> right

        ordered = letters + digits
        chars = [(glyph, c) for _, glyph, c in ordered]
        # normalize() splits letters from digits itself, but emit the canonical
        # separator anyway so the raw text is readable in the diagnostics panel.
        text = ("".join(g for _, g, _ in letters) + " "
                + "".join(g for _, g, _ in digits)).strip()
        conf = float(np.mean([c for _, c in chars]))
        return ReadResult(text=text, confidence=conf, chars=chars)


@dataclass
class _Det:
    """One character box proposed by the model."""

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


def _covers(a: _Det, b: _Det) -> float:
    """Overlap as a fraction of the smaller box - not IoU.

    Two readings of the same glyph often differ in box height (one tight on the
    numeral, one including the frame below it), and IoU punishes that enough to
    let both through. What actually identifies "same character" is that one box
    sits on top of the other, whatever their sizes.
    """
    ix = max(min(a.x2, b.x2) - max(a.x1, b.x1), 0.0)
    iy = max(min(a.y2, b.y2) - max(a.y1, b.y1), 0.0)
    small = min(a.area, b.area)
    return (ix * iy) / small if small else 0.0


def _group_by_position(dets: list[_Det], overlap: float = 0.5
                       ) -> list[list[_Det]]:
    """Collapse the box list into one group per character, best reading first."""
    groups: list[list[_Det]] = []
    for d in sorted(dets, key=lambda d: -d.conf):
        for g in groups:
            if _covers(g[0], d) >= overlap:
                g.append(d)
                break
        else:
            groups.append([d])
    return sorted(groups, key=lambda g: g[0].cx)


def _settle_letter_or_digit(slots: list[list[_Det]]) -> None:
    """
    Decide the letter/digit toss-ups by where they sit on the plate.

    ٤ and ع are the same shape, as are ٥/ه and ٦/و, and the model returns
    both readings for one glyph with nothing much between them. Confidence
    cannot settle it, but the plate's layout can: an Egyptian plate keeps the
    number in one block and the letters in the other, so a character sitting
    among the digits is a digit whatever the model preferred. Getting this
    wrong is expensive - a digit misfiled as a letter corrupts the letter
    group AND shortens the number, so one bad glyph changes the whole plate.

    Slots the model was not torn about define the two blocks; only genuinely
    ambiguous slots are moved, and only when there is a block to move them to.
    """
    digit_x = [s[0].cx for s in slots
               if all(d.glyph.isdigit() for d in s)]
    letter_x = [s[0].cx for s in slots
                if all(not d.glyph.isdigit() for d in s)]
    if not digit_x or not letter_x:
        return
    for slot in slots:
        kinds = {d.glyph.isdigit() for d in slot}
        if len(kinds) < 2:                       # model was not torn
            continue
        x = slot[0].cx
        want_digit = (min(abs(x - dx) for dx in digit_x)
                      <= min(abs(x - lx) for lx in letter_x))
        if slot[0].glyph.isdigit() == want_digit:
            continue
        pick = next((d for d in slot if d.glyph.isdigit() == want_digit), None)
        if pick is not None:
            slot.insert(0, slot.pop(slot.index(pick)))


class _EasyOcrReader:
    """Off-the-shelf Arabic OCR. Works with no training; accept ~90% accuracy."""

    def __init__(self, lang: str = "ar") -> None:
        import easyocr  # noqa: PLC0415

        self.reader = easyocr.Reader([lang, "en"], gpu=True, verbose=False)

    def read(self, img: np.ndarray, context=None) -> ReadResult:
        prepped = enhance(img)
        allow = plate_text.LETTERS + plate_text.AR_DIGITS + "0123456789"
        out = self.reader.readtext(prepped, allowlist=allow, detail=1,
                                   paragraph=False)
        if not out:
            return ReadResult()
        # Right-to-left ordering by box centre.
        out.sort(key=lambda r: -np.mean([p[0] for p in r[0]]))
        text = "".join(r[1] for r in out)
        conf = float(np.mean([r[2] for r in out]))
        return ReadResult(text=text, confidence=conf)


class _StubReader:
    """
    Test backend.

    Reads the plate text that tools/make_test_plates.py bakes into the bottom
    row of a synthetic image as a tiny binary barcode. Lets the whole pipeline
    (tracking, voting, dedupe, DB, alerts, visits) be tested deterministically
    with no model weights.
    """

    def read(self, img: np.ndarray, context=None) -> ReadResult:
        text = decode_marker(img)
        if not text and context is not None:
            # The marker lives on the bottom row of the full frame, not on the
            # plate crop, so fall back to the frame the crop came from.
            text = decode_marker(context)
        if not text:
            return ReadResult()
        return ReadResult(text=text, confidence=0.97)


# --- synthetic marker codec (shared with tools/make_test_plates.py) ------------

MARKER_ROWS = 4


def encode_marker(text: str, width: int) -> np.ndarray:
    """Encode text as a black/white bit strip, MARKER_ROWS pixels tall."""
    data = text.encode("utf-8")
    bits = [int(b) for byte in data for b in f"{byte:08b}"]
    bits = [1, 1, 1, 1, 1, 1, 1, 1, 0] + bits  # sync preamble
    strip = np.full((MARKER_ROWS, width), 255, dtype=np.uint8)
    cell = max(width // max(len(bits), 1), 1)
    for i, bit in enumerate(bits):
        x = i * cell
        if x + cell > width:
            break
        strip[:, x:x + cell] = 0 if bit else 255
    return strip


def decode_marker(img: np.ndarray) -> str:
    if img is None or img.size == 0 or img.shape[0] < MARKER_ROWS:
        return ""
    gray = img if img.ndim == 2 else img[:, :, 0]
    strip = gray[-MARKER_ROWS:, :]
    row = (strip.mean(axis=0) < 128).astype(int)
    if not row.any():
        return ""
    # Find cell size from the 8-bit sync preamble of 1s followed by a 0.
    lead = 0
    while lead < len(row) and row[lead] == 1:
        lead += 1
    if lead < 8:
        return ""
    cell = max(lead // 8, 1)
    bits = [int(row[min(i * cell + cell // 2, len(row) - 1)])
            for i in range(len(row) // cell)]
    bits = bits[9:]                                    # drop preamble
    bits = bits[: (len(bits) // 8) * 8]
    data = bytes(int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8))
    try:
        return data.decode("utf-8").rstrip("\x00").strip()
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="ignore").rstrip("\x00").strip()
