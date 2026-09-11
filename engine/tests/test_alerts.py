"""Alert delivery (P9): the engine half, without a single existing feature.

Five pieces, tested in the order they depend on each other:

- `events`     what happened, as a message may say it - and nothing else
- `catalogue`  the wording, English and Arabic
- `providers`  Twilio and Gmail, behind fake transports - no test touches the
               network
- `store`      recipients, rules, the delivery log, acknowledgements
- `service`    the queue and the one sender thread, driven a pass at a time

The rules they hold are the spec's hard ones: nothing about a minor can enter
a message; "sent" means the courier accepted it; every attempt is a row; a
restart re-sends nothing. See specs/013-alert-delivery.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from vg.alerts import events

NOW = datetime(2026, 10, 6, 9, 30, tzinfo=timezone.utc)   # a Tuesday


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

class _Health:
    def __init__(self, last_frame_at):
        self.last_frame_at = last_frame_at


class _Source:
    def __init__(self, last_frame_at):
        self.health = _Health(last_frame_at)


class FakeWorker:
    """A camera as `offline_cameras` sees it: a status and a last frame."""

    def __init__(self, status: str = "ok", last_frame_at: datetime | None = None):
        self.status = status
        self.source = _Source(last_frame_at)


class TestEvents:
    @pytest.mark.parametrize("key", ["name", "person", "student", "snapshot", "clip"])
    def test_a_fact_that_could_carry_a_child_is_refused(self, key):
        """The structural half of SC-007: there is no field a name can use."""
        with pytest.raises(ValueError, match="not allowed"):
            events.AlertEvent(kind="intrusion", template="intrusion.opened",
                              event_key="k", at=NOW, facts={key: "Layla"})

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="kind"):
            events.AlertEvent(kind="lost_bag", template="x", event_key="k", at=NOW)

    def test_facts_cannot_be_changed_after_the_check(self):
        event = events.intrusion_opened("s1", "cam-a", NOW)
        with pytest.raises(TypeError):
            event.facts["name"] = "Layla"          # type: ignore[index]

    def test_each_event_carries_the_key_the_ledger_uses(self):
        since = datetime(2026, 10, 6, 7, 5, 9, tzinfo=timezone.utc)
        assert events.weapon_opened("s1", "cam-a", NOW, 0.76).event_key == "weapon:s1:opened"
        assert events.weapon_verdict("s1", "cam-a", NOW, "dismissed", "Guard A").event_key \
            == "weapon:s1:verdict"
        assert events.intrusion_opened("z1", "cam-a", NOW).event_key == "intrusion:z1"
        assert events.gate_alert("p1", "cam-g", NOW, "ABC 123", 1, "blacklist",
                                 0.9, False).event_key == "vehicles:p1"
        assert events.camera_down("cam-a", since).event_key \
            == "camera:cam-a:down:20261006T070509Z"
        assert events.camera_up("cam-a", since).event_key \
            == "camera:cam-a:up:20261006T070509Z"
        assert events.attendance_report("2026-10-06", NOW, ()).event_key \
            == "attendance:2026-10-06"

    def test_every_test_send_is_its_own_event(self):
        a = events.test_message("r1", NOW)
        b = events.test_message("r1", NOW)
        assert a.event_key != b.event_key
        assert a.event_key.startswith("test:r1:")

    def test_the_verdict_knows_its_opening(self):
        verdict = events.weapon_verdict("s1", "cam-a", NOW, "confirmed", "Guard A")
        assert events.opening_key(verdict) == "weapon:s1:opened"
        assert verdict.template == "weapon.confirmed"

    def test_a_verdict_is_confirmed_or_dismissed(self):
        with pytest.raises(ValueError):
            events.weapon_verdict("s1", "cam-a", NOW, "pending", "Guard A")

    def test_a_gate_reason_is_one_of_three(self):
        with pytest.raises(ValueError):
            events.gate_alert("p1", "cam-g", NOW, "ABC", 1, "known", 0.9, False)


class TestOfflineCameras:
    """One rule for Home and for the sender: dark for N minutes, since when."""

    def test_a_camera_dark_four_minutes_is_not_yet_offline(self):
        workers = {"cam-a": FakeWorker("down", NOW - timedelta(minutes=4))}
        assert events.offline_cameras(workers, NOW, 5, NOW - timedelta(hours=1)) == {}

    def test_a_camera_dark_five_minutes_is_offline_since_its_last_frame(self):
        last = NOW - timedelta(minutes=5)
        workers = {"cam-a": FakeWorker("down", last)}
        assert events.offline_cameras(workers, NOW, 5, NOW - timedelta(hours=1)) \
            == {"cam-a": last}

    def test_no_frame_since_start_counts_from_the_start(self):
        started = NOW - timedelta(minutes=6)
        workers = {"cam-a": FakeWorker("auth", None)}
        assert events.offline_cameras(workers, NOW, 5, started) == {"cam-a": started}

    def test_a_working_camera_is_never_listed(self):
        """Even one whose last frame is old: status is the camera's own word."""
        workers = {"cam-a": FakeWorker("ok", NOW - timedelta(hours=2))}
        assert events.offline_cameras(workers, NOW, 5, NOW - timedelta(hours=3)) == {}

    def test_the_since_does_not_move_while_it_stays_dark(self):
        """A moving `since` would be a new outage - and a new message - every tick."""
        last = NOW - timedelta(minutes=7)
        workers = {"cam-a": FakeWorker("down", last)}
        first = events.offline_cameras(workers, NOW, 5, NOW - timedelta(hours=1))
        later = events.offline_cameras(workers, NOW + timedelta(minutes=30), 5,
                                       NOW - timedelta(hours=1))
        assert first == later


