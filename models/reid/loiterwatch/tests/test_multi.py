"""Several cameras in one process: shared identities, separate tracker IDs."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch import parse_config
from loiterwatch.identity import BodySignature, IdentityStitcher
from loiterwatch.live import Detection
from loiterwatch.multi import CameraSpec, parse_camera_arg, run_multi

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
BOX = (100, 60, 220, 420)


def person_frame(top=RED, bottom=BLUE, box=BOX, size=(480, 640)):
    frame = np.full((size[0], size[1], 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=BOX):
    return Detection(str(track_id), box, 0.9)


class FixedDetector:
    """Always reports the same person, with a fixed tracker ID."""

    def __init__(self, track_id="1", box=BOX):
        self.track_id, self.box = track_id, box
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return [det(self.track_id, self.box)]


def frames(n, top=RED, bottom=BLUE, box=BOX):
    for _ in range(n):
        yield person_frame(top, bottom, box)


def clock_from(start=1_770_000_000.0, step=0.1):
    state = {"t": start}

    def tick():
        state["t"] += step
        return state["t"]
    return tick


# -- argument parsing -------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("laptop=0", ("laptop", 0)),
    ("ipcam=rtsp://h/s", ("ipcam", "rtsp://h/s")),
    ("0", ("cam_0", 0)),
    ("  front = 1 ", ("front", 1)),
])
def test_parse_camera_arg(raw, expected):
    assert parse_camera_arg(raw) == expected


# -- the core reason this exists -------------------------------------------
def test_both_cameras_calling_a_person_track_1_are_not_confused():
    """Every tracker numbers its own people from 1. Without namespacing, the
    two feeds' 'track 1' would collapse into a single person."""
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6)
    red = person_frame(RED, BLUE)
    green = person_frame(GREEN, BLACK)

    a = stitcher.update(red, [det(1)], 100.0, camera="cam_a")
    b = stitcher.update(green, [det(1)], 100.0, camera="cam_b")

    assert a.detections[0].track_id != b.detections[0].track_id
    assert stitcher.merges == 0


def test_the_same_person_on_two_cameras_at_once_shares_one_id():
    """Overlapping views: the anti-jitter delay must not block a cross-camera
    match, or a person straddling two feeds becomes two people."""
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6, min_absence_s=5.0)
    frame = person_frame(RED, BLUE)

    # an identity another camera is holding is claimed over several agreeing
    # observations, not off one frame -- a tenth of a second at 30fps
    for i in range(4):
        a = stitcher.update(frame, [det(1)], 100.0 + i, camera="cam_a")
        b = stitcher.update(frame, [det(1)], 100.0 + i, camera="cam_b")

    assert b.detections[0].track_id == a.detections[0].track_id
    assert stitcher.merges >= 1


def test_the_jitter_delay_still_applies_within_one_camera():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6, min_absence_s=5.0)
    frame = person_frame(RED, BLUE)
    stitcher.update(frame, [det(1)], 100.0, camera="cam_a")
    result = stitcher.update(frame, [det(2)], 100.2, camera="cam_a")
    assert stitcher.merges == 0
    assert result.detections[0].track_id != "p1"


def test_walking_from_one_camera_to_the_other_keeps_the_id():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6)
    frame = person_frame(RED, BLUE)

    first = stitcher.update(frame, [det(1)], 100.0, camera="cam_a")
    stable = first.detections[0].track_id
    stitcher.update(person_frame(BLACK, BLACK), [], 110.0, camera="cam_a")

    later = stitcher.update(frame, [det(1)], 130.0, camera="cam_b")
    assert later.detections[0].track_id == stable


def test_different_mounting_angles_do_not_block_a_cross_camera_match():
    """A webcam sees you head-on and tall; a ceiling camera sees you squat.
    Build must not be scored across cameras or the colour match is buried."""
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.60)
    tall = (100, 40, 180, 440)      # aspect 5.0, eye-level view
    squat = (100, 150, 300, 400)    # aspect 1.25, overhead view

    a = stitcher.update(person_frame(RED, BLUE, tall), [det(1, tall)],
                        100.0, camera="laptop")
    b = stitcher.update(person_frame(RED, BLUE, squat), [det(1, squat)],
                        130.0, camera="ipcam")

    assert b.detections[0].track_id == a.detections[0].track_id
    assert stitcher.merges == 1


def test_build_still_counts_within_a_single_camera():
    """Same camera, same angle: a very different build is real evidence."""
    from loiterwatch.identity import similarity

    tall = BodySignature().signature(person_frame(RED, BLUE, (100, 40, 180, 440)),
                                     (100, 40, 180, 440))
    squat = BodySignature().signature(person_frame(RED, BLUE, (100, 150, 300, 400)),
                                      (100, 150, 300, 400))
    with_shape = similarity(tall, squat, use_shape=True)
    without = similarity(tall, squat, use_shape=False)
    assert with_shape < without, "shape must penalise mismatched build"


def test_cross_camera_threshold_defaults_below_the_same_camera_one():
    stitcher = IdentityStitcher(min_similarity=0.60)
    assert stitcher.cross_min_similarity == pytest.approx(0.50)


def test_cross_camera_threshold_can_be_set_explicitly():
    stitcher = IdentityStitcher(min_similarity=0.60, cross_min_similarity=0.42)
    assert stitcher.cross_min_similarity == pytest.approx(0.42)


