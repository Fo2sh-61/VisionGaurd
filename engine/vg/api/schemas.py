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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class Note(Wire):
    """An explanation the console can say in any language.

    The engine says *what happened*; the console says it *in a language*. The
    code is the contract, the wording is not - changing an English sentence
    must never need an engine deploy, and every wording lives in
    `web/src/i18n/`.

    `code` must be declared in `notes.py`; `note()` refuses anything else and
    `engine/tests/test_notes.py` catches an unregistered one without having to
    execute the branch that emits it.

    `args` are **facts** - a camera name, a count, a number of minutes. Never a
    phrase: an English phrase smuggled through `args` is untranslatable, and if
    something needs saying it needs its own code.

    Nothing on the wire carries this yet. The fields that should are listed in
    `specs/008-arabic-console/data-model.md`; converting them is one
    coordinated change across both stores and both front ends, and it is
    deliberately not half-done.
    """

    code: str
    args: dict[str, str | int | float] = Field(default_factory=dict)


class Box(Wire):
    """A detection box in fractions of the frame, origin top-left."""

    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction
    label: str | None = None
    confidence: Confidence | None = None
    #: What this box IS, which decides how the console colours it.
    #:
    #: `"plate"` was missing here until 27 Aug and gate tiles had never once
    #: drawn a box because of it: `_plate_boxes` built one, this literal
    #: refused it, and the whole detections response raised — so a plate in
    #: view took the overlay down rather than appearing on it. The console
    #: half had been right all along (`boxColor()` has had its plate branch
    #: since the feature shipped). Widen this only with a test that ends at a
    #: validated `CameraView`; see `tests/test_vehicle_overlay.py` for why the
    #: near end of the path is not enough.
    kind: Literal["person", "weapon", "object", "face", "match", "plate"] = "person"
    match: MatchKind = MatchKind.NONE
    severity: Severity = Severity.INFO
    # The appearance identity following this body, e.g. "p7". Survives leaving
    # and re-entering a frame, and moving between cameras, which is the whole
    # point of tracking — so it has to reach the screen, not stop at the
    # database. None when the camera is not being tracked.
    track_id: str | None = None
    #: How wide this plate is, in pixels of the source frame. Plate boxes only.
    #:
    #: Display information rather than geometry, which is why it sits beside
    #: the fractions instead of replacing them. The console needs it to tell
    #: an operator whether a plate is big enough to read, and a fraction
    #: cannot answer that without the capture resolution — which the console
    #: does not have and should not have to learn.
    plate_width_px: int | None = None


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
    #: The named place this camera watches. What the live grid partitions by,
    #: and the same string the counting page groups on.
    area: str = ""
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
    #: Which recognition tier this camera is in. True means faces are the
    #: point here and it runs the recogniser at full rate; false is the patrol
    #: tier. Shown on Settings and System Health, not on the Track page.
    faces: bool = False


#: Every overlay a camera tile can ask for.
#:
#: **One list, in one place, and the endpoint's validation is built from it.**
#: The `feature` query parameter used to carry its own hand-written regex, and
#: `vehicles` was added to `LiveStore._boxes` without being added there - so
#: every plate-box poll was refused with a 422 before it reached the engine
#: and no gate camera ever drew a box. A feature whose overlay is rejected by
#: the front door looks exactly like a feature that found nothing.
#:
#: Adding a branch to `_boxes` means adding its name here. `test_api.py`
#: checks that, by reading `_boxes` itself.
OVERLAY_FEATURES = (
    "attendance", "track", "counting", "intrusion", "weapons", "lost",
    "vehicles", "falls",
)

OVERLAY_FEATURE_PATTERN = f"^({'|'.join(OVERLAY_FEATURES)})$"


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


class Recording(Wire):
    """A recording of one camera, running or finished.

    Started and stopped by a person. It records from the moment the button is
    pressed and no earlier: nothing is buffered, so the seconds before the
    press do not exist. The UI has to say that where it matters — a weapon
    detection that has already happened is not in the video.
    """

    id: str
    camera_id: str
    camera_name: str | None = None
    state: Literal["recording", "saved", "failed"]
    started_at: Instant
    stopped_at: Instant | None = None
    seconds: float = 0.0
    frames: int = 0
    #: Where it landed, for an operator to go and open. None while running,
    #: and None when it failed - a path to a file that was never written is
    #: exactly the fake save rule 4 forbids.
    file: str | None = None
    #: Why it stopped by itself, or why it failed. None after a plain stop.
    reason: str | None = None
    #: The safety limit, so the UI can say "stops itself after 10 minutes"
    #: rather than surprising somebody.
    max_seconds: float = 600.0


class RecordingResult(Wire):
    """What happened when the console asked to start or stop.

    A refusal travels as `ok: false` with a reason, not as an error status.
    "Recording is not available because no cameras are running" is something
    the operator needs to read next to the button they just pressed.
    """

    ok: bool
    recording: Recording | None = None
    reason: str | None = None


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
    # The three below are additive with defaults, so an older client keeps
    # parsing this payload unchanged.
    #
    # Peak, not last: the final frame of every scene has nobody in it, so the
    # last count would report 0 people for every entry that has ended.
    people: int = 1
    #: none | recording | saved | replaced | failed. Only `saved` has a file,
    #: and `clip` is populated only then.
    clip_state: str = "none"
    #: Why there is no playable clip, in the operator's words. The UI shows it
    #: beside a disabled control — a button that does nothing is worse than no
    #: button, and a missing reason is how it becomes one.
    clip_reason: str | None = None


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
    # None means the knife is still in view; the page says so rather than
    # printing a duration that is still growing as if it were final.
    ended_at: Instant | None = None
    seconds: float = 0.0
    clip_state: str = "none"
    # Why there is no video. Rendered next to the missing button, so it has
    # to be a sentence that explains itself with nothing around it.
    clip_reason: str | None = None
    end_reason: str | None = None


class WeaponReview(Wire):
    verdict: Literal[ReviewVerdict.CONFIRMED, ReviewVerdict.DISMISSED]
    # Optional because the live engine records the signed-in account and
    # ignores whatever the body claims — a caller cannot review as somebody
    # else. `MockStore` still reads it, so demo mode keeps working.
    actor: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# falls
# ---------------------------------------------------------------------------

class FallEntry(Wire):
    """One fall: somebody went down on a camera, and what happened next.

    `at` is when they went down. `alerted_at` is when they had been down long
    enough to count (`FallsStatus.down_seconds`); None means they got up
    before that and nothing was raised. `ended_at` None means they are still
    down. Nobody is named — this feature sees a body, not a person.

    Entries are never removed, "not a fall" included; there is no delete.
    """

    id: str
    at: Instant
    camera_id: str
    camera_name: str
    location: str
    detected_at: Instant
    alerted_at: Instant | None = None
    ended_at: Instant | None = None
    seconds: float = 0.0
    #: `got_up`, `left_view`, `switched_off` or `shutdown`. The console words
    #: them; None while the person is still down.
    end_reason: str | None = None
    confidence: Confidence
    #: `none` or `not_a_fall`. Once `not_a_fall`, never back.
    verdict: Literal["none", "not_a_fall"] = "none"
    reviewed_by: str | None = None
    reviewed_at: Instant | None = None
    #: Who pressed "I'm on my way", and when. Cleared by Undo.
    responder: str | None = None
    responded_at: Instant | None = None
    clip: Clip | None = None
    clip_state: str = "none"
    clip_reason: str | None = None
    model_version: str | None = None


