"""The wire contract.

These mirror `web/src/types.ts`, but structured. The front end's types carry
rendered prose — `time: 'Today, 6:12am'`, `meta: '7 seconds - 2 people'`,
`heading: '1,679 of 1,742 arrived'` — which is fine for a fixture and wrong for
an API. Copy changes and Arabic would need a backend deploy, and the data would
be useless to anything but this one screen.

So the split is:

    engine  ->  numbers, ISO-8601 UTC instants, enums, ids
    api.ts  ->  the sentences the pages already expect (services/format.ts)

The pages still never change. Only the seam gets a formatting layer.

Three rules carried over from docs/INTEGRATION-PLAN.md §1.1 and enforced here:

  Geometry is normalised.  Boxes and polygons are fractions of the frame,
      origin top-left. Validated 0..1 — a pixel value is a bug, not a big number.

  Time is server-authoritative.  Every event carries `tsUtc` plus the camera's
      `tzOffsetMinutes`. The UI never computes "11 min ago" from its own clock.

  Severity is a backend decision.  The engine emits `severity`; the UI maps it
      to a colour. Thresholds stay server-side and auditable, and the UI keeps
      naming its own palette.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# A fraction of the frame or the floor-plan. Never pixels.
Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Wire(BaseModel):
    """Base: camelCase on the wire, snake_case in Python, extras rejected."""

    model_config = ConfigDict(
        alias_generator=lambda s: "".join(
            w if i == 0 else w.capitalize() for i, w in enumerate(s.split("_"))
        ),
        populate_by_name=True,
        extra="forbid",
    )


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """What the engine decides. `format.ts` maps this onto the UI's `Tone`.

    info -> neutral/good, warn -> warn, critical -> bad.
    """

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class SourceStatus(str, Enum):
    """Matches `SourceStatus` in types.ts exactly."""

    OK = "ok"
    DOWN = "down"
    AUTH = "auth"


class SourceType(str, Enum):
    NVR = "NVR"
    DVR = "DVR"
    IP_CAMERA = "IP camera"
    RTSP = "RTSP"


class PersonType(str, Enum):
    STUDENT = "Student"
    STAFF = "Staff"
    VISITOR = "Visitor"


class Role(str, Enum):
    ADMIN = "admin"
    IT = "it"


class MatchKind(str, Enum):
    """How a person was identified.

    The UI already distinguishes these — green box for a face match, blue for
    appearance — so the distinction has to survive the wire.
    """

    FACE = "face"
    APPEARANCE = "appearance"
    NONE = "none"


class ReviewVerdict(str, Enum):
    """The weapons review state machine.

    `PENDING -> CONFIRMED | DISMISSED`, and dismissed rows are retained forever.
    Collapsing these would break the product's core safety claim: nothing fans
    out until a human decides.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class BreachStatus(str, Enum):
    OPEN = "open"
    AUTHORISED = "authorised"
    RESOLVED = "resolved"


class ScheduleMode(str, Enum):
    OUTSIDE = "outside"
    INSIDE = "inside"
    ALWAYS = "always"


class AttendanceStatus(str, Enum):
    ON_TIME = "on_time"
    LATE = "late"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

class Instant(Wire):
    """A moment in time, unambiguously.

    `utc` is the truth. `tz_offset_minutes` is the camera's local offset, so the
    UI can render "6:12am" as the site experienced it without guessing at the
    viewer's timezone — a phone in another country must not relabel an event.
    """

    utc: datetime
    tz_offset_minutes: int = 0


class Box(Wire):
    """A detection box in fractions of the frame, origin top-left."""

    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction
    label: str | None = None
    confidence: Confidence | None = None
    kind: Literal["person", "weapon", "object", "face", "match"] = "person"
    match: MatchKind = MatchKind.NONE
    severity: Severity = Severity.INFO
    # The appearance identity following this body, e.g. "p7". Survives leaving
    # and re-entering a frame, and moving between cameras, which is the whole
    # point of tracking — so it has to reach the screen, not stop at the
    # database. None when the camera is not being tracked.
    track_id: str | None = None


class Point(Wire):
    x: Fraction
    y: Fraction


