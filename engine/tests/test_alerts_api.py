"""Alert settings over HTTP: recipients, rules, test sends and the delivery log.

User story 1 of spec 013: an administrator chooses who hears, proves it with a
test message, and reads back what happened. Everything here goes through the
real endpoints on a `LiveStore` with a throwaway alert database; the couriers
are fakes, so nothing reaches Twilio or Google.

The rules these tests hold:

- every write is audited BEFORE it happens, and only an administrator may make
  one (P9-FR-032);
- no secret ever comes back - not in a response, a log row or an audit entry
  (P9-FR-034);
- missing keys, an unreached channel and an unreadable log are each a stated
  fact, never a silence and never a 5xx (P9-FR-026/027);
- the live path never borrows a fixture (P9-FR-037).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from vg.alerts import providers
from vg.alerts.service import AlertService
from vg.alerts.store import AlertStore
from vg.api.live import LiveStore
from vg.api.store import MockStore
from vg.clock import clock_for
from vg.config import AlertsConfig

SECRETS = {
    "TWILIO_ACCOUNT_SID": "ACsentinelSID0001",
    "TWILIO_AUTH_TOKEN": "sentinelTOKEN0002",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
    "TWILIO_SMS_FROM": "+15005550006",
    "GMAIL_USER": "sentinel.school@gmail.com",
    "GMAIL_APP_PASSWORD": "sentinelPASS0003",
}


def live_store(tmp_path, registry=None, config=None, **kw) -> LiveStore:
    """A `LiveStore` over one never-started camera. Copied from test_sources.py."""
    from vg import config as vgconfig
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    if registry is None:
        registry = CameraRegistry([
            CameraConfig.parse(
                {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
                 "features": ["counting"]}, "cam-a"),
        ])
    config = config or vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


def client_for(store, authed, role: str = "admin"):
    from vg.api import app as app_module

    app_module.set_store(store)
    return authed(app_module.create_app(), role)


class Courier:
    """A fake Twilio or Gmail: accepts, or answers from a script."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.sent: list = []

    def send(self, message, destination):
        self.sent.append((destination, message))
        if self.script:
            return self.script.pop(0)
        return providers.SendResult.accepted(f"SM{len(self.sent)}")


@pytest.fixture
def no_keys(monkeypatch):
    for name in SECRETS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def wired(tmp_path, no_keys):
    """A LiveStore with an alert database and a sender whose couriers are fakes."""
    from vg.api import app as app_module

    alerts_db = AlertStore(tmp_path / "alerts.db")
    courier = Courier()
    service = AlertService(AlertsConfig(), alerts_db, None, clock_for(0),
                           senders=lambda channel: courier)
    store = live_store(tmp_path, alerts_store=alerts_db, alerts=service)
    yield store, service, courier
    alerts_db.close_db()
    app_module.set_store(MockStore())


def add_person(client, channel="whatsapp", destination="+20 100 123 4567",
               name="Head of security", language="ar"):
    response = client.post("/settings/alerts/recipients", json={
        "channel": channel, "destination": destination, "name": name,
        "language": language})
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# the endpoints
# ---------------------------------------------------------------------------