class FallsStatus(Wire):
    """What the Falls page says about the feature itself."""

    #: Down this long without getting up and it counts. The page quotes it.
    down_seconds: float
    #: How many cameras are being checked for falls right now.
    cameras_checked: int = 0


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
    """One past day for one person. The row `AttendanceRecord` is for a group.

    Carries `minutes_late` for the same reason the group row does: "Late" on
    its own is a different conversation with a parent than "Late by four
    minutes".
    """

    date: str  # ISO date, "2026-07-29"
    status: AttendanceStatus
    seen_at: Instant | None = None
    location: str | None = None
    minutes_late: int | None = None


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
# a job that runs and finishes
# ---------------------------------------------------------------------------

class SearchJob(Wire):
    """POST returns one of these; the console polls until it leaves `running`.

    `stopped` is a finished search that was cut short by hand or replaced by
    a newer one. It keeps its hits — stopping does not throw them away.
    """

    id: str
    state: Literal["queued", "running", "done", "stopped", "failed"]
    progress: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    submitted_at: Instant
    clips_searched: int = 0
    clips_total: int = 0
    error: str | None = None


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


class NameSource(str, Enum):
    """Which cameras in this result were able to put a name on a body.

    A FACT, not a sentence - the console builds the wording, in whichever
    language it is showing. The engine only knows which cameras were running
    a recogniser.

    ALL       every enabled camera could name somebody: the identity tier at
              the doorways, and the patrol tier everywhere else.
    IDENTITY  only the `faces: true` / attendance cameras. Patrol is off, so
              a corridor sighting is a body without a name.

    This exists because switching patrol off makes a path quietly THINNER -
    the same person, fewer named stops - and a result that is quietly thinner
    is indistinguishable from a person who genuinely was not seen. Saying
    which is which is the difference between an honest answer and a wrong one.
    """

    ALL = "all"
    IDENTITY = "identity"


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
    #: Which cameras could name somebody while this path was built. IDENTITY
    #: means patrol was off and corridor stops carry no name - the console
    #: must say so rather than let a thinner answer read as a fuller one.
    names_from: NameSource = NameSource.ALL


# ---------------------------------------------------------------------------
# system health
# ---------------------------------------------------------------------------

class Recorder(Wire):
    id: str
    name: str
    cameras: int
    online: bool
    ip: str | None = None


class WorkerLoad(Wire):
    """What one feature worker is actually costing, right now.

    Every number here is a counter that was already being kept and never
    shown. `frames_processed` and `last_inference_ms` come off the worker,
    the queue figures and `frames_dropped` off its frame-bus subscription.

    There is deliberately **no per-worker processor share**. Feature workers
    are threads inside one process and the operating system attributes CPU to
    the process, not the thread - so a per-worker percentage would be a
    number this engine made up. The process figure sits on `SystemHealth`
    instead, and what identifies the expensive worker here is its inference
    time, its queue and its drops, which are all real.
    """

    #: The worker's own name - "recognition", "people", "weapons".
    name: str
    cameras: int
    frames_processed: int
    last_inference_ms: float
    queue_depth: int
    queue_max: int
    #: Frames the bus discarded because this worker was still busy. Non-zero
    #: with a full queue is what "behind" means.
    frames_dropped: int
    #: Behind, not merely busy. Omitted rather than guessed when a counter
    #: cannot be read - false would read as "keeping up", which is a claim.
    behind: bool | None = None


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
    #: False on every stage: no endpoint restarts anything. When it was true,
    #: System Health drew a Restart button that did nothing.
    restartable: bool = False
    model_version: str | None = None
    #: Only the workers stage fills this. Empty everywhere else.
    workers: list[WorkerLoad] = Field(default_factory=list)


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


class CapacityRow(Wire):
    """What one running worker asks of the machine, every second.

    Arithmetic, not an observation: `frames_per_second` x `ms_per_frame`.
    Both halves are honest on their own - the rate is the one the loop
    actually uses, and the cost is what the last frame took on this machine -
    but their product is a projection and the page says so.

    `measured` is the whole point of this row existing rather than a constant
    somewhere. True means `ms_per_frame` was timed here, by this worker, on
    this hardware. False means it is a figure carried in from an earlier run
    because this worker has not analysed a frame yet, and a reader deciding
    whether to add a camera needs to know which of the two they are reading.
    """

    #: The worker's own name - "people", "recognition", "weapons".
    name: str
    #: Which pool this is charged to: "gpu", "cpu", or absent when the worker
    #: could not say. An unplaced worker is listed and left out of both
    #: totals rather than guessed into one of them.
    pool: str | None = None
    #: The raw string the model reported - "cuda:0", "cpu". Kept beside the
    #: pool so the page can show what it was actually told.
    device: str | None = None
    cameras: int
    #: Frames a second this worker is asked for: the SUM of its cameras' own
    #: rates, so two cameras at 2/sec beside one at 5 is 9, not 3.
    #: Absent for a worker whose rate nothing fixes - see `on_demand`.
    frames_per_second: float | None = None
    ms_per_frame: float
    measured: bool
    #: `frames_per_second` x `ms_per_frame`. Absent whenever either half is.
    ms_per_second: float | None = None
    #: Runs only while somebody is looking at the tile. Its idle cost is zero
    #: and its watched cost is not fixed by any setting, so it contributes
    #: nothing to the totals and is shown as the exception it is.
    on_demand: bool = False
    #: The one person detection that counting, intrusion, track and knife
    #: detection all read. It runs once per frame however many of them want
    #: it, so it is costed ONCE, here, and every worker's own row has it
    #: subtracted. Before this row existed each of those workers reported
    #: the pass as its own time - including the time spent waiting for
    #: another worker to finish it - and the page added them up.
    shared: bool = False
    #: MEASURED. Milliseconds this worker really spent, per second, over the
    #: last `Capacity.window_seconds` - and the frames it got through. This
    #: is the reading; `ms_per_second` above is the projection it is checked
    #: against. Zero here is a true statement: it did nothing in the window.
    busy_ms_per_second: float = 0.0
    analysed_per_second: float = 0.0