def test_probation_stays_open_long_enough_for_the_other_camera():
    """Camera B may see someone before camera A has learned them. Freezing the
    ID after five frames -- a sixth of a second -- gives no second chance."""
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.60, probation_samples=2,
                                probation_window_s=5.0)
    frame = person_frame(RED, BLUE)

    # camera B sees a stranger first, over many frames
    for i in range(10):
        stitcher.update(frame, [det(1)], 100.0 + i * 0.1, camera="ipcam")
    assert stitcher.merges == 0

    # camera A now sees the same person; still within the probation window,
    # so B's track can still be corrected onto A's identity -- or vice versa
    for i in range(3):
        result = stitcher.update(frame, [det(1)], 101.5 + i * 0.1,
                                 camera="laptop")
    assert stitcher.merges == 1
    assert result.detections[0].track_id in stitcher.identities


def test_probation_does_eventually_close():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.60, probation_samples=2,
                                probation_window_s=1.0)
    frame = person_frame(RED, BLUE)
    for i in range(20):
        stitcher.update(frame, [det(1)], 100.0 + i * 0.5, camera="ipcam")
    assert stitcher._probation == {}


def test_last_best_reports_the_closest_candidate_for_tuning():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.99, cross_min_similarity=0.99)
    stitcher.update(person_frame(RED, BLUE), [det(1)], 100.0, camera="a")
    stitcher.update(person_frame(GREEN, BLACK), [det(1)], 130.0, camera="b")
    assert stitcher.last_best is not None
    score, who = stitcher.last_best
    assert 0.0 <= score <= 1.0 and who.startswith("p")


# -- the loop ---------------------------------------------------------------
def _config(threshold=0.3):
    return parse_config({
        "exit_grace_s": 3, "tick_s": 0.1,
        "rules": [{"id": "intr", "type": "intrusion", "confirm_s": threshold,
                   "min_observations": 2, "cooldown_s": 5}],
    })


def test_run_multi_drives_every_camera():
    cams = [
        CameraSpec("cam_a", detector=FixedDetector("1"), frame_source=frames(15)),
        CameraSpec("cam_b", detector=FixedDetector("1"), frame_source=frames(15)),
    ]
    run_multi(_config(), cams, window=False, clock=clock_from(), play_alarm=False)
    assert cams[0].detector.calls == 15
    assert cams[1].detector.calls == 15


def test_alerts_are_tagged_with_the_camera_that_raised_them():
    cams = [
        CameraSpec("front_door", detector=FixedDetector("1"),
                   frame_source=frames(30)),
        CameraSpec("atm", detector=FixedDetector("1"), frame_source=frames(30)),
    ]
    engine = run_multi(_config(), cams, window=False, clock=clock_from(),
                       play_alarm=False)
    zones = {a.zone for a in engine.alerts}
    assert zones and zones <= {"front_door", "atm"}


def test_one_dead_camera_does_not_stop_the_other():
    cams = [
        CameraSpec("good", detector=FixedDetector("1"), frame_source=frames(12)),
        CameraSpec("dead", detector=FixedDetector("1"), frame_source=iter([])),
    ]
    run_multi(_config(), cams, window=False, clock=clock_from(), play_alarm=False)
    assert cams[0].detector.calls == 12


def test_shared_stitcher_gives_one_person_one_id_across_both_feeds():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6, min_absence_s=0.0)
    cams = [
        CameraSpec("cam_a", detector=FixedDetector("1"), frame_source=frames(20)),
        CameraSpec("cam_b", detector=FixedDetector("1"), frame_source=frames(20)),
    ]
    run_multi(_config(), cams, stitcher=stitcher, window=False,
              clock=clock_from(), play_alarm=False)
    # one person, seen by both cameras, must not become two identities
    assert len(stitcher.identities) == 1


def test_two_different_people_on_two_cameras_stay_separate():
    stitcher = IdentityStitcher(BodySignature(), max_gap_s=9999,
                                min_similarity=0.6, min_absence_s=0.0)
    cams = [
        CameraSpec("cam_a", detector=FixedDetector("1"),
                   frame_source=frames(20, RED, BLUE)),
        CameraSpec("cam_b", detector=FixedDetector("1"),
                   frame_source=frames(20, GREEN, BLACK)),
    ]
    run_multi(_config(), cams, stitcher=stitcher, window=False,
              clock=clock_from(), play_alarm=False)
    assert len(stitcher.identities) == 2
    assert stitcher.merges == 0


def test_alerts_are_logged_with_zone(tmp_path):
    import json
    log = tmp_path / "alerts.jsonl"
    cams = [CameraSpec("cam_a", detector=FixedDetector("1"),
                       frame_source=frames(30))]
    run_multi(_config(), cams, window=False, clock=clock_from(),
              play_alarm=False, log_path=str(log))
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows and rows[0]["zone"] == "cam_a"


def test_no_openable_camera_is_a_clear_error():
    cams = [CameraSpec("nope", source="/definitely/not/a/camera")]
    with pytest.raises(SystemExit):
        run_multi(_config(), cams, window=False, clock=clock_from())


# -- CLI parity with `live` -------------------------------------------------
def test_multi_requires_config_or_no_rules(capsys):
    from loiterwatch.cli import main
    assert main(["multi", "--camera", "a=0", "--no-window"]) == 1
    assert "no-rules" in capsys.readouterr().err


def test_multi_accepts_no_rules_without_a_config():
    from loiterwatch.cli import build_parser
    args = build_parser().parse_args(
        ["multi", "--no-rules", "--camera", "laptop=0", "--camera", "ip=rtsp://x/1"])
    assert args.config is None and args.no_rules
    assert args.camera == ["laptop=0", "ip=rtsp://x/1"]


def test_multi_rejects_duplicate_camera_names(capsys):
    from loiterwatch.cli import main
    code = main(["multi", "--no-rules", "--camera", "a=0", "--camera", "a=1",
                 "--no-window"])
    assert code == 1
    assert "duplicate camera name" in capsys.readouterr().err
