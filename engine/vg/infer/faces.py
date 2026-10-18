"""Face detection, alignment and embedding.

Both models run through OpenCV directly — `cv2.FaceDetectorYN` and
`cv2.FaceRecognizerSF` — so there is no extra runtime to install and nothing to
keep in step with a CUDA build.

    YuNet    227 KB, finds faces and five landmarks (eyes, nose, mouth corners)
    SFace     37 MB, turns an aligned face into a 128-d vector

The landmarks matter more than they look. Recognition compares vectors, and two
photos of the same person taken at different angles only produce similar vectors
if both faces are warped to the same canonical position first. Skipping
alignment is the single biggest accuracy loss available.

Embedding is SFace, and that is settled (DEV_PLAN.md §0.2). It stays behind a
protocol anyway, because the protocol is what makes the guarantee below
enforceable rather than merely intended.

The guarantee: vectors from two different face models are NOT comparable.
Comparing them does not error — it returns plausible-looking nonsense, which is
far worse. So the model name is stored alongside every embedding and a mismatch
is refused rather than silently compared. Changing the face model means
re-enrolling every face in the school, which is why it is a decision and not a
setting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_DIR / "models"

# OpenCV Zoo's published operating point for SFace. Cosine similarity above
# this counts as the same person. It is a starting point, not a truth: the
# right value for a specific camera and population is measured, not assumed.
# `engine/tools/calibrate_faces.py` measures it.
SFACE_COSINE_THRESHOLD = 0.363

# Smallest face worth embedding, in pixels.
#
# Measured, not guessed. At 40 px the same person in consecutive frames scored
# 0.23-0.48 against themselves — below the 0.363 threshold, so they would fail
# to match their own enrolment while still being close enough to occasionally
# match somebody else. A face that small carries too little detail to embed and
# the result is not a weak signal but a meaningless one.
#
# Recognition needs a face that fills a reasonable part of the frame. On a
# 640x480 entrance camera that means roughly arm's length. Faces further away
# are detected and counted as people; they are simply not identified, which the
# UI already knows how to say.
MIN_FACE_PIXELS = 80


@dataclass(frozen=True)
class DetectedFace:
    """One face in a frame.

    Box is in PIXELS here because alignment needs pixels. It is converted to
    fractions of the frame at the API boundary, never before.
    """

    x: int
    y: int
    w: int
    h: int
    confidence: float
    landmarks: np.ndarray  # (5, 2) — right eye, left eye, nose, mouth corners
    raw: np.ndarray        # the detector row, needed by alignCrop

    @property
    def area(self) -> int:
        return self.w * self.h

    def to_fractions(self, frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
        return (
            max(0.0, self.x / frame_w),
            max(0.0, self.y / frame_h),
            min(1.0, self.w / frame_w),
            min(1.0, self.h / frame_h),
        )

    def offset(self, dx: int, dy: int) -> "DetectedFace":
        """The same face, expressed in the coordinates of a larger image.

        Run YuNet on a crop and every coordinate it returns is relative to
        THE CROP. Convert those against the full frame and the box lands in
        the wrong place - and plausibly, which is the dangerous part: a box
        that is merely misplaced looks like a detection, not like a fault.

        Three things move together and it is a bug if they ever do not:

          - the box, which is what the operator sees drawn
          - `landmarks`, which is what the overlay draws the five points from
          - `raw`, which is what `alignCrop` warps the face upright with

        Leaving `raw` behind is the worst of the three, because nothing looks
        wrong. The box is right, the picture is right, and the embedding is
        computed from the wrong patch of image - so the wrong person is
        named. Width, height and score are not coordinates and do not move.
        """
        moved = self.raw.copy()
        moved[0] += dx
        moved[1] += dy
        # Landmarks are five (x, y) pairs at indices 4..13.
        moved[4:14:2] += dx
        moved[5:14:2] += dy
        return DetectedFace(
            x=self.x + dx,
            y=self.y + dy,
            w=self.w,
            h=self.h,
            confidence=self.confidence,
            landmarks=self.landmarks + np.array([dx, dy], dtype=np.float32),
            raw=moved,
        )


class FaceDetector:
    """YuNet.

    The detector is stateful about input size — it must be told the frame
    dimensions before every detect on a differently-sized frame, which is easy
    to forget and produces silently wrong boxes rather than an error.
    """

    def __init__(
        self,
        weights: Path | None = None,
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        self.weights = Path(weights or MODELS_DIR / "face_detection_yunet_2023mar.onnx")
        if not self.weights.is_file():
            raise FileNotFoundError(f"YuNet weights not found: {self.weights}")

        self.score_threshold = score_threshold
        self._size: tuple[int, int] = (320, 320)
        self._detector = cv2.FaceDetectorYN.create(
            str(self.weights), "", self._size, score_threshold, nms_threshold, top_k
        )

    def detect(
        self, image: np.ndarray, min_size: int = MIN_FACE_PIXELS
    ) -> list[DetectedFace]:
        """Faces in a BGR frame, largest first.

        `min_size` drops faces too small to recognise. Below roughly 80 px an
        embedding is not a weak signal but a meaningless one — see
        MIN_FACE_PIXELS. Pass a smaller value only to *count* faces, never to
        identify them.
        """
        h, w = image.shape[:2]
        if (w, h) != self._size:
            self._size = (w, h)
            self._detector.setInputSize(self._size)

        _, raw = self._detector.detect(image)
        if raw is None:
            return []

        faces = []
        for row in raw:
            # YuNet can emit a row with inf/nan; int() on it raised and cost
            # the whole frame's faces (seen on the first site install, 18 Oct 2026).
            if not np.isfinite(row).all():
                continue
            fx, fy, fw, fh = (int(v) for v in row[:4])
            if fw < min_size or fh < min_size:
                continue
            faces.append(DetectedFace(
                x=fx, y=fy, w=fw, h=fh,
                confidence=float(row[-1]),
                landmarks=row[4:14].reshape(5, 2).astype(np.float32),
                raw=row,
            ))

        faces.sort(key=lambda f: f.area, reverse=True)
        return faces


class Embedder(Protocol):
    """Turns an aligned face into a comparable vector."""

    name: str
    dimensions: int
    threshold: float

    def embed(self, image: np.ndarray, face: DetectedFace) -> np.ndarray: ...
    def similarity(self, a: np.ndarray, b: np.ndarray) -> float: ...


class SFaceEmbedder:
    """OpenCV Zoo SFace. 128-d, cosine similarity."""

    name = "sface-2021dec"
    dimensions = 128

    def __init__(
        self, weights: Path | None = None, threshold: float = SFACE_COSINE_THRESHOLD
    ) -> None:
        self.weights = Path(
            weights or MODELS_DIR / "face_recognition_sface_2021dec.onnx"
        )
        if not self.weights.is_file():
            raise FileNotFoundError(f"SFace weights not found: {self.weights}")
        self.threshold = threshold
        self._recognizer = cv2.FaceRecognizerSF.create(str(self.weights), "")

    def embed(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        """Align to the canonical 112x112 pose, then embed.

        `alignCrop` uses the five landmarks to warp the face upright and
        centred. Without it, the same person at two angles lands far apart in
        embedding space and recognition collapses.
        """
        aligned = self._recognizer.alignCrop(image, face.raw)
        feature = self._recognizer.feature(aligned)
        # L2-normalise so similarity is a plain dot product and vectors from
        # different runs are directly comparable.
        vector = np.asarray(feature, dtype=np.float32).flatten()
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity in [-1, 1]; in practice [0, 1] for faces."""
        return float(np.dot(a, b))


