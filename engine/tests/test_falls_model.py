"""The fall model in the engine is the owner's model, and stays it.

`vg/infer/falls.py` carries a copy of the owner's code from `models/falling/`
— the 30-pose window, the normalisation, the LSTM, the smoothing, the alert
rules and the id-switch linker. A copy is only safe while something checks it
still behaves like the thing it was copied from, so the first half of this file
runs **the owner's own files**, unmodified, in a separate interpreter, and the
engine's copy in this one, over the same skeletons, and requires the same
falls on the same frames with the same confidences.

The second half is the engine's own addition, the 30-a-second timeline: the
engine analyses a camera five times a second, and fills in the poses between.
Those tests drive the real trained network, not a stand-in, because "does the
installed model still see a fall at five frames a second" is the question.

Everything here needs torch. Without it the file skips, which is the right
answer on a machine that cannot run the model at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from vg.infer import falls as F  # noqa: E402

REPO_DIR = Path(__file__).resolve().parents[2]
OWNER_DIR = REPO_DIR / "models" / "falling"
CHECKPOINT = OWNER_DIR / "checkpoints__temporal_model.pt"

#: The owner's files, as they were handed over (flattened, `core/x.py` became
#: `core__x.py`), and where each goes back to so the package imports work.
OWNER_FILES = {
    "core____init__.py": "core/__init__.py",
    "core__keypoints.py": "core/keypoints.py",
    "core__features.py": "core/features.py",
    "core__boxes.py": "core/boxes.py",
    "core__pose.py": "core/pose.py",
    "detectors____init__.py": "detectors/__init__.py",
    "detectors__base.py": "detectors/base.py",
    "detectors__events.py": "detectors/events.py",
    "detectors__registry.py": "detectors/registry.py",
    "detectors__rule_based.py": "detectors/rule_based.py",
    "detectors__temporal_model.py": "detectors/temporal_model.py",
    "train____init__.py": "train/__init__.py",
    "train__model.py": "train/model.py",
}

T0 = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not CHECKPOINT.is_file(), reason="the owner's fall model is not in models/falling/")


# ---------------------------------------------------------------------------
# synthetic people — the owner's tests/synth.py, which needs no weights
# ---------------------------------------------------------------------------

UPRIGHT = np.array([
    [0.00, -0.93],
    [0.02, -0.95], [-0.02, -0.95],
    [0.05, -0.93], [-0.05, -0.93],
    [0.12, -0.80], [-0.12, -0.80],
    [0.15, -0.62], [-0.15, -0.62],
    [0.16, -0.47], [-0.16, -0.47],
    [0.08, -0.50], [-0.08, -0.50],
    [0.08, -0.27], [-0.08, -0.27],
    [0.08, -0.03], [-0.08, -0.03],
])


def skeleton(cx, feet_y, height, angle_deg=0.0, conf=0.9, sway=0.0):
    th = np.radians(angle_deg)
    off = UPRIGHT * height
    off = off + np.array([sway, 0.0]) * height * (off[:, 1:2] < -0.4 * height)
    rot = np.stack([off[:, 0] * np.cos(th) - off[:, 1] * np.sin(th),
                    off[:, 0] * np.sin(th) + off[:, 1] * np.cos(th)], axis=1)
    kps = np.empty((17, 3), dtype=np.float32)
    kps[:, :2] = rot + np.array([cx, feet_y])
    kps[:, 2] = conf
    return kps


def fall_sequence(n_before=45, n_fall=15, n_after=120, cx=300.0, height=220.0, seed=0):
    """Walk, tip over during `n_fall` frames, lie still."""
    rng = np.random.default_rng(seed)
    kps = [skeleton(cx + 1.5 * t, 400.0, height, sway=0.03 * np.sin(t / 3))
           for t in range(n_before)]
    x = cx + 1.5 * n_before
    kps += [skeleton(x, 400.0, height, angle_deg=90.0 * (t + 1) / n_fall)
            for t in range(n_fall)]
    kps += [skeleton(x, 400.0, height, angle_deg=90.0) for _ in range(n_after)]
    kps = np.stack(kps)
    kps[..., :2] += rng.normal(0, 1.0, size=kps[..., :2].shape)
    return kps.astype(np.float32)


def walk_sequence(n=150, cx=100.0, height=220.0, seed=1):
    rng = np.random.default_rng(seed)
    kps = np.stack([skeleton(cx + 2.0 * t, 400.0, height, sway=0.03 * np.sin(t / 3))
                    for t in range(n)])
    kps[..., :2] += rng.normal(0, 1.0, size=kps[..., :2].shape)
    return kps.astype(np.float32)


def lying_sequence(n=150, cx=300.0, height=220.0):
    """Somebody lying down the whole time: never a fall."""
    return np.stack([skeleton(cx, 400.0, height, angle_deg=90.0) for _ in range(n)])


def fall_then_get_up(n_down=60, seed=2):
    """Falls, stays down two seconds, stands again."""
    down = fall_sequence(n_after=n_down, seed=seed)
    x = 300.0 + 1.5 * 45
    up = np.stack([skeleton(x, 400.0, 220.0, angle_deg=90.0 * (1 - (t + 1) / 20))
                   for t in range(20)] + [skeleton(x, 400.0, 220.0) for _ in range(90)])
    return np.concatenate([down, up.astype(np.float32)])


def bbox_of(kps):
    return (float(kps[:, 0].min()), float(kps[:, 1].min()),
            float(kps[:, 0].max()), float(kps[:, 1].max()))


def frames_of(*tracks, drop=(), switch=None):
    """Per frame: a list of (track_id, kps) — what both copies are fed.

    `tracks` are (track_id, kps sequence) pairs, run side by side.
    `drop` names frames with nobody detected. `switch=(frame, new_id)` renames
    the first track from that frame on, which is what ByteTrack does to a
    person mid-fall and what the owner's `TrackLinker` exists for.
    """
    n = max(len(k) for _, k in tracks)
    out = []
    for f in range(n):
        if f in set(drop):
            out.append([])
            continue
        row = []
        for i, (tid, kps) in enumerate(tracks):
            if f >= len(kps):
                continue
            if switch is not None and i == 0 and f >= switch[0]:
                tid = switch[1]
            row.append((tid, kps[f]))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# running the owner's code, untouched, in its own interpreter
# ---------------------------------------------------------------------------

OWNER_RUNNER = textwrap.dedent("""
    import json, sys
    import numpy as np
    from core.pose import Person
    from detectors.temporal_model import TemporalModelDetector

    frames = json.load(open(sys.argv[1]))
    det = TemporalModelDetector(checkpoint=sys.argv[2], device="cpu")
    det.reset(30.0)
    events, states = [], []
    for f, row in enumerate(frames):
        persons = [Person(track_id=tid, bbox=tuple(box), conf=0.9,
                          keypoints=np.asarray(kps, dtype=np.float32))
                   for tid, box, kps in row]
        for e in det.update(f, persons):
            events.append([e.track_id, e.frame_idx, e.confidence,
                           e.fall_start_frame])
        states.append(sorted([tid, s.state, s.confidence, s.alerted]
                             for tid, s in det.statuses().items()))
    json.dump({"events": events, "states": states}, sys.stdout)
