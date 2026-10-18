"""The store, with real cameras in it.

`LiveStore` subclasses `MockStore` and overrides only what is genuinely live.
Everything else keeps returning demo data.

That hybrid is deliberate. The alternative — one big switch from mock to real —
means nothing works until everything works, and every feature has to land at
once. This way each capability moves across on its own: today the camera list,
health and snapshots are real while weapons and alerts are still unbuilt,
and the console does not care. When intrusion goes live it overrides
`breaches()` and nothing else changes.

The methods still inherited from MockStore are the honest to-do list.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

from vg import platetext
from vg.clock import Clock, clock_for
from vg.events import vehicles as vehicle_events
from vg.ingest.recorder import AlreadyRecording
from vg.config import PERSON_FEATURES, CameraConfig, EngineConfig
from vg.api import schemas as S
from vg.api.notes import note
from vg.auth.store import email_key
from vg.api.store import (
    AlreadyBusy,
    FallRefused,
    MockStore,
    NotAffordable,
    NothingThere,
    SubsystemUnavailable,
)
from vg.features.vehicles import MIN_VOTES
from vg.ingest.archive import ArchiveUnavailable, QueueFull
from vg.features.tracking import (
    AlreadyFollowing as FollowExists,
    AlreadyRecordingFollow,
    NobodyThere,
    NoRecorder,
    NotFollowing,
    NotRecordingFollow,
)
from vg.ingest.registry import CameraRegistry

log = logging.getLogger(__name__)


def _instant(when: datetime | None, clock: Clock) -> S.Instant | None:
    """An instant, stamped with the offset that was in force *when it happened*.

    Not the offset at startup and not the offset today. An arrival at 07:42 on
    a July morning still reads 07:42 in December, so a register printed in July
    still matches the screen after the clocks change.
    """
    if when is None:
        return None
    return S.Instant(utc=when, tz_offset_minutes=clock.offset_minutes(when))


def _at_on(on: str, hhmm: str | None, clock: Clock) -> datetime | None:
    """"2026-08-21" + "07:30" -> the instant the SITE calls 07:30 that day.

    The site's clock and never the viewer's: a window typed by somebody in
    Cairo means Cairo's 07:30, and reading it as the server's would quietly
    shift every path by the offset between them.
    """
    if not hhmm:
        return None
    try:
        hour, minute = (int(part) for part in hhmm.split(":")[:2])
        day = date.fromisoformat(on)
    except (ValueError, TypeError):
        return None
    naive = datetime(day.year, day.month, day.day, hour, minute)
    # The offset in force on that day, asked per instant.
    guess = naive.replace(tzinfo=timezone.utc)
    return naive.replace(tzinfo=timezone.utc) - timedelta(
        minutes=clock.offset_minutes(guess)
    )

def _day_label(iso_date: str) -> str:
    """"2026-08-19" -> "Wed 19". The date is already site-local.

    The weekday alone repeats every five rows, which leaves a reader unable to
    say which Tuesday a bar refers to.
    """
    day = date.fromisoformat(iso_date)
    return f"{day.strftime('%a')} {day.day}"



def _gpu_reading() -> dict:
    """What the graphics card is doing right now, from the driver. Or {}.

    Whole device, not this process - NVML reports utilisation for the card,
    and another program using it is counted. Said in the schema rather than
    corrected for, because there is nothing honest to correct it with.
    Empty when there is no NVIDIA driver to ask; never zeros, which would
    read as idle.
    """
    try:
        import pynvml
    except Exception:
        return {}
    try:
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return {
                "util": float(util),
                "used_mb": round(memory.used / 2**20, 0),
                "total_mb": round(memory.total / 2**20, 0),
            }
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return {}


def _gpu_percent() -> float | None:
    return _gpu_reading().get("util")


# psutil's `cpu_percent(interval=None)` reports the change SINCE THE LAST
# CALL ON THE SAME OBJECT, and returns 0.0 the first time. Building a fresh
# `Process()` on every poll - which is what this did until 3 Sep 2026 - made
# every call the first call, so the engine's processor share read 0.0 for as
# long as the product existed. Held once, primed once, read forever.
_PROCESS = None
_PRIMED = False


def _process_cpu() -> float | None:
    """This process's share of one second of processor time, or None.

    None is a real answer and the UI renders it as unavailable with a reason.
    It must never become 0.0: a machine at 90% and a machine nobody can
    measure would then look identical, and the second one is the dangerous
    case. That is also why the very first reading is None rather than the
    0.0 psutil hands back before it has a baseline.

    Process-level rather than per-worker on purpose. Feature workers are
    threads inside this process, so the operating system has no per-worker
    number to give - see `WorkerLoad`. Inventing one would be exactly the
    kind of confident fiction Principle III forbids.
    """
    return _cpu_readings()["process"]


def _machine_cpu() -> float | None:
    """The whole machine, 0-100, every program. Or None before a baseline."""
    return _cpu_readings()["machine"]


def _cpu_readings() -> dict:
    """Both processor readings from ONE call, so they share a baseline.

    psutil measures the change since the last call, so the two figures have
    to be taken together: reading the process, then priming, then reading
    the machine a microsecond later hands back a machine figure of 0.0 on
    the very poll the process figure was honest enough to withhold. One
    function, one prime, and the first poll returns None for both.
    """
    global _PROCESS, _PRIMED
    try:
        import psutil
    except Exception:
        return {"process": None, "machine": None}
    try:
        if _PROCESS is None:
            _PROCESS = psutil.Process()
        process = float(_PROCESS.cpu_percent(interval=None))
        machine = float(psutil.cpu_percent(interval=None))
        if not _PRIMED:
            _PRIMED = True
            return {"process": None, "machine": None}
        return {"process": process, "machine": machine}
    except Exception:
        return {"process": None, "machine": None}


class LiveStore(MockStore):
    """Real cameras; demo data for everything not yet built."""

    def __init__(
        self,
        config: EngineConfig,
        registry: CameraRegistry,
        gallery=None,
        sightings=None,
        recogniser=None,
        cameras=None,
        people=None,
        tracking=None,
        anchors=None,
        archive=None,
        counts=None,
        recorder=None,
        users=None,
        scenes=None,
        zones=None,
        weapons=None,
        weapon_scenes=None,
        falls=None,
        fall_scenes=None,
        lost=None,
        vehicles=None,
        vehicle_store=None,
        patrol=None,
        alerts_store=None,
        alerts=None,
    ) -> None:
        super().__init__()
        # Accounts. Real since P2, so the Users page stops saying the feature
        # does not exist while people are signing in with it.
        self.users_store = users
        self.config = config
        self.registry = registry
        self.gallery = gallery
        self.sightings = sightings
        self.recogniser = recogniser
        # The second recognition tier, or None when it is switched off.
        # Two things read it: the workers stage on System Health, and
        # `_name_source` - because with patrol off a tracked path comes back
        # with fewer NAMED stops, and that has to be visible rather than
        # looking like a person who was not seen.
        self.patrol = patrol
        # Runtime camera roster. Without it the console can still show the
        # YAML cameras, it just cannot add or remove any.
        self.cameras = cameras
        # Person detection / zone occupancy. Independent of recognition:
        # either can be absent without disabling the other.
        #
        # NOT `self.people` — that is the name of the directory method this
        # class inherits from Store, and assigning it here replaced the method
        # with the worker object, so every call to /people raised
        # "'NoneType' object is not callable" and the People page 500'd.
        self.people_worker = people
        # Where somebody has been, written by recognition when the evidence
        # clears the bar. Absent means the past-path question has no answer
        # rather than a made-up one.
        self.anchors = anchors
        # The archive job runner. Absent means recorded video cannot be
        # fetched, which the page says rather than offering a dead control.
        self.archive = archive
        # Track-a-person. Absent unless a camera has the `track` feature;
        # /track then falls back to fixtures rather than 500ing.
        self.tracking = tracking
        # Headcount history, so the hour/day charts are measurements rather
        # than invented numbers. Absent means those windows have nothing real
        # to show and say so instead of falling back to fixtures.
        self.counts = counts
        # On-demand video recording. Absent means the console says so rather
        # than offering a button that quietly does nothing.
        self.recorder = recorder
        # Restricted zones. `scenes` is the log; `zones_worker` is what watches.
        # Either can be absent — the camera list and its toggle work with no
        # worker running at all, and the page says so rather than implying the
        # areas are being watched.
        self.scenes = scenes
        self.zones_worker = zones
        # Knife detection. `weapon_scenes` is the log; `weapons_worker` is
        # what watches. NOT `self.weapons` — that is the name of the method
        # this class inherits from Store, and assigning it here would
        # replace the method with the worker object, the way `self.people`
        # once broke the People page.
        self.weapons_worker = weapons
        self.weapon_scenes = weapon_scenes
        # Fall detection. `fall_scenes` is the history; `falls_worker` is what
        # watches. NOT `self.falls` - that is the name of the Store method.
        self.falls_worker = falls
        self.fall_scenes = fall_scenes
        # Bag detection, on whichever cameras somebody is looking at.
        self.lost_watch = lost
        # Vehicle gate. `vehicle_store` is the register and the pass log;
        # `vehicles_worker` is what reads plates. Either can be absent: the
        # register is usable with no camera running, and the cameras are
        # watchable with no register - and the page says which is missing
        # rather than showing an empty tile that reads as "no cars today".
        #
        # NOT `self.vehicles` - that is the name of a Store method, and
        # assigning a worker over it is what once broke the People page.
        self.vehicles_worker = vehicles
        self.vehicle_store = vehicle_store
        # Alert delivery (spec 013). `alerts_store` holds recipients, rules,
        # the delivery log and Home's acknowledgements; `alerts` is the one
        # sender thread. The Home list needs only the store, so switching
        # sending off in engine.yaml never empties it.
        self.alerts_store = alerts_store
        self.alerts = alerts
        # When the engine came up: a camera with no frame since then has been
        # dark since then, which is all the Home list can honestly say.
        self._started_at = datetime.now(timezone.utc)
        # The site's clock, asked per timestamp. Holding one number from
        # startup left every time an hour out after the October change until
        # somebody restarted the engine, and nothing said so.
        self.clock = clock_for(config.timezone)
        # Set by the lifespan when a subsystem failed to start. Surfaced on
        # System Health so a degraded engine is visible on the page an operator
        # opens to ask exactly that.
        self.recognition_error: str | None = None
        self.people_error: str | None = None
        self.tracking_error: str | None = None
        self.zones_error: str | None = None
        self.weapons_error: str | None = None
        self.falls_error: str | None = None
        self.lost_error: str | None = None
        self.vehicles_error: str | None = None
        self.alerts_error: str | None = None

        # Every camera's own analytics rate, pushed into every worker that
        # serves it. The workers are built in `app.py` with ONE rate each -
        # `min(fps)` across their cameras - and until this line existed that
        # was the whole story: turning one camera down to 2/sec turned every
        # other camera on that worker down with it. Seeding here gives each
        # camera the rate it was configured with, and `_apply_features` keeps
        # it that way when somebody edits one.
        self._seed_rates()

    #: The workers a camera's analytics rate applies to. `lost_watch` is
    #: deliberately absent: bag search runs only while somebody is looking at
    #: the tile, at whatever rate frames arrive, so there is no configured
    #: rate to set on it.
    def _rated_workers(self) -> tuple:
        return (self.people_worker, self.recogniser, self.patrol,
                self.zones_worker, self.tracking, self.vehicles_worker,
                self.weapons_worker, self.falls_worker)

    def _seed_rates(self) -> None:
        """Give every camera in the roster its configured rate, at startup."""
        try:
            configs = list(self.registry.configs())
        except Exception:  # noqa: BLE001 - a store that cannot read the
            # roster still has to construct. Every worker then keeps the rate
            # it was built with, which is what happened before this existed.
            log.warning("could not seed analytics rates from the roster")
            return
        for camera in configs:
            self._set_rate(camera)

    def _set_rate(self, config: CameraConfig) -> None:
        """Tell every worker how often to analyse this one camera.

        Takes effect on the next frame. This is what makes the analytics rate
        on the camera form a setting rather than a stored number - before it,
        an edit changed the decode rate and the models carried on at the old
        rate until somebody restarted the engine.
        """
        for worker in self._rated_workers():
            if worker is None:
                continue
            try:
                worker.set_rate(config.id, config.fps)
            except (AttributeError, ValueError):
                # A worker that predates per-camera rates, or one that
                # refuses the value. Neither is a reason to fail an
                # operator's edit; that worker keeps the rate it was built
                # with and the camera is still served.
                log.warning("%s cannot set the analytics rate for %s",
                            type(worker).__name__, config.id)

    @property
    def recognition_live(self) -> bool:
        return self.gallery is not None and self.sightings is not None

    # -- cameras ------------------------------------------------------------

    def camera_view(
        self, camera_id: str, *, include_zone: bool = False,
        feature: str | None = None,
    ) -> S.CameraView | None:
        """One camera as the UI sees it.

        The offline/stale distinction is the whole contract here: a dropped
        stream still returns its last frame, but flagged, so the console shows
        NO SIGNAL over it instead of presenting it as current.

        `include_zone` is off by default. A restricted-area outline belongs on
        the Intrusion page, where it is the subject; drawing it on an
        attendance tile is noise that implies the zone is being enforced there.
        Only the caller knows the context, so only the caller asks for it.

        `feature` picks the overlay for the same reason. Tracking ids on an
        attendance tile, or face boxes on a counting tile, are both the wrong
        answer to the question that page is asking.
        """
        worker = self.registry.worker(camera_id)
        if worker is None:
            disabled = self.registry.disabled.get(camera_id)
            if disabled is None:
                return None
            return S.CameraView(
                id=disabled.id, name=disabled.name,
                area=self._area_of(disabled.id), offline=True, stale=True,
            )

        frame = worker.last_frame()
        online = worker.status == "ok"
        return S.CameraView(
            id=worker.config.id,
            name=worker.config.name,
            area=worker.config.area,
            faces=worker.config.faces,
            offline=not online,
            captured_at=_instant(frame.captured_at if frame else None, self.clock),
            # Stale means "this pixel data is not current", which is true
            # whenever the stream is down but we still have something to show.
            stale=bool(frame) and not online,
            people_count=self._people_count(worker.config.id, online),
            boxes=self._boxes(worker.config.id, feature) if online else [],
            zone=self._zone_overlay(worker.config.id) if include_zone else None,
            snapshot_url=f"/cameras/{worker.config.id}/snapshot",
            stream_url=f"/cameras/{worker.config.id}/stream",
        )

    def overlay(self, camera_id: str, feature: str | None = None,
                colour: str | None = None) -> list[S.Box]:
        """The public name for `_boxes`, for callers outside this class.

        `app.py` needs the tracking overlay to build the identities list, so
        that the page and the picture cannot disagree about who is who. It
        used to reach for `_tracked_boxes` by getattr; this is the same data
        through the front door, and it keeps the per-feature rule - the caller
        still has to say which feature is asking.
        """
        return self._boxes(camera_id, feature, colour)

    def _boxes(self, camera_id: str, feature: str | None = None,
               colour: str | None = None) -> list[S.Box]:
        """What to draw on a camera tile, for the page that asked.

        **Each feature draws its own overlay.** The same camera means different
        things on different pages: attendance is asking "who is this", tracking
        is asking "which body is this and is it still the same one", counting is
        asking "how many". Sharing one overlay across all of them puts tracking
        ids on the attendance register and person boxes on a face review — which
        is noise at best and a false claim at worst.

        This mirrors the rule `include_zone` already follows: only the caller
        knows the context, so only the caller asks.
        """
        if feature == "track":
            return self._tracked_boxes(camera_id)
        if feature in ("counting", "intrusion"):
            # Restricted zones ask "is there a body here", never "who is it".
            # Face boxes on that page would put a name beside a detection this
            # feature never made — rule 1 — and would make it need attendance
            # switched on to draw anything at all — rule 9.
            return self._person_boxes(camera_id)
        if feature == "vehicles":
            # Above the face default, for exactly the reason the weapons
            # branch below records: falling through would draw a person's
            # NAME over a car.
            return self._plate_boxes(camera_id)
        if feature == "weapons":
            # Above the face default on purpose. Everything unrecognised
            # used to fall through to faces, weapons included — so this
            # page would have drawn somebody's NAME beside a knife the
            # recogniser never associated with them. Rule 1, and the worst
            # sentence in the product to get wrong.
            return self._knife_boxes(camera_id)
        if feature == "falls":
            # Above the face default, for the reason every branch here gives:
            # a person on the floor is a body this feature found, and a name
            # beside them would be a claim it never made (rule 1).
            return self._fall_boxes(camera_id)
        if feature == "lost":
            # Above the face default for the same reason as weapons, and the
            # reason is not hypothetical: knife detection shipped with this
            # branch missing. A bag search that fell through to faces would
            # draw somebody's NAME over a bag nobody has claimed.
            return self._bag_boxes(camera_id, colour)
        # attendance and the default grid want faces.
        return self._face_boxes(camera_id)

    def _tracked_boxes(self, camera_id: str) -> list[S.Box]:
        """Bodies with their appearance id. **Never uses recognition to track.**

        The id comes from clothing colour and build alone, which is the whole
        point: it survives someone turning away, leaving the frame, and walking
        onto another camera, none of which a face can do.

        A name is drawn only when a face is being matched *inside this body, in
        this frame*. It is a live annotation on top of tracking, never an input
        to it, and never carried forward from an earlier binding — that is what
        put one person's name on everybody. If the face is not visible right
        now, the box says the id and nothing else, which is the truth.
        """
        if self.tracking is None or not self.tracking.serves(camera_id):
            return []

        faces = list(self.recogniser.faces_on(camera_id)) if self.recogniser else []

        boxes: list[S.Box] = []
        for sighting in self.tracking.sightings_on(camera_id):
            name = self._face_inside(sighting, faces)
            boxes.append(S.Box(
                x=sighting.x, y=sighting.y, w=sighting.w, h=sighting.h,
                label=name,
                confidence=sighting.confidence,
                kind="match" if name else "person",
                # APPEARANCE always: the box is here because clothing matched,
                # regardless of whether a face happens to be readable as well.
                match=S.MatchKind.APPEARANCE,
                severity=S.Severity.INFO,
                track_id=sighting.stable_id,
            ))
        return boxes

    @staticmethod
    def _face_inside(sighting, faces) -> str | None:
        """The name of a face sitting inside this body, right now, or None.

        Containment rather than overlap: a head is a small part of a body, so
        their intersection-over-union is tiny even when they match perfectly.
        Two faces inside one body means we cannot say whose it is, so we say
        nothing — a hedged name still reads as an identification.
        """
        matched = []
        for face in faces:
            if not face.identified or face.person is None:
                continue
            cx, cy = face.x + face.w / 2, face.y + face.h / 2
            if (sighting.x <= cx <= sighting.x + sighting.w
                    and sighting.y <= cy <= sighting.y + sighting.h):
                matched.append(face.person.name)
        return matched[0] if len(matched) == 1 else None

    def _person_boxes(self, camera_id: str) -> list[S.Box]:
        """Unlabelled bodies, for counting. A count needs no names."""
        if self.people_worker is None:
            return []
        return [
            S.Box(x=p.x, y=p.y, w=p.w, h=p.h, confidence=p.confidence, kind="person")
            for p in self.people_worker.people_on(camera_id)
        ]

    def _plate_boxes(self, camera_id: str) -> list[S.Box]:
        """Number plates, coloured by whether the car is on the register.

        **A plate names a car, never the person driving it.** The label is the
        plate and the owner is deliberately absent: the register's owner field
        belongs to the vehicle, and painting a name over a windscreen would
        claim the system saw who was inside. Rule 1.

        `kind="plate"` keeps this out of every other feature's colouring, and
        the severity is what `boxColor()` paints - red for a withdrawn car,
        amber for one nobody knows, green for a registered one.
        """
        if self.vehicles_worker is None:
            return []

        today = self._site_today()
        boxes: list[S.Box] = []
        for read in self.vehicles_worker.plates_on(camera_id):
            width = max(read.box.w, 0)
            height = max(read.box.h, 0)
            if not width or not height:
                continue

            status = "unknown"
            if read.text and self.vehicle_store is not None:
                status = vehicle_events.status_for(
                    self.vehicle_store.by_plate(read.text), today)

            severity = {
                "blacklist": S.Severity.CRITICAL,
                "unknown": S.Severity.WARN,
                "expired": S.Severity.WARN,
            }.get(status, S.Severity.INFO)

            frame_w, frame_h = self._frame_size(camera_id)
            boxes.append(S.Box(
                # Clamped before sending: `Fraction` validates 0..1 and an
                # out-of-range value would 500 the response, which is
                # degradation as a 5xx - the thing rule 7 forbids.
                x=max(0.0, min(1.0, read.box.x1 / frame_w)),
                y=max(0.0, min(1.0, read.box.y1 / frame_h)),
                w=max(0.0, min(1.0, width / frame_w)),
                h=max(0.0, min(1.0, height / frame_h)),
                label=read.text and platetext.display(read.text) or "Plate",
                confidence=max(0.0, min(1.0, read.confidence)),
                kind="plate",
                severity=severity,
                # Pixels, deliberately, beside the fractions above. This is
                # the aiming aid: it tells an operator whether the camera is
                # close enough, which is the one accuracy problem no amount of
                # software fixes. `read.box.w` is already source-frame pixels.
                plate_width_px=width,
            ))
        return boxes

    def _site_today(self) -> date:
        """The site's today, as a `date`.

        `Clock.today()` returns an ISO **string** because that is what the
        wire wants. Permit expiry is date arithmetic, so it needs the real
        thing — and it must come from the site's clock rather than the
        server's, or a permit expires at the wrong midnight.
        """
        try:
            return date.fromisoformat(self.clock.today())
        except ValueError:
            return datetime.now(timezone.utc).date()

    def _frame_size(self, camera_id: str) -> tuple[int, int]:
        """The camera's frame size, for turning pixels into fractions.

        Geometry crosses the API as fractions, never pixels, and the plate
        reader works in pixels — so the conversion has to happen here, against
        the frame the boxes were measured on.

        Falls back to 1 rather than 0: a camera that has not produced a frame
        yet must not divide by zero inside an overlay request.
        """
        worker = self.registry.worker(camera_id) if self.registry else None
        frame = worker.last_frame() if worker else None
        if frame is not None and getattr(frame, "width", 0):
            return max(frame.width, 1), max(frame.height, 1)
        return 1, 1

    def _knife_boxes(self, camera_id: str) -> list[S.Box]:
        """Possible knives, on the bodies holding them. No identity, ever.

        `kind="weapon"` and `severity=CRITICAL` are what `boxColor()` paints
        red. `match=NONE` and no `track_id` are not omissions: a knife is
        not a person, has no identity to match and is not tracked between
        frames.
        """
        if self.weapons_worker is None:
            return []
        return [
            S.Box(
                x=max(0.0, min(1.0, k.x)),
                y=max(0.0, min(1.0, k.y)),
                w=max(0.0, min(1.0, k.w)),
                h=max(0.0, min(1.0, k.h)),
                label="Knife",
                confidence=max(0.0, min(1.0, k.confidence)),
                kind="weapon",
                severity=S.Severity.CRITICAL,
            )
            for k in self.weapons_worker.knives_on(camera_id)
        ]

    def _fall_boxes(self, camera_id: str) -> list[S.Box]:
        """People down on this camera. No identity, ever.

        Red (`CRITICAL`) once they have been down long enough to count, amber
        (`WARN`) before that - the same two colours, for the same two
        meanings, as everywhere else. Only people who are DOWN are drawn: a
        Falls tile covered in boxes round everyone standing would bury the
        one that matters.
        """
        if self.falls_worker is None:
            return []
        return [
            S.Box(
                x=max(0.0, min(1.0, d.x)),
                y=max(0.0, min(1.0, d.y)),
                w=max(0.0, min(1.0, d.w)),
                h=max(0.0, min(1.0, d.h)),
                label="Down",
                confidence=max(0.0, min(1.0, d.confidence)),
                kind="person",
                severity=S.Severity.CRITICAL if d.alerted else S.Severity.WARN,
            )
            for d in self.falls_worker.down_on(camera_id)
        ]

    def _face_boxes(self, camera_id: str) -> list[S.Box]:
        """Recognition boxes: who the camera can identify.

        Green (face match) versus blue (unidentified) is a distinction the UI
        already draws, so it has to survive the wire — `match` carries it.
        An unidentified face is labelled "Unknown" rather than given a name
        with a low percentage, because a hedged name still reads as an
        identification to anyone glancing at the screen.
        """
        if self.recogniser is None:
            return []

        return [
            S.Box(
                x=face.x, y=face.y, w=face.w, h=face.h,
                label=face.label,
                confidence=face.score if face.identified else None,
                kind="match" if face.identified else "face",
                match=S.MatchKind.FACE if face.identified else S.MatchKind.NONE,
                severity=S.Severity.INFO,
            )
            for face in self.recogniser.faces_on(camera_id)
        ]

    def _people_count(self, camera_id: str, online: bool) -> int | None:
        """Bodies in frame, from the person detector — not a face count.

        Comes from the people worker, never from recognition: a face count
        misses anyone turned away, and counting must not require attendance
        to be switched on.

        None means nothing recent measured this camera, which is a different
        claim from a measured zero and must not be rendered as one.
        """
        if not online or self.people_worker is None:
            return None
        return self.people_worker.count_on(camera_id)

    def _zone_overlay(self, camera_id: str) -> S.ZoneOverlay | None:
        zones = self.config.zones_for(camera_id)
        if not zones:
            return None
        zone = zones[0]
        return S.ZoneOverlay(
            id=zone.id,
            label=zone.name,
            polygon=[S.Point(x=x, y=y) for x, y in zone.polygon],
            enabled=zone.enabled,
        )

    # -- camera management --------------------------------------------------

    def add_camera(self, req: S.AddCameraRequest, actor: str = "unknown") -> S.CameraSource:
        """Persist a camera and start watching it in the same call."""
        source = _with_credentials(req.source.strip(), req.username, req.password)
        camera_id = req.id or _slug(req.name)

        # Before the write, as everywhere else. A camera appearing changes
        # what the whole system watches, so the attempt is recorded even if
        # the write then fails.
        self._log(actor, "camera.add", camera_id,
                  f"{req.kind.value} {_redacted(source)}")

        config = self.cameras.add(
            camera_id=camera_id,
            name=req.name,
            source=source,
            kind=req.kind.value,
            area=req.area,
            fps=req.fps,
            features=tuple(req.features),
            rotate=req.rotate,
            faces=req.faces,
            gate=req.gate,
            direction=req.direction,
            neighbours=tuple(req.neighbours),
        )
        self.registry.add(config)
        notes = self._apply_features(config)

        return self._source_view(config, feature_notes=notes)

    def bulk_add(
        self, req: S.BulkAddRequest, actor: str = "unknown"
    ) -> list[S.AddCameraOutcome]:
        """Add several cameras, reporting an outcome for each.

        Never abandons the rest on a failure: one channel with a duplicate id
        must not cost the other fifteen. Each camera is audited before its own
        write by `add_camera`, so a partial run leaves a complete record.
        """
        outcomes: list[S.AddCameraOutcome] = []
        for index, camera in enumerate(req.cameras):
            source = _with_credentials(
                camera.source.strip(), camera.username, camera.password)
            try:
                added = self.add_camera(camera, actor)
            except Exception as exc:
                outcomes.append(S.AddCameraOutcome(
                    index=index, ok=False, source=_redacted(source),
                    error=str(exc)))
            else:
                outcomes.append(S.AddCameraOutcome(
                    index=index, ok=True, id=added.id, source=added.ip))
        return outcomes

    def edit_camera(
        self, camera_id: str, req: S.EditCameraRequest, actor: str = "unknown"
    ) -> S.EditCameraResult | None:
        """Correct a camera in place, keeping its identity and its history."""
        if self.cameras is None:
            raise SubsystemUnavailable(
                "The runtime camera roster is not available, so no camera can "
                "be changed.")

        current = self._config_for(camera_id)
        if current is None:
            return None

        changes = req.model_dump(exclude_none=True)
        username = changes.pop("username", None)
        password = changes.pop("password", None)
        source = changes.get("source", current.source)
        if username:
            source = _with_credentials(source, username, password)
        changes["source"] = source

        # Named, not valued: `detail` must never carry a credential, and the
        # fields that changed are what an audit reader actually needs.
        self._log(actor, "camera.edit", camera_id,
                  "changed " + ", ".join(sorted(changes)) if changes else "no change")

        merged = {
            "id": current.id,
            "name": current.name,
            "source": current.source,
            "kind": current.kind,
            "area": current.area,
            "fps": current.fps,
            "rotate": current.rotate,
            "enabled": current.enabled,
            "features": list(current.features),
            "faces": current.faces,
            "gate": current.gate,
            "direction": current.direction,
            "face_gate": current.face_gate,
            "live_capture": current.live_capture,
            "neighbours": list(current.neighbours),
            **changes,
        }
        # Validate before writing, so a refused edit changes nothing at all.
        config = CameraConfig.parse(merged, f"camera {camera_id!r}")

        shadows = not any(c.id == camera_id for c in self.cameras.all())
        self.cameras.add(
            camera_id=config.id, name=config.name, source=config.source,
            kind=config.kind, area=config.area, fps=config.fps,
            features=config.features, rotate=config.rotate,
            enabled=config.enabled, faces=config.faces, gate=config.gate,
            direction=config.direction, face_gate=config.face_gate,
            live_capture=config.live_capture, neighbours=config.neighbours,
        )

        # Only when the STREAM changed. Reopening an RTSP connection to add a
        # tickbox is a visible stutter on a camera somebody may be watching.
        restarted = any(
            getattr(config, field) != getattr(current, field)
            for field in ("source", "fps", "rotate", "enabled")
        )
        if restarted:
            self.registry.add(config)
        else:
            # Same stream, new settings: recorded where the console reads the
            # camera back from, with nothing reopened.
            self.registry.update(config)

        notes = self._apply_features(config, previous=current)
        return S.EditCameraResult(
            camera=self._source_view(config, feature_notes=notes),
            shadows_config=shadows,
            restarted=restarted,
            feature_notes=notes,
        )

    def remove_camera(self, camera_id: str, actor: str = "unknown") -> bool:
        # Before the write. A camera going quiet is exactly the change
        # somebody may later need to explain.
        self._log(actor, "camera.remove", camera_id, None)

        self._unwatch_everywhere(camera_id)
        stopped = self.registry.remove(camera_id)
        recorded = self.cameras.remove(camera_id) if self.cameras else False
        return stopped or recorded

    def _config_for(self, camera_id: str) -> CameraConfig | None:
        """The camera as the engine currently sees it, YAML or stored."""
        worker = self.registry.worker(camera_id)
        if worker is not None:
            return worker.config
        disabled = self.registry.disabled.get(camera_id)
        if disabled is not None:
            return disabled
        return next((c for c in self.config.cameras if c.id == camera_id), None)

    def _source_view(
        self, config: CameraConfig, feature_notes: list[S.FeatureNote] | None = None
    ) -> S.CameraSource:
        """One camera, as the console sees it."""
        worker = self.registry.worker(config.id)
        stored = {c.id for c in self.cameras.all()} if self.cameras else set()
        return S.CameraSource(
            id=config.id,
            name=config.name,
            type=_source_type(config.kind),
            ip=config.redacted_source(),
            channels=1,
            # Honest immediately: a camera that has not connected yet is down,
            # not ok. It flips to ok on its first frame.
            status=S.SourceStatus(worker.status) if worker else S.SourceStatus.DOWN,
            area=config.area,
            last_error=worker.source.health.last_error if worker else None,
            features=list(config.features),
            faces=config.faces,
            enabled=config.enabled,
            gate=config.gate,
            direction=config.direction,
            fps=config.fps,
            rotate=config.rotate,
            from_config=config.id not in stored,
        )

    # -- feature assignment -------------------------------------------------
    #
    # One camera's feature list decides one camera's analysis, and nothing
    # else's. This is the only place that mapping is written down in code; the
    # table it implements is in specs/011-camera-onboarding/data-model.md.
    #
    # Every worker here can be None, because a subsystem that failed to start
    # leaves one behind. That is not an error and must not refuse the camera -
    # it is reported as a note so the operator learns at the moment they chose
    # the feature, rather than never.

    def _apply_features(
        self, config: CameraConfig, previous: CameraConfig | None = None
    ) -> list[S.FeatureNote]:
        """Make the running workers agree with this camera's feature list."""
        wanted = set(config.features) if config.enabled else set()
        identity = config.enabled and (config.faces or "attendance" in wanted)

        # Before the watches, so a worker that is about to start serving this
        # camera already knows how often to look at it. Doing it afterwards
        # would leave one frame analysed at the wrong rate.
        self._set_rate(config)

        # The shared person pass. Not a feature in its own right - it is what
        # counting, intrusion and track all read - so it gets no note.
        self._set_watch(
            self.people_worker, config.id,
            bool(PERSON_FEATURES.intersection(wanted)))

        # The identity tier is a MOVE between two workers, not a toggle. Watch
        # the new tier before unwatching the old, or there is an instant where
        # neither is looking at this camera.
        self._set_watch(self.recogniser, config.id, identity)
        self._set_watch(self.patrol, config.id, config.enabled and not identity)

        notes: list[S.FeatureNote] = []
        for feature, worker, want, reason in (
            ("counting", self.people_worker, "counting" in wanted, self.people_error),
            ("intrusion", self.zones_worker, "intrusion" in wanted, self.zones_error),
            ("track", self.tracking, "track" in wanted, self.tracking_error),
            ("attendance", self.recogniser, "attendance" in wanted,
             self.recognition_error),
            ("vehicles", self.vehicles_worker,
             config.enabled and config.is_gate, self.vehicles_error),
            ("weapons", self.weapons_worker, "weapons" in wanted, self.weapons_error),
            ("falls", self.falls_worker, "falls" in wanted, self.falls_error),
            ("lostitems", self.lost_watch, "lostitems" in wanted, self.lost_error),
        ):
            if feature not in ("counting", "attendance"):
                # counting and attendance are served by workers already set
                # above; setting them twice would fight over the same list.
                self._set_watch(worker, config.id, want)
            if want and worker is None:
                notes.append(S.FeatureNote(
                    feature=feature, running=False,
                    reason=reason or "This feature is not running on this engine.",
                ))
            elif want:
                notes.append(S.FeatureNote(feature=feature, running=True))
        return notes

    def _unwatch_everywhere(self, camera_id: str) -> None:
        """Stop every feature analysing this camera.

        Removing a camera has to stop the analysis too, or "remove" means only
        that it left a list. Each worker closes whatever it held for this
        camera on that camera's own thread.
        """
        for worker in (self.people_worker, self.recogniser, self.patrol,
                       self.zones_worker, self.tracking, self.vehicles_worker,
                       self.weapons_worker, self.falls_worker, self.lost_watch):
            self._set_watch(worker, camera_id, False)

    @staticmethod
    def _set_watch(worker, camera_id: str, wanted: bool) -> None:
        """Watch or unwatch one camera on one worker, if that worker exists.

        Absent workers are skipped rather than raising: a subsystem that did
        not start must not stop a camera being configured for the other six
        features (rule 9).
        """
        if worker is None:
            return
        try:
            (worker.watch if wanted else worker.unwatch)(camera_id)
        except AttributeError:
            # A worker that predates this mechanism. Better to log and carry
            # on than to fail an operator's edit over it.
            log.warning("%s cannot change cameras at runtime",
                        type(worker).__name__)

    def camera_detections(
        self, camera_id: str, feature: str | None = None,
        colour: str | None = None,
    ) -> S.CameraDetections:
        """Boxes and headcount from the same inference pass.

        Together rather than separately so they cannot disagree by a frame,
        and so the enlarged view runs one poll instead of two.

        `feature` selects the overlay, so the enlarged view on the tracking
        page shows appearance ids while the same camera on attendance shows
        faces. One camera, different questions.
        """
        worker = self.registry.worker(camera_id)
        online = worker is not None and worker.status == "ok"
        frame = worker.last_frame() if worker else None
        result = self.recogniser.result(camera_id) if self.recogniser else None

        return S.CameraDetections(
            camera_id=camera_id,
            at=_instant(frame.captured_at if frame else None, self.clock),
            boxes=self._boxes(camera_id, feature, colour) if online else [],
            people_count=self._people_count(camera_id, online),
            inference_ms=round(result.inference_ms, 1) if result else None,
        )

    def live_counts(self) -> dict[str, int | None]:
        """Headcount per camera for the grid's single poll."""
        counts: dict[str, int | None] = {}
        for camera_id, worker in self.registry.workers.items():
            online = worker.status == "ok"
            counts[camera_id] = self._people_count(camera_id, online)
        for camera_id in self.registry.disabled:
            counts[camera_id] = None
        return counts

    def live_cameras(self) -> list[S.CameraView]:
        views = [self.camera_view(cid) for cid in self.registry.workers]
        views += [self.camera_view(cid) for cid in self.registry.disabled]
        return [v for v in views if v is not None]

    # -- overrides ----------------------------------------------------------

    def site(self) -> S.SiteInfo:
        """The app chrome. Built outright, not copied from the fixtures.

        It used to start from `MockStore.site()` and overwrite seven of the
        eight fields. The eighth was `areas`, so every dropdown in the console
        offered rooms this school does not have.
        """
        areas = self.areas()
        # `today` is the *site's* date, not the server's. The schema has said
        # so since it was written; the code sent the UTC date, so between
        # midnight and 03:00 Cairo the whole console was a day behind - the
        # attendance register included.
        now = datetime.now(timezone.utc)
        return S.SiteInfo(
            name=self.config.site_name,
            today=self.clock.local_date(now),
            timezone=self.config.timezone,
            tz_offset_minutes=self.clock.offset_minutes(now),
            cameras_online=self.registry.online,
            # Enabled cameras only, like System Health. "1 of 3 up" over two
            # cameras switched off on purpose is the top bar telling the
            # whole console something is wrong when nothing is.
            cameras_total=len(self.registry.workers),
            places=([self.ALL_PLACES] + areas) if areas else [],
            areas=areas,
            clip_retention_days=self.config.storage.clip_retention_days,
        )

    # -- restricted zones ---------------------------------------------------
    #
    # A zone IS a camera. Switching one on makes its **whole frame** the
    # restricted area, so there is no polygon to draw and nothing to get
    # wrong about where the line is. The wire still carries a polygon because
    # `Zone.polygon` requires at least three points; it carries the four frame
    # corners, which is literally true and keeps every existing client valid.

    #: The zone, as a polygon: the entire frame.
    FRAME_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

    def _restricted_ids(self) -> set[str]:
        """Which cameras are switched on, from the database.

        Intersected with the roster, so a camera that has been removed since
        somebody restricted it does not keep appearing as a watched area.
        """
        if self.cameras is None:
            return set()
        roster = {c.id for c in self.registry.configs()}
        return self.cameras.restricted_ids() & roster

    def _start_of_today(self) -> datetime:
        """Midnight at the *site*, as an instant.

        Not the server's midnight. A school in Cairo at 00:30 local is still on
        the previous UTC day, and counting today's scenes against the wrong
        boundary puts last night's entries on this morning's total.
        """
        now = datetime.now(timezone.utc)
        local = self.clock.local(now)
        midnight_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight_local.astimezone(timezone.utc)

    def zones(self) -> list[S.Zone]:
        """The real camera roster, each with its toggle. Never fixtures.

        Every camera appears whether or not it is restricted — the toggle is
        how you tell, and a camera that vanished when switched off would take
        its history with it (P4-FR-010).
        """
        restricted = self._restricted_ids()
        today = (self.scenes.counts_since(self._start_of_today())
                 if self.scenes is not None else {})
        return [
            S.Zone(
                id=camera.id,
                name=camera.name,
                camera_id=camera.id,
                schedule=S.Schedule(mode=S.ScheduleMode.ALWAYS, days=[]),
                enabled=camera.id in restricted,
                polygon=[S.Point(x=x, y=y) for x, y in self.FRAME_CORNERS],
                breaches_today=today.get(camera.id, 0),
            )
            for camera in self.registry.configs()
        ]

    def set_zone_enabled(self, zone_id: str, enabled: bool) -> S.Zone | None:
        """Flip the toggle, and make it true on the next frame.

        Written to the database first, so it survives a restart, then pushed
        into the running worker. Only writing one of the two is how a setting
        ends up meaning different things to the page and to the engine.

        Existence is checked against the **roster**, not the camera table: the
        baseline cameras come from engine.yaml and have no row there at all, so
        asking the table would 404 on every camera a site starts with.
        """
        if self.cameras is None:
            return None
        if not any(c.id == zone_id for c in self.registry.configs()):
            # No such camera. The endpoint 404s rather than reporting a change
            # it did not make.
            return None

        self.cameras.set_restricted(zone_id, enabled)

        if self.zones_worker is not None:
            self.zones_worker.set_restricted(self._restricted_ids())

        return next((z for z in self.zones() if z.id == zone_id), None)

    def intrusion_cameras(self) -> list[S.CameraView]:
        """Tiles for the cameras that are actually restricted.

        `include_zone` stays off: the zone is the frame, so drawing a rectangle
        inside it would claim a boundary that does not exist (P4-FR-002).
        """
        restricted = self._restricted_ids()
        # Roster order, not set order, so the grid does not reshuffle itself
        # between two polls of the same unchanged data.
        views = [self.camera_view(camera.id, feature="intrusion")
                 for camera in self.registry.configs() if camera.id in restricted]
        # No `or super()`: a site with nothing switched on has no restricted
        # cameras, and saying so is the truth. Demo cameras appearing here
        # once looked exactly like a working zone.
        return [v for v in views if v is not None]

    def breaches(self, since_days: int) -> list[S.Breach]:
        """The detection log: one entry per scene, newest first.

        **Nobody is named here.** This feature detects bodies; it never runs a
        face against them, so `subject` is always an unidentified match. A name
        on one of these rows would be a claim nothing in this pipeline made —
        rule 1, and the bug that once had every person read as one person.

        **Entries whose clip has been replaced are not listed** (owner
        decision, 2026-08-21). Each camera keeps its newest three clips, so
        this is at most three watchable entries per camera plus anything still
        recording or whose recording failed — a failure is news and stays.
        The rows themselves are never deleted; `SceneStore.recent()` still
        returns them, which is what the audit view in P3 will read.
        """
        if self.scenes is None:
            return []

        # From the roster, not from engine.yaml: a camera added through the
        # console is not in the config file, and `_camera_name` falls back to
        # the raw id for it — which would put "cam-3" on the screen where the
        # operator typed "Back stairwell".
        names = {c.id: c.name for c in self.registry.configs()}

        out: list[S.Breach] = []
        for scene in self.scenes.recent(since_days, include_replaced=False):
            name = names.get(scene.camera_id) or scene.camera_id
            out.append(S.Breach(
                id=scene.id,
                zone_id=scene.camera_id,
                zone_name=name,
                camera_id=scene.camera_id,
                camera_name=name,
                at=_instant(scene.started_at, self.clock),
                subject=S.PersonRef(name="Unidentified", match=S.MatchKind.NONE),
                # Open means somebody is still standing there, not that a human
                # owes it a review — this feature has no review workflow.
                status=(S.BreachStatus.OPEN if scene.running
                        else S.BreachStatus.RESOLVED),
                severity=S.Severity.WARN,
                # Person detection has a confidence per box; a scene does not.
                # Inventing one would be a number nothing measured.
                confidence=0.0,
                dwell_seconds=round(scene.seconds, 1),
                people=scene.peak_people,
                clip_state=scene.clip_state,
                clip_reason=scene.clip_reason or self._no_clip_reason(scene),
                clip=self._scene_clip(scene),
            ))
        return out

    def clip_for_breach(self, scene_id: str):
        """The file for one scene, or why there is not one.

        Returns `(path, reason)` — exactly one is set. The endpoint turns a
        reason into a 404 with those words in it, so every refusal says what
        happened rather than "not found".

        **The path is never taken from the request.** The id is looked up, the
        stored path is checked to be inside the zones clip directory, and only
        then is anything opened. A row is data like any other; a wrong one must
        not become a way to read the disk.
        """
        if self.scenes is None:
            return None, "The detection log is not available."

        scene = self.scenes.get(scene_id)
        if scene is None:
            return None, f"no detection {scene_id!r}"
        if scene.clip_state != "saved" or scene.clip_path is None:
            return None, (
                scene.clip_reason
                or "There is no clip for this detection."
            )

        root = self.config.storage.zone_clips_dir
        try:
            path = scene.clip_path.resolve()
            path.relative_to(root.resolve())
        except (OSError, ValueError):
            log.error("scene %s names a clip outside %s: %s",
                      scene_id, root, scene.clip_path)
            return None, "That clip is not where it should be, so it was not served."

        if not path.is_file():
            # Rule 4: never claim a file that is not there. A row can outlive
            # its file — a disk wiped by hand, a folder moved — and the honest
            # answer is that it is gone, not a 500 from a failed open.
            return None, "The clip is no longer on disk."

        return path, ""

    @staticmethod
    def _no_clip_reason(scene) -> str | None:
        """A sentence for every state that has no file, so no control is bare."""
        if scene.clip_state == "saved":
            return None
        if scene.clip_state == "recording":
            return "Still recording — the clip is saved when they leave."
        if scene.clip_state == "none":
            return "No clip was recorded for this detection."
        return None

    def _scene_clip(self, scene) -> S.Clip | None:
        """The playable clip, and only when there genuinely is one.

        The URL is **same-origin and relative**, built like the stream URLs
        above. A `<video src>` cannot send an Authorization header, so an
        absolute engine URL would play for nobody — that is exactly what made
        the camera streams go black last cycle.
        """
        if not scene.playable:
            return None
        return S.Clip(
            id=scene.id,
            url=f"/breaches/{scene.id}/clip",
            duration_seconds=round(scene.seconds, 1),
            starts_at=_instant(scene.started_at, self.clock),
        )

    # -- lost bag -----------------------------------------------------------

    def note_lost_interest(self, camera_id: str) -> None:
        """A tile asked for a bag overlay, so that camera is worth looking at.

        This is the only thing that makes the bag model run. No poll, no work.
        """
        if self.lost_watch is not None:
            self.lost_watch.note_interest(camera_id)

    def _bag_boxes(self, camera_id: str, colour: str | None = None) -> list[S.Box]:
        """Possible bags, on the tiles. No identity, ever.

        `kind="object"` and `severity=WARN` are what `boxColor()` paints amber:
        never green (a face), never blue (a body). `match=NONE` and no
        `track_id` are not omissions - a bag has no identity to match and is
        not tracked between frames.

        The label is the class name, so an operator can tell a rucksack from a
        suitcase at a glance. It is never a person's name.
        """
        if self.lost_watch is None:
            return []
        return [
            S.Box(
                x=max(0.0, min(1.0, hit.x)),
                y=max(0.0, min(1.0, hit.y)),
                w=max(0.0, min(1.0, hit.w)),
                h=max(0.0, min(1.0, hit.h)),
                label=hit.label.title(),
                confidence=max(0.0, min(1.0, hit.confidence)),
                kind="object",
                severity=S.Severity.WARN,
            )
            for hit in self.lost_watch.boxes_on(camera_id, colour)
        ]

    def _lost_state(self) -> tuple[S.DataState, str | None]:
        """Whether bags can be looked for at all, and if not, why not."""
        if self.lost_watch is None:
            if self.lost_error:
                return S.DataState.UNAVAILABLE, self.lost_error
            return (S.DataState.UNAVAILABLE,
                    "Bag detection is not running, so no camera can be "
                    "checked for a bag.")
        return S.DataState.LIVE, None

    @staticmethod
    def _running_on(detector) -> str:
        """"<version> on <device> (<form>)" for a System Health row.

        The form is the half that has been missing. This repo ran every model
        unaccelerated for months with five unused TensorRT engines sitting on
        disk, and nothing on any screen said so - it was only findable by
        timing a frame by hand. P6-FR-035 makes it a sentence.

        `getattr` throughout because a stage may be asked about a detector
        that failed to construct, and System Health going down with it is the
        opposite of what this page is for.
        """
        version = getattr(detector, "version", "unknown")
        device = getattr(detector, "device", "unknown")
        form = getattr(detector, "form", None)
        return f"{version} on {device}" + (f" ({form})" if form else "")

    def _lost_stage(self) -> S.PipelineStage:
        """Rule 8: a subsystem that failed to start says so in the UI."""
        state, reason = self._lost_state()
        if state is not S.DataState.LIVE:
            return S.PipelineStage(
                key="search_lost", name="Bag detection",
                detail=reason or "Not running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self._stats_of(self.lost_watch)
        if stats is None:
            return S.PipelineStage(
                key="search_lost", name="Bag detection",
                detail="Running, but it could not report its counters.",
                healthy=False, severity=S.Severity.WARN, restartable=True,
            )
        detector = getattr(self.lost_watch, "detector", None)
        cameras = stats["cameras"]
        doing = (f"watching {cameras} camera{'' if cameras == 1 else 's'}"
                 if cameras else "idle - nobody is looking")
        return S.PipelineStage(
            key="search_lost", name="Bag detection",
            detail=f"{self._running_on(detector)} - {doing}",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    # -- knife detection ----------------------------------------------------

    def weapons(self, since: datetime | None,
                until: datetime | None = None) -> list[S.WeaponDetection]:
        """The knife log: one entry per incident, newest first.

        **Nobody is named here.** This feature detects a knife on a body; it
        never runs a face against that body, so no entry carries an identity.
        A name on one of these rows would be a claim nothing in this pipeline
        made — rule 1, and the bug that once had every person read as one
        person.

        **Nothing is ever removed from this list.** Not by verdict, not by
        retention, not by anything. A dismissed detection stays, with its
        reason and its reviewer; only the video goes, and the entry then says
        so. A page that hides its own false alarms cannot be audited, and the
        record of what was looked at is most of the value here.
        """
        if self.weapon_scenes is None:
            return []

        # Cheap on every read: one indexed query that usually matches
        # nothing. It runs here as well as at startup because a
        # long-running engine would otherwise keep a video past the period
        # this very page promises.
        self._expire_weapon_clips()

        # From the roster, not from engine.yaml: a camera added through the
        # console is not in the config file, and the raw id would put "cam-3"
        # on the screen where the operator typed "Back stairwell".
        names = {c.id: c.name for c in self.registry.configs()}

        out: list[S.WeaponDetection] = []
        for scene in self.weapon_scenes.recent(since, until):
            name = names.get(scene.camera_id) or scene.camera_id
            dismissed = scene.verdict == "dismissed"
            out.append(S.WeaponDetection(
                id=scene.id,
                at=_instant(scene.started_at, self.clock),
                camera_id=scene.camera_id,
                camera_name=name,
                location=self._area_of(scene.camera_id),
                item="Knife",
                # `Confidence` is validated 0..1 and a stored peak is a float
                # from a model; clamping here beats a 500 on the list endpoint.
                confidence=max(0.0, min(1.0, scene.peak_confidence)),
                # Dismissed means a person looked and said no. Leaving it
                # CRITICAL would keep it red in a list somebody has already
                # cleared, and the next real one would not stand out.
                severity=S.Severity.INFO if dismissed else S.Severity.CRITICAL,
                verdict=S.ReviewVerdict(scene.verdict),
                reviewed_by=scene.reviewed_by,
                reviewed_at=_instant(scene.reviewed_at, self.clock)
                if scene.reviewed_at else None,
                dismissal_reason=scene.review_reason,
                # Boxes are live overlay, not history: a box drawn over a frame
                # that is no longer on screen is decoration.
                box=None,
                clip=self._weapon_clip(scene),
                model_version=scene.model_version or None,
                ended_at=_instant(scene.ended_at, self.clock)
                if scene.ended_at else None,
                seconds=round(scene.seconds, 1),
                clip_state=scene.clip_state,
                clip_reason=scene.clip_reason or self._no_weapon_clip_reason(scene),
                end_reason=scene.end_reason,
            ))
        return out

    def _expire_weapon_clips(self) -> int:
        """Remove knife videos past the configured retention period.

        The period lives in the configuration, not in the store: a site that
        changes `clip_retention_days` must not need a code change, and the
        store must not have to be told the number twice.
        """
        if self.weapon_scenes is None:
            return 0
        days = self.config.storage.clip_retention_days
        return self.weapon_scenes.expire(
            datetime.now(timezone.utc) - timedelta(days=days))

    def weapon_cameras(self) -> list[S.CameraView]:
        """The cameras actually being checked for knives.

        Not the whole roster: the header says "*N* cameras being checked", and
        a camera the worker does not serve is not being checked. Without a
        worker the honest answer is none at all, and the capability says why.
        """
        if self.weapons_worker is None:
            return []
        out: list[S.CameraView] = []
        for camera in self.registry.configs():
            if not self.weapons_worker.serves(camera.id):
                continue
            view = self.camera_view(camera.id, feature="weapons")
            if view is not None:
                out.append(view)
        return out

    # -- fall detection -----------------------------------------------------

    def falls(self, since: datetime | None,
              until: datetime | None = None) -> list[S.FallEntry]:
        """The fall history: one entry per fall, newest first.

        **Nobody is named here.** The model sees a body on the floor; it never
        runs a face against it (rule 1).

        **Nothing is ever removed from this list.** "Not a fall" stays, with
        who said so; only the video goes with age, and the entry then says so.
        """
        if self.fall_scenes is None:
            return []
        self._expire_fall_clips()
        names = {c.id: c.name for c in self.registry.configs()}
        return [self._fall_entry(scene, names) for scene in
                self.fall_scenes.recent(since, until)]

    def _fall_entry(self, scene, names: dict | None = None) -> S.FallEntry:
        if names is None:
            names = {c.id: c.name for c in self.registry.configs()}

        def instant(when):
            return _instant(when, self.clock) if when else None

        return S.FallEntry(
            id=scene.id,
            at=_instant(scene.started_at, self.clock),
            camera_id=scene.camera_id,
            camera_name=names.get(scene.camera_id) or scene.camera_id,
            location=self._area_of(scene.camera_id),
            detected_at=_instant(scene.detected_at, self.clock),
            alerted_at=instant(scene.alerted_at),
            ended_at=instant(scene.ended_at),
            seconds=round(scene.seconds, 1),
            end_reason=scene.end_reason,
            # Validated 0..1; a stored float from a model is clamped rather
            # than allowed to 500 the list.
            confidence=max(0.0, min(1.0, scene.peak_confidence)),
            verdict=scene.verdict if scene.verdict in ("none", "not_a_fall") else "none",
            reviewed_by=scene.reviewed_by,
            reviewed_at=instant(scene.reviewed_at),
            responder=scene.responder,
            responded_at=instant(scene.responded_at),
            clip=self._fall_clip(scene),
            clip_state=scene.clip_state,
            clip_reason=scene.clip_reason or self._no_fall_clip_reason(scene),
            model_version=scene.model_version or None,
        )

    def falls_now(self) -> list[S.FallEntry]:
        """Everybody down right now, whenever they went down. Longest first.

        Separate from `falls(since, until)` on purpose: the live cards and the
        "nobody is on the ground" line must never depend on which history
        period somebody picked. Built from the period list, choosing
        Yesterday hid a person on the floor now and printed the all-clear.
        """
        if self.fall_scenes is None:
            return []
        names = {c.id: c.name for c in self.registry.configs()}
        return [self._fall_entry(scene, names) for scene in self.fall_scenes.running()]

    def falls_status(self) -> S.FallsStatus:
        """The rule the page quotes, and how many cameras it applies to.

        The rule is the worker's own number when one is running, so the page
        can never quote a different one from the rule actually applied.
        """
        from vg.features.falls import DOWN_SECONDS

        worker = self.falls_worker
        if worker is None:
            return S.FallsStatus(down_seconds=DOWN_SECONDS, cameras_checked=0)
        return S.FallsStatus(
            down_seconds=float(worker.down_seconds),
            cameras_checked=len(worker.cameras),
        )

    def _fall_write(self, fall_id: str):
        """The entry a button is about to change, or why it cannot be."""
        if self.fall_scenes is None:
            raise SubsystemUnavailable(
                "The fall history is not available, so nothing can be recorded.")
        return self.fall_scenes.get(fall_id)

    def respond_to_fall(self, fall_id: str, who: str) -> S.FallEntry | None:
        """"I'm on my way". The audit entry goes first, as with every write."""
        self._log(who, "fall.respond", fall_id, None)
        scene = self._fall_write(fall_id)
        if scene is None:
            return None
        if not self.fall_scenes.respond(fall_id, who, datetime.now(timezone.utc)):
            current = self.fall_scenes.get(fall_id)
            if current.ended_at is not None:
                raise FallRefused("They are no longer down, so nobody needs to go.")
            raise FallRefused(f"{current.responder} is already on the way.")
        return self._fall_entry(self.fall_scenes.get(fall_id))

    def undo_fall_response(self, fall_id: str, who: str) -> S.FallEntry | None:
        """Take back "I'm on my way". Audited first, naming whose name went."""
        scene = self._fall_write(fall_id)
        self._log(who, "fall.respond.undo", fall_id,
                  scene.responder if scene is not None else None)
        if scene is None:
            return None
        if self.fall_scenes.undo_response(fall_id) is None:
            raise FallRefused("Nobody is recorded as on the way.")
        return self._fall_entry(self.fall_scenes.get(fall_id))

    def mark_not_a_fall(self, fall_id: str, who: str) -> S.FallEntry | None:
        """"Not a fall". Once, by one person, never back; audited first."""
        self._log(who, "fall.not_a_fall", fall_id, None)
        scene = self._fall_write(fall_id)
        if scene is None:
            return None
        if not self.fall_scenes.mark_not_a_fall(fall_id, who, datetime.now(timezone.utc)):
            current = self.fall_scenes.get(fall_id)
            raise FallRefused(f"{current.reviewed_by} already marked this not a fall.")
        return self._fall_entry(self.fall_scenes.get(fall_id))

    def fall_cameras(self) -> list[S.CameraView]:
        """The cameras actually being checked for falls, with the falls overlay."""
        if self.falls_worker is None:
            return []
        out: list[S.CameraView] = []
        for camera in self.registry.configs():
            if not self.falls_worker.serves(camera.id):
                continue
            view = self.camera_view(camera.id, feature="falls")
            if view is not None:
                out.append(view)
        return out

    def _expire_fall_clips(self) -> int:
        if self.fall_scenes is None:
            return 0
        days = self.config.storage.clip_retention_days
        return self.fall_scenes.expire(datetime.now(timezone.utc) - timedelta(days=days))

    def clip_for_fall(self, fall_id: str):
        """The video for one fall, or why there is not one. `(path, reason)`.

        The path is never taken from the request: the id is looked up and the
        stored path must sit inside the fall clip folder, the check
        `clip_for_weapon` makes.
        """
        if self.fall_scenes is None:
            return None, "The fall history is not available."
        scene = self.fall_scenes.get(fall_id)
        if scene is None:
            return None, f"no fall {fall_id!r}"
        if scene.clip_state != "saved" or scene.clip_path is None:
            return None, (scene.clip_reason or self._no_fall_clip_reason(scene)
                          or "There is no video for this fall.")
        root = self.config.storage.fall_clips_dir
        try:
            path = scene.clip_path.resolve()
            path.relative_to(root.resolve())
        except (OSError, ValueError):
            log.error("fall %s names a clip outside %s: %s", fall_id, root, scene.clip_path)
            return None, "That video is not where it should be, so it was not served."
        if not path.is_file():
            return None, "The video is no longer on disk."
        return path, ""

    @staticmethod
    def _no_fall_clip_reason(scene) -> str | None:
        if scene.clip_state == "saved":
            return None
        if scene.clip_state == "recording":
            return "Still recording — the video is saved when they get up or leave the camera."
        if scene.clip_state == "expired":
            return "Video no longer kept."
        if scene.clip_state == "none":
            return "No video was recorded for this fall."
        return None

    def _fall_clip(self, scene) -> S.Clip | None:
        """Same-origin and relative, for the reason `_weapon_clip` gives."""
        if not scene.playable:
            return None
        from vg.features.falls import MAX_CLIP_SECONDS

        return S.Clip(
            id=scene.id,
            url=f"/falls/{scene.id}/clip",
            # The video stops at two minutes; the entry may run far longer.
            duration_seconds=round(min(scene.seconds, MAX_CLIP_SECONDS), 1),
            starts_at=_instant(scene.started_at, self.clock),
        )

    # -- vehicle gate -------------------------------------------------------

    def _gate_cameras(self) -> list:
        """The configured gate cameras. Empty is a real answer."""
        return [c for c in self.registry.configs() if c.is_gate]

    def _gate_name(self, gate: int) -> str:
        """"Gate 2 - staff", from the camera names, or just "Gate 2".

        Built from configuration rather than stored: a gate is not an entity
        in this system, it is a number two cameras agree on.
        """
        for camera in self._gate_cameras():
            if camera.gate == gate and " - " in camera.name:
                return camera.name.split(" - ", 1)[0]
        return f"Gate {gate}"

    def _gate_directions(self) -> dict[int, set[str]]:
        """Which directions each gate has a camera for."""
        directions: dict[int, set[str]] = {}
        for camera in self._gate_cameras():
            directions.setdefault(camera.gate, set()).add(camera.direction)
        return directions

    def _pairing_available(self) -> bool:
        """Is there a gate with both an entry and an exit camera?

        Without one, an exit can never be matched to an entry, so "inside now"
        is not a number this engine can produce. P6-FR-012 forbids showing a
        paired figure with nothing to pair against, so this is what the page
        checks before printing one.
        """
        return any(len(d) > 1 for d in self._gate_directions().values())

    def _vehicles_state(self) -> tuple[S.DataState, str | None]:
        """Whether plates are being read, and if not, exactly why not.

        Four different nothings, and an operator can act on only some of them:
        no gate camera is theirs to fix, a model that would not load is not.
        Collapsing them into one empty list is what makes a page look broken
        when it is merely unconfigured.
        """
        if not self._gate_cameras():
            return (S.DataState.UNAVAILABLE,
                    "No camera is set up as a gate, so no plates are being "
                    "read. A gate camera needs a gate number and a direction.")
        if self.vehicles_worker is None:
            if self.vehicles_error:
                return S.DataState.UNAVAILABLE, self.vehicles_error
            return (S.DataState.UNAVAILABLE,
                    "Plate reading is not running, so no car is being read.")
        if self.vehicle_store is None:
            return (S.DataState.UNAVAILABLE,
                    "The vehicle log is not available, so nothing can be "
                    "shown even though the gate cameras are being watched.")
        return S.DataState.LIVE, None

    def vehicle_summary(self) -> S.GateSummary:
        """The six Live tiles.

        **Absent, never zero.** Every count here is optional, and when plates
        are not being read they are all left out and `reason` says why. A tile
        reading `0` is a measurement - "no car came through today" - and
        sending it for "we are not looking" is the exact untruth SC-010
        exists to prevent.
        """
        gates = {c.gate for c in self._gate_cameras()}
        state, reason = self._vehicles_state()
        registered = self.vehicle_store.count() if self.vehicle_store else None

        if state is not S.DataState.LIVE:
            return S.GateSummary(gates=len(gates), reason=reason,
                                 registered=registered,
                                 pairing_available=self._pairing_available())

        counts = self.vehicle_store.counts_since(self._start_of_day())
        pairing = self._pairing_available()
        reading, total, note = self._cameras_reading()
        return S.GateSummary(
            cameras_reading=reading,
            cameras_total=total,
            cameras_note=note,
            entered=counts["entered"],
            left=counts["left"] if pairing else None,
            # Only when an exit camera exists to pair against.
            inside=len(self.vehicle_store.inside(self._start_of_day()))
            if pairing else None,
            unknown=counts["unknown"],
            blacklist=counts["blacklist"],
            needs_review=counts["needs_review"],
            gates=len(gates),
            registered=registered,
            pairing_available=pairing,
            reason=None if pairing else (
                "No exit camera is configured, so no car can be matched to "
                "its exit. Cars leaving are not being counted."),
        )

    def _cameras_reading(self) -> tuple[int, int, str | None]:
        """How many gate cameras are actually being read, of those configured.

        A gate camera that is down is not reading plates, and the tile that
        says "3 of 4" is the one place that is visible at a glance. The note
        names which one and what it costs — an offline exit camera means cars
        leaving that way are not counted, so "still inside" is an over-count
        until it comes back, and an operator should be told that rather than
        left to infer it from a figure that looks fine.
        """
        cameras = self._gate_cameras()
        down: list[str] = []
        for camera in cameras:
            worker = self.registry.worker(camera.id) if self.registry else None
            if worker is None or worker.status != "ok":
                direction = camera.direction or "gate"
                down.append(f"{camera.name} ({direction})")

        if not down:
            return len(cameras), len(cameras), None

        missing = ", ".join(down)
        exits = any("exit" in name for name in down)
        note = (f"{missing} is offline, so plates are not being read there."
                if len(down) == 1 else
                f"{missing} are offline, so plates are not being read there.")
        if exits:
            note += (" Cars leaving that way are not being counted, so "
                     "\"inside now\" is an over-count until it is back.")
        return len(cameras) - len(down), len(cameras), note

    def _start_of_day(self) -> datetime:
        """Midnight, site-local, as UTC. The window every "today" count uses.

        The offset comes from the site's clock. It used to come from
        `getattr(self, "_offset", 0)`, an attribute nothing ever set - so the
        day always turned over at **UTC** midnight, which in Cairo is 3am. A
        car passing at 1am was counted against the day before, and "today"
        was three hours out for the first three hours of every day.
        """
        today = self._site_today()
        local_midnight = datetime(today.year, today.month, today.day,
                                  tzinfo=timezone.utc)
        return local_midnight - timedelta(
            minutes=self.clock.offset_minutes(local_midnight))

    def _day_bounds(self, day: str = "") -> tuple[datetime, datetime]:
        """Site-local midnight to midnight for one day, as UTC.

        Empty `day` means today, which is what every caller wanted before any
        day could be picked. A malformed date raises `ValueError` and the
        endpoint turns that into a 422 — silently falling back to today would
        answer a question nobody asked, and the operator would read yesterday's
        chart believing it was Tuesday's.
        """
        start = self._start_of_day()
        if day:
            wanted = date.fromisoformat(day)
            local_midnight = datetime(wanted.year, wanted.month, wanted.day,
                                      tzinfo=timezone.utc)
            start = local_midnight - timedelta(
                minutes=self.clock.offset_minutes(local_midnight))
        return start, start + timedelta(days=1)

    def vehicle_traffic(self, day: str = "") -> list[S.TrafficHour]:
        """One day's entries and exits by hour — the chart on Movements.

        Hours with nothing in them are absent rather than zero. A flat bar at
        3am is noise, and an empty list is the honest shape of a day when
        nothing drove through.
        """
        if self.vehicle_store is None:
            return []
        since, until = self._day_bounds(day)
        # The site's offset in MINUTES, handed to the store rather than
        # applied here. Shifting a UTC hour by `offset // 60` looks equivalent
        # and is an hour wrong for half the clock in any half-hour zone; the
        # store does it exactly. Same rule as every other rendered time on
        # this page: the site experienced it, so the site's clock names it.
        rows = self.vehicle_store.hourly(
            since, until, self.clock.offset_minutes(since))
        return [S.TrafficHour(hour=row["hour"], entered=row["entered"],
                              left=row["left"])
                for row in rows]

    def vehicle_passes(self, **filters) -> list[S.VehiclePass]:
        """The pass log, newest first."""
        if self.vehicle_store is None:
            return []
        limit = int(filters.pop("limit", 100) or 100)
        day = filters.pop("day", "")
        applied = {k: v for k, v in filters.items() if v not in (None, "")}
        if day:
            applied["since"], applied["until"] = self._day_bounds(day)
        records = self.vehicle_store.passes(limit=limit, **applied)
        return [self._to_wire_pass(p) for p in records]

    def _to_wire_pass(self, record) -> S.VehiclePass:
        return S.VehiclePass(
            id=record.id,
            at=_instant(record.at, self.clock),
            plate=record.plate,
            plate_display=record.plate_display,
            gate=record.gate,
            gate_name=self._gate_name(record.gate),
            direction=record.direction,
            status=record.status,
            confidence=max(0.0, min(1.0, record.confidence)),
            votes=record.votes,
            needs_review=record.needs_review,
            owner=record.owner_name,
            unit=record.unit,
            has_snapshot=record.has_snapshot,
            corrected_by=record.corrected_by,
        )

    def vehicle_cameras(self) -> list[S.CameraView]:
        """The gate cameras, each labelled with what it is configured to see.

        Not the whole roster - a camera with no gate number is not watching a
        gate, and listing it would imply the plates it cannot read.
        """
        out: list[S.CameraView] = []
        for camera in self._gate_cameras():
            view = self.camera_view(camera.id, feature="vehicles")
            if view is not None:
                out.append(view)
        return out

    def vehicle_reader(self) -> S.GateReaderNow:
        """What the reader is seeing now — every attempt, not just the wins.

        **The pass log cannot answer the question this does.** It contains
        successes by construction, so a gate that records nothing produces an
        empty log whether the camera is too far away, the model is failing, or
        nothing is running at all. Those need different fixes and this is the
        only place they look different.

        Deliberately assembled per request rather than pushed: the attempts
        already exist as a by-product of a worker that is running anyway, so
        this costs a dictionary lookup, and it stops entirely when the last
        person closes the page.
        """
        state, reason = self._vehicles_state()
        if state is not S.DataState.LIVE or self.vehicles_worker is None:
            # No cameras and no attempts, with the sentence that explains it.
            # The card renders `reason` in place of the table; an empty table
            # would read as "the reader is looking and finding nothing".
            return S.GateReaderNow(votes_needed=MIN_VOTES, reason=reason)

        worker = self.vehicles_worker
        reader = getattr(worker, "reader", None)
        cameras: list[S.GateReaderCamera] = []
        attempts: list[S.ReaderAttempt] = []

        for camera in self._gate_cameras():
            reading = worker.reading_now(camera.id)
            cameras.append(S.GateReaderCamera(
                camera_id=camera.id,
                camera_name=camera.name,
                gate=camera.gate,
                direction=camera.direction,
                # What is LOADED, never what was configured. A model that fell
                # back off its accelerated build says so here, on the page
                # where its work shows, rather than only on System Health.
                finder=getattr(reader, "plates_loaded", None)
                and reader.plates_loaded.stem or "unknown",
                reader=getattr(reader, "chars_loaded", None)
                and reader.chars_loaded.stem or "unknown",
                form=getattr(reader, "form", "unknown"),
                read_ms=worker.read_ms(camera.id),
                reading_display=reading[1] if reading else None,
                reading_votes=reading[2] if reading else 0,
                has_crop=reading is not None,
                reading_pass_id=reading[4] if reading else None,
                reading_plate=reading[5] if reading else None,
            ))
            for attempt in worker.attempts_on(camera.id):
                attempts.append(S.ReaderAttempt(
                    at=_instant(attempt.at, self.clock),
                    camera_id=attempt.camera_id,
                    camera_name=camera.name,
                    display=attempt.display,
                    confidence=attempt.confidence,
                    plausibility=attempt.plausibility,
                    width_px=attempt.width_px,
                    leader_display=attempt.leader_display,
                    votes=attempt.votes,
                    votes_needed=MIN_VOTES,
                ))

        # Newest first across every gate, so two cameras read as one stream of
        # what just happened rather than one camera's history then another's.
        attempts.sort(key=lambda a: a.at.utc, reverse=True)
        return S.GateReaderNow(cameras=cameras, attempts=attempts,
                               votes_needed=MIN_VOTES)

    def vehicle_crop(self, camera_id: str) -> bytes | None:
        """A JPEG of the plate this camera is reading right now, or None.

        Served rather than embedded in the reader payload: a picture polled
        every two seconds does not belong inside a JSON document that also
        carries the numbers, and the browser caches and cancels an <img> far
        better than it does a base64 blob.
        """
        if self.vehicles_worker is None:
            return None
        reading = self.vehicles_worker.reading_now(camera_id)
        return reading[0] if reading else None

    # -- movements ----------------------------------------------------------

    def _to_wire_visit(self, visit, now: datetime) -> S.VehicleVisit:
        return S.VehicleVisit(
            plate=visit.plate,
            plate_display=visit.plate_display,
            entered=_instant(visit.entered, self.clock),
            entry_gate=visit.entry_gate,
            left_at=_instant(visit.left_at, self.clock),
            exit_gate=visit.exit_gate,
            minutes=visit.minutes(now),
            entry_pass_id=visit.entry_pass_id,
            exit_pass_id=visit.exit_pass_id,
            entry_has_snapshot=visit.entry_has_snapshot,
            exit_has_snapshot=visit.exit_has_snapshot,
            owner=visit.owner_name,
            unit=visit.unit,
            category=visit.category,
            inferred=visit.inferred,
        )

    def vehicle_gates(self, day: str = "") -> list[S.GateTotals]:
        """Today, gate by gate.

        Every configured gate appears, including one nothing drove through:
        a gate camera that is watching and saw no car is a measurement, and
        leaving the row out would read as "not configured".

        `inside` is **absent** for a gate with no exit camera. There is
        nothing to pair an entry against, so any figure would be the count of
        cars that entered wearing the name of something else (P6-FR-012).
        """
        state, _ = self._vehicles_state()
        if state is not S.DataState.LIVE or self.vehicle_store is None:
            # Not reading plates. Zeros here would be indistinguishable from
            # a quiet morning; `vehicle_summary().reason` carries the words.
            return []

        counted = {row["gate"]: row
                   for row in self.vehicle_store.gates(*self._day_bounds(day))}
        directions = self._gate_directions()

        out: list[S.GateTotals] = []
        for gate in sorted(directions):
            row = counted.get(gate, {"entered": 0, "left": 0, "inside": 0})
            paired = len(directions[gate]) > 1
            out.append(S.GateTotals(
                gate=gate,
                name=self._gate_name(gate),
                entered=row.get("entered", 0),
                left=row.get("left", 0),
                inside=row.get("inside", 0) if paired else None,
                pairing_available=paired,
            ))
        return out

    def vehicles_inside(self) -> list[S.VehicleVisit]:
        """Cars that came in today and have not been seen leaving."""
        if self.vehicle_store is None:
            return []
        now = datetime.now(timezone.utc)
        return [self._to_wire_visit(v, now)
                for v in self.vehicle_store.inside(self._start_of_day())]

    def vehicle_visits(self, day: str = "") -> list[S.VehicleVisit]:
        """Today's completed visits, newest first.

        A visit closed by the car being seen entering *again* comes back with
        `inferred` set. It is still shown - the car did leave, nobody watched
        it - but it never claims to be an observed exit.
        """
        if self.vehicle_store is None:
            return []
        now = datetime.now(timezone.utc)
        return [self._to_wire_visit(v, now)
                for v in self.vehicle_store.visits(*self._day_bounds(day))
                if not v.inside]

    def delete_pass(self, pass_id: str, actor: str) -> bool:
        """Remove one pass from the log, with its photograph and plate crop.

        For the read that is plainly nonsense - a reflection, half a lorry, a
        plate that belongs to nobody. It is permanent: `visits` and "inside
        now" are computed from this table, so a row that stayed hidden would
        keep answering questions after somebody deleted it.

        **The audit entry is written first**, and names the plate as it was
        read. Somebody deleting a pass is a fact whether or not the delete
        succeeded, and the audit entry cannot itself be deleted - so the log
        can lose a row without the system losing the knowledge that it did.
        """
        store = self._need_register()
        record = store.pass_by_id(pass_id)
        if record is None:
            return False
        self._log(actor, "vehicle.pass.delete", record.plate,
                  f"{record.direction} at gate {record.gate}, "
                  f"read {record.confidence:.2f} over {record.votes} frames")
        return store.delete_pass(pass_id)

    def plate_alphabet(self) -> S.PlateAlphabet:
        """What a plate may contain, and what the reader mixes up.

        Straight from `platetext`, so the console's correction picker offers
        exactly the characters this model is measured to confuse rather than a
        copy that drifts the day the model changes.
        """
        confusions: dict[str, list[str]] = {}
        for a, b in platetext.CONFUSIONS:
            confusions.setdefault(a, []).append(b)
            confusions.setdefault(b, []).append(a)
        return S.PlateAlphabet(
            letters=list(platetext.LETTERS),
            common_letters=list(platetext.STRICT_LETTERS),
            digits=list("0123456789"),
            confusions=confusions,
        )

    def correct_plate(self, pass_id: str, plate: str,
                      actor: str) -> S.VehiclePass | None:
        """Somebody looked at the photograph and typed what it says.

        Audited before the write, like every other change here — and the
        entry names **both** plates, because "who changed this and from what"
        is the whole question anybody will ask of it later.
        """
        store = self._need_register()
        record = store.pass_by_id(pass_id)
        if record is None:
            return None
        self._log(actor, "vehicle.pass.correct", record.plate,
                  f"read as {platetext.transliterate(record.plate)}, "
                  f"corrected to {platetext.transliterate(platetext.normalize(plate))}")
        updated = store.set_plate(pass_id, plate, actor, self._site_today())
        return self._to_wire_pass(updated) if updated else None

    # -- alerts -------------------------------------------------------------

    def vehicle_alerts(self) -> list[S.GateAlert]:
        """Today's passes that are waiting for a person, newest first.

        **Derived, never stored.** An alert is a pass whose status needs
        somebody and which nobody has dismissed. Nothing here can fall out of
        step with the log, because there is nothing here but the log.

        Home's "Needs your attention" is built from this list too (spec 013),
        and the vehicles alert rule's three switches decide which reasons
        count there and in messages - all three on by default, the owner's
        choice. Acknowledging on Home takes an item off Home only; dismissing
        it here takes it off both, because it leaves this list.
        """
        if self.vehicle_store is None:
            return []

        since = self._start_of_day()
        dismissed = self.vehicle_store.dismissed_alerts(since)
        pairing = self._pairing_available()
        inside = ({v.plate for v in self.vehicle_store.inside(since)}
                  if pairing else set())

        out: list[S.GateAlert] = []
        for record in self.vehicle_store.passes(limit=200, since=since):
            if record.status == "known" or record.id in dismissed:
                continue

            near_display = near_owner = None
            if record.status == "unknown":
                candidates = self.vehicle_store.near_matches(record.plate)
                # Exactly one, or nothing. Two candidates is a coin toss, and
                # a wrong name against a stranger's car is worse than silence.
                if len(candidates) == 1:
                    near_display = candidates[0].plate_display
                    near_owner = candidates[0].owner_name

            expired_on = None
            if record.status == "expired":
                vehicle = self.vehicle_store.by_plate(record.plate)
                expired_on = vehicle.valid_until if vehicle else None

            out.append(S.GateAlert(
                pass_id=record.id,
                kind=record.status,
                at=_instant(record.at, self.clock),
                plate=record.plate,
                plate_display=record.plate_display,
                gate_name=self._gate_name(record.gate),
                owner=record.owner_name,
                permit_expired_on=expired_on,
                near_match_display=near_display,
                near_match_owner=near_owner,
                # Only claimable where an exit camera exists to pair against.
                # Without one, "and is still inside" is a guess.
                inside=pairing and record.plate in inside,
            ))
        return out

    def dismiss_alert(self, pass_id: str, actor: str,
                      action_taken: bool = False) -> bool:
        """Clear one alert, under the name of whoever cleared it.

        **The audit entry goes first**, as everywhere else here: somebody
        clearing an alert is a fact whether or not the write succeeds, and a
        dismissal that left no trace would be indistinguishable from the alert
        never having been raised.
        """
        store = self._need_register()
        record = store.pass_by_id(pass_id)
        if record is None:
            # KeyError, not False. "No such pass" and "somebody already dealt
            # with it" are different answers and the endpoint owes the caller
            # different ones - 404 against 409. Collapsing them into one
            # falsy return is how a second click reports the alert as missing.
            raise KeyError(pass_id)
        self._log(actor, "vehicle.alert.dismiss", record.plate,
                  f"{record.status} at gate {record.gate}, "
                  + ("resolved by acting on it" if action_taken
                     else "dismissed without acting"))
        return store.dismiss_alert(pass_id, actor, action_taken)

    def export_passes(self, actor: str, **filters) -> bytes:
        """The pass log as a spreadsheet.

        **The audit entry is written before the file is built**, not after.
        Somebody exporting the log is a fact whether or not the CSV was
        produced; logging afterwards means a failed export leaves no trace
        that anyone ever asked for it. Same rule as a track search.
        """
        import csv
        import io as _io

        store = self._need_register()
        applied = {k: v for k, v in filters.items() if v not in (None, "")}
        self._log(actor, "vehicle.export", "vehicle passes",
                  ", ".join(f"{k}={v}" for k, v in sorted(applied.items()))
                  or "no filter")

        limit = int(applied.pop("limit", 5000) or 5000)
        # `day` is the console's word for it; the store takes a window.
        #
        # This runs AFTER the audit entry, which is deliberate and not an
        # oversight: somebody asking for an export is a fact whether or not
        # the file was ever built, so even a request that fails validation
        # leaves a trace that it was made. `_day_bounds` raises ValueError on
        # a bad date and the endpoint turns that into a 422.
        day = applied.pop("day", "")
        if day:
            since, until = self._day_bounds(day)
            applied["since"], applied["until"] = since, until
        records = store.passes(limit=limit, **applied)

        buffer = _io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow([
            "at_local", "at_utc", "plate", "plate_display", "gate",
            "gate_name", "direction", "status", "owner", "unit",
            "confidence", "votes", "needs_review", "snapshot_kept",
        ])

        offset = 0
        for record in records:
            moment = _instant(record.at, self.clock)
            local = ""
            if moment is not None:
                offset = moment.tz_offset_minutes
                local = (moment.utc + timedelta(minutes=offset)).strftime(
                    "%Y-%m-%d %H:%M:%S")
            writer.writerow([
                local,
                record.at.isoformat(timespec="seconds"),
                record.plate,
                record.plate_display,
                record.gate,
                self._gate_name(record.gate),
                record.direction,
                record.status,
                record.owner_name or "",
                record.unit or "",
                f"{record.confidence:.3f}",
                record.votes,
                "yes" if record.needs_review else "no",
                # The row outlives its images. Saying which rows still have
                # one is the difference between "no photo" and "no idea".
                "yes" if record.has_snapshot else "no",
            ])

        writer.writerow([])
        writer.writerow(["rows", len(records)])
        writer.writerow(["exported_utc",
                         datetime.now(timezone.utc).isoformat(timespec="seconds")])
        writer.writerow(["timezone_offset_minutes", offset])
        return buffer.getvalue().encode("utf-8")

    # -- the register -------------------------------------------------------

    def _need_register(self):
        if self.vehicle_store is None:
            raise SubsystemUnavailable(
                "The vehicle register is not available, so it cannot be read "
                "or changed.")
        return self.vehicle_store

    def _to_wire_vehicle(self, record) -> S.RegisteredVehicle:
        return S.RegisteredVehicle(
            id=record.id,
            plate=record.plate,
            plate_display=record.plate_display,
            category=record.category,
            owner=record.owner_name,
            phone=record.phone,
            unit=record.unit,
            car_make=record.car_make,
            car_colour=record.car_colour,
            valid_until=record.valid_until,
            notes=record.notes,
            # Computed here rather than stored: a stored flag needs a nightly
            # job to stay true and is wrong between midnight and whenever it
            # runs.
            expired=record.expired_on(self._site_today()),
        )

    def vehicle_register(self, query: str = "",
                         category: str = "") -> list[S.RegisteredVehicle]:
        if self.vehicle_store is None:
            return []
        return [self._to_wire_vehicle(v)
                for v in self.vehicle_store.search(query, category)]

    def add_vehicle(self, body: S.VehicleRegistration,
                    actor: str) -> S.RegisteredVehicle:
        """Register a car. Takes effect at the gates on its next pass."""
        store = self._need_register()
        self._log(actor, "vehicle.add", body.plate, body.category)
        record = store.add(
            plate=body.plate, owner_name=body.owner, phone=body.phone,
            unit=body.unit, category=body.category, car_make=body.car_make,
            car_colour=body.car_colour, valid_until=body.valid_until,
            notes=body.notes,
        )
        return self._to_wire_vehicle(record)

    def edit_vehicle(self, vehicle_id: str, body: S.VehicleRegistration,
                     actor: str) -> S.RegisteredVehicle | None:
        store = self._need_register()
        if store.vehicle(vehicle_id) is None:
            return None
        self._log(actor, "vehicle.edit", body.plate, body.category)
        record = store.update(
            vehicle_id, plate=body.plate, owner_name=body.owner,
            phone=body.phone, unit=body.unit, category=body.category,
            car_make=body.car_make, car_colour=body.car_colour,
            valid_until=body.valid_until, notes=body.notes,
        )
        return self._to_wire_vehicle(record) if record else None

    def remove_vehicle(self, vehicle_id: str, actor: str) -> bool:
        """Delete a register entry. **Its passes are kept.**"""
        store = self._need_register()
        record = store.vehicle(vehicle_id)
        if record is None:
            return False
        self._log(actor, "vehicle.remove", record.plate,
                  record.owner_name or "no owner recorded")
        return store.remove(vehicle_id)

    def last_import(self) -> S.VehicleImportRun | None:
        """The most recent register import, or None if there has never been one."""
        if self.vehicle_store is None:
            return None
        run = self.vehicle_store.last_import_run()
        if run is None:
            return None
        return S.VehicleImportRun(
            at=_instant(run["at"], self.clock), added=run["added"],
            updated=run["updated"], skipped=run["skipped"],
            rejected=run["rejected"], by_who=run["by_who"],
        )

    def import_vehicles(self, filename: str, data: bytes,
                        actor: str) -> S.VehicleImportResult:
        """Load a spreadsheet. Every refused row comes back with its reason."""
        from vg.events import vehicles as ve

        store = self._need_register()
        self._log(actor, "vehicle.import", filename, f"{len(data)} bytes")

        if filename.lower().endswith((".xlsx", ".xlsm")):
            rows = ve.read_xlsx(data)
        else:
            rows = ve.read_csv(data)

        result = store.import_rows(rows, by_who=actor)
        return S.VehicleImportResult(
            added=result["added"], updated=result["updated"],
            skipped_duplicates=result["skipped_duplicates"],
            problems=result["problems"],
        )

    def review_weapon(self, detection_id: str, review: S.WeaponReview,
                      reviewer: str | None = None) -> S.WeaponDetection | None:
        """A person decides, and the people who were told hear the answer.

        Since spec 013 (the owner's decision of 11 Sep 2026) the detector's
        one fan-out is a message marked "awaiting review — not yet confirmed
        by a person", sent when the entry opens. This verdict sends the
        second, to exactly the people the first went to, naming who decided —
        so nobody is left holding a scare. Nothing locks, calls or acts on its
        own: a message is the only thing that hangs from detection, and a
        person still decides.

        **The audit entry is written first**, before the verdict it
        records. Somebody pressing Confirm is a fact whether or not the
        write behind it succeeded; logging afterwards means a failed write
        leaves no trace that anyone ever looked at this detection.

        `reviewer` is the signed-in account, passed by the endpoint.
        `review.actor` is ignored: a caller must not be able to record a
        verdict under somebody else's name.

        None means there is nothing here awaiting a decision — either the
        id is unknown or somebody has already decided. Both are a 404 with
        words on it.
        """
        who = reviewer or "unknown"
        self._log(who, f"weapon.{review.verdict.value}", detection_id,
                  review.reason)

        if self.weapon_scenes is None:
            return None
        if not self.weapon_scenes.review(
            detection_id, review.verdict.value, who,
            datetime.now(timezone.utc), review.reason,
        ):
            return None

        scene = self.weapon_scenes.get(detection_id)
        if scene is None:  # pragma: no cover - the row was just updated
            return None
        if self.alerts is not None:
            # The verdict is recorded whatever happens here; a sender that
            # cannot take the follow-up costs the message, never the verdict.
            try:
                self.alerts.verdict(scene.id, scene.camera_id, review.verdict.value,
                                    who, datetime.now(timezone.utc),
                                    since=scene.started_at)
            except Exception:
                log.exception("knife %s: the verdict message could not be queued",
                              detection_id[:8])
        # Rebuilt through the same mapper the list uses, so a reviewed
        # entry can never render differently from how the list will show it
        # a moment later.
        for entry in self.weapons(scene.started_at, None):
            if entry.id == detection_id:
                return entry
        return None  # pragma: no cover - unreachable, the row exists

    def clip_for_weapon(self, detection_id: str):
        """The video for one detection, or why there is not one.

        Returns `(path, reason)` — exactly one is set. The endpoint turns a
        reason into a 404 with those words in it, so every refusal says what
        happened rather than "not found".

        **The path is never taken from the request.** The id is looked up, the
        stored path is checked to be inside the knife clip directory, and only
        then is anything opened. A row is data like any other; a wrong one must
        not become a way to read the disk.
        """
        if self.weapon_scenes is None:
            return None, "The knife log is not available."

        scene = self.weapon_scenes.get(detection_id)
        if scene is None:
            return None, f"no detection {detection_id!r}"
        if scene.clip_state != "saved" or scene.clip_path is None:
            return None, (
                scene.clip_reason
                or self._no_weapon_clip_reason(scene)
                or "There is no video for this detection."
            )

        root = self.config.storage.weapon_clips_dir
        try:
            path = scene.clip_path.resolve()
            path.relative_to(root.resolve())
        except (OSError, ValueError):
            log.error("knife scene %s names a clip outside %s: %s",
                      detection_id, root, scene.clip_path)
            return None, "That video is not where it should be, so it was not served."

        if not path.is_file():
            # Rule 4: never claim a file that is not there. A row can outlive
            # its file — a disk wiped by hand, a folder moved — and the honest
            # answer is that it is gone, not a 500 from a failed open.
            return None, "The video is no longer on disk."

        return path, ""

    @staticmethod
    def _no_weapon_clip_reason(scene) -> str | None:
        """A sentence for every state that has no file, so no control is bare."""
        if scene.clip_state == "saved":
            return None
        if scene.clip_state == "recording":
            return "Still recording — the video is saved when the knife leaves view."
        if scene.clip_state == "expired":
            return "Video no longer kept."
        if scene.clip_state == "none":
            return "No video was recorded for this detection."
        return None

    def _weapon_clip(self, scene) -> S.Clip | None:
        """The playable video, and only when there genuinely is one.

        The URL is **same-origin and relative**. A `<video src>` cannot send an
        Authorization header, so an absolute engine URL would play for nobody —
        that is exactly what made the camera streams go black last cycle.
        """
        if not scene.playable:
            return None
        return S.Clip(
            id=scene.id,
            url=f"/weapons/{scene.id}/clip",
            duration_seconds=round(scene.seconds, 1),
            starts_at=_instant(scene.started_at, self.clock),
        )

    def sources(self) -> list[S.CameraSource]:
        """The configured cameras, with their true status.

        Built through `_source_view` rather than inline, so the list, an add
        and an edit cannot describe the same camera differently. They did:
        this method never learnt about `features`, `faces` or `gate`, so a
        camera the console had just set up read back as having no features at
        all.
        """
        return [
            self._source_view(worker.config)
            for worker in self.registry.workers.values()
        ] + [
            self._source_view(cam)
            for cam in self.registry.disabled.values()
        ]

    # -- people counting ----------------------------------------------------

    #: The place that means "add every area up". Not an area itself, so it
    #: never appears on the plan — only in the picker.
    ALL_PLACES = "All"

    def count(self, place: str, window: str) -> S.CountResult:
        """How many people are in each area, right now.

        Built from the configured areas alone. It used to start from
        `MockStore.count()` and paint real numbers over the demo ones, which
        left every area nobody watches sitting on the plan with an invented
        headcount beside it. `live` marked the difference, but a number on a
        plan is read long before the flag beside it is.

        An area with no camera measuring it now reports no count rather than a
        plausible one. "Right now" is still the only honest window: there is
        real history once `AreaCountStore` has recorded some, and an empty
        chart saying so before that.
        """
        counts = self._area_counts()
        names = self.areas()

        # A simple grid, because engine.yaml carries no floor-plan geometry.
        # Overlapping rectangles at a fixed point were worse: several areas
        # stacked on one spot read as a single room.
        areas: list[S.CountArea] = []
        for i, name in enumerate(names):
            capacity = self._capacity(name, 0)
            measured = name in counts
            col, row = i % 4, i // 4
            areas.append(S.CountArea(
                id=name.lower().replace(" ", "-"),
                name=name,
                count=counts.get(name, 0),
                capacity=capacity,
                x=min(0.78, 0.04 + col * 0.24), y=min(0.74, 0.06 + row * 0.24),
                w=0.18, h=0.18,
                severity=self._fill_severity(counts.get(name, 0), capacity),
                # False means nothing measured this area, so its 0 is "we
                # cannot see", not "nobody is there".
                live=measured,
            ))

        uncovered = [a.name for a in areas if not a.live]
        if place == self.ALL_PLACES:
            selected_name = self.ALL_PLACES
            # Sum only the areas actually being measured. An area with no
            # camera contributes nothing rather than a zero, because "nobody
            # there" and "we cannot see" must not add up to the same total.
            selected_count = sum(a.count for a in areas if a.live)
            selected_cap = sum(a.capacity for a in areas if a.live)
            # ANY, not ALL. The total really was measured — it is just
            # incomplete, which is what `uncovered` below says. Requiring every
            # area to be live made a real headcount label itself "not
            # measured" the moment one camera was off.
            live = any(a.live for a in areas)
        else:
            selected = next((a for a in areas if a.name == place), None)
            if selected is None:
                selected_name, selected_count, selected_cap, live = place, 0, 0, False
            else:
                selected_name, selected_count = selected.name, selected.count
                selected_cap, live = selected.capacity, selected.live

        bars, bars_title, bars_note = self._history(window)

        metrics = [
            S.Metric(key="here", label="People here",
                     value=selected_count if live else None,
                     unit="count" if live else "text",
                     text=None if live else "No camera is counting this area"),
            S.Metric(key="capacity", label="Safe capacity", value=selected_cap),
        ]
        if selected_cap and live:
            metrics.append(S.Metric(key="fill", label="Of capacity",
                                    value=selected_count / selected_cap,
                                    unit="percent"))
        else:
            metrics.append(S.Metric(
                key="fill", label="Of capacity", unit="text",
                text="No capacity set for this area" if live
                else "Nothing is measuring this area"))
        metrics.append(S.Metric(
            key="source", label="Source", unit="text",
            text="Measured live" if live else "Not measured"))
        # Rule 5: never claim precision the code lacks. A campus total that
        # quietly omits three rooms is not a campus total.
        if live and uncovered and place == self.ALL_PLACES:
            metrics.append(S.Metric(
                key="coverage", label="Not included", unit="text",
                text=f"No camera is counting {', '.join(sorted(uncovered))}"))
        if bars_note:
            metrics.append(S.Metric(key="history", label="History",
                                    unit="text", text=bars_note))

        return S.CountResult(
            place=selected_name,
            count=selected_count,
            capacity=selected_cap or None,
            measured_at=_instant(datetime.now(timezone.utc), self.clock),
            # Areas are SUMMED across their cameras. Nothing de-duplicates a
            # person standing where two cameras overlap, so claiming otherwise
            # would be a straight overstatement. Real de-duplication needs
            # cross-camera identity, which is the tracking feature's job.
            deduplicated=False,
            metrics=metrics,
            bars=bars,
            bars_title=bars_title,
            areas=areas,
            # No `or super().cameras`: an area with no camera shows no tile.
            cameras=[
                v for v in (self.camera_view(cid, feature="counting")
                            for cid in self._cameras_for(selected_name))
                if v is not None
            ],
        )

    def _history(self, window: str):
        """Real hour/day buckets, split by area.

        Returns `([], None, note)` when nothing has been recorded yet. An empty
        chart that says "recording started today" is honest; the old fixtures
        looked like a week of history the system never had.
        """
        if window == "Right now":
            return [], None, None
        if self.counts is None:
            return [], None, "No headcount history is being recorded."

        if window == "Today by hour":
            # The site's today, not the server's. Rows are filed under the
            # site's date, so between midnight and 03:00 Cairo a UTC date
            # asked for yesterday's chart and got an empty one.
            buckets = self.counts.by_hour(self.clock.today())
            title = "Today by hour"
        elif window == "This week by day":
            buckets = self.counts.by_day(7)
            title = "This week by day"
        else:
            return [], None, None

        live_areas = set(self._area_counts())
        bars = [
            S.CountBar(
                label=label,
                value=sum(p.people for p in points),
                parts=[
                    S.CountBarPart(name=p.area, value=p.people,
                                   live=p.area in live_areas)
                    for p in sorted(points, key=lambda x: x.area)
                ],
            )
            for label, points in buckets.items()
        ]
        note = None if bars else "Nothing recorded yet - history starts from now."
        return bars, title, note

    def _area_counts(self) -> dict[str, int]:
        """Live headcount per area, summed over the cameras watching it.

        Only areas with at least one camera that has actually measured
        something appear. A camera that is down contributes nothing rather than
        a zero — "nobody there" and "we cannot see" are different claims.
        """
        if self.people_worker is None:
            return {}

        totals: dict[str, int] = {}
        for camera in self.registry.configs():
            if not camera.area or not camera.enabled:
                continue
            seen = self.people_worker.count_on(camera.id)
            if seen is None:
                continue
            totals[camera.area] = totals.get(camera.area, 0) + seen
        return totals

    def _cameras_for(self, area: str) -> list[str]:
        if area == self.ALL_PLACES:
            return [c.id for c in self.registry.configs() if c.enabled]
        return [c.id for c in self.registry.configs() if c.area == area and c.enabled]

    def _capacity(self, area: str, fallback: int) -> int:
        """Safe capacity from engine.yaml, or 0 when nobody has set one.

        0 is not "no room" - it is "unknown", and the wire treats it that way:
        the page shows the headcount and no percentage. Dividing by a made-up
        denominator produces a confident figure that means nothing, which is
        worse than showing no figure at all.
        """
        configured = self.config.areas.get(area)
        if configured is not None:
            return configured.capacity
        # An area the config has never heard of keeps whatever the fixtures
        # said, so the demo areas still render as before.
        return fallback

    @staticmethod
    def _fill_severity(count: int, capacity: int) -> S.Severity:
        if not capacity:
            return S.Severity.INFO
        fill = count / capacity
        return (S.Severity.CRITICAL if fill > 0.9
                else S.Severity.WARN if fill > 0.7
                else S.Severity.INFO)


    def areas(self) -> list[str]:
        # From the live registry, so an area introduced by a camera added at
        # runtime is immediately offered in the dropdowns.
        return sorted({c.area for c in self.registry.configs() if c.area})

    # -- not built yet ------------------------------------------------------
    #
    # These override MockStore purely to stop it answering. Each is a feature
    # the console has a page for and the engine cannot yet serve, so the page
    # gets nothing plus a reason from `capabilities()` rather than a plausible
    # row somebody might act on.
    #
    # A banner saying "not available" above a list of three invented breaches
    # would be worse than either on its own: the page would contradict itself,
    # and the rows are the half people believe.
    #
    # When one of these is built, delete its stub here and flip its entry in
    # `capabilities()`. Until then this list IS the to-do list.

    def users(self) -> list[S.User]:
        """The real accounts, from the auth database.

        This used to return nothing with a note saying there was no auth at
        all. There is now (P2), so returning nothing would be the opposite
        lie: an operator would read "no accounts" on a console they had just
        signed in to.

        No password hash and no session token cross this boundary. The page
        shows who can sign in, not how.
        """
        if self.users_store is None:
            return []
        locks = self.users_store.active_locks()
        return [
            S.User(id=u.id, name=u.name, email=u.email, role=u.role,
                   disabled=u.disabled,
                   locked_until=_instant(locks.get(email_key(u.email)), self.clock))
            for u in self.users_store.users()
        ]

    def unlock_user(self, user_id: str, actor: str, where: str) -> S.User | None:
        """Lift a sign-in lock now (spec 020). Audited before the write."""
        if self.users_store is None:
            raise SubsystemUnavailable(
                "sign-in is not running, so there are no accounts to unlock")
        target = next((u for u in self.users_store.users() if u.id == user_id), None)
        if target is None:
            return None
        self._log(actor, "signin.unlock", target.email, where)
        self.users_store.unlock(target.email)
        return next(u for u in self.users() if u.id == user_id)

    def update_user(self, user_id: str, body: S.UserEdit,
                    actor: str) -> S.User | None:
        """Change an account. Audited first; the last administrator is kept.

        `LastAdminError` passes through for the route to answer 409. The
        entry is written before the store is touched, so a refused or failed
        change is still a logged attempt.
        """
        if self.users_store is None:
            raise SubsystemUnavailable(
                "sign-in is not running, so there are no accounts to change")
        before = next((u for u in self.users_store.users() if u.id == user_id), None)
        if before is None:
            return None
        changes = [
            f"{field} {old!r} → {new!r}"
            for field, old, new in (
                ("name", before.name, body.name),
                ("role", before.role, body.role.value if body.role else None),
                ("disabled", before.disabled, body.disabled),
            )
            if new is not None and new != old
        ]
        self._log(actor, "user.edit", before.email,
                  "; ".join(changes) or "no change")
        u = self.users_store.update_user(
            user_id, name=body.name,
            role=body.role.value if body.role else None,
            disabled=body.disabled)
        if u is None:
            return None
        return S.User(id=u.id, name=u.name, email=u.email, role=u.role,
                      disabled=u.disabled)

    def audit(self, limit: int) -> list[S.AuditEntry]:
        # Real entries, from this process. They are lost on restart and
        # `capabilities()` says so, but what is here actually happened.
        return super().audit(limit)

    def _roster_name(self, camera_id: str | None) -> str | None:
        """The name the operator gave a camera, from the running roster.

        The roster, not engine.yaml: a camera added in Settings has a name too,
        and it is the name every page shows. Unknown ids come back as
        themselves rather than vanishing.
        """
        if not camera_id:
            return None
        for config in self.registry.configs():
            if config.id == camera_id:
                return config.name
        return self._camera_name(camera_id)

    def attention(self) -> list[S.AttentionItem]:
        """Home's "Needs your attention": the real open items, newest first.

        Derived on every read from the stores that already hold them - knife
        entries awaiting a verdict, today's restricted-zone scenes (running or
        ended: a ten-second breach must not vanish before anybody looked),
        today's gate alerts, cameras dark past the window - each kind shown
        only while its rule has In-app on, minus what somebody acknowledged.
        No second copy exists to drift from the Weapons, Zones or Vehicles
        pages. It needs the alert database and nothing else - not the sender,
        so switching sending off never empties Home.
        """
        from vg.alerts.events import camera_item_id, offline_cameras

        if self.alerts_store is None:
            return []
        try:
            rules = self.alerts_store.rules()
            acked = self.alerts_store.acked()
        except sqlite3.Error:
            log.exception("the alert database could not be read for Home")
            return []

        def shown(kind: str) -> bool:
            rule = rules.get(kind)
            return bool(rule and rule.in_app)

        items: list[S.AttentionItem] = []

        if shown("weapon") and self.weapon_scenes is not None:
            for scene in self.weapon_scenes.pending():
                items.append(S.AttentionItem(
                    id=f"weapon:{scene.id}", kind="weapon",
                    at=_instant(scene.started_at, self.clock),
                    severity=S.Severity.CRITICAL,
                    title=self._roster_name(scene.camera_id) or scene.camera_id,
                    detail="", target="weapons", target_id=scene.id,
                    note=note("attention.weapon",
                              confidence=round(scene.peak_confidence * 100)),
                ))

        # Somebody down long enough to count, and still down. Not behind an
        # alert rule: a fall is never SENT anywhere - the owner's design says
        # so - and the one place it is announced is here, on the console, at
        # once. Taken off the list by getting up, or by "not a fall".
        if self.fall_scenes is not None:
            for scene in self.fall_scenes.running():
                if not scene.alerted or scene.verdict == "not_a_fall":
                    continue
                items.append(S.AttentionItem(
                    id=f"fall:{scene.id}", kind="fall",
                    at=_instant(scene.started_at, self.clock),
                    severity=S.Severity.CRITICAL,
                    title=self._roster_name(scene.camera_id) or scene.camera_id,
                    detail="", target="falls", target_id=scene.id,
                    note=note("attention.fall"),
                ))

        if shown("intrusion") and self.scenes is not None:
            since = self._start_of_day()
            for scene in self.scenes.recent(since_days=1):
                if scene.started_at < since:
                    continue
                items.append(S.AttentionItem(
                    id=f"intrusion:{scene.id}", kind="intrusion",
                    at=_instant(scene.started_at, self.clock),
                    severity=S.Severity.WARN,
                    title=self._roster_name(scene.camera_id) or scene.camera_id,
                    detail="", target="intrusion", target_id=scene.id,
                    note=note("attention.intrusion"),
                ))

        if shown("vehicles"):
            rule = rules["vehicles"]
            for alert in self.vehicle_alerts():
                if not rule.reason_on(alert.kind):
                    continue
                if alert.kind == "blacklist":
                    said = note("attention.vehicles.blacklist", gate=alert.gate_name)
                elif alert.kind == "expired":
                    said = note("attention.vehicles.expired", gate=alert.gate_name)
                else:
                    said = note("attention.vehicles.unknown", gate=alert.gate_name)
                items.append(S.AttentionItem(
                    id=f"vehicles:{alert.pass_id}", kind="vehicles", at=alert.at,
                    severity=(S.Severity.CRITICAL if alert.kind == "blacklist"
                              else S.Severity.WARN),
                    title=alert.plate_display, detail="", target="vehicles",
                    target_id=alert.pass_id, note=said,
                ))

        if shown("camera"):
            now = datetime.now(timezone.utc)
            dark = offline_cameras(self.registry.workers, now,
                                   self.config.alerts.camera_offline_minutes,
                                   self._started_at)
            for camera_id, since in dark.items():
                items.append(S.AttentionItem(
                    id=camera_item_id(camera_id, since), kind="camera",
                    at=_instant(since, self.clock), severity=S.Severity.WARN,
                    title=self._roster_name(camera_id) or camera_id,
                    detail="", target="system", target_id=camera_id,
                    note=note("attention.camera",
                              minutes=int((now - since).total_seconds() // 60)),
                ))

        items = [item for item in items if item.id not in acked]
        items.sort(key=lambda item: item.at.utc, reverse=True)
        return items

    def acknowledge(self, item_id: str, actor: str) -> S.AttentionItem | None:
        """Somebody on duty has dealt with a Home item. Deletes nothing.

        None when the item is not in the current list - unknown, or already
        acknowledged. Otherwise **the audit entry goes first**, as with every
        write here, and then the one row that takes the item off Home.
        """
        item = next((i for i in self.attention() if i.id == item_id), None)
        if item is None:
            return None
        self._log(actor, "attention.ack", item_id, item.title)
        self.alerts_store.ack(item_id, actor, datetime.now(timezone.utc))
        return item.model_copy(update={"acknowledged": True})

    def _attention_state(self) -> tuple[S.DataState, str | None]:
        """Home's list needs the alert database and nothing else.

        LIVE carries no reason - a live capability never explains itself - so
        a missing provider key is said on System Health and Settings instead.
        """
        if self.alerts_store is None:
            return (S.DataState.UNAVAILABLE,
                    self.alerts_error
                    or "The alert database is not available, so Home cannot list "
                       "what needs attention. Detection is unaffected.")
        return S.DataState.LIVE, None

    # -- alert delivery (spec 013) -------------------------------------------
    #
    # Recipients, rules and the delivery log live in `alerts_store`; the
    # console asks and the engine keeps (P9-FR-016). Every write is audited
    # BEFORE it happens and is administrator-only by path. No method here
    # returns a secret in any form: channels report which .env names are
    # missing, never a value.

    def _need_alerts(self):
        if self.alerts_store is None:
            raise SubsystemUnavailable(
                self.alerts_error
                or "The alert database is not available, so alerts cannot be "
                   "set up or listed. Detection is unaffected.")
        return self.alerts_store

    def _sending(self) -> tuple[str, str | None]:
        """running | off | failed, and why when it is not running."""
        if not self.config.alerts.enabled:
            return "off", None
        if self.alerts is None or self.alerts.dead:
            return "failed", self.alerts_error or "the alert sender is not running"
        return "running", None

    @staticmethod
    def _wire_rule(rule) -> S.AlertRule:
        return S.AlertRule(
            kind=rule.kind, in_app=rule.in_app, email=rule.email,
            vehicle_blacklist=rule.vehicle_blacklist,
            vehicle_unknown=rule.vehicle_unknown,
            vehicle_expired=rule.vehicle_expired,
        )

    def _wire_recipient(self, person) -> S.Recipient:
        return S.Recipient(
            id=person.id, channel=person.channel, destination=person.destination,
            name=person.name, language=person.language, enabled=person.enabled,
            created_at=_instant(person.created_at, self.clock),
        )

    def _wire_delivery(self, row) -> S.DeliveryRow:
        return S.DeliveryRow(
            id=row.id, at=_instant(row.at, self.clock), kind=row.kind,
            channel=row.channel, recipient_name=row.recipient_name,
            outcome=row.outcome, reason=row.reason,
            provider_reason=row.provider_reason, provider_id=row.provider_id,
            attempts=row.attempts,
        )

    @staticmethod
    def _masked(destination: str) -> str:
        from vg.alerts.store import mask_destination

        return mask_destination(re.sub(r"[\s\-().]", "", str(destination or "")))

    def alert_settings(self) -> S.AlertSettings:
        from vg.alerts import catalogue, providers
        from vg.alerts.events import CHANNELS, report_state

        store = self._need_alerts()
        try:
            rules = store.rules()
            people = store.recipients()
        except sqlite3.Error as exc:
            raise SubsystemUnavailable(
                f"The alert database could not be read ({exc}).") from exc
        sending, error = self._sending()
        hours = self.config.hours
        today = date.fromisoformat(self.clock.today())
        return S.AlertSettings(
            sending=sending, sending_error=error,
            rules=[self._wire_rule(rule) for rule in rules.values()],
            recipients=[self._wire_recipient(person) for person in people],
            channels=[
                S.ChannelStatus(channel=channel,
                                configured=not providers.missing_env(channel),
                                missing=providers.missing_env(channel))
                for channel in CHANNELS
            ],
            unreached=[
                S.Unreached(kind=kind, channel=channel)
                for kind, rule in rules.items() for channel in CHANNELS
                if rule.channel_on(channel)
                and not any(p.channel == channel and p.enabled for p in people)
            ],
            report=S.ReportStatus(
                time=f"{self.config.alerts.report_time:%H:%M}",
                state=report_state(today, hours.term_from, hours.term_to),
                term_from=hours.term_from, term_to=hours.term_to,
            ),
            camera_offline_minutes=self.config.alerts.camera_offline_minutes,
            console_url_set=bool(self.config.alerts.console_url),
            arabic_reviewed=catalogue.ARABIC_REVIEWED,
        )

    def update_rule(self, kind: str, update: S.AlertRuleUpdate,
                    actor: str) -> S.AlertRule:
        store = self._need_alerts()
        changes = update.model_dump(exclude_unset=True, exclude_none=True)
        self._log(actor, "alerts.rule", kind,
                  ", ".join(f"{name} {'on' if on else 'off'}"
                            for name, on in sorted(changes.items())) or "no change")
        return self._wire_rule(store.update_rule(kind, **changes))

    def add_recipient(self, body: S.RecipientCreate, actor: str) -> S.Recipient:
        store = self._need_alerts()
        self._log(actor, "alerts.recipient.add", body.name.strip(),
                  f"{body.channel} {self._masked(body.destination)}")
        person = store.add_recipient(body.channel, body.destination, body.name,
                                     body.language, body.enabled)
        return self._wire_recipient(person)

    def edit_recipient(self, recipient_id: str, body: S.RecipientUpdate,
                       actor: str) -> S.Recipient:
        store = self._need_alerts()
        person = store.recipient(recipient_id)
        if person is None:
            raise KeyError(recipient_id)
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        detail = ", ".join(
            f"destination {self._masked(value)}" if name == "destination"
            else f"{name} {value}" for name, value in sorted(changes.items()))
        self._log(actor, "alerts.recipient.edit", person.name, detail or "no change")
        return self._wire_recipient(store.update_recipient(recipient_id, **changes))

    def remove_recipient(self, recipient_id: str, actor: str) -> None:
        store = self._need_alerts()
        person = store.recipient(recipient_id)
        if person is None:
            raise KeyError(recipient_id)
        self._log(actor, "alerts.recipient.remove", person.name,
                  f"{person.channel} {self._masked(person.destination)}")
        if not store.remove_recipient(recipient_id):
            raise KeyError(recipient_id)

    def test_send(self, recipient_id: str, actor: str) -> S.DeliveryRow:
        """The one way an administrator proves the wiring on a real phone.

        Audited first; sent whatever the rules and the recipient's switch say.
        """
        store = self._need_alerts()
        person = store.recipient(recipient_id)
        if person is None:
            raise KeyError(recipient_id)
        self._log(actor, "alerts.test", person.name,
                  f"{person.channel} {self._masked(person.destination)}")
        if self.alerts is None:
            raise SubsystemUnavailable(
                "Sending is switched off in engine.yaml, so no test can be sent."
                if not self.config.alerts.enabled else
                (self.alerts_error or "The alert sender is not running")
                + ", so no test can be sent.")
        row_id = self.alerts.test_send(recipient_id)
        return self._wire_delivery(store.row(row_id))

    def deliveries(self, limit: int) -> S.DeliveryLog:
        """The log, or why it cannot be read - never a 5xx."""
        if self.alerts_store is None:
            return S.DeliveryLog(
                available=False,
                reason=self.alerts_error or "The alert database is not available.")
        try:
            rows = self.alerts_store.recent(max(1, min(int(limit), 200)))
        except sqlite3.Error as exc:
            return S.DeliveryLog(available=False,
                                 reason=f"The delivery log could not be read ({exc}).")
        return S.DeliveryLog(available=True,
                             rows=[self._wire_delivery(row) for row in rows])

    def _alerts_stage(self) -> S.PipelineStage:
        """Rule 8 and SC-005: whether alerts can leave the building, and why not.

        A missing key is said HERE and on Settings - not as a reason on the
        `attention` capability, because a live capability never explains
        itself and Home's list works without any key at all.
        """
        from vg.alerts import providers
        from vg.alerts.events import CHANNELS

        def stage(detail: str, healthy: bool) -> S.PipelineStage:
            return S.PipelineStage(
                key="alerts", name="Alert sending", detail=detail, healthy=healthy,
                severity=S.Severity.INFO if healthy else S.Severity.WARN,
                restartable=False)

        if self.alerts_store is None:
            return stage(
                f"{self.alerts_error or 'The alert database is not available'}"
                " - nothing can be listed or sent. Detection is unaffected.", False)
        if not self.config.alerts.enabled:
            return stage("Switched off in engine.yaml - nothing is sent by email. "
                         "The Home list still works.", True)
        if self.alerts is None or self.alerts.dead:
            return stage(
                f"{self.alerts_error or 'The alert sender is not running'} - nothing "
                "is sent by email. Detection is unaffected.", False)
        try:
            rules = self.alerts_store.rules()
            counts = self.alerts_store.counts_since(
                datetime.now(timezone.utc) - timedelta(hours=24))
        except sqlite3.Error as exc:
            return stage(f"The alert database could not be read ({exc}). "
                         "Detection is unaffected.", False)

        label = {"email": "email"}
        used = [c for c in CHANNELS if any(r.channel_on(c) for r in rules.values())]
        broken = [c for c in used if providers.missing_env(c)]
        if broken:
            names: list[str] = []
            for channel in broken:
                for name in providers.missing_env(channel):
                    if name not in names:
                        names.append(name)
            return stage(
                f"No {', '.join(names)} is set, so "
                f"{' and '.join(label[c] for c in broken)} cannot be sent. "
                "Detection is unaffected.", False)
        if not used:
            return stage("Running - email is not switched on for any alert, so "
                         "only the Home list is used.", True)
        return stage(f"Running - {counts.get('sent', 0)} sent, "
                     f"{counts.get('failed', 0)} failed in the last 24 hours.", True)

    #: How soon before the end the certificate row turns amber.
    CERT_WARN_DAYS = 30

    def _certificate_stage(self) -> S.PipelineStage:
        """The site certificate: which names it covers and when it ends.

        Every phone and PC stops trusting the site on the morning it expires,
        so the row warns a month ahead and says the one command that fixes it.
        The file is re-read only when it changes, so a renewal shows without a
        restart and a health poll does not parse a certificate every time.
        """
        def stage(detail: str, severity: S.Severity) -> S.PipelineStage:
            return S.PipelineStage(
                key="certificate", name="Site certificate", detail=detail,
                healthy=severity is S.Severity.INFO, severity=severity,
                restartable=False)

        tls = self.config.tls
        if tls is None:
            return stage("Not set up - this machine has no HTTPS front (no tls "
                         "block in engine.yaml).", S.Severity.INFO)
        path = tls.cert_dir / "site.crt"
        renew = "Run engine/tools/site_cert.py site with the USB stick in."
        try:
            st = path.stat()
        except OSError:
            return stage(f"No certificate at {path} - phones and PCs cannot open "
                         f"the site over HTTPS. {renew}", S.Severity.CRITICAL)

        key = (st.st_mtime_ns, st.st_size)
        cached = getattr(self, "_cert_cache", None)
        if cached is None or cached[0] != key:
            try:
                from cryptography import x509
                crt = x509.load_pem_x509_certificate(path.read_bytes())
                cached = (key, crt.not_valid_after_utc, None)
            except (OSError, ValueError) as exc:
                cached = (key, None, f"{path} is not a certificate this engine can "
                                     f"read ({exc}). {renew}")
            self._cert_cache = cached
        _, ends, problem = cached
        if problem:
            return stage(problem, S.Severity.CRITICAL)

        names = ", ".join(tls.names)
        when = f"{ends.day} {ends:%b %Y}"
        left = ends - datetime.now(timezone.utc)
        if left <= timedelta(0):
            return stage(f"Expired on {when} - phones and PCs no longer trust the "
                         f"site. {renew}", S.Severity.CRITICAL)
        if left <= timedelta(days=self.CERT_WARN_DAYS):
            return stage(f"Ends on {when}, in {left.days} days. {renew}",
                         S.Severity.WARN)
        return stage(f"Valid until {when} for {names}.", S.Severity.INFO)

    def _attendance_counts(self, day: str):
        """The noon report's figures: one count per group, from the register.

        The same `attendance("group", ...)` the Attendance page runs - the
        report adds no calculation of its own. None when face recognition is
        not running: the counts would be invented zeros, and a report that
        reads "everyone absent" is worse than no report. Groups overlap
        (Everyone holds everybody) and are listed as they come; nothing here
        adds them up. A count carries no name.
        """
        from vg.alerts.events import GroupCount

        if not self.recognition_live:
            return None
        counts = []
        for group in self.groups():
            result = self.attendance("group", group.name, day)
            counts.append(GroupCount(group.name, result.present, result.late,
                                     result.absent))
        return tuple(counts)

    def capabilities(self) -> list[S.Capability]:
        """What the console can honestly show right now, and why not otherwise.

        This is the list every page checks before it renders a number. It
        exists because a page cannot tell an empty register from a broken one:
        both arrive as zero rows. Guessing misleads in both directions — an
        empty day read as a fault, or a dead subsystem read as "nobody came".

        Nothing here reports DEMO. `LiveStore` no longer serves a fixture
        under any condition, so demo is `MockStore`'s answer and only reachable
        with VG_MOCK=1, where the whole store is fixtures and says so.
        """
        # Why a subsystem is down, when the lifespan told us. Beats a generic
        # sentence: "weights not found: yolov8s.pt" is actionable, "not
        # running" is not.
        def live(available: bool, reason: str, detail: str | None = None):
            if available:
                return S.DataState.LIVE, None
            return S.DataState.UNAVAILABLE, f"{reason} ({detail})" if detail else reason

        cameras_up = self.registry.total > 0
        recognition = self.recognition_live
        counting = self.people_worker is not None
        tracking = self.tracking is not None
        gallery = self.gallery is not None

        states = {
            "cameras": live(cameras_up, "No cameras are configured."),
            "recording": live(
                self.recorder is not None and cameras_up,
                "Recording is not running, so nothing can be recorded."),
            "attendance": live(
                recognition,
                "Face recognition is not running, so no register is being kept.",
                self.recognition_error),
            "people": live(gallery, "The face gallery is not loaded, so the "
                           "directory cannot be read.", self.recognition_error),
            "groups": live(gallery, "The face gallery is not loaded, so groups "
                           "cannot be listed.", self.recognition_error),
            "count": live(counting, "Person detection is not running, so nobody "
                          "is being counted.", self.people_error),
            "vehicles": self._vehicles_state(),
            "track": live(tracking, "Tracking is not running, so no path can be "
                          "built.", self.tracking_error),
            # An empty log on a dead watcher must never read as "all clear".
            # LIVE carries no reason at all: an excuse attached to a working
            # feature reads as a fault, which is the P0-08 lesson in reverse.
            "breaches": self._breaches_state(),
            # Not built yet. Saying "not built" is the truth and is different
            # from "broken" — an operator should not be waiting for these to
            # come back.
            "weapons": self._weapons_state(),
            "falls": self._falls_state(),
            "search_lost": self._lost_state(),
            "users": live(
                self.users_store is not None,
                "The accounts database is not loaded, so nobody can sign in."),
            "audit": (S.DataState.UNAVAILABLE,
                      "The audit trail is kept in memory only and is lost when "
                      "the engine restarts."),
            # Home's list (spec 013). Needs the alert database only; whether
            # email can send is System Health's alert row.
            "attention": self._attention_state(),
            "ask": self._ask_state(),
        }

        out: list[S.Capability] = []
        for key, name in self.CAPABILITIES:
            state, reason = states.get(
                key, (S.DataState.UNAVAILABLE, "Not built yet."))
            out.append(S.Capability(key=key, name=name, state=state, reason=reason))
        return out

    def _ask_state(self) -> tuple[S.DataState, str | None]:
        """Whether Ask can actually answer, and why not.

        Three different reasons, three different sentences. "Unavailable" alone
        would leave an administrator unable to tell a switched-off feature from
        a missing key, and only one of those is theirs to fix. Constitution
        rule 8: a subsystem that cannot start says so in the UI, not only in
        the log.
        """
        if not self.config.ask.enabled:
            return (S.DataState.UNAVAILABLE,
                    "Ask is switched off in engine.yaml. Every other feature "
                    "is unaffected.")
        if not os.environ.get("GEMINI_API_KEY"):
            return (S.DataState.UNAVAILABLE,
                    "No GEMINI_API_KEY is set, so questions cannot be "
                    "interpreted. Detection, recording and the gate are "
                    "unaffected.")
        return S.DataState.LIVE, None

    def _ask_today(self) -> str:
        """The site's today, from the site's clock.

        `MockStore` answers with its own demo date. This is the one piece of
        `ask` that has to know where it is running, and it is a date rather
        than a decision — which is why it is an override and the orchestration
        above it is not.
        """
        return self.clock.today()

    def _breaches_state(self) -> tuple[S.DataState, str | None]:
        """Whether anything is actually watching the restricted areas.

        Three different failures, three different sentences. "Unavailable" on
        its own leaves an operator unable to tell a model that would not load
        from a feature nobody switched on, and only one of those is theirs to
        fix.
        """
        if self.zones_worker is None:
            if self.zones_error:
                return (S.DataState.UNAVAILABLE,
                        f"Restricted zones failed to start ({self.zones_error})")
            if self.people_worker is None:
                return (S.DataState.UNAVAILABLE,
                        "Person detection is not running, so nothing is "
                        "watching the restricted areas."
                        + (f" ({self.people_error})" if self.people_error else ""))
            return (S.DataState.UNAVAILABLE,
                    "Restricted zones are not running, so nothing is being "
                    "recorded.")
        if self.scenes is None:
            return (S.DataState.UNAVAILABLE,
                    "The detection log is not available, so nothing can be "
                    "shown even though the cameras are being watched.")
        return S.DataState.LIVE, None

    def _weapons_state(self) -> tuple[S.DataState, str | None]:
        """Whether anything is actually looking for a knife.

        Four different failures, four different sentences. "Unavailable" on
        its own leaves an operator unable to tell a model that would not
        load from a camera nobody switched on, and only one of those is
        theirs to fix. On this feature above all others, an empty list must
        never be allowed to read as an all-clear.
        """
        if self.weapons_worker is None:
            if self.weapons_error:
                return S.DataState.UNAVAILABLE, self.weapons_error
            if self.people_worker is None:
                return (S.DataState.UNAVAILABLE,
                        "Person detection is not running, so knives cannot "
                        "be checked - knives are looked for on people."
                        + (f" ({self.people_error})" if self.people_error else ""))
            return (S.DataState.UNAVAILABLE,
                    "Knife detection is not running, so no camera is being "
                    "checked.")
        if self.weapon_scenes is None:
            return (S.DataState.UNAVAILABLE,
                    "The knife log is not available, so nothing can be shown "
                    "even though the cameras are being checked.")
        return S.DataState.LIVE, None

    def _falls_state(self) -> tuple[S.DataState, str | None]:
        """Whether anything is actually watching for falls, and why not.

        "No camera is checked" is its own sentence: the worker can be running
        with nothing to watch, which is the state of every site the day this
        feature arrives, and an empty history must not read as "nobody fell".
        """
        if self.falls_worker is None:
            if self.falls_error:
                return S.DataState.UNAVAILABLE, self.falls_error
            return (S.DataState.UNAVAILABLE,
                    "Fall detection is not running, so no camera is being checked.")
        if self.fall_scenes is None:
            return (S.DataState.UNAVAILABLE,
                    "The fall history is not available, so nothing can be shown "
                    "even though the cameras are being checked.")
        if not self.falls_worker.cameras:
            return (S.DataState.UNAVAILABLE,
                    "No camera is checked for falls. Turn checking on per camera "
                    "in System health.")
        return S.DataState.LIVE, None

    def _falls_stage(self) -> S.PipelineStage:
        """Rule 8: said on the page, in the same words as the capability."""
        state, reason = self._falls_state()
        if state is not S.DataState.LIVE:
            # Off because nobody switched it on is a choice, not a fault, but
            # it is still not watching anything - a warning, never green.
            return S.PipelineStage(
                key="falls", name="Fall detection",
                detail=reason or "Not running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )
        stats = self._stats_of(self.falls_worker)
        if stats is None:
            return S.PipelineStage(
                key="falls", name="Fall detection",
                detail="Running, but it could not report its counters.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )
        stopped = self._stopped_stage("falls", "Fall detection", stats,
                                      "nobody is watched for falls")
        if stopped is not None:
            return stopped
        # Running and silent is not the same as running and judging. A camera
        # whose frames arrive too far apart never fills the model's window,
        # and that looks exactly like a camera where nobody fell.
        starved = getattr(self.falls_worker, "starved", lambda: [])()
        if starved:
            return S.PipelineStage(
                key="falls", name="Fall detection",
                detail=(f"Frames from {self._camera_names(starved)} arrive more than "
                        f"half a second apart, so the fall model cannot judge anybody "
                        f"there. Raise that camera's analytics rate."),
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )
        detector = getattr(self.falls_worker, "detector", None)
        pose = getattr(detector, "pose_version", None)
        return S.PipelineStage(
            key="falls", name="Fall detection",
            detail=(f"{self._running_on(detector)}"
                    + (f", pose {pose}" if pose else "")
                    + f" - {stats['cameras']} camera(s), "
                      f"{stats['last_inference_ms']}ms last frame"),
            healthy=True, severity=S.Severity.INFO, restartable=False,
            model_version=getattr(detector, "version", None),
        )

    def _clock_stage(self) -> S.PipelineStage:
        """Rule 8: a subsystem that failed to start says so in the UI.

        A clock that cannot be resolved does not crash anything - it just
        quietly relabels every time in the console. Cairo would read three
        hours early, so a 6:12am arrival shows as 3:12am and nobody looking at
        it has any way to tell. That is worse than a crash and it belongs on
        the page an operator opens to ask what is wrong.
        """
        if not self.clock.ok:
            return S.PipelineStage(
                key="clock", name="Site clock",
                detail=self.clock.error or "the site timezone could not be read",
                healthy=False, severity=S.Severity.CRITICAL, restartable=False,
            )
        offset = self.clock.offset_minutes()
        sign = "+" if offset >= 0 else "-"
        return S.PipelineStage(
            key="clock", name="Site clock",
            detail=f"{self.clock.name}, currently UTC{sign}"
                   f"{abs(offset) // 60:02d}:{abs(offset) % 60:02d}",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    def _workers_stage(self) -> S.PipelineStage:
        """What each feature worker is costing, and whether it is keeping up.

        Rule 7 and Principle IV: overload has to be visible. Before this, a
        saturated engine and a comfortable one produced the same page - the
        counters existed, nothing read them, and the only symptom was that
        overlays quietly went stale.

        A worker that is not running is ABSENT from the list rather than
        present with zeros. "Stopped" and "idle" are different answers and a
        row of zeros reads as the second one.
        """
        # `getattr`, because a store built before a subsystem existed simply
        # does not carry the attribute - and a health page that raises
        # AttributeError is a degradation answered with a 500, which rule 7
        # forbids. The whole point of this stage is to survive absence.
        candidates = [
            getattr(self, name, None) for name in (
                "recogniser", "patrol", "people_worker", "tracking",
                "weapons_worker", "falls_worker", "vehicles_worker", "lost_watch",
            )
        ]

        loads: list[S.WorkerLoad] = []
        # Workers whose thread died, and which of the rows below are theirs.
        stopped: list[str] = []
        stopped_rows: set[int] = set()
        dead_threads = 0
        for worker in candidates:
            if worker is None:
                continue
            try:
                stats = worker.stats
            except Exception:
                # A worker that cannot describe itself is not a reason to
                # fail the health page. Skipping it leaves it absent, which
                # is the same honest answer as "not running".
                continue
            loads.append(S.WorkerLoad(
                name=str(stats.get("name", "worker")),
                cameras=int(stats.get("cameras", 0)),
                frames_processed=int(stats.get("frames_processed", 0)),
                last_inference_ms=float(stats.get("last_inference_ms", 0.0)),
                queue_depth=int(stats.get("queue_depth", 0)),
                queue_max=int(stats.get("queue_max", 0)),
                frames_dropped=int(stats.get("frames_dropped", 0)),
                behind=stats.get("behind"),
            ))
            died = self._died_on(stats)
            if died:
                stopped.append(
                    f"{loads[-1].name} on {self._camera_names(died)}")
                stopped_rows.add(len(loads) - 1)
                dead_threads += len(died)

        if not loads:
            return S.PipelineStage(
                key="workers", name="Feature workers",
                detail="Nothing is running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        if stopped:
            # Before "behind": a worker doing nothing is worse than one
            # falling behind, and "N running" over a dead thread is the
            # sentence that hid the vehicles worker for a whole day. Its own
            # row is left off the list, for the reason the docstring gives -
            # a dead thread's counters read as idle, so under a "stopped"
            # headline that row would say "keeping up".
            return S.PipelineStage(
                key="workers", name="Feature workers",
                detail=(f"Stopped - "
                        f"{'a thread' if dead_threads == 1 else 'threads'} "
                        f"died in {'; '.join(sorted(stopped))}. "
                        f"Restart the engine."),
                healthy=False, severity=S.Severity.CRITICAL,
                restartable=False,
                workers=[w for i, w in enumerate(loads)
                         if i not in stopped_rows],
            )

        behind = [w.name for w in loads if w.behind]
        if behind:
            detail = (f"{len(loads)} running - behind on "
                      f"{', '.join(sorted(behind))}")
        else:
            detail = f"{len(loads)} running, all keeping up"

        return S.PipelineStage(
            key="workers", name="Feature workers", detail=detail,
            healthy=not behind,
            severity=S.Severity.WARN if behind else S.Severity.INFO,
            restartable=False,
            workers=loads,
        )

    #: What one frame costs each worker, in milliseconds, for a worker that
    #: has not yet timed one on this machine.
    #:
    #: These are ASSUMPTIONS carried in from earlier runs on this project's
    #: own hardware - `engine.yaml`'s camera comments and `docs/PLAN.md` - and
    #: every row built from one is flagged `measured: false` so the page can
    #: say which figures were timed here and which were not. The moment a
    #: worker analyses a frame, its real number replaces the entry below.
    #:
    #: `engine/tools/benchmark.py` keeps its own table for offline sizing.
    #: The two are deliberately separate: that one is keyed by mix component
    #: for a site that does not exist yet, this one by running worker.
    #: The one detection that counting, intrusion, track and knife detection
    #: all read. Its cost is `SharedDetection.last_pass_ms`, timed around the
    #: model call alone, and it goes on ONE row - every worker's own row has
    #: the time it borrowed from this pass subtracted (`Result.shared_ms`).
    #: Before that, each of those workers reported the pass as its own
    #: inference - including the time spent waiting for another worker to
    #: finish it - and the page added them up: three rows of 13 ms for one
    #: 13 ms model, and a graphics-card bar at 100% over a card the driver
    #: had at 18%.
    PERSON_PASS_ROW = "person detection"

    #: Measured on this machine 3 Sep 2026 (RTX 2080 Max-Q, 60 frames off the
    #: recorded clip): the person pass is 13.3 ms p50 / 18.4 ms p95 WITH the
    #: TensorRT build loaded, against the 23 ms below. The table stays at 23
    #: on purpose - it is the figure for a machine that has NOT built an
    #: engine, which is the machine most likely to be reading an estimate in
    #: the first place. It therefore reads high, which is the safe direction
    #: for a sizing figure, and every row built from it says "estimate".
    ASSUMED_MS_PER_FRAME = {
        PERSON_PASS_ROW: 23.0,  # the YOLO person pass, costed once
        # The workers that READ that pass. These are their OWN costs, with
        # the pass already taken out - bookkeeping for counting and zones,
        # ByteTrack and the appearance matcher for tracking.
        "people": 1.0,
        "zones": 1.0,
        "tracking": 2.0,
        "recognition": 44.0,  # YuNet + SFace
        "patrol": 44.0,       # the same pair, run slower on the other cameras
        "weapons": 17.0,      # knife model, only on frames with a person
        # Pose model (the size of the person pass) plus the owner's LSTM
        # stepped through the frames filled in between two real ones. Not
        # measured on the deployment GPU yet - hence an estimate.
        "falls": 30.0,
        "vehicles": 6.0,      # the plate pair
        "lostitems": 29.0,    # bag model, only while somebody is watching
    }

    @staticmethod
    def _stats_of(worker) -> dict | None:
        """One worker's counters, or None when it cannot describe itself.

        Rule 7. Four stages used to read `worker.stats` unguarded, so a
        worker whose bookkeeping raised took the whole of System Health down
        with a 500 - the one page an operator opens to find out what is
        broken, refusing to answer precisely because something was. The
        workers stage already skipped such a worker; the four per-feature
        stages did not.

        None means "could not read", which the caller renders as exactly
        that. It is not the same answer as "not running", and neither is a
        row of zeros.
        """
        if worker is None:
            return None
        try:
            return worker.stats
        except Exception:  # noqa: BLE001 - reported as payload, never raised
            log.exception("could not read counters for %s",
                          type(worker).__name__)
            return None

    @staticmethod
    def _died_on(stats: dict | None) -> list[str]:
        """Cameras a worker's thread has died on. Empty when it cannot say.

        Rule 8. A dying thread takes itself off the worker's books but leaves
        its camera configured, so every other counter reads as idle rather
        than stopped - the vehicles worker sat like that for a whole day,
        4-5 Sep 2026, under "all keeping up". A worker whose counters carry
        no `died_on` at all (bag detection, a test double) gets exactly
        today's answer, because this returns nothing for it.
        """
        died = (stats or {}).get("died_on")
        if not isinstance(died, (list, tuple, set, frozenset)):
            return []
        return sorted(str(c) for c in died)

    def _camera_names(self, camera_ids: list[str]) -> str:
        """The names the operator typed, quoted, for a list of camera ids.

        Quoted because a name is free text: unquoted, "Gate, north" beside
        "Lobby" reads as three cameras. An id with no name on the roster is
        shown as itself rather than dropped - a camera whose thread died must
        never vanish from the sentence that reports it.
        """
        names = {c.id: c.name for c in self.registry.configs()}
        return ", ".join(f'"{names.get(c, c)}"' for c in camera_ids)

    def _stopped_stage(self, key: str, name: str, stats: dict | None,
                       what: str) -> S.PipelineStage | None:
        """A feature's row when its thread has died, or None if none has.

        Same key and name as the feature's usual row, so the console shows
        this in its place rather than beside it. Not restartable: the only
        thing that brings a thread back is the engine starting it again.
        """
        died = self._died_on(stats)
        if not died:
            return None
        total = int((stats or {}).get("cameras", 0) or 0) or len(died)
        # One thread per camera, so two dead cameras are two dead threads.
        threads = "thread" if len(died) == 1 else "threads"
        return S.PipelineStage(
            key=key, name=name,
            detail=(f"Stopped on {self._camera_names(died)} ({len(died)} of "
                    f"{total} camera(s)) - its {threads} died, so {what} "
                    f"there. Restart the engine."),
            healthy=False, severity=S.Severity.CRITICAL, restartable=False,
        )

    @staticmethod
    def _pool(device: str | None) -> str | None:
        """Which budget a device string belongs to. None when it does not say.

        Returning None rather than defaulting to one of them is the point: a
        worker charged to the wrong pool makes both totals wrong, and the
        page can render "did not say" honestly.
        """
        if not device:
            return None
        text = str(device).strip().lower()
        if text.startswith("cpu"):
            return "cpu"
        if text.startswith(("cuda", "gpu", "mps")) or text.isdigit():
            return "gpu"
        return None

    def _machine_capacity(self) -> S.Capacity | None:
        """What this engine is doing, and what its configuration asks for.

        Two figures per row, and the page keeps them apart:

        - `busy_ms_per_second` is a **reading**: milliseconds this worker
          really spent, per second, over the last `window_seconds`. It is
          what the bars are checked against, and it is what an operator
          means by "how full is the machine right now".
        - `ms_per_second` is a **projection**: the rate each camera is
          configured at, times what one frame last cost. It is what lets
          somebody see the wall before adding the camera that hits it.

        The first version of this card showed only the projection, drawn as
        a bar, and the bar read 100% over a card the driver had at 18%.
        Nothing on the page could say otherwise. Now the driver's own figure
        draws the bar and this arithmetic sits beside it, labelled.

        Two budgets, never one number. Face recognition is OpenCV and has no
        CUDA path, so it genuinely does not compete with the person detector
        for the same milliseconds; adding GPU and CPU together would produce
        a percentage of nothing.

        A worker serving no camera is absent rather than present with zeros,
        for the same reason it is absent from the workers stage: "not running"
        and "running for free" are different answers.
        """
        candidates = [
            getattr(self, name, None) for name in (
                "recogniser", "patrol", "people_worker", "tracking",
                "weapons_worker", "falls_worker", "vehicles_worker", "lost_watch",
            )
        ]

        rows: list[S.CapacityRow] = []
        window = 5.0
        for worker in candidates:
            if worker is None:
                continue
            try:
                stats = worker.stats
            except Exception:  # noqa: BLE001 - a worker that cannot describe
                # itself is skipped, not a 500. Rule 7.
                continue

            cameras = int(stats.get("cameras", 0) or 0)
            if not cameras:
                continue

            name = str(stats.get("name", "worker"))
            timed = float(stats.get("last_inference_ms", 0.0) or 0.0)
            measured = timed > 0
            ms = timed if measured else self.ASSUMED_MS_PER_FRAME.get(name, 0.0)
            if not ms and not stats.get("busy_ms_per_second"):
                # No measurement, no carried-in figure, and nothing done in
                # the window. Nothing honest to say about this worker's
                # cost, so it gets no row rather than a zero that would
                # read as "free".
                continue

            hz = stats.get("frames_per_second")
            hz = float(hz) if hz is not None else None
            window = float(stats.get("window_seconds", window) or window)
            rows.append(S.CapacityRow(
                name=name,
                pool=self._pool(stats.get("device")),
                device=stats.get("device"),
                cameras=cameras,
                frames_per_second=hz,
                ms_per_frame=round(ms, 1),
                measured=measured,
                ms_per_second=round(hz * ms, 1) if hz is not None else None,
                on_demand=bool(stats.get("on_demand")),
                busy_ms_per_second=float(stats.get("busy_ms_per_second", 0.0) or 0.0),
                analysed_per_second=float(stats.get("analysed_per_second", 0.0) or 0.0),
            ))

        shared = self._shared_pass_row()
        if shared is not None:
            rows.insert(0, shared)

        if not rows:
            return None

        # Logical cores, which is what supplies the processor budget: an
        # 8-core box has 8000 ms of work to give every second.
        cores = os.cpu_count() or 1

        def asks(pool: str | None) -> float:
            return sum(r.ms_per_second or 0.0 for r in rows if r.pool == pool)

        def busy(pool: str | None) -> float:
            return sum(r.busy_ms_per_second for r in rows if r.pool == pool)

        return S.Capacity(
            gpu_ms_per_second=round(asks("gpu"), 1),
            cpu_ms_per_second=round(asks("cpu"), 1),
            cpu_budget_ms=float(cores * 1000),
            cores=cores,
            unplaced_ms_per_second=round(asks(None), 1),
            all_measured=all(r.measured for r in rows),
            gpu_busy_ms_per_second=round(busy("gpu"), 1),
            cpu_busy_ms_per_second=round(busy("cpu"), 1),
            unplaced_busy_ms_per_second=round(busy(None), 1),
            window_seconds=window,
            rows=rows,
        )

    def _shared_pass_row(self) -> S.CapacityRow | None:
        """The one person detection, costed once.

        Projection: it runs at most once per (camera, frame) whatever asks
        for it, so what it costs a camera each second is its cost times the
        FASTEST rate any of its readers runs that camera at - the slower
        readers land on frames the fastest one already paid for. Summed
        over cameras.

        Reading: `SharedDetection.load()` - passes that actually happened
        in the window and the milliseconds they took.

        A zones worker only asks for the pass on cameras that are actually
        restricted; on the rest it returns before any detection call, so
        those cameras are not charged for it.
        """
        readers = [w for w in (self.people_worker, self.zones_worker,
                               self.tracking, self.weapons_worker)
                   if w is not None]
        detector = next(
            (d for d in (getattr(w, "detector", None) or getattr(w, "people", None)
                         for w in readers) if d is not None),
            None)
        if detector is None:
            return None

        fastest: dict[str, float] = {}
        for worker in readers:
            cameras = getattr(worker, "cameras", None)
            rate_for = getattr(worker, "rate_for", None)
            if cameras is None or rate_for is None:
                continue
            asks = set(cameras)
            restricted = getattr(worker, "restricted", None)
            if callable(restricted):
                asks &= set(restricted())
            for camera_id in asks:
                try:
                    hz = float(rate_for(camera_id))
                except Exception:  # noqa: BLE001 - a worker that cannot say
                    continue      # its rate is not charged, not guessed
                fastest[camera_id] = max(fastest.get(camera_id, 0.0), hz)
        if not fastest:
            return None

        timed = float(getattr(detector, "last_pass_ms", 0.0) or 0.0)
        measured = timed > 0
        ms = timed if measured else self.ASSUMED_MS_PER_FRAME[self.PERSON_PASS_ROW]
        hz = sum(fastest.values())
        device = getattr(detector, "device", None)

        load = {}
        loader = getattr(detector, "load", None)
        if callable(loader):
            try:
                load = loader() or {}
            except Exception:  # noqa: BLE001 - no reading is not a 500
                load = {}

        return S.CapacityRow(
            name=self.PERSON_PASS_ROW,
            pool=self._pool(device),
            device=device,
            cameras=len(fastest),
            frames_per_second=round(hz, 2),
            ms_per_frame=round(ms, 1),
            measured=measured,
            ms_per_second=round(hz * ms, 1),
            shared=True,
            busy_ms_per_second=float(load.get("busy_ms_per_second", 0.0) or 0.0),
            analysed_per_second=float(load.get("passes_per_second", 0.0) or 0.0),
        )

    def health(self) -> S.SystemHealth:
        # "Total" is the cameras that are switched ON. `registry.total` also
        # counts disabled ones - rightly, for the setup list, where a camera
        # somebody turned off must not vanish - but here it made every one
        # of them a fault: two cameras disabled on purpose read as "1 of 3
        # online", the ingest stage went amber, and the summary said two
        # cameras were not being analysed. Off is not down.
        online = self.registry.online
        total = len(self.registry.workers)
        disabled = len(self.registry.disabled)
        # Same rule for the recorder count: a source that is off is not a
        # recorder that is down.
        sources = [s for s in self.sources() if s.enabled]

        pipeline = [
            S.PipelineStage(
                key="ingest", name="Camera ingest",
                detail=(f"{online} of {total} streams decoding"
                        + (f" - {disabled} switched off" if disabled else "")),
                healthy=online == total and total > 0,
                severity=S.Severity.INFO if online == total else S.Severity.WARN,
                restartable=False,
            ),
            self._recognition_stage(),
            self._people_stage(),
            self._clock_stage(),
            self._weapons_stage(),
            self._falls_stage(),
            self._vehicles_stage(),
            self._lost_stage(),
            self._alerts_stage(),
            self._certificate_stage(),
            self._workers_stage(),
        ]

        # A page that says "all good" over a machine that is dropping frames
        # is the exact failure this feature exists to remove. Any stage that
        # is unhealthy raises the summary with it.
        struggling = any(not stage.healthy for stage in pipeline)
        dropped = sum(w.source.health.frames_dropped
                      for w in self.registry.workers.values())
        skipped = sum(getattr(w.source.health, "frames_skipped", 0)
                      for w in self.registry.workers.values())

        gpu = _gpu_reading()
        cpu = _cpu_readings()
        return S.SystemHealth(
            cameras_online=online, cameras_total=total,
            cameras_disabled=disabled,
            recorders_online=sum(1 for s in sources if s.status is S.SourceStatus.OK),
            recorders_total=len(sources),
            severity=(S.Severity.WARN if (online < total or struggling)
                      else S.Severity.INFO),
            cpu_percent=cpu["process"],
            cpu_machine_percent=cpu["machine"],
            gpu_percent=gpu.get("util"),
            gpu_memory_used_mb=gpu.get("used_mb"),
            gpu_memory_total_mb=gpu.get("total_mb"),
            metrics=[
                S.Metric(key="cameras", label="Cameras up", value=online, total=total),
                S.Metric(key="frames", label="Frames read",
                         value=sum(w.source.health.frames_read
                                   for w in self.registry.workers.values())),
                S.Metric(key="reconnects", label="Reconnects",
                         value=sum(w.source.health.reconnects
                                   for w in self.registry.workers.values())),
                S.Metric(key="dropped", label="Frames dropped", value=dropped,
                         severity=(S.Severity.WARN if dropped
                                   else S.Severity.INFO)),
                # NOT a drop. Frames pulled off the camera - and so decoded,
                # because `grab()` is the decode - but deliberately never
                # turned into pixels, because nobody was watching it. The
                # saving, shown so it can be checked rather than believed.
                # It was labelled "not decoded" until 12 Sep 2026: untrue.
                S.Metric(key="skipped", label="Frames decoded, not used",
                         value=skipped),
            ],
            capacity=self._machine_capacity(),
            recorders=[
                S.Recorder(id=s.id, name=s.name, cameras=s.channels,
                           online=s.status is S.SourceStatus.OK, ip=s.ip)
                for s in sources
            ],
            pipeline=pipeline,
            cameras=self.live_cameras(),
        )

    def _recognition_stage(self) -> S.PipelineStage:
        """What face recognition is actually doing, in the operator's words.

        The distinction that matters here is between "off", "broken" and
        "running but nobody is enrolled". They look identical on the attendance
        page — everyone reads as absent — and have completely different fixes.
        """
        if self.recognition_error:
            return S.PipelineStage(
                key="recognition", name="Face recognition",
                detail=f"Failed to start - {self.recognition_error}. "
                       f"Attendance is showing DEMO DATA.",
                healthy=False, severity=S.Severity.CRITICAL, restartable=False,
            )

        if not self.recognition_live:
            return S.PipelineStage(
                key="recognition", name="Face recognition",
                detail="Off - no camera has the 'attendance' feature. "
                       "Attendance is showing DEMO DATA.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        # Before "nobody is enrolled": a thread that died recognises nobody
        # whoever is enrolled, and "running on N camera(s)" below would say
        # the opposite.
        stopped = self._stopped_stage(
            "recognition", "Face recognition",
            self._stats_of(self.recogniser), "nobody is recognised")
        if stopped is not None:
            return stopped

        enrolled = self.gallery.size
        if enrolled == 0:
            return S.PipelineStage(
                key="recognition", name="Face recognition",
                detail="Running, but nobody is enrolled - no one can be "
                       "recognised. Enrol faces to start taking attendance.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        cameras = len(self.recogniser.cameras) if self.recogniser else 0
        return S.PipelineStage(
            key="recognition", name="Face recognition",
            detail=f"{enrolled} enrolled, {self.gallery.embedding_count} faces, "
                   f"running on {cameras} camera(s)",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    def _people_stage(self) -> S.PipelineStage:
        if self.people_error:
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail=f"Failed to start - {self.people_error}. "
                       f"Counting and intrusion are showing DEMO DATA.",
                healthy=False, severity=S.Severity.CRITICAL, restartable=False,
            )

        if self.people_worker is None:
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail="Off - no camera asks for counting, intrusion or track",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self._stats_of(self.people_worker)
        if stats is None:
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail="Running, but it could not report its counters.",
                healthy=False, severity=S.Severity.WARN, restartable=True,
            )
        stopped = self._stopped_stage("detect", "Person detection", stats,
                                      "nobody is counted")
        if stopped is not None:
            return stopped
        if not stats["cameras"]:
            # The model is loaded and knife detection is using it, but no
            # camera asked for counting, intrusion or track. "Running on 0
            # camera(s)" would read as broken; it is neither broken nor idle.
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail="Loaded and shared with knife detection. No camera "
                       "asks for counting, intrusion or track.",
                healthy=True, severity=S.Severity.INFO, restartable=False,
            )
        detector = getattr(self.people_worker, "detector", None)
        return S.PipelineStage(
            key="detect", name="Person detection",
            detail=f"{self._running_on(detector)} - {stats['cameras']} camera(s), "
                   f"{stats['last_inference_ms']}ms last inference",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    def _vehicles_stage(self) -> S.PipelineStage:
        """Rule 8: a subsystem that failed to start says so in the UI.

        The reason is the same sentence the capability gives, so the page and
        System Health cannot disagree about whether plates are being read.
        """
        state, reason = self._vehicles_state()
        if state is not S.DataState.LIVE:
            return S.PipelineStage(
                key="vehicles", name="Plate reading",
                detail=reason or "Not running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self._stats_of(self.vehicles_worker)
        if stats is None:
            return S.PipelineStage(
                key="vehicles", name="Plate reading",
                detail="Running, but it could not report its counters.",
                healthy=False, severity=S.Severity.WARN, restartable=True,
            )
        stopped = self._stopped_stage("vehicles", "Plate reading", stats,
                                      "no plates are read")
        if stopped is not None:
            return stopped
        reader = getattr(self.vehicles_worker, "reader", None)
        return S.PipelineStage(
            key="vehicles", name="Plate reading",
            detail=f"{self._running_on(reader)} - {stats['cameras']} camera(s), "
                   f"{stats['last_inference_ms']}ms last inference",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    def _weapons_stage(self) -> S.PipelineStage:
        """Rule 8: a subsystem that failed to start says so in the UI.

        The reason is the same sentence the capability gives, so the page and
        System Health cannot disagree about whether knives are being looked
        for.
        """
        state, reason = self._weapons_state()
        if state is not S.DataState.LIVE:
            return S.PipelineStage(
                key="weapons", name="Knife detection",
                detail=reason or "Not running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self._stats_of(self.weapons_worker)
        if stats is None:
            return S.PipelineStage(
                key="weapons", name="Knife detection",
                detail="Running, but it could not report its counters.",
                healthy=False, severity=S.Severity.WARN, restartable=True,
            )
        stopped = self._stopped_stage("weapons", "Knife detection", stats,
                                      "no knife is looked for")
        if stopped is not None:
            return stopped
        knives = getattr(self.weapons_worker, "knives", None)
        return S.PipelineStage(
            key="weapons", name="Knife detection",
            detail=f"{self._running_on(knives)} - {stats['cameras']} camera(s), "
                   f"{stats['last_inference_ms']}ms last inference",
            healthy=True, severity=S.Severity.INFO, restartable=False,
        )

    # -- people and attendance ---------------------------------------------

    def people(self) -> list[S.DirectoryPerson]:
        """The enrolled directory.

        `photo_on_file` is a statement about capability, not paperwork: without
        a face on file the system cannot recognise this person, and the UI says
        so plainly rather than reporting them absent as if it had looked.
        """
        if self.gallery is None:
            # No gallery means nobody is enrolled that we can see. An
            # invented directory here would be a list of children who do
            # not attend this school.
            return []

        today = self.sightings.local_date(datetime.now(timezone.utc)) if self.sightings else None
        register = self._register(today) if today else None

        # One query for the whole directory, not one per row. At the target
        # roll of a couple of thousand people the difference is a page that
        # opens and a page nobody opens twice.
        latest = self.sightings.last_seen() if self.sightings else {}

        # Names from the runtime roster, like the breach log builds them: a
        # camera added or renamed through the console is not in engine.yaml,
        # and putting "cam-3" where the operator typed "Back stairwell" is the
        # same mistake as showing a database key.
        names = {c.id: c.name for c in self.registry.configs()}

        out = []
        for person in self.gallery.people():
            status = None
            if register is not None:
                entry = register.entry(person.id)
                status = S.AttendanceStatus(entry.status) if entry else None

            seen_at, camera_id = latest.get(person.id, (None, None))
            out.append(S.DirectoryPerson(
                id=person.id, name=person.name,
                type=S.PersonType(person.type),
                group=person.group, detail=person.detail,
                photo_on_file=person.photo_on_file,
                attendance_today=status,
                photos=person.photo_count,
                enrolled_at=_instant(person.created_at, self.clock),
                last_seen=_instant(seen_at, self.clock),
                # Falls back to the id for a camera that has since been
                # removed. Ugly, but "cam-retired" is true and blank would
                # read as "no camera", which is a different claim.
                last_camera=(names.get(camera_id) or camera_id) if camera_id else None,
            ))
        return out

    def remove_person(self, person_id: str, actor: str) -> bool:
        """Take a person out of the system. Audited first, then deleted.

        What goes: the directory row and every face vector behind it — the
        `face_embedding` rows cascade, because every connection this process
        opens sets `foreign_keys=ON`. Deleting the name while quietly keeping
        the biometrics would be the worst outcome available.

        What stays: their sightings, and every audit entry. The sightings are
        unreachable from any page after this and wait for P3's erasure (owner
        decision, 2026-08-21); the audit trail is never deleted by anything.

        The order matters. The entry is written BEFORE the delete runs, the
        same rule track searches follow, so a crash in between leaves an
        audited intent rather than a person who vanished with nothing saying
        why. It also means a failed delete is a logged attempt, which is the
        safe direction to be wrong in.

        `gallery.remove_person` ends by reloading the in-memory index that the
        recognition worker shares, so the removed person stops being named
        from the next frame — no restart (PPL-FR-006).
        """
        if self.gallery is None:
            raise SubsystemUnavailable(
                "face recognition is not running, so there is no gallery to "
                "remove anybody from"
            )

        person = self.gallery.person(person_id)
        if person is None:
            return False

        self._log(actor, "person.remove", person.name,
                  "removed from the directory and the face gallery")
        return self.gallery.remove_person(person_id)

    def school_profile(self) -> S.SchoolProfile:
        hours = self.config.hours
        return S.SchoolProfile(
            name=self.config.site_name,
            hours_from=hours.start.strftime("%H:%M"),
            hours_to=hours.end.strftime("%H:%M"),
            term_from=hours.term_from,
            term_to=hours.term_to,
            late_cutoff=hours.late_cutoff.strftime("%H:%M"),
            timezone=self.config.timezone,
        )

    #: The group that holds the whole school. Every enrolled person is in it,
    #: always, and a specific group is something extra on top rather than
    #: instead of.
    #:
    #: This used to be the name of the bucket for people with **no** group,
    #: which made it the leftovers: it shrank as people were sorted into
    #: grades and disappeared entirely once everybody had one, under a word
    #: that says the opposite. Worse, `attendance()` already used the same
    #: word for the whole school, so the Attendance dropdown offered
    #: "Everyone", sent it as a filter, and got the leftovers back under a
    #: heading claiming to be the school.
    #:
    #: Kept in one place because the register filters on the same string the
    #: dropdown was populated from, and the two drifting apart would empty a
    #: group.
    EVERYONE = "Everyone"

    def _specific_group_of(self, person) -> str | None:
        """The optional group somebody was filed into, if any.

        None for a person nobody has assigned. That is not a group and gets no
        bucket of its own — they are in Everyone, which is where an unassigned
        person belongs. Somebody who typed "Everyone" into the optional box is
        treated the same way: they are in it regardless, and a second row with
        that name and a different count would be a page arguing with itself.
        """
        group = (person.group or "").strip()
        if not group or group == self.EVERYONE:
            return None
        return group

    def _register(self, on: str, group: str | None = None):
        """The day's register. Absence is derived from missing sightings.

        Bounded by school hours so a sighting at 01:14 does not count as an
        on-time arrival just because it precedes the 08:00 cutoff.

        `group` narrows who is expected. Without it the page headed "Grade 8"
        listed every enrolled person in the school, which is not a Grade 8
        register and would have been read as one.

        `Everyone` is not a narrowing. It is the whole school, and asking for
        it has to give the same answer as asking for no group at all — they
        are the same question, and they used to be two different registers
        under one heading.
        """
        hours = self.config.hours
        wanted = None if group in (None, self.EVERYONE) else group
        expected = [
            p.id for p in self.gallery.people()
            if p.photo_on_file
            and (wanted is None or self._specific_group_of(p) == wanted)
        ]
        return self.sightings.register(
            on,
            expected,
            cutoff=hours.late_cutoff,
            day_start=hours.start,
            day_end=hours.end,
        )

    # -- honest emptiness ---------------------------------------------------
    #
    # These replace what used to be `super()` calls. The rule they serve is
    # that an empty answer plus a stated reason is honest, and an invented one
    # never is however plausible it looks. The reason itself travels on
    # `/system/capabilities`, so a page can say *why* it is empty rather than
    # leaving an operator to guess between "nobody came" and "nothing was on".

    def _empty_attendance(self, mode: str, subject: str,
                          on: str) -> S.AttendanceResult:
        """A register nobody was watching. Not a register of absences.

        `expected` stays 0 rather than the roll size: claiming 400 expected and
        0 present would read as a school where nobody turned up.
        """
        return S.AttendanceResult(
            mode="person" if mode == "person" else "group",
            date=on, subject=subject,
            expected=0, present=0, late=0, absent=0,
            metrics=[S.Metric(
                key="source", label="Source", unit="text",
                text="Face recognition is not running, so nothing was recorded",
            )],
        )

    def _empty_track(self, query: S.TrackQuery, actor: str) -> S.TrackResult:
        """No path, and the search still goes in the audit trail.

        Constitution rule 11: the audit entry is written before the result
        returns. That a search found nothing does not make it less of a search
        of a named child's movements, and an unlogged one is exactly the
        search somebody would want unlogged.
        """
        who = query.who or query.person_id or "?"
        entry = self._log(actor, "track.search", who,
                          f"{query.date} - tracking unavailable")
        return S.TrackResult(
            subject=S.PersonRef(id=query.person_id, name=who,
                                type=S.PersonType.STUDENT,
                                match=S.MatchKind.NONE),
            date=query.date,
            audit_id=entry.id,
            sightings=0,
            metrics=[S.Metric(
                key="source", label="Source", unit="text",
                text="Tracking is not running, so no path could be built",
            )],
        )

    def attendance(self, mode: str, subject: str, on: str) -> S.AttendanceResult:
        if not self.recognition_live:
            # An invented register marks real children present or absent.
            # Empty, with the reason on /system/capabilities, is the only
            # honest answer when nothing was watching.
            return self._empty_attendance(mode, subject, on)

        if mode == "person":
            person = self.gallery.find_by_name(subject) or self.gallery.person(subject)
            if person is None:
                return self._empty_attendance(mode, subject, on)

            # P0-04. Every day here used to be reported on time and `late`
            # was hardcoded to 0, while the day register applied the cutoff
            # properly. Same child, same morning, two screens, two answers.
            # The cutoff and the school-hours bound are the register's, so
            # there is now only one rule.
            hours = self.config.hours
            history = self.sightings.history(
                person.id, days=self.HISTORY_DAYS,
                cutoff=hours.late_cutoff,
                day_start=hours.start, day_end=hours.end,
            )
            days = [
                S.AttendanceDay(
                    date=day,
                    status=S.AttendanceStatus(entry.status),
                    seen_at=_instant(entry.first_seen, self.clock),
                    location=self._camera_name(entry.camera_id),
                    minutes_late=entry.minutes_late,
                )
                for day, entry in sorted(history.items(), reverse=True)
            ]
            late = sum(1 for d in days if d.status == S.AttendanceStatus.LATE)
            return S.AttendanceResult(
                mode="person", date=on, subject=person.name,
                expected=len(days), present=len(days), late=late,
                absent=0,
                metrics=[
                    S.Metric(key="days_seen", label="Days seen", value=len(days)),
                    S.Metric(key="late", label="Times late", value=late),
                    S.Metric(key="sightings", label="Total sightings",
                             value=sum(e.sightings for e in history.values())),
                ],
                days=days, cameras=self.live_cameras(),
            )

        # Narrow to the group that was asked for. A blank subject is the whole
        # school; anything else is the name the dropdown was populated with, so
        # it either matches a bucket or matches nobody, and matching nobody is
        # the honest answer for a group that has no one in it.
        register = self._register(on, group=subject or None)
        people = {p.id: p for p in self.gallery.people()}

        records = []
        for entry in register.entries:
            person = people.get(entry.person_id)
            if person is None:
                continue
            records.append(S.AttendanceRecord(
                person=S.PersonRef(
                    id=person.id, name=person.name,
                    type=S.PersonType(person.type),
                    match=(S.MatchKind.FACE if entry.status != "absent"
                           else S.MatchKind.NONE),
                    confidence=entry.confidence,
                ),
                status=S.AttendanceStatus(entry.status),
                seen_at=_instant(entry.first_seen, self.clock),
                camera_id=entry.camera_id,
                location=self._camera_name(entry.camera_id),
                minutes_late=entry.minutes_late,
            ))

        # Say how many cameras were up. A register produced while half the
        # cameras were down is not the same claim as one produced with all of
        # them up, and the difference must not be invisible.
        online, total = self.registry.online, self.registry.total
        metrics = [
            S.Metric(key="present", label="Here", value=register.present,
                     total=register.expected),
            S.Metric(key="late", label="Late", value=register.late),
            S.Metric(key="absent", label="Absent", value=register.absent),
            S.Metric(key="cameras", label="Cameras up", value=online, total=total,
                     severity=S.Severity.INFO if online == total else S.Severity.WARN),
        ]

        return S.AttendanceResult(
            mode="group", date=on, subject=subject or "Everyone",
            expected=register.expected, present=register.present,
            late=register.late, absent=register.absent,
            metrics=metrics, records=records, cameras=self.live_cameras(),
        )

    # -- track a person -----------------------------------------------------

    def track(self, query: S.TrackQuery, actor: str) -> S.TrackResult:
        """Where one person went, rebuilt from stored sightings.

        Two sources, deliberately kept distinguishable all the way to the
        screen:

          FACE        a face was recognised. Evidence about *identity*.
          APPEARANCE  the same body was seen again. Evidence about *continuity*
                      only - clothing cannot tell you which person somebody is.

        Merging them into one confidence would hide that difference, and the
        difference is the whole basis on which an operator decides how much to
        believe a path.

        Returns an empty path when tracking is not running, with the reason
        on /system/capabilities so the page can say which it is. It used to
        serve fixtures here instead, on the reasoning that an empty day looks
        like "this person went nowhere" — but an invented day looks like
        somewhere they went, which is worse and much harder to notice.
        """
        if self.tracking is None or self.sightings is None:
            return self._empty_track(query, actor)

        person_id, name = self._resolve_person(query)
        if person_id is None:
            return self._empty_track(query, actor)

        on = query.date
        stops: list[S.TrackStop] = []

        # Face sightings first - the strong claim.
        for sighting in self.sightings.sightings_on(on, person_id):
            stops.append(S.TrackStop(
                at=_instant(sighting.seen_at, self.clock),
                camera_id=sighting.camera_id,
                camera_name=self._camera_name(sighting.camera_id) or sighting.camera_id,
                place=self._area_of(sighting.camera_id),
                match=S.MatchKind.FACE,
                confidence=float(sighting.confidence),
            ))

        # Then the body, wherever the face was not visible.
        for stop in self.tracking.store.path_for(person_id, on):
            stops.append(S.TrackStop(
                at=_instant(stop.first_seen, self.clock),
                until=_instant(stop.last_seen, self.clock) if stop.seconds > 0 else None,
                camera_id=stop.camera_id,
                camera_name=self._camera_name(stop.camera_id) or stop.camera_id,
                place=self._area_of(stop.camera_id),
                match=S.MatchKind.APPEARANCE,
                confidence=stop.confidence,
            ))

        stops.sort(key=lambda s: s.at.utc)

        entry = self._log(actor, "track.search", name or person_id,
                          f"{on} {query.start or ''}-{query.end or ''}")
        cameras = {s.camera_id for s in stops}
        return S.TrackResult(
            subject=S.PersonRef(
                id=person_id, name=name or person_id,
                type=S.PersonType.STUDENT,
                match=S.MatchKind.FACE if any(
                    s.match == S.MatchKind.FACE for s in stops) else S.MatchKind.APPEARANCE,
            ),
            date=on,
            audit_id=entry.id,
            sightings=len(stops),
            first_seen=stops[0].at if stops else None,
            last_seen=stops[-1].at if stops else None,
            metrics=[
                S.Metric(key="sightings", label="Sightings", value=len(stops)),
                S.Metric(key="cameras", label="Cameras", value=len(cameras)),
                S.Metric(key="byFace", label="By face",
                         value=sum(1 for s in stops if s.match == S.MatchKind.FACE)),
                S.Metric(key="byAppearance", label="By clothing",
                         value=sum(1 for s in stops if s.match == S.MatchKind.APPEARANCE)),
            ],
            path=stops,
            cameras=[v for v in (self.camera_view(c) for c in sorted(cameras)) if v],
            names_from=self._name_source(),
        )

    def _name_source(self) -> S.NameSource:
        """Which cameras could put a name on a body while this path was built.

        With the patrol tier off, only the doorway cameras run a recogniser.
        A corridor sighting is then a body with no name, and the path comes
        back with fewer named stops than it would have had.

        That is a legitimate trade - patrol was the largest processor line in
        the engine and almost nothing read it - but it is NOT allowed to be
        invisible. A quietly thinner answer looks exactly like a person who
        was not there, and an operator has no way to tell the two apart. So
        the fact travels with the result and the console says which it is.
        """
        patrol = getattr(self, "patrol", None)
        return S.NameSource.ALL if patrol is not None else S.NameSource.IDENTITY

    def _resolve_person(self, query: S.TrackQuery):
        """`person_id` or `who` -> (id, name). Names travel in URLs today."""
        if self.gallery is None:
            return query.person_id, query.who

        if query.person_id:
            person = self.gallery.person(query.person_id)
            return query.person_id, person.name if person else query.who
        if query.who:
            person = self.gallery.find_by_name(query.who)
            return (person.id, person.name) if person else (None, query.who)
        return None, None

    def _area_of(self, camera_id: str) -> str:
        """Where this camera is, in words. Never its id if that can be helped.

        The **live roster first**, engine.yaml second. Asking the file alone
        meant a camera an operator added through the console had no entry to
        find, so the id fell through to the screen: "cam-3" in the Area
        column where somebody had typed "Back stairwell". Worse, the camera
        NAME on the same row already came from the roster, so one entry could
        show the name and the raw id side by side.

        The id is still the last resort. A camera that has been deleted since
        the detection happened has no name left anywhere, and its id is more
        honest than inventing one or leaving the column blank.
        """
        for cam in self.registry.configs():
            if cam.id == camera_id:
                return cam.area or cam.name
        for cam in self.config.cameras:
            if cam.id == camera_id:
                return cam.area or cam.name
        return camera_id

    def _camera_name(self, camera_id: str | None) -> str | None:
        if not camera_id:
            return None
        camera = self.config.camera(camera_id)
        return camera.name if camera else camera_id

    # -- the video behind a stop --------------------------------------------

    NO_ARCHIVE = ("There is no recorded-video archive configured, so a stop "
                  "cannot be played back. Set `archive:` in engine.yaml.")

    def _runner(self):
        if self.archive is None:
            raise SubsystemUnavailable(self.NO_ARCHIVE)
        return self.archive

    def start_leg(self, req: S.LegRequest, actor: str) -> S.LegJob:
        """Queue the video for one stop, and start answering with its pieces."""
        runner = self._runner()
        if self.config.camera(req.camera_id) is None:
            raise NothingThere(f"There is no camera {req.camera_id!r}.")

        seconds = (req.end - req.start).total_seconds()
        if seconds <= 0:
            raise NothingThere("That span ends before it starts.")

        descriptor = None
        if req.descriptor_of is not None:
            descriptor = self._descriptor_at(req.descriptor_of)

        # Audit before the work, not after it: the promise is that looking at
        # somebody's recorded movements leaves a trail, and a job that started
        # before the write could run to completion with nothing in the log.
        self._log(actor, "path.leg", req.person_id or req.camera_id,
                  f"{self._camera_name(req.camera_id)} "
                  f"{req.start.isoformat(timespec='seconds')} +{seconds:.0f}s")

        try:
            job = runner.submit(
                req.camera_id, req.start, req.end,
                person_id=req.person_id, descriptor=descriptor,
            )
        except QueueFull as exc:
            raise AlreadyBusy(str(exc)) from exc
        except ArchiveUnavailable as exc:
            raise SubsystemUnavailable(str(exc)) from exc

        return self._leg_view(job)

    def leg(self, job_id: str) -> S.LegJob:
        runner = self._runner()
        job = runner.job(job_id)
        if job is None:
            raise NothingThere(
                "That leg has been replaced by newer ones. Ask for the stop "
                "again and it will be rebuilt from the archive."
            )
        return self._leg_view(job)

    def leg_chunk(self, job_id: str, index: int):
        """`(path, reason)`, the shape the breach clip endpoint already uses."""
        runner = self._runner()
        return runner.chunk(job_id, index)

    def warm_next(self, anchors: list, index: int, camera_id: str, actor: str
                  ) -> str | None:
        """Warm up the camera the operator will probably click next.

        Best effort by definition. A prefetch that cannot start is not an
        error — the leg will simply be fetched when it is asked for.
        """
        if self.archive is None:
            return None
        from vg.ingest.archive import next_to_warm

        target = next_to_warm(anchors, index, list(self.config.cameras), camera_id)
        return target

    def _descriptor_at(self, point: S.ChunkPoint):
        """The body under a click inside a chunk, as an appearance descriptor.

        Deliberately returns evidence about a BODY. Whatever comes back from
        following it is APPEARANCE — blue, unnamed — even if that person is
        enrolled, because clothing is not an identification.
        """
        runner = self._runner()
        from vg.ingest.archive import descriptor_at

        path, reason = runner.chunk(point.job_id, point.chunk)
        if path is None:
            raise NothingThere(reason)

        found = descriptor_at(path, point.x, point.y, runner.detector)
        if found is None:
            raise NothingThere(
                "There is no body at that point, or too little of them is in "
                "frame to describe. Click the person themselves."
            )
        signature, _box = found
        return signature

    def _leg_view(self, job) -> S.LegJob:
        rates = self.anchors.rates() if self.anchors is not None else None
        estimate = None
        if rates is not None:
            from vg.ingest.archive import estimate_for

            estimate = estimate_for(
                job.seconds / 3600.0, rates, budget_seconds=1e9,
                chunk_seconds=self.config.archive.chunk_seconds,
            ).seconds

        return S.LegJob(
            job=S.SearchJob(
                id=job.id,
                state=job.state,
                progress=round(job.progress, 3),
                submitted_at=_instant(job.submitted_at, self.clock),
                clips_searched=len(job.chunks),
                clips_total=job.chunks_total,
                error=job.error,
            ),
            camera_id=job.camera_id,
            camera_name=self._camera_name(job.camera_id) or job.camera_id,
            place=self._area_of(job.camera_id),
            start=_instant(job.start, self.clock),
            seconds=job.seconds,
            chunks_ready=len(job.chunks),
            chunks_total=job.chunks_total,
            chunks_missing=getattr(job, "gaps", 0),
            gap_reason=getattr(job, "gap_reason", None),
            # Same-origin paths, never absolute URLs: `<video>` cannot send an
            # Authorization header, so a chunk has to be fetched through the
            # same origin the page is already signed in to.
            chunk_urls=[
                f"/path/legs/{job.id}/chunks/{chunk.index}" for chunk in job.chunks
            ],
            estimate_seconds=round(estimate, 1) if estimate is not None else None,
        )

    # -- the path behind somebody -------------------------------------------

    NO_ANCHORS = ("The path store is not running, so there is no record of "
                  "where anybody has been. Face recognition writes it.")

    def path_skeleton(
        self, person: str, on: str, actor: str,
        start: str | None = None, end: str | None = None,
    ) -> S.PathSkeleton:
        """Where somebody was that day, read straight out of the anchor table.

        No scan, no video, no model — which is the whole point: the answer is
        one indexed read, and nothing below the evidence bar was ever written,
        so it cannot contain a stop the system does not actually believe.
        """
        if self.anchors is None:
            raise SubsystemUnavailable(self.NO_ANCHORS)

        person_id, name = self._resolve_path_subject(person)
        if person_id is None:
            raise NothingThere(
                f"Nobody here is called {person!r}. Check the spelling, or "
                f"pick them from the directory."
            )

        # Audit BEFORE the answer. The promise is that every search for a
        # person is recorded, and the promise only means anything in this
        # order — a search that returned before the write could return after
        # a crash with nothing in the log.
        entry = self._log(actor, "path.skeleton", name or person_id,
                          f"{on} {start or ''}-{end or ''}")

        window_from = _at_on(on, start, self.clock)
        window_to = _at_on(on, end, self.clock)
        anchors = self.anchors.skeleton(person_id, on, window_from, window_to)

        stops: list[S.TrackStop] = []
        if self.tracking is not None:
            # The blue layer: the same body seen again, collapsed into visits
            # by the appearance store's own gap rule. Never named, never
            # merged with the green one.
            for stop in self.tracking.store.path_for(person_id, on):
                if window_from and stop.last_seen < window_from:
                    continue
                if window_to and stop.first_seen > window_to:
                    continue
                stops.append(S.TrackStop(
                    at=_instant(stop.first_seen, self.clock),
                    until=(_instant(stop.last_seen, self.clock)
                           if stop.seconds > 0 else None),
                    camera_id=stop.camera_id,
                    camera_name=self._camera_name(stop.camera_id) or stop.camera_id,
                    place=self._area_of(stop.camera_id),
                    match=S.MatchKind.APPEARANCE,
                    confidence=min(1.0, max(0.0, stop.confidence)),
                ))

        cameras = {a.camera_id for a in anchors} | {s.camera_id for s in stops}
        return S.PathSkeleton(
            subject=S.PersonRef(
                id=person_id, name=name or person_id,
                type=S.PersonType.STUDENT,
                match=S.MatchKind.FACE if anchors else S.MatchKind.NONE,
            ),
            date=on,
            audit_id=entry.id,
            anchors=[self._path_anchor(a) for a in anchors],
            appearance=stops,
            cameras=[v for v in (self.camera_view(c) for c in sorted(cameras)) if v],
            names_from=self._name_source(),
        )

    def _path_anchor(self, anchor) -> S.PathAnchor:
        return S.PathAnchor(
            camera_id=anchor.camera_id,
            camera_name=self._camera_name(anchor.camera_id) or anchor.camera_id,
            place=self._area_of(anchor.camera_id),
            at=_instant(anchor.started_at, self.clock),
            until=_instant(anchor.ended_at, self.clock),
            matches=anchor.matches,
            # Clamped, not trusted: `Confidence` is validated 0..1 and a score
            # that slipped outside it would 500 the whole response.
            score=min(1.0, max(0.0, anchor.best)),
            face_px=anchor.face_px,
        )

    def _resolve_path_subject(self, person: str) -> tuple[str | None, str | None]:
        """An id or a display name -> (id, name), or (None, None) if neither.

        Not `_resolve_person`: that one hands back whatever id it was given
        even when nobody has it, which is right for `/track` (it answers with
        an empty day) and wrong here. Asking about somebody who does not exist
        is a different thing from somebody who exists and went nowhere, and
        only one of them is worth an operator re-checking the spelling.
        """
        if self.gallery is None:
            # Nothing to check against. Take the id at face value rather than
            # refuse a question this engine simply cannot verify.
            return person, None

        found = self.gallery.person(person) or self.gallery.find_by_name(person)
        return (found.id, found.name) if found else (None, None)

    # -- sweeping a window --------------------------------------------------

    #: The wall-clock a sweep may take. Everything over it is refused with the
    #: arithmetic, so the operator narrows the question instead of watching a
    #: progress bar for an hour.
    SWEEP_BUDGET_SECONDS = 15 * 60.0

    def _sweep_cameras(self, req: S.SweepRequest) -> list[str]:
        known = {c.id: c for c in self.config.cameras if c.enabled}
        if req.camera_ids:
            chosen = [c for c in req.camera_ids if c in known]
            if not chosen:
                raise NothingThere(
                    "None of those cameras are configured and switched on.")
            return chosen
        if req.areas:
            wanted = {a.lower() for a in req.areas}
            chosen = [c.id for c in known.values() if (c.area or "").lower() in wanted]
            if not chosen:
                raise NothingThere(
                    f"No camera watches {', '.join(req.areas)}.")
            return chosen
        return list(known)

    def sweep_estimate(self, req: S.SweepRequest) -> S.SweepEstimate:
        """What it would cost. Nothing runs, and nothing is audited.

        Deliberately not audited: this is the operator finding out whether the
        question is affordable, not asking it. The audit entry belongs on the
        sweep itself, which is the thing that actually looks at people.
        """
        from vg.ingest.archive import estimate_for

        cameras = self._sweep_cameras(req)
        span = (req.end - req.start).total_seconds()
        if span <= 0:
            raise NothingThere("That window ends before it starts.")

        camera_hours = len(cameras) * span / 3600.0
        rates = self.anchors.rates() if self.anchors is not None else None
        estimate = estimate_for(
            camera_hours, rates, budget_seconds=self.SWEEP_BUDGET_SECONDS,
            chunk_seconds=self.config.archive.chunk_seconds,
        )

        return S.SweepEstimate(
            seconds=round(estimate.seconds, 1),
            # Three places, not two: a ten-minute look at one camera is
            # 0.167 camera-hours, and 0.17 reads as a rounder number than
            # the arithmetic behind it actually is.
            camera_hours=round(camera_hours, 3),
            cameras=len(cameras),
            allowed=estimate.allowed and self.archive is not None,
            reason=(estimate.reason if not estimate.allowed
                    else None if self.archive is not None else self.NO_ARCHIVE),
            measured_at=_instant(estimate.measured_at, self.clock),
        )

    def follow_stranger(self, point: S.ChunkPoint, req: S.SweepRequest,
                        actor: str) -> S.SweepJob:
        """Look for the body somebody clicked, on other cameras.

        The same sweep machinery with a colour signature instead of a person,
        and every hit it returns is APPEARANCE. Nothing here can produce a
        name, however well the system happens to know that person from
        somewhere else — clothing is not an identification, and the moment a
        page can show one from a body match, the distinction stops meaning
        anything.
        """
        runner = self._runner()
        estimate = self.sweep_estimate(req)
        if not estimate.allowed:
            raise NotAffordable(estimate.reason or "That search is too big to run.")

        descriptor = self._descriptor_at(point)
        cameras = self._sweep_cameras(req)
        self._log(actor, "path.sweep", "an unidentified person",
                  f"{len(cameras)} camera(s) from a clicked body")

        try:
            job = runner.submit_sweep(
                cameras, req.start, req.end, descriptor=descriptor)
        except QueueFull as exc:
            raise AlreadyBusy(str(exc)) from exc
        except ArchiveUnavailable as exc:
            raise SubsystemUnavailable(str(exc)) from exc

        return self._sweep_view(job, estimate.seconds)

    def start_sweep(self, req: S.SweepRequest, actor: str) -> S.SweepJob:
        """Run it — but only if the same estimate says it is affordable."""
        runner = self._runner()
        estimate = self.sweep_estimate(req)
        if not estimate.allowed:
            raise NotAffordable(estimate.reason or "That sweep is too big to run.")

        person_id, name = self._resolve_path_subject(req.person)
        if person_id is None:
            raise NothingThere(f"Nobody here is called {req.person!r}.")

        cameras = self._sweep_cameras(req)
        self._log(actor, "path.sweep", name or person_id,
                  f"{len(cameras)} camera(s), "
                  f"{estimate.camera_hours:.1f} camera-hours")

        try:
            job = runner.submit_sweep(cameras, req.start, req.end, person_id)
        except QueueFull as exc:
            raise AlreadyBusy(str(exc)) from exc
        except ArchiveUnavailable as exc:
            raise SubsystemUnavailable(str(exc)) from exc

        return self._sweep_view(job, estimate.seconds)

    def sweep(self, job_id: str) -> S.SweepJob:
        runner = self._runner()
        job = runner.sweep(job_id)
        if job is None:
            raise NothingThere("That sweep is not running any more.")
        return self._sweep_view(job)

    def stop_sweep(self, job_id: str, actor: str) -> S.SweepJob:
        runner = self._runner()
        job = runner.cancel_sweep(job_id)
        if job is None:
            raise NothingThere("That sweep is not running any more.")
        self._log(actor, "path.sweep.stop", job.person_id or "?",
                  f"stopped after {job.segments_done} of {job.segments_total}")
        return self._sweep_view(job)

    def _sweep_view(self, job, estimate: float | None = None) -> S.SweepJob:
        return S.SweepJob(
            job=S.SearchJob(
                id=job.id,
                # `stopped` is not one of SearchJob's states, and it must not
                # be dressed up as `done` — a sweep somebody cancelled found
                # what it found, not everything there was.
                state="done" if job.state == "stopped" else job.state,
                progress=round(job.progress, 3),
                submitted_at=_instant(job.submitted_at, self.clock),
                clips_searched=job.segments_done,
                clips_total=job.segments_total,
                error=job.error or ("stopped" if job.state == "stopped" else None),
            ),
            cameras=list(job.cameras),
            hits=[self._sweep_hit(h) for h in job.hits],
            segments_done=job.segments_done,
            segments_total=job.segments_total,
            segments_missing=getattr(job, "segments_missing", 0),
            estimate_seconds=round(estimate, 1) if estimate is not None else None,
        )

    def _sweep_hit(self, hit) -> S.SweepHit:
        return S.SweepHit(
            camera_id=hit.camera_id,
            camera_name=self._camera_name(hit.camera_id) or hit.camera_id,
            place=self._area_of(hit.camera_id),
            at=_instant(hit.started_at, self.clock),
            until=_instant(hit.ended_at, self.clock),
            matches=hit.matches,
            score=min(1.0, max(0.0, hit.best)),
            face_px=getattr(hit, "face_px", 0),
            # Whatever found them, said plainly. A body matched by colour is
            # APPEARANCE and is drawn blue; dressing it as FACE would make the
            # weakest evidence in the system look like the strongest.
            match=(S.MatchKind.APPEARANCE
                   if getattr(hit, "match", "face") == "appearance"
                   else S.MatchKind.FACE),
        )

    # -- following one person, live -----------------------------------------
    #
    # Every method here is a thin translation. The session itself lives in the
    # tracking worker, advanced by the frames it is already processing, which
    # is what makes the timer and the track-loss stop work with nobody
    # watching the page.

    NO_TRACKING = ("Tracking is not running, so there is nobody to follow. "
                   "Give a camera the 'track' feature and restart the engine.")

    def _tracking_worker(self):
        if self.tracking is None:
            raise SubsystemUnavailable(self.NO_TRACKING)
        return self.tracking

    def follow_start(self, camera_id: str, x: float, y: float,
                     actor: str) -> S.FollowView:
        worker = self._tracking_worker()
        try:
            session = worker.follow(camera_id, x, y, actor)
        except FollowExists as exc:
            raise AlreadyBusy(
                f"Already following {self._who(exc.session) or exc.session.stable_id} "
                f"on {self._camera_name(exc.session.camera_id)}. Stop that one first."
            ) from exc
        except NobodyThere as exc:
            raise NothingThere(str(exc)) from exc

        # Written before the answer goes out, and only for a follow that
        # actually started — a log of clicks that hit nothing is noise in the
        # one place that has to stay readable.
        self._log(actor, "track.follow", self._who(session) or session.stable_id,
                  f"{self._camera_name(camera_id)} at {x:.2f},{y:.2f}")
        return self._follow_view(session)

    def follow_view(self) -> S.FollowView | None:
        if self.tracking is None:
            return None
        session = self.tracking.follow_view()
        if session is None:
            return None
        # Keep the camera warm for as long as somebody is watching. Expires by
        # itself, so a closed tab releases it without telling us.
        self.tracking.note_interest(session.camera_id)
        return self._follow_view(session)

    def follow_end(self, actor: str) -> S.FollowView | None:
        worker = self._tracking_worker()
        session = worker.end_follow("manual")
        if session is None:
            return None
        self._log(actor, "track.follow.end",
                  self._who(session) or session.stable_id, "manual")
        return self._follow_view(session)

    def follow_record_start(self, timer_seconds: float | None,
                            actor: str) -> S.FollowView:
        worker = self._tracking_worker()
        try:
            session = worker.record(timer_seconds, actor)
        except NotFollowing as exc:
            raise NothingThere(str(exc)) from exc
        except NoRecorder as exc:
            raise SubsystemUnavailable(str(exc)) from exc
        except AlreadyRecordingFollow as exc:
            raise AlreadyBusy(str(exc)) from exc

        self._log(actor, "track.record.start",
                  self._who(session) or session.stable_id,
                  f"timer {int(timer_seconds)}s" if timer_seconds else "no timer")
        return self._follow_view(session)

    def follow_record_stop(self, actor: str) -> S.FollowView:
        worker = self._tracking_worker()
        try:
            session = worker.stop_record("manual", actor)
        except NotFollowing as exc:
            raise NothingThere(str(exc)) from exc
        except NotRecordingFollow as exc:
            raise NothingThere(str(exc)) from exc

        segments = session.recording.segments if session.recording else []
        self._log(actor, "track.record.stop",
                  self._who(session) or session.stable_id,
                  f"{len(segments)} segment(s)")
        return self._follow_view(session)

    def _who(self, session) -> str | None:
        """The followed person's name, if a face has earned one yet."""
        if not session.person_id or self.gallery is None:
            return None
        person = self.gallery.person(session.person_id)
        return person.name if person else session.person_id

    def _follow_view(self, session) -> S.FollowView:
        name = self._who(session)
        recording = None
        if session.recording is not None:
            left = None
            if session.recording.running and session.recording.timer_deadline:
                left = max(0.0, (session.recording.timer_deadline
                                 - session.last_seen_at).total_seconds())
            recording = S.FollowRecording(
                state=session.recording.state,
                reason=session.recording.reason,
                timer_seconds_left=round(left, 1) if left is not None else None,
                segments=[self._recording(r) for r in session.recording.segments],
            )

        return S.FollowView(
            stable_id=session.stable_id,
            camera_id=session.camera_id,
            camera_name=self._camera_name(session.camera_id) or session.camera_id,
            place=self._area_of(session.camera_id),
            since=_instant(session.started_at, self.clock),
            person_id=session.person_id,
            name=name,
            # FACE only once the sustained gate has been cleared: `person_id`
            # is only ever set from a binding that gate made. APPEARANCE means
            # we are holding a body, which is a claim about continuity and not
            # about who anybody is.
            match=S.MatchKind.FACE if session.person_id else S.MatchKind.APPEARANCE,
            trail=[
                S.TrailHop(
                    camera_id=hop.camera_id,
                    camera_name=self._camera_name(hop.camera_id) or hop.camera_id,
                    place=self._area_of(hop.camera_id),
                    at=_instant(hop.at, self.clock),
                )
                for hop in session.trail
            ],
            recording=recording,
            ended_reason=session.ended_reason,
        )

    def groups(self) -> list[S.GroupSummary]:
        if self.gallery is None:
            return []

        people = self.gallery.people()
        if not people:
            return []

        # The roll is enrolment and is known either way. Who is here is
        # recognition, and without it the honest answer is "unknown" - this
        # used to crash instead, because the register was read unconditionally.
        register = None
        if self.recognition_live:
            register = self._register(
                self.sightings.local_date(datetime.now(timezone.utc)))

        # Everyone holds all of them; the specific groups hold whoever was
        # filed into them. The two overlap deliberately — being in Grade 8
        # does not take somebody out of the school — so these counts do not
        # sum to the roll and nothing may add them up as though they did.
        by_group: dict[str, list] = {}
        for person in people:
            group = self._specific_group_of(person)
            if group is not None:
                by_group.setdefault(group, []).append(person)

        def here(members) -> int | None:
            if register is None:
                return None
            return sum(1 for m in members
                       if (e := register.entry(m.id)) and e.status != "absent")

        def summary(name, members) -> S.GroupSummary:
            return S.GroupSummary(name=name, people=len(members), classes=None,
                                  here=here(members))

        # Everyone first: it is the whole school, so it reads as the parent of
        # the rest rather than as one more grade sorted in among them.
        return [summary(self.EVERYONE, people)] + [
            summary(name, members) for name, members in sorted(by_group.items())
        ]

    def group(self, name: str) -> S.GroupDetail | None:
        """One group's register for today.

        `MockStore`'s version built the roster from an unfiltered register, so
        every group showed the whole school. Here the filter is the same one
        `groups()` counted with, which is what makes the header and the list
        agree.
        """
        if self.gallery is None:
            return None

        summary = next((g for g in self.groups() if g.name == name), None)
        if summary is None:
            return None

        roster = []
        if self.recognition_live:
            today = self.sightings.local_date(datetime.now(timezone.utc))
            roster = self.attendance("group", name, today).records
        return S.GroupDetail(summary=summary, roster=roster)

    #: How far back a person's history looks. Days, not weeks: a term is the
    #: unit a head teacher thinks in and 30 recorded days is close to one.
    HISTORY_DAYS = 30

    def history(self, person: str) -> S.PersonHistory | None:
        """One person's attendance over the days the system was watching.

        The denominator is deliberately not a calendar month. Weekends,
        holidays and every hour the engine was switched off would all land in
        it as absences, and a child with perfect attendance would read as
        truant. `days_recorded` counts only days somebody — anybody — was seen,
        which is the same as saying the system was up and looking.

        With recognition down the page still opens and still names the person:
        she is enrolled, nothing was watching, and "no such person" would say
        the first of those is false. The numbers come back empty and
        `/system/capabilities` carries the reason.
        """
        if self.gallery is None:
            return None

        who = self.gallery.find_by_name(person) or self.gallery.person(person)
        if who is None:
            return None

        card = S.DirectoryPerson(
            id=who.id, name=who.name, type=S.PersonType(who.type),
            group=who.group, detail=who.detail,
            photo_on_file=who.photo_on_file,
        )

        if not self.recognition_live:
            return S.PersonHistory(
                person=card, period_label="No days recorded",
                present_days=0, total_days=0,
                metrics=[S.Metric(
                    key="source", label="Source", unit="text",
                    text="Face recognition is not running, so nothing was recorded",
                )],
            )

        hours = self.config.hours
        recorded = self.sightings.days_recorded(limit=self.HISTORY_DAYS)
        seen = self.sightings.history(
            who.id, days=self.HISTORY_DAYS,
            cutoff=hours.late_cutoff, day_start=hours.start, day_end=hours.end,
        )

        present = [d for d in recorded if d in seen]
        late = [d for d in present if seen[d].status == "late"]
        missed = [d for d in recorded if d not in seen]

        # Oldest first, so the chart reads left to right like a week does.
        trend = [
            S.AttendanceTrend(
                date=day,
                label=_day_label(day),
                present_ratio=1.0 if day in seen else 0.0,
                status=(S.AttendanceStatus(seen[day].status) if day in seen
                        else S.AttendanceStatus.ABSENT),
            )
            for day in reversed(recorded)
        ]

        flags = [
            S.AttendanceFlag(date=day, kind="absence", severity=S.Severity.WARN,
                             detail="Not seen on a day the cameras were recording")
            for day in missed
        ] + [
            S.AttendanceFlag(
                date=day, kind="late", severity=S.Severity.INFO,
                detail=(f"Arrived {seen[day].minutes_late} minutes after the "
                        f"{hours.late_cutoff.strftime('%H:%M')} cut-off"),
            )
            for day in late
        ]
        flags.sort(key=lambda f: f.date, reverse=True)

        metrics = [
            S.Metric(key="present", label="Days present", value=len(present),
                     total=len(recorded)),
            S.Metric(key="late", label="Times late", value=len(late)),
        ]
        # A percentage of nothing is not 0%, it is unanswerable. Saying 0%
        # attendance for a school that has recorded no days is the kind of
        # number somebody acts on.
        if recorded:
            metrics.append(S.Metric(key="rate", label="Attendance",
                                    value=len(present) / len(recorded),
                                    unit="percent"))

        return S.PersonHistory(
            person=card,
            period_label=(f"Last {len(recorded)} recorded days"
                          if recorded else "No days recorded"),
            present_days=len(present), total_days=len(recorded),
            metrics=metrics, trend=trend, flags=flags,
        )

    # -- recording ----------------------------------------------------------

    NO_RECORDER = ("Recording is not running, so nothing can be recorded. "
                   "It starts with the cameras.")

    def _recording(self, rec) -> S.Recording:
        return S.Recording(
            id=rec.id, camera_id=rec.camera_id,
            camera_name=self._camera_name(rec.camera_id),
            state=rec.state,
            started_at=_instant(rec.started_at, self.clock),
            stopped_at=_instant(rec.stopped_at, self.clock),
            seconds=round(rec.seconds, 1),
            frames=rec.frames,
            file=str(rec.path) if rec.path else None,
            reason=rec.reason,
            max_seconds=self.recorder.max_seconds if self.recorder else 0.0,
        )

    def recording(self, camera_id: str) -> S.RecordingResult:
        """What this camera is doing, or what it last did.

        A finished recording is still worth returning: the operator pressed
        stop and wants to know where the file went.
        """
        if self.recorder is None:
            return S.RecordingResult(ok=False, reason=self.NO_RECORDER)
        current = self.recorder.current(camera_id)
        return S.RecordingResult(
            ok=True, recording=self._recording(current) if current else None)

    def start_recording(self, camera_id: str, actor: str) -> S.RecordingResult:
        if self.recorder is None:
            return S.RecordingResult(ok=False, reason=self.NO_RECORDER)
        if self.config.camera(camera_id) is None:
            return S.RecordingResult(
                ok=False, reason=f"There is no camera {camera_id!r}.")
        worker = self.registry.worker(camera_id)
        if worker is None or worker.status != "ok":
            # Starting anyway would produce a running indicator and, fifteen
            # seconds later, an empty failed recording. Saying so now is
            # kinder and just as true.
            return S.RecordingResult(
                ok=False,
                reason=f"{self._camera_name(camera_id)} is not sending frames, "
                       f"so there is nothing to record.")

        try:
            # No frame rate is passed. `camera.fps` is the analytics rate -
            # how often models run - and handing it to the recorder is what
            # turned two seconds of webcam into twenty-five seconds of slow
            # motion. The recorder measures what the camera actually delivers.
            rec = self.recorder.start(camera_id, actor)
        except AlreadyRecording:
            current = self.recorder.current(camera_id)
            return S.RecordingResult(
                ok=False,
                recording=self._recording(current) if current else None,
                reason="This camera is already recording.")

        self._log(actor, "recording.start", camera_id, f"recording {rec.id}")
        return S.RecordingResult(ok=True, recording=self._recording(rec))

    def stop_recording(self, camera_id: str, actor: str) -> S.RecordingResult:
        if self.recorder is None:
            return S.RecordingResult(ok=False, reason=self.NO_RECORDER)
        rec = self.recorder.stop(camera_id, actor)
        if rec is None:
            # It may have ended itself a moment ago - the ten-minute limit, or
            # the camera going dark. Answering a bare "not recording" would
            # hide a file that was just written, and the operator pressing
            # stop is exactly the person who wants to know where it went.
            last = self.recorder.current(camera_id)
            if last is None:
                return S.RecordingResult(
                    ok=False, reason="This camera is not recording.")
            return S.RecordingResult(
                ok=False, recording=self._recording(last),
                reason=last.reason or "This recording had already been saved.")

        self._log(actor, "recording.stop", camera_id,
                  f"recording {rec.id} - {rec.frames} frames")
        return S.RecordingResult(ok=True, recording=self._recording(rec))

    # -- recorders ----------------------------------------------------------

    #: How many channels are opened at once. A recorder is a small box and a
    #: hundred simultaneous RTSP connections is a good way to make it refuse
    #: all of them; eight keeps sixteen channels inside a few seconds without
    #: looking like an attack.
    PROBE_CONCURRENCY = 8

    def _probe_channel(
        self, channel: str, template: str, req: S.DvrConnectRequest
    ) -> S.DvrChannel:
        """Open one channel for real and report what happened.

        This is `test_connection` applied to one channel of a recorder, and
        deliberately so - there is one prober in this system, not two.
        """
        import time as _time

        from vg.ingest.source import CameraSource

        url = (template
               .replace("{channel}", channel)
               .replace("{host}", req.host)
               .replace("{port}", str(req.port)))
        source = _with_credentials(url, req.username, req.password)
        name = f"{req.name or req.host} {channel}"

        try:
            probe = CameraSource(f"probe-{channel}", source, target_fps=1)
        except ValueError as exc:
            # A template that produces something unopenable. Reported per
            # channel like any other failure, so one bad substitution does not
            # take the whole recorder down.
            return S.DvrChannel(
                channel=channel, name=name, enabled=False,
                source=_redacted(source), checked=True,
                status=S.SourceStatus.DOWN, error=str(exc),
            )

        started = _time.monotonic()
        try:
            if not probe.open():
                return S.DvrChannel(
                    channel=channel, name=name, enabled=False,
                    source=_redacted(source), checked=True,
                    status=S.SourceStatus(probe.health.status),
                    error=probe.health.last_error or "Could not open the stream",
                )
            frame = probe.read()
            latency = (_time.monotonic() - started) * 1000
            if frame is None or frame.is_stale:
                return S.DvrChannel(
                    channel=channel, name=name, enabled=False,
                    source=_redacted(source), checked=True,
                    status=S.SourceStatus.DOWN, latency_ms=latency,
                    error="Connected, but no frame arrived",
                )
            return S.DvrChannel(
                channel=channel, name=name, enabled=True,
                source=_redacted(source), checked=True,
                status=S.SourceStatus.OK, latency_ms=latency,
                resolution=f"{frame.width}x{frame.height}",
            )
        except Exception as exc:
            return S.DvrChannel(
                channel=channel, name=name, enabled=False,
                source=_redacted(source), checked=True,
                status=S.SourceStatus.DOWN, error=str(exc),
            )
        finally:
            probe.close()

    def connect_dvr(self, req: S.DvrConnectRequest) -> S.DvrConnectResult:
        """Ask a recorder which of its channels actually have a camera.

        **This override is the point of the feature.** Without it `LiveStore`
        inherited `MockStore.connect_dvr`, so a real recorder - switched off,
        wrong password, unplugged - always reported sixteen channels at
        704x576 and a green tick.

        Every channel here was opened. Nothing is inferred from a count, and a
        channel the budget never reached comes back `checked=False`, which is
        a different answer from one that was asked and did not reply.
        """
        from concurrent.futures import ThreadPoolExecutor, wait

        def unchecked(channel: str) -> S.DvrChannel:
            # No error, deliberately. There is nothing to report about a
            # channel whose answer never came back in time - "we do not know"
            # is the honest state, and it is not the same as "nothing there".
            return S.DvrChannel(
                channel=channel, name=f"{req.name or req.host} {channel}",
                enabled=False, checked=False, status=S.SourceStatus.DOWN,
            )

        workers = min(self.PROBE_CONCURRENCY, len(req.channels))
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                pool.submit(self._probe_channel, channel, req.template, req): channel
                for channel in req.channels
            }
            # One wait for the whole set, not a timeout per future. The budget
            # is wall-clock for the operator staring at a spinner, and OpenCV
            # does NOT honour its own open timeout on an unroutable address -
            # a single dead channel can block for half a minute. So the answer
            # is bounded here rather than trusted from below.
            done, _ = wait(set(futures), timeout=req.budget)

            results: dict[str, S.DvrChannel] = {}
            for future, channel in futures.items():
                if future in done and not future.cancelled():
                    try:
                        results[channel] = future.result()
                    except Exception as exc:
                        results[channel] = S.DvrChannel(
                            channel=channel,
                            name=f"{req.name or req.host} {channel}",
                            enabled=False, checked=True,
                            status=S.SourceStatus.DOWN, error=str(exc),
                        )
                else:
                    results[channel] = unchecked(channel)
        finally:
            # Never `wait=True`, which is what a `with` block would do: it
            # would block for exactly as long as the budget exists to avoid.
            # Stragglers finish into a result nobody reads, which is why they
            # are reported as unchecked rather than guessed at.
            #
            # A probe that overran keeps its thread until OpenCV lets go - up
            # to ~30s on an unroutable address, which it reaches by its own
            # timeout and not ours. Bounded by PROBE_CONCURRENCY per request,
            # so a determined operator pressing Connect repeatedly holds a few
            # dozen sleeping threads for half a minute rather than growing
            # without limit.
            pool.shutdown(wait=False, cancel_futures=True)

        # Every channel asked about is reported, answered or not (P13-FR-002).
        # Dropping the failures would leave an operator with a reason and no
        # way to see WHICH channel is wrong.
        channels = [results[c] for c in req.channels]
        answered = [c for c in channels if c.status == S.SourceStatus.OK]
        tried = [c for c in channels if c.checked]
        checked = len(tried)

        if answered:
            return S.DvrConnectResult(
                reachable=True, checked=checked, channels=channels,
                status=S.SourceStatus.OK,
            )

        auth = any(c.status == S.SourceStatus.AUTH for c in tried)
        if not tried:
            reason = (
                f"No channel answered within {req.budget:.0f}s. The recorder "
                f"at {req.host} may be switched off or unreachable.")
        elif auth:
            reason = f"{req.host} refused the username and password."
        else:
            first = next((c.error for c in tried if c.error), None)
            reason = (
                f"None of the {len(tried)} channel(s) tried on {req.host} "
                f"returned a picture." + (f" {first}" if first else ""))

        return S.DvrConnectResult(
            reachable=False, reason=reason, checked=checked, channels=channels,
            status=S.SourceStatus.AUTH if auth else S.SourceStatus.DOWN,
        )

    def scan(self) -> S.ScanResult:
        """Searching the network for devices is not built.

        It used to return `[]`, which the console rendered as "0 devices
        found" - so "we cannot look" and "your network is empty" were the same
        sentence, and the second one is a lie.
        """
        return S.ScanResult(
            available=False,
            reason=(
                "Searching the network for cameras is not available on this "
                "engine. Add a camera by its address, or connect a recorder."
            ),
        )

    def test_connection(self, req: S.TestConnectionRequest) -> S.TestConnectionResult:
        """Actually open the stream and pull a frame.

        A failure returns 200 with `ok: false` and the reason — the operator
        needs to read it next to the form they just filled in, which an HTTP
        error status could not deliver.
        """
        import time as _time

        from vg.ingest.source import CameraSource

        source = req.source
        if req.username and "://" in source and "@" not in source:
            scheme, rest = source.split("://", 1)
            source = f"{scheme}://{req.username}:{req.password or ''}@{rest}"

        try:
            probe = CameraSource("probe", source, target_fps=1)
        except ValueError as exc:
            # A source that cannot even be interpreted - an address with no
            # scheme, most often. That is the operator's typo and belongs
            # beside the form as a sentence, not as a 500.
            return S.TestConnectionResult(
                ok=False, status=S.SourceStatus.DOWN, error=str(exc))

        started = _time.monotonic()
        try:
            if not probe.open():
                return S.TestConnectionResult(
                    ok=False,
                    status=S.SourceStatus(probe.health.status),
                    error=probe.health.last_error or "Could not open the stream",
                )
            frame = probe.read()
            latency = (_time.monotonic() - started) * 1000
            if frame is None or frame.is_stale:
                return S.TestConnectionResult(
                    ok=False, status=S.SourceStatus.DOWN,
                    error="Connected, but no frame arrived",
                    latency_ms=latency,
                )
            return S.TestConnectionResult(
                ok=True, status=S.SourceStatus.OK, latency_ms=latency,
                camera=S.CameraView(
                    id="probe", name=f"{frame.width}x{frame.height}",
                    captured_at=_instant(frame.captured_at, self.clock),
                ),
            )
        finally:
            probe.close()


def _slug(name: str) -> str:
    """A stable, readable camera id from a display name."""
    import re as _re

    base = _re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return f"cam-{base}" if base else "cam"


def _with_credentials(source: str, username: str | None, password: str | None) -> str:
    """Fold a username and password into a URL.

    One source string from here on, so exactly one place has to redact it.
    Only when the URL does not already carry credentials — an operator who
    typed them into the address meant them.
    """
    if username and "://" in source and "@" not in source:
        scheme, rest = source.split("://", 1)
        return f"{scheme}://{username}:{password or ''}@{rest}"
    return source


def _redacted(source: str) -> str:
    """Mask a password in a source string that is not yet a `CameraConfig`.

    The same expression `CameraConfig.redacted_source` uses. It exists
    separately because a bulk outcome has to report the source of a camera
    that was **refused**, and a refused camera never became a config.
    """
    import re as _re

    return _re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", source)


def _source_type(kind: str) -> S.SourceType:
    mapping = {
        "RTSP": S.SourceType.RTSP,
        "DVR": S.SourceType.DVR,
        "NVR": S.SourceType.NVR,
    }
    # Webcams and files have no place in the front end's SourceType vocabulary;
    # 'IP camera' is the closest honest label for a single direct stream.
    return mapping.get(kind, S.SourceType.IP_CAMERA)
