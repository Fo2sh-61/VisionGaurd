"""The work-station machine, frame by frame (spec 025, T037 and T038).

Every test chooses its own `captured_at`, so eight seconds is eight seconds on
every machine. Faces are a fake pipeline and gallery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vg.areas import Area
from vg.config import StationsConfig
from vg.events.stations import StationStore
from vg.features.stations import StationsWorker
from vg.identity.gallery import Match, Person
from vg.infer.persons import DetectedPerson
from vg.ingest.source import Frame

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
BENCH = ((0.1, 0.4), (0.6, 0.4), (0.6, 0.95), (0.1, 0.95))
IN = (0.2, 0.2, 0.2, 0.6)        # feet at (0.3, 0.8): inside
OUT = (0.7, 0.2, 0.2, 0.6)       # feet at (0.8, 0.8): outside
CFG = StationsConfig()           # leave 8, return 3, gap 2, stall 10


def frame(sec, n=0, camera="cam-a"):
    return Frame(camera_id=camera, image=np.zeros((100, 100, 3), np.uint8),
                 captured_at=T0 + timedelta(seconds=sec), sequence=n)


class Detector:
    def __init__(self):
        self.boxes = []
        self.asked = 0

    def detect(self, frame):
        self.asked += 1
        return [DetectedPerson(x=x, y=y, w=w, h=h, confidence=0.9)
                for x, y, w, h in self.boxes]


def station(sid="st1", limit=5, **kw):
    base = dict(id=sid, kind="station", name="Bench", camera_id="cam-a",
                polygon=BENCH, hours_mode="always", limit_minutes=limit)
    base.update(kw)
    return Area(**base)


@pytest.fixture
def store(tmp_path):
    s = StationStore(tmp_path / "st.db")
    yield s
    s.close_db()


class NoBus:
    def subscribe(self, *a, **kw):  # pragma: no cover
        raise AssertionError("never started")


def make(store, areas=None, **kw):
    d = Detector()
    w = StationsWorker(NoBus(), d, ["cam-a"], store,
                       areas=areas if areas is not None else [station()],
                       config=kw.pop("config", CFG), **kw)
    return w, d


def run(w, d, script, sid="st1"):
    """`(seconds, boxes)` pairs; returns the last result."""
    out = None
    for i, (sec, boxes) in enumerate(script):
        d.boxes = boxes
        out = w.analyse(frame(sec, i))
    return out


def present(a, b, step=0.5):
    n = int((b - a) / step) + 1
    return [(a + i * step, [IN]) for i in range(n)]


def empty(a, b, step=0.5):
    n = int((b - a) / step) + 1
    return [(a + i * step, []) for i in range(n)]


def states(store, sid="st1"):
    return [(s.state, (s.started_at - T0).total_seconds(),
             None if s.ended_at is None else (s.ended_at - T0).total_seconds())
            for s in store.segments(sid, T0 - timedelta(days=1),
                                    T0 + timedelta(days=1))]


def kinds(store, sid="st1"):
    return [e.kind for e in reversed(store.events(
        sid, T0 - timedelta(days=1), T0 + timedelta(days=1)))]


class TestTheMachine:
    def test_the_first_frame_starts_away_and_somebody_there_turns_it_on(
            self, store):
        w, d = make(store)
        run(w, d, present(0, 4))
        seg = [s for s in states(store) if s[0] == "on"]
        assert seg and seg[0][1] == 0.0, "back since the first moment of the run"

    def test_an_empty_first_frame_is_away_since_that_frame(self, store):
        w, d = make(store)
        r = run(w, d, empty(0, 2))
        assert r.stations[0].state == "away"
        assert states(store)[0][:2] == ("away", 0.0)

    def test_on_goes_away_only_after_the_leave_time_and_stores_the_last_moment(
            self, store):
        w, d = make(store)
        run(w, d, present(0, 4) + empty(4.5, 11))
        assert w.analyse(frame(11.5)).stations[0].state == "on", "7.5 s: not yet"
        run(w, d, [(12.5, [])])
        away = [s for s in states(store) if s[0] == "away"][-1]
        assert away[1] == 4.0, "the last moment somebody counted"

    def test_walking_out_and_back_inside_the_confirmation_makes_no_event(
            self, store):
        w, d = make(store)
        run(w, d, present(0, 4) + empty(4.5, 9) + present(9.5, 14))
        assert kinds(store) == ["at_station"], "only the arrival"
        assert [s[0] for s in states(store)].count("on") == 1

    def test_away_to_on_needs_the_return_time_and_stores_the_run_start(
            self, store):
        w, d = make(store)
        run(w, d, empty(0, 20) + present(20, 22))
        assert w.analyse(frame(22.5)).stations[0].state == "away"
        run(w, d, [(23.0, [IN])])
        on = [s for s in states(store) if s[0] == "on"][0]
        assert on[1] == 20.0

    def test_a_short_gap_does_not_break_the_run(self, store):
        w, d = make(store)
        run(w, d, empty(0, 20))
        run(w, d, [(20.0, [IN]), (20.5, [IN]), (21.0, []), (21.5, [IN]),
                   (22.5, [IN]), (23.0, [IN])])
        on = [s for s in states(store) if s[0] == "on"][0]
        assert on[1] == 20.0

    def test_a_long_gap_restarts_the_run(self, store):
        w, d = make(store)
        run(w, d, empty(0, 20))
        run(w, d, [(20.0, [IN]), (20.5, []), (23.0, [IN]), (24.0, [IN]),
                   (25.0, [IN])])
        assert not [s for s in states(store) if s[0] == "on"]
        run(w, d, [(26.0, [IN])])
        on = [s for s in states(store) if s[0] == "on"][0]
        assert on[1] == 23.0

    def test_two_people_are_still_one_on(self, store):
        w, d = make(store)
        r = run(w, d, [(t / 2, [IN, (0.3, 0.2, 0.2, 0.6)]) for t in range(8)])
        assert r.stations[0].state == "on" and r.stations[0].people == 2

    def test_body_outside_the_area_does_not_count(self, store):
        w, d = make(store)
        r = run(w, d, [(t / 2, [OUT]) for t in range(10)])
        assert r.stations[0].state == "away"


class TestAbsence:
    def test_absent_at_exactly_away_since_plus_limit_with_one_alert(self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, present(0, 3) + empty(3.5, 200, step=5))
        absent = [s for s in states(store) if s[0] == "absent"]
        assert absent and absent[0][1] == 3.0 + 60
        assert len(calls) == 1
        assert calls[0][5] == 1 and calls[0][4] == "Bench"
        assert kinds(store).count("absence_alert") == 1

    def test_nothing_more_while_it_continues_and_a_new_absence_alerts_again(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, present(0, 3) + empty(3.5, 150, step=5)
            + present(200, 204) + empty(204.5, 400, step=5))
        assert len(calls) == 2

    def test_a_restart_in_the_middle_cannot_alert_the_same_absence_twice(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, empty(0, 100, step=5))
        assert len(calls) == 1
        # Same absence offered again (a second worker after a restart).
        store.absence_alert("st1", "cam-a", T0 + timedelta(seconds=120),
                            T0, "Bench", 1)
        assert len(calls) == 1

    def test_somebody_returning_turns_an_absence_back_on(self, store):
        w, d = make(store, [station(limit=1)])
        run(w, d, empty(0, 100, step=5) + present(101, 106))
        assert states(store)[-1][0] == "on"
        assert "at_station" in kinds(store)

    def test_the_alert_names_the_assignee_and_carries_the_notify_choice(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        gallery = FakeGallery({"p1": "Layla"})
        w, d = make(store, [station(limit=1, assignee_id="p1",
                                    notify_email=True)],
                    pipeline=FakePipeline([]), gallery=gallery)
        run(w, d, empty(0, 100, step=5))
        assert calls[0][6] == "Layla" and calls[0][7] == frozenset({"email"})


class TestReviewFixes:
    """Fixes from the spec 025 review, each with the case that found it."""

    def test_a_return_under_way_at_the_limit_raises_no_absence(self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        # away since 0, due at 60; somebody starts walking back at 59 and is
        # confirmed at 62 - the alert must not go out for somebody returning.
        run(w, d, empty(0, 58.5) + present(59, 64))
        assert calls == []
        assert not [s for s in states(store) if s[0] == "absent"]
        assert kinds(store) == ["at_station"]
        assert all(s[2] is None or s[2] >= s[1] for s in states(store))
        assert states(store)[-1][:2] == ("on", 59.0)

    def test_a_run_that_breaks_before_it_confirms_lets_the_absence_stand(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, empty(0, 58.5) + [(59.0, [IN])] + empty(59.5, 70))
        assert len(calls) == 1
        assert [s for s in states(store) if s[0] == "absent"][0][1] == 60.0

    def test_a_stall_before_the_hours_end_does_not_cover_the_gap(self, store):
        class Clock:
            def local(self, when):
                return when
        window = station(limit=0, hours_mode="custom", hours_from="09:00",
                         hours_to="10:00")
        w, d = make(store, [window], clock=Clock())
        run(w, d, [(3500, []), (3540, [])])             # 09:59
        w.analyse(frame(3700, 9))                       # 10:01.6, long silence
        away = states(store)
        assert away[-1][2] == 3540.0, "closed at the last frame, not at 10:00"

    def test_a_moved_station_closes_its_segment_when_the_new_camera_steps(
            self, store):
        w, d = make(store, [station()])
        run(w, d, present(0, 4))
        w.set_areas([station(camera_id="cam-b")])
        d.boxes = [IN]
        w.analyse(frame(5, 50, camera="cam-b"))         # the NEW camera first
        segs = states(store)
        first_on = [x for x in segs if x[0] == "on"][0]
        assert first_on[2] == 4.0, "the old camera's segment ends where it was last seen"
        assert segs[-1][2] is None and segs[-1][1] >= 5.0
        # the old camera stepping afterwards must not disturb the new one
        w.analyse(frame(6, 51, camera="cam-a"))
        assert states(store)[-1][2] is None

    def test_a_restart_mid_absence_starts_a_new_absence_that_can_alert_again(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, empty(0, 100, step=5))
        assert len(calls) == 1
        # The engine restarts: open rows are closed and a fresh worker starts
        # with its Away clock at its first frame, though nobody came back.
        store.close_orphans()
        w2, d2 = make(store, [station(limit=1)])
        run(w2, d2, [(300 + i * 5, []) for i in range(10)])
        assert len(calls) == 1, "not before another full limit"
        run(w2, d2, [(300 + i * 5, []) for i in range(10, 16)])
        assert len(calls) == 2, "the restarted Away clock reaches the limit"


class TestHoursAndGaps:
    def test_hours_ending_closes_at_the_hours_end_and_is_not_carried_over(
            self, store):
        window = station(limit=1, hours_mode="custom", hours_from="09:00",
                         hours_to="09:10")
        class Clock:
            def local(self, when):
                return when
        w, d = make(store, [window], clock=Clock())
        run(w, d, [(0, []), (60, [])] + [(t, []) for t in range(540, 600, 5)])
        d.boxes = []
        w.analyse(frame(601, 9))                       # 10:00:01, frames were continuous
        away = [s for s in states(store) if s[0] in ("away", "absent")]
        assert max(s[2] for s in away if s[2] is not None) == 600.0
        w.analyse(frame(30 * 60 * 24, 10))
        assert w.analyse(frame(30 * 60 * 24 + 1, 11)).restricted is False

    def test_outside_hours_counts_nothing_and_alerts_nothing(self, store):
        class Clock:
            def local(self, when):
                return when
        window = station(hours_mode="custom", hours_from="12:00",
                         hours_to="13:00")
        w, d = make(store, [window], clock=Clock())
        run(w, d, empty(0, 1000, step=50))
        assert states(store) == [] and kinds(store) == []
        assert d.asked == 0, "never reached the detector"

    def test_a_stall_closes_the_segment_and_restarts_the_away_clock(
            self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        w, d = make(store, [station(limit=1)])
        run(w, d, empty(0, 50, step=5))
        run(w, d, [(500, [])])                          # 450 s of silence
        assert states(store)[0][2] == 50.0, "closed at the last frame"
        assert calls == [], "no alert for time nobody measured"
        assert states(store)[-1][:2] == ("away", 500.0)

    def test_writes_only_on_change_and_heartbeat(self, store):
        w, d = make(store)
        run(w, d, present(0, 4) + [(t, [IN]) for t in range(5, 60)])
        assert len(states(store)) <= 3 and len(kinds(store)) == 1

    def test_the_machine_uses_the_frame_clock_not_the_wall_clock(self):
        import ast
        import inspect
        from vg.features import stations
        used = {n.attr for n in ast.walk(ast.parse(inspect.getsource(stations)))
                if isinstance(n, ast.Attribute)}
        assert "monotonic" not in used


    def test_segments_sum_to_the_time_watched(self, store):
        w, d = make(store)
        run(w, d, present(0, 20) + empty(20.5, 60, step=1))
        f = store.figures("st1", [(T0, T0 + timedelta(seconds=60))],
                          T0 + timedelta(seconds=60))
        assert f.covered_seconds + f.not_watched_seconds == pytest.approx(60)

    def test_restricted_lists_cameras_with_a_station(self, store):
        w, _ = make(store, [station(), station("st2", camera_id="cam-b")])
        assert w.restricted() == {"cam-a", "cam-b"}

    def test_a_deleted_station_is_closed_on_the_next_frame(self, store):
        w, d = make(store)
        run(w, d, present(0, 4))
        w.set_areas([])
        w.analyse(frame(5, 99))
        assert all(s[2] is not None for s in states(store))


# ---------------------------------------------------------------------------
# the assigned person
# ---------------------------------------------------------------------------

@dataclass
class FakeFace:
    w: int = 100


@dataclass
class FakeObs:
    face: FakeFace
    embedding: object
    model: str = "sface"


class FakeDetector:
    def __init__(self, widths):
        self.widths = widths
        self.calls = 0

    def detect(self, image, min_size=80):
        self.calls += 1
        return [FakeFace(w) for w in self.widths]


class FakePipeline:
    """`observe` returns one observation per face the test says is visible;
    the embedding is the label of who it is."""

    def __init__(self, who, width=100, small=()):
        self.who = list(who)
        self.width = width
        self.observed = 0
        self.detector = FakeDetector(small)

    def observe(self, crop, **kw):
        self.observed += 1
        return [FakeObs(FakeFace(self.width), label) for label in self.who]


class FakeGallery:
    def __init__(self, people):
        self.people = people

    def person(self, pid):
        return Person(id=pid, name=self.people[pid]) if pid in self.people else None

    def match(self, embedding, model=None):
        if embedding in self.people:
            return Match(person=Person(id=embedding, name=self.people[embedding]),
                         score=0.9)
        return Match(person=None, score=0.1)


def assigned(store, who, **kw):
    gallery = FakeGallery({"p1": "Layla", "p2": "Omar"})
    pipeline = FakePipeline(who, **kw.pop("pipe", {}))
    w, d = make(store, [station(assignee_id="p1", **kw)],
                pipeline=pipeline, gallery=gallery)
    return w, d, pipeline


class TestAssignee:
    def test_only_the_assignees_face_makes_it_on(self, store):
        w, d, _ = assigned(store, ["p1"])
        r = run(w, d, present(0, 4))
        assert r.stations[0].state == "on" and not r.stations[0].unrecognised

    def test_a_stranger_never_reads_on(self, store):
        w, d, _ = assigned(store, ["p2"])
        r = run(w, d, present(0, 20))
        assert r.stations[0].state == "away"
        assert r.stations[0].unrecognised is True, "live flag, not stored"
        assert not [s for s in states(store) if s[0] == "on"]

    def test_after_the_assignee_leaves_a_stranger_reads_away(self, store):
        w, d, pipe = assigned(store, ["p1"])
        run(w, d, present(0, 4))
        pipe.who = ["p2"]
        r = run(w, d, [(5 + t * 0.5, [IN]) for t in range(40)])
        assert r.stations[0].state == "away"

    def test_the_worker_holds_no_name_afterwards(self, store):
        w, d, _ = assigned(store, ["p1"])
        run(w, d, present(0, 4))
        seen = []

        def walk(value, path):
            if id(value) in seen:
                return
            seen.append(id(value))
            if isinstance(value, np.ndarray):
                raise AssertionError(f"an embedding is held at {path}")
            if isinstance(value, str) and value in ("p1", "Layla"):
                raise AssertionError(f"a person is held at {path}")
            items = []
            if isinstance(value, dict):
                items = list(value.items())
            elif isinstance(value, (list, tuple, set, frozenset)):
                items = list(enumerate(value))
            elif hasattr(value, "__dict__") and not callable(value):
                items = list(vars(value).items())
            for key, sub in items:
                walk(sub, f"{path}.{key}")

        for name, value in vars(w).items():
            # The area is the ASSIGNMENT the owner drew; everything else is
            # what the worker learned by looking.
            if name in ("_areas", "gallery", "pipeline", "store", "detector",
                        "bus", "config"):
                continue
            if name.startswith("_") or name in ("stations",):
                walk(value, name)

    def test_the_face_step_runs_only_with_an_assignee_and_somebody_inside(
            self, store):
        w, d, pipe = assigned(store, ["p1"])
        run(w, d, empty(0, 5))
        assert pipe.observed == 0, "empty station: no face work"
        run(w, d, [(6, [OUT])])
        assert pipe.observed == 0
        run(w, d, [(7, [IN])])
        assert pipe.observed == 1

        w2, d2 = make(store, [station("st9")], pipeline=FakePipeline(["p1"]),
                      gallery=FakeGallery({"p1": "Layla"}))
        run(w2, d2, present(0, 3))
        assert w2.pipeline.observed == 0, "no assignee: no face work"

    def test_an_assignee_gone_from_the_directory_counts_anyone_and_says_so(
            self, store):
        w, d = make(store, [station(assignee_id="gone")],
                    pipeline=FakePipeline([]), gallery=FakeGallery({}))
        r = run(w, d, present(0, 4))
        assert r.stations[0].state == "on" and r.stations[0].assignee_missing

    def test_faces_too_small_counts_anyone_and_says_so(self, store):
        w, d, pipe = assigned(store, [], pipe={"small": [30]})
        run(w, d, [(t * 0.5, [IN]) for t in range(8)])
        r = run(w, d, [(10, [IN])])
        assert r.stations[0].face_check == "facesTooSmall"
        assert r.stations[0].face_px == 30
        run(w, d, [(11 + t * 0.5, [IN]) for t in range(8)])
        assert w.analyse(frame(16)).stations[0].state == "on"

    def test_never_measured_keeps_the_normal_face_check(self, store):
        w, d, _ = assigned(store, [])
        r = run(w, d, [(0, [IN])])
        assert r.stations[0].face_check == "face" and r.stations[0].face_px is None

    def test_big_enough_faces_keep_the_face_check(self, store):
        w, d, _ = assigned(store, ["p2"], pipe={"width": 120})
        r = run(w, d, [(t * 0.5, [IN]) for t in range(12)])
        assert r.stations[0].face_check == "face"
