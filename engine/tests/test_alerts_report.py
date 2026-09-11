"""The noon attendance report (spec 013, user story 5).

At 12:00 site time on a school day - Sunday to Thursday, inside the term -
each recipient on an enabled channel gets present, late and absent counts per
group, and nothing that names a student. The engine has no scheduler: the
sender's own tick fires it, and the delivery log is what stops it firing
twice, including across a restart.

The rules held here:

- once a day, never twice, never late: a noon the engine was down for is a
  logged skip, not a message at 12:30;
- a service that was running at noon with nothing switched on says nothing
  afterwards - it was not down;
- no counts (face recognition not running) is a logged skip, never a report
  of zeros that reads "everyone absent";
- Friday, Saturday and days outside the term send nothing.
"""

from __future__ import annotations

import dataclasses
import tempfile
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg import config as vgconfig
from vg.alerts import catalogue, events, providers
from vg.alerts.service import AlertService
from vg.alerts.store import AlertStore
from vg.clock import FixedClock
from vg.config import AlertsConfig

CAIRO = FixedClock(offset_minutes=180)
TERM = dataclasses.replace(vgconfig.load().hours, term_from="2026-09-20",
                           term_to="2027-06-15")
ENDED = dataclasses.replace(vgconfig.load().hours, term_from="2025-09-01",
                            term_to="2026-06-20")
TUESDAY, FRIDAY = 6, 9          # October 2026