@dataclass(frozen=True)
class FaceObservation:
    """A face found in a frame, with its vector. Identity comes later."""

    face: DetectedFace
    embedding: np.ndarray
    model: str


class FacePipeline:
    """Detect, align, embed — the whole front half of recognition."""

    def __init__(
        self, detector: FaceDetector | None = None, embedder: Embedder | None = None
    ) -> None:
        self.detector = detector or FaceDetector()
        self.embedder = embedder or SFaceEmbedder()

    def observe(
        self, image: np.ndarray, max_faces: int = 8, min_size: int = MIN_FACE_PIXELS
    ) -> list[FaceObservation]:
        """Every usable face in the frame.

        Capped because a crowd shot at an entrance can contain dozens, and
        embedding all of them costs more than it is worth — the largest faces
        are the ones close enough to identify.
        """
        faces = self.detector.detect(image, min_size=min_size)[:max_faces]
        out = []
        for face in faces:
            try:
                out.append(FaceObservation(
                    face=face,
                    embedding=self.embedder.embed(image, face),
                    model=self.embedder.name,
                ))
            except cv2.error as exc:
                # A face clipped by the frame edge can fail to align. Skip it
                # rather than dropping the whole frame.
                log.debug("could not embed face at (%d,%d): %s", face.x, face.y, exc)
        return out

    @property
    def model_name(self) -> str:
        return self.embedder.name

    @property
    def threshold(self) -> float:
        return self.embedder.threshold
