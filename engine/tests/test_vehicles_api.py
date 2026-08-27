"""The vehicle gate over the wire: permissions, honesty, and degradation.

Two rules do most of the work here, and both have been broken elsewhere in
this product before:

**Absent is not zero.** `GateSummary` sends optional counts. A tile with no
number renders the reason beside it; a tile showing `0` is claiming a
measurement. "No car came through today" and "we are not looking" must not
arrive as the same payload — that is SC-010, and it is the whole reason the
design file's invented figures (2,140 registered, 148 entered) can never
reach a screen.

**A guard reads, an administrator writes.** Decided by path prefix in
`auth/deps.py`, once, rather than by a decorator per endpoint. A guard has to
read the register to do their job and must not be able to un-blacklist a car.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import app as app_module  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import deps as auth_deps  # noqa: E402

VEHICLE_READS = (
    "/vehicles/summary",
    "/vehicles/passes",
    "/vehicles/cameras",
)


@pytest.fixture
def app(user_store):
    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


@pytest.fixture
def bare_app(bare_live_store, user_store):
    """A real `LiveStore` with no worker and no register behind it.

    The state a fresh machine is in, and the one that used to make pages lie.
    """
    app_module.set_store(bare_live_store)
    application = create_app()
    application.state.users = user_store
    return application


class TestNothingIsRunning:
    """A fresh engine: no gate camera, no plate model, no register.

    Every one of these must answer, and answer honestly. A 503 or a stack
    trace here would make an unconfigured feature look like a broken one.
    """

    @pytest.mark.parametrize("path", VEHICLE_READS)
    def test_every_read_answers_200(self, bare_app, authed, path):
        response = authed(bare_app, role="it").get(path)

        assert response.status_code == 200, (
            "degradation is payload, never a status code - rule 7")

    def test_the_summary_says_why_rather_than_showing_zeros(self, bare_app, authed):
        body = authed(bare_app, role="it").get("/vehicles/summary").json()

        assert body["reason"], "a summary with no data must say why"
        assert body["entered"] is None, "absent, not 0 - 0 is a measurement"
        assert body["inside"] is None
        assert body["blacklist"] is None

    def test_no_gate_camera_is_named_as_the_reason(self, bare_app, authed):
        body = authed(bare_app, role="it").get("/vehicles/summary").json()

        assert "gate" in body["reason"].lower()

    def test_the_pass_log_is_empty_rather_than_invented(self, bare_app, authed):
        assert authed(bare_app, role="it").get("/vehicles/passes").json() == []

    def test_no_camera_is_offered_as_a_gate(self, bare_app, authed):
        assert authed(bare_app, role="it").get("/vehicles/cameras").json() == []


class TestTheMockStoreDoesNotInventVehicles:
    """`VG_MOCK=1` means the whole store is fixtures and says so. This feature
    still answers "not configured" there, because the design it was built from
    carries invented figures and a mock serving those would put them on screen
    in the one mode nobody expects to be lying differently."""

    def test_the_summary_is_empty_and_explains_itself(self, app, authed):
        body = authed(app, role="it").get("/vehicles/summary").json()

        assert body["reason"]
        assert body["entered"] is None

    def test_no_passes_are_fabricated(self, app, authed):
        assert authed(app, role="it").get("/vehicles/passes").json() == []

    @pytest.mark.parametrize("invented", ["2140", "2,140", "148", "121", "27"])
    def test_the_designs_placeholder_numbers_appear_nowhere(
            self, app, authed, invented):
        """The mock-up says "2,140 on record" and "148 entered today". Those
        are invented, and SC-010 says none of them ships."""
        client = authed(app, role="it")
        for path in VEHICLE_READS:
            assert invented not in client.get(path).text


class TestWhoMayDoWhat:
    def test_a_guard_may_read_the_register(self, bare_app, authed):
        """Not a courtesy. Reading the gate log is the job."""
        response = authed(bare_app, role="it").get("/vehicles/passes")

        assert response.status_code == 200

    @pytest.mark.parametrize("method,path", [
        ("post", "/vehicles/register"),
        ("patch", "/vehicles/register/anything"),
        ("delete", "/vehicles/register/anything"),
        ("post", "/vehicles/import"),
        ("post", "/vehicles/export"),
    ])
    def test_a_guard_may_not_write(self, bare_app, authed, method, path):
        """A guard must not be able to un-blacklist a car.

        The refusal happens in middleware, before any handler runs, so these
        pass whether or not the endpoint has been written yet — which is the
        point of deciding by path rather than by decorator.
        """
        client = authed(bare_app, role="it")
        call = getattr(client, method)
        response = (call(path) if method == "delete"
                    else call(path, json={"plate": "بجد 1234"}))

        assert response.status_code == 403, f"{method.upper()} {path} was allowed"

    def test_the_prefix_is_the_mechanism(self):
        """Pinned so a later endpoint under /vehicles cannot be added open by
        accident. A decorator per endpoint is the same rule written as a hope."""
        assert "/vehicles" in auth_deps.ADMIN_WRITE_PREFIXES
        assert "/vehicles" not in auth_deps.ADMIN_PREFIXES, (
            "admin-only would stop a guard reading the gate log")

    @pytest.mark.parametrize("path", VEHICLE_READS)
    def test_nobody_gets_in_without_signing_in(self, bare_app, path):
        assert TestClient(bare_app).get(path).status_code == 401

    def test_no_vehicle_path_became_public(self):
        assert not any(p.startswith("/vehicles") for p in auth_deps.PUBLIC_PATHS)


@pytest.fixture
def register_app(user_store, tmp_path):
    """A `LiveStore` with a real register behind it.

    Built by hand rather than by fixture, the way `test_groups.py` does it.
    The store is closed before the tempdir or Windows fails the teardown.
    """
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.events.vehicles import VehicleStore
    from vg.ingest.registry import CameraRegistry

    vehicles = VehicleStore(tmp_path / "vehicles.db")
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                      vehicle_store=vehicles)
    app_module.set_store(store)
    application = create_app()
    application.state.users = user_store
    application.state.vehicle_store = vehicles
    try:
        yield application, vehicles
    finally:
        vehicles.close_db()


class TestTheRegisterOverTheWire:
    def test_an_admin_can_add_a_vehicle(self, register_app, authed):
        application, _ = register_app

        response = authed(application).post("/vehicles/register", json={
            "plate": "ب ج د ١٢٣٤", "owner": "Tarek", "category": "staff"})

        assert response.status_code == 201
        body = response.json()
        assert body["plate"] == "بجد 1234"
        assert body["category"] == "staff"

    def test_the_same_plate_twice_is_a_409_not_a_second_row(
            self, register_app, authed):
        application, vehicles = register_app
        client = authed(application)
        client.post("/vehicles/register", json={"plate": "بجد 1234"})

        # The same car, typed the other way.
        again = client.post("/vehicles/register",
                            json={"plate": "ب ج د ١٢٣٤"})

        assert again.status_code == 409
        assert vehicles.count() == 1

    def test_an_unknown_category_is_refused(self, register_app, authed):
        application, _ = register_app

        response = authed(application).post("/vehicles/register", json={
            "plate": "بجد 1234", "category": "resident"})

        assert response.status_code == 400

    def test_a_guard_can_read_it_and_an_admin_can_change_it(
            self, register_app, authed):
        application, _ = register_app
        authed(application).post("/vehicles/register",
                                 json={"plate": "بجد 1234", "owner": "Tarek"})

        guard = authed(application, role="it")
        assert guard.get("/vehicles/register").status_code == 200
        assert len(guard.get("/vehicles/register").json()) == 1
        assert guard.post("/vehicles/register",
                          json={"plate": "سصط 9876"}).status_code == 403

    def test_editing_a_vehicle_that_is_not_there_is_a_404(
            self, register_app, authed):
        application, _ = register_app

        response = authed(application).patch(
            "/vehicles/register/nope", json={"plate": "بجد 1234"})

        assert response.status_code == 404

    def test_removing_a_vehicle_keeps_its_passes(self, register_app, authed):
        """`SET NULL`, never `CASCADE`. Over the wire this time."""
        application, vehicles = register_app
        client = authed(application)
        vehicle_id = client.post(
            "/vehicles/register",
            json={"plate": "بجد 1234", "owner": "Tarek"}).json()["id"]
        vehicles.record_pass(
            at=_day_start(), camera_id="gate1", gate=1, direction="entry",
            plate="بجد 1234", confidence=0.9, votes=3, needs_review=False,
            today=_day_start().date())

        assert client.delete(f"/vehicles/register/{vehicle_id}").status_code == 200

        assert len(vehicles.passes()) == 1
        assert vehicles.count() == 0

    def test_the_search_narrows_the_register(self, register_app, authed):
        application, _ = register_app
        client = authed(application)
        client.post("/vehicles/register",
                    json={"plate": "بجد 1234", "owner": "Tarek", "unit": "IT"})
        client.post("/vehicles/register",
                    json={"plate": "سصط 9876", "owner": "Nadia"})

        assert len(client.get("/vehicles/register?q=Tarek").json()) == 1
        assert len(client.get("/vehicles/register?q=nobody").json()) == 0

    def test_the_template_downloads_and_is_importable(self, register_app, authed):
        """The first thing a school does with the template is upload it."""
        application, _ = register_app
        client = authed(application)

        template = client.get("/vehicles/template")
        assert template.status_code == 200
        assert "attachment" in template.headers["content-disposition"]

        loaded = client.post(
            "/vehicles/import",
            files={"file": ("template.csv", template.content, "text/csv")})

        assert loaded.status_code == 200
        assert loaded.json()["added"] == 1, loaded.json()["problems"]

    def test_an_import_reports_every_rejected_row(self, register_app, authed):
        """A silent partial import is the worst outcome: the office believes
        the list is loaded and finds out at the gate."""
        application, _ = register_app
        rows = [
            "plate,owner_name,category",
            "بجد 1234,Tarek,staff",
            ",No plate,staff",
            "سصط 9876,Nadia,resident",
        ]
        csv = chr(10).join(rows).encode("utf-8")

        result = authed(application).post(
            "/vehicles/import",
            files={"file": ("list.csv", csv, "text/csv")}).json()

        assert result["added"] == 1
        assert len(result["problems"]) == 2

    def test_the_audit_entry_is_written_for_every_change(
            self, register_app, authed):
        """Who changed the register, and when. Written before the change."""
        application, _ = register_app
        client = authed(application)
        client.post("/vehicles/register", json={"plate": "بجد 1234"})

        actions = {e["action"] for e in client.get("/audit").json()}

        assert "vehicle.add" in actions


class TestTheOverlayCarriesNoIdentity:
    """Rule 1. A plate names a **car**, never the person driving it.

    The `vehicles` branch in `_boxes` sits above the face default for exactly
    this reason — falling through would draw somebody's name over a
    windscreen, which the knife feature already shipped once by accident.
    """

    def test_a_gate_camera_draws_no_face_boxes(self, bare_live_store):
        boxes = bare_live_store.overlay("cam-laptop", feature="vehicles")

        assert all(b.kind == "plate" for b in boxes)

    def test_the_branch_is_above_the_face_default(self, bare_live_store):
        """With no worker there are no plate boxes — and crucially no face
        boxes either. A non-empty list here would mean the branch is missing
        and the request fell through to recognition."""
        assert bare_live_store.overlay("cam-laptop", feature="vehicles") == []


class TestSystemHealthSaysWhetherPlatesAreBeingRead:
    """Rule 8. A subsystem that failed to start says so on the page an
    operator opens to ask exactly that."""

    def test_there_is_a_row_for_plate_reading(self, bare_live_store):
        stages = {s.key for s in bare_live_store.health().pipeline}

        assert "vehicles" in stages

    def test_it_is_unhealthy_and_says_why_when_nothing_is_running(
            self, bare_live_store):
        stage = next(s for s in bare_live_store.health().pipeline
                     if s.key == "vehicles")

        assert stage.healthy is False
        assert stage.detail and stage.detail != "Not running."

    def test_the_capability_and_the_stage_give_the_same_reason(
            self, bare_live_store):
        """Or the page and System Health disagree about whether plates are
        being read, and an operator cannot tell which to believe."""
        capability = next(c for c in bare_live_store.capabilities()
                          if c.key == "vehicles")
        stage = next(s for s in bare_live_store.health().pipeline
                     if s.key == "vehicles")

        assert capability.reason == stage.detail

    def test_health_is_still_200_with_everything_off(self, bare_app, authed):
        """System Health stays up even when everything it describes is down."""
        assert authed(bare_app).get("/system/health").status_code == 200


@pytest.fixture
def gate_app(user_store, tmp_path):
    """A `LiveStore` with a real register **and** the configured cameras.

    `cam-laptop` is a gate camera with `direction: entry` and no exit
    counterpart, which is the state P6-FR-012 is about: entries can be
    counted, exits cannot be paired, and the page must say so rather than
    print a figure.
    """
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.events.vehicles import VehicleStore
    from vg.ingest.registry import CameraRegistry

    cfg = vgconfig.load()
    vehicles = VehicleStore(tmp_path / "vehicles.db")
    store = LiveStore(config=cfg, registry=CameraRegistry(cfg.cameras),
                      vehicle_store=vehicles)
    # Plate reading is "running" as far as the movements pages are
    # concerned. The worker itself reads frames, which this test has none of.
    store.vehicles_worker = _StoppedWorker()
    app_module.set_store(store)
    application = create_app()
    application.state.users = user_store
    application.state.vehicle_store = vehicles
    try:
        yield application, vehicles, store
    finally:
        vehicles.close_db()


class _StoppedWorker:
    """A worker that started and has seen nothing yet."""

    def plates_on(self, camera_id):
        return []


def _day_start():
    """Site-local midnight as UTC — the window "today" actually means.

    Computed from the site's clock rather than written down. These tests
    pinned `2026-08-24` and passed for one day: on the 25th every "today"
    count read zero and four tests failed, having found nothing wrong with
    the product. A fixture that expires is not a fixture.
    """
    from datetime import date, datetime, timedelta, timezone

    from vg import config as vgconfig
    from vg.clock import clock_for

    clock = clock_for(vgconfig.load().timezone)
    today = date.fromisoformat(clock.today())
    midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return midnight - timedelta(minutes=clock.offset_minutes(midnight))


def _pass(vehicles, plate="بجد 1234", hour=8, direction="entry", gate=1):
    """One pass, `hour - 8` hours into the site's day.

    `hour` keeps its old spelling so the call sites still read like times and
    the gaps between them are unchanged — 8 and 9 are still an hour apart.
    """
    from datetime import date, timedelta

    at = _day_start() + timedelta(hours=hour - 8)
    return vehicles.record_pass(
        at=at, camera_id="cam-laptop", gate=gate, direction=direction,
        plate=plate, confidence=0.9, votes=3, needs_review=False,
        today=date.fromisoformat(_day_start().date().isoformat()))


class TestMovements:
    """Who is inside, and what the engine may claim about it.

    With only an entry camera every entry stays open for ever, because
    nothing is watching the way out. The honest answer is to say that, not to
    print the number of cars that came in under the heading "inside".
    """

    def test_with_no_exit_camera_pairing_is_false(self, gate_app, authed):
        application, _, _ = gate_app

        body = authed(application, role="it").get("/vehicles/summary").json()

        assert body["pairingAvailable"] is False
        assert body["reason"], "the page needs the words, not just the flag"
        assert "exit" in body["reason"].lower()

    def test_with_no_exit_camera_no_figure_is_offered_for_inside(
            self, gate_app, authed):
        """SC-010 in its sharpest form: a count that cannot be computed is
        absent, never zero."""
        application, vehicles, _ = gate_app
        _pass(vehicles)

        body = authed(application, role="it").get("/vehicles/summary").json()

        assert body["entered"] == 1, "entries are countable and are counted"
        assert body["inside"] is None
        assert body["left"] is None

    def test_a_gate_row_says_pairing_is_unavailable_rather_than_zero(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles)

        rows = authed(application, role="it").get("/vehicles/gates").json()

        assert len(rows) == 1
        assert rows[0]["gate"] == 1
        assert rows[0]["entered"] == 1
        assert rows[0]["pairingAvailable"] is False
        assert rows[0]["inside"] is None

    def test_a_gate_with_nothing_through_it_still_appears(
            self, gate_app, authed):
        """A configured gate that saw no car is a measurement. Leaving the row
        out would read as "that gate is not set up"."""
        application, _, _ = gate_app

        rows = authed(application, role="it").get("/vehicles/gates").json()

        assert [r["gate"] for r in rows] == [1]
        assert rows[0]["entered"] == 0

    def test_no_totals_are_offered_when_plates_are_not_being_read(
            self, gate_app, authed):
        """Zero at a gate nobody is watching is indistinguishable from a quiet
        morning. The summary's reason carries the words instead."""
        application, vehicles, store = gate_app
        _pass(vehicles)
        store.vehicles_worker = None
        client = authed(application, role="it")

        assert client.get("/vehicles/gates").json() == []

        # ...and the words are on the summary instead of the numbers.
        assert client.get("/vehicles/summary").json()["reason"]

    def test_an_entry_with_no_exit_reads_as_still_inside(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles)

        inside = authed(application, role="it").get("/vehicles/inside").json()

        assert len(inside) == 1
        assert inside[0]["plate"] == "بجد 1234"
        assert inside[0]["leftAt"] is None
        assert inside[0]["minutes"] is not None

    def test_a_completed_visit_leaves_the_inside_list(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, hour=8, direction="entry")
        _pass(vehicles, hour=9, direction="exit")
        client = authed(application, role="it")

        assert client.get("/vehicles/inside").json() == []
        visits = client.get("/vehicles/visits").json()
        assert len(visits) == 1
        assert visits[0]["minutes"] == 60.0
        assert visits[0]["inferred"] is False

    def test_an_exit_nobody_saw_is_reported_as_inferred(self, gate_app, authed):
        """Two entries in a row. The car did leave; the engine never saw it,
        and must not claim it did."""
        application, vehicles, _ = gate_app
        _pass(vehicles, hour=8)
        _pass(vehicles, hour=11)

        visits = authed(application, role="it").get("/vehicles/visits").json()

        assert len(visits) == 1
        assert visits[0]["inferred"] is True
        assert visits[0]["exitGate"] is None

    def test_the_visit_carries_the_owner_when_the_car_is_registered(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        vehicles.add("بجد 1234", owner_name="Tarek", unit="IT")
        _pass(vehicles)

        inside = authed(application, role="it").get("/vehicles/inside").json()

        assert inside[0]["owner"] == "Tarek"
        assert inside[0]["unit"] == "IT"

    def test_a_guard_may_read_all_three(self, gate_app, authed):
        application, _, _ = gate_app
        client = authed(application, role="it")

        for path in ("/vehicles/gates", "/vehicles/inside", "/vehicles/visits"):
            assert client.get(path).status_code == 200, path


class TestTheExportIsAuditedFirst:
    """P6-FR-023. Somebody exporting the gate log is a fact whether or not
    the file was produced — so the entry is written before the CSV is built,
    never after it is handed over."""

    def test_the_export_returns_a_spreadsheet(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles)

        response = authed(application).post("/vehicles/export")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert "بجد 1234" in response.text
        assert "rows,1" in response.text

    def test_the_audit_entry_names_the_filters_that_were_applied(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles)
        client = authed(application)

        client.post("/vehicles/export?direction=entry&status=unknown")

        entry = next(e for e in client.get("/audit").json()
                     if e["action"] == "vehicle.export")
        assert "direction=entry" in entry["detail"]
        assert "status=unknown" in entry["detail"]

    def test_the_entry_survives_the_export_failing(self, gate_app, authed):
        """The proof that it is written **first**. If the log cannot be read
        the caller gets an error — and the request they made is still on the
        record."""
        application, vehicles, _ = gate_app

        def broken(*args, **kwargs):
            raise RuntimeError("the log could not be read")

        vehicles.passes = broken
        client = authed(application)

        with pytest.raises(RuntimeError):
            client.post("/vehicles/export")

        assert any(e["action"] == "vehicle.export"
                   for e in client.get("/audit").json())

    def test_a_guard_cannot_export_the_log(self, gate_app, authed):
        """A POST, so the same one line in `auth/deps.py` that protects the
        register protects this. A GET export would have been unaudited and
        readable by anybody."""
        application, _, _ = gate_app

        assert authed(application, role="it").post(
            "/vehicles/export").status_code == 403

    def test_the_export_carries_whether_the_photograph_is_still_there(
            self, gate_app, authed):
        """The row outlives its images by thirty days. "no photo" and "no
        idea" are different answers."""
        application, vehicles, _ = gate_app
        _pass(vehicles)

        body = authed(application).post("/vehicles/export").text

        assert "snapshot_kept" in body


class TestThePassLogFilters:
    def test_each_filter_narrows_the_log(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, plate="بجد 1234", hour=8, direction="entry", gate=1)
        _pass(vehicles, plate="سصط 9876", hour=9, direction="exit", gate=1)
        client = authed(application, role="it")

        assert len(client.get("/vehicles/passes").json()) == 2
        assert len(client.get("/vehicles/passes?direction=exit").json()) == 1
        assert len(client.get("/vehicles/passes?plate=1234").json()) == 1
        assert len(client.get("/vehicles/passes?gate=2").json()) == 0
        assert len(client.get("/vehicles/passes?status=known").json()) == 0

    def test_the_newest_pass_comes_first(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, plate="بجد 1234", hour=8)
        _pass(vehicles, plate="سصط 9876", hour=9)

        log = authed(application, role="it").get("/vehicles/passes").json()

        assert log[0]["plate"] == "سصط 9876"

    def test_the_export_obeys_the_same_filters(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, plate="بجد 1234", hour=8, direction="entry")
        _pass(vehicles, plate="سصط 9876", hour=9, direction="exit")

        body = authed(application).post("/vehicles/export?direction=exit").text

        assert "سصط 9876" in body
        assert "بجد 1234" not in body


class TestTheSnapshotEndpoint:
    """"The photo is gone" and "the pass is gone" are different answers, and
    the endpoint has to be able to give the first one."""

    def test_a_pass_with_a_photograph_serves_it(self, gate_app, authed, tmp_path):
        application, vehicles, _ = gate_app
        photo = tmp_path / "pass.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
        record = vehicles.record_pass(
            at=_day_start(), camera_id="cam-laptop", gate=1,
            direction="entry", plate="بجد 1234", confidence=0.9, votes=3,
            needs_review=False, today=_day_start().date(),
            snapshot=str(photo))

        client = authed(application, role="it")
        response = client.get(f"/vehicles/passes/{record.id}/snapshot")

        assert response.status_code == 200
        assert client.get("/vehicles/passes").json()[0]["hasSnapshot"] is True

    def test_an_aged_out_photograph_is_a_404_with_words_on_it(
            self, gate_app, authed):
        """The pass is still there. Only its picture has gone."""
        application, vehicles, _ = gate_app
        record = _pass(vehicles)

        client = authed(application, role="it")
        response = client.get(f"/vehicles/passes/{record.id}/snapshot")

        assert response.status_code == 404
        assert "retention" in response.text.lower()
        assert len(client.get("/vehicles/passes").json()) == 1, (
            "the row outlives its images")


class TestDeletingOnePass:
    """A read that is plainly nonsense can be removed from the log.

    Three things make that safe rather than a hole: only an administrator can
    do it, the audit entry is written **before** the row goes and cannot
    itself be deleted, and the delete is real — "inside now" is computed from
    this table, so a row kept hidden would keep answering after somebody
    deleted it.
    """

    def test_an_admin_can_delete_a_pass(self, gate_app, authed):
        application, vehicles, _ = gate_app
        record = _pass(vehicles)
        client = authed(application)

        assert client.delete(f"/vehicles/passes/{record.id}").status_code == 200

        assert client.get("/vehicles/passes").json() == []

    def test_a_guard_cannot(self, gate_app, authed):
        application, vehicles, _ = gate_app
        record = _pass(vehicles)

        response = authed(application, role="it").delete(
            f"/vehicles/passes/{record.id}")

        assert response.status_code == 403
        assert len(vehicles.passes()) == 1

    def test_the_audit_entry_names_the_plate_and_survives_the_row(
            self, gate_app, authed):
        """The point of writing it first. The pass is gone; the fact that
        somebody removed it, and which car it was, is not."""
        application, vehicles, _ = gate_app
        record = _pass(vehicles)
        client = authed(application)

        client.delete(f"/vehicles/passes/{record.id}")

        entry = next(e for e in client.get("/audit").json()
                     if e["action"] == "vehicle.pass.delete")
        assert entry["subject"] == "بجد 1234"
        assert "gate 1" in entry["detail"]

    def test_the_photograph_and_the_crop_go_with_it(self, gate_app, authed,
                                                    tmp_path):
        """Deleting the row and leaving the images would leave two orphans
        nothing will ever point at — the retention sweep only knows about
        files a row still names."""
        application, vehicles, _ = gate_app
        photo, crop = tmp_path / "p.jpg", tmp_path / "p-plate.jpg"
        photo.write_bytes(b"jpeg")
        crop.write_bytes(b"jpeg")
        record = vehicles.record_pass(
            at=_day_start(), camera_id="cam-laptop", gate=1,
            direction="entry", plate="بجد 1234", confidence=0.9, votes=3,
            needs_review=False, today=_day_start().date(),
            snapshot=str(photo), plate_crop=str(crop))

        authed(application).delete(f"/vehicles/passes/{record.id}")

        assert not photo.exists()
        assert not crop.exists()

    def test_a_deleted_pass_stops_answering_who_is_inside(self, gate_app, authed):
        """The reason there is no hidden flag. Visits are derived from this
        table, and a soft delete would need every query to remember to exclude
        the row. The one that forgets is the bug."""
        application, vehicles, _ = gate_app
        record = _pass(vehicles)
        client = authed(application)
        assert len(vehicles.inside()) == 1

        client.delete(f"/vehicles/passes/{record.id}")

        assert vehicles.inside() == []
        assert client.get("/vehicles/inside").json() == []

    def test_deleting_a_pass_that_is_not_there_is_a_404(self, gate_app, authed):
        application, _, _ = gate_app

        assert authed(application).delete(
            "/vehicles/passes/nope").status_code == 404

    def test_deleting_it_twice_is_a_404_the_second_time(self, gate_app, authed):
        application, vehicles, _ = gate_app
        record = _pass(vehicles)
        client = authed(application)

        assert client.delete(f"/vehicles/passes/{record.id}").status_code == 200
        assert client.delete(f"/vehicles/passes/{record.id}").status_code == 404

    def test_the_register_entry_is_untouched(self, gate_app, authed):
        """Deleting a bad read of a car must not remove the car."""
        application, vehicles, _ = gate_app
        vehicles.add("بجد 1234", owner_name="Tarek")
        record = _pass(vehicles)

        authed(application).delete(f"/vehicles/passes/{record.id}")

        assert vehicles.count() == 1
        assert vehicles.by_plate("بجد 1234").owner_name == "Tarek"

    def test_the_other_passes_stay(self, gate_app, authed):
        application, vehicles, _ = gate_app
        first = _pass(vehicles, plate="بجد 1234", hour=8)
        _pass(vehicles, plate="سصط 9876", hour=9)

        authed(application).delete(f"/vehicles/passes/{first.id}")

        assert [p.plate for p in vehicles.passes()] == ["سصط 9876"]
