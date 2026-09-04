"""Camera setup: what the console is told about a recorder, and what it saves.

The bugs this file exists to keep dead:

- `LiveStore` never overrode `connect_dvr`, so the live engine answered from
  `MockStore`: sixteen channels, "ok", 704x576, whatever the recorder was and
  whether or not it answered at all.
- `LiveStore.scan` returned `[]`, which the console rendered as "0 devices
  found" - so "we cannot look" and "your network is empty" read identically.
- The console's Add buttons for a discovered device and for recorder channels
  called nothing. A row appeared, the page was refreshed, and it was gone.
- Nothing under `/sources` was audited.

Every test here is one of those, or one of the invariants that keeps them
dead: a channel is only ever offered when a frame arrived from it, a password
never leaves the engine, and the audit entry precedes the write.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vg.api import schemas as S
from vg.api.live import LiveStore
from vg.api.store import MockStore

#: A password that appears nowhere else in the repository, so a single grep
#: over a response proves redaction rather than merely suggesting it.
SENTINEL = "SENTINELPW"


def live_store(tmp_path, registry=None, **kw) -> LiveStore:
    """A `LiveStore` over a roster and a throwaway database.

    Copied from `test_lost_bag.py::live_store`. Pass a registry to control
    what is running; without one the cameras are real `CameraWorker`s that
    were never started, so they read **offline** - which quietly turns an
    endpoint assertion into one that passes for the wrong reason.
    """
    from vg import config as vgconfig
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry

    if registry is None:
        registry = CameraRegistry([
            CameraConfig.parse(
                {"id": "cam-a", "name": "Main entrance", "source": "webcam:0",
                 "features": ["counting"]}, "cam-a"),
        ])
    config = vgconfig.load()
    object.__setattr__(config.storage, "clips_dir", Path(tmp_path) / "clips")
    return LiveStore(config, registry, **kw)


def client_for(store, authed, role: str = "admin") -> TestClient:
    """Mount a store and sign in. Caller restores the mock in a `finally`."""
    from vg.api import app as app_module

    app_module.set_store(store)
    return authed(app_module.create_app(), role)


# ---------------------------------------------------------------------------
# audit — the entry precedes the write, always
# ---------------------------------------------------------------------------

class TestCameraChangesAreAudited:
    """Nothing under `/sources` used to be audited at all.

    A camera appearing or disappearing changes what the whole system watches,
    and there was no record of who did it. The constitution wants the entry
    written BEFORE the thing it records, so a write that then fails still
    leaves the attempt visible.
    """

    def _client(self, tmp_path, authed):
        from vg.ingest.store import CameraStore

        store = live_store(tmp_path, cameras=CameraStore(tmp_path / "roster.db"))
        return store, client_for(store, authed)

    def test_adding_a_camera_writes_an_audit_entry(self, tmp_path, authed):
        from vg.api import app as app_module

        store, client = self._client(tmp_path, authed)
        try:
            client.post("/sources", json={
                "name": "Side gate", "source": "webcam:9", "features": ["counting"]})

            actions = [e.action for e in store.audit(50)]
            assert "camera.add" in actions
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_removing_a_camera_writes_an_audit_entry(self, tmp_path, authed):
        from vg.api import app as app_module

        store, client = self._client(tmp_path, authed)
        try:
            added = client.post("/sources", json={
                "name": "Side gate", "source": "webcam:9",
                "features": ["counting"]}).json()
            client.delete(f"/sources/{added['id']}")

            actions = [e.action for e in store.audit(50)]
            assert "camera.remove" in actions
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_the_audit_entry_names_who_did_it(self, tmp_path, authed):
        from vg.api import app as app_module

        store, client = self._client(tmp_path, authed)
        try:
            client.post("/sources", json={
                "name": "Side gate", "source": "webcam:9", "features": ["counting"]})

            entry = next(e for e in store.audit(50) if e.action == "camera.add")
            assert entry.actor and entry.actor != "unknown"
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_a_password_never_reaches_the_audit(self, tmp_path, authed):
        from vg.api import app as app_module

        store, client = self._client(tmp_path, authed)
        try:
            client.post("/sources", json={
                "name": "Side gate", "source": f"rtsp://admin:{SENTINEL}@10.0.0.5/s",
                "features": ["counting"]})

            for entry in store.audit(50):
                assert SENTINEL not in (entry.detail or "")
                assert SENTINEL not in (entry.subject or "")
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())


class TestCameraSetupIsAdminOnly:
    """Decided by path in `auth/deps.py`, not by the console hiding a button.

    `/sources` is already in ADMIN_PREFIXES, so this should pass without new
    code. The test exists to prove the NEW routes really did land under that
    prefix rather than beside it.
    """

    def test_an_it_user_cannot_change_cameras(self, tmp_path, authed):
        from vg.api import app as app_module
        from vg.ingest.store import CameraStore

        store = live_store(tmp_path, cameras=CameraStore(tmp_path / "roster.db"))
        try:
            client = client_for(store, authed, role="it")

            assert client.post("/sources", json={
                "name": "X", "source": "webcam:9"}).status_code == 403
            assert client.post("/sources/bulk", json={"cameras": [
                {"name": "X", "source": "webcam:9"}]}).status_code == 403
            assert client.patch("/sources/cam-a", json={"name": "X"}).status_code == 403
            assert client.delete("/sources/cam-a").status_code == 403
            assert client.post("/sources/dvr", json={
                "host": "10.0.0.5", "username": "u", "password": "p",
                "template": "rtsp://{host}/ch{channel}",
                "channels": ["1"]}).status_code == 403
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# the recorder — what it said, not what we assumed
# ---------------------------------------------------------------------------

class TestTheRecorderIsNotAFixture:
    def test_live_store_does_not_inherit_the_dvr_fixture(self):
        """The bug this whole feature came from.

        `LiveStore` subclasses `MockStore` and never overrode `connect_dvr`,
        so the live engine answered from the fixture: sixteen channels, "ok",
        704x576, whatever the recorder was and whether or not it answered.

        Shaped after the `LiveStore.ask is MockStore.ask` assertion in
        `test_ask.py`, which exists for the same class of mistake - there
        asserting sameness deliberately, here the opposite.
        """
        assert LiveStore.connect_dvr is not MockStore.connect_dvr

    def test_live_store_does_not_inherit_the_scan_fixture(self):
        assert LiveStore.scan is not MockStore.scan

    def request(self, **kw) -> S.DvrConnectRequest:
        """A recorder that answers nothing, failing FAST.

        A `file:` path that does not exist fails in milliseconds and goes
        through the identical probe path. An unroutable RTSP address would be
        more evocative and takes ~30s per channel, because OpenCV does not
        honour its own open timeout there - which is a real property of the
        thing under test, and exactly why `connect_dvr` bounds the wait
        itself. `test_the_budget_actually_bounds_the_wait` covers that; the
        rest of these do not need to pay for it.
        """
        return S.DvrConnectRequest(**{
            "host": "10.255.255.1",
            "username": "admin",
            "password": SENTINEL,
            "template": "file:/nonexistent/ch{channel}.mp4",
            "channels": ["1", "2", "3"],
            "budget": 10.0,
            **kw,
        })

    def test_an_unreachable_recorder_offers_nothing_to_add(self, tmp_path):
        """Not reachable, a reason, and no channel a person could tick.

        The channels are still LISTED - P13-FR-002 requires the ones that did
        not answer to be reported with their reason, or an operator has a
        failure and no way to see which channel is wrong. What must not happen
        is one of them being addable.
        """
        store = live_store(tmp_path)

        result = store.connect_dvr(self.request())

        assert result.reachable is False
        assert result.reason
        assert len(result.channels) == 3
        assert not [c for c in result.channels if c.status == S.SourceStatus.OK]
        assert not [c for c in result.channels if c.enabled]

    def test_an_unreachable_recorder_is_not_an_error(self, tmp_path, authed):
        """200 with a reason. Degradation is payload, never a status code."""
        from vg.api import app as app_module

        store = live_store(tmp_path)
        try:
            client = client_for(store, authed)
            response = client.post("/sources/dvr", json={
                "host": "10.255.255.1", "username": "admin", "password": "x",
                "template": "file:/nonexistent/ch{channel}.mp4",
                "channels": ["1"], "budget": 10.0})

            assert response.status_code == 200
            body = response.json()
            assert body["reachable"] is False
            assert body["reason"]
            assert not [c for c in body["channels"] if c["enabled"]]
        finally:
            app_module.set_store(MockStore())

    def test_a_template_without_a_channel_placeholder_is_refused(self, tmp_path, authed):
        from vg.api import app as app_module

        store = live_store(tmp_path)
        try:
            client = client_for(store, authed)
            response = client.post("/sources/dvr", json={
                "host": "10.0.0.5", "username": "u", "password": "p",
                "template": "rtsp://{host}/stream", "channels": ["1"]})

            assert response.status_code == 422
            assert "{channel}" in response.text
        finally:
            app_module.set_store(MockStore())

    def test_the_probe_never_returns_a_password(self, tmp_path):
        store = live_store(tmp_path)

        result = store.connect_dvr(self.request())

        assert SENTINEL not in result.model_dump_json()

    def test_the_budget_actually_bounds_the_wait(self, tmp_path, monkeypatch):
        """The budget is wall-clock for a person watching a spinner.

        The probe is stubbed to be slow rather than pointed at a real dead
        address, for two reasons: an unroutable RTSP host takes ~30s per
        channel because OpenCV ignores its own open timeout there, and each
        one leaves a worker thread running that long. Both are properties of
        OpenCV, not of the code under test - what IS under test is that
        `connect_dvr` returns without waiting for them.

        The first version used `with ThreadPoolExecutor(...)`, whose exit
        waits for every probe. A 3s budget took 91s.
        """
        import time as _time

        store = live_store(tmp_path)

        def glacial(self, channel, template, req):
            _time.sleep(30)
            raise AssertionError("should never be reached")

        monkeypatch.setattr(LiveStore, "_probe_channel", glacial)

        started = _time.monotonic()
        result = store.connect_dvr(self.request(
            channels=[str(i) for i in range(1, 17)], budget=1.0))
        elapsed = _time.monotonic() - started

        assert elapsed < 10.0, f"budget was 1s, call took {elapsed:.0f}s"
        assert result.reachable is False
        assert len(result.channels) == 16, "every channel is still reported"
        assert result.checked == 0

    def test_a_channel_the_budget_never_reached_is_not_a_failure(
        self, tmp_path, monkeypatch,
    ):
        """`checked: false` and `status: down` are different facts.

        "We never got an answer" must not read as "there is no camera there",
        or an operator disconnects a working channel on the strength of it.
        """
        import time as _time

        answered = {"1", "2"}

        def selective(self, channel, template, req):
            if channel in answered:
                return S.DvrChannel(
                    channel=channel, name=f"ch{channel}", enabled=True,
                    checked=True, status=S.SourceStatus.OK,
                    resolution="640x480", latency_ms=5.0,
                )
            _time.sleep(30)
            raise AssertionError("should never be reached")

        monkeypatch.setattr(LiveStore, "_probe_channel", selective)
        store = live_store(tmp_path)

        result = store.connect_dvr(self.request(
            channels=[str(i) for i in range(1, 9)], budget=1.5))

        assert result.checked == sum(1 for c in result.channels if c.checked)

        unchecked = [c for c in result.channels if not c.checked]
        assert unchecked, "the slow channels should be left unknown"
        assert all(c.error is None for c in unchecked), (
            "an unchecked channel has no failure reason - none came back")
        assert all(not c.enabled for c in unchecked)
        # And the two that DID answer are still offered, so a slow recorder
        # does not cost an operator the channels that work.
        assert {c.channel for c in result.channels if c.enabled} == answered

    def test_every_channel_is_reported_even_when_none_answer(self, tmp_path):
        store = live_store(tmp_path)

        result = store.connect_dvr(self.request())

        assert result.checked == 3, "a fast failure IS an answer"
        assert len(result.channels) == 3
        assert {c.channel for c in result.channels} == {"1", "2", "3"}
        # Tried and failed carries a reason; the operator can act on it.
        assert all(c.checked and c.error for c in result.channels)

    def test_a_working_channel_carries_what_it_actually_returned(self, tmp_path):
        """The positive case, against a file source rather than a recorder.

        A recorded clip is a stream like any other, so it exercises the whole
        probe - substitute the channel, open, read a frame, measure - without
        hardware. The clip is copied to `ch1.mp4` so `{channel}` has real work
        to do rather than being a placeholder nothing depends on.
        """
        import shutil

        from vg import config as vgconfig

        clip = next(
            (vgconfig.REPO_DIR / "engine/data/footage").glob("*.mp4"), None)
        if clip is None:
            pytest.skip("no recorded clip on this machine")

        shutil.copy(clip, tmp_path / "ch1.mp4")
        store = live_store(tmp_path)

        result = store.connect_dvr(S.DvrConnectRequest(
            host="unused", username="", password="",
            template="file:" + (tmp_path / "ch{channel}.mp4").as_posix(),
            channels=["1", "2"], budget=20.0,
        ))

        assert result.reachable is True, "ch1 exists and should have answered"

        one = next(c for c in result.channels if c.channel == "1")
        assert one.status == S.SourceStatus.OK
        assert one.checked is True
        assert one.resolution and "x" in one.resolution
        assert one.latency_ms is not None

        # ch2 was never copied, so it is a real "nothing there" - checked,
        # down, and carrying a reason. The two states must not look alike.
        two = next(c for c in result.channels if c.channel == "2")
        assert two.checked is True
        assert two.status == S.SourceStatus.DOWN
        assert two.resolution is None


# ---------------------------------------------------------------------------
# adding many at once, and correcting one
# ---------------------------------------------------------------------------

def roster_store(tmp_path):
    """A LiveStore with a real runtime roster and one YAML-seeded camera."""
    from vg.config import CameraConfig
    from vg.ingest.registry import CameraRegistry
    from vg.ingest.store import CameraStore

    seeded = CameraConfig.parse(
        {"id": "cam-seeded", "name": "Seeded", "source": "webcam:0",
         "features": ["counting"]}, "cam-seeded")
    registry = CameraRegistry([seeded])
    return live_store(tmp_path, registry,
                      cameras=CameraStore(tmp_path / "roster.db"))


class TestAddingManyAtOnce:
    def test_every_camera_gets_an_outcome(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            response = client.post("/sources/bulk", json={"cameras": [
                {"name": f"Cam {i}", "source": f"webcam:{i}",
                 "features": ["counting"]}
                for i in range(6)
            ]})

            assert response.status_code == 200
            outcomes = response.json()
            assert [o["index"] for o in outcomes] == list(range(6))
            assert all(o["ok"] for o in outcomes)
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_one_bad_camera_does_not_refuse_the_others(self, tmp_path, authed):
        """The whole reason this endpoint exists rather than sixteen calls."""
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            cameras = [
                {"name": f"Cam {i}", "source": f"webcam:{i}",
                 "features": ["counting"]}
                for i in range(6)
            ]
            # 'vehicles' with no gate is refused by CameraConfig.parse.
            cameras[3] = {"name": "Bad", "source": "webcam:9",
                          "features": ["vehicles"]}

            outcomes = client.post(
                "/sources/bulk", json={"cameras": cameras}).json()

            assert [o["ok"] for o in outcomes] == [
                True, True, True, False, True, True]
            assert outcomes[3]["error"]
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_a_refused_camera_still_reports_its_source_redacted(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            outcomes = client.post("/sources/bulk", json={"cameras": [
                {"name": "Bad", "source": f"rtsp://admin:{SENTINEL}@10.0.0.5/s",
                 "features": ["vehicles"]},
            ]}).json()

            assert outcomes[0]["ok"] is False
            assert SENTINEL not in outcomes[0]["source"]
            assert "****" in outcomes[0]["source"]
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_adding_does_not_disturb_a_camera_already_running(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            before = store.registry.worker("cam-seeded")
            client = client_for(store, authed)
            client.post("/sources/bulk", json={"cameras": [
                {"name": "New", "source": "webcam:7", "features": ["counting"]}]})

            assert store.registry.worker("cam-seeded") is before
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())


class TestCorrectingACamera:
    def add(self, client, **kw):
        body = {"name": "Side gate", "source": "webcam:9",
                "features": ["counting"], **kw}
        return client.post("/sources", json=body).json()

    def test_a_features_only_edit_does_not_reopen_the_stream(self, tmp_path, authed):
        """Reopening an RTSP connection to add a tickbox is a visible stutter."""
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)

            result = client.patch(f"/sources/{added['id']}",
                                  json={"features": ["counting", "track"]}).json()

            assert result["restarted"] is False
            assert set(result["camera"]["features"]) == {"counting", "track"}
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_changing_the_rate_does_reopen_the_stream(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)

            result = client.patch(f"/sources/{added['id']}",
                                  json={"fps": 10.0}).json()

            assert result["restarted"] is True
            assert result["camera"]["fps"] == 10.0
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_editing_a_config_file_camera_says_it_now_shadows_it(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)

            result = client.patch("/sources/cam-seeded",
                                  json={"area": "Yard"}).json()

            assert result["shadowsConfig"] is True
            assert result["camera"]["area"] == "Yard"
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_a_camera_added_here_does_not_shadow_the_config(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)

            result = client.patch(f"/sources/{added['id']}",
                                  json={"area": "Yard"}).json()

            assert result["shadowsConfig"] is False
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_an_edit_keeps_the_cameras_identity(self, tmp_path, authed):
        """Its id is what everything recorded against it is attached to."""
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)

            result = client.patch(f"/sources/{added['id']}",
                                  json={"name": "Renamed entirely"}).json()

            assert result["camera"]["id"] == added["id"]
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_an_edit_is_audited_before_it_is_written(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)
            client.patch(f"/sources/{added['id']}", json={"area": "Yard"})

            entry = next(e for e in store.audit(50) if e.action == "camera.edit")
            assert entry.subject == added["id"]
            assert "area" in (entry.detail or "")
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_an_edit_never_puts_a_password_in_the_audit(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)
            client.patch(f"/sources/{added['id']}", json={
                "source": "rtsp://10.0.0.5/s", "username": "admin",
                "password": SENTINEL})

            for entry in store.audit(50):
                assert SENTINEL not in (entry.detail or "")
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_an_invalid_edit_is_refused_and_changes_nothing(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = self.add(client)

            # 'vehicles' with no gate: refused by CameraConfig.parse.
            response = client.patch(f"/sources/{added['id']}",
                                    json={"features": ["vehicles"]})

            assert response.status_code == 422
            current = next(s for s in store.sources() if s.id == added["id"])
            assert current.features == ["counting"]
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_editing_a_camera_that_does_not_exist_is_a_404(self, tmp_path, authed):
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)

            assert client.patch("/sources/cam-nope",
                                json={"area": "Yard"}).status_code == 404
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_editing_with_no_roster_is_a_503_not_a_404(self, tmp_path, authed):
        """Nothing is running is a different answer from not found."""
        from vg.api import app as app_module

        store = live_store(tmp_path)          # no CameraStore at all
        try:
            client = client_for(store, authed)

            assert client.patch("/sources/cam-a",
                                json={"area": "Yard"}).status_code == 503
        finally:
            app_module.set_store(MockStore())


# ---------------------------------------------------------------------------
# credentials — one sentinel, every path
# ---------------------------------------------------------------------------

class TestNoPasswordEscapes:
    """One password, every surface it could reach.

    Cheaper and harder to fool than asserting redaction per endpoint: if a new
    path forgets `redacted_source()`, this fails without anybody having
    remembered to extend it.
    """

    def test_a_password_reaches_no_response_and_no_audit(self, tmp_path, authed, caplog):
        import logging

        from vg.api import app as app_module

        store = roster_store(tmp_path)
        caplog.set_level(logging.DEBUG)
        try:
            client = client_for(store, authed)
            source = f"rtsp://admin:{SENTINEL}@10.0.0.5/stream"

            added = client.post("/sources", json={
                "name": "Sentinel", "source": source, "features": ["counting"]})
            assert added.status_code == 201
            camera_id = added.json()["id"]

            surfaces = {
                "add response": added.text,
                "sources list": client.get("/sources").text,
                "edit response": client.patch(
                    f"/sources/{camera_id}", json={"area": "Yard"}).text,
                "bulk response": client.post("/sources/bulk", json={"cameras": [
                    {"name": "Sentinel 2", "source": source,
                     "features": ["counting"]}]}).text,
                "audit": client.get("/audit").text,
                "health": client.get("/system/health").text,
                "log": caplog.text,
            }

            for where, text in surfaces.items():
                assert SENTINEL not in text, f"password leaked into the {where}"
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())

    def test_the_masked_address_is_still_useful(self, tmp_path, authed):
        """Redaction must not take the host with it.

        An operator has to be able to tell two cameras apart, so masking the
        whole string would trade one problem for another.
        """
        from vg.api import app as app_module

        store = roster_store(tmp_path)
        try:
            client = client_for(store, authed)
            added = client.post("/sources", json={
                "name": "Sentinel",
                "source": f"rtsp://admin:{SENTINEL}@10.0.0.5/stream",
                "features": ["counting"]}).json()

            assert "10.0.0.5" in added["ip"]
            assert "admin" in added["ip"]
            assert "****" in added["ip"]
        finally:
            store.cameras.close()
            app_module.set_store(MockStore())


class TestEditingEveryField:
    """The edit form once exposed only name, area and features. The engine
    always accepted the rest; these pin that the whole configuration is
    reachable through a single PATCH."""

    def _added(self, client):
        return client.post("/sources", json={
            "name": "Full", "source": "webcam:9", "features": ["counting"]}).json()

    def test_rotation_is_editable(self, tmp_path, authed):
        from vg.api import app as app_module
        store = roster_store(tmp_path)
        try:
            c = client_for(store, authed)
            cam = self._added(c)
            r = c.patch(f"/sources/{cam['id']}", json={"rotate": 90}).json()
            assert r["camera"]["rotate"] == 90
            assert r["restarted"] is True
        finally:
            store.cameras.close(); app_module.set_store(MockStore())

    def test_the_analytics_rate_is_editable(self, tmp_path, authed):
        from vg.api import app as app_module
        store = roster_store(tmp_path)
        try:
            c = client_for(store, authed)
            cam = self._added(c)
            r = c.patch(f"/sources/{cam['id']}", json={"fps": 12.0}).json()
            assert r["camera"]["fps"] == 12.0
        finally:
            store.cameras.close(); app_module.set_store(MockStore())

    def test_a_camera_can_be_switched_off_and_on(self, tmp_path, authed):
        from vg.api import app as app_module
        store = roster_store(tmp_path)
        try:
            c = client_for(store, authed)
            cam = self._added(c)
            off = c.patch(f"/sources/{cam['id']}", json={"enabled": False}).json()
            assert off["camera"]["enabled"] is False
            on = c.patch(f"/sources/{cam['id']}", json={"enabled": True}).json()
            assert on["camera"]["enabled"] is True
        finally:
            store.cameras.close(); app_module.set_store(MockStore())

    def test_the_address_and_credentials_are_editable_and_redacted(self, tmp_path, authed):
        from vg.api import app as app_module
        store = roster_store(tmp_path)
        try:
            c = client_for(store, authed)
            cam = self._added(c)
            r = c.patch(f"/sources/{cam['id']}", json={
                "source": "rtsp://10.0.0.9/s", "username": "admin",
                "password": SENTINEL}).json()
            assert "10.0.0.9" in r["camera"]["ip"]
            assert SENTINEL not in r["camera"]["ip"]
            assert "****" in r["camera"]["ip"]
            assert r["restarted"] is True
        finally:
            store.cameras.close(); app_module.set_store(MockStore())
