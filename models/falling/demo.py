"""Render a presentation video: run a fall detector over a video and save an annotated copy.

    python demo.py INPUT.mp4 --out demo.mp4 --title "Person falls in a living room"
    python demo.py fall-02-cam0.mp4 --crop right_half --out urfd_fall.mp4     # depth|RGB source

The overlay (core/render.py) is driven entirely by the detector's own output: skeleton and
box colors follow each person's predicted state, and the red FALL DETECTED banner appears
only when the detector actually raises an alert. Uses the installed temporal model by
default (--detector rule_based for the baseline). Output is MPEG-4 (plays everywhere and
imports into Premiere/DaVinci); there is no H.264 encoder on this machine.
"""

import argparse
from pathlib import Path

import cv2

from core.render import auto_scale, draw_frame
from core.video import FrameSource
from detectors import create_detector

BANNER_SECONDS = 3.0
END_HOLD_SECONDS = 1.5


def render_demo(source, out, detector, estimator, title="", crop=None, scale=None, banner_s=BANNER_SECONDS,
                end_hold_s=END_HOLD_SECONDS):
    """Write the annotated video; returns {"alerts": [seconds...], "frames": n, "size": (w, h)}."""
    frames = FrameSource(source, crop=crop)
    fps = frames.fps
    estimator.reset()
    detector.reset(fps)
    writer, alerts, banner_left, last, n = None, [], 0, None, 0
    for idx, frame in frames:
        persons = estimator(frame)
        events = detector.update(idx, persons)
        for e in events:
            alerts.append(e.frame_idx / fps)
            banner_left = round(banner_s * fps)
        s = scale or auto_scale(frame.shape[0])
        img = draw_frame(frame, persons, detector, s, title, idx / fps, alerts, banner_left, fps, idx)
        banner_left = max(0, banner_left - 1)
        if writer is None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (img.shape[1], img.shape[0]))
            if not writer.isOpened():
                raise IOError(f"could not open {out} for writing")
        writer.write(img)
        last, n = img, n + 1
    if writer is None:
        raise ValueError(f"no frames in {source}")
    for _ in range(round(end_hold_s * fps)):   # hold the last frame so the outcome stays on screen
        writer.write(last)
    writer.release()
    return {"alerts": alerts, "frames": n, "size": (last.shape[1], last.shape[0])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="video file or image folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="", help="caption in the top-left corner")
    ap.add_argument("--detector", default="temporal_model", choices=["temporal_model", "rule_based"])
    ap.add_argument("--checkpoint", help="temporal model checkpoint (default: installed one)")
    ap.add_argument("--crop", help="left_half | right_half | x1,y1,x2,y2 (pixels)")
    ap.add_argument("--scale", type=int, help="integer upscale factor (default: reach 720p)")
    ap.add_argument("--pose-weights")
    ap.add_argument("--device")
    args = ap.parse_args(argv)

    crop = args.crop
    if crop and "," in crop:
        crop = [int(v) for v in crop.split(",")]
    kwargs = {"checkpoint": args.checkpoint, "device": args.device} if args.detector == "temporal_model" else {}
    detector = create_detector(args.detector, **kwargs)
    from core.pose import PoseEstimator
    estimator = PoseEstimator(args.pose_weights, device=args.device)
    res = render_demo(args.input, args.out, detector, estimator, args.title, crop, args.scale)
    alerts = ", ".join(f"{a:.1f}s" for a in res["alerts"]) or "none"
    print(f"{args.out}: {res['frames']} frames, {res['size'][0]}x{res['size'][1]}, alerts: {alerts}")
    return res


if __name__ == "__main__":
    main()
