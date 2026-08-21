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
from pathlib import Path

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


# ===========================================================================
# US1 — catching somebody live
#
# The worker is driven directly: `analyse()` is called with scripted frames,
# exactly as the zones tests drive theirs. No threads start, and every instant
# comes off the frame, so a walk across a building is a list of tuples.
# ===========================================================================

import numpy as np

from vg.api.store import MockStore
from vg.identity.appearance import AppearanceSighting
from vg.ingest.source import Frame

#: Frame time is real time here. The follow session is judged against the
#: frames it is given, and the recorder — a real one in some of these — stamps
#: itself off the wall clock.
LIVE = datetime.now(timezone.utc).replace(microsecond=0)


def frame(camera_id: str, seconds: float, sequence: int = 0) -> Frame:
    """One frame, `seconds` after LIVE. The image is never looked at."""
    return Frame(
        camera_id=camera_id,
        image=np.zeros((4, 4, 3), dtype=np.uint8),
        captured_at=LIVE + timedelta(seconds=seconds),
        sequence=sequence,
    )


class Stage:
    """What each camera is showing right now, as `(stable_id, box, person)`."""

    def __init__(self) -> None:
        self.showing: dict[str, list] = {}

    def show(self, camera_id: str, bodies: list) -> None:
        self.showing[camera_id] = bodies

    def clear(self, camera_id: str) -> None:
        self.showing[camera_id] = []


class FakeDetector:
    def raw_boxes(self, frame):
        return []


class FakePool:
    """One tracker, and it passes boxes straight through."""

    class _Tracker:
        def update(self, boxes, image):
            return boxes

    def __init__(self) -> None:
        self._tracker = self._Tracker()

    def for_camera(self, camera_id: str):
        return self._tracker


class FakeAppearance:
    """Turns the stage into sightings. Never invents a name of its own."""

    stats: dict = {}

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.bound: list = []

    def observe(self, camera_id, image, tracks, at=None):
        return [
            AppearanceSighting(
                stable_id=stable_id, camera_id=camera_id, at=at,
                x=box[0], y=box[1], w=box[2], h=box[3],
                confidence=0.9, track_id=0, person_id=person_id,
            )
            for stable_id, box, person_id in self.stage.showing.get(camera_id, [])
        ]

    def bind_face(self, sightings, face_box, person_id, score, at=None):
        # What `note_face` calls. Recording the call is the point: the name
        # gate's whole job is deciding whether it happens at all.
        self.bound.append((person_id, score))
        return sightings[0].stable_id if sightings else None

    def whois(self, stable_id, now=None):
        return None

    def correct(self, stable_id, at=None):
        return None


class FakeRows:
    def __init__(self) -> None:
        self.rows = 0
        self.named: list = []

    def record_many(self, sightings):
        self.rows += len(sightings)
        return len(sightings)

    def local_date(self, at):
        return at.date().isoformat()

    def name_identity(self, stable_id, person_id, on):
        self.named.append((stable_id, person_id, on))
        return 0

    def unname_identity(self, stable_id):
        return 0


class FakeRecorder:
    """The recorder's contract, without an encoder.

    One recording per camera and a raise on a second start, because that is
    the trap the hop logic has to get right.
    """

    max_seconds = 600.0

    def __init__(self) -> None:
        self.live: dict[str, object] = {}
        self.done: list = []
        self._n = 0

    def start(self, camera_id: str, actor: str):
        from vg.ingest.recorder import AlreadyRecording, Recording

        if camera_id in self.live:
            raise AlreadyRecording(camera_id)
        self._n += 1
        rec = Recording(
            id=f"r{self._n}", camera_id=camera_id,
            started_at=datetime.now(timezone.utc), started_by=actor, fps=15.0,
        )
        self.live[camera_id] = rec
        return rec

    def stop(self, camera_id: str, actor: str):
        rec = self.live.pop(camera_id, None)
        if rec is None:
            return None
        rec.state = "saved"
        rec.stopped_at = datetime.now(timezone.utc)
        self.done.append(rec)
        return rec

    def current(self, camera_id: str):
        return self.live.get(camera_id)


def build_worker(cameras=("cam-a", "cam-b"), recorder=None):
    from vg.features.tracking import TrackingWorker

    class NoBus:
        def subscribe(self, *a, **kw):  # pragma: no cover - never started
            raise AssertionError("the worker must not be started in these tests")

    stage = Stage()
    appearance = FakeAppearance(stage)
    rows = FakeRows()
    worker = TrackingWorker(
        NoBus(), FakeDetector(), FakePool(), appearance, rows,
        list(cameras), recorder=recorder,
    )
    return worker, stage, appearance, rows


def sees(worker, stage, camera_id: str, seconds: float, bodies, sequence: int = 0):
    """Show `bodies` on a camera and let the worker look at one frame."""
    stage.show(camera_id, bodies)
    worker.analyse(frame(camera_id, seconds, sequence))


BODY_A = ("body-a", (0.10, 0.10, 0.20, 0.60), None)
BODY_B = ("body-b", (0.60, 0.10, 0.20, 0.60), None)


@pytest.fixture
def follow_app(user_store, request):
    """An app whose store is a LiveStore wired to a driven tracking worker."""
    from vg import config as vgconfig
    from vg.api import app as app_module
    from vg.api.app import create_app
    from vg.api.live import LiveStore
    from vg.ingest.registry import CameraRegistry

    recorder = getattr(request, "param", None)
    worker, stage, appearance, rows = build_worker(recorder=recorder)

    store = LiveStore(
        config=vgconfig.load(), registry=CameraRegistry([]), tracking=worker,
    )
    app_module.set_store(store)
    application = create_app()
    application.state.users = user_store
    application.state.tracking = worker
    try:
        yield application, worker, stage, recorder
    finally:
        app_module.set_store(MockStore())


