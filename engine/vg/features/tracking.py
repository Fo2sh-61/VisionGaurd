"""The track-a-person worker.

Detect once, track, identify by appearance, store. This is the feature that
answers "where did this person go", and it is assembled entirely from layers
that already exist:

    person boxes (shared)  ->  ByteTrack  ->  appearance stitching  ->  rows

**It shares the person detector and never runs its own.** §3.4's first rule.
Counting, intrusion and this all consume the same YOLO pass.

**It never names anybody itself.** Names arrive from the recognition worker via
`note_face`, because only a face can say *which* person this is. Clothing can
only say *the same body as before*. A worker that guessed names from appearance
would be the single most damaging bug in this system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vg.features.base import FeatureWorker
from vg.ingest.source import Frame

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackingResult:
    """One frame's worth of identified bodies."""

    sightings: tuple = ()
    tracks: int = 0

    @property
    def named(self) -> int:
        return sum(1 for s in self.sightings if s.named)


class TrackingWorker(FeatureWorker[TrackingResult]):
    """Person tracking and appearance identity, per camera."""

    def __init__(self, bus, detector, tracker_pool, appearance, store,
                 cameras: list[str], rate_hz: float = 2.0, boost_hz: float = 12.0
                 ) -> None:
        super().__init__("tracking", bus, cameras, rate_hz, boost_hz)
        self.detector = detector
        self.pool = tracker_pool
        self.appearance = appearance
        self.store = store
        self.rows_written = 0

    def analyse(self, frame: Frame) -> TrackingResult:
        boxes = self.detector.raw_boxes(frame.image)

        # The tracker is called on EVERY analysed frame, including empty ones.
        # That is how lost tracks age out; skipping empties would let a track
        # survive an arbitrary absence and hand its ID to the next person in.
        tracks = self.pool.for_camera(frame.camera_id).update(boxes, frame.image)

        sightings = self.appearance.observe(
            frame.camera_id, frame.image, tracks, frame.captured_at
        )
        if sightings:
            self.rows_written += self.store.record_many(sightings)

        return TrackingResult(sightings=tuple(sightings), tracks=len(tracks))

    # -- naming, driven by the recognition worker ---------------------------

    def note_face(self, camera_id: str, face_box, person_id: str, score: float,
                  at=None) -> str | None:
        """Recognition matched a face; attach that name to the body wearing it.

        Also backfills the rows already written for that body. Recognition
        lands a few frames after the body first appears, and a path that starts
        at the moment of the face match is missing its beginning — which is
        usually the part being asked about.
        """
        payload = self.payload(camera_id)
        if payload is None or not payload.sightings:
            return None

        stable_id = self.appearance.bind_face(
            payload.sightings, face_box, person_id, score, at
        )
        if stable_id is None:
            return None

        on = self.store.local_date(at or payload.sightings[0].at)
        backfilled = self.store.name_identity(stable_id, person_id, on)
        if backfilled:
            log.debug("named %d earlier row(s) for %s", backfilled, person_id)
        return stable_id

    def correct(self, stable_id: str) -> str | None:
        """Operator says the name on this body is wrong.

        The rows stay — a body really was there. Only the claim about who it
        was is withdrawn, and the stitcher issues a fresh identity so the
        mistake does not propagate forward.
        """
        self.store.unname_identity(stable_id)
        return self.appearance.correct(stable_id)

    # -- reads ---------------------------------------------------------------

    def sightings_on(self, camera_id: str):
        payload = self.payload(camera_id)
        return payload.sightings if payload else ()

    @property
    def stats(self) -> dict:
        return {
            **super().stats,
            "rows_written": self.rows_written,
            **self.appearance.stats,
        }
