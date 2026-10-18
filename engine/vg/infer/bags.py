"""Bag detection — a YOLO-World prompted with nine words for "bag".

`models/bagsearch.pt` is `yolov8m-worldv2.pt` with a fixed vocabulary baked in
by the owner's `set_classes()` step, then stripped of its text encoder by
`engine/tools/strip_clip.py`. It is **not** a trained model — nothing was
fine-tuned into it. What it has is a well-chosen prompt list:

    person · bag · backpack · handbag · suitcase · duffel bag ·
    shopping bag · tote bag · luggage · briefcase

`person` is class 0 and is filtered out in the model call; the other nine are
all treated as one thing, a bag. Whether an object is "a backpack" or "a duffel
bag" is not a distinction worth surfacing to somebody looking for their bag —
it is one bag either way, and merging them means a bag missed under one word can
still be caught under another.

**Why this and not `bagbest.pt`.** `bagbest.pt` *is* fine-tuned — 50 epochs on
the owner's merged dataset, 7 Aug 2026 — and it is worse here, measurably. On
the two clips with no bag in them, at the configured confidence:

    bagbest.pt    17 false bags, incl. a black office chair read as a
                  `suitcase` at up to 0.88, held for seconds at a time
    bagsearch.pt   1 false bag

Nine ways to say "bag" beat three trained classes on this footage. `bagbest.pt`
stays in `models/` and in `engine.yaml` history; nothing loads it.

**The text encoder is gone and is not missed.** `set_classes()` converts the
prompts to vectors once and saves them as `txt_feats (1, 10, 512)`; inference
reads those. The encoder that did the converting is 300 MB that exists only to
make the file need the `clip` package to unpickle. Stripping it was proved to
change nothing: 252 boxes over 140 sampled frames, identical class, confidence
and geometry on every one.

**Accuracy on real bags is still unmeasured** — there is no recorded clip with a
bag in it. A box is therefore *a possible bag*, drawn amber over a live picture
somebody is looking at, never a claim that a bag is there.

**One instance, many callers, so the lock lives here** — inside `detect()`
rather than in the caller, for the reason it does in `weapons.py`: a caller
cannot forget what it does not have to remember.

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
DEFAULT_WEIGHTS = REPO_DIR / "models" / "bagsearch.pt"

# Class names that are not a bag. Everything else the checkpoint knows about is
# treated as one, which is what lets the same code run two very differently
# indexed checkpoints without a table to keep in step.
#
# Hard-coded indices were a trap: `bagbest.pt` numbers backpack/handbag/suitcase
# 0/4/5, while `bagsearch.pt` puts `person` at 0 and nine bag words at 1..9.
# The same literal `{0, 4, 5}` means "backpack, handbag, suitcase" in one file
# and "person, suitcase, duffel bag" in the other, and nothing would have
# complained - it would just have drawn boxes round people.
NOT_A_BAG: frozenset[str] = frozenset({"person"})


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

        # Prefer the TensorRT build made for this exact input size, and
        # record which form actually loaded - System Health prints it, so a
        # lost acceleration is visible on a page (P6-FR-035).
        from vg.infer.shared import load_model

        self.model, self.loaded, self.form = load_model(
            self.weights, imgsz, device=self.device)
        self.version = self.weights.stem

        # Read the vocabulary off the checkpoint itself.
        self.bag_classes: dict[int, str] = {
            index: name
            for index, name in self.model.names.items()
            if name not in NOT_A_BAG
        }
        if not self.bag_classes:
            raise ValueError(
                f"{self.weights.name} knows no bag classes, only "
                f"{sorted(self.model.names.values())}"
            )

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
            "bag detector ready on %s (%s, %s, warm-up %.0f ms)",
            self.device, self.loaded.name, self.form,
            (time.perf_counter() - started) * 1000,
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
                # `quantize=` replaced `half=` in ultralytics 8.4.127. Passing
                # `half` still works but logs a deprecation line **per inference
                # call**, which on a live camera is thousands an hour - enough to
                # bury a real error in the startup log, which is how this was
                # found. 16 = FP16, 32 = FP32.
                quantize=16 if self.half else 32,
                # The eight other classes never leave the model.
                classes=list(self.bag_classes),
                verbose=False,
            )

        if not results:
            return []
        return self.bags_from(
            results[0].boxes.cpu(), width, height, min_confidence,
            classes=self.bag_classes)

    @staticmethod
    def bags_from(boxes, width: int, height: int,
                  min_confidence: float | None = None,
                  classes: dict[int, str] | None = None) -> list[DetectedBag]:
        """Turn ultralytics boxes into fractions of the frame.

        Static and pure, like `WeaponDetector.weapons_from`: no model, no
        device, no lock. It is the half of detection that is safe to call from
        any thread.

        A class index the checkpoint does not call a bag is dropped rather than
        labelled "bag". `classes=` in the model call already prevents it, and
        this is the belt to that pair of braces — a box round a person, labelled
        "bag", is worse than no box at all.
        """
        if boxes is None:
            return []

        found: list[DetectedBag] = []
        for box in boxes:
            confidence = float(box.conf[0])
            if min_confidence is not None and confidence < min_confidence:
                continue
            class_id = int(box.cls[0]) if box.cls is not None else -1
            label = (classes or {}).get(class_id)
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
