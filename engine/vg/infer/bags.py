"""Bag detection — the owner's trained model, on the GPU through ultralytics.

`models/bagbest.pt` is a **YOLO-World v2 medium, fine-tuned** from
`yolov8m-worldv2.pt` on the owner's merged dataset: 7 Aug 2026, 50 epochs,
28.4 M parameters. It carries eleven classes with the text features baked in
(`txt_feats (1, 11, 512)`) and the CLIP encoder stripped, so nothing here needs
a text encoder at run time. Own-validation mAP50 0.89, precision 0.90,
recall 0.82 — across all eleven classes, not bags alone.

**Three of eleven classes, filtered in the model call.** The full set is
backpack, laptop, jacket, key, handbag, suitcase, cup, book, shoes, cap,
glasses. Lost-bag search uses `backpack` (0), `handbag` (4) and `suitcase` (5)
and passes `classes=[0, 4, 5]` into `predict`, so the other eight never leave
the detector at all. That is not tidiness: `laptop` fires on every desk in the
building, and a lost-property search that offers somebody a laptop they did not
ask about is noise on the one screen that must not have any.

Verified on this machine that a `WorldModel` honours `classes=` the same way a
plain YOLO does — over 706 sampled frames of the two no-bag clips, the one
frame where a non-bag class fired returned nothing through the filter.

**Its accuracy on real bags is unmeasured**: there is no recorded clip with a
bag in it. What *is* measured, on footage with no bag, is that it produces
false positives which persistence alone cannot rule out — a black office chair
reads as `suitcase` at 0.88 for seconds at a time. See research D10. That is
why a hit here is presented as *a possible bag* for a person to judge, and
never as a finding.

Cost, measured on the RTX 2080 Max-Q with FP16, imgsz 640: **p50 28.1 ms,
p95 30.9 ms** a frame — roughly twice the knife model. Affordable only because
it runs while somebody is searching and not one millisecond longer.

**One instance, one thread today, but the lock stays.** `features/lostbag.py`
runs a single loop, so nothing contends right now. The lock lives here anyway,
inside `detect()`, for the reason it lives in `weapons.py`: a caller cannot
forget what it does not have to remember.

Every box leaves here as a fraction of the original frame, per the geometry
rule: pixels never cross the API.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Loading a YOLO-World checkpoint triggers a dependency check that will try to
# pip-install CLIP mid-run. Nothing here should ever install anything. This has
# to run before `from ultralytics import YOLO`, which is why it is at module
# level and not in the constructor.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = REPO_DIR / "models" / "bagbest.pt"

# Index -> name, for the three classes this feature is about. The index is the
# model's own, so this doubles as the `classes=` argument; keeping one mapping
# means the filter and the label can never disagree.
BAG_CLASSES: dict[int, str] = {0: "backpack", 4: "handbag", 5: "suitcase"}


@dataclass(frozen=True)
class DetectedBag:
    """One possible bag, in fractions of the frame."""

    x: float
    y: float
    w: float
    h: float
    confidence: float
    label: str

    @property
    def area(self) -> float:
        return self.w * self.h


class BagDetector:
    """YOLO-World bag detection, GPU-first.

    Falls back to CPU with a warning rather than failing: a slow search is
    worth more than none, and the console should say what it is running on.
    """

    def __init__(
        self,
        weights: Path | str | None = None,
        device: str = "auto",
        imgsz: int = 640,
        conf: float = 0.4,
        iou: float = 0.45,
        half: bool = True,
    ) -> None:
        from ultralytics import YOLO

        self.weights = Path(weights or DEFAULT_WEIGHTS)
        if not self.weights.is_file():
            raise FileNotFoundError(f"bag weights not found: {self.weights}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = _resolve_device(device)
        # FP16 halves the memory traffic and is free accuracy-wise for
        # detection, but only exists on the GPU.
        self.half = half and self.device != "cpu"

        self.model = YOLO(str(self.weights))
        self.version = self.weights.stem

        self._lock = threading.Lock()

        if self.device == "cpu":
            log.warning(
                "bag detection is running on the CPU. "
                "Install a CUDA build of torch to get ~28 ms a frame."
            )

        self._warm_up()

    def _warm_up(self) -> None:
        """First inference allocates and compiles; do it now, not mid-search.

        Without this the first frame of a search takes several hundred
        milliseconds, which on a sixty-second budget is a whole camera's worth
        of looks lost to start-up.
        """
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        started = time.perf_counter()
        self.detect(blank)
        log.info(
            "bag detector ready on %s (%s, warm-up %.0f ms)",
            self.device, self.weights.name, (time.perf_counter() - started) * 1000,
        )

    def detect(
        self, image: np.ndarray, min_confidence: float | None = None
    ) -> list[DetectedBag]:
        """Possible bags in a BGR frame, most confident first.

        `min_confidence` raises the bar for this call only. The model's own
        `conf` has already dropped everything below the configured threshold,
        so this is a second filter for a caller that wants to be surer than the
        configuration is — never a way to see more.
        """
        height, width = image.shape[:2]

        with self._lock:
            results = self.model.predict(
                image,
                device=self.device,
                imgsz=self.imgsz,
                conf=self.conf,
                iou=self.iou,
                half=self.half,
                # The eight other classes never leave the model.
                classes=list(BAG_CLASSES),
                verbose=False,
            )

        if not results:
            return []
        return self.bags_from(
            results[0].boxes.cpu(), width, height, min_confidence)

    @staticmethod
    def bags_from(boxes, width: int, height: int,
                  min_confidence: float | None = None) -> list[DetectedBag]:
        """Turn ultralytics boxes into fractions of the frame.

        Static and pure, like `WeaponDetector.weapons_from`: no model, no
        device, no lock. It is the half of detection that is safe to call from
        any thread.

        A class index outside `BAG_CLASSES` is dropped rather than labelled
        "bag". `classes=` in the model call already prevents it, and this is
        the belt to that pair of braces — a mislabelled cup is worse than a
        missing one.
        """
        if boxes is None:
            return []

        found: list[DetectedBag] = []
        for box in boxes:
            confidence = float(box.conf[0])
            if min_confidence is not None and confidence < min_confidence:
                continue
            class_id = int(box.cls[0]) if box.cls is not None else -1
            label = BAG_CLASSES.get(class_id)
            if label is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            fx = max(0.0, min(1.0, x1 / width))
            fy = max(0.0, min(1.0, y1 / height))
            found.append(DetectedBag(
                x=fx,
                y=fy,
                w=max(0.0, min(1.0 - fx, (x2 - x1) / width)),
                h=max(0.0, min(1.0 - fy, (y2 - y1) / height)),
                confidence=confidence,
                label=label,
            ))

        # Most confident first. A bag's size in frame says how close it is to
        # the camera, not how much it matters, so the score is all there is.
        found.sort(key=lambda d: d.confidence, reverse=True)
        return found

    def export_tensorrt(self, workspace_gb: int = 4) -> Path:
        """Build a TensorRT engine from the .pt, for this machine only.

        Takes several minutes and produces a file locked to this GPU and this
        TensorRT version. It will not load on the deployment workstation —
        rebuild it there. This is a deploy step, not an artifact.
        """
        log.info("building a TensorRT engine from %s (this takes minutes)", self.weights)
        path = self.model.export(
            format="engine",
            imgsz=self.imgsz,
            half=self.half,
            workspace=workspace_gb,
            device=0,
            verbose=False,
        )
        log.info("wrote %s", path)
        return Path(path)


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"
