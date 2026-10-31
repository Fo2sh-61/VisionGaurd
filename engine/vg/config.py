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

#: The only directions a gate camera may claim. `both` is deliberately absent
#: - see `CameraConfig.direction`.
GATE_DIRECTIONS: tuple[str, ...] = ("entry", "exit")

#: Where face detection looks. "" means "decide from the feature list".
FACE_GATES: frozenset[str] = frozenset({"", "person", "frame"})

#: Whether every frame is turned into pixels, or only the ones something
#: reads. Every frame is DECODED either way - see CameraConfig.live_capture.
LIVE_CAPTURE: frozenset[str] = frozenset({"watched", "always"})

#: Features that already run the shared person pass. A camera carrying
#: one of these has person boxes going spare; a camera carrying none
#: would have to start the person model just to gate faces.
PERSON_FEATURES: frozenset[str] = frozenset({"counting", "intrusion", "track"})

#: Everything a camera can be watched for. A closed set, because an unknown
#: name used to be accepted and then silently do nothing: `weapon` instead of
#: `weapons` meant no knife detection on that camera, for ever, with nothing
#: anywhere to say why. Refusing at parse time turns that into a startup
#: error naming the word.
#:
#: Adding a feature here is half the job - the other half is the camera list
#: the worker is started with in `api/app.py`, and `LiveStore._apply_features`
#: which maps this name onto that worker at runtime.
FEATURES: frozenset[str] = frozenset({
    "attendance",   # face recognition -> the register
    "counting",     # headcount per area
    "intrusion",    # restricted-area watching
    "track",        # follow one person across cameras
    "vehicles",     # plate reading at a gate
    "weapons",      # knife detection
    "lostitems",    # bag search on demand
    "falls",        # somebody who goes down and stays down
})


