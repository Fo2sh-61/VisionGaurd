"""Alerts on the phone (spec 020, US5, P9-FR-101...109; T031).

A phone registers itself from the phone app and receives nothing until an
administrator switches it on, like a new email recipient (spec 013). A
notification says only what kind of thing happened, on which camera, at what
site time - never a name, a face, a picture, a plate or a reviewer - and its
title says what is known: "Possible knife" until a person decides. It goes
only to the browsers' own push services, end-to-end encrypted by Web Push, and
a failure is a row in the delivery log, never silence. No test touches the
network: the Web Push call is a stand-in.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from vg import config as vgconfig
from vg.alerts import catalogue, events, providers
from vg.alerts import push as push_mod
from vg.alerts.service import AlertService
from vg.alerts.store import AlertStore
from vg.clock import clock_for
from vg.config import AlertsConfig

from conftest import LAN

NOW = datetime(2026, 10, 20, 11, 5, tzinfo=timezone.utc)      # 14:05 in Cairo
CAIRO = clock_for("Africa/Cairo")
FCM = "https://fcm.googleapis.com/fcm/send/abc123"
HOSTS = vgconfig.PushConfig().allowed_hosts
KEYS = {"p256dh": "BOr" + "x" * 84, "auth": "a" * 22}


@pytest.fixture
def alert_db(tmp_path):
    store = AlertStore(tmp_path / "alerts.db")
    yield store
    store.close_db()


@pytest.fixture
def vapid(monkeypatch):
    public, private = push_mod.make_vapid_keys()
    monkeypatch.setenv("VG_VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("VG_VAPID_PRIVATE_KEY", private)
    monkeypatch.setenv("VG_VAPID_SUBJECT", "mailto:vg.factory@example.com")
    return public


def a_phone(store, user="u1", name="Ali", endpoint=FCM, label="Pixel"):
    device, recipient = store.register_push_device(
        user_id=user, user_name=name, label=label, endpoint=endpoint,
        p256dh=KEYS["p256dh"], auth=KEYS["auth"])
    return device, recipient


# --- what a notification says -------------------------------------------------

def named(event, camera_name):
    """The camera's name, as the sender thread fills it in."""
    return replace(event, camera_name=camera_name)


class TestWording:
    def build(self, event, language="en", draft=False):
        return catalogue.build_push(event, language, clock=CAIRO, send_draft_arabic=draft)

    def test_an_open_knife_is_possible_not_confirmed(self):
        msg = self.build(named(events.weapon_opened("s1", "cam-g2", NOW, 0.91), "Gate 2"))
        assert msg.subject == "Possible knife"
        assert msg.body == "Gate 2 · 14:05"
        assert msg.path == "/weapons"

    @pytest.mark.parametrize("verdict,title", [("confirmed", "Knife confirmed"),
                                               ("dismissed", "False alarm")])
    def test_the_verdict_titles(self, verdict, title):
        event = events.weapon_verdict("s1", "cam-g2", NOW, verdict, "Mr Reviewer", since=NOW)
        msg = self.build(named(event, "Gate 2"))
        assert msg.subject == title
        assert "Reviewer" not in msg.body and "Reviewer" not in msg.subject

    def test_nothing_but_kind_camera_and_time(self):
        """A gate alert carries a plate, a gate and a confidence: none go out."""
        event = named(events.gate_alert("p1", "cam-gate", NOW, "ABC 123", 4, "blacklist", 0.87, True),
            "Main gate")
        msg = self.build(event)
        text = msg.subject + " " + msg.body
        # "Blacklisted car" is the kind of alert; the plate, the gate number,
        # the reader's confidence and its doubt are facts, and stay home.
        for leak in ("ABC", "123", "87", "4 ", "uncertain", "weak"):
            assert leak not in text, leak
        assert msg.body == "Main gate · 14:05"

    def test_every_template_has_a_title_in_both_languages(self):
        for template in catalogue.TEMPLATES:
            if template in ("vehicles.weak_read", "attendance.group", "attendance.empty",
                            "attendance.more"):
                continue
            assert set(catalogue.PUSH_TITLES[template]) == {"en", "ar"}, template

    def test_arabic_only_once_reviewed_or_asked_for(self):
        event = events.intrusion_opened("z1", "cam-a", NOW)
        assert self.build(event, "ar").language == "en"
        assert self.build(event, "ar", draft=True).language == "ar"

    def test_a_report_says_no_counts(self):
        event = events.attendance_report("2026-10-20", NOW, (events.GroupCount("Grade 8", 30, 2, 1),))
        msg = self.build(event)
        assert "30" not in msg.body and "Grade" not in msg.body
        assert msg.path == "/attendance"


