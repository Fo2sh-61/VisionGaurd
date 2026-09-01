"""Weak crops are weak evidence, not no evidence.

Re-entering a frame guarantees a truncated crop -- the person arrives cut off
at an edge. Discarding those frames meant refusing to look at the exact moment
identification matters most. They are now usable for matching against a
stricter bar, but are never learned from.
"""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import BodySignature, IdentityStitcher, detection_quality
from loiterwatch.live import Detection

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
EMPTY = (30, 30, 30)
INSIDE = (200, 100, 320, 430)
EDGE = (-30, 100, 90, 430)        # cut off by the left edge
FAR_OUT = (-110, 100, 10, 430)    # almost entirely outside


def person(top=RED, bottom=BLUE, box=INSIDE):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    lo, hi = max(0, x1), min(640, x2)
    bh = y2 - y1
    if hi > lo:
        frame[y1:y1 + int(bh * 0.52), lo:hi] = top
        frame[y1 + int(bh * 0.52):y2, lo:hi] = bottom
    return frame


def det(track_id, box=INSIDE):
    return Detection(str(track_id), box, 0.9)


def seen_then_gone(st, top=RED, bottom=BLUE):
    known = st.update(person(top, bottom, INSIDE), [det(1, INSIDE)],
                      100.0).detections[0].track_id
    st.update(person(EMPTY, EMPTY), [], 105.0)
    return known


def stitcher(**kw):
    params = dict(max_gap_s=3600, min_similarity=0.48, margin=0.02)
    params.update(kw)
    return IdentityStitcher(BodySignature(), **params)


# -- the behaviour being fixed ---------------------------------------------
def test_a_truncated_re_entry_is_recognised():
    st = stitcher()
    known = seen_then_gone(st)
    back = st.update(person(RED, BLUE, EDGE), [det(2, EDGE)], 110.0)
    assert back.detections[0].track_id == known


def test_it_works_at_the_stricter_default_threshold_too():
    st = stitcher(min_similarity=0.60)
    known = seen_then_gone(st)
    back = st.update(person(RED, BLUE, EDGE), [det(2, EDGE)], 110.0)
    assert back.detections[0].track_id == known


def test_a_stranger_arriving_truncated_is_not_merged():
    """The precision half of the trade -- weak crops must not create merges."""
    st = stitcher()
    known = seen_then_gone(st)
    other = st.update(person(GREEN, BLACK, EDGE), [det(2, EDGE)], 110.0)
    assert other.detections[0].track_id != known
    assert st.merges == 0


def test_weak_crops_never_enter_the_gallery():
    """A truncated view would teach the wrong description of the person."""
    st = stitcher()
    st.update(person(RED, BLUE, INSIDE), [det(1, INSIDE)], 100.0)
    before = len(st.identities["p1"].gallery)
    for i in range(10):
        st.update(person(RED, BLUE, EDGE), [det(1, EDGE)], 101.0 + i)
    assert len(st.identities["p1"].gallery) == before


def test_a_weak_crop_needs_a_better_score_than_a_good_one():
    st = stitcher(min_similarity=0.48, low_quality_penalty=0.15)
    assert st.low_quality_penalty == pytest.approx(0.15)
    # a barely-similar person should clear the normal bar but not the weak one
    known = seen_then_gone(st)
    weak = st.update(person(GREEN, BLACK, EDGE), [det(2, EDGE)], 110.0)
    assert weak.detections[0].track_id != known


def test_crops_below_the_floor_are_still_ignored_entirely():
    st = stitcher(quality_floor=0.15)
    assert detection_quality((480, 640, 3), FAR_OUT, 0.9) < st.quality_floor
    known = seen_then_gone(st)
    result = st.update(person(RED, BLUE, FAR_OUT), [det(2, FAR_OUT)], 110.0)
    assert result.detections[0].track_id != known
    assert st.merges == 0


def test_the_floor_and_the_trust_line_are_different_thresholds():
    st = stitcher()
    assert st.quality_floor < st.min_quality, (
        "there must be a band where a crop can match but not teach")


def test_good_crops_are_unaffected():
    st = stitcher()
    known = seen_then_gone(st)
    back = st.update(person(RED, BLUE, INSIDE), [det(2, INSIDE)], 110.0)
    assert back.detections[0].track_id == known
    assert len(st.identities[known].gallery) >= 1
