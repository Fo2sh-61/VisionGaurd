"""Console v2, car plates (spec 024): the engine half.

One file so it can run alone. What is under test:

  Gone          a person closes an open visit by hand, audited first, and the
                counts that derive from visits drop with it. Never an exit.
  Filters       `q`, `days` and `exact` on the pass log; `q` on the export.
  Fix           keeps what the reader read; sends no message for a car that
                was corrected while still in view.
  Plate width   stored with new passes, null on old ones.
  Reader trouble  a reader that raises on every frame never reads as running.
  FP32          plates are never reduced precision, whatever engine.yaml says.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg.api import app as app_module  # noqa: E402
from vg.api import schemas as S  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.events.vehicles import VehicleStore  # noqa: E402
from vg.features.base import FeatureWorker  # noqa: E402
from vg.ingest.framebus import FrameBus  # noqa: E402
from vg.ingest.source import Frame  # noqa: E402

PLATE = "بجد 1234"
OTHER = "رقص 9058"


# ---------------------------------------------------------------------------
# fixtures and helpers (copied from test_vehicles_api.py and
# test_vehicles_store.py: a store with real data is built by hand)
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """A real store on a throwaway database, closed before the tempdir."""
    vehicles = VehicleStore(tmp_path / "vehicles.db")
    try:
        yield vehicles
    finally:
        vehicles.close_db()


class _StoppedWorker:
    """A worker that started and has seen nothing yet."""

    def plates_on(self, camera_id):
        return []


class _TroubledWorker(_StoppedWorker):
    """A worker whose counters say some cameras are dead or failing."""

    def __init__(self, died=(), failing=None):
        self._died = list(died)
        self._failing = dict(failing or {})

    @property
    def stats(self):
        return {"name": "vehicles", "cameras": 1, "frames_processed": 0,
                "last_inference_ms": 0.0, "queue_depth": 0, "queue_max": 1,
                "frames_dropped": 0, "behind": False,
                "died_on": self._died, "failing_on": self._failing}


@pytest.fixture
def gate_app(user_store, tmp_path):
    """A `LiveStore` with a real register and the configured cameras."""
    from vg import config as vgconfig
    from vg.api.live import LiveStore
    from vg.ingest.registry import CameraRegistry

    cfg = vgconfig.load()
    vehicles = VehicleStore(tmp_path / "gate.db")
    live = LiveStore(config=cfg, registry=CameraRegistry(cfg.cameras),
                     vehicle_store=vehicles)
    live.vehicles_worker = _StoppedWorker()
    app_module.set_store(live)
    application = create_app()
    application.state.users = user_store
    application.state.vehicle_store = vehicles
    try:
        yield application, vehicles, live
    finally:
        vehicles.close_db()


def _day_start():
    """Site-local midnight as UTC: the window "today" actually means."""
    from vg import config as vgconfig
    from vg.clock import clock_for

    clock = clock_for(vgconfig.load().timezone)
    today = date.fromisoformat(clock.today())
    midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return midnight - timedelta(minutes=clock.offset_minutes(midnight))


def _today():
    """The site's calendar date (not the UTC date of its midnight)."""
    from vg import config as vgconfig
    from vg.clock import clock_for

    return date.fromisoformat(clock_for(vgconfig.load().timezone).today())


def _pass(vehicles, plate=PLATE, hour=8, direction="entry", gate=1,
          days_ago=0, **extra):
    """One pass, `hour - 8` hours into the site's day, `days_ago` days back."""
    at = _day_start() + timedelta(hours=hour - 8) - timedelta(days=days_ago)
    return vehicles.record_pass(
        at=at, camera_id="cam-laptop", gate=gate, direction=direction,
        plate=plate, confidence=0.9, votes=3, needs_review=False,
        today=_today(), **extra)


def _entries(live, action):
    return [e for e in live.audit(100) if e.action == action]


def _audit(client):
    return client.get("/audit").json()


# ---------------------------------------------------------------------------
# plate width, and the late columns
# ---------------------------------------------------------------------------

