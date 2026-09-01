"""Evidence averaging, ambiguity reporting, and the rules-free ReID mode."""
from __future__ import annotations

import numpy as np
import pytest

from loiterwatch.cli import main
from loiterwatch.identity import (BodySignature, Identity, IdentityStitcher,
                                  Signature, average_signatures, similarity)
from loiterwatch.live import Detection

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)
BOX = (100, 60, 220, 420)


def person_frame(top=RED, bottom=BLUE, box=BOX, noise=0, seed=0):
    frame = np.full((480, 640, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    if noise:
        rng = np.random.default_rng(seed)
        grain = rng.integers(-noise, noise + 1, frame.shape, dtype=np.int16)
        frame = np.clip(frame.astype(np.int16) + grain, 0, 255).astype(np.uint8)
    return frame


def det(track_id, box=BOX):
    return Detection(str(track_id), box, 0.9)


# -- averaging --------------------------------------------------------------
def test_averaging_one_signature_returns_it_unchanged():
    sig = BodySignature().signature(person_frame(), BOX)
    assert average_signatures([sig]) is sig


def test_averaging_ignores_missing_views():
    sig = BodySignature().signature(person_frame(), BOX)
    assert average_signatures([None, sig, None]) is not None
    assert average_signatures([None, None]) is None
    assert average_signatures([]) is None


def test_averaged_signature_is_a_unit_descriptor():
    sigs = [BodySignature().signature(person_frame(noise=25, seed=i), BOX)
            for i in range(5)]
    blended = average_signatures(sigs)
    assert blended.upper is not None
    assert float(np.linalg.norm(blended.upper)) == pytest.approx(1.0, abs=1e-5)


def test_averaging_beats_a_single_noisy_frame():
    """The point of accumulating evidence: per-frame noise is uncorrelated."""
    clean = BodySignature().signature(person_frame(), BOX)
    noisy = [BodySignature().signature(person_frame(noise=60, seed=i), BOX)
             for i in range(8)]
    single = similarity(clean, noisy[0])
    averaged = similarity(clean, average_signatures(noisy))
    assert averaged >= single


def test_averaging_takes_the_median_aspect():
    sigs = [Signature(aspect=a) for a in (2.0, 3.0, 10.0)]
    sigs = [Signature(upper=np.array([1.0], dtype=np.float32), aspect=s.aspect)
            for s in sigs]
    assert average_signatures(sigs).aspect == pytest.approx(3.0)


def test_plain_vector_signatures_average_too():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    blended = average_signatures([a, b])
    assert float(np.linalg.norm(blended)) == pytest.approx(1.0, abs=1e-6)


# -- ambiguity reporting ----------------------------------------------------
def test_ambiguous_rejection_explains_itself():
    """Matching uniforms are the real-world cause; the message should say so."""
    probe = BodySignature().signature(person_frame(RED, BLUE), BOX)
    st = IdentityStitcher(min_similarity=0.5, margin=0.05)
    for name in ("p1", "p2"):
        st.identities[name] = Identity(name, gallery=[probe], last_seen=100.0,
                                       first_seen=100.0, samples=50)
    st._next_id = 3

    st.update(person_frame(RED, BLUE), [det(9)], 300.0)
    assert st.rejected_ambiguous == 1
    assert "ambiguous" in (st.last_reject_reason or "")
    assert "p1" in st.last_reject_reason and "p2" in st.last_reject_reason


def test_a_smaller_margin_accepts_the_ambiguous_match():
    probe = BodySignature().signature(person_frame(RED, BLUE), BOX)
    slightly_different = BodySignature().signature(
        person_frame(RED, BLUE, noise=10, seed=3), BOX)

    st = IdentityStitcher(min_similarity=0.5, margin=0.0)
    st.identities["p1"] = Identity("p1", [probe], 100.0, 100.0, samples=50)
    st.identities["p2"] = Identity("p2", [slightly_different], 100.0, 100.0,
                                   samples=50)
    st._next_id = 3

    result = st.update(person_frame(RED, BLUE), [det(9)], 300.0)
    assert st.merges == 1
    assert result.detections[0].track_id in ("p1", "p2")


class FixedAppearance:
    """Hands back a preset descriptor, so match scores can be stated exactly."""

    def __init__(self, vector):
        self.vector = vector

    def signature(self, frame, box):
        return self.vector


def at_cosine(c: float):
    """A unit vector whose cosine against (1, 0) is exactly `c`."""
    return np.array([c, float(np.sqrt(1.0 - c * c))], dtype=np.float32)


def rigged(scores, seen_on=None, **kw):
    """A stitcher facing candidates that score exactly `scores` against the
    next detection, each last seen on camera `seen_on`. Real histograms cannot
    be aimed this precisely, and these rules are all about where a boundary
    sits."""
    params = dict(max_gap_s=9999, min_similarity=0.61, margin=0.05,
                  adaptive_weights=False)
    params.update(kw)
    st = IdentityStitcher(FixedAppearance(at_cosine(1.0)), **params)
    for i, score in enumerate(scores, start=1):
        st.identities[f"p{i}"] = Identity(f"p{i}", [at_cosine(score)], 100.0,
                                          100.0, samples=50,
                                          last_camera=seen_on)
    st._next_id = len(scores) + 1
    return st


def test_a_rival_below_the_threshold_still_counts_as_ambiguity():
    """The hole this closes: the runner-up used to have to clear the bar too.

    Two people scoring 0.62 and 0.60 are indistinguishable, but with the bar at
    0.61 only one of them was ever compared -- so the winner was unopposed by
    construction and the ambiguity guard never fired. Lowering the bar to catch
    cross-camera matches widened that hole rather than the candidate list.
    """
    st = rigged([0.62, 0.60])
    result = st.update(person_frame(), [det(9)], 300.0)
    assert st.merges == 0
    assert st.rejected_ambiguous == 1
    assert "p2" in (st.last_reject_reason or ""), "the near-miss is the rival"
    assert result.detections[0].track_id not in ("p1", "p2")


def test_a_clear_winner_is_untouched_by_the_wider_comparison():
    st = rigged([0.80, 0.40])
    result = st.update(person_frame(), [det(9)], 300.0)
    assert result.detections[0].track_id == "p1"
    assert st.merges == 1


def test_cross_camera_matches_answer_to_a_wider_margin():
    """Same evidence, same threshold -- only which camera last saw them.

    Cross-camera is where the descriptor is least reliable and the candidate
    pool is largest, so that is where a narrow win is least worth trusting.
    """
    def run(seen_on, camera):
        st = rigged([0.70, 0.63], seen_on=seen_on)
        st.update(person_frame(), [det(9)], 300.0, camera=camera)
        return st.merges

    assert run(seen_on="cam_a", camera="cam_a") == 1, "0.07 clears margin 0.05"
    assert run(seen_on="cam_b", camera="cam_a") == 0, "but not cross_margin 0.10"


def test_the_cross_margin_defaults_to_twice_the_local_one():
    st = IdentityStitcher(margin=0.05)
    assert st.cross_margin == pytest.approx(0.10)
    assert IdentityStitcher(margin=0.05, cross_margin=0.2).cross_margin == 0.2


def test_another_camera_may_not_claim_a_barely_known_identity():
    st = rigged([0.90], seen_on="cam_b", cross_min_evidence=80)
    st.update(person_frame(), [det(9)], 300.0, camera="cam_a")
    assert st.merges == 0, "50 observations is under the 80 demanded"
    assert st.last_best is not None, "it was still compared, just not claimable"

    lenient = rigged([0.90], seen_on="cam_b", cross_min_evidence=10)
    lenient.update(person_frame(), [det(9)], 300.0, camera="cam_a")
    assert lenient.merges == 1


def test_no_candidate_reason_is_reported():
    st = IdentityStitcher(min_similarity=0.99)
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    st.update(person_frame(BLACK, BLACK), [], 200.0)
    st.update(person_frame(GREEN, BLACK), [det(2)], 300.0)
    assert st.last_reject_reason == "no candidate above threshold"


# -- re-entry, which is the behaviour being tuned ---------------------------
def test_re_entry_keeps_the_id_at_a_sensitive_threshold():
    st = IdentityStitcher(BodySignature(), max_gap_s=3600, min_similarity=0.48,
                          margin=0.02)
    frame = person_frame(RED, BLUE)
    first = st.update(frame, [det(1)], 100.0).detections[0].track_id
    st.update(person_frame(BLACK, BLACK), [], 160.0)
    again = st.update(person_frame(RED, BLUE, noise=30, seed=7),
                      [det(77)], 400.0)
    assert again.detections[0].track_id == first
    assert st.merges == 1


def test_the_retired_tracker_id_is_cleaned_up_on_a_match():
    st = IdentityStitcher(BodySignature(), max_gap_s=3600, min_similarity=0.48)
    frame = person_frame(RED, BLUE)
    st.update(frame, [det(1)], 100.0)
    st.update(person_frame(BLACK, BLACK), [], 160.0)
    st.update(frame, [det(2)], 300.0)
    assert st.merges == 1
    assert "1" not in st._pending_views
    assert "1" not in st.raw_to_stable
    assert "1" not in st._probation


def test_bookkeeping_for_vanished_tracks_does_not_grow_forever():
    """Trackers hand out fresh IDs indefinitely; each one must be reclaimed."""
    st = IdentityStitcher(BodySignature(), max_gap_s=30, min_similarity=0.99)
    for i in range(60):
        st.update(person_frame(RED, BLUE), [det(i)], 100.0 + i * 10)
    assert len(st.raw_to_stable) <= 4
    assert len(st._pending_views) <= 4
    assert len(st._raw_last_seen) <= 4


# -- rules-free mode --------------------------------------------------------
def test_live_requires_config_or_no_rules(capsys):
    assert main(["live", "--no-window"]) == 1
    assert "no-rules" in capsys.readouterr().err


def test_no_rules_builds_an_empty_engine():
    from loiterwatch.config import Config
    engine = Config(rules=[], exit_grace_s=3.0, tick_s=0.5).engine()
    assert engine.rules == []
    engine.advance(1_770_000_000.0)
    assert engine.alerts == []


# -- short absences are themselves evidence ---------------------------------
def test_a_brief_absence_lowers_the_bar():
    """Someone back after 3 seconds is far likelier to be the person who just
    left than a stranger who happens to resemble them."""
    st = IdentityStitcher(BodySignature(), max_gap_s=9999, min_similarity=0.60,
                          recent_absence_s=20.0, recent_bonus=0.08)
    assert st.recent_bonus == pytest.approx(0.08)

    frame = person_frame(RED, BLUE)
    first = st.update(frame, [det(1)], 100.0).detections[0].track_id
    st.update(person_frame(BLACK, BLACK), [], 103.0)
    back = st.update(person_frame(RED, BLUE, noise=40, seed=2), [det(2)], 105.0)
    assert back.detections[0].track_id == first


def test_the_bonus_does_not_apply_to_a_long_absence():
    """Same inputs, same threshold -- only the length of the absence differs."""
    returning = person_frame(RED, BLUE, noise=40, seed=2)

    def run(gap_s, recent_window):
        st = IdentityStitcher(BodySignature(), max_gap_s=9999,
                              min_similarity=0.60, margin=0.0,
                              recent_absence_s=recent_window, recent_bonus=0.08)
        st.update(person_frame(RED, BLUE), [det(1)], 100.0)
        st.update(person_frame(BLACK, BLACK), [], 100.0 + gap_s / 2)
        st.update(returning, [det(2)], 100.0 + gap_s)
        return st.merges

    brief = run(gap_s=6.0, recent_window=20.0)     # inside the bonus window
    long = run(gap_s=600.0, recent_window=20.0)    # far outside it
    assert brief >= long, "a short absence must be at least as easy to match"


def test_quality_is_reported_for_diagnostics():
    st = IdentityStitcher(BodySignature())
    st.update(person_frame(RED, BLUE), [det(1)], 100.0)
    assert st.last_quality is not None and 0.0 <= st.last_quality <= 1.0
