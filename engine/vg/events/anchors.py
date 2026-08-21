"""Anchors — the stops on a person's path, and the bar for claiming one.

An anchor is the system saying, on the record: *this person was at this
camera, between these two times, and here is why I believe it.* It is the unit
the Track page draws a path out of, and it is the same verdict that decides
whether a live body may wear a name.

One bar for one claim. Naming a body on screen and marking a stop on a path
are the same assertion about the same evidence, so they cost the same. Two
separate thresholds for one claim drift apart, and the day they do, the page
and the path disagree about who somebody is.

**Why the decision is made here and not from stored sightings.** The sighting
table is debounced: after the first row, repeats are thinned to roughly one a
minute. So "five clear looks in three seconds" — the very thing that makes an
identification trustworthy — is *invisible* once it is written down. The
evidence exists only in the worker's frame stream as it goes past, which is
why the accumulator sits in the worker and not in a query.

**What counts as a look.** Not a frame. Five frames inside a third of a second
are one look at one moment; treating them as five would let a single lucky
burst buy a name, which is exactly the failure this gate exists to stop. So
frames arriving within `gap_seconds` of the last look fold into it — they can
improve the score and lower the reported face size, but they do not count
again.

`AnchorAccumulator` is pure logic and holds no database handle, so it can be
tested one look at a time. `AnchorStore` is the storage beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from vg.config import AnchorGates

#: How long a run may go quiet before the next look starts a new stop rather
#: than continuing the old one. Not a gate — nothing is refused by it — it
#: only decides where one stop on a path ends and the next begins. Generous
#: enough that the patrol tier's slow sampling never splits a run by accident.
RUN_GAP_SECONDS = 30.0


@dataclass(frozen=True)
class FaceMatch:
    """One frame's worth of evidence about one person, on one camera.

    `runner_up` travels with it because a confident score means nothing on its
    own: if the second-best candidate is right behind the best, the two are
    not separable and naming either one is a guess.
    """

    person_id: str
    score: float
    runner_up: float
    face_px: int
    at: datetime
    model: str

    @property
    def margin(self) -> float:
        return self.score - self.runner_up


@dataclass(frozen=True)
class Anchor:
    """A stop on a path, with the evidence that earned it.

    The evidence travels so the page can answer "why do you believe this?" in
    the operator's own terms — "3 matches over 4 seconds, best 0.71" — instead
    of asking them to trust a coloured dot.

    There is deliberately no box geometry here. An anchor is a place on a
    path, not something to draw on a frame.
    """

    person_id: str
    camera_id: str
    started_at: datetime
    ended_at: datetime
    #: separate looks, not frames.
    matches: int
    best: float
    mean: float
    #: the smallest face that contributed. The weakest link, not the flattering
    #: one — an anchor is only as good as its worst piece of evidence.
    face_px: int
    model: str

    @property
    def span_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class _Run:
    """One unbroken series of looks at one person on one camera."""

    __slots__ = ("started_at", "last_at", "look_started_at", "scores", "face_px",
                 "model", "emitted_at")

    def __init__(self, match: FaceMatch) -> None:
        self.started_at = match.at
        self.last_at = match.at
        #: when the look being folded into began. The gap is measured from
        #: HERE and never from the last frame, or a continuous stream would
        #: fold forever: at 5fps every frame lands 0.2s after the one before
        #: it, so a run would never advance and somebody standing still
        #: could never be identified at all.
        self.look_started_at = match.at
        self.scores: list[float] = [match.score]
        self.face_px = match.face_px
        self.model = match.model
        #: when this run last produced an anchor, so a person standing still
        #: does not mean a write per frame.
        self.emitted_at: datetime | None = None

    def add_look(self, match: FaceMatch) -> None:
        self.last_at = match.at
        self.look_started_at = match.at
        self.scores.append(match.score)
        self.face_px = min(self.face_px, match.face_px)

    def fold_in(self, match: FaceMatch) -> None:
        """Same look, seen again. It can improve the evidence but not count."""
        self.last_at = match.at
        self.face_px = min(self.face_px, match.face_px)
        if match.score > self.scores[-1]:
            self.scores[-1] = match.score

    @property
    def looks(self) -> int:
        return len(self.scores)

    @property
    def span_seconds(self) -> float:
        return (self.last_at - self.started_at).total_seconds()


class AnchorAccumulator:
    """Feeds on matches, and says when there is finally enough of them.

    Pure logic: no database, no clock of its own, no threads. Every instant
    comes in on the match, which is what makes a whole minute of walking past
    a camera testable in a few lines.
    """

    def __init__(self, gates: AnchorGates, run_gap_seconds: float = RUN_GAP_SECONDS) -> None:
        self.gates = gates
        self.run_gap = timedelta(seconds=run_gap_seconds)
        # (camera_id, person_id) -> the run currently building
        self._runs: dict[tuple[str, str], _Run] = {}

    @property
    def tracked_runs(self) -> int:
        """How many runs are being held. Housekeeping visibility, not a fact."""
        return len(self._runs)

    def offer(self, camera_id: str, match: FaceMatch) -> Anchor | None:
        """Feed one match. Returns an anchor when there is enough to claim one.

        Returns an anchor the first time a run clears every gate, and again as
        that run grows — always carrying the same `started_at`, so the caller
        writes one row and then updates it. A person standing at one camera is
        one stop that gets longer, not a new stop every second.
        """
        self._forget_stale(match.at)

        if not self._is_evidence(match):
            # Below the bar is not weak evidence, it is none: it does not
            # count, and it does not get averaged into what does.
            return None

        key = (camera_id, match.person_id)
        run = self._runs.get(key)

        if run is None:
            self._runs[key] = _Run(match)
            return None

        if (match.at - run.look_started_at).total_seconds() < self.gates.gap_seconds:
            run.fold_in(match)
        else:
            run.add_look(match)

        return self._verdict(camera_id, match.person_id, run)

    def drop(self, camera_id: str, person_id: str | None = None) -> None:
        """Forget a run. Used when a camera stops, so it cannot resume later."""
        for key in list(self._runs):
            if key[0] == camera_id and (person_id is None or key[1] == person_id):
                del self._runs[key]

    # -- the gates ----------------------------------------------------------

    def _is_evidence(self, match: FaceMatch) -> bool:
        gates = self.gates
        return (
            match.score >= gates.score
            and match.margin >= gates.margin
            and match.face_px >= gates.face_px
        )

    def _verdict(self, camera_id: str, person_id: str, run: _Run) -> Anchor | None:
        gates = self.gates
        if run.looks < gates.matches or run.span_seconds < gates.seconds:
            return None

        if run.emitted_at is not None:
            # Already claimed. Re-state it only once the stop has grown by as
            # much time as the gate is built on, so standing still costs one
            # write every `seconds` rather than one per frame.
            if (run.last_at - run.emitted_at).total_seconds() < gates.seconds:
                return None

        run.emitted_at = run.last_at
        return Anchor(
            person_id=person_id,
            camera_id=camera_id,
            started_at=run.started_at,
            ended_at=run.last_at,
            matches=run.looks,
            best=max(run.scores),
            mean=sum(run.scores) / len(run.scores),
            face_px=run.face_px,
            model=run.model,
        )

    def _forget_stale(self, now: datetime) -> None:
        """Drop runs nobody is adding to, so memory tracks who is here."""
        stale = [key for key, run in self._runs.items() if now - run.last_at > self.run_gap]
        for key in stale:
            del self._runs[key]
