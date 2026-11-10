"""Work stations: is somebody at their place, and for how long was it empty.

A station is an area drawn on a camera (`vg/areas.py`) that must stay staffed.
Somebody **counts** when their feet are inside it, the same point zones use. If
the station is assigned to a person, only that person counts, and "that person"
is a yes or no worked out from their face on this one frame.

The machine is one small table per station, run on every frame it is watched,
with every time taken from `frame.captured_at` (never `time.monotonic()`), so a
test chooses its own clock and the answer follows the video:

    (none)  --first frame in hours-->  away      since that frame
    on      --nobody for LEAVE-->      away      since the LAST moment somebody counted
    away    --somebody for RETURN-->   on        since the FIRST moment of the run
    absent  --somebody for RETURN-->   on        since the first moment of the run
    away    --limit minutes elapsed--> absent    since away + limit, exactly; ONE alert
    any     --hours end-->             (none)    closed at the hours end, not carried over
    any     --no frame for STALL-->    (none)    closed at the last frame; the next starts fresh

A gap shorter than `gap_tolerance_seconds` does not break a run of somebody
being there. **A stored time is the first moment of the new situation, not the
moment it was confirmed**: the confirming wait is for being sure, not for
being late.

**Rule 2 - nothing about a person survives a frame.** The face step returns one
boolean out of local variables. The worker holds timers about *somebody
counting*, never who: no person id, no body key, no embedding, no set of
identities. It does not call `RecognitionWorker`, tracking, anchors or
sightings, and does not read what recognition last saw - that would carry a
name forward between frames and would need attendance switched on (rule 9). A
stranger at an assigned station reads as nobody.

**The face step runs only when it has something to decide**: an assigned
station with somebody standing in it. An empty station, or one with no
assignee, costs one `feet_point` test per person.

**Faces too small to read.** The widest face found at an assigned station is
kept for ten minutes, as a number. Under `min_face_px` with at least five
seen, the station says its faces are too small to read and counts anyone,
instead of reading Away for ever. Nothing measured yet means the normal face
check, which is the cautious answer.

There is no threading in this file. `FeatureWorker` owns it.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from vg.areas import Area, parse_hhmm, watching_at
from vg.config import HoursConfig, StationsConfig
from vg.events.stations import StationStore
from vg.features.base import FeatureWorker
from vg.features.people import feet_point, point_in_polygon
from vg.features.recognition import person_crops
from vg.infer.shared import SharedDetection
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

#: How long the working hours read from Settings are reused, as in zones.
HOURS_REUSE_SECONDS = 2.0

#: How long a measured face width is remembered, and how many sightings it
#: takes before "too small" is a finding and not a glance.
REACH_WINDOW_SECONDS = 600.0
REACH_MIN_SIGHTINGS = 5

#: The smallest face the measuring pass reports. Lower than the recognition
#: floor on purpose: it is counting faces, never naming one.
MEASURE_MIN_PIXELS = 20

EDGE_EPSILON = 1e-6


@dataclass
class _Machine:
    """One station's timers. Times only; never who."""

    state: str | None = None          # on | away | absent | None
    segment_id: str | None = None
    since: datetime | None = None
    away_since: datetime | None = None
    last_frame: datetime | None = None
    last_counted: datetime | None = None
    run_start: datetime | None = None
    #: The camera this segment was recorded on. The station's camera can be
    #: edited, so the segment must remember its own.
    camera_id: str | None = None


@dataclass(frozen=True)
class StationReading:
    """What one station saw on one frame."""

    station_id: str
    state: str                         # on | away | absent
    since: datetime
    #: People standing inside the area on this frame.
    people: int = 0
    #: Somebody is inside and nobody matched the assignee. Live; never stored.
    unrecognised: bool = False
    assignee_missing: bool = False
    face_check: str = "anyone"         # anyone | face | facesTooSmall
    face_px: float | None = None


@dataclass(frozen=True)
class StationsResult:
    restricted: bool = False
    stations: tuple[StationReading, ...] = ()