#: The lowest analytics rate at which a feature can still do its job.
#:
#: Only for features whose rule is written in FRAMES rather than in time.
#: Knife detection opens an entry on `CONFIRM_HITS` (3) sightings inside
#: `CONFIRM_SECONDS` (1.0), so below three frames a second the third sighting
#: can never arrive: the camera watches for knives it is incapable of
#: reporting, and every screen says the feature is running.
#:
#: Everything else is deliberately absent. Counting, intrusion and attendance
#: answer questions about a second rather than about a frame, and a floor for
#: them would be an invented threshold.
#:
#: `test_config.py` pins this against `features/weapons.py`'s own constants,
#: because a copied number is only safe while something checks it still
#: matches the number it was copied from.
#:
#: Falls are the other feature written in frames. The owner's model reads a
#: window of 30 poses at 30 a second; `infer/falls.py` fills in the poses
#: between two real frames up to `MAX_INTERPOLATE_SECONDS` (half a second)
#: apart and invents nothing beyond that, so a slower camera never fills a
#: window and the model never gets to say anything.
#:
#: **Five, not three, and the difference was measured.** The configured rate
#: is not the rate the model sees: the camera paces its frames and the worker
#: then skips any frame that arrives a little early, so a camera set to 3 a
#: second delivered 1.75 to the worker, most gaps over half a second, and the
#: real model raised nothing. At 5 the longest gap was 0.41 s and it raised
#: the fall. `features/falls.py` also says so on System Health when frames
#: still arrive too far apart. Nothing at any rate has been measured on a
#: school camera. `test_falls_live.py` pins this against the interpolation.
MIN_ANALYTICS_HZ: dict[str, float] = {"weapons": 3.0, "falls": 5.0}


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
    # Which recognition tier this camera is in. True means "faces are the
    # point here" — a doorway or a desk — and it gets the main recognition
    # worker at its full rate. False is the patrol tier: the same recogniser
    # at a much lower rate, whose job is to leave a trail to read later
    # rather than to watch anybody now.
    faces: bool = False
    # Cameras a person can plausibly walk to from this one. Optional, and
    # only ever a hint: it tells the archive layer which camera to warm up
    # next. Empty falls back to the rest of the same `area`.
    neighbours: tuple[str, ...] = ()

    # Which gate this camera watches, and which way it looks. Both None
    # unless set, so every camera that existed before Vehicle gate parses
    # unchanged and no other feature notices these exist.
    #
    # `direction` accepts `entry` or `exit`, NEVER `both`. A camera states
    # what it sees. Inferring direction from whether a plate grows or shrinks
    # in frame is a guess, and the gate-anpr project this technique came from
    # calls it "noticeably less reliable" in its own documentation. Here that
    # guess would decide whether a car is recorded as arriving or leaving,
    # which is the whole point of the feature.
    gate: int | None = None
    direction: str | None = None

    # Where face detection looks on this camera.
    #
    #   person   only inside the people the shared detection pass already
    #            found - the same gating knives and plate characters use
    #   frame    the whole picture, which is what this did before
    #
    # Empty means "decide from the feature list": `person` where the camera
    # already runs person detection for something else, `frame` otherwise.
    # That default matters. On a camera carrying ONLY `attendance` there is
    # no person pass to share, so gating would ADD the person model and a GPU
    # dependency to a camera that today runs two small models and no GPU at
    # all - costing time rather than saving it.
    face_gate: str = ""

    # How often frames are turned into pixels when nobody is looking at this
    # camera.
    #
    #   watched  convert every frame only while an operator has it open;
    #            otherwise convert at `fps`
    #   always   convert every frame, which is what this did before
    #
    # Frames are still GRABBED at the camera's own rate either way. That is
    # the whole trick: `cap.read()` returns the next buffered frame rather
    # than the newest, so skipping reads makes the stream fall further behind
    # every second. Grabbing keeps the buffer drained; only the conversion is
    # skipped. See CameraSource.frames() for the trap this avoids.
    #
    # Grabbing is also the decode - OpenCV's FFmpeg backend decodes inside
    # `grab()` - so every frame is decoded whatever this says. `watched`
    # saves the conversion, which is a fraction of a frame's cost;
    # `engine/tools/benchmark.py --decode` measures how big a fraction.
    live_capture: str = "watched"

    @property
    def is_gate(self) -> bool:
        """Is this camera actually usable as a gate camera?

        All three or none. A camera carrying `vehicles` but no gate number
        cannot label its passes, and a gate number without `vehicles` reads
        like a configured gate that silently watches nothing. `parse` refuses
        both half-states rather than running one.
        """
        return (
            self.gate is not None
            and self.direction is not None
            and "vehicles" in self.features
        )

    @property
    def gates_faces(self) -> bool:
        """Does face detection run on person crops on this camera?

        **Off unless asked for**, and that is a measured decision rather than
        caution. `engine/tools/compare_detections.py --gate-check` runs both
        paths over the labelled clip: gating finds every face the whole-frame
        pass finds - 60 of 60, so the crop padding and the offset arithmetic
        are right - but the boxes land up to 11 pixels away, 5 on average.

        That is inherent, not a bug. YuNet is told its input size, so a
        160x240 crop is a different computation from a 640x480 frame. The
        shift moves the five landmarks, `alignCrop` then warps a slightly
        different patch, and the embedding that decides WHO a face is
        changes with it.

        Nobody has shown that never flips an identity, and P8-FR-002 says a
        change that cannot demonstrate an unchanged result is rejected rather
        than shipped behind a default. So the machinery is here, tested, and
        switched off until somebody measures identities across a real
        enrolled roll.
        """
        return self.face_gate == "person"

    @classmethod
    def parse(cls, raw: dict[str, Any], where: str) -> "CameraConfig":
        for required in ("id", "name", "source"):
            if not raw.get(required):
                raise ConfigError(f"{where}: missing required key {required!r}")

        # The source has to be something that can actually be opened, and this
        # is the only place every path goes through - engine.yaml, the console,
        # a bulk add and an edit. Checking here means a bad address is refused
        # BEFORE it is written, rather than persisted and then failing when the
        # worker tries to start.
        #
        # Imported inside the function on purpose: `config` is the bottom layer
        # and importing `ingest` at module scope would invert that.
        from vg.ingest.source import parse_source

        try:
            kind, handle = parse_source(str(raw["source"]))
        except ValueError as exc:
            raise ConfigError(f"{where}.source: {exc}") from exc
        # A pushed camera names itself, so frames sent for one camera can
        # never land in another's stream.
        if kind.value == "push" and handle != str(raw.get("id", "")):
            raise ConfigError(
                f"{where}.source: a push source must name its own camera, "
                f"push:{raw.get('id', '')}, not push:{handle}")

        rotate = int(raw.get("rotate", 0))
        if rotate not in (0, 90, 180, 270):
            raise ConfigError(f"{where}.rotate: expected 0/90/180/270, got {rotate}")

        fps = float(raw.get("fps", 5.0))
        if not 0 < fps <= 60:
            raise ConfigError(f"{where}.fps: expected 0 < fps <= 60, got {fps}")

        gate = raw.get("gate")
        if gate is not None:
            gate = int(gate)
            if gate < 1:
                raise ConfigError(
                    f"{where}.gate: expected a positive number, got {gate}")

        direction = raw.get("direction")
        if direction is not None:
            direction = str(direction).strip().lower()
            if direction not in GATE_DIRECTIONS:
                # `both` is the tempting one and is refused on purpose - see
                # the field comment. Naming it here saves the next person
                # working out why their config was rejected.
                extra = (
                    " - one camera per direction; a single camera guessing "
                    "from plate size is not accurate enough to record"
                    if direction == "both" else ""
                )
                raise ConfigError(
                    f"{where}.direction: expected one of {GATE_DIRECTIONS}, "
                    f"got {direction!r}{extra}"
                )

        face_gate = str(raw.get("face_gate", "") or "").strip().lower()
        if face_gate not in FACE_GATES:
            raise ConfigError(
                f"{where}.face_gate: expected one of {sorted(FACE_GATES - {''})}, "
                f"got {face_gate!r}"
            )

        live_capture = str(raw.get("live_capture", "watched")).strip().lower()
        if live_capture not in LIVE_CAPTURE:
            raise ConfigError(
                f"{where}.live_capture: expected one of {sorted(LIVE_CAPTURE)}, "
                f"got {live_capture!r}"
            )

        features = tuple(raw.get("features", ()))
        unknown = [f for f in features if f not in FEATURES]
        if unknown:
            # Naming both halves on purpose: the word that was wrong, and what
            # was available. A typo here used to cost a feature silently, so
            # the message has to be enough to fix it without opening config.py.
            raise ConfigError(
                f"{where}.features: unknown feature(s) "
                f"{', '.join(repr(f) for f in unknown)} - "
                f"expected any of {', '.join(sorted(FEATURES))}"
            )

        # A feature that CANNOT FIRE at the configured rate is refused here,
        # not accepted and left silently dead. This is the same failure the
        # closed `FEATURES` set above exists to prevent, reached by a
        # different route: the camera is watched, the model is loaded, the
        # console shows the feature as running, and no entry can ever be
        # written. Turning the rate down is the cheapest saving this product
        # has, which is exactly why it needs a floor under it.
        for feature, floor in MIN_ANALYTICS_HZ.items():
            if feature in features and fps < floor:
                raise ConfigError(
                    f"{where}.fps: {feature!r} needs at least {floor:g} frames "
                    f"a second to be able to report anything, got {fps:g}. "
                    f"Raise the rate or drop the feature."
                )

        has_gate = gate is not None and direction is not None
        if "vehicles" in features and not has_gate:
            raise ConfigError(
                f"{where}: has 'vehicles' in features but no gate/direction - "
                "a pass cannot be recorded without knowing which gate it "
                "passed and which way it was going"
            )
        if has_gate and "vehicles" not in features:
            raise ConfigError(
                f"{where}: has gate/direction but no 'vehicles' in features - "
                "that reads like a configured gate watching nothing"
            )

        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            source=str(raw["source"]),
            kind=raw.get("kind", "RTSP"),
            area=str(raw.get("area", "Unassigned")),
            fps=fps,
            enabled=bool(raw.get("enabled", True)),
            features=features,
            rotate=rotate,
            faces=bool(raw.get("faces", False)),
            neighbours=tuple(str(n) for n in raw.get("neighbours", ())),
            gate=gate,
            direction=direction,
            face_gate=face_gate,
            live_capture=live_capture,
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
    #: Use the TensorRT build beside these weights when one exists.
    #:
    #: Per model, and false is a real answer. A plan is compiled at a fixed
    #: input size and, with `half`, at FP16 — so it is close to the weights it
    #: came from but not identical. A person detector has room for that. A
    #: model that decides which of 38 characters a 20-pixel glyph is has less,
    #: and the difference shows up as a plate that is nearly right.
    accelerate: bool = True
    #: Run frames that are already waiting on the model as one call.
    #:
    #: Throughput only. Only threads ALREADY blocked are collected, so a
    #: lone caller never waits for company and no latency is added. The
    #: cache key is untouched, so which boxes belong to which frame does
    #: not change. False restores one frame per call.
    batch: bool = False
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
            accelerate=bool(raw.get("accelerate", True)),
            batch=bool(raw.get("batch", False)),
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
    # The built console (`web/dist`) for the engine to serve itself, so one
    # address carries both the pages and the API. Unset on the laptop, where
    # Vite serves the console: nothing about the engine's paths changes then.
    console_dir: Path | None = None


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

    @property
    def weapon_clips_dir(self) -> Path:
        """Where knife-detection clips land, under the configured clips folder.

        A subfolder rather than a config key, for the reason `zone_clips_dir`
        gives: it is the boundary the clip endpoint checks a path against before
        serving it, and it keeps the retention sweep away from files an operator
        recorded by hand. The sweep here deletes by age only — knife videos have
        no per-camera cap, because the second knife of the day matters as much as
        the first.
        """
        return self.clips_dir / "weapons"

    @property
    def fall_clips_dir(self) -> Path:
        """Where fall clips land, under the configured clips folder.

        A subfolder for the reason `weapon_clips_dir` gives: it is the boundary
        the clip endpoint checks a path against before serving it, and it keeps
        the retention sweep away from anything an operator recorded by hand.
        Deleted by age only, like knives.
        """
        return self.clips_dir / "falls"

    @property
    def gate_images_dir(self) -> Path:
        """Where the photograph and plate crop of each gate pass land.

        A subfolder for the same reason the two clip folders are: it is the
        boundary the retention sweep works inside, so it can delete by age
        without ever touching a file an operator put there by hand. Stills,
        not video — a pass is a moment, and thirty days of gate video is a
        different product.
        """
        return self.clips_dir / "gate"