# --- the store --------------------------------------------------------------------

class TestStore:
    def test_push_is_off_for_every_kind_on_a_fresh_install(self, alert_db):
        assert all(rule.push is False for rule in alert_db.rules().values())
        assert "push" in events.CHANNELS

    def test_an_older_database_gains_the_column_and_keeps_its_rules(self, tmp_path):
        path = tmp_path / "old.db"
        with sqlite3.connect(path) as old:
            old.execute("CREATE TABLE alert_rule (kind TEXT PRIMARY KEY, in_app INTEGER,"
                        " email INTEGER NOT NULL DEFAULT 0, vehicle_blacklist INTEGER,"
                        " vehicle_unknown INTEGER, vehicle_expired INTEGER)")
            old.execute("INSERT INTO alert_rule VALUES ('weapon', 1, 1, NULL, NULL, NULL)")
        store = AlertStore(path)
        try:
            rule = store.rules()["weapon"]
            assert (rule.email, rule.push) == (True, False)
            assert store.update_rule("weapon", push=True).push is True
        finally:
            store.close_db()

    def test_a_new_phone_is_listed_switched_off(self, alert_db):
        device, recipient = a_phone(alert_db)
        assert (recipient.channel, recipient.destination) == ("push", device.id)
        assert recipient.enabled is False
        assert recipient.name == "Ali · Pixel"

    def test_the_same_phone_again_is_the_same_entry(self, alert_db):
        first, _ = a_phone(alert_db)
        again, _ = a_phone(alert_db, label="Pixel 8")
        assert again.id == first.id
        assert len([r for r in alert_db.recipients() if r.channel == "push"]) == 1

    def test_a_phone_passed_to_another_person_is_switched_off_again(self, alert_db):
        device, recipient = a_phone(alert_db)
        alert_db.update_recipient(recipient.id, enabled=True)
        _, now = a_phone(alert_db, user="u2", name="Sara")
        assert now.enabled is False and now.name == "Sara · Pixel"

    def test_removing_the_recipient_removes_the_phone(self, alert_db):
        device, recipient = a_phone(alert_db)
        assert alert_db.remove_recipient(recipient.id)
        assert alert_db.push_device(device.id) is None

    def test_removing_the_phone_removes_the_recipient(self, alert_db):
        device, recipient = a_phone(alert_db)
        assert alert_db.remove_push_device(device.id)
        assert alert_db.recipient(recipient.id) is None

    def test_an_accounts_phones_go_together(self, alert_db):
        a_phone(alert_db, endpoint=FCM + "1")
        a_phone(alert_db, endpoint=FCM + "2")
        a_phone(alert_db, user="u2", name="Sara", endpoint=FCM + "3")
        assert alert_db.remove_devices_of("u1") == 2
        assert [d.user_id for d in alert_db.push_devices()] == ["u2"]

    def test_a_phone_cannot_be_typed_in_as_a_recipient(self, alert_db):
        with pytest.raises(ValueError):
            alert_db.add_recipient("push", "0" * 32, "Someone")


# --- where a notification may go --------------------------------------------------