class TestPlateWidth:
    def test_a_new_pass_keeps_how_wide_its_plate_was(self, store):
        record = _pass(store, plate_width=212)

        assert record.plate_width == 212
        assert store.passes()[0].plate_width == 212

    def test_a_pass_with_no_width_reads_as_unknown_never_zero(self, store):
        _pass(store)
        _pass(store, plate=OTHER, plate_width=0)

        assert {p.plate_width for p in store.passes()} == {None}

    def test_a_pass_recorded_before_the_column_existed_reads_null(self, tmp_path):
        """A gate that has been running is not wiped to get a feature."""
        path = tmp_path / "old.db"
        raw = sqlite3.connect(path)
        raw.execute(
            "CREATE TABLE vehicle_pass (id TEXT PRIMARY KEY, at TEXT NOT NULL,"
            " camera_id TEXT NOT NULL, gate INTEGER NOT NULL,"
            " direction TEXT NOT NULL, plate TEXT NOT NULL,"
            " plate_display TEXT NOT NULL, status TEXT NOT NULL,"
            " vehicle_id TEXT, confidence REAL NOT NULL, votes INTEGER NOT NULL,"
            " needs_review INTEGER NOT NULL DEFAULT 0, snapshot TEXT,"
            " plate_crop TEXT, created_at TEXT NOT NULL)")
        raw.execute(
            "INSERT INTO vehicle_pass VALUES ('old1', ?, 'cam', 1, 'entry', ?,"
            " ?, 'unknown', NULL, 0.9, 3, 0, NULL, NULL, ?)",
            (datetime.now(timezone.utc).isoformat(), "بجد 1234", "بجد 1234",
             datetime.now(timezone.utc).isoformat()))
        raw.commit()
        raw.close()

        upgraded = VehicleStore(path)
        try:
            (old,) = upgraded.passes()
            assert old.plate_width is None
            assert old.read_plate is None
        finally:
            upgraded.close_db()

    def test_a_better_photograph_refreshes_the_width_and_none_leaves_it(
            self, store):
        record = _pass(store, snapshot="a.jpg", plate_crop="a-plate.jpg",
                       plate_width=100)

        store.amend_pass(record.id, PLATE, 0.95, 5, False, _today(),
                         snapshot="b.jpg", plate_crop="b-plate.jpg",
                         plate_width=240)
        assert store.pass_by_id(record.id).plate_width == 240

        # No new photograph with the correction: the width belongs to the
        # photograph, so it stays with the one that is kept.
        store.amend_pass(record.id, PLATE, 0.96, 6, False, _today(),
                         plate_width=999)
        assert store.pass_by_id(record.id).plate_width == 240

    def test_the_wire_carries_the_width_or_null(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, plate_width=180)
        _pass(vehicles, plate=OTHER, hour=9)

        rows = authed(application).get("/vehicles/passes").json()

        assert {r["plateWidth"] for r in rows} == {180, None}


# ---------------------------------------------------------------------------
# the pass log: q, days, exact
# ---------------------------------------------------------------------------

