"""Attendance demo logic: enrolled gallery, matching, face tracks and the day register.

The recognition models are VisionGuard's own (YuNet + SFace, loaded read-only from its
engine folder), and the matching rule is a copy of ``vg.identity.gallery.FaceGallery.match``:
best score per person, a threshold, and a margin over the runner-up. Nothing here writes to
VisionGuard (no database, no bytecode caches).

Naming bar. VisionGuard names a *body* with the stricter ``tracking.identity`` gate
(score 0.60, margin 0.10) rather than the raw gallery threshold (0.363): measured on its own
clips, strangers score up to ~0.4 against an enrolled face, so with a small gallery the raw
threshold alone can put a name on the wrong person. The demo uses the strict bar everywhere,
so everything a viewer sees named is something the product would stand behind.
"""

import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path

import numpy as np

VG_ENGINE_DIR = Path(os.environ.get("VG_ENGINE_DIR", r"E:\VisionGuard\engine"))

# VisionGuard's values (verified against its code by tests/test_attendance_demo.py when present).
GALLERY_THRESHOLD = 0.363     # vg.infer.faces.SFACE_COSINE_THRESHOLD
GALLERY_MARGIN = 0.06         # vg.identity.gallery.FaceGallery.DEFAULT_MARGIN
IDENTITY_SCORE = 0.60         # engine.yaml tracking.identity.score
IDENTITY_MARGIN = 0.10        # engine.yaml tracking.identity.margin
MIN_FACE_PIXELS = 80          # vg.infer.faces.MIN_FACE_PIXELS
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_pipeline():
    """VisionGuard's FacePipeline (detect, align, embed), imported without touching its folder."""
    sys.dont_write_bytecode = True
    if str(VG_ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(VG_ENGINE_DIR))
    from vg.infer.faces import FacePipeline
    return FacePipeline()


# ------------------------------------------------------------------ gallery --

@dataclass(frozen=True)
class Match:
    person_id: str | None
    score: float
    runner_up: float = 0.0
    reason: str = ""

    @property
    def matched(self):
        return self.person_id is not None


class Gallery:
    """Enrolled people and 'who is this?', with an honest refusal to guess."""

    def __init__(self, threshold=IDENTITY_SCORE, margin=IDENTITY_MARGIN):
        self.threshold, self.margin = threshold, margin
        self.names: dict[str, str] = {}
        self._vectors: list[np.ndarray] = []
        self._owners: list[str] = []

    def add(self, person_id, name, vector):
        v = np.asarray(vector, dtype=np.float32).flatten()
        norm = np.linalg.norm(v)
        self.names.setdefault(person_id, name)
        self._vectors.append(v / norm if norm > 0 else v)
        self._owners.append(person_id)

    def photo_count(self, person_id):
        return self._owners.count(person_id)

    def match(self, embedding) -> Match:
        if not self._vectors:
            return Match(None, 0.0, reason="gallery is empty")
        query = np.asarray(embedding, dtype=np.float32).flatten()
        scores = np.stack(self._vectors) @ query
        best: dict[str, float] = {}
        for owner, s in zip(self._owners, scores):
            best[owner] = max(best.get(owner, -1.0), float(s))
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        if top < self.threshold:
            return Match(None, top, runner, "below threshold")
        if len(ranked) > 1 and top - runner < self.margin:
            return Match(None, top, runner, "too close to call")
        return Match(top_id, top, runner, "matched")


def display_name(folder_name):
    return folder_name.replace("_", " ").strip()


def enrol_from_folder(folder, pipeline, gallery, min_size=MIN_FACE_PIXELS):
    """One subfolder per person, named after them, as in VisionGuard's enroll.py --photos.
    A photo must contain exactly one usable face. Returns {name: {"used": n, "skipped": [...]}}."""
    folder = Path(folder)
    report = {}
    for person_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        name = display_name(person_dir.name)
        used, skipped = 0, []
        for path in sorted(person_dir.iterdir()):
            if path.suffix.lower() not in PHOTO_EXTS:
                continue
            import cv2
            image = cv2.imread(str(path))
            if image is None:
                skipped.append(f"{path.name}: unreadable")
                continue
            faces = pipeline.detector.detect(image, min_size=min_size)
            if len(faces) != 1:
                skipped.append(f"{path.name}: {len(faces)} faces (needs exactly one)")
                continue
            gallery.add(person_dir.name, name, pipeline.embedder.embed(image, faces[0]))
            used += 1
        report[name] = {"used": used, "skipped": skipped}
    return report


def gallery_from_vg_db(db_path, threshold=IDENTITY_SCORE, margin=IDENTITY_MARGIN):
    """The people enrolled in a VisionGuard database, opened read-only."""
    gallery = Gallery(threshold, margin)
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        names = {pid: name for pid, name in con.execute("select id, name from person")}
        for pid, vec in con.execute("select person_id, vector from face_embedding where model = 'sface-2021dec'"):
            gallery.add(pid, names.get(pid, pid), np.frombuffer(vec, dtype=np.float32))
    finally:
        con.close()
    return gallery