# ---------------------------------------------------------------------------
# tracking: the bar for a name, and the patrol tier
# ---------------------------------------------------------------------------

# The smallest face the system will believe, in pixels. Measured, not chosen:
# `infer/faces.py::MIN_FACE_PIXELS` records that at 40 px the same person
# scored 0.23-0.48 against themselves — below the match threshold — so a face
# that small is not a weak signal but a meaningless one.
#
# Repeated here rather than imported because `infer.faces` pulls in cv2 and
# config has to stay importable without it. `test_track_page.py` pins the two
# together so they cannot drift apart.
FACE_PIXEL_FLOOR = 80


@dataclass(frozen=True)
class AnchorGates:
    """What it takes before the system will put a name on a body.

    A gallery match has already cleared its own threshold and margin. That is
    enough to say "this frame looks like Sara". It is not enough to *claim*
    her, because one lucky frame naming a body is exactly how every person on
    screen once read as one name.

    So this is a second bar, and it asks for evidence over time rather than a
    bigger number: the same person, several separate times, spread across
    seconds, with a real gap between the looks. Five frames inside a third of
    a second are one look at one moment, not five pieces of evidence.

    The numbers are per tier because a corner camera sees faces smaller and at
    worse angles than a doorway one. A single bar sized for the doorway would
    mean corner cameras never anchor at all, which is the same as not having
    the feature.
    """

    #: cosine similarity the best match must reach.
    #:
    #: **Measured, not chosen.** `calibrate_faces.py` on the enrolled gallery
    #: gives genuine scores of median 0.812, 5th percentile 0.732, min 0.725 —
    #: so 0.45 accepted anything from 0.45 upward while the real person never
    #: scored below 0.72. A stranger was named in that gap, which is the worst
    #: failure this system has. 0.60 keeps 0.12 of headroom below the genuine
    #: floor, because those figures come from enrolment stills and a live
    #: 80px frame scores lower than a photograph.
    #:
    #: Re-measure after enrolling a real roll; do not carry this number to a
    #: different camera or a different population on faith.
    score: float = 0.60
    #: how far clear of the runner-up the best match must be. Wider than the
    #: gallery's own margin: matching is an observation, naming is a claim.
    margin: float = 0.10
    #: how many separate looks are needed.
    matches: int = 3
    #: spread over at least this long.
    seconds: float = 1.5
    #: two matches closer together than this are the same look, not two.
    gap_seconds: float = 0.3
    #: smallest face that counts. Never below FACE_PIXEL_FLOOR.
    face_px: int = FACE_PIXEL_FLOOR

    _KEYS = ("score", "margin", "matches", "seconds", "gap_seconds", "face_px")

    @classmethod
    def parse(
        cls, raw: dict[str, Any] | None, where: str, default: "AnchorGates"
    ) -> "AnchorGates":
        raw = raw or {}
        unknown = sorted(set(raw) - set(cls._KEYS))
        if unknown:
            raise ConfigError(
                f"{where}: unknown key(s) {unknown}. Expected any of "
                f"{list(cls._KEYS)}"
            )

        score = float(raw.get("score", default.score))
        if not 0 < score <= 1:
            raise ConfigError(f"{where}.score: expected 0 < score <= 1, got {score}")

        margin = float(raw.get("margin", default.margin))
        if not 0 <= margin <= 1:
            raise ConfigError(
                f"{where}.margin: expected 0 <= margin <= 1, got {margin}"
            )

        matches = int(raw.get("matches", default.matches))
        if matches < 2:
            raise ConfigError(
                f"{where}.matches: expected at least 2, got {matches}. Seeing "
                f"somebody twice is the whole point of this gate; at 1 it is "
                f"the single-frame naming it exists to stop."
            )

        seconds = float(raw.get("seconds", default.seconds))
        if seconds <= 0:
            raise ConfigError(f"{where}.seconds: expected > 0, got {seconds}")

        gap = float(raw.get("gap_seconds", default.gap_seconds))
        if gap < 0:
            raise ConfigError(f"{where}.gap_seconds: expected >= 0, got {gap}")

        face_px = int(raw.get("face_px", default.face_px))
        if face_px < FACE_PIXEL_FLOOR:
            raise ConfigError(
                f"{where}.face_px: {face_px} is below the measured floor of "
                f"{FACE_PIXEL_FLOOR}px, and cannot go lower. A face that small "
                f"does not carry enough detail to identify anybody — see "
                f"infer/faces.py::MIN_FACE_PIXELS. Raising it is allowed."
            )

        return cls(
            score=score, margin=margin, matches=matches,
            seconds=seconds, gap_seconds=gap, face_px=face_px,
        )


