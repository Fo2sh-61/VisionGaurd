"""Record footage from a camera, with live labelling.

There is no test footage for this project. Every model claim — "the weapons
detector works", "intrusion has no false alarms overnight" — is unverifiable
until there are clips to check it against. This tool exists to fix that, and it
should be the first thing run each time a camera is available.

It does two jobs at once:

  1. writes an .mp4 to engine/data/footage/
  2. writes a .json sidecar with the metadata AND any marks you set while
     recording

The marks are the point. Pressing SPACE the moment someone crosses into the zone
costs nothing during the take and turns a raw clip into a labelled example. A
folder of unlabelled video is only slightly more useful than no video.

Usage
-----
    # from the configured camera, 30 seconds
    python engine/tools/record.py --camera cam-laptop --seconds 30 --label walk-in

    # any source, no config needed
    python engine/tools/record.py --source webcam:0 --label baseline-empty

    # overlay the zones so you can see what you are actually testing
    python engine/tools/record.py --camera cam-laptop --show-zones

Keys (in the preview window)
    SPACE   mark this moment  (e.g. "person entered the zone")
    N       mark as a negative  (e.g. "this is a kitchen knife, not a threat")
    Q / ESC stop recording

What to record first
--------------------
    baseline-empty     several minutes of nothing happening. The false-alarm
                       set. This is the most valuable and most skipped clip.
    walk-through       someone crossing the zone briefly, then leaving
    loiter             someone entering and staying
    two-people         occlusion, the case trackers get wrong
    edge-of-frame      someone half in shot at the boundary
    backlit            same walk against a window — CCTV's hardest condition
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.ingest.source import CameraSource  # noqa: E402

# BGR
GREEN = (120, 220, 120)
RED = (80, 80, 240)
AMBER = (60, 180, 250)
WHITE = (245, 245, 245)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Record labelled footage for the evaluation set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Keys")[1] if "Keys" in __doc__ else None,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument("--camera", help="camera id from engine.yaml")
    src.add_argument("--source", help="raw source, e.g. webcam:0 or rtsp://…")

    p.add_argument("--label", default="clip", help="name for the clip (default: clip)")
    p.add_argument("--seconds", type=float, help="stop after N seconds")
    p.add_argument("--fps", type=float, default=15.0, help="record fps (default: 15)")
    p.add_argument("--out", type=Path, help="output directory")
    p.add_argument("--show-zones", action="store_true", help="overlay configured zones")
    p.add_argument("--no-preview", action="store_true", help="headless recording")
    p.add_argument("--list", action="store_true", help="list configured cameras and exit")
    return p.parse_args(argv)


def list_cameras(cfg) -> int:
    print(f"\ncameras in {ENGINE_DIR / 'engine.yaml'}:\n")
    for cam in cfg.cameras:
        state = "enabled" if cam.enabled else "disabled"
        zones = cfg.zones_for(cam.id)
        print(f"  {cam.id:<16} {cam.name:<22} {cam.redacted_source()}")
        print(f"  {'':<16} {state}, {cam.fps} fps, {len(zones)} zone(s)")
    print()
    return 0


def draw_zones(image, zones) -> None:
    """Overlay normalised zone polygons. What you see is what the engine sees."""
    import numpy as np

    h, w = image.shape[:2]
    for zone in zones:
        pts = np.array(
            [(int(x * w), int(y * h)) for x, y in zone.polygon], dtype=np.int32
        )
        colour = AMBER if zone.enabled else (140, 140, 140)
        overlay = image.copy()
        cv2.fillPoly(overlay, [pts], colour)
        cv2.addWeighted(overlay, 0.18, image, 0.82, 0, image)
        cv2.polylines(image, [pts], True, colour, 2)
        cv2.putText(
            image, zone.name, tuple(pts[0] + (4, -8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA,
        )


def draw_hud(image, *, elapsed: float, marks: int, stale: bool, limit: float | None):
    h, w = image.shape[:2]
    cv2.rectangle(image, (0, 0), (w, 34), (24, 24, 28), -1)

    cv2.circle(image, (18, 17), 7, RED if not stale else (110, 110, 110), -1)
    clock = f"{int(elapsed // 60):02d}:{elapsed % 60:04.1f}"
    if limit:
        clock += f" / {int(limit // 60):02d}:{limit % 60:04.1f}"
    cv2.putText(image, clock, (34, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)

    if marks:
        cv2.putText(image, f"{marks} mark(s)", (w - 190, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREEN, 1, cv2.LINE_AA)

    if stale:
        cv2.putText(image, "NO SIGNAL", (w // 2 - 70, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, RED, 2, cv2.LINE_AA)

    cv2.putText(image, "SPACE mark   N negative   Q stop", (34, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 175), 1, cv2.LINE_AA)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        cfg = vgconfig.load()
    except vgconfig.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.list:
        return list_cameras(cfg)

    # -- resolve the source -------------------------------------------------
    zones: tuple = ()
    if args.camera:
        cam_cfg = cfg.camera(args.camera)
        if cam_cfg is None:
            known = ", ".join(c.id for c in cfg.cameras) or "none"
            print(f"unknown camera {args.camera!r}. Known: {known}", file=sys.stderr)
            return 2
        source, camera_id, rotate = cam_cfg.source, cam_cfg.id, cam_cfg.rotate
        zones = cfg.zones_for(cam_cfg.id)
    elif args.source:
        source, camera_id, rotate = args.source, "adhoc", 0
    else:
        # Default to the first enabled camera — the common case is "just record".
        cam_cfg = next((c for c in cfg.cameras if c.enabled), None)
        if cam_cfg is None:
            print("no enabled camera in engine.yaml; pass --source", file=sys.stderr)
            return 2
        source, camera_id, rotate = cam_cfg.source, cam_cfg.id, cam_cfg.rotate
        zones = cfg.zones_for(cam_cfg.id)
        print(f"using {cam_cfg.id} ({cam_cfg.name})")

    out_dir = args.out or cfg.storage.footage_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in args.label)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"{safe_label}_{camera_id}_{stamp}"
    video_path = out_dir / f"{stem}.mp4"
    meta_path = out_dir / f"{stem}.json"

    preview = not args.no_preview
    marks: list[dict] = []
    writer: cv2.VideoWriter | None = None
    started = datetime.now(timezone.utc)
    frames_written = 0
    stale_frames = 0

    print(f"\nrecording -> {video_path}")
    if args.seconds:
        print(f"stopping after {args.seconds}s")
    print("SPACE mark   N negative   Q stop\n")

    cam = CameraSource(camera_id, source, target_fps=args.fps, rotate=rotate)
    if not cam.open():
        print(f"could not open {cam.redacted}: {cam.health.last_error}", file=sys.stderr)
        return 1

    t0 = time.monotonic()
    try:
        for frame in cam.frames():
            elapsed = time.monotonic() - t0

            if writer is None:
                writer = cv2.VideoWriter(
                    str(video_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    args.fps,
                    (frame.width, frame.height),
                )
                if not writer.isOpened():
                    print("could not open the video writer", file=sys.stderr)
                    return 1

            # Write the clean frame. Overlays are for the operator's eyes only —
            # burning a HUD into the eval footage would poison the training set.
            writer.write(frame.image)
            frames_written += 1
            if frame.is_stale:
                stale_frames += 1

            if preview:
                display = frame.image.copy()
                if args.show_zones and zones:
                    draw_zones(display, zones)
                draw_hud(
                    display,
                    elapsed=elapsed,
                    marks=len(marks),
                    stale=frame.is_stale,
                    limit=args.seconds,
                )
                cv2.imshow(f"recording — {camera_id}", display)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    print("\nstopped")
                    break
                if key == ord(" "):
                    marks.append(_mark(elapsed, frames_written, "event"))
                    print(f"  mark #{len(marks)} at {elapsed:6.2f}s")
                elif key == ord("n"):
                    marks.append(_mark(elapsed, frames_written, "negative"))
                    print(f"  negative #{len(marks)} at {elapsed:6.2f}s")

            if args.seconds and elapsed >= args.seconds:
                print("\nreached the time limit")
                break
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        cam.close()
        if writer is not None:
            writer.release()
        if preview:
            cv2.destroyAllWindows()

    if frames_written == 0:
        video_path.unlink(missing_ok=True)
        print("no frames captured; nothing written", file=sys.stderr)
        return 1

    duration = time.monotonic() - t0
    meta = {
        "clip": video_path.name,
        "label": args.label,
        "camera_id": camera_id,
        "source": cam.redacted,
        "started_utc": started.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 2),
        "fps": args.fps,
        "frames": frames_written,
        "stale_frames": stale_frames,
        "resolution": [frame.width, frame.height],
        "zones": [
            {"id": z.id, "name": z.name, "polygon": [list(p) for p in z.polygon]}
            for z in zones
        ],
        "marks": marks,
        "notes": "",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    size_mb = video_path.stat().st_size / 1e6
    print(f"\nwrote {video_path.name}  ({duration:.1f}s, {frames_written} frames, {size_mb:.1f} MB)")
    print(f"      {meta_path.name}  ({len(marks)} mark(s))")
    if stale_frames:
        pct = 100 * stale_frames / frames_written
        print(f"      warning: {stale_frames} stale frames ({pct:.0f}%) - the stream dropped")
    if not marks:
        print("      no marks set. Fine for a baseline clip; for an event clip,")
        print("      press SPACE next time as the thing happens - it is the label.")
    return 0


def _mark(elapsed: float, frame_no: int, kind: str) -> dict:
    return {
        "kind": kind,
        "at_seconds": round(elapsed, 2),
        "frame": frame_no,
        "note": "",
    }


if __name__ == "__main__":
    raise SystemExit(main())
