"""Lost bag search — a job, not a worker.

**Why this is not a `FeatureWorker`.** Every other feature in this folder runs
a permanent thread per camera because it answers a question nobody asked: how
many people are here, is anyone holding a knife. A lost bag is the opposite — a
question asked once, by a person, about a bag that is already missing. A
`FeatureWorker` would cost one thread per camera for every minute of every day
so that somebody could use it twice a term, which is exactly what "on demand"
must not mean. So: one thread, started by the button, gone in a minute (D2).

**No person gate.** Knife detection only looks at frames with somebody in them,
which is what makes it affordable across 208 cameras. A bag search cannot do
that and must not: the bag worth finding is precisely the one with nobody near
it. The detector runs on the whole frame.

**Nothing is recorded.** No clip, no still, no row in any table. A search is a
question asked now and answered now, and when the next one starts this one is
gone. There is no history to leak because there is no history.

**What this can and cannot tell you.** A confirmed hit means the bag model
fired on the same camera in at least two frames. Measured on footage with no
bag in it (research D10), that is *not* enough to mean a bag: a black office
chair reads as `suitcase` at 0.88 for seconds at a time, and persistence cannot
tell a stationary wrong answer from a stationary right one — a lost bag is
stationary by definition. The size limits below throw out the two shapes that
are never a bag anybody can collect, and everything that survives is offered as
*a possible bag* for a person to look at. This file must never call it a
finding.

Cost while searching, at ~28 ms a pass (D8): ten cameras checked ~200 times
each in a minute; 208 cameras checked ~10 times each. Idle cost is zero — no
thread, no model call, nothing subscribed.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# The time limit. SC-002, and the budget in docs/PLAN.md §7. A search that ran
# until it was told to stop would still be running tomorrow.
LIMIT_SECONDS = 60.0

# A camera is a result only when a bag was seen in at least this many frames.
# One frame in 240 is what a false hit looked like on the no-bag clips (D1); a
# bag sitting on a bench is seen dozens of times in a minute.
CONFIRM_FRAMES = 2

# Do not spin when every chosen camera's frame is unchanged. One thread at full
# tilt asking `last_frame()` for nothing is a whole core spent on no looks.
ROUND_PAUSE_SECONDS = 0.1

# How long a box stays on the overlay after the frame that produced it. A box
# drawn over a live picture of where a bag *was* is a stale frame wearing a
# rectangle (D5).
OVERLAY_HOLD_SECONDS = 5.0

# Ignore a bag box under 1 % of the frame: a distant smudge, not a bag somebody
# can go and pick up.
MIN_BOX_FRACTION = 0.01

# ...and over 60 % of it. Measured (research D10): a motion-blurred frame comes
# back as one `suitcase` box covering 99.7 % of the picture, at up to 0.88
# confidence, and it recurs — so the two-frame rule does not catch it. No bag
# anybody can walk over and collect fills the frame.
MAX_BOX_FRACTION = 0.6

_STATES = ("running", "done", "stopped", "failed")


@dataclass(frozen=True)
class Hit:
    """One box, on one camera, in one frame. Not yet a result."""

    at: datetime
    x: float
    y: float
    w: float
    h: float
    label: str
    confidence: float
    #: which frame this came from. Two hits from one frame are two bags; two
    #: hits from two frames are the same bag seen twice, which is a different
    #: claim and must not be drawn twice.
    sequence: int = 0
    colour: str | None = None
    colours: frozenset[str] = frozenset()

    @property
    def area(self) -> float:
        return self.w * self.h


def matches_colour(hit: Hit, wanted: str) -> bool:
    """Does this hit answer to `wanted`?

    Matched against the **lenient** set, never the single best name: a dark
    blue bag looks black in poor light and has to answer to both.

    A hit whose colour could not be named at all matches **everything**. An
    unnamed colour means "we could not narrow this down", which is a different
    answer from "this is not the one". Treating it as a mismatch would hide the
    bag somebody is looking for because a crop came back one pixel wide.
    """
    return not hit.colours or wanted in hit.colours


@dataclass(frozen=True)
class Unavailable:
    """A camera that was asked for and could not be looked at, and why.

    Named rather than dropped: an operator who ticked a box is owed an answer
    about it, and "the camera is switched off" is an answer.
    """

    camera_id: str
    camera_name: str
    reason: str


@dataclass
class Job:
    """One search. Lives in memory, dies with the next one."""

    id: str
    query: object
    started_at: datetime
    ends_at: datetime
    cameras: list[str]
    state: str = "running"
    checked: set[str] = field(default_factory=set)
    unavailable: list[Unavailable] = field(default_factory=list)
    hits: dict[str, list[Hit]] = field(default_factory=dict)
    frames_checked: int = 0
    error: str | None = None

    def seconds_elapsed(self, now: datetime) -> float:
        return max(0.0, (now - self.started_at).total_seconds())

    def confirmed(self) -> list[str]:
        """Cameras that saw a bag often enough to be worth showing somebody.

        Sorted by the best confidence on each, so the most likely camera is
        first — which is the order the grid pins them in.
        """
        # Snapshot each list before measuring it: the search thread may be
        # appending to any of them while this runs, and a length that changes
        # between the filter and the sort would sort on a different set than it
        # filtered.
        seen = {c: list(hs) for c, hs in list(self.hits.items())}
        good = [c for c, hs in seen.items() if len(hs) >= CONFIRM_FRAMES]
        good.sort(key=lambda c: max(h.confidence for h in seen[c]), reverse=True)
        return good


class BagSearch:
    """The one search this engine has, if it has one at all.

    Holds at most one running job and the last finished one. A new `start()`
    replaces whatever is there, in any state — the spec says results must never
    mix, and a queue of searches for a missing bag is a queue nobody wants to
    wait in. `AlreadyBusy` is deliberately not raised here.
    """

    def __init__(self, registry, detector, clock, *,
                 limit_seconds: float = LIMIT_SECONDS, now=None) -> None:
        self.registry = registry
        self.detector = detector
        # The site clock. Held rather than used: the wire mapper in `api/live.py`
        # owns every rendered timestamp, and a job that formatted its own would
        # be a second place for the timezone to be wrong.
        self.clock = clock
        self.limit_seconds = limit_seconds
        # Wall clock, injectable. This feature is live-only, so frame time is
        # not the right clock for either the limit or the overlay hold — but a
        # test must not have to sleep for a minute to prove a minute.
        self._now = now or (lambda: datetime.now(timezone.utc))

        self._lock = threading.Lock()
        self._job: Job | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_inference_ms = 0
        self._colour_warned = False

    # -- the public surface -------------------------------------------------

    def start(self, query) -> Job:
        """Stop whatever is running and search for this instead.

        Returns immediately with a `running` job — or a `failed` one carrying a
        sentence, when there is nothing to search. An empty camera list is
        payload, not an error: there is nothing an error code helps somebody do
        except tick a box.
        """
        self.stop()

        now = self._now()
        job = Job(
            id=uuid.uuid4().hex,
            query=query,
            started_at=now,
            ends_at=now + timedelta(seconds=self.limit_seconds),
            cameras=list(getattr(query, "cameras", []) or []),
        )

        if not job.cameras:
            job.state = "failed"
            job.error = "No camera was chosen."
            with self._lock:
                self._job = job
            return job

        # Unknown and switched-off cameras are decided here, before the thread
        # starts: neither will ever produce a frame, so waiting to find out
        # would only delay telling the operator something already known.
        live: list[str] = []
        for camera_id in job.cameras:
            reason = self._why_not(camera_id)
            if reason is None:
                live.append(camera_id)
            else:
                job.unavailable.append(
                    Unavailable(camera_id, self._name_of(camera_id), reason))

        if not live:
            job.state = "failed"
            job.error = "None of the chosen cameras could be looked at."
            with self._lock:
                self._job = job
            return job

        # One list per camera, created up front. The console polls
        # `GET /lost-items/search` once a second while the search runs, and that
        # read walks `job.hits` on the HTTP thread while `_run` is writing to it
        # on the search thread. Adding a key mid-iteration is
        # `RuntimeError: dictionary changed size during iteration` - an
        # intermittent 500 on the one request the page depends on. Fixing the
        # key set at the start means only the lists ever change, and appending
        # to a list while another thread reads it is safe under the GIL.
        job.hits = {camera_id: [] for camera_id in live}

        self._stop = threading.Event()
        with self._lock:
            self._job = job
        thread = threading.Thread(
            target=self._run, args=(job, live), name="lost-bag-search", daemon=True)
        self._thread = thread
        thread.start()
        return job

    def current(self) -> Job | None:
        with self._lock:
            return self._job

    def stop(self) -> None:
        """End the running search, keeping its hits. Stopping nothing is fine."""
        thread = self._thread
        self._stop.set()
        if thread is not None and thread.is_alive():
            # Bounded: a search that would not end must not hold the caller,
            # and the thread is a daemon so a stuck one cannot outlive the
            # process either.
            thread.join(timeout=2.0)
            if thread.is_alive():
                log.warning("lost bag search did not stop within 2s")
        self._thread = None
        with self._lock:
            if self._job is not None and self._job.state == "running":
                self._job.state = "stopped"

    def join(self, timeout: float | None = None) -> None:
        """Wait for the search to end on its own. For tests and shutdown."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def boxes_on(self, camera_id: str) -> list[Hit]:
        """The latest look at one camera, for the overlay. Never a stale one.

        Only the hits from the **most recent frame** that saw something, not
        every hit inside the hold. A bag sitting still is seen once per pass,
        so five seconds of holding every one of them would stack a hundred and
        eighty near-identical rectangles on the same rucksack - which reads as
        a thick smear, not a box. Keyed on the frame `sequence`, not the time:
        two cameras can hand over frames stamped the same millisecond, and a
        stalled one repeats a timestamp for as long as it is stalled. The newest
        frame is also the truest - if the bag has been picked up since, its
        boxes are the ones that say so.
        """
        job = self.current()
        if job is None:
            return []
        cutoff = self._now() - timedelta(seconds=OVERLAY_HOLD_SECONDS)
        recent = [h for h in list(job.hits.get(camera_id, [])) if h.at >= cutoff]
        # The overlay answers the same question the search does. Somebody who
        # asked for a blue bag and gets an amber box round a black one has been
        # shown a detection they did not ask for, on the tile they are staring
        # at while they wait.
        wanted = getattr(job.query, "colour", None)
        if wanted:
            recent = [h for h in recent if matches_colour(h, wanted)]
        if not recent:
            return []
        newest = max(h.sequence for h in recent)
        return [h for h in recent if h.sequence == newest]

    @property
    def stats(self) -> dict:
        """The same keys `FeatureWorker.stats` uses, so System Health reads alike."""
        job = self.current()
        running = job is not None and job.state == "running"
        return {
            "cameras": len(job.cameras) if running and job else 0,
            "last_inference_ms": self._last_inference_ms,
            "state": job.state if job else "idle",
        }

    # -- the loop -----------------------------------------------------------

    def _run(self, job: Job, cameras: list[str]) -> None:
        """One thread, every chosen camera, until the limit or the button.

        Every time comes from `self._now()`. This is live, so it is wall clock:
        the knife worker's frame-time hold is right *there* because it also runs
        over recorded clips, and there is no such thing here.
        """
        seen: dict[str, int] = {}
        offline: set[str] = set()
        try:
            while not self._stop.is_set() and self._now() < job.ends_at:
                fresh = False
                for camera_id in cameras:
                    # Between cameras, not only between rounds: a search over
                    # two hundred cameras would otherwise take six seconds to
                    # notice it had been stopped.
                    if self._stop.is_set() or self._now() >= job.ends_at:
                        break

                    worker = self.registry.worker(camera_id)
                    if worker is None or worker.status != "ok":
                        if camera_id not in offline:
                            offline.add(camera_id)
                            job.unavailable.append(Unavailable(
                                camera_id, self._name_of(camera_id),
                                "The camera is offline."))
                        continue

                    frame = worker.last_frame()
                    if frame is None:
                        continue
                    # `last_frame()` returns the same frame until the camera
                    # delivers a new one. Counting it again would make "seen 40
                    # times" describe one look, forty times over.
                    if seen.get(camera_id) == frame.sequence:
                        continue
                    seen[camera_id] = frame.sequence
                    fresh = True

                    started = time.perf_counter()
                    boxes = self.detector.detect(frame.image)
                    self._last_inference_ms = int(
                        (time.perf_counter() - started) * 1000)

                    job.checked.add(camera_id)
                    job.frames_checked += 1
                    for box in boxes:
                        if not MIN_BOX_FRACTION <= box.w * box.h <= MAX_BOX_FRACTION:
                            continue
                        job.hits[camera_id].append(self._hit(box, frame))

                if not fresh:
                    time.sleep(ROUND_PAUSE_SECONDS)

            # A camera that was online throughout and still never handed over a
            # frame is a different failure from one that was switched off, and
            # the operator who ticked it is owed the distinction.
            for camera_id in cameras:
                if camera_id not in job.checked and camera_id not in offline:
                    job.unavailable.append(Unavailable(
                        camera_id, self._name_of(camera_id),
                        "The camera sent no frames."))

            if job.state == "running":
                job.state = "stopped" if self._stop.is_set() else "done"
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("lost bag search failed")
            job.state = "failed"
            job.error = f"The search stopped early ({exc})."

    def _hit(self, box, frame) -> Hit:
        colour, colours = self._colour_of(box, frame)
        return Hit(
            at=frame.captured_at,
            x=box.x, y=box.y, w=box.w, h=box.h,
            label=box.label,
            confidence=box.confidence,
            sequence=frame.sequence,
            colour=colour,
            colours=colours,
        )

    def _colour_of(self, box, frame) -> tuple[str | None, frozenset[str]]:
        """Name the bag's colour, or lose the colour rather than the hit.

        A degenerate crop - a box one pixel wide at the frame edge - must not
        cost somebody the camera their bag is on. Logged once so a systematic
        failure is visible, then the hit goes on without a colour, which the
        filter reads as "cannot be narrowed" rather than "does not match".
        """
        from vg.infer.colour import crop_for, name_colour

        try:
            guess = name_colour(crop_for(frame.image, box), frame.image)
            return guess.best, guess.lenient
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            if not self._colour_warned:
                self._colour_warned = True
                log.warning("could not name a bag's colour: %s", exc)
            return None, frozenset()

    # -- naming -------------------------------------------------------------

    def _why_not(self, camera_id: str) -> str | None:
        """Why this camera cannot be searched, or None if it can."""
        if camera_id in getattr(self.registry, "disabled", {}):
            return "The camera is switched off."
        if self.registry.worker(camera_id) is None:
            return "Not a camera on this engine."
        return None

    def _name_of(self, camera_id: str) -> str:
        for config in self.registry.configs():
            if config.id == camera_id:
                return config.name
        # An id on screen is bad; an id on screen with no explanation is worse.
        # A camera this engine has never heard of has no name to give.
        return camera_id
