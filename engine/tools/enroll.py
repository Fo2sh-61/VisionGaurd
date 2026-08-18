"""Enrol a face so the system can recognise it.

Nothing about attendance can be tested until at least one person is in the
gallery, so this is the first thing to run. Start with yourself.

    # capture from the webcam — press SPACE to take each shot
    python engine/tools/enroll.py --name "Mohamed Fouad" --type Staff

    # or from a folder of photos, one person per subfolder
    python engine/tools/enroll.py --photos data/faces/

    python engine/tools/enroll.py --list
    python engine/tools/enroll.py --remove p-mohamed-fouad
    python engine/tools/enroll.py --test        # live recognition check

Take several shots, not one
---------------------------
A single photo captures one angle under one light. Recognition then fails the
moment someone turns their head or walks in under a different lamp. Four or five
varied captures — straight on, turned left, turned right, chin up, chin down —
are worth far more than one perfect one. The tool asks for five by default and
tells you when a shot is too similar to one already taken.

Note on what is stored
----------------------
Only the 128-number vector is saved, never the image. That vector cannot be
turned back into a photograph. It is still biometric data about a person, and
where minors are involved that is regulated separately from ordinary personal
data in most places.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.identity.gallery import FaceGallery  # noqa: E402
from vg.infer.faces import FacePipeline  # noqa: E402
from vg.ingest.source import CameraSource  # noqa: E402

GREEN = (120, 220, 120)
AMBER = (60, 180, 250)
RED = (80, 80, 240)
WHITE = (245, 245, 245)

SHOTS_WANTED = 5
# Two captures more similar than this are the same pose and add nothing.
TOO_SIMILAR = 0.92


def slugify(name: str) -> str:
    return "p-" + re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def open_gallery(pipeline: FacePipeline) -> FaceGallery:
    try:
        cfg = vgconfig.load()
        db = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not db.is_absolute():
            db = ENGINE_DIR.parent / db
    except vgconfig.ConfigError:
        db = ENGINE_DIR / "data" / "visionguard.db"

    return FaceGallery(db, model=pipeline.model_name, threshold=pipeline.threshold)


def draw_face(image, face, colour, label: str) -> None:
    cv2.rectangle(image, (face.x, face.y), (face.x + face.w, face.y + face.h), colour, 2)
    cv2.putText(image, label, (face.x, max(18, face.y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2, cv2.LINE_AA)
    for lx, ly in face.landmarks.astype(int):
        cv2.circle(image, (lx, ly), 2, colour, -1)


def hud(image, lines: list[tuple[str, tuple]]) -> None:
    h = image.shape[0]
    cv2.rectangle(image, (0, h - 26 * len(lines) - 10), (image.shape[1], h), (24, 24, 28), -1)
    for i, (text, colour) in enumerate(lines):
        cv2.putText(image, text, (12, h - 12 - 26 * (len(lines) - 1 - i)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# capture from the webcam
# ---------------------------------------------------------------------------

def enrol_from_camera(args, pipeline: FacePipeline, gallery: FaceGallery) -> int:
    person_id = args.id or slugify(args.name)
    gallery.add_person(person_id, args.name, args.type, args.group, args.detail)

    print(f"\nenrolling {args.name}  ({person_id})")
    print(f"take {args.shots} shots — vary the angle between each one")
    print("SPACE capture   Q finish   ESC cancel\n")

    captured: list[np.ndarray] = []
    cam = CameraSource("enrol", args.source, target_fps=15)
    if not cam.open():
        print(f"could not open {cam.redacted}: {cam.health.last_error}", file=sys.stderr)
        return 1

    try:
        for frame in cam.frames():
            display = frame.image.copy()
            faces = pipeline.detector.detect(frame.image)

            usable = None
            if len(faces) == 1:
                usable = faces[0]
                draw_face(display, usable, GREEN, f"{usable.confidence:.2f}")
            elif len(faces) > 1:
                # Ambiguous: we would not know which face we just enrolled.
                for f in faces:
                    draw_face(display, f, RED, "")
            hud(display, [
                (f"{len(captured)}/{args.shots} captured", GREEN if captured else WHITE),
                ("SPACE capture   Q finish   ESC cancel", (170, 170, 175)),
                (("ready" if usable is not None
                  else "more than one face in shot" if faces
                  else "no face detected"),
                 GREEN if usable is not None else AMBER),
            ])
            cv2.imshow(f"enrol — {args.name}", display)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                print("cancelled")
                gallery.remove_person(person_id)
                return 1
            if key in (ord("q"), ord("Q")):
                break
            if key == ord(" ") and usable is not None:
                vector = pipeline.embedder.embed(frame.image, usable)

                clash = max(
                    (float(np.dot(vector, prior)) for prior in captured), default=0.0
                )
                if clash > TOO_SIMILAR:
                    print(f"  too similar to an earlier shot ({clash:.2f}) — "
                          f"change angle and try again")
                    continue

                captured.append(vector)
                gallery.add_embedding(person_id, vector, pipeline.model_name,
                                      quality=usable.confidence, source="webcam")
                print(f"  captured {len(captured)}/{args.shots}")
                if len(captured) >= args.shots:
                    break
    finally:
        cam.close()
        cv2.destroyAllWindows()

    if not captured:
        gallery.remove_person(person_id)
        print("nothing captured; person not enrolled", file=sys.stderr)
        return 1

    print(f"\nenrolled {args.name} with {len(captured)} face(s)")
    if len(captured) < 3:
        print("only a few angles captured — recognition will be brittle.")
        print("re-run this to add more; they accumulate.")
    return 0


# ---------------------------------------------------------------------------
# enrol from a folder
# ---------------------------------------------------------------------------

def enrol_from_photos(folder: Path, pipeline: FacePipeline, gallery: FaceGallery) -> int:
    """Expects one subfolder per person, named after them:

        data/faces/Layla Ahmed/1.jpg
        data/faces/Omar Khaled/a.png
    """
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 1

    people = sorted(p for p in folder.iterdir() if p.is_dir())
    if not people:
        print(f"no person subfolders in {folder}", file=sys.stderr)
        return 1

    total = 0
    for person_dir in people:
        name = person_dir.name
        person_id = slugify(name)
        gallery.add_person(person_id, name)

        images = [
            p for p in sorted(person_dir.iterdir())
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        ]
        added = 0
        for path in images:
            image = cv2.imread(str(path))
            if image is None:
                print(f"  {path.name}: unreadable")
                continue

            faces = pipeline.detector.detect(image)
            if not faces:
                print(f"  {path.name}: no face found")
                continue
            if len(faces) > 1:
                # Do not guess which face is the person being enrolled.
                print(f"  {path.name}: {len(faces)} faces, skipping (needs one)")
                continue

            gallery.add_embedding(
                person_id, pipeline.embedder.embed(image, faces[0]),
                pipeline.model_name, quality=faces[0].confidence, source=path.name,
            )
            added += 1

        total += added
        state = "ok" if added >= 3 else "thin" if added else "FAILED"
        print(f"{name:<28} {added}/{len(images)} usable  [{state}]")

    print(f"\nenrolled {total} face(s) across {len(people)} people")
    return 0 if total else 1


# ---------------------------------------------------------------------------
# live check
# ---------------------------------------------------------------------------

def run_test(args, pipeline: FacePipeline, gallery: FaceGallery) -> int:
    if gallery.size == 0:
        print("gallery is empty — enrol someone first", file=sys.stderr)
        return 1

    print(f"\nrecognising against {gallery.size} enrolled "
          f"person(s), {gallery.embedding_count} face(s)")
    print(f"threshold {gallery.threshold:.3f}   margin {gallery.margin:.3f}")
    print("Q to quit\n")

    cam = CameraSource("test", args.source, target_fps=15)
    if not cam.open():
        print(f"could not open camera: {cam.health.last_error}", file=sys.stderr)
        return 1

    try:
        for frame in cam.frames():
            display = frame.image.copy()
            for obs in pipeline.observe(frame.image):
                match = gallery.match(obs.embedding, obs.model)
                if match.matched:
                    colour, label = GREEN, f"{match.person.name} {match.score:.2f}"
                else:
                    # Show WHY it declined — "unknown" alone teaches nothing
                    # about where the threshold should sit.
                    colour = AMBER if match.score > 0.2 else RED
                    label = f"? {match.score:.2f} ({match.reason})"
                draw_face(display, obs.face, colour, label)

            hud(display, [(f"{gallery.size} enrolled   Q to quit", WHITE)])
            cv2.imshow("recognition test", display)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cam.close()
        cv2.destroyAllWindows()
    return 0


def list_people(gallery: FaceGallery) -> int:
    people = gallery.people()
    if not people:
        print("\ngallery is empty\n")
        return 0

    print(f"\n{len(people)} people, {gallery.embedding_count} faces "
          f"({gallery.model})\n")
    print(f"  {'id':<26} {'name':<26} {'type':<9} faces")
    for p in people:
        flag = "" if p.photo_count >= 3 else "  <- thin, add more angles"
        print(f"  {p.id:<26} {p.name:<26} {p.type:<9} {p.photo_count}{flag}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Enrol faces into the gallery.")
    p.add_argument("--name", help="person's full name")
    p.add_argument("--id", help="stable id (default: derived from the name)")
    p.add_argument("--type", default="Student", choices=["Student", "Staff", "Visitor"])
    p.add_argument("--group", help="e.g. 'Grade 8'")
    p.add_argument("--detail", help="e.g. 'Grade 8 - B'")
    p.add_argument("--shots", type=int, default=SHOTS_WANTED)
    p.add_argument("--source", default="webcam:0")
    p.add_argument("--photos", type=Path, help="enrol from a folder instead")
    p.add_argument("--list", action="store_true")
    p.add_argument("--remove", metavar="ID")
    p.add_argument("--test", action="store_true", help="live recognition check")
    args = p.parse_args(argv)

    pipeline = FacePipeline()
    gallery = open_gallery(pipeline)

    try:
        if args.list:
            return list_people(gallery)
        if args.remove:
            ok = gallery.remove_person(args.remove)
            print(f"removed {args.remove}" if ok else f"no such person: {args.remove}")
            return 0 if ok else 1
        if args.test:
            return run_test(args, pipeline, gallery)
        if args.photos:
            return enrol_from_photos(args.photos, pipeline, gallery)
        if args.name:
            return enrol_from_camera(args, pipeline, gallery)

        p.print_help()
        return 2
    finally:
        gallery.close()


if __name__ == "__main__":
    raise SystemExit(main())
