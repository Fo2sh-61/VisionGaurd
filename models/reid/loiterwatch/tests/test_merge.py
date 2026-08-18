"""The `j` (join) key: 'these two IDs are the same person', and what it learns.

Two overlapping cameras render the same person differently enough that the
cross-camera score falls under the bar. Rather than guess a lower threshold
globally -- which would merge strangers everywhere -- the operator confirms one
pairing and the system learns how much slack *that specific camera pair* needs.
"""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import BodySignature, IdentityStitcher
from loiterwatch.live import Detection, handle_id_prompt, prompt_text

BOX = (100, 60, 220, 420)
RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
CAST = (1.25, 0.95, 0.80)      # the second camera's colour rendition

ENTER, ESC, BACKSPACE, SPACE = 13, 27, 8, 32


def person(top=RED, bottom=BLUE, tint=(1.0, 1.0, 1.0), box=BOX):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return np.clip(frame.astype(np.float32) * np.array(tint), 0, 255).astype(np.uint8)


def det(track_id):
    return Detection(str(track_id), BOX, 0.9)


def split_across_cameras(st, top=RED, bottom=BLUE, t=100.0):
    """Same person on both feeds at once, scoring too low to auto-merge."""
    a = st.update(person(top, bottom), [det(1)], t,
                  camera="laptop").detections[0].track_id
    b = st.update(person(top, bottom, CAST), [det(1)], t + 0.1,
                  camera="ipcam").detections[0].track_id
    return a, b


def stitcher(**kw):
    params = dict(max_gap_s=9999, min_similarity=0.60)
    params.update(kw)
    return IdentityStitcher(BodySignature(), **params)


# -- the merge itself -------------------------------------------------------
def test_merging_keeps_one_identity():
    st = stitcher()
    a, b = split_across_cameras(st)
    assert a != b, "setup expects the cameras to disagree"
    kept = st.merge(a, b, 101.0)
    assert kept in (a, b)
    assert len([i for i in (a, b) if i in st.identities]) == 1
    assert st.manual_merges == 1


def test_the_surviving_gallery_holds_views_from_both_cameras():
    """The lasting benefit: each camera can now match against its own angle."""
    st = stitcher()
    a, b = split_across_cameras(st)
    before = len(st.identities[a].gallery)
    kept = st.merge(a, b, 101.0)
    assert len(st.identities[kept].gallery) > before


def test_live_tracks_follow_the_merged_identity():
    st = stitcher()
    a, b = split_across_cameras(st)
    kept = st.merge(a, b, 101.0)
    assert set(st.raw_to_stable.values()) == {kept}


def test_merging_unknown_or_identical_ids_is_refused():
    st = stitcher()
    a, _ = split_across_cameras(st)
    assert st.merge(a, a, 101.0) is None
    assert st.merge(a, "p999", 101.0) is None
    assert st.merge("p998", "p999", 101.0) is None
    assert st.manual_merges == 0


def test_merging_overrides_an_earlier_correction():
    """An explicit 'same person' must beat an earlier 'not this person'."""
    st = stitcher()
    a, b = split_across_cameras(st)
    st.forbidden.add(frozenset({a, b}))
    kept = st.merge(a, b, 101.0)
    assert kept is not None
    assert not st._is_forbidden(a, b)


# -- what it learns ---------------------------------------------------------
def test_a_confirmed_merge_teaches_the_camera_pair():
    st = stitcher()
    a, b = split_across_cameras(st)
    assert st.pair_offsets == {}
    st.merge(a, b, 101.0)
    pair = frozenset({"laptop", "ipcam"})
    assert pair in st.pair_offsets
    assert 0 < st.pair_offsets[pair] <= st.max_pair_offset


def test_the_next_person_is_shared_automatically():
    """The whole point: correct it once, not once per person."""
    st = stitcher()
    a, b = split_across_cameras(st)
    st.merge(a, b, 101.0)

    for i in range(4):
        c = st.update(person(GREEN, BLACK), [det(5)], 200.0 + i,
                      camera="laptop").detections[0].track_id
        d = st.update(person(GREEN, BLACK, CAST), [det(5)], 200.1 + i,
                      camera="ipcam").detections[0].track_id
    assert c == d