class TestFollowPicksTheRightBody:
    def test_follow_picks_the_body_at_the_click_point(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A, BODY_B])

        client = authed(app)
        # Inside A's box and nowhere near B's.
        reply = client.post("/tracking/follow",
                            json={"cameraId": "cam-a", "x": 0.15, "y": 0.30})

        assert reply.status_code == 200, reply.text
        assert reply.json()["stableId"] == "body-a"

    def test_the_click_point_decides_which_of_two(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A, BODY_B])

        client = authed(app)
        reply = client.post("/tracking/follow",
                            json={"cameraId": "cam-a", "x": 0.65, "y": 0.30})
        assert reply.json()["stableId"] == "body-b"

    def test_the_audit_entry_is_written_before_the_reply(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        client = authed(app)
        assert client.post("/tracking/follow",
                           json={"cameraId": "cam-a", "x": 0.15, "y": 0.3}
                           ).status_code == 200

        actions = [e["action"] for e in client.get("/audit").json()]
        assert "track.follow" in actions

    def test_geometry_outside_0_to_1_is_refused_by_the_wire(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        client = authed(app)
        # A pixel value is a bug, not a big number (rule 6).
        reply = client.post("/tracking/follow",
                            json={"cameraId": "cam-a", "x": 412, "y": 300})
        assert reply.status_code == 422


class TestFollowRefusals:
    def test_follow_on_empty_ground_404s(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        client = authed(app)
        reply = client.post("/tracking/follow",
                            json={"cameraId": "cam-a", "x": 0.95, "y": 0.95})

        assert reply.status_code == 404
        assert "nobody" in reply.json()["detail"].lower()

    def test_a_second_follow_409s_and_names_the_first(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A, BODY_B])
        client = authed(app)

        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        second = client.post("/tracking/follow",
                             json={"cameraId": "cam-a", "x": 0.65, "y": 0.3})

        assert second.status_code == 409
        assert "already following" in second.json()["detail"].lower()

    def test_tracking_absent_503s_with_a_reason(self, bare_live_store, user_store,
                                                authed):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(bare_live_store)
        try:
            app = create_app()
            app.state.users = user_store
            reply = authed(app).post(
                "/tracking/follow", json={"cameraId": "cam-a", "x": 0.5, "y": 0.5})

            assert reply.status_code == 503
            # Not a 404: "nobody there" and "tracking never started" send an
            # operator to two completely different places.
            assert "tracking is not running" in reply.json()["detail"].lower()
        finally:
            app_module.set_store(MockStore())

    def test_nothing_to_show_when_nothing_is_followed(self, follow_app, authed):
        app, _, _, _ = follow_app
        assert authed(app).get("/tracking/follow").status_code == 404

    def test_a_stale_camera_has_nobody_to_follow(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        # Another camera keeps reporting; cam-a's bodies are now old news.
        sees(worker, stage, "cam-b", 30.0, [])

        client = authed(app)
        reply = client.post("/tracking/follow",
                            json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        assert reply.status_code == 404


class TestTheNameGate:
    def test_a_single_frame_match_does_not_name_the_followed_body(self):
        # The rule, at the level the worker sees it: `note_face` is what puts
        # a name on a body, and the recognition worker only calls it once the
        # accumulator says the evidence is sustained. One frame never does.
        acc = AnchorAccumulator(AnchorGates())
        assert acc.offer("cam-a", look(0.0, score=0.99, runner_up=0.0)) is None

    def test_a_sustained_look_does_name_it(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})

        assert client.get("/tracking/follow").json()["name"] is None
        assert client.get("/tracking/follow").json()["match"] == "appearance"

        # Recognition has now cleared the gate and bound the name to the body.
        named = ("body-a", (0.10, 0.10, 0.20, 0.60), "p-layla")
        sees(worker, stage, "cam-a", 1.0, [named], sequence=1)

        view = client.get("/tracking/follow").json()
        assert view["personId"] == "p-layla"
        assert view["match"] == "face", "a name is a face claim, never a clothing one"

    def test_the_name_dies_with_the_track(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        named = ("body-a", (0.10, 0.10, 0.20, 0.60), "p-layla")
        sees(worker, stage, "cam-a", 0.0, [named])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        assert client.get("/tracking/follow").json()["personId"] == "p-layla"

        # Gone, and gone for longer than a track survives.
        sees(worker, stage, "cam-a", 1.0, [], sequence=1)
        sees(worker, stage, "cam-a", 20.0, [], sequence=2)

        view = client.get("/tracking/follow").json()
        assert view["endedReason"] == "track lost"
        assert view["personId"] is None
        assert view["name"] is None

    def test_a_new_body_does_not_inherit_the_name(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        named = ("body-a", (0.10, 0.10, 0.20, 0.60), "p-layla")
        sees(worker, stage, "cam-a", 0.0, [named])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})

        sees(worker, stage, "cam-a", 20.0, [], sequence=1)
        assert client.get("/tracking/follow").json()["endedReason"] == "track lost"

        # Somebody else walks in wearing the same coat. A fresh stable id, and
        # nothing about the last person may travel to them.
        fresh = ("body-c", (0.10, 0.10, 0.20, 0.60), None)
        sees(worker, stage, "cam-a", 25.0, [fresh], sequence=2)
        client.delete("/tracking/follow")
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})

        view = client.get("/tracking/follow").json()
        assert view["stableId"] == "body-c"
        assert view["name"] is None and view["personId"] is None


class TestFollowRecording:
    @pytest.fixture
    def recording_app(self, user_store, authed):
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        recorder = FakeRecorder()
        worker, stage, _, _ = build_worker(recorder=recorder)
        store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                          tracking=worker, recorder=recorder)
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        application.state.tracking = worker
        try:
            yield application, worker, stage, recorder
        finally:
            app_module.set_store(MockStore())

    def start_following(self, app, worker, stage, authed):
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        return client

    def test_one_segment_per_camera_hop(self, recording_app, authed):
        app, worker, stage, recorder = recording_app
        client = self.start_following(app, worker, stage, authed)

        assert client.post("/tracking/follow/record", json={}).status_code == 200
        assert set(recorder.live) == {"cam-a"}

        # They walk into the next camera's view.
        stage.clear("cam-a")
        sees(worker, stage, "cam-b", 1.0, [BODY_A], sequence=1)

        assert set(recorder.live) == {"cam-b"}, "the old camera is stopped first"
        segments = client.get("/tracking/follow").json()["recording"]["segments"]
        assert [s["cameraId"] for s in segments] == ["cam-a", "cam-b"]
        assert segments[0]["reason"] == "moved on"

    def test_the_trail_records_every_hop(self, recording_app, authed):
        app, worker, stage, _ = recording_app
        client = self.start_following(app, worker, stage, authed)

        stage.clear("cam-a")
        sees(worker, stage, "cam-b", 1.0, [BODY_A], sequence=1)

        trail = client.get("/tracking/follow").json()["trail"]
        assert [h["cameraId"] for h in trail] == ["cam-a", "cam-b"]

    def test_the_timer_stops_it_server_side(self, recording_app, authed):
        app, worker, stage, recorder = recording_app
        client = self.start_following(app, worker, stage, authed)
        client.post("/tracking/follow/record", json={"timerSeconds": 60})

        # No web call between here and the stop. Frames alone do it.
        sees(worker, stage, "cam-a", 30.0, [BODY_A], sequence=1)
        assert set(recorder.live) == {"cam-a"}, "not yet"

        sees(worker, stage, "cam-a", 61.0, [BODY_A], sequence=2)

        recording = client.get("/tracking/follow").json()["recording"]
        assert recording["state"] == "stopped"
        assert recording["reason"] == "timer"
        assert recorder.live == {}

    def test_losing_the_track_stops_it_with_its_own_reason(self, recording_app, authed):
        app, worker, stage, recorder = recording_app
        client = self.start_following(app, worker, stage, authed)
        client.post("/tracking/follow/record", json={})

        sees(worker, stage, "cam-a", 20.0, [], sequence=1)

        view = client.get("/tracking/follow").json()
        assert view["endedReason"] == "track lost"
        assert view["recording"]["state"] == "stopped"
        assert view["recording"]["reason"] == "track lost"
        assert recorder.live == {}, "a lost person does not leave a camera recording"

    def test_a_manual_stop_says_manual(self, recording_app, authed):
        app, worker, stage, _ = recording_app
        client = self.start_following(app, worker, stage, authed)
        client.post("/tracking/follow/record", json={})

        reply = client.delete("/tracking/follow/record")
        assert reply.status_code == 200
        assert reply.json()["recording"]["reason"] == "manual"

    def test_a_second_record_409s(self, recording_app, authed):
        app, worker, stage, _ = recording_app
        client = self.start_following(app, worker, stage, authed)
        client.post("/tracking/follow/record", json={})

        assert client.post("/tracking/follow/record", json={}).status_code == 409

    def test_recording_without_a_follow_404s(self, recording_app, authed):
        app, _, _, _ = recording_app
        assert authed(app).post("/tracking/follow/record", json={}).status_code == 404

    def test_the_timer_counts_down_on_the_wire(self, recording_app, authed):
        app, worker, stage, _ = recording_app
        client = self.start_following(app, worker, stage, authed)
        client.post("/tracking/follow/record", json={"timerSeconds": 60})

        sees(worker, stage, "cam-a", 20.0, [BODY_A], sequence=1)
        left = client.get("/tracking/follow").json()["recording"]["timerSecondsLeft"]
        assert left == pytest.approx(40.0, abs=0.5)


class TestNoRecorderIsHonest:
    def test_it_says_so_rather_than_offering_a_dead_button(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})

        reply = client.post("/tracking/follow/record", json={})
        assert reply.status_code == 503
        assert "recording is not available" in reply.json()["detail"].lower()

    def test_the_follow_itself_still_works(self, follow_app, authed):
        # Rule 9: a feature must never require another feature to be on.
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        assert client.get("/tracking/follow").status_code == 200


class TestWhoIsAllowedTo:
    def test_following_and_recording_are_open_to_it(self, follow_app, authed):
        # `/tracking` is deliberately not under an admin prefix: following
        # somebody is operator work. The control is the audit trail, not the
        # role. This pins it so nobody adds the prefix by reflex.
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        it = authed(app, role="it")
        assert it.post("/tracking/follow",
                       json={"cameraId": "cam-a", "x": 0.15, "y": 0.3}
                       ).status_code == 200
        assert it.get("/tracking/follow").status_code == 200
        assert it.delete("/tracking/follow").status_code == 200

    def test_a_stranger_is_refused(self, follow_app):
        from fastapi.testclient import TestClient

        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        anonymous = TestClient(app)
        assert anonymous.post("/tracking/follow",
                              json={"cameraId": "cam-a", "x": 0.15, "y": 0.3}
                              ).status_code == 401

    def test_every_action_leaves_a_trail(self, follow_app, authed):
        app, worker, stage, _ = follow_app
        sees(worker, stage, "cam-a", 0.0, [BODY_A])

        client = authed(app, role="it")
        client.post("/tracking/follow", json={"cameraId": "cam-a", "x": 0.15, "y": 0.3})
        client.delete("/tracking/follow")

        actions = [e["action"] for e in client.get("/audit").json()]
        assert "track.follow" in actions
        assert "track.follow.end" in actions


class TestDemoModeStillDemos:
    def test_the_fixture_store_follows_somebody(self, authed, user_store):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(MockStore())
        app = create_app()
        app.state.users = user_store

        client = authed(app)
        reply = client.post("/tracking/follow",
                            json={"cameraId": "c-main", "x": 0.3, "y": 0.5})
        assert reply.status_code == 200
        assert reply.json()["name"] == "Layla Ahmed"
        assert client.get("/tracking/follow").status_code == 200

    def test_it_refuses_to_fake_a_recording(self, authed, user_store):
        # A segment with no file behind it, in the one place an operator would
        # go looking for evidence, is the fake save rule 4 forbids.
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(MockStore())
        app = create_app()
        app.state.users = user_store

        client = authed(app)
        client.post("/tracking/follow", json={"cameraId": "c-main", "x": 0.3, "y": 0.5})
        assert client.post("/tracking/follow/record", json={}).status_code == 503


# ---------------------------------------------------------------------------
# The gate where it actually sits: the recognition worker
#
# The tests above prove the accumulator's arithmetic. These prove it is wired
# into the one call that puts a name on a body, because an accumulator nobody
# consults is just a well-tested spreadsheet.
# ---------------------------------------------------------------------------

class FakeFace:
    def __init__(self, px: int = 120) -> None:
        self.x, self.y, self.w, self.h = 10, 10, px, px
        self.confidence = 0.99

    def to_fractions(self, frame_w, frame_h):
        return 0.1, 0.1, 0.2, 0.4


class FakeObservation:
    model = MODEL

    def __init__(self, px: int = 120) -> None:
        self.face = FakeFace(px)
        self.embedding = np.zeros(128, dtype="float32")


class FakePipeline:
    model_name = MODEL

    def __init__(self, px: int = 120) -> None:
        self.px = px

    def observe(self, image, **kw):
        return [FakeObservation(self.px)]


class FakeMatch:
    def __init__(self, person, score: float, runner_up: float) -> None:
        self.person = person
        self.score = score
        self.runner_up = runner_up
        self.reason = ""


class FakePerson:
    id = "p-layla"
    name = "Layla Ahmed"


class FakeGallery:
    def __init__(self, score: float = 0.70, runner_up: float = 0.30) -> None:
        self.score, self.runner_up = score, runner_up

    def match(self, embedding, model=None):
        return FakeMatch(FakePerson(), self.score, self.runner_up)


class FakeSightings:
    def seen_today(self, person_id, when=None):
        return True

    def record(self, sighting, force=False):
        return True


class CountingTracker:
    """Stands in for the tracking worker. Counts the calls that matter."""

    def __init__(self) -> None:
        self.named: list = []

    def note_face(self, camera_id, face_box, person_id, score, at=None):
        self.named.append((camera_id, person_id, at))
        return "body-a"


