"""Engine configuration.

Two sources, deliberately separated:

  engine.yaml   what the system is — cameras, zones, schedules, thresholds.
                Checked into the repo, safe to read.
  .env          secrets — camera passwords, tokens. Never committed.

YAML values may reference env vars as ``${VAR}`` or ``${VAR:default}``; they are
expanded at load time. That is how an RTSP URL keeps its password out of the
repo while the rest of the camera definition stays readable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from datetime import time as dtime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

ENGINE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ENGINE_DIR.parent

SourceType = Literal["NVR", "DVR", "IP camera", "RTSP", "Webcam", "File"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


class ConfigError(ValueError):
    """Raised for a malformed engine.yaml, with the offending path in the message."""


# ---------------------------------------------------------------------------
# env expansion
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. Existing environment variables always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def _expand(value: Any, where: str) -> Any:
    if isinstance(value, dict):
        return {k: _expand(v, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, f"{where}[{i}]") for i, v in enumerate(value)]
    if not isinstance(value, str):
        return value

    def sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        env = os.environ.get(name)
        if env is not None:
            return env
        if default is not None:
            return default
        raise ConfigError(
            f"{where}: environment variable ${{{name}}} is not set and has no "
            f"default. Add it to engine/.env (see .env.example)."
        )

    return _ENV_PATTERN.sub(sub, value)


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Schedule:
    """When a zone is restricted.

    The front end shows this as free text ("Locked outside 8am-4pm, weekdays"),
    but the engine needs it structured to actually evaluate a breach. The UI
    renders the sentence; this is the truth behind it.

    mode ``outside``  restricted OUTSIDE the window (a lab, locked after hours)
    mode ``inside``   restricted DURING the window (an exam hall, in session)
    mode ``always``   restricted at all times (a server room)
    """

    mode: Literal["outside", "inside", "always"] = "always"
    days: tuple[str, ...] = WEEKDAYS
    start: dtime | None = None
    end: dtime | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "Schedule":
        if not raw:
            return cls()

        mode = raw.get("mode", "always")
        if mode not in ("outside", "inside", "always"):
            raise ConfigError(
                f"{where}.mode: expected outside|inside|always, got {mode!r}"
            )

        days = tuple(str(d).lower()[:3] for d in raw.get("days", WEEKDAYS))
        for day in days:
            if day not in WEEKDAYS:
                raise ConfigError(f"{where}.days: {day!r} is not a weekday")

        start = _parse_time(raw.get("from"), f"{where}.from")
        end = _parse_time(raw.get("to"), f"{where}.to")

        if mode != "always" and (start is None or end is None):
            raise ConfigError(
                f"{where}: mode {mode!r} needs both 'from' and 'to' times"
            )

        return cls(mode=mode, days=days, start=start, end=end)

    def is_restricted_at(self, when) -> bool:
        """True if the zone is off-limits at this local datetime."""
        if WEEKDAYS[when.weekday()] not in self.days:
            # Outside the scheduled days: an 'outside' rule still applies
            # (a weekday-only lab is restricted all weekend), the others don't.
            return self.mode == "outside"

        if self.mode == "always":
            return True

        assert self.start is not None and self.end is not None
        now = when.time()
        if self.start <= self.end:
            within = self.start <= now < self.end
        else:  # window crosses midnight
            within = now >= self.start or now < self.end

        return within if self.mode == "inside" else not within

    def to_wire(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "days": list(self.days),
            "from": self.start.strftime("%H:%M") if self.start else None,
            "to": self.end.strftime("%H:%M") if self.end else None,
        }


def _parse_time(raw: Any, where: str) -> dtime | None:
    if raw is None:
        return None
    if isinstance(raw, dtime):
        return raw
    text = str(raw).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M%p", "%I%p"):
        try:
            from datetime import datetime

            return datetime.strptime(text.upper().replace(" ", ""), fmt).time()
        except ValueError:
            continue
    raise ConfigError(f"{where}: cannot parse time {raw!r} (expected HH:MM)")


# ---------------------------------------------------------------------------
# cameras and zones
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CameraConfig:
    id: str
    name: str
    source: str
    kind: SourceType = "RTSP"
    area: str = "Unassigned"
    fps: float = 5.0
    enabled: bool = True
    features: tuple[str, ...] = ()
    rotate: int = 0

    @classmethod
    def parse(cls, raw: dict[str, Any], where: str) -> "CameraConfig":
        for required in ("id", "name", "source"):
            if not raw.get(required):
                raise ConfigError(f"{where}: missing required key {required!r}")

        rotate = int(raw.get("rotate", 0))
        if rotate not in (0, 90, 180, 270):
            raise ConfigError(f"{where}.rotate: expected 0/90/180/270, got {rotate}")

        fps = float(raw.get("fps", 5.0))
        if not 0 < fps <= 60:
            raise ConfigError(f"{where}.fps: expected 0 < fps <= 60, got {fps}")

        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            source=str(raw["source"]),
            kind=raw.get("kind", "RTSP"),
            area=str(raw.get("area", "Unassigned")),
            fps=fps,
            enabled=bool(raw.get("enabled", True)),
            features=tuple(raw.get("features", ())),
            rotate=rotate,
        )

    def redacted_source(self) -> str:
        """The source with any password masked, safe to log or return over the API."""
        return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", self.source)



@dataclass(frozen=True)
class AreaConfig:
    """A named place, and how many people belong in it.

    Capacity lives on the AREA rather than the camera because several cameras
    can watch one place, and "safe capacity" is a property of the room, not of
    the lens pointed at it.

    `capacity` of 0 means unset. People Counting then shows the headcount and
    no percentage, rather than dividing by an invented number - a made-up
    denominator produces a confident percentage that means nothing.
    """

    name: str
    capacity: int = 0

    @classmethod
    def parse(cls, name: str, raw: dict[str, Any] | int | None, where: str) -> "AreaConfig":
        if raw is None:
            return cls(name=name)
        if isinstance(raw, int):
            return cls(name=name, capacity=max(0, raw))
        capacity = int(raw.get("capacity", 0) or 0)
        if capacity < 0:
            raise ConfigError(f"{where}.capacity: cannot be negative, got {capacity}")
        return cls(name=name, capacity=capacity)


@dataclass(frozen=True)
class ZoneConfig:
    """A restricted area on one camera.

    ``polygon`` is a list of (x, y) points as **fractions of the frame**,
    origin top-left — the same normalised geometry the front end renders, so
    nothing has to know the camera's resolution.
    """

    id: str
    name: str
    camera_id: str
    polygon: tuple[tuple[float, float], ...]
    schedule: Schedule = field(default_factory=Schedule)
    enabled: bool = True
    min_dwell_seconds: float = 2.0

    @classmethod
    def parse(cls, raw: dict[str, Any], where: str) -> "ZoneConfig":
        for required in ("id", "name", "camera"):
            if not raw.get(required):
                raise ConfigError(f"{where}: missing required key {required!r}")

        points = raw.get("polygon") or _rect_to_polygon(raw.get("rect"), where)
        if not points or len(points) < 3:
            raise ConfigError(
                f"{where}: needs a 'polygon' of >=3 points or a 'rect' "
                f"[x, y, w, h], all as fractions 0-1"
            )

        poly: list[tuple[float, float]] = []
        for i, pt in enumerate(points):
            if len(pt) != 2:
                raise ConfigError(f"{where}.polygon[{i}]: expected [x, y]")
            x, y = float(pt[0]), float(pt[1])
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ConfigError(
                    f"{where}.polygon[{i}]: ({x}, {y}) is outside 0-1. "
                    f"Geometry is normalised, not pixels."
                )
            poly.append((x, y))

        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            camera_id=str(raw["camera"]),
            polygon=tuple(poly),
            schedule=Schedule.parse(raw.get("schedule"), f"{where}.schedule"),
            enabled=bool(raw.get("enabled", True)),
            min_dwell_seconds=float(raw.get("min_dwell_seconds", 2.0)),
        )


def _rect_to_polygon(rect: Any, where: str) -> list[list[float]] | None:
    if rect is None:
        return None
    if len(rect) != 4:
        raise ConfigError(f"{where}.rect: expected [x, y, w, h]")
    x, y, w, h = (float(v) for v in rect)
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """One entry in the model registry.

    ``weights`` is resolved relative to the repo root. Prefer a ``.pt`` here:
    a ``.engine`` is compiled for one GPU and one TensorRT version, so it is a
    build output for a specific machine, never the archived artifact.
    """

    name: str
    task: str
    weights: Path
    imgsz: int = 640
    conf: float = 0.25
    iou: float = 0.45
    classes: tuple[str, ...] = ()
    device: str = "auto"
    half: bool = True
    version: str = "unversioned"

    @classmethod
    def parse(cls, name: str, raw: dict[str, Any], where: str) -> "ModelConfig":
        if not raw.get("weights"):
            raise ConfigError(f"{where}: missing 'weights'")

        weights = Path(raw["weights"])
        if not weights.is_absolute():
            weights = REPO_DIR / weights

        conf = float(raw.get("conf", 0.25))
        if not 0.0 < conf < 1.0:
            raise ConfigError(f"{where}.conf: expected 0 < conf < 1, got {conf}")

        return cls(
            name=name,
            task=str(raw.get("task", "detect")),
            weights=weights,
            imgsz=int(raw.get("imgsz", 640)),
            conf=conf,
            iou=float(raw.get("iou", 0.45)),
            classes=tuple(raw.get("classes", ())),
            device=str(raw.get("device", "auto")),
            half=bool(raw.get("half", True)),
            version=str(raw.get("version", "unversioned")),
        )

    def exists(self) -> bool:
        return self.weights.is_file()


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HoursConfig:
    """School hours, in site-local time.

    `start`/`end` bound what counts as an arrival. Sightings outside the window
    are still stored — they are real and matter for tracking — but they do not
    establish attendance.
    """

    start: dtime = dtime(7, 30)
    end: dtime = dtime(15, 0)
    late_cutoff: dtime = dtime(8, 0)
    term_from: str = ""
    term_to: str = ""

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "HoursConfig":
        raw = raw or {}
        start = _parse_time(raw.get("from"), f"{where}.from") or cls.start
        end = _parse_time(raw.get("to"), f"{where}.to") or cls.end
        cutoff = _parse_time(raw.get("late_cutoff"), f"{where}.late_cutoff") or cls.late_cutoff

        if not (start <= cutoff <= end):
            raise ConfigError(
                f"{where}: late_cutoff {cutoff} must fall between "
                f"from {start} and to {end}. A cutoff outside school hours "
                f"means nobody can ever be marked on time."
            )

        return cls(
            start=start, end=end, late_cutoff=cutoff,
            term_from=str(raw.get("term_from", "")),
            term_to=str(raw.get("term_to", "")),
        )


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:5174")
    poll_seconds: float = 5.0


@dataclass(frozen=True)
class StorageConfig:
    database_url: str = "sqlite:///engine/data/visionguard.db"
    clips_dir: Path = ENGINE_DIR / "data" / "clips"
    footage_dir: Path = ENGINE_DIR / "data" / "footage"
    clip_pre_roll_seconds: float = 5.0
    clip_post_roll_seconds: float = 10.0
    clip_retention_days: int = 30

    @property
    def zone_clips_dir(self) -> Path:
        """Where restricted-zone clips land, under the configured clips folder.

        A subfolder rather than a config key, because it is not a choice: the
        retention rule here is "a few clips per camera", and applying that to a
        folder an operator also records into by hand would delete their file.
        Keeping them apart is what makes the rule safe to run at all, and it
        is also the boundary the clip endpoint checks a path against before
        serving it.
        """
        return self.clips_dir / "zones"


@dataclass(frozen=True)
class EngineConfig:
    site_name: str
    timezone: str
    hours: HoursConfig
    api: ApiConfig
    storage: StorageConfig
    cameras: tuple[CameraConfig, ...]
    zones: tuple[ZoneConfig, ...]
    models: dict[str, ModelConfig]
    # Named places and their safe capacity. Keyed by the same name cameras use
    # in their `area` field.
    areas: dict[str, AreaConfig] = field(default_factory=dict)

    def camera(self, camera_id: str) -> CameraConfig | None:
        return next((c for c in self.cameras if c.id == camera_id), None)

    def zones_for(self, camera_id: str) -> tuple[ZoneConfig, ...]:
        return tuple(z for z in self.zones if z.camera_id == camera_id)


def _apply_camera_override(cameras: tuple[CameraConfig, ...]) -> tuple[CameraConfig, ...]:
    """`VG_CAMERAS=cam-clip,cam-2` — run only these, whatever the file says.

    Exists so `dev.ps1 up -Clip` can switch from the webcam to the recorded
    test clip without rewriting engine.yaml. Rewriting a config file to change
    a runtime choice destroys its comments and turns a typo into a failed
    restart, so the override is an environment variable and the file stays the
    single readable description of the site.

    Unknown ids are a hard error. Silently running zero cameras because of a
    typo looks exactly like every camera being offline.
    """
    raw = os.environ.get("VG_CAMERAS", "").strip()
    if not raw:
        return cameras

    wanted = [c.strip() for c in raw.split(",") if c.strip()]
    known = {c.id for c in cameras}
    unknown = [c for c in wanted if c not in known]
    if unknown:
        raise ConfigError(
            f"VG_CAMERAS names unknown camera(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(known)) or 'none'}"
        )

    return tuple(
        replace(c, enabled=c.id in wanted) for c in cameras
    )


def load(path: Path | str | None = None) -> EngineConfig:
    """Read engine.yaml, expand env vars, validate, return a frozen config."""
    cfg_path = Path(path) if path else ENGINE_DIR / "engine.yaml"
    if not cfg_path.is_file():
        raise ConfigError(f"no config at {cfg_path}")

    _load_dotenv(ENGINE_DIR / ".env")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = _expand(raw, "engine.yaml")

    cameras = tuple(
        CameraConfig.parse(c, f"cameras[{i}]")
        for i, c in enumerate(raw.get("cameras") or [])
    )
    _reject_duplicates([c.id for c in cameras], "camera")
    cameras = _apply_camera_override(cameras)

    zones = tuple(
        ZoneConfig.parse(z, f"zones[{i}]")
        for i, z in enumerate(raw.get("zones") or [])
    )
    _reject_duplicates([z.id for z in zones], "zone")

    known = {c.id for c in cameras}
    for zone in zones:
        if zone.camera_id not in known:
            raise ConfigError(
                f"zone {zone.id!r} points at camera {zone.camera_id!r}, "
                f"which is not defined. Known cameras: {sorted(known) or 'none'}"
            )

    models = {
        name: ModelConfig.parse(name, spec, f"models.{name}")
        for name, spec in (raw.get("models") or {}).items()
    }

    areas = {
        name: AreaConfig.parse(name, spec, f"areas.{name}")
        for name, spec in (raw.get("areas") or {}).items()
    }

    api_raw = raw.get("api") or {}
    store_raw = raw.get("storage") or {}

    return EngineConfig(
        site_name=str(raw.get("site_name", "VisionGuard")),
        timezone=str(raw.get("timezone", "UTC")),
        hours=HoursConfig.parse(raw.get("hours"), "hours"),
        api=ApiConfig(
            host=str(api_raw.get("host", "127.0.0.1")),
            port=int(api_raw.get("port", 8000)),
            cors_origins=tuple(
                api_raw.get("cors_origins", ApiConfig.cors_origins)
            ),
            poll_seconds=float(api_raw.get("poll_seconds", 5.0)),
        ),
        storage=StorageConfig(
            database_url=str(
                store_raw.get("database_url", StorageConfig.database_url)
            ),
            clips_dir=_resolve(store_raw.get("clips_dir"), StorageConfig.clips_dir),
            footage_dir=_resolve(
                store_raw.get("footage_dir"), StorageConfig.footage_dir
            ),
            clip_pre_roll_seconds=float(store_raw.get("clip_pre_roll_seconds", 5.0)),
            clip_post_roll_seconds=float(store_raw.get("clip_post_roll_seconds", 10.0)),
            clip_retention_days=int(store_raw.get("clip_retention_days", 30)),
        ),
        cameras=cameras,
        zones=zones,
        areas=areas,
        models=models,
    )


def _resolve(value: Any, default: Path) -> Path:
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else REPO_DIR / p


def _reject_duplicates(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ConfigError(f"duplicate {what} id {i!r}")
        seen.add(i)


@lru_cache(maxsize=1)
def get_config() -> EngineConfig:
    """Process-wide config. Call ``get_config.cache_clear()`` to reload."""
    return load()
