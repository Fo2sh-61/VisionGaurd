"""Cinematic simulated demo: face boxes, scripted names, re-linking, demo clock, caption."""

from types import SimpleNamespace

import cv2
import numpy as np

import demo_cinematic as dc
from attendance import cinematic as C
from attendance.recognise import Register


def kps(eyes_dx=20.0, cx=200.0, cy=120.0, conf=0.9):
    k = np.zeros((17, 3), np.float32)
    k[0] = (cx, cy + eyes_dx * 0.6, conf)
    k[1] = (cx + eyes_dx / 2, cy, conf)
    k[2] = (cx - eyes_dx / 2, cy, conf)
    return k


def test_face_box_needs_a_face_turned_to_camera():
    x, y, w, h = C.face_box(kps())
    assert abs(x + w / 2 - 200) < 8 and h == 60.0 and w < h
    away = kps()
    away[0, 2] = 0.1                                   # nose not seen: walking away
    assert C.face_box(away) is None
    assert C.face_box(kps(eyes_dx=4)) is None          # far too small to be a face worth boxing


def test_names_in_order_then_employees_and_visitors():
    q = C.NameQueue(["Anna", "?"], unknown_every=3)
    got = [q.next() for _ in range(6)]
    assert got[:2] == ["Anna", "?"] and got[2] == "?"                # 3rd person is every-3rd -> visitor
    assert got[3] == "Employee 03" and got[4] == "Employee 04"
    assert got[5] == "?"


def test_tracks_lock_after_a_few_frames_and_relink_after_id_switch():
    ct = C.CineTracks(C.NameQueue(["Anna"]), lock_frames=3)
    box = (100.0, 100.0, 60.0, 74.0)
    for i in range(3):
        (t,) = ct.update(i, [(7, box)])
    assert t.name == "Anna" and t.locked_frame == 2
    ct.update(3, [])                                                 # tracker drops the id...
    (t2,) = ct.update(4, [(99, (104.0, 102.0, 60.0, 74.0))])         # ...and renames the person nearby
    assert t2.name == "Anna" and ct.queue.count == 1                 # same person, same name, no new script entry
    (far,) = ct.update(5, [(55, (900.0, 100.0, 60.0, 74.0))])
    assert far.name is None                                          # a different spot is a new person


def test_demo_clock_speed():
    reg = Register({}, "07:57:30", "08:00", rate=25.0)
    reg.names["a"] = "A"
    assert reg.clock_at(2.0) == 7 * 3600 + 57 * 60 + 30 + 50
    assert reg.mark("a", 8.0, 1, 1.0).status == "late"               # 07:57:30 + 200 s = 08:00:50


class FakeEstimator:
    def __init__(self, per_frame):
        self.per_frame, self.i = per_frame, 0

    def reset(self):
        self.i = 0

    def __call__(self, frame):
        out = self.per_frame[min(self.i, len(self.per_frame) - 1)]
        self.i += 1
        return out


def frames_dir(tmp_path, n):
    d = tmp_path / "f"
    d.mkdir()
    for i in range(n):
        cv2.imwrite(str(d / f"{i:03d}.png"), np.full((540, 960, 3), 90, np.uint8))
    return d


def test_render_marks_everyone_scripted_and_keeps_caption(tmp_path):
    a = SimpleNamespace(track_id=1, keypoints=kps(cx=300), bbox=(0, 0, 1, 1))
    b = SimpleNamespace(track_id=2, keypoints=kps(cx=700), bbox=(0, 0, 1, 1))
    per_frame = [[a]] * 8 + [[a, b]] * 30
    res = dc.render_cinematic(frames_dir(tmp_path, len(per_frame)), tmp_path / "o.mp4", FakeEstimator(per_frame),
                              "Test", names=["Anna", "?"], clock="07:59:50", rate=10.0, end_hold_s=0.5)
    assert res["simulated"] is True and res["present"] == 1 and res["unknown"] == 1
    assert res["arrivals"]["Anna"]["status"] in ("on_time", "late")
    assert res["size"] == (1920, 1080)
    cap = cv2.VideoCapture(str(tmp_path / "o.mp4"))
    ok, frame = cap.read()
    ok, frame = (cap.read() if ok else (False, None))
    strip = frame[int(1080 * 0.93):int(1080 * 0.97), 600:1320]       # where the caption sits: amber text
    amber = (strip[..., 2] > 180) & (strip[..., 1] > 120) & (strip[..., 0] < 90)
    assert amber.any(), "the SIMULATED caption must be on every frame"
