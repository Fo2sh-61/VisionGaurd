"""The data source behind the API.

`Store` is the seam inside the seam. Routes only ever call this protocol, so
today's `MockStore` (fixtures translated into the wire shape) and tomorrow's
`EngineStore` (real detections out of the database) are interchangeable and the
route code never changes.

That matters for sequencing: the front end can be rewired against the mock and
verified *before* a single model runs. When intrusion goes live, only the
breach/zone methods swap over — the other twenty endpoints keep serving demo
data and nothing regresses.

The demo values here mirror web/src/services/mockData.ts so that swapping the
front end onto the API is a visibly no-op change.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from vg.api import schemas as S

# Cairo. The demo fixtures are written in local school time.
TZ_OFFSET_MINUTES = 180
SCHOOL_NAME = "Greenfield International School"
TODAY = date(2026, 7, 29)
CAMERA_TOTAL = 208


def at(hh: int, mm: int, day: date | None = None) -> S.Instant:
    """A school-local wall-clock time, carried as UTC plus the site's offset."""
    local = datetime.combine(day or TODAY, time(hh, mm))
    return S.Instant(
        utc=(local - timedelta(minutes=TZ_OFFSET_MINUTES)).replace(tzinfo=timezone.utc),
        tz_offset_minutes=TZ_OFFSET_MINUTES,
    )


def now() -> S.Instant:
    return S.Instant(
        utc=datetime.now(timezone.utc), tz_offset_minutes=TZ_OFFSET_MINUTES
    )


def box(x, y, w, h, **kw) -> S.Box:
    return S.Box(x=x, y=y, w=w, h=h, **kw)


def poly(x, y, w, h) -> list[S.Point]:
    return [
        S.Point(x=x, y=y),
        S.Point(x=x + w, y=y),
        S.Point(x=x + w, y=y + h),
        S.Point(x=x, y=y + h),
    ]


class SubsystemUnavailable(RuntimeError):
    """The subsystem this call needs is not running.

    Deliberately not the same answer as "not found". A 404 for a person who is
    perfectly present, on an engine where recognition never started, sends an
    administrator hunting for a problem that is not theirs. The reason travels
    in the message and reaches the screen.
    """


class NothingThere(LookupError):
    """What was asked for is not there — 404, and usually retryable.

    Separate from `SubsystemUnavailable` for the same reason that one exists:
    "nobody is standing where you clicked" and "tracking never started" send
    an operator to two completely different places.
    """


class AlreadyBusy(RuntimeError):
    """Something is already doing this — 409. The message names what."""


class NotAffordable(ValueError):
    """More work than the budget allows — 422, with the arithmetic.

    Distinct from `AlreadyBusy` on purpose: "come back in a minute" and
    "narrow your question" are different instructions, and only one of them
    is worth the operator's time to follow.
    """


class Store(Protocol):
    """Everything the API needs. Implement this to go live."""

    def site(self) -> S.SiteInfo: ...
    def zones(self) -> list[S.Zone]: ...
    def set_zone_enabled(self, zone_id: str, enabled: bool) -> S.Zone | None: ...
    def breaches(self, since_days: int) -> list[S.Breach]: ...
    def clip_for_breach(self, breach_id: str): ...
    def intrusion_cameras(self) -> list[S.CameraView]: ...

    def weapons(
        self, since: datetime | None, until: datetime | None = None
    ) -> list[S.WeaponDetection]: ...
    def review_weapon(
        self, detection_id: str, review: S.WeaponReview,
        reviewer: str | None = None,
    ) -> S.WeaponDetection | None: ...
    def weapon_cameras(self) -> list[S.CameraView]: ...
    def clip_for_weapon(self, detection_id: str): ...


    def attendance(
        self, mode: str, subject: str, on: str
    ) -> S.AttendanceResult: ...
    def count(self, place: str, window: str) -> S.CountResult: ...
    def search_lost(self, query: S.LostQuery) -> S.LostResult: ...
    def track(self, query: S.TrackQuery, actor: str) -> S.TrackResult: ...

    def path_skeleton(
        self, person: str, on: str, actor: str,
        start: str | None = None, end: str | None = None,
    ) -> S.PathSkeleton: ...

    def sweep_estimate(self, req: S.SweepRequest) -> S.SweepEstimate: ...
    def start_sweep(self, req: S.SweepRequest, actor: str) -> S.SweepJob: ...
    def follow_stranger(
        self, point: S.ChunkPoint, req: S.SweepRequest, actor: str
    ) -> S.SweepJob: ...
    def sweep(self, job_id: str) -> S.SweepJob: ...
    def stop_sweep(self, job_id: str, actor: str) -> S.SweepJob: ...

    def start_leg(self, req: S.LegRequest, actor: str) -> S.LegJob: ...
    def leg(self, job_id: str) -> S.LegJob: ...
    def leg_chunk(self, job_id: str, index: int): ...

    def follow_start(
        self, camera_id: str, x: float, y: float, actor: str
    ) -> S.FollowView: ...
    def follow_view(self) -> S.FollowView | None: ...
    def follow_end(self, actor: str) -> S.FollowView | None: ...
    def follow_record_start(
        self, timer_seconds: float | None, actor: str
    ) -> S.FollowView: ...
    def follow_record_stop(self, actor: str) -> S.FollowView: ...

    def recording(self, camera_id: str) -> S.RecordingResult: ...
    def start_recording(self, camera_id: str, actor: str) -> S.RecordingResult: ...
    def stop_recording(self, camera_id: str, actor: str) -> S.RecordingResult: ...

    def health(self) -> S.SystemHealth: ...
    def sources(self) -> list[S.CameraSource]: ...
    def areas(self) -> list[str]: ...
    def scan(self) -> list[S.FoundDevice]: ...
    def connect_dvr(self, req: S.DvrConnectRequest) -> S.DvrConnectResult: ...
    def test_connection(self, req: S.TestConnectionRequest) -> S.TestConnectionResult: ...

    def people(self) -> list[S.DirectoryPerson]: ...
    def remove_person(self, person_id: str, actor: str) -> bool: ...
    def groups(self) -> list[S.GroupSummary]: ...
    def group(self, name: str) -> S.GroupDetail | None: ...
    def history(self, person: str) -> S.PersonHistory | None: ...
    def users(self) -> list[S.User]: ...

    def attention(self) -> list[S.AttentionItem]: ...
    def acknowledge(self, item_id: str, actor: str) -> S.AttentionItem | None: ...
    def school_profile(self) -> S.SchoolProfile: ...
    def alert_rules(self) -> list[S.AlertRule]: ...
    def delivery_targets(self) -> list[S.DeliveryTarget]: ...
    def audit(self, limit: int) -> list[S.AuditEntry]: ...
    def capabilities(self) -> list[S.Capability]: ...