class Capacity(Wire):
    """How full this machine is, as arithmetic over what is configured.

    Two budgets, never one number. The GPU supplies 1000 ms of work every
    second and the processor supplies `cores` x 1000, and face recognition -
    which is OpenCV and has no CUDA path - genuinely does not compete with
    the person detector for the same milliseconds. Adding them would produce
    a percentage of nothing.

    This is a **projection**: what the current configuration asks for, not a
    reading of what the machine is doing. The measured figure for that is
    `SystemHealth.gpu_percent` beside it, and `WorkerLoad.behind` is what
    says the engine has actually fallen behind. A projection is what lets
    somebody see the wall before they hit it; it is not evidence they have.
    """

    gpu_ms_per_second: float
    #: One second of GPU per second of wall clock.
    gpu_budget_ms: float = 1000.0
    cpu_ms_per_second: float
    #: `cores` x 1000. An 8-core box supplies 8000 ms of work every second.
    cpu_budget_ms: float
    cores: int
    #: Milliseconds a second belonging to workers that did not say which pool
    #: they run on. Carried separately so it is never silently added to
    #: either budget, and so the page can name it.
    unplaced_ms_per_second: float = 0.0
    #: True when every row's cost was timed on this machine. False means at
    #: least one is carried in, and the page says which.
    all_measured: bool = True
    #: MEASURED totals: what this engine's workers really spent, per second,
    #: over the last `window_seconds`, per pool. The bars on the page are
    #: drawn from the driver's own utilisation figures (`SystemHealth.
    #: gpu_percent`, `cpu_machine_percent`); these say how much of that is
    #: this engine. `*_ms_per_second` above remain the projection.
    gpu_busy_ms_per_second: float = 0.0
    cpu_busy_ms_per_second: float = 0.0
    unplaced_busy_ms_per_second: float = 0.0
    window_seconds: float = 5.0
    rows: list[CapacityRow] = Field(default_factory=list)


class SystemHealth(Wire):
    cameras_online: int
    #: Cameras that are switched ON. A camera an operator has disabled is
    #: not here and not offline: it is off, on purpose, and the page says so
    #: through `cameras_disabled` instead of counting it as a fault.
    cameras_total: int
    cameras_disabled: int = 0
    recorders_online: int
    recorders_total: int
    severity: Severity
    #: How busy the graphics card is right now, whole-device, from the
    #: driver (NVML). A measurement, not a projection - it is what the
    #: capacity card's GPU bar is checked against. None when there is no
    #: NVIDIA driver to ask; never 0, which would read as idle.
    gpu_percent: float | None = None
    #: Graphics memory in use / fitted, whole device, from the driver.
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    #: This process's share of one second of processor time (can exceed
    #: 100 on a multi-core machine - it is a sum over cores).
    cpu_percent: float | None = None
    #: The whole machine, 0-100, every program. What the CPU bar draws.
    cpu_machine_percent: float | None = None
    storage_percent: float | None = None
    uptime_seconds: float | None = None
    metrics: list[Metric] = Field(default_factory=list)
    #: What the configuration asks of this machine. Absent rather than empty
    #: when nothing is running: "no workers" and "workers costing nothing"
    #: are different answers and zero would read as the second.
    capacity: Capacity | None = None
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
    #: The source string with any password masked. **Never the raw one** —
    #: `CameraConfig.redacted_source()` is the only way this is built.
    ip: str
    channels: int
    status: SourceStatus
    area: str | None = None
    last_error: str | None = None
    #: What this camera is watched for, and the settings those features need.
    #: All of it used to be invisible to the console, so a camera could be
    #: listed without any way to see or change what it was actually doing.
    features: list[str] = Field(default_factory=list)
    faces: bool = False
    enabled: bool = True
    gate: int | None = None
    direction: str | None = None
    fps: float = 5.0
    rotate: int = 0
    #: Seeded by engine.yaml rather than added here. Derived, not stored: a
    #: camera is `from_config` when it has no row in the runtime roster. The
    #: console needs it to say what editing this camera means, because an edit
    #: writes a stored row that shadows the file from then on.
    from_config: bool = False


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
    #: The identity tier: people pass close enough here to be recognised. A
    #: camera can carry `attendance` without this — that combination is legal
    #: and is what the patrol tier is for.
    faces: bool = False
    #: Which gate this camera watches and which way it looks. `CameraConfig`
    #: refuses both half-states (a gate with no `vehicles`, `vehicles` with no
    #: gate) and refuses `direction: both` outright.
    gate: int | None = None
    direction: str | None = None
    #: Where somebody can walk to from here. Only ever a hint for the archive.
    neighbours: list[str] = Field(default_factory=list)


class FeatureNote(Wire):
    """One chosen feature, and whether it is actually running.

    Rule 8 says a subsystem that fails to start must say so in the UI. This
    carries that to the moment of *assignment*, which is when an operator can
    still do something about it: a camera set to check for knives on an engine
    whose knife model did not load is added, and told.
    """

    feature: str
    running: bool
    #: The subsystem's own startup error. Absent when it is running.
    reason: str | None = None


class AddCameraOutcome(Wire):
    """What happened to one camera in a bulk add.

    A refused camera is payload, never a status code: sixteen channels where
    the fourth has a duplicate id must still add the other fifteen and say so.
    """

    #: Position in the submitted list, so the console can line outcomes up
    #: with the rows the operator ticked.
    index: int
    ok: bool
    id: str | None = None
    #: Redacted, like every other source string that crosses this boundary.
    source: str = ""
    error: str | None = None


class BulkAddRequest(Wire):
    cameras: list[AddCameraRequest] = Field(min_length=1, max_length=500)