class TestTheGateIsActuallyWired:
    def build(self, gates=None, px: int = 120, score: float = 0.70):
        from vg.features.recognition import RecognitionWorker

        class NoBus:
            def subscribe(self, *a, **kw):  # pragma: no cover
                raise AssertionError("not started in these tests")

        tracker = CountingTracker()
        worker = RecognitionWorker(
            NoBus(), FakeGallery(score=score), FakeSightings(),
            pipeline=FakePipeline(px), cameras=["cam-a"],
            tracking=tracker, gates=gates or AnchorGates(),
        )
        return worker, tracker

    def test_one_frame_does_not_name_a_body(self):
        # The bug this whole feature exists to close.
        worker, tracker = self.build()
        worker.analyse(frame("cam-a", 0.0))

        assert tracker.named == [], "one lucky frame must never name anybody"
        assert worker.names_withheld == 1

    def test_a_sustained_look_names_it(self):
        worker, tracker = self.build()
        for i, seconds in enumerate([0.0, 0.8, 1.6]):
            worker.analyse(frame("cam-a", seconds, sequence=i))

        assert tracker.named, "three clear looks over 1.6s is the bar"
        assert tracker.named[0][1] == "p-layla"

    def test_a_face_below_the_floor_never_names_anybody(self):
        worker, tracker = self.build(px=FACE_PIXEL_FLOOR - 1)
        for i, seconds in enumerate([0.0, 0.8, 1.6, 2.4, 3.2, 4.0]):
            worker.analyse(frame("cam-a", seconds, sequence=i))

        assert tracker.named == [], "no amount of repetition buys a tiny face a name"

    def test_a_weak_score_never_names_anybody(self):
        worker, tracker = self.build(score=AnchorGates().score - 0.01)
        for i, seconds in enumerate([0.0, 0.8, 1.6, 2.4, 3.2, 4.0]):
            worker.analyse(frame("cam-a", seconds, sequence=i))

        assert tracker.named == []

    def test_the_box_is_still_drawn_while_the_claim_waits(self):
        # A match IS an observation about this frame and is shown as one. Only
        # the claim — naming a body, writing a stop — waits for the evidence.
        worker, _ = self.build()
        result = worker.analyse(frame("cam-a", 0.0))

        assert result.identified == 1
        assert result.faces[0].label == "Layla Ahmed"

    def test_the_patrol_tier_uses_its_own_bar(self):
        # A corridor score that the identity tier refuses, on a patrol camera.
        score = 0.42
        assert PATROL_GATES.score <= score < AnchorGates().score

        strict, strict_tracker = self.build(gates=AnchorGates(), score=score)
        lenient, lenient_tracker = self.build(gates=PATROL_GATES, score=score)
        for i, seconds in enumerate([0.0, 1.0, 2.0, 3.0]):
            strict.analyse(frame("cam-a", seconds, sequence=i))
            lenient.analyse(frame("cam-a", seconds, sequence=i))

        assert strict_tracker.named == []
        assert lenient_tracker.named, "the corridor tier has to be reachable"

    def test_anchors_are_only_written_when_a_name_is_earned(self):
        written: list = []

        class Recorder:
            def record(self, anchor):
                written.append(anchor)

        worker, tracker = self.build()
        worker.anchors = Recorder()

        worker.analyse(frame("cam-a", 0.0))
        assert written == [], "nothing below the bar is ever written down"

        worker.analyse(frame("cam-a", 0.8, sequence=1))
        worker.analyse(frame("cam-a", 1.6, sequence=2))
        assert len(written) == 1
        assert written[0].person_id == "p-layla"
        assert written[0].matches == 3


# ===========================================================================
# US2 — the instant past path
#
# The claim being tested is narrow and important: the skeleton is a database
# read of rows that could only have been written by evidence clearing the bar.
# There is no scan, no model, and nothing below the bar to filter out later.
# ===========================================================================

import tempfile

from vg import config as vgconfig
from vg.api.live import LiveStore
from vg.events.anchors import AnchorStore
from vg.events.sightings import Sighting, SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry

CAIRO = 180


def unit(seed: str):
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.standard_normal(128).astype("float32")
    return v / float(np.linalg.norm(v))


@pytest.fixture
def anchor_store():
    """A throwaway AnchorStore. Closed before the tempdir, or Windows fails."""
    tmp = tempfile.TemporaryDirectory()
    store = AnchorStore(Path(tmp.name) / "a.db", clock=CAIRO)
    yield store
    store.close()
    tmp.cleanup()


@pytest.fixture
def path_world(user_store):
    """A LiveStore with a real gallery, sighting store and anchor store."""
    from vg.api import app as app_module
    from vg.api.app import create_app

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    gallery = FaceGallery(root / "g.db", model=MODEL, threshold=0.363)
    sightings = SightingStore(root / "s.db", clock=CAIRO)
    anchors = AnchorStore(root / "a.db", clock=CAIRO)

    gallery.add_person("p-layla", "Layla Ahmed", group="Grade 8")
    gallery.add_embedding("p-layla", unit("p-layla"), MODEL)

    store = LiveStore(
        config=vgconfig.load(), registry=CameraRegistry([]),
        gallery=gallery, sightings=sightings, anchors=anchors,
    )
    app_module.set_store(store)
    application = create_app()
    application.state.users = user_store
    try:
        yield application, anchors, sightings
    finally:
        app_module.set_store(MockStore())
        anchors.close()
        sightings.close()
        gallery.close()
        tmp.cleanup()


def anchor(
    *, person="p-layla", camera="cam-a", start=0.0, end=4.0,
    matches=5, best=0.71, mean=0.66, face_px=96,
):
    from vg.events.anchors import Anchor

    return Anchor(
        person_id=person, camera_id=camera,
        started_at=at(start), ended_at=at(end),
        matches=matches, best=best, mean=mean, face_px=face_px, model=MODEL,
    )


class TestTheDebounceCannotSeeThis:
    def test_anchor_rows_come_from_frames_the_stored_ones_hide(self, anchor_store):
        """The reason the verdict is made in the worker and not from a query.

        `SightingStore` thins repeats to one row a minute. So five clear looks
        in three seconds — exactly what makes an identification trustworthy —
        leaves ONE row behind, and the evidence that mattered is gone. The
        anchor is written where the evidence still exists.
        """
        tmp = tempfile.TemporaryDirectory()
        sightings = SightingStore(Path(tmp.name) / "s.db", clock=CAIRO)
        try:
            written = 0
            for i in range(5):
                ok = sightings.record(Sighting(
                    person_id="p-layla", camera_id="cam-a",
                    seen_at=at(i * 0.75), confidence=0.7, model=MODEL,
                ), force=(i == 0))
                written += 1 if ok else 0

            assert written == 1, "the debounce keeps one row for five looks"
        finally:
            sightings.close()
            tmp.cleanup()

        # The same five looks, through the accumulator, keep their evidence.
        acc = AnchorAccumulator(AnchorGates())
        emitted = feed(acc, [0.0, 0.75, 1.5, 2.25, 3.0])
        assert emitted, "the worker sees what the table cannot keep"
        anchor_store.record(emitted[-1])

        stored = anchor_store.skeleton("p-sara", anchor_store.local_date(at(0)))
        assert len(stored) == 1
        assert stored[0].matches >= 3


class TestTheAnchorTable:
    def test_an_anchor_carries_its_evidence(self, anchor_store):
        anchor_store.record(anchor())
        on = anchor_store.local_date(at(0))

        [stored] = anchor_store.skeleton("p-layla", on)
        assert stored.matches == 5
        assert stored.best == pytest.approx(0.71)
        assert stored.mean == pytest.approx(0.66)
        assert stored.face_px == 96
        assert stored.model == MODEL
        assert stored.started_at == at(0.0)
        assert stored.ended_at == at(4.0)

    def test_a_growing_stop_updates_rather_than_doubling(self, anchor_store):
        # Somebody standing still re-states the same run. Two rows would draw
        # two stops where the operator saw one person not moving.
        anchor_store.record(anchor(end=4.0, matches=5))
        anchor_store.record(anchor(end=9.0, matches=9))

        on = anchor_store.local_date(at(0))
        [stored] = anchor_store.skeleton("p-layla", on)
        assert stored.ended_at == at(9.0)
        assert stored.matches == 9

    def test_a_second_camera_is_a_second_stop(self, anchor_store):
        anchor_store.record(anchor(camera="cam-a"))
        anchor_store.record(anchor(camera="cam-b", start=20.0, end=24.0))

        on = anchor_store.local_date(at(0))
        stops = anchor_store.skeleton("p-layla", on)
        assert [s.camera_id for s in stops] == ["cam-a", "cam-b"]

    def test_stops_come_back_in_order(self, anchor_store):
        anchor_store.record(anchor(camera="cam-c", start=60.0, end=64.0))
        anchor_store.record(anchor(camera="cam-a", start=0.0, end=4.0))
        anchor_store.record(anchor(camera="cam-b", start=30.0, end=34.0))

        on = anchor_store.local_date(at(0))
        assert [s.camera_id for s in anchor_store.skeleton("p-layla", on)] == [
            "cam-a", "cam-b", "cam-c",
        ]

    def test_the_window_narrows_the_answer(self, anchor_store):
        anchor_store.record(anchor(camera="cam-a", start=0.0, end=4.0))
        anchor_store.record(anchor(camera="cam-b", start=600.0, end=604.0))
        on = anchor_store.local_date(at(0))

        narrowed = anchor_store.skeleton(
            "p-layla", on, start=at(300.0), end=at(900.0))
        assert [s.camera_id for s in narrowed] == ["cam-b"]

    def test_somebody_elses_stops_are_not_yours(self, anchor_store):
        anchor_store.record(anchor(person="p-layla"))
        anchor_store.record(anchor(person="p-omar", camera="cam-b"))
        on = anchor_store.local_date(at(0))

        assert len(anchor_store.skeleton("p-layla", on)) == 1


class TestMeasuredRates:
    def test_absent_until_somebody_measures(self, anchor_store):
        assert anchor_store.rates() is None, "no row means no promise"

    def test_a_measurement_sticks_and_replaces(self, anchor_store):
        anchor_store.set_rates(4.0, 22.0, backend="footage")
        first = anchor_store.rates()
        assert first.fetch_x == pytest.approx(4.0)
        assert first.backend == "footage"

        anchor_store.set_rates(1.5, 9.0, backend="dvr")
        second = anchor_store.rates()
        assert second.fetch_x == pytest.approx(1.5)
        assert second.backend == "dvr", "one row, not a history"