class TestSchoolDays:
    TERM = ("2026-09-20", "2027-06-15")

    def test_a_tuesday_in_term_is_a_school_day(self):
        assert events.is_school_day(date(2026, 10, 6), *self.TERM)

    @pytest.mark.parametrize("day", [date(2026, 10, 9), date(2026, 10, 10)])
    def test_friday_and_saturday_are_not(self, day):
        assert not events.is_school_day(day, *self.TERM)

    def test_sunday_is(self):
        assert events.is_school_day(date(2026, 10, 4), *self.TERM)

    def test_outside_the_term_is_not(self):
        assert not events.is_school_day(date(2026, 9, 15), *self.TERM)

    def test_no_term_dates_means_no_school_day(self):
        assert not events.is_school_day(date(2026, 10, 6), "", "")

    def test_the_states_settings_says(self):
        assert events.report_state(date(2026, 10, 6), *self.TERM) == "scheduled"
        assert events.report_state(date(2026, 9, 1), *self.TERM) == "before_term"
        assert events.report_state(date(2027, 7, 1), *self.TERM) == "after_term"
        assert events.report_state(date(2026, 10, 6), "", "") == "no_term_dates"

    def test_the_shipped_term_has_ended(self):
        """Today, on this machine: 11 Sep 2026 against a term ending 20 Jun 2026.
        Settings must say so rather than the report going quietly silent."""
        assert events.report_state(date(2026, 9, 11), "2025-09-01", "2026-06-20") \
            == "after_term"


# ---------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------

from vg.alerts import catalogue  # noqa: E402
from vg.clock import FixedClock  # noqa: E402

CAIRO_SUMMER = FixedClock(offset_minutes=180)
LONG_NAME = "Building C - second floor corridor by the chemistry lab"   # 55 chars
LONG_URL = "https://" + "v" * 84 + ".school"                              # 100 chars


def every_event():
    """One of each template, with every fact filled."""
    since = NOW - timedelta(minutes=12)
    groups = (events.GroupCount("Everyone", 300, 12, 20),
              events.GroupCount("Grade 8", 28, 2, 1))
    return [
        events.weapon_opened("s1", "cam-a", NOW, 0.764),
        events.weapon_verdict("s1", "cam-a", NOW, "confirmed", "Guard A", since),
        events.weapon_verdict("s1", "cam-a", NOW, "dismissed", "Guard A", since),
        events.intrusion_opened("z1", "cam-a", NOW),
        events.gate_alert("p1", "cam-g", NOW, "ABC 123", 1, "blacklist", 0.91, False),
        events.gate_alert("p2", "cam-g", NOW, "ABC 124", 1, "unknown", 0.88, True),
        events.gate_alert("p3", "cam-g", NOW, "ABC 125", 2, "expired", 0.95, False),
        events.camera_down("cam-a", since),
        events.camera_up("cam-a", NOW),
        events.attendance_report("2026-10-06", NOW, groups),
        events.test_message("r1", NOW),
    ]