class ZoneOverlay(Wire):
    """A zone drawn on a frame. Polygon, not a rectangle.

    types.ts calls `CameraZone` a polygon but models it as x/y/w/h. Real zones
    are rarely rectangles, so the wire carries points and `format.ts` collapses
    them to a bounding box for today's renderer. When the UI learns polygons,
    only that helper changes.
    """

    id: str
    label: str
    polygon: list[Point] = Field(min_length=3)
    enabled: bool = True


class CameraView(Wire):
    """A camera tile.

    `offline` is deliberately separate from "no detections". The UI is required
    to say NO SIGNAL rather than show a stale frame as if it were live, so the
    engine must distinguish 'stream down' from 'stream up, nothing found'.
    """

    id: str
    name: str
    offline: bool = False
    captured_at: Instant | None = None
    # Set when serving the last good frame of a dropped stream. The UI shows
    # NO SIGNAL over it; it must never be presented as current.
    stale: bool = False
    people_count: int | None = None
    boxes: list[Box] = Field(default_factory=list)
    zone: ZoneOverlay | None = None
    # Vertical position of the counting line, as a fraction of frame height.
    count_line: Fraction | None = None
    snapshot_url: str | None = None
    stream_url: str | None = None


class CameraDetections(Wire):
    """Everything that changes frame to frame, in one small payload.

    The enlarged view polls this ~10x a second, so it carries the boxes AND
    the headcount together rather than making the client run two timers
    against two endpoints for data from the same inference pass. Splitting
    them would also let the count and the boxes disagree by a frame.
    """

    camera_id: str
    at: Instant | None = None
    boxes: list["Box"] = Field(default_factory=list)
    # None means nothing measured this camera — not zero.
    people_count: int | None = None
    inference_ms: float | None = None


class Metric(Wire):
    """One number on a stat tile.

    `value` is a number and `unit` says what it is, so the UI can format and
    localise. types.ts has `Stat.value: string`; format.ts renders this into it.
    """

    key: str
    label: str
    value: float | None = None
    unit: Literal["count", "percent", "seconds", "ratio", "text"] = "count"
    text: str | None = None
    total: float | None = None
    severity: Severity = Severity.INFO


class Clip(Wire):
    id: str
    url: str
    thumbnail_url: str | None = None
    duration_seconds: float
    starts_at: Instant


class PersonRef(Wire):
    """Who someone is, when we know.

    `id` is opaque and stable. The front end currently keys people by display
    name and puts names in URLs, which breaks the moment two students share one.
    The wire carries both so the UI can migrate without a flag day.
    """

    id: str | None = None
    name: str | None = None
    type: PersonType | None = None
    match: MatchKind = MatchKind.NONE
    confidence: Confidence | None = None


# ---------------------------------------------------------------------------
# intrusion — the first slice
# ---------------------------------------------------------------------------

class Schedule(Wire):
    """When a zone is restricted. The UI renders this as a sentence."""

    mode: ScheduleMode
    days: list[str] = Field(default_factory=list)
    start: str | None = None  # "08:00"
    end: str | None = None  # "16:00"


class Zone(Wire):
    id: str
    name: str
    camera_id: str
    schedule: Schedule
    enabled: bool
    polygon: list[Point] = Field(min_length=3)
    # Disabled zones stay in every response. The UI promises a paused zone
    # remains visible, so filtering it out server-side would be a lie.
    breaches_today: int = 0


class ZoneUpdate(Wire):
    enabled: bool


class Breach(Wire):
    id: str
    zone_id: str
    zone_name: str
    camera_id: str
    camera_name: str
    at: Instant
    subject: PersonRef
    status: BreachStatus
    severity: Severity
    confidence: Confidence
    dwell_seconds: float
    clip: Clip | None = None
    model_version: str | None = None


# ---------------------------------------------------------------------------
# weapons
# ---------------------------------------------------------------------------