""")


@pytest.fixture(scope="module")
def owner_package(tmp_path_factory) -> Path:
    """The owner's files, put back in their folders, in a throwaway place."""
    root = tmp_path_factory.mktemp("falling_owner")
    for flat, real in OWNER_FILES.items():
        target = root / real
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((OWNER_DIR / flat).read_bytes())
    (root / "run.py").write_text(OWNER_RUNNER)
    return root


def run_owner(package: Path, frames) -> dict:
    payload = [[[tid, list(bbox_of(kps)), kps.tolist()] for tid, kps in row]
               for row in frames]
    data = package / "frames.json"
    data.write_text(json.dumps(payload))
    done = subprocess.run(
        [sys.executable, "run.py", str(data), str(CHECKPOINT)],
        cwd=package, capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_engine(frames) -> dict:
    tracker = F.FallTracker(F.TemporalClassifier(CHECKPOINT, device="cpu"))
    tracker.reset(30.0)
    events, states = [], []
    for f, row in enumerate(frames):
        persons = [F.Person(track_id=tid, bbox=bbox_of(kps), conf=0.9, keypoints=kps)
                   for tid, kps in row]
        for e in tracker.update(f, persons):
            events.append([e.track_id, e.frame_idx, e.confidence, e.fall_start_frame])
        states.append(sorted([tid, s.state, s.confidence, s.alerted]
                             for tid, s in tracker.statuses().items()))
    # Through JSON, exactly as the owner's side arrives, so a float that
    # differs only in how it was printed cannot fail the comparison.
    return json.loads(json.dumps({"events": events, "states": states}))


SCENARIOS = {
    "a fall": lambda: frames_of((1, fall_sequence())),
    "walking": lambda: frames_of((1, walk_sequence())),
    "lying the whole time": lambda: frames_of((1, lying_sequence())),
    "falls, then gets up": lambda: frames_of((1, fall_then_get_up())),
    "an id switch mid-fall": lambda: frames_of((1, fall_sequence()), switch=(52, 9)),
    "tracking gaps": lambda: frames_of((1, fall_sequence()), drop=(20, 21, 22, 70)),
    "a long gap": lambda: frames_of((1, fall_sequence()), drop=tuple(range(30, 40))),
    "two people, one falls": lambda: frames_of(
        (1, fall_sequence()), (2, walk_sequence(cx=40.0))),
}


class TestTheEngineRunsTheOwnersModel:
    """Same skeletons in, same falls out — to the frame and to the float."""

    @pytest.mark.parametrize("name", list(SCENARIOS))
    def test_the_same_falls_on_the_same_frames(self, owner_package, name):
        frames = SCENARIOS[name]()
        owner = run_owner(owner_package, frames)
        engine = run_engine(frames)
        assert engine["events"] == owner["events"]
        assert engine["states"] == owner["states"]

    def test_a_fall_is_actually_raised(self, owner_package):
        """Parity over nothing would pass too. This one must fire."""
        engine = run_engine(SCENARIOS["a fall"]())
        assert len(engine["events"]) == 1

    def test_walking_and_lying_raise_nothing(self):
        assert run_engine(SCENARIOS["walking"]())["events"] == []
        assert run_engine(SCENARIOS["lying the whole time"]())["events"] == []

    def test_the_installed_model_is_the_lstm_the_owner_picked(self):
        clf = F.TemporalClassifier(CHECKPOINT, device="cpu")
        assert clf.arch == "lstm"
        assert clf.version == "lstm_cctv"
        # Calibrated by the owner's train/calibrate.py and stored in the
        # checkpoint. Used as stored; nothing in the engine retunes them.
        assert clf.fallen_threshold == pytest.approx(0.8)
        assert clf.emitter_config.falling_alert_s == pytest.approx(1.0)
        assert clf.emitter_config.lost_alert_s == pytest.approx(0.5)

    def test_it_is_the_same_file_as_the_lstm_cctv_run(self):
        """`train.compare --install` copies the winner; nothing else moved it."""
        assert CHECKPOINT.read_bytes() == (OWNER_DIR / "runs__lstm_cctv__best.pt").read_bytes()


# ---------------------------------------------------------------------------
# the engine's timeline: real frames at the camera's rate, model at 30
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def classifier():
    return F.TemporalClassifier(CHECKPOINT, device="cpu")


def run_timeline(classifier, kps, every: int, start=T0):
    """Feed every `every`-th frame of a 30 fps sequence, timed as it would be."""
    timeline = F.FallTimeline(classifier)
    readings = []
    for i in range(0, len(kps), every):
        person = F.Person(1, bbox_of(kps[i]), 0.9, kps[i])
        readings.append(timeline.step(start + timedelta(seconds=i / 30), {1: person}, 640, 480))
    return readings


class TestFiveFramesASecond:
    """The engine analyses a camera at its configured rate, usually 5/sec."""

    @pytest.mark.parametrize("every", [1, 6, 10])
    def test_a_fall_is_seen_at_30_5_and_3_frames_a_second(self, classifier, every):
        readings = run_timeline(classifier, fall_sequence(n_after=150), every)
        alerts = [a for r in readings for a in r.alerts]
        assert len(alerts) == 1
        # The fall starts 1.5 s in; the alert lands within a couple of
        # seconds of it, never before it.
        fell = (alerts[0].fell_at - T0).total_seconds()
        said = (alerts[0].at - T0).total_seconds()
        assert 1.0 <= fell <= said <= 4.0

    @pytest.mark.parametrize("every", [1, 6])
    def test_walking_and_lying_are_never_a_fall(self, classifier, every):
        for kps in (walk_sequence(), lying_sequence()):
            readings = run_timeline(classifier, kps, every)
            assert [a for r in readings for a in r.alerts] == []

    def test_someone_on_the_floor_reads_fallen(self, classifier):
        readings = run_timeline(classifier, fall_sequence(n_after=150), 6)
        assert readings[-1].people[0].state == "fallen"

    def test_geometry_leaves_as_fractions(self, classifier):
        readings = run_timeline(classifier, fall_sequence(n_after=60), 6)
        alert = next(a for r in readings for a in r.alerts)
        for value in (alert.x, alert.y, alert.w, alert.h, alert.confidence):
            assert 0.0 <= value <= 1.0
        person = readings[-1].people[0]
        assert 0.0 < person.w <= 1.0 and 0.0 < person.h <= 1.0


class TestTheTimeline:

    def test_the_frames_between_are_filled_in(self, classifier, monkeypatch):
        """Five real frames a second become thirty model frames a second."""
        timeline = F.FallTimeline(classifier)
        fed = []
        real_update = timeline.tracker.update
        monkeypatch.setattr(timeline.tracker, "update",
                            lambda f, people: fed.append((f, len(people))) or real_update(f, people))
        kps = walk_sequence()
        for i in (0, 6, 12):
            timeline.step(T0 + timedelta(seconds=i / 30),
                          {1: F.Person(1, bbox_of(kps[i]), 0.9, kps[i])})
        assert [f for f, _ in fed] == list(range(13))
        assert all(n == 1 for _, n in fed)

    def test_a_gap_longer_than_half_a_second_is_not_invented(self, classifier, monkeypatch):
        timeline = F.FallTimeline(classifier)
        fed = []
        real_update = timeline.tracker.update
        monkeypatch.setattr(timeline.tracker, "update",
                            lambda f, people: fed.append(f) or real_update(f, people))
        kps = walk_sequence()
        timeline.step(T0, {1: F.Person(1, bbox_of(kps[0]), 0.9, kps[0])})
        timeline.step(T0 + timedelta(seconds=2), {1: F.Person(1, bbox_of(kps[1]), 0.9, kps[1])})
        assert fed == [0, 60]

    def test_a_hidden_joint_stays_hidden_in_between(self):
        a = F.Person(1, (0, 0, 10, 10), 0.9, skeleton(100, 400, 200))
        b = F.Person(1, (10, 10, 20, 20), 0.9, skeleton(110, 400, 200))
        b.keypoints[3, 2] = 0.1   # an ear the pose model was not sure of
        mid = F._between(a, b, 0.5)
        assert mid.keypoints[3, 2] == pytest.approx(0.1)
        assert mid.keypoints[0, 0] == pytest.approx((a.keypoints[0, 0] + b.keypoints[0, 0]) / 2)
        assert mid.bbox == (5.0, 5.0, 15.0, 15.0)

    def test_the_clock_going_backwards_starts_again(self, classifier):
        timeline = F.FallTimeline(classifier)
        kps = walk_sequence()
        timeline.step(T0 + timedelta(seconds=5), {1: F.Person(1, bbox_of(kps[0]), 0.9, kps[0])})
        timeline.step(T0, {1: F.Person(1, bbox_of(kps[1]), 0.9, kps[1])})
        assert timeline.last_index == 0

    def test_a_person_who_leaves_is_still_known_for_a_while(self, classifier):
        """Lying on the floor is where pose models lose people most."""
        timeline = F.FallTimeline(classifier)
        kps = walk_sequence()
        for i in range(0, 60, 6):
            timeline.step(T0 + timedelta(seconds=i / 30),
                          {1: F.Person(1, bbox_of(kps[i]), 0.9, kps[i])})
        reading = timeline.step(T0 + timedelta(seconds=2.2), {})
        assert reading.people == ()
        assert 1 in reading.known


class TestTracking:
    """ByteTrack says which detection each track is, so keypoints stay put."""

    def test_the_detection_index_follows_the_person(self):
        pytest.importorskip("ultralytics")
        from ultralytics.engine.results import Boxes

        from vg.infer.tracking import PersonTracker

        tracker = PersonTracker(5.0)
        image = np.zeros((480, 640, 3), dtype=np.uint8)

        def boxes(rows):
            return Boxes(np.array(rows, dtype=np.float32).reshape(-1, 6), (480, 640))

        left, right = [100, 100, 200, 400, 0.9, 0], [300, 100, 400, 400, 0.8, 0]
        for _ in range(3):
            tracks = tracker.update(boxes([left, right]), image)
        ids = {t.index: t.track_id for t in tracks}
        # Same two people, handed over in the other order.
        tracks = tracker.update(boxes([right, left]), image)
        swapped = {t.index: t.track_id for t in tracks}
        assert swapped == {0: ids[1], 1: ids[0]}

    def test_an_empty_frame_ages_tracks_without_a_fault(self, caplog):
        pytest.importorskip("ultralytics")
        from vg.infer.tracking import PersonTracker

        tracker = PersonTracker(5.0)
        assert tracker.update(F._no_boxes(480, 640), np.zeros((480, 640, 3), np.uint8)) == []
        assert "tracker update failed" not in caplog.text


# ---------------------------------------------------------------------------
# end to end: frames in, an entry out — everything real but the pose model
# ---------------------------------------------------------------------------

class TestFramesToAnEntry:
    """ByteTrack, the timeline, the owner's network and the worker, together.

    Only the pose model is replaced, by one that returns the synthetic
    skeleton as ultralytics would: boxes plus keypoints in detection order.
    The pose weights are 22 MB and supplied out of band; everything after
    them is what this proves.
    """

    def detector(self, classifier):
        pytest.importorskip("ultralytics")
        import threading
        from ultralytics.engine.results import Boxes

        detector = F.FallDetector.__new__(F.FallDetector)
        detector.classifier = classifier
        detector.version = classifier.version
        detector.device = "cpu"
        detector._cameras = {}
        detector._cameras_lock = threading.Lock()

        def poses(image, kps_by_frame=self.script):
            kps = kps_by_frame.pop(0)
            x1, y1, x2, y2 = bbox_of(kps)
            boxes = Boxes(np.array([[x1, y1, x2, y2, 0.9, 0]], dtype=np.float32),
                          image.shape[:2])
            return boxes, kps[None].astype(np.float32)

        detector.poses = poses
        return detector

    def test_a_fall_on_camera_becomes_one_entry(self, classifier, tmp_path):
        from vg.events.falls import FallSceneStore
        from vg.features.falls import FallsWorker
        from vg.ingest.source import Frame

        sequence = fall_sequence(n_after=150)
        self.script = [sequence[i] for i in range(0, len(sequence), 6)]   # 5 fps
        frames = len(self.script)
        detector = self.detector(classifier)
        scenes = FallSceneStore(tmp_path / "falls.db")
        try:
            worker = FallsWorker(object(), detector, ["cam-a"], scenes)
            image = np.zeros((480, 640, 3), dtype=np.uint8)
            for n in range(frames):
                worker.analyse(Frame(camera_id="cam-a", image=image,
                                     captured_at=T0 + timedelta(seconds=n / 5),
                                     sequence=n))
            [scene] = scenes.recent(None)
            assert scene.running
            # Down from about 1.5 s; the clip ran 7 s, so past the 10 s rule
            # is not reached and nothing has been alerted yet.
            assert 1.0 <= (scene.started_at - T0).total_seconds() <= 3.0
            assert scene.alerted_at is None
            [box] = worker.down_on("cam-a")
            assert 0.0 <= box.x <= 1.0 and box.w > box.h, "a person lying down is wide"
        finally:
            scenes.close_db()
