"""The store, with real cameras in it.

`LiveStore` subclasses `MockStore` and overrides only what is genuinely live.
Everything else keeps returning demo data.

That hybrid is deliberate. The alternative — one big switch from mock to real —
means nothing works until everything works, and every feature has to land at
once. This way each capability moves across on its own: today the camera list,
health and snapshots are real while attendance and fights are still fixtures,
and the console does not care. When intrusion goes live it overrides
`breaches()` and nothing else changes.

The methods still inherited from MockStore are the honest to-do list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from vg.config import EngineConfig
from vg.api import schemas as S
from vg.api.store import MockStore
from vg.ingest.registry import CameraRegistry

log = logging.getLogger(__name__)


def _instant(when: datetime | None, offset_minutes: int) -> S.Instant | None:
    if when is None:
        return None
    return S.Instant(utc=when, tz_offset_minutes=offset_minutes)


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
        counts=None,
    ) -> None:
        super().__init__()
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
        # Track-a-person. Absent unless a camera has the `track` feature;
        # /track then falls back to fixtures rather than 500ing.
        self.tracking = tracking
        # Headcount history, so the hour/day charts are measurements rather
        # than invented numbers. Absent means those windows have nothing real
        # to show and say so instead of falling back to fixtures.
        self.counts = counts
        self._offset = _tz_offset_minutes(config.timezone)
        # Set by the lifespan when a subsystem failed to start. Surfaced on
        # System Health so a degraded engine is visible on the page an operator
        # opens to ask exactly that.
        self.recognition_error: str | None = None
        self.people_error: str | None = None
        self.tracking_error: str | None = None

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
                id=disabled.id, name=disabled.name, offline=True, stale=True
            )

        frame = worker.last_frame()
        online = worker.status == "ok"
        return S.CameraView(
            id=worker.config.id,
            name=worker.config.name,
            offline=not online,
            captured_at=_instant(frame.captured_at if frame else None, self._offset),
            # Stale means "this pixel data is not current", which is true
            # whenever the stream is down but we still have something to show.
            stale=bool(frame) and not online,
            people_count=self._people_count(worker.config.id, online),
            boxes=self._boxes(worker.config.id, feature) if online else [],
            zone=self._zone_overlay(worker.config.id) if include_zone else None,
            snapshot_url=f"/cameras/{worker.config.id}/snapshot",
            stream_url=f"/cameras/{worker.config.id}/stream",
        )

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
        if feature == "counting":
            return self._person_boxes(camera_id)
        # attendance, intrusion, weapons and the default grid all want faces.
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
            at=_instant(frame.captured_at if frame else None, self._offset),
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
        base = super().site()
        places = [self.ALL_PLACES] + [
            a.name for a in self.count(self.ALL_PLACES, "Right now").areas
        ]
        return base.model_copy(update={
            "places": places,
            "name": self.config.site_name,
            "today": datetime.now(timezone.utc).date().isoformat(),
            "timezone": self.config.timezone,
            "tz_offset_minutes": self._offset,
            "cameras_online": self.registry.online,
            "cameras_total": self.registry.total,
        })

    def zones(self) -> list[S.Zone]:
        """Zones from engine.yaml, not fixtures.

        Disabled zones are included — a paused zone stays visible.
        """
        return [
            S.Zone(
                id=z.id,
                name=z.name,
                camera_id=z.camera_id,
                schedule=S.Schedule(
                    mode=S.ScheduleMode(z.schedule.mode),
                    days=list(z.schedule.days),
                    start=z.schedule.start.strftime("%H:%M") if z.schedule.start else None,
                    end=z.schedule.end.strftime("%H:%M") if z.schedule.end else None,
                ),
                enabled=z.enabled,
                polygon=[S.Point(x=x, y=y) for x, y in z.polygon],
                breaches_today=0,
            )
            for z in self.config.zones
        ]

    def set_zone_enabled(self, zone_id: str, enabled: bool) -> S.Zone | None:
        # Config is frozen at load; the override lives in memory until the
        # events database lands in Stage C.
        self._zone_overrides = getattr(self, "_zone_overrides", {})
        self._zone_overrides[zone_id] = enabled
        for zone in self.zones():
            if zone.id == zone_id:
                return zone.model_copy(update={"enabled": enabled})
        return None

    def intrusion_cameras(self) -> list[S.CameraView]:
        # The one place the zone outline IS the subject, so it is drawn here.
        with_zones = {z.camera_id for z in self.config.zones}
        views = [self.camera_view(cid, include_zone=True) for cid in with_zones]
        return [v for v in views if v is not None] or super().intrusion_cameras()

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

        Live for any area a camera actually watches; demo figures for the rest,
        flagged as such. Mixing the two silently is what made the console
        untrustworthy before, so `CountArea.live` carries the difference all the
        way to the screen.

        "Right now" is the only honest window today. There is no time-series
        table yet, so the historical bars stay as fixtures and the page still
        renders them — but the number on the tile is measured.
        """
        base = super().count(place, window)
        counts = self._area_counts()

        areas = [
            area.model_copy(update={
                "count": counts[area.name],
                "live": True,
                "capacity": self._capacity(area.name, area.capacity),
                "severity": self._fill_severity(
                    counts[area.name], self._capacity(area.name, area.capacity)),
            })
            if area.name in counts else area
            for area in base.areas
        ]

        # Areas the config knows about but the fixtures never invented. A camera
        # added at runtime should appear here rather than being invisible.
        known = {a.name for a in areas}
        for name, value in counts.items():
            if name in known:
                continue
            capacity = self._capacity(name, 0)
            areas.append(S.CountArea(
                id=name.lower().replace(" ", "-"), name=name,
                count=value, capacity=capacity,
                x=0.05, y=0.05, w=0.18, h=0.22,
                severity=self._fill_severity(value, capacity), live=True,
            ))

        if place == self.ALL_PLACES:
            total = sum(a.count for a in areas)
            capacity = sum(a.capacity for a in areas)
            selected_name, selected_count, selected_cap = self.ALL_PLACES, total, capacity
            live = all(a.live for a in areas)
        else:
            selected = next((a for a in areas if a.name == place), areas[0])
            selected_name, selected_count = selected.name, selected.count
            selected_cap, live = selected.capacity, selected.live

        bars, bars_title, bars_note = self._history(window)

        return base.model_copy(update={
            "bars": bars,
            "bars_title": bars_title or base.bars_title,
            "place": selected_name,
            "count": selected_count,
            "capacity": selected_cap,
            "measured_at": _instant(datetime.now(timezone.utc), self._offset),
            # Areas are SUMMED across their cameras. Nothing de-duplicates a
            # person standing where two cameras overlap, so claiming otherwise
            # would be a straight overstatement. Real de-duplication needs
            # cross-camera identity, which is the tracking feature's job.
            "deduplicated": False,
            "areas": areas,
            "metrics": [
                S.Metric(key="here", label="People here", value=selected_count),
                S.Metric(key="capacity", label="Safe capacity", value=selected_cap),
                *([S.Metric(key="fill", label="Of capacity",
                            value=selected_count / selected_cap, unit="percent")]
                  if selected_cap else
                  [S.Metric(key="fill", label="Of capacity", unit="text",
                            text="No capacity set for this area")]),
                S.Metric(key="source", label="Source", unit="text",
                         text="Measured live" if live else "Demo figure"),
            ],
            "cameras": [
                v for v in (self.camera_view(cid, feature="counting")
                            for cid in self._cameras_for(selected_name))
                if v is not None
            ] or base.cameras,
        })

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
            on = datetime.now(timezone.utc).date().isoformat()
            buckets = self.counts.by_hour(on)
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
        known = sorted({c.area for c in self.registry.configs() if c.area})
        return known or super().areas()

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
            # Honest about what is not built yet. A green tick next to a feature
            # that does not exist is how a school ends up trusting nothing.
            S.PipelineStage(
                key="fights", name="Fight detection",
                detail="No model - not yet trained",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            ),
            S.PipelineStage(
                key="weapons", name="Weapon detection",
                detail="Model present but not wired to the API - "
                       "detections shown are demo data",
                healthy=False, severity=S.Severity.WARN, restartable=False,
            ),
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
        return S.PipelineStage(
            key="detect", name="Person detection",
            detail=f"Running on {stats['cameras']} camera(s), "
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
            return super().people()

        today = self.sightings.local_date(datetime.now(timezone.utc)) if self.sightings else None
        register = self._register(today) if today else None

        out = []
        for person in self.gallery.people():
            status = None
            if register is not None:
                entry = register.entry(person.id)
                status = S.AttendanceStatus(entry.status) if entry else None
            out.append(S.DirectoryPerson(
                id=person.id, name=person.name,
                type=S.PersonType(person.type),
                group=person.group, detail=person.detail,
                photo_on_file=person.photo_on_file,
                attendance_today=status,
            ))
        return out

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

    def _register(self, on: str):
        """The day's register. Absence is derived from missing sightings.

        Bounded by school hours so a sighting at 01:14 does not count as an
        on-time arrival just because it precedes the 08:00 cutoff.
        """
        hours = self.config.hours
        expected = [p.id for p in self.gallery.people() if p.photo_on_file]
        return self.sightings.register(
            on,
            expected,
            cutoff=hours.late_cutoff,
            day_start=hours.start,
            day_end=hours.end,
        )

    def attendance(self, mode: str, subject: str, on: str) -> S.AttendanceResult:
        if not self.recognition_live:
            return super().attendance(mode, subject, on)

        register = self._register(on)
        people = {p.id: p for p in self.gallery.people()}

        if mode == "person":
            person = self.gallery.find_by_name(subject) or self.gallery.person(subject)
            if person is None:
                return super().attendance(mode, subject, on)

            history = self.sightings.history(person.id, days=30)
            days = [
                S.AttendanceDay(
                    date=day,
                    status=S.AttendanceStatus.ON_TIME,
                    seen_at=_instant(entry.first_seen, self._offset),
                    location=None,
                )
                for day, entry in history.items()
            ]
            return S.AttendanceResult(
                mode="person", date=on, subject=person.name,
                expected=len(days), present=len(days), late=0,
                absent=0,
                metrics=[
                    S.Metric(key="days_seen", label="Days seen", value=len(days)),
                    S.Metric(key="sightings", label="Total sightings",
                             value=sum(e.sightings for e in history.values())),
                ],
                days=days, cameras=self.live_cameras(),
            )

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
                seen_at=_instant(entry.first_seen, self._offset),
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

        Falls back to fixtures when tracking is not running, rather than
        returning an empty day that looks like "this person went nowhere".
        """
        if self.tracking is None or self.sightings is None:
            return super().track(query, actor)

        person_id, name = self._resolve_person(query)
        if person_id is None:
            return super().track(query, actor)

        on = query.date
        stops: list[S.TrackStop] = []

        # Face sightings first - the strong claim.
        for sighting in self.sightings.sightings_on(on, person_id):
            stops.append(S.TrackStop(
                at=_instant(sighting.seen_at, self._offset),
                camera_id=sighting.camera_id,
                camera_name=self._camera_name(sighting.camera_id) or sighting.camera_id,
                place=self._area_of(sighting.camera_id),
                match=S.MatchKind.FACE,
                confidence=float(sighting.confidence),
            ))

        # Then the body, wherever the face was not visible.
        for stop in self.tracking.store.path_for(person_id, on):
            stops.append(S.TrackStop(
                at=_instant(stop.first_seen, self._offset),
                until=_instant(stop.last_seen, self._offset) if stop.seconds > 0 else None,
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
        for cam in self.config.cameras:
            if cam.id == camera_id:
                return cam.area or cam.name
        return camera_id

    def _camera_name(self, camera_id: str | None) -> str | None:
        if not camera_id:
            return None
        camera = self.config.camera(camera_id)
        return camera.name if camera else camera_id

    def groups(self) -> list[S.GroupSummary]:
        if self.gallery is None:
            return super().groups()

        people = self.gallery.people()
        if not people:
            return []

        today = self.sightings.local_date(datetime.now(timezone.utc))
        register = self._register(today)
        by_group: dict[str, list] = {}
        for person in people:
            by_group.setdefault(person.group or "Everyone", []).append(person)

        return [
            S.GroupSummary(
                name=name, people=len(members), classes=None,
                here=sum(
                    1 for m in members
                    if (e := register.entry(m.id)) and e.status != "absent"
                ),
            )
            for name, members in sorted(by_group.items())
        ]

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
                    captured_at=_instant(frame.captured_at, self._offset),
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


def _tz_offset_minutes(timezone_name: str) -> int:
    """The site's current UTC offset, in minutes.

    Windows ships no system timezone database, so `zoneinfo` needs the `tzdata`
    package (it is in requirements.txt). Falling back to 0 silently would put
    every timestamp in the console three hours out for Cairo — an event at
    6:12am would read 3:12am — so the failure is logged loudly instead.
    """
    try:
        from zoneinfo import ZoneInfo

        offset = datetime.now(ZoneInfo(timezone_name)).utcoffset()
        if offset is None:
            raise ValueError("no UTC offset")
        return int(offset.total_seconds() // 60)
    except Exception as exc:
        log.error(
            "cannot resolve timezone %r (%s) - every timestamp shown in the "
            "console will be in UTC, not local time. Install tzdata: "
            "pip install tzdata",
            timezone_name,
            exc,
        )
        return 0
