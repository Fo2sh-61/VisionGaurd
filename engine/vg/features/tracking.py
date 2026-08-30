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
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from vg.features.base import FeatureWorker
from vg.infer.tracking import LOST_TRACK_SECONDS
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


# ---------------------------------------------------------------------------
# following one person, live
# ---------------------------------------------------------------------------
#
# The session lives inside this worker and is advanced inside `analyse()`,
# which is already called for every camera on every analysed frame. That is
# the whole reason there is no thread here: the loop that would need to exist
# to notice somebody walking from one camera to another is already running.
#
# It also means the stop conditions are server-side. A timer runs out and a
# track is lost whether or not anybody is looking at the page, so a closed
# browser tab can never leave a recording running.


class NobodyThere(LookupError):
    """Nothing to follow at that point. Retryable — they may have moved."""


class AlreadyFollowing(RuntimeError):
    """A follow is already open. One person at a time, and the reply says who."""

    def __init__(self, session: "FollowSession") -> None:
        self.session = session
        super().__init__(f"already following {session.stable_id}")


class NotFollowing(LookupError):
    """Nothing is being followed."""


class NoRecorder(RuntimeError):
    """This engine has no recorder, so a follow cannot be recorded."""


class AlreadyRecordingFollow(RuntimeError):
    """This follow is already recording."""


class NotRecordingFollow(LookupError):
    """This follow is not recording."""


@dataclass
class TrailHop:
    """A camera the followed person crossed, and when."""

    camera_id: str
    at: datetime


@dataclass
class FollowRecording:
    """The recording riding along with a follow.

    One segment per camera, because that is what a recorder produces and what
    an operator can actually use: a file per place, each playable on its own.
    """

    segments: list = field(default_factory=list)
    timer_deadline: datetime | None = None
    state: str = "recording"  # recording | stopped
    reason: str | None = None

    @property
    def running(self) -> bool:
        return self.state == "recording"


@dataclass
class FollowSession:
    """One operator, following one body, right now."""

    stable_id: str
    started_by: str
    started_at: datetime
    camera_id: str
    last_seen_at: datetime
    trail: list = field(default_factory=list)
    #: Who the face says this body is, as of the most recent frame. A live
    #: annotation and never a stored binding: it is re-read from the sighting
    #: every frame, so it goes when the body does. A name that outlived its
    #: track is what once made every person on a camera read as one name.
    person_id: str | None = None
    recording: FollowRecording | None = None
    ended_reason: str | None = None

    @property
    def ended(self) -> bool:
        return self.ended_reason is not None


def _body_at(sightings, x: float, y: float):
    """The tracked body under a click, in frame fractions.

    Smallest containing box wins, so clicking somebody standing in front of a
    larger box picks the person and not the crowd behind them.
    """
    hits = [
        s for s in sightings
        if s.x <= x <= s.x + s.w and s.y <= y <= s.y + s.h
    ]
    return min(hits, key=lambda s: s.w * s.h) if hits else None