class EditCameraRequest(Wire):
    """Change one camera. Every field is optional; absent means leave alone.

    `None` is therefore ambiguous for the two nullable fields — `gate` and
    `direction` — so clearing a gate is done by sending `features` without
    `vehicles`, which `CameraConfig.parse` already refuses to half-apply.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = None
    area: str | None = None
    fps: float | None = Field(default=None, gt=0, le=60)
    rotate: int | None = None
    features: list[str] | None = None
    faces: bool | None = None
    gate: int | None = None
    direction: str | None = None
    neighbours: list[str] | None = None
    enabled: bool | None = None
    username: str | None = None
    password: str | None = None


class EditCameraResult(Wire):
    camera: CameraSource
    #: This camera came from engine.yaml and now has a stored row shadowing
    #: it. The console turns this into the sentence about what happens the
    #: next time the config file changes.
    shadows_config: bool = False
    #: The stream was reopened. False for a features-or-name edit — reopening
    #: an RTSP stream to add a tickbox is a visible stutter for nothing.
    restarted: bool = False
    feature_notes: list[FeatureNote] = Field(default_factory=list)


class FoundDevice(Wire):
    name: str
    ip: str
    channels: int
    type: SourceType = SourceType.IP_CAMERA
    duplicate: bool = False
    added: bool = False


class DvrConnectRequest(Wire):
    """Ask a recorder which of its channels actually have a camera on them.

    `template` exists because every recorder spells its stream URLs
    differently, and `archive.playback_url` in engine.yaml already solves the
    same problem the same way. A template rather than code means a new brand
    is a form field, not a release.
    """

    host: str
    port: int = 554
    username: str
    password: str
    type: SourceType = SourceType.DVR
    name: str | None = None
    area: str | None = None
    #: Must contain `{channel}`. `{host}` and `{port}` are also substituted.
    template: str = Field(min_length=1)
    #: The channel ids to try. Not a count: recorders number channels in
    #: their own ways, and inventing `1..16` is how the fixture lied.
    channels: list[str] = Field(min_length=1, max_length=64)
    #: Seconds for the WHOLE probe, not per channel. Sixteen channels at an
    #: 8s open timeout would be over two minutes serially, so the probe runs
    #: several at a time and stops when this runs out.
    budget: float = Field(default=20.0, gt=0, le=120)

    @field_validator("template")
    @classmethod
    def _must_address_a_channel(cls, value: str) -> str:
        """Without `{channel}` every channel would probe the same URL.

        Refused here rather than in the store so it comes back as a 422 with
        the reason, next to the field the operator typed it into.
        """
        if "{channel}" not in value:
            raise ValueError(
                "template must contain {channel} - it is what tells one "
                "channel from another")
        return value


class DvrChannel(Wire):
    """One channel, and what actually happened when it was opened.

    Every field below is measured. Nothing here may be produced by the engine
    itself — that is exactly what the fixture did, and it reported sixteen
    channels at 704x576 from recorders that were switched off.
    """

    channel: str
    name: str
    enabled: bool = True
    #: Real, read off the frame that arrived. `None` when none did.
    resolution: str | None = None
    #: The URL this channel would use, **redacted**.
    source: str = ""
    #: False means the budget ran out before this one was tried. A different
    #: answer from "we asked and nothing came back", and the console must
    #: render it differently.
    checked: bool = True
    status: SourceStatus = SourceStatus.DOWN
    latency_ms: float | None = None
    #: The probe's own reason, exactly as `test_connection` returns it.
    error: str | None = None


class DvrConnectResult(Wire):
    #: Did anything at all answer. False with a reason is the honest result
    #: for a recorder that is switched off, and it carries no channels.
    reachable: bool = False
    reason: str | None = None
    #: How many channels were actually tried, against how many were asked for.
    checked: int = 0
    channels: list[DvrChannel] = Field(default_factory=list)
    status: SourceStatus = SourceStatus.DOWN
    #: Nullable: connecting is a probe and creates nothing. Cameras appear
    #: only through `POST /sources/bulk`.
    source_id: str | None = None


class ScanResult(Wire):
    """Whether the network can be searched at all, and what was found.

    `available: false` with a reason is "we cannot look". `available: true`
    with no devices is "we looked and found nothing". Returning a bare list
    made those the same answer, and the console rendered the second sentence
    for the first situation.
    """

    available: bool = False
    reason: str | None = None
    devices: list[FoundDevice] = Field(default_factory=list)


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
    #: How many faces are on file. `photo_on_file` says whether the system can
    #: recognise this person at all; this says how well, and the console turns
    #: it into a sentence rather than a badge nobody could interpret.
    photos: int = 0
    #: When they were added to the directory.
    enrolled_at: Instant | None = None
    #: Their most recent sighting anywhere, and the camera's display NAME.
    #: Null means never sighted — the console says "Not seen yet" in words. A
    #: placeholder here would travel as data and be indistinguishable from a
    #: real answer once it left this boundary.
    last_seen: Instant | None = None
    last_camera: str | None = None


class GroupSummary(Wire):
    """How many are in a group, and how many of them are here.

    `here` is None when nothing is recording attendance. Zero would say the
    group is empty today, which is a different and much louder claim than
    "nobody was watching".
    """

    name: str
    people: int
    classes: int | None = None
    here: int | None = None


class GroupDetail(Wire):
    summary: GroupSummary
    roster: list[AttendanceRecord] = Field(default_factory=list)


class AttendanceTrend(Wire):
    """One day in a person's history chart.

    `present_ratio` is binary for one person on one day — they were here or
    they were not. `status` is what separates a late morning from an on-time
    one, which the ratio alone cannot say.
    """

    date: str
    label: str
    present_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    status: AttendanceStatus = AttendanceStatus.ON_TIME


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
    """One open item on Home's "Needs your attention".

    On the live engine (spec 013) `title` is the subject - a camera's name or
    a plate as displayed - `detail` is empty, and `note` says what happened as
    a code the console words, so the list reads in the operator's language.
    """

    id: str
    kind: Literal["weapon", "intrusion", "vehicles", "camera", "attendance", "system",
                  "fall"]
    at: Instant
    severity: Severity
    title: str
    detail: str
    target: str
    target_id: str | None = None
    acknowledged: bool = False
    clip: Clip | None = None
    note: Note | None = None


class LiveEvent(Wire):
    """One WebSocket frame.

    Home's "Needs your attention" list and the mobile push settings both assume
    these arrive unprompted rather than on a poll.
    """

    type: Literal[
        "weapon.detected",
        "weapon.reviewed",
        "intrusion.breach",
        "camera.status",
        "count.updated",
        "system.health",
    ]
    at: Instant
    attention: AttentionItem | None = None
    breach: Breach | None = None
    weapon: WeaponDetection | None = None
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
    #: A disabled account cannot sign in. Listed all the same, so an
    #: administrator can see it and turn it back on.
    disabled: bool = False
    #: When a sign-in lock lifts by itself (spec 020); None when not locked.
    #: An administrator can lift it sooner (`POST /users/{id}/unlock`).
    locked_until: Instant | None = None


class UserEdit(Wire):
    """`PATCH /users/{id}`: any subset. The email is not editable here."""

    name: str | None = None
    role: Role | None = None
    disabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("a name cannot be empty")
        return value.strip() if value is not None else None


class SchoolProfile(Wire):
    name: str
    hours_from: str
    hours_to: str
    term_from: str
    term_to: str
    late_cutoff: str
    timezone: str


# ---------------------------------------------------------------------------
# alert delivery (spec 013) — who is told, how, and what happened
#
# Facts and enums only; the console words every state (P11). The one place
# the engine writes sentences for people is the message itself, because there
# is no console at the far end of an email — and that never crosses this API.
# ---------------------------------------------------------------------------

AlertKind = Literal["weapon", "intrusion", "vehicles", "camera", "attendance"]
AlertChannel = Literal["email", "push"]
AlertLanguage = Literal["en", "ar"]
DeliveryOutcome = Literal["queued", "sent", "failed", "skipped"]
DeliveryReason = Literal[
    "no_recipients", "provider_missing", "recipient_off", "engine_down_at_noon",
    "attendance_unavailable", "queue_full", "engine_stopped", "provider_refused",
    "timeout", "unreachable",
    # Spec 020, phone notifications: the push service forgot the phone (it
    # was removed), or the phone's account is disabled.
    "device_gone", "account_disabled",
]


class AlertRule(Wire):
    """One kind of alert, and the channels it goes out on.

    `in_app` is None where Home has no item for the kind (the noon report),
    so no In-app switch is offered for it. The three `vehicle_*` switches exist
    only on the vehicles rule, and decide which gate alerts count at all - on
    every channel of the row, In-app included.
    """

    kind: AlertKind
    in_app: bool | None = None
    email: bool = False
    #: A notification on every registered phone that is switched on (spec 020).
    push: bool = False
    vehicle_blacklist: bool | None = None
    vehicle_unknown: bool | None = None
    vehicle_expired: bool | None = None


class AlertRuleUpdate(Wire):
    """A partial change. A flag left out is left as it is."""

    in_app: bool | None = None
    email: bool | None = None
    push: bool | None = None
    vehicle_blacklist: bool | None = None
    vehicle_unknown: bool | None = None
    vehicle_expired: bool | None = None


class PushKey(Wire):
    """`GET /push/key`: what a phone subscribes with, or why it cannot (spec 020)."""

    available: bool
    #: The site's VAPID public key (base64url): the browser's applicationServerKey.
    public_key: str | None = None
    reason: str | None = None


class PushSubscriptionKeys(Wire):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscription(Wire):
    """`POST /push/devices`: this phone's subscription, as the browser gave it."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys
    #: What the phone is called in the list, by its owner: "Pixel 8".
    label: str = Field(default="Phone", max_length=40)


