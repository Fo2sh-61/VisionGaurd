"""The site clock, and the hour it used to lose every October.

The engine worked out "Cairo is 180 minutes ahead of UTC" once, when the
process started, and used that number for every timestamp afterwards. Egypt
puts its clocks back on the last Friday in October, so an engine started in
September is an hour wrong from that Friday until somebody restarts it. Every
arrival time, every chart bucket and every "which school day is this?"
boundary, all silently off by one hour, with nothing on any screen to say so.

The fix is that an offset is not a property of the site. It is a property of an
instant at the site. So every test here builds **one** clock and then asks it
about two instants on opposite sides of a transition - because building a new
clock per test would pass even with the bug still in.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vg.clock import Clock, FixedClock, SiteClock, clock_for

# 04:42 UTC. In Cairo that is 07:42 in summer and 06:42 in winter - a school
# arrival either side of the October change.
SUMMER = datetime(2026, 7, 15, 4, 42, tzinfo=timezone.utc)
WINTER = datetime(2026, 11, 5, 4, 42, tzinfo=timezone.utc)


@pytest.fixture
def cairo() -> Clock:
    """One clock, built once. Exactly like an engine that has been up a while."""
    clock = SiteClock("Africa/Cairo")
    if not clock.ok:
        pytest.skip("no timezone database available (pip install tzdata)")
    return clock


class TestTheHourThatWentMissing:
    def test_one_clock_gives_two_answers(self, cairo):
        """The whole bug in one assertion.

        A single long-lived clock must report summer time in July and winter
        time in November. Frozen at startup it reported 180 for both.
        """
        assert cairo.offset_minutes(SUMMER) == 180
        assert cairo.offset_minutes(WINTER) == 120

    def test_a_july_morning_still_reads_07_42_in_the_winter(self, cairo):
        """The choice, stated as a test.

        A past moment keeps the offset it happened under, so a register
        printed in July still matches the screen in December. Rendering
        everything with today's offset would move every historical arrival by
        an hour on the day the clocks change.
        """
        assert cairo.local(SUMMER).strftime("%H:%M") == "07:42"
        assert cairo.local(WINTER).strftime("%H:%M") == "06:42"

    def test_the_school_day_boundary_moves_with_the_clock(self, cairo):
        """22:30 UTC is already tomorrow in Cairo, and by a different margin
        in each season. Filing an arrival under the wrong date corrupts the
        register silently."""
        summer_night = datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)
        winter_night = datetime(2026, 11, 5, 22, 30, tzinfo=timezone.utc)

        assert cairo.local_date(summer_night) == "2026-07-16"
        assert cairo.local_date(winter_night) == "2026-11-06"

    def test_the_last_friday_in_october_is_where_it_flips(self, cairo):
        """Pinning the transition itself, not just two months far apart."""
        before = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
        after = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
        assert cairo.offset_minutes(before) != cairo.offset_minutes(after)


class TestATimestampCarriesItsOwnOffset:
    def test_instant_stamps_the_offset_of_the_moment_not_of_today(self, cairo):
        """`_instant` is what every timestamp in the API goes through."""
        from vg.api.live import _instant

        assert _instant(SUMMER, cairo).tz_offset_minutes == 180
        assert _instant(WINTER, cairo).tz_offset_minutes == 120

    def test_no_moment_is_no_instant(self, cairo):
        from vg.api.live import _instant

        assert _instant(None, cairo) is None


class TestTheStoresMoveWithIt:
    def test_a_sighting_is_filed_under_the_right_school_day(self, cairo):
        """The store used to hold the same frozen number the API did."""
        from vg.events.sightings import SightingStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SightingStore(Path(tmp) / "s.db", clock=cairo)
            # 22:30 UTC: past midnight in Cairo in both seasons, so both
            # belong to the following day.
            assert store.local_date(
                datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)) == "2026-07-16"
            assert store.local_date(
                datetime(2026, 11, 5, 22, 30, tzinfo=timezone.utc)) == "2026-11-06"
            store.close()

    def test_an_hour_bucket_stays_where_it_happened(self, cairo):
        """A headcount chart labelled by hour must not shift its bars."""
        from vg.events.counts import AreaCountStore

        with tempfile.TemporaryDirectory() as tmp:
            store = AreaCountStore(Path(tmp) / "c.db", clock=cairo)
            assert store._local(SUMMER).hour == 7
            assert store._local(WINTER).hour == 6
            store.close()


class TestABrokenClockSaysSo:
    def test_an_unresolvable_zone_admits_it_rather_than_pretending(self):
        """Constitution rule 8: it must say so in the UI, not only the log.

        Falling back to UTC is survivable. Doing it silently is not - Cairo
        would read three hours early and a 6:12am arrival shows as 3:12am with
        nothing to hint that it is wrong.
        """
        clock = SiteClock("Mars/Olympus_Mons")
        assert clock.ok is False
        assert clock.error and "tzdata" in clock.error
        assert clock.offset_minutes(SUMMER) == 0

    def test_system_health_carries_the_failure(self, bare_live_store):
        stage = bare_live_store._clock_stage()
        assert stage.key == "clock"

        bare_live_store.clock = SiteClock("Mars/Olympus_Mons")
        broken = bare_live_store._clock_stage()
        assert broken.healthy is False
        assert "timezone" in broken.detail

    def test_a_working_clock_shows_which_one_it_is(self, cairo, bare_live_store):
        bare_live_store.clock = cairo
        stage = bare_live_store._clock_stage()
        assert stage.healthy is True
        assert "Africa/Cairo" in stage.detail and "UTC+0" in stage.detail


class TestFixedClock:
    def test_a_fixed_offset_never_moves(self):
        """Tests need a clock that gives the same answer in June and December,
        or they would change their own answers twice a year."""
        clock = FixedClock(180)
        assert clock.offset_minutes(SUMMER) == clock.offset_minutes(WINTER) == 180

    def test_a_plain_number_still_works(self):
        """The stores used to take `tz_offset_minutes: int`."""
        assert clock_for(180).offset_minutes() == 180
        assert clock_for(None).offset_minutes() == 0

    def test_a_name_becomes_a_real_clock(self):
        assert isinstance(clock_for("Africa/Cairo"), SiteClock)

    def test_a_clock_passes_through_unchanged(self):
        clock = FixedClock(60)
        assert clock_for(clock) is clock


class TestNaiveDatetimes:
    def test_a_naive_time_is_treated_as_utc(self, cairo):
        """The stores write ISO-8601 UTC throughout, but a datetime parsed
        without an offset must not silently become local time."""
        naive = SUMMER.replace(tzinfo=None)
        assert cairo.local(naive) == cairo.local(SUMMER)
