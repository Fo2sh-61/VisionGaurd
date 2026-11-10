"""How fast the models run on this machine, and what that means for 208 cameras.

Run:  python engine/tools/benchmark.py
      python engine/tools/benchmark.py --site 100     # size a whole site
      python engine/tools/benchmark.py --decode       # what capture costs
      python engine/tools/benchmark.py --decode --hw  # ... on a graphics chip
      python engine/tools/benchmark.py --streams      # how many cameras a chip carries

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

`--hw` adds the graphics chips to that comparison, and `--streams` asks how
many cameras at once each one carries. Neither changes how the engine
captures: they measure what a change would be worth, on this machine, so the
decision rests on figures rather than on a hope. See `_measure_hardware`.
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
import tempfile
import threading
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
    # Processor time for one pass of YuNet plus SFace with a face in view,
    # one OpenCV thread: 63 ms on the labelled clip (i7-9750H, 4 Nov 2026).
    # With nobody in view it is cheaper - 18 ms on the real NVR sub-stream -
    # so this is the busy-entrance figure. It was 44 ms, a wall-clock time
    # that hid how much processor the default thread pool burned.
    "faces": 63.0,
    # The patrol tier is the SAME pipeline - YuNet plus SFace - just run
    # slower and on the other cameras. Same cost per frame; the saving was
    # always in the rate and the camera count, never in the model.
    "patrol": 63.0,
    # One plate pass with no car, the .pt at FP32: 18.4-19.5 ms on frames
    # from the real NVR, 18.9 ms on the clip (RTX 2080 Max-Q, 4-5 Nov 2026).
    # A car adds the character pass, 18.2 ms, for as long as it is there.
    "plates": 19.0,
    # One camera frame taken all the way to pixels: `grab()` plus
    # `retrieve()`, on a real site camera: a Hikvision NVR's sub-stream,
    # H.265 640x360, timed with `--clip` on 5 Nov 2026 - 1.18 ms with the
    # engine's 12 decoder threads. The main stream (2560x1440) costs 27 ms,
    # which is why cameras are added on their sub-stream. It was 6 ms, a
    # figure nothing in the repository could trace.
    "decode": 1.2,
}

#: Frames per second a camera actually delivers, for the capture rows. The
#: real NVR measured on 5 Nov 2026 sends 20 on both of its streams.
CAMERA_FPS = 20.0

#: Passes over the clip for each column of the decode split. The two columns
#: are timed alternately, so a laptop that warms up or throttles part-way
#: through shifts both of them rather than one.
DECODE_ROUNDS = 3

#: Streams tried at once in the `--streams` ramp, in order. It stops early at
#: the first count where a stream can no longer keep up with a camera.
STREAM_RAMP = (1, 2, 4, 8, 16, 24, 32)

#: How long each count in the ramp runs for. Long enough to average over a
#: laptop's clock ticks, short enough that the whole ramp is a few minutes.
STREAM_SECONDS = 6.0


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
    """Processor ms per frame for `grab()` alone and `grab()` + `retrieve()`.

    The last four fields say WHO decoded. A run on a graphics chip carries
    the chip's name, the adapter number OpenCV was given, whether the chip
    actually took the work - `accelerated` - and how fast one stream ran by
    the wall clock. `accelerated` is the one that matters: asking for a
    graphics chip and being handed the processor looks like success from
    every other angle.
    """

    threads: int
    frames: int
    grab_ms: float
    both_ms: float
    round_shares: list[float]
    label: str = "processor"
    device: int | None = None
    accelerated: bool = False
    grab_fps: float = 0.0
    both_fps: float = 0.0

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


def _hw_params(device: int) -> list[int]:
    """VideoCapture parameters that hand the decode to graphics chip `device`.

    Naming a chip means naming the interface too: OpenCV refuses
    `CAP_PROP_HW_DEVICE` alongside `VIDEO_ACCELERATION_ANY` ("Invalid usage
    of CAP_PROP_HW_DEVICE with 'ANY'"). D3D11VA is the interface Windows
    offers, and it is the one a Windows deployment would use - on an NVIDIA
    card it runs on the same NVDEC hardware CUDA would reach.

    Used by the measurement only. Nothing in `vg/` asks for a graphics chip;
    that is the decision this measurement exists to inform.
    """
    api = (cv2.VIDEO_ACCELERATION_D3D11 if sys.platform == "win32"
           else cv2.VIDEO_ACCELERATION_VAAPI)
    return [cv2.CAP_PROP_HW_ACCELERATION, api, cv2.CAP_PROP_HW_DEVICE, device]


def _capture_params(device: int | None) -> list[int]:
    """How to open a capture: nothing at all for the processor, else the chip.

    The processor row has to be opened with NOTHING. Asking for
    `VIDEO_ACCELERATION_ANY` and printing the answer as the processor is how
    this tool, on its first run, reported the Intel chip's throughput twice -
    once under the chip's name and once as the processor - and the two
    agreeing to within 1% read like corroboration.
    """
    return [] if device is None else _hw_params(device)


@dataclass
class Pass:
    """One run over the clip, and what it cost."""

    threads: int
    accelerated: bool
    frames: int
    processor_s: float
    wall_s: float


def _decode_pass(clip: Path, retrieve: bool, threads: int | None,
                 device: int | None = None) -> Pass:
    """One pass over the whole clip.

    Processor time for the whole process, not wall time: FFmpeg decodes on
    threads of its own, and a wall clock would show the work being shared
    out rather than the work. It is the unit `--site` adds up. Wall time is
    kept too, because a graphics chip's work is not the processor's and the
    only way to see it is how fast frames come out.

    Not paced. A real camera hands over a frame every 40 ms; this takes them
    as fast as they come. Pacing was tried and is not reliable here: Windows
    charges processor time, at each clock tick, to whichever thread happens
    to be running, so a loop that sleeps between frames is mis-counted. Paced
    runs on this laptop put retrieve() anywhere from 35% to 90% of a frame.

    Opening is outside the clock, and has to be: opening a capture on a
    graphics chip costs 200-300 ms of processor time and about 0.7 s of
    waiting - a third of what a hardware frame appeared to cost, when it was
    counted in. A camera opens once and then runs for weeks.
    """
    params = [] if threads is None else [cv2.CAP_PROP_N_THREADS, threads]
    params += _capture_params(device)
    cap = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG, params)
    if not cap.isOpened():
        raise SystemExit(f"FFmpeg could not open {clip}")
    used = int(cap.get(cv2.CAP_PROP_N_THREADS))
    accelerated = cap.get(cv2.CAP_PROP_HW_ACCELERATION) != cv2.VIDEO_ACCELERATION_NONE
    frames = 0
    started, started_wall = time.process_time(), time.monotonic()
    while cap.grab():
        if retrieve:
            cap.retrieve()
        frames += 1
    spent = time.process_time() - started
    wall = time.monotonic() - started_wall
    cap.release()
    return Pass(used, accelerated, frames, spent, wall)


def _decode_split(clip: Path, threads: int | None = None,
                  rounds: int = DECODE_ROUNDS, device: int | None = None,
                  label: str = "processor") -> DecodeSplit:
    """Time `grab()` alone against `grab()` + `retrieve()` over the clip.

    `threads=None` is FFmpeg's own choice, which is how the engine opens a
    camera. `threads=1` is the work alone, without the cost of sharing it
    out - and the two give very different answers, which is why both are
    reported rather than one.

    `device` hands the decode to that graphics chip. Whether the chip took it
    is read back, not assumed: OpenCV falls back to the processor without
    complaining when a chip will not decode the file's format.
    """
    _decode_pass(clip, False, threads, device)  # warm-up: disk cache, codec start
    used = frames = 0
    accelerated = False
    grab_s = both_s = grab_wall = both_wall = 0.0
    shares: list[float] = []
    for _ in range(rounds):
        grab = _decode_pass(clip, False, threads, device)
        both = _decode_pass(clip, True, threads, device)
        used, accelerated = grab.threads, grab.accelerated
        frames += grab.frames
        grab_s += grab.processor_s
        both_s += both.processor_s
        grab_wall += grab.wall_s
        both_wall += both.wall_s
        if grab.frames and both.frames and both.processor_s > 0:
            per_grab = grab.processor_s / grab.frames
            per_both = both.processor_s / both.frames
            shares.append((per_both - per_grab) / per_both)
    per_pass = frames // rounds if rounds else 0
    return DecodeSplit(
        threads=used,
        frames=per_pass,
        grab_ms=grab_s * 1000 / frames if frames else 0.0,
        both_ms=both_s * 1000 / frames if frames else 0.0,
        round_shares=shares,
        label=label,
        device=device,
        accelerated=accelerated,
        grab_fps=frames / grab_wall if grab_wall else 0.0,
        both_fps=frames / both_wall if both_wall else 0.0,
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


# ---------------------------------------------------------------------------
# Hardware decode - what a graphics chip would take off the processor
# ---------------------------------------------------------------------------
#
# Measurements §1b leaves decoding as the biggest cost a 100-camera site pays:
# 6 to 13.5 of its 14-20 cores, on every frame of every camera, and
# `live_capture: watched` cannot touch a single one of them because `grab()`
# IS the decode. A graphics chip can - it has silicon that does nothing else.
# Whether that is worth building was measured by hand on 11 Sep and no command
# repeated it. This is the command.
#
# It measures and changes nothing. `CameraSource.open()` still asks for no
# acceleration, and will until the owner decides otherwise.
#
# Two ways this could quietly report a fiction, and what stops each:
#
# - **A chip that refuses the file.** The labelled clip is MPEG-4 Part 2, a
#   format no chip here decodes. OpenCV opens it anyway, decodes on the
#   processor, and says nothing about it. So every row reads
#   `CAP_PROP_HW_ACCELERATION` back after opening, and the comparison runs on
#   an H.264 copy, H.264 being what cameras actually send.
# - **Timing the wrong clock.** A chip's work is not the processor's, so
#   processor time alone would make any chip look infinitely fast. Frames a
#   second, by the wall clock, is printed beside it.


def _adapter_names() -> dict[int, str]:
    """Graphics chips, by the number `CAP_PROP_HW_DEVICE` counts in.

    OpenCV takes an adapter NUMBER and reports nothing about what that number
    is, so a measurement would read "device 1" - which tells somebody choosing
    hardware nothing at all. Windows lists adapters in DXGI order, the order
    D3D11VA counts in, so this asks Windows for their names.

    Best effort, and a nicety rather than the measurement: an empty answer
    means the names could not be read, and the caller falls back to numbers.
    """
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import POINTER, byref, c_uint, c_void_p

        class _Desc(ctypes.Structure):
            _fields_ = [
                ("Description", ctypes.c_wchar * 128),
                ("VendorId", c_uint), ("DeviceId", c_uint),
                ("SubSysId", c_uint), ("Revision", c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", ctypes.c_longlong),
                ("Flags", c_uint),
            ]

        #: DXGI_ADAPTER_FLAG_SOFTWARE. Windows always lists a software
        #: renderer after the real chips; it decodes nothing and asking it to
        #: prints a driver error. Left out, so the list is chips.
        software = 0x2

        class _Guid(ctypes.Structure):
            _fields_ = [("d1", c_uint), ("d2", ctypes.c_ushort),
                        ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

        # IID_IDXGIFactory1, and the slots its methods sit at: Release is 2 on
        # every COM object, EnumAdapters1 is 12 on the factory, GetDesc1 is 10
        # on an adapter.
        iid = _Guid(0x770AAE78, 0xF26F, 0x4DBA,
                    (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C,
                                         0x83, 0xD1, 0xB3, 0x87))
        factory = c_void_p()
        if ctypes.WinDLL("dxgi").CreateDXGIFactory1(byref(iid), byref(factory)):
            return {}

        def method(obj, slot, restype, argtypes):
            table = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
            call = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(table[slot])
            return lambda *args: call(obj, *args)

        names: dict[int, str] = {}
        enumerate_adapters = method(factory, 12, ctypes.c_long,
                                    [c_uint, POINTER(c_void_p)])
        index = 0
        while True:
            adapter = c_void_p()
            if enumerate_adapters(index, byref(adapter)):
                break
            desc = _Desc()
            method(adapter, 10, ctypes.c_long, [POINTER(_Desc)])(byref(desc))
            method(adapter, 2, ctypes.c_ulong, [])()
            if not desc.Flags & software:
                names[index] = desc.Description.strip()
            index += 1
        method(factory, 2, ctypes.c_ulong, [])()
        return names
    except Exception:  # noqa: BLE001 - a name is not worth failing a measurement
        return {}


def _describe(clip: Path) -> str:
    """`H264, 640x480, 15 fps, 4.5 Mbit/s` - what is being decoded."""
    cap = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    cap.release()
    codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip()
    seconds = count / fps if fps else 0.0
    rate = clip.stat().st_size * 8 / seconds / 1e6 if seconds else 0.0
    return f"{codec}, {width}x{height}, {fps:.0f} fps, {rate:.1f} Mbit/s"


def _h264_copy(clip: Path, into: Path) -> Path | None:
    """An H.264 copy of the clip - the format cameras actually send.

    Same pictures, same size, same rate; only the compression differs. The
    labelled clip is MPEG-4 Part 2, which no graphics chip here decodes, so
    timing hardware against software on it would be timing the processor
    against itself.

    Windows' own encoder writes it (`CAP_MSMF`, `avc1`) - this OpenCV wheel
    has no H.264 encoder of its own. It picks its own bitrate, about a bit a
    pixel, which is roughly 4.5 Mbit/s for this 640x480 15 fps clip and inside
    a real camera's range. It cannot be told a different one, so a copy of a
    1080p recording comes out far above what a camera sends and its decode
    would read dear. `_describe` prints the rate so a reader can see that.

    None if the copy could not be written or does not open again - never a
    silent substitute. A hardware figure taken on a file the chip refused
    would be worse than no figure.
    """
    source = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG)
    if not source.isOpened():
        return None
    fps = source.get(cv2.CAP_PROP_FPS) or CAMERA_FPS
    size = (int(source.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(source.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    writer = cv2.VideoWriter(str(into), cv2.CAP_MSMF,
                             cv2.VideoWriter_fourcc(*"avc1"), fps, size)
    if not writer.isOpened():
        source.release()
        writer.release()
        return None
    while True:
        ok, frame = source.read()
        if not ok:
            break
        writer.write(frame)
    source.release()
    writer.release()

    if not into.is_file():
        return None
    probe = cv2.VideoCapture(str(into), cv2.CAP_FFMPEG)
    ok = probe.isOpened() and probe.grab()
    probe.release()
    return into if ok else None


def _decoders(clip: Path, only: int | None = None) -> list[tuple[str, int | None]]:
    """The processor, then every graphics chip that really decodes this clip.

    A chip is included only if the file opens AND the chip reports that it
    took the decode. One that refuses is named and left out, because "this
    machine has an Intel chip" and "the Intel chip decodes this camera's
    stream" are different facts, and only the second one sizes a site.
    """
    found: list[tuple[str, int | None]] = [("processor, no chip asked", None)]
    names = _adapter_names()
    indices = [only] if only is not None else sorted(names) or list(range(4))
    for index in indices:
        name = names.get(index, f"graphics chip {index}")
        cap = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG, _capture_params(index))
        opened = cap.isOpened()
        took = opened and (cap.get(cv2.CAP_PROP_HW_ACCELERATION)
                           != cv2.VIDEO_ACCELERATION_NONE)
        cap.release()
        if took:
            found.append((name, index))
        else:
            why = ("decoded on the processor instead" if opened
                   else "would not open this recording")
            print(f"    {name}: {why} - not measured")
    return found


def _print_hardware(splits: list[DecodeSplit]) -> None:
    print()
    print(f"    {'decoder':<42} {'grab()':>9} {'+ retrieve()':>13} "
          f"{'retrieve() share':>17} {'one stream':>11}")
    for split in splits:
        # A chip that was asked and did not take it. It should not reach here
        # - `_decoders` checks first - but a row that silently ran on the
        # processor under a chip's name is the one lie this must never tell.
        refused = split.device is not None and not split.accelerated
        label = split.label + (" - REFUSED, this is the processor" if refused else "")
        print(f"    {label:<42} {split.grab_ms:6.3f} ms {split.both_ms:10.3f} ms "
              f"{split.share:16.0%} {split.grab_fps:8.0f} fps")
    print()
    print("    Processor ms per frame, every thread in the process, not paced.")
    print("    `one stream` is the wall clock: how fast a single stream grabs")
    print("    when nothing paces it. A camera sends 25 a second.")
    print()
    print("    On a graphics chip, grab() stops being the expensive half and")
    print("    retrieve() becomes it: the picture has to be copied back off the")
    print("    chip and converted. retrieve() is exactly what `live_capture:")
    print("    watched` skips on a camera nobody is looking at.")


def _stream_level(clip: Path, device: int | None, streams: int,
                  seconds: float = STREAM_SECONDS) -> tuple[float, float] | None:
    """Decode `streams` copies at once: (frames a second, cores kept busy).

    Each stream gets its own capture, opened before the clock starts so that
    opening is not counted as decoding, and loops the clip when it runs out.
    `grab()` only - this is the decoder's own capacity, and retrieve() is the
    part a camera nobody watches does not pay.

    None if that many streams would not open at once. That is an answer in
    itself, and not the same answer as "too slow".
    """
    caps = []
    for _ in range(streams):
        cap = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG, _capture_params(device))
        if not cap.isOpened():
            for opened in [*caps, cap]:
                opened.release()
            return None
        caps.append(cap)

    counts = [0] * streams
    stop = threading.Event()

    def work(slot: int, cap) -> None:
        while not stop.is_set():
            if cap.grab():
                counts[slot] += 1
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # ran out; round again
            if not cap.grab():
                return
            counts[slot] += 1

    workers = [threading.Thread(target=work, args=(slot, cap), daemon=True)
               for slot, cap in enumerate(caps)]
    started, started_wall = time.process_time(), time.monotonic()
    for worker in workers:
        worker.start()
    time.sleep(seconds)
    stop.set()
    for worker in workers:
        worker.join(timeout=30)
    wall = time.monotonic() - started_wall
    cores = (time.process_time() - started) / wall if wall else 0.0
    for cap in caps:
        cap.release()
    return (sum(counts) / wall if wall else 0.0), cores


def _measure_streams(clip: Path, decoders: list[tuple[str, int | None]],
                     most: int) -> None:
    """How many streams at once each decoder carries, by trying it.

    Ramps until a stream can no longer keep up with a camera's 25 frames a
    second, or until the ramp runs out - and says which of the two happened,
    because "it never struggled" is a different answer from "this is where it
    stopped coping" and they look identical in a table of numbers.

    The answer is in cameras OF THIS CLIP'S PICTURE SIZE. Turning it into
    cameras needs a recording from a real camera; `--clip` takes one.
    """
    print()
    print("  How many streams at once - more and more of them, until one falls")
    print(f"  below the {CAMERA_FPS:.0f} frames a second a camera sends. "
          f"{STREAM_SECONDS:.0f} seconds at each count, grabbing only.")
    for label, device in decoders:
        print()
        print(f"    {label}")
        print(f"      {'streams':>7} {'frames/s':>9} {'per stream':>11} "
              f"{'cores busy':>11}")
        peak = 0.0
        struggled = False
        counts = [n for n in STREAM_RAMP if n <= most]
        for count in counts:
            level = _stream_level(clip, device, count)
            if level is None:
                print(f"      {count:>7}   would not open {count} at once")
                break
            frames_per_second, cores = level
            each = frames_per_second / count
            print(f"      {count:>7} {frames_per_second:>9.0f} {each:>11.0f} "
                  f"{cores:>11.2f}")
            peak = max(peak, frames_per_second)
            struggled = each < CAMERA_FPS
            if struggled:
                break
        ending = ("a stream fell behind a camera here"
                  if struggled else
                  f"still keeping up at {counts[-1]} - the ramp ran out, "
                  f"not the decoder")
        print(f"      {peak:.0f} frames a second at its best = about "
              f"{peak / CAMERA_FPS:.0f} streams")
        print(f"      of THIS clip at {CAMERA_FPS:.0f} fps; {ending}")
    print()
    print("    Not cameras. This clip is 640x480 and a camera is usually 1080p,")
    print("    six times the pixels - but a decoder's cost per frame is not all")
    print("    pixels, so dividing by six is a guess in one direction and the")
    print("    per-frame overhead is a guess in the other. For a real number,")
    print("    record a few minutes off a site camera and pass it to --clip.")
    print()
    print("    `cores busy` is the processor the decoding still costs. On a")
    print("    graphics chip that is the driver and the copying, not the decode.")


def _measure_hardware(clip: Path | None, only: int | None = None,
                      streams: int | None = None) -> list[DecodeSplit]:
    """Time every decoder on this machine against the processor."""
    print()
    if clip is None:
        print("  Hardware decode NOT measured - no clip. Pass --clip, or put the")
        print("  labelled recording in engine/data/footage/.")
        return []

    print("  What a graphics chip would take off the processor")
    print()
    with tempfile.TemporaryDirectory(prefix="vg-decode-") as scratch:
        copy = _h264_copy(clip, Path(scratch) / "camera-like.mp4")
        if copy is None:
            print("  NOT measured: no H.264 copy could be written on this")
            print("  machine, and the labelled clip's own format is one no")
            print("  graphics chip decodes. Pass --clip with an H.264")
            print("  recording - anything a camera wrote - to measure directly.")
            return []

        print(f"    from   {clip.name} ({_describe(clip)})")
        print(f"    timing an H.264 copy ({_describe(copy)}), because that is")
        print("    the format cameras send and the one chips decode")
        print()
        decoders = _decoders(copy, only)
        splits = [_decode_split(copy, None, DECODE_ROUNDS, device, label)
                  for label, device in decoders]
        _print_hardware(splits)
        if streams:
            _measure_streams(copy, decoders, streams)
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
    parser.add_argument("--hw", action="store_true",
                        help="also time every graphics chip on this machine "
                             "against the processor, on an H.264 copy of the "
                             "clip. Measures only - the engine still decodes "
                             "on the processor")
    parser.add_argument("--hw-device", type=int, metavar="N", default=None,
                        help="time only graphics chip N (the numbers are the "
                             "ones printed by --hw)")
    parser.add_argument("--streams", type=int, nargs="?", metavar="MOST",
                        const=max(STREAM_RAMP),
                        help=f"also measure how many streams at once each "
                             f"decoder carries, up to MOST (default "
                             f"{max(STREAM_RAMP)}). Implies --hw, and keeps "
                             f"the graphics chips busy for a few minutes")
    parser.add_argument("--clip", metavar="PATH",
                        help="recording to time (default: the labelled "
                             "walk-through clip in engine/data/footage)")
    args = parser.parse_args(argv)

    clip = _clip(args.clip)

    # Asking about the graphics chips is asking about capture, so it turns the
    # capture measurement on rather than being ignored without one.
    hardware = args.hw or args.streams is not None
    if hardware:
        args.decode = True

    # Measured before any model loads, so no GPU runtime thread is in the
    # process to have its processor time counted as capture.
    splits: list[DecodeSplit] = []
    if args.decode or args.site:
        print("\nVisionGuard benchmark - capture")
        splits = _measure_capture(clip)
        if hardware:
            _measure_hardware(clip, args.hw_device, args.streams)
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
