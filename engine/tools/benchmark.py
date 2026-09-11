"""How fast the models run on this machine, and what that means for 208 cameras.

Run:  python engine/tools/benchmark.py
      python engine/tools/benchmark.py --site 100     # size a whole site
      python engine/tools/benchmark.py --decode       # what capture costs

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

`--decode` measures something else, and needs no model: how a camera frame's
capture cost splits between `grab()` and `retrieve()`. That split decides
what `live_capture: watched` saves, and it was once assumed rather than
measured - see `_decode_split`.
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
import time
from dataclasses import dataclass
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
    # One camera frame taken all the way to pixels: `grab()` plus
    # `retrieve()`. How that splits between the two IS measured - by
    # `_decode_split`, on the clip. The 6 ms total is not: nothing in the
    # repository records where it came from. It stays, labelled as assumed,
    # until a recording from a real site camera is timed with `--clip`.
    "decode": 6.0,
}

#: Frames per second a camera actually delivers, for the capture rows.
CAMERA_FPS = 25.0

#: Passes over the clip for each column of the decode split. The two columns
#: are timed alternately, so a laptop that warms up or throttles part-way
#: through shifts both of them rather than one.
DECODE_ROUNDS = 3


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


def _demand(cameras, mix, person_ms, decode_hz, share):
    """One row per cost: (what, cameras, Hz, ms a frame, cores).

    Capture is two rows because it is two costs, and only one of them is
    optional:

    - `grab` is paid on EVERY frame each camera sends, watched or not. On
      OpenCV's FFmpeg backend `grab()` reads the frame and decodes it.
    - `retrieve` is paid only on frames something reads - `decode_hz` of them
      a second. It turns the decoded frame into BGR pixels and copies it out.

    `share` is retrieve()'s part of a whole frame's cost, 0..1. At 0,
    `live_capture: watched` saves nothing; at 1, skipping retrieve() would
    skip the whole decode - which is what the 30 Aug figures assumed, and
    what OpenCV does not do.
    """
    rows = []
    for name, (part, hz) in mix.items():
        count = cameras * part
        ms = person_ms if name == "person" else ASSUMED_MS.get(name, 0.0)
        rows.append((name, count, hz, ms, count * hz * ms / 1000.0))

    grab_ms = ASSUMED_MS["decode"] * (1.0 - share)
    retrieve_ms = ASSUMED_MS["decode"] * share
    rows.append(("grab", cameras, CAMERA_FPS, grab_ms,
                 cameras * CAMERA_FPS * grab_ms / 1000.0))
    rows.append(("retrieve", cameras, decode_hz, retrieve_ms,
                 cameras * decode_hz * retrieve_ms / 1000.0))
    return rows


def _fit(total, cameras, cores):
    """(cores per camera, boxes needed, cameras one box carries)."""
    per_camera = total / cameras if cameras else 0.0
    boxes = max(1, int(-(-total // cores))) if total else 1
    fits = int(cores / per_camera) if per_camera else 0
    return per_camera, boxes, fits


def _site(cameras, mix_spec, person_ms, cores, decode_hz=CAMERA_FPS, shares=()):
    """What a whole site costs, and how many boxes that needs.

    The unit is **cores**: how many processor cores the work would keep
    busy, flat out, all the time. An 8-core box supplies 8, so "needs 25"
    against "has 8" is a comparison anybody can make. (It is the same number
    as seconds of processor time per second, said plainly.) Frames per
    second is not - it hides how many models each frame goes through.

    `shares` are the measured retrieve() shares from `_decode_split`. The
    table uses the SMALLEST, because it credits `watched` with the least and
    so gives the biggest bill - a sizing figure that is too low is how a site
    ends up one box short. The other end is printed beside it, since the
    real figure lies between them. No shares means nothing was measured,
    and then `watched` is credited with no saving at all.

    Two things this deliberately does NOT do:

    - **Assume a camera count.** It is an argument. The site being sized has
      not fixed its count, and a tool with 208 written into it would have to
      be edited the day that changed.
    - **Blur measured and assumed.** The person figure and the capture split
      were timed by this run on this machine. Everything else is a number
      carried in from an earlier one. They are printed under separate
      headings because a reader deciding what hardware to buy needs to know
      which is which.
    """
    mix = _parse_mix(mix_spec)
    low = min(shares) if shares else 0.0
    high = max(shares) if shares else 0.0

    print()
    print(f"  Sizing {cameras} cameras")
    print()
    print(f"    {'what':<10} {'cameras':>8} {'Hz':>6} {'ms':>7} {'cores':>8}")
    print(f"    {'-' * 10} {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 8}")

    rows = _demand(cameras, mix, person_ms, decode_hz, low)
    for name, count, hz, ms, cost in rows:
        print(f"    {name:<10} {count:>8.0f} {hz:>6.1f} {ms:>7.1f} {cost:>8.2f}")
    total = sum(row[-1] for row in rows)

    print()
    print("    grab      the decode. Every frame each camera sends, watched or not.")
    print("    retrieve  turning a decoded frame into pixels. Only the frames")
    if shares:
        print(f"              something reads; {low:.0%} of a frame's cost, measured.")
    else:
        print("              something reads. NOT measured - no clip - so no")
        print("              saving is credited to `live_capture: watched`.")

    per_camera, boxes, fits = _fit(total, cameras, cores)
    print()
    print(f"    site needs   {total:6.2f} cores working flat out")
    print(f"    per camera   {per_camera:6.3f} of a core")
    print(f"    on {cores} cores   {total / cores:6.2f}x the box  ->  {boxes} box(es)")
    print(f"    one {cores}-core box carries about {fits} cameras of this mix")

    other = sum(row[-1] for row in _demand(cameras, mix, person_ms, decode_hz, high))
    if shares and round(other, 2) != round(total, 2):
        _, other_boxes, other_fits = _fit(other, cameras, cores)
        print()
        print(f"    At the other measured share, {high:.0%}, the same site needs")
        print(f"    {other:.2f} cores, {other_boxes} box(es), about {other_fits} "
              f"cameras a box.")
        print("    The real figure is between the two; this tool cannot say where.")

    print()
    print("    MEASURED by this run, on this machine: the person row, and how a")
    print("    frame's capture cost splits between grab and retrieve.")
    print("    ASSUMED, carried from earlier runs: every other row's ms, and the")
    print(f"    {ASSUMED_MS['decode']:.0f} ms a frame costs to capture in all.")
    print("    The site total is arithmetic over those, not an observation of")
    print("    a site that exists. Re-run on the deployment box before buying.")
    print()
    return 0


# ---------------------------------------------------------------------------
# What capture costs, and which part of it `live_capture: watched` removes
# ---------------------------------------------------------------------------
#
# `CameraSource.read()` calls `grab()` on every frame and `retrieve()` only on
# the frames something will read. Workload placement costed that as skipping
# the decode on four frames in five. OpenCV does not work that way: on the
# FFmpeg backend `grab()` reads the packet AND decodes it, and `retrieve()`
# only converts the decoded frame to BGR and copies it out. So what `watched`
# skips is the retrieve() share of a frame, and this measures that share
# instead of assuming it.


@dataclass
class DecodeSplit:
    """Processor ms per frame for `grab()` alone and `grab()` + `retrieve()`."""

    threads: int
    frames: int
    grab_ms: float
    both_ms: float
    round_shares: list[float]

    @property
    def share(self) -> float:
        """retrieve()'s part of a frame's cost, 0..1.

        Floored at 0. When retrieve() is lost in the noise the two columns can
        come out the wrong way round, and a negative share would mean skipping
        retrieve() made capture dearer - noise, not a finding.
        """
        if self.both_ms <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.both_ms - self.grab_ms) / self.both_ms))


def _clip(path: str | None = None) -> Path | None:
    """The recording to time: `--clip` if given, else the labelled clip."""
    if path:
        if not Path(path).is_file():
            # Refused rather than replaced by the default. A timing that
            # quietly came from a different recording would be reported as
            # the one asked for.
            raise SystemExit(f"no such clip: {path}")
        return Path(path)
    clips = sorted(glob.glob(str(ENGINE_DIR / "data" / "footage" / "*.mp4")))
    walk = [c for c in clips if "walk-through" in c] or clips
    return Path(walk[0]) if walk else None


def _decode_pass(clip: Path, retrieve: bool,
                 threads: int | None) -> tuple[int, int, float]:
    """One pass over the whole clip: (decoder threads, frames, processor s).

    Processor time for the whole process, not wall time: FFmpeg decodes on
    threads of its own, and a wall clock would show the work being shared
    out rather than the work. It is the unit `--site` adds up.

    Not paced. A real camera hands over a frame every 40 ms; this takes them
    as fast as they come. Pacing was tried and is not reliable here: Windows
    charges processor time, at each clock tick, to whichever thread happens
    to be running, so a loop that sleeps between frames is mis-counted. Paced
    runs on this laptop put retrieve() anywhere from 35% to 90% of a frame.
    """
    params = [] if threads is None else [cv2.CAP_PROP_N_THREADS, threads]
    cap = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG, params)
    if not cap.isOpened():
        raise SystemExit(f"FFmpeg could not open {clip}")
    used = int(cap.get(cv2.CAP_PROP_N_THREADS))
    frames = 0
    started = time.process_time()
    while cap.grab():
        if retrieve:
            cap.retrieve()
        frames += 1
    spent = time.process_time() - started
    cap.release()
    return used, frames, spent


def _decode_split(clip: Path, threads: int | None = None,
                  rounds: int = DECODE_ROUNDS) -> DecodeSplit:
    """Time `grab()` alone against `grab()` + `retrieve()` over the clip.

    `threads=None` is FFmpeg's own choice, which is how the engine opens a
    camera. `threads=1` is the work alone, without the cost of sharing it
    out - and the two give very different answers, which is why both are
    reported rather than one.
    """
    _decode_pass(clip, False, threads)          # warm-up: disk cache, codec start
    used = frames = 0
    grab_s = both_s = 0.0
    shares: list[float] = []
    for _ in range(rounds):
        used, grab_n, grab_t = _decode_pass(clip, False, threads)
        _, both_n, both_t = _decode_pass(clip, True, threads)
        frames += grab_n
        grab_s += grab_t
        both_s += both_t
        if grab_n and both_n and both_t > 0:
            per_grab, per_both = grab_t / grab_n, both_t / both_n
            shares.append((per_both - per_grab) / per_both)
    per_pass = frames // rounds if rounds else 0
    return DecodeSplit(
        threads=used,
        frames=per_pass,
        grab_ms=grab_s * 1000 / frames if frames else 0.0,
        both_ms=both_s * 1000 / frames if frames else 0.0,
        round_shares=shares,
    )


def _measure_capture(clip: Path | None) -> list[DecodeSplit]:
    """Measure and print the decode split. Empty if there is no clip."""
    print()
    if clip is None:
        print("  Capture split NOT measured - no clip. Pass --clip, or put the")
        print("  labelled recording in engine/data/footage/.")
        return []

    probe = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG)
    size = (f"{int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))}, "
            f"{probe.get(cv2.CAP_PROP_FPS):.0f} fps")
    probe.release()

    print(f"  What a camera frame costs to capture - {clip.name} ({size})")
    print(f"  measuring, {DECODE_ROUNDS} passes over the whole clip for each column...")
    splits = [_decode_split(clip, None), _decode_split(clip, 1)]
    labels = [f"{splits[0].threads} threads, as the engine", "1 thread, the work alone"]

    print()
    print(f"    {'':<27} {'grab()':>9} {'+ retrieve()':>13} {'retrieve() share':>18}")
    for label, split in zip(labels, splits):
        spread = (f"({min(split.round_shares):.0%} to {max(split.round_shares):.0%})"
                  if split.round_shares else "")
        print(f"    {label:<27} {split.grab_ms:6.3f} ms {split.both_ms:10.3f} ms "
              f"{split.share:9.0%}  {spread}")
    print()
    print(f"    Processor ms per frame, every thread in the process, {splits[0].frames}")
    print("    frames a pass, not paced. The bracket is the lowest and highest pass.")
    print()
    print("    grab() IS the decode: it reads the frame and decodes it.")
    print("    retrieve() only turns the decoded frame into pixels and copies it.")
    print("    `live_capture: watched` skips retrieve() on frames nobody reads,")
    print("    so it saves the retrieve() share of those frames - never their decode.")
    return splits


def _frames(count: int, clip: Path | None) -> list[np.ndarray]:
    """Real frames from the labelled clip, or synthetic if it is not here."""
    if clip is None:
        print("  no clip found - using synthetic frames, timings are indicative")
        return [np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
                for _ in range(count)]

    cap = cv2.VideoCapture(str(clip))
    out: list[np.ndarray] = []
    while len(out) < count:
        ok, frame = cap.read()
        if not ok:
            break
        out.append(frame)
    cap.release()
    print(f"  frames from {clip.name}")
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
                        help=f"frames per camera per second turned into "
                             f"pixels by retrieve() (default {CAMERA_FPS:.0f} "
                             f"- every frame, as `live_capture: always` does). "
                             f"Pass the analytics rate for an unwatched camera "
                             f"under `watched`. Every frame is still decoded "
                             f"either way")
    parser.add_argument("--decode", action="store_true",
                        help="measure only how capture cost splits between "
                             "grab() and retrieve(); loads no model")
    parser.add_argument("--clip", metavar="PATH",
                        help="recording to time (default: the labelled "
                             "walk-through clip in engine/data/footage)")
    args = parser.parse_args(argv)

    clip = _clip(args.clip)

    # Measured before any model loads, so no GPU runtime thread is in the
    # process to have its processor time counted as capture.
    splits: list[DecodeSplit] = []
    if args.decode or args.site:
        print("\nVisionGuard benchmark - capture")
        splits = _measure_capture(clip)
        if args.decode:
            print()
            return 0

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
    frames = _frames(args.frames + WARMUP, clip)

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
        return _site(args.site, args.mix, mean, args.cores, args.decode_hz,
                     [split.share for split in splits])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
