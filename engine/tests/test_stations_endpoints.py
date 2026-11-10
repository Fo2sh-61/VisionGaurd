"""Work stations over the API (spec 025, T039).

What can lie here: a station that reads "on" when nothing is looking, an
audit line written after the thing it records, a name shown to a role that
must not see one, and a fixture on the live path.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from vg import config as vgconfig
from vg.alerts.store import AlertStore
from vg.api import app as app_module
from vg.api.live import LiveStore
from vg.api.store import MockStore
from vg.areas import AreaStore
from vg.events.stations import StationStore
from vg.features.stations import StationReading, StationsResult
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry
from vg.ingest.store import CameraStore
from vg.config import CameraConfig

SQUARE = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
          {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
MODEL = "sface-2021dec"


def body(**kw):
    base = {"name": "Lab bench 2", "cameraId": "cam-a", "polygon": SQUARE,
            "watched": {"mode": "working"}, "limitMinutes": 10}
    base.update(kw)
    return base


def audit(store):
    return [(e.action, e.subject) for e in reversed(store.audit(100))]


@pytest.fixture
def parts():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    gallery = FaceGallery(root / "g.db", model=MODEL, threshold=0.363)
    gallery.add_person("p-layla", "Layla Ahmed")
    gallery.add_embedding("p-layla", np.ones(128, dtype="float32") / 11.3, MODEL)
    cameras = CameraStore(root / "cameras.db")
    cameras.add("cam-a", "Lab camera", "webcam:0", features=("counting",))
    areas = AreaStore(root / "areas.db")
    log = StationStore(root / "stations.db")
    alerts = AlertStore(root / "alerts.db")
    registry = CameraRegistry([CameraConfig.parse(
        {"id": "cam-a", "name": "Lab camera", "source": "webcam:0",
         "features": ["counting"]}, "cam-a")])
    store = LiveStore(config=vgconfig.load(), registry=registry, gallery=gallery,
                      cameras=cameras, alerts_store=alerts, area_store=areas,
                      station_store=log)
    yield store, areas, log, cameras, gallery
    for closer in (areas.close_db, log.close_db, cameras.close, gallery.close):
        closer()
    tmp.cleanup()


@pytest.fixture
def app(user_store, parts):
    from vg.api.app import create_app

    app_module.set_store(parts[0])
    application = create_app()
    application.state.users = user_store
    yield application
    app_module.set_store(MockStore())


@pytest.fixture
def admin(app, authed):
    return authed(app, role="admin")


@pytest.fixture
def it(app, authed):
    return authed(app, role="it")


class TestRead:
    def test_an_empty_site_is_200_and_empty_not_demo(self, it):
        r = it.get("/stations")
        assert r.status_code == 200 and r.json() == []

    def test_every_row_has_a_state_even_with_the_worker_absent(self, admin, parts):
        admin.post("/stations", json=body(watched={"mode": "custom",
                                                   "from": "00:00", "to": "23:59"}))
        # A camera that is delivering, nothing watching it.
        real = parts[0].registry.worker("cam-a")
        parts[0].registry.workers["cam-a"] = SimpleNamespace(
            status="ok", config=real.config, last_frame=lambda: None)
        row = admin.get("/stations").json()[0]
        assert row["state"] == "unknown" and row["unknownReason"] == "notRunning"

    def test_a_dark_camera_says_so(self, admin):
        admin.post("/stations", json=body(watched={"mode": "custom",
                                                   "from": "00:00", "to": "23:59"}))
        row = admin.get("/stations").json()[0]
        assert row["state"] == "unknown" and row["unknownReason"] == "cameraOffline"

    def test_a_fresh_worker_reading_is_what_the_state_says(self, admin, parts):
        store = parts[0]
        made = admin.post("/stations", json=body(
            watched={"mode": "custom", "from": "00:00", "to": "23:59"})).json()
        real = store.registry.worker("cam-a")
        store.registry.workers["cam-a"] = SimpleNamespace(
            status="ok", config=real.config, last_frame=lambda: None)
        now = datetime.now(timezone.utc)
        worker = SimpleNamespace(
            cameras=["cam-a"],
            payload=lambda cam: StationsResult(restricted=True, stations=(
                StationReading(station_id=made["id"], state="absent",
                               since=now - timedelta(minutes=12)),)),
        )
        store.stations_worker = worker
        row = admin.get("/stations").json()[0]
        assert row["state"] == "absent" and row["stateSince"]
        assert row["unknownReason"] is None

    def test_outside_the_hours_it_is_not_started_or_closed(self, admin, parts):
        now = parts[0].clock.local(datetime.now(timezone.utc))
        ahead = (now + timedelta(hours=2), now + timedelta(hours=3))
        if ahead[0].date() == ahead[1].date() == now.date():
            window, expect, opens = ahead, "notStarted", ahead[0].strftime("%H:%M")
        else:                                  # near midnight: use the past
            window = (now - timedelta(hours=3), now - timedelta(hours=2))
            expect, opens = "closed", None
        admin.post("/stations", json=body(watched={
            "mode": "custom", "from": window[0].strftime("%H:%M"),
            "to": window[1].strftime("%H:%M")}))
        row = admin.get("/stations").json()[0]
        assert row["state"] == expect and row["opensAt"] == opens

    def test_it_sees_the_assignee_id_but_never_the_name(self, admin, it):
        admin.post("/stations", json=body(assigneeId="p-layla"))
        seen = it.get("/stations").json()[0]
        assert seen["assigneeId"] == "p-layla" and seen["assigneeName"] is None
        as_admin = admin.get("/stations").json()[0]
        assert as_admin["assigneeName"] == "Layla Ahmed"

    def test_an_assignee_gone_from_the_directory_is_reported(self, admin, parts):
        admin.post("/stations", json=body(assigneeId="p-layla"))
        parts[4].remove_person("p-layla")
        row = admin.get("/stations").json()[0]
        assert row["assigneeMissing"] is True and row["assigneeName"] is None

    def test_detail_404s_for_an_unknown_id_and_422s_a_bad_day(self, admin):
        assert admin.get("/stations/nope").status_code == 404
        made = admin.post("/stations", json=body()).json()
        assert admin.get(f"/stations/{made['id']}?day=yesterday").status_code == 422

    def test_face_reach_is_not_read_as_an_id(self, it):
        r = it.get("/stations/face-reach?cameraId=cam-a")
        assert r.status_code == 200
        assert r.json() == {"facePx": None, "needed": 80}


class TestWrite:
    def test_create_audits_first_and_adds_the_feature(self, admin, parts):
        store, areas, _, cameras, _ = parts
        r = admin.post("/stations", json=body())
        assert r.status_code == 201, r.text
        assert r.json()["polygon"] == SQUARE and r.json()["limitMinutes"] == 10
        saved = next(c for c in cameras.all() if c.id == "cam-a")
        assert "stations" in saved.features
        actions = audit(store)
        assert ("station.create", "Lab bench 2") in actions
        assert [a for a, _ in actions].count("camera.edit") == 1

    def test_the_audit_line_is_written_before_the_row(self, admin, parts,
                                                      monkeypatch):
        store, areas, *_ = parts

        def boom(*a, **kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr(areas, "create", boom)
        with pytest.raises(RuntimeError):
            admin.post("/stations", json=body())
        assert ("station.create", "Lab bench 2") in audit(store)

    @pytest.mark.parametrize("patch,word", [
        ({"limitMinutes": 0}, "minutes"),
        ({"limitMinutes": 481}, "minutes"),
        ({"watched": {"mode": "custom", "from": "17:00", "to": "09:00"}}, "before"),
        ({"assigneeId": "nobody"}, "directory"),
        ({"polygon": SQUARE[:2]}, "3"),
        ({"name": ""}, "name"),
        ({"cameraId": "nope"}, "camera"),
    ])
    def test_a_bad_station_is_refused_with_a_reason(self, admin, parts, patch, word):
        r = admin.post("/stations", json=body(**patch))
        assert r.status_code == 422, r.text
        assert word in r.text.lower()
        assert parts[1].list(kind="station") == [] and audit(parts[0]) == []

    def test_only_an_admin_draws_edits_or_removes(self, it, admin):
        made = admin.post("/stations", json=body()).json()
        assert it.post("/stations", json=body()).status_code == 403
        assert it.patch(f"/stations/{made['id']}", json={"name": "x"}).status_code == 403
        assert it.delete(f"/stations/{made['id']}").status_code == 403

    def test_patch_can_clear_the_assignee_and_audits_an_edit(self, admin, parts):
        made = admin.post("/stations", json=body(assigneeId="p-layla")).json()
        r = admin.patch(f"/stations/{made['id']}", json={"assigneeId": None})
        assert r.status_code == 200 and r.json()["assigneeId"] is None
        assert ("station.edit", "Lab bench 2") in audit(parts[0])

    def test_patch_unknown_is_404(self, admin):
        assert admin.patch("/stations/nope", json={"name": "x"}).status_code == 404

    def test_delete_is_soft_and_the_events_stay(self, admin, parts):
        made = admin.post("/stations", json=body()).json()
        parts[2].add_event(made["id"], datetime.now(timezone.utc), "at_station")
        assert admin.delete(f"/stations/{made['id']}").status_code == 204
        assert ("station.delete", "Lab bench 2") in audit(parts[0])
        assert admin.get("/stations").json() == []
        kept = admin.get("/stations?includeDeleted=true").json()
        assert kept[0]["deletedAt"]
        detail = admin.get(f"/stations/{made['id']}").json()
        assert detail["deletedAt"] and len(detail["events"]) == 1
        assert admin.delete(f"/stations/{made['id']}").status_code == 404


class TestAcknowledge:
    def alert(self, admin, parts):
        made = admin.post("/stations", json=body()).json()
        now = datetime.now(timezone.utc)
        parts[2].absence_alert(made["id"], "cam-a", now, now - timedelta(minutes=12),
                               "Lab bench 2", 10)
        return made["id"]

    def test_admin_and_it_may_acknowledge_and_state_is_unchanged(
            self, admin, it, parts):
        sid = self.alert(admin, parts)
        assert admin.get("/stations").json()[0]["unacknowledgedAlert"]
        r = it.post(f"/stations/{sid}/acknowledge")
        assert r.status_code == 200, r.text
        assert r.json()["unacknowledgedAlert"] is None
        kinds = [e["kind"] for e in r.json()["events"]]
        assert "absenceAlert" in kinds and "acknowledged" in kinds
        assert r.json()["events"][0]["byWho"] == "Test It"
        assert r.json()["assigneeName"] is None

    def test_the_audit_line_comes_before_the_row(self, admin, parts, monkeypatch):
        sid = self.alert(admin, parts)

        def boom(*a, **kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr(parts[2], "acknowledge", boom)
        with pytest.raises(RuntimeError):
            admin.post(f"/stations/{sid}/acknowledge")
        assert ("station.ack", "Lab bench 2") in audit(parts[0])

    def test_nothing_to_acknowledge_is_404(self, admin):
        made = admin.post("/stations", json=body()).json()
        assert admin.post(f"/stations/{made['id']}/acknowledge").status_code == 404
        assert admin.post("/stations/nope/acknowledge").status_code == 404

    def test_a_second_acknowledge_is_404(self, admin, parts):
        sid = self.alert(admin, parts)
        assert admin.post(f"/stations/{sid}/acknowledge").status_code == 200
        assert admin.post(f"/stations/{sid}/acknowledge").status_code == 404


class TestHome:
    def test_an_unacknowledged_alert_is_an_item_and_acking_it_answers_the_station(
            self, admin, parts):
        store = parts[0]
        made = admin.post("/stations", json=body()).json()
        now = datetime.now(timezone.utc)
        event = parts[2].absence_alert(made["id"], "cam-a", now,
                                       now - timedelta(minutes=12), "Lab bench 2", 10)
        items = [i for i in store.attention() if i.kind == "station"]
        assert [i.id for i in items] == [f"station:{event}"]
        assert items[0].target == "stations" and items[0].target_id == made["id"]
        done = admin.post(f"/attention/station:{event}/ack")
        assert done.status_code == 200, done.text
        assert [i for i in store.attention() if i.kind == "station"] == []
        assert parts[2].open_alerts(made["id"]) == []

    def test_in_app_off_hides_the_item(self, admin, parts):
        store = parts[0]
        made = admin.post("/stations", json=body(notifyInApp=False)).json()
        now = datetime.now(timezone.utc)
        parts[2].absence_alert(made["id"], "cam-a", now,
                               now - timedelta(minutes=12), "Lab bench 2", 10)
        assert [i for i in store.attention() if i.kind == "station"] == []


class TestReviewFixes:
    """Fixes from the spec 025 review."""

    def station_alert(self, admin, parts, **kw):
        made = admin.post("/stations", json=body(**kw)).json()
        now = datetime.now(timezone.utc)
        parts[2].absence_alert(made["id"], "cam-a", now,
                               now - timedelta(minutes=12), "Lab bench 2", 10)
        return made["id"]

    def test_the_stations_own_in_app_tick_beats_the_settings_row_off(
            self, admin, parts):
        store = parts[0]
        store.alerts_store.update_rule("station", in_app=False)
        self.station_alert(admin, parts, notifyInApp=True)
        assert [i for i in store.attention() if i.kind == "station"], \
            "the station's own tick decides, not the default row"

    def test_the_stations_own_in_app_off_beats_the_settings_row_on(
            self, admin, parts):
        store = parts[0]
        store.alerts_store.update_rule("station", in_app=True)
        self.station_alert(admin, parts, notifyInApp=False)
        assert [i for i in store.attention() if i.kind == "station"] == []

    def _live(self, admin, parts, reading):
        store = parts[0]
        made = admin.post("/stations", json=body(
            watched={"mode": "custom", "from": "00:00", "to": "23:59"})).json()
        real = store.registry.worker("cam-a")
        store.registry.workers["cam-a"] = SimpleNamespace(
            status="ok", config=real.config, last_frame=lambda: None)
        return store, made

    def test_present_not_recognised_reaches_the_wire_and_is_never_stored(
            self, admin, parts):
        store, made = self._live(admin, parts, None)
        now = datetime.now(timezone.utc)
        store.stations_worker = SimpleNamespace(
            cameras=["cam-a"],
            payload=lambda cam: StationsResult(restricted=True, stations=(
                StationReading(station_id=made["id"], state="away",
                               since=now - timedelta(minutes=1), people=1,
                               unrecognised=True),)))
        row = admin.get("/stations").json()[0]
        assert row["presentNotRecognised"] is True
        start, end = now - timedelta(days=1), now + timedelta(days=1)
        assert parts[2].events(made["id"], start, end) == []
        assert parts[2].segments(made["id"], start, end) == []

    def test_detector_stopped_has_three_branches_and_each_says_so(
            self, admin, parts):
        store, made = self._live(admin, parts, None)
        # 1. a worker that is not watching this camera
        store.stations_worker = SimpleNamespace(cameras=[], payload=lambda c: None)
        row = admin.get("/stations").json()[0]
        assert row["state"] == "unknown" and row["unknownReason"] == "detectorStopped"
        # 2. watching it, but no payload yet
        store.stations_worker = SimpleNamespace(
            cameras=["cam-a"], payload=lambda c: None)
        row = admin.get("/stations").json()[0]
        assert row["state"] == "unknown" and row["unknownReason"] == "detectorStopped"
        # 3. a payload that has no reading for this station
        store.stations_worker = SimpleNamespace(
            cameras=["cam-a"],
            payload=lambda c: StationsResult(restricted=True, stations=()))
        row = admin.get("/stations").json()[0]
        assert row["state"] == "unknown" and row["unknownReason"] == "detectorStopped"
        assert parts[2].open_alerts(made["id"]) == [], "no alert while unknown"

    def test_figures_are_null_not_zero_when_the_log_is_missing(
            self, admin, parts):
        made = admin.post("/stations", json=body()).json()
        parts[0].station_store = None
        row = next(r for r in admin.get("/stations").json()
                   if r["id"] == made["id"])
        assert row["workSeconds"] is None
        assert row["absentSeconds"] is None
        assert row["notWatchedSeconds"] is None
        assert row["rate"] is None

    def test_figures_are_numbers_when_the_log_is_there(self, admin):
        admin.post("/stations", json=body())
        row = admin.get("/stations").json()[0]
        assert row["workSeconds"] == 0.0 and row["absentSeconds"] == 0.0

    def test_detail_is_503_not_404_when_the_area_table_failed(
            self, admin, parts):
        made = admin.post("/stations", json=body()).json()
        parts[0].area_store = None
        r = admin.get(f"/stations/{made['id']}")
        assert r.status_code == 503, r.text


class TestCapabilityAndHealth:
    def state(self, store):
        cap = next(c for c in store.capabilities() if c.key == "stations")
        return cap.state.value, cap.reason

    def test_three_different_reasons(self, parts):
        store = parts[0]
        state, reason = self.state(store)
        assert state == "unavailable" and "Person detection" in reason
        store.stations_error = "weights missing"
        assert "failed to start (weights missing)" in self.state(store)[1]
        store.stations_error = None
        store.people_worker = object()
        assert "not running" in self.state(store)[1]
        store.stations_worker = SimpleNamespace()
        assert self.state(store) == ("live", None)
        store.station_store = None
        assert "log is not available" in self.state(store)[1]

    def test_the_health_stage_is_there_and_says_why(self, parts):
        stages = {s.key: s for s in parts[0].health().pipeline}
        assert "stations" in stages and stages["stations"].healthy is False
        assert stages["stations"].detail