class PushDevice(Wire):
    """One of my phones. `enabled` is the administrator's switch for it."""

    id: str
    label: str
    enabled: bool
    created_at: Instant
    last_sent_at: Instant | None = None
    last_error: str | None = None


class Recipient(Wire):
    """One person on one channel. They get every kind whose rule has it on."""

    id: str
    channel: AlertChannel
    destination: str
    name: str
    language: AlertLanguage
    enabled: bool
    created_at: Instant


class RecipientCreate(Wire):
    channel: AlertChannel
    destination: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=80)
    language: AlertLanguage = "en"
    enabled: bool = True


class RecipientUpdate(Wire):
    """The channel is fixed; a person moving to another channel is a new row."""

    destination: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    language: AlertLanguage | None = None
    enabled: bool | None = None


class ChannelStatus(Wire):
    """Whether a channel can send, and if not, which .env names are missing.

    Names, never values: a secret must not cross this API in any form.
    """

    channel: AlertChannel
    configured: bool
    missing: list[str] = Field(default_factory=list)


class Unreached(Wire):
    """A rule has this channel on and nobody enabled receives on it."""

    kind: AlertKind
    channel: AlertChannel


class ReportStatus(Wire):
    """Why the noon report will or will not go out."""

    time: str                       # "12:00", site time
    state: Literal["scheduled", "no_term_dates", "before_term", "after_term"]
    term_from: str = ""
    term_to: str = ""


class AlertSettings(Wire):
    """Everything the Alerts part of Settings shows, in one read."""

    #: running | off (switched off in engine.yaml) | failed (did not start)
    sending: Literal["running", "off", "failed"]
    sending_error: str | None = None
    rules: list[AlertRule]
    recipients: list[Recipient]
    channels: list[ChannelStatus]
    unreached: list[Unreached] = Field(default_factory=list)
    report: ReportStatus
    #: How long a camera must show no picture before it is a message.
    camera_offline_minutes: float = 5.0
    console_url_set: bool = False
    #: False until a native speaker has read the Arabic wording; until then an
    #: Arabic recipient receives English.
    arabic_reviewed: bool = False


class DeliveryRow(Wire):
    """One attempt. `sent` means the courier accepted it - never "delivered"."""

    id: str
    at: Instant
    kind: Literal["weapon", "intrusion", "vehicles", "camera", "attendance", "test"]
    channel: AlertChannel | None = None
    recipient_name: str | None = None
    outcome: DeliveryOutcome
    reason: DeliveryReason | None = None
    #: The courier's own words, with every secret value removed.
    provider_reason: str | None = None
    provider_id: str | None = None
    attempts: int = 0


class DeliveryLog(Wire):
    """The log, or why it cannot be read. Never a 5xx (AGENTS rule 7)."""

    available: bool
    reason: str | None = None
    rows: list[DeliveryRow] = Field(default_factory=list)


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
    # How long recorded clips are kept, from `storage.clip_retention_days`.
    # Site policy, so it belongs with the rest of the chrome: a page that
    # tells an operator "videos are kept for 30 days" must be reading the
    # number the engine actually deletes by, not one typed into the markup.
    clip_retention_days: int = 30


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


# ---------------------------------------------------------------------------
# the path behind somebody — anchors
# ---------------------------------------------------------------------------

class PathAnchor(Wire):
    """A stop on a path, with the evidence that earned it.

    The evidence travels because the operator is entitled to ask "why do you
    believe this?" and get an answer in their own terms — "6 matches over 4
    seconds, best 0.71" — rather than being asked to trust a coloured dot.

    Deliberately no box geometry. An anchor is a place on a path, not
    something to draw over a frame.
    """

    camera_id: str
    camera_name: str
    place: str
    at: Instant
    until: Instant
    #: separate looks, not frames.
    matches: int
    score: Confidence
    face_px: int


class PathSkeleton(Wire):
    """Where somebody was, from the anchor table alone.

    Two layers, never merged, because they are answers to different questions:

      anchors     a face was recognised, well enough and often enough to
                  claim it. Evidence about IDENTITY.
      appearance  the same body was seen again. Evidence about CONTINUITY
                  only — clothing cannot tell you which person somebody is,
                  so nothing here is ever named.

    An empty `anchors` list is an answer, not a failure: it means nobody was
    identified in that window, which is different from the system being
    unable to look.
    """

    subject: PersonRef
    date: str
    # Written BEFORE this result is returned. If the write fails the search
    # fails — the promise that every search is recorded is only worth
    # anything if it is ordered this way.
    audit_id: str
    anchors: list[PathAnchor] = Field(default_factory=list)
    appearance: list[TrackStop] = Field(default_factory=list)
    #: Which cameras appear, for the tiles the page draws beside the path.
    cameras: list[CameraView] = Field(default_factory=list)
    #: Which cameras could name somebody while this path was built.
    #:
    #: IDENTITY means the patrol tier is off, so only the doorway cameras ran
    #: a recogniser and a corridor sighting is a body with no name. The page
    #: must say so: an anchor list that is short because nobody was looking
    #: reads exactly like one that is short because nobody was there.
    names_from: NameSource = NameSource.ALL

# ---------------------------------------------------------------------------
# the video behind a stop
# ---------------------------------------------------------------------------

class ChunkPoint(Wire):
    """A point inside a chunk that has already been built. Fractions, as ever."""

    job_id: str
    chunk: int
    x: Fraction
    y: Fraction


class LegRequest(Wire):
    """Fetch and process the recorded video for one stop.

    `start`/`end` rather than the `from`/`to` the operator types: `from` is a
    Python keyword, and `TrackQuery` already settled on these names.
    """

    camera_id: str
    start: datetime
    end: datetime
    #: Whose leg this is, when it came from an anchor. None for the footage
    #: browsing and stranger flows, where nobody has been identified.
    person_id: str | None = None
    #: A body clicked inside an existing chunk, for following a stranger. The
    #: result is APPEARANCE evidence and never carries a name.
    descriptor_of: ChunkPoint | None = None


class LegJob(Wire):
    """A leg being built, and the pieces of it that are ready.

    `chunk_urls` grows while the job runs. The page plays the first the moment
    it lands rather than waiting for the last, which is the difference between
    a ten-second wait and a two-minute one.
    """

    job: SearchJob
    camera_id: str
    camera_name: str
    place: str
    start: Instant
    seconds: float
    chunks_ready: int = 0
    chunks_total: int = 0
    #: Pieces of the stop the archive holds no video for. A stop starts when
    #: somebody was recognised and a recording starts when somebody pressed a
    #: button, so a gap at the front is ordinary rather than exceptional.
    chunks_missing: int = 0
    #: The archive's own words about the gap, naming what it does hold.
    gap_reason: str | None = None
    #: Same-origin, because `<video>` cannot send an Authorization header —
    #: exactly like breach clips and camera streams.
    chunk_urls: list[str] = Field(default_factory=list)
    #: The camera being warmed up for the next stop, if one is.
    next_prefetched: str | None = None
    #: How long this is expected to take, from what was measured on this
    #: machine. None when nobody has measured it — never a guess.
    estimate_seconds: float | None = None

