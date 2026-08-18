"""Identity stitching: a person who steps out and back keeps their clock."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch import parse_config
from loiterwatch.identity import ColorHistogram, IdentityStitcher, cosine
from loiterwatch.live import Detection, run

BOX = (100, 80, 220, 400)
OTHER_BOX = (400, 80, 520, 400)

RED = (40, 40, 200)      # BGR
BLUE = (200, 60, 40)


def frame_with(*people, size=(480, 640)):
    """people = (box, bgr_color) pairs painted onto a dark frame."""
    frame = np.full((size[0], size[1], 3), 30, dtype=np.uint8)
    for box, color in people:
        x1, y1, x2, y2 = box
        frame[y1:y2, x1:x2] = color
    return frame


def det(track_id, box=BOX, conf=0.9):
    return Detection(str(track_id), box, conf)


def test_signature_is_stable_for_the_same_person():
    hist = ColorHistogram()
    a = hist.signature(frame_with((BOX, RED)), BOX)
    b = hist.signature(frame_with((BOX, RED)), BOX)
    assert cosine(a, b) > 0.99


def test_signature_separates_different_clothing():
    hist = ColorHistogram()
    red = hist.signature(frame_with((BOX, RED)), BOX)
    blue = hist.signature(frame_with((BOX, BLUE)), BOX)
    assert cosine(red, blue) < 0.3


def test_same_raw_id_keeps_one_stable_id():
    st = IdentityStitcher()
    frame = frame_with((BOX, RED))
    first = st.update(frame, [det(7)], 100.0).detections[0].track_id
    second = st.update(frame, [det(7)], 101.0).detections[0].track_id
    assert first == second
    assert st.merges == 0


def test_person_who_leaves_and_returns_gets_the_same_identity():
    """The bug this exists to fix: tracker hands out ID 2, we hand back p1."""
    st = IdentityStitcher(max_gap_s=120, min_similarity=0.7)
    frame = frame_with((BOX, RED))
    stable_before = st.update(frame, [det(1)], 100.0).detections[0].track_id

    st.update(frame_with(), [], 110.0)            # gone for 20s

    result = st.update(frame, [det(2)], 120.0)    # tracker gives a brand new ID
    assert result.detections[0].track_id == stable_before
    assert result.relinked == {stable_before: "1"}
    assert st.merges == 1


def test_a_differently_dressed_person_is_not_merged():
    st = IdentityStitcher(max_gap_s=120, min_similarity=0.7)
    red_id = st.update(frame_with((BOX, RED)), [det(1)], 100.0).detections[0].track_id
    st.update(frame_with(), [], 110.0)
    blue_id = st.update(frame_with((BOX, BLUE)), [det(2)], 120.0).detections[0].track_id
    assert blue_id != red_id
    assert st.merges == 0


def test_two_people_on_screen_together_are_never_merged():
    """Even in identical clothing -- being simultaneously visible settles it."""
    st = IdentityStitcher(min_similarity=0.1)   # deliberately eager
    frame = frame_with((BOX, RED), (OTHER_BOX, RED))
    result = st.update(frame, [det(1, BOX), det(2, OTHER_BOX)], 100.0)
    ids = {d.track_id for d in result.detections}
    assert len(ids) == 2
    assert st.merges == 0


def test_returning_after_the_memory_window_is_a_new_person():
    st = IdentityStitcher(max_gap_s=30, min_similarity=0.7)
    frame = frame_with((BOX, RED))
    first = st.update(frame, [det(1)], 100.0).detections[0].track_id
    st.update(frame_with(), [], 140.0)
    second = st.update(frame, [det(2)], 200.0).detections[0].track_id
    assert second != first


def test_instant_reappearance_is_left_to_exit_grace_not_stitching():
    st = IdentityStitcher(min_absence_s=2.0, min_similarity=0.7)
    frame = frame_with((BOX, RED))
    st.update(frame, [det(1)], 100.0)
    result = st.update(frame, [det(2)], 100.2)   # 0.2s later, same appearance
    assert st.merges == 0
    assert result.detections[0].track_id != "p1"


class StubAppearance:
    """Returns a scripted sequence of signatures, including None (no crop)."""

    def __init__(self, signatures):
        self._sigs = list(signatures)

    def signature(self, frame, box):
        return self._sigs.pop(0) if self._sigs else None


def test_an_identity_created_without_a_usable_crop_does_not_crash_on_later_match():
    """Regression: a person at the frame edge yields no crop (signature=None) on
    creation. A later, fully-visible person must not crash trying to compare a
    512-d histogram against that missing signature."""
    vec = np.zeros(512, dtype=np.float32)
    vec[0] = 1.0
    appearance = StubAppearance([None, vec])
    st = IdentityStitcher(appearance, max_gap_s=120, min_similarity=0.7,
                          min_absence_s=0.5)

    st.update(frame_with(), [det(1)], 100.0)      # no crop -> signature=None
    st.update(frame_with(), [], 110.0)             # departs

    result = st.update(frame_with((BOX, RED)), [det(2)], 120.0)  # full crop
    assert st.merges == 0                          # correctly not matched
    assert result.detections[0].track_id != "p1"


def test_identities_are_pruned_and_do_not_grow_without_bound():
    st = IdentityStitcher(max_gap_s=5, memory=8)
    for i in range(40):
        st.update(frame_with((BOX, RED)), [det(i)], 100.0 + i * 10)
    assert len(st.identities) <= 8


def test_dwell_survives_a_re_entry_end_to_end():
    """Without stitching the second visit restarts the clock and never alerts."""
    config = parse_config({
        "exit_grace_s": 1, "tick_s": 0.1,
        "rules": [{"id": "i", "type": "cumulative_dwell", "threshold_s": 4.0,
                   "window_s": 60, "cooldown_s": 1}],
    })

    class Scripted:
        """Present, then absent, then back with a different tracker ID."""

        def __init__(self):
            self.n = 0

        def detect(self, frame):
            self.n += 1
            if self.n <= 20:
                return [det(1)]
            if self.n <= 40:
                return []
            return [det(2)]

    def frames():
        for i in range(70):
            yield frame_with((BOX, RED)) if (i < 20 or i >= 40) else frame_with()

    def clock(start=[1_770_000_000.0]):
        start[0] += 0.1
        return start[0]

    stitched = run(config, Scripted(), window=False, camera="cam",
                   frame_source=frames(), clock=clock,
                   stitcher=IdentityStitcher(max_gap_s=60, min_similarity=0.7,
                                             min_absence_s=0.5))
    assert stitched.alerts, "re-linked visits should sum past the 4s threshold"

    def clock2(start=[1_770_000_000.0]):
        start[0] += 0.1
        return start[0]

    plain = run(config, Scripted(), window=False, camera="cam",
                frame_source=frames(), clock=clock2, stitcher=None)
    assert plain.alerts == [], "without stitching the clock resets on re-entry"