def test_the_learned_slack_is_capped():
    st = stitcher(min_similarity=0.99)
    st.max_pair_offset = 0.05
    a, b = split_across_cameras(st)
    st.merge(a, b, 101.0)
    assert max(st.pair_offsets.values()) <= 0.05


def test_offsets_average_rather_than_chase_the_last_merge():
    st = stitcher()
    a, b = split_across_cameras(st)
    st.merge(a, b, 101.0)
    pair = frozenset({"laptop", "ipcam"})
    first = st.pair_offsets[pair]

    c, d = split_across_cameras(st, GREEN, BLACK, t=300.0)
    if c != d:                       # only if they still disagree
        st.merge(c, d, 301.0)
        assert st.pair_samples[pair] == 2
        assert st.pair_offsets[pair] <= max(first, st.max_pair_offset)


def test_nothing_is_learned_from_a_same_camera_merge():
    """Two IDs on one camera say nothing about how two cameras differ."""
    st = stitcher()
    st.update(person(RED, BLUE), [det(1)], 100.0, camera="laptop")
    st.update(person(GREEN, BLACK), [det(2)], 100.0, camera="laptop")
    st.merge("p1", "p2", 101.0)
    assert st.pair_offsets == {}


def test_nothing_is_learned_when_the_score_was_already_good_enough():
    st = stitcher(min_similarity=0.60)
    a = st.update(person(RED, BLUE), [det(1)], 100.0,
                  camera="laptop").detections[0].track_id
    st.update(person(BLACK, BLACK), [], 110.0, camera="laptop")
    b = st.update(person(GREEN, BLACK), [det(9)], 200.0,
                  camera="ipcam").detections[0].track_id
    st.merge(a, b, 201.0)
    # they genuinely look different; a huge shortfall must not be "learned"
    assert all(v <= st.max_pair_offset for v in st.pair_offsets.values())


# -- the keyboard prompt ----------------------------------------------------
def test_join_prompt_collects_two_numbers():
    st = stitcher()
    a, b = split_across_cameras(st)
    mode, buffer = "join", ""
    for key in (ord(a[1:]), SPACE, ord(b[1:])):
        mode, buffer = handle_id_prompt(key, mode, buffer, st, 101.0)
    assert buffer == f"{a[1:]} {b[1:]}"
    mode, buffer = handle_id_prompt(ENTER, mode, buffer, st, 101.0)
    assert mode is None and st.manual_merges == 1


def test_join_needs_exactly_two_ids(capsys):
    st = stitcher()
    split_across_cameras(st)
    handle_id_prompt(ENTER, "join", "1", st, 101.0)
    assert "two IDs" in capsys.readouterr().out
    assert st.manual_merges == 0


def test_escape_cancels_without_merging():
    st = stitcher()
    split_across_cameras(st)
    mode, buffer = handle_id_prompt(ESC, "join", "1 2", st, 101.0)
    assert mode is None and buffer == ""
    assert st.manual_merges == 0


def test_backspace_edits_the_buffer():
    st = stitcher()
    mode, buffer = handle_id_prompt(BACKSPACE, "join", "12", st, 101.0)
    assert buffer == "1"


def test_space_is_only_a_separator_in_join_mode():
    st = stitcher()
    _, joined = handle_id_prompt(SPACE, "join", "1", st, 101.0)
    _, corrected = handle_id_prompt(SPACE, "correct", "1", st, 101.0)
    assert joined == "1 " and corrected == "1"


@pytest.mark.parametrize("mode,expected", [
    ("join", "same person"),
    ("correct", "wrong ID"),
])
def test_prompt_text_differs_by_mode(mode, expected):
    assert expected in prompt_text(mode, "4")


def test_prompt_survives_no_stitcher(capsys):
    mode, buffer = handle_id_prompt(ENTER, "join", "1 2", None, 101.0)
    assert mode is None
    assert "no identity tracking" in capsys.readouterr().out