class SweepRequest(Wire):
    """Look for somebody across several cameras and a stretch of time."""

    #: Empty for a stranger search, where nobody has a name to look for.
    person: str = ""
    start: datetime
    end: datetime
    #: Explicit cameras, or every camera in these areas. One or the other.
    camera_ids: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)


class StrangerRequest(Wire):
    """Follow the body somebody clicked in a chunk, onto other cameras.

    There is no `person` here and there cannot be one. Whatever this finds is
    evidence that the same body moved, never evidence about who it is.
    """

    point: ChunkPoint
    sweep: SweepRequest


class SweepEstimate(Wire):
    """The arithmetic, shown before anything runs.

    `allowed: false` always carries its reason in words, and the reason is
    either "that is more work than the budget" with the sum, or "nobody has
    measured this machine yet". Never a shrug, and never a number that was
    typed rather than measured.
    """

    seconds: float
    camera_hours: float
    cameras: int
    allowed: bool
    reason: str | None = None
    measured_at: Instant | None = None


class SweepHit(Wire):
    """Somebody found in recorded video, with the evidence that found them."""

    camera_id: str
    camera_name: str
    place: str
    at: Instant
    until: Instant
    matches: int
    score: Confidence
    face_px: int
    #: FACE when a face cleared the bar, APPEARANCE when only a body matched.
    #: Never merged: one says who, the other only says the same body.
    match: MatchKind = MatchKind.FACE


class SweepJob(Wire):
    job: SearchJob
    cameras: list[str] = Field(default_factory=list)
    hits: list[SweepHit] = Field(default_factory=list)
    segments_done: int = 0
    segments_total: int = 0
    #: How many of those pieces had no recorded video behind them. A sweep
    #: that examined nothing must never be read as having found nobody, so
    #: this travels and the page says it out loud.
    segments_missing: int = 0
    estimate_seconds: float | None = None

# ---------------------------------------------------------------------------
# following one person, live
# ---------------------------------------------------------------------------

class FollowRequest(Wire):
    """Where the operator clicked, in fractions of the frame.

    Fractions and never pixels: the console does not know the camera's
    resolution and must not have to guess it.
    """

    camera_id: str
    x: Fraction
    y: Fraction


class FollowRecordRequest(Wire):
    #: None means "until somebody presses stop". A number means the engine
    #: stops it itself, so a closed tab cannot leave a camera recording.
    timer_seconds: float | None = Field(default=None, ge=1.0, le=3600.0)


class TrailHop(Wire):
    """A camera the followed person crossed, and when."""

    camera_id: str
    camera_name: str
    place: str
    at: Instant


class FollowRecording(Wire):
    """The recording riding along with a follow.

    One segment per camera. Segments carry their own stop reason, because
    "the timer ran out" and "we lost them" are different things to an operator
    holding the file afterwards.
    """

    state: Literal["recording", "stopped"]
    reason: str | None = None
    #: Counts down while a timer is set. None when there is no timer, or once
    #: it has stopped.
    timer_seconds_left: float | None = None
    segments: list[Recording] = Field(default_factory=list)


class FollowView(Wire):
    """The followed body as it stands right now.

    `name` is present only after a face has been recognised well enough,
    several times, to claim it — and it is gone the moment the track is. It is
    an annotation on this body in these frames, never a binding that outlives
    them.
    """

    stable_id: str
    camera_id: str
    camera_name: str
    place: str
    since: Instant
    person_id: str | None = None
    name: str | None = None
    #: FACE once a name has been earned, APPEARANCE while the system is only
    #: holding on to the clothing. Never merged — the difference is the whole
    #: basis on which an operator decides how much to believe this.
    match: MatchKind = MatchKind.APPEARANCE
    trail: list[TrailHop] = Field(default_factory=list)
    recording: FollowRecording | None = None
    #: manual | timer | track lost. Set once, and the follow is over.
    ended_reason: str | None = None

    @property
    def ended(self) -> bool:
        return self.ended_reason is not None


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


class PreviewFace(Wire):
    """One face in the enrolment camera's latest frame.

    Geometry only. There is deliberately no name, no person id and no match
    here: an enrolment preview must never claim to know who it is looking at,
    so there is nowhere for an identity to travel even if something sent one.
    """

    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction
    #: Right eye, left eye, nose, mouth corners — the order YuNet emits.
    points: list[Point] = Field(default_factory=list)
    confidence: Confidence = 0.0


class EnrolmentPreview(Wire):
    """What the enrolment page draws over the live view.

    `faces: []` with `offline: false` means the engine looked and nobody was
    there. `offline: true` means it could not look, and the page shows NO
    SIGNAL rather than an empty overlay pretending to have checked — those are
    different claims and only one of them is about the room.
    """

    camera_id: str
    #: When the analysed frame was captured. Null when there is no frame: the
    #: overlay is only ever as current as the picture it came from.
    at: Instant | None = None
    offline: bool = False
    faces: list[PreviewFace] = Field(default_factory=list)


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

# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

class LanguageRequest(Wire):
    """Change your own language.

    No `user_id`. A caller changes their own preference and nobody else's,
    which keeps this endpoint off the permission surface entirely; an
    administrator who wants to change a colleague's language asks them.
    `Wire` forbids extras, so a smuggled id is a 422 rather than a quiet
    write to somebody else's row.
    """

    language: Literal["en", "ar"]


class LoginRequest(Wire):
    """What the sign-in form sends.

    The password is here and nowhere else: never logged, never echoed, never
    stored. It exists between this model and argon2 and then it is gone.
    """

    email: str
    password: str


class Account(Wire):
    """The signed-in user, as the server sees them.

    No password hash, and no permissions list. The console asks the server
    what it may do rather than deciding from a role it holds locally.
    """

    id: str
    name: str
    email: str
    role: str
    initials: str
    #: Which language this person reads the console in. A preference, not a
    #: permission - `auth/deps.py` decides access by path and never reads this.
    language: Literal["en", "ar"] = "en"


class LoginResult(Wire):
    token: str
    expires_at: Instant
    user: Account


class Connection(Wire):
    """`GET /connection`: how this caller is reaching the site (spec 020).

    `remote` is decided by the engine from the real address: only the factory
    network is local. The limits are the site's configuration, sent so the
    screens can say what they show ("every 2 s", "reduced for remote") rather
    than guess. The engine applies them whatever a screen does.
    """

    remote: bool
    tile_interval_seconds: float
    live_width: int
    live_fps: float
    live_views: int
    #: This account's remote live views open right now.
    live_views_open: int


class RegisterRequest(Wire):
    """What the sign-up form sends.

    There is no `role` field, and `extra="forbid"` means adding one is a 422
    rather than a promotion. The role is decided by the server
    (`SELF_SIGNUP_ROLE`), because the alternative is a public form that hands
    out administrator of a system holding face data for children.
    """

    name: str
    email: str
    password: str