class TestCatalogue:
    def test_every_template_builds_in_both_languages(self):
        for event in every_event():
            for language in ("en", "ar"):
                message = catalogue.build(event, language, clock=CAIRO_SUMMER,
                                          send_draft_arabic=True)
                assert message.body.strip(), event.template
                assert message.language == language
                assert "{" not in message.body, f"unfilled field in {event.template}"

    def test_arabic_waits_for_a_native_speaker(self):
        """ARABIC_REVIEWED is False until Mohamed has read the Arabic column."""
        assert catalogue.ARABIC_REVIEWED is False
        message = catalogue.build(events.intrusion_opened("z1", "cam-a", NOW), "ar",
                                  clock=CAIRO_SUMMER)
        assert message.language == "en"
        assert "restricted" in message.body

    def test_the_draft_can_be_read_on_a_phone_when_asked_for(self):
        message = catalogue.build(events.intrusion_opened("z1", "cam-a", NOW), "ar",
                                  clock=CAIRO_SUMMER, send_draft_arabic=True)
        assert message.language == "ar"
        assert "المحظورة" in message.body

    def test_the_knife_opening_says_nobody_has_confirmed_it(self):
        """The owner's condition for sending on detection (PLAN §6, amended)."""
        message = catalogue.build(events.weapon_opened("s1", "cam-a", NOW, 0.764),
                                  "en", clock=CAIRO_SUMMER)
        assert "awaiting review — not yet confirmed by a person" in message.body.lower()
        assert "76%" in message.body

    def test_the_time_is_the_sites(self):
        message = catalogue.build(events.intrusion_opened("z1", "cam-a", NOW), "en",
                                  clock=CAIRO_SUMMER)
        assert "12:30" in message.body          # 09:30 UTC in Cairo summer time

    def test_the_verdict_names_who_decided(self):
        verdict = events.weapon_verdict("s1", "cam-a", NOW, "dismissed", "Guard A",
                                        NOW - timedelta(minutes=12))
        body = catalogue.build(verdict, "en", clock=CAIRO_SUMMER).body
        assert "false alarm" in body.lower()
        assert "Guard A" in body
        assert "12:18" in body and "12:30" in body

    def test_a_link_only_when_the_console_address_is_known(self):
        event = events.weapon_opened("s1", "cam-a", NOW, 0.8)
        assert "http" not in catalogue.build(event, "en", clock=CAIRO_SUMMER).body
        body = catalogue.build(event, "en", clock=CAIRO_SUMMER,
                               console_url="http://10.0.0.5:5173").body
        assert body.rstrip().endswith("http://10.0.0.5:5173/weapons")

    @pytest.mark.parametrize("event, page", [
        (events.intrusion_opened("z1", "cam-a", NOW), "/intrusion"),
        (events.gate_alert("p1", "cam-g", NOW, "ABC", 1, "blacklist", 0.9, False), "/vehicles"),
        (events.camera_up("cam-a", NOW), "/system"),
        (events.attendance_report("2026-10-06", NOW, ()), "/attendance"),
    ])
    def test_each_link_opens_its_page(self, event, page):
        body = catalogue.build(event, "en", clock=CAIRO_SUMMER, console_url="http://c").body
        assert body.rstrip().endswith("http://c" + page)

    def test_an_event_message_fits_the_limit_with_long_names(self):
        for event in every_event():
            if event.kind == "attendance":
                continue
            event = type(event)(**{**event.__dict__, "camera_name": LONG_NAME})
            for language in ("en", "ar"):
                body = catalogue.build(event, language, clock=CAIRO_SUMMER,
                                       console_url=LONG_URL, send_draft_arabic=True).body
                assert len(body) <= catalogue.EVENT_LIMIT, (event.template, len(body))

    def test_a_long_report_is_cut_and_says_how_much(self):
        groups = tuple(events.GroupCount(f"Grade {n} - section {n}", 30, 2, 1)
                       for n in range(60))
        body = catalogue.build(events.attendance_report("2026-10-06", NOW, groups), "en",
                               clock=CAIRO_SUMMER, console_url="http://c").body
        assert len(body) <= catalogue.REPORT_LIMIT
        assert "more groups" in body
        assert body.rstrip().endswith("http://c/attendance")

    def test_the_report_is_counts_per_group(self):
        groups = (events.GroupCount("Grade 8", 28, 2, 1),)
        body = catalogue.build(events.attendance_report("2026-10-06", NOW, groups), "en",
                               clock=CAIRO_SUMMER).body
        assert "Grade 8: 28 present, 2 late, 1 absent" in body

    def test_an_uncertain_plate_says_so(self):
        body = catalogue.build(
            events.gate_alert("p2", "cam-g", NOW, "ABC 124", 1, "unknown", 0.6, True),
            "en", clock=CAIRO_SUMMER).body
        assert "uncertain" in body.lower()
        assert "ABC 124" in body and "gate 1" in body

    def test_no_message_claims_more_than_the_courier_said(self):
        """"Sent" means accepted. Nothing here may say delivered or read."""
        for event in every_event():
            for language in ("en", "ar"):
                body = catalogue.build(event, language, clock=CAIRO_SUMMER,
                                       send_draft_arabic=True).body.lower()
                assert "delivered" not in body
                assert "read by" not in body

    def test_a_camera_with_no_name_shows_its_id(self):
        body = catalogue.build(events.intrusion_opened("z1", "cam-a", NOW), "en",
                               clock=CAIRO_SUMMER).body
        assert "cam-a" in body

    def test_the_email_subject_names_the_kind(self):
        message = catalogue.build(events.weapon_opened("s1", "cam-a", NOW, 0.8), "en",
                                  clock=CAIRO_SUMMER)
        assert message.subject == "VisionGuard · Knife alert"


# ---------------------------------------------------------------------------
# providers - fake transports only; nothing here touches the network
# ---------------------------------------------------------------------------

import smtplib  # noqa: E402
import urllib.error  # noqa: E402
from urllib.parse import parse_qs  # noqa: E402

from vg.alerts import providers  # noqa: E402
from vg.alerts.catalogue import Message  # noqa: E402

MSG = Message(subject="VisionGuard · Test message", body="hello", language="en")
PHONE = "+201001234567"

#: Values that appear nowhere else, so one search of a result proves redaction.
SECRETS = {
    "TWILIO_ACCOUNT_SID": "ACsentinelSID0001",
    "TWILIO_AUTH_TOKEN": "sentinelTOKEN0002",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+14155238886",
    "TWILIO_SMS_FROM": "+15005550006",
    "GMAIL_USER": "sentinel.school@gmail.com",
    "GMAIL_APP_PASSWORD": "sentinelPASS0003",
}