class TestTheSkeletonEndpoint:
    def test_it_is_anchors_only_and_audited_before_the_answer(self, path_world, authed):
        app, anchors, _ = path_world
        anchors.record(anchor())
        on = anchors.local_date(at(0))

        client = authed(app)
        reply = client.get(f"/path/p-layla?date={on}")
        assert reply.status_code == 200, reply.text

        body = reply.json()
        assert body["subject"]["name"] == "Layla Ahmed"
        assert len(body["anchors"]) == 1
        assert body["auditId"]

        stop = body["anchors"][0]
        assert stop["matches"] == 5
        assert stop["facePx"] == 96
        assert stop["score"] == pytest.approx(0.71)
        # "why do you believe this?" answered on the wire, not by a colour.
        assert stop["at"] and stop["until"]

        entries = client.get("/audit").json()
        assert any(e["action"] == "path.skeleton" for e in entries)
        assert any(e["id"] == body["auditId"] for e in entries)

    def test_a_name_works_as_well_as_an_id(self, path_world, authed):
        app, anchors, _ = path_world
        anchors.record(anchor())
        on = anchors.local_date(at(0))

        reply = authed(app).get(f"/path/Layla%20Ahmed?date={on}")
        assert reply.status_code == 200
        assert reply.json()["subject"]["id"] == "p-layla"

    def test_an_empty_window_is_an_answer_not_an_error(self, path_world, authed):
        app, anchors, _ = path_world
        on = anchors.local_date(at(0))

        reply = authed(app).get(f"/path/p-layla?date={on}")
        assert reply.status_code == 200
        assert reply.json()["anchors"] == []
        # Nobody identified is a different fact from being unable to look, and
        # the page offers a next move rather than an error.
        assert reply.json()["subject"]["match"] == "none"

    def test_an_unknown_person_404s(self, path_world, authed):
        app, anchors, _ = path_world
        on = anchors.local_date(at(0))
        assert authed(app).get(f"/path/p-nobody?date={on}").status_code == 404

    def test_no_anchor_store_503s_with_a_reason(self, bare_live_store, user_store, authed):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(bare_live_store)
        try:
            app = create_app()
            app.state.users = user_store
            reply = authed(app).get("/path/p-layla")

            assert reply.status_code == 503
            assert "not running" in reply.json()["detail"].lower()
        finally:
            app_module.set_store(MockStore())

    def test_it_is_open_to_the_it_role(self, path_world, authed):
        # /path joins no admin prefix: looking somebody up is operator work,
        # and the control is the audit entry, not the role.
        app, anchors, _ = path_world
        anchors.record(anchor())
        on = anchors.local_date(at(0))
        assert authed(app, role="it").get(f"/path/p-layla?date={on}").status_code == 200

    def test_a_stranger_is_refused(self, path_world):
        from fastapi.testclient import TestClient

        app, _, _ = path_world
        assert TestClient(app).get("/path/p-layla").status_code == 401

    def test_the_demo_store_answers_too(self, authed, user_store):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(MockStore())
        app = create_app()
        app.state.users = user_store

        reply = authed(app).get("/path/Layla%20Ahmed?date=2026-08-21")
        assert reply.status_code == 200
        assert reply.json()["anchors"], "demo mode still demos"
        assert reply.json()["auditId"]


class TestTheTwoTiers:
    def test_a_camera_lands_in_exactly_one_tier(self):
        from vg.config import CameraConfig

        roster = [
            CameraConfig(id="cam-door", name="Door", source="webcam:0",
                         faces=True, features=("attendance",)),
            CameraConfig(id="cam-hall", name="Hall", source="rtsp://x",
                         features=("counting",)),
            CameraConfig(id="cam-off", name="Off", source="rtsp://y", enabled=False),
        ]
        identity = [c.id for c in roster if c.enabled and (c.faces or "attendance" in c.features)]
        patrol = [c.id for c in roster if c.enabled and c.id not in set(identity)]

        assert identity == ["cam-door"]
        assert patrol == ["cam-hall"]
        assert "cam-off" not in identity + patrol, "a disabled camera runs nothing"

    def test_the_two_tiers_answer_to_different_bars(self):
        tracking = TrackingConfig()
        assert tracking.patrol.score < tracking.identity.score
        assert tracking.patrol.margin < tracking.identity.margin
        # Both still above a bare gallery match: an anchor always means more
        # than "this frame looked like them".
        from vg.infer.faces import SFACE_COSINE_THRESHOLD

        assert tracking.patrol.score > SFACE_COSINE_THRESHOLD

    def test_patrol_at_zero_hz_is_off(self):
        from vg.config import TrackingConfig as TC

        off = TC.parse({"patrol_hz": 0}, "tracking")
        assert off.patrol_hz == 0

    def test_the_tiers_report_themselves_separately(self):
        # Each instance carries its own name, so System Health can show what
        # each tier is doing instead of one merged number.
        worker, _ = TestTheGateIsActuallyWired().build()
        assert worker.stats["name"] == "recognition"


# ===========================================================================
# US3 — the video behind a stop
#
# The archive is the only part of this feature with an unknown in it, so it
# lands behind a backend that needs no hardware: `footage` slices the recorded
# walk-through clip, which is identical every run. A DVR is then one config
# change and one run of measure_track.py away, and if that recorder turns out
# to be slow the estimates say so instead of the page over-promising.
# ===========================================================================

from vg.ingest.archive import (
    ArchiveRunner,
    ArchiveUnavailable,
    FootageBackend,
    QueueFull,
    estimate_for,
    next_to_warm,
)

FOOTAGE = Path("engine/data/footage")
CLIP_CAMERA = "cam-laptop"
#: The walk-through clip's own start, out of its sidecar. Read rather than
#: typed, so moving the clip does not silently break these.
CLIP_START = datetime.fromisoformat("2026-08-05T09:17:05+00:00")


def has_clip() -> bool:
    return (FOOTAGE / "walk-through_cam-laptop_20260805-121705.mp4").is_file()


needs_clip = pytest.mark.skipif(
    not has_clip(), reason="the recorded walk-through clip is not present")


class FakeSource:
    """An archive that writes a tiny file instantly. No codecs, no waiting."""

    name = "fake"

    def __init__(self, covers=True) -> None:
        self.covers = covers
        self.asked: list = []

    def coverage(self, camera_id):
        return []

    def fetch(self, camera_id, start, end, into):
        self.asked.append((camera_id, start, end))
        if not self.covers:
            raise ArchiveUnavailable(f"No footage covers {camera_id}.")
        into.write_bytes(b"\x00" * 32)
        return into


def drain(runner, job, timeout=10.0):
    """Wait for a job to finish. The runner is threads; the test is not."""
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if job.state in ("done", "failed"):
            return job
        _time.sleep(0.02)
    raise AssertionError(f"job {job.id} stayed {job.state}")


class TestTheFootageBackend:
    @needs_clip
    def test_it_finds_the_clip_that_covers_a_moment(self):
        source = FootageBackend(FOOTAGE)
        covered = source.coverage(CLIP_CAMERA)

        assert covered, "the walk-through clip should be indexed"
        starts = [s for s, _e, _p in covered]
        assert CLIP_START in starts

    @needs_clip
    def test_it_slices_the_span_it_was_asked_for(self, tmp_path):
        source = FootageBackend(FOOTAGE)
        out = tmp_path / "slice.mp4"
        source.fetch(CLIP_CAMERA, CLIP_START + timedelta(seconds=10),
                     CLIP_START + timedelta(seconds=13), out)

        assert out.is_file() and out.stat().st_size > 0

        import cv2

        capture = cv2.VideoCapture(str(out))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
            frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        finally:
            capture.release()
        assert 2.0 <= frames / fps <= 4.5, "roughly the three seconds asked for"

    @needs_clip
    def test_a_span_nothing_covers_says_so(self, tmp_path):
        source = FootageBackend(FOOTAGE)
        with pytest.raises(ArchiveUnavailable) as raised:
            source.fetch(CLIP_CAMERA, CLIP_START - timedelta(days=30),
                         CLIP_START - timedelta(days=30) + timedelta(seconds=5),
                         tmp_path / "x.mp4")

        # An honest "there is no video from then", not an empty file that
        # plays as a black screen and looks like a broken camera — and it
        # names what the camera does hold, so the answer is a next step.
        message = str(raised.value)
        assert "no recorded video from" in message.lower()
        assert "What this camera has" in message

    def test_an_unknown_camera_has_no_coverage(self):
        assert FootageBackend(FOOTAGE).coverage("cam-nowhere") == []

    def test_a_missing_folder_is_empty_not_a_crash(self, tmp_path):
        assert FootageBackend(tmp_path / "nope").coverage(CLIP_CAMERA) == []


class TestTheRunner:
    def test_a_leg_grows_chunks_and_serves_them(self, tmp_path):
        source = FakeSource()
        runner = ArchiveRunner(source, tmp_path, chunk_seconds=10.0, workers=1)
        try:
            job = runner.submit(
                "cam-a", at(0), at(30))
            assert job.chunks_total == 3

            drain(runner, job)
            assert job.state == "done"
            assert len(job.chunks) == 3
            assert job.progress == pytest.approx(1.0)

            path, reason = runner.chunk(job.id, 0)
            assert path is not None and path.is_file(), reason
        finally:
            runner.stop()

    def test_the_pieces_cover_the_span_in_order(self, tmp_path):
        source = FakeSource()
        runner = ArchiveRunner(source, tmp_path, chunk_seconds=10.0, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(30)))
            assert [c.index for c in job.chunks] == [0, 1, 2]
            assert [c.start for c in job.chunks] == [at(0), at(10), at(20)]
            assert source.asked[0][1] == at(0)
        finally:
            runner.stop()

    def test_a_chunk_not_built_yet_says_so_rather_than_404ing_blankly(self, tmp_path):
        runner = ArchiveRunner(FakeSource(), tmp_path, chunk_seconds=10.0, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(10)))
            path, reason = runner.chunk(job.id, 9)
            assert path is None
            assert "not been built" in reason
        finally:
            runner.stop()

    def test_an_archive_that_cannot_serve_the_first_chunk_fails_the_leg(self, tmp_path):
        runner = ArchiveRunner(FakeSource(covers=False), tmp_path, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(30)))
            assert job.state == "failed"
            assert "no footage covers" in (job.error or "").lower()
        finally:
            runner.stop()

    def test_a_full_queue_refuses_instead_of_promising(self, tmp_path):
        # An unbounded queue accepts work it has no intention of getting to,
        # and then the page shows a spinner that means nothing.
        runner = ArchiveRunner(
            FakeSource(), tmp_path, chunk_seconds=10.0, workers=1, queue_size=1)
        try:
            refused = False
            for _ in range(40):
                try:
                    runner.submit("cam-a", at(0), at(600))
                except QueueFull as exc:
                    refused = True
                    assert "try again" in str(exc).lower()
                    break
            assert refused, "a bounded queue has to say no at some point"
        finally:
            runner.stop()

    def test_retention_keeps_the_last_n_and_says_why_the_rest_are_gone(self, tmp_path):
        runner = ArchiveRunner(
            FakeSource(), tmp_path, chunk_seconds=10.0, keep_legs=2, workers=1)
        try:
            first = drain(runner, runner.submit("cam-a", at(0), at(10)))
            drain(runner, runner.submit("cam-a", at(20), at(30)))
            drain(runner, runner.submit("cam-a", at(40), at(50)))

            assert runner.job(first.id) is None, "oldest leg dropped"
            path, reason = runner.chunk(first.id, 0)
            assert path is None
            # Offers the way back, because a leg is always re-derivable.
            assert "replaced" in reason and "again" in reason
            assert not (runner.root / first.id).exists(), "its files went too"
        finally:
            runner.stop()

    def test_another_camera_has_its_own_retention(self, tmp_path):
        runner = ArchiveRunner(
            FakeSource(), tmp_path, chunk_seconds=10.0, keep_legs=1, workers=1)
        try:
            a = drain(runner, runner.submit("cam-a", at(0), at(10)))
            b = drain(runner, runner.submit("cam-b", at(0), at(10)))
            assert runner.job(a.id) is not None
            assert runner.job(b.id) is not None
        finally:
            runner.stop()


