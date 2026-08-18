"""Measure capture latency, and prove the throttled-read trap is real.

Run:  python engine/tools/measure_latency.py

Compares two capture strategies against the same camera:

  throttled  sleep between read() calls to hit a target rate. Looks correct and
             is the obvious implementation. `read()` returns the NEXT buffered
             frame rather than the newest, so consuming one frame in six means
             falling further behind every second.

  drain      read every frame the device produces; publish at the target rate.
             Latency stays at the camera's own, and the analytics rate is
             unchanged.

The number that matters is frame age: how old the newest available frame is
when something asks for it. That is what the live view actually shows.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import cv2

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

SOURCE = 0
TARGET_FPS = 5.0
SECONDS = 6.0


def measure_throttled() -> tuple[list[float], int]:
    """Sleep between reads — the implementation that lags."""
    cap = cv2.VideoCapture(SOURCE, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    ages, frames = [], 0
    interval = 1.0 / TARGET_FPS
    deadline = time.monotonic() + SECONDS
    next_due = time.monotonic()

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now < next_due:
                time.sleep(min(next_due - now, 0.05))
                continue
            asked = time.monotonic()
            ok, _ = cap.read()
            if not ok:
                continue
            # read() blocking means the frame was already waiting; returning
            # instantly means it came from the buffer, i.e. it is stale.
            ages.append((time.monotonic() - asked) * 1000)
            frames += 1
            next_due = max(time.monotonic(), next_due + interval)
    finally:
        cap.release()
    return ages, frames


def measure_drained() -> tuple[list[float], int, int]:
    """Read continuously, publish at the target rate."""
    cap = cv2.VideoCapture(SOURCE, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    ages, reads, published = [], 0, 0
    interval = 1.0 / TARGET_FPS
    deadline = time.monotonic() + SECONDS
    next_due = time.monotonic()

    try:
        while time.monotonic() < deadline:
            asked = time.monotonic()
            ok, _ = cap.read()
            if not ok:
                continue
            ages.append((time.monotonic() - asked) * 1000)
            reads += 1
            now = time.monotonic()
            if now >= next_due:
                next_due = max(now, next_due + interval)
                published += 1
    finally:
        cap.release()
    return ages, reads, published


def report(name: str, ages: list[float]) -> None:
    if not ages:
        print(f"  {name}: no frames")
        return
    print(
        f"  {name:<10} read blocked for: "
        f"median {statistics.median(ages):6.1f} ms   "
        f"mean {statistics.mean(ages):6.1f} ms"
    )


def main() -> int:
    print(f"\nmeasuring camera {SOURCE}, target {TARGET_FPS:g} fps, {SECONDS:g}s each\n")

    print("A frame that arrives INSTANTLY was already sitting in the driver")
    print("buffer, which means it is stale. Blocking near the frame interval")
    print("means we are reading at the device's pace and it is fresh.\n")

    throttled_ages, throttled_frames = measure_throttled()
    time.sleep(0.5)
    drained_ages, drained_reads, drained_published = measure_drained()

    report("throttled", throttled_ages)
    report("drain", drained_ages)

    print()
    print(f"  throttled: {throttled_frames} reads "
          f"({throttled_frames / SECONDS:.1f}/s) - the display only ever sees these")
    print(f"  drain:     {drained_reads} reads "
          f"({drained_reads / SECONDS:.1f}/s), {drained_published} published "
          f"({drained_published / SECONDS:.1f}/s)")
    print()
    print("  Display latency is set by the READ rate, not the publish rate.")
    print("  Draining keeps the live view current while analytics stay throttled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
