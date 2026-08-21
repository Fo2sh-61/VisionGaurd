"""Track a person — the bar for a name, the path behind one, and the video.

The rules with teeth in this feature all live server-side on purpose, because
this is the only place that can hold them. There is no web test runner, and
the two rules that matter most are the two the constitution names:

  * a face names a person, clothing only ever says "same body"
  * a name is a live annotation on a body and is never carried forward

Everything here exists to stop those from quietly breaking again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vg.config import (
    FACE_PIXEL_FLOOR,
    PATROL_GATES,
    AnchorGates,
    ConfigError,
    TrackingConfig,
)
from vg.events.anchors import AnchorAccumulator, FaceMatch

# An hour behind the clock, never a date typed on the day this was written:
# some of these assertions read back through windows measured from `now`, and
# a fixed date stops matching its own window as soon as it is stale.
START = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)

MODEL = "sface-2021dec"


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def look(
    seconds: float,
    *,
    person: str = "p-sara",
    score: float = 0.70,
    runner_up: float = 0.30,
    face_px: int = 120,
) -> FaceMatch:
    """One frame's worth of evidence, comfortably over every gate by default.

    Each test then spoils exactly one thing, so a failure names its own cause.
    """
    return FaceMatch(
        person_id=person,
        score=score,
        runner_up=runner_up,
        face_px=face_px,
        at=at(seconds),
        model=MODEL,
    )


def feed(acc: AnchorAccumulator, seconds, camera="cam-a", **kw):
    """Offer a series of looks and return every anchor that came back."""
    return [
        anchor
        for s in seconds
        if (anchor := acc.offer(camera, look(s, **kw))) is not None
    ]


@pytest.fixture
def gates() -> AnchorGates:
    # The identity tier: 3 looks, 1.5s apart-ish, 0.3s between looks.
    return AnchorGates()


@pytest.fixture
def acc(gates) -> AnchorAccumulator:
    return AnchorAccumulator(gates)


# ---------------------------------------------------------------------------
# The floor that is never bent
# ---------------------------------------------------------------------------

class TestTheFacePixelFloor:
    def test_config_floor_is_the_measured_floor(self):
        # Two constants, one truth. config.py cannot import infer.faces (cv2),
        # so the number is written twice — this is what stops them drifting.
        from vg.infer.faces import MIN_FACE_PIXELS

        assert FACE_PIXEL_FLOOR == MIN_FACE_PIXELS, (
            "the anchor gate's face floor and the measured embedding floor are "
            "the same number for the same reason; if one moves the other must"
        )

    def test_it_cannot_be_configured_lower(self):
        with pytest.raises(ConfigError) as raised:
            AnchorGates.parse({"face_px": 40}, "tracking.patrol", PATROL_GATES)

        assert "40" in str(raised.value) and str(FACE_PIXEL_FLOOR) in str(raised.value)

    def test_it_can_be_configured_higher(self):
        # Stricter is always allowed. Only downward is refused.
        stricter = AnchorGates.parse({"face_px": 140}, "tracking.identity", AnchorGates())
        assert stricter.face_px == 140

    def test_one_match_cannot_be_configured_as_enough(self):
        # `matches: 1` is exactly the single-frame naming this gate exists to
        # stop, so the config refuses it rather than quietly obeying.
        with pytest.raises(ConfigError) as raised:
            AnchorGates.parse({"matches": 1}, "tracking.identity", AnchorGates())

        assert "at least 2" in str(raised.value)


# ---------------------------------------------------------------------------
# Each gate, alone, blocks the verdict
# ---------------------------------------------------------------------------

class TestEachGateAlone:
    def test_one_perfect_match_is_never_enough(self, acc):
        # The whole point. A single frame, however confident, names nobody.
        assert acc.offer("cam-a", look(0.0, score=0.99, runner_up=0.01)) is None

    def test_enough_looks_over_enough_time_anchors(self, acc):
        anchors = feed(acc, [0.0, 0.8, 1.6])

        assert anchors, "3 looks spanning 1.6s clears the identity tier"
        assert anchors[0].person_id == "p-sara"
        assert anchors[0].camera_id == "cam-a"

    def test_a_low_score_is_not_evidence(self, acc, gates):
        below = gates.score - 0.01
        assert feed(acc, [0.0, 0.8, 1.6, 2.4, 3.2], score=below) == []

    def test_a_narrow_margin_is_not_evidence(self, acc, gates):
        # Over the score bar, but the runner-up is right behind: the two
        # candidates are not separable and naming either is a guess.
        runner_up = 0.70 - gates.margin + 0.01
        assert feed(acc, [0.0, 0.8, 1.6, 2.4, 3.2], runner_up=runner_up) == []

    def test_a_small_face_is_not_evidence(self, acc):
        assert feed(acc, [0.0, 0.8, 1.6, 2.4, 3.2], face_px=FACE_PIXEL_FLOOR - 1) == []

    def test_a_face_exactly_on_the_floor_is_evidence(self, acc):
        # The floor is inclusive: 80px was measured as workable, not as failing.
        assert feed(acc, [0.0, 0.8, 1.6], face_px=FACE_PIXEL_FLOOR) != []

    def test_too_few_looks_blocks_the_verdict(self, acc):
        # Two good looks, well spread. Still one short of the bar.
        assert feed(acc, [0.0, 2.0]) == []

    def test_too_short_a_span_blocks_the_verdict(self, acc, gates):
        # Three separate looks — the gap gate passes — but crammed into less
        # than the required span. Someone glancing past is not someone here.
        assert gates.gap_seconds < 0.4
        assert feed(acc, [0.0, 0.5, 1.0]) == [], "1.0s < the 1.5s span gate"

    def test_a_burst_inside_the_gap_is_one_look(self, acc):
        # Five frames in a third of a second is one look at one moment, not
        # five pieces of evidence. This is the gate that stops a lucky burst
        # from buying a name.
        assert feed(acc, [0.0, 0.05, 0.10, 0.15, 0.20]) == []


# ---------------------------------------------------------------------------
# The corner tier — "don't make it so hard"
# ---------------------------------------------------------------------------

class TestTheCornerTier:
    def test_a_plausible_corner_sequence_anchors(self):
        # A corridor camera at the patrol rate: a face seen three times over
        # four seconds, off-angle, scoring modestly, at a face size a corridor
        # actually produces. If this does not anchor, corridors never appear
        # on a path and the feature does not exist.
        acc = AnchorAccumulator(PATROL_GATES)
        anchors = feed(
            acc, [0.0, 2.0, 4.0], score=0.44, runner_up=0.34, face_px=88
        )

        assert anchors, "the corner defaults must pass a real corridor look"
        assert anchors[0].matches == 3

    def test_the_corner_tier_is_still_a_bar(self, gates):
        # Lenient is not absent. The same sequence one notch below the patrol
        # score still buys nothing.
        acc = AnchorAccumulator(PATROL_GATES)
        assert PATROL_GATES.score < gates.score
        assert feed(acc, [0.0, 2.0, 4.0], score=PATROL_GATES.score - 0.01) == []

    def test_a_camera_gets_the_tier_its_flag_says(self):
        from vg.config import CameraConfig

        tracking = TrackingConfig()
        doorway = CameraConfig(id="cam-a", name="Door", source="webcam:0", faces=True)
        corridor = CameraConfig(id="cam-b", name="Hall", source="webcam:1")

        assert tracking.gates_for(doorway) is tracking.identity
        assert tracking.gates_for(corridor) is tracking.patrol


# ---------------------------------------------------------------------------
# Runs are kept apart, and carry their evidence
# ---------------------------------------------------------------------------

class TestRuns:
    def test_two_people_on_one_camera_do_not_pool_evidence(self, acc):
        # Two people each seen twice is not one person seen four times.
        for seconds, person in ((0.0, "p-sara"), (0.8, "p-omar"),
                                (1.6, "p-sara"), (2.4, "p-omar")):
            assert acc.offer("cam-a", look(seconds, person=person)) is None

    def test_one_person_on_two_cameras_does_not_pool_evidence(self, acc):
        for seconds, camera in ((0.0, "cam-a"), (0.8, "cam-b"),
                                (1.6, "cam-a"), (2.4, "cam-b")):
            assert acc.offer(camera, look(seconds)) is None

    def test_a_long_silence_starts_a_new_stop(self, acc):
        first = feed(acc, [0.0, 0.8, 1.6])
        assert first

        # Gone long enough to have left and come back. The next run is a
        # second stop on the path, not a continuation of the first.
        second = feed(acc, [600.0, 600.8, 601.6])
        assert second
        assert second[0].started_at > first[0].ended_at

    def test_the_anchor_carries_its_evidence(self, acc):
        anchors = feed(acc, [0.0, 0.8, 1.6], score=0.66, face_px=95)
        anchor = anchors[0]

        # "3 matches over 1.6s, best 0.66" — the sentence the page shows when
        # somebody asks why this stop is believed.
        assert anchor.matches == 3
        assert anchor.started_at == at(0.0)
        assert anchor.ended_at == at(1.6)
        assert anchor.span_seconds == pytest.approx(1.6)
        assert anchor.best == pytest.approx(0.66)
        assert anchor.mean == pytest.approx(0.66)
        assert anchor.face_px == 95, "the smallest face that contributed"
        assert anchor.model == MODEL

    def test_the_smallest_face_is_the_one_reported(self, acc):
        acc.offer("cam-a", look(0.0, face_px=200))
        acc.offer("cam-a", look(0.8, face_px=90))
        anchor = acc.offer("cam-a", look(1.6, face_px=140))

        assert anchor is not None and anchor.face_px == 90

    def test_evidence_below_the_bar_is_not_averaged_in(self, acc, gates):
        # A weak frame between two strong ones must not drag the reported
        # score down, because it was never evidence in the first place.
        acc.offer("cam-a", look(0.0, score=0.70))
        acc.offer("cam-a", look(0.8, score=gates.score - 0.2))
        acc.offer("cam-a", look(1.6, score=0.70))
        anchor = acc.offer("cam-a", look(2.4, score=0.70))

        assert anchor is not None
        assert anchor.matches == 3
        assert anchor.mean == pytest.approx(0.70)


class TestStandingStill:
    def test_a_growing_stop_extends_rather_than_repeating(self, acc):
        anchors = feed(acc, [0.0, 0.8, 1.6, 3.2, 4.8, 6.4])

        # Somebody standing at one camera is ONE stop that grows, not a new
        # stop every second. Every re-emit carries the same start so the store
        # updates one row.
        assert len({a.started_at for a in anchors}) == 1
        assert anchors[-1].ended_at > anchors[0].ended_at
        assert anchors[-1].matches > anchors[0].matches

    def test_it_does_not_re_emit_on_every_frame(self, acc, gates):
        # At 5fps a person standing still would otherwise mean five writes a
        # second, for one fact that has not changed.
        seconds = [i * 0.2 for i in range(40)]  # 8 seconds at 5fps
        anchors = feed(acc, seconds)

        assert anchors, "it still anchors"
        assert len(anchors) <= 8 / gates.seconds + 1, "but it does not spam"


class TestHousekeeping:
    def test_people_who_left_are_forgotten(self, acc):
        feed(acc, [0.0, 0.8, 1.6])
        assert acc.tracked_runs == 1

        # A later look at somebody else prunes the run nobody is adding to.
        acc.offer("cam-a", look(600.0, person="p-omar"))
        assert acc.tracked_runs == 1