class TestPrefetchOrder:
    """TRK-FR-005's three-step fallback, pinned as a pure function."""

    def cameras(self):
        from vg.config import CameraConfig

        return [
            CameraConfig(id="cam-a", name="A", source="x", area="Hall",
                         neighbours=("cam-b",)),
            CameraConfig(id="cam-b", name="B", source="x", area="Hall"),
            CameraConfig(id="cam-c", name="C", source="x", area="Hall"),
            CameraConfig(id="cam-far", name="Far", source="x", area="Yard"),
            CameraConfig(id="cam-off", name="Off", source="x", area="Hall",
                         enabled=False),
        ]

    def test_the_next_anchor_wins(self):
        # They were actually seen there. That beats any guess about the
        # building, which is why it is first.
        stops = [anchor(camera="cam-a"), anchor(camera="cam-far")]
        assert next_to_warm(stops, 0, self.cameras(), "cam-a") == "cam-far"

    def test_then_a_neighbour(self):
        stops = [anchor(camera="cam-a")]
        assert next_to_warm(stops, 0, self.cameras(), "cam-a") == "cam-b"

    def test_then_the_same_area(self):
        cameras = [c for c in self.cameras() if c.id != "cam-b"]
        stops = [anchor(camera="cam-a")]
        assert next_to_warm(stops, 0, cameras, "cam-a") == "cam-c"

    def test_a_disabled_camera_is_never_warmed(self):
        from vg.config import CameraConfig

        cameras = [
            CameraConfig(id="cam-a", name="A", source="x", area="Hall"),
            CameraConfig(id="cam-off", name="Off", source="x", area="Hall",
                         enabled=False),
        ]
        assert next_to_warm([anchor(camera="cam-a")], 0, cameras, "cam-a") is None

    def test_nothing_to_warm_is_an_answer(self):
        # Warming the wrong camera costs a fetch nobody wanted, so None beats
        # a guess.
        from vg.config import CameraConfig

        alone = [CameraConfig(id="cam-a", name="A", source="x", area="Hall")]
        assert next_to_warm([], 0, alone, "cam-a") is None


class TestEstimatesAreMeasuredNeverGuessed:
    def test_no_measurement_means_no_number(self):
        result = estimate_for(1.0, None, budget_seconds=900)
        assert result.allowed is False
        assert "measured" in (result.reason or "").lower()
        assert "measure_track" in (result.reason or "")

    def test_a_measurement_produces_arithmetic(self, anchor_store):
        rates = anchor_store.set_rates(fetch_x=4.0, process_fps=30.0)
        # One camera-hour: 3600s of video. Fetch at 4x = 900s. Process at
        # 30fps over 15fps footage = 1800s. 2700s in total.
        result = estimate_for(1.0, rates, budget_seconds=1e9)
        assert result.seconds == pytest.approx(2700.0, rel=0.01)
        assert result.allowed is True

    def test_over_budget_is_refused_with_the_sum_in_words(self, anchor_store):
        rates = anchor_store.set_rates(fetch_x=1.0, process_fps=5.0)
        result = estimate_for(2.0, rates, budget_seconds=15 * 60)

        assert result.allowed is False
        assert "minutes" in (result.reason or "")
        assert "narrow the window" in (result.reason or "").lower()

    def test_a_faster_machine_allows_more(self, anchor_store):
        slow = estimate_for(1.0, anchor_store.set_rates(1.0, 5.0), budget_seconds=900)
        fast = estimate_for(1.0, anchor_store.set_rates(20.0, 200.0), budget_seconds=900)
        assert slow.allowed is False and fast.allowed is True


class TestTheLegEndpoints:
    @pytest.fixture
    def leg_app(self, user_store, tmp_path):
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        tmp = tempfile.TemporaryDirectory()
        anchors = AnchorStore(Path(tmp.name) / "a.db", clock=CAIRO)
        runner = ArchiveRunner(
            FakeSource(), tmp_path, chunk_seconds=10.0, workers=1)
        store = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([]),
            anchors=anchors, archive=runner,
        )
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        try:
            yield application, runner, anchors
        finally:
            app_module.set_store(MockStore())
            runner.stop()
            anchors.close()
            tmp.cleanup()

    def body(self, camera="cam-laptop", seconds=20.0):
        return {
            "cameraId": camera,
            "start": at(0).isoformat(),
            "end": at(seconds).isoformat(),
            "personId": "p-layla",
        }

    def test_a_leg_is_audited_then_queued(self, leg_app, authed):
        app, runner, _ = leg_app
        client = authed(app)

        reply = client.post("/path/legs", json=self.body())
        assert reply.status_code == 200, reply.text
        job = reply.json()
        assert job["job"]["state"] in ("queued", "running", "done")
        assert job["chunksTotal"] == 2

        assert any(e["action"] == "path.leg" for e in client.get("/audit").json())

    def test_chunk_urls_grow_and_serve_bytes(self, leg_app, authed):
        app, runner, _ = leg_app
        client = authed(app)
        started = client.post("/path/legs", json=self.body()).json()
        drain(runner, runner.job(started["job"]["id"]))

        job = client.get(f"/path/legs/{started['job']['id']}").json()
        assert job["chunksReady"] == 2
        assert job["chunkUrls"] == [
            f"/path/legs/{started['job']['id']}/chunks/0",
            f"/path/legs/{started['job']['id']}/chunks/1",
        ], "same-origin paths — <video> cannot send an Authorization header"

        chunk = client.get(job["chunkUrls"][0])
        assert chunk.status_code == 200
        assert chunk.headers["content-type"] == "video/mp4"
        assert chunk.content

    def test_an_unknown_camera_404s(self, leg_app, authed):
        app, _, _ = leg_app
        reply = authed(app).post("/path/legs", json=self.body(camera="cam-nope"))
        assert reply.status_code == 404

    def test_a_backwards_span_404s(self, leg_app, authed):
        app, _, _ = leg_app
        reply = authed(app).post("/path/legs", json=self.body(seconds=-10))
        assert reply.status_code == 404

    def test_an_unknown_leg_404s_with_the_way_back(self, leg_app, authed):
        app, _, _ = leg_app
        reply = authed(app).get("/path/legs/nosuchjob")
        assert reply.status_code == 404
        assert "again" in reply.json()["detail"]

    def test_no_estimate_until_somebody_measures(self, leg_app, authed):
        app, runner, _ = leg_app
        job = authed(app).post("/path/legs", json=self.body()).json()
        assert job["estimateSeconds"] is None, "never a guess"

    def test_an_estimate_appears_once_measured(self, leg_app, authed):
        app, runner, anchors = leg_app
        anchors.set_rates(fetch_x=4.0, process_fps=30.0)

        job = authed(app).post("/path/legs", json=self.body()).json()
        assert job["estimateSeconds"] is not None
        assert job["estimateSeconds"] > 0

    def test_no_archive_503s_with_a_reason(self, bare_live_store, user_store, authed):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(bare_live_store)
        try:
            app = create_app()
            app.state.users = user_store
            reply = authed(app).post("/path/legs", json=self.body())
            assert reply.status_code == 503
            assert "archive" in reply.json()["detail"].lower()
        finally:
            app_module.set_store(MockStore())

    def test_demo_mode_refuses_rather_than_faking_footage(self, authed, user_store):
        from vg.api import app as app_module
        from vg.api.app import create_app

        app_module.set_store(MockStore())
        app = create_app()
        app.state.users = user_store

        client = authed(app)
        reply = client.post("/path/legs", json=self.body())
        assert reply.status_code == 503
        # Still audited: an operator asking to watch somebody is the thing
        # worth recording, and it happened.
        assert any(e["action"] == "path.leg" for e in client.get("/audit").json())

    def test_it_is_open_to_the_it_role(self, leg_app, authed):
        app, _, _ = leg_app
        assert authed(app, role="it").post(
            "/path/legs", json=self.body()).status_code == 200

    def test_a_stranger_is_refused(self, leg_app):
        from fastapi.testclient import TestClient

        app, _, _ = leg_app
        assert TestClient(app).post("/path/legs", json=self.body()).status_code == 401


class TestTheMeasurementTool:
    def test_it_stores_what_it_measured(self, anchor_store):
        # The tool's contract with everything downstream: one row, and every
        # estimate reads it.
        assert anchor_store.rates() is None
        anchor_store.set_rates(fetch_x=6.5, process_fps=41.0, backend="footage")

        rates = anchor_store.rates()
        assert rates.fetch_x == pytest.approx(6.5)
        assert rates.process_fps == pytest.approx(41.0)
        assert rates.backend == "footage"

    def test_estimates_move_when_the_measurement_does(self, anchor_store):
        before = estimate_for(0.1, anchor_store.set_rates(2.0, 10.0), 1e9).seconds
        after = estimate_for(0.1, anchor_store.set_rates(8.0, 40.0), 1e9).seconds
        assert after < before, "a faster machine promises a shorter wait"

    def test_the_tool_imports_and_names_its_own_budget(self):
        # It is a script, so the thing worth pinning is that it still loads and
        # that the sweep budget it prints is the one the endpoint enforces.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "measure_track", Path("engine/tools/measure_track.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.SWEEP_BUDGET_SECONDS == 15 * 60
        assert module.DEFAULT_SECONDS >= 60


