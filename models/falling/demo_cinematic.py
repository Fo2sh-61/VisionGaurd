"""Cinematic SIMULATED attendance demo: everyone who turns to the camera gets a lock-on box and a name.

    python demo_cinematic.py footage.mp4 --out demo.mp4 --title "Morning arrivals" \
        --clock 07:57:30 --rate 25 --names "Employee 01,Employee 02" --unknown-every 4

This is an illustration, not recognition: people are found with a pose detector (a face box needs the
face turned to the camera) and names are scripted placeholders. A permanent on-screen caption says so on
every frame; do not remove it and do not pair these videos with accuracy claims. --rate speeds the demo
clock (site seconds per video second) so a short clip can span on-time and late arrivals.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

from attendance import cinematic as C
from attendance.recognise import Register
from core.video import FrameSource

HOLD_SECONDS = 2.5


def render_cinematic(source, out, estimator, title="Attendance", names=(), clock="07:57:30", cutoff="08:00",
                     rate=25.0, unknown_every=4, hours=("06:30", "16:00"), work_height=1080, end_hold_s=HOLD_SECONDS,
                     crop=None):
    frames = FrameSource(source, crop=crop)
    fps = frames.fps
    estimator.reset()
    register = Register({}, clock, cutoff, hours, rate)
    tracks = C.CineTracks(C.NameQueue(names, unknown_every))
    appear, toasts, unknown_ids = {}, [], set()
    writer, vignette, last, n = None, None, None, 0
    for idx, frame in frames:
        if frame.shape[0] != work_height:
            k = work_height / frame.shape[0]
            frame = cv2.resize(frame, (round(frame.shape[1] * k) // 2 * 2, work_height), interpolation=cv2.INTER_AREA)
        persons = estimator(frame)
        faces = []
        for p in persons:
            box = C.face_box(p.keypoints) if p.track_id is not None else None
            if box is not None:
                faces.append((p.track_id, box))
        seen = tracks.update(idx, faces)
        for t in seen:
            if t.name == "?":
                unknown_ids.add(t.id)
            elif t.name and t.name not in register.entries:
                x, y, w, h = (int(v) for v in t.box)
                pad = int(w * 0.25)
                t.thumb = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad].copy()
                register.names.setdefault(t.name, t.name)
                entry = register.mark(t.name, idx / fps, idx, 1.0, t.thumb)
                if entry is not None:
                    appear[t.name] = idx
                    toasts.append((idx, entry))
        img = frame.copy()
        for t in seen:
            if t.name:
                C.draw_track(img, t, idx, fps)
        C.draw_register(img, register, appear, idx, fps, idx / fps, rate)
        if toasts and idx - toasts[-1][0] <= 3.0 * fps:
            C.lower_third(img, toasts[-1][1], idx - toasts[-1][0], fps)
        if vignette is None:
            vignette = C.make_vignette(*img.shape[:2])
        img = C.grade(img, vignette)
        C.title_card(img, title.upper(), idx, fps)                  # fades first ...
        C.top_bar(img, title, C.fmt(register.clock_at(idx / fps)))
        C.caption(img)                                              # ... so the disclosure is never dimmed
        if writer is None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (img.shape[1], img.shape[0]))
        writer.write(img)
        last, n = img, n + 1
    if writer is None:
        raise ValueError(f"no frames in {source}")
    for k in range(round(end_hold_s * fps)):
        card = last.copy()
        C.summary_card(card, register, len(tracks.tracks), len(unknown_ids), C.ease_out(k / (0.6 * fps)))
        C.caption(card)
        writer.write(card)
    writer.release()
    return {"simulated": True, "frames": n, "size": (last.shape[1], last.shape[0]),
            "present": register.present, "unknown": len(unknown_ids),
            "arrivals": {e.name: {"clock": C.fmt(e.clock_s), "status": e.status, "minutes_late": e.minutes_late}
                         for e in register.entries.values()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Morning arrivals")
    ap.add_argument("--names", default="", help="comma-separated placeholder names given in order of appearance")
    ap.add_argument("--unknown-every", type=int, default=4, help="every Nth person after the script is a visitor (0 = never)")
    ap.add_argument("--clock", default="07:57:30")
    ap.add_argument("--cutoff", default="08:00")
    ap.add_argument("--rate", type=float, default=25.0, help="demo clock speed (site seconds per video second)")
    ap.add_argument("--hours", default="06:30-16:00")
    ap.add_argument("--crop")
    ap.add_argument("--json")
    ap.add_argument("--pose-weights")
    ap.add_argument("--device")
    args = ap.parse_args(argv)
    from core.pose import PoseEstimator
    est = PoseEstimator(args.pose_weights, conf=0.25, imgsz=1280, device=args.device)
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    start, end = args.hours.split("-")
    res = render_cinematic(args.input, args.out, est, args.title, names, args.clock, args.cutoff, args.rate,
                           args.unknown_every, (start, end), crop=args.crop)
    print(f"{args.out}: {res['frames']} frames, {res['size'][0]}x{res['size'][1]}, present {res['present']}, unknown {res['unknown']}")
    for name, a in res["arrivals"].items():
        print(f"  {name}: {a['clock']} {a['status']}" + (f" (+{a['minutes_late']} min)" if a["minutes_late"] else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