# -------------------------------------------------------------------- tracks --

def iou(a, b):
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


@dataclass
class FaceTrack:
    id: int
    box: tuple          # x, y, w, h in pixels
    last_frame: int
    history: list = field(default_factory=list)    # (person_id | None, score) of recent looks
    person_id: str | None = None
    score: float = 0.0
    hits: int = 0                                  # looks so far

    def observe(self, box, frame_idx, match, window=6, confirm=2):
        self.box, self.last_frame = box, frame_idx
        self.hits += 1
        self.history = (self.history + [(match.person_id, match.score)])[-window:]
        votes: dict[str, list[float]] = {}
        for pid, sc in self.history:
            if pid is not None:
                votes.setdefault(pid, []).append(sc)
        best = max(votes.items(), key=lambda kv: len(kv[1]), default=None)
        if best and len(best[1]) >= confirm:
            self.person_id, self.score = best[0], float(np.mean(best[1]))
        else:
            self.person_id, self.score = None, match.score


class FaceTracks:
    """Greedy box association: a face that overlaps (or sits very near) last frame's face is
    the same face. A person is named only after ``confirm`` matching looks among the last few,
    so one lucky frame never puts a name on someone."""

    def __init__(self, max_age=8, confirm=2, window=6):
        self.max_age, self.confirm, self.window = max_age, confirm, window
        self.tracks: list[FaceTrack] = []
        self._next = 1

    def update(self, frame_idx, observations):
        """observations: [(box, Match)] -> [(track, box)] in the same order."""
        out, taken = [], set()
        for box, match in observations:
            best, best_score = None, 0.0
            for t in self.tracks:
                if t.id in taken or frame_idx - t.last_frame > self.max_age:
                    continue
                overlap = iou(box, t.box)
                dist = math.hypot(box[0] + box[2] / 2 - t.box[0] - t.box[2] / 2,
                                  box[1] + box[3] / 2 - t.box[1] - t.box[3] / 2) / max(box[2], t.box[2])
                score = overlap if overlap > 0.15 else (0.15 - dist * 0.1 if dist < 0.6 else 0.0)
                if score > best_score:
                    best, best_score = t, score
            if best is None:
                best = FaceTrack(self._next, box, frame_idx)
                self._next += 1
                self.tracks.append(best)
            taken.add(best.id)
            best.observe(box, frame_idx, match, self.window, self.confirm)
            out.append((best, box))
        self.tracks = [t for t in self.tracks if frame_idx - t.last_frame <= self.max_age]
        return out


# ------------------------------------------------------------------ register --

def parse_clock(text):
    parts = [int(p) for p in str(text).split(":")]
    if not 2 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise ValueError(f"expected HH:MM or HH:MM:SS, got {text!r}")
    h, m, s = (parts + [0])[:3]
    return h * 3600 + m * 60 + s


def fmt_clock(seconds):
    s = int(seconds) % 86400
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def minutes_late(arrival_s, cutoff_s):
    """Whole minutes past the cutoff, rounded up (so 08:00:30 is 1 minute late)."""
    return max(1, math.ceil((arrival_s - cutoff_s) / 60))


@dataclass
class Entry:
    person_id: str
    name: str
    clock_s: float
    status: str                  # on_time | late
    minutes_late: int | None
    frame_idx: int
    score: float
    thumb: np.ndarray | None = None


class Register:
    """The day register: first sighting per person, on time or late against a cutoff.

    Mirrors VisionGuard: an arrival only counts inside the site's hours, and absence is just
    the lack of an arrival. ``clock_start`` is the demo's site clock at video time zero."""

    def __init__(self, names, clock_start="07:50:00", cutoff="08:00", hours=("06:30", "16:00"), rate=1.0):
        self.names = dict(names)
        self.clock_start = parse_clock(clock_start)
        self.cutoff = parse_clock(cutoff)
        self.window = (parse_clock(hours[0]), parse_clock(hours[1]))
        self.rate = rate               # demo clock speed: site seconds per video second
        self.entries: dict[str, Entry] = {}
        self.seen_outside_hours: set[str] = set()   # recognised, but not inside the site's hours

    def clock_at(self, video_seconds):
        return self.clock_start + video_seconds * self.rate

    def mark(self, person_id, video_seconds, frame_idx, score, thumb=None):
        """Record an arrival; returns the Entry if this is the person's first, else None."""
        if person_id in self.entries or person_id not in self.names:
            return None
        now = self.clock_at(video_seconds)
        if not self.window[0] <= now <= self.window[1]:
            self.seen_outside_hours.add(person_id)   # recorded sighting, but not an arrival
            return None
        late = now > self.cutoff
        entry = Entry(person_id, self.names[person_id], now, "late" if late else "on_time",
                      minutes_late(now, self.cutoff) if late else None, frame_idx, score, thumb)
        self.entries[person_id] = entry
        return entry

    @property
    def present(self):
        return len(self.entries)
