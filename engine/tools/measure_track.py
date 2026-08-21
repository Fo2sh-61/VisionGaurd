"""Measure how fast this machine actually handles recorded video.

Every waiting time the Track page quotes comes from the row this writes. Until
it has been run, the page says the wait is unknown and sweeps are refused —
which is the point. A number typed by a developer on a different machine is
not an estimate, it is a decoration, and the one place it would be read is the
one place somebody is deciding whether to wait.

Two numbers, both measured against whatever `archive.backend` is configured:

  fetch_x       how fast video arrives, as a multiple of real time. 4.0 means
                a minute of footage is fetched in fifteen seconds. A local
                file is fast; a DVR over a busy network may be below 1.0, and
                that is exactly the case worth knowing about.

  process_fps   frames a second through detection and re-encoding, which is
                the other half of the wait.

    python engine/tools/measure_track.py                    measure and store
    python engine/tools/measure_track.py --seconds 120      a longer sample
    python engine/tools/measure_track.py --camera cam-clip  a specific camera
    python engine/tools/measure_track.py --show             print what is stored

The measurement is deliberately end-to-end: it fetches through the configured
backend and processes with the real detector, because the thing being promised
to an operator is the whole round trip and not the model's benchmark speed.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.clock import clock_for  # noqa: E402
from vg.events.anchors import AnchorStore  # noqa: E402
from vg.ingest.archive import (  # noqa: E402
    SOURCE_FPS,
    ArchiveUnavailable,
    backend_for,
    estimate_for,
)

#: How much video to sample. Two minutes is long enough that start-up cost is
#: not the whole measurement and short enough that nobody skips running it.
DEFAULT_SECONDS = 120.0

#: The wall-clock a sweep is allowed to take. Derived numbers are quoted
#: against it, and the sweep endpoint refuses anything over it.
SWEEP_BUDGET_SECONDS = 15 * 60.0


def database(cfg) -> Path:
    raw = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
    return raw if raw.is_absolute() else vgconfig.REPO_DIR / raw


def pick_span(source, cameras, wanted: float):
    """A camera and a span the archive can actually serve.

    Measuring against a span that is not there measures the error path, which
    is fast and meaningless.
    """
    for camera in cameras:
        covered = source.coverage(camera.id)
        for start, end, _clip in covered:
            have = (end - start).total_seconds()
            if have >= 5.0:
                span = min(wanted, have)
                return camera.id, start, start + timedelta(seconds=span)
    return None, None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                        help="how much video to sample")
    parser.add_argument("--camera", help="measure this camera only")
    parser.add_argument("--show", action="store_true",
                        help="print the stored measurement and exit")
    parser.add_argument("--start", help="ISO instant to sample from (dvr backend)")
    args = parser.parse_args()

    cfg = vgconfig.load()
    store = AnchorStore(database(cfg), cfg.timezone)

    try:
        if args.show:
            rates = store.rates()
            if rates is None:
                print("Nothing measured yet. Run this without --show.")
                return 1
            print(f"backend      {rates.backend or 'unknown'}")
            print(f"fetch_x      {rates.fetch_x:.2f}x real time")
            print(f"process_fps  {rates.process_fps:.1f} frames/sec")
            print(f"measured     {rates.measured_at.isoformat(timespec='seconds')}")
            report(rates, cfg)
            return 0

        try:
            source = backend_for(
                cfg.archive, cfg.storage.footage_dir, clock_for(cfg.timezone))
        except ArchiveUnavailable as exc:
            print(f"No archive to measure: {exc}")
            return 2

        cameras = [c for c in cfg.cameras if not args.camera or c.id == args.camera]
        if not cameras:
            print(f"No camera called {args.camera!r} in engine.yaml.")
            return 2

        if args.start:
            start = datetime.fromisoformat(args.start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            camera_id = cameras[0].id
            end = start + timedelta(seconds=args.seconds)
        else:
            camera_id, start, end = pick_span(source, cameras, args.seconds)
            if camera_id is None:
                print("The archive holds nothing to measure against. For the "
                      "footage backend, put a clip in "
                      f"{cfg.storage.footage_dir}. For a dvr, pass --start.")
                return 2

        span = (end - start).total_seconds()
        print(f"Measuring {cfg.archive.backend} on {camera_id}: "
              f"{span:.0f}s from {start.isoformat(timespec='seconds')}")

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "sample.mp4"

            began = time.perf_counter()
            try:
                source.fetch(camera_id, start, end, raw)
            except ArchiveUnavailable as exc:
                print(f"Fetch failed: {exc}")
                return 2
            fetch_seconds = max(0.001, time.perf_counter() - began)
            fetch_x = span / fetch_seconds
            print(f"  fetch     {fetch_seconds:6.1f}s  ->  {fetch_x:.2f}x real time")

            process_fps = measure_processing(raw)
            if process_fps is None:
                print("  process   skipped — no person model could be loaded")
                return 2
            print(f"  process   {process_fps:6.1f} frames/sec")

        rates = store.set_rates(
            fetch_x, process_fps, backend=cfg.archive.backend)
        print("\nStored. The Track page now quotes these numbers.")
        report(rates, cfg)
        return 0

    finally:
        store.close()


def measure_processing(clip: Path) -> float | None:
    """Frames a second through detection and re-encoding, end to end."""
    import cv2

    try:
        from vg.infer.persons import PersonDetector
    except Exception as exc:  # pragma: no cover - depends on the install
        print(f"  (no detector: {exc})")
        return None

    spec = None
    cfg = vgconfig.load()
    for name in ("person", "people", "yolo"):
        spec = cfg.models.get(name)
        if spec is not None:
            break
    if spec is None:
        print("  (no `person` model in engine.yaml)")
        return None

    try:
        detector = PersonDetector(
            weights=spec.weights, device=spec.device, imgsz=spec.imgsz,
            conf=spec.conf,
        )
    except Exception as exc:  # pragma: no cover - depends on the machine
        print(f"  (detector would not load: {exc})")
        return None

    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        return None

    frames = 0
    began = time.perf_counter()
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            detector.detect(frame)
            frames += 1
    finally:
        capture.release()

    elapsed = max(0.001, time.perf_counter() - began)
    return frames / elapsed


def report(rates, cfg) -> None:
    """What those numbers mean for the two waits an operator actually sees."""
    chunk = cfg.archive.chunk_seconds
    first = estimate_for(chunk / 3600.0, rates, budget_seconds=1e9,
                         chunk_seconds=chunk)
    print(f"\nFirst {chunk:.0f}s of video ready in about "
          f"{first.seconds:.0f}s.")
    if first.seconds > 15:
        print("  That is over the 10-15s the page promises. Drop "
              "`archive.chunk_seconds` to 15 and measure again.")

    hour = estimate_for(1.0, rates, budget_seconds=SWEEP_BUDGET_SECONDS)
    print(f"One camera-hour of sweep: about {hour.seconds / 60:.0f} min "
          f"({'allowed' if hour.allowed else 'over budget'}).")
    budget_hours = SWEEP_BUDGET_SECONDS / max(0.01, hour.seconds) if hour.seconds else 0
    print(f"A sweep may cover roughly {budget_hours:.1f} camera-hours "
          f"within the {SWEEP_BUDGET_SECONDS / 60:.0f} minute limit.")
    print(f"(Frame counts assume {SOURCE_FPS:.0f} fps footage.)")


if __name__ == "__main__":
    raise SystemExit(main())