class WeaponDetection(Wire):
    """A candidate, not a verdict.

    Nothing downstream fires on this alone — the review endpoint is the only
    thing that fans out. Dismissed rows are kept and still returned by history;
    there is deliberately no delete.
    """

    id: str
    at: Instant
    camera_id: str
    camera_name: str
    location: str
    item: str
    confidence: Confidence
    severity: Severity
    verdict: ReviewVerdict
    reviewed_by: str | None = None
    reviewed_at: Instant | None = None
    dismissal_reason: str | None = None
    box: Box | None = None
    clip: Clip | None = None
    model_version: str | None = None


class WeaponReview(Wire):
    verdict: Literal[ReviewVerdict.CONFIRMED, ReviewVerdict.DISMISSED]
    actor: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# fights
# ---------------------------------------------------------------------------

class FightIncident(Wire):
    """Duration and participants are numbers here.

    types.ts packs them into `meta: '7 seconds - 2 people'`. The product rule is
    that a fight needs >= 3 seconds, enforced server-side, and the UI's "7
    seconds" must be the model's actual measurement — so it travels as a float.
    """

    id: str
    at: Instant
    camera_id: str
    camera_name: str
    location: str
    area: str
    duration_seconds: float
    participants: int
    confidence: Confidence
    severity: Severity
    reviewed: bool = False
    marked_not_a_fight: bool = False
    clip: Clip | None = None
    model_version: str | None = None


class FightFeedback(Wire):
    """The label that retrains the classifier. Worth storing properly."""

    not_a_fight: bool = True
    actor: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# attendance
# ---------------------------------------------------------------------------

class AttendanceRecord(Wire):
    person: PersonRef
    status: AttendanceStatus
    seen_at: Instant | None = None
    camera_id: str | None = None
    location: str | None = None
    minutes_late: int | None = None


class AttendanceDay(Wire):
    date: str  # ISO date, "2026-07-29"
    status: AttendanceStatus
    seen_at: Instant | None = None
    location: str | None = None


