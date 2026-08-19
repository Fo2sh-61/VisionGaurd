"""How long a lost track stays alive, in seconds rather than in hope.

The rule this defends: **an ID must outlive a glance away, and must not outlive
the person leaving.** Too short and one person collects a new ID every few
seconds, so a path breaks into fragments and "follow this person" cannot. Too
long and the next person through the door inherits the ID, which puts one
child's movements onto another — the failure this whole subsystem is built to
avoid.

The trap being pinned here is that ByteTrack does not count `track_buffer` in
real frames. `BYTETracker.__init__` computes

    max_time_lost = int(frame_rate / 30 * track_buffer)

so the number is quoted against an implied 30 fps whatever the real rate is.
`track_buffer=30` on a 5 Hz feed therefore bought five frames — one second —
while the comment beside it claimed six. Measured on the recorded clip, one
person collected four separate IDs in 120 frames.

Scaling the buffer by 30 cancels the implied rate, so the window is the same
number of seconds at any frame rate. These tests fail if anyone sets
`track_buffer` back to a raw frame count.
"""

from __future__ import annotations

import pytest

from vg.infer.tracking import (
    LOST_TRACK_SECONDS,
    TRACK_BUFFER,
    TRACKER_DEFAULTS,
    PersonTracker,
)


@pytest.mark.parametrize("frame_rate", [1.0, 5.0, 12.0, 25.0, 30.0])
def test_the_window_is_the_same_seconds_at_every_frame_rate(frame_rate: float):
    """Six seconds means six seconds, whether the feed is 5 Hz or 30."""
    tracker = PersonTracker(frame_rate=frame_rate)
    frames = tracker._tracker.max_time_lost
    assert frames / frame_rate == pytest.approx(LOST_TRACK_SECONDS, abs=0.5)


def test_the_buffer_is_scaled_not_a_raw_frame_count():
    """The regression: `track_buffer=30` was read as 30 frames. It is not.

    At 5 Hz it bought 5 frames — one second — against a comment promising six.
    """
    assert TRACK_BUFFER == int(round(30.0 * LOST_TRACK_SECONDS))
    assert TRACKER_DEFAULTS["track_buffer"] == TRACK_BUFFER

    # What the old value actually did, stated so it cannot come back quietly.
    old_max_time_lost = int(5.0 / 30.0 * 30)
    assert old_max_time_lost == 5, "the old buffer was 5 frames, not 30"
    assert PersonTracker(frame_rate=5.0)._tracker.max_time_lost == 30


def test_a_glance_away_keeps_the_id_and_a_departure_does_not():
    """Both directions of the trade-off, at the rate the Track page really uses.

    The page boosts analysis to 12 Hz. Two seconds of absence is someone
    turning to a locker; a minute is someone who left the building.
    """
    tracker = PersonTracker(frame_rate=12.0)
    window_seconds = tracker._tracker.max_time_lost / 12.0

    assert window_seconds > 2.0, "a two-second glance away must not retire the ID"
    assert window_seconds < 60.0, "a departed person must not keep their ID"
