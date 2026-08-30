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


#: What share of cameras runs each feature, and how often.
#:
#: A DEFAULT, not a fact. The real mix belongs to a site, and nobody has fixed
#: this one yet - which is exactly why the camera count is an ARGUMENT rather
#: than a constant. `--site 40 --mix person=1.0@2,faces=0.1@5` answers for a
#: different site without this file being edited.
#:
#: Read `feature=share@hz`: `person=1.0@2` is every camera running the person
#: pass twice a second.
DEFAULT_MIX = "person=1.0@2,faces=0.15@5,plates=0.05@5"

#: Per-frame cost of the parts that are NOT the person model, in milliseconds.
#:
#: These are ASSUMPTIONS, and the output labels them as such. They come from
#: this project's own earlier measurements - engine.yaml records ~44 ms for
#: YuNet plus SFace, and the plate pair is timed in docs/PLAN.md - but they
#: were not measured by THIS run, and a projection that presented them as if
#: they were would be the confident fiction Principle III forbids.
ASSUMED_MS = {
    "faces": 44.0,
    # The patrol tier is the SAME pipeline - YuNet plus SFace - just run
    # slower and on the other cameras. Same cost per frame; the saving was
    # always in the rate and the camera count, never in the model.
    "patrol": 44.0,
    "plates": 12.0,
    "decode": 6.0,
}

#: Frames per second a camera actually delivers, for the decode line.
CAMERA_FPS = 25.0


def _parse_mix(spec):
    """`person=1.0@2,faces=0.15@5` -> {"person": (1.0, 2.0), ...}"""
    mix = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, rest = part.partition("=")
        share, _, hz = rest.partition("@")
        name = name.strip()
        if name != "person" and name not in ASSUMED_MS:
            # Refused, not costed at zero. A typo that silently contributes
            # nothing produces a confident total that is quietly too low -
            # and a sizing figure that is too low is how a site ends up one
            # box short. Say the name is unknown instead.
            known = ", ".join(sorted(["person", *ASSUMED_MS]))
            raise SystemExit(
                f"unknown feature {name!r} in --mix. Known: {known}. "
                "Add its per-frame cost to ASSUMED_MS if it is real."
            )
        mix[name] = (float(share), float(hz or 1))
    return mix


def _site(cameras, mix_spec, person_ms, cores, decode_hz=CAMERA_FPS):
    """What a whole site costs per second, and how many boxes that needs.

    The unit is **seconds of processor time per second of wall clock**, and it
    is the honest one for this question. An 8-core box supplies 8 seconds of
    processor time every second, so "needs 25" against "has 8" is a
    comparison anybody can make. Frames per second is not - it hides how many
    models each frame goes through.

    Two things this deliberately does NOT do:

    - **Assume a camera count.** It is an argument. The site being sized has
      not fixed its count, and a tool with 208 written into it would have to
      be edited the day that changed.
    - **Blur measured and assumed.** The person figure was timed by this run
      on this machine. Everything else is a number carried in from an earlier
      one. They are printed under separate headings because a reader deciding
      what hardware to buy needs to know which is which.
    """
    mix = _parse_mix(mix_spec)

    print()
    print(f"  Sizing {cameras} cameras")
    print()
    print(f"    {'what':<10} {'cameras':>8} {'Hz':>6} {'ms':>7} {'s/s':>8}")
    print(f"    {'-' * 10} {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 8}")

    total = 0.0
    for name, (share, hz) in mix.items():
        count = cameras * share
        ms = person_ms if name == "person" else ASSUMED_MS.get(name, 0.0)
        cost = count * hz * ms / 1000.0
        total += cost
        print(f"    {name:<10} {count:>8.0f} {hz:>6.1f} {ms:>7.1f} {cost:>8.2f}")

    # Every camera, every frame, whether anything reads it or not. This is the
    # line workload placement removes: decoding at the camera's rate when the
    # analytics only ever look at a few frames a second.
    decode = cameras * ASSUMED_MS["decode"] * decode_hz / 1000.0
    total += decode
    print(f"    {'decode':<10} {cameras:>8d} {decode_hz:>6.1f} "
          f"{ASSUMED_MS['decode']:>7.1f} {decode:>8.2f}")

    per_camera = total / cameras if cameras else 0.0
    boxes = max(1, int(-(-total // cores))) if total else 1
    fits = int(cores / per_camera) if per_camera else 0

    print()
    print(f"    site         {total:8.2f} s of processor time per second")
    print(f"    per camera   {per_camera:8.3f} s/s")
    print(f"    on {cores} cores  {total / cores:8.2f}x the box  ->  {boxes} box(es)")
    print(f"    one {cores}-core box carries about {fits} cameras of this mix")
    print()
    print("    MEASURED by this run, on this machine: the person row.")
    print("    ASSUMED from earlier runs: faces, plates, decode.")
    print("    The site total is arithmetic over those, not an observation of")
    print("    a site that exists. Re-run on the deployment box before buying.")
    print()
    return 0


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
    parser.add_argument("--site", type=int, metavar="CAMERAS",
                        help="size a whole site of this many cameras")
    parser.add_argument("--mix", default=DEFAULT_MIX, metavar="SPEC",
                        help="per-feature share of cameras, e.g. person=1.0@2")
    parser.add_argument("--cores", type=int, default=8,
                        help="processor cores on the target box (default 8)")
    parser.add_argument("--decode-hz", type=float, default=CAMERA_FPS,
                        help=f"frames decoded per camera per second "
                             f"(default {CAMERA_FPS:.0f} - the camera's own "
                             f"rate. Pass the analytics rate to see what "
                             f"`live_capture: watched` saves)")
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
    if args.site:
        return _site(args.site, args.mix, mean, args.cores, args.decode_hz)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