# ===========================================================================
# MockStore
# ===========================================================================

class MockStore:
    """Fixtures in the wire shape. Mutations are in-memory and non-persistent.

    Writes here are real enough to exercise the UI's state machines — reviewing
    a weapon, pausing a zone, acknowledging an alert all stick for the life of
    the process — so the front end can be validated properly before the engine
    exists.
    """

    def __init__(self, seed: int = 7) -> None:
        self._rng = random.Random(seed)
        self._started = datetime.now(timezone.utc)
        self._zones = self._build_zones()
        self._breaches = self._build_breaches()
        self._weapons = self._build_weapons()
        self._attention = self._build_attention()
        self._audit: list[S.AuditEntry] = []
        self._sources = self._build_sources()
        self._people = self._build_people()
        self._follow: S.FollowView | None = None
        self._follow_audit: str | None = None

    # -- overlays -----------------------------------------------------------

    def overlay(self, camera_id: str, feature: str | None = None) -> list[S.Box]:
        """Boxes to draw on one camera, for the page that asked.

        Empty here: `MockStore`'s fixture cameras carry their boxes inline,
        and there is no per-feature overlay machinery behind them to query.
        Returning nothing is the honest answer rather than handing back some
        other camera's fixtures.

        It exists on the mock at all so that callers have one interface to
        use. `app.py` previously did `getattr(store, "_tracked_boxes", None)`
        and called it if it happened to be there - which silently returned no
        identities whenever the store was a mock, and reached into another
        object's private method when it was not.
        """
        return []

    # -- site ---------------------------------------------------------------

    def site(self) -> S.SiteInfo:
        health = self.health()
        return S.SiteInfo(
            name=SCHOOL_NAME,
            today=str(TODAY),
            timezone="Africa/Cairo",
            tz_offset_minutes=TZ_OFFSET_MINUTES,
            cameras_online=health.cameras_online,
            cameras_total=health.cameras_total,
            places=["All"] + [a.name for a in self.count("Cafeteria", "Right now").areas],
            areas=self.areas(),
        )

    # -- intrusion ----------------------------------------------------------

    def _build_zones(self) -> list[S.Zone]:
        weekdays = ["mon", "tue", "wed", "thu", "fri"]
        return [
            S.Zone(
                id="chem", name="Chemistry lab", camera_id="i-chem",
                schedule=S.Schedule(mode=S.ScheduleMode.OUTSIDE, days=weekdays,
                                    start="08:00", end="16:00"),
                enabled=True, polygon=poly(0.10, 0.18, 0.52, 0.62), breaches_today=1,
            ),
            S.Zone(
                id="server", name="Server room", camera_id="i-server",
                schedule=S.Schedule(mode=S.ScheduleMode.ALWAYS, days=[]),
                enabled=True, polygon=poly(0.20, 0.22, 0.48, 0.58), breaches_today=0,
            ),
            S.Zone(
                id="roof", name="Roof access", camera_id="i-roof",
                schedule=S.Schedule(mode=S.ScheduleMode.ALWAYS, days=[]),
                enabled=True, polygon=poly(0.14, 0.24, 0.55, 0.60), breaches_today=0,
            ),
            S.Zone(
                id="pool", name="Swimming pool", camera_id="i-pool",
                schedule=S.Schedule(mode=S.ScheduleMode.OUTSIDE, days=weekdays,
                                    start="14:00", end="17:00"),
                # Paused, and deliberately still returned — the UI promises a
                # disabled zone stays visible rather than vanishing.
                enabled=False, polygon=poly(0.12, 0.20, 0.60, 0.64), breaches_today=0,
            ),
        ]

    def _build_breaches(self) -> list[S.Breach]:
        return [
            S.Breach(
                id="b1", zone_id="chem", zone_name="Chemistry lab",
                camera_id="i-chem", camera_name="Chemistry lab - door",
                at=at(6, 12), subject=S.PersonRef(match=S.MatchKind.NONE),
                status=S.BreachStatus.OPEN, severity=S.Severity.CRITICAL,
                confidence=0.93, dwell_seconds=41.0,
                clip=S.Clip(id="clip-b1", url="/clips/b1.mp4",
                            duration_seconds=24.0, starts_at=at(6, 12)),
                model_version="coco-yolov8s",
            ),
            S.Breach(
                id="b2", zone_id="roof", zone_name="Roof access",
                camera_id="i-roof", camera_name="Roof stairwell",
                at=at(22, 47, TODAY - timedelta(days=2)),
                subject=S.PersonRef(match=S.MatchKind.NONE),
                status=S.BreachStatus.RESOLVED, severity=S.Severity.WARN,
                confidence=0.81, dwell_seconds=12.0, model_version="coco-yolov8s",
            ),
            S.Breach(
                id="b3", zone_id="server", zone_name="Server room",
                camera_id="i-server", camera_name="Server room - door",
                at=at(19, 20, TODAY - timedelta(days=3)),
                subject=S.PersonRef(id="p-nassar", name="Tarek Nassar",
                                    type=S.PersonType.STAFF,
                                    match=S.MatchKind.FACE, confidence=0.96),
                status=S.BreachStatus.AUTHORISED, severity=S.Severity.INFO,
                confidence=0.96, dwell_seconds=380.0, model_version="sface-2021dec",
            ),
            S.Breach(
                id="b4", zone_id="chem", zone_name="Chemistry lab",
                camera_id="i-chem", camera_name="Chemistry lab - door",
                at=at(5, 58, TODAY - timedelta(days=9)),
                subject=S.PersonRef(match=S.MatchKind.NONE),
                status=S.BreachStatus.RESOLVED, severity=S.Severity.WARN,
                confidence=0.74, dwell_seconds=8.0, model_version="coco-yolov8s",
            ),
        ]

    def zones(self) -> list[S.Zone]:
        return list(self._zones)

    def set_zone_enabled(self, zone_id: str, enabled: bool) -> S.Zone | None:
        for i, zone in enumerate(self._zones):
            if zone.id == zone_id:
                self._zones[i] = zone.model_copy(update={"enabled": enabled})
                return self._zones[i]
        return None

    def breaches(self, since_days: int) -> list[S.Breach]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        return [b for b in self._breaches if b.at.utc >= cutoff]

    def clip_for_breach(self, breach_id: str):
        """Demo mode has no files. `(path, reason)` — the reason is honest."""
        return None, "Demo mode does not record video, so there is no clip."

    def intrusion_cameras(self) -> list[S.CameraView]:
        chem = next(z for z in self._zones if z.id == "chem")
        return [
            S.CameraView(
                id="i-chem", name="Chemistry lab - door", captured_at=at(6, 12),
                people_count=1,
                boxes=[box(0.24, 0.34, 0.19, 0.42, label="Person in zone",
                           confidence=0.93, kind="person",
                           severity=S.Severity.CRITICAL)],
                zone=S.ZoneOverlay(id="chem", label="Restricted",
                                   polygon=chem.polygon, enabled=True),
                snapshot_url="/cameras/i-chem/snapshot",
            ),
            S.CameraView(
                id="i-server", name="Server room - door", captured_at=now(),
                people_count=0,
                zone=S.ZoneOverlay(id="server", label="Restricted",
                                   polygon=poly(0.20, 0.22, 0.48, 0.58)),
                snapshot_url="/cameras/i-server/snapshot",
            ),
        ]

    # -- weapons ------------------------------------------------------------

    def _build_weapons(self) -> list[S.WeaponDetection]:
        return [
            S.WeaponDetection(
                id="w1", at=at(9, 14, date(2026, 5, 6)), camera_id="w-gate",
                camera_name="Main gate", location="Main gate - bag check",
                item="Kitchen utensil", confidence=0.62, severity=S.Severity.WARN,
                verdict=S.ReviewVerdict.DISMISSED, reviewed_by="Mohamed Fouad",
                reviewed_at=at(9, 16, date(2026, 5, 6)),
                dismissal_reason="Cafeteria knife, catering staff",
                model_version="worldv2-school-2026-05-06",
            ),
            S.WeaponDetection(
                id="w2", at=at(13, 22, date(2026, 3, 11)), camera_id="w-yard",
                camera_name="Yard 1", location="Building A - yard",
                item="Scissors", confidence=0.55, severity=S.Severity.INFO,
                verdict=S.ReviewVerdict.DISMISSED, reviewed_by="Tarek Nassar",
                reviewed_at=at(13, 25, date(2026, 3, 11)),
                dismissal_reason="Art class supplies",
                model_version="worldv2-school-2026-05-06",
            ),
            S.WeaponDetection(
                id="w3", at=at(14, 40, date(2026, 2, 18)), camera_id="w-corridor",
                camera_name="Building C corridor", location="Building C - corridor",
                item="Knife-shaped object", confidence=0.88,
                severity=S.Severity.CRITICAL, verdict=S.ReviewVerdict.CONFIRMED,
                reviewed_by="Mohamed Fouad", reviewed_at=at(14, 41, date(2026, 2, 18)),
                box=box(0.42, 0.38, 0.10, 0.14, label="Knife-shaped object",
                        confidence=0.88, kind="weapon", severity=S.Severity.CRITICAL),
                clip=S.Clip(id="clip-w3", url="/clips/w3.mp4",
                            duration_seconds=18.0, starts_at=at(14, 40, date(2026, 2, 18))),
                model_version="worldv2-school-2026-05-06",
            ),
        ]

    def weapons(
        self, since: datetime | None, until: datetime | None = None
    ) -> list[S.WeaponDetection]:
        # Either bound may be None, meaning open-ended: the page's "All"
        # period asks for every row there has ever been.
        #
        # Dismissed detections are returned too. The product promises false
        # alarms stay in the history; there is no delete and no hiding.
        return [
            w for w in self._weapons
            if (since is None or w.at.utc >= since)
            and (until is None or w.at.utc < until)
        ]

    def review_weapon(
        self, detection_id: str, review: S.WeaponReview,
        reviewer: str | None = None,
    ) -> S.WeaponDetection | None:
        # The signed-in account wins over anything the body claims. Demo
        # mode has no session, so it falls back to the body's `actor`.
        who = reviewer or review.actor or "unknown"
        for i, det in enumerate(self._weapons):
            if det.id == detection_id:
                self._weapons[i] = det.model_copy(update={
                    "verdict": review.verdict,
                    "reviewed_by": who,
                    "reviewed_at": now(),
                    "dismissal_reason": review.reason,
                })
                self._log(who, f"weapon.{review.verdict.value}",
                          detection_id, review.reason)
                return self._weapons[i]
        return None

    def clip_for_weapon(self, detection_id: str):
        """Demo mode has no files. `(path, reason)` — the reason is honest."""
        return None, "Demo mode does not record video, so there is no clip."

    def weapon_cameras(self) -> list[S.CameraView]:
        return [
            S.CameraView(
                id="w-gate", name="Main gate", captured_at=now(), people_count=3,
                boxes=[box(0.20, 0.30, 0.16, 0.40, label="Person", confidence=0.91),
                       box(0.48, 0.28, 0.17, 0.44, label="Person", confidence=0.94)],
                snapshot_url="/cameras/w-gate/snapshot",
            )
        ]

    # -- attendance ---------------------------------------------------------

    def attendance(self, mode: str, subject: str, on: str) -> S.AttendanceResult:
        if mode == "person":
            days = [
                S.AttendanceDay(date=str(TODAY - timedelta(days=d)),
                                status=(S.AttendanceStatus.ABSENT if d == 3
                                        else S.AttendanceStatus.LATE if d == 1
                                        else S.AttendanceStatus.ON_TIME),
                                seen_at=None if d == 3 else at(7, 42 + d),
                                location=None if d == 3 else "Main entrance")
                for d in range(5)
            ]
            present = sum(1 for d in days if d.status != S.AttendanceStatus.ABSENT)
            return S.AttendanceResult(
                mode="person", date=on, subject=subject,
                expected=len(days), present=present, late=1,
                absent=len(days) - present,
                metrics=[
                    S.Metric(key="present_days", label="Days present",
                             value=present, total=len(days)),
                    S.Metric(key="late_days", label="Days late", value=1),
                ],
                days=days, cameras=self._entrance_cameras(),
            )

        roster = [
            ("Layla Ahmed", "8 - B", S.AttendanceStatus.ON_TIME, at(7, 42)),
            ("Nour Hassan", "8 - B", S.AttendanceStatus.ON_TIME, at(7, 44)),
            ("Omar Khaled", "8 - A", S.AttendanceStatus.LATE, at(8, 9)),
            ("Youssef Ali", "8 - C", S.AttendanceStatus.ABSENT, None),
            ("Malak Samir", "8 - A", S.AttendanceStatus.ON_TIME, at(7, 39)),
        ]
        records = [
            S.AttendanceRecord(
                person=S.PersonRef(id=f"p-{n.split()[0].lower()}", name=n,
                                   type=S.PersonType.STUDENT,
                                   match=S.MatchKind.FACE if seen else S.MatchKind.NONE,
                                   confidence=0.94 if seen else None),
                status=st, seen_at=seen,
                location="Main entrance" if seen else None,
                minutes_late=27 if st is S.AttendanceStatus.LATE else None,
            )
            for n, _grp, st, seen in roster
        ]
        present = sum(1 for r in records if r.status != S.AttendanceStatus.ABSENT)
        return S.AttendanceResult(
            mode="group", date=on, subject=subject,
            expected=142, present=133, late=6, absent=9,
            metrics=[
                S.Metric(key="present", label="Here", value=133, total=142),
                S.Metric(key="late", label="Late", value=6),
                S.Metric(key="absent", label="Absent", value=9),
                S.Metric(key="rate", label="Attendance", value=0.936,
                         unit="percent"),
            ],
            records=records, cameras=self._entrance_cameras(),
        )

    def _entrance_cameras(self) -> list[S.CameraView]:
        return [
            S.CameraView(
                id="c-main", name="Main entrance", captured_at=at(7, 42),
                people_count=2,
                boxes=[box(0.18, 0.26, 0.20, 0.44, label="Layla A.",
                           confidence=0.96, kind="match", match=S.MatchKind.FACE),
                       box(0.52, 0.31, 0.19, 0.41, label="Nour H.",
                           confidence=0.94, kind="match", match=S.MatchKind.FACE)],
                snapshot_url="/cameras/c-main/snapshot",
            )
        ]

    # -- counting -----------------------------------------------------------

    def count(self, place: str, window: str) -> S.CountResult:
        areas_spec = [
            ("cafeteria", "Cafeteria", 372, 400, 0.28, 0.56, 0.33, 0.40),
            ("yard-a", "Yard A", 210, 500, 0.05, 0.10, 0.20, 0.35),
            ("library", "Library", 64, 120, 0.66, 0.12, 0.28, 0.30),
            ("gym", "Sports hall", 88, 250, 0.66, 0.52, 0.30, 0.42),
            ("corridor-b", "Building B corridor", 41, 150, 0.30, 0.10, 0.32, 0.36),
            ("entrance", "Main entrance", 12, 80, 0.05, 0.52, 0.20, 0.40),
        ]
        areas = [
            S.CountArea(
                id=i, name=n, count=c, capacity=cap, x=x, y=y, w=w, h=h,
                severity=(S.Severity.CRITICAL if c / cap > 0.9
                          else S.Severity.WARN if c / cap > 0.7
                          else S.Severity.INFO),
            )
            for i, n, c, cap, x, y, w, h in areas_spec
        ]
        # "All" is every area added up, not an area of its own — it never
        # appears on the plan, only in the picker.
        if place == "All":
            selected = S.CountArea(
                id="all", name="All", x=0.0, y=0.0, w=0.0, h=0.0,
                count=sum(a.count for a in areas),
                capacity=sum(a.capacity for a in areas),
                severity=S.Severity.INFO,
            )
        else:
            selected = next((a for a in areas if a.name == place), areas[0])

        bars: list[S.CountBar] = []
        title = None
        if window == "Today by hour":
            title = "Today by hour"
            bars = [S.CountBar(label=f"{h}:00", value=v)
                    for h, v in zip(range(7, 16),
                                    [40, 180, 320, 290, 372, 355, 210, 160, 90])]
        elif window == "This week by day":
            title = "This week by day"
            bars = [S.CountBar(label=d, value=v) for d, v in
                    zip(["Mon", "Tue", "Wed", "Thu", "Fri"],
                        [341, 366, 372, 358, 291])]

        return S.CountResult(
            place=selected.name, count=selected.count, capacity=selected.capacity,
            measured_at=now(), deduplicated=True,
            metrics=[
                S.Metric(key="here", label="People here", value=selected.count),
                S.Metric(key="capacity", label="Safe capacity",
                         value=selected.capacity),
                S.Metric(key="fill", label="Of capacity",
                         value=selected.count / selected.capacity, unit="percent"),
            ],
            bars=bars, bars_title=title, areas=areas,
            cameras=[S.CameraView(id="cnt-caf", name="Cafeteria - north",
                                  captured_at=now(), people_count=37,
                                  count_line=0.62,
                                  snapshot_url="/cameras/cnt-caf/snapshot")],
        )

    # -- lost items ---------------------------------------------------------

    def search_lost(self, query: S.LostQuery) -> S.LostResult:
        hits = [
            S.LostHit(camera_id="l-lib", camera_name="Library - east",
                      at=at(13, 8), confidence=0.94,
                      note="Left on a table, no owner nearby",
                      box=box(0.55, 0.62, 0.12, 0.14, kind="object",
                              confidence=0.94)),
            S.LostHit(camera_id="l-corr", camera_name="Building A corridor",
                      at=at(12, 51), confidence=0.71,
                      note="Carried, partially occluded"),
        ]
        return S.LostResult(
            job=S.SearchJob(id="job-1", state="done", progress=1.0,
                            submitted_at=now(), clips_searched=284,
                            clips_total=284),
            query=query, hits=hits,
            cameras=[S.CameraView(id="l-lib", name="Library - east",
                                  captured_at=at(13, 8),
                                  boxes=[h.box for h in hits if h.box],
                                  snapshot_url="/cameras/l-lib/snapshot")],
        )

    # -- track --------------------------------------------------------------

    def track(self, query: S.TrackQuery, actor: str) -> S.TrackResult:
        # Audit FIRST. The UI promises every tracking search is recorded, and
        # the promise only means something if the write precedes the result.
        entry = self._log(actor, "track.search", query.who or query.person_id or "?",
                          f"{query.date} {query.start or ''}-{query.end or ''}")
        path = [
            S.TrackStop(at=at(7, 42), camera_id="c-main", camera_name="Main entrance",
                        place="Main entrance", match=S.MatchKind.FACE, confidence=0.96),
            S.TrackStop(at=at(8, 3), camera_id="t-corr-a",
                        camera_name="Building A corridor", place="Building A",
                        match=S.MatchKind.APPEARANCE, confidence=0.89),
            S.TrackStop(at=at(11, 20), camera_id="cnt-caf", camera_name="Cafeteria",
                        place="Cafeteria", match=S.MatchKind.FACE, confidence=0.92),
            S.TrackStop(at=at(14, 55), camera_id="c-main", camera_name="Main entrance",
                        place="Main entrance", match=S.MatchKind.FACE, confidence=0.95),
        ]
        return S.TrackResult(
            subject=S.PersonRef(id=query.person_id or "p-layla",
                                name=query.who or "Layla Ahmed",
                                type=S.PersonType.STUDENT, match=S.MatchKind.FACE),
            date=query.date, audit_id=entry.id, sightings=len(path),
            first_seen=path[0].at, last_seen=path[-1].at,
            metrics=[
                S.Metric(key="sightings", label="Sightings", value=len(path)),
                S.Metric(key="cameras", label="Cameras",
                         value=len({s.camera_id for s in path})),
            ],
            path=path,
            cameras=[S.CameraView(
                id="c-main", name="Main entrance", captured_at=at(7, 42),
                boxes=[box(0.18, 0.26, 0.20, 0.44, label="Layla Ahmed",
                           confidence=0.96, kind="match", match=S.MatchKind.FACE)],
                snapshot_url="/cameras/c-main/snapshot")],
        )


    def path_skeleton(
        self, person: str, on: str, actor: str,
        start: str | None = None, end: str | None = None,
    ) -> S.PathSkeleton:
        # Audit FIRST, exactly as the live store does — demo mode teaches the
        # same habit rather than a different one.
        entry = self._log(actor, "path.skeleton", person, f"{on} {start or ''}-{end or ''}")
        anchors = [
            S.PathAnchor(camera_id="c-main", camera_name="Main entrance",
                         place="Main entrance", at=at(7, 42), until=at(7, 43),
                         matches=6, score=0.71, face_px=112),
            S.PathAnchor(camera_id="cnt-caf", camera_name="Cafeteria",
                         place="Cafeteria", at=at(11, 20), until=at(11, 22),
                         matches=4, score=0.66, face_px=94),
        ]
        return S.PathSkeleton(
            subject=S.PersonRef(id="p-layla", name=person or "Layla Ahmed",
                                type=S.PersonType.STUDENT, match=S.MatchKind.FACE),
            date=on, audit_id=entry.id, anchors=anchors,
            appearance=[
                S.TrackStop(at=at(8, 3), camera_id="t-corr-a",
                            camera_name="Building A corridor", place="Building A",
                            match=S.MatchKind.APPEARANCE, confidence=0.89),
            ],
        )

    NO_ARCHIVE = ("Demo mode has no recorded-video archive, so there is no "
                  "footage to play behind a stop.")

    def start_leg(self, req: S.LegRequest, actor: str) -> S.LegJob:
        # Audited even though it refuses: an operator asking to watch somebody
        # is the thing worth recording, and it happened.
        self._log(actor, "path.leg", req.person_id or req.camera_id, "demo mode")
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    def leg(self, job_id: str) -> S.LegJob:
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    def leg_chunk(self, job_id: str, index: int):
        return None, self.NO_ARCHIVE

    def sweep_estimate(self, req: S.SweepRequest) -> S.SweepEstimate:
        # An estimate with no measurement behind it is the one number this
        # feature must never invent, and demo mode has no machine to measure.
        return S.SweepEstimate(
            seconds=0.0, camera_hours=0.0, cameras=0, allowed=False,
            reason=("Demo mode has no recorded video to sweep and no measured "
                    "speeds to estimate from."),
        )

    def start_sweep(self, req: S.SweepRequest, actor: str) -> S.SweepJob:
        self._log(actor, "path.sweep", req.person, "demo mode")
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    def follow_stranger(self, point: S.ChunkPoint, req: S.SweepRequest,
                        actor: str) -> S.SweepJob:
        self._log(actor, "path.sweep", "an unidentified person", "demo mode")
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    def sweep(self, job_id: str) -> S.SweepJob:
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    def stop_sweep(self, job_id: str, actor: str) -> S.SweepJob:
        raise SubsystemUnavailable(self.NO_ARCHIVE)

    # -- following one person, live -----------------------------------------

    def follow_start(self, camera_id: str, x: float, y: float,
                     actor: str) -> S.FollowView:
        """Demo mode follows a fixture body, and audits it like the real one.

        No geometry is consulted, because there are no real bodies here to
        consult. That is the demo being a demo; the live store picks the body
        the click actually landed on.
        """
        if self._follow is not None and not self._follow.ended_reason:
            raise AlreadyBusy(
                f"Already following {self._follow.name or self._follow.stable_id}. "
                f"Stop that one first."
            )

        entry = self._log(actor, "track.follow", "Layla Ahmed",
                          f"{camera_id} at {x:.2f},{y:.2f}")
        self._follow_audit = entry.id
        self._follow = S.FollowView(
            stable_id="p7",
            camera_id="c-main",
            camera_name="Main entrance",
            place="Main entrance",
            since=now(),
            person_id="p-layla",
            name="Layla Ahmed",
            match=S.MatchKind.FACE,
            trail=[S.TrailHop(camera_id="c-main", camera_name="Main entrance",
                              place="Main entrance", at=now())],
        )
        return self._follow

    def follow_view(self) -> S.FollowView | None:
        return self._follow

    def follow_end(self, actor: str) -> S.FollowView | None:
        if self._follow is None or self._follow.ended_reason:
            return self._follow
        self._log(actor, "track.follow.end", self._follow.name, "manual")
        self._follow = self._follow.model_copy(update={"ended_reason": "manual"})
        return self._follow

    def follow_record_start(self, timer_seconds: float | None,
                            actor: str) -> S.FollowView:
        # The same refusal every other recording call gives in demo mode. A
        # fabricated segment with no file behind it is the fake save rule 4
        # forbids, and it would be fabricated exactly where an operator would
        # go looking for evidence.
        raise SubsystemUnavailable(self.NO_CAMERAS)

    def follow_record_stop(self, actor: str) -> S.FollowView:
        raise SubsystemUnavailable(self.NO_CAMERAS)

    # -- system -------------------------------------------------------------

    def _build_sources(self) -> list[S.CameraSource]:
        spec = [
            ("src-1", "NVR 1-2 - Main building", S.SourceType.NVR, "192.168.1.41", 32, "ok"),
            ("src-2", "NVR 3 - Building A", S.SourceType.NVR, "192.168.1.42", 32, "ok"),
            ("src-3", "DVR 4-6 - Building B", S.SourceType.DVR, "192.168.1.45", 48, "ok"),
            ("src-4", "DVR 7 - Building C", S.SourceType.DVR, "192.168.1.47", 16, "down"),
            ("src-5", "NVR 8 - Sports hall", S.SourceType.NVR, "192.168.1.51", 24, "ok"),
            ("src-6", "DVR 9-10 - Yards", S.SourceType.DVR, "192.168.1.55", 32, "ok"),
            ("src-7", "IP - Library", S.SourceType.IP_CAMERA, "192.168.1.80", 8, "ok"),
            ("src-8", "IP - Labs", S.SourceType.IP_CAMERA, "192.168.1.88", 15, "ok"),
            ("src-9", "Playground PTZ", S.SourceType.RTSP,
             "rtsp://192.168.1.130/main", 1, "auth"),
        ]
        return [
            S.CameraSource(id=i, name=n, type=t, ip=ip, channels=c,
                           status=S.SourceStatus(s),
                           last_error=("Recorder unreachable" if s == "down"
                                       else "Credentials rejected" if s == "auth"
                                       else None))
            for i, n, t, ip, c, s in spec
        ]

    #: Every capability the console can render, in the operator's words. One
    #: entry per thing a page can show, keyed by the store method that serves
    #: it. `LiveStore` answers the same list with real states; keeping the
    #: catalogue here means a new capability cannot be added to one and
    #: forgotten in the other.
    CAPABILITIES: tuple[tuple[str, str], ...] = (
        ("cameras", "Camera streams"),
        ("recording", "Video recording"),
        ("attendance", "Attendance register"),
        ("people", "People directory"),
        ("groups", "Groups"),
        ("count", "People counting"),
        ("track", "Track a person"),
        ("breaches", "Restricted zones"),
        ("weapons", "Weapon detection"),
        ("search_lost", "Lost item search"),
        ("users", "Users and roles"),
        ("audit", "Audit trail"),
        ("attention", "Alerts"),
    )

    def capabilities(self) -> list[S.Capability]:
        """Fixtures, and they say so.

        Every number this store returns was invented to exercise the UI. That
        is legitimate — it is how the console gets built without cameras — but
        only while the screen admits it, so there is no branch here that could
        report LIVE by accident.
        """
        return [
            S.Capability(key=key, name=name, state=S.DataState.DEMO,
                         reason="Demo mode: every number on this page is invented.")
            for key, name in self.CAPABILITIES
        ]

    def health(self) -> S.SystemHealth:
        online = sum(s.channels for s in self._sources
                     if s.status is S.SourceStatus.OK)
        total = sum(s.channels for s in self._sources)
        uptime = (datetime.now(timezone.utc) - self._started).total_seconds()
        return S.SystemHealth(
            cameras_online=online, cameras_total=total,
            recorders_online=sum(1 for s in self._sources
                                 if s.status is S.SourceStatus.OK),
            recorders_total=len(self._sources),
            severity=S.Severity.WARN if online < total else S.Severity.INFO,
            gpu_percent=0.61, cpu_percent=0.34, storage_percent=0.47,
            uptime_seconds=uptime,
            metrics=[
                S.Metric(key="gpu", label="GPU", value=0.61, unit="percent"),
                S.Metric(key="cpu", label="CPU", value=0.34, unit="percent"),
                S.Metric(key="storage", label="Storage", value=0.47, unit="percent"),
                S.Metric(key="uptime", label="Uptime 30d", value=0.996,
                         unit="percent"),
            ],
            recorders=[S.Recorder(id=s.id, name=s.name, cameras=s.channels,
                                  online=s.status is S.SourceStatus.OK, ip=s.ip)
                       for s in self._sources],
            pipeline=[
                S.PipelineStage(key="ingest", name="Camera ingest",
                                detail=f"{online} of {total} streams decoding",
                                healthy=online == total,
                                severity=(S.Severity.INFO if online == total
                                          else S.Severity.WARN),
                                restartable=True),
                S.PipelineStage(key="detect", name="Detection engine",
                                detail="Person + weapons running", healthy=True,
                                severity=S.Severity.INFO, restartable=True,
                                model_version="coco-yolov8s"),
                S.PipelineStage(key="storage", name="Clip storage",
                                detail="30 day retention, 47% used", healthy=True,
                                severity=S.Severity.INFO),
            ],
            cameras=[S.CameraView(id="sy-c3", name="Building C - Cam 3",
                                  offline=True, stale=True, captured_at=at(6, 4))],
        )

    def sources(self) -> list[S.CameraSource]:
        return list(self._sources)

    def areas(self) -> list[str]:
        return ["Main building", "Building A", "Building B", "Building C",
                "Sports hall", "Yards", "Library", "Labs"]

    def scan(self) -> list[S.FoundDevice]:
        known = {s.ip for s in self._sources}
        return [
            S.FoundDevice(name="HIK-DS7616 (Building D)", ip="192.168.1.60",
                          channels=16, type=S.SourceType.DVR),
            S.FoundDevice(name="Dahua NVR (Annex)", ip="192.168.1.63", channels=8,
                          type=S.SourceType.NVR),
            S.FoundDevice(name="IP cam - Gate 2", ip="192.168.1.80", channels=1,
                          type=S.SourceType.IP_CAMERA,
                          duplicate="192.168.1.80" in known),
        ]

    def connect_dvr(self, req: S.DvrConnectRequest) -> S.DvrConnectResult:
        count = 16
        return S.DvrConnectResult(
            source_id=f"src-{len(self._sources) + 1}",
            status=S.SourceStatus.OK,
            channels=[S.DvrChannel(channel=f"{i:02d}",
                                   name=f"{req.name or req.host} - Cam {i}",
                                   enabled=True, resolution="704x576")
                      for i in range(1, count + 1)],
        )

    # -- recording ----------------------------------------------------------
    #
    # Demo mode has no cameras, so there is nothing to record. Returning a
    # plausible-looking recording here would be a fake save: the operator
    # presses stop, is told a file was written, and goes looking for it.

    NO_CAMERAS = "There are no real cameras in demo mode, so nothing can be recorded."

    def recording(self, camera_id: str) -> S.RecordingResult:
        return S.RecordingResult(ok=False, reason=self.NO_CAMERAS)

    def start_recording(self, camera_id: str, actor: str) -> S.RecordingResult:
        return S.RecordingResult(ok=False, reason=self.NO_CAMERAS)

    def stop_recording(self, camera_id: str, actor: str) -> S.RecordingResult:
        return S.RecordingResult(ok=False, reason=self.NO_CAMERAS)

    def test_connection(self, req: S.TestConnectionRequest) -> S.TestConnectionResult:
        return S.TestConnectionResult(
            ok=True, status=S.SourceStatus.OK, latency_ms=142.0,
            camera=S.CameraView(id="test", name="Test connection",
                                captured_at=now(), people_count=0,
                                snapshot_url="/cameras/test/snapshot"),
        )

    # -- directory ----------------------------------------------------------

    def _build_people(self) -> list[S.DirectoryPerson]:
        spec = [
            ("p-layla", "Layla Ahmed", S.PersonType.STUDENT, "Grade 8", "Grade 8 - B",
             "Rana Ahmed", "mother", "+20 100 555 0143", True,
             S.AttendanceStatus.ON_TIME),
            ("p-omar", "Omar Khaled", S.PersonType.STUDENT, "Grade 8", "Grade 8 - A",
             "Khaled Fahmy", "father", "+20 100 555 0177", True,
             S.AttendanceStatus.LATE),
            ("p-youssef", "Youssef Ali", S.PersonType.STUDENT, "Grade 9", "Grade 9 - C",
             "Mona Ali", "mother", "+20 100 555 0192", False,
             S.AttendanceStatus.ABSENT),
            ("p-nassar", "Tarek Nassar", S.PersonType.STAFF, "All staff", "IT lead",
             None, None, None, True, S.AttendanceStatus.ON_TIME),
            ("p-samia", "Samia Farouk", S.PersonType.STAFF, "All staff", "Deputy head",
             None, None, None, True, S.AttendanceStatus.ON_TIME),
            ("p-dhl", "DHL courier", S.PersonType.VISITOR, None,
             "Registered Jul 28, one day", None, None, None, False, None),
        ]
        return [
            S.DirectoryPerson(id=i, name=n, type=t, group=g, detail=d,
                              guardian_name=gn, guardian_relation=gr,
                              guardian_phone=gp, photo_on_file=ph,
                              attendance_today=a)
            for i, n, t, g, d, gn, gr, gp, ph, a in spec
        ]

    def people(self) -> list[S.DirectoryPerson]:
        return list(self._people)

    def remove_person(self, person_id: str, actor: str) -> bool:
        """Take somebody out of the demo directory, and mean it.

        The demo is a working demo: a Remove button that visibly did nothing
        here would teach an evaluator that the feature does not work. The row
        goes for the life of the process, and the audit entry is written first
        exactly as the live store writes it.
        """
        person = next((p for p in self._people if p.id == person_id), None)
        if person is None:
            return False

        self._log(actor, "person.remove", person.name,
                  "removed from the directory and the face gallery")
        self._people = [p for p in self._people if p.id != person_id]
        return True

    def groups(self) -> list[S.GroupSummary]:
        # Everyone first and holding all of them, exactly as the live store
        # builds it — a demo that groups people differently from the product
        # teaches an evaluator the wrong thing about the product.
        #
        # 507 is Grades 7-9 plus staff. Bus riders overlaps those, which is
        # the point: the specific groups are not slices of a pie.
        return [
            S.GroupSummary(name="Everyone", people=507, classes=None, here=480),
            S.GroupSummary(name="All staff", people=96, classes=None, here=91),
            S.GroupSummary(name="Bus riders", people=214, classes=None, here=203),
            S.GroupSummary(name="Grade 7", people=138, classes=5, here=130),
            S.GroupSummary(name="Grade 8", people=142, classes=5, here=133),
            S.GroupSummary(name="Grade 9", people=131, classes=5, here=126),
        ]

    def group(self, name: str) -> S.GroupDetail | None:
        summary = next((g for g in self.groups() if g.name == name), None)
        if summary is None:
            return None
        return S.GroupDetail(
            summary=summary,
            roster=self.attendance("group", name, str(TODAY)).records,
        )

    def history(self, person: str) -> S.PersonHistory | None:
        who = next((p for p in self._people
                    if p.id == person or p.name == person), None)
        if who is None:
            return None
        trend = [
            S.AttendanceTrend(date=str(TODAY - timedelta(days=i)),
                              label=["Mon", "Tue", "Wed", "Thu", "Fri"][4 - i],
                              present_ratio=r, status=s)
            for i, (r, s) in enumerate([
                (1.0, S.AttendanceStatus.ON_TIME),
                (1.0, S.AttendanceStatus.LATE),
                (0.0, S.AttendanceStatus.ABSENT),
                (1.0, S.AttendanceStatus.ON_TIME),
                (1.0, S.AttendanceStatus.ON_TIME),
            ])
        ]
        return S.PersonHistory(
            person=who, period_label="Last 30 school days",
            present_days=27, total_days=30,
            metrics=[
                S.Metric(key="present", label="Days present", value=27, total=30),
                S.Metric(key="late", label="Times late", value=2),
                S.Metric(key="rate", label="Attendance", value=0.9, unit="percent"),
            ],
            trend=trend,
            flags=[S.AttendanceFlag(date=str(TODAY - timedelta(days=2)),
                                    detail="Absent, no guardian contact",
                                    kind="absence", severity=S.Severity.WARN)],
        )

    def users(self) -> list[S.User]:
        return [
            S.User(id="u1", name="Mohamed Fouad", email="mohamed61fouad@gmail.com",
                   role=S.Role.ADMIN, last_active=now()),
            S.User(id="u2", name="Tarek Nassar", email="t.nassar@greenfield.edu.eg",
                   role=S.Role.IT, last_active=at(8, 12)),
        ]

    # -- attention / settings / audit ---------------------------------------

    def _build_attention(self) -> list[S.AttentionItem]:
        return [
            S.AttentionItem(id="breach-chem", kind="intrusion", at=at(6, 12),
                            severity=S.Severity.CRITICAL,
                            title="Chemistry lab entered out of hours",
                            detail="Unidentified person, 41 seconds",
                            target="intrusion", target_id="b1"),
            S.AttentionItem(id="cam-c3-down", kind="camera", at=at(6, 4),
                            severity=S.Severity.WARN,
                            title="Building C - Cam 3 offline",
                            detail="No signal since 6:04am", target="system",
                            target_id="sy-c3"),
        ]

    def attention(self) -> list[S.AttentionItem]:
        return list(self._attention)

    def acknowledge(self, item_id: str, actor: str) -> S.AttentionItem | None:
        for i, item in enumerate(self._attention):
            if item.id == item_id:
                self._attention[i] = item.model_copy(update={"acknowledged": True})
                self._log(actor, "attention.ack", item_id, None)
                return self._attention[i]
        return None

    def school_profile(self) -> S.SchoolProfile:
        return S.SchoolProfile(
            name=SCHOOL_NAME, hours_from="07:30", hours_to="15:00",
            term_from="2025-09-01", term_to="2026-06-20", late_cutoff="08:00",
            timezone="Africa/Cairo",
        )

    def alert_rules(self) -> list[S.AlertRule]:
        return [
            S.AlertRule(key="weapon", title="Knife alerts",
                        detail="Immediately - reviewed by a person first",
                        push=True, email=True, sms=True),
            S.AlertRule(key="intrusion", title="Restricted zone alerts",
                        detail="Immediately, when someone enters a restricted area",
                        push=True, email=True, sms=False),
            S.AlertRule(key="camera", title="Camera offline",
                        detail="Sent after 5 minutes of no signal",
                        push=False, email=True, sms=False),
            S.AlertRule(key="attendance", title="Daily attendance ready",
                        detail="9:00am each school day",
                        push=False, email=True, sms=False),
        ]

    def delivery_targets(self) -> list[S.DeliveryTarget]:
        return [
            S.DeliveryTarget(key="app", title="This app", enabled=True,
                             destination="Push notifications", editable=False),
            S.DeliveryTarget(key="email", title="Email", enabled=True,
                             destination="mohamed61fouad@gmail.com"),
            S.DeliveryTarget(key="sms", title="SMS", enabled=False,
                             destination="+20 100 555 0100"),
            S.DeliveryTarget(key="wa", title="WhatsApp", enabled=False,
                             destination="+20 100 555 0100"),
        ]

    def audit(self, limit: int) -> list[S.AuditEntry]:
        return list(reversed(self._audit))[:limit]

    def _log(self, actor: str, action: str, subject: str | None,
             detail: str | None) -> S.AuditEntry:
        entry = S.AuditEntry(id=f"a{len(self._audit) + 1}", at=now(), actor=actor,
                             action=action, subject=subject, detail=detail)
        self._audit.append(entry)
        return entry
