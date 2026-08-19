"""Face recognition — attendance, and nothing else.

This worker identifies people. It does not count them, does not evaluate zones,
and is not required by any other feature. A camera configured for counting or
intrusion never loads a face model and never runs this code.

That separation is deliberate and was learned the hard way: person detection
used to live inside this class, which meant counting silently depended on
attendance being switched on, and a camera set to `[counting]` alone was
processed by nothing at all.

Detect → align → embed → match, at ~2 Hz idle and up to ~12 Hz on a camera
someone is watching. Runs on its own thread because recognition costs 40-70 ms
a frame; inline it would drag capture down to match.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vg.events.sightings import Sighting, SightingStore
from vg.features.base import FeatureWorker
from vg.identity.gallery import FaceGallery, Person
from vg.infer.faces import FacePipeline
from vg.ingest.source import Frame

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecognisedFace:
    """One face on one frame, identified or not.

    Geometry is already normalised to fractions of the frame, so the API hands
    it to the UI without either end knowing the camera's resolution.
    """

    x: float
    y: float
    w: float
    h: float
    detection_confidence: float
    person: Person | None
    score: float
    reason: str

    @property
    def identified(self) -> bool:
        return self.person is not None

    @property
    def label(self) -> str:
        """What the box says.

        An unidentified face says "Unknown" rather than a name with a low
        percentage: a hedged name still reads as an identification to anyone
        glancing at the screen.
        """
        return self.person.name if self.person else "Unknown"


@dataclass(frozen=True)
class FacesResult:
    faces: tuple[RecognisedFace, ...] = ()

    @property
    def identified(self) -> int:
        return sum(1 for f in self.faces if f.identified)


class RecognitionWorker(FeatureWorker[FacesResult]):
    """Face recognition for attendance."""

    def __init__(
        self,
        bus,
        gallery: FaceGallery,
        sightings: SightingStore,
        pipeline: FacePipeline | None = None,
        cameras: list[str] | None = None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
        tracking=None,
    ) -> None:
        super().__init__("recognition", bus, cameras or [], rate_hz, boost_hz)
        self.gallery = gallery
        self.sightings = sightings
        self.pipeline = pipeline or FacePipeline()
        # Optional. When present, a face match also tells the tracker WHICH
        # person the body it is following is - the only way a name reaches
        # cameras where the face is not visible. Recognition never depends
        # on tracking being switched on.
        self.tracking = tracking

        self.faces_seen = 0
        self.identifications = 0

    def analyse(self, frame: Frame) -> FacesResult:
        faces: list[RecognisedFace] = []

        for observation in self.pipeline.observe(frame.image):
            match = self.gallery.match(observation.embedding, observation.model)
            fx, fy, fw, fh = observation.face.to_fractions(frame.width, frame.height)

            faces.append(RecognisedFace(
                x=fx, y=fy, w=fw, h=fh,
                detection_confidence=observation.face.confidence,
                person=match.person,
                score=match.score,
                reason=match.reason,
            ))

            if match.person is not None:
                self._record(match.person, frame, match.score, match.runner_up)
                self._name_the_body(frame, (fx, fy, fw, fh), match)

        self.faces_seen += len(faces)
        self.identifications += sum(1 for f in faces if f.identified)
        return FacesResult(faces=tuple(faces))

    def _name_the_body(self, frame: Frame, face_box, match) -> None:
        """Tell tracking whose body this face belongs to.

        This is the join between the two halves of identity: a face says *which
        person*, appearance says *the same body*. Binding them here is what
        lets a name follow someone into a corridor where no face is visible.

        Failure is deliberately silent at debug level: tracking is an optional
        feature, and recognition must not degrade because it is off, missing
        the body, or unsure which of two overlapping people the face belongs to.
        """
        if self.tracking is None:
            return
        try:
            self.tracking.note_face(
                frame.camera_id, face_box, match.person.id,
                match.score, frame.captured_at,
            )
        except Exception:
            log.debug("could not bind %s to a body", match.person.id, exc_info=True)


    def _record(
        self, person: Person, frame: Frame, score: float, runner_up: float
    ) -> None:
        sighting = Sighting(
            person_id=person.id,
            camera_id=frame.camera_id,
            seen_at=frame.captured_at,
            confidence=score,
            model=self.pipeline.model_name,
            runner_up=runner_up,
        )
        # The first sighting of the day bypasses the debounce: arrival time is
        # the number attendance depends on, so it is never dropped as noise.
        first_today = not self.sightings.seen_today(person.id, frame.captured_at)
        if self.sightings.record(sighting, force=first_today) and first_today:
            log.info(
                "%s arrived at %s on %s (%.3f)",
                person.name,
                frame.captured_at.isoformat(timespec="seconds"),
                frame.camera_id,
                score,
            )

    # -- reads --------------------------------------------------------------

    def faces_on(self, camera_id: str) -> tuple[RecognisedFace, ...]:
        payload = self.payload(camera_id)
        return payload.faces if payload else ()