class TestEndpoints:
    @pytest.mark.parametrize("url", [
        FCM,
        "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
        "https://web.push.apple.com/QGuQyavXutnMH",
        "https://fcm.googleapis.com:443/fcm/send/x",
    ])
    def test_the_browsers_push_services(self, url):
        assert push_mod.endpoint_allowed(url, HOSTS)

    @pytest.mark.parametrize("url", [
        "http://fcm.googleapis.com/fcm/send/x",              # not https
        "https://192.168.1.1/x",                              # the factory network
        "https://127.0.0.1:8000/x",                           # the engine itself
        "https://[::1]/x",
        "https://fcm.googleapis.com:8443/x",                  # another port
        "https://fcm.googleapis.com.evil.example/x",
        "https://evil.example/fcm.googleapis.com",
        "https://user@fcm.googleapis.com/x",
        "https://notify.windows.com/x",                       # the wildcard needs a name
        "ftp://fcm.googleapis.com/x",
        "",
        "https://" + "a" * 3000,
    ])
    def test_nothing_else(self, url):
        assert not push_mod.endpoint_allowed(url, HOSTS)


# --- the courier ------------------------------------------------------------------------

class FakeWebPush:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises

        class Answer:
            status_code = 201
            headers = {"Location": "https://fcm.googleapis.com/msg/42"}
        return Answer()


def gone(status):
    response = requests.Response()
    response.status_code = status
    return push_mod.WebPushException("Push failed", response=response)


def sender(store, webpush, active=lambda user_id: True):
    return push_mod.PushSender(store=store, allowed_hosts=HOSTS, user_active=active,
                               timeout=10, webpush=webpush)


MESSAGE = catalogue.Message(subject="Possible knife", body="Gate 2 · 14:05",
                            language="en", path="/weapons")


class TestCourier:
    def test_it_sends_only_title_body_and_page(self, alert_db, vapid):
        device, _ = a_phone(alert_db)
        webpush = FakeWebPush()
        result = sender(alert_db, webpush).send(MESSAGE, device.id)
        assert result.ok and result.provider_id == "https://fcm.googleapis.com/msg/42"
        [call] = webpush.calls
        assert json.loads(call["data"]) == {
            "title": "Possible knife", "body": "Gate 2 · 14:05", "path": "/weapons"}
        assert call["subscription_info"] == {"endpoint": FCM, "keys": KEYS}
        assert call["vapid_claims"] == {"sub": "mailto:vg.factory@example.com"}
        assert call["ttl"] > 0

    def test_a_phone_that_was_removed(self, alert_db, vapid):
        result = sender(alert_db, FakeWebPush()).send(MESSAGE, "0" * 32)
        assert (result.ok, result.reason) == (False, "device_gone")

    def test_a_disabled_account_gets_nothing(self, alert_db, vapid):
        device, _ = a_phone(alert_db)
        webpush = FakeWebPush()
        result = sender(alert_db, webpush, active=lambda user_id: False).send(MESSAGE, device.id)
        assert (result.ok, result.reason) == (False, "account_disabled")
        assert webpush.calls == []

    @pytest.mark.parametrize("status", [404, 410])
    def test_a_subscription_the_service_forgot_removes_the_phone(self, alert_db, vapid, status):
        device, recipient = a_phone(alert_db)
        result = sender(alert_db, FakeWebPush(raises=gone(status))).send(MESSAGE, device.id)
        assert (result.ok, result.reason) == (False, "device_gone")
        assert alert_db.push_device(device.id) is None
        assert alert_db.recipient(recipient.id) is None

    def test_no_internet_says_so(self, alert_db, vapid):
        device, _ = a_phone(alert_db)
        result = sender(alert_db, FakeWebPush(raises=requests.ConnectionError("nope"))
                        ).send(MESSAGE, device.id)
        assert (result.ok, result.reason) == (False, "unreachable")
        assert "no internet" in result.provider_reason

    def test_a_stored_address_that_is_not_a_push_service_is_never_called(self, alert_db, vapid):
        device, _ = a_phone(alert_db)
        alert_db._conn.execute("UPDATE push_device SET endpoint = 'https://192.168.1.1/x'")
        webpush = FakeWebPush()
        result = sender(alert_db, webpush).send(MESSAGE, device.id)
        assert not result.ok and webpush.calls == []

    def test_no_keys_means_the_channel_is_not_set_up(self, alert_db, monkeypatch):
        for name in providers.REQUIRED_ENV["push"]:
            monkeypatch.delenv(name, raising=False)
        assert providers.missing_env("push") == list(providers.REQUIRED_ENV["push"])
        assert providers.for_channel("push", push={"store": alert_db}) is None

    def test_the_private_key_never_reaches_a_log_row(self, alert_db, vapid, monkeypatch):
        private = providers.os.environ["VG_VAPID_PRIVATE_KEY"]
        assert private not in (providers.redact(f"oops {private}") or "")


