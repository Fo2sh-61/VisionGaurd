"""Alerts that wait for a person, and the dismissals that clear them.

**An alert is not a row.** It is a today's pass whose status needs somebody
and which nobody has dismissed yet. That is the whole design, and most of
this file exists to hold it: nothing derived can drift out of step with the
log, because there is nothing but the log.

Three rules get their own tests because each one has a tempting wrong answer:

- **A dismissal is per pass, not per car.** The same car passing again raises
  a new alert. Silencing the car would be a filter somebody set once and then
  stopped seeing a blacklisted vehicle.
- **The audit entry goes first**, as everywhere else here.
- **A near match is a question about exactly one candidate**, or it is not
  asked. Two candidates is a coin toss, and a wrong name against a stranger's
  car is worse than saying nothing at all.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as vgconfig  # noqa: E402
from vg.api.live import LiveStore  # noqa: E402
from vg.auth import deps as auth_deps  # noqa: E402
from vg.events.vehicles import VehicleStore  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402


def _day_start():
    """Site-local midnight as UTC — the window "today" actually means.

    Computed, never written down: a fixture that pins a date passes for one
    day and then fails having found nothing wrong with the product.
    """
    from datetime import date, datetime, timezone

    from vg.clock import clock_for

    clock = clock_for(vgconfig.load().timezone)
    today = date.fromisoformat(clock.today())
    midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return midnight - timedelta(minutes=clock.offset_minutes(midnight))


@pytest.fixture
def gate(tmp_path):
    cfg = vgconfig.load()
    vehicles = VehicleStore(tmp_path / "vehicles.db")
    store = LiveStore(config=cfg, registry=CameraRegistry(cfg.cameras),
                      vehicle_store=vehicles)
    try:
        yield store, vehicles
    finally:
        vehicles.close_db()


def _pass(vehicles, plate="سنر 582", hour=8, gate_no=1):
    """One pass today, `hour - 8` hours in.

    `today` is the site's today from the clock, not the UTC date — permit
    expiry is decided against it, and a site an hour ahead of UTC would
    otherwise judge an expiry on the wrong day around midnight.
    """
    from datetime import date

    from vg.clock import clock_for

    at = _day_start() + timedelta(hours=hour - 8, minutes=30)
    return vehicles.record_pass(
        at=at, camera_id="cam-laptop", gate=gate_no, direction="entry",
        plate=plate, confidence=0.9, votes=3, needs_review=False,
        today=date.fromisoformat(clock_for(vgconfig.load().timezone).today()),
    )


class TestWhatRaisesAnAlert:
    def test_an_unregistered_car(self, gate):
        store, vehicles = gate
        _pass(vehicles)

        alerts = store.vehicle_alerts()

        assert [a.kind for a in alerts] == ["unknown"]

    def test_a_blacklisted_car(self, gate):
        store, vehicles = gate
        vehicles.add(plate="رقص 9058", owner_name="Former contractor",
                     category="blacklist")
        _pass(vehicles, plate="رقص 9058")

        assert [a.kind for a in store.vehicle_alerts()] == ["blacklist"]

    def test_an_expired_permit_says_when_it_ran_out(self, gate):
        store, vehicles = gate
        vehicles.add(plate="نيع 3317", owner_name="Hoda Kamel",
                     category="visitor", valid_until="2020-07-28")
        _pass(vehicles, plate="نيع 3317")

        alert = store.vehicle_alerts()[0]
        assert alert.kind == "expired"
        assert alert.permit_expired_on == "2020-07-28"

    def test_a_registered_car_raises_nothing(self, gate):
        """The overwhelmingly common case. An alert per car through the gate
        is an alert nobody reads."""
        store, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        _pass(vehicles, plate="بجد 1234")

        assert store.vehicle_alerts() == []

    def test_the_owner_travels_with_the_alert(self, gate):
        store, vehicles = gate
        vehicles.add(plate="رقص 9058", owner_name="Former contractor",
                     category="blacklist")
        _pass(vehicles, plate="رقص 9058")

        assert store.vehicle_alerts()[0].owner == "Former contractor"

    def test_newest_first(self, gate):
        store, vehicles = gate
        _pass(vehicles, plate="سنر 582", hour=8)
        _pass(vehicles, plate="مصف 8170", hour=10)

        first = store.vehicle_alerts()[0]
        assert first.plate_display.replace(" ", "").endswith("٨١٧٠")


class TestDismissing:
    def test_a_dismissed_alert_goes(self, gate):
        store, vehicles = gate
        record = _pass(vehicles)

        assert store.dismiss_alert(record.id, "Mohamed Fouad") is True
        assert store.vehicle_alerts() == []

    def test_dismissing_twice_is_refused(self, gate):
        """The endpoint turns this into a 409 — a different answer from
        "no such pass", and a second click deserves the honest one."""
        store, vehicles = gate
        record = _pass(vehicles)
        store.dismiss_alert(record.id, "Mohamed Fouad")

        assert store.dismiss_alert(record.id, "Mohamed Fouad") is False

    def test_dismissing_a_pass_that_does_not_exist_raises(self, gate):
        store, _ = gate

        with pytest.raises(KeyError):
            store.dismiss_alert("no-such-pass", "Mohamed Fouad")

    def test_the_audit_entry_is_written_before_the_dismissal(self, gate):
        """Somebody clearing an alert is a fact whether or not the write
        succeeded. Logging afterwards loses exactly the case worth keeping."""
        store, vehicles = gate
        record = _pass(vehicles)
        store.dismiss_alert(record.id, "Mohamed Fouad")

        entries = [e for e in store.audit(50)
                   if e.action == "vehicle.alert.dismiss"]
        assert len(entries) == 1
        assert entries[0].actor == "Mohamed Fouad"

    def test_the_audit_says_whether_the_action_was_taken(self, gate):
        """"I dealt with it" and "not worth acting on" are different answers
        to the same alert, and the log should be able to tell them apart."""
        store, vehicles = gate
        record = _pass(vehicles)
        store.dismiss_alert(record.id, "Sara Ibrahim", action_taken=True)

        entry = next(e for e in store.audit(50)
                     if e.action == "vehicle.alert.dismiss")
        assert "resolved by acting on it" in entry.detail

    def test_the_same_car_passing_again_raises_a_new_alert(self, gate):
        """**A dismissal is per pass, not per car.**

        Silencing the car would be a filter somebody set once at 8am and then
        stopped seeing a blacklisted vehicle for the rest of the day.
        """
        store, vehicles = gate
        first = _pass(vehicles, hour=8)
        store.dismiss_alert(first.id, "Mohamed Fouad")
        _pass(vehicles, hour=11)

        assert len(store.vehicle_alerts()) == 1

    def test_a_dismissal_cannot_be_undone(self, gate):
        """There is no withdraw path, here or anywhere else in this product.
        An acknowledgement that can be taken back is not one."""
        store, vehicles = gate
        record = _pass(vehicles)
        store.dismiss_alert(record.id, "Mohamed Fouad")

        assert not hasattr(store, "undismiss_alert")
        assert not hasattr(vehicles, "undismiss_alert")


class TestTheNearMatchIsAQuestion:
    """`ب` and `ت` are the same shape at gate distance. One misread letter
    turns a colleague into a stranger, and the console should be able to ask
    about that — without ever asserting it."""

    def test_one_candidate_is_offered(self, gate):
        store, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        _pass(vehicles, plate="تجد 1234")

        alert = store.vehicle_alerts()[0]
        assert alert.near_match_owner == "Mohamed Fouad"
        assert alert.near_match_display

    def test_two_candidates_are_not_a_suggestion(self, gate):
        """A coin toss put against a stranger's car is worse than silence."""
        store, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        vehicles.add(plate="تجد 1234", owner_name="Sara Ibrahim",
                     category="staff")
        _pass(vehicles, plate="ثجد 1234")

        alert = store.vehicle_alerts()[0]
        assert alert.near_match_owner is None
        assert alert.near_match_display is None

    def test_no_candidate_offers_nothing(self, gate):
        store, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        _pass(vehicles, plate="رقص 9058")

        assert store.vehicle_alerts()[0].near_match_display is None

    def test_the_pass_is_still_recorded_as_unknown(self, gate):
        """**Nothing is merged.** The suggestion is a question for a person;
        the pass says what the reader actually saw, for ever."""
        store, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        record = _pass(vehicles, plate="تجد 1234")

        assert record.status == "unknown"
        assert vehicles.pass_by_id(record.id).status == "unknown"
        assert store.vehicle_alerts()[0].kind == "unknown"