class TrackingWorker(FeatureWorker[TrackingResult]):
    """Person tracking and appearance identity, per camera."""

    def __init__(self, bus, detector, tracker_pool, appearance, store,
                 cameras: list[str], rate_hz: float = 2.0, boost_hz: float = 12.0,
                 recorder=None) -> None:
        super().__init__("tracking", bus, cameras, rate_hz, boost_hz)
        self.detector = detector
        self.pool = tracker_pool
        self.appearance = appearance
        self.store = store
        # Absent means a follow can still be watched, it just cannot be
        # recorded — and it says so rather than offering a button that does
        # nothing.
        self.recorder = recorder
        self.rows_written = 0
        self.follows_started = 0

        # Its own lock, not the base class's: that one guards the results
        # cache and is taken on every frame by every camera thread.
        self._follow_lock = threading.RLock()
        self._follow: FollowSession | None = None
        # camera id -> (frame time, the bodies it showed)
        self._seen: dict[str, tuple[datetime, tuple]] = {}
        self._newest_frame_at: datetime | None = None

    def analyse(self, frame: Frame) -> TrackingResult:
        boxes = self.detector.raw_boxes(frame)

        # The tracker is called on EVERY analysed frame, including empty ones.
        # That is how lost tracks age out; skipping empties would let a track
        # survive an arbitrary absence and hand its ID to the next person in.
        tracks = self.pool.for_camera(frame.camera_id).update(boxes, frame.image)

        sightings = self.appearance.observe(
            frame.camera_id, frame.image, tracks, frame.captured_at
        )
        if sightings:
            self.rows_written += self.store.record_many(sightings)

        self._note_seen(frame.camera_id, frame.captured_at, sightings)
        self._advance_follow(frame.camera_id, frame.captured_at, sightings)

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

    # -- following one person, live -----------------------------------------

    def follow(self, camera_id: str, x: float, y: float, actor: str) -> FollowSession:
        """Start following whichever body is under that point.

        Fractions of the frame, never pixels — the console does not know the
        camera's resolution and must not have to.
        """
        with self._follow_lock:
            if self._follow is not None and not self._follow.ended:
                raise AlreadyFollowing(self._follow)

            seen = self._seen.get(camera_id)
            if seen is None or self._is_stale(seen[0]):
                raise NobodyThere(
                    f"{camera_id} has not reported any bodies recently, so "
                    f"there is nothing there to follow."
                )

            at, sightings = seen
            body = _body_at(sightings, x, y)
            if body is None:
                raise NobodyThere(
                    "Nobody there to follow. They may have moved — try again "
                    "on the body itself."
                )

            self._follow = FollowSession(
                stable_id=body.stable_id,
                started_by=actor,
                started_at=at,
                camera_id=camera_id,
                last_seen_at=at,
                trail=[TrailHop(camera_id=camera_id, at=at)],
                person_id=body.person_id,
            )
            self.follows_started += 1

        # Outside the lock: the boost is the base class's, with its own.
        self.note_interest(camera_id)
        return self._follow

    def follow_view(self) -> FollowSession | None:
        """The session as it stands. Reads only — time is advanced by frames."""
        with self._follow_lock:
            return self._follow

    def end_follow(self, reason: str = "manual") -> FollowSession | None:
        with self._follow_lock:
            session = self._follow
            if session is None or session.ended:
                return session
            self._end(session, reason)
            return session

    def record(self, timer_seconds: float | None, actor: str) -> FollowSession:
        """Start recording the followed person, camera by camera."""
        with self._follow_lock:
            session = self._require_follow()
            if self.recorder is None:
                raise NoRecorder(
                    "Recording is not available on this engine, so a follow "
                    "cannot be recorded."
                )
            if session.recording is not None and session.recording.running:
                raise AlreadyRecordingFollow(
                    "This follow is already being recorded."
                )

            deadline = None
            if timer_seconds:
                # Measured from the last frame the session saw, not the wall
                # clock: the session's whole life is told in frame time, and
                # mixing the two would make the timer drift against the
                # track-loss check sitting next to it.
                deadline = session.last_seen_at + timedelta(seconds=timer_seconds)

            session.recording = FollowRecording(timer_deadline=deadline)
            self._start_segment(session, session.camera_id, actor)
            return session

    def stop_record(self, reason: str = "manual", actor: str = "operator") -> FollowSession:
        with self._follow_lock:
            session = self._require_follow()
            if session.recording is None or not session.recording.running:
                raise NotRecordingFollow("This follow is not being recorded.")
            self._stop_recording(session, reason, actor)
            return session

    # -- the session, advanced by frames ------------------------------------

    def _advance_follow(self, camera_id: str, now, sightings) -> None:
        """One frame's worth of session life. Called from `analyse` only."""
        with self._follow_lock:
            session = self._follow
            if session is None or session.ended:
                return

            here = next(
                (s for s in sightings if s.stable_id == session.stable_id), None
            )
            if here is not None:
                session.last_seen_at = now
                # Re-read every frame. Never remembered across a track.
                session.person_id = here.person_id
                if camera_id != session.camera_id:
                    self._hop(session, camera_id, now)

            recording = session.recording
            if (recording is not None and recording.running
                    and recording.timer_deadline is not None
                    and now >= recording.timer_deadline):
                self._stop_recording(session, "timer", session.started_by)

            if (now - session.last_seen_at).total_seconds() > LOST_TRACK_SECONDS:
                # The stable id has aged out. The name goes with it, because
                # the name was only ever an annotation on that id.
                self._end(session, "track lost")

    def _hop(self, session: FollowSession, camera_id: str, now) -> None:
        previous = session.camera_id
        session.camera_id = camera_id
        session.trail.append(TrailHop(camera_id=camera_id, at=now))

        recording = session.recording
        if recording is not None and recording.running:
            # Stop the old camera BEFORE starting the new one. The recorder
            # holds one recording per camera and a second start on a camera
            # already running raises; more to the point, one file per place is
            # what makes the segments usable.
            self._stop_segment(session, previous, "moved on", session.started_by)
            self._start_segment(session, camera_id, session.started_by)

    def _start_segment(self, session: FollowSession, camera_id: str, actor: str) -> None:
        if self.recorder is None:
            return
        try:
            segment = self.recorder.start(camera_id, actor)
        except Exception as exc:
            # A camera that cannot record must not end the follow. The
            # operator is watching a person, not a file.
            log.warning("follow recording could not start on %s: %s", camera_id, exc)
            return
        session.recording.segments.append(segment)

    def _stop_segment(self, session: FollowSession, camera_id: str, reason: str,
                      actor: str) -> None:
        if self.recorder is None:
            return
        try:
            segment = self.recorder.stop(camera_id, actor)
        except Exception:
            log.exception("follow recording could not stop on %s", camera_id)
            return
        if segment is None:
            return
        # Why it ended, on the segment itself. `Recorder.stop` has no opinion
        # about that; the session does.
        segment.reason = reason
        for i, existing in enumerate(session.recording.segments):
            if existing.id == segment.id:
                session.recording.segments[i] = segment
                break
        else:
            session.recording.segments.append(segment)

    def _stop_recording(self, session: FollowSession, reason: str, actor: str) -> None:
        recording = session.recording
        if recording is None or not recording.running:
            return
        self._stop_segment(session, session.camera_id, reason, actor)
        recording.state = "stopped"
        recording.reason = reason

    def _end(self, session: FollowSession, reason: str) -> None:
        if session.recording is not None and session.recording.running:
            self._stop_recording(session, reason, session.started_by)
        session.ended_reason = reason
        # The name goes with the track, always. Nothing carries it forward.
        session.person_id = None

    def _require_follow(self) -> FollowSession:
        session = self._follow
        if session is None or session.ended:
            raise NotFollowing("Nothing is being followed.")
        return session

    # -- what the cameras last showed ---------------------------------------

    def _note_seen(self, camera_id: str, at, sightings) -> None:
        """Remember each camera's last bodies, so a click has something to hit.

        Deliberately not `self.payload()`: that cache is judged stale against
        the wall clock, and everything here is told in frame time so that a
        whole walk across a building is testable in a few lines.
        """
        self._seen[camera_id] = (at, tuple(sightings))
        if self._newest_frame_at is None or at > self._newest_frame_at:
            self._newest_frame_at = at

    def _is_stale(self, at) -> bool:
        newest = self._newest_frame_at
        if newest is None:
            return True
        return (newest - at).total_seconds() > self.RESULT_TTL_SECONDS

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
            "follows_started": self.follows_started,
            **self.appearance.stats,
        }