# ---------------------------------------------------------------------------
# vehicle gate
# ---------------------------------------------------------------------------

class VehiclePass(Wire):
    """One car through one gate, once.

    `owner` is None when the plate is not on the register, and the console
    shows "Not in the register" rather than an empty cell — a blank reads as
    missing data, which this is not.
    """

    id: str
    at: Instant
    plate: str                      # canonical, for matching
    plate_display: str              # as it appears on the car, RTL Arabic
    gate: int
    gate_name: str
    direction: str                  # entry | exit
    status: str                     # known | unknown | blacklist | expired
    confidence: Confidence
    votes: int                      # how many frames agreed
    needs_review: bool
    owner: str | None = None
    unit: str | None = None
    has_snapshot: bool = False
    #: Who typed this plate in by hand, if anybody. None is the reader's own
    #: answer. Shown on the row so a corrected reading is visibly a person's
    #: judgement rather than the model's, and so nobody re-corrects it.
    corrected_by: str | None = None


class RegisteredVehicle(Wire):
    """A car the school knows about."""

    id: str
    plate: str
    plate_display: str
    category: str                   # staff | visitor | vip | blacklist
    owner: str | None = None
    phone: str | None = None
    unit: str | None = None
    car_make: str | None = None
    car_colour: str | None = None
    valid_until: str | None = None  # ISO date; None = no expiry
    notes: str | None = None
    #: Computed at read time, never stored. A stored flag needs a nightly job
    #: to stay true and is wrong between midnight and whenever it runs.
    expired: bool = False
    last_seen: Instant | None = None


class PlateCorrection(Wire):
    """A plate somebody typed in after looking at the photograph."""

    plate: str


class PlateAlphabet(Wire):
    """What a plate may contain, and what the reader mixes up.

    Served rather than mirrored in TypeScript because the confusion table is
    **measured** — it lists the pairs the character model actually returns for
    one another, and it will change when the model does. A copy in the console
    would drift, and the drift would show up as a correction picker that fails
    to offer the one character the reader was likely to have got wrong.
    """

    #: Every letter the reader may output.
    letters: list[str] = Field(default_factory=list)
    #: The narrower set public sources agree is actually issued. Offered
    #: first in a picker; the rest stay reachable.
    common_letters: list[str] = Field(default_factory=list)
    digits: list[str] = Field(default_factory=list)
    #: character -> the characters it is genuinely confused with, commonest
    #: first. One tap fixes the overwhelmingly likely mistake.
    confusions: dict[str, list[str]] = Field(default_factory=dict)


class VehicleRegistration(Wire):
    """The write body. Only the plate is required; a gate log is filled in
    over weeks, and refusing a row for a missing phone number is how a
    register ends up half-entered on paper."""

    plate: str
    category: str = "visitor"
    owner: str | None = None
    phone: str | None = None
    unit: str | None = None
    car_make: str | None = None
    car_colour: str | None = None
    valid_until: str | None = None
    notes: str | None = None


class GateTotals(Wire):
    """One gate's day.

    `pairing_available` is false where no exit camera is configured, and
    `inside` is then **absent** rather than zero — with nothing to pair
    against, "0 inside" would be a number the engine cannot stand behind.
    """

    gate: int
    name: str
    entered: int
    left: int
    inside: int | None = None
    pairing_available: bool = False


class VehicleVisit(Wire):
    """An entry and the exit it was paired with, if there was one.

    `inferred` marks a visit closed because the car was seen entering again
    rather than because an exit was observed. Reported, never presented as
    observed.
    """

    plate: str
    plate_display: str
    entered: Instant
    entry_gate: int
    left_at: Instant | None = None
    exit_gate: int | None = None
    minutes: float | None = None
    owner: str | None = None
    unit: str | None = None
    category: str | None = None
    inferred: bool = False
    #: The passes this visit was derived from, so a row can show the
    #: photograph that proves it. The console links these straight at
    #: `/vehicles/passes/{id}/snapshot` rather than the images being copied
    #: anywhere - one store of pass images, one retention rule.
    #:
    #: The `has_snapshot` flags are separate from the ids because an image is
    #: deleted at thirty days while its pass row is kept for ever. False means
    #: "no picture to show", never "no such pass".
    entry_pass_id: str | None = None
    exit_pass_id: str | None = None
    entry_has_snapshot: bool = False
    exit_has_snapshot: bool = False


class VehicleImportResult(Wire):
    """What an import actually did. Every refusal is named.

    A silent partial import is the worst outcome: the office believes the list
    is loaded and finds out at the gate.
    """

    added: int
    updated: int
    skipped_duplicates: int
    problems: list[str] = []


class VehicleImportRun(Wire):
    """The most recent register import, for the "last import" line.

    The design draws "Last import: 2,140 rows · 6 skipped · 12 Aug". That is
    either a fact or the line is absent - so this endpoint returns 404 on a
    database nobody has ever imported into, and the console shows nothing
    rather than a row of zeros. "0 rows imported" reads as a failed import
    rather than as an import that never happened.
    """

    at: Instant
    added: int
    updated: int
    skipped: int
    rejected: int
    by_who: str = ""


class GateSummary(Wire):
    """The six Live tiles.

    **Every count is optional, and that is the point.** A tile with no number
    renders its reason instead — "no gate camera is configured", "plates are
    not being read". Zero is a measurement; absent is an admission. Sending 0
    for "we do not know" is exactly the untruth SC-010 exists to prevent.
    """

    entered: int | None = None
    left: int | None = None
    inside: int | None = None
    unknown: int | None = None
    blacklist: int | None = None
    needs_review: int | None = None
    gates: int = 0
    registered: int | None = None
    #: Why any of the above are absent. None when everything is measured.
    reason: str | None = None
    #: False where no exit camera exists, so `inside` cannot be computed.
    pairing_available: bool = False
    #: How many gate cameras are actually being read, of those configured.
    #:
    #: The tile this feeds replaced "Needs review", which retired with the
    #: pass list. `needs_review` above stays on the wire because the export
    #: still reports it - a weak read is still flagged, it just no longer has
    #: a tile. All three of these are absent, not zero, when plate reading is
    #: not running at all: `reason` already carries that case, and "0 of 0"
    #: would read as a measurement of a system that is not looking.
    cameras_reading: int | None = None
    cameras_total: int | None = None
    #: Which camera is not being read and why. None when all of them are.
    cameras_note: str | None = None


class ReaderAttempt(Wire):
    """One go at reading a plate, including the ones that came to nothing.

    **This is the diagnostic surface, so a failure has to be as visible as a
    success.** `display` empty means the reader found a plate and read no
    characters from it; the console renders that as words, never as a blank
    cell, because a blank reads as "we failed to load this row".

    `confidence` and `plausibility` are absent rather than zero on a read that
    produced nothing - there is no reading to be confident about.

    Not stored anywhere. This is a live window onto a worker that is running
    because somebody is watching it.
    """

    at: Instant
    camera_id: str
    camera_name: str
    #: The plate as it would appear on the car. Empty = read nothing.
    display: str = ""
    confidence: Confidence | None = None
    plausibility: Confidence | None = None
    #: How wide the plate was, in pixels of the source frame. The aiming aid.
    width_px: int = 0
    #: What this car's vote is currently leaning towards, and how far along.
    leader_display: str | None = None
    votes: int = 0
    votes_needed: int = 0