class TestPassFilters:
    @pytest.fixture
    def filled(self, gate_app):
        application, vehicles, live = gate_app
        vehicles.add(PLATE, owner_name="Tarek Nassar", unit="IT", category="staff")
        _pass(vehicles, plate=PLATE, hour=8)
        _pass(vehicles, plate=PLATE, hour=9, days_ago=3)
        _pass(vehicles, plate="بجد 123", hour=10)
        _pass(vehicles, plate=OTHER, hour=11, days_ago=10)
        return application, vehicles

    def test_days_one_is_today_only(self, filled, authed):
        application, _ = filled

        rows = authed(application).get("/vehicles/passes?days=1").json()

        assert len(rows) == 2

    def test_days_without_day_means_today_and_without_days_nothing_changed(
            self, filled, authed):
        application, _ = filled
        client = authed(application)

        assert len(client.get("/vehicles/passes?days=1").json()) == 2
        # No `days` and no `day` is still all time: Ask links rely on it.
        assert len(client.get("/vehicles/passes").json()) == 4

    def test_days_seven_with_exact_is_that_plate_and_no_other(
            self, filled, authed):
        application, _ = filled

        rows = authed(application).get(
            "/vehicles/passes", params={"days": 7, "plate": PLATE,
                                         "exact": "true"}).json()

        assert [r["plate"] for r in rows] == [PLATE, PLATE]

    def test_without_exact_a_plate_is_still_a_substring(self, filled, authed):
        application, _ = filled

        rows = authed(application).get(
            "/vehicles/passes", params={"days": 7, "plate": "بجد 123"}).json()

        assert len(rows) == 3, "1234 contains 123"

    def test_days_ends_at_the_end_of_day_when_a_day_is_given(
            self, filled, authed):
        application, _ = filled
        three_ago = (_today() - timedelta(days=3)).isoformat()

        client = authed(application)
        rows = client.get(
            "/vehicles/passes", params={"day": three_ago, "days": 1}).json()
        assert len(rows) == 1

        rows = client.get(
            "/vehicles/passes", params={"day": three_ago, "days": 4}).json()
        assert len(rows) == 1, "today's passes are after that window"

    @pytest.mark.parametrize("days", [0, 32])
    def test_days_outside_1_to_31_is_refused(self, filled, authed, days):
        application, _ = filled

        response = authed(application).get(f"/vehicles/passes?days={days}")

        assert response.status_code == 422

    @pytest.mark.parametrize("query", ["Tarek", "1234", "١٢٣٤", "tarek"])
    def test_q_finds_by_owner_and_by_plate_in_either_digit_system(
            self, filled, authed, query):
        application, _ = filled

        rows = authed(application).get(
            "/vehicles/passes", params={"q": query, "days": 7}).json()

        assert rows and all(r["plate"] == PLATE for r in rows)

    def test_q_that_matches_nothing_returns_nothing(self, filled, authed):
        application, _ = filled

        assert authed(application).get(
            "/vehicles/passes?q=nobody-here").json() == []


class TestExportFollowsTheSearch:
    def test_q_writes_only_the_matching_rows(self, gate_app, authed):
        application, vehicles, _ = gate_app
        vehicles.add(PLATE, owner_name="Tarek Nassar", category="staff")
        _pass(vehicles, plate=PLATE, hour=8)
        _pass(vehicles, plate=OTHER, hour=9)

        response = authed(application).post("/vehicles/export?q=Tarek")

        assert response.status_code == 200
        # The file ends with a blank line and a short footer; the rows are
        # what comes before it.
        lines = response.text.split("\n\n")[0].splitlines()
        assert len(lines) == 2, "the heading and one row"
        assert "Tarek Nassar" in lines[1]

    def test_the_csv_has_no_new_column(self, gate_app, authed):
        """A file people may already parse."""
        application, vehicles, _ = gate_app
        _pass(vehicles, plate_width=200)

        heading = authed(application).post(
            "/vehicles/export").text.splitlines()[0]

        assert "width" not in heading
        assert heading.split(",")[-1] == "snapshot_kept"

    def test_the_audit_entry_is_written_before_the_file(self, gate_app):
        _, vehicles, live = gate_app
        _pass(vehicles)

        def boom(**_):
            raise RuntimeError("the file could not be built")

        vehicles.passes = boom
        with pytest.raises(RuntimeError):
            live.export_passes("Test Admin", q="Tarek")

        (entry,) = _entries(live, "vehicle.export")
        assert "q=Tarek" in entry.detail


# ---------------------------------------------------------------------------
# fix: keeps the original, sends nothing for a car still in view
# ---------------------------------------------------------------------------

