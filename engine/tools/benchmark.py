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
    parser.add_argument("--model", choices=("person", "weapons", "bags"), default="person",
                        help="which model to time (default person)")
    args = parser.parse_args(argv)

    # The knife model is timed the same way, on the same clip, so the two rows
    # in PLAN section 7 are comparable. It is a second pass on top of the
    # person one - but only on frames that had somebody in them, which is why
    # the sizing arithmetic below stays the person model's question.
    if args.model == "weapons":
        from vg.infer.weapons import WeaponDetector as Detector
    elif args.model == "bags":
        from vg.infer.bags import BagDetector as Detector
    else:
        from vg.infer.persons import PersonDetector as Detector

    print(f"\nVisionGuard benchmark - {args.model} detection\n")
    frames = _frames(args.frames + WARMUP)

    detector = Detector()
    print(f"  device  {detector.device}")
    print(f"  weights {detector.weights.name}")
    try:
        import torch
        if detector.device != "cpu" and torch.cuda.is_available():
            print(f"  gpu     {torch.cuda.get_device_name(0)}")
    except Exception:
        pass
    print()

    # `raw_boxes` on the person model returns ultralytics boxes with no
    # conversion; the knife model has no such split and is timed through
    # `detect`. Both are one model pass - turning boxes into fractions is a
    # handful of floats and does not move the number.
    def run(frame):
        if args.model in ("weapons", "bags"):
            return detector.detect(frame)
        return detector.raw_boxes(frame)

    for frame in frames[:WARMUP]:
        run(frame)

    timings: list[float] = []
    found = 0
    for frame in frames[WARMUP:]:
        started = time.perf_counter()
        boxes = run(frame)
        timings.append((time.perf_counter() - started) * 1000)
        found += 0 if boxes is None else len(boxes)

    if not timings:
        print("  no frames timed")
        return 1

    p50, p95 = _percentile(timings, 50), _percentile(timings, 95)
    mean = statistics.fmean(timings)
    throughput = 1000.0 / mean

    print(f"  frames timed      {len(timings)}")
    label = {"weapons": "knives detected",
             "bags": "bags detected"}.get(args.model, "people detected")
    print(f"  {label:<17} {found}")
    print(f"  p50               {p50:6.1f} ms")
    print(f"  p95               {p95:6.1f} ms   <- PLAN section 7 budget: 250 ms")
    print(f"  mean              {mean:6.1f} ms")
    print(f"  throughput        {throughput:6.1f} frames/sec\n")

    verdict = "MEETS" if p95 <= 250 else "MISSES"
    print(f"  camera -> detection ready: {verdict} the 250 ms p95 budget\n")

    if args.model == "weapons":
        # The labelled clip contains no knife, so the count above should be 0.
        # Anything else is a false positive worth looking at, not a timing
        # result.
        print("  The labelled clip contains no knife, so any detection above")
        print("  is a false positive rather than a hit.\n")

    if args.model == "bags":
        # Same for bags - and unlike knives, this one is known to fire. See
        # research D10: a black office chair reads as `suitcase` at up to
        # 0.88 and holds it for seconds, which the two-frame rule cannot
        # catch. A count above zero here is expected, not a regression.
        print("  The labelled clip contains no bag, so any detection above")
        print("  is a false positive rather than a hit. Some are expected:")
        print("  research D10 measured 19 over 706 sampled frames.")
        print()

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
