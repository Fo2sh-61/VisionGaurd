"""Operator correction: 'that is the wrong person, try again'."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import BodySignature, Identity, IdentityStitcher
from loiterwatch.live import Detection, Overlay

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
BOX = (100, 60, 220, 420)


def person_frame(top=RED, bottom=BLUE, box=BOX):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=BOX):
    return Detection(str(track_id), box, 0.9)


def stitcher(**kw):
    params = dict(max_gap_s=9999, min_similarity=0.48, margin=0.02)
    params.update(kw)
    return IdentityStitcher(BodySignature(), **params)


def wrongly_merged():
    """Two people the matcher has decided are one. Returns (stitcher, id)."""
    st = stitcher()
    frame = person_frame(RED, BLUE)
    first = st.update(frame, [det(1)], 100.0).detections[0].track_id
    st.update(person_frame(BLACK, BLACK), [], 160.0)
    second = st.update(frame, [det(2)], 300.0).detections[0].track_id
    assert second == first, "setup expects the matcher to have merged them"
    return st, second


# -- the correction itself --------------------------------------------------
def test_correcting_splits_the_live_track_onto_a_new_id():
    st, wrong = wrongly_merged()
    new_id = st.correct(wrong, 301.0)
    assert new_id is not None and new_id != wrong
    assert st.raw_to_stable["2"] == new_id
    assert st.corrections == 1


def test_the_corrected_pair_is_never_merged_again():
    """Re-running the matcher unchanged would just repeat the same mistake."""
    st, wrong = wrongly_merged()
    new_id = st.correct(wrong, 301.0)

    # keep showing the same person; they must not drift back onto the old ID
    for i in range(30):
        result = st.update(person_frame(RED, BLUE), [det(2)], 302.0 + i)
        assert result.detections[0].track_id == new_id


def test_the_ban_survives_the_person_leaving_and_returning():
    st, wrong = wrongly_merged()
    new_id = st.correct(wrong, 301.0)
    st.update(person_frame(BLACK, BLACK), [], 400.0)      # everyone leaves
    result = st.update(person_frame(RED, BLUE), [det(9)], 500.0)
    assert result.detections[0].track_id != wrong or st.forbidden


def test_correcting_an_id_that_is_not_on_screen_returns_none():
    st = stitcher()
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    assert st.correct("p999", 101.0) is None
    assert st.corrections == 0


def test_the_new_identity_starts_with_a_real_description():
    """A blank identity would match the next person who walks past."""
    st, wrong = wrongly_merged()
    new_id = st.correct(wrong, 301.0)
    assert st.identities[new_id].gallery, "new identity must know what they look like"


def test_correction_recovers_the_persons_real_old_id():
    """The whole point: `n` should not just mint a new number, it should let
    the person fall back onto the identity they actually had before."""
    st = stitcher()
    empty = person_frame((30, 30, 30), (30, 30, 30))

    real = st.update(person_frame(RED, BLUE), [det(1)], 100.0).detections[0].track_id
    st.update(empty, [], 120.0)
    other = st.update(person_frame(GREEN, BLACK), [det(2)], 200.0).detections[0].track_id
    st.update(empty, [], 220.0)
    assert real != other

    # the red/blue person returns but is mislabelled as the green/black one
    st.update(person_frame(RED, BLUE), [det(9)], 300.0)
    st.raw_to_stable["9"] = other

    new_id = st.correct(other, 301.0)
    assert new_id not in (real, other)

    landed = st.update(person_frame(RED, BLUE), [det(9)], 302.0)
    assert landed.detections[0].track_id == real, (
        "should re-match onto the real previous identity, not keep the new one")


def test_correction_gives_the_track_another_chance_to_match():
    """Correction says 'not that one', not 'never match anything'."""
    st = stitcher()
    st.update(person_frame(GREEN, BLACK), [det(1)], 50.0)
    st.update(person_frame(BLACK, BLACK), [], 80.0)

    st.update(person_frame(RED, BLUE), [det(2)], 100.0)
    wrong = st.raw_to_stable["2"]
    new_id = st.correct(wrong, 101.0)
    assert st.raw_to_stable["2"] == new_id
    assert "2" in st._probation, "should be able to re-match after a correction"


def test_the_ban_follows_the_track_onto_its_recovered_identity():
    """Otherwise the ban is pinned to a placeholder that gets discarded, and
    the same wrong merge is free to happen again."""
    st = stitcher()
    empty = person_frame((30, 30, 30), (30, 30, 30))

    real = st.update(person_frame(RED, BLUE), [det(1)], 100.0).detections[0].track_id
    st.update(empty, [], 120.0)
    other = st.update(person_frame(GREEN, BLACK), [det(2)], 200.0).detections[0].track_id
    st.update(empty, [], 220.0)

    st.update(person_frame(RED, BLUE), [det(9)], 300.0)
    st.raw_to_stable["9"] = other
    st.correct(other, 301.0)
    st.update(person_frame(RED, BLUE), [det(9)], 302.0)   # recovers `real`

    assert st._is_forbidden(real, other), (
        "the correction must still apply after the placeholder is absorbed")


def test_forbidden_pairs_are_symmetric():
    st, wrong = wrongly_merged()
    new_id = st.correct(wrong, 301.0)
    assert st._is_forbidden(wrong, new_id)
    assert st._is_forbidden(new_id, wrong)


def test_repeated_corrections_each_produce_a_fresh_id():
    st, wrong = wrongly_merged()
    first = st.correct(wrong, 301.0)
    second = st.correct(first, 302.0)
    assert len({wrong, first, second}) == 3
    assert st.corrections == 2


def test_correcting_does_not_disturb_other_people():
    st = stitcher()
    st.update(person_frame(RED, BLUE, (100, 60, 220, 420)),
              [det(1, (100, 60, 220, 420))], 100.0)
    st.update(person_frame(GREEN, BLACK, (300, 60, 420, 420)),
              [det(2, (300, 60, 420, 420))], 100.0)
    other = st.raw_to_stable["2"]
    st.correct(st.raw_to_stable["1"], 101.0)
    assert st.raw_to_stable["2"] == other


# -- the on-screen prompt ---------------------------------------------------
def test_overlay_renders_the_correction_prompt():
    from loiterwatch import Engine, IntrusionRule

    engine = Engine([IntrusionRule("i", confirm_s=3)], exit_grace=3.0, tick_s=0.5)
    plain = np.zeros((480, 640, 3), dtype=np.uint8)
    prompting = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = [Detection("p1", BOX, 0.9)]

    Overlay("cam").draw(plain, dets, engine, {}, 1000.0, [], 30.0)
    Overlay("cam").draw(prompting, dets, engine, {}, 1000.0, [], 30.0,
                        correcting="4")
    assert not np.array_equal(plain, prompting), "prompt should be visible"


def test_overlay_without_correction_is_unchanged():
    from loiterwatch import Engine, IntrusionRule

    engine = Engine([IntrusionRule("i", confirm_s=3)], exit_grace=3.0, tick_s=0.5)
    a = np.zeros((480, 640, 3), dtype=np.uint8)
    b = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = [Detection("p1", BOX, 0.9)]
    Overlay("cam").draw(a, dets, engine, {}, 1000.0, [], 30.0, None, 0, None)
    Overlay("cam").draw(b, dets, engine, {}, 1000.0, [], 30.0)
    assert np.array_equal(a, b)
