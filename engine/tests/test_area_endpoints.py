"""Drawing and managing zones over the API (spec 025, T017 and T025).

What can lie here: a shape saved that has no honest "inside", a status that
reads "clear" because nothing answered, an audit line written after the thing
it records, and a delete that takes the log with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vg.alerts.store import AlertStore
from vg.api.store import MockStore
from vg.areas import AreaStore
from vg.events.zones import SceneStore
from vg.ingest.store import CameraStore

from test_zones_live import live_store

SQUARE = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
          {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
BOW_TIE = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9},
           {"x": 0.9, "y": 0.1}, {"x": 0.1, "y": 0.9}]
SLIVER = [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}, {"x": 0.9, "y": 0.5005}]


def body(**kw):
    base = {"name": "Server room", "cameraId": "cam-a", "polygon": SQUARE,
            "watched": {"mode": "always"}}
    base.update(kw)
    return base


@pytest.fixture
def parts(tmp_path):
    cameras = CameraStore(tmp_path / "cameras.db")
    cameras.add("cam-a", "Main entrance", "webcam:0", features=("counting",))
    cameras.add("cam-b", "Back door", "webcam:1", features=("counting",))
    scenes = SceneStore(tmp_path / "scenes.db")
    areas = AreaStore(tmp_path / "areas.db")
    alerts = AlertStore(tmp_path / "alerts.db")
    store = live_store(tmp_path, camera_store=cameras, scene_store=scenes,
                       alerts_store=alerts)
    store.area_store = areas
    yield store, areas, scenes, cameras
    areas.close_db()
    scenes.close_db()
    cameras.close()


@pytest.fixture
def app(user_store, parts):
    from vg.api import app as app_module
    from vg.api.app import create_app

    app_module.set_store(parts[0])
    application = create_app()
    application.state.users = user_store
    yield application
    app_module.set_store(MockStore())


@pytest.fixture
def admin(app, authed):
    return authed(app, role="admin")


def audit(store):
    return [(e.action, e.subject) for e in reversed(store.audit(100))]


class TestCreate:
    def test_a_valid_zone_comes_back_in_fractions(self, admin):
        r = admin.post("/zones", json=body())
        assert r.status_code == 201, r.text
        zone = r.json()
        assert zone["name"] == "Server room" and zone["cameraId"] == "cam-a"
        assert zone["polygon"] == SQUARE
        assert zone["enabled"] is True
        assert zone["schedule"] == {"mode": "always", "days": [], "start": None,
                                    "end": None}
        assert zone["watched"]["mode"] == "always"
        assert admin.get("/zones").json()[0]["id"] == zone["id"]

    @pytest.mark.parametrize("patch,word", [
        ({"polygon": SQUARE[:2]}, "3"),
        ({"polygon": [*SQUARE[:3], {"x": 1.4, "y": 0.5}]}, "frame"),
        ({"polygon": BOW_TIE}, "cross"),
        ({"polygon": SLIVER}, "line"),
        ({"name": "  "}, "name"),
        ({"watched": {"mode": "custom", "from": "08:00"}}, "hours"),
        ({"cameraId": "nope"}, "camera"),
    ])
    def test_a_bad_zone_is_refused_with_a_reason(self, admin, parts, patch, word):
        r = admin.post("/zones", json=body(**patch))
        assert r.status_code == 422, r.text
        assert word in r.text.lower()
        assert parts[1].list(kind="zone") == [], "nothing was written"
        assert audit(parts[0]) == [], "nor logged"

    def test_saving_adds_intrusion_to_the_camera_and_audits_it_once(
            self, admin, parts):
        store = parts[0]
        assert admin.post("/zones", json=body()).status_code == 201
        saved = next(c for c in parts[3].all() if c.id == "cam-a")
        assert "intrusion" in saved.features
        actions = [a for a, _ in audit(store)]
        assert actions.count("camera.edit") == 1
        assert actions.count("zone.create") == 1
        assert admin.post("/zones", json=body(name="Second")).status_code == 201
        assert [a for a, _ in audit(store)].count("camera.edit") == 1

    def test_the_audit_line_is_written_before_the_row(self, admin, parts,
                                                      monkeypatch):
        store, areas, _, _ = parts

        def boom(*a, **kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr(areas, "create", boom)
        with pytest.raises(RuntimeError):
            admin.post("/zones", json=body())
        assert ("zone.create", "Server room") in audit(store)

    def test_only_an_admin_may_draw(self, app, authed):
        assert authed(app, role="it").post("/zones", json=body()).status_code == 403


class TestStatus:
    def test_it_is_never_clear_when_nothing_answered(self, admin):
        zone = admin.post("/zones", json=body()).json()
        got = admin.get("/zones").json()[0]
        assert got["id"] == zone["id"]
        assert got["status"] in ("cameraOffline", "detectorStopped")
        assert got["status"] != "clear" and got["inZoneNow"] is None

    def test_a_paused_zone_says_paused(self, admin):
        zone = admin.post("/zones", json=body()).json()
        admin.patch(f"/zones/{zone['id']}", json={"enabled": False})
        assert admin.get("/zones").json()[0]["status"] == "paused"

    def test_a_zone_outside_its_hours_says_so(self, admin, parts):
        now = parts[0].clock.local(datetime.now(timezone.utc))
        start = (now + timedelta(hours=2)).strftime("%H:%M")
        end = (now + timedelta(hours=3)).strftime("%H:%M")
        # A window that wraps midnight is a valid zone window, so no skip.
        admin.post("/zones", json=body(
            watched={"mode": "custom", "from": start, "to": end}))
        assert admin.get("/zones").json()[0]["status"] == "outsideHours"

    def test_with_the_store_absent_it_is_200_with_nothing(self, tmp_path, app,
                                                          authed, parts):
        parts[0].area_store = None
        r = authed(app, role="admin").get("/zones")
        assert r.status_code == 200 and r.json() == []


class TestPatch:
    def make(self, admin):
        return admin.post("/zones", json=body()).json()["id"]

    def test_the_old_client_toggle_still_works(self, admin, parts):
        zid = self.make(admin)
        r = admin.patch(f"/zones/{zid}", json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
        r = admin.patch(f"/zones/{zid}", json={"enabled": True})
        assert r.json()["enabled"] is True

    def test_pausing_says_who_and_when_to_a_second_user(self, admin, app, authed,
                                                        parts):
        zid = self.make(admin)
        admin.patch(f"/zones/{zid}", json={"enabled": False})
        assert ("zone.pause", "Server room") in audit(parts[0])
        seen = authed(app, role="it").get("/zones").json()[0]
        assert seen["pausedBy"] and seen["pausedAt"] is not None
        admin.patch(f"/zones/{zid}", json={"enabled": True})
        again = admin.get("/zones").json()[0]
        assert again["pausedBy"] is None and again["pausedAt"] is None

    def test_other_fields_audit_as_an_edit(self, admin, parts):
        zid = self.make(admin)
        r = admin.patch(f"/zones/{zid}", json={"name": "Server cage",
                                               "alertAfterSeconds": 10})
        assert r.status_code == 200
        assert r.json()["name"] == "Server cage"
        assert r.json()["alertAfterSeconds"] == 10
        assert ("zone.edit", "Server room") in audit(parts[0])

    def test_a_bad_edit_is_refused_and_leaves_the_zone(self, admin):
        zid = self.make(admin)
        r = admin.patch(f"/zones/{zid}", json={"polygon": BOW_TIE})
        assert r.status_code == 422
        assert admin.get("/zones").json()[0]["polygon"] == SQUARE

    def test_an_unknown_zone_is_404(self, admin):
        assert admin.patch("/zones/nope", json={"enabled": False}).status_code == 404


class TestDelete:
    def test_it_is_soft_and_the_log_stays_readable(self, admin, parts):
        store, _, scenes, _ = parts
        zid = admin.post("/zones", json=body()).json()["id"]
        when = datetime.now(timezone.utc) - timedelta(minutes=5)
        scenes.open("cam-a", when, zone_id=zid)
        assert admin.delete(f"/zones/{zid}").status_code == 204
        assert ("zone.delete", "Server room") in audit(store)
        assert admin.get("/zones").json() == []
        kept = admin.get("/zones?includeDeleted=true").json()
        assert [z["id"] for z in kept] == [zid] and kept[0]["deletedAt"]
        rows = admin.get("/breaches?window=today").json()
        assert rows and rows[0]["zoneName"] == "Server room"

    def test_an_unknown_zone_is_404(self, admin):
        assert admin.delete("/zones/nope").status_code == 404

    def test_the_audit_line_comes_before_the_delete(self, admin, parts,
                                                    monkeypatch):
        store, areas, _, _ = parts
        zid = admin.post("/zones", json=body()).json()["id"]

        def boom(*a, **kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr(areas, "soft_delete", boom)
        with pytest.raises(RuntimeError):
            admin.delete(f"/zones/{zid}")
        assert ("zone.delete", "Server room") in audit(store)


class TestBreaches:
    def test_the_zone_filter_and_replaced_entries(self, admin, parts, tmp_path):
        _, _, scenes, _ = parts
        a = admin.post("/zones", json=body(name="A")).json()["id"]
        b = admin.post("/zones", json=body(name="B")).json()["id"]
        now = datetime.now(timezone.utc)
        for i in range(4):                      # four clips: the oldest is replaced
            sid = scenes.open("cam-a", now - timedelta(minutes=30 - i), zone_id=a)
            scenes.start_clip(sid)
            clip = tmp_path / f"{i}.mp4"
            clip.write_bytes(b"x")
            scenes.attach_clip(sid, clip)
        scenes.open("cam-a", now - timedelta(minutes=1), zone_id=b)

        only_a = admin.get(f"/breaches?window=today&zoneId={a}").json()
        assert len(only_a) == 4 and {r["zoneId"] for r in only_a} == {a}
        replaced = [r for r in only_a if r["clipState"] == "replaced"]
        assert len(replaced) == 1 and replaced[0]["clip"] is None
        assert len(admin.get("/breaches?window=today").json()) == 5

    def test_entries_today_equals_the_row_count(self, admin, parts):
        _, _, scenes, _ = parts
        zid = admin.post("/zones", json=body()).json()["id"]
        now = datetime.now(timezone.utc)
        for i in range(3):
            scenes.open("cam-a", now - timedelta(seconds=30 * (i + 1)), zone_id=zid)
        assert admin.get("/zones").json()[0]["breachesToday"] == 3
        assert len(admin.get(f"/breaches?window=today&zoneId={zid}").json()) == 3


class TestHomeItems:
    def items(self, store):
        return [i for i in store.attention() if i.kind == "intrusion"]

    def test_a_zone_with_in_app_off_shows_nothing(self, admin, parts):
        store, _, scenes, _ = parts
        zid = admin.post("/zones", json=body(notifyInApp=False)).json()["id"]
        scenes.open("cam-a", datetime.now(timezone.utc), zone_id=zid)
        assert self.items(store) == []

    def test_delayed_alert_shows_only_once_it_was_raised(self, admin, parts):
        store, _, scenes, _ = parts
        zid = admin.post("/zones", json=body(alertAfterSeconds=10)).json()["id"]
        now = datetime.now(timezone.utc) - timedelta(minutes=2)
        sid = scenes.open("cam-a", now, zone_id=zid, alert_now=False)
        assert self.items(store) == []
        scenes.alert(sid)
        assert len(self.items(store)) == 1

    def test_no_delay_shows_every_scene_continuations_too(self, admin, parts):
        store, _, scenes, _ = parts
        zid = admin.post("/zones", json=body()).json()["id"]
        now = datetime.now(timezone.utc) - timedelta(minutes=2)
        scenes.open("cam-a", now, zone_id=zid)
        scenes.open("cam-a", now + timedelta(seconds=30), continues=True,
                    zone_id=zid)
        assert len(self.items(store)) == 2

    def test_a_zones_notify_choice_reaches_the_alert_channels(self, admin, parts):
        store = parts[0]
        zid = admin.post("/zones", json=body(notifyEmail=True)).json()["id"]
        assert store.zone_channels(zid) == frozenset({"email"})
        other = admin.post("/zones", json=body(name="B", notifyEmail=False)).json()["id"]
        assert store.zone_channels(other) == frozenset()
        assert store.zone_channels("nope") is None


class TestEndReason:
    def test_a_cut_entry_says_it_was_cut_and_a_running_one_says_nothing(
            self, admin, parts):
        _, _, scenes, _ = parts
        zid = admin.post("/zones", json=body()).json()["id"]
        now = datetime.now(timezone.utc)
        cut = scenes.open("cam-a", now - timedelta(minutes=10), zone_id=zid)
        scenes.close(cut, now - timedelta(minutes=8), "limit")
        scenes.open("cam-a", now - timedelta(minutes=1), zone_id=zid)
        rows = {r["endReason"] for r in admin.get("/breaches?window=today").json()}
        assert rows == {"limit", None}