class GateReaderCamera(Wire):
    """Which models are actually reading at one gate camera, and how fast.

    **The names are what is loaded, never what was configured.** A model that
    fell back from its accelerated build to the supplied weights says so here,
    on the page where its work shows, rather than only on System Health.

    `read_ms` is None until the first read - a camera nobody has driven past
    has no timing, and 0 ms would claim one.
    """

    camera_id: str
    camera_name: str
    gate: int
    direction: str                  # entry | exit
    finder: str                     # the plate detector actually loaded
    reader: str                     # the character model actually loaded
    form: str                       # TensorRT | PyTorch CUDA
    read_ms: float | None = None
    #: The car in front of this camera right now, if there is one.
    #:
    #: `reading_display` is the settled answer the votes have converged on —
    #: **not** the last frame's raw read, which wobbles by a character and
    #: was only ever a diagnostic. `has_crop` says a photograph of that plate
    #: can be fetched; the console shows the picture beside the answer, so a
    #: person judges the two together rather than taking either on faith.
    reading_display: str | None = None
    #: The same reading in canonical form — letters, space, ASCII digits.
    #: The display form is spaced and carries Indic digits, which is right for
    #: reading off a screen and wrong for feeding an editor; parsing it back
    #: in the console would be a second implementation of `normalize`.
    reading_plate: str | None = None
    reading_votes: int = 0
    has_crop: bool = False
    #: The row this car was filed as, once it has been. None while the votes
    #: are still gathering. Carrying it is what lets somebody correct the
    #: reading from here — the same row the pass list would correct, never a
    #: second one.
    reading_pass_id: str | None = None


class GateReaderNow(Wire):
    """Everything the "what the reader is seeing now" card needs, in one poll.

    `reason` set means plate reading is not running, and the card renders that
    sentence instead of an empty table - the same wording the tiles use, from
    the same place, so the page never gives two accounts of one situation.
    """

    cameras: list[GateReaderCamera] = Field(default_factory=list)
    attempts: list[ReaderAttempt] = Field(default_factory=list)
    votes_needed: int = 0
    reason: str | None = None


class GateAlert(Wire):
    """A pass that is waiting for a person to deal with it.

    **Derived from the pass, never stored.** An alert exists while a
    qualifying pass of today has no dismissal against it; there is no alert
    lifecycle to drift out of step with the log.

    **The engine sends facts and the console writes the sentences** (rule:
    `format.ts` owns every rendered string). So there is no `message` field
    here - there are the things a message would need to be true.

    `near_match_*` is filled only when exactly one registered plate is within
    one edit of an unread-as-registered plate. Zero candidates or several and
    it stays empty, because a guess between two cars puts a wrong name against
    a stranger. The console must phrase it as a question; this is never a
    claim that the two are the same car, and nothing is merged or rewritten.
    """

    pass_id: str
    kind: str                       # unknown | blacklist | expired
    at: Instant
    plate: str                      # canonical, for matching
    plate_display: str              # as it appears on the car
    gate_name: str
    owner: str | None = None
    #: For `expired`: the ISO date the permit ran out.
    permit_expired_on: str | None = None
    near_match_display: str | None = None
    near_match_owner: str | None = None
    #: True only where pairing is available and the car has no exit yet, so
    #: "and is still inside" can be said without guessing.
    inside: bool = False
    dismissable: bool = True


class TrafficHour(Wire):
    """One hour of one day at the gates. In above the line, out below it."""

    hour: int                       # 0..23, site local
    entered: int
    left: int


# ---------------------------------------------------------------------------
# Ask — the natural-language query console (P12)
# ---------------------------------------------------------------------------

class AskOutcome(str, Enum):
    """Four outcomes, four different screens.

    They must never collapse into "no results". "I cannot answer that",
    "which one did you mean?", "the counting subsystem is off" and "here is
    the answer, and it is empty" are four different things to tell a guard,
    and the console already keeps empty/zero/unknown apart everywhere else.
    """

    ANSWERED = "answered"
    UNSUPPORTED = "unsupported"
    NEEDS_DETAIL = "needs_detail"
    UNAVAILABLE = "unavailable"


class AskUnderstanding(Wire):
    """What Ask decided the question was — shown to the operator, always.

    This is the anti-fabrication device. Ask answers straight away rather than
    asking for confirmation first, so a confidently wrong route would otherwise
    produce a true answer to a question nobody asked. The operator's only
    defence is being able to see what was actually run on their behalf, which
    is why the console may never hide or abbreviate this line.
    """

    #: A menu id from `vg/ask/menu.py`. Never free text, never a sentence.
    query: str
    #: Resolved to real values — placeholders already put back, locally.
    params: dict[str, str] = {}
    #: Parameters Ask filled in itself rather than reading from the question,
    #: e.g. `date` when the question said "today" or said nothing at all. A
    #: wrong assumption has to be visible; a silent one is how a figure for
    #: the wrong day gets believed.
    assumed: list[str] = []


class AskRow(Wire):
    """One piece of evidence from the query's own result.

    `label` is a **value** the query returned — a name, a plate, a zone, a
    camera. Never a sentence: sentences are built by the console (P11).
    """

    label: str
    at: Instant | None = None
    camera: str | None = None
    confidence: Confidence | None = None
    clip_url: str | None = None
    #: Per-row honesty, forwarded from the query: demo data, an estimated
    #: exit, a weak plate read. A row that is less certain than its
    #: neighbours must say so on the row, not in a footnote.
    note: Note | None = None


class AskAnswer(Wire):
    """The answer to one question.

    **There is no free-text field on this type, and that is the point.** Every
    sentence the operator reads is built by the console from `note` and
    `understood.query`. The model that read the question has nowhere to write,
    so it cannot contribute a fact even by mistake — P12-FR-003 enforced by
    the shape of the data rather than by review.
    """

    outcome: AskOutcome
    understood: AskUnderstanding | None = None
    #: The same figures the matching page shows.
    headline: list[Metric] = []
    rows: list[AskRow] = []
    #: The honest state, when there is one to explain.
    note: Note | None = None
    #: Where to go for the fuller view. Always *additional* — never the answer
    #: itself. A response with a deep link and no data has not answered.
    deep_link: str | None = None
    #: The exact text that left the site, byte for byte. Always present, even
    #: when nothing left (then it is empty) and even when the question failed.
    #: With unrecognised words sent as typed, this record is the only way to
    #: know what actually went.
    sent_off_site: str = ""
    #: The audit receipt. Proof the entry was written before this was built.
    audit_id: str = ""


class AskRequest(Wire):
    """One question, as typed.

    No language field. The parser reads mixed script, and asking the console to
    guess a language in order to help it is a way to be wrong about a sentence
    that is half Arabic and half English — which is most of them here.
    """

    question: str = Field(min_length=1, max_length=500)