# --- through the sender thread ----------------------------------------------------------

def a_service(store, webpush, active=lambda user_id: True):
    return AlertService(AlertsConfig(), store, None, CAIRO, now=lambda: NOW,
                        senders=lambda channel: sender(store, webpush, active)
                        if channel == "push" else None)


class TestSending:
    def test_a_new_phone_receives_nothing_until_switched_on(self, alert_db, vapid):
        alert_db.update_rule("weapon", push=True)
        a_phone(alert_db)
        webpush = FakeWebPush()
        service = a_service(alert_db, webpush)
        service.enqueue(events.weapon_opened("s1", "cam-a", NOW, 0.9))
        service.step()
        assert webpush.calls == []
        assert {(r.channel, r.outcome, r.reason) for r in alert_db.recent(5)} == {
            ("push", "skipped", "recipient_off"), ("push", "skipped", "no_recipients")}

    def test_push_alone_with_email_off(self, alert_db, vapid):
        """P9-FR-107: a strict factory uses notifications only."""
        alert_db.update_rule("weapon", push=True, email=False)
        _, recipient = a_phone(alert_db)
        alert_db.update_recipient(recipient.id, enabled=True)
        alert_db.add_recipient("email", "head@school.example", "Head")
        webpush = FakeWebPush()
        service = a_service(alert_db, webpush)
        service.enqueue(events.weapon_opened("s1", "cam-a", NOW, 0.9))
        service.step()
        assert len(webpush.calls) == 1
        assert [(r.channel, r.outcome) for r in alert_db.recent(5)] == [("push", "sent")]
        assert json.loads(webpush.calls[0]["data"])["title"] == "Possible knife"

    def test_the_verdict_follows_to_the_same_phone(self, alert_db, vapid):
        alert_db.update_rule("weapon", push=True)
        _, recipient = a_phone(alert_db)
        alert_db.update_recipient(recipient.id, enabled=True)
        webpush = FakeWebPush()
        service = a_service(alert_db, webpush)
        service.enqueue(events.weapon_opened("s1", "cam-a", NOW, 0.9))
        service.step()
        service.enqueue(events.weapon_verdict("s1", "cam-a", NOW, "confirmed", "Guard A"))
        service.step()
        titles = [json.loads(c["data"])["title"] for c in webpush.calls]
        assert titles == ["Possible knife", "Knife confirmed"]

    def test_a_failed_notification_is_a_row_with_its_reason(self, alert_db, vapid):
        alert_db.update_rule("intrusion", push=True)
        _, recipient = a_phone(alert_db)
        alert_db.update_recipient(recipient.id, enabled=True)
        service = a_service(alert_db, FakeWebPush(raises=requests.ConnectionError("down")))
        clock = [NOW]
        service._now = lambda: clock[0]
        service.enqueue(events.intrusion_opened("z1", "cam-a", NOW))
        for _ in range(5):                     # the retries, 5 s apart
            service.step()
            clock[0] += timedelta(seconds=10)
        [row] = alert_db.recent(5)
        assert (row.outcome, row.reason) == ("failed", "unreachable")
        assert "no internet" in row.provider_reason


# --- the API ----------------------------------------------------------------------------

