"""Restricted zones: who is on a camera nobody should be on.

A camera marked restricted has its **whole frame** restricted. There is no
polygon here and no feet point — every detection is inside by definition, so
`point_in_polygon` in `features/people.py` is irrelevant to this feature and
deliberately not called. It stays there for the polygon zones in engine.yaml.

The entire feature is one small state machine per camera:

    idle      --person seen-->      recording    open a scene, start recording
    recording --person seen-->      recording    extend, raise the peak count
    recording --nobody, <1 s-->     recording    a blink; do nothing
    recording --nobody, >=1 s-->    idle         close, reason "nobody"
    recording --2 min elapsed-->    idle         close, reason "limit"
    recording --toggled off-->      idle         close, reason "switched_off"

**The one-second rule is wall clock, measured from the last frame that had a
person in it** — not a count of empty frames. Counting frames would make the
rule mean something different on a 2 Hz camera than on a 12 Hz boosted one, so
the same walk would be one entry on a quiet page and three on a watched one.

**Time comes from `frame.captured_at`, never `time.monotonic()`.** The gap then
matches the video rather than however long the machine was busy, and a test can
prove a two-minute limit in microseconds by choosing its own timestamps.

**A camera that is not restricted returns before any detection call.** Not
after — before. Switching this feature on must cost nothing at all on the
cameras nobody restricted, or a site with 208 cameras pays for 208 detection
passes to watch two.

There is no threading in this file. `FeatureWorker` owns it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from vg.events.zones import SceneStore
from vg.features.base import FeatureWorker
from vg.infer.shared import SharedDetection
from vg.ingest.recorder import AlreadyRecording
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

#: How long the camera must see nobody before the scene is over. Short enough
#: that a walk-through ends promptly, long enough to ride out a detector losing
#: somebody who turned around. P4-FR-006.
GAP_SECONDS = 1.0

#: Longest a single scene may run. Somebody standing in a doorway all afternoon
#: is not one clip, and the entry says it was cut rather than looking like they
#: left. Deliberately NOT `recorder.MAX_SECONDS` — the manual record button
#: legitimately wants its ten minutes. P4-FR-009.
MAX_SCENE_SECONDS = 120.0

#: Who the recorder logs as having asked. Never a person's name: pretending an
#: operator pressed record would be a lie in the recording log.
ACTOR = "restricted-zones"

#: What an entry says when the operator was already recording that camera by
#: hand. The scene is still logged; the clip belongs to them.
BUSY_REASON = (
    "No clip: an operator was already recording this camera by hand."
)


@dataclass
class SceneState:
    """One camera's in-flight scene. Lost on restart, and closed on the next."""

    scene_id: str
    started_at: datetime
    last_person_at: datetime
    peak: int = 1
    recording: bool = False


@dataclass(frozen=True)
class ZonesResult:
    """What this worker saw on one frame.

    Serves the same purpose as `PeopleResult`: the API can ask what the last
    frame said without reaching into the state machine. `people` is this
    frame's count, `scene_id` is the scene it belongs to, if any.
    """

    restricted: bool = False
    people: int = 0
    scene_id: str | None = None


