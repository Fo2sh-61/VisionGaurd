"""Restricted zones: who is standing where nobody should be.

A zone is a polygon drawn on one camera (`vg/areas.py`). A person is **inside**
when their *feet* are: the bottom-centre of the box, the same point
`features/people.py` uses. A body that merely overlaps the shape from behind or
above does not count. An old whole-camera zone is a full-frame polygon, so every
person is inside it and the behaviour is the old one, as a special case rather
than a second code path.

The entire feature is one small state machine per zone (spec 025 re-keyed it
from camera to zone; nothing else about it changed):

    idle      --person seen-->      waiting      remember them; write nothing
    waiting   --still there, 2 s--> recording    open a scene, start recording
    waiting   --nobody, >=5 s-->    idle         forget them; nothing happened
    recording --person seen-->      recording    extend, raise the peak count
    recording --nobody, <5 s-->     recording    a blink; do nothing
    recording --nobody, >=5 s-->    idle         close, reason "nobody"
    recording --2 min elapsed-->    idle         close, reason "limit"
    recording --paused/deleted-->   idle         close, reason "switched_off"
    recording --hours ended-->      idle         close, reason "hours"

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

**A camera with no zone watching right now returns before any detection
call.** Not after — before. Switching this feature on must cost nothing at all
on the cameras nobody restricted, or a site with 208 cameras pays for 208
detection passes to watch two. Paused, deleted and out-of-hours zones count as
not watching.

**Alert after N seconds.** A zone may be told to alert only once somebody has
stayed N seconds. The scene is opened and logged as always; the alert goes later,
once, if the visit lasts. `_announced` therefore means "an alert was raised in
this run", not "a scene opened": a four-second visit that never alerted must not
silence the next arrival a minute later.

There is no threading in this file. `FeatureWorker` owns it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from vg.areas import Area, watching_at
from vg.config import HoursConfig
from vg.events.zones import SceneStore
from vg.features.base import FeatureWorker
from vg.features.people import feet_point, point_in_polygon
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
#: this feature - another zone's entry on the same camera - and blaming a
#: person for it would be a guess printed as fact. One recorder per camera is
#: the rule: the first zone's entry gets the clip and a second zone entered at
#: the same time gets none, and says so. The clip belongs to the first entry
#: alone and stops when that entry closes, even if the second is still going.
BUSY_REASON = "No clip - the camera was already recording another zone's entry"

#: How long the working hours read from Settings are reused. Only a zone that
#: depends on them asks, and a Settings save still reaches the next frame
#: within this, with no restart. Measured on the frame's own clock.
HOURS_REUSE_SECONDS = 2.0

#: A feet point is nudged this far inside the frame before the polygon test, so
#: somebody standing right at the bottom edge of a whole-frame zone is inside it.
#: Ray casting calls a point exactly on an edge outside.
EDGE_EPSILON = 1e-6


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
    #: The camera this scene was opened on. A zone's camera can be edited, so
    #: the scene must remember its own: the recorder to stop and the thread
    #: allowed to close it both follow this, never the zone's current camera.
    camera_id: str = ""
    peak: int = 1
    recording: bool = False
    #: When this visit began, for the alert timer. A scene cut at the limit
    #: carries the visit's start forward, or a delay longer than two minutes
    #: could never be reached.
    run_since: datetime | None = None
    #: The alert for this visit has not gone yet and is still owed.
    alert_pending: bool = False


@dataclass(frozen=True)
class ZoneReading:
    """What one zone saw on one frame: who was inside, and the scene if any."""

    zone_id: str
    people: int = 0
    scene_id: str | None = None


@dataclass(frozen=True)
class ZonesResult:
    """What this worker saw on one frame.

    Serves the same purpose as `PeopleResult`: the API can ask what the last
    frame said without reaching into the state machine. `restricted` is whether
    any zone was watching, `people` is how many were inside any of them,
    `scene_id` is the first running scene, and `zones` is each zone's own count
    - the page's "in zone now" is built from those, never defaulted.
    """

    restricted: bool = False
    people: int = 0
    scene_id: str | None = None
    zones: tuple[ZoneReading, ...] = ()


class ZonesWorker(FeatureWorker[ZonesResult]):
    """Watches drawn zones and logs each visit as one scene."""

    def __init__(
        self,
        bus,
        detector: SharedDetection,
        cameras: list[str],
        scenes: SceneStore,
        recorder=None,
        areas: Iterable[Area] | None = None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
        clock=None,
        hours: Callable[[], HoursConfig] | None = None,
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
        # The site's clock and working hours, for zones whose watched hours
        # depend on them. Absent: UTC and the default hours.
        self._clock = clock
        self._hours = hours
        self._hours_cache: tuple[datetime, HoursConfig] | None = None
        # camera id -> its areas. Replaced whole by `set_areas`.
        self._areas: dict[str, tuple[Area, ...]] = {}
        self.set_areas(areas or ())
        # area id -> the camera it was last stepped on, so a zone deleted or
        # moved away can be found and closed from its old camera's thread.
        self._owner: dict[str, str] = {}
        # area id -> somebody seen, not yet long enough to be a visit.
        self._candidates: dict[str, Candidate] = {}
        # area id -> the scene running in it right now.
        self._live: dict[str, SceneState] = {}
        # area id -> the last frame that had anybody in it, ACROSS scenes.
        # A scene's own `last_person_at` dies with the scene; this outlives it,
        # and is the only thing that can say whether the zone has been clear
        # long enough for the next arrival to be a new incident.
        self._last_person_at: dict[str, datetime] = {}
        # Zones whose current run has already had its alert raised.
        self._announced: set[str] = set()

    # -- the zones ----------------------------------------------------------

    def set_areas(self, areas: Iterable[Area]) -> None:
        """Which zones exist, from the database.

        One assignment, and nothing else. A zone just paused, deleted or moved
        has its scene closed by **its camera's own thread**, on that camera's
        next frame, at the top of `analyse` - which is why there is not a lock
        in this file.

        Closing it here instead is what it looked like it should do, and it was
        wrong: this runs on the API thread while the camera's worker thread may
        be part-way through `analyse`, holding a scene it is about to write to.
        Closing underneath it made that thread open a *second* scene on the next
        line, and the second scene's clip then replaced the first one's - so
        switching a camera off destroyed the recording of the very scene that
        was running. The page showed "clip no longer kept" on an entry seconds
        old.

        The cost is that the scene closes on the next frame rather than this
        instant - under a second. The page is right immediately either way: it
        reads the zone from the database, not from here.
        """
        grouped: dict[str, list[Area]] = {}
        for area in areas:
            if area.kind == "zone" and not area.deleted:
                grouped.setdefault(area.camera_id, []).append(area)
        self._areas = {cid: tuple(group) for cid, group in grouped.items()}

    def set_hours(self, hours: Callable[[], HoursConfig]) -> None:
        """Where the working hours come from, once the store that owns them
        exists. The worker is built before it, with engine.yaml's seed."""
        self._hours = hours
        self._hours_cache = None

    def restricted(self) -> set[str]:
        """Cameras with at least one zone watching right now."""
        now = datetime.now(timezone.utc)
        return {cid for cid, group in self._areas.items()
                if any(self._watching(a, now) for a in group)}

    def _watching(self, area: Area, now: datetime) -> bool:
        needs_hours = area.hours_mode in ("outside_working", "working")
        local = self._clock.local(now) if self._clock is not None else now
        return watching_at(area, local, self._working_hours(now, needs_hours))

    def _working_hours(self, now: datetime, needed: bool) -> HoursConfig:
        if not needed or self._hours is None:
            return HoursConfig()
        cached = self._hours_cache
        if (cached is not None
                and abs((now - cached[0]).total_seconds()) < HOURS_REUSE_SECONDS):
            return cached[1]
        hours = self._hours()
        self._hours_cache = (now, hours)
        return hours

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> ZonesResult:
        camera_id = frame.camera_id
        now = frame.captured_at
        areas = self._areas.get(camera_id, ())

        self._retire_gone(camera_id, {a.id for a in areas}, now)
        watching: list[Area] = []
        for area in areas:
            if self._watching(area, now):
                watching.append(area)
            else:
                # Paused is somebody's decision; anything else is the hours.
                self._stand_down(
                    area.id, now, "switched_off" if area.paused else "hours")

        if not watching:
            # BEFORE any detection call. A camera nobody is watching costs
            # this feature nothing.
            return ZonesResult(restricted=False)

        feet = [self._feet(p) for p in self.detector.detect(frame)]
        readings: list[ZoneReading] = []
        inside_any: set[int] = set()
        for area in watching:
            self._owner[area.id] = camera_id
            inside = [i for i, (x, y) in enumerate(feet)
                      if point_in_polygon(x, y, area.polygon)]
            inside_any.update(inside)
            readings.append(ZoneReading(
                zone_id=area.id, people=len(inside),
                scene_id=self._step(area, now, len(inside))))
        first = next((r.scene_id for r in readings if r.scene_id), None)
        return ZonesResult(restricted=True, people=len(inside_any),
                           scene_id=first, zones=tuple(readings))

    @staticmethod
    def _feet(person) -> tuple[float, float]:
        x, y = feet_point(person)
        return (min(max(x, EDGE_EPSILON), 1.0 - EDGE_EPSILON),
                min(max(y, EDGE_EPSILON), 1.0 - EDGE_EPSILON))

    def _step(self, area: Area, now: datetime, people: int) -> str | None:
        """One zone, one frame: the unchanged state machine. Returns its scene."""
        zone_id = area.id
        live = self._live.get(zone_id)
        if live is not None and live.camera_id != area.camera_id:
            # The zone was moved to another camera while a scene was running.
            # This is the new camera's thread, so closing here would be wrong
            # for the OLD camera's recorder only if we looked it up by the
            # zone; the scene knows its own camera, so it is stopped there.
            self._stand_down(zone_id, now, "switched_off")
        # Before the state machine, because it spans scenes: this is what
        # decides whether the next arrival is a new incident or the same one.
        # It runs on every frame and not only on empty ones, and it runs
        # BEFORE the mark is moved: a camera that went dark delivers no empty
        # frames at all, and if the run could only end on those, the first
        # person after an outage would be taken for the last one before it and
        # nobody would be told.
        self._end_run(zone_id, now)
        if people:
            self._last_person_at[zone_id] = now
        state = self._live.get(zone_id)

        if state is None:
            if people == 0:
                return None
            # None while they have not stayed long enough to be a visit.
            return self._note_candidate(area, now, people)

        if people == 0:
            # A blink, or the end. Measured from the last frame that actually
            # had somebody in it, so the answer does not depend on frame rate.
            if (now - state.last_person_at).total_seconds() >= GAP_SECONDS:
                self._close(zone_id, now, "nobody")
                return None
            return state.scene_id

        state.last_person_at = now
        if people > state.peak:
            state.peak = people
            self.scenes.note_people(state.scene_id, people)

        self._maybe_alert(area, state, now)

        if (now - state.started_at).total_seconds() >= MAX_SCENE_SECONDS:
            # Cut, but not blind: they are still standing there, so the next
            # scene opens on this same frame.
            self._close(zone_id, now, "limit")
            # Same visit, still going: a new scene, not a new alert - and
            # `_open` works that out from the run rather than being told,
            # because "still going" is only true while the frames kept
            # coming. A camera dark for two hours reaches this line too.
            return self._open(area, now, people, at=now, carry=state)

        return state.scene_id

    def _maybe_alert(self, area: Area, state: SceneState, now: datetime) -> None:
        """Raise the alert once the visit has lasted the zone's delay."""
        if not state.alert_pending:
            return
        delay = area.alert_after_seconds or 0.0
        since = state.run_since or state.started_at
        if (now - since).total_seconds() >= delay:
            state.alert_pending = False
            # Marked even if the hook fails: the entry says it alerted, and the
            # delivery log says what became of it.
            self._announced.add(area.id)
            self.scenes.alert(state.scene_id)

    # -- opening and closing ------------------------------------------------

    def _note_candidate(self, area: Area, now: datetime,
                        people: int) -> str | None:
        """Remember somebody seen, and open a scene once they have stayed.

        Returns the new scene's id, or None while this is still a candidate.
        A candidate whose last sighting is older than `GAP_SECONDS` is not the
        same person coming back - it is a fresh arrival, and the wait starts
        again.
        """
        zone_id = area.id
        candidate = self._candidates.get(zone_id)
        if candidate is None or (
                (now - candidate.last_at).total_seconds() >= GAP_SECONDS):
            self._candidates[zone_id] = Candidate(
                first_at=now, last_at=now, peak=people)
            return None

        candidate.last_at = now
        candidate.peak = max(candidate.peak, people)
        if (now - candidate.first_at).total_seconds() < CONFIRM_SECONDS:
            return None

        started_at, peak = candidate.first_at, candidate.peak
        del self._candidates[zone_id]
        # The entry starts at the FIRST sighting - it must say when they
        # arrived, even though the recorder can only start here - but the gap
        # is measured from THIS frame, which is the last one that saw them.
        # Starting the gap at the arrival would spend the wait as if nobody
        # had been seen since, and close the scene `CONFIRM_SECONDS` early.
        return self._open(area, started_at, peak, at=now)

    def _end_run(self, zone_id: str, now: datetime) -> None:
        """A zone clear this long ends the run: the next arrival is news.

        Called on every frame, before the mark is moved. The mark is dropped
        with the run, so an empty zone costs one dictionary lookup a frame
        and nothing else.
        """
        last = self._last_person_at.get(zone_id)
        if last is None:
            return
        if (now - last).total_seconds() >= ALERT_AGAIN_AFTER_SECONDS:
            del self._last_person_at[zone_id]
            self._announced.discard(zone_id)

    def _forget(self, zone_id: str) -> None:
        """Drop everything remembered about a zone outside its scene.

        Pausing a zone and resuming it, or deleting it, ends the run: the next
        person in it is news, not a continuation of whatever was happening
        before somebody touched the switch.
        """
        self._candidates.pop(zone_id, None)
        self._last_person_at.pop(zone_id, None)
        self._announced.discard(zone_id)

    def _stand_down(self, zone_id: str, at: datetime, reason: str) -> None:
        if zone_id in self._live:
            self._close(zone_id, at, reason)
        self._forget(zone_id)

    def _retire_gone(self, camera_id: str, current: set[str],
                     at: datetime) -> None:
        """Close the scenes of zones this camera no longer has (deleted, moved)."""
        gone = [zid for zid, cid in self._owner.items()
                if cid == camera_id and zid not in current]
        for zone_id in gone:
            self._stand_down(zone_id, at, "switched_off")
            del self._owner[zone_id]

    def _open(self, area: Area, started_at: datetime, people: int,
              at: datetime | None = None,
              carry: SceneState | None = None) -> str:
        # `started_at` is when they arrived and `at` when they were last seen.
        # They differ by the confirming wait, and only the second may time the
        # gap. See `_note_candidate`.
        #
        # Whether this is news is never passed in: it is the run that decides,
        # in one place. Still inside a run - the zone has not been clear
        # for `ALERT_AGAIN_AFTER_SECONDS` - means a new entry and not a new
        # alert, and the alert hook reads `continues` and sends nothing.
        zone_id = area.id
        continues = zone_id in self._announced
        alert_now = (area.alert_after_seconds or 0.0) <= 0
        scene_id = self.scenes.open(
            area.camera_id, started_at, continues=continues,
            zone_id=zone_id, alert_now=alert_now)
        if alert_now:
            self._announced.add(zone_id)
        pending = (not alert_now) and not continues
        state = SceneState(
            scene_id=scene_id, started_at=started_at,
            last_person_at=at or started_at, camera_id=area.camera_id,
            peak=people,
            run_since=(carry.run_since if carry is not None and pending
                       else started_at),
            alert_pending=pending,
        )
        if people > 1:
            self.scenes.note_people(scene_id, people)
        self._live[zone_id] = state
        state.recording = self._start_recording(area.camera_id, scene_id)
        log.info("scene %s opened in %s on %s",
                 scene_id[:8], zone_id, area.camera_id)
        return scene_id

    def _close(self, zone_id: str, at: datetime, reason: str) -> None:
        state = self._live.pop(zone_id, None)
        if state is None:
            return
        self.scenes.close(state.scene_id, at, reason)
        if state.recording:
            self._stop_recording(state.camera_id, state.scene_id)
        log.info("scene %s closed in %s (%s)",
                 state.scene_id[:8], zone_id, reason)

    def _closing(self, camera_id: str) -> None:
        """This camera is leaving the worker. Close its scenes, on its thread.

        Runs on the camera's own thread from `FeatureWorker._run`, which is
        the entire reason `unwatch` does not do this itself - see the note on
        `set_areas` above, and the recording it once destroyed.
        """
        now = datetime.now(timezone.utc)
        for zone_id in [z for z, c in self._owner.items() if c == camera_id]:
            self._stand_down(zone_id, now, "switched_off")
            del self._owner[zone_id]
        super()._closing(camera_id)

    def close_all(self, reason: str = "shutdown") -> None:
        """Close every running scene. Call only when no worker thread is live.

        No scene may be left showing as still running, or the page reports
        somebody standing in a restricted area who left when the engine did.
        """
        for zone_id in list(self._live):
            self._close(zone_id, datetime.now(timezone.utc), reason)
        for zone_id in list(self._candidates) + list(self._announced):
            self._forget(zone_id)

    def stop(self) -> None:
        # Threads first, then the scenes. The other order would close a scene
        # underneath the thread still writing to it - the same race that
        # `set_areas` documents above. Once `super().stop()` returns, the
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
        """A running scene on a camera, if somebody is in any of its zones."""
        for zone_id, state in self._live.items():
            if self._owner.get(zone_id) == camera_id:
                return state.scene_id
        return None

    def scene_in(self, zone_id: str) -> str | None:
        """The running scene in one zone, if somebody is there right now."""
        state = self._live.get(zone_id)
        return state.scene_id if state else None
