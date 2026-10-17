"""List every model file this site needs, and say which are missing.

    python engine/tools/check_models.py

The installer runs this after copying the owner's models and before it starts
the service. Under the service (`VG_STRICT=1`) a missing model stops the
engine, which on a site means the whole system is down; checking here moves
that stop to the install, with the file's name and where it goes.

It reads the same config the engine does (engine.yaml, or `VG_HOME`'s), plus
any cameras added from the console. It never downloads or fetches anything:
the owner supplies every model.

What needs what mirrors the `_start_*` functions in `vg/api/app.py`:

- enrolment always starts, so the two face models are always needed;
- any enabled camera loads person detection and fall detection;
- `weapons`, `lostitems` and a gate camera with `vehicles` add their own;
- `track` needs the appearance matcher package, which ships in the repo.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402

#: Where the two face models live. FacePipeline reads them from here, not from
#: engine.yaml.
FACE_DIR = vgconfig.REPO_DIR / "models"
FACE_FILES = ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx")


@dataclass(frozen=True)
class Need:
    #: The file, or None when engine.yaml has no entry for it.
    path: Path | None
    #: Which feature needs it, and on which cameras.
    why: str
    #: The engine.yaml `models:` key, when it comes from there.
    config_key: str = ""

    @property
    def present(self) -> bool:
        return self.path is not None and self.path.is_file()


def _cameras(roster: Sequence[vgconfig.CameraConfig], feature: str | None = None,
             *, gate: bool = False) -> list[str]:
    return [c.id for c in roster if c.enabled
            and (feature is None or feature in c.features)
            and (not gate or c.is_gate)]


def needed(cfg: vgconfig.EngineConfig,
           roster: Sequence[vgconfig.CameraConfig]) -> list[Need]:
    out = [Need(FACE_DIR / f, "enrolment (always on)") for f in FACE_FILES]

    def model(key: str, why: str, default: Path | None = None) -> None:
        spec = cfg.models.get(key)
        out.append(Need(spec.weights if spec else default, why, key))

    enabled = _cameras(roster)
    if enabled:
        on = f"every enabled camera: {', '.join(enabled)}"
        # PersonDetector falls back to this file when engine.yaml has no entry.
        model("person", f"person detection ({on})",
              vgconfig.REPO_DIR / "models" / "yolov8s.pt")
        model("pose", f"fall detection ({on})")
        model("falls", f"fall detection ({on})")

    for key, feature, label, gate in (
        ("weapons", "weapons", "knife detection", False),
        ("bags", "lostitems", "lost items", False),
        ("plates", "vehicles", "plate reading", True),
        ("plate_chars", "vehicles", "plate reading", True),
    ):
        cams = _cameras(roster, feature, gate=gate)
        if cams:
            model(key, f"{label} ({', '.join(cams)})")
    return out


def _tracking_missing(roster: Sequence[vgconfig.CameraConfig]) -> str | None:
    cams = _cameras(roster, "track")
    if not cams or importlib.util.find_spec("loiterwatch") is not None:
        return None
    return (f"missing: the appearance matcher → pip install "
            f"{vgconfig.REPO_DIR / 'models' / 'reid' / 'loiterwatch'} "
            f"(person tracking: {', '.join(cams)})")


def report(cfg: vgconfig.EngineConfig,
           roster: Sequence[vgconfig.CameraConfig]) -> int:
    """Print every need. Returns 1 when anything is missing."""
    needs = needed(cfg, roster)
    missing = 0
    for n in needs:
        if n.path is None:
            missing += 1
            print(f"missing: no '{n.config_key}' entry in engine.yaml models: "
                  f"→ add one ({n.why})")
        elif not n.present:
            missing += 1
            print(f"missing: {n.path.name} → {n.path}  ({n.why})")
        else:
            print(f"ok:      {n.path.name}  ({n.why})")
    tracking = _tracking_missing(roster)
    if tracking:
        missing += 1
        print(tracking)
    if missing:
        print(f"\n{missing} missing. The owner supplies every model; nothing is "
              f"downloaded. Copy them in and run this again.")
        return 1
    print("\nevery model this site needs is in place.")
    return 0


def _roster(cfg: vgconfig.EngineConfig) -> list[vgconfig.CameraConfig]:
    """engine.yaml's cameras plus any added from the console, as the engine does."""
    from vg.ingest.store import CameraStore, merge_cameras

    raw = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
    database = raw if raw.is_absolute() else vgconfig.REPO_DIR / raw
    if not database.is_file():
        return list(cfg.cameras)
    return list(merge_cameras(cfg.cameras, CameraStore(database).all()))


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = vgconfig.load()
    except vgconfig.ConfigError as exc:
        print(f"engine.yaml does not load: {exc}")
        return 1
    return report(cfg, _roster(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
