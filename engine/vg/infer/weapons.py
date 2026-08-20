"""Knife detection — a trained detector, decoded here rather than borrowed.

`models/knife detection/knife-finetuned-v3.onnx` is a real fine-tuned YOLOv8,
one class, `knife`, trained 13 Aug 2026 on a combined public + on-site dataset.
It replaces the zero-shot prompted model that also looked for scissors and
screwdrivers, which every classroom and maintenance cupboard contains.

**Why this file decodes the raw tensor instead of calling ultralytics.**

The obvious implementation is `YOLO(path).predict(frame)`, three lines. It is
also wrong here, and quietly so. The model was exported with ultralytics
8.4.118; the pinned runtime is 8.4.7, and that version misreads this file's
output layout — it treats the four box-coordinate rows as four detections and
returns them with "confidences" of 90 and 100. The result is four knife alerts
on every frame, including a flat grey image and an empty corridor, on the one
feature in the product where a false alarm costs the most trust.

The raw tensor is fine. Row 4 peaks at 0.002 on random noise: the model finds
nothing, correctly. Only the decode was broken. So the decode lives here, where
it is pinned to the model's documented layout, is unit-tested against known
inputs, and cannot change under us when a dependency moves.

Output layout, `[1, 4 + classes, 8400]`:

    rows 0-3   cx, cy, w, h   in letterboxed input pixels (not fractions)
    row  4+    class score     already sigmoid'd, one row per class

Every box leaves here as a fraction of the original frame, per the geometry
rule: pixels never cross the API.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = REPO_DIR / "models" / "knife detection" / "knife-finetuned-v3.onnx"

# The model is single-class. Kept as a tuple so a future multi-class export
# needs a config change here and nowhere else.
CLASS_NAMES: tuple[str, ...] = ("knife",)


@dataclass(frozen=True)
class DetectedWeapon:
    """One possible weapon, in fractions of the frame."""

    x: float
    y: float
    w: float
    h: float
    confidence: float
    label: str

    @property
    def area(self) -> float:
        return self.w * self.h


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    """Resize keeping aspect ratio, pad the remainder grey.

    Returns the canvas plus the scale and padding needed to map a box back to
    the original frame. Stretching instead would distort a knife's aspect
    ratio, which is most of what distinguishes it from a pen.
    """
    height, width = image.shape[:2]
    scale = min(size / height, size / width)
    new_w, new_h = int(round(width * scale)), int(round(height * scale))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)  # ultralytics' grey
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


class WeaponDetector:
    """Knife detection over ONNX Runtime, GPU-first with an honest fallback.

    A CPU fallback is a working detector, roughly an order of magnitude slower.
    It is better than no detection, but it is never silent: the reason goes to
    the log and the caller can read `device` to put it on System Health.
    """

    def __init__(
        self,
        weights: Path | str | None = None,
        device: str = "auto",
        imgsz: int = 640,
        conf: float = 0.35,
        iou: float = 0.45,
    ) -> None:
        import onnxruntime as ort

        self.weights = Path(weights or DEFAULT_WEIGHTS)
        if not self.weights.is_file():
            raise FileNotFoundError(f"weapon weights not found: {self.weights}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou

        available = ort.get_available_providers()
        wanted: list[str]
        if device == "cpu":
            wanted = ["CPUExecutionProvider"]
        else:
            wanted = [p for p in ("CUDAExecutionProvider", "TensorrtExecutionProvider")
                      if p in available]
            wanted.append("CPUExecutionProvider")

        self.session = ort.InferenceSession(str(self.weights), providers=wanted)
        self.device = "cuda" if "CUDAExecutionProvider" in self.session.get_providers() else "cpu"
        self.version = self.weights.stem

        self._input = self.session.get_inputs()[0].name
        shape = self.session.get_inputs()[0].shape
        # The export is static: batch 1, 640x640. Trusting `imgsz` blindly
        # against a static graph fails inside the session with a shape error
        # that reads like a corrupt file.
        if isinstance(shape[-1], int) and shape[-1] != imgsz:
            log.warning(
                "weapon model expects %dx%d but imgsz=%d was requested; using %d",
                shape[-1], shape[-2], imgsz, shape[-1],
            )
            self.imgsz = int(shape[-1])

        if self.device == "cpu":
            log.warning(
                "knife detection is running on the CPU. Install onnxruntime-gpu "
                "to use the GPU; on CPU this is roughly 10x slower and will not "
                "keep up with many cameras."
            )

        self._warm_up()

    def _warm_up(self) -> None:
        """First inference allocates; do it now, not on the first real frame."""
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        started = time.perf_counter()
        self.detect(blank)
        log.info(
            "weapon detector ready on %s (%s, warm-up %.0f ms)",
            self.device, self.weights.name, (time.perf_counter() - started) * 1000,
        )

    def detect(self, image: np.ndarray, min_confidence: float | None = None) -> list[DetectedWeapon]:
        """Possible weapons in a BGR frame, most confident first."""
        if image is None or image.size == 0:
            return []

        threshold = self.conf if min_confidence is None else min_confidence
        height, width = image.shape[:2]

        canvas, scale, pad_x, pad_y = _letterbox(image, self.imgsz)
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.ascontiguousarray(blob.transpose(2, 0, 1)[None])  # NCHW

        output = self.session.run(None, {self._input: blob})[0]

        # [1, 4+nc, 8400] -> [8400, 4+nc]. Without this transpose the rows are
        # read as detections, which is the exact bug this module exists to
        # avoid.
        predictions = output[0].T
        boxes_xywh = predictions[:, :4]
        scores_all = predictions[:, 4:]

        class_ids = scores_all.argmax(axis=1)
        scores = scores_all.max(axis=1)

        keep = scores >= threshold
        if not keep.any():
            return []

        boxes_xywh = boxes_xywh[keep]
        scores = scores[keep]
        class_ids = class_ids[keep]

        # centre form -> corner form, still in letterboxed pixels
        cx, cy, bw, bh = boxes_xywh.T
        x1 = cx - bw / 2
        y1 = cy - bh / 2

        # cv2's NMS wants integer xywh boxes in a single coordinate space; any
        # consistent space works, so this runs before the un-letterbox.
        rects = np.stack([x1, y1, bw, bh], axis=1).astype(np.int32).tolist()
        indices = cv2.dnn.NMSBoxes(rects, scores.astype(np.float32).tolist(),
                                   float(threshold), float(self.iou))
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        found: list[DetectedWeapon] = []
        for i in indices:
            # undo the padding, then the scale, to land back on the original
            ox1 = (x1[i] - pad_x) / scale
            oy1 = (y1[i] - pad_y) / scale
            ow = bw[i] / scale
            oh = bh[i] / scale

            fx = max(0.0, min(1.0, ox1 / width))
            fy = max(0.0, min(1.0, oy1 / height))
            found.append(
                DetectedWeapon(
                    x=fx,
                    y=fy,
                    w=max(0.0, min(1.0 - fx, ow / width)),
                    h=max(0.0, min(1.0 - fy, oh / height)),
                    confidence=float(scores[i]),
                    label=CLASS_NAMES[int(class_ids[i])] if int(class_ids[i]) < len(CLASS_NAMES) else "weapon",
                )
            )

        found.sort(key=lambda d: d.confidence, reverse=True)
        return found
