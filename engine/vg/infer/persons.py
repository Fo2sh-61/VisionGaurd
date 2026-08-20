"""Person detection — the real headcount.

Face detection cannot count people. Someone facing away, wearing a hood, or
standing behind another person has no visible face, so a face-based count
silently under-reports exactly when a room is crowded. "People in frame" needs
a body detector.

This wraps YOLO (COCO class 0) and runs it on the GPU. Measured on this
machine, 640x480:

    CPU        161 ms/frame     6 fps
    CUDA        23 ms/frame    42 fps      <- 7x, no export step
    TensorRT     ~12 ms/frame   80 fps      after a one-off engine build

TensorRT is the fastest but its engine file is compiled for one GPU and one
TensorRT version, so it is a build artifact for a specific machine, never
something to archive. `.pt` stays the source of truth; the engine is rebuilt
wherever it runs. See models/README.md.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Loading a YOLO-World checkpoint triggers a dependency check that will try to
# pip-install CLIP mid-run. Nothing here should ever install anything.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO_DIR = Path(__file__).resolve().parents[3]
COCO_PERSON_CLASS = 0


@dataclass(frozen=True)
class DetectedPerson:
    """One person, in fractions of the frame."""

    x: float
    y: float
    w: float
    h: float
    confidence: float

    @property
    def area(self) -> float:
        return self.w * self.h


class PersonDetector:
    """YOLO person detection, GPU-first.

    Falls back to CPU with a warning rather than failing: a slow headcount is
    worth more than none, and the console should say what it is running on.
    """

    def __init__(
        self,
        weights: Path | str | None = None,
        device: str = "auto",
        imgsz: int = 640,
        conf: float = 0.35,
        iou: float = 0.45,
        half: bool = True,
    ) -> None:
        from ultralytics import YOLO

        self.weights = Path(weights or REPO_DIR / "models" / "yolov8s.pt")
        if not self.weights.is_file():
            raise FileNotFoundError(f"person weights not found: {self.weights}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = _resolve_device(device)
        # FP16 halves the memory traffic and is free accuracy-wise for
        # detection, but only exists on the GPU.
        self.half = half and self.device != "cpu"

        self.model = YOLO(str(self.weights))
        self.version = self.weights.stem

        if self.device == "cpu":
            log.warning(
                "person detection is running on the CPU (~160 ms/frame). "
                "Install a CUDA build of torch to get ~23 ms."
            )

        self._warm_up()

    def _warm_up(self) -> None:
        """First inference allocates and compiles; do it now, not mid-stream.

        Without this the first real frame takes several hundred milliseconds
        and looks like a stall on the very first person who walks past.
        """
        blank = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        started = time.perf_counter()
        self.detect(blank)
        log.info(
            "person detector ready on %s (%s, warm-up %.0f ms)",
            self.device, self.weights.name, (time.perf_counter() - started) * 1000,
        )

    def raw_boxes(self, image: np.ndarray):
        """The ultralytics `Boxes` for this frame, or None.

        Exposed so tracking can reuse the detection that already happened
        instead of running the model a second time — §3.4's first rule is that
        the person pass runs once per frame and fans out. `Boxes` is what
        ByteTrack consumes, so it is handed over unconverted; everything else
        goes through `detect()` and gets fractions.
        """
        results = self.model.predict(
            image,
            device=self.device,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            half=self.half,
            classes=[COCO_PERSON_CLASS],
            verbose=False,
        )
        if not results:
            return None
        # ByteTrack does its association in NumPy, and a CUDA tensor cannot be
        # converted without an explicit copy to host memory. Doing it here
        # rather than in the tracker keeps the device detail with the model
        # that chose the device.
        return results[0].boxes.cpu()

    def detect(self, image: np.ndarray, min_area: float = 0.0) -> list[DetectedPerson]:
        """People in a BGR frame, largest first.

        `min_area` drops boxes smaller than a fraction of the frame — useful on
        a wide view where distant blobs are noise rather than countable people.
        """
        boxes = self.raw_boxes(image)
        height, width = image.shape[:2]
        return self.people_from(boxes, width, height, min_area)

    @staticmethod
    def people_from(boxes, width: int, height: int,
                    min_area: float = 0.0) -> list[DetectedPerson]:
        """Turn ultralytics boxes into fractions of the frame.

        Split out of `detect` so a detection pass can be run once and consumed
        twice. `SharedDetection` hands the same `boxes` to counting and to
        tracking; without this the second consumer would have to re-run the
        model purely to get the same numbers in a different shape.

        Pure and static on purpose: no model, no device, no lock. It is the
        half of detection that is safe to call from any thread.
        """
        if boxes is None:
            return []

        people: list[DetectedPerson] = []
        for box in boxes:
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            person = DetectedPerson(
                x=max(0.0, x1 / width),
                y=max(0.0, y1 / height),
                w=min(1.0, (x2 - x1) / width),
                h=min(1.0, (y2 - y1) / height),
                confidence=float(box.conf[0]),
            )
            if person.area >= min_area:
                people.append(person)

        people.sort(key=lambda p: p.area, reverse=True)
        return people

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
