"""Attendance demo logic: matching, naming, register, and the QA check."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import demo_attendance as da
from attendance import recognise as r


def unit(seed, dim=128):
    v = np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def near(v, noise, seed):
    w = v + noise * np.random.default_rng(seed).normal(size=v.shape).astype(np.float32)
    return w / np.linalg.norm(w)


def test_gallery_threshold_margin_and_empty():
    g = r.Gallery(threshold=0.6, margin=0.1)
    assert g.match(unit(1)).reason == "gallery is empty"
    g.add("a", "Anna", unit(1))
    assert g.match(near(unit(1), 0.05, 2)).person_id == "a"
    stranger = g.match(unit(99))
    assert stranger.person_id is None and stranger.reason == "below threshold"
    g.add("b", "Bo", near(unit(1), 0.6, 3))                 # a look-alike of Anna
    close = g.match(unit(1))
    assert close.person_id in (None, "a")
    if close.person_id is None:
        assert close.reason == "too close to call"


def test_best_vector_per_person_counts():
    g = r.Gallery(0.6, 0.1)
    for k in range(3):
        g.add("a", "Anna", unit(10 + k))
    assert g.photo_count("a") == 3 and g.match(unit(11)).person_id == "a"


def test_matches_visionguard_rule_exactly_when_available(tmp_path):
    pytest.importorskip("cv2")
    if not (r.VG_ENGINE_DIR / "vg").is_dir():
        pytest.skip("VisionGuard engine not found")
    import sys
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(r.VG_ENGINE_DIR))
    from vg.identity.gallery import FaceGallery
    from vg.infer.faces import MIN_FACE_PIXELS, SFACE_COSINE_THRESHOLD
    assert (r.GALLERY_THRESHOLD, r.GALLERY_MARGIN, r.MIN_FACE_PIXELS) == (
        SFACE_COSINE_THRESHOLD, FaceGallery.DEFAULT_MARGIN, MIN_FACE_PIXELS)
    vg = FaceGallery(tmp_path / "g.db", "sface-2021dec", r.IDENTITY_SCORE, r.IDENTITY_MARGIN)
    mine = r.Gallery()
    for pid, seed in (("a", 1), ("b", 2), ("c", 3)):
        vg.add_person(pid, pid.upper())
        for k in range(3):
            v = near(unit(seed), 0.3, seed * 10 + k)
            vg.add_embedding(pid, v, "sface-2021dec")
            mine.add(pid, pid.upper(), v)
    for q in [near(unit(1), 0.3, 50), near(unit(2), 0.5, 51), unit(77), near(unit(3), 0.9, 52)]:
        a, b = vg.match(q), mine.match(q)
        assert (a.person.id if a.person else None) == b.person_id and a.score == pytest.approx(b.score, abs=1e-5)


def test_a_name_needs_repeated_looks_and_never_flips_on_one_frame():
    tr = r.FaceTracks(confirm=2, window=6)
    box = (100, 100, 90, 90)
    hit, miss = r.Match("a", 0.8), r.Match(None, 0.3)
    named = []
    for i, m in enumerate([miss, hit, miss, hit, hit, miss, miss, miss, miss, miss, miss]):
        ((t, _),) = tr.update(i, [(box, m)])
        named.append(t.person_id)
    assert named[:3] == [None, None, None] and named[3] == "a"          # second matching look names it
    assert named[-1] is None                                           # evidence ages out
    ((t, _),) = tr.update(20, [((600, 100, 90, 90), hit)])               # a new face is a new track
    assert t.person_id is None and len(tr.tracks) == 2 or t.id != 1


def test_two_faces_stay_separate_tracks():
    tr = r.FaceTracks()
    out = tr.update(0, [((50, 50, 80, 80), r.Match("a", 0.9)), ((300, 60, 80, 80), r.Match(None, 0.2))])
    out2 = tr.update(1, [((52, 50, 80, 80), r.Match("a", 0.9)), ((302, 60, 80, 80), r.Match(None, 0.2))])
    assert [t.id for t, _ in out] == [t.id for t, _ in out2] and out[0][0].id != out[1][0].id


def test_register_on_time_late_and_hours():
    reg = r.Register({"a": "Anna", "b": "Bo", "c": "Cy"}, clock_start="07:58:00", cutoff="08:00")
    e = reg.mark("a", 30, 10, 0.8)
    assert e.status == "on_time" and e.minutes_late is None and r.fmt_clock(e.clock_s) == "07:58:30"
    assert reg.mark("a", 40, 11, 0.9) is None                           # first sighting only
    late = reg.mark("b", 150, 12, 0.8)                                  # 08:00:30 -> 1 minute late
    assert late.status == "late" and late.minutes_late == 1
    assert reg.mark("zed", 1, 1, 0.9) is None                           # not enrolled: never recorded
    night = r.Register({"a": "Anna"}, clock_start="17:30:00")
    assert night.mark("a", 5, 1, 0.9) is None and night.present == 0    # outside hours: not an arrival
    assert night.seen_outside_hours == {"a"}
    assert r.minutes_late(r.parse_clock("08:14:10"), r.parse_clock("08:00")) == 15
    with pytest.raises(ValueError):
        r.parse_clock("8")


class FakePipeline:
    """Stands in for VisionGuard's FacePipeline: one scripted face per frame."""

    def __init__(self, script):
        self.script, self.i = script, 0
        self.detector = SimpleNamespace(detect=lambda frame, min_size=80: [
            SimpleNamespace(x=100, y=80, w=96, h=96)] if self.script[min(self.i - 1, len(self.script) - 1)] is not None else [])

    def observe(self, frame, max_faces=8, min_size=80):
        emb = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if emb is None:
            return []
        return [SimpleNamespace(face=SimpleNamespace(x=100, y=80, w=96, h=96), embedding=emb)]