@pytest.fixture
def live(tmp_path, user_store):
    from vg.api import app as app_module
    from vg.api.live import LiveStore
    from vg.api.store import MockStore
    from vg.ingest.registry import CameraRegistry

    alerts = AlertStore(tmp_path / "alerts.db")
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                      users=user_store, alerts_store=alerts)
    app_module.set_store(store)
    yield store
    app_module.set_store(MockStore())
    alerts.close_db()


def person(app, user_store, email, role="it", name=None):
    user = user_store.create_user(email=email, name=name or email.split("@")[0],
                                  role=role, password="a-long-enough-test-password")
    token, _ = user_store.start_session(user)
    app.state.users = user_store
    return TestClient(app, client=LAN, headers={"Authorization": f"Bearer {token}"}), user


SUBSCRIPTION = {"endpoint": FCM, "keys": KEYS, "label": "Pixel"}


class TestApi:
    @pytest.fixture
    def app(self, live):
        from vg.api.app import create_app
        return create_app()

    def test_the_public_key_or_why_not(self, app, user_store, monkeypatch):
        for name in providers.REQUIRED_ENV["push"]:
            monkeypatch.delenv(name, raising=False)
        client, _ = person(app, user_store, "ali@x.com")
        body = client.get("/push/key").json()
        assert body["available"] is False and "VG_VAPID_PUBLIC_KEY" in body["reason"]

    def test_the_public_key(self, app, user_store, vapid):
        client, _ = person(app, user_store, "ali@x.com")
        assert client.get("/push/key").json() == {
            "available": True, "publicKey": vapid, "reason": None}

    def test_any_signed_in_person_registers_their_own_phone(self, app, user_store, live):
        client, user = person(app, user_store, "ali@x.com")
        answer = client.post("/push/devices", json=SUBSCRIPTION)
        assert answer.status_code == 201
        assert answer.json()["enabled"] is False and answer.json()["label"] == "Pixel"
        [entry] = [e for e in live.audit(20) if e.action == "push.register"]
        assert entry.actor == user.name

    def test_a_push_address_that_is_not_a_push_service_is_refused(self, app, user_store):
        client, _ = person(app, user_store, "ali@x.com")
        for endpoint in ("http://fcm.googleapis.com/x", "https://192.168.1.1/x",
                         "https://127.0.0.1:8000/healthz"):
            answer = client.post("/push/devices", json={**SUBSCRIPTION, "endpoint": endpoint})
            assert answer.status_code == 400, endpoint

    def test_each_person_sees_and_removes_only_their_own(self, app, user_store):
        ali, _ = person(app, user_store, "ali@x.com")
        sara, _ = person(app, user_store, "sara@x.com")
        mine = ali.post("/push/devices", json=SUBSCRIPTION).json()
        sara.post("/push/devices", json={**SUBSCRIPTION, "endpoint": FCM + "sara"})
        assert [d["id"] for d in ali.get("/push/devices").json()] == [mine["id"]]
        assert sara.delete(f"/push/devices/{mine['id']}").status_code == 404
        assert ali.delete(f"/push/devices/{mine['id']}").status_code == 204
        assert ali.get("/push/devices").json() == []

    def test_an_administrator_switches_a_phone_on_in_the_recipient_list(self, app, user_store):
        ali, _ = person(app, user_store, "ali@x.com")
        admin, _ = person(app, user_store, "head@x.com", role="admin")
        ali.post("/push/devices", json=SUBSCRIPTION)
        [phone] = [r for r in admin.get("/settings/alerts").json()["recipients"]
                   if r["channel"] == "push"]
        assert phone["enabled"] is False
        admin.patch(f"/settings/alerts/recipients/{phone['id']}", json={"enabled": True})
        assert ali.get("/push/devices").json()[0]["enabled"] is True

    def test_disabling_an_account_removes_its_phones(self, app, user_store, live):
        ali, user = person(app, user_store, "ali@x.com")
        admin, _ = person(app, user_store, "head@x.com", role="admin")
        ali.post("/push/devices", json=SUBSCRIPTION)
        assert admin.patch(f"/users/{user.id}", json={"disabled": True}).status_code == 200
        assert live.alerts_store.push_devices() == []
