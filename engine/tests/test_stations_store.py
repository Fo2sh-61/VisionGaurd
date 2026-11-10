"""The station log: segments, events, acknowledgements (spec 025, T036).

What can lie here: a segment that outlives an engine that died, an absence
alerted twice, an acknowledgement that rewrites the alert it answers, and a
day's figures that count time nobody measured.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vg.events.stations import HEARTBEAT_SECONDS, StationStore

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def at(minutes=0.0, seconds=0.0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


@pytest.fixture
def store(tmp_path):
    s = StationStore(tmp_path / "stations.db")
    yield s
    s.close_db()


class TestSegments:
    def test_open_and_close(self, store):
        sid = store.open_segment("st1", "on", at())
        store.close_segment(sid, at(5))
        (seg,) = store.segments("st1", at(-1), at(10))
        assert (seg.state, seg.started_at, seg.ended_at) == ("on", at(), at(5))

    def test_a_state_other_than_on_away_absent_is_refused(self, store):
        with pytest.raises(ValueError):
            store.open_segment("st1", "asleep", at())

    def test_closing_twice_changes_nothing(self, store):
        sid = store.open_segment("st1", "on", at())
        store.close_segment(sid, at(5))
        store.close_segment(sid, at(9))
        assert store.segments("st1", at(), at(10))[0].ended_at == at(5)

    def test_touch_writes_at_most_every_ten_seconds(self, store):
        sid = store.open_segment("st1", "on", at())
        assert store.touch(sid, at(seconds=3)) is False
        assert store.touch(sid, at(seconds=HEARTBEAT_SECONDS)) is True
        assert store.touch(sid, at(seconds=HEARTBEAT_SECONDS + 4)) is False
        seg = store.segments("st1", at(-1), at(10))[0]
        assert seg.checked_at == at(seconds=HEARTBEAT_SECONDS)

    def test_close_orphans_ends_open_rows_where_they_were_last_confirmed(
            self, store):
        sid = store.open_segment("st1", "on", at())
        store.touch(sid, at(seconds=30))
        assert store.close_orphans() == 1
        seg = store.segments("st1", at(-1), at(10))[0]
        assert seg.ended_at == at(seconds=30)
        assert store.close_orphans() == 0

    def test_it_works_for_a_station_nobody_lists_any_more(self, store):
        sid = store.open_segment("deleted-one", "on", at())
        store.close_segment(sid, at(1))
        assert store.segments("deleted-one", at(-1), at(2))


class TestEvents:
    def test_a_duplicate_alert_key_is_refused(self, store):
        first = store.add_event("st1", at(), "absence_alert", limit_minutes=5,
                                alert_key="station:st1:x")
        again = store.add_event("st1", at(1), "absence_alert", limit_minutes=5,
                                alert_key="station:st1:x")
        assert first and again is None
        assert len(store.events("st1", at(-1), at(10))) == 1

    def test_the_absence_hook_runs_once_per_absence(self, store):
        calls = []
        store.on_alert = lambda *a: calls.append(a)
        for _ in range(3):
            store.absence_alert("st1", "cam-a", at(5), at(), "Bench", 5)
        assert len(calls) == 1
        assert calls[0][0] == "st1" and calls[0][5] == 5
        store.absence_alert("st1", "cam-a", at(35), at(30), "Bench", 5)
        assert len(calls) == 2, "a new absence is a new alert"

    def test_a_failing_hook_does_not_lose_the_row(self, store):
        def boom(*a):
            raise RuntimeError("mail is down")
        store.on_alert = boom
        assert store.absence_alert("st1", "cam-a", at(5), at(), "Bench", 5)
        assert store.open_alerts("st1")

    def test_acknowledging_writes_a_row_and_changes_nothing_else(self, store):
        alert = store.absence_alert("st1", "cam-a", at(5), at(), "Bench", 5)
        assert store.acknowledge("st1", "Mona", at(6)) is not None
        events = store.events("st1", at(), at(10))
        assert [e.kind for e in events] == ["acknowledged", "absence_alert"]
        assert events[0].ref == alert and events[0].by_who == "Mona"
        assert store.get_event(alert).kind == "absence_alert"
        assert store.open_alerts("st1") == []

    def test_acknowledging_with_nothing_to_answer_is_none(self, store):
        assert store.acknowledge("st1", "Mona", at()) is None

    def test_an_alert_cannot_be_acknowledged_twice(self, store):
        store.absence_alert("st1", "cam-a", at(5), at(), "Bench", 5)
        assert store.acknowledge("st1", "Mona", at(6))
        assert store.acknowledge("st1", "Sara", at(7)) is None

    def test_open_alerts_lists_only_unanswered_ones_newest_first(self, store):
        a = store.absence_alert("st1", "cam-a", at(5), at(), "Bench", 5)
        b = store.absence_alert("st1", "cam-a", at(45), at(40), "Bench", 5)
        other = store.absence_alert("st2", "cam-a", at(46), at(41), "Other", 5)
        store.acknowledge("st1", "Mona", at(46), event_id=a)
        assert [e.id for e in store.open_alerts("st1")] == [b]
        assert {e.id for e in store.open_alerts()} == {b, other}

    def test_events_are_newest_first_and_bounded_by_the_day(self, store):
        store.add_event("st1", at(1), "at_station")
        store.add_event("st1", at(2), "left_station")
        store.add_event("st1", at(60 * 24 + 1), "at_station")
        got = store.events("st1", at(), at(60 * 24))
        assert [e.kind for e in got] == ["left_station", "at_station"]

    def test_an_unknown_kind_is_refused(self, store):
        with pytest.raises(ValueError):
            store.add_event("st1", at(), "waved")


class TestFigures:
    def window(self, start_min=0, end_min=60):
        return [(at(start_min), at(end_min))]

    def seg(self, store, state, a, b=None):
        sid = store.open_segment("st1", state, at(a))
        if b is not None:
            store.close_segment(sid, at(b))
        return sid

    def test_sums_clip_to_the_watched_window(self, store):
        self.seg(store, "on", -30, 20)         # starts before the window opens
        self.seg(store, "away", 20, 30)
        self.seg(store, "on", 30, 90)          # runs past it
        f = store.figures("st1", self.window(), at(60))
        assert f.work_seconds == 50 * 60 and f.away_seconds == 10 * 60
        assert f.not_watched_seconds == 0 and f.watched_seconds == 3600
        assert f.rate == pytest.approx(50 / 60)

    def test_uncovered_watched_time_is_not_watched_and_not_in_the_rate(self, store):
        self.seg(store, "on", 0, 20)
        self.seg(store, "away", 20, 30)
        f = store.figures("st1", self.window(), at(60))
        assert f.not_watched_seconds == 30 * 60
        assert f.rate == pytest.approx(20 / 30), "over covered time only"
        assert [s for s, *_ in f.timeline] == ["on", "away", "notWatched"]

    def test_nothing_covered_means_no_rate(self, store):
        f = store.figures("st1", self.window(), at(60))
        assert f.rate is None and f.not_watched_seconds == 3600

    def test_absence_counts_as_off_station(self, store):
        self.seg(store, "away", 0, 5)
        self.seg(store, "absent", 5, 15)
        f = store.figures("st1", self.window(), at(60))
        assert f.absent_seconds == 10 * 60 and f.off_station_seconds == 15 * 60

    def test_nothing_after_now_is_counted(self, store):
        self.seg(store, "on", 0, 50)
        f = store.figures("st1", self.window(), at(10))
        assert f.watched_seconds == 600 and f.work_seconds == 600

    def test_an_open_segment_counts_to_now_while_confirmed(self, store):
        sid = self.seg(store, "on", 0)
        store.touch(sid, at(10))
        f = store.figures("st1", self.window(), at(10, 5))
        assert f.work_seconds == 10 * 60 + 5

    def test_an_open_segment_stops_where_it_was_last_confirmed(self, store):
        sid = self.seg(store, "on", 0)
        store.touch(sid, at(10))
        f = store.figures("st1", self.window(), at(40))
        assert f.work_seconds == 10 * 60
        assert f.watched_seconds == 40 * 60
        assert f.not_watched_seconds == 30 * 60

    def test_two_windows_are_summed_separately(self, store):
        self.seg(store, "on", 0, 200)
        f = store.figures("st1", [(at(0), at(10)), (at(100), at(110))], at(300))
        assert f.watched_seconds == 1200 and f.work_seconds == 1200

    def test_no_window_means_empty_figures(self, store):
        assert store.figures("st1", [], at(60)).watched_seconds == 0
