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
from datetime import date, datetime, timedelta, timezone

from vg.clock import Clock, clock_for
from vg.ingest.recorder import AlreadyRecording
from vg.config import EngineConfig
from vg.api import schemas as S
from vg.api.store import (
    AlreadyBusy,
    MockStore,
    NotAffordable,
    NothingThere,
    SubsystemUnavailable,
)
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
        lost=None,
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
        # Lost bag search. `lost_search_job` for the same reason as
        # `weapons_worker`: `lost_search` is a method on Store, and
        # assigning the job to it here would shadow the method.
        self.lost_search_job = lost
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
        self.lost_error: str | None = None

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

    def overlay(self, camera_id: str, feature: str | None = None) -> list[S.Box]:
        """The public name for `_boxes`, for callers outside this class.

        `app.py` needs the tracking overlay to build the identities list, so
        that the page and the picture cannot disagree about who is who. It
        used to reach for `_tracked_boxes` by getattr; this is the same data
        through the front door, and it keeps the per-feature rule - the caller
        still has to say which feature is asking.
        """
        return self._boxes(camera_id, feature)

    def _boxes(self, camera_id: str, feature: str | None = None) -> list[S.Box]:
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
        if feature == "weapons":
            # Above the face default on purpose. Everything unrecognised
            # used to fall through to faces, weapons included — so this
            # page would have drawn somebody's NAME beside a knife the
            # recogniser never associated with them. Rule 1, and the worst
            # sentence in the product to get wrong.
            return self._knife_boxes(camera_id)
        if feature == "lost":
            # Above the face default for the same reason as weapons, and the
            # reason is not hypothetical: knife detection shipped with this
            # branch missing. A bag search that fell through to faces would
            # draw somebody's NAME over a bag nobody has claimed.
            return self._bag_boxes(camera_id)
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

    def _bag_boxes(self, camera_id: str) -> list[S.Box]:
        """Possible bags, on the tiles. No identity, ever.

        `kind="object"` and `severity=WARN` are what `boxColor()` paints amber:
        never green (a face), never blue (a body). `match=NONE` and no
        `track_id` are not omissions - a bag has no identity to match and is
        not tracked between frames.

        The label is the class name, so an operator can tell a rucksack from a
        suitcase at a glance. It is never a person's name, and never the word
        "bag" alone dressed up as a certainty the model does not have.
        """
        if self.lost_search_job is None:
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
            for hit in self.lost_search_job.boxes_on(camera_id)
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

    def add_camera(self, req: S.AddCameraRequest) -> S.CameraSource:
        """Persist a camera and start watching it in the same call."""
        source = req.source.strip()
        # Fold credentials into the URL so the rest of the system only ever
        # deals with one source string, and only one place has to redact it.
        if req.username and "://" in source and "@" not in source:
            scheme, rest = source.split("://", 1)
            source = f"{scheme}://{req.username}:{req.password or ''}@{rest}"

        camera_id = req.id or _slug(req.name)
        config = self.cameras.add(
            camera_id=camera_id,
            name=req.name,
            source=source,
            kind=req.kind.value,
            area=req.area,
            fps=req.fps,
            features=tuple(req.features),
            rotate=req.rotate,
        )
        self.registry.add(config)

        worker = self.registry.worker(config.id)
        return S.CameraSource(
            id=config.id,
            name=config.name,
            type=req.kind,
            ip=config.redacted_source(),
            channels=1,
            # Honest immediately: a camera that has not connected yet is down,
            # not ok. It flips to ok on its first frame.
            status=S.SourceStatus(worker.status) if worker else S.SourceStatus.DOWN,
            area=config.area,
            last_error=worker.source.health.last_error if worker else None,
        )

    def remove_camera(self, camera_id: str) -> bool:
        stopped = self.registry.remove(camera_id)
        recorded = self.cameras.remove(camera_id) if self.cameras else False
        return stopped or recorded

    def camera_detections(
        self, camera_id: str, feature: str | None = None
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
            boxes=self._boxes(camera_id, feature) if online else [],
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
            cameras_total=self.registry.total,
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

    def search_lost(self, query: S.LostQuery) -> S.LostResult:
        """Start a live search over the cameras the operator ticked.

        Returns at once with a `running` job. Nothing was running before this
        call and nothing keeps running after the job ends, which is the whole
        of what "on demand" means here.
        """
        from vg.infer.colour import KNOWN_COLOURS

        # Checked here rather than on the wire type so the error can name the
        # six. "Input should be a valid enumeration member" tells an operator
        # nothing they can act on; a list of the colours does.
        if query.colour and query.colour not in KNOWN_COLOURS:
            raise ValueError(
                f"'{query.colour}' is not a colour this can look for. "
                f"Choose one of: {', '.join(KNOWN_COLOURS)}.")

        if self.lost_search_job is None:
            return self._no_lost_search(query)
        job = self.lost_search_job.start(query)
        return self._lost_result(job)

    def lost_search(self) -> S.LostResult | None:
        """The running search, or the last one. None before any has been run."""
        if self.lost_search_job is None:
            return None
        job = self.lost_search_job.current()
        return None if job is None else self._lost_result(job)

    def stop_lost_search(self) -> None:
        if self.lost_search_job is not None:
            self.lost_search_job.stop()

    def _no_lost_search(self, query: S.LostQuery) -> S.LostResult:
        """`failed`, never `done` with no hits.

        "We searched and found nothing" and "we never searched" are different
        answers, and only one of them should stop somebody looking for a
        child's missing bag.
        """
        _, reason = self._lost_state()
        return S.LostResult(
            job=S.SearchJob(
                id="unavailable", state="failed", progress=0.0,
                submitted_at=_instant(datetime.now(timezone.utc), self.clock),
                error=reason or "Lost bag search is not running.",
            ),
            query=query, hits=[], cameras=[],
        )

    def _lost_result(self, job) -> S.LostResult:
        """One job, as the page sees it.

        Two things happen here that the job deliberately does not do for
        itself: cameras get their names and areas from the live roster, and the
        colour filter is applied. The job records every bag it saw; which of
        them the operator asked about is a question about the query, not about
        the search.
        """
        from vg.features.lostbag import LIMIT_SECONDS

        now = datetime.now(timezone.utc)
        elapsed = job.seconds_elapsed(now)
        limit = getattr(self.lost_search_job, "limit_seconds", LIMIT_SECONDS)
        wanted = (job.query.colour or None) if hasattr(job.query, "colour") else None

        hits: list[S.LostHit] = []
        views: list[S.CameraView] = []
        hidden = 0
        for camera_id in job.confirmed():
            seen = job.hits[camera_id]
            matching = [h for h in seen if wanted is None or wanted in h.colours]
            if not matching:
                # Found, and deliberately not shown. The count goes on screen:
                # an operator who filtered by the wrong colour has to be able
                # to tell that from having found nothing at all.
                hidden += 1
                continue
            best = max(matching, key=lambda h: h.confidence)
            last = max(matching, key=lambda h: h.at)
            span = (last.at - min(h.at for h in matching)).total_seconds()
            hits.append(S.LostHit(
                camera_id=camera_id,
                camera_name=self._lost_camera_name(camera_id),
                at=_instant(last.at, self.clock),
                confidence=max(0.0, min(1.0, best.confidence)),
                note=f"Seen {len(matching)} times over {span:.0f} seconds",
                box=self._bag_box(best),
                # Nothing is recorded, so there is never a clip to offer.
                clip=None,
                colour=best.colour,
                colours=sorted(best.colours),
            ))
            view = self.camera_view(camera_id, feature="lost")
            if view is not None:
                # The result's box, not the live overlay's. `_bag_boxes` only
                # hands back hits younger than OVERLAY_HOLD_SECONDS, which is
                # right for a picture of what is there *now* and wrong for a
                # finished search: a minute after it ended the camera would
                # still be pinned as the one that saw a bag, with nothing drawn
                # on it to say where.
                views.append(view.model_copy(update={"boxes": [self._bag_box(best)]}))

        return S.LostResult(
            job=S.SearchJob(
                id=job.id,
                state=job.state if job.state in
                ("queued", "running", "done", "stopped", "failed") else "failed",
                progress=max(0.0, min(1.0, elapsed / limit if limit else 1.0)),
                submitted_at=_instant(job.started_at, self.clock),
                # There are no clips. Reporting a count would be the precision
                # rule broken in the one place somebody might believe it.
                clips_searched=0, clips_total=0,
                error=job.error,
            ),
            query=job.query,
            hits=hits,
            cameras=views,
            cameras_checked=len(job.checked),
            cameras_unavailable=[
                S.UnavailableCamera(camera_id=u.camera_id,
                                    camera_name=u.camera_name,
                                    reason=u.reason)
                for u in job.unavailable
            ],
            hidden_by_colour=hidden,
            frames_checked=job.frames_checked,
            seconds_limit=float(limit),
            seconds_elapsed=round(elapsed, 1),
        )

    def _bag_box(self, hit) -> S.Box:
        return S.Box(
            x=max(0.0, min(1.0, hit.x)),
            y=max(0.0, min(1.0, hit.y)),
            w=max(0.0, min(1.0, hit.w)),
            h=max(0.0, min(1.0, hit.h)),
            label=hit.label.title(),
            confidence=max(0.0, min(1.0, hit.confidence)),
            kind="object",
            severity=S.Severity.WARN,
        )

    def _lost_camera_name(self, camera_id: str) -> str:
        """The live roster first, engine.yaml second - the `_area_of` lesson.

        Not `_camera_name`: that one asks `config.camera()`, which only knows
        the cameras in engine.yaml, so a camera an operator added through the
        console comes back as its raw id. A search result is the wrong place to
        show somebody "cam-3" for a camera they named themselves.
        """
        for config in self.registry.configs():
            if config.id == camera_id:
                return config.name
        return self._camera_name(camera_id) or camera_id

    def _lost_state(self) -> tuple[S.DataState, str | None]:
        """Whether a search could be run at all, and if not, why not.

        Three failures, three sentences. "Unavailable" on its own leaves an
        operator unable to tell a model that would not load from a site with no
        camera switched on, and only one of those is theirs to fix.
        """
        if self.lost_search_job is None:
            if self.lost_error:
                return S.DataState.UNAVAILABLE, self.lost_error
            return (S.DataState.UNAVAILABLE,
                    "Lost bag search is not running, so no camera can be "
                    "searched.")
        return S.DataState.LIVE, None

    def _lost_stage(self) -> S.PipelineStage:
        """Rule 8: a subsystem that failed to start says so in the UI.

        The reason is the same sentence the capability gives, so the page and
        System Health cannot disagree about whether a search is possible.
        """
        state, reason = self._lost_state()
        if state is not S.DataState.LIVE:
            return S.PipelineStage(
                key="search_lost", name="Lost bag search",
                detail=reason or "Not running.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self.lost_search_job.stats
        detector = getattr(self.lost_search_job, "detector", None)
        version = getattr(detector, "version", "unknown")
        device = getattr(detector, "device", "unknown")
        cameras = stats["cameras"]
        doing = (f"searching {cameras} camera{'' if cameras == 1 else 's'}"
                 if stats["state"] == "running" else "idle")
        return S.PipelineStage(
            key="search_lost", name="Lost bag search",
            detail=f"{version} on {device} - {doing}",
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

    def review_weapon(self, detection_id: str, review: S.WeaponReview,
                      reviewer: str | None = None) -> S.WeaponDetection | None:
        """A person decides. The only thing in this feature that fans out.

        The detector never notifies, calls or locks anything on its own —
        this endpoint is the single point an alert spec may hang from, and
        today it hangs nothing.

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
        """The configured cameras, with their true status."""
        out: list[S.CameraSource] = []
        for cid, worker in self.registry.workers.items():
            out.append(S.CameraSource(
                id=cid,
                name=worker.config.name,
                type=_source_type(worker.config.kind),
                ip=worker.source.redacted,
                channels=1,
                status=S.SourceStatus(worker.status),
                area=worker.config.area,
                last_error=worker.source.health.last_error,
            ))
        for cid, cam in self.registry.disabled.items():
            out.append(S.CameraSource(
                id=cid, name=cam.name, type=_source_type(cam.kind),
                ip=cam.redacted_source(), channels=1,
                status=S.SourceStatus.DOWN, area=cam.area,
                last_error="Disabled in engine.yaml",
            ))
        return out

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
        return [
            S.User(id=u.id, name=u.name, email=u.email, role=u.role)
            for u in self.users_store.users()
            if not u.disabled
        ]

    def audit(self, limit: int) -> list[S.AuditEntry]:
        # Real entries, from this process. They are lost on restart and
        # `capabilities()` says so, but what is here actually happened.
        return super().audit(limit)

    def attention(self) -> list[S.AttentionItem]:
        return []

    def acknowledge(self, item_id: str, actor: str) -> S.AttentionItem | None:
        return None

    def alert_rules(self) -> list[S.AlertRule]:
        return []

    def delivery_targets(self) -> list[S.DeliveryTarget]:
        return []

    def scan(self) -> list[S.FoundDevice]:
        return []

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
            "search_lost": self._lost_state(),
            "users": live(
                self.users_store is not None,
                "The accounts database is not loaded, so nobody can sign in."),
            "audit": (S.DataState.UNAVAILABLE,
                      "The audit trail is kept in memory only and is lost when "
                      "the engine restarts."),
            "attention": (S.DataState.UNAVAILABLE,
                          "Alerts are not built yet. Nothing is being sent to "
                          "anybody."),
        }

        out: list[S.Capability] = []
        for key, name in self.CAPABILITIES:
            state, reason = states.get(
                key, (S.DataState.UNAVAILABLE, "Not built yet."))
            out.append(S.Capability(key=key, name=name, state=state, reason=reason))
        return out

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

    def health(self) -> S.SystemHealth:
        online, total = self.registry.online, self.registry.total
        sources = self.sources()

        pipeline = [
            S.PipelineStage(
                key="ingest", name="Camera ingest",
                detail=f"{online} of {total} streams decoding",
                healthy=online == total and total > 0,
                severity=S.Severity.INFO if online == total else S.Severity.WARN,
                restartable=True,
            ),
            self._recognition_stage(),
            self._people_stage(),
            self._clock_stage(),
            self._weapons_stage(),
            self._lost_stage(),
        ]

        return S.SystemHealth(
            cameras_online=online, cameras_total=total,
            recorders_online=sum(1 for s in sources if s.status is S.SourceStatus.OK),
            recorders_total=len(sources),
            severity=S.Severity.WARN if online < total else S.Severity.INFO,
            metrics=[
                S.Metric(key="cameras", label="Cameras up", value=online, total=total),
                S.Metric(key="frames", label="Frames read",
                         value=sum(w.source.health.frames_read
                                   for w in self.registry.workers.values())),
                S.Metric(key="reconnects", label="Reconnects",
                         value=sum(w.source.health.reconnects
                                   for w in self.registry.workers.values())),
            ],
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
                healthy=False, severity=S.Severity.CRITICAL, restartable=True,
            )

        if not self.recognition_live:
            return S.PipelineStage(
                key="recognition", name="Face recognition",
                detail="Off - no camera has the 'attendance' feature. "
                       "Attendance is showing DEMO DATA.",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

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
            healthy=True, severity=S.Severity.INFO, restartable=True,
        )

    def _people_stage(self) -> S.PipelineStage:
        if self.people_error:
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail=f"Failed to start - {self.people_error}. "
                       f"Counting and intrusion are showing DEMO DATA.",
                healthy=False, severity=S.Severity.CRITICAL, restartable=True,
            )

        if self.people_worker is None:
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail="Off - no camera asks for counting, intrusion or track",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            )

        stats = self.people_worker.stats
        if not stats["cameras"]:
            # The model is loaded and knife detection is using it, but no
            # camera asked for counting, intrusion or track. "Running on 0
            # camera(s)" would read as broken; it is neither broken nor idle.
            return S.PipelineStage(
                key="detect", name="Person detection",
                detail="Loaded and shared with knife detection. No camera "
                       "asks for counting, intrusion or track.",
                healthy=True, severity=S.Severity.INFO, restartable=True,
            )
        return S.PipelineStage(
            key="detect", name="Person detection",
            detail=f"Running on {stats['cameras']} camera(s), "
                   f"{stats['last_inference_ms']}ms last inference",
            healthy=True, severity=S.Severity.INFO, restartable=True,
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

        stats = self.weapons_worker.stats
        knives = getattr(self.weapons_worker, "knives", None)
        version = getattr(knives, "version", "unknown")
        device = getattr(knives, "device", "unknown")
        return S.PipelineStage(
            key="weapons", name="Knife detection",
            detail=f"{version} on {device} - {stats['cameras']} camera(s), "
                   f"{stats['last_inference_ms']}ms last inference",
            healthy=True, severity=S.Severity.INFO, restartable=True,
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
        )

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

        probe = CameraSource("probe", source, target_fps=1)
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


def _source_type(kind: str) -> S.SourceType:
    mapping = {
        "RTSP": S.SourceType.RTSP,
        "DVR": S.SourceType.DVR,
        "NVR": S.SourceType.NVR,
    }
    # Webcams and files have no place in the front end's SourceType vocabulary;
    # 'IP camera' is the closest honest label for a single direct stream.
    return mapping.get(kind, S.SourceType.IP_CAMERA)