class StationsWorker(FeatureWorker[StationsResult]):
    """Watches drawn stations and logs how long each was staffed."""

    def __init__(
        self,
        bus,
        detector: SharedDetection,
        cameras: list[str],
        store: StationStore,
        areas: Iterable[Area] | None = None,
        config: StationsConfig | None = None,
        pipeline=None,
        gallery=None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
        clock=None,
        hours: Callable[[], HoursConfig] | None = None,
    ) -> None:
        super().__init__("stations", bus, cameras, rate_hz, boost_hz)
        # The SAME SharedDetection the people worker holds: one person pass
        # per frame however many features ask.
        self.detector = detector
        # Scene bookkeeping and a yes/no; the face models run through OpenCV
        # on the processor either way.
        self.device = "cpu"
        self.store = store
        self.config = config or StationsConfig()
        # The one FacePipeline and FaceGallery the engine already holds. Both
        # may be absent: stations then count anyone, and say nothing else.
        self.pipeline = pipeline
        self.gallery = gallery
        self._clock = clock
        self._hours = hours
        self._hours_cache: tuple[datetime, HoursConfig] | None = None
        self._areas: dict[str, tuple[Area, ...]] = {}
        self.set_areas(areas or ())
        # station id -> its timers, and the camera that last stepped it.
        self._machines: dict[str, _Machine] = {}
        self._owner: dict[str, str] = {}
        # station id -> (when, face width in pixels). Numbers only.
        self._reach: dict[str, deque] = {}

    # -- the stations -------------------------------------------------------

    def set_areas(self, areas: Iterable[Area]) -> None:
        """Which stations exist. One assignment: a station deleted or moved has
        its segment closed by its camera's own thread, on the next frame."""
        grouped: dict[str, list[Area]] = {}
        for area in areas:
            if area.kind == "station" and not area.deleted:
                grouped.setdefault(area.camera_id, []).append(area)
        self._areas = {cid: tuple(group) for cid, group in grouped.items()}

    def set_hours(self, hours: Callable[[], HoursConfig]) -> None:
        self._hours = hours
        self._hours_cache = None

    def restricted(self) -> set[str]:
        """Cameras with at least one station watched right now - what the
        shared-pass row reads to know where this worker really asks."""
        now = datetime.now().astimezone()
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

    def _hours_end(self, area: Area, last: datetime, now: datetime) -> datetime:
        """When the watched hours ended, between the last frame and this one."""
        if area.hours_mode == "custom":
            end_time = parse_hhmm(area.hours_to)
        else:
            end_time = self._working_hours(now, True).end
        local = self._clock.local(last) if self._clock is not None else last
        end_local = local.replace(hour=end_time.hour, minute=end_time.minute,
                                  second=0, microsecond=0)
        return min(max(last + (end_local - local), last), now)

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> StationsResult:
        camera_id = frame.camera_id
        now = frame.captured_at
        areas = self._areas.get(camera_id, ())

        self._retire_gone(camera_id, {a.id for a in areas})
        watching: list[Area] = []
        for area in areas:
            if self._watching(area, now):
                watching.append(area)
            else:
                self._end_for_hours(area, now)

        if not watching:
            # BEFORE any detection call: a camera nobody needs watched costs
            # this feature nothing.
            return StationsResult(restricted=False)

        people = self.detector.detect(frame)
        readings = []
        for area in watching:
            self._owner[area.id] = camera_id
            readings.append(self._step(area, frame, people))
        return StationsResult(restricted=True, stations=tuple(readings))

    def _step(self, area: Area, frame: Frame, people) -> StationReading:
        now = frame.captured_at
        m = self._machines.setdefault(area.id, _Machine())

        if (m.state is not None and m.camera_id is not None
                and m.camera_id != area.camera_id):
            # The station was moved to another camera and this is the new
            # camera's thread: what the old camera saw ends where it last saw
            # it, and this frame starts fresh.
            self._end(m, m.last_frame or now)
        m.camera_id = area.camera_id

        if (m.last_frame is not None and m.state is not None
                and (now - m.last_frame).total_seconds()
                >= self.config.stall_seconds):
            # Nobody was looking for a while. Time nobody measured is not time:
            # the segment ends where it was last confirmed and this frame
            # starts fresh, with the Away clock restarting.
            self._end(m, m.last_frame)
        m.last_frame = now

        inside = [p for p in people
                  if point_in_polygon(*_nudge(feet_point(p)), area.polygon)]
        counted, unrecognised, missing, face_check = self._counts(
            area, frame, inside)

        if counted:
            if (m.run_start is None or m.last_counted is None
                    or (now - m.last_counted).total_seconds()
                    >= self.config.gap_tolerance_seconds):
                m.run_start = now
            m.last_counted = now

        if m.state is None:
            self._begin(m, area, "away", now)
            m.away_since = now

        self._advance(m, area, now, counted)
        self.store.touch(m.segment_id, now)
        return StationReading(
            station_id=area.id, state=m.state, since=m.since,
            people=len(inside), unrecognised=unrecognised,
            assignee_missing=missing, face_check=face_check,
            face_px=self._widest(area.id, now))

    def _advance(self, m: _Machine, area: Area, now: datetime,
                 counted: bool) -> None:
        cfg = self.config
        if m.state == "on":
            gone = (m.last_counted is None or
                    (now - m.last_counted).total_seconds()
                    >= cfg.leave_confirm_seconds)
            if gone:
                left = m.last_counted or now
                self.store.add_event(area.id, left, "left_station")
                self._begin(m, area, "away", left)
                m.away_since = left
            return

        # away or absent
        if (counted and m.run_start is not None
                and (now - m.run_start).total_seconds()
                >= cfg.return_confirm_seconds):
            self.store.add_event(area.id, m.run_start, "at_station")
            self._begin(m, area, "on", m.run_start)
            m.away_since = None
            return
        if m.state == "away" and m.away_since is not None and area.limit_minutes:
            due = m.away_since + timedelta(minutes=area.limit_minutes)
            # Somebody walking back whose return is not confirmed yet is not
            # absent: the alert waits until the run confirms or breaks.
            returning = (m.run_start is not None and m.last_counted is not None
                         and (now - m.last_counted).total_seconds()
                         < cfg.gap_tolerance_seconds)
            if now >= due and not returning:
                away_since = m.away_since
                self._begin(m, area, "absent", due)
                m.away_since = away_since
                self.store.absence_alert(
                    area.id, area.camera_id, now, away_since, area.name,
                    area.limit_minutes, self._assignee_name(area),
                    frozenset({"email"}) if area.notify_email else frozenset())

    def _begin(self, m: _Machine, area: Area, state: str,
               since: datetime) -> None:
        """Close the open segment where the new situation began; open the next."""
        if m.segment_id is not None:
            self.store.close_segment(m.segment_id, since)
        m.segment_id = self.store.open_segment(area.id, state, since)
        m.state, m.since = state, since

    def _end(self, m: _Machine, at: datetime) -> None:
        if m.segment_id is not None:
            self.store.close_segment(m.segment_id, at)
        self._reset(m)

    @staticmethod
    def _reset(m: _Machine) -> None:
        m.state = m.segment_id = m.since = m.away_since = None
        m.last_counted = m.run_start = None

    def _end_for_hours(self, area: Area, now: datetime) -> None:
        m = self._machines.get(area.id)
        if m is None or m.state is None or m.last_frame is None:
            return
        if (now - m.last_frame).total_seconds() >= self.config.stall_seconds:
            # Frames stopped before the hours did: the time up to the end of
            # the hours was never watched, so it is not covered.
            self._end(m, m.last_frame)
            return
        self._end(m, self._hours_end(area, m.last_frame, now))

    def _retire_gone(self, camera_id: str, current: set[str]) -> None:
        """Close the segments of stations this camera no longer has."""
        for sid in [s for s, c in self._owner.items()
                    if c == camera_id and s not in current]:
            m = self._machines.pop(sid, None)
            if m is not None and m.state is not None and m.last_frame is not None:
                self._end(m, m.last_frame)
            del self._owner[sid]
            self._reach.pop(sid, None)

    def _closing(self, camera_id: str) -> None:
        """This camera is leaving the worker: close its stations, on its thread."""
        for sid in [s for s, c in self._owner.items() if c == camera_id]:
            m = self._machines.get(sid)
            if m is not None and m.state is not None and m.last_frame is not None:
                self._end(m, m.last_frame)
            del self._owner[sid]
        super()._closing(camera_id)

    def close_all(self) -> None:
        """Close every open segment. Only when no worker thread is live."""
        for m in self._machines.values():
            if m.state is not None and m.last_frame is not None:
                self._end(m, m.last_frame)

    def stop(self) -> None:
        # Threads first, then the segments: the other order would close one
        # underneath the thread still writing to it.
        super().stop()
        self.close_all()

    # -- who counts ---------------------------------------------------------

    def _counts(self, area: Area, frame: Frame, inside) -> tuple:
        """(counted, unrecognised, assignee_missing, face_check) for one frame.

        All four are local to this call. With an assignee, `counted` is whether
        the assignee's face was found among the people inside - a boolean, and
        the only thing that leaves the face step.
        """
        if not inside:
            return False, False, False, self._face_check(area, frame.captured_at)
        if (not area.assignee_id or self.pipeline is None
                or self.gallery is None):
            return True, False, False, "anyone"
        if self.gallery.person(area.assignee_id) is None:
            # Gone from the directory since the station was drawn: count anyone
            # and say so. The id stays, so restoring the person restores this.
            return True, False, True, "anyone"
        check = self._face_check(area, frame.captured_at)
        if check == "facesTooSmall":
            return True, False, False, check
        found = self._assignee_here(area, frame, inside)
        return found, not found, False, check

    def _assignee_here(self, area: Area, frame: Frame, inside) -> bool:
        crops = person_crops(frame.image, [(p.x, p.y, p.w, p.h) for p in inside])
        for crop, _origin in crops:
            observations = self.pipeline.observe(crop)
            if not observations:
                self._measure(area.id, crop, frame.captured_at)
                continue
            for obs in observations:
                self._note_reach(area.id, frame.captured_at, float(obs.face.w))
                match = self.gallery.match(obs.embedding, obs.model)
                if match.person is not None and match.person.id == area.assignee_id:
                    return True
        return False

    def _measure(self, station_id: str, crop, at: datetime) -> None:
        """Faces below the recognition floor, counted to see if the station is
        simply too far from its camera. YuNet only; no embedding, no name."""
        try:
            faces = self.pipeline.detector.detect(
                crop, min_size=MEASURE_MIN_PIXELS)
        except Exception:
            log.debug("could not measure faces", exc_info=True)
            return
        for face in faces:
            self._note_reach(station_id, at, float(face.w))

    def _note_reach(self, station_id: str, at: datetime, px: float) -> None:
        self._reach.setdefault(station_id, deque(maxlen=200)).append((at, px))

    def _window(self, station_id: str, now: datetime) -> list[float]:
        seen = self._reach.get(station_id)
        if not seen:
            return []
        cutoff = now - timedelta(seconds=REACH_WINDOW_SECONDS)
        while seen and seen[0][0] < cutoff:
            seen.popleft()
        return [px for _, px in seen]

    def _widest(self, station_id: str, now: datetime) -> float | None:
        widths = self._window(station_id, now)
        return max(widths) if widths else None

    def _face_check(self, area: Area, now: datetime) -> str:
        if not area.assignee_id or self.pipeline is None or self.gallery is None:
            return "anyone"
        widths = self._window(area.id, now)
        if (len(widths) >= REACH_MIN_SIGHTINGS
                and max(widths) < self.config.min_face_px):
            return "facesTooSmall"
        return "face"

    def _assignee_name(self, area: Area) -> str | None:
        """The assigned person's name for the alert text. A directory lookup of
        the ASSIGNMENT, not a recognition, and not kept."""
        if not area.assignee_id or self.gallery is None:
            return None
        person = self.gallery.person(area.assignee_id)
        return person.name if person is not None else None

    # -- reads --------------------------------------------------------------

    def reading(self, station_id: str, camera_id: str) -> StationReading | None:
        """The last frame's reading of one station, if it is fresh."""
        seen = self.payload(camera_id)
        if seen is None:
            return None
        return next((r for r in seen.stations if r.station_id == station_id), None)


def _nudge(point: tuple[float, float]) -> tuple[float, float]:
    """Keep a feet point inside the frame, so a station that reaches the bottom
    edge contains somebody standing on it."""
    x, y = point
    return (min(max(x, EDGE_EPSILON), 1.0 - EDGE_EPSILON),
            min(max(y, EDGE_EPSILON), 1.0 - EDGE_EPSILON))
