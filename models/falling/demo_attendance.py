"""Render an attendance demo video from REAL recognition.

    python demo_attendance.py clip.mp4 --people people/ --out demo.mp4 --title "Arrives on time" \
        --clock 07:52:00 --cutoff 08:00 --blur-unknown --expect "Layla Ahmed,Omar Khaled"

``people/`` holds one subfolder per enrolled person (named after them) with a few clear photos.
Faces are found, aligned and embedded by VisionGuard's own YuNet + SFace models and matched with
its gallery rule at the strict naming bar. A name appears only when the engine really recognised
the face; everything else is "Unknown" (and blurred with --blur-unknown, to protect bystanders).

The site clock is a STAGING input: the demo starts it at --clock so arrival times can be on time or
late. The video says "Site clock (demo)" on screen. --expect checks the run against who really
walked through (everyone expected was recognised, nobody else was named) and exits non-zero if not.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

from attendance.recognise import (
    FaceTracks, Gallery, Register, enrol_from_folder, gallery_from_vg_db, load_pipeline,
)
from attendance.recognise import Match as r_Match
from attendance.render import blur_region, draw_face, draw_panel, draw_toast
from core.video import FrameSource

TOAST_SECONDS = 3.0
END_HOLD_SECONDS = 1.5
OUT_HEIGHT = 720


SIMULATION_CAPTION = "SIMULATED DEMONSTRATION - illustrative, not live system output"


def render_attendance(source, out, pipeline, gallery, register, title="", crop=None, blur_unknown=False,
                      end_hold_s=END_HOLD_SECONDS, tracks=None, small_face_px=24, simulate=None, sim_min_px=60,
                      work_height=1080, sim_min_frames=12):
    """Write the video; returns the report dict.

    simulate: list of names (``"?"`` = shown as Unknown) assigned, in order of first appearance, to the
    faces found in the footage. NO recognition runs: names are scripted, and the video carries a
    permanent on-screen caption saying so. Never use it for anything presented as measured output."""
    frames = FrameSource(source, crop=crop)
    fps = frames.fps
    tracks = tracks or FaceTracks()
    writer, toast, toast_left, last, n = None, None, 0, None, 0
    sim_names = {}
    unnamed_looks = unknown_faces = 0
    for idx, frame in frames:
        if frame.shape[0] > work_height:   # 4K sources: work at 1080p, plenty for a 720p video
            k = work_height / frame.shape[0]
            frame = cv2.resize(frame, (round(frame.shape[1] * k), work_height), interpolation=cv2.INTER_AREA)
        if simulate is None:
            obs = pipeline.observe(frame)
            results = [((o.face.x, o.face.y, o.face.w, o.face.h), gallery.match(o.embedding), o) for o in obs]
        else:   # faces are only LOCATED; who they are comes from the script
            faces = pipeline.detector.detect(frame, min_size=sim_min_px)[:8]
            results = [((f.x, f.y, f.w, f.h), r_Match(None, 0.0), None) for f in faces]
        tracked = tracks.update(idx, [(box, m) for box, m, _ in results])
        if simulate is not None:
            for track, _ in tracked:
                if track.id not in sim_names and track.hits >= sim_min_frames:   # only faces that stay in view
                    k = len(sim_names)
                    sim_names[track.id] = simulate[k] if k < len(simulate) else "?"
                pid = sim_names.get(track.id)
                track.person_id, track.score = (None if pid in (None, "?") else pid), 1.0
            tracked = [(t, b) for t, b in tracked if t.id in sim_names]       # draw only scripted faces
        s = OUT_HEIGHT / frame.shape[0]
        img = cv2.resize(frame, (round(frame.shape[1] * s), OUT_HEIGHT), interpolation=cv2.INTER_LANCZOS4)
        named_boxes = []
        for (track, box), (_, _, o) in zip(tracked, results):
            if track.person_id:
                named_boxes.append(box)
                entry = register.mark(track.person_id, idx / fps, idx, track.score,
                                      frame[max(0, box[1]):box[1] + box[3], max(0, box[0]):box[0] + box[2]].copy())
                if entry is not None:
                    toast, toast_left = entry, round(TOAST_SECONDS * fps)
            else:
                unknown_faces += 1
        if blur_unknown:   # every face we did not name, including ones too small to identify
            named = [(b[0] * s, b[1] * s, b[2] * s, b[3] * s) for b in named_boxes]
            for f in pipeline.detector.detect(frame, min_size=small_face_px):
                fb = (f.x * s, f.y * s, f.w * s, f.h * s)
                cx, cy = fb[0] + fb[2] / 2, fb[1] + fb[3] / 2
                if not any(b[0] <= cx <= b[0] + b[2] and b[1] <= cy <= b[1] + b[3] for b in named):
                    blur_region(img, int(fb[0]), int(fb[1]), int(fb[2]), int(fb[3]))
        for (track, box) in tracked:
            draw_face(img, box, gallery.names.get(track.person_id) if track.person_id else None, s)
        if toast is not None and toast_left > 0:
            draw_toast(img, toast, s)
            toast_left -= 1
        if title:
            from core.render import WHITE, text_chip
            text_chip(img, title, (12, 12), WHITE, scale=0.62)
        if simulate is not None:
            from attendance.render import AMBER as _A
            from core.render import text_chip as _t
            _t(img, SIMULATION_CAPTION, (12, img.shape[0] - 44), _A, scale=0.55)
        panel = draw_panel(img.shape[0], register, idx / fps)
        canvas = cv2.hconcat([img, panel])
        if writer is None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (canvas.shape[1], canvas.shape[0]))
        writer.write(canvas)
        last, n = canvas, n + 1
    if writer is None:
        raise ValueError(f"no frames in {source}")
    for _ in range(round(end_hold_s * fps)):
        writer.write(last)
    writer.release()
    return {
        "frames": n, "size": (last.shape[1], last.shape[0]), "unknown_face_looks": unknown_faces,
        "simulated": simulate is not None,
        "arrivals": {e.name: {"clock": e.clock_s, "status": e.status, "minutes_late": e.minutes_late,
                              "video_seconds": round(e.frame_idx / fps, 2), "score": round(e.score, 3)}
                     for e in register.entries.values()},
    }


def check_expected(report, expected_names, enrolled_names):
    """Problems (empty list = pass): someone expected was not recognised, or someone not expected was."""
    got, want = set(report["arrivals"]), set(expected_names)
    problems = [f"{n} was expected but not recognised" for n in sorted(want - got)]
    problems += [f"{n} was named but not expected" for n in sorted(got - want)]
    problems += [f"{n} is not enrolled" for n in sorted(want - set(enrolled_names))]
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--people", help="folder: one subfolder of photos per enrolled person")
    src.add_argument("--vg-db", help="a VisionGuard database to read enrolled people from (read-only)")
    src.add_argument("--nobody", action="store_true", help="enrol no one (shows an unenrolled visitor)")
    ap.add_argument("--simulate", help="SIMULATION: comma-separated names given to faces in order of appearance "
                    "('?' = Unknown). No recognition runs; a permanent caption says so. Not for real-output claims.")
    ap.add_argument("--title", default="")
    ap.add_argument("--clock", default="07:50:00", help="site clock at video start (HH:MM[:SS])")
    ap.add_argument("--cutoff", default="08:00", help="late cutoff")
    ap.add_argument("--hours", default="06:30-16:00", help="arrivals only count inside these hours")
    ap.add_argument("--crop")
    ap.add_argument("--blur-unknown", action="store_true")
    ap.add_argument("--expect", help="comma-separated names who really walked through (QA check)")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args(argv)

    pipeline = load_pipeline()
    gallery = Gallery()
    simulate = [n.strip() for n in args.simulate.split(",")] if args.simulate else None
    if simulate is not None:
        for n in simulate:
            if n != "?":
                gallery.names[n] = n          # the roster the panel lists; nobody is really enrolled
    elif args.people:
        for name, r in enrol_from_folder(args.people, pipeline, gallery).items():
            print(f"enrolled {name}: {r['used']} photos" + (f", skipped {r['skipped']}" if r["skipped"] else ""))
    elif args.vg_db:
        gallery = gallery_from_vg_db(args.vg_db)
    start, end = args.hours.split("-")
    register = Register(gallery.names, args.clock, args.cutoff, (start, end))
    crop = [int(v) for v in args.crop.split(",")] if args.crop and "," in args.crop else args.crop
    report = render_attendance(args.input, args.out, pipeline, gallery, register, args.title, crop, args.blur_unknown,
                               simulate=simulate)
    print(f"{args.out}: {report['frames']} frames, {report['size'][0]}x{report['size'][1]}")
    for name, a in report["arrivals"].items():
        print(f"  {name}: marked present at video {a['video_seconds']}s -> {a['status']}"
              + (f" (+{a['minutes_late']} min)" if a["minutes_late"] else ""))
    if not report["arrivals"]:
        print("  nobody was marked present")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
    if args.expect is not None:
        problems = check_expected(report, [n.strip() for n in args.expect.split(",") if n.strip()], gallery.names.values())
        print("QA:", "PASS" if not problems else "FAIL - " + "; ".join(problems))
        return 0 if not problems else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