#: The patrol tier's defaults. Easier to clear than the identity tier's on
#: purpose: these cameras see people in passing, further away and off-angle,
#: and the owner's call was not to make it so hard that a corridor never
#: anchors at all. The evidence requirement carries the weight the raw score
#: gives up.
#: **Deliberately NOT raised with the identity tier.** When identity went
#: 0.45 -> 0.60 after a stranger was named, patrol was moved to 0.55 by the
#: same reasoning — and `test_track_page.py` refused it. A real corridor look
#: scores about 0.44, so a 0.55 patrol bar means corridor cameras never anchor
#: and "Track a person" stops working everywhere except doorways. Fixing one
#: feature by silently deleting another is not a fix.
#:
#: What keeps a patrol anchor honest is not the raw score, it is the evidence:
#: three separate looks, two seconds apart, with real gaps between them. That
#: is why this bar can be lower than the doorway one without being a guess.
PATROL_GATES = AnchorGates(
    score=0.40, margin=0.07, matches=3, seconds=2.0, gap_seconds=0.4
)


@dataclass(frozen=True)
class TrackingConfig:
    """The patrol tier's rate, and the gates each tier answers to."""

    #: how often the patrol recogniser looks at a camera that is not a
    #: `faces:` camera. Slow on purpose: patrol exists so "where did they go"
    #: can be answered later, not so that anybody is watched now. 0 switches
    #: the tier off entirely.
    patrol_hz: float = 0.0
    identity: AnchorGates = field(default_factory=AnchorGates)
    patrol: AnchorGates = field(default_factory=lambda: PATROL_GATES)

    def gates_for(self, camera: "CameraConfig") -> AnchorGates:
        """Which bar this camera's recognitions have to clear."""
        return self.identity if camera.faces else self.patrol

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "TrackingConfig":
        raw = raw or {}
        unknown = sorted(set(raw) - {"patrol_hz", "identity", "patrol"})
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")

        patrol_hz = float(raw.get("patrol_hz", 0.0))
        if not 0 <= patrol_hz <= 30:
            raise ConfigError(
                f"{where}.patrol_hz: expected 0 <= patrol_hz <= 30, got "
                f"{patrol_hz}. 0 switches the patrol tier off."
            )

        return cls(
            patrol_hz=patrol_hz,
            identity=AnchorGates.parse(
                raw.get("identity"), f"{where}.identity", AnchorGates()
            ),
            patrol=AnchorGates.parse(
                raw.get("patrol"), f"{where}.patrol", PATROL_GATES
            ),
        )