class ZonesWorker(FeatureWorker[ZonesResult]):
    """Watches restricted cameras and logs each visit as one scene."""

    def __init__(
        self,
        bus,
        detector: SharedDetection,
        cameras: list[str],
        scenes: SceneStore,
        recorder=None,
        restricted: set[str] | None = None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
    ) -> None:
        super().__init__("zones", bus, cameras, rate_hz, boost_hz)
        # The SAME SharedDetection the people worker holds, never a second
        # detector. It caches on (camera_id, frame.sequence), so when both
        # workers land on one frame the model runs once. P1-01 exists to stop
        # a second pass and this is where it would otherwise appear.
        self.detector = detector
        self.scenes = scenes
        # Absent means scenes are still logged, with an honest reason for the
        # missing clip rather than a button that does nothing.
        self.recorder = recorder
        self._restricted: set[str] = set(restricted or ())
        # camera id -> the scene running on it right now.
        self._live: dict[str, SceneState] = {}

    # -- the toggle ---------------------------------------------------------

    def set_restricted(self, ids: set[str]) -> None:
        """Which cameras are restricted, from the database. Takes effect now.

        A camera just switched off has its live scene closed and whatever was
        recorded saved — a scene that stayed open would show somebody standing
        in an area that is no longer restricted.
        """
        switched_off = set(self._live) - set(ids)
        self._restricted = set(ids)
        for camera_id in switched_off:
            self._close(camera_id, datetime.now(timezone.utc), "switched_off")

    def restricted(self) -> set[str]:
        return set(self._restricted)

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> ZonesResult:
        camera_id = frame.camera_id

        if camera_id not in self._restricted:
            # BEFORE any detection call. A camera nobody switched on costs
            # this feature nothing.
            if camera_id in self._live:
                self._close(camera_id, frame.captured_at, "switched_off")
            return ZonesResult(restricted=False)

        now = frame.captured_at
        people = len(self.detector.detect(frame))
        state = self._live.get(camera_id)

        if state is None:
            if people == 0:
                return ZonesResult(restricted=True)
            return ZonesResult(
                restricted=True, people=people,
                scene_id=self._open(camera_id, now, people),
            )

        if people == 0:
            # A blink, or the end. Measured from the last frame that actually
            # had somebody in it, so the answer does not depend on frame rate.
            if (now - state.last_person_at).total_seconds() >= GAP_SECONDS:
                self._close(camera_id, now, "nobody")
                return ZonesResult(restricted=True)
            return ZonesResult(restricted=True, scene_id=state.scene_id)

        state.last_person_at = now
        if people > state.peak:
            state.peak = people
            self.scenes.note_people(state.scene_id, people)

        if (now - state.started_at).total_seconds() >= MAX_SCENE_SECONDS:
            # Cut, but not blind: they are still standing there, so the next
            # scene opens on this same frame.
            self._close(camera_id, now, "limit")
            return ZonesResult(
                restricted=True, people=people,
                scene_id=self._open(camera_id, now, people),
            )

        return ZonesResult(restricted=True, people=people, scene_id=state.scene_id)

    # -- opening and closing ------------------------------------------------

    def _open(self, camera_id: str, at: datetime, people: int) -> str:
        scene_id = self.scenes.open(camera_id, at)
        if people > 1:
            self.scenes.note_people(scene_id, people)
        state = SceneState(
            scene_id=scene_id, started_at=at, last_person_at=at, peak=people,
        )
        self._live[camera_id] = state
        state.recording = self._start_recording(camera_id, scene_id)
        log.info("scene %s opened on %s", scene_id[:8], camera_id)
        return scene_id

    def _close(self, camera_id: str, at: datetime, reason: str) -> None:
        state = self._live.pop(camera_id, None)
        if state is None:
            return
        self.scenes.close(state.scene_id, at, reason)
        if state.recording:
            self._stop_recording(camera_id, state.scene_id)
        log.info("scene %s closed on %s (%s)", state.scene_id[:8], camera_id, reason)

    def close_all(self, reason: str = "shutdown") -> None:
        """Shut down cleanly: no scene may be left showing as still running."""
        for camera_id in list(self._live):
            self._close(camera_id, datetime.now(timezone.utc), reason)

    def stop(self) -> None:
        # Before the threads go, so the last frame's scene is closed and its
        # file released rather than left as an unplayable mp4.
        self.close_all("shutdown")
        super().stop()

    # -- recording ----------------------------------------------------------

    def _start_recording(self, camera_id: str, scene_id: str) -> bool:
        """Begin a clip. Returns whether one is actually being written.

        Every failure here is recorded as a reason on the scene rather than
        raised: a scene that happened is worth logging even when no video of
        it exists, and a "saved" entry with no file is the fake save rule 4
        forbids.
        """
        if self.recorder is None:
            self.scenes.fail_clip(
                scene_id, "No clip: recording is not running on this engine.")
            return False
        try:
            self.recorder.start(camera_id, actor=ACTOR)
        except AlreadyRecording:
            # Never steal the operator's file.
            self.scenes.fail_clip(scene_id, BUSY_REASON)
            return False
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("could not start recording %s", camera_id)
            self.scenes.fail_clip(scene_id, f"No clip: recording failed to start ({exc}).")
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
                scene_id,
                recording.reason or "No clip: nothing was written to disk.")
            return
        self.scenes.attach_clip(scene_id, recording.path)

    # -- reads --------------------------------------------------------------

    def scene_on(self, camera_id: str) -> str | None:
        """The running scene for a camera, if somebody is there right now."""
        state = self._live.get(camera_id)
        return state.scene_id if state else None
