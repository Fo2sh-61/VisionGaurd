"""The `station` alert kind and a per-event channel choice (spec 025).

A work station left empty past its limit is one message per absence. The
message names the station, the camera and, only when one was assigned, the
person it is assigned to. No picture, no clip, no detection ever goes in it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vg.alerts import catalogue, events, providers
from vg.alerts.service import AlertService
from vg.alerts.store import AlertStore, DEFAULT_RULES
from vg.clock import FixedClock
from vg.config import AlertsConfig

NOW = datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc)
SINCE = NOW - timedelta(minutes=12)


class Courier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, message, destination):
        self.sent.append((destination, message.body))
        return providers.SendResult.accepted(f"SM{len(self.sent)}")


def drain(service, passes=20):
    for _ in range(passes):
        service.step()


@pytest.fixture
def world(tmp_path, monkeypatch):
    for name in ("GMAIL_USER", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    store = AlertStore(tmp_path / "alerts.db")
    courier = Courier()
    service = AlertService(AlertsConfig(), store, None,
                           FixedClock(offset_minutes=180),
                           senders=lambda channel: courier)
    service.bind(camera_name=lambda cid: {"cam-a": "Lab camera"}.get(cid))
    store.add_recipient("email", "head@school.example", "Head")
    yield store, service, courier


def absent(**kw):
    args = dict(station_id="st1", camera_id="cam-a", at=NOW, away_since=SINCE,
                station="Lab bench 2", limit_minutes=10)
    args.update(kw)
    return events.station_absent(**args)


class TestKind:
    def test_station_is_a_kind_and_its_facts_are_allowed(self):
        assert "station" in events.KINDS
        assert {"station", "assignee", "limit"} <= events.ALLOWED_FACTS

    def test_other_facts_are_still_refused(self):
        with pytest.raises(ValueError, match="not allowed"):
            events.AlertEvent(kind="station", template="station.absent",
                              event_key="k", at=NOW, facts={"person": "Layla"})

    def test_the_key_names_the_absence_by_when_it_began(self):
        assert absent().event_key == f"station:st1:{events.stamp(SINCE)}"
        later = absent(away_since=SINCE + timedelta(hours=1))
        assert later.event_key != absent().event_key

    def test_the_default_rule_is_in_app_on_email_off(self):
        row = [r for r in DEFAULT_RULES if r[0] == "station"]
        assert row == [("station", 1, 0, None, None, None)]

    def test_an_existing_database_gets_the_rule(self, tmp_path):
        path = tmp_path / "old.db"
        AlertStore(path)
        conn = sqlite3.connect(path)
        conn.execute("DELETE FROM alert_rule WHERE kind = 'station'")
        conn.commit()
        conn.close()
        reopened = AlertStore(path)
        rule = reopened.rules()["station"]
        assert rule.in_app is True and rule.email is False


class TestMessage:
    def build(self, event, language="en"):
        return catalogue.build(event, language, clock=FixedClock(offset_minutes=180))

    def test_english_names_station_camera_and_limit(self):
        body = self.build(absent()).body
        assert "Lab bench 2" in body and "Lab camera" not in body  # no roster here
        assert "10" in body

    def test_the_assignee_is_in_brackets_only_when_there_is_one(self):
        with_one = self.build(absent(assignee="Layla")).body
        without = self.build(absent()).body
        assert "Lab bench 2 (Layla)" in with_one
        assert "(" not in without

    def test_arabic_draft_renders_too(self):
        body = self.build(absent(assignee="Layla"), "ar").body
        assert "Lab bench 2" in body

    def test_it_carries_no_picture(self):
        event = absent()
        assert event.facts.keys() <= {"station", "assignee", "limit"}
        assert "clip" not in self.build(event).body.lower()


class TestChannels:
    def test_none_changes_nothing(self, world):
        store, service, courier = world
        store.update_rule("station", email=True)
        service.enqueue(absent(channels=None))
        drain(service)
        assert len(courier.sent) == 1

    def test_an_empty_set_overrides_a_rule_that_says_email(self, world):
        store, service, courier = world
        store.update_rule("station", email=True)
        service.enqueue(absent(channels=frozenset()))
        drain(service)
        assert courier.sent == []

    def test_email_in_the_set_overrides_a_rule_that_says_no(self, world):
        store, service, courier = world
        service.enqueue(absent(channels=frozenset({"email"})))
        drain(service)
        assert len(courier.sent) == 1

    def test_one_absence_is_one_message_however_often_it_is_raised(self, world):
        store, service, courier = world
        store.update_rule("station", email=True)
        service.enqueue(absent())
        service.enqueue(absent())
        drain(service)
        assert len(courier.sent) == 1

    def test_the_intrusion_builder_is_unchanged_without_channels(self):
        event = events.intrusion_opened("s1", "cam-a", NOW)
        assert event.channels is None
        pinned = events.intrusion_opened("s1", "cam-a", NOW, channels=frozenset())
        assert pinned.channels == frozenset()
