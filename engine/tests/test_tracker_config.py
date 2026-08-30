"""How long a lost track stays alive, in seconds rather than in hope.

The rule this defends: **an ID must outlive a glance away, and must not outlive
the person leaving.** Too short and one person collects a new ID every few
seconds, so a path breaks into fragments and "follow this person" cannot. Too
long and the next person through the door inherits the ID, which puts one
child's movements onto another — the failure this whole subsystem is built to
avoid.

**These tests have now caught the same rule being broken twice, in opposite
directions.** That is why they assert seconds and not frame counts.

*First*, in our own code: `track_buffer=30` was written as though ByteTrack
counted real frames. It did not — `BYTETracker.__init__` computed
`max_time_lost = int(frame_rate / 30 * track_buffer)`, quoting the number
against an implied 30 fps whatever the real rate was. At 5 Hz that bought five
frames, one second, against a comment promising six. Measured on the recorded
clip, one person collected four separate IDs in 120 frames. The fix was to
pre-multiply by 30 and cancel the implied rate.

*Second*, in ultralytics: 8.4.127 removed the `frame_rate` argument and now
uses the value raw as `max_frames_lost`. The pre-multiplied 180 became 180
real frames — 36 seconds at 5 Hz, 180 at 1 Hz. These seven tests failed on the
upgrade, which is the only reason it was noticed; nothing else would have
shown it until two people shared an ID.

So the buffer is now computed from the feed's own rate by
`track_buffer_for(frame_rate)`, and the invariant below is unchanged: **the
window is LOST_TRACK_SECONDS at any frame rate.** Assert that, never the
mechanism, because the mechanism has now moved twice.
"""

from __future__ import annotations

import pytest

from vg.infer.tracking import (
    LOST_TRACK_SECONDS,
    TRACK_BUFFER,
    TRACKER_DEFAULTS,
    PersonTracker,
    track_buffer_for,
)


def lost_frames(tracker: PersonTracker) -> int:
    """How many frames a lost track survives, whatever ultralytics calls it.

    `max_time_lost` up to 8.4.7, `max_frames_lost` from 8.4.127. Reading both
    here keeps the assertions about seconds rather than about a spelling.
    """
    inner = tracker._tracker
    for name in ("max_frames_lost", "max_time_lost"):
        if hasattr(inner, name):
            return getattr(inner, name)
    raise AssertionError(
        "BYTETracker exposes neither max_frames_lost nor max_time_lost - "
        "the lost-track window has moved again and this file must follow it"
    )


@pytest.mark.parametrize("frame_rate", [1.0, 5.0, 12.0, 25.0, 30.0])
def test_the_window_is_the_same_seconds_at_every_frame_rate(frame_rate: float):
    """Six seconds means six seconds, whether the feed is 5 Hz or 30.

    The one assertion in this file that has survived both mechanism changes.
    """
    tracker = PersonTracker(frame_rate=frame_rate)
    assert lost_frames(tracker) / frame_rate == pytest.approx(
        LOST_TRACK_SECONDS, abs=0.5)


def test_the_buffer_is_frames_for_this_feeds_rate():
    """The buffer belongs to the feed, not to the module.

    A single constant cannot serve feeds at different rates once the unit is
    real frames, and pretending it can is what made the window 36 seconds at
    5 Hz after the ultralytics upgrade.
    """
    assert track_buffer_for(5.0) == 30, "6 s at 5 Hz is 30 frames"
    assert track_buffer_for(30.0) == 180, "6 s at 30 Hz is 180 frames"
    assert TRACK_BUFFER == track_buffer_for(30.0)

    # The value that shipped briefly, named so it cannot come back quietly:
    # 180 frames handed to a 5 Hz feed is 36 seconds, six times the intent.
    assert 180 / 5.0 == 36.0
    assert lost_frames(PersonTracker(frame_rate=5.0)) == 30


def test_an_explicit_override_still_wins():
    """A caller naming a frame count means it, and is not second-guessed."""
    tracker = PersonTracker(frame_rate=5.0, track_buffer=7)

    assert lost_frames(tracker) == 7


def test_the_defaults_are_still_a_complete_bytetrack_config():
    """`track_buffer` is overwritten per feed, but must still be present -
    ByteTrack reads it off the namespace and would raise without it."""
    assert set(TRACKER_DEFAULTS) >= {
        "tracker_type", "track_high_thresh", "track_low_thresh",
        "new_track_thresh", "track_buffer", "match_thresh", "fuse_score",
    }


def test_a_glance_away_keeps_the_id_and_a_departure_does_not():
    """Both directions of the trade-off, at the rate the Track page really uses.

    The page boosts analysis to 12 Hz. Two seconds of absence is someone
    turning to a locker; a minute is someone who left the building.
    """
    tracker = PersonTracker(frame_rate=12.0)
    window_seconds = lost_frames(tracker) / 12.0

    assert window_seconds > 2.0, "a two-second glance away must not retire the ID"
    assert window_seconds < 60.0, "a departed person must not keep their ID"
