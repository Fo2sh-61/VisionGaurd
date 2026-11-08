"""Frame sources: video files, camera indices and image-sequence folders
(UR Fall ships its RGB data as folders of PNGs)."""

import re
from pathlib import Path

import cv2

VIDEO_EXTS = {".avi", ".mp4", ".mkv", ".mov", ".webm", ".m4v", ".wmv", ".mpg", ".mpeg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}
DEFAULT_FPS = 30.0


def natural_key(path):
    """Sort key putting frame_2.png before frame_10.png (and -999 before -1000)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(path).name)]


def crop_frame(frame, crop):
    """``crop``: None, "left_half", "right_half" or pixel box (x1, y1, x2, y2)."""
    if crop is None:
        return frame
    w = frame.shape[1]
    if crop == "left_half":
        return frame[:, :w // 2]
    if crop == "right_half":
        return frame[:, w // 2:]
    x1, y1, x2, y2 = (int(v) for v in crop)
    return frame[y1:y2, x1:x2]


class FrameSource:
    """Iterate ``(frame_idx, frame_bgr)`` pairs from a video, camera or image folder.

    ``fps`` falls back to ``DEFAULT_FPS`` (or the ``fps`` argument) when the
    container doesn't report one. Frame indices are 0-based. ``crop`` keeps only
    part of each frame (e.g. UR Fall's videos are depth | RGB side by side).
    """

    def __init__(self, source, fps=None, crop=None):
        self.source = source
        self.crop = tuple(crop) if isinstance(crop, list) else crop
        self._images = None
        if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
            self._cap_arg = int(source)
        else:
            path = Path(source)
            if path.is_dir():
                self._images = sorted((p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS),
                                      key=natural_key)
                if not self._images:
                    raise FileNotFoundError(f"no images in {path}")
            elif not path.is_file():
                raise FileNotFoundError(f"video not found: {path}")
            self._cap_arg = str(path)
        self.fps = fps or self._probe_fps() or DEFAULT_FPS

    def _probe_fps(self):
        if self._images is not None:
            return None
        cap = cv2.VideoCapture(self._cap_arg)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
        finally:
            cap.release()
        return fps if fps and 1.0 <= fps <= 240.0 else None

    def __iter__(self):
        if self._images is not None:
            for i, path in enumerate(self._images):
                frame = cv2.imread(str(path))
                if frame is None:
                    raise IOError(f"could not read image {path}")
                yield i, crop_frame(frame, self.crop)
            return
        cap = cv2.VideoCapture(self._cap_arg)
        if not cap.isOpened():
            raise IOError(f"could not open {self.source}")
        try:
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield i, crop_frame(frame, self.crop)
                i += 1
        finally:
            cap.release()