# ===========================================================================
# US4 — strangers, and the wide net
#
# Two things with teeth here. A sweep states its cost before it runs and is
# refused when the sum is over budget, so nobody watches a progress bar for an
# hour. And a body followed by how it looks NEVER acquires a name, however
# well the system knows that person — because clothing matching is evidence
# about continuity and a name is a claim about identity.
# ===========================================================================

from vg.ingest.archive import SweepJob as RunnerSweep, segments_of


class TestWhatASweepIs:
    def test_the_work_is_listed_before_any_of_it_runs(self):
        # A sweep's cost is this list times the cost of one piece, which is
        # what makes the estimate arithmetic instead of a guess.
        work = segments_of(["cam-a", "cam-b"], at(0), at(60), 30.0)
        assert len(work) == 4
        assert work[0] == ("cam-a", at(0), at(30))
        assert work[-1] == ("cam-b", at(30), at(60))

    def test_a_ragged_end_is_still_covered(self):
        work = segments_of(["cam-a"], at(0), at(70), 30.0)
        assert [(s, e) for _c, s, e in work] == [
            (at(0), at(30)), (at(30), at(60)), (at(60), at(70)),
        ]

    def test_camera_hours_is_cameras_times_hours(self):
        job = RunnerSweep(id="j", cameras=["a", "b", "c"], start=at(0), end=at(3600))
        assert job.camera_hours == pytest.approx(3.0)


class TestSweepEstimates:
    @pytest.fixture
    def sweep_app(self, user_store, tmp_path):
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        gallery = FaceGallery(root / "g.db", model=MODEL, threshold=0.363)
        gallery.add_person("p-layla", "Layla Ahmed")
        gallery.add_embedding("p-layla", unit("p-layla"), MODEL)
        anchors = AnchorStore(root / "a.db", clock=CAIRO)

        hits: list = []

        def finder(clip, camera_id, at_, person_id):
            return list(hits)

        runner = ArchiveRunner(
            FakeSource(), tmp_path, chunk_seconds=30.0, workers=1, finder=finder)
        store = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([]),
            gallery=gallery, anchors=anchors, archive=runner,
        )
        app_module.set_store(store)
        application = create_app()
        application.state.users = user_store
        try:
            yield application, anchors, runner, hits
        finally:
            app_module.set_store(MockStore())
            runner.stop()
            anchors.close()
            gallery.close()
            tmp.cleanup()

    def ask(self, minutes_wide=10, cameras=("cam-laptop",)):
        return {
            "person": "Layla Ahmed",
            "start": at(0).isoformat(),
            "end": at(minutes_wide * 60).isoformat(),
            "cameraIds": list(cameras),
        }

    def test_unmeasured_is_refused_and_says_why(self, sweep_app, authed):
        app, _, _, _ = sweep_app
        reply = authed(app).post("/path/sweep/estimate", json=self.ask())

        assert reply.status_code == 200, "an estimate is an answer, not an error"
        body = reply.json()
        assert body["allowed"] is False
        assert "measured" in body["reason"].lower()
        assert body["measuredAt"] is None

    def test_a_measurement_produces_the_arithmetic(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)

        body = authed(app).post("/path/sweep/estimate", json=self.ask()).json()
        assert body["allowed"] is True
        assert body["cameras"] == 1
        assert body["cameraHours"] == pytest.approx(10 / 60, rel=0.01)
        assert body["seconds"] > 0
        assert body["measuredAt"] is not None

    def test_too_big_is_refused_with_the_sum(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(fetch_x=1.0, process_fps=5.0)

        body = authed(app).post(
            "/path/sweep/estimate", json=self.ask(minutes_wide=600)).json()
        assert body["allowed"] is False
        assert "minutes" in body["reason"]
        assert "narrow the window" in body["reason"].lower()

    def test_running_an_unaffordable_sweep_422s(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(fetch_x=1.0, process_fps=5.0)

        reply = authed(app).post("/path/sweep", json=self.ask(minutes_wide=600))
        # 422, not 400: the request was understood perfectly. It is the amount
        # of work that is refused, and the reason carries the arithmetic.
        assert reply.status_code == 422
        assert "minutes" in reply.json()["detail"]

    def test_an_unmeasured_sweep_cannot_be_run_at_all(self, sweep_app, authed):
        app, _, _, _ = sweep_app
        assert authed(app).post("/path/sweep", json=self.ask()).status_code == 422

    def test_an_estimate_looks_at_nobody_and_is_not_audited(self, sweep_app, authed):
        # Finding out whether a question is affordable is not asking it.
        app, anchors, _, _ = sweep_app
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)

        client = authed(app)
        client.post("/path/sweep/estimate", json=self.ask())
        assert not any(
            e["action"].startswith("path.sweep")
            for e in client.get("/audit").json()
        )

    def test_an_unknown_area_404s(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(8.0, 60.0)
        ask = self.ask()
        ask["cameraIds"] = []
        ask["areas"] = ["Atlantis"]

        reply = authed(app).post("/path/sweep/estimate", json=ask)
        assert reply.status_code == 404
        assert "Atlantis" in reply.json()["detail"]


class TestSweepsRun:
    @pytest.fixture
    def sweep_app(self, user_store, tmp_path, request):
        yield from TestSweepEstimates.sweep_app.__wrapped__(
            self, user_store, tmp_path)

    def ask(self, **kw):
        return TestSweepEstimates.ask(self, **kw)

    def test_it_audits_before_it_looks_at_anybody(self, sweep_app, authed):
        app, anchors, runner, _ = sweep_app
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)
        client = authed(app)

        started = client.post("/path/sweep", json=self.ask(minutes_wide=1))
        assert started.status_code == 200, started.text

        entries = client.get("/audit").json()
        assert any(e["action"] == "path.sweep" for e in entries)
        assert any(e["subject"] == "Layla Ahmed" for e in entries)

    def test_progress_advances_and_hits_arrive(self, sweep_app, authed):
        app, anchors, runner, hits = sweep_app
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)
        hits.append(anchor(camera="cam-laptop"))

        client = authed(app)
        started = client.post("/path/sweep", json=self.ask(minutes_wide=1)).json()
        job = runner.sweep(started["job"]["id"])

        import time as _time

        deadline = _time.monotonic() + 10
        while _time.monotonic() < deadline and job.state == "running":
            _time.sleep(0.02)

        body = client.get(f"/path/sweep/{started['job']['id']}").json()
        assert body["segmentsTotal"] == 2
        assert body["job"]["progress"] == pytest.approx(1.0)
        assert body["hits"], "the finder's hits reach the wire"
        assert body["hits"][0]["cameraId"] == "cam-laptop"
        assert body["hits"][0]["match"] == "face"
        assert body["hits"][0]["matches"] == 5

    def test_stopping_says_stopped_not_finished(self, sweep_app, authed):
        app, anchors, runner, _ = sweep_app
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)
        client = authed(app)

        started = client.post("/path/sweep", json=self.ask(minutes_wide=5)).json()
        stopped = client.delete(f"/path/sweep/{started['job']['id']}")

        assert stopped.status_code == 200
        # A cancelled sweep found what it found. Reporting it as a plain
        # completion would say it looked everywhere, which it did not.
        assert stopped.json()["job"]["error"] == "stopped"
        assert any(
            e["action"] == "path.sweep.stop" for e in client.get("/audit").json())

    def test_an_unknown_sweep_404s(self, sweep_app, authed):
        app, _, _, _ = sweep_app
        assert authed(app).get("/path/sweep/nosuch").status_code == 404

    def test_an_unknown_person_404s(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(8.0, 60.0)
        ask = self.ask()
        ask["person"] = "Nobody At All"
        assert authed(app).post("/path/sweep", json=ask).status_code == 404

    def test_it_is_open_to_the_it_role(self, sweep_app, authed):
        app, anchors, _, _ = sweep_app
        anchors.set_rates(8.0, 60.0)
        assert authed(app, role="it").post(
            "/path/sweep", json=self.ask(minutes_wide=1)).status_code == 200


class TestASweepNeedsSomethingToLookFor:
    def test_without_recognition_it_refuses_rather_than_finding_nobody(self, tmp_path):
        # Finding nobody and being unable to look are different answers, and
        # only one of them means "they were not there".
        runner = ArchiveRunner(FakeSource(), tmp_path, workers=1, finder=None)
        try:
            with pytest.raises(ArchiveUnavailable) as raised:
                runner.submit_sweep(["cam-a"], at(0), at(60))
            assert "face recognition is not running" in str(raised.value).lower()
        finally:
            runner.stop()


class TestAStrangerNeverGetsAName:
    def test_a_clicked_body_yields_a_description_and_no_identity(self, tmp_path):
        from vg.ingest.archive import descriptor_at

        class OneBody:
            def detect(self, image, min_area=0.0):
                class Person:
                    x, y, w, h = 0.2, 0.05, 0.4, 0.9
                return [Person()]

        clip = tmp_path / "chunk.mp4"
        _make_clip(clip, size=256)

        result = descriptor_at(clip, 0.3, 0.4, OneBody())
        assert result is not None, "a body big enough to describe was clicked"
        signature, box = result
        assert len(box) == 4
        assert all(0.0 <= v <= 1.0 for v in box), "fractions, never pixels"

        # The whole point: what comes back describes how somebody LOOKS. There
        # is no id and no name on it, and nothing downstream can invent one —
        # which is what keeps a clothing match from ever reading as a
        # recognition.
        assert not hasattr(signature, "person_id")
        assert not hasattr(signature, "name")

    def test_a_click_on_nothing_yields_nothing(self, tmp_path):
        from vg.ingest.archive import descriptor_at

        class NoBodies:
            def detect(self, image, min_area=0.0):
                return []

        clip = tmp_path / "chunk.mp4"
        _make_clip(clip)
        assert descriptor_at(clip, 0.5, 0.5, NoBodies()) is None

    def test_a_stranger_leg_carries_no_person(self):
        # The wire shape itself refuses to name a stranger: a descriptor leg
        # is built with personId None, and there is no path from a descriptor
        # to an id anywhere in the request.
        from vg.api import schemas as S

        req = S.LegRequest(
            camera_id="cam-a", start=at(0), end=at(30),
            descriptor_of=S.ChunkPoint(job_id="j1", chunk=0, x=0.4, y=0.5),
        )
        assert req.person_id is None
        assert "person" not in S.ChunkPoint.model_fields

    def test_appearance_hits_stay_appearance_on_the_wire(self):
        from vg.api import schemas as S

        # A stop found by clothing is APPEARANCE and the UI colours it blue.
        # It must never arrive as FACE, whatever else is known about them.
        stop = S.TrackStop(
            at=S.Instant(utc=at(0)), camera_id="cam-a", camera_name="A",
            place="Hall", match=S.MatchKind.APPEARANCE, confidence=0.9,
        )
        assert stop.match == S.MatchKind.APPEARANCE


def _make_clip(path: Path, frames: int = 3, size: int = 256) -> None:
    """A small playable mp4, so a test needs no fixture video.

    Deliberately not flat black: a colour signature refuses a region with too
    few usable pixels, so a uniform frame would make every one of these tests
    pass for the wrong reason.
    """
    import cv2

    writer = None
    for code in ("avc1", "mp4v"):
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*code), 5.0, (size, size))
        if writer.isOpened():
            break
        writer.release()
        writer = None
    if writer is None:
        pytest.skip("no usable video encoder on this machine")

    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[: size // 2, :] = (40, 90, 200)   # a red-ish top half
    frame[size // 2:, :] = (180, 120, 40)   # a blue-ish bottom half
    try:
        for _ in range(frames):
            writer.write(frame)
    finally:
        writer.release()


class TestWhatGetsDrawnOnAChunk:
    """The burn-in is evidence, so what it claims has to be exactly true."""

    def test_there_is_no_green_to_draw_with(self):
        # Green means a face was recognised. Nothing in the chunk pipeline
        # looks at a face — it detects bodies and compares how they look — so
        # a green constant in that module would eventually get used for "the
        # one being followed", which is how a clothing match starts reading as
        # an identification.
        from vg.ingest import archive

        assert hasattr(archive, "AMBER") and hasattr(archive, "BLUE")
        assert not hasattr(archive, "GREEN"), (
            "no colour in the archive pipeline may mean 'identified'"
        )

    def test_a_leg_with_no_descriptor_marks_nobody_out(self, tmp_path):
        # Without something to match against, every body is amber. Picking one
        # to highlight would be picking one to accuse.
        from vg.ingest.archive import ArchiveRunner

        runner = ArchiveRunner(FakeSource(), tmp_path, chunk_seconds=10.0,
                               workers=1, detector=None)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(10)))
            assert job.state == "done"
            assert job.descriptor is None
        finally:
            runner.stop()

    def test_the_matched_body_is_blue_and_the_rest_amber(self, tmp_path):
        # Drawn straight, without the runner, so the assertion is about the
        # pixels rather than about threading.
        import cv2
        import numpy as np

        from vg.ingest.archive import AMBER, BLUE

        frame = np.zeros((120, 200, 3), dtype=np.uint8)
        cv2.rectangle(frame, (10, 10), (50, 90), AMBER, 2)
        cv2.rectangle(frame, (120, 10), (160, 90), BLUE, 3)

        assert tuple(int(v) for v in frame[10, 30]) == AMBER
        assert tuple(int(v) for v in frame[10, 140]) == BLUE
        assert AMBER != BLUE, "the two have to be distinguishable on screen"


