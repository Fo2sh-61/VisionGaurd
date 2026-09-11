"""Home's "Needs your attention", real (spec 013, user story 4).

The feed used to be always empty on the live engine: `attention()` returned
`[]` and the capability said alerts were not built. Now it is derived on every
read from the stores that already hold the items - pending knife entries,
today's zone scenes, today's gate alerts, cameras dark past the window - minus
what somebody acknowledged. There is no second copy that could drift from the
Weapons, Zones or Vehicles pages.

The rules held here:

- each kind is shown only when its rule has In-app on, and the gate's reason
  switches decide which gate alerts count;
- acknowledging is audited first, names the session account, deletes nothing,
  and is the one write here that is not an administrator's;
- the capability is LIVE with no reason while the alert database is open;
- the live path never borrows the demo feed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vg.alerts.store import AlertStore
from vg.api import schemas as S
from vg.api.live import LiveStore
from vg.api.store import MockStore
from vg.clock import FixedClock
from vg.events.vehicles import VehicleStore
from vg.events.weapons import WeaponSceneStore
from vg.events.zones import SceneStore


class StoppedClock(FixedClock):
    """Cairo's offset, and one instant that stays "today" for the whole test.

    The feed reads the site's day afresh on every call. With the real clock a
    run that straddles local midnight would build the items on one day and
    look for them on the next, and fail with nothing wrong.
    """

    def __init__(self, at: datetime):
        super().__init__(180, "Africa/Cairo")
        self.at = at

    def today(self, when: datetime | None = None) -> str:
        return self.local_date(when or self.at)


class DarkCamera:
    """A camera worker as the feed sees it: a status and a last frame."""

    def __init__(self, status, last_frame_at, config):
        self.status = status
        self.config = config
        self.source = type("Source", (), {})()
        self.source.health = type("Health", (), {"last_frame_at": last_frame_at})()


def live_store(tmp_path, **kw) -> LiveStore:
    from vg import config as vgconfig
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    registry = CameraRegistry([
        CameraConfig.parse({"id": "cam-a", "name": "Yard camera", "source": "webcam:0",
                            "features": ["counting"]}, "cam-a"),
        CameraConfig.parse({"id": "cam-b", "name": "Back door", "source": "webcam:1",
                            "features": ["counting"]}, "cam-b"),
    ])
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


@pytest.fixture
def feed(tmp_path):
    """Every kind of open item, plus the ones that must NOT appear."""
    alerts = AlertStore(tmp_path / "alerts.db")
    weapons = WeaponSceneStore(tmp_path / "weapons.db")
    scenes = SceneStore(tmp_path / "zones.db")
    vehicles = VehicleStore(tmp_path / "vehicles.db")
    store = live_store(tmp_path, weapon_scenes=weapons, scenes=scenes,
                       vehicle_store=vehicles, alerts_store=alerts)
    now = datetime.now(timezone.utc)
    store.clock = StoppedClock(now)
    today = store._start_of_day()

    pending = weapons.open("cam-a", today + timedelta(seconds=1), 0.76, "knifebest")
    reviewed = weapons.open("cam-a", today + timedelta(seconds=2), 0.8, "knifebest")
    weapons.review(reviewed, "dismissed", "Guard A", now)

    breach = scenes.open("cam-b", today + timedelta(seconds=3))
    scenes.close(breach, today + timedelta(seconds=13), "gone")       # ended: still listed
    scenes.open("cam-b", today - timedelta(hours=1))                  # yesterday: not

    vehicles.add(plate="رقص 9058", owner_name="Former contractor", category="blacklist")
    site_today = date.fromisoformat(store.clock.today())
    blacklisted = vehicles.record_pass(
        at=today + timedelta(seconds=4), camera_id="cam-a", gate=1, direction="entry",
        plate="رقص 9058", confidence=0.9, votes=3, needs_review=False, today=site_today)
    unregistered = vehicles.record_pass(
        at=today + timedelta(seconds=5), camera_id="cam-a", gate=1, direction="entry",
        plate="بجد 1234", confidence=0.9, votes=3, needs_review=False, today=site_today)

    dark_since = now - timedelta(minutes=6)
    real = store.registry.workers
    store.registry.workers = {"cam-a": DarkCamera("ok", now, real["cam-a"].config),
                              "cam-b": DarkCamera("down", dark_since, real["cam-b"].config)}

    ids = {
        "weapon": f"weapon:{pending}",
        "intrusion": f"intrusion:{breach}",
        "blacklist": f"vehicles:{blacklisted.id}",
        "unknown": f"vehicles:{unregistered.id}",
    }
    yield store, alerts, ids
    for closable in (alerts, weapons, scenes, vehicles):
        closable.close_db()


class TestAttentionFeed:
    def test_every_open_item_and_nothing_else(self, feed):
        store, _, ids = feed
        items = {item.id: item for item in store.attention()}
        camera_ids = [i for i in items if i.startswith("camera:cam-b:")]
        assert set(items) == {ids["weapon"], ids["intrusion"], ids["blacklist"],
                              ids["unknown"], *camera_ids}
        assert len(camera_ids) == 1, "one dark camera, one item"

    def test_each_item_says_what_happened_as_a_code_the_console_words(self, feed):
        store, _, ids = feed
        items = {item.id: item for item in store.attention()}
        knife = items[ids["weapon"]]
        assert (knife.kind, knife.severity, knife.title) == ("weapon", S.Severity.CRITICAL,
                                                             "Yard camera")
        assert knife.note.code == "attention.weapon" and knife.note.args["confidence"] == 76
        assert items[ids["intrusion"]].note.code == "attention.intrusion"
        assert items[ids["blacklist"]].severity == S.Severity.CRITICAL
        assert items[ids["blacklist"]].note.code == "attention.vehicles.blacklist"
        assert items[ids["unknown"]].severity == S.Severity.WARN
        assert items[ids["unknown"]].note.code == "attention.vehicles.unknown"
        (camera,) = [i for i in items.values() if i.kind == "camera"]
        assert camera.title == "Back door" and camera.note.code == "attention.camera"
        assert camera.note.args["minutes"] >= 6

    def test_nothing_names_a_person(self, feed):
        store, _, _ = feed
        for item in store.attention():
            assert "Former contractor" not in item.model_dump_json()

    def test_newest_first(self, feed):
        store, _, _ = feed
        times = [item.at.utc for item in store.attention()]
        assert times == sorted(times, reverse=True)

    def test_in_app_off_takes_a_kind_off_home(self, feed):
        store, alerts, ids = feed
        alerts.update_rule("weapon", in_app=False)
        assert ids["weapon"] not in {i.id for i in store.attention()}

    def test_the_gate_switches_decide_which_gate_alerts_show(self, feed):
        store, alerts, ids = feed
        alerts.update_rule("vehicles", vehicle_unknown=False)
        shown = {i.id for i in store.attention()}
        assert ids["unknown"] not in shown and ids["blacklist"] in shown

    def test_the_report_never_appears_on_home(self, feed):
        store, _, _ = feed
        assert "attendance" not in {i.kind for i in store.attention()}


class TestAcknowledge:
    def test_acknowledging_audits_first_and_the_item_goes(self, feed):
        store, _, ids = feed
        item = store.acknowledge(ids["weapon"], "Guard A")
        assert item is not None and item.acknowledged is True
        entry = store.audit(1)[0]
        assert (entry.action, entry.actor, entry.subject) == (
            "attention.ack", "Guard A", ids["weapon"])
        assert ids["weapon"] not in {i.id for i in store.attention()}

    def test_the_audit_survives_a_failing_write(self, feed, monkeypatch):
        store, alerts, ids = feed

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")
        monkeypatch.setattr(alerts, "ack", boom)
        with pytest.raises(RuntimeError):
            store.acknowledge(ids["intrusion"], "Guard A")
        assert store.audit(1)[0].action == "attention.ack"

    def test_acknowledging_deletes_nothing(self, feed):
        store, _, ids = feed
        store.acknowledge(ids["weapon"], "Guard A")
        pending = [s.id for s in store.weapon_scenes.pending()]
        assert ids["weapon"].split(":", 1)[1] in pending, "the entry still awaits review"

    def test_a_second_acknowledgement_is_not_found(self, feed):
        store, _, ids = feed
        assert store.acknowledge(ids["weapon"], "Guard A") is not None
        assert store.acknowledge(ids["weapon"], "Guard B") is None

    def test_a_non_administrator_acknowledges_under_their_own_name(self, feed, authed):
        from vg.api import app as app_module

        store, _, ids = feed
        app_module.set_store(store)
        try:
            client = authed(app_module.create_app(), "it")
            response = client.post(f"/attention/{ids['intrusion']}/ack",
                                   json={"actor": "Somebody else"})
            assert response.status_code == 200, response.text
            assert response.json()["acknowledged"] is True
            entry = store.audit(1)[0]
            assert (entry.action, entry.actor) == ("attention.ack", "Test It")
            assert client.post(f"/attention/{ids['intrusion']}/ack").status_code == 404
        finally:
            app_module.set_store(MockStore())


class TestEachItemOpensTheThingItself:
    """The console's alert bell and Home open an item AT the item: the link is
    `/weapons?entry=<target_id>` and the page looks for that id among the rows
    it lists (useAttention.ts `attentionLink`). So `target_id` must be the id
    the page's own list uses. If the two drift apart, every link lands on a
    "no longer in the list" note instead of on the thing."""

    @staticmethod
    def _items(store):
        return {item.id: item for item in store.attention()}

    def test_the_knife_entry_is_a_row_on_the_weapons_page(self, feed):
        store, _, ids = feed
        knife = self._items(store)[ids["weapon"]]
        assert knife.target == "weapons"
        assert knife.target_id in {d.id for d in store.weapons(None)}

    def test_the_zone_scene_is_a_row_on_the_zones_page(self, feed):
        store, _, ids = feed
        scene = self._items(store)[ids["intrusion"]]
        assert scene.target == "intrusion"
        assert scene.target_id in {b.id for b in store.breaches(since_days=1)}

    def test_the_gate_alert_is_one_the_gate_page_is_waiting_on(self, feed):
        store, _, ids = feed
        waiting = {a.pass_id for a in store.vehicle_alerts()}
        for key in ("blacklist", "unknown"):
            gate = self._items(store)[ids[key]]
            assert gate.target == "vehicles"
            assert gate.target_id in waiting

    def test_the_dark_camera_is_a_camera_in_the_roster(self, feed):
        store, _, _ = feed
        (camera,) = [i for i in store.attention() if i.kind == "camera"]
        assert camera.target == "system"
        assert camera.target_id in {c.id for c in store.registry.configs()}


class TestHonestState:
    def test_the_capability_is_live_and_explains_nothing(self, feed):
        store, _, _ = feed
        (cap,) = [c for c in store.capabilities() if c.key == "attention"]
        assert (cap.state, cap.reason) == (S.DataState.LIVE, None)

    def test_no_alert_database_is_unavailable_and_empty(self, tmp_path):
        store = live_store(tmp_path)
        (cap,) = [c for c in store.capabilities() if c.key == "attention"]
        assert cap.state == S.DataState.UNAVAILABLE and cap.reason
        assert store.attention() == []

    @pytest.mark.parametrize("name", ["attention", "acknowledge"])
    def test_live_answers_for_itself(self, name):
        assert getattr(LiveStore, name) is not getattr(MockStore, name)
