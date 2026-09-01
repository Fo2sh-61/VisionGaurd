"""Cues are weighted by how well they separate the people actually seen.

A uniform defeats fixed weights: if everyone wears the same apron, the
upper-body cue agrees for all of them, contributing 0.45 of apparent
similarity while distinguishing nobody. Two colleagues then score 0.82 against
each other -- above any threshold that still allows a genuine re-entry -- and
one takes the other's ID.
"""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import (WEIGHT_LOWER, WEIGHT_SHAPE, WEIGHT_UPPER,
                                  BodySignature, IdentityStitcher, Signature,
                                  similarity)
from loiterwatch.live import Detection

BOX = (100, 60, 220, 420)
APRON = (230, 230, 235)
EMPTY = np.full((480, 640, 3), 30, dtype=np.uint8)

UNIFORMED = [(APRON, (90, 60, 40)), (APRON, (70, 70, 75)), (APRON, (40, 90, 140)),
             (APRON, (120, 40, 40)), (APRON, (30, 110, 60))]
VARIED = [((40, 40, 200), (200, 60, 40)), ((60, 180, 60), (20, 20, 20)),
          ((200, 200, 60), (60, 20, 120)), ((20, 120, 220), (220, 220, 220)),
          ((120, 20, 180), (40, 140, 40))]


def person(top, bottom, box=BOX):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=BOX):
    return Detection(str(track_id), box, 0.9)


def stitcher(adaptive=True, **kw):
    params = dict(max_gap_s=9999, min_similarity=0.55, adaptive_weights=adaptive,
                  min_population=3, weights_refresh_s=0.0)
    params.update(kw)
    return IdentityStitcher(BodySignature(), **params)


def walk_through(st, outfits, frames=3):
    """Each person passes the camera once, in turn."""
    ids, t = [], 100.0
    for i, outfit in enumerate(outfits):
        for k in range(frames):
            result = st.update(person(*outfit), [det(i)], t + k, camera="cam1")
        ids.append(result.detections[0].track_id)
        st.update(EMPTY, [], t + 8, camera="cam1")
        t += 20
    return ids


# -- the statistic ----------------------------------------------------------
def test_a_uniform_cue_is_weighted_toward_zero():
    st = stitcher()
    walk_through(st, UNIFORMED)
    weights = st.cue_weights(1000.0)
    assert weights is not None
    upper, lower, _ = weights
    assert upper < 0.05, "an identical apron distinguishes nobody"
    assert lower > upper, "the trousers must carry the decision"


def test_varied_clothing_keeps_both_colour_cues():
    st = stitcher()
    walk_through(st, VARIED)
    upper, lower, _ = st.cue_weights(1000.0)
    assert upper > 0.2 and lower > 0.2


def test_build_is_down_weighted_because_everyone_is_person_shaped():
    """shape_similarity returns ~1.0 for almost any pair, so at a fixed weight
    it is a constant floor of agreement between strangers -- and the floor
    rises when another cue collapses, since the score is renormalised."""
    st = stitcher()
    walk_through(st, UNIFORMED)
    _, _, shape = st.cue_weights(1000.0)
    assert shape < WEIGHT_SHAPE


def test_defaults_are_used_until_enough_people_are_known():
    st = stitcher(min_population=4)
    st.update(person(*UNIFORMED[0]), [det(1)], 100.0, camera="cam1")
    assert st.cue_weights(101.0) is None


def test_the_statistic_can_be_switched_off():
    st = stitcher(adaptive=False)
    walk_through(st, UNIFORMED)
    assert st.cue_weights(1000.0) is None


# -- the outcome it exists for ---------------------------------------------
def test_uniformed_staff_are_kept_apart_far_better():
    fixed = stitcher(adaptive=False)
    adaptive = stitcher(adaptive=True)
    before = len(set(walk_through(fixed, UNIFORMED)))
    after = len(set(walk_through(adaptive, UNIFORMED)))
    assert before == 1, "fixed weights collapse the whole shift into one ID"
    assert after >= 4, "adaptive weighting must recover most of them"


def test_varied_clothing_does_not_regress():
    fixed = len(set(walk_through(stitcher(adaptive=False), VARIED)))
    adaptive = len(set(walk_through(stitcher(adaptive=True), VARIED)))
    assert fixed == adaptive == 5


def test_a_returning_person_still_matches_themselves():
    """The correction must not overshoot into refusing every re-entry."""
    st = stitcher()
    walk_through(st, UNIFORMED)
    t = 1000.0
    left = st.update(person(*UNIFORMED[1]), [det(50)], t,
                     camera="cam1").detections[0].track_id
    st.update(EMPTY, [], t + 10, camera="cam1")
    back = st.update(person(*UNIFORMED[1]), [det(51)], t + 40,
                     camera="cam1").detections[0].track_id
    assert back == left


# -- the population sample --------------------------------------------------
def test_the_sample_ignores_near_duplicates():
    """One person standing still must not flood the statistic."""
    st = stitcher()
    for i in range(200):
        st.update(person(*UNIFORMED[0]), [det(1)], 100.0 + i, camera="cam1")
    assert len(st._population) <= 2


def test_the_sample_is_bounded():
    st = stitcher()
    st.population_size = 5
    for i, outfit in enumerate(VARIED * 4):
        st.update(person(*outfit), [det(i)], 100.0 + i, camera="cam1")
    assert len(st._population) <= 5


def test_the_sample_comes_from_observations_not_identities():
    """It must not depend on the matching it exists to correct: a uniform
    merges everyone into one identity, so an identity-derived population would
    never reach the size that triggers the fix."""
    st = stitcher()
    walk_through(st, UNIFORMED)
    assert len(st.identities) < len(st._population)


def test_weights_are_cached_between_refreshes():
    st = stitcher(weights_refresh_s=100.0)
    walk_through(st, UNIFORMED)
    first = st.cue_weights(1000.0)
    st._population.clear()
    assert st.cue_weights(1001.0) == first


# -- the scoring function ---------------------------------------------------
def test_custom_weights_change_the_score():
    a = BodySignature().signature(person(APRON, (90, 60, 40)), BOX)
    b = BodySignature().signature(person(APRON, (30, 110, 60)), BOX)
    default = similarity(a, b)
    lower_only = similarity(a, b, weights=(0.0, WEIGHT_LOWER, 0.0))
    assert lower_only < default, "ignoring the shared apron must separate them"


def test_zero_total_weight_is_not_a_divide_by_zero():
    a = BodySignature().signature(person(APRON, (90, 60, 40)), BOX)
    b = BodySignature().signature(person(APRON, (30, 110, 60)), BOX)
    assert similarity(a, b, weights=(0.0, 0.0, 0.0)) is None


def test_shape_alone_still_never_matches():
    a = Signature(aspect=3.0)
    b = Signature(aspect=3.0)
    assert similarity(a, b, weights=(0.45, 0.35, 0.20)) is None