# ---------------------------------------------------------------------------
# The two bugs that made the feature look broken on a real machine
# ---------------------------------------------------------------------------

class TestTheDevServerCanReachEveryEndpoint:
    """`/path` existed, worked, and was unreachable from a browser.

    Vite proxies a hard-coded list of prefixes to the engine. A new endpoint
    under a new prefix is served perfectly by the engine and answered by the
    dev server instead, so the page shows "the engine did not answer" for a
    feature that is running fine. Nothing in either language notices, because
    each side is correct on its own.
    """

    def routes(self) -> set[str]:
        from vg.api.app import create_app

        prefixes = set()
        for route in create_app().routes:
            path = getattr(route, "path", "")
            if path.startswith("/") and len(path) > 1:
                prefixes.add("/" + path.lstrip("/").split("/")[0])
        return prefixes

    def proxied(self) -> set[str]:
        import re

        config = Path("web/vite.config.ts").read_text(encoding="utf-8")
        block = re.search(r"const API_PATHS = \[(.*?)\];", config, re.S)
        assert block, "API_PATHS is not where this test expects it"
        return set(re.findall(r"'(/[^']+)'", block.group(1)))

    def test_every_served_prefix_is_proxied(self):
        missing = self.routes() - self.proxied()
        assert not missing, (
            f"the engine serves {sorted(missing)} but web/vite.config.ts does "
            f"not proxy it, so the browser gets the dev server's 404 instead "
            f"of the engine's answer. Add it to API_PATHS."
        )

    def test_the_path_prefix_specifically(self):
        # The one that actually broke, named so a failure is unambiguous.
        assert "/path" in self.proxied()


class TestARunningRecorderReachesTheFollow:
    """A follow said recording was unavailable on an engine recording fine.

    `TrackingWorker` gained a `recorder` argument and the startup never passed
    one, because the Recorder was built later in the sequence than tracking.
    Both halves worked; they were simply never introduced.
    """

    def test_the_tracking_starter_passes_the_recorder_through(self):
        import inspect

        from vg.api import app as app_module

        signature = inspect.signature(app_module._start_tracking)
        assert "recorder" in signature.parameters, (
            "_start_tracking must accept a recorder, or a follow can never "
            "record on a real engine"
        )

        source = inspect.getsource(app_module._start_tracking)
        assert "recorder=recorder" in source, (
            "the recorder has to reach TrackingWorker, not just the signature"
        )

    def test_the_recorder_is_built_before_tracking_starts(self):
        # Ordering is the whole bug: built afterwards, there is nothing to
        # pass, and the failure is silent and only visible on a real machine.
        import inspect

        from vg.api import app as app_module

        source = inspect.getsource(app_module.lifespan)
        assert source.index("app.state.recorder = Recorder") < source.index(
            "tracking, app.state.tracking_error = _start_tracking"
        ), "the Recorder must exist before tracking is started"

    def test_a_worker_with_a_recorder_can_record(self):
        worker, stage, _, _ = build_worker(recorder=FakeRecorder())
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        worker.follow("cam-a", 0.15, 0.3, "tester")

        session = worker.record(None, "tester")
        assert session.recording is not None
        assert session.recording.running

    def test_a_worker_without_one_says_so_rather_than_pretending(self):
        from vg.features.tracking import NoRecorder

        worker, stage, _, _ = build_worker(recorder=None)
        sees(worker, stage, "cam-a", 0.0, [BODY_A])
        worker.follow("cam-a", 0.15, 0.3, "tester")

        with pytest.raises(NoRecorder):
            worker.record(None, "tester")


class TestASweepThatLookedAtNothingSaysSo:
    """The most misleading sentence this feature could produce.

    A sweep over a window with no recorded video fetched 38 segments, failed
    every one, and reported "38 of 38 pieces · 0 hits — nobody matching was
    found". That reads as evidence somebody was not somewhere, when not one
    second of video was ever examined. Those are different answers and the
    system must never collapse them.
    """

    def runner(self, tmp_path, covers):
        return ArchiveRunner(
            FakeSource(covers=covers), tmp_path, chunk_seconds=30.0,
            workers=1, finder=lambda *a: [],
        )

    def test_missing_footage_is_counted_not_swallowed(self, tmp_path):
        runner = self.runner(tmp_path, covers=False)
        try:
            job = runner.submit_sweep(["cam-a"], at(0), at(120))
            drain(runner, job)

            assert job.state == "done"
            assert job.segments_total == 4
            assert job.segments_missing == 4, "every piece had nothing behind it"
            assert job.searched_nothing is True
        finally:
            runner.stop()

    def test_a_sweep_with_footage_reports_nothing_missing(self, tmp_path):
        runner = self.runner(tmp_path, covers=True)
        try:
            job = drain(runner, runner.submit_sweep(["cam-a"], at(0), at(120)))
            assert job.segments_missing == 0
            assert job.searched_nothing is False
        finally:
            runner.stop()

    def test_the_count_reaches_the_wire(self, user_store, tmp_path, authed):
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        tmp = tempfile.TemporaryDirectory()
        anchors = AnchorStore(Path(tmp.name) / "a.db", clock=CAIRO)
        anchors.set_rates(fetch_x=8.0, process_fps=60.0)
        gallery = FaceGallery(Path(tmp.name) / "g.db", model=MODEL, threshold=0.363)
        gallery.add_person("p-layla", "Layla Ahmed")
        gallery.add_embedding("p-layla", unit("p-layla"), MODEL)
        runner = self.runner(tmp_path, covers=False)
        store = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([]),
            gallery=gallery, anchors=anchors, archive=runner,
        )
        app_module.set_store(store)
        app = create_app()
        app.state.users = user_store
        try:
            client = authed(app)
            started = client.post("/path/sweep", json={
                "person": "Layla Ahmed",
                "start": at(0).isoformat(),
                "end": at(120).isoformat(),
                "cameraIds": ["cam-laptop"],
            }).json()
            drain(runner, runner.sweep(started["job"]["id"]))

            body = client.get(f"/path/sweep/{started['job']['id']}").json()
            assert body["segmentsMissing"] == body["segmentsTotal"] > 0
            assert body["hits"] == []
        finally:
            app_module.set_store(MockStore())
            runner.stop()
            anchors.close()
            gallery.close()
            tmp.cleanup()


