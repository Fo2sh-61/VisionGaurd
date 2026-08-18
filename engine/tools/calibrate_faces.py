"""Measure what the recognition threshold should actually be.

The 0.363 default is OpenCV Zoo's published operating point, measured on
benchmark photography. Your cameras, your lighting and your population are not
that benchmark, so the number has to be re-measured here or every confidence
percentage the console shows a head teacher is decoration.

Two things get measured:

  genuine   same person, different captures. Should score HIGH.
  impostor  different people. Should score LOW.

If the two overlap, no threshold separates them and the honest answer is that
recognition is not reliable under these conditions — which is worth knowing
before it is put in front of a school rather than after.

    python engine/tools/calibrate_faces.py             use the enrolled gallery
    python engine/tools/calibrate_faces.py --live      measure face size effects

`--live` answers a different question: how big does a face have to be? It
watches you move towards and away from the camera and reports how stable the
embedding is at each distance. That is how MIN_FACE_PIXELS was set.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from vg import config as vgconfig  # noqa: E402
from vg.infer.faces import FacePipeline  # noqa: E402
from vg.ingest.source import CameraSource  # noqa: E402


def database_path() -> Path:
    try:
        cfg = vgconfig.load()
        db = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        return db if db.is_absolute() else ENGINE_DIR.parent / db
    except vgconfig.ConfigError:
        return ENGINE_DIR / "data" / "visionguard.db"


def load_vectors(model: str) -> dict[str, list[np.ndarray]]:
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT p.name, e.vector FROM face_embedding e "
            "JOIN person p ON p.id = e.person_id WHERE e.model = ?",
            (model,),
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, list[np.ndarray]] = {}
    for row in rows:
        out.setdefault(row["name"], []).append(
            np.frombuffer(row["vector"], dtype=np.float32)
        )
    return out


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def calibrate_gallery(model: str) -> int:
    people = load_vectors(model)
    if not people:
        print(f"\nno {model} embeddings enrolled yet.\n"
              f"run:  python engine/tools/enroll.py --name \"Your Name\"\n",
              file=sys.stderr)
        return 1

    usable = {n: v for n, v in people.items() if len(v) >= 2}
    print(f"\n{len(people)} people enrolled, {sum(len(v) for v in people.values())} faces")

    genuine: list[float] = []
    for name, vectors in usable.items():
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                genuine.append(float(np.dot(vectors[i], vectors[j])))

    impostor: list[float] = []
    names = list(people)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for va in people[a]:
                for vb in people[b]:
                    impostor.append(float(np.dot(va, vb)))

    if not genuine:
        print("\nEvery person has only one face enrolled, so there is nothing to")
        print("compare. Enrol 4-5 varied angles each and run this again.")
        print("That is also what makes recognition work in the first place.\n")
        return 1

    print(f"\ngenuine  (same person)      n={len(genuine)}")
    print(f"  median {np.median(genuine):.3f}   "
          f"5th pct {percentile(genuine, 5):.3f}   min {min(genuine):.3f}")

    if impostor:
        print(f"\nimpostor (different people) n={len(impostor)}")
        print(f"  median {np.median(impostor):.3f}   "
              f"95th pct {percentile(impostor, 95):.3f}   max {max(impostor):.3f}")
    else:
        print("\nimpostor: none — only one person enrolled.")
        print("  Enrol a second person to measure false accepts. Without that,")
        print("  the false-accept rate is simply unknown.")

    print("\n" + "-" * 62)
    if impostor:
        low, high = percentile(genuine, 5), percentile(impostor, 95)
        if low > high:
            recommended = (low + high) / 2
            print(f"Clean separation. Recommended threshold: {recommended:.3f}")
            print(f"  genuine 5th pct  {low:.3f}")
            print(f"  impostor 95th pct {high:.3f}")
        else:
            print("OVERLAP — genuine and impostor scores are not separable.")
            print(f"  genuine 5th pct   {low:.3f}  (want this HIGH)")
            print(f"  impostor 95th pct {high:.3f}  (want this LOW)")
            print("\n  No threshold makes this reliable. Likely causes: too few")
            print("  angles enrolled, faces too small, or poor lighting. Fix the")
            print("  captures before trusting any number this produces.")
    else:
        print(f"With one person there is no false-accept measurement.")
        print(f"Genuine 5th pct is {percentile(genuine, 5):.3f} — a threshold above")
        print("that would start rejecting the person you enrolled.")
    print("-" * 62 + "\n")
    return 0


def calibrate_live(source: str) -> int:
    """How large does a face need to be? Move towards and away from the camera."""
    import cv2

    pipeline = FacePipeline()
    print("\nMove slowly towards and away from the camera for ~20 seconds.")
    print("Measuring embedding stability against face size. Q to stop.\n")

    cam = CameraSource("calib", source, target_fps=15)
    if not cam.open():
        print(f"could not open camera: {cam.health.last_error}", file=sys.stderr)
        return 1

    samples: list[tuple[int, np.ndarray]] = []
    try:
        for frame in cam.frames():
            # min_size=20 deliberately: we are measuring the small end.
            faces = pipeline.detector.detect(frame.image, min_size=20)
            display = frame.image.copy()
            if len(faces) == 1:
                face = faces[0]
                samples.append((face.w, pipeline.embedder.embed(frame.image, face)))
                cv2.rectangle(display, (face.x, face.y),
                              (face.x + face.w, face.y + face.h), (120, 220, 120), 2)
                cv2.putText(display, f"{face.w}px  n={len(samples)}",
                            (face.x, max(18, face.y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 220, 120), 2)

            cv2.imshow("calibration - move closer and further", display)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
            if len(samples) >= 400:
                break
    finally:
        cam.close()
        cv2.destroyAllWindows()

    if len(samples) < 20:
        print("not enough samples - was a face in view?", file=sys.stderr)
        return 1

    # Consecutive frames are the same person a fraction of a second apart, so
    # anything below ~0.9 is instability rather than a real difference.
    buckets: dict[int, list[float]] = {}
    for i in range(1, len(samples)):
        width = (samples[i][0] + samples[i - 1][0]) // 2
        buckets.setdefault(width // 20 * 20, []).append(
            float(np.dot(samples[i][1], samples[i - 1][1]))
        )

    print(f"\n{len(samples)} samples\n")
    print("  face width   n    median   min     verdict")
    for lo in sorted(buckets):
        values = buckets[lo]
        if len(values) < 3:
            continue
        median = float(np.median(values))
        verdict = ("stable" if median > 0.9
                   else "usable" if median > 0.75
                   else "TOO SMALL")
        print(f"  {lo:3d}-{lo + 19:3d} px  {len(values):3d}   "
              f"{median:.3f}   {min(values):.3f}   {verdict}")

    print("\n  Consecutive frames are the same face a fraction of a second apart,")
    print("  so anything well below 1.0 is the embedding being unstable, not the")
    print("  person changing. Set MIN_FACE_PIXELS at the smallest 'stable' row.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure face recognition thresholds.")
    p.add_argument("--live", action="store_true",
                   help="measure how face size affects stability")
    p.add_argument("--source", default="webcam:0")
    args = p.parse_args(argv)

    if args.live:
        return calibrate_live(args.source)
    return calibrate_gallery(FacePipeline().model_name)


if __name__ == "__main__":
    raise SystemExit(main())
