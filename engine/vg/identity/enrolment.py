"""Enrolment: staging photos, scoring them, and committing a person.

You cannot enrol 400 students from a command line, so this is the service layer
behind the browser's Enrolment Studio. `tools/enroll.py` keeps working and is
still the right tool for enrolling yourself during development.

Three things shape the design.

**Nothing is committed until it is worth committing.** Photos are staged in
memory against a session and only written to the gallery on `commit()`. A
half-enrolled person — one blurry photo, then the operator wanders off — is
worse than no person at all, because the register will confidently fail to
recognise them and nobody will know why.

**Images are never stored.** The gallery holds 128-number vectors and no
pixels, deliberately: a vector cannot be turned back into a photograph, which
materially limits what a database leak exposes when the subjects are children.
That property is preserved here. Frames arrive, are embedded, and the pixels are
dropped. The thumbnails in the UI live in the browser, never on the server.

**Similarity is a quality signal, not just a duplicate check.** A second photo
scoring 0.95 against the first adds nothing to recognition — it is the same
pose under the same light. What makes recognition robust is *varied* angles, so
a too-similar shot is rejected with an explanation rather than silently stored
to pad the count.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from vg.identity.gallery import FaceGallery, Person
from vg.infer.faces import MIN_FACE_PIXELS, DetectedFace, FacePipeline

log = logging.getLogger(__name__)

# Two captures more similar than this are the same pose and teach the model
# nothing new. Matches the value tools/enroll.py has used since the start.
TOO_SIMILAR = 0.92

# Below this the detector is not confident it is even looking at a face.
MIN_CONFIDENCE = 0.75

# A face this wide or wider scores full marks for size. Above roughly 200 px
# extra pixels stop improving the embedding.
GOOD_FACE_PIXELS = 200

# How many varied photos a person needs before Save unlocks. One photo is one
# lighting condition and one angle; recognition then fails the moment they turn
# their head.
#
# Five, raised from three (owner decision, 2026-08-21). Three was the point at
# which recognition became *possible*; five is where it becomes dependable
# across the angles and lighting an entrance camera actually sees. The cost is
# real and lands on the operator, not the engine: every photo must also differ
# from all the others (TOO_SIMILAR), so five takes noticeably more tries at the
# camera than three did.
#
# Nobody is enrolled below this. `commit()` refuses before `add_person` runs,
# so there is never a directory row with no face behind it — a person the
# cameras cannot recognise, sitting in a register that can only ever mark them
# absent.
#
# Raising it does not invalidate anybody already enrolled: existing people keep
# the vectors they have and stay recognisable. The People page reports the real
# count per person, so a three-photo enrolment from before reads as exactly
# that rather than being quietly presented as complete.
REQUIRED_PHOTOS = 5

# Sessions are abandoned all the time — an operator closes the tab mid-enrolment.
# Without expiry the staged vectors accumulate for the life of the process.
SESSION_TTL = timedelta(minutes=30)


def slugify(name: str) -> str:
    """`p-ahmed-hassan`. Same rule as tools/enroll.py, so ids stay consistent
    whichever route enrolled the person."""
    return "p-" + re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def describe_angle(face: DetectedFace) -> tuple[float, str]:
    """A rough head-turn estimate from the five landmarks, and a label.

    Returns `(yaw, label)` where yaw is roughly -1..1, negative and positive
    being opposite turns. Used to tell the operator that a new shot is a
    genuinely different angle rather than another version of the same one.

    Deliberately not labelled "left" or "right". The sign is reliable — it is
    just the nose's offset from the eye midpoint — but mapping it to the
    subject's own left and right depends on landmark ordering conventions that
    are easy to get backwards, and a confidently wrong instruction ("turn left")
    is worse than an honest "try a different angle". The sign is exposed so the
    UI can tell two angles apart, which is the thing that actually matters.
    """
    landmarks = np.asarray(face.landmarks, dtype=np.float32)
    if landmarks.shape[0] < 3:
        return 0.0, "unknown angle"

    eye_a, eye_b, nose = landmarks[0], landmarks[1], landmarks[2]
    eye_mid_x = (eye_a[0] + eye_b[0]) / 2.0
    eye_distance = abs(eye_b[0] - eye_a[0])
    if eye_distance < 1.0:
        return 0.0, "unknown angle"

    yaw = float((nose[0] - eye_mid_x) / eye_distance)
    magnitude = abs(yaw)

    if magnitude < 0.12:
        return yaw, "front on"
    if magnitude < 0.30:
        return yaw, "slight angle"
    return yaw, "strong angle"


def quality_score(face_pixels: int, confidence: float) -> float:
    """0-100, from the two things the pipeline already measures.

    Size dominates because it is the harder floor: below MIN_FACE_PIXELS an
    embedding is not a weak signal but a meaningless one, and no amount of
    detector confidence rescues it. A face at exactly the minimum still scores
    something rather than zero — it is usable, just not good.
    """
    span = max(1, GOOD_FACE_PIXELS - MIN_FACE_PIXELS)
    size = 0.30 + 0.70 * min(1.0, max(0.0, (face_pixels - MIN_FACE_PIXELS) / span))
    return round(100.0 * (0.55 * size + 0.45 * min(1.0, max(0.0, confidence))), 1)


@dataclass(frozen=True)
class StagedPhoto:
    """One assessed capture, held in memory until the session is committed."""

    id: str
    usable: bool
    score: float
    face_pixels: int
    confidence: float
    similarity: float
    yaw: float
    note: str
    vector: np.ndarray | None = None
    source: str = "upload"


@dataclass
class EnrolmentSession:
    """One person being enrolled, in progress."""

    id: str
    name: str
    type: str = "Student"
    group: str | None = None
    detail: str | None = None
    person_id: str = ""
    photos: list[StagedPhoto] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    touched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def usable(self) -> list[StagedPhoto]:
        return [p for p in self.photos if p.usable]

    @property
    def ready(self) -> bool:
        """Enough varied photos that recognition has a chance."""
        return len(self.usable) >= REQUIRED_PHOTOS

    @property
    def advice(self) -> str:
        """What the operator has to do next, in their words."""
        count = len(self.usable)
        if count == 0:
            return f"No usable photos yet. Need {REQUIRED_PHOTOS} from different angles."
        if count < REQUIRED_PHOTOS:
            short = REQUIRED_PHOTOS - count
            return (
                f"{count} usable. Need {short} more from a different angle."
            )

        angles = {round(p.yaw, 1) for p in self.usable}
        if len(angles) < 2:
            return (
                f"{count} usable, but they are all the same angle. "
                "One turned shot would make this much more reliable."
            )
        return f"{count} usable photos across {len(angles)} angles. Ready to save."


def _fraction(value: float) -> float:
    """A fraction of the frame, inside 0..1 whatever the detector said."""
    return max(0.0, min(1.0, float(value)))


class EnrolmentService:
    """Stages, scores and commits enrolments.

    Thread-safe because FastAPI serves requests from a thread pool and two
    uploads for the same session can genuinely overlap.
    """

    def __init__(self, gallery: FaceGallery, pipeline: FacePipeline) -> None:
        self.gallery = gallery
        self.pipeline = pipeline
        self._sessions: dict[str, EnrolmentSession] = {}
        self._lock = threading.RLock()

    # -- sessions -----------------------------------------------------------

    def start(
        self,
        name: str,
        type: str = "Student",
        group: str | None = None,
        detail: str | None = None,
        person_id: str | None = None,
    ) -> EnrolmentSession:
        name = name.strip()
        if not name:
            raise ValueError("a person needs a name")

        session = EnrolmentSession(
            id=uuid.uuid4().hex,
            name=name,
            type=type,
            group=group,
            detail=detail,
            person_id=(person_id or slugify(name)),
        )
        with self._lock:
            self._expire_locked()
            self._sessions[session.id] = session
        log.info("enrolment session %s started for %s", session.id, name)
        return session

    def session(self, session_id: str) -> EnrolmentSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.touched_at = datetime.now(timezone.utc)
            return session

    def cancel(self, session_id: str) -> bool:
        """Drop a session and every vector staged in it.

        Nothing was written to the gallery, so there is nothing to roll back —
        which is the point of staging.
        """
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def _expire_locked(self) -> None:
        cutoff = datetime.now(timezone.utc) - SESSION_TTL
        stale = [sid for sid, s in self._sessions.items() if s.touched_at < cutoff]
        for sid in stale:
            self._sessions.pop(sid, None)
        if stale:
            log.info("expired %d abandoned enrolment session(s)", len(stale))

    # -- photos -------------------------------------------------------------

    def add_photo(
        self, session_id: str, image: np.ndarray, source: str = "upload"
    ) -> StagedPhoto:
        """Assess one capture and stage it if it is worth keeping.

        An unusable photo is still returned and still recorded on the session,
        because the operator needs to see *why* it failed. A silently ignored
        upload looks like a broken button.
        """
        session = self.session(session_id)
        if session is None:
            raise KeyError(session_id)

        photo = self._assess(image, session, source)
        with self._lock:
            session.photos.append(photo)
        return photo

    # -- live preview -------------------------------------------------------

    def preview(self, frame) -> list[dict]:
        """The faces in one frame, as fractions, for the enrolment overlay.

        Geometry and nothing else. No embedding runs, no gallery is consulted,
        and no name comes back — an enrolment preview that claimed to know who
        it was looking at would be recognition leaking into enrolment, which is
        the bug that once made every person on a camera read as one person.

        The size floor is the same one `_assess` uses to pick a candidate, so
        the box the operator sees is a face capture would actually accept.
        Dropping it lower makes YuNet return dozens of "faces" on a normal
        corridor frame — texture, distant heads, noise — and the page would
        tell the operator there were nine people in the room.

        Runs in the request, on the frame the camera already has. Nothing runs
        when nobody is enrolling.
        """
        faces = []
        for face in self.pipeline.detector.detect(frame.image, min_size=MIN_FACE_PIXELS):
            x, y = frame.to_normalised(face.x, face.y)
            w, h = frame.to_normalised(face.w, face.h)
            faces.append({
                # Clamped because a face half out of shot has a negative
                # origin or a box past the edge, and the wire refuses anything
                # outside 0..1 — the overlay would vanish mid-enrolment and
                # read as "no face" when there plainly is one.
                "x": _fraction(x),
                "y": _fraction(y),
                "w": _fraction(w),
                "h": _fraction(h),
                "confidence": max(0.0, min(1.0, float(face.confidence))),
                "points": [
                    {
                        "x": _fraction(px / frame.width),
                        "y": _fraction(py / frame.height),
                    }
                    for px, py in face.landmarks
                ],
            })
        return faces

    def remove_photo(self, session_id: str, photo_id: str) -> bool:
        session = self.session(session_id)
        if session is None:
            raise KeyError(session_id)

        with self._lock:
            before = len(session.photos)
            session.photos = [p for p in session.photos if p.id != photo_id]
            return len(session.photos) != before

    def _assess(
        self, image: np.ndarray, session: EnrolmentSession, source: str
    ) -> StagedPhoto:
        photo_id = uuid.uuid4().hex[:12]

        def reject(note: str, **kw) -> StagedPhoto:
            return StagedPhoto(
                id=photo_id, usable=False, score=0.0, face_pixels=0,
                confidence=0.0, similarity=0.0, yaw=0.0, note=note,
                source=source, **kw,
            )

        # Detect below the recognition floor so we can say "too small" rather
        # than "no face", which sends the operator looking for the wrong problem.
        detections = self.pipeline.detector.detect(image, min_size=1)
        if not detections:
            return reject("No face found. Move closer and face the camera.")

        # Only faces big enough to be the subject count as candidates.
        #
        # Measured on the walk-through clip: dropping the floor to 1px makes
        # YuNet return 61 "faces" on a normal corridor frame — texture, distant
        # heads, noise. Counting those as competing candidates made every single
        # capture fail as ambiguous. A background blob is not a person someone
        # might be trying to enrol; a second face at conversational distance is.
        candidates = [f for f in detections if min(f.w, f.h) >= MIN_FACE_PIXELS]

        if len(candidates) > 1:
            # Enrolling the wrong face here poisons the gallery permanently and
            # silently. Never guess which one is the subject.
            return reject(
                f"{len(candidates)} faces in shot. Only the person being enrolled."
            )

        if not candidates:
            biggest = max(min(f.w, f.h) for f in detections)
            return reject(
                f"Too small ({biggest}px). Needs {MIN_FACE_PIXELS}px — move closer."
            )

        face = candidates[0]
        pixels = min(face.w, face.h)
        if face.confidence < MIN_CONFIDENCE:
            return reject(
                f"Unclear face ({face.confidence:.2f}). Check the light and try again."
            )

        try:
            vector = self.pipeline.embedder.embed(image, face)
        except Exception as exc:
            # A face clipped by the frame edge can fail to align.
            log.debug("could not embed staged photo: %s", exc)
            return reject("Face is cut off at the edge of the shot.")

        similarity = max(
            (float(np.dot(vector, p.vector)) for p in session.usable if p.vector is not None),
            default=0.0,
        )
        yaw, angle = describe_angle(face)

        if similarity > TOO_SIMILAR:
            return reject(
                f"Too similar to a photo you already have ({similarity:.2f}). "
                "Turn your head a little."
            )

        return StagedPhoto(
            id=photo_id,
            usable=True,
            score=quality_score(pixels, face.confidence),
            face_pixels=pixels,
            confidence=round(float(face.confidence), 3),
            similarity=round(similarity, 3),
            yaw=round(yaw, 3),
            note=f"{angle}, {pixels}px",
            vector=vector,
            source=source,
        )

    # -- commit -------------------------------------------------------------

    def commit(self, session_id: str) -> Person:
        """Write the person and their vectors to the gallery.

        Refuses below REQUIRED_PHOTOS rather than enrolling someone the system
        will then fail to recognise. The failure mode of a thin enrolment is
        not "no match" — it is an unreliable match, which is worse, because the
        register looks like it is working.
        """
        session = self.session(session_id)
        if session is None:
            raise KeyError(session_id)

        usable = session.usable
        if len(usable) < REQUIRED_PHOTOS:
            raise ValueError(
                f"{len(usable)} usable photo(s); {REQUIRED_PHOTOS} are required. "
                "Recognition from fewer is unreliable in a way that looks like "
                "it is working."
            )

        person = self.gallery.add_person(
            session.person_id, session.name, session.type,
            session.group, session.detail,
        )
        for photo in usable:
            if photo.vector is None:
                continue
            self.gallery.add_embedding(
                session.person_id, photo.vector, self.pipeline.model_name,
                quality=photo.score / 100.0, source=photo.source,
            )

        self.cancel(session_id)
        log.info(
            "enrolled %s (%s) with %d face(s)",
            session.name, session.person_id, len(usable),
        )
        return self.gallery.person(session.person_id) or person
