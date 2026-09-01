"""An ID belongs to one person.

The rule: several cameras may show the same identity at once -- that is one
person seen from two angles. What must never happen is one number ending up on
two different people, or a number being handed out twice.
"""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.identity import BodySignature, IdentityStitcher
from loiterwatch.live import Detection

BOX = (100, 60, 220, 420)
OTHER_BOX = (330, 60, 450, 420)
RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)


def person(top=RED, bottom=BLUE, box=BOX):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=BOX):
    return Detection(str(track_id), box, 0.9)


def stitcher(**kw):
    params = dict(max_gap_s=9999, min_similarity=0.55)
    params.update(kw)
    return IdentityStitcher(BodySignature(), **params)


def overlap(st, rounds=4, top=RED, bottom=BLUE, t=100.0, step=1.0):
    """Show the same person on both feeds for `rounds` frames.

    Taking an identity another camera is holding right now needs
    `concurrent_confirmations` agreeing observations, so a genuine overlap is
    a short sequence rather than a single frame.
    """
    a = b = None
    for i in range(rounds):
        when = t + i * step
        a = st.update(person(top, bottom), [det(1)], when,
                      camera="cam1").detections[0].track_id
        b = st.update(person(top, bottom), [det(1)], when + 0.1,
                      camera="cam2").detections[0].track_id
    return a, b


# -- one person, two cameras: sharing is correct ----------------------------
def test_overlapping_cameras_hold_one_identity_together():
    st = stitcher()
    a, b = overlap(st)
    assert a == b
    assert st.holders(a) == {"cam1", "cam2"}


def test_a_single_frame_is_not_enough_to_take_an_id_in_use_elsewhere():
    """The other half of the trade: one frame of colour histogram is a
    coin-flip, and the concurrent case is where a lost flip costs an ID."""
    st = stitcher(concurrent_confirmations=3)
    a = st.update(person(), [det(1)], 100.0, camera="cam1").detections[0].track_id
    b = st.update(person(), [det(1)], 100.1, camera="cam2").detections[0].track_id
    assert a != b, "one frame must not claim an identity another camera holds"
    assert st.rejected_unconfirmed == 1


def test_confirmations_can_be_switched_off():
    st = stitcher(concurrent_confirmations=1)
    a = st.update(person(), [det(1)], 100.0, camera="cam1").detections[0].track_id
    b = st.update(person(), [det(1)], 100.1, camera="cam2").detections[0].track_id
    assert a == b


def test_agreements_separated_by_a_gap_do_not_add_up():
    """A lookalike wins the occasional frame forever; a real overlap wins them
    back to back. Let the gap between two agreements exceed the window and the
    streak starts over, however many have come before."""
    # both feeds keep showing them, so this stays the concurrent case, but the
    # agreements arrive three seconds apart against a one-second window
    st = stitcher(confirm_window_s=1.0, holder_window_s=10.0)
    a, b = overlap(st, rounds=6, step=3.0)
    assert a != b
    assert st.rejected_unconfirmed >= 6
    assert st.merges == 0


def test_the_shared_identity_survives_repeated_frames():
    """Regression: retiring the *other* camera's mapping made the two feeds
    steal the identity back and forth, inventing a new one each round."""
    st = stitcher()
    settled = set()
    for i in range(8):
        a = st.update(person(), [det(1)], 100.0 + i,
                      camera="cam1").detections[0].track_id
        b = st.update(person(), [det(1)], 100.0 + i + 0.1,
                      camera="cam2").detections[0].track_id
        if i >= 4:                      # past the confirmation window
            settled.update({a, b})
    assert len(settled) == 1, "the pair must settle on one identity, not oscillate"
    assert len(st.identities) == 1


def test_holders_reports_only_the_cameras_showing_someone():
    st = stitcher()
    a = st.update(person(), [det(1)], 100.0, camera="cam1").detections[0].track_id
    assert st.holders(a) == {"cam1"}
    a, _ = overlap(st)
    assert st.holders(a) == {"cam1", "cam2"}


def test_a_camera_stops_holding_an_identity_once_it_stops_showing_it():
    """`holders` without a clock answers 'seen recently', and tracker
    bookkeeping lingers for max_gap_s -- fifteen minutes by default. Passing
    `now` is what makes the concurrent guard mean 'right now'."""
    st = stitcher(holder_window_s=2.0)
    a, _ = overlap(st)
    assert st.holders(a, 104.0) == {"cam1", "cam2"}
    assert st.holders(a, 400.0) == set(), "nobody is showing them five minutes on"
    assert st.holders(a) == {"cam1", "cam2"}, "clockless call is unchanged"