@pytest.fixture
def keys(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def no_keys(monkeypatch):
    for name in SECRETS:
        monkeypatch.delenv(name, raising=False)


class FakeTwilio:
    """Stands where urllib would. Records what it was asked, answers as told."""

    def __init__(self, status=201, body=b'{"sid": "SM0123"}', raises=None):
        self.status, self.body, self.raises = status, body, raises
        self.calls: list[tuple] = []

    def __call__(self, url, data, headers, timeout):
        self.calls.append((url, parse_qs(data.decode()), headers, timeout))
        if self.raises is not None:
            raise self.raises
        return self.status, self.body


class FakeSMTP:
    """Stands where smtplib.SMTP_SSL would."""

    def __init__(self, login_error=None, send_error=None):
        self.login_error, self.send_error = login_error, send_error
        self.sent: list = []
        self.logged_in: tuple | None = None

    def __call__(self, host, port, timeout):
        self.opened = (host, port, timeout)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if self.login_error:
            raise self.login_error
        self.logged_in = (user, password)

    def send_message(self, mail):
        if self.send_error:
            raise self.send_error
        self.sent.append(mail)


class TestProviders:
    def test_twilio_accepts_and_the_log_gets_its_id(self, keys):
        fake = FakeTwilio()
        result = providers.TwilioSender("sms", 10, transport=fake).send(MSG, PHONE)
        assert result.ok and result.provider_id == "SM0123"
        url, form, headers, timeout = fake.calls[0]
        assert url.endswith("/Accounts/ACsentinelSID0001/Messages.json")
        assert form == {"From": ["+15005550006"], "To": [PHONE], "Body": ["hello"]}
        assert headers["Authorization"].startswith("Basic ")
        assert timeout == 10

    def test_whatsapp_prefixes_both_numbers_once(self, keys):
        fake = FakeTwilio()
        providers.TwilioSender("whatsapp", 10, transport=fake).send(MSG, PHONE)
        form = fake.calls[0][1]
        assert form["From"] == ["whatsapp:+14155238886"]
        assert form["To"] == [f"whatsapp:{PHONE}"]

    def test_a_bare_whatsapp_sender_number_gets_its_prefix(self, keys, monkeypatch):
        monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "+14155238886")
        fake = FakeTwilio()
        providers.TwilioSender("whatsapp", 10, transport=fake).send(MSG, PHONE)
        assert fake.calls[0][1]["From"] == ["whatsapp:+14155238886"]

    def test_a_refusal_carries_twilios_own_words(self, keys):
        fake = FakeTwilio(401, b'{"code": 20003, "message": "Authenticate", "status": 401}')
        result = providers.TwilioSender("sms", 10, transport=fake).send(MSG, PHONE)
        assert not result.ok
        assert result.reason == "provider_refused"
        assert result.provider_reason == "Authenticate (Twilio 20003)"

    def test_an_error_page_that_is_not_json_says_its_status(self, keys):
        fake = FakeTwilio(503, b"<html>busy</html>")
        result = providers.TwilioSender("sms", 10, transport=fake).send(MSG, PHONE)
        assert result.reason == "provider_refused"
        assert result.provider_reason == "HTTP 503"

    def test_a_network_error_never_carries_the_account_sid(self, keys):
        """urllib's words can include the URL, and the URL holds the SID."""
        leak = urllib.error.URLError(
            "no route to https://api.twilio.com/2010-04-01/Accounts/ACsentinelSID0001/")
        result = providers.TwilioSender("sms", 10, transport=FakeTwilio(raises=leak)).send(
            MSG, PHONE)
        assert result.reason == "unreachable"
        assert "ACsentinelSID0001" not in (result.provider_reason or "")

    @pytest.mark.parametrize("error", [
        TimeoutError("timed out"),
        urllib.error.URLError(TimeoutError("timed out")),
    ])
    def test_a_courier_that_does_not_answer_is_a_timeout(self, keys, error):
        result = providers.TwilioSender("sms", 10, transport=FakeTwilio(raises=error)).send(
            MSG, PHONE)
        assert result.reason == "timeout"

    def test_gmail_sends_plain_text_and_the_log_gets_the_message_id(self, keys):
        smtp = FakeSMTP()
        result = providers.GmailSender(10, smtp_factory=smtp).send(MSG, "head@school.example")
        assert result.ok
        mail = smtp.sent[0]
        assert result.provider_id == mail["Message-ID"]
        assert mail["To"] == "head@school.example"
        assert mail["From"] == "sentinel.school@gmail.com"
        assert mail["Subject"] == "VisionGuard · Test message"
        assert mail.get_content_type() == "text/plain"
        assert not mail.is_multipart(), "no attachment, ever"
        assert smtp.opened == ("smtp.gmail.com", 465, 10)
        assert smtp.logged_in == ("sentinel.school@gmail.com", "sentinelPASS0003")

    def test_a_wrong_app_password_carries_googles_words(self, keys):
        smtp = FakeSMTP(login_error=smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted."))
        result = providers.GmailSender(10, smtp_factory=smtp).send(MSG, "a@school.example")
        assert result.reason == "provider_refused"
        assert "Username and Password not accepted" in result.provider_reason
        assert "(SMTP 535)" in result.provider_reason

    def test_gmail_out_of_reach_is_unreachable(self, keys):
        def refuse(host, port, timeout):
            raise ConnectionRefusedError(10061, "No connection could be made")
        result = providers.GmailSender(10, smtp_factory=refuse).send(MSG, "a@school.example")
        assert result.reason == "unreachable"
        assert "ConnectionRefusedError" in result.provider_reason

    def test_missing_keys_are_named_not_guessed(self, no_keys):
        assert providers.missing_env("sms") == [
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM"]
        assert providers.missing_env("email") == ["GMAIL_USER", "GMAIL_APP_PASSWORD"]
        assert providers.for_channel("whatsapp") is None
        assert providers.for_channel("email") is None

    def test_one_missing_key_is_enough_to_say_so(self, keys, monkeypatch):
        monkeypatch.delenv("TWILIO_SMS_FROM")
        assert providers.missing_env("sms") == ["TWILIO_SMS_FROM"]
        assert providers.missing_env("whatsapp") == []
        assert providers.for_channel("sms") is None

    def test_configured_channels_get_their_sender(self, keys):
        assert isinstance(providers.for_channel("sms"), providers.TwilioSender)
        assert isinstance(providers.for_channel("whatsapp"), providers.TwilioSender)
        assert isinstance(providers.for_channel("email"), providers.GmailSender)

    def test_redact_removes_every_secret_value(self, keys):
        text = "token sentinelTOKEN0002, sid ACsentinelSID0001, pw sentinelPASS0003"
        cleaned = providers.redact(text)
        for value in ("sentinelTOKEN0002", "ACsentinelSID0001", "sentinelPASS0003"):
            assert value not in cleaned
        assert providers.redact(None) is None


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

from vg.alerts.store import AlertStore, DuplicateRecipient, normalise_destination  # noqa: E402


@pytest.fixture
def alert_db(tmp_path):
    store = AlertStore(tmp_path / "alerts.db")
    yield store
    store.close_db()


class TestAlertStore:
    def test_a_fresh_install_sends_nothing(self, alert_db):
        """P9-FR-015: every external channel off, nobody listed, In-app on."""
        rules = alert_db.rules()
        assert sorted(rules) == sorted(events.KINDS)
        for kind, rule in rules.items():
            assert not (rule.whatsapp or rule.sms or rule.email), kind
        assert rules["weapon"].in_app is True
        assert alert_db.recipients() == []

    def test_the_report_offers_no_in_app_switch(self, alert_db):
        assert alert_db.rules()["attendance"].in_app is None
        with pytest.raises(ValueError, match="in_app"):
            alert_db.update_rule("attendance", in_app=True)

    def test_the_gate_switches_live_only_on_the_gate_rule(self, alert_db):
        rules = alert_db.rules()
        assert (rules["vehicles"].vehicle_blacklist, rules["vehicles"].vehicle_unknown,
                rules["vehicles"].vehicle_expired) == (True, True, True)
        assert rules["weapon"].vehicle_unknown is None
        with pytest.raises(ValueError, match="vehicle"):
            alert_db.update_rule("weapon", vehicle_unknown=False)

    def test_an_unknown_kind_is_not_found(self, alert_db):
        with pytest.raises(KeyError):
            alert_db.update_rule("lost_bag", whatsapp=True)

    def test_edits_survive_a_restart(self, tmp_path):
        """SC-006. Seeding on open must never undo what an administrator set."""
        first = AlertStore(tmp_path / "a.db")
        first.update_rule("weapon", whatsapp=True)
        first.add_recipient("whatsapp", "+201001234567", "Head of security", "ar")
        first.close_db()
        again = AlertStore(tmp_path / "a.db")
        try:
            assert again.rules()["weapon"].whatsapp is True
            (person,) = again.recipients()
            assert (person.name, person.language, person.enabled) == (
                "Head of security", "ar", True)
        finally:
            again.close_db()

    def test_the_same_number_twice_on_one_channel_is_one_recipient(self, alert_db):
        alert_db.add_recipient("sms", "+201001234567", "A")
        with pytest.raises(DuplicateRecipient):
            alert_db.add_recipient("sms", " +20 100-123 4567 ", "B")
        # the same number on another channel is a different recipient
        alert_db.add_recipient("whatsapp", "+201001234567", "A")

    @pytest.mark.parametrize("raw, clean", [
        (" +20 100-123 4567 ", "+201001234567"),
        ("+20 (100) 123.4567", "+201001234567"),
    ])
    def test_phone_numbers_are_kept_in_international_form(self, raw, clean):
        assert normalise_destination("sms", raw) == clean

    @pytest.mark.parametrize("channel, raw", [
        ("sms", "01001234567"),            # no country code: which country?
        ("whatsapp", "+0100"),
        ("email", "a@b"),
        ("email", "not an address"),
        ("pager", "123"),
    ])
    def test_a_destination_that_cannot_be_reached_is_refused(self, channel, raw):
        with pytest.raises(ValueError):
            normalise_destination(channel, raw)

    def test_an_address_is_lower_cased(self):
        assert normalise_destination("email", " Head@School.Example ") == "head@school.example"

    def test_edit_and_remove(self, alert_db):
        person = alert_db.add_recipient("email", "a@school.example", "A")
        edited = alert_db.update_recipient(person.id, enabled=False, language="ar")
        assert (edited.enabled, edited.language) == (False, "ar")
        assert alert_db.remove_recipient(person.id) is True
        assert alert_db.remove_recipient(person.id) is False
        with pytest.raises(KeyError):
            alert_db.update_recipient(person.id, name="gone")

    def test_a_removed_recipient_keeps_its_name_in_the_log(self, alert_db):
        person = alert_db.add_recipient("email", "a@school.example", "Deputy head")
        alert_db.add_row("test:x:1", "test", "queued", at=NOW, channel="email",
                         recipient=person, language="en")
        alert_db.remove_recipient(person.id)
        (row,) = alert_db.recent(10)
        assert row.recipient_name == "Deputy head"

    def test_leftovers_from_a_stopped_engine_are_failed_not_forgotten(self, alert_db):
        waiting = alert_db.add_row("k1", "weapon", "queued", at=NOW, channel="sms")
        done = alert_db.add_row("k2", "weapon", "queued", at=NOW, channel="sms")
        alert_db.mark_sent(done, "SM1", 1, NOW)
        assert alert_db.fail_unfinished("engine_stopped", NOW) == 1
        assert alert_db.row(waiting).outcome == "failed"
        assert alert_db.row(waiting).reason == "engine_stopped"
        assert alert_db.row(done).outcome == "sent"

    def test_the_log_is_newest_first(self, alert_db):
        alert_db.add_row("k1", "weapon", "skipped", at=NOW, reason="no_recipients")
        alert_db.add_row("k2", "weapon", "skipped", at=NOW + timedelta(seconds=1),
                         reason="no_recipients")
        assert [r.event_key for r in alert_db.recent(10)] == ["k2", "k1"]

    def test_the_ledger_knows_what_it_has_seen(self, alert_db):
        assert not alert_db.has_rows("weapon:s1:opened")
        alert_db.add_row("weapon:s1:opened", "weapon", "skipped", at=NOW,
                         channel="sms", reason="provider_missing")
        assert alert_db.has_rows("weapon:s1:opened")

    def test_the_verdict_finds_who_got_the_opening(self, alert_db):
        a = alert_db.add_recipient("sms", "+201001234567", "A")
        b = alert_db.add_recipient("sms", "+201001234568", "B")
        alert_db.add_row("weapon:s1:opened", "weapon", "queued", at=NOW,
                         channel="sms", recipient=a)
        alert_db.add_row("weapon:s1:opened", "weapon", "skipped", at=NOW,
                         channel="sms", recipient=b, reason="recipient_off")
        assert alert_db.recipients_of("weapon:s1:opened") == {("sms", a.id)}

    def test_the_last_word_on_each_camera(self, alert_db):
        since = NOW - timedelta(minutes=6)
        alert_db.add_row(events.camera_down("cam-a", since).event_key, "camera",
                         "skipped", at=since, channel="sms", reason="no_recipients")
        alert_db.add_row(events.camera_up("cam-a", NOW).event_key, "camera",
                         "skipped", at=NOW, channel="sms", reason="no_recipients")
        alert_db.add_row(events.camera_down("cam:b", since).event_key, "camera",
                         "skipped", at=since, channel="sms", reason="no_recipients")
        assert alert_db.last_camera_events() == {"cam-a": "up", "cam:b": "down"}

    def test_retention_removes_only_old_rows(self, alert_db):
        alert_db.add_row("old", "weapon", "skipped", at=NOW - timedelta(days=91),
                         reason="no_recipients")
        alert_db.add_row("new", "weapon", "skipped", at=NOW, reason="no_recipients")
        assert alert_db.delete_older_than(NOW - timedelta(days=90)) == 1
        assert [r.event_key for r in alert_db.recent(10)] == ["new"]

    def test_counts_for_system_health(self, alert_db):
        one = alert_db.add_row("k1", "weapon", "queued", at=NOW, channel="sms")
        alert_db.mark_sent(one, "SM1", 1, NOW)
        two = alert_db.add_row("k2", "weapon", "queued", at=NOW, channel="sms")
        alert_db.mark_failed(two, "timeout", "TimeoutError", 3, NOW)
        assert alert_db.counts_since(NOW - timedelta(hours=24)) == {"sent": 1, "failed": 1}

    def test_an_acknowledgement_is_once(self, alert_db):
        assert alert_db.ack("weapon:s1", "Guard A", NOW) is True
        assert alert_db.ack("weapon:s1", "Guard B", NOW) is False
        assert alert_db.acked() == {"weapon:s1"}


# ---------------------------------------------------------------------------
# service - the sender, driven one pass at a time
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402
import threading  # noqa: E402

from vg.alerts.service import AlertService  # noqa: E402
from vg.config import AlertsConfig  # noqa: E402


class Clockwork:
    """An injectable `now` that a test moves by hand."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


class FakeSender:
    """Answers from a script; accepts once the script runs out."""

    def __init__(self, script=None, before=None):
        self.script = list(script or [])
        self.before = before
        self.sent: list[tuple[str, Message]] = []

    def send(self, message, destination):
        if self.before:
            self.before()
        self.sent.append((destination, message))
        if self.script:
            outcome = self.script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return providers.SendResult.accepted(f"SM{len(self.sent)}")


def couriers(**by_channel):
    """A sender factory: the channels given are configured, the rest are not."""
    return lambda channel: by_channel.get(channel)


def make_service(store, senders, *, now=None, config=None, registry=None, hours=None):
    return AlertService(config or AlertsConfig(), store, registry, CAIRO_SUMMER,
                        hours=hours, senders=senders, now=now or Clockwork(NOW))


def knife(scene="s1", camera="cam-a"):
    return events.weapon_opened(scene, camera, NOW, 0.8)


class TestSenderCore:
    def test_the_row_exists_before_the_courier_is_called(self, alert_db):
        """Rows before couriers: a hard kill mid-call must not leave no trace."""
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")

        def row_is_already_queued():
            (row,) = alert_db.recent(5)
            assert row.outcome == "queued"

        sender = FakeSender(before=row_is_already_queued)
        service = make_service(alert_db, couriers(sms=sender))
        service.enqueue(knife())
        service.step()
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.provider_id, row.attempts) == ("sent", "SM1", 1)
        assert sender.sent[0][0] == "+201001234567"

    def test_three_refusals_are_one_failed_row_with_the_couriers_words(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        no = providers.SendResult.failed("provider_refused", "Authenticate (Twilio 20003)")
        sender = FakeSender([no, no, no])
        clock = Clockwork(NOW)
        service = make_service(alert_db, couriers(sms=sender), now=clock)

        service.enqueue(knife())
        service.step()                         # attempt 1
        clock.advance(seconds=4)
        service.step()                         # not due yet
        assert len(sender.sent) == 1
        clock.advance(seconds=1)
        service.step()                         # attempt 2
        clock.advance(seconds=5)
        service.step()                         # attempt 3
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.reason, row.attempts) == ("failed", "provider_refused", 3)
        assert row.provider_reason == "Authenticate (Twilio 20003)"
        assert len(sender.sent) == 3

    def test_a_retry_that_succeeds_is_sent(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        sender = FakeSender([providers.SendResult.failed("timeout", "TimeoutError")])
        clock = Clockwork(NOW)
        service = make_service(alert_db, couriers(sms=sender), now=clock)
        service.enqueue(knife())
        service.step()
        clock.advance(seconds=5)
        service.step()
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.attempts) == ("sent", 2)

    def test_no_keys_is_one_skip_for_the_channel(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers())
        service.enqueue(knife())
        service.step()
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.reason, row.channel) == ("skipped", "provider_missing", "sms")

    def test_a_channel_on_with_nobody_on_it_says_so(self, alert_db):
        alert_db.update_rule("weapon", whatsapp=True)
        service = make_service(alert_db, couriers(whatsapp=FakeSender()))
        service.enqueue(knife())
        service.step()
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.reason) == ("skipped", "no_recipients")

    def test_a_recipient_switched_off_is_skipped_by_name(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        off = alert_db.add_recipient("sms", "+201001234567", "Away", enabled=False)
        alert_db.add_recipient("sms", "+201001234568", "Here")
        sender = FakeSender()
        service = make_service(alert_db, couriers(sms=sender))
        service.enqueue(knife())
        service.step()
        rows = {r.recipient_name: r for r in alert_db.recent(5)}
        assert (rows["Away"].outcome, rows["Away"].reason) == ("skipped", "recipient_off")
        assert rows["Here"].outcome == "sent"
        assert [d for d, _ in sender.sent] == ["+201001234568"]
        assert off.id

    def test_a_channel_switched_off_writes_nothing(self, alert_db):
        """Not an attempt, so not a row - otherwise the log drowns in them."""
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers(sms=FakeSender()))
        service.enqueue(knife())
        service.step()
        assert alert_db.recent(5) == []

    def test_one_row_per_recipient_per_channel(self, alert_db):
        alert_db.update_rule("weapon", sms=True, email=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        alert_db.add_recipient("sms", "+201001234568", "B")
        alert_db.add_recipient("email", "c@school.example", "C")
        service = make_service(alert_db, couriers(sms=FakeSender(), email=FakeSender()))
        service.enqueue(knife())
        for _ in range(3):
            service.step()
        rows = alert_db.recent(10)
        assert sorted((r.channel, r.recipient_name, r.outcome) for r in rows) == [
            ("email", "C", "sent"), ("sms", "A", "sent"), ("sms", "B", "sent")]

    def test_the_same_event_twice_writes_nothing_more(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        sender = FakeSender()
        service = make_service(alert_db, couriers(sms=sender))
        service.enqueue(knife())
        service.enqueue(knife())
        service.step()
        service.step()
        assert len(alert_db.recent(10)) == 1
        assert len(sender.sent) == 1

    def test_a_full_queue_drops_the_oldest_and_logs_it(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers(sms=FakeSender()),
                               config=AlertsConfig(queue_size=2))
        service.enqueue(knife("s1"))
        service.enqueue(knife("s2"))
        service.enqueue(knife("s3"))              # s1 falls off the end
        dropped = [r for r in alert_db.recent(10) if r.reason == "queue_full"]
        assert [(r.event_key, r.outcome) for r in dropped] == [("weapon:s1:opened", "failed")]
        for _ in range(3):
            service.step()
        sent = {r.event_key for r in alert_db.recent(10) if r.outcome == "sent"}
        assert sent == {"weapon:s2:opened", "weapon:s3:opened"}

    def test_a_test_send_ignores_the_rules_and_the_switch(self, alert_db):
        """An administrator proving the wiring must not be stopped by a chip."""
        person = alert_db.add_recipient("sms", "+201001234567", "A", enabled=False)
        sender = FakeSender()
        service = make_service(alert_db, couriers(sms=sender))
        row_id = service.test_send(person.id)
        assert alert_db.row(row_id).outcome == "queued"
        service.step()
        assert alert_db.row(row_id).outcome == "sent"
        assert "test" in sender.sent[0][1].body.lower()

    def test_a_test_send_without_keys_is_skipped_at_once(self, alert_db):
        person = alert_db.add_recipient("email", "a@school.example", "A")
        service = make_service(alert_db, couriers())
        row = alert_db.row(service.test_send(person.id))
        assert (row.outcome, row.reason) == ("skipped", "provider_missing")

    def test_a_test_send_to_nobody_is_not_found(self, alert_db):
        service = make_service(alert_db, couriers())
        with pytest.raises(KeyError):
            service.test_send("no-such-id")

    def test_a_restart_fails_the_leftovers_and_sends_nothing(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        refusing = FakeSender([providers.SendResult.failed("timeout", "TimeoutError")] * 5)
        first = make_service(alert_db, couriers(sms=refusing))
        first.enqueue(knife())
        first.step()                           # attempt 1 fails; the row stays queued
        assert alert_db.recent(1)[0].outcome == "queued"

        # the engine is killed here; a new one starts over the same database
        sender = FakeSender()
        second = make_service(alert_db, couriers(sms=sender))
        second.start(run_thread=False)
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.reason) == ("failed", "engine_stopped")
        second.step()
        assert sender.sent == []

    def test_a_graceful_stop_logs_what_was_still_waiting(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers(sms=FakeSender()))
        service.enqueue(knife("s1"))
        service.stop()
        (row,) = alert_db.recent(5)
        assert (row.event_key, row.outcome, row.reason) == (
            "weapon:s1:opened", "failed", "engine_stopped")

    def test_a_sender_that_raises_is_a_failure_not_a_dead_thread(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers(sms=FakeSender([RuntimeError("boom")] * 3)),
                               config=AlertsConfig(retries=1))
        service.enqueue(knife())
        service.step()
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.reason) == ("failed", "unreachable")

    def test_camera_names_are_filled_by_the_sender(self, alert_db):
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        sender = FakeSender()
        service = make_service(alert_db, couriers(sms=sender))
        service.bind(camera_name=lambda camera_id: {"cam-a": "Yard camera"}.get(camera_id))
        service.enqueue(knife())
        service.step()
        assert "Yard camera" in sender.sent[0][1].body

    def test_retention_runs_once_a_day(self, alert_db):
        alert_db.add_row("old", "weapon", "skipped", at=NOW - timedelta(days=120),
                         reason="no_recipients")
        clock = Clockwork(NOW)
        service = make_service(alert_db, couriers(), now=clock)
        service.step()
        assert alert_db.recent(5) == []

    def test_the_thread_starts_and_stops(self, alert_db):
        service = make_service(alert_db, couriers(), now=None)
        service.start()
        try:
            assert service.running
        finally:
            finished = service.stop()
        assert finished is True, "stop() says the sender is done, so its store may close"
        assert not service.running

    def test_stop_never_calls_failed_a_message_a_courier_still_carries(self, alert_db):
        """Its outcome is the courier's answer, not a guess made while the courier
        is still talking. A stop that gives up waiting leaves that one row
        queued; the courier's answer, when it comes, is what the log says."""
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        inside, release = threading.Event(), threading.Event()

        def a_slow_courier():
            inside.set()
            release.wait(5)

        service = make_service(alert_db, couriers(sms=FakeSender(before=a_slow_courier)))
        service.start()
        thread = service._thread
        try:
            service.enqueue(knife())
            assert inside.wait(5), "the courier was never called"
            # False: a courier is still talking, so the caller must leave the
            # store open for its answer.
            assert service.stop(timeout=0.05) is False
            (row,) = alert_db.recent(5)
            assert row.outcome == "queued"
        finally:
            release.set()
            thread.join(5)
        (row,) = alert_db.recent(5)
        assert (row.outcome, row.provider_id) == ("sent", "SM1")

    def test_stop_waits_as_long_as_a_courier_may_take(self, alert_db):
        """A shorter wait gives up on a call the courier may still answer."""
        service = make_service(alert_db, couriers(),
                               config=AlertsConfig(timeout_seconds=10))
        waited: list[float] = []

        class SenderThread:
            def join(self, timeout=None):
                waited.append(timeout)

            def is_alive(self):
                return False

        service._thread = SenderThread()
        service.stop()
        assert waited and waited[0] > 10

    def test_once_stopping_a_pass_records_but_calls_no_courier(self, alert_db):
        """So a stop waits on the one call already running, never a new one."""
        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        sender = FakeSender()
        service = make_service(alert_db, couriers(sms=sender))
        service.stop()
        service.enqueue(knife())
        service.step()
        assert sender.sent == []
        (row,) = alert_db.recent(5)
        assert row.outcome == "queued"


class FlakyConnection:
    """The alert store's connection, with chosen writes to the delivery log
    failing - a disk that hiccups, or a lock held past the busy timeout.
    `fail` counts the log's inserts from 1."""

    def __init__(self, conn, fail):
        self._conn = conn
        self.fail = set(fail)
        self.inserts = 0

    def execute(self, sql, *args):
        if sql.lstrip().startswith("INSERT INTO alert_delivery"):
            self.inserts += 1
            if self.inserts in self.fail:
                raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestWhenAWriteFails:
    """An event with any row is never recorded again - that is what makes a
    restart harmless. So a write that fails must leave the event with no row
    and able to be tried again, never half recorded or marked as handled
    (P9-FR-023: a message that could not go is a row, never a missing row)."""

    def test_an_event_is_written_whole_or_not_at_all(self, alert_db, monkeypatch):
        alert_db.update_rule("weapon", whatsapp=True, sms=True)
        alert_db.add_recipient("whatsapp", "+201001234567", "A")
        alert_db.add_recipient("sms", "+201001234568", "B")
        sender = FakeSender()
        service = make_service(alert_db, couriers(whatsapp=sender, sms=sender))
        monkeypatch.setattr(alert_db, "_conn", FlakyConnection(alert_db._conn, fail={2}))

        service.enqueue(knife())
        service.step()                         # B's row fails, so A's is not kept
        assert alert_db.recent(5) == []
        assert sender.sent == []

        for _ in range(3):                     # the next pass writes both
            service.step()
        rows = alert_db.recent(5)
        assert sorted((r.recipient_name, r.outcome) for r in rows) == [
            ("A", "sent"), ("B", "sent")]

    def test_an_event_that_cannot_be_written_is_not_held_for_ever(
            self, alert_db, monkeypatch):
        from vg.alerts.service import RECORD_TRIES

        alert_db.update_rule("weapon", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        service = make_service(alert_db, couriers(sms=FakeSender()))
        broken = FlakyConnection(alert_db._conn, fail=range(1, 100))
        monkeypatch.setattr(alert_db, "_conn", broken)
        service.enqueue(knife())
        for _ in range(RECORD_TRIES + 3):
            service.step()
        assert broken.inserts == RECORD_TRIES

    def test_a_dark_camera_whose_message_could_not_be_written_is_tried_again(
            self, alert_db, monkeypatch):
        """Down and back alike: the camera is only taken as announced once its
        row exists, or no later pass would ever say it."""
        alert_db.update_rule("camera", sms=True)
        alert_db.add_recipient("sms", "+201001234567", "A")
        camera = FakeWorker("down", NOW - timedelta(minutes=10))
        registry = type("Registry", (), {"workers": {"cam-a": camera}})()
        service = make_service(alert_db, couriers(sms=FakeSender()), registry=registry)
        monkeypatch.setattr(alert_db, "_conn",
                            FlakyConnection(alert_db._conn, fail={1, 3}))

        with pytest.raises(sqlite3.OperationalError):
            service.step()                     # "no picture" could not be written
        service.step()                         # ... so it is written now
        service.step()
        assert [r.event_key.split(":")[2] for r in alert_db.recent(5)] == ["down"]

        camera.status = "ok"
        with pytest.raises(sqlite3.OperationalError):
            service.step()                     # "back" could not be written
        service.step()
        service.step()
        states = sorted(r.event_key.split(":")[2] for r in alert_db.recent(5))
        assert states == ["down", "up"]
        assert {r.outcome for r in alert_db.recent(5)} == {"sent"}
