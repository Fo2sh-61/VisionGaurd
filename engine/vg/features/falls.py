"""Falls: somebody goes down and stays down, on any camera checked for it.

The model (`infer/falls.py`, the owner's learned temporal model) decides that
a person fell. This file decides what that means on the site, in the owner's
words from the Falls page design:

    "Someone who goes down and stays down shows here at once, with the camera
     on them."
    "Down shorter than ten seconds is listed as 'got up' and never raises an
     alert."
    "The entry closes by itself when they get up or leave the camera."

So, per person the model says fell:

    fell          --model decides-->       an entry opens, a video starts
    down          --DOWN_SECONDS-->        alerted: the Falls page shows it
    down          --upright GOT_UP_S-->    closed "got_up"
    down          --not seen LOST_S-->     closed "left_view"

**Time comes from `frame.captured_at`, never `time.monotonic()`**, for the
reason `features/weapons.py` gives: the rules then mean the same thing on a
live camera and a recorded clip, and a test can prove a ten-second rule in
microseconds.

**The person, not the id.** ByteTrack renames people, the owner's linker joins
the renames up for a second, and a pose model loses people most of all once
they are lying on the floor. An entry therefore follows the *place* as well as
the number: when the person it was opened for is not in the frame, somebody
who is not upright, in the same spot, is taken to be them. Losing a person on
the floor for a few frames must not close the entry and then — because the
model only raises a fall for somebody it saw upright first — never open
another one while they lie there.

There is no threading in this file. `FeatureWorker` owns it, and the models
own their own locks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from vg.events.falls import FallSceneStore
from vg.features.base import FeatureWorker
from vg.infer.falls import FallAlert, FallingPerson, FallReading
from vg.ingest.recorder import AlreadyRecording
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

#: How long somebody has to stay down before it counts. From the owner's
#: design: "A person counts as down after 10 seconds without getting up", and
#: "Down shorter than 10 seconds is listed as 'got up' and never raises an
#: alert." Long enough that a child who trips and bounces straight up is not
#: an alert; short enough that somebody who does not get up is on the screen
#: well inside a minute.
DOWN_SECONDS = 10.0

#: Upright this long, without a break, and the person has got up. The model's
#: own rule for the same thing — its `rearm_s`, one second of standing before
#: it will consider a second fall by the same person.
GOT_UP_SECONDS = 1.0

#: Not seen for this long and the person has left the camera. Generous on
#: purpose: a pose model loses somebody lying on the floor far more often than
#: it loses somebody standing, and closing too early is the worse mistake —
#: see the module note.
LOST_SECONDS = 5.0

#: How close another person must be to an entry's last box to be taken for the
#: person it was opened for: their box centres within this many lengths of
#: the larger box's longer side. A body on the floor does not move far.
SAME_PLACE = 0.6

#: A video of a fall stops by itself after this long, whether or not the
#: person is still down. Two minutes shows how it started and whether anybody
#: came; the entry itself stays open, and keeps counting, for as long as they
#: are down.
MAX_CLIP_SECONDS = 120.0

#: Who the recorder logs as having asked. Never a person's name.
ACTOR = "fall-detection"

BUSY_REASON = "No clip: this camera was already recording another fall."


@dataclass
class DownState:
    """One person down on one camera. Lost on restart, and closed on the next."""

    scene_id: str
    person_id: int
    started_at: datetime
    last_seen_at: datetime
    box: tuple[float, float, float, float]
    peak: float = 0.0
    alerted: bool = False
    upright_since: datetime | None = None
    recording: bool = False


@dataclass(frozen=True)
class DownBox:
    """What the overlay draws for one person down: where, and for how long."""

    x: float
    y: float
    w: float
    h: float
    seconds: float
    alerted: bool
    confidence: float


@dataclass(frozen=True)
class FallsResult:
    """What this worker saw on one frame."""

    people: int = 0
    down: tuple[str, ...] = ()       # the entries running on this camera


class FallsWorker(FeatureWorker[FallsResult]):
    """Watches for somebody who goes down and stays down."""

    def __init__(
        self,
        bus,
        detector,
        cameras: list[str],
        scenes: FallSceneStore,
        recorder=None,
        retention_days: int | None = None,
        down_seconds: float = DOWN_SECONDS,
        rate_hz: float = 5.0,
        boost_hz: float = 12.0,
    ) -> None:
        super().__init__("falls", bus, cameras, rate_hz, boost_hz)
        # One `FallDetector` for every camera thread. Its per-camera state is
        # inside it, keyed by camera id; its models carry their own locks.
        self.detector = detector
        self.device = getattr(detector, "device", None)
        self.scenes = scenes
        self.recorder = recorder
        self.retention_days = retention_days
        self.down_seconds = float(down_seconds)
        # camera id -> scene id -> the person down.
        self._live: dict[str, dict[str, DownState]] = {}
        # camera id -> the last frame time analysed. The overlay's clock.
        self._last_frame_at: dict[str, datetime] = {}

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> FallsResult:
        camera_id = frame.camera_id
        now = frame.captured_at
        self._last_frame_at[camera_id] = now
        reading = self.detector.observe(
            camera_id, frame.image, now, self.rate_for(camera_id))
        return self.apply(camera_id, now, reading)

    def apply(self, camera_id: str, now: datetime, reading: FallReading) -> FallsResult:
        """What one reading of the model means for this camera's entries.

        Public so a test can drive the rules with readings of its own, with
        no model and no camera.
        """
        self._last_frame_at[camera_id] = now
        live = self._live.setdefault(camera_id, {})

        # Who is in this frame, and which of them already belongs to an entry.
        here = {p.person_id: p for p in reading.people}
        owned = {s.person_id for s in live.values()}

        for alert in reading.alerts:
            if alert.person_id in owned:
                continue
            # The model raised a fall for an id an entry already follows under
            # another number - the linker lost them and ByteTrack renamed them.
            # Same person, same fall: the entry adopts the new number.
            twin = self._entry_near(live, _box(alert))
            if twin is not None:
                twin.person_id = alert.person_id
                owned.add(alert.person_id)
                continue
            self._open(camera_id, alert, now)
            owned.add(alert.person_id)

        for state in list(live.values()):
            person = here.get(state.person_id)
            if person is None:
                person = self._stand_in(state, here, owned)
                if person is not None:
                    owned.discard(state.person_id)
                    state.person_id = person.person_id
                    owned.add(person.person_id)
            if person is not None:
                self._seen(state, person, now)
            self._decide(camera_id, state, now)

        return FallsResult(
            people=len(here),
            down=tuple(s.scene_id for s in self._live.get(camera_id, {}).values()),
        )

    def _seen(self, state: DownState, person: FallingPerson, now: datetime) -> None:
        state.last_seen_at = now
        box = (person.x, person.y, person.w, person.h)
        if person.state == "normal":
            if state.upright_since is None:
                state.upright_since = now
            return
        # Anything but upright - fallen, falling, or a pose too hidden to
        # judge - is still down. Only standing ends a fall.
        state.upright_since = None
        if box != state.box:
            state.box = box
            self.scenes.note_box(state.scene_id, box)
        if person.state == "fallen" and person.confidence > state.peak:
            state.peak = person.confidence
            self.scenes.note_confidence(state.scene_id, person.confidence)

    def _decide(self, camera_id: str, state: DownState, now: datetime) -> None:
        if (state.upright_since is not None
                and (now - state.upright_since).total_seconds() >= GOT_UP_SECONDS):
            # Ended when they stood, not when it was certain they had.
            self._close(camera_id, state.scene_id, state.upright_since, "got_up")
            return
        if (now - state.last_seen_at).total_seconds() >= LOST_SECONDS:
            self._close(camera_id, state.scene_id, state.last_seen_at, "left_view")
            return
        if (not state.alerted and state.upright_since is None
                and (now - state.started_at).total_seconds() >= self.down_seconds):
            # Stamped at the moment the rule was met, not at this frame.
            at = state.started_at + timedelta(seconds=self.down_seconds)
            self.scenes.alert(state.scene_id, min(at, now))
            # Set whether or not this call wrote it: the row allows one alert,
            # and asking again every frame would change nothing but the log.
            state.alerted = True
            log.info("fall %s on %s: still down after %.0f s",
                     state.scene_id[:8], camera_id, self.down_seconds)

    def _entry_near(self, live: dict[str, DownState], box) -> DownState | None:
        best, best_d = None, SAME_PLACE
        for state in live.values():
            d = _distance(state.box, box)
            if d <= best_d:
                best, best_d = state, d
        return best

    def _stand_in(self, state: DownState, here: dict[int, FallingPerson],
                  owned: set[int]) -> FallingPerson | None:
        """Somebody not upright, where this entry's person was, nobody else's."""
        best, best_d = None, SAME_PLACE
        for person in here.values():
            if person.person_id in owned or person.state == "normal":
                continue
            d = _distance(state.box, (person.x, person.y, person.w, person.h))
            if d <= best_d:
                best, best_d = person, d
        return best

    # -- opening and closing ------------------------------------------------

    def _open(self, camera_id: str, alert: FallAlert, now: datetime) -> str:
        box = _box(alert)
        scene_id = self.scenes.open(
            camera_id,
            started_at=alert.fell_at,
            detected_at=alert.at,
            confidence=alert.confidence,
            model_version=getattr(self.detector, "version", ""),
            box=box,
        )
        state = DownState(
            scene_id=scene_id,
            person_id=alert.person_id,
            started_at=alert.fell_at,
            last_seen_at=now,
            box=box,
            peak=alert.confidence,
        )
        self._live.setdefault(camera_id, {})[scene_id] = state
        state.recording = self._start_recording(camera_id, scene_id)
        log.info("fall %s opened on %s", scene_id[:8], camera_id)
        return scene_id

    def _close(self, camera_id: str, scene_id: str, at: datetime, reason: str) -> None:
        state = self._live.get(camera_id, {}).pop(scene_id, None)
        if state is None:
            return
        self.scenes.close(scene_id, at, reason)
        if state.recording:
            self._stop_recording(camera_id, scene_id)
        log.info("fall %s closed on %s (%s)", scene_id[:8], camera_id, reason)

    def _closing(self, camera_id: str) -> None:
        """This camera is leaving the worker. Close its entries, on its thread."""
        now = datetime.now(timezone.utc)
        for scene_id in list(self._live.get(camera_id, {})):
            self._close(camera_id, scene_id, now, "switched_off")
        self._live.pop(camera_id, None)
        self._last_frame_at.pop(camera_id, None)
        forget = getattr(self.detector, "forget", None)
        if forget is not None:
            forget(camera_id)
        super()._closing(camera_id)

    def close_all(self, reason: str = "shutdown") -> None:
        """Close every running entry. Call only when no worker thread is live.

        Nobody may be left showing as on the floor when the engine stops.
        """
        now = datetime.now(timezone.utc)
        for camera_id in list(self._live):
            for scene_id in list(self._live[camera_id]):
                self._close(camera_id, scene_id, now, reason)

    def stop(self) -> None:
        # Threads first, then the entries — the order `WeaponsWorker` gives.
        super().stop()
        self.close_all("shutdown")

    # -- recording ----------------------------------------------------------

    def _start_recording(self, camera_id: str, scene_id: str) -> bool:
        """Begin a clip. Every failure is a reason on the entry, never raised."""
        if self.recorder is None:
            self.scenes.fail_clip(
                scene_id, "No clip: recording is not running on this engine.")
            return False
        try:
            self.recorder.start(camera_id, actor=ACTOR)
        except AlreadyRecording:
            self.scenes.fail_clip(scene_id, BUSY_REASON)
            return False
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("could not start recording %s", camera_id)
            self.scenes.fail_clip(
                scene_id, f"No clip: recording failed to start ({exc}).")
            return False
        self.scenes.start_clip(scene_id)
        return True

    def _stop_recording(self, camera_id: str, scene_id: str) -> None:
        try:
            recording = self.recorder.stop(camera_id, actor=ACTOR)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("could not stop recording %s", camera_id)
            self.scenes.fail_clip(scene_id, f"No clip: recording failed ({exc}).")
            return
        if recording is None:
            self.scenes.fail_clip(
                scene_id, "No clip: the recording had already stopped.")
            return
        if recording.state != "saved" or recording.path is None:
            self.scenes.fail_clip(
                scene_id, recording.reason or "No clip: nothing was written to disk.")
            return
        self.scenes.attach_clip(scene_id, recording.path)
        self._expire_old_clips()

    def _expire_old_clips(self) -> None:
        """Drop videos past their retention whenever a new one saves."""
        if not self.retention_days:
            return
        try:
            self.scenes.expire(
                datetime.now(timezone.utc) - timedelta(days=self.retention_days))
        except Exception:  # noqa: BLE001 - reported, never raised
            log.exception("could not expire old fall clips")

    # -- reads --------------------------------------------------------------

    def down_on(self, camera_id: str) -> list[DownBox]:
        """The people to draw as down on this camera right now.

        Measured against the last FRAME time, never the wall clock, so it
        means the same on a live camera and a recorded clip. Whether the
        camera is still delivering frames is the caller's question, as it is
        for knives: `api/live.py` draws nothing for a camera that is offline.
        """
        now = self._last_frame_at.get(camera_id)
        if now is None:
            return []
        # A snapshot: this runs on the API's thread while the camera's own
        # thread opens and closes entries, and walking a dict another thread
        # is resizing raises. `list()` of a dict view is one step under the GIL.
        states = list(self._live.get(camera_id, {}).values())
        return [
            DownBox(
                x=s.box[0], y=s.box[1], w=s.box[2], h=s.box[3],
                seconds=max(0.0, (now - s.started_at).total_seconds()),
                alerted=s.alerted,
                confidence=s.peak,
            )
            for s in states
        ]

    def scenes_on(self, camera_id: str) -> list[str]:
        """The entries running on a camera right now."""
        return list(self._live.get(camera_id, {}))


def _box(alert) -> tuple[float, float, float, float]:
    return (alert.x, alert.y, alert.w, alert.h)


def _distance(a, b) -> float:
    """Centre distance between two fraction boxes, in the larger's longer sides."""
    ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
    scale = max(a[2], a[3], b[2], b[3], 1e-6)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 / scale