# -- two people must never share a number -----------------------------------
def test_a_different_person_on_the_other_camera_gets_a_different_id():
    st = stitcher()
    a = st.update(person(RED, BLUE), [det(1)], 100.0,
                  camera="cam1").detections[0].track_id
    b = st.update(person(GREEN, BLACK), [det(1)], 100.1,
                  camera="cam2").detections[0].track_id
    assert a != b


def test_two_people_on_one_camera_never_share_an_id():
    st = stitcher(min_similarity=0.05)      # deliberately eager
    result = st.update(person(RED, BLUE), [det(1, BOX), det(2, OTHER_BOX)],
                       100.0, camera="cam1")
    assert len({d.track_id for d in result.detections}) == 2


def test_an_in_use_identity_is_not_handed_out_on_a_discount():
    """Cross-camera and short-absence discounts must not apply to an identity
    another camera is showing right now -- that is the two-people-one-number
    case, and it is worth losing a legitimate merge to prevent."""
    st = stitcher(min_similarity=0.90, cross_min_similarity=0.10,
                  recent_bonus=0.5, concurrent_min_similarity=1.01)
    a, b = overlap(st, rounds=8)
    # the 0.10 cross bar and the 0.5 short-absence bonus would both have
    # matched these identical frames; the concurrent bar is what governs
    assert a != b
    assert st.merges == 0

    relaxed = stitcher(min_similarity=0.90, cross_min_similarity=0.10,
                       recent_bonus=0.5, concurrent_min_similarity=0.80)
    c, d = overlap(relaxed, rounds=8)
    assert c == d, "a bar the pair can clear must still let them share an ID"
    assert relaxed.concurrent_min_similarity == pytest.approx(0.80)


def test_an_unreachable_concurrent_bar_holds_even_on_identical_frames():
    """The discount is not a back door: no number of confirmations lets a
    cross-camera claim slide under the concurrent threshold."""
    st = stitcher(min_similarity=1.01, cross_min_similarity=0.10,
                  recent_bonus=0.5)
    a, b = overlap(st, rounds=10)
    assert a != b
    assert st.last_reject_reason == "no candidate above threshold"


def test_a_weak_crop_can_never_claim_an_in_use_identity():
    st = stitcher()
    edge = (-30, 60, 90, 420)
    a = st.update(person(), [det(1)], 100.0, camera="cam1").detections[0].track_id
    b = st.update(person(RED, BLUE, edge), [det(1, edge)], 100.1,
                  camera="cam2").detections[0].track_id
    assert a != b, "a truncated view must not adopt an identity in use elsewhere"


# -- numbers are never reissued ---------------------------------------------
def test_id_numbers_are_never_reused_even_after_pruning():
    st = stitcher(max_gap_s=1, min_similarity=0.99)
    issued = [st.update(person(), [det(i)], 100.0 + i * 10,
                        camera="cam1").detections[0].track_id
              for i in range(8)]
    assert len(issued) == len(set(issued))


def test_one_counter_serves_every_camera():
    """With matching made impossible, every track must mint its own number and
    no two cameras may ever land on the same one."""
    # genuinely unreachable: the short-absence bonus would otherwise bring a
    # 1.01 bar down to 0.93, which identical frames clear
    st = stitcher(min_similarity=1.01, recent_bonus=0.0)
    ids = []
    for i in range(5):
        for cam in ("cam1", "cam2", "cam3"):
            ids.append(st.update(person(), [det(f"{cam}{i}")], 100.0 + i,
                                 camera=cam).detections[0].track_id)
    assert len(ids) == 15
    assert len(set(ids)) == 15, "no number may be issued twice across cameras"


def test_a_restored_session_does_not_reissue_old_numbers(tmp_path):
    db = str(tmp_path / "ids.json")
    first = stitcher(min_similarity=0.99)
    used = {first.update(person(), [det(i)], 100.0 + i,
                         camera="cam1").detections[0].track_id
            for i in range(3)}
    first.save(db)

    second = stitcher(min_similarity=0.99)
    second.load(db)
    fresh = second.update(person(GREEN, BLACK), [det(99)], 500.0,
                          camera="cam1").detections[0].track_id
    assert fresh not in used


def test_camera_names_are_recovered_from_namespaced_keys():
    st = stitcher()
    st.update(person(), [det(1)], 100.0, camera="cam1")
    assert st._camera_of("cam1\x001") == "cam1"
    assert st._camera_of("1") is None