def write_frames(folder, n):
    folder.mkdir(parents=True)
    for i in range(n):
        cv2.imwrite(str(folder / f"f-{i:03d}.png"), np.full((240, 320, 3), 90, np.uint8))
    return folder


def test_end_to_end_marks_only_the_enrolled_and_blurs_the_stranger(tmp_path):
    g = r.Gallery()
    g.add("anna", "Anna", unit(1))
    me, stranger = near(unit(1), 0.05, 5), unit(42)
    script = [None] * 5 + [me] * 20 + [None] * 5 + [stranger] * 20
    reg = r.Register(g.names, "07:52:00", "08:00")
    rep = da.render_attendance(write_frames(tmp_path / "f", len(script)), tmp_path / "o.mp4",
                               FakePipeline(script), g, reg, "Test", blur_unknown=True, end_hold_s=0)
    assert list(rep["arrivals"]) == ["Anna"] and rep["arrivals"]["Anna"]["status"] == "on_time"
    assert rep["unknown_face_looks"] >= 15                              # the stranger was never named
    assert rep["size"][1] == 720 and rep["size"][0] > 720
    assert da.check_expected(rep, ["Anna"], g.names.values()) == []
    assert da.check_expected(rep, ["Anna", "Bo"], g.names.values())     # Bo expected but absent / not enrolled
    assert da.check_expected(rep, [], g.names.values()) == ["Anna was named but not expected"]


def test_nobody_enrolled_means_nobody_named(tmp_path):
    g = r.Gallery()
    script = [unit(3)] * 20
    rep = da.render_attendance(write_frames(tmp_path / "f", 20), tmp_path / "o.mp4", FakePipeline(script), g,
                               r.Register(g.names), end_hold_s=0)
    assert rep["arrivals"] == {}


def test_blur_region_changes_only_the_face_area():
    img = np.random.default_rng(0).integers(0, 255, (200, 300, 3), dtype=np.uint8)
    from attendance.render import blur_region
    before = img.copy()
    blur_region(img, 100, 60, 60, 60, pad=0)
    assert not np.array_equal(img[60:120, 100:160], before[60:120, 100:160])
    assert np.array_equal(img[:50], before[:50]) and np.array_equal(img[:, :90], before[:, :90])


class LocateOnlyPipeline:
    """Finds faces by script and fails the test if anything tries to recognise them."""

    def __init__(self, boxes_by_call):
        self.boxes, self.calls = boxes_by_call, 0
        self.detector = SimpleNamespace(detect=self._detect)

    def _detect(self, frame, min_size=80):
        boxes = self.boxes[min(self.calls, len(self.boxes) - 1)]
        self.calls += 1
        return [SimpleNamespace(x=x, y=y, w=w, h=h) for x, y, w, h in boxes]

    def observe(self, *a, **k):
        raise AssertionError("simulation must not run recognition")


def test_simulation_names_faces_in_order_and_never_recognises(tmp_path):
    left, right = [(60, 60, 90, 90)], [(220, 70, 90, 90)]
    script = [left] * 14 + [[]] * 20 + [right] * 14
    g = r.Gallery()
    for n in ("Anna", "Bo"):
        g.names[n] = n
    rep = da.render_attendance(write_frames(tmp_path / "f", len(script)), tmp_path / "o.mp4", LocateOnlyPipeline(script),
                               g, r.Register(g.names, "07:50:00", "08:00"), "T", simulate=["Anna", "?"], end_hold_s=0)
    assert rep["simulated"] is True
    assert list(rep["arrivals"]) == ["Anna"]                 # second face is the scripted "?" -> Unknown, no entry
    assert rep["unknown_face_looks"] >= 2
    real = da.render_attendance(write_frames(tmp_path / "g", 3), tmp_path / "p.mp4", FakePipeline([None] * 3),
                                r.Gallery(), r.Register({}), end_hold_s=0)
    assert real["simulated"] is False                         # real runs are never marked simulated