class TestOnlyAlertsAreGuardWritable:
    """The carve-out, tested from both sides.

    A prefix that quietly widened would hand the register to every guard on
    the site, and nothing about the code would look wrong.
    """

    def test_a_guard_may_dismiss_an_alert(self):
        assert auth_deps.requires_admin(
            "POST", "/vehicles/alerts/abc123/dismiss") is False

    def test_a_guard_may_not_write_the_register(self):
        assert auth_deps.requires_admin("POST", "/vehicles/register") is True

    def test_a_guard_may_not_delete_a_pass(self):
        assert auth_deps.requires_admin(
            "DELETE", "/vehicles/passes/abc123") is True

    def test_a_guard_may_not_import_the_register(self):
        assert auth_deps.requires_admin("POST", "/vehicles/import") is True

    def test_a_guard_may_not_export_the_log(self):
        assert auth_deps.requires_admin("POST", "/vehicles/export") is True

    def test_the_carve_out_does_not_leak_to_a_sibling_prefix(self):
        """`/vehicles/alertsomething` must not match `/vehicles/alerts`."""
        assert auth_deps.requires_admin(
            "POST", "/vehicles/alertsomething") is True

    def test_reading_alerts_needs_no_administrator(self):
        assert auth_deps.requires_admin("GET", "/vehicles/alerts") is False

    def test_the_carve_out_stays_small(self):
        """One prefix. If this ever grows, it should be a decision somebody
        argued for rather than a line that crept in."""
        assert auth_deps.OPERATOR_WRITE_PREFIXES == ("/vehicles/alerts",)
