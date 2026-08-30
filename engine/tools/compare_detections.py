"""Did that change move a detection? Record the clip, then diff two records.

The one hard rule of workload placement is that **no detection result may
change**. Removing work nothing reads is worth doing; removing work something
reads is a missed face, an uncounted person or an unread plate, and no amount
of saved processor time buys that back.

That rule needs a machine to enforce it. A unit test cannot tell you a face
box moved four pixels, and eyeballing the clip cannot tell you a plate read
came back with one character different.

Run:

    python engine/tools/compare_detections.py --record before.json
    # ... apply one change ...
    python engine/tools/compare_detections.py --record after.json
    python engine/tools/compare_detections.py --diff before.json after.json

`--diff` prints `identical` or names every frame that moved. Anything other
than `identical` means the change is rejected: not shipped behind a flag, and
not fixed by moving a threshold until the diff goes quiet.

**Why this drives the models directly rather than starting the engine.** The
live pipeline rate-limits each worker independently and `SharedDetection`
caches on `(camera, sequence)`, so two live runs do not sample the same
frames. The diff would then report scheduling noise as a regression, the
regressions would be ignored, and the gate would be worse than useless.
Here every frame goes through every model, in order, once.

Nothing about accuracy is claimed. This measures SAMENESS. If the engine was
wrong before the change it will be equally wrong after, and this will call
that a pass - correctly, because that is a different question.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

#: Coordinates are rounded to this many decimal places before comparing.
#:
#: Not a tolerance for real movement - it is 1/10000th of the frame, well
#: under a pixel at any resolution this runs at. It exists because GPU
#: floating point is not bit-reproducible between runs, and without it the
#: gate would cry wolf on every run and be ignored within a day.
PLACES = 4


def _frames(limit: int) -> list[np.ndarray]:
    clips = sorted(glob.glob(str(ENGINE_DIR / "data" / "footage" / "*.mp4")))
    walk = [c for c in clips if "walk-through" in c] or clips
    if not walk:
        raise SystemExit(
            "no clip in engine/data/footage - there is nothing to compare "
            "against. Record one with: python engine/tools/record.py"
        )

    cap = cv2.VideoCapture(walk[0])
    out: list[np.ndarray] = []
    while len(out) < limit:
        ok, frame = cap.read()
        if not ok:
            break
        out.append(frame)
    cap.release()
    print(f"  {len(out)} frames from {Path(walk[0]).name}")
    return out


def _round(values) -> list[float]:
    return [round(float(v), PLACES) for v in values]


def _people(detector, image) -> list[list[float]]:
    from vg.infer.persons import PersonDetector

    boxes = detector.raw_boxes(image)
    h, w = image.shape[:2]
    return sorted(
        _round((p.x, p.y, p.w, p.h, p.confidence))
        for p in PersonDetector.people_from(boxes, w, h)
    )


def _faces(pipeline, gallery, image) -> list[dict]:
    """Faces, where they are, and who they were matched to.

    The identity matters as much as the box. A change that finds the same
    faces but names a different person is the worst possible outcome for this
    feature, and a box-only diff would pass it.
    """
    out = []
    for observation in pipeline.observe(image):
        face = observation.face
        h, w = image.shape[:2]
        entry = {"box": _round(face.to_fractions(w, h))}
        if gallery is not None:
            match = gallery.match(observation.embedding, observation.model)
            person = getattr(match, "person", None)
            entry["person"] = getattr(person, "name", None)
            entry["score"] = round(float(getattr(match, "score", 0.0)), 3)
        out.append(entry)
    return sorted(out, key=lambda e: e["box"])


def _plates(reader, image) -> list[str]:
    """Every plate found, and what it was read as.

    Detector then characters, exactly as the feature runs them - the
    character model only ever sees a crop the detector returned. Comparing
    the READING and not just the box is the point: a plate found in the same
    place and read one character differently is still a changed result, and
    it is the way plate reading actually goes wrong.
    """
    out = []
    for box in reader.find(image):
        try:
            text, confidence, _ = reader.read_plate(box.crop(image))
        except Exception:
            continue
        if text:
            out.append(f"{text}@{round(float(confidence), 3)}")
    return sorted(out)


def batch_check(limit):
    """Batched shared detection vs unbatched, on the same frames.

    Same reason `--gate-check` exists: `--record` drives the models directly,
    so `SharedDetection` never runs and batching would never be exercised. A
    before/after pair of recordings would come back identical while proving
    nothing at all.

    Here the same frames go through a real `SharedDetection` twice - once with
    batching off, once on - and the boxes are compared per frame. The failure
    this is looking for is not "slightly different numbers". It is one
    camera's boxes being filed against another camera's frame, which looks
    entirely plausible on screen and is the whole risk of batching.
    """
    import threading

    from vg.infer.persons import PersonDetector
    from vg.infer.shared import SharedDetection

    class Frame:
        def __init__(self, camera_id, sequence, image):
            self.camera_id = camera_id
            self.sequence = sequence
            self.image = image
            self.width = image.shape[1]
            self.height = image.shape[0]

    print("\nBatching check - shared detection, batched vs not\n")
    frames = _frames(limit)
    detector = PersonDetector()
    print(f"  person   {detector.weights.name} on {detector.device}")
    print()

    def run(batch):
        shared = SharedDetection(detector, batch=batch)
        out = {}
        lock = threading.Lock()

        def ask(index, image):
            # Four cameras, all handed the same picture. Any mix-up then
            # shows as one camera's answer differing from the others', which
            # a single-camera run could never reveal.
            f = Frame(f"cam-{index % 4}", index, image)
            try:
                boxes = shared.raw_boxes(f)
                people = PersonDetector.people_from(boxes, f.width, f.height)
                answer = sorted(
                    _round((q.x, q.y, q.w, q.h, q.confidence)) for q in people)
            except BaseException as exc:          # noqa: BLE001 - shown below
                answer = f"ERROR {type(exc).__name__}: {exc}"
            with lock:
                out[index] = answer

        threads = [threading.Thread(target=ask, args=(i, im))
                   for i, im in enumerate(frames)]
        for chunk in range(0, len(threads), 4):
            group = threads[chunk:chunk + 4]
            for th in group:
                th.start()
            for th in group:
                th.join(timeout=30)
        return out, shared.passes

    plain, plain_passes = run(False)
    batched, batched_passes = run(True)

    moved = [i for i in plain if plain.get(i) != batched.get(i)]

    print(f"  {len(frames)} frames, 4 cameras")
    print(f"  unbatched  {plain_passes} model calls")
    print(f"  batched    {batched_passes} model calls")

    if not moved:
        print("\n  identical - batching changed no box\n")
        return 0

    print(f"  DIFFERENT on {len(moved)} frame(s)")
    for i in moved[:10]:
        print(f"    frame {i}")
        print(f"      unbatched: {plain.get(i)}")
        print(f"      batched:   {batched.get(i)}")
    print("\n  A frame received boxes that are not its own. REJECTED.\n")
    return 1


def gate_check(limit: int) -> int:
    """Whole-frame face detection vs person-gated, on the same frames.

    This is the check change 2 actually has to pass, and a before/after
    recording cannot make it. `--record` drives the models directly, so
    gating - which lives in the WORKER - never runs and a crop-offset bug
    would sail through with two identical files.

    Here both paths run over the same frame in the same process, and the
    faces are compared in FULL-FRAME coordinates. If gating moved a box, lost
    a face or changed who it matched, it shows up on the frame it happened on.

    A gated run finding FEWER faces is the expected way this fails: a person
    box is a body box, so a tight crop clips the head. That is what CROP_PAD
    exists for, and this is what proves the padding is enough.
    """
    from vg.features.recognition import person_crops
    from vg.infer.faces import FacePipeline
    from vg.infer.persons import PersonDetector

    print("\nFace gating check - whole frame vs person crops\n")
    frames = _frames(limit)

    pipeline = FacePipeline()
    detector = PersonDetector()
    print(f"  faces    {pipeline.model_name}")
    print(f"  person   {detector.weights.name} on {detector.device}\n")

    moved = []
    whole_total = gated_total = 0

    for index, image in enumerate(frames):
        h, w = image.shape[:2]

        whole = sorted(_round(o.face.to_fractions(w, h))
                       for o in pipeline.observe(image))

        people = PersonDetector.people_from(
            detector.raw_boxes(image), w, h)
        gated = []
        for crop, (ox, oy) in person_crops(
                image, [(p.x, p.y, p.w, p.h) for p in people]):
            for observation in pipeline.observe(crop):
                gated.append(_round(
                    observation.face.offset(ox, oy).to_fractions(w, h)))
        gated.sort()

        whole_total += len(whole)
        gated_total += len(gated)
        if whole != gated:
            moved.append((index, whole, gated))

    print(f"  {len(frames)} frames")
    print(f"  whole frame  {whole_total} faces")
    print(f"  gated        {gated_total} faces")

    if not moved:
        print("\n  identical - gating changed no face on this clip\n")
        return 0

    print(f"\n  DIFFERENT on {len(moved)} frame(s)")
    for index, whole, gated in moved[:10]:
        print(f"    frame {index:>4}")
        print(f"      whole: {whole}")
        print(f"      gated: {gated}")
    if len(moved) > 10:
        print(f"    ... and {len(moved) - 10} more")
    print("\n  Under P8-FR-002 gating is REJECTED until this reads identical.")
    print("  Look first at the crop origin - a face found in a crop is in")
    print("  CROP coordinates until `offset` puts it back.\n")
    return 1


def record(path: Path, limit: int, skip_faces: bool, skip_plates: bool) -> int:
    print("\nVisionGuard detection record\n")
    frames = _frames(limit)

    from vg.infer.persons import PersonDetector
    detector = PersonDetector()
    print(f"  person   {detector.weights.name} on {detector.device}")

    pipeline = gallery = None
    if not skip_faces:
        try:
            from vg import config as vgconfig
            from vg.identity.gallery import FaceGallery
            from vg.infer.faces import FacePipeline

            pipeline = FacePipeline()
            cfg = vgconfig.load()
            database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
            if not database.is_absolute():
                database = vgconfig.REPO_DIR / database
            if database.is_file():
                gallery = FaceGallery(database, model=pipeline.model_name,
                                      threshold=pipeline.threshold)
                print(f"  faces    {pipeline.model_name}, "
                      f"{gallery.size} enrolled")
            else:
                print(f"  faces    {pipeline.model_name}, no gallery - "
                      "boxes only, identities NOT compared")
        except Exception as exc:
            print(f"  faces    unavailable ({exc}) - NOT compared")
            pipeline = None

    plates = None
    if not skip_plates:
        try:
            from vg.infer.plates import PlateReader
            plates = PlateReader()
            print("  plates   loaded")
        except Exception as exc:
            print(f"  plates   unavailable ({exc}) - NOT compared")

    # What was actually compared is recorded WITH the data. A record made
    # without the gallery and one made with it are not comparable, and a diff
    # that silently treated them as such would report a clean pass on a run
    # that never checked identities at all.
    covered = {
        "people": True,
        "faces": pipeline is not None,
        "identities": gallery is not None,
        "plates": plates is not None,
    }
    print(f"\n  comparing: {', '.join(k for k, v in covered.items() if v)}")
    missing = [k for k, v in covered.items() if not v]
    if missing:
        print(f"  NOT comparing: {', '.join(missing)}")

    rows = []
    for index, image in enumerate(frames):
        row = {"frame": index, "people": _people(detector, image)}
        if pipeline is not None:
            row["faces"] = _faces(pipeline, gallery, image)
        if plates is not None:
            try:
                row["plates"] = _plates(plates, image)
            except Exception:
                row["plates"] = []
        rows.append(row)
        if index and index % 20 == 0:
            print(f"  {index}/{len(frames)}")

    path.write_text(json.dumps(
        {"covered": covered, "frames": rows}, indent=1), encoding="utf-8")
    total = sum(len(r["people"]) for r in rows)
    print(f"\n  wrote {path}  ({len(rows)} frames, {total} person boxes)\n")
    return 0


def diff(before: Path, after: Path) -> int:
    a = json.loads(before.read_text(encoding="utf-8"))
    b = json.loads(after.read_text(encoding="utf-8"))

    print(f"\n  {before.name}  vs  {after.name}\n")

    if a.get("covered") != b.get("covered"):
        # Comparing a run that checked identities against one that did not
        # would report "identical" while having checked nothing of the kind.
        print("  REFUSED: the two records cover different things.")
        print(f"    {before.name}: {a.get('covered')}")
        print(f"    {after.name}: {b.get('covered')}")
        return 2

    rows_a, rows_b = a["frames"], b["frames"]
    if len(rows_a) != len(rows_b):
        print(f"  DIFFERENT: {len(rows_a)} frames vs {len(rows_b)}")
        return 1

    changed = []
    for ra, rb in zip(rows_a, rows_b):
        for key in ("people", "faces", "plates"):
            if ra.get(key) != rb.get(key):
                changed.append((ra["frame"], key, ra.get(key), rb.get(key)))

    if not changed:
        covered = ", ".join(k for k, v in a["covered"].items() if v)
        print(f"  identical  ({len(rows_a)} frames; compared: {covered})")
        skipped = [k for k, v in a["covered"].items() if not v]
        if skipped:
            # Said out loud. "Identical" over a comparison that skipped
            # identities is a narrower claim than it sounds, and the person
            # reading this output is deciding whether to ship.
            print(f"  NOT compared: {', '.join(skipped)} - "
                  "this result says nothing about them")
        print()
        return 0

    print(f"  DIFFERENT: {len(changed)} change(s)\n")
    for frame, key, was, now in changed[:20]:
        print(f"    frame {frame:>4}  {key}")
        print(f"      was: {was}")
        print(f"      now: {now}")
    if len(changed) > 20:
        print(f"    ... and {len(changed) - 20} more")

    print("\n  A detection moved. Under P8-FR-002 this change is REJECTED -")
    print("  not shipped behind a flag, and not fixed by moving a threshold")
    print("  until the diff goes quiet.\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, metavar="OUT")
    parser.add_argument("--diff", type=Path, nargs=2, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--no-faces", action="store_true")
    parser.add_argument("--no-plates", action="store_true")
    parser.add_argument("--batch-check", action="store_true",
                        help="compare batched shared detection against "
                             "unbatched, on the same frames")
    parser.add_argument("--gate-check", action="store_true",
                        help="compare whole-frame face detection against "
                             "person-gated, on the same frames")
    args = parser.parse_args(argv)

    if args.batch_check:
        return batch_check(args.frames)
    if args.gate_check:
        return gate_check(args.frames)
    if args.diff:
        return diff(*args.diff)
    if args.record:
        return record(args.record, args.frames, args.no_faces, args.no_plates)
    parser.error("give --record OUT, --diff BEFORE AFTER, or --gate-check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
