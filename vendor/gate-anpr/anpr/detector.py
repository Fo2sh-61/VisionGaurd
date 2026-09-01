"""
Plate localisation: find the plate rectangle(s) in a frame.

Two backends:
  * "yolo"      - Ultralytics YOLO weights fine-tuned on plates. Production.
                  On Jetson, export to TensorRT first (see README) for ~4x speed.
  * "classical" - No model needed. Two proposal sources merged: character edge
                  density, and local-contrast bright panels. Weak in the rain
                  and at night, but it lets you install the system and start
                  collecting real images the same day, before any weights
                  exist. Also what the test suite runs on.

"auto" picks yolo when the weights file is present, otherwise classical.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Egyptian plates are roughly 35x17cm -> aspect ~2.06. Perspective from a
# gate-mounted camera stretches this, so accept a generous band.
MIN_ASPECT, MAX_ASPECT = 1.4, 4.5


@dataclass
class PlateBox:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float

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
        ph, pw = int(self.h * pad), int(self.w * pad)
        y1 = max(self.y1 - ph, 0)
        y2 = min(self.y2 + ph, frame.shape[0])
        x1 = max(self.x1 - pw, 0)
        x2 = min(self.x2 + pw, frame.shape[1])
        return frame[y1:y2, x1:x2]

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2


class PlateDetector:
    def __init__(self, backend: str = "auto", weights: str = "",
                 min_conf: float = 0.35, device: str = "auto") -> None:
        self.min_conf = min_conf
        self.backend = backend
        self._model = None
        if backend in ("auto", "yolo"):
            if weights and Path(weights).exists():
                try:
                    from ultralytics import YOLO  # noqa: PLC0415

                    self._model = YOLO(weights)
                    if device and device != "auto":
                        self._model.to(device)
                    self.backend = "yolo"
                    log.info("plate detector: YOLO weights %s", weights)
                except Exception as exc:  # pragma: no cover
                    log.warning("YOLO unavailable (%s), using classical", exc)
                    self.backend = "classical"
            else:
                if backend == "yolo":
                    log.warning("weights %s not found, falling back", weights)
                self.backend = "classical"
                log.info("plate detector: classical (no weights yet)")

    # -- public -----------------------------------------------------------

    def detect(self, frame: np.ndarray) -> list[PlateBox]:
        if frame is None or frame.size == 0:
            return []
        boxes = (self._detect_yolo(frame) if self.backend == "yolo"
                 else self._detect_classical(frame))
        return sorted(boxes, key=lambda b: b.area, reverse=True)[:5]

    # -- backends ---------------------------------------------------------

    def _detect_yolo(self, frame: np.ndarray) -> list[PlateBox]:  # pragma: no cover
        res = self._model.predict(frame, conf=self.min_conf, verbose=False)[0]
        out = []
        for b in res.boxes:
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            out.append(PlateBox(x1, y1, x2, y2, float(b.conf[0])))
        return out

    def _detect_classical(self, frame: np.ndarray) -> list[PlateBox]:
        """
        Two independent proposal sources, merged.

        Egyptian plates give two strong classical signals: dense vertical edges
        from the characters, and a bright near-white panel. Running both and
        merging catches plates that either one alone misses (edges fail on a
        blurred plate, brightness fails on a white car).
        """
        gray = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if frame.ndim == 3 else frame)
        h, w = gray.shape[:2]
        smooth = cv2.bilateralFilter(gray, 7, 60, 60)
        frame_area = h * w

        out: list[PlateBox] = []
        out += self._edge_proposals(smooth, frame_area, w)
        out += self._bright_proposals(smooth, frame_area)
        return _nms(out, 0.3)

    def _edge_proposals(self, gray: np.ndarray, frame_area: int,
                        w: int) -> list[PlateBox]:
        grad = cv2.Sobel(gray, cv2.CV_8U, 1, 0, ksize=3)
        _, th = cv2.threshold(grad, 0, 255,
                              cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        kern = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 40, 9), 3))
        closed = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kern)
        closed = cv2.morphologyEx(
            closed, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

        # RETR_LIST, not RETR_EXTERNAL: a plate sits inside the car's own
        # outline, so an "external only" search throws the plate away with it.
        cnts, _ = cv2.findContours(closed, cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_SIMPLE)
        out: list[PlateBox] = []
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            if ch < 12 or cw < 30:
                continue
            aspect = cw / float(ch)
            if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
                continue
            area = cw * ch
            if area < frame_area * 0.0006 or area > frame_area * 0.35:
                continue
            fill = cv2.countNonZero(closed[y:y + ch, x:x + cw]) / float(area)
            if fill < 0.30:
                continue
            aspect_score = 1.0 - min(abs(aspect - 2.1) / 2.4, 1.0)
            conf = round(float(0.45 * aspect_score + 0.55 * min(fill, 1.0)), 3)
            if conf >= self.min_conf:
                out.append(PlateBox(x, y, x + cw, y + ch, conf))
        return out

    def _bright_proposals(self, gray: np.ndarray,
                          frame_area: int) -> list[PlateBox]:
        """
        Bright rectangular panels — the plate body itself.

        Compared against a heavily blurred copy of the frame rather than a
        global threshold. A global threshold fails whenever the car itself is
        pale: the body and the plate land in the same bright blob and the plate
        disappears. Local contrast keeps the plate separate from the panel it
        is bolted to.
        """
        sigma = max(gray.shape[1] // 40, 9)
        bg = cv2.GaussianBlur(gray, (0, 0), sigma)
        ratio = gray.astype(np.float32) / (bg.astype(np.float32) + 1.0)
        bright = ((ratio > 1.10) & (gray > 90)).astype(np.uint8) * 255
        bright = cv2.morphologyEx(
            bright, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (11, 5)))

        cnts, _ = cv2.findContours(bright, cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_SIMPLE)
        out: list[PlateBox] = []
        for c in cnts:
            x, y, cw, ch = cv2.boundingRect(c)
            if ch < 12 or cw < 30:
                continue
            aspect = cw / float(ch)
            if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
                continue
            area = cw * ch
            if area < frame_area * 0.0006 or area > frame_area * 0.35:
                continue
            solidity = cv2.contourArea(c) / float(area)
            if solidity < 0.55:
                continue
            # A plate has dark characters on it; a blank bright panel does not.
            patch = gray[y:y + ch, x:x + cw]
            local = float(np.median(patch))
            dark_ratio = float((patch < local * 0.6).mean())
            if not (0.02 < dark_ratio < 0.6):
                continue
            aspect_score = 1.0 - min(abs(aspect - 2.1) / 2.4, 1.0)
            conf = round(float(0.4 * aspect_score + 0.3 * solidity
                               + 0.3 * min(dark_ratio * 4, 1.0)), 3)
            if conf >= self.min_conf:
                out.append(PlateBox(x, y, x + cw, y + ch, conf))
        return out


def _nms(boxes: list[PlateBox], iou_thresh: float) -> list[PlateBox]:
    """
    Suppress overlapping proposals.

    Plain IoU is not enough here: the two proposal sources often return the
    whole plate AND its left/right halves. A small box sitting inside a big one
    has low IoU, so it would survive and the tracker would treat one plate as
    three vehicles. Containment is therefore checked as well.

    Ordering stays confidence-first: sorting by area instead would let a large
    low-confidence blob (a car body that happens to be plate-shaped) swallow
    the real plate inside it.
    """
    boxes = sorted(boxes, key=lambda b: b.conf, reverse=True)
    keep: list[PlateBox] = []
    for b in boxes:
        if any(_iou(b, k) >= iou_thresh or _containment(b, k) >= 0.7
               for k in keep):
            continue
        keep.append(b)
    return keep


def _containment(inner: PlateBox, outer: PlateBox) -> float:
    """Fraction of `inner` that lies inside `outer`."""
    ix1, iy1 = max(inner.x1, outer.x1), max(inner.y1, outer.y1)
    ix2, iy2 = min(inner.x2, outer.x2), min(inner.y2, outer.y2)
    inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    return inter / inner.area if inner.area else 0.0


def _iou(a: PlateBox, b: PlateBox) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(ix2 - ix1, 0), max(iy2 - iy1, 0)
    inter = iw * ih
    union = a.area + b.area - inter
    return inter / union if union else 0.0


# --- image prep for the reader -------------------------------------------------

def deskew(plate_img: np.ndarray) -> np.ndarray:
    """Straighten a plate photographed at an angle. Helps OCR a lot."""
    if plate_img is None or plate_img.size == 0:
        return plate_img
    gray = (cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
            if plate_img.ndim == 3 else plate_img)
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 60,
                            minLineLength=gray.shape[1] // 3, maxLineGap=12)
    if lines is None:
        return plate_img
    # OpenCV 4 returns HoughLinesP as (N, 1, 4); OpenCV 5 returns (N, 4).
    # Indexing lines[:, 0] is correct on one and silently wrong on the other,
    # so reshape instead of assuming a layout.
    try:
        segments = np.asarray(lines).reshape(-1, 4)
    except ValueError:
        return plate_img
    angles = []
    for x1, y1, x2, y2 in segments:
        ang = np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1)))
        if abs(ang) < 30:
            angles.append(ang)
    if not angles:
        return plate_img
    angle = float(np.median(angles))
    if abs(angle) < 0.7:
        return plate_img
    h, w = plate_img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(plate_img, m, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def enhance(plate_img: np.ndarray, target_h: int = 96) -> np.ndarray:
    """Upscale, equalise and sharpen a plate crop before reading it."""
    if plate_img is None or plate_img.size == 0:
        return plate_img
    img = deskew(plate_img)
    h, w = img.shape[:2]
    if h < target_h and h > 0:
        scale = target_h / h
        img = cv2.resize(img, (int(w * scale), target_h),
                         interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    return cv2.addWeighted(gray, 1.6, blur, -0.6, 0)


def strip_blue_band(plate_img: np.ndarray) -> np.ndarray:
    """
    Remove the coloured 'مصر / EGYPT' strip at the top of Egyptian plates.

    The band carries no registration information and reliably confuses OCR,
    which reads "مصر" as extra letters. We detect the band by colour saturation
    in the top third rather than cropping a fixed percentage, so it still works
    on taxis (orange), trucks (red) and government plates (grey).
    """
    if plate_img is None or plate_img.size == 0 or plate_img.ndim != 3:
        return plate_img
    h, w = plate_img.shape[:2]
    if h < 20:
        return plate_img
    hsv = cv2.cvtColor(plate_img, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].mean(axis=1)          # mean saturation per row
    val = hsv[:, :, 2].mean(axis=1)
    limit = int(h * 0.55)
    body_sat = float(np.median(sat[limit:])) if h > limit else float(sat.mean())
    cut = 0
    for y in range(limit):
        coloured = sat[y] > max(body_sat * 1.8, 55)
        dark = val[y] < 90
        if coloured or dark:
            cut = y + 1
        elif cut and y - cut > 3:
            break
    if 0 < cut < int(h * 0.5):
        return plate_img[cut:, :]
    return plate_img
