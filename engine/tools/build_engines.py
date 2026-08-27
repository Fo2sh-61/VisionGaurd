"""Build a TensorRT engine for every model this engine.yaml configures.

    python engine/tools/build_engines.py            build what is missing
    python engine/tools/build_engines.py --force    rebuild everything
    python engine/tools/build_engines.py --only person weapons

**A TensorRT plan is a build output, never an artifact.** It is compiled
against one GPU architecture and one library version, so it does not travel:
run this on the machine that will serve, as a deployment step. The `.pt` stays
the thing you keep. See models/README.md.

**Why this checks the filesystem instead of trusting a return value.**

Building these the first time cost two silent failures. The cu13 TensorRT
wheel imports cleanly, builds a Logger, and then **segfaults** inside
`trt.Builder()`. A segfault kills the interpreter outright, so the export
reported **exit code 0** and produced no file:

    TensorRT: starting export with TensorRT 11.2.1.2...
    [exited with code 0]

No traceback, no error, no engine. A tool that inferred success from a return
code would have reported six clean builds and produced nothing — which is
exactly the class of untruth this product is not allowed to commit. So every
build here is confirmed by looking for the file afterwards, and the summary at
the end counts files on disk.

**The output is renamed.** ultralytics writes `<stem>.engine`; the loader
looks for `<stem>-<imgsz>.engine`, because a static-shape plan built at 480
cannot serve a model configured at 640 and the size in the filename is what
makes that impossible rather than merely wrong.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

# ultralytics will otherwise pip-install onnx and onnxruntime-gpu mid-build,
# roughly 180 MB, without being asked. Nothing here installs anything.
import os  # noqa: E402

os.environ.setdefault("YOLO_AUTOINSTALL", "false")

from vg import config as vgconfig  # noqa: E402
from vg.infer.shared import engine_path_for, tensorrt_available  # noqa: E402

#: Models that are not ultralytics and have no engine form. Named here so the
#: report says "skipped, and why" rather than silently covering four of six.
NOT_ULTRALYTICS = {
    "face": "OpenCV DNN, not ultralytics - SFace is settled, see AGENTS.md",
}


def fp16_available() -> bool:
    """Can this install build an FP16 engine?

    On TensorRT 11 ultralytics routes FP16 through NVIDIA's `modelopt`
    (`modelopt.onnx.autocast`), which is a separate multi-hundred-megabyte
    package. Without it, asking for `half=True` fails the whole export with
    `ModuleNotFoundError` — and losing the engine entirely to gain nothing is
    a bad trade when FP32 already gives most of the win.

    So: build FP32 and say so. FP16 is roughly another 1.5x on top and is
    worth revisiting once the plate models have been measured under real load.
    """
    try:
        from modelopt.onnx import autocast
    except Exception:
        return False
    return autocast is not None


def build(name: str, weights: Path, imgsz: int, half: bool, force: bool) -> tuple[str, str]:
    """Build one engine. Returns (status, detail). Never raises."""
    target = engine_path_for(weights, imgsz)
    # Silently dropping to FP32 would be its own small untruth, so the
    # precision travels into the report.
    precision = "FP16" if half else "FP32"

    if not weights.is_file():
        return "missing", f"no weights at {weights}"
    if target.exists() and not force:
        size_mb = target.stat().st_size / 1e6
        return "present", f"{target.name} already built ({size_mb:.0f} MB)"

    from ultralytics import YOLO

    started = time.perf_counter()
    try:
        model = YOLO(str(weights))
        produced = model.export(
            format="engine", imgsz=imgsz, half=half, workspace=4,
            device=0, verbose=False,
        )
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"

    # The check that matters. `produced` is whatever ultralytics claims it
    # wrote, and a crashed build claims nothing while still returning.
    produced = Path(produced) if produced else None
    if produced is None or not produced.is_file():
        return "failed", (
            "export returned without writing a file - if there was no error "
            "above, the build crashed the process (see this file's docstring)"
        )

    if produced != target:
        produced.replace(target)
    if not target.is_file():
        return "failed", f"could not place the engine at {target.name}"

    size_mb = target.stat().st_size / 1e6
    return "built", (
        f"{target.name} ({precision}, {size_mb:.0f} MB, "
        f"{time.perf_counter() - started:.0f}s)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="rebuild even where an engine already exists")
    parser.add_argument("--only", nargs="*", metavar="MODEL",
                        help="build only these models from engine.yaml")
    args = parser.parse_args()

    try:
        cfg = vgconfig.load()
    except vgconfig.ConfigError as exc:
        print(f"config is not loadable: {exc}")
        return 2

    if not tensorrt_available():
        print("TensorRT is not importable, so nothing can be built here.")
        print()
        print("  pip install tensorrt_cu12_bindings tensorrt_cu12_libs")
        print("  pip install tensorrt-cu12")
        print()
        print("Install the cu12 line, not `tensorrt` - the cu13 build imports")
        print("and then segfaults at Builder() against a cu128 torch.")
        print("Every model keeps working on .pt over CUDA meanwhile, and")
        print("System Health says which form each one loaded.")
        return 1

    half = fp16_available()
    if not half:
        print("  modelopt is not installed, so engines are built FP32.")
        print("  TensorRT 11 routes FP16 through it; FP32 needs nothing extra")
        print("  and already gives most of the speed-up.")
        print()

    wanted = set(args.only or [])
    results: list[tuple[str, str, str]] = []

    for name, spec in sorted(cfg.models.items()):
        if wanted and name not in wanted:
            continue
        if name in NOT_ULTRALYTICS:
            results.append((name, "skipped", NOT_ULTRALYTICS[name]))
            continue

        print(f"  {name:14} building at {spec.imgsz}...", flush=True)
        status, detail = build(
            name, spec.weights, spec.imgsz, spec.half and half, args.force)
        results.append((name, status, detail))
        print(f"  {name:14} {status:8} {detail}", flush=True)

    print()
    print("  " + "-" * 66)
    for name, status, detail in results:
        mark = {"built": "ok", "present": "ok", "skipped": "--"}.get(status, "!!")
        print(f"  [{mark}] {name:14} {status:8} {detail}")

    failed = [n for n, s, _ in results if s in ("failed", "missing")]
    print()
    if failed:
        # Not a hard error. P6-FR-033: a model with no engine runs on .pt over
        # CUDA and System Health says so. Reporting it is the requirement;
        # stopping the deployment over it is not.
        print(f"  {len(failed)} model(s) have no engine: {', '.join(failed)}")
        print("  Those run unaccelerated on the GPU. The console will say so.")
    else:
        print("  every configured model has an engine for its input size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