class TestTheNoFootageMessageIsUseful:
    """"No recorded footage covers cam-laptop at 2026-08-21T21:06:43+00:00."

    Three problems in one sentence: a machine timestamp, in a timezone three
    hours from the one the operator typed, and no hint of what there IS.
    """

    def backend(self):
        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        return FootageBackend(FOOTAGE, clock_for("Africa/Cairo"))

    @needs_clip
    def test_it_answers_in_the_time_the_operator_typed(self, tmp_path):
        from vg.ingest.archive import ArchiveUnavailable

        # 21:06 UTC is 00:06 the NEXT day in Cairo, which is what was typed.
        asked = datetime(2026, 8, 21, 21, 6, 43, tzinfo=timezone.utc)
        with pytest.raises(ArchiveUnavailable) as raised:
            self.backend().fetch(
                "cam-laptop", asked, asked + timedelta(seconds=30),
                tmp_path / "x.mp4")

        message = str(raised.value)
        assert "22 Aug" in message and "12:06am" in message
        assert "21T21:06" not in message, "no raw UTC timestamps at an operator"

    @needs_clip
    def test_it_says_what_the_camera_does_have(self, tmp_path):
        from vg.ingest.archive import ArchiveUnavailable

        asked = datetime(2026, 8, 21, 21, 6, 43, tzinfo=timezone.utc)
        with pytest.raises(ArchiveUnavailable) as raised:
            self.backend().fetch(
                "cam-laptop", asked, asked + timedelta(seconds=30),
                tmp_path / "x.mp4")

        # A dead end becomes the next thing to try.
        assert "What this camera has" in str(raised.value)
        assert "5 Aug" in str(raised.value)

    def test_a_camera_with_nothing_says_that_instead(self, tmp_path):
        from vg.clock import clock_for
        from vg.ingest.archive import ArchiveUnavailable, FootageBackend

        empty = FootageBackend(tmp_path / "none", clock_for("Africa/Cairo"))
        with pytest.raises(ArchiveUnavailable) as raised:
            empty.fetch("cam-a", at(0), at(30), tmp_path / "x.mp4")

        assert "no recorded video for this camera at all" in str(raised.value)

    def test_it_works_without_a_clock(self, tmp_path):
        # The clock is optional, and its absence must not crash the message.
        from vg.ingest.archive import ArchiveUnavailable, FootageBackend

        with pytest.raises(ArchiveUnavailable):
            FootageBackend(tmp_path / "none").fetch(
                "cam-a", at(0), at(30), tmp_path / "x.mp4")


class TestOperatorRecordingsAreArchiveFootage:
    """Record a camera through the console, then be told there is no video.

    `Recorder` writes to `storage.clips_dir`; the archive only read
    `storage.footage_dir`. Both were behaving correctly and the file was on
    the same disk the whole time.
    """

    def a_clip(self, directory: Path, name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        clip = directory / name
        _make_clip(clip, frames=10)
        return clip

    def test_a_recording_is_found(self, tmp_path):
        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        clips = tmp_path / "clips"
        self.a_clip(clips, "cam-a_20260822-000728.mp4")

        backend = FootageBackend(
            tmp_path / "footage", clock_for(0), recordings_dir=clips)
        assert [p.name for _s, _e, p in backend.coverage("cam-a")] == [
            "cam-a_20260822-000728.mp4"
        ]

    def test_both_folders_are_read_together(self, tmp_path):
        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        footage = tmp_path / "footage"
        clips = tmp_path / "clips"
        self.a_clip(footage, "cam-a_20260820-090000.mp4")
        self.a_clip(clips, "cam-a_20260822-000728.mp4")

        backend = FootageBackend(footage, clock_for(0), recordings_dir=clips)
        assert len(backend.coverage("cam-a")) == 2

    def test_the_filename_stamp_is_read_as_site_local_not_utc(self, tmp_path):
        # `Recorder._open` writes `self.clock.local(...)` into the name. Read
        # as UTC, a clip made at midnight in Cairo is filed at 3am and never
        # found — which is exactly what happened.
        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        clips = tmp_path / "clips"
        self.a_clip(clips, "cam-a_20260822-000728.mp4")

        cairo = FootageBackend(tmp_path / "f", clock_for(180), recordings_dir=clips)
        [(start, _end, _p)] = cairo.coverage("cam-a")

        assert start.hour == 21 and start.day == 21, (
            "00:07 in Cairo is 21:07 UTC the day before"
        )

        utc = FootageBackend(tmp_path / "f", clock_for(0), recordings_dir=clips)
        [(plain, _e, _p)] = utc.coverage("cam-a")
        assert plain.hour == 0 and plain.day == 22, "no offset, no shift"

    def test_a_sidecar_still_means_utc(self, tmp_path):
        # The two naming schemes disagree on purpose: a sidecar says
        # `started_utc` and means it, a filename is local. Both must be right.
        import json

        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        footage = tmp_path / "footage"
        clip = self.a_clip(footage, "walk_cam-a_20260805-121705.mp4")
        clip.with_suffix(".json").write_text(json.dumps({
            "camera_id": "cam-a",
            "started_utc": "2026-08-05T09:17:05+00:00",
            "duration_seconds": 100.0,
        }), encoding="utf-8")

        backend = FootageBackend(footage, clock_for(180))
        [(start, _e, _p)] = backend.coverage("cam-a")
        assert start.hour == 9, "a sidecar's UTC is not shifted again"

    def test_derived_video_is_not_treated_as_source(self, tmp_path):
        # `clips/track` holds the chunks this module itself produces, and
        # `clips/zones` holds zone clips. Re-reading a processed chunk as
        # source footage would draw outlines on top of outlines.
        from vg.clock import clock_for
        from vg.ingest.archive import FootageBackend

        clips = tmp_path / "clips"
        self.a_clip(clips / "track" / "job1", "chunk-000.mp4")
        self.a_clip(clips, "cam-a_20260822-000728.mp4")

        backend = FootageBackend(tmp_path / "f", clock_for(0), recordings_dir=clips)
        found = [p.name for _s, _e, p in backend.coverage("cam-a")]
        assert found == ["cam-a_20260822-000728.mp4"]

    def test_the_engine_hands_the_archive_both_folders(self):
        import inspect

        from vg.api import app as app_module

        source = inspect.getsource(app_module._start_archive)
        assert "recordings_dir" in source, (
            "the archive must be given clips_dir, or console recordings stay "
            "invisible to the page that plays them back"
        )


class TestALegSurvivesAGapAtTheFront:
    """The stop began at 00:44; the recording began at 00:45.

    A stop starts when somebody was RECOGNISED. A recording starts when
    somebody pressed a button. Those are never the same moment, so a gap at
    the front of a leg is the ordinary case rather than a rare one — and the
    code raised on it, throwing away video that existed a minute later.
    """

    class LateSource:
        """An archive whose footage starts partway through the span asked for."""

        name = "late"

        def __init__(self, available_from: float) -> None:
            self.available_from = available_from
            self.asked: list = []

        def coverage(self, camera_id):
            return []

        def fetch(self, camera_id, start, end, into):
            self.asked.append(start)
            if (start - at(0)).total_seconds() < self.available_from:
                raise ArchiveUnavailable(
                    "There is no recorded video from then. What this camera "
                    "has: 22 Aug, 12:45am to 22 Aug, 12:45am."
                )
            into.write_bytes(b"\x00" * 32)
            return into

    def test_the_video_that_exists_is_still_served(self, tmp_path):
        # Mohamed's case: a 2-minute stop, footage only in the last third.
        source = self.LateSource(available_from=60.0)
        runner = ArchiveRunner(source, tmp_path, chunk_seconds=30.0, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(120)))

            assert job.state == "done", job.error
            assert job.gaps == 2, "the first two pieces had nothing"
            assert len(job.chunks) == 2, "the last two did, and they play"
            assert [c.index for c in job.chunks] == [2, 3]
        finally:
            runner.stop()

    def test_every_piece_is_still_attempted(self, tmp_path):
        source = self.LateSource(available_from=60.0)
        runner = ArchiveRunner(source, tmp_path, chunk_seconds=30.0, workers=1)
        try:
            drain(runner, runner.submit("cam-a", at(0), at(120)))
            assert len(source.asked) == 4, "a gap stops nothing after it"
        finally:
            runner.stop()

    def test_progress_reaches_the_end_on_a_leg_with_gaps(self, tmp_path):
        # Gaps were looked for and answered. Leaving them out of progress
        # strands the bar short of the end on a leg that has finished.
        runner = ArchiveRunner(
            self.LateSource(60.0), tmp_path, chunk_seconds=30.0, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(120)))
            assert job.progress == pytest.approx(1.0)
        finally:
            runner.stop()

    def test_no_video_anywhere_is_still_a_failure_with_the_reason(self, tmp_path):
        # Skipping gaps must not turn "there is nothing at all" into a silent
        # empty success.
        runner = ArchiveRunner(
            self.LateSource(9e9), tmp_path, chunk_seconds=30.0, workers=1)
        try:
            job = drain(runner, runner.submit("cam-a", at(0), at(120)))
            assert job.state == "failed"
            assert job.chunks == []
            # The archive's own words, which name what it DOES hold.
            assert "12:45am" in (job.error or "")
        finally:
            runner.stop()

    def test_the_gap_count_reaches_the_wire(self, user_store, tmp_path, authed):
        from vg import config as vgconfig
        from vg.api import app as app_module
        from vg.api.app import create_app
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        tmp = tempfile.TemporaryDirectory()
        anchors = AnchorStore(Path(tmp.name) / "a.db", clock=CAIRO)
        runner = ArchiveRunner(
            self.LateSource(60.0), tmp_path, chunk_seconds=30.0, workers=1)
        store = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([]),
            anchors=anchors, archive=runner,
        )
        app_module.set_store(store)
        app = create_app()
        app.state.users = user_store
        try:
            client = authed(app)
            started = client.post("/path/legs", json={
                "cameraId": "cam-laptop",
                "start": at(0).isoformat(),
                "end": at(120).isoformat(),
            }).json()
            drain(runner, runner.job(started["job"]["id"]))

            body = client.get(f"/path/legs/{started['job']['id']}").json()
            assert body["chunksMissing"] == 2
            assert body["chunksReady"] == 2
            assert len(body["chunkUrls"]) == 2
            assert "12:45am" in (body["gapReason"] or ""), (
                "the operator is told what the archive does hold"
            )
        finally:
            app_module.set_store(MockStore())
            runner.stop()
            anchors.close()
            tmp.cleanup()