class TestFixKeepsTheOriginal:
    def test_the_first_fix_keeps_what_the_reader_read(self, store):
        record = _pass(store)

        fixed = store.set_plate(record.id, OTHER, "Test Admin", _today())

        assert fixed.read_plate == PLATE
        assert fixed.plate == store.pass_by_id(record.id).plate != PLATE

    def test_a_second_fix_still_keeps_the_first_original(self, store):
        record = _pass(store)
        store.set_plate(record.id, OTHER, "Test Admin", _today())

        again = store.set_plate(record.id, "مثم 5555", "Test Admin", _today())

        assert again.read_plate == PLATE

    def test_the_wire_shows_the_original_only_when_it_changed(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        untouched = _pass(vehicles, plate=OTHER, hour=9)
        same = _pass(vehicles, plate=PLATE, hour=10)
        changed = _pass(vehicles, plate="مثم 5555", hour=11)
        client = authed(application)

        client.patch(f"/vehicles/passes/{same.id}/plate", json={"plate": PLATE})
        client.patch(f"/vehicles/passes/{changed.id}/plate",
                     json={"plate": "نيع 3317"})
        rows = {r["id"]: r for r in client.get("/vehicles/passes").json()}

        assert rows[untouched.id]["readPlateDisplay"] is None
        assert rows[same.id]["readPlateDisplay"] is None, "equal says nothing"
        assert rows[changed.id]["readPlateDisplay"], "the reader's own plate"
        assert rows[changed.id]["correctedBy"]

    def test_a_pass_fixed_before_it_is_finished_sends_no_message(self, store):
        sent = []
        store.on_pass = sent.append
        record = _pass(store)
        store.set_plate(record.id, OTHER, "Test Admin", _today())

        store.finish_pass(record.id)

        assert sent == [], "somebody looked at the photograph already"
        row = store._conn.execute(
            "SELECT finished_at FROM vehicle_pass WHERE id = ?",
            (record.id,)).fetchone()
        assert row["finished_at"], "still marked finished"

    def test_an_uncorrected_pass_still_sends(self, store):
        sent = []
        store.on_pass = sent.append
        record = _pass(store)

        store.finish_pass(record.id)
        store.finish_pass(record.id)

        assert [p.id for p in sent] == [record.id], "once, as before"

    def test_the_audit_entries_are_written_before_the_change(self, gate_app):
        _, vehicles, live = gate_app
        record = _pass(vehicles)

        def boom(*_a, **_k):
            raise RuntimeError("disk full")

        vehicles.set_plate = boom
        with pytest.raises(RuntimeError):
            live.correct_plate(record.id, OTHER, "Test Admin")
        assert len(_entries(live, "vehicle.pass.correct")) == 1

        vehicles.delete_pass = boom
        with pytest.raises(RuntimeError):
            live.delete_pass(record.id, "Test Admin")
        assert len(_entries(live, "vehicle.pass.delete")) == 1


# ---------------------------------------------------------------------------
# Gone
# ---------------------------------------------------------------------------

class TestGone:
    def test_an_open_visit_is_closed_by_hand(self, gate_app, authed):
        application, vehicles, _ = gate_app
        entry = _pass(vehicles)
        client = authed(application)

        response = client.post(f"/vehicles/visits/{entry.id}/gone")

        assert response.status_code == 200
        assert response.json() == {"ok": True, "changed": True}
        assert vehicles.inside(since=None) == []
        (visit,) = vehicles.visits()
        assert visit.ended_by == "Test Admin"
        assert visit.inferred is False, "three closings never share a label"
        assert visit.exit_gate is None and visit.exit_pass_id is None
        assert visit.left_at is not None
        # Nothing was invented: still one pass, no exit among them.
        assert [p.direction for p in vehicles.passes()] == ["entry"]

    def test_the_visit_comes_back_on_the_wire_as_ended_by_hand(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        entry = _pass(vehicles)
        client = authed(application)
        client.post(f"/vehicles/visits/{entry.id}/gone")

        (visit,) = client.get("/vehicles/visits").json()

        assert visit["endedBy"] == "Test Admin"
        assert visit["inferred"] is False
        assert visit["exitGate"] is None and visit["exitPassId"] is None

    def test_the_inside_counts_drop(self, gate_app, authed):
        application, vehicles, live = gate_app
        live._pairing_available = lambda: True
        entry = _pass(vehicles)
        client = authed(application)
        assert client.get("/vehicles/summary").json()["inside"] == 1
        since = _day_start()
        assert vehicles.gates(since)[0]["inside"] == 1

        client.post(f"/vehicles/visits/{entry.id}/gone")

        assert client.get("/vehicles/summary").json()["inside"] == 0
        assert vehicles.gates(since)[0]["inside"] == 0
        assert client.get("/vehicles/inside").json() == []

    def test_pressing_it_twice_is_not_an_error(self, gate_app, authed):
        application, vehicles, _ = gate_app
        entry = _pass(vehicles)
        client = authed(application)
        client.post(f"/vehicles/visits/{entry.id}/gone")

        again = client.post(f"/vehicles/visits/{entry.id}/gone")

        assert again.status_code == 200
        assert again.json() == {"ok": True, "changed": False}

    def test_a_visit_that_already_closed_changes_nothing(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        seen_leaving = _pass(vehicles, hour=8)
        _pass(vehicles, hour=9, direction="exit")
        reentered = _pass(vehicles, plate=OTHER, hour=10)
        _pass(vehicles, plate=OTHER, hour=11)
        client = authed(application)

        for entry in (seen_leaving, reentered):
            body = client.post(f"/vehicles/visits/{entry.id}/gone")
            assert body.status_code == 200
            assert body.json()["changed"] is False

        by_plate = {v.plate: v for v in vehicles.visits()}
        assert by_plate[seen_leaving.plate].ended_by is None
        assert by_plate[seen_leaving.plate].exit_gate == 1, "an observed exit"

    def test_an_unknown_pass_and_an_exit_pass_are_404(self, gate_app, authed):
        application, vehicles, _ = gate_app
        _pass(vehicles, hour=8)
        leaving = _pass(vehicles, hour=9, direction="exit")
        client = authed(application)

        assert client.post("/vehicles/visits/nope/gone").status_code == 404
        assert client.post(
            f"/vehicles/visits/{leaving.id}/gone").status_code == 404

    def test_no_vehicle_log_is_503_and_not_a_500(self, bare_live_store,
                                                 user_store, authed):
        app_module.set_store(bare_live_store)
        application = create_app()
        application.state.users = user_store

        response = authed(application).post("/vehicles/visits/x/gone")

        assert response.status_code == 503

    def test_the_demo_store_answers_503_too(self, user_store, authed):
        from vg.api.store import MockStore

        app_module.set_store(MockStore())
        application = create_app()
        application.state.users = user_store

        assert authed(application).post(
            "/vehicles/visits/x/gone").status_code == 503

    def test_deleting_the_entry_pass_takes_the_mark_with_it(
            self, gate_app, authed):
        application, vehicles, _ = gate_app
        entry = _pass(vehicles)
        client = authed(application)
        client.post(f"/vehicles/visits/{entry.id}/gone")
        assert vehicles._conn.execute(
            "SELECT COUNT(*) FROM vehicle_gone").fetchone()[0] == 1

        client.delete(f"/vehicles/passes/{entry.id}")

        assert vehicles._conn.execute(
            "SELECT COUNT(*) FROM vehicle_gone").fetchone()[0] == 0

    def test_the_audit_names_the_plate_and_is_written_before_the_mark(
            self, gate_app):
        _, vehicles, live = gate_app
        entry = _pass(vehicles)

        def boom(*_a, **_k):
            raise RuntimeError("the mark could not be written")

        vehicles.end_visit = boom
        with pytest.raises(RuntimeError):
            live.mark_gone(entry.id, "Test Admin")

        (logged,) = _entries(live, "vehicle.visit.gone")
        assert logged.subject == PLATE
        assert logged.actor == "Test Admin"
        assert "gate 1" in logged.detail
        assert vehicles._conn.execute(
            "SELECT COUNT(*) FROM vehicle_gone").fetchone()[0] == 0

    def test_pressing_gone_twice_logs_one_mark_and_says_nothing_changed(
            self, gate_app):
        _, vehicles, live = gate_app
        entry = _pass(vehicles)

        first = live.mark_gone(entry.id, "Test Admin")
        second = live.mark_gone(entry.id, "Test Admin")

        assert first.changed is True
        assert second.ok is True
        assert second.changed is False
        marks = [e for e in _entries(live, "vehicle.visit.gone")
                 if "marked as gone by hand" in e.detail]
        assert len(marks) == 1

    def test_an_it_account_may_press_it_and_is_named(self, gate_app, authed):
        application, vehicles, _ = gate_app
        entry = _pass(vehicles)

        response = authed(application, role="it").post(
            f"/vehicles/visits/{entry.id}/gone")

        assert response.status_code == 200
        assert vehicles.visits()[0].ended_by == "Test It"

    def test_a_marked_visit_can_be_entered_again(self, gate_app):
        """A car marked gone that comes back is a new visit, not a stale one."""
        _, vehicles, _ = gate_app
        first = _pass(vehicles, hour=8)
        assert vehicles.end_visit(first.id, "Test Admin") is True
        _pass(vehicles, hour=11)

        by_entry = {v.entry_pass_id: v for v in vehicles.visits()}

        assert by_entry[first.id].inside is False
        assert len(vehicles.inside(since=None)) == 1


class TestWhatAnItAccountMayNotChange:
    @pytest.mark.parametrize("method, path, body", [
        ("patch", "/vehicles/passes/{id}/plate", {"plate": OTHER}),
        ("delete", "/vehicles/passes/{id}", None),
        ("post", "/vehicles/register", {"plate": OTHER}),
        ("patch", "/vehicles/register/abc", {"plate": OTHER}),
        ("delete", "/vehicles/register/abc", None),
        ("post", "/vehicles/import", None),
        ("post", "/vehicles/export", None),
    ])
    def test_403(self, gate_app, authed, method, path, body):
        application, vehicles, _ = gate_app
        record = _pass(vehicles)
        client = authed(application, role="it")

        call = getattr(client, method)
        url = path.format(id=record.id)
        response = call(url) if body is None else call(url, json=body)

        assert response.status_code == 403, f"{method.upper()} {url}"
        assert len(vehicles.passes()) == 1

    def test_the_gone_pattern_is_anchored(self):
        from vg.auth import deps

        assert not deps.requires_admin("POST", "/vehicles/visits/abc/gone")
        assert not deps.requires_admin("POST", "/vehicles/visits/abc/gone/")
        assert deps.requires_admin("GET", "/vehicles/visits/abc/gone") is False
        # Siblings and look-alikes stay administrator-only.
        assert deps.requires_admin("POST", "/vehicles/visits/abc/def/gone")
        assert deps.requires_admin("POST", "/vehicles/visits/abc/gone/x")
        assert deps.requires_admin("POST", "/vehicles/visits/abc")


# ---------------------------------------------------------------------------
# the failure counter on every FeatureWorker
# ---------------------------------------------------------------------------

class Failer(FeatureWorker[int]):
    """Raises on its first `failures` frames, then waits for a release, so a
    test can read the counters at exactly that moment."""

    def __init__(self, bus, cameras, *, failures: int, message="boom") -> None:
        super().__init__("failer", bus, cameras, rate_hz=0)
        self.failures = failures
        self.message = message
        self.calls = 0
        self.release = threading.Event()

    def analyse(self, frame) -> int:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(self.message)
        self.release.wait(5)
        return 0


def _feed_until(bus, camera_id, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    sequence = 0
    while time.monotonic() < deadline:
        if predicate():
            return
        bus.publish(Frame(camera_id, np.zeros((4, 4, 3), np.uint8),
                          datetime.now(timezone.utc), sequence))
        sequence += 1
        time.sleep(0.02)
    raise AssertionError("condition never became true")


@pytest.fixture
def run_failer():
    made = []

    def make(**kwargs):
        bus = FrameBus()
        worker = Failer(bus, ["gate-1"], **kwargs)
        worker.start()
        made.append((worker, bus))
        return worker, bus

    yield make
    for worker, bus in made:
        worker.release.set()
        worker.stop()
        bus.close()


class TestFailingCounter:
    def test_five_frames_in_a_row_make_the_camera_failing_with_the_error(
            self, run_failer):
        worker, bus = run_failer(failures=5, message="CUDA out of memory")
        _feed_until(bus, "gate-1", lambda: worker.calls >= 6)

        assert worker.stats["failing_on"] == {"gate-1": "CUDA out of memory"}
        assert worker.stats["died_on"] == [], "alive, not dead"

    def test_four_do_not(self, run_failer):
        worker, bus = run_failer(failures=4)
        _feed_until(bus, "gate-1", lambda: worker.calls >= 5)

        assert worker.stats["failing_on"] == {}

    def test_one_good_frame_clears_it(self, run_failer):
        worker, bus = run_failer(failures=5)
        _feed_until(bus, "gate-1", lambda: worker.calls >= 6)
        assert worker.stats["failing_on"]

        worker.release.set()
        _feed_until(bus, "gate-1",
                    lambda: worker.frames_processed > 0
                    and worker.stats["failing_on"] == {})

    def test_the_error_text_is_kept_to_200_characters(self, run_failer):
        worker, bus = run_failer(failures=5, message="x" * 500)
        _feed_until(bus, "gate-1", lambda: worker.calls >= 6)

        assert len(worker.stats["failing_on"]["gate-1"]) == 200

    def test_a_camera_switched_off_is_no_longer_reported(self, run_failer):
        worker, bus = run_failer(failures=5)
        _feed_until(bus, "gate-1", lambda: worker.calls >= 6)

        worker.unwatch("gate-1")
        worker.release.set()

        assert worker.stats["failing_on"] == {}

    def test_a_worker_that_never_fails_says_so_with_an_empty_dict(
            self, run_failer):
        worker, bus = run_failer(failures=0)
        worker.release.set()
        _feed_until(bus, "gate-1", lambda: worker.frames_processed > 0)

        assert worker.stats["failing_on"] == {}


# ---------------------------------------------------------------------------
# a reader in trouble is never shown as running
# ---------------------------------------------------------------------------

def _gate(camera_id, name, direction="entry", gate=1):
    return SimpleNamespace(id=camera_id, name=name, direction=direction,
                           gate=gate, is_gate=True)


@pytest.fixture
def trouble_store(gate_app):
    """The configured gate camera streaming fine, its plate reader failing."""
    _, vehicles, live = gate_app
    live.registry.worker = lambda camera_id: SimpleNamespace(status="ok")
    camera = next(c for c in live._gate_cameras())
    live.vehicles_worker = _TroubledWorker(
        failing={camera.id: "CUDA out of memory"})
    return live, camera


class TestPlateReaderTrouble:
    def test_the_trouble_names_the_camera_and_says_out_of_memory(
            self, trouble_store):
        live, camera = trouble_store

        trouble = live._plate_trouble()

        assert list(trouble) == [camera.id]
        assert "out of memory" in trouble[camera.id]

    def test_another_error_keeps_its_text(self, gate_app):
        _, _, live = gate_app
        live.vehicles_worker = _TroubledWorker(failing={"c": "bad engine file"})

        assert "bad engine file" in live._plate_trouble()["c"]

    def test_a_dead_thread_is_trouble_too(self, gate_app):
        _, _, live = gate_app
        live.vehicles_worker = _TroubledWorker(died=["c"])

        assert "stopped" in live._plate_trouble()["c"]

    def test_a_worker_that_cannot_report_is_no_trouble_and_no_error(
            self, gate_app):
        _, _, live = gate_app
        live.vehicles_worker = _StoppedWorker()

        assert live._plate_trouble() == {}

    def test_a_failing_camera_is_left_out_of_cameras_reading_and_named(
            self, gate_app):
        _, _, live = gate_app
        live.registry.worker = lambda camera_id: SimpleNamespace(status="ok")
        live._gate_cameras = lambda: [_gate("a", "Gate A"),
                                      _gate("b", "Gate B", "exit", 2)]
        live.vehicles_worker = _TroubledWorker(
            failing={"a": "CUDA out of memory"})

        reading, total, note = live._cameras_reading()

        assert (reading, total) == (1, 2)
        assert "Gate A" in note and "out of memory" in note
        assert "Gate B" not in note

    def test_some_failing_leaves_the_counts_live(self, gate_app):
        _, _, live = gate_app
        live._gate_cameras = lambda: [_gate("a", "Gate A"),
                                      _gate("b", "Gate B", "exit", 2)]
        live.vehicles_worker = _TroubledWorker(failing={"a": "boom"})

        state, reason = live._vehicles_state()

        assert state is S.DataState.LIVE and reason is None

    def test_every_gate_camera_failing_is_unavailable_with_the_reason_and_no_counts(
            self, trouble_store):
        live, camera = trouble_store

        state, reason = live._vehicles_state()
        summary = live.vehicle_summary()

        assert state is S.DataState.UNAVAILABLE
        assert "out of memory" in reason and camera.name in reason
        assert summary.entered is None and summary.inside is None
        assert summary.reason == reason, "dashes, not zeros, and why"

    def test_every_gate_camera_dead_is_unavailable_too(self, gate_app):
        _, _, live = gate_app
        camera = next(iter(live._gate_cameras()))
        live.vehicles_worker = _TroubledWorker(died=[camera.id])

        state, reason = live._vehicles_state()

        assert state is S.DataState.UNAVAILABLE
        assert camera.name in reason

    def test_the_plate_stage_shows_the_failing_row(self, gate_app):
        _, _, live = gate_app
        live._gate_cameras = lambda: [_gate("a", "Gate A"),
                                      _gate("b", "Gate B", "exit", 2)]
        live.vehicles_worker = _TroubledWorker(
            failing={"a": "CUDA out of memory"})

        stage = live._vehicles_stage()

        assert stage.healthy is False
        assert stage.severity is S.Severity.CRITICAL
        assert "Failing on" in stage.detail and "Gate A" in stage.detail

    def test_the_plate_stage_for_a_wholly_failing_reader_gives_the_reason(
            self, trouble_store):
        live, camera = trouble_store

        stage = live._vehicles_stage()

        assert stage.healthy is False
        assert "out of memory" in stage.detail

    def test_system_health_stays_200(self, gate_app, user_store, authed):
        _, _, live = gate_app
        camera = next(iter(live._gate_cameras()))
        live.vehicles_worker = _TroubledWorker(
            failing={camera.id: "CUDA out of memory"})
        app_module.set_store(live)
        application = create_app()
        application.state.users = user_store

        response = authed(application).get("/system/health")

        assert response.status_code == 200
        stage = next(s for s in response.json()["pipeline"]
                     if s["key"] == "vehicles")
        assert stage["healthy"] is False


# ---------------------------------------------------------------------------
# plates are FP32 .pt, whatever the yaml says
# ---------------------------------------------------------------------------

class TestPlatesAreFullPrecision:
    def test_a_yaml_asking_for_half_and_a_plan_still_builds_fp32(
            self, monkeypatch, tmp_path, caplog):
        import dataclasses
        import logging

        from vg import config as vgconfig
        import vg.infer.plates as plates_module

        cfg = vgconfig.load()
        models = {name: dataclasses.replace(m, half=True, accelerate=True)
                  if name in ("plates", "plate_chars") else m
                  for name, m in cfg.models.items()}
        cfg = dataclasses.replace(cfg, models=models)
        seen = {}

        class FakeReader:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                raise FileNotFoundError("no weights in this test")

        monkeypatch.setattr(plates_module, "PlateReader", FakeReader)
        monkeypatch.setattr(app_module, "_database",
                            lambda _cfg: tmp_path / "start.db")
        roster = [c for c in cfg.cameras if c.enabled and c.is_gate]
        assert roster, "engine.yaml has a gate camera"

        with caplog.at_level(logging.WARNING):
            worker, vehicles, reason = app_module._start_vehicles(
                cfg, None, roster)
        vehicles.close_db()

        assert worker is None and "failed to start" in reason
        assert seen["half"] is False
        assert seen["accelerate"] is False
        assert "full precision" in caplog.text

    def test_the_yaml_pins_fp32_too(self):
        from vg import config as vgconfig

        cfg = vgconfig.load()

        assert cfg.models["plates"].half is False
        assert cfg.models["plates"].accelerate is False
