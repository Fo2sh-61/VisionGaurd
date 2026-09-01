"""Configuration: cameras, gates, thresholds. Backed by config/cameras.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("ANPR_CONFIG", ROOT / "config" / "cameras.yaml"))
DATA_DIR_FILE = ROOT / "config" / "data_dir.txt"


def _resolve_data_dir() -> Path:
    """
    Where the database and snapshots live.

    Resolution order — env var, then a one-line file next to the config, then
    the project folder. The file matters: without it, launching from a shortcut
    (which sets the env var) and launching by typing `python run.py` (which
    does not) would quietly use two different databases, so a `reset` would
    appear to do nothing. One source of truth, whatever the launch path.
    """
    env = os.environ.get("ANPR_DATA")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    try:
        if DATA_DIR_FILE.exists():
            line = DATA_DIR_FILE.read_text(encoding="utf-8").strip()
            if line and not line.startswith("#"):
                return Path(os.path.expandvars(line)).expanduser()
    except OSError:
        pass
    return ROOT / "data"


DATA_DIR = _resolve_data_dir()
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DATASET_DIR = DATA_DIR / "dataset"
DB_PATH = Path(os.environ.get("ANPR_DB", DATA_DIR / "anpr.db"))
MODELS_DIR = ROOT / "models"

DIRECTIONS = ("entry", "exit", "both")
DIRECTION_AR = {"entry": "دخول", "exit": "خروج", "both": "دخول/خروج"}


@dataclass
class CameraConfig:
    """One physical camera. Every camera must declare its gate and direction."""

    id: str                       # short unique id, e.g. "gate1_in"
    name: str                     # human label shown in the dashboard
    source: str                   # rtsp:// url, /dev/video0, file path, or "0"
    gate_number: int              # which gate this camera watches
    direction: str                # entry | exit | both
    enabled: bool = True
    # Region of interest as fractions of frame (x1,y1,x2,y2). Cuts out the
    # street/sky so the detector only looks where cars actually stop.
    roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    # DEPRECATED and ignored. It used to discard any plate narrower than this,
    # which threw away exactly the distant plates an operator wants to catch,
    # and the correct value depends on lens, distance and mounting height, so
    # nobody could set it right. Plate size now only weights the vote. Kept as
    # a field so existing config files still load.
    min_plate_width_px: int = 0
    rotate: int = 0               # 0/90/180/270, for sideways-mounted cameras
    fps_limit: float = 8.0        # frames/sec actually processed (saves CPU)
    reconnect_seconds: int = 5
    # Capture size to request from a USB webcam. Ignored for RTSP, which
    # streams whatever the camera itself is configured for. Zero means use the
    # default in capture.py. This is the main lever on how far the system can
    # read: a webcam left at its 640x480 default cannot resolve a plate beyond
    # roughly 2m, and the same camera at 1280x720 reads comfortably at 3m.
    capture_width: int = 0
    capture_height: int = 0

    def validate(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(
                f"camera {self.id}: direction must be one of {DIRECTIONS}, "
                f"got {self.direction!r}"
            )
        if self.gate_number < 1:
            raise ValueError(f"camera {self.id}: gate_number must be >= 1")
        if self.rotate not in (0, 90, 180, 270):
            raise ValueError(f"camera {self.id}: rotate must be 0/90/180/270")

    @property
    def direction_ar(self) -> str:
        return DIRECTION_AR.get(self.direction, self.direction)


@dataclass
class RecognitionConfig:
    plate_detector_weights: str = "models/plate_detector.pt"
    char_detector_weights: str = "models/char_detector.pt"
    ocr_backend: str = "auto"          # auto | yolo_chars | easyocr | stub
    detector_backend: str = "auto"     # auto | yolo | classical
    min_detect_conf: float = 0.35
    # A plate must be read this many times across frames before it becomes an
    # event. Kills nearly all single-frame misreads.
    min_votes: int = 3
    # Final confidence (ocr x plausibility) below this is logged as "low
    # confidence" and flagged for the guard rather than trusted.
    min_accept_conf: float = 0.55
    # Same plate at the same camera inside this window = one visit, not two.
    dedupe_seconds: int = 60
    device: str = "auto"               # auto | cpu | cuda | 0


@dataclass
class SystemConfig:
    site_name: str = "بوابة الموقع"
    timezone: str = "Africa/Cairo"
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    # Save every plate crop for later labelling and fine-tuning. Turn this on
    # for the first few weeks, then train on your own camera angle.
    collect_dataset: bool = True
    collect_max_per_day: int = 3000
    keep_snapshot_days: int = 90
    alert_on_unknown: bool = True
    alert_on_blacklist: bool = True
    # Live camera feed inside the dashboard. A guard needs to see the gate,
    # not just a table of what already happened. Costs one JPEG encode per
    # processed frame; turn off on a loaded Jetson with many cameras.
    live_view: bool = True
    live_view_width: int = 900
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    cameras: list[CameraConfig] = field(default_factory=list)

    # -- persistence ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "SystemConfig":
        path = Path(path or CONFIG_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"No config at {path}.\nRun:  python run.py setup"
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rec = RecognitionConfig(**(raw.pop("recognition", {}) or {}))
        cams = [CameraConfig(**c) for c in (raw.pop("cameras", []) or [])]
        cfg = cls(recognition=rec, cameras=cams, **raw)
        cfg.validate()
        return cfg

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or CONFIG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d["cameras"] = [
            {**c, "roi": list(c["roi"])} for c in d["cameras"]
        ]
        path.write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def validate(self) -> None:
        seen: set[str] = set()
        for c in self.cameras:
            c.validate()
            if c.id in seen:
                raise ValueError(f"duplicate camera id: {c.id}")
            seen.add(c.id)

    # -- helpers -------------------------------------------------------------

    def camera(self, cam_id: str) -> CameraConfig | None:
        return next((c for c in self.cameras if c.id == cam_id), None)

    @property
    def gates(self) -> list[int]:
        return sorted({c.gate_number for c in self.cameras})


def ensure_dirs() -> None:
    for d in (DATA_DIR, SNAPSHOT_DIR, DATASET_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
