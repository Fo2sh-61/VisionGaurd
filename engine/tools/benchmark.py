"""How fast the models run on this machine, and what that means for 208 cameras.

Run:  python engine/tools/benchmark.py

P1-06. `docs/PLAN.md` section 7 lists latency targets and says plainly that
nothing has been measured. This measures the one that sets the hardware bill:
**camera -> detection ready**, the person-detection pass every body feature
waits on.

It runs against the labelled clip, not random noise. Noise gives a number for
a picture the model will never see; the clip is the footage the regression
suite already uses, so the timing is for work the engine actually does. It
falls back to synthetic frames only if the clip is missing.

The sizing arithmetic at the end is deliberately blunt: cameras x rate divided
by measured throughput. It assumes every camera runs person detection at the
same rate, which is the pessimistic case and not the intended deployment - not
every camera will run every model. Treat it as an upper bound to design down
from, and re-run it on the real workstation before anything is bought.

Nothing here is a claim about accuracy. It measures speed only.
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

TARGET_CAMERAS = 208
RATES = (1, 2, 5)
WARMUP = 8


def _frames(count: int) -> list[np.ndarray]:
    """Real frames from the labelled clip, or synthetic if it is not here."""
    clips = sorted(glob.glob(str(ENGINE_DIR / "data" / "footage" / "*.mp4")))
    walk = [c for c in clips if "walk-through" in c] or clips
    if not walk:
        print("  no clip found - using synthetic frames, timings are indicative")
        return [np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
                for _ in range(count)]

    cap = cv2.VideoCapture(walk[0])
    out: list[np.ndarray] = []
    while len(out) < count:
        ok, frame = cap.read()
        if not ok:
            break
        out.append(frame)
    cap.release()
    print(f"  frames from {Path(walk[0]).name}")
    return out or [np.zeros((480, 640, 3), dtype=np.uint8)]


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=60,
                        help="frames to time (default 60)")
    parser.add_argument("--cameras", type=int, default=TARGET_CAMERAS)
    args = parser.parse_args(argv)

    from vg.infer.persons import PersonDetector

    print("\nVisionGuard benchmark - person detection\n")
    frames = _frames(args.frames + WARMUP)

    detector = PersonDetector()
    print(f"  device  {detector.device}")
    print(f"  weights {detector.weights.name}")
    try:
        import torch
        if detector.device != "cpu" and torch.cuda.is_available():
            print(f"  gpu     {torch.cuda.get_device_name(0)}")
    except Exception:
        pass
    print()

    for frame in frames[:WARMUP]:
        detector.raw_boxes(frame)

    timings: list[float] = []
    people_seen = 0
    for frame in frames[WARMUP:]:
        started = time.perf_counter()
        boxes = detector.raw_boxes(frame)
        timings.append((time.perf_counter() - started) * 1000)
        people_seen += 0 if boxes is None else len(boxes)

    if not timings:
        print("  no frames timed")
        return 1

    p50, p95 = _percentile(timings, 50), _percentile(timings, 95)
    mean = statistics.fmean(timings)
    throughput = 1000.0 / mean

    print(f"  frames timed      {len(timings)}")
    print(f"  people detected   {people_seen}")
    print(f"  p50               {p50:6.1f} ms")
    print(f"  p95               {p95:6.1f} ms   <- PLAN section 7 budget: 250 ms")
    print(f"  mean              {mean:6.1f} ms")
    print(f"  throughput        {throughput:6.1f} frames/sec\n")

    verdict = "MEETS" if p95 <= 250 else "MISSES"
    print(f"  camera -> detection ready: {verdict} the 250 ms p95 budget\n")

    print(f"  Scaling to {args.cameras} cameras, every camera detecting:")
    for hz in RATES:
        need = args.cameras * hz
        print(f"    @ {hz} Hz = {need:>5} frames/sec"
              f"  ->  {need / throughput:5.1f}x this machine")
    print("\n  Upper bound: assumes every camera runs person detection at that")
    print("  rate. Real deployments run fewer models on fewer cameras.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