GROUPS = (events.GroupCount("Everyone", 300, 12, 20),
          events.GroupCount("Grade 8", 28, 2, 1),
          events.GroupCount("Grade 9", 30, 0, 2))


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time at the school, as the UTC instant the engine holds."""
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc) - timedelta(minutes=180)


class Clockwork:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class Courier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, message, destination):
        self.sent.append((destination, message.body))
        return providers.SendResult.accepted(f"id{len(self.sent)}")


@pytest.fixture
def alerts(tmp_path):
    store = AlertStore(tmp_path / "alerts.db")
    store.update_rule("attendance", email=True)
    store.add_recipient("email", "head@school.example", "Head")
    store.add_recipient("email", "deputy@school.example", "Deputy")
    yield store
    store.close_db()


def sender(alerts, clock, *, hours=TERM, counts=lambda day: GROUPS, config=None,
           courier=None):
    courier = courier or Courier()
    service = AlertService(config or AlertsConfig(), alerts, None, CAIRO, hours=hours,
                           senders=lambda channel: courier, now=clock)
    service.bind(attendance_counts=counts)
    service.start(run_thread=False)
    return service, courier


def drain(service, passes: int = 10) -> None:
    for _ in range(passes):
        service.step()


def report_rows(alerts, day="2026-10-06"):
    return [r for r in alerts.recent(50) if r.event_key == f"attendance:{day}"]


class TestNoonReport:
    def test_before_noon_nothing(self, alerts):
        service, courier = sender(alerts, Clockwork(local(TUESDAY, 11, 59)))
        drain(service)
        assert alerts.recent(10) == [] and courier.sent == []

    def test_at_noon_one_report_per_person_with_counts_per_group(self, alerts):
        clock = Clockwork(local(TUESDAY, 11, 59))
        service, courier = sender(alerts, clock)
        drain(service)
        clock.now = local(TUESDAY, 12, 0)
        drain(service)
        rows = report_rows(alerts)
        assert sorted((r.recipient_name, r.outcome) for r in rows) == [
            ("Deputy", "sent"), ("Head", "sent")]
        for _, body in courier.sent:
            assert "Grade 8: 28 present, 2 late, 1 absent" in body
            assert "Everyone: 300 present, 12 late, 20 absent" in body

    def test_once_a_day(self, alerts):
        clock = Clockwork(local(TUESDAY, 12, 0))
        service, courier = sender(alerts, clock)
        drain(service)
        clock.now = local(TUESDAY, 12, 5)
        drain(service)
        assert len(report_rows(alerts)) == 2 and len(courier.sent) == 2

    def test_a_restart_inside_the_window_sends_nothing_again(self, alerts):
        clock = Clockwork(local(TUESDAY, 12, 0))
        drain(sender(alerts, clock)[0])
        clock.now = local(TUESDAY, 12, 6)
        again, courier = sender(alerts, clock)
        drain(again)
        assert len(report_rows(alerts)) == 2
        assert courier.sent == []

    def test_a_noon_the_engine_missed_is_logged_not_sent_late(self, alerts):
        service, courier = sender(alerts, Clockwork(local(TUESDAY, 12, 30)))
        drain(service)
        rows = report_rows(alerts)
        assert [(r.outcome, r.reason, r.channel) for r in rows] == [
            ("skipped", "engine_down_at_noon", "email")]
        assert courier.sent == []

    def test_running_at_noon_with_nothing_on_is_not_a_missed_noon(self, alerts):
        """It was not down: nothing was asked for, so nothing is written."""
        alerts.update_rule("attendance", email=False)
        clock = Clockwork(local(TUESDAY, 9, 0))
        service, courier = sender(alerts, clock)
        drain(service)
        clock.now = local(TUESDAY, 14, 0)
        alerts.update_rule("attendance", email=True)
        drain(service)
        assert alerts.recent(10) == [] and courier.sent == []

    @pytest.mark.parametrize("day", [FRIDAY, FRIDAY + 1])
    def test_friday_and_saturday_send_nothing(self, alerts, day):
        service, courier = sender(alerts, Clockwork(local(day, 12, 0)))
        drain(service)
        assert alerts.recent(10) == [] and courier.sent == []

    def test_outside_the_term_sends_nothing(self, alerts):
        service, courier = sender(alerts, Clockwork(local(TUESDAY, 12, 0)), hours=ENDED)
        drain(service)
        assert alerts.recent(10) == [] and courier.sent == []

    def test_no_counts_is_a_skip_never_a_report_of_zeros(self, alerts):
        service, courier = sender(alerts, Clockwork(local(TUESDAY, 12, 0)),
                                  counts=lambda day: None)
        drain(service)
        rows = report_rows(alerts)
        assert [(r.outcome, r.reason) for r in rows] == [("skipped", "attendance_unavailable")]
        assert courier.sent == []

    def test_the_report_time_is_the_sites_setting(self, alerts):
        config = AlertsConfig(report_time=dtime(9, 30))
        clock = Clockwork(local(TUESDAY, 9, 29))
        service, courier = sender(alerts, clock, config=config)
        drain(service)
        assert courier.sent == []
        clock.now = local(TUESDAY, 9, 30)
        drain(service)
        assert len(courier.sent) == 2


class TestTheCountsComeFromTheRegister:
    """The report adds no calculation: it asks the same register the
    Attendance page reads, per group, and a count carries no name."""

    def test_counts_per_group_and_nobody_named(self):
        from vg.api.live import LiveStore
        from vg.events.sightings import Sighting, SightingStore
        from vg.identity.gallery import FaceGallery
        from vg.ingest.registry import CameraRegistry

        model = "sface-2021dec"
        tmp = tempfile.TemporaryDirectory()
        gallery = FaceGallery(Path(tmp.name) / "g.db", model=model, threshold=0.363)
        sightings = SightingStore(Path(tmp.name) / "s.db", clock=180)
        try:
            for index, (pid, name, group) in enumerate([
                ("p-layla", "Layla Ahmed", "Grade 8"),
                ("p-omar", "Omar Khaled", "Grade 8"),
                ("p-youssef", "Youssef Ali", "Grade 9"),
            ]):
                vector = np.random.default_rng(index).standard_normal(128).astype("float32")
                gallery.add_person(pid, name, group=group)
                gallery.add_embedding(pid, vector / float(np.linalg.norm(vector)), model)
            store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                              gallery=gallery, sightings=sightings)
            today = store.clock.today()
            first_thing = datetime.fromisoformat(f"{today}T07:40:00") - timedelta(
                minutes=store.clock.offset_minutes())
            sightings.record(Sighting("p-layla", "cam-entrance",
                                      first_thing.replace(tzinfo=timezone.utc), 0.8, model),
                             force=True)

            counts = store._attendance_counts(today)
            by_group = {c.name: c for c in counts}
            assert by_group["Grade 8"].present == 1 and by_group["Grade 8"].absent == 1
            assert by_group["Grade 9"].present == 0 and by_group["Grade 9"].absent == 1
            assert by_group["Everyone"].present == 1

            body = catalogue.build(events.attendance_report(today, datetime.now(timezone.utc),
                                                            counts), "en", clock=CAIRO).body
            for name in ("Layla", "Omar", "Youssef", "Ahmed", "Khaled", "p-layla"):
                assert name not in body
        finally:
            sightings.close()
            gallery.close()
            tmp.cleanup()

    def test_no_register_is_no_counts(self):
        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry

        store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]))
        assert store._attendance_counts(store.clock.today()) is None