class AttendanceResult(Wire):
    mode: Literal["group", "person"]
    date: str
    subject: str
    expected: int
    present: int
    late: int
    absent: int
    metrics: list[Metric] = Field(default_factory=list)
    records: list[AttendanceRecord] = Field(default_factory=list)
    days: list[AttendanceDay] = Field(default_factory=list)
    cameras: list[CameraView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# counting
# ---------------------------------------------------------------------------

class CountBarPart(Wire):
    """One area's share of a bar.

    The bar used to be a single number with nothing saying which place it
    counted, which made "320 at 9:00" unreadable on a site with six areas.
    """

    name: str
    value: int
    live: bool = False


class CountBar(Wire):
    """`value` is the count. The UI derives bar height itself.

    types.ts carries a precomputed `pct` relative to the tallest bar; that is a
    rendering concern and does not belong on the wire.
    """

    label: str
    value: int
    at: Instant | None = None
    # Per-area split of this bucket. Empty when nothing was recorded.
    parts: list[CountBarPart] = Field(default_factory=list)


class CountArea(Wire):
    """One area on the campus plan. Geometry normalised, like everything else."""

    id: str
    name: str
    count: int
    capacity: int
    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction
    severity: Severity
    # Whether a camera actually measured this, or it is a demo figure. DEV_PLAN
    # 4.6: a page mixing real and invented numbers with nothing to tell them
    # apart is the exact failure that made the console untrustworthy before.
    live: bool = False


class CountResult(Wire):
    place: str
    count: int
    capacity: int | None = None
    measured_at: Instant
    # Counting dedups across overlapping cameras. Saying so lets the UI keep its
    # "a person between two cameras is counted once" promise honestly.
    deduplicated: bool = True
    metrics: list[Metric] = Field(default_factory=list)
    bars: list[CountBar] = Field(default_factory=list)
    bars_title: str | None = None
    areas: list[CountArea] = Field(default_factory=list)
    cameras: list[CameraView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# lost items — job-based, it runs over stored footage
# ---------------------------------------------------------------------------

class LostQuery(Wire):
    item: str
    colour: str | None = None
    area: str | None = None
    since: str | None = None


class LostHit(Wire):
    camera_id: str
    camera_name: str
    at: Instant
    confidence: Confidence
    note: str | None = None
    box: Box | None = None
    clip: Clip | None = None


class SearchJob(Wire):
    """POST returns one of these; the UI polls or streams until `done`.

    The Lost Items page already has a "Searching footage…" state built for
    exactly this, and the budget is under a minute.
    """

    id: str
    state: Literal["queued", "running", "done", "failed"]
    progress: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    submitted_at: Instant
    clips_searched: int = 0
    clips_total: int = 0
    error: str | None = None


class LostResult(Wire):
    job: SearchJob
    query: LostQuery
    hits: list[LostHit] = Field(default_factory=list)
    cameras: list[CameraView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# track a person
# ---------------------------------------------------------------------------

class TrackQuery(Wire):
    person_id: str | None = None
    who: str | None = None
    date: str
    start: str | None = None  # "07:30"
    end: str | None = None


class TrackStop(Wire):
    at: Instant
    until: Instant | None = None
    camera_id: str
    camera_name: str
    place: str
    match: MatchKind
    confidence: Confidence
    clip: Clip | None = None


class TrackResult(Wire):
    subject: PersonRef
    date: str
    # The audit row is written BEFORE this result is returned. If the write
    # fails the search fails — the UI promises every search is recorded, and
    # that promise is only worth anything if it is ordered this way.
    audit_id: str
    sightings: int
    first_seen: Instant | None = None
    last_seen: Instant | None = None
    metrics: list[Metric] = Field(default_factory=list)
    path: list[TrackStop] = Field(default_factory=list)
    cameras: list[CameraView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# system health
# ---------------------------------------------------------------------------

class Recorder(Wire):
    id: str
    name: str
    cameras: int
    online: bool
    ip: str | None = None


class PipelineStage(Wire):
    """A running piece of the engine, plus honest degradation.

    A model being unloaded or a recorder refusing a password are states the UI
    already renders. They arrive as payload, never as an HTTP 500.
    """

    key: str
    name: str
    detail: str
    healthy: bool
    severity: Severity
    restartable: bool = False
    model_version: str | None = None


class DataState(str, Enum):
    """Where a page's data came from. There is no fourth answer.

    The distinction the UI has to draw is not "good/bad", it is "believe this
    or do not". LIVE is measured. UNAVAILABLE is an honest refusal and always
    carries a reason. DEMO is invented on purpose, for showing the console to
    someone without cameras, and must never appear outside demo mode.
    """

    LIVE = "live"
    UNAVAILABLE = "unavailable"
    DEMO = "demo"


class Capability(Wire):
    """One thing the console can show, and whether it currently can.

    This is the list the screen checks before it renders a number. It exists
    because a page cannot tell an empty register from a broken one, and
    guessing wrong in either direction misleads an operator: invented rows
    read as fact, and a real empty day reads as a fault.
    """

    #: Matches the store method that serves it — "attendance", "track".
    key: str
    #: What an operator calls it, not what the code calls it.
    name: str
    state: DataState
    #: Why, in the operator's words. Required when UNAVAILABLE, and absent
    #: when LIVE — an explanation attached to a working feature reads as a
    #: fault report.
    reason: str | None = None


class SystemHealth(Wire):
    cameras_online: int
    cameras_total: int
    recorders_online: int
    recorders_total: int
    severity: Severity
    gpu_percent: float | None = None
    cpu_percent: float | None = None
    storage_percent: float | None = None
    uptime_seconds: float | None = None
    metrics: list[Metric] = Field(default_factory=list)
    recorders: list[Recorder] = Field(default_factory=list)
    pipeline: list[PipelineStage] = Field(default_factory=list)
    cameras: list[CameraView] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# camera onboarding
#
# `connectDvr()` and `testConnection()` currently take no arguments — the host
# and credentials the operator types never leave the component. These request
# bodies are the fix, and they are why those two signatures have to change.
# ---------------------------------------------------------------------------

class CameraSource(Wire):
    id: str
    name: str
    type: SourceType
    ip: str
    channels: int
    status: SourceStatus
    area: str | None = None
    last_error: str | None = None


class AddCameraRequest(Wire):
    """Add a camera from the console.

    `source` is the same vocabulary engine.yaml uses — `rtsp://…`, `webcam:0`,
    or a file path — so what an operator types is exactly what a config file
    would contain. No second dialect to learn or translate.
    """

    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1)
    id: str | None = None
    kind: SourceType = SourceType.RTSP
    area: str = "Unassigned"
    fps: float = Field(default=5.0, gt=0, le=60)
    # What this camera is watched for. Each feature loads models, so an empty
    # list means the camera streams but nothing analyses it — a valid choice.
    features: list[str] = Field(default_factory=lambda: ["counting"])
    rotate: int = 0
    username: str | None = None
    password: str | None = None


class FoundDevice(Wire):
    name: str
    ip: str
    channels: int
    type: SourceType = SourceType.IP_CAMERA
    duplicate: bool = False
    added: bool = False


class DvrConnectRequest(Wire):
    host: str
    port: int = 554
    username: str
    password: str
    type: SourceType = SourceType.DVR
    name: str | None = None
    area: str | None = None


class DvrChannel(Wire):
    channel: str
    name: str
    enabled: bool = True
    resolution: str | None = None


class DvrConnectResult(Wire):
    source_id: str
    channels: list[DvrChannel]
    status: SourceStatus


class TestConnectionRequest(Wire):
    source: str  # rtsp:// url, webcam:0, or an existing source id
    username: str | None = None
    password: str | None = None
    timeout_seconds: float = 8.0


class TestConnectionResult(Wire):
    ok: bool
    status: SourceStatus
    camera: CameraView | None = None
    # A failure is data, not an error status code — the UI renders it.
    error: str | None = None
    latency_ms: float | None = None


# ---------------------------------------------------------------------------
# people directory
# ---------------------------------------------------------------------------

class DirectoryPerson(Wire):
    id: str
    name: str
    type: PersonType
    group: str | None = None
    detail: str | None = None
    guardian_name: str | None = None
    guardian_relation: str | None = None
    guardian_phone: str | None = None
    # Drives the UI's honest "cannot be recognised without a photo" line.
    photo_on_file: bool = False
    attendance_today: AttendanceStatus | None = None


class GroupSummary(Wire):
    name: str
    people: int
    classes: int | None = None
    here: int


class GroupDetail(Wire):
    summary: GroupSummary
    roster: list[AttendanceRecord] = Field(default_factory=list)


class AttendanceTrend(Wire):
    date: str
    label: str
    present_ratio: Annotated[float, Field(ge=0.0, le=1.0)]


class AttendanceFlag(Wire):
    date: str
    detail: str
    kind: str
    severity: Severity


class PersonHistory(Wire):
    person: DirectoryPerson
    period_label: str
    present_days: int
    total_days: int
    metrics: list[Metric] = Field(default_factory=list)
    trend: list[AttendanceTrend] = Field(default_factory=list)
    flags: list[AttendanceFlag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# attention feed — what the WebSocket pushes
# ---------------------------------------------------------------------------

class AttentionItem(Wire):
    id: str
    kind: Literal["weapon", "intrusion", "camera", "attendance", "system"]
    at: Instant
    severity: Severity
    title: str
    detail: str
    target: str
    target_id: str | None = None
    acknowledged: bool = False
    clip: Clip | None = None


class Acknowledgement(Wire):
    actor: str


class LiveEvent(Wire):
    """One WebSocket frame.

    Home's "Needs your attention" list and the mobile push settings both assume
    these arrive unprompted rather than on a poll.
    """

    type: Literal[
        "weapon.detected",
        "weapon.reviewed",
        "fight.detected",
        "intrusion.breach",
        "camera.status",
        "count.updated",
        "system.health",
    ]
    at: Instant
    attention: AttentionItem | None = None
    breach: Breach | None = None
    weapon: WeaponDetection | None = None
    fight: FightIncident | None = None
    camera: CameraView | None = None
    health: SystemHealth | None = None


# ---------------------------------------------------------------------------
# users, settings, audit
# ---------------------------------------------------------------------------

class User(Wire):
    id: str
    name: str
    email: str
    role: Role
    last_active: Instant | None = None


class SchoolProfile(Wire):
    name: str
    hours_from: str
    hours_to: str
    term_from: str
    term_to: str
    late_cutoff: str
    timezone: str


class AlertRule(Wire):
    key: str
    title: str
    detail: str
    push: bool = False
    email: bool = False
    sms: bool = False


class DeliveryTarget(Wire):
    key: Literal["app", "email", "sms", "wa"]
    title: str
    enabled: bool
    destination: str
    editable: bool = True


class AuditEntry(Wire):
    id: str
    at: Instant
    actor: str
    action: str
    subject: str | None = None
    detail: str | None = None


class SiteInfo(Wire):
    """Everything the app chrome needs before any page loads.

    The school's name, what day it is *at the school*, and the live camera
    tally shown in the top bar. `today` is server-authoritative: a device with
    a wrong clock or in another timezone must not decide what "today" means for
    an attendance register.
    """

    name: str
    today: str  # ISO date, in the site's timezone
    timezone: str
    tz_offset_minutes: int
    cameras_online: int
    cameras_total: int
    places: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)


class Problem(Wire):
    """Error envelope for the cases that genuinely are errors.

    Degradation — a camera down, a model unloaded, a recorder refusing a
    password — is NOT this. Those are normal payload fields the UI renders.
    This is for malformed requests and real faults.
    """

    error: str
    detail: str | None = None
    retryable: bool = False


# ---------------------------------------------------------------------------
# enrolment
#
# The photo pixels never appear here in either direction. The browser holds its
# own thumbnails for display; the engine receives an image, embeds it, returns
# an assessment, and drops the pixels. The gallery stores vectors and never
# images — a vector cannot be turned back into a photograph, which is the
# property that limits what a leak of children's data actually exposes.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# live tracking
# ---------------------------------------------------------------------------

class TrackedIdentity(Wire):
    """One body the tracker is holding on to, right now."""

    stable_id: str
    camera_id: str
    camera_name: str
    at: Instant
    box: Box
    person_id: str | None = None
    name: str | None = None
    # FACE when a face match named this body, APPEARANCE when we are only
    # holding on to the clothing. Never merged.
    match: MatchKind = MatchKind.APPEARANCE


class LiveTracking(Wire):
    """Everything the tracker can currently see, across every tracked camera.

    One request rather than one per camera: the tracking page needs to know
    where an identity IS, and polling each camera separately would let the
    answers disagree with each other between frames.
    """

    running: bool = False
    # Why not, in the operator's words. Empty when it is running.
    reason: str | None = None
    cameras: list[str] = Field(default_factory=list)
    identities: list[TrackedIdentity] = Field(default_factory=list)


class StartEnrolmentRequest(Wire):
    name: str = Field(min_length=1, max_length=120)
    type: PersonType = PersonType.STUDENT
    group: str | None = None
    detail: str | None = None
    # Override the id derived from the name. Use it to add photos to someone
    # already enrolled rather than creating a near-duplicate record.
    person_id: str | None = None


class EnrolmentPhoto(Wire):
    """One assessed capture.

    Unusable photos are returned too, with `note` explaining why. A silently
    discarded upload reads as a broken button, and the operator cannot fix a
    problem nobody described to them.
    """

    id: str
    usable: bool
    # 0-100, from face size and detector confidence.
    score: float = Field(ge=0.0, le=100.0)
    face_pixels: int
    confidence: Confidence
    # Cosine similarity against this person's other staged photos. High is bad:
    # it means the same pose again, which adds nothing to recognition.
    similarity: float
    # Rough head turn. The sign distinguishes two angles; the magnitude says
    # how far from front-on.
    yaw: float
    note: str
    source: str = "upload"


class EnrolmentSessionView(Wire):
    """An enrolment in progress. Nothing here is in the gallery yet."""

    id: str
    name: str
    type: PersonType
    person_id: str
    group: str | None = None
    detail: str | None = None
    photos: list[EnrolmentPhoto] = Field(default_factory=list)
    usable_count: int = 0
    required_count: int = 3
    # Save is disabled until this is true. Committing a thin enrolment produces
    # unreliable recognition, which on a register looks like it is working.
    ready: bool = False
    # What to do next, in the operator's words.
    advice: str = ""
