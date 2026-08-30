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

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vg import db
from vg.clock import Clock, clock_for
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

    Pure logic: no database and no clock of its own. Every instant comes in
    on the match, which is what makes a whole minute of walking past a camera
    testable in a few lines.

    It starts no threads, but it is called from several: one worker holds one
    accumulator and `FeatureWorker` runs a thread per camera. The lock is for
    that, and it is the only concurrency in this file.
    """

    def __init__(self, gates: AnchorGates, run_gap_seconds: float = RUN_GAP_SECONDS) -> None:
        self.gates = gates
        self.run_gap = timedelta(seconds=run_gap_seconds)
        self._lock = threading.RLock()
        # (camera_id, person_id) -> the run currently building
        self._runs: dict[tuple[str, str], _Run] = {}

    @property
    def tracked_runs(self) -> int:
        """How many runs are being held. Housekeeping visibility, not a fact."""
        with self._lock:
            return len(self._runs)

    def offer(self, camera_id: str, match: FaceMatch) -> Anchor | None:
        """Feed one match. Returns an anchor when there is enough to claim one.

        Returns an anchor the first time a run clears every gate, and again as
        that run grows — always carrying the same `started_at`, so the caller
        writes one row and then updates it. A person standing at one camera is
        one stop that gets longer, not a new stop every second.
        """
        with self._lock:
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
        with self._lock:
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


SCHEMA = """
CREATE TABLE IF NOT EXISTS anchor (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     TEXT NOT NULL,
    camera_id     TEXT NOT NULL,
    started_at    TEXT NOT NULL,          -- ISO-8601 UTC
    ended_at      TEXT NOT NULL,
    local_date    TEXT NOT NULL,          -- the SITE's date, as sightings uses
    matches       INTEGER NOT NULL,       -- separate looks, not frames
    best          REAL NOT NULL,
    mean          REAL NOT NULL,
    face_px       INTEGER NOT NULL,       -- the smallest face that contributed
    model         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anchor_person_date
    ON anchor(person_id, local_date);
CREATE INDEX IF NOT EXISTS idx_anchor_date ON anchor(local_date);

-- One row per run, not per verdict. The accumulator re-states a stop as it
-- grows, always with the same start, so this turns "they are still there"
-- into an update instead of a second stop in the same doorway.
CREATE UNIQUE INDEX IF NOT EXISTS idx_anchor_run
    ON anchor(person_id, camera_id, started_at);

-- Exactly one row, written by tools/measure_track.py. Estimates read it and
-- refuse to guess when it is absent.
CREATE TABLE IF NOT EXISTS measured_rates (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    fetch_x       REAL NOT NULL,          -- archive fetch speed, x real-time
    process_fps   REAL NOT NULL,          -- detect + track + encode, frames/sec
    measured_at   TEXT NOT NULL,
    backend       TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(frozen=True)
class MeasuredRates:
    """How fast this machine actually did the work, when somebody measured it.

    Never a default and never a guess. Every wait this feature quotes comes
    from here, and when there is no row the page says the wait is unknown —
    which is a worse answer to read and a much better one to trust.
    """

    fetch_x: float
    process_fps: float
    measured_at: datetime
    backend: str = ""


class AnchorStore:
    """The anchor table, and the one row of measured rates beside it.

    Same idioms as `SightingStore`, deliberately: one connection through
    `db.connect`, one re-entrant lock, ISO-8601 UTC on the way in, the site's
    own date for anything a person will ask a question about.
    """

    def __init__(self, database: Path | str, clock: Clock | int | str = 0) -> None:
        self.path = Path(database)
        # Asked per instant, never cached. An offset held from startup is an
        # hour wrong from the last Friday in October until someone restarts.
        self.clock = clock_for(clock)

        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def local_date(self, when: datetime) -> str:
        return self.clock.local_date(when)

    # -- writing ------------------------------------------------------------

    def record(self, anchor: Anchor) -> None:
        """Write a stop, or extend the one already there.

        An upsert rather than an insert, because a person standing at a camera
        is one stop that grows: the accumulator re-states it with the same
        start and a later end, and two rows for one visit would draw two stops
        on the path where the operator saw one person standing still.
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO anchor (person_id, camera_id, started_at, ended_at, "
                "local_date, matches, best, mean, face_px, model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(person_id, camera_id, started_at) DO UPDATE SET "
                "ended_at = excluded.ended_at, matches = excluded.matches, "
                "best = excluded.best, mean = excluded.mean, "
                "face_px = excluded.face_px",
                (
                    anchor.person_id,
                    anchor.camera_id,
                    _iso(anchor.started_at),
                    _iso(anchor.ended_at),
                    self.local_date(anchor.started_at),
                    anchor.matches,
                    anchor.best,
                    anchor.mean,
                    anchor.face_px,
                    anchor.model,
                ),
            )
            self._conn.commit()

    # -- reading ------------------------------------------------------------

    def skeleton(
        self,
        person_id: str,
        on: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Anchor]:
        """One person's stops on one day, in order. One indexed read.

        This is the whole of the "instant path": there is no scan, no video
        and no model. Nothing below the gates was ever written, so the query
        cannot return a stop the system does not actually believe.
        """
        query = ("SELECT * FROM anchor WHERE person_id = ? AND local_date = ?")
        params: list = [person_id, on]
        if start is not None:
            query += " AND ended_at >= ?"
            params.append(_iso(start))
        if end is not None:
            query += " AND started_at <= ?"
            params.append(_iso(end))
        query += " ORDER BY started_at"

        with self._lock:
            rows = list(self._conn.execute(query, params))
        return [_to_anchor(r) for r in rows]

    def dates_for(self, person_id: str) -> list[str]:
        """Which days this person has any stops on. Newest first."""
        with self._lock:
            rows = list(self._conn.execute(
                "SELECT DISTINCT local_date FROM anchor WHERE person_id = ? "
                "ORDER BY local_date DESC",
                (person_id,),
            ))
        return [r["local_date"] for r in rows]

    # -- measured rates -----------------------------------------------------

    def rates(self) -> MeasuredRates | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM measured_rates WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return MeasuredRates(
            fetch_x=float(row["fetch_x"]),
            process_fps=float(row["process_fps"]),
            measured_at=_parse(row["measured_at"]),
            backend=row["backend"] or "",
        )

    def set_rates(
        self, fetch_x: float, process_fps: float, backend: str = "",
        at: datetime | None = None,
    ) -> MeasuredRates:
        at = at or datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                "INSERT INTO measured_rates (id, fetch_x, process_fps, "
                "measured_at, backend) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET fetch_x = excluded.fetch_x, "
                "process_fps = excluded.process_fps, "
                "measured_at = excluded.measured_at, backend = excluded.backend",
                (float(fetch_x), float(process_fps), _iso(at), backend),
            )
            self._conn.commit()
        return MeasuredRates(fetch_x, process_fps, at, backend)

    # -- housekeeping -------------------------------------------------------

    def clear(self) -> None:
        """Wipe every anchor. Test and demo use only."""
        with self._lock:
            self._conn.execute("DELETE FROM anchor")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "AnchorStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_anchor(row) -> Anchor:
    return Anchor(
        person_id=row["person_id"],
        camera_id=row["camera_id"],
        started_at=_parse(row["started_at"]),
        ended_at=_parse(row["ended_at"]),
        matches=int(row["matches"]),
        best=float(row["best"]),
        mean=float(row["mean"]),
        face_px=int(row["face_px"]),
        model=row["model"],
    )
