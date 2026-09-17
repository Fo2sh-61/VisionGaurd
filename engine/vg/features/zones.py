"""Restricted zones: who is on a camera nobody should be on.

A camera marked restricted has its **whole frame** restricted. There is no
polygon here and no feet point — every detection is inside by definition, so
`point_in_polygon` in `features/people.py` is irrelevant to this feature and
deliberately not called. It stays there for the polygon zones in engine.yaml.

The entire feature is one small state machine per camera:

    idle      --person seen-->      waiting      remember them; write nothing
    waiting   --still there, 2 s--> recording    open a scene, start recording
    waiting   --nobody, >=5 s-->    idle         forget them; nothing happened
    recording --person seen-->      recording    extend, raise the peak count
    recording --nobody, <5 s-->     recording    a blink; do nothing
    recording --nobody, >=5 s-->    idle         close, reason "nobody"
    recording --2 min elapsed-->    idle         close, reason "limit"
    recording --toggled off-->      idle         close, reason "switched_off"

**The gap rule is wall clock, measured from the last frame that had a person in
it** — not a count of empty frames. Counting frames would make the rule mean
something different on a 2 Hz camera than on a 12 Hz boosted one, so the same
walk would be one entry on a quiet page and three on a watched one.

**A scene is an entry; a run is a message.** Those are two different clocks and
this file owns both. A scene ends after `GAP_SECONDS` of nobody, or at the
two-minute limit — so one visit can be several entries, each with its own clip.
A *run* ends only after `ALERT_AGAIN_AFTER_SECONDS` of the camera being empty,
and every scene inside a run after the first is opened `continues=True`, which
the alert hook reads as "same incident, send nothing". Without that, a detector
that blinks turns one person walking past into one message per blink: on
12 Sep 2026 a single fifty-second visit sent thirty-two emails.

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

#: How long the camera must see nobody before the scene is over. Long enough to
#: ride out a detector losing somebody who is still standing there, short enough
#: that a walk-through ends promptly. P4-FR-006.
#:
#: **Five seconds, set by the owner on 12 Sep 2026 after one walk past a webcam
#: sent thirty-two emails.** It was one second, which at the 5 Hz analysis rate
#: is five frames — and the person detector loses a person for longer than that
#: routinely. One continuous fifty-second visit became sixteen scenes, each
#: ending "nobody" after a dropout of 1.0 to 1.9 seconds, each opening a fresh
#: alert; the three-clips-per-camera cap then replaced thirteen of the sixteen
#: clips it had just recorded. Five seconds covers every dropout that visit
#: produced, with room over.
#:
#: The cost is real and was accepted: the clip now runs five seconds past the
#: last sighting rather than one, and two people four seconds apart read as one
#: visit rather than two.
GAP_SECONDS = 5.0

#: How long somebody must stay in view before a visit is a visit.
#:
#: One frame with a body in it is not somebody entering a restricted area; it is
#: as easily a coat on a chair, or the detector guessing once. Until this much
#: time has passed with them still there, nothing at all is written — no row, no
#: clip, no message — so a candidate that never confirms leaves no trace. This
#: is the rule `features/weapons.py` already runs as `CONFIRM_HITS` and
#: `CONFIRM_SECONDS`; zones had none.
#:
#: The cost is that the recorder starts here rather than at the first sighting,
#: so the first two seconds of an arrival are not on the video. The scene's own
#: `started_at` is still the first sighting, so the entry says when they
#: arrived. Owner's decision, 12 Sep 2026.
CONFIRM_SECONDS = 2.0

#: How long a restricted camera must be EMPTY before somebody on it is news
#: again — the length of a *run*, as opposed to a scene.
#:
#: Spec 013 states the rule this enforces: "a person standing in a restricted
#: room for ten minutes is one message, not five." A scene cut at the two-minute
#: limit, or by a dropout longer than `GAP_SECONDS`, is the same person still
#: standing there. Only the first scene of a run is announced; the rest are
#: opened `continues=True` and send nothing.
#:
#: Scenes are untouched by this: every one is still logged, recorded and listed.
#: It decides who hears about them. Owner's decision, 12 Sep 2026 — a minute
#: clear, and the next arrival is news again.
ALERT_AGAIN_AFTER_SECONDS = 60.0

#: Longest a single scene may run. Somebody standing in a doorway all afternoon
#: is not one clip, and the entry says it was cut rather than looking like they
#: left. Deliberately NOT `recorder.MAX_SECONDS` — the manual record button
#: legitimately wants its ten minutes. P4-FR-009.
MAX_SCENE_SECONDS = 120.0

#: Who the recorder logs as having asked. Never a person's name: pretending an
#: operator pressed record would be a lie in the recording log.
ACTOR = "restricted-zones"

#: What an entry says when the recorder refused because one was already
#: running on that camera. Deliberately does not name an operator: this
#: feature has its own recorder, so the only thing that can be holding it is
#: this feature, and blaming a person for it would be a guess printed as fact.
BUSY_REASON = (
    "No clip: a recording was already running on this camera."
)


@dataclass
class Candidate:
    """Somebody seen, not yet long enough to count as a visit.

    Nothing of a candidate reaches the database. One that never confirms must
    leave no row, no clip and no message behind it, or the log fills with the
    single-frame guesses `CONFIRM_SECONDS` exists to remove.
    """

    first_at: datetime
    last_at: datetime
    peak: int = 1


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
        # The processor: once the shared pass is subtracted, what is left of
        # this worker is scene bookkeeping. Charging that to the detector's
        # device would put Python on the graphics-card budget.
        self.device = "cpu"
        self.scenes = scenes
        # Absent means scenes are still logged, with an honest reason for the
        # missing clip rather than a button that does nothing.
        self.recorder = recorder
        self._restricted: set[str] = set(restricted or ())
        # camera id -> somebody seen, not yet long enough to be a visit.
        self._candidates: dict[str, Candidate] = {}
        # camera id -> the scene running on it right now.
        self._live: dict[str, SceneState] = {}
        # camera id -> the last frame that had anybody on it, ACROSS scenes.
        # A scene's own `last_person_at` dies with the scene; this outlives it,
        # and is the only thing that can say whether the camera has been clear
        # long enough for the next arrival to be a new incident.
        self._last_person_at: dict[str, datetime] = {}
        # Cameras whose current run has already been handed to the alert hook.
        self._announced: set[str] = set()

    # -- the toggle ---------------------------------------------------------

    def set_restricted(self, ids: set[str]) -> None:
        """Which cameras are restricted, from the database.

        One assignment, and nothing else. A camera just switched off has its
        scene closed by **its own thread**, on its next frame, at the top of
        `analyse` — which is why there is not a lock in this file.

        Closing it here instead is what it looked like it should do, and it was
        wrong: this runs on the API thread while the camera's worker thread may
        be part-way through `analyse`, holding a scene it is about to write to.
        Closing underneath it made that thread open a *second* scene on the next
        line, and the second scene's clip then replaced the first one's — so
        switching a camera off destroyed the recording of the very scene that
        was running. The page showed "clip no longer kept" on an entry seconds
        old.

        The cost is that the scene closes on the next frame rather than this
        instant — under a second. The page is right immediately either way: it
        reads the toggle from the database, not from here.
        """
        self._restricted = set(ids)

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
            self._forget(camera_id)
            return ZonesResult(restricted=False)

        now = frame.captured_at
        people = len(self.detector.detect(frame))
        # Before the state machine, because it spans scenes: this is what
        # decides whether the next arrival is a new incident or the same one.
        # It runs on every frame and not only on empty ones, and it runs
        # BEFORE the mark is moved: a camera that went dark delivers no empty
        # frames at all, and if the run could only end on those, the first
        # person after an outage would be taken for the last one before it and
        # nobody would be told.
        self._end_run(camera_id, now)
        if people:
            self._last_person_at[camera_id] = now
        state = self._live.get(camera_id)

        if state is None:
            if people == 0:
                return ZonesResult(restricted=True)
            return ZonesResult(
                restricted=True, people=people,
                # None while they have not stayed long enough to be a visit.
                scene_id=self._note_candidate(camera_id, now, people),
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
                # Same visit, still going: a new scene, not a new alert — and
                # `_open` works that out from the run rather than being told,
                # because "still going" is only true while the frames kept
                # coming. A camera dark for two hours reaches this line too.
                scene_id=self._open(camera_id, now, people, at=now),
            )

        return ZonesResult(restricted=True, people=people, scene_id=state.scene_id)

    # -- opening and closing ------------------------------------------------

    def _note_candidate(self, camera_id: str, now: datetime,
                        people: int) -> str | None:
        """Remember somebody seen, and open a scene once they have stayed.

        Returns the new scene's id, or None while this is still a candidate.
        A candidate whose last sighting is older than `GAP_SECONDS` is not the
        same person coming back — it is a fresh arrival, and the wait starts
        again.
        """
        candidate = self._candidates.get(camera_id)
        if candidate is None or (
                (now - candidate.last_at).total_seconds() >= GAP_SECONDS):
            self._candidates[camera_id] = Candidate(
                first_at=now, last_at=now, peak=people)
            return None

        candidate.last_at = now
        candidate.peak = max(candidate.peak, people)
        if (now - candidate.first_at).total_seconds() < CONFIRM_SECONDS:
            return None

        started_at, peak = candidate.first_at, candidate.peak
        del self._candidates[camera_id]
        # The entry starts at the FIRST sighting — it must say when they
        # arrived, even though the recorder can only start here — but the gap
        # is measured from THIS frame, which is the last one that saw them.
        # Starting the gap at the arrival would spend the wait as if nobody
        # had been seen since, and close the scene `CONFIRM_SECONDS` early.
        return self._open(camera_id, started_at, peak, at=now)

    def _end_run(self, camera_id: str, now: datetime) -> None:
        """A camera clear this long ends the run: the next arrival is news.

        Called on every frame, before the mark is moved. The mark is dropped
        with the run, so an empty corridor costs one dictionary lookup a frame
        and nothing else.
        """
        last = self._last_person_at.get(camera_id)
        if last is None:
            return
        if (now - last).total_seconds() >= ALERT_AGAIN_AFTER_SECONDS:
            del self._last_person_at[camera_id]
            self._announced.discard(camera_id)

    def _forget(self, camera_id: str) -> None:
        """Drop everything remembered about a camera outside its scene.

        Switching a camera off and on again, or taking it off the roster, ends
        the run: the next person on it is news, not a continuation of whatever
        was happening before somebody touched the switch.
        """
        self._candidates.pop(camera_id, None)
        self._last_person_at.pop(camera_id, None)
        self._announced.discard(camera_id)

    def _open(self, camera_id: str, started_at: datetime, people: int,
              at: datetime | None = None) -> str:
        # `started_at` is when they arrived and `at` when they were last seen.
        # They differ by the confirming wait, and only the second may time the
        # gap. See `_note_candidate`.
        #
        # Whether this is news is never passed in: it is the run that decides,
        # in one place. Still inside a run — the camera has not been clear for
        # `ALERT_AGAIN_AFTER_SECONDS` — means a new entry and not a new alert,
        # and the alert hook reads `continues` and sends nothing.
        continues = camera_id in self._announced
        scene_id = self.scenes.open(camera_id, started_at, continues=continues)
        self._announced.add(camera_id)
        if people > 1:
            self.scenes.note_people(scene_id, people)
        state = SceneState(
            scene_id=scene_id, started_at=started_at,
            last_person_at=at or started_at, peak=people,
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

    def _closing(self, camera_id: str) -> None:
        """This camera is leaving the worker. Close its scene, on its thread.

        Runs on the camera's own thread from `FeatureWorker._run`, which is
        the entire reason `unwatch` does not do this itself - see the note on
        `set_restricted` above, and the recording it once destroyed.
        """
        self._close(camera_id, datetime.now(timezone.utc), "switched_off")
        self._forget(camera_id)
        super()._closing(camera_id)

    def close_all(self, reason: str = "shutdown") -> None:
        """Close every running scene. Call only when no worker thread is live.

        No scene may be left showing as still running, or the page reports
        somebody standing in a restricted area who left when the engine did.
        """
        for camera_id in list(self._live):
            self._close(camera_id, datetime.now(timezone.utc), reason)
        for camera_id in list(self._candidates) + list(self._announced):
            self._forget(camera_id)

    def stop(self) -> None:
        # Threads first, then the scenes. The other order would close a scene
        # underneath the thread still writing to it — the same race that
        # `set_restricted` documents above. Once `super().stop()` returns, the
        # camera threads are joined and this is the only one left.
        super().stop()
        self.close_all("shutdown")

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
