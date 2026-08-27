"""Why a plate is only recorded once several frames agree.

The reader is right about nine times in ten on a single frame. That is not
good enough to write a car into a gate log — one frame in ten records somebody
else's plate. But a car approaching a gate is visible for dozens of frames and
the errors are *not* correlated: misreads scatter, the correct reading
repeats. This file pins the machinery that turns the second fact into a
reliable system.

Three properties, and each fails differently if it breaks:

- **Too few frames** → the wrong car is recorded, confidently.
- **Votes that split instead of merging** → nothing is *ever* recorded, and it
  looks like the reader is broken rather than the arithmetic.
- **No de-duplication** → a car waiting at a barrier becomes twenty arrivals.

No model, no camera, no database. Frames are dataclasses and time is chosen by
the test, so a sixty-second window is proven in microseconds.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import platetext  # noqa: E402
from vg.features.vehicles import (  # noqa: E402
    DEDUPE_SECONDS,
    KEEP_ATTEMPTS,
    LOST_FRAMES,
    MIN_VOTES,
    REVIEW_BELOW,
    VehiclesWorker,
    _Track,
    vote_weight,
)
from vg.infer.plates import MIN_PLATE_WIDTH_PX, PlateBox, PlateRead  # noqa: E402
from vg.ingest.source import Frame  # noqa: E402

PLATE = "بجد 1234"
OTHER = "سصط 9876"

START = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)


def box(x1: int = 100, width: int = 120) -> PlateBox:
    return PlateBox(x1=x1, y1=200, x2=x1 + width, y2=240, confidence=0.9)


def read(text: str, confidence: float = 0.9, width: int = 120,
         x1: int = 100) -> PlateRead:
    return PlateRead(box=box(x1, width), text=text, confidence=confidence)


class FakeReader:
    """Returns whatever the test says the camera saw this frame."""

    def __init__(self, script: list[list[PlateRead]]) -> None:
        self.script = list(script)
        self.form = "test"
        self.version = "test"
        self.device = "cpu"

    def read_frame(self, image) -> list[PlateRead]:
        return self.script.pop(0) if self.script else []


def frame(at: datetime, sequence: int = 0) -> Frame:
    return Frame(camera_id="gate1", image=np.zeros((4, 4, 3), dtype=np.uint8),
                 captured_at=at, sequence=sequence)


def worker(script: list[list[PlateRead]], recorded: list | None = None,
           dedupe_seconds: float = DEDUPE_SECONDS):
    """A worker that never starts a thread. `analyse` is called directly."""
    passes = recorded if recorded is not None else []
    return VehiclesWorker(
        bus=None, reader=FakeReader(script), cameras=[],
        on_pass=lambda camera_id, record: passes.append((camera_id, record)),
        dedupe_seconds=dedupe_seconds,
    )


def run(script: list[list[PlateRead]], seconds: float = 0.25):
    """Feed the script frame by frame. Returns everything recorded."""
    recorded: list = []
    w = worker(script, recorded)
    at = START
    for i in range(len(script)):
        w.analyse(frame(at, sequence=i))
        at += timedelta(seconds=seconds)
    return recorded, w


# ---------------------------------------------------------------------------
# the weighting
# ---------------------------------------------------------------------------

class TestWhatAFrameIsWorth:
    """All three factors have to be in the product, and each covers a
    different way a single frame can be misleading."""

    def test_a_clear_close_plausible_read_is_worth_the_most(self):
        assert vote_weight(1.0, 1.0, 200) == 1.0

    def test_an_implausible_read_is_worth_less_however_confident(self):
        """Otherwise a crisp reading of nonsense outvotes a real plate."""
        assert vote_weight(1.0, 0.2, 200) < vote_weight(0.6, 1.0, 200)

    def test_a_tiny_plate_is_worth_less_however_plausible(self):
        """Otherwise a barely-visible plate outvotes a clear one."""
        assert vote_weight(1.0, 1.0, 40) < vote_weight(1.0, 1.0, 200)

    def test_being_enormous_stops_helping(self):
        """Capped so one huge plate cannot outvote three good readings."""
        assert vote_weight(1.0, 1.0, 400) == vote_weight(1.0, 1.0, 200)

    def test_nothing_is_worth_nothing(self):
        assert vote_weight(0.0, 1.0, 200) == 0.0
        assert vote_weight(1.0, 0.0, 200) == 0.0
        assert vote_weight(1.0, 1.0, 0) == 0.0


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------

class TestFramesMustAgree:
    def test_one_frame_is_never_enough(self):
        recorded, _ = run([[read(PLATE)]])

        assert recorded == []

    def test_two_frames_are_still_not_enough(self):
        recorded, _ = run([[read(PLATE)], [read(PLATE)]])

        assert recorded == [], f"{MIN_VOTES} frames must agree, not two"

    def test_three_agreeing_frames_record_exactly_one_pass(self):
        recorded, _ = run([[read(PLATE)]] * 3)

        assert len(recorded) == 1
        assert recorded[0][1].plate == PLATE
        assert recorded[0][1].votes >= MIN_VOTES

    def test_more_frames_of_the_same_car_do_not_record_it_again(self):
        """A car sits at a barrier. It is one arrival, not eight."""
        recorded, _ = run([[read(PLATE)]] * 8)

        assert len(recorded) == 1

    def test_three_frames_of_different_cars_record_nothing(self):
        """Disagreement is not agreement, however many frames there are."""
        recorded, _ = run([[read(PLATE)], [read(OTHER)], [read("مثم 5555")]])

        assert recorded == []

    def test_the_pass_is_stamped_with_the_first_sighting(self):
        """An operator opening the snapshot should watch the car arrive, not
        find it already at the barrier."""
        recorded, _ = run([[read(PLATE)]] * 3, seconds=1.0)

        assert recorded[0][1].first_seen == START


# ---------------------------------------------------------------------------
# merging — the property that makes the rest possible
# ---------------------------------------------------------------------------

class TestNearReadingsMerge:
    """`ب/ت` and `ج/ح` are the same shape at gate distances.

    If two spellings of one plate compete instead of combining, three frames
    never agree and the car is **never recorded** — which looks like the
    reader failing rather than the arithmetic.
    """

    def test_two_spellings_of_one_plate_reach_agreement_together(self):
        recorded, _ = run([
            [read("بجد 1234")],
            [read("بجد 1244")],     # one digit misread
            [read("بجد 1234")],
        ])

        assert len(recorded) == 1

    def test_the_fuller_reading_wins_the_merge(self):
        """A dropped character is far more common than an invented one."""
        track = _Track(box=box(), first_seen=START, last_seen=START)
        track.vote("مب 451", 1.0, 0.9)
        track.vote("مجب 451", 1.0, 0.9)

        assert track.leader[0] == "مجب 451"

    def test_a_genuinely_different_plate_does_not_merge(self):
        track = _Track(box=box(), first_seen=START, last_seen=START)
        track.vote(PLATE, 1.0, 0.9)
        track.vote(OTHER, 1.0, 0.9)

        assert len(track.votes) == 2

    def test_an_empty_reading_is_not_a_vote(self):
        track = _Track(box=box(), first_seen=START, last_seen=START)
        track.vote("", 1.0, 0.9)

        assert track.votes == {}


# ---------------------------------------------------------------------------
# weak reads
# ---------------------------------------------------------------------------

class TestAWeakReadIsKeptNotDiscarded:
    """P6-FR-005. A weak reading is still evidence a car went through, and the
    snapshot is kept with it. Discarding it loses the only record that
    anything happened; keeping it unflagged states something not known."""

    def test_it_is_recorded_and_flagged(self):
        weak = REVIEW_BELOW - 0.1
        recorded, _ = run([[read(PLATE, confidence=weak)]] * 6)

        assert len(recorded) == 1
        assert recorded[0][1].needs_review is True

    def test_a_confident_read_is_not_flagged(self):
        recorded, _ = run([[read(PLATE, confidence=0.95)]] * 3)

        assert recorded[0][1].needs_review is False

    def test_the_confidence_and_the_frame_count_travel_with_it(self):
        """So a guard can judge for themselves rather than take a flag on
        faith."""
        recorded, _ = run([[read(PLATE, confidence=0.95)]] * 3)
        record = recorded[0][1]

        assert 0.0 < record.confidence <= 1.0
        assert record.votes >= MIN_VOTES


# ---------------------------------------------------------------------------
# de-duplication
# ---------------------------------------------------------------------------

class TestOneCarIsOnePass:
    def test_the_same_plate_returning_at_once_is_not_a_second_pass(self):
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded)
        at = START
        for i in range(3):
            w.analyse(frame(at, i))
            at += timedelta(seconds=0.25)
        assert len(recorded) == 1

        # The car leaves view and comes straight back — still one visit.
        w.reader.script = [[]] * 12 + [[read(PLATE)]] * 3
        for i in range(15):
            w.analyse(frame(at, 100 + i))
            at += timedelta(seconds=0.25)

        assert len(recorded) == 1

    def test_the_same_plate_much_later_is_a_new_pass(self):
        """The car really did leave and came back. That is two arrivals.

        Note what "left" has to mean here: **frames with no plate in them**,
        long enough for the track to be dropped. Simply moving the clock
        forward is not the same thing and must not be — a car idling at a
        barrier for two minutes is still one arrival, and a de-duplication
        window that expired underneath it would log a second.
        """
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded)
        at = START
        for i in range(3):
            w.analyse(frame(at, i))
            at += timedelta(seconds=0.25)
        assert len(recorded) == 1

        # Gone: empty frames until the track is dropped, and long enough that
        # the de-duplication window has passed too.
        w.reader.script = [[]] * 20
        for i in range(20):
            w.analyse(frame(at, 100 + i))
            at += timedelta(seconds=5)
        assert at - START > timedelta(seconds=DEDUPE_SECONDS)

        # Back again.
        w.reader.script = [[read(PLATE)]] * 3
        for i in range(3):
            w.analyse(frame(at, 200 + i))
            at += timedelta(seconds=0.25)

        assert len(recorded) == 2

    def test_a_car_idling_at_the_barrier_stays_one_pass(self):
        """The other half of the same rule, and the one that would quietly
        corrupt a gate log. A car in view for well past the de-duplication
        window has still only arrived once."""
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded)
        at = START
        for i in range(3):
            w.analyse(frame(at, i))
            at += timedelta(seconds=0.25)

        w.reader.script = [[read(PLATE)]] * 40
        for i in range(40):
            w.analyse(frame(at, 300 + i))
            at += timedelta(seconds=5)
        assert at - START > timedelta(seconds=DEDUPE_SECONDS)

        assert len(recorded) == 1

    def test_two_different_cars_in_the_same_frames_are_two_passes(self):
        """Boxes far apart are different vehicles, not one changing its mind."""
        recorded, _ = run([
            [read(PLATE, x1=100), read(OTHER, x1=600)],
        ] * 3)

        assert {r[1].plate for r in recorded} == {PLATE, OTHER}


# ---------------------------------------------------------------------------
# a plate too small to read
# ---------------------------------------------------------------------------

class TestAPlateTooSmallToRead:
    """No amount of software fixes a plate forty pixels wide. Saying so is
    worth more than trying — an operator should be told to move the camera,
    not left wondering why nothing is recorded."""

    def test_it_is_not_voted_on(self):
        tiny = MIN_PLATE_WIDTH_PX - 20
        recorded, _ = run([[read(PLATE, width=tiny)]] * 6)

        assert recorded == []

    def test_the_result_says_the_plate_was_too_small(self):
        tiny = MIN_PLATE_WIDTH_PX - 20
        w = worker([[read(PLATE, width=tiny)]])

        assert w.analyse(frame(START)).too_small is True

    def test_a_readable_plate_does_not_raise_it(self):
        w = worker([[read(PLATE, width=MIN_PLATE_WIDTH_PX + 40)]])

        assert w.analyse(frame(START)).too_small is False


# ---------------------------------------------------------------------------
# the worker keeps working
# ---------------------------------------------------------------------------

class TestFailuresDoNotStopTheCamera:
    def test_a_store_that_refuses_a_write_does_not_kill_the_thread(self):
        """A camera thread dying inside a database error would take live view
        down with it, and the operator would see a frozen picture rather than
        an error."""
        def explode(camera_id, record):
            raise RuntimeError("database is locked")

        w = VehiclesWorker(bus=None, reader=FakeReader([[read(PLATE)]] * 3),
                           cameras=[], on_pass=explode)
        at = START
        for i in range(3):
            w.analyse(frame(at, i))       # must not raise
            at += timedelta(seconds=0.25)

    def test_a_frame_with_nothing_in_it_is_free(self):
        w = worker([[]])

        result = w.analyse(frame(START))

        assert result.reads == ()
        assert result.passes == ()

    @pytest.mark.parametrize("text", ["", "   "])
    def test_a_plate_found_but_not_read_records_nothing(self, text):
        """The detector saw a plate; the reader could not make it out. That is
        not a pass, and inventing one would be the worst kind of guess."""
        recorded, _ = run([[read(text)]] * 6)

        assert recorded == []


# ---------------------------------------------------------------------------
# the window is configured, not compiled in
# ---------------------------------------------------------------------------

class TestTheRepeatWindowIsConfigured:
    """P6-FR-006 says *configured*, and it was a module constant.

    What that cost showed up with a plate in somebody's hand: the second read
    of the same plate is ignored for a minute. At a barrier that is exactly
    right. On a desk, testing, it looks precisely like a reader that has
    stopped working — and nothing on screen says otherwise.
    """

    @staticmethod
    def _seen_again(w, recorded, gap_seconds: float) -> int:
        """Show the plate, take it away long enough to drop the track, show it
        again `gap_seconds` after the first pass. Returns the passes recorded.

        The track has to be dropped, or nothing is emitted whatever the window
        says — a car still in view has still only arrived once, which is the
        rule the test below this one pins.
        """
        at = START
        for i in range(3):
            w.analyse(frame(at, i))
            at += timedelta(seconds=0.25)

        w.reader.script = [[]] * (LOST_FRAMES + 2)
        for i in range(LOST_FRAMES + 2):
            w.analyse(frame(at, 100 + i))
            at += timedelta(seconds=0.1)

        at = START + timedelta(seconds=gap_seconds)
        w.reader.script = [[read(PLATE)]] * 3
        for i in range(3):
            w.analyse(frame(at, 200 + i))
            at += timedelta(seconds=0.25)
        return len(recorded)

    def test_the_default_matches_the_constant_it_replaced(self):
        from vg.config import VehiclesConfig

        assert VehiclesConfig().dedupe_seconds == DEDUPE_SECONDS

    def test_the_default_still_swallows_a_repeat_eight_seconds_later(self):
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded)

        assert self._seen_again(w, recorded, gap_seconds=8.0) == 1

    def test_a_configured_short_window_lets_it_through(self):
        """The same eight seconds, with the window set the way somebody
        testing would set it."""
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded, dedupe_seconds=3.0)

        assert self._seen_again(w, recorded, gap_seconds=8.0) == 2

    def test_zero_records_every_settled_read(self):
        """`engine.yaml` says so in words, so it has to be true."""
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded, dedupe_seconds=0.0)

        assert self._seen_again(w, recorded, gap_seconds=1.0) == 2

    def test_a_short_window_does_not_split_a_car_that_never_left(self):
        """The rule the window must not break, at any setting. A car idling in
        view has arrived once however long it sits there."""
        recorded: list = []
        w = worker([[read(PLATE)]] * 3, recorded, dedupe_seconds=1.0)
        at = START
        for i in range(3):
            w.analyse(frame(at, i))
            at += timedelta(seconds=0.25)

        w.reader.script = [[read(PLATE)]] * 40
        for i in range(40):
            w.analyse(frame(at, 300 + i))
            at += timedelta(seconds=5)

        assert len(recorded) == 1

    def test_the_config_refuses_a_negative_window(self):
        from vg.config import ConfigError, VehiclesConfig

        with pytest.raises(ConfigError, match="dedupe_seconds"):
            VehiclesConfig.parse({"dedupe_seconds": -1}, "vehicles")

    def test_the_config_refuses_a_key_nobody_reads(self):
        """A typo in `engine.yaml` must not silently leave the default in
        place — that is a setting somebody believes they changed."""
        from vg.config import ConfigError, VehiclesConfig

        with pytest.raises(ConfigError, match="unknown key"):
            VehiclesConfig.parse({"dedup_seconds": 5}, "vehicles")

    def test_the_shipped_file_parses_and_carries_a_window(self):
        from vg import config as vgconfig

        assert vgconfig.load().vehicles.dedupe_seconds > 0


# ---------------------------------------------------------------------------
# what the console's reader card is shown
# ---------------------------------------------------------------------------

class TestEveryAttemptIsKept:
    """The failures are the point of this feed.

    A reader that returns nothing and one that returns something different
    every frame are different problems with different fixes — the camera's
    placement against the model itself — and neither is visible in the pass
    log, which by design contains only successes.
    """

    def test_one_attempt_per_read(self):
        _, w = run([[read("بجد 1234")], [read("بجد 1234")]])

        assert len(w.attempts_on("gate1")) == 2

    def test_newest_first(self):
        _, w = run([[read("بجد 1234")], [read("سنر 582", x1=400)]])

        assert w.attempts_on("gate1")[0].display == platetext.display("سنر 582")

    def test_a_read_that_found_nothing_still_appears(self):
        """`display` empty is the row that says "read nothing" on screen.

        Dropping it would leave the card blank on exactly the footage an
        operator most needs to look at.
        """
        _, w = run([[read("")]])

        attempt = w.attempts_on("gate1")[0]
        assert attempt.display == ""
        assert attempt.width_px == 120

    def test_a_read_that_found_nothing_claims_no_confidence(self):
        """None, not 0.0. Zero is a measurement; there was nothing to measure."""
        _, w = run([[read("")]])

        attempt = w.attempts_on("gate1")[0]
        assert attempt.confidence is None
        assert attempt.plausibility is None

    def test_a_plate_too_small_to_read_is_recorded_as_an_attempt(self):
        """The most common reason a gate records nothing, and invisible
        everywhere else by definition."""
        narrow = MIN_PLATE_WIDTH_PX - 10
        _, w = run([[read("بجد 1234", width=narrow)]])

        attempts = w.attempts_on("gate1")
        assert len(attempts) == 1
        assert attempts[0].width_px == narrow

    def test_the_leader_and_votes_travel_with_the_attempt(self):
        """This is what lets somebody watch three frames agree."""
        _, w = run([[read("بجد 1234")], [read("بجد 1234")], [read("بجد 1234")]])

        assert [a.votes for a in reversed(w.attempts_on("gate1"))] == [1, 2, 3]
        assert w.attempts_on("gate1")[0].leader_display == platetext.display(
            "بجد 1234")

    def test_the_time_comes_from_the_frame_not_the_clock(self):
        """Same rule as everything else recorded here: the timestamps match
        the video rather than however busy the machine was."""
        _, w = run([[read("بجد 1234")]])

        assert w.attempts_on("gate1")[0].at == START

    def test_the_window_is_bounded(self):
        """A live window, not a log. The pass table is the record."""
        _, w = run([[read("بجد 1234")] for _ in range(KEEP_ATTEMPTS + 8)])

        assert len(w.attempts_on("gate1")) == KEEP_ATTEMPTS

    def test_a_camera_nobody_has_read_has_no_attempts(self):
        _, w = run([[read("بجد 1234")]])

        assert w.attempts_on("some-other-camera") == []


class TestHowLongAReadTakes:
    def test_no_timing_before_the_first_read(self):
        """None, never 0.0 — a camera nobody has driven past has no timing."""
        w = worker([])

        assert w.read_ms("gate1") is None

    def test_a_timing_appears_after_a_read(self):
        _, w = run([[read("بجد 1234")]])

        assert w.read_ms("gate1") is not None
        assert w.read_ms("gate1") >= 0.0

    def test_timing_is_per_camera(self):
        _, w = run([[read("بجد 1234")]])

        assert w.read_ms("some-other-camera") is None
