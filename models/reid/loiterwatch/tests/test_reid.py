"""Re-identification by clothes + shape, and its false-merge guards."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import (BodySignature, IdentityStitcher, Signature,
                                  detection_quality, shape_similarity, similarity)
from loiterwatch.live import Detection

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
WHITE, GREY = (235, 235, 235), (128, 128, 128)


def person_frame(top=RED, bottom=BLUE, box=(100, 60, 220, 420), size=(480, 640)):
    """A two-tone figure: `top` over the torso band, `bottom` over the legs."""
    frame = np.full((size[0], size[1], 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=(100, 60, 220, 420)):
    return Detection(str(track_id), box, 0.9)


# -- the cues themselves ---------------------------------------------------
def test_signature_captures_top_and_bottom_separately():
    box = (100, 60, 220, 420)
    sig = BodySignature().signature(person_frame(RED, BLUE, box), box)
    assert sig.upper is not None and sig.lower is not None
    assert sig.aspect == pytest.approx((420 - 60) / (220 - 100))


def test_same_outfit_scores_high():
    box = (100, 60, 220, 420)
    a = BodySignature().signature(person_frame(RED, BLUE, box), box)
    b = BodySignature().signature(person_frame(RED, BLUE, box), box)
    assert similarity(a, b) > 0.95


def test_same_top_different_trousers_is_pulled_down():
    """Lower body is what separates two people in the same uniform shirt."""
    box = (100, 60, 220, 420)
    a = BodySignature().signature(person_frame(RED, BLUE, box), box)
    b = BodySignature().signature(person_frame(RED, GREEN, box), box)
    score = similarity(a, b)
    assert score < 0.72, "same shirt alone must not clear the merge threshold"


def test_completely_different_outfit_scores_low():
    box = (100, 60, 220, 420)
    a = BodySignature().signature(person_frame(RED, BLUE, box), box)
    b = BodySignature().signature(person_frame(GREEN, BLACK, box), box)
    assert similarity(a, b) < 0.4


def test_shape_similarity_decays_with_build_difference():
    assert shape_similarity(3.0, 3.0) == pytest.approx(1.0)
    assert shape_similarity(3.0, 3.3) < 1.0
    assert shape_similarity(3.0, 6.0) < 0.2
    assert shape_similarity(None, 3.0) is None


def test_shape_alone_is_never_enough_to_merge():
    """Lots of people are the same build; that cannot justify reusing an ID."""
    a = Signature(upper=None, lower=None, aspect=3.0)
    b = Signature(upper=None, lower=None, aspect=3.0)
    assert similarity(a, b) is None


def test_incomparable_signatures_return_none_not_zero():
    assert similarity(None, Signature(aspect=3.0)) is None
    assert similarity(np.zeros(4, dtype=np.float32), Signature(aspect=3.0)) is None


# -- the stitcher end to end ----------------------------------------------
def test_same_person_returning_after_a_long_gap_keeps_their_id():
    st = IdentityStitcher(max_gap_s=900, min_similarity=0.72)
    frame = person_frame(RED, BLUE)

    first = st.update(frame, [det(1)], 100.0).detections[0].track_id
    st.update(person_frame(BLACK, BLACK), [], 200.0)          # empty scene

    result = st.update(frame, [det(99)], 700.0)               # 10 minutes later
    assert result.detections[0].track_id == first
    assert st.merges == 1


def test_a_different_person_gets_a_new_id():
    st = IdentityStitcher(max_gap_s=900, min_similarity=0.72)
    first = st.update(person_frame(RED, BLUE), [det(1)], 100.0).detections[0].track_id
    st.update(person_frame(BLACK, BLACK), [], 200.0)
    second = st.update(person_frame(GREEN, BLACK), [det(2)], 300.0).detections[0].track_id
    assert second != first
    assert st.merges == 0


def test_gallery_keeps_multiple_views_but_stays_bounded():
    # novelty above 1.0 is unreachable, so every view is considered new
    st = IdentityStitcher(gallery_size=4, novelty=1.01)
    frame = person_frame(RED, BLUE)
    for i in range(20):
        st.update(frame, [det(1)], 100.0 + i)
    assert len(st.identities["p1"].gallery) == 4


def test_near_duplicate_views_are_not_hoarded():
    st = IdentityStitcher(gallery_size=12, novelty=0.93)
    frame = person_frame(RED, BLUE)
    for i in range(30):
        st.update(frame, [det(1)], 100.0 + i)
    assert len(st.identities["p1"].gallery) == 1, "identical views should collapse"


def test_a_second_outfit_view_is_added_to_the_gallery():
    st = IdentityStitcher(novelty=0.93)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    # same tracker id, person turned around and now looks different
    st.update(person_frame(GREEN, BLACK), [det(1)], 101.0)
    assert len(st.identities["p1"].gallery) == 2


def test_a_returning_person_matches_any_stored_view():
    """Seen from the front, then the back; returns showing the back."""
    st = IdentityStitcher(max_gap_s=900, min_similarity=0.72, novelty=0.93)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    st.update(person_frame(GREEN, BLACK), [det(1)], 101.0)    # second view
    st.update(person_frame(BLACK, BLACK), [], 200.0)          # leaves

    result = st.update(person_frame(GREEN, BLACK), [det(7)], 300.0)
    assert result.detections[0].track_id == "p1"
    assert st.merges == 1


def test_two_people_visible_together_are_never_merged():
    st = IdentityStitcher(min_similarity=0.05)   # deliberately eager
    frame = person_frame(RED, BLUE)
    result = st.update(frame, [det(1, (100, 60, 220, 420)),
                               det(2, (300, 60, 420, 420))], 100.0)
    assert len({d.track_id for d in result.detections}) == 2
    assert st.merges == 0


# -- brightness rescues clothing that hue cannot describe -----------------
def test_brightness_separates_black_from_white():
    """Both are unsaturated, so hue is pure noise -- only tone tells them apart."""
    box = (100, 60, 220, 420)
    black = BodySignature().signature(person_frame(BLACK, BLACK, box), box)
    white = BodySignature().signature(person_frame(WHITE, WHITE, box), box)
    assert similarity(black, white) < 0.4


def test_identical_dark_clothing_still_matches_itself():
    box = (100, 60, 220, 420)
    a = BodySignature().signature(person_frame(BLACK, BLACK, box), box)
    b = BodySignature().signature(person_frame(BLACK, BLACK, box), box)
    assert similarity(a, b) > 0.95


# -- refusing to answer on bad evidence -----------------------------------
def test_quality_collapses_for_a_person_half_outside_the_frame():
    full = detection_quality((480, 640, 3), (100, 60, 220, 420), 0.9)
    truncated = detection_quality((480, 640, 3), (-60, 60, 60, 420), 0.9)
    assert full > 0.9
    assert truncated < 0.3, "a vertical sliver of a person must not be trusted"


def test_quality_tolerates_feet_clipped_by_the_bottom_edge():
    """Standing close to the camera is normal, not a truncation failure."""
    assert detection_quality((480, 640, 3), (100, 60, 220, 479), 0.9) > 0.7


def test_tiny_and_low_confidence_detections_score_low():
    assert detection_quality((480, 640, 3), (300, 200, 320, 250), 0.9) < 0.7
    assert detection_quality((480, 640, 3), (100, 60, 220, 420), 0.15) < 0.4


def test_a_truncated_arrival_is_not_matched_to_anyone():
    """The exact wrong-ID case: someone walking in from the side."""
    st = IdentityStitcher(max_gap_s=900, min_quality=0.55)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    st.update(person_frame(BLACK, BLACK), [], 200.0)

    edge_box = (-60, 60, 60, 420)      # mostly off the left edge
    result = st.update(person_frame(RED, BLUE, box=edge_box),
                       [det(2, edge_box)], 300.0)
    assert st.merges == 0, "must not identify anyone from a sliver"
    assert result.detections[0].track_id != "p1"


def test_probation_re_links_once_a_clean_view_arrives():
    """Entering truncated then becoming fully visible must still re-link."""
    st = IdentityStitcher(max_gap_s=900, min_quality=0.55, probation_samples=5)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    st.update(person_frame(BLACK, BLACK), [], 200.0)

    edge_box = (-60, 60, 60, 420)
    st.update(person_frame(RED, BLUE, box=edge_box), [det(9, edge_box)], 300.0)
    assert st.merges == 0                       # too truncated to decide yet

    result = st.update(person_frame(RED, BLUE), [det(9)], 301.0)  # now fully in
    assert result.detections[0].track_id == "p1"
    assert st.merges == 1


def test_ambiguous_candidates_are_refused():
    """Two stored people look equally like the newcomer -- guess nothing.

    Built by hand: two people this similar cannot be created through normal
    observation, because the stitcher would have merged them on sight.
    """
    from loiterwatch.identity import Identity

    box = (100, 60, 220, 420)
    probe = BodySignature().signature(person_frame(RED, BLUE, box), box)

    st = IdentityStitcher(max_gap_s=900, min_similarity=0.5, margin=0.05)
    for name in ("p1", "p2"):
        st.identities[name] = Identity(
            name, gallery=[probe], last_seen=100.0, first_seen=100.0, samples=50,
        )
    st._next_id = 3

    result = st.update(person_frame(RED, BLUE, box), [det(9, box)], 300.0)
    assert st.merges == 0, "ambiguous match should be declined"
    assert st.rejected_ambiguous > 0
    assert result.detections[0].track_id not in ("p1", "p2")


def test_a_clear_winner_is_still_matched_despite_the_margin_rule():
    """The ambiguity guard must not block genuinely distinguishable people."""
    from loiterwatch.identity import Identity

    box = (100, 60, 220, 420)
    match = BodySignature().signature(person_frame(RED, BLUE, box), box)
    other = BodySignature().signature(person_frame(GREEN, BLACK, box), box)

    st = IdentityStitcher(max_gap_s=900, min_similarity=0.5, margin=0.05)
    st.identities["p1"] = Identity("p1", [match], 100.0, 100.0, samples=50)
    st.identities["p2"] = Identity("p2", [other], 100.0, 100.0, samples=50)
    st._next_id = 3

    result = st.update(person_frame(RED, BLUE, box), [det(9, box)], 300.0)
    assert result.detections[0].track_id == "p1"
    assert st.merges == 1


def test_someone_glimpsed_for_a_moment_is_not_a_match_target():
    st = IdentityStitcher(max_gap_s=900, min_evidence=10)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)   # one frame only
    st.update(person_frame(BLACK, BLACK), [], 200.0)
    result = st.update(person_frame(RED, BLUE), [det(2)], 300.0)
    assert st.merges == 0
    assert result.detections[0].track_id != "p1"


# -- persistence ----------------------------------------------------------
def test_identities_survive_a_restart(tmp_path):
    db = tmp_path / "identities.json"
    frame = person_frame(RED, BLUE)

    first = IdentityStitcher(max_gap_s=9999)
    original = first.update(frame, [det(1)], 100.0).detections[0].track_id
    first.save(str(db))

    # brand new process: different tracker IDs, no in-memory state
    second = IdentityStitcher(max_gap_s=9999, min_similarity=0.72)
    assert second.load(str(db)) == 1
    result = second.update(frame, [det(55)], 500.0)
    assert result.detections[0].track_id == original
    assert second.merges == 1


def test_restored_ids_do_not_collide_with_new_people(tmp_path):
    db = tmp_path / "identities.json"
    first = IdentityStitcher()
    first.update(person_frame(RED, BLUE), [det(1)], 100.0)
    first.save(str(db))

    second = IdentityStitcher()
    second.load(str(db))
    newcomer = second.update(person_frame(GREEN, BLACK), [det(2)], 500.0)
    assert newcomer.detections[0].track_id != "p1"


def test_loading_a_missing_or_corrupt_db_is_not_fatal(tmp_path):
    st = IdentityStitcher()
    assert st.load(str(tmp_path / "nope.json")) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert st.load(str(bad)) == 0
