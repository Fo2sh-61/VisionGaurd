"""Knife detection — the owner's trained model, on the GPU through ultralytics.

`models/knifebest.pt` is a YOLOv8s with one class, `knife`: 11.1 M parameters,
imgsz 640, trained 13 Aug 2026 for 80 epochs on a combined public + on-site
dataset. Own-validation mAP50 0.90, precision 0.83, recall 0.84. **Its accuracy
on school cameras is unmeasured** — there is no footage with a knife in it yet
— which is why every detection this file produces waits for a person to decide.

It replaces two things:

  * the zero-shot prompted model, which also looked for scissors and
    screwdrivers. Every classroom and maintenance cupboard contains those.
  * an ONNX copy of this same checkpoint, decoded by hand in this file.

**Why the hand-rolled decode went.** It existed because the ONNX *export*
misread its own output layout under the pinned ultralytics (8.4.7 reading a
file written by 8.4.118): the four box-coordinate rows came back as four
detections with "confidences" of 90 and 100 — four knife alerts on a flat grey
image. The fix at the time was to decode the raw tensor here. The `.pt` has no
such problem: verified in the pinned runtime, it reports `{0: 'knife'}` and
finds nothing on grey and nothing on noise. So the decode, the letterbox, the
hand-rolled NMS and the onnxruntime dependency are all gone — onnxruntime is
not installed here, and its GPU build wants a CUDA this driver does not offer.

Cost, measured on the RTX 2080 with FP16: **p50 15.6 ms, p95 22.9 ms** a frame
— the same as the person model. TensorRT is faster again, but its engine file
is compiled for one GPU and one TensorRT version, so it is a build step on the
target machine, never an artifact to archive. See models/README.md.

**One instance, many threads.** `SharedDetection` guards the person model;
nothing guards this one, and `features/weapons.py` shares a single detector
across every camera thread it runs. The lock therefore lives here, inside
`detect()`, rather than in the worker — a caller cannot forget it.

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
# pip-install CLIP mid-run. Nothing here should ever install anything.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO_DIR = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = REPO_DIR / "models" / "knifebest.pt"

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


class WeaponDetector:
    """YOLO knife detection, GPU-first.

    Falls back to CPU with a warning rather than failing: a slow check is worth
    more than none, and the console should say what it is running on.
    """

    def __init__(
        self,
        weights: Path | str | None = None,
        device: str = "auto",
        imgsz: int = 640,
        conf: float = 0.5,
        iou: float = 0.45,
        half: bool = True,
    ) -> None:
        self.weights = Path(weights or DEFAULT_WEIGHTS)
        if not self.weights.is_file():
            raise FileNotFoundError(f"knife weights not found: {self.weights}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = _resolve_device(device)
        # FP16 halves the memory traffic and is free accuracy-wise for
        # detection, but only exists on the GPU.
        self.half = half and self.device != "cpu"

        # Prefer the TensorRT build made for this exact input size, and
        # record which form actually loaded - System Health prints it, so a
        # lost acceleration is visible on a page (P6-FR-035).
        from vg.infer.shared import load_model

        self.model, self.loaded, self.form = load_model(
            self.weights, imgsz, device=self.device)
        self.version = self.weights.stem

        # One detector, one model, every camera thread of the worker. Held
        # around `predict` only — the conversion to fractions afterwards
        # touches nothing shared.
        self._lock = threading.Lock()

        if self.device == "cpu":
            log.warning(
                "knife detection is running on the CPU. "
                "Install a CUDA build of torch to get ~16 ms a frame."
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
            "knife detector ready on %s (%s, %s, warm-up %.0f ms)",
            self.device, self.loaded.name, self.form,
            (time.perf_counter() - started) * 1000,
        )

    def detect(
        self, image: np.ndarray, min_confidence: float | None = None
    ) -> list[DetectedWeapon]:
        """Possible knives in a BGR frame, most confident first.

        `min_confidence` raises the bar for this call only. The model's own
        `conf` has already dropped everything below the configured threshold,
        so this is a second filter for a caller that wants to be surer than the
        configuration is — never a way to see more.
        """
        height, width = image.shape[:2]

        # One model shared by every camera thread. ultralytics is not
        # re-entrant on a single model instance, and two threads inside
        # `predict` at once is how you get boxes from one camera drawn on
        # another.
        with self._lock:
            results = self.model.predict(
                image,
                device=self.device,
                imgsz=self.imgsz,
                conf=self.conf,
                iou=self.iou,
                # `quantize=` replaced `half=` in ultralytics 8.4.127. Passing
                # `half` still works but logs a deprecation line **per inference
                # call**, which on a live camera is thousands an hour - enough to
                # bury a real error in the startup log, which is how this was
                # found. 16 = FP16, 32 = FP32.
                quantize=16 if self.half else 32,
                verbose=False,
            )

        if not results:
            return []
        return self.weapons_from(
            results[0].boxes.cpu(), width, height, min_confidence)

    @staticmethod
    def weapons_from(boxes, width: int, height: int,
                     min_confidence: float | None = None) -> list[DetectedWeapon]:
        """Turn ultralytics boxes into fractions of the frame.

        Static and pure, like `PersonDetector.people_from`: no model, no
        device, no lock. It is the half of detection that is safe to call from
        any thread.
        """
        if boxes is None:
            return []

        found: list[DetectedWeapon] = []
        for box in boxes:
            confidence = float(box.conf[0])
            if min_confidence is not None and confidence < min_confidence:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            class_id = int(box.cls[0]) if box.cls is not None else 0
            fx = max(0.0, min(1.0, x1 / width))
            fy = max(0.0, min(1.0, y1 / height))
            found.append(DetectedWeapon(
                x=fx,
                y=fy,
                w=max(0.0, min(1.0 - fx, (x2 - x1) / width)),
                h=max(0.0, min(1.0 - fy, (y2 - y1) / height)),
                confidence=confidence,
                label=(CLASS_NAMES[class_id] if class_id < len(CLASS_NAMES)
                       else "weapon"),
            ))

        # Most confident first — the opposite of the person detector, which
        # sorts by area. A knife is small by definition, so size says nothing
        # about which detection matters; the score is all there is.
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
            # `quantize=` replaced `half=` in ultralytics 8.4.127, on export
            # as well as on inference: `half` is no longer a configuration key
            # at all, so passing it raises rather than building anything.
            # 16 is half precision, 32 is full.
            quantize=16 if self.half else 32,
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