@dataclass(frozen=True)
class VehiclesConfig:
    """How long the same car is one arrival rather than several.

    P6-FR-006 says a repeated read of the same plate at the same camera
    inside a **configured** window is one pass. This is that window, and it
    was a hardcoded constant until somebody testing with a plate in their
    hand found the gate log ignoring them for a minute with nothing on screen
    to say why.

    A car sits at a barrier for twenty seconds, so the default is comfortably
    longer than that: without it, every frame the car is read in becomes
    another arrival and the log turns into noise. Testing wants a much
    smaller number - two or three seconds - and that is the whole reason this
    is in the file rather than in the code.

    It does not affect *reading*. A plate in view is read, boxed and labelled
    on the tile continuously whatever this is set to; the window only decides
    when a new **row** is written.
    """

    dedupe_seconds: float = 60.0

    #: The same window, for a plate that is **nearly** the same.
    #:
    #: **Why this is short, and separate.** The reader wobbles by a character:
    #: a car whose plate is briefly hidden loses its track, is picked up again
    #: and can settle one character off, producing a second row for one car.
    #: Matching loosely fixes that - and introduces a worse mistake, because
    #: two genuinely different cars whose plates differ by one character would
    #: be collapsed into one row and the second car would go unrecorded. A
    #: blacklisted car disappearing is far worse than a duplicate.
    #:
    #: Time is what separates the two, which is the whole reason this value
    #: exists. A track dies after `LOST_FRAMES` and needs three more agreeing
    #: frames to settle, so a re-acquired car returns within about two to four
    #: seconds. A genuinely different car has to physically drive up, which is
    #: ten seconds at the very least. Five sits comfortably between the two.
    #:
    #: Raise it and duplicates vanish while the risk of swallowing a real car
    #: grows. Set it to 0 to switch loose matching off entirely and de-duplicate
    #: on the exact plate only, which is what this did before 28 Aug 2026.
    near_dedupe_seconds: float = 5.0

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "VehiclesConfig":
        raw = raw or {}
        known = {"dedupe_seconds", "near_dedupe_seconds"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")

        seconds = float(raw.get("dedupe_seconds", 60.0))
        if not 0 <= seconds <= 3600:
            raise ConfigError(
                f"{where}.dedupe_seconds: expected 0 <= seconds <= 3600, got "
                f"{seconds}. 0 records every settled read as its own pass."
            )

        near = float(raw.get("near_dedupe_seconds", 5.0))
        if not 0 <= near <= 3600:
            raise ConfigError(
                f"{where}.near_dedupe_seconds: expected 0 <= seconds <= 3600, "
                f"got {near}. 0 turns loose matching off."
            )
        if near > seconds:
            # Loose matching inside a window wider than the exact one would
            # mean a near miss is de-duplicated for longer than an exact hit,
            # which is backwards: the weaker evidence would get the stronger
            # benefit of the doubt.
            raise ConfigError(
                f"{where}.near_dedupe_seconds ({near}) must not exceed "
                f"dedupe_seconds ({seconds}). A nearly-matching plate is "
                f"weaker evidence than an exact one and cannot be trusted for "
                f"longer."
            )
        return cls(dedupe_seconds=seconds, near_dedupe_seconds=near)


@dataclass(frozen=True)
class AskConfig:
    """The natural-language query console (P12).

    Deliberately three fields. Ask has no thresholds to tune and no per-camera
    behaviour — it turns a sentence into a menu choice and runs an existing
    query. Everything that *could* be configured about it is either a fact
    about the site (which comes from the store) or a decision that belongs in
    code (which queries exist, and what may be sent off-site).

    The API key is **not** here. It lives in `.env` as `GEMINI_API_KEY`, the
    same rule the camera credentials follow: a secret in engine.yaml is a
    secret in git.
    """

    enabled: bool = True

    #: Confirm against the live model list before shipping. Gemini ids move
    #: faster than this file does; a wrong one fails at the first question
    #: with the provider's own error rather than answering wrongly.
    #:
    #: flash-lite rather than the better flash, and measured rather than
    #: preferred: the free tier gives `gemini-3.7-flash` twenty requests a
    #: day, which is fewer than one accuracy run and far fewer than one
    #: school day. See specs/010-ask/evidence/routing.md.
    model: str = "gemini-3.5-flash-lite"

    #: A person is waiting at a screen. Saying "temporarily unavailable" after
    #: eight seconds beats an indefinite spinner, and the answer is never so
    #: valuable that it is worth waiting longer for.
    timeout_seconds: float = 8.0

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "AskConfig":
        raw = raw or {}
        known = {"enabled", "model", "timeout_seconds"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")

        model = str(raw.get("model", "gemini-3.5-flash-lite")).strip()
        if not model:
            raise ConfigError(
                f"{where}.model: must name a model. Ask cannot pick one for "
                f"you — the id decides both the cost and the Arabic accuracy."
            )

        seconds = float(raw.get("timeout_seconds", 8.0))
        if not 1 <= seconds <= 120:
            raise ConfigError(
                f"{where}.timeout_seconds: expected 1 <= seconds <= 120, got "
                f"{seconds}. Below a second nothing would ever answer; above "
                f"two minutes the operator has given up and asked again."
            )

        return cls(
            enabled=bool(raw.get("enabled", True)),
            model=model,
            timeout_seconds=seconds,
        )


@dataclass(frozen=True)
class AlertsConfig:
    """Alert delivery (P9): how the engine tells people by email.

    How the sender behaves, and nothing else. **Who** is told, and about
    which kind of alert, is not here: recipients and rules are database state
    an administrator edits in Settings, and a yaml edit must never be the way
    an address gets added.

    The Gmail keys are not here either. They live in `.env` — GMAIL_USER,
    GMAIL_APP_PASSWORD — the same rule the camera credentials and the Gemini
    key follow: a secret in engine.yaml is a secret in git.
    """

    #: False: the sender does not start, nothing goes out by email, and
    #: Settings and System Health say so. Home's list still works.
    enabled: bool = True
    #: NO SIGNAL for this long is a message. A camera reads "down" after ten
    #: seconds without a frame; a phone buzzing for every hiccup would be
    #: switched off within a day.
    camera_offline_minutes: float = 5.0
    #: Site-local time of the daily attendance report.
    report_time: dtime = dtime(12, 0)
    #: Per courier call. The sender thread waits this long at most, and
    #: nothing else ever waits on the sender.
    timeout_seconds: float = 10.0
    #: The hand-off queue between the cameras and the sender. Two hundred is a
    #: week of alerts here; it only fills when a courier has been down a while.
    queue_size: int = 200
    #: Attempts per message, five seconds apart, before it is logged failed.
    retries: int = 3
    #: Delivery-log rows older than this are deleted. Nothing else is.
    log_retention_days: int = 90
    #: Send the Arabic wording before a native speaker has read it — only so
    #: that it can be read on a real phone. Off, Arabic recipients get English.
    send_draft_arabic: bool = False
    #: The console's address, used for the link in every message. Empty: no
    #: link. The engine cannot learn its own public address from a request
    #: that came through the dev proxy, and a guessed link is a dead link.
    console_url: str = ""

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "AlertsConfig":
        raw = raw or {}
        known = {
            "enabled", "camera_offline_minutes", "report_time",
            "timeout_seconds", "queue_size", "retries", "log_retention_days",
            "send_draft_arabic", "console_url",
        }
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")

        report = _parse_time(raw.get("report_time"), f"{where}.report_time")
        minutes = float(raw.get("camera_offline_minutes", 5.0))
        if minutes <= 0:
            raise ConfigError(
                f"{where}.camera_offline_minutes: must be above zero, got "
                f"{minutes}. Zero would send a message for every dropped frame.")
        seconds = float(raw.get("timeout_seconds", 10.0))
        if not 1 <= seconds <= 60:
            raise ConfigError(
                f"{where}.timeout_seconds: expected 1 <= seconds <= 60, got "
                f"{seconds}.")
        retries = int(raw.get("retries", 3))
        if not 1 <= retries <= 5:
            raise ConfigError(
                f"{where}.retries: expected 1 to 5, got {retries}.")
        size = int(raw.get("queue_size", 200))
        if size < 10:
            raise ConfigError(
                f"{where}.queue_size: expected at least 10, got {size}.")
        keep = int(raw.get("log_retention_days", 90))
        if keep < 1:
            raise ConfigError(
                f"{where}.log_retention_days: expected at least 1, got {keep}.")
        url = str(raw.get("console_url", "") or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise ConfigError(
                f"{where}.console_url: must start with http:// or https://, "
                f"got {url!r}. A link a phone cannot open is worse than none.")
        if len(url) > 100:
            raise ConfigError(
                f"{where}.console_url: at most 100 characters, so every "
                f"message stays short.")

        return cls(
            enabled=bool(raw.get("enabled", True)),
            camera_offline_minutes=minutes,
            report_time=report or dtime(12, 0),
            timeout_seconds=seconds,
            queue_size=size,
            retries=retries,
            log_retention_days=keep,
            send_draft_arabic=bool(raw.get("send_draft_arabic", False)),
            console_url=url,
        )


ArchiveBackend = Literal["dvr", "footage"]


@dataclass(frozen=True)
class ArchiveConfig:
    """Where recorded video comes from when somebody asks to watch a leg.

    ``footage`` slices files already sitting under ``storage.footage_dir``.
    That is the dev backend and the one the tests run against, and it needs no
    hardware at all.

    ``dvr`` pulls a time range off the recorder over the network, filling
    ``playback_url`` with the camera's channel and the span wanted. Every DVR
    spells that URL differently, which is why it is a template here and not
    code.
    """

    backend: ArchiveBackend = "footage"
    playback_url: str = ""
    #: camera id -> the channel that camera is on the recorder.
    channels: dict[str, str] = field(default_factory=dict)
    #: how much video one processed piece covers. Playback starts once the
    #: first one lands, so this is also the "how long until I see anything"
    #: number. `tools/measure_track.py` says whether the machine sustains it.
    chunk_seconds: float = 30.0
    #: how many legs' worth of processed chunks to keep per camera before the
    #: oldest goes. A leg is always re-derivable from the archive.
    keep_legs: int = 3

    @property
    def configured(self) -> bool:
        """False when asking for archive video would fail, whatever the reason."""
        return self.backend == "footage" or bool(self.playback_url)

    def channel_for(self, camera_id: str) -> str | None:
        return self.channels.get(camera_id)

    @classmethod
    def parse(cls, raw: dict[str, Any] | None, where: str) -> "ArchiveConfig":
        raw = raw or {}
        unknown = sorted(
            set(raw)
            - {"backend", "playback_url", "channels", "chunk_seconds", "keep_legs"}
        )
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")

        backend = str(raw.get("backend", "footage"))
        if backend not in ("dvr", "footage"):
            raise ConfigError(
                f"{where}.backend: expected dvr|footage, got {backend!r}"
            )

        url = str(raw.get("playback_url", "") or "")
        if backend == "dvr":
            if not url:
                raise ConfigError(
                    f"{where}.playback_url: the dvr backend needs a URL "
                    f"template. Use {{channel}}, {{start}} and {{end}}."
                )
            for token in ("{start}", "{end}"):
                if token not in url:
                    raise ConfigError(
                        f"{where}.playback_url: template is missing {token}. "
                        f"Without it every request would fetch the same video."
                    )

        chunk = float(raw.get("chunk_seconds", 30.0))
        if not 5 <= chunk <= 120:
            raise ConfigError(
                f"{where}.chunk_seconds: expected 5 <= chunk_seconds <= 120, "
                f"got {chunk}"
            )

        keep = int(raw.get("keep_legs", 3))
        if keep < 1:
            raise ConfigError(f"{where}.keep_legs: expected at least 1, got {keep}")

        channels = {
            str(cam): str(channel)
            for cam, channel in (raw.get("channels") or {}).items()
        }

        return cls(
            backend=backend, playback_url=url, channels=channels,
            chunk_seconds=chunk, keep_legs=keep,
        )


#: What a `profile:` key may say. Empty is the workstation, as it has always
#: been. `cloud` is the free-GPU trial (specs/021-cloud-trial): a public
#: address, so the developer sign-in refuses to start under it.
PROFILES: tuple[str, ...] = ("", "cloud")


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
    profile: str = ""
    # Named places and their safe capacity. Keyed by the same name cameras use
    # in their `area` field.
    areas: dict[str, AreaConfig] = field(default_factory=dict)
    # The naming bar and the patrol tier's rate.
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    # Where recorded video is fetched from. Defaults to slicing local footage,
    # so a site with no DVR configured still has a working archive.
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    # How long the same plate at the same gate camera is one arrival.
    vehicles: VehiclesConfig = field(default_factory=VehiclesConfig)
    # The natural-language query console. Off, or keyless, changes nothing
    # else — no feature may require another (constitution rule 9).
    ask: AskConfig = field(default_factory=AskConfig)
    # How alerts leave the building. Who receives them lives in the database.
    alerts: AlertsConfig = field(default_factory=AlertsConfig)

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


def _merge(base: Any, over: Any) -> Any:
    """`over` laid on `base`: mappings merge key by key, anything else replaces.

    Lists replace rather than append, so an overlay's `zones:` is the whole
    list of zones. Appending would leave no way to remove one.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        merged = dict(base)
        for key, value in over.items():
            merged[key] = _merge(base.get(key), value)
        return merged
    return over


def _apply_overlay(raw: dict) -> dict:
    """`VG_CONFIG_OVERLAY=engine/profiles/cloud.yaml` — a second file laid on top.

    The same reasoning as `VG_CAMERAS`: a different way of running must not
    mean rewriting engine.yaml. The overlay is merged before `${VAR}`
    expansion, so it can name folders and addresses that only exist at start.

    A named overlay that is not there is a hard error. Starting without it
    would start the workstation's configuration somewhere it was not meant
    to run, which is the one outcome the overlay exists to prevent.
    """
    name = os.environ.get("VG_CONFIG_OVERLAY", "").strip()
    if not name:
        return raw

    path = Path(name)
    if not path.is_absolute():
        path = REPO_DIR / path
    if not path.is_file():
        raise ConfigError(f"VG_CONFIG_OVERLAY names {path}, which does not exist")

    over = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(over, dict):
        raise ConfigError(f"VG_CONFIG_OVERLAY {path}: must be a mapping at the top")
    # Lists replace, so `cameras:` here would drop every camera engine.yaml
    # defines. `add_cameras:` appends instead: the cloud trial's pushed webcam
    # joins the site's cameras rather than replacing them.
    added = over.pop("add_cameras", None) or []
    if not isinstance(added, list):
        raise ConfigError(f"VG_CONFIG_OVERLAY {path}: add_cameras must be a list")
    merged = _merge(raw, over)
    if added:
        merged["cameras"] = list(merged.get("cameras") or []) + added
    return merged


def load(path: Path | str | None = None) -> EngineConfig:
    """Read engine.yaml, expand env vars, validate, return a frozen config."""
    cfg_path = Path(path) if path else ENGINE_DIR / "engine.yaml"
    if not cfg_path.is_file():
        raise ConfigError(f"no config at {cfg_path}")

    _load_dotenv(ENGINE_DIR / ".env")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = _apply_overlay(raw)
    raw = _expand(raw, "engine.yaml")

    profile = str(raw.get("profile") or "").strip()
    if profile not in PROFILES:
        raise ConfigError(
            f"profile: {profile!r} is not a profile. Use one of "
            f"{', '.join(repr(p) for p in PROFILES)}"
        )

    cameras = tuple(
        CameraConfig.parse(c, f"cameras[{i}]")
        for i, c in enumerate(raw.get("cameras") or [])
    )
    _reject_duplicates([c.id for c in cameras], "camera")

    # Checked against the whole file, not the running subset: `VG_CAMERAS`
    # narrows what starts, and a neighbour pointing at a camera that exists
    # but is not running today is correct config, not a typo.
    defined = {c.id for c in cameras}
    for camera in cameras:
        for neighbour in camera.neighbours:
            if neighbour not in defined:
                raise ConfigError(
                    f"camera {camera.id!r} lists neighbour {neighbour!r}, "
                    f"which is not defined. Known cameras: "
                    f"{sorted(defined) or 'none'}"
                )
            if neighbour == camera.id:
                raise ConfigError(
                    f"camera {camera.id!r} lists itself as a neighbour"
                )

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

    archive = ArchiveConfig.parse(raw.get("archive"), "archive")
    for camera_id in archive.channels:
        if camera_id not in defined:
            raise ConfigError(
                f"archive.channels names camera {camera_id!r}, which is not "
                f"defined. Known cameras: {sorted(defined) or 'none'}"
            )

    api_raw = raw.get("api") or {}
    store_raw = raw.get("storage") or {}

    return EngineConfig(
        # Blank is a real answer: no site named. `or ""` also catches the
        # key being present but empty, which YAML reads as None — str(None)
        # would put the word "None" in the console's title bar.
        site_name=str(raw.get("site_name") or "").strip(),
        timezone=str(raw.get("timezone", "UTC")),
        hours=HoursConfig.parse(raw.get("hours"), "hours"),
        api=ApiConfig(
            host=str(api_raw.get("host", "127.0.0.1")),
            port=int(api_raw.get("port", 8000)),
            cors_origins=tuple(
                api_raw.get("cors_origins", ApiConfig.cors_origins)
            ),
            poll_seconds=float(api_raw.get("poll_seconds", 5.0)),
            console_dir=(
                _resolve(api_raw["console_dir"], REPO_DIR)
                if api_raw.get("console_dir") else None
            ),
        ),
        profile=profile,
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
        tracking=TrackingConfig.parse(raw.get("tracking"), "tracking"),
        archive=archive,
        vehicles=VehiclesConfig.parse(raw.get("vehicles"), "vehicles"),
        ask=AskConfig.parse(raw.get("ask"), "ask"),
        alerts=AlertsConfig.parse(raw.get("alerts"), "alerts"),
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