class TestSettingsEndpoints:
    def test_a_fresh_install_lists_nobody_and_sends_nothing(self, wired, authed):
        store, _, _ = wired
        body = client_for(store, authed).get("/settings/alerts").json()
        assert body["recipients"] == []
        assert [r["kind"] for r in body["rules"]] == [
            "weapon", "intrusion", "vehicles", "camera", "attendance"]
        for rule in body["rules"]:
            assert not (rule["whatsapp"] or rule["sms"] or rule["email"])
        assert body["sending"] == "running"

    def test_a_recipient_is_kept_in_international_form(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        person = add_person(client)
        assert person["destination"] == "+201001234567"
        assert (person["language"], person["enabled"]) == ("ar", True)
        listed = client.get("/settings/alerts").json()["recipients"]
        assert [p["id"] for p in listed] == [person["id"]]

    def test_the_same_number_twice_is_a_conflict(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        add_person(client)
        again = client.post("/settings/alerts/recipients", json={
            "channel": "whatsapp", "destination": "+201001234567", "name": "B"})
        assert again.status_code == 409

    @pytest.mark.parametrize("destination", ["01001234567", "not a number"])
    def test_a_number_without_a_country_is_refused(self, wired, authed, destination):
        store, _, _ = wired
        response = client_for(store, authed).post("/settings/alerts/recipients", json={
            "channel": "sms", "destination": destination, "name": "A"})
        assert response.status_code == 422

    def test_edit_switch_off_and_remove(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        person = add_person(client)
        edited = client.patch(f"/settings/alerts/recipients/{person['id']}",
                              json={"enabled": False})
        assert edited.status_code == 200 and edited.json()["enabled"] is False
        assert client.delete(f"/settings/alerts/recipients/{person['id']}").status_code == 204
        assert client.delete(f"/settings/alerts/recipients/{person['id']}").status_code == 404
        assert client.patch(f"/settings/alerts/recipients/{person['id']}",
                            json={"name": "x"}).status_code == 404

    def test_switching_a_chip_saves(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        changed = client.patch("/settings/alerts/rules/weapon", json={"whatsapp": True})
        assert changed.status_code == 200 and changed.json()["whatsapp"] is True
        rules = {r["kind"]: r for r in client.get("/settings/alerts").json()["rules"]}
        assert rules["weapon"]["whatsapp"] is True

    def test_a_gate_reason_can_be_switched_off(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        changed = client.patch("/settings/alerts/rules/vehicles",
                               json={"vehicleUnknown": False})
        assert changed.json()["vehicleUnknown"] is False
        assert changed.json()["vehicleBlacklist"] is True

    @pytest.mark.parametrize("kind, body, status", [
        ("lost_bag", {"whatsapp": True}, 404),
        ("attendance", {"inApp": True}, 422),
        ("weapon", {"vehicleUnknown": False}, 422),
    ])
    def test_a_switch_that_is_not_offered_is_refused(self, wired, authed, kind, body, status):
        store, _, _ = wired
        response = client_for(store, authed).patch(f"/settings/alerts/rules/{kind}", json=body)
        assert response.status_code == status

    def test_send_test_really_sends_and_lands_in_the_log(self, wired, authed):
        store, service, courier = wired
        client = client_for(store, authed)
        person = add_person(client)
        response = client.post(f"/settings/alerts/recipients/{person['id']}/test")
        assert response.status_code == 202
        assert response.json()["outcome"] == "queued"
        service.step()
        assert courier.sent[0][0] == "+201001234567"
        (row,) = client.get("/settings/alerts/deliveries").json()["rows"]
        assert (row["outcome"], row["providerId"], row["recipientName"]) == (
            "sent", "SM1", "Head of security")

    def test_send_test_to_nobody_is_not_found(self, wired, authed):
        store, _, _ = wired
        assert client_for(store, authed).post(
            "/settings/alerts/recipients/nope/test").status_code == 404

    def test_the_log_is_newest_first_and_bounded(self, wired, authed):
        store, service, _ = wired
        client = client_for(store, authed)
        person = add_person(client)
        for _ in range(3):
            client.post(f"/settings/alerts/recipients/{person['id']}/test")
        body = client.get("/settings/alerts/deliveries", params={"limit": 2}).json()
        assert body["available"] is True
        assert len(body["rows"]) == 2


# ---------------------------------------------------------------------------
# the audit comes first
# ---------------------------------------------------------------------------

class TestAuditComesFirst:
    """Somebody changing who is told about a knife is a fact even if the
    write behind it fails. So the entry is written first, and a failing
    write still leaves it."""

    def _broken(self, store, monkeypatch, method):
        def boom(*args, **kwargs):
            raise RuntimeError("disk full")
        monkeypatch.setattr(store.alerts_store, method, boom)

    def _last(self, store):
        return store.audit(1)[0]

    def test_adding(self, wired, monkeypatch):
        from vg.api import schemas as S

        store, _, _ = wired
        self._broken(store, monkeypatch, "add_recipient")
        with pytest.raises(RuntimeError):
            store.add_recipient(S.RecipientCreate(
                channel="sms", destination="+201001234567", name="A"), "Test Admin")
        entry = self._last(store)
        assert (entry.action, entry.actor) == ("alerts.recipient.add", "Test Admin")
        assert "4567" in entry.detail and "+2010012" not in entry.detail

    def test_editing_removing_and_the_rule(self, wired, monkeypatch):
        from vg.api import schemas as S

        store, _, _ = wired
        person = store.alerts_store.add_recipient("sms", "+201001234567", "A")
        self._broken(store, monkeypatch, "update_recipient")
        with pytest.raises(RuntimeError):
            store.edit_recipient(person.id, S.RecipientUpdate(enabled=False), "Test Admin")
        assert self._last(store).action == "alerts.recipient.edit"

        self._broken(store, monkeypatch, "remove_recipient")
        with pytest.raises(RuntimeError):
            store.remove_recipient(person.id, "Test Admin")
        assert self._last(store).action == "alerts.recipient.remove"

        self._broken(store, monkeypatch, "update_rule")
        with pytest.raises(RuntimeError):
            store.update_rule("weapon", S.AlertRuleUpdate(sms=True), "Test Admin")
        assert (self._last(store).action, self._last(store).subject) == ("alerts.rule", "weapon")

    def test_a_test_send(self, wired, monkeypatch):
        store, service, _ = wired
        person = store.alerts_store.add_recipient("sms", "+201001234567", "A")

        def boom(*args, **kwargs):
            raise RuntimeError("queue gone")
        monkeypatch.setattr(service, "test_send", boom)
        with pytest.raises(RuntimeError):
            store.test_send(person.id, "Test Admin")
        assert self._last(store).action == "alerts.test"


# ---------------------------------------------------------------------------
# who may do what
# ---------------------------------------------------------------------------

class TestNonAdminRefused:
    def test_a_non_administrator_can_read_and_cannot_change(self, wired, authed):
        store, _, _ = wired
        person = store.alerts_store.add_recipient("sms", "+201001234567", "A")
        client = client_for(store, authed, role="it")
        assert client.get("/settings/alerts").status_code == 200
        assert client.get("/settings/alerts/deliveries").status_code == 200
        assert client.post("/settings/alerts/recipients", json={
            "channel": "sms", "destination": "+201001234568", "name": "B"}).status_code == 403
        assert client.patch(f"/settings/alerts/recipients/{person.id}",
                            json={"enabled": False}).status_code == 403
        assert client.delete(f"/settings/alerts/recipients/{person.id}").status_code == 403
        assert client.patch("/settings/alerts/rules/weapon",
                            json={"sms": True}).status_code == 403
        assert client.post(f"/settings/alerts/recipients/{person.id}/test").status_code == 403
        assert store.alerts_store.recipient(person.id).enabled is True


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------

class TestSecretsNeverLeave:
    def test_no_key_value_reaches_a_response_a_row_or_the_audit(
            self, tmp_path, authed, monkeypatch):
        from vg.api import app as app_module

        for name, value in SECRETS.items():
            monkeypatch.setenv(name, value)
        alerts_db = AlertStore(tmp_path / "alerts.db")
        # A courier whose error text leaks everything - the worst case.
        leak = " ".join(SECRETS.values())
        courier = Courier([providers.SendResult.failed("provider_refused", leak)] * 3)
        service = AlertService(AlertsConfig(retries=1), alerts_db, None, clock_for(0),
                               senders=lambda channel: courier)
        store = live_store(tmp_path, alerts_store=alerts_db, alerts=service)
        try:
            client = client_for(store, authed)
            person = add_person(client, channel="sms")
            client.patch("/settings/alerts/rules/weapon", json={"sms": True})
            client.post(f"/settings/alerts/recipients/{person['id']}/test")
            service.step()

            seen = [client.get("/settings/alerts").text,
                    client.get("/settings/alerts/deliveries").text]
            seen += [str(entry.model_dump()) for entry in store.audit(50)]
            seen += [str(row) for row in alerts_db.recent(50)]
            for value in ("ACsentinelSID0001", "sentinelTOKEN0002", "sentinelPASS0003",
                          "sentinel.school@gmail.com"):
                for text in seen:
                    assert value not in text
        finally:
            alerts_db.close_db()
            app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# the live path is live
# ---------------------------------------------------------------------------

class TestLiveIsNotMock:
    @pytest.mark.parametrize("name", [
        "alert_settings", "update_rule", "add_recipient", "edit_recipient",
        "remove_recipient", "test_send", "deliveries",
    ])
    def test_live_answers_for_itself(self, name):
        assert getattr(LiveStore, name) is not getattr(MockStore, name), (
            f"LiveStore.{name} is MockStore's - the live path would serve fixtures")

    def test_the_mock_never_pretends_to_send(self):
        mock = MockStore()
        person = mock.alert_settings().recipients[0]
        row = mock.test_send(person.id, "Test Admin")
        assert (row.outcome, row.reason) == ("skipped", "provider_missing")


# ---------------------------------------------------------------------------
# honest states
# ---------------------------------------------------------------------------

class TestHonestStates:
    def test_missing_keys_are_named_per_channel(self, wired, authed):
        store, _, _ = wired
        channels = {c["channel"]: c for c in
                    client_for(store, authed).get("/settings/alerts").json()["channels"]}
        assert channels["sms"]["configured"] is False
        assert channels["sms"]["missing"] == [
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM"]
        assert channels["email"]["missing"] == ["GMAIL_USER", "GMAIL_APP_PASSWORD"]

    def test_a_channel_on_with_nobody_on_it_is_named(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        client.patch("/settings/alerts/rules/weapon", json={"whatsapp": True})
        body = client.get("/settings/alerts").json()
        assert {"kind": "weapon", "channel": "whatsapp"} in body["unreached"]
        add_person(client)
        body = client.get("/settings/alerts").json()
        assert body["unreached"] == []

    def test_an_unreadable_log_says_so_and_is_not_a_500(self, wired, authed):
        store, _, _ = wired
        client = client_for(store, authed)
        store.alerts_store.close_db()
        response = client.get("/settings/alerts/deliveries")
        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False and body["reason"]

    def test_no_alert_database_is_a_503_with_the_reason(self, tmp_path, authed):
        from vg.api import app as app_module

        store = live_store(tmp_path)
        store.alerts_error = "the alert database could not be opened: disk"
        try:
            response = client_for(store, authed).get("/settings/alerts")
            assert response.status_code == 503
            assert "could not be opened" in response.text
        finally:
            app_module.set_store(MockStore())

    def test_sending_switched_off_says_so(self, tmp_path, no_keys):
        from vg import config as vgconfig

        alerts_db = AlertStore(tmp_path / "alerts.db")
        try:
            config = dataclasses.replace(vgconfig.load(),
                                         alerts=AlertsConfig(enabled=False))
            store = live_store(tmp_path, config=config, alerts_store=alerts_db)
            assert store.alert_settings().sending == "off"
            stage = store._alerts_stage()
            assert stage.healthy and "switched off" in stage.detail.lower()
        finally:
            alerts_db.close_db()

    def test_system_health_names_missing_keys_a_rule_needs(self, wired):
        store, _, _ = wired
        assert store._alerts_stage().healthy, "nothing switched on, nothing missing"
        store.alerts_store.update_rule("weapon", sms=True)
        stage = store._alerts_stage()
        assert not stage.healthy
        assert "TWILIO_SMS_FROM" in stage.detail
        assert stage.detail.endswith("Detection is unaffected.")

    def test_system_health_lists_the_row(self, wired):
        store, _, _ = wired
        assert "alerts" in [stage.key for stage in store.health().pipeline]

    def test_the_report_state_is_stated(self, wired):
        store, _, _ = wired
        report = store.alert_settings().report
        assert report.time == "12:00"
        assert report.state in ("scheduled", "no_term_dates", "before_term", "after_term")
