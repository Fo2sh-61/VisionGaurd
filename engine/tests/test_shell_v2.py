"""Spec 022 (console v2 shell): roles, accounts, and what an IT account may read.

Other stories (settings, working days, knife detection, serving) add their
tests to this file as they land.

Fixtures come from `conftest.py`: `user_store`, `sign_in`, `authed`.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as vgconfig  # noqa: E402
from vg.api import app as app_module  # noqa: E402
from vg.api import schemas as S  # noqa: E402
from vg.api.app import create_app  # noqa: E402
from vg.api.live import LiveStore  # noqa: E402
from vg.api.store import MockStore  # noqa: E402
from vg.auth import dev_signin  # noqa: E402
from vg.auth.deps import requires_admin  # noqa: E402
from vg.auth.store import LastAdmin  # noqa: E402
from vg.ingest import encoder  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402

PASSWORD = "a-long-enough-test-password"


# ---------------------------------------------------------------------------
# P14-FR-110: the path rules
# ---------------------------------------------------------------------------

class TestPathRules:
    @pytest.mark.parametrize("path", [
        "/attendance", "/attendance/export", "/groups", "/groups/x",
        "/people", "/people/x/history",
    ])
    def test_the_register_groups_and_directory_are_admin_only(self, path):
        assert requires_admin("GET", path)

    @pytest.mark.parametrize("method", ["POST", "DELETE"])
    def test_an_it_account_may_start_and_stop_a_recording(self, method):
        assert not requires_admin(method, "/cameras/cam-1/recording")
        assert not requires_admin(method, "/cameras/cam-1/recording/")

    @pytest.mark.parametrize("method,path", [
        ("PATCH", "/cameras/cam-1"),
        ("DELETE", "/cameras/cam-1"),
        ("POST", "/cameras/cam-1/recording/extra"),
        ("POST", "/cameras/recording"),
        ("POST", "/sources"),
        ("GET", "/sources"),
        ("GET", "/sources/scan"),
        ("DELETE", "/sources/cam-1"),
        ("PATCH", "/users/u1"),
    ])
    def test_everything_else_stays_as_it_was(self, method, path):
        assert requires_admin(method, path)

    def test_an_it_session_gets_403_on_the_records(self, user_store, sign_in):
        app_module.set_store(MockStore())
        app = create_app()
        token = sign_in(app, "it")
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        for path in ("/attendance", "/groups", "/people"):
            assert client.get(path).status_code == 403, path


# ---------------------------------------------------------------------------
# the recording actor comes from the session
# ---------------------------------------------------------------------------

class TestRecordingActor:
    @pytest.fixture
    def seen(self, monkeypatch):
        calls = []

        def start(self, camera_id, actor):
            calls.append(("start", camera_id, actor))
            return S.RecordingResult(ok=False, reason="test")

        def stop(self, camera_id, actor):
            calls.append(("stop", camera_id, actor))
            return S.RecordingResult(ok=False, reason="test")

        monkeypatch.setattr(MockStore, "start_recording", start, raising=False)
        monkeypatch.setattr(MockStore, "stop_recording", stop, raising=False)
        return calls

    def test_the_account_name_is_the_actor_not_the_query(self, authed, seen):
        app_module.set_store(MockStore())
        client = authed(create_app(), "it")
        client.post("/cameras/cam-1/recording?actor=somebody-else")
        client.delete("/cameras/cam-1/recording?actor=somebody-else")
        assert seen == [("start", "cam-1", "Test It"),
                        ("stop", "cam-1", "Test It")]


# ---------------------------------------------------------------------------
# UserStore.set_role
# ---------------------------------------------------------------------------

def _make(store, role, email=None):
    return store.create_user(email or f"{role}-{id(role)}@t.local", role.title(),
                             role, PASSWORD)


class TestSetRole:
    def test_promoting_works(self, user_store):
        admin = _make(user_store, "admin", "a@t.local")
        it = _make(user_store, "it", "i@t.local")
        assert user_store.set_role(it.id, "admin").role == "admin"
        assert {u.id: u.role for u in user_store.users()}[it.id] == "admin"
        # Now there are two, so the first may be demoted.
        assert user_store.set_role(admin.id, "it").role == "it"

    def test_the_last_enabled_admin_cannot_be_demoted(self, user_store):
        admin = _make(user_store, "admin", "a@t.local")
        _make(user_store, "it", "i@t.local")
        with pytest.raises(LastAdmin):
            user_store.set_role(admin.id, "it")
        assert {u.id: u.role for u in user_store.users()}[admin.id] == "admin"

    def test_a_disabled_admin_does_not_count(self, user_store):
        first = _make(user_store, "admin", "a@t.local")
        second = _make(user_store, "admin", "b@t.local")
        user_store.set_disabled(second.id, True)
        with pytest.raises(LastAdmin):
            user_store.set_role(first.id, "it")

    def test_an_unknown_role_is_refused(self, user_store):
        admin = _make(user_store, "admin", "a@t.local")
        with pytest.raises(ValueError):
            user_store.set_role(admin.id, "superuser")

    def test_an_unknown_account_is_a_key_error(self, user_store):
        with pytest.raises(KeyError):
            user_store.set_role("nobody", "it")

    def test_a_session_sees_the_new_role_on_the_next_request(self, user_store):
        _make(user_store, "admin", "a@t.local")
        it = _make(user_store, "it", "i@t.local")
        token, _ = user_store.start_session(it)
        assert user_store.user_for_token(token).role == "it"
        user_store.set_role(it.id, "admin")
        assert user_store.user_for_token(token).role == "admin"

    def test_users_carry_the_last_sign_in(self, user_store):
        _make(user_store, "admin", "a@t.local")
        assert user_store.users()[0].last_login_at is None
        assert user_store.authenticate("a@t.local", PASSWORD) is not None
        assert user_store.users()[0].last_login_at is not None


# ---------------------------------------------------------------------------
# PATCH /users/{id}, GET /users
# ---------------------------------------------------------------------------

@pytest.fixture
def live(user_store):
    """A LiveStore with real accounts behind it, mounted on a real app."""
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                      users=user_store)
    app_module.set_store(store)
    return store


class TestUsersEndpoint:
    def test_admin_changes_a_role_and_the_audit_comes_first(
            self, live, user_store, authed, monkeypatch):
        app = create_app()
        client = authed(app, "admin")
        target = _make(user_store, "it", "target@t.local")

        order = []
        real = user_store.set_role

        def spy(user_id, role):
            # By the time the change happens the entry must already exist.
            order.append([e.action for e in live._audit])
            return real(user_id, role)

        monkeypatch.setattr(user_store, "set_role", spy)
        res = client.patch(f"/users/{target.id}", json={"role": "admin"})
        assert res.status_code == 200, res.text
        assert res.json()["role"] == "admin"
        assert order == [["user.role"]]
        entry = live._audit[0]
        assert entry.actor == "Test Admin"
        assert entry.subject == target.id

    def test_it_is_refused(self, live, user_store, authed):
        client = authed(create_app(), "it")
        target = _make(user_store, "it", "target@t.local")
        res = client.patch(f"/users/{target.id}", json={"role": "admin"})
        assert res.status_code == 403
        assert {u.id: u.role for u in user_store.users()}[target.id] == "it"
        assert live._audit == []

    def test_demoting_the_last_admin_is_a_409_with_a_reason(
            self, live, user_store, authed):
        client = authed(create_app(), "admin")  # the only admin
        me = next(u for u in user_store.users() if u.role == "admin")
        res = client.patch(f"/users/{me.id}", json={"role": "it"})
        assert res.status_code == 409
        assert "only administrator" in res.json()["detail"]
        assert next(u for u in user_store.users()
                    if u.id == me.id).role == "admin"

    def test_an_unknown_id_is_a_404(self, live, authed):
        client = authed(create_app(), "admin")
        res = client.patch("/users/nobody", json={"role": "it"})
        assert res.status_code == 404

    def test_an_unknown_role_is_a_422(self, live, user_store, authed):
        client = authed(create_app(), "admin")
        target = _make(user_store, "it", "target@t.local")
        res = client.patch(f"/users/{target.id}", json={"role": "root"})
        assert res.status_code == 422

    def test_the_list_carries_last_active(self, live, user_store, authed):
        client = authed(create_app(), "admin")
        user_store.authenticate("admin@test.local", PASSWORD)
        rows = {r["email"]: r for r in client.get("/users").json()}
        assert rows["admin@test.local"]["lastActive"] is not None
        assert rows["admin@test.local"]["lastActive"]["utc"]

    def test_a_user_who_never_signed_in_has_no_last_active(
            self, live, user_store, authed):
        client = authed(create_app(), "admin")
        _make(user_store, "it", "never@t.local")
        rows = {r["email"]: r for r in client.get("/users").json()}
        assert rows["never@t.local"]["lastActive"] is None


# ---------------------------------------------------------------------------
# Ask: IT may not read attendance or people through it
# ---------------------------------------------------------------------------

class _Stub:
    def __init__(self, query, **params):
        from vg.ask.parser import Parsed
        self.parsed = Parsed(query=query, params=params)

    def parse(self, masked):
        return self.parsed


class TestAskRoles:
    @pytest.mark.parametrize("query,params", [
        ("attendance", {"mode": "group", "subject": "Grade 8"}),
        ("group_roster", {"group": "Grade 8"}),
        ("person_directory", {}),
        ("person_history", {"person": "Mohamed Fouad"}),
    ])
    def test_it_gets_the_admins_only_note(self, query, params):
        store = MockStore()
        answer = store.ask("q", "guard", parser=_Stub(query, **params),
                           role="it")
        assert answer.outcome is S.AskOutcome.UNSUPPORTED
        assert answer.note.code == "ask.adminsOnly"
        assert answer.rows == [] and answer.headline == []
        # Asked, so on the record - and the refusal is in the same row.
        assert "refused" in store._audit[-1].detail

    def test_admin_still_gets_the_answer(self):
        answer = MockStore().ask(
            "q", "admin", role="admin",
            parser=_Stub("group_roster", group="Grade 8"))
        assert answer.outcome is S.AskOutcome.ANSWERED

    def test_it_still_gets_a_query_outside_the_records(self):
        answer = MockStore().ask(
            "q", "guard", role="it",
            parser=_Stub("headcount", place="Yard"))
        assert answer.note is None or answer.note.code != "ask.adminsOnly"

    def test_the_route_passes_the_session_role(self, authed, monkeypatch):
        seen = []

        def spy(self, question, actor, parser=None, role="admin"):
            seen.append(role)
            return S.AskAnswer(outcome=S.AskOutcome.UNSUPPORTED)

        monkeypatch.setattr(MockStore, "ask", spy)
        app_module.set_store(MockStore())
        authed(create_app(), "it").post("/ask", json={"question": "hi"})
        assert seen == ["it"]

    def test_the_note_is_declared(self):
        from vg.api import notes
        assert "ask.adminsOnly" in notes.CODES
        assert notes.note("ask.adminsOnly").code == "ask.adminsOnly"


# ---------------------------------------------------------------------------
# Settings that save, and working days (US2)
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402

from vg.alerts import events  # noqa: E402
from vg.settings_store import SiteSettingsStore  # noqa: E402


@pytest.fixture
def site(tmp_path):
    store = SiteSettingsStore(tmp_path / "site.db")
    yield store
    store.close_db()


@pytest.fixture
def live_site(user_store, site):
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                      users=user_store, site_settings=site)
    app_module.set_store(store)
    return store


class TestSiteSettingsStore:
    def test_every_key_round_trips(self, site):
        values = {"name": "Nile School", "hours_from": "07:00", "hours_to": "14:30",
                  "late_cutoff": "08:15", "term_from": "2026-09-20",
                  "term_to": "2027-06-15", "working_days": [0, 1, 2, 3, 6]}
        site.save(values, "Test Admin")
        assert site.get_all() == values

    def test_nothing_saved_means_nothing_returned(self, site):
        assert site.get_all() == {}

    def test_a_second_save_changes_only_the_keys_it_names(self, site):
        site.save({"name": "A", "hours_from": "07:00"}, "x")
        site.save({"name": "B"}, "x")
        assert site.get_all() == {"name": "B", "hours_from": "07:00"}

    def test_an_unknown_key_is_refused(self, site):
        with pytest.raises(ValueError):
            site.save({"colour": "red"}, "x")
        assert site.get_all() == {}

    def test_it_survives_a_restart(self, tmp_path):
        first = SiteSettingsStore(tmp_path / "s.db")
        first.save({"working_days": [0, 1]}, "x")
        first.close_db()
        second = SiteSettingsStore(tmp_path / "s.db")
        try:
            assert second.get_all() == {"working_days": [0, 1]}
        finally:
            second.close_db()


class TestWorkingDays:
    def test_the_default_is_saturday_to_thursday(self):
        assert vgconfig.HoursConfig().working_days == frozenset({5, 6, 0, 1, 2, 3})
        assert vgconfig.load().hours.working_days == frozenset({5, 6, 0, 1, 2, 3})

    def test_yaml_may_name_other_days(self):
        hours = vgconfig.HoursConfig.parse({"working_days": [0, 1, 2]}, "hours")
        assert hours.working_days == frozenset({0, 1, 2})

    @pytest.mark.parametrize("bad", [[], [7], [-1], ["mon"], "all"])
    def test_yaml_with_a_bad_list_is_refused(self, bad):
        with pytest.raises(vgconfig.ConfigError, match="working_days"):
            vgconfig.HoursConfig.parse({"working_days": bad}, "hours")

    def test_is_school_day_uses_the_days_it_is_given(self):
        friday, saturday = date(2026, 10, 9), date(2026, 10, 10)
        term = ("2026-09-20", "2027-06-15")
        sat_to_thu = frozenset({5, 6, 0, 1, 2, 3})
        assert not events.is_school_day(friday, *term, sat_to_thu)
        assert events.is_school_day(saturday, *term, sat_to_thu)
        assert events.is_school_day(friday, *term, frozenset({4}))
        assert not events.is_school_day(saturday, *term, frozenset({4}))


class TestEffectiveHours:
    def test_with_nothing_saved_the_yaml_seed_is_used(self, live_site):
        assert live_site.hours() == live_site.config.hours

    def test_saved_values_overlay_the_seed(self, live_site):
        live_site.save_site_settings("Test Admin", S.SiteSettingsUpdate(
            hours_from="07:00", late_cutoff="08:20", working_days=[0, 1]))
        hours = live_site.hours()
        assert hours.start.strftime("%H:%M") == "07:00"
        assert hours.late_cutoff.strftime("%H:%M") == "08:20"
        assert hours.end == live_site.config.hours.end      # not saved: seed
        assert hours.working_days == frozenset({0, 1})

    def test_a_save_takes_effect_at_once_and_survives_a_new_store(
            self, live_site, site, user_store):
        live_site.save_site_settings("a", S.SiteSettingsUpdate(
            term_from="2026-09-01", term_to="2027-06-30"))
        again = LiveStore(config=vgconfig.load(), registry=CameraRegistry([]),
                          users=user_store, site_settings=site)
        assert again.hours().term_from == "2026-09-01"

    @pytest.mark.parametrize("update", [
        {"late_cutoff": "06:00"},                      # before the day starts
        {"late_cutoff": "17:00"},                      # after it ends
        {"hours_from": "09:00"},                       # leaves the seed cut-off before the start
        {"hours_to": "07:45"},                         # leaves the seed cut-off after the end
        {"term_from": "2027-01-01", "term_to": "2026-01-01"},
        {"working_days": []},
        {"working_days": [9]},
        {"hours_from": "soon"},
        {"term_from": "yesterday"},
        {"name": "   "},
    ])
    def test_an_invalid_change_is_refused_and_nothing_is_saved(
            self, live_site, site, update):
        with pytest.raises(ValueError):
            live_site.save_site_settings("a", S.SiteSettingsUpdate(**update))
        assert site.get_all() == {}

    def test_the_cutoff_is_checked_against_the_hours_saved_with_it(self, live_site):
        live_site.save_site_settings("a", S.SiteSettingsUpdate(
            hours_from="09:00", late_cutoff="09:30"))
        assert live_site.hours().late_cutoff.strftime("%H:%M") == "09:30"

    def test_without_a_store_a_save_is_unavailable_not_lost(self, bare_live_store):
        from vg.api.store import SubsystemUnavailable
        with pytest.raises(SubsystemUnavailable):
            bare_live_store.save_site_settings("a", S.SiteSettingsUpdate(name="X"))
        # Reading still works, from the seed.
        assert bare_live_store.hours() == bare_live_store.config.hours

    def test_the_school_profile_carries_the_working_days_and_saved_name(self, live_site):
        assert live_site.school_profile().working_days == [0, 1, 2, 3, 5, 6]
        live_site.save_site_settings("a", S.SiteSettingsUpdate(
            name="Nile School", working_days=[0, 2]))
        profile = live_site.school_profile()
        assert profile.name == "Nile School"
        assert profile.working_days == [0, 2]


class TestSiteSettingsEndpoint:
    def test_admin_saves_and_the_audit_comes_first(self, live_site, site, authed,
                                                   monkeypatch):
        client = authed(create_app(), "admin")
        order = []
        real = site.save

        def spy(values, actor):
            order.append([e.action for e in live_site._audit])
            return real(values, actor)

        monkeypatch.setattr(site, "save", spy)
        res = client.patch("/settings/site", json={
            "hoursFrom": "07:00", "workingDays": [6, 0, 1, 2, 3, 3]})
        assert res.status_code == 200, res.text
        assert res.json()["hoursFrom"] == "07:00"
        assert res.json()["workingDays"] == [0, 1, 2, 3, 6]
        assert order == [["settings.site"]]
        assert live_site._audit[0].actor == "Test Admin"
        # What was saved is what is read back.
        assert client.get("/settings/school").json()["workingDays"] == [0, 1, 2, 3, 6]

    def test_it_is_refused(self, live_site, site, authed):
        client = authed(create_app(), "it")
        res = client.patch("/settings/site", json={"name": "Hacked"})
        assert res.status_code == 403
        assert site.get_all() == {} and live_site._audit == []

    @pytest.mark.parametrize("body", [
        {"lateCutoff": "06:00"},
        {"workingDays": []},
        {"termFrom": "2027-01-01", "termTo": "2026-01-01"},
    ])
    def test_an_invalid_change_is_a_422_with_the_reason(self, live_site, site,
                                                        authed, body):
        client = authed(create_app(), "admin")
        res = client.patch("/settings/site", json=body)
        assert res.status_code == 422
        assert res.json()["detail"]
        assert site.get_all() == {}

    def test_an_unknown_field_is_a_422(self, live_site, authed):
        client = authed(create_app(), "admin")
        assert client.patch("/settings/site", json={"colour": "red"}).status_code == 422

    def test_without_a_store_it_is_a_503(self, authed, user_store):
        app_module.set_store(LiveStore(config=vgconfig.load(),
                                       registry=CameraRegistry([]), users=user_store))
        client = authed(create_app(), "admin")
        assert client.patch("/settings/site", json={"name": "X"}).status_code == 503

    def test_the_school_profile_always_lists_working_days(self, authed):
        app_module.set_store(MockStore())
        client = authed(create_app(), "it")
        assert client.get("/settings/school").json()["workingDays"] == [0, 1, 2, 3, 5, 6]


# ---------------------------------------------------------------------------
# US3: knife detection is not shown when no camera runs it
# ---------------------------------------------------------------------------

def _camera(feature_list, camera_id="cam-w", enabled=True):
    from vg.config import CameraConfig

    return CameraConfig.parse(
        {"id": camera_id, "name": "Gate", "source": "webcam:0",
         "features": feature_list, "enabled": enabled}, camera_id)


def _alerts_live(tmp_path, camera):
    from vg.alerts.store import AlertStore

    alerts_db = AlertStore(tmp_path / "alerts.db")
    store = LiveStore(config=vgconfig.load(), registry=CameraRegistry([camera]),
                      alerts_store=alerts_db)
    return store, alerts_db


class TestKnivesAreOptional:
    def test_no_camera_running_weapons_means_no_stage_rule_or_ask_query(self, tmp_path):
        from vg.ask import QUERY_IDS

        store, alerts_db = _alerts_live(tmp_path, _camera(["counting"]))
        try:
            assert "weapons" not in [s.key for s in store.health().pipeline]
            settings = store.alert_settings()
            assert "weapon" not in [r.kind for r in settings.rules]
            assert not any(u.kind == "weapon" for u in settings.unreached)
            assert "weapons" not in QUERY_IDS
        finally:
            alerts_db.close_db()

    def test_a_camera_running_weapons_brings_the_stage_and_rule_back(self, tmp_path):
        store, alerts_db = _alerts_live(tmp_path, _camera(["counting", "weapons"]))
        try:
            stage = next(s for s in store.health().pipeline if s.key == "weapons")
            # Switched on but not running: the stage says so, it is not hidden.
            assert not stage.healthy and stage.detail
            assert "weapon" in [r.kind for r in store.alert_settings().rules]
        finally:
            alerts_db.close_db()

    def test_a_disabled_camera_does_not_count(self, tmp_path):
        store, alerts_db = _alerts_live(
            tmp_path, _camera(["weapons"], enabled=False))
        try:
            assert "weapons" not in [s.key for s in store.health().pipeline]
        finally:
            alerts_db.close_db()

    def test_the_shipped_cameras_do_not_run_weapons(self):
        assert not any("weapons" in c.features for c in vgconfig.load().cameras)


# ---------------------------------------------------------------------------
# US5: one address - the engine serves the built console
# ---------------------------------------------------------------------------

NAVIGATE = {"Sec-Fetch-Mode": "navigate", "Accept": "text/html,application/xhtml+xml"}


@pytest.fixture
def console_dir(tmp_path):
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><div id=root></div>")
    (folder / "assets" / "index-abc123.js").write_text("console.log(1)")
    (folder / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the folder")
    return folder


def _console_app(monkeypatch, user_store, folder):
    monkeypatch.delenv(dev_signin.ENV, raising=False)
    if folder is None:
        monkeypatch.delenv("VG_CONSOLE_DIR", raising=False)
    else:
        monkeypatch.setenv("VG_CONSOLE_DIR", str(folder))
    app_module.set_store(MockStore())
    application = create_app()
    application.state.users = user_store
    return application


@pytest.fixture
def console_app(monkeypatch, user_store, console_dir):
    return _console_app(monkeypatch, user_store, console_dir)


class TestConsole:
    def test_the_page_needs_no_session(self, console_app):
        response = TestClient(console_app).get("/")
        assert response.status_code == 200
        assert "id=root" in response.text
        assert response.headers["cache-control"] == "no-cache"

    def test_assets_and_top_level_files_need_no_session(self, console_app):
        client = TestClient(console_app)
        assert client.get("/assets/index-abc123.js").status_code == 200
        assert client.get("/favicon.svg").status_code == 200

    def test_a_reload_on_a_console_route_gets_the_page(self, console_app):
        response = TestClient(console_app).get("/cameras", headers=NAVIGATE)
        assert response.status_code == 200
        assert "id=root" in response.text

    def test_the_api_is_still_closed(self, console_app):
        """A fetch is not a navigation: same path, same refusal as ever."""
        assert TestClient(console_app).get("/cameras").status_code == 401

    def test_nothing_outside_the_folder(self, console_app):
        client = TestClient(console_app)
        assert client.get("/../secret.txt").status_code in (401, 404)
        assert client.get("/assets/../../secret.txt").status_code in (401, 404)
        assert "outside" not in client.get("/%2e%2e/secret.txt").text

    def test_the_engines_own_pages_stay_the_engines(self, console_app):
        response = TestClient(console_app).get("/openapi.json", headers=NAVIGATE)
        assert "id=root" not in response.text

    def test_writes_are_never_served_from_the_folder(self, console_app):
        assert TestClient(console_app).post("/").status_code != 200

    def test_an_unbuilt_console_says_so(self, monkeypatch, tmp_path, user_store):
        application = _console_app(monkeypatch, user_store, tmp_path / "empty")
        response = TestClient(application).get("/")
        assert response.status_code == 503
        assert "not built" in response.text
        # The API still runs.
        assert TestClient(application).get("/healthz").status_code == 200

    def test_the_workstation_serves_no_console(self, monkeypatch, user_store):
        application = _console_app(monkeypatch, user_store, None)
        assert TestClient(application).get("/", headers=NAVIGATE).status_code == 401

    def test_a_relative_folder_is_read_from_the_repo_root(self, monkeypatch):
        monkeypatch.setenv("VG_CONSOLE_DIR", "web/dist")
        assert app_module._console_dir() == vgconfig.REPO_DIR / "web" / "dist"


# ---------------------------------------------------------------------------
# US5: clips saved on Linux play in the browser
# ---------------------------------------------------------------------------

class TestLinuxEncoder:
    def test_linux_tries_the_ffmpeg_program_before_mp4v(self, monkeypatch):
        monkeypatch.setattr(encoder.sys, "platform", "linux")
        assert encoder.candidates() == (
            encoder.FFMPEG_H264, encoder.PIPE_X264, encoder.FFMPEG_MP4V)

    def test_windows_keeps_media_foundation_first(self, monkeypatch):
        monkeypatch.setattr(encoder.sys, "platform", "win32")
        assert encoder.candidates() == (
            encoder.MSMF_H264, encoder.FFMPEG_H264, encoder.FFMPEG_MP4V)

    def test_an_ffmpeg_without_x264_first_on_path_does_not_hide_one_with_it(self, monkeypatch):
        monkeypatch.setattr(encoder, "_ffmpeg_candidates",
                            lambda: ["/opt/conda/bin/ffmpeg", "/usr/bin/ffmpeg"])

        class Listed:
            def __init__(self, exe):
                self.stdout = (b" V..... libx264  H.264\n" if exe == "/usr/bin/ffmpeg"
                               else b" V..... mpeg4  MPEG-4\n")

        monkeypatch.setattr(encoder.subprocess, "run", lambda cmd, **_: Listed(cmd[0]))
        encoder._ffmpeg_with_x264.cache_clear()
        try:
            assert encoder._ffmpeg_with_x264() == "/usr/bin/ffmpeg"
        finally:
            encoder._ffmpeg_with_x264.cache_clear()

    def test_vg_ffmpeg_is_asked_first(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg"
        exe.write_text("")
        monkeypatch.setenv("VG_FFMPEG", str(exe))
        assert encoder._ffmpeg_candidates()[0] == str(exe)

    def test_no_ffmpeg_means_not_opened(self, monkeypatch, tmp_path):
        monkeypatch.setattr(encoder, "_ffmpeg_with_x264", lambda: None)
        writer = encoder.PipeWriter(tmp_path / "x.mp4", 15, 64, 64)
        assert not writer.isOpened()
        writer.release()

    def test_the_pipe_writes_h264_a_browser_plays(self, tmp_path):
        """Real frames through the real program, then ask ffprobe what it wrote."""
        if encoder._ffmpeg_with_x264() is None or shutil.which("ffprobe") is None:
            pytest.skip("ffmpeg with libx264, or ffprobe, is not on PATH")
        path = tmp_path / "clip.mp4"
        writer = encoder.PipeWriter(path, 15, 320, 240)
        assert writer.isOpened()
        for i in range(30):
            writer.write(np.full((240, 320, 3), i * 8, dtype=np.uint8))
        writer.release()

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,pix_fmt,nb_frames",
             "-of", "json", str(path)],
            capture_output=True, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["pix_fmt"] == "yuv420p"
        assert int(stream["nb_frames"]) == 30

    def test_open_writer_reaches_the_pipe_on_linux(self, monkeypatch, tmp_path):
        """With OpenCV's own avc1 refused, Linux lands on the pipe, not on mp4v."""
        if encoder._ffmpeg_with_x264() is None:
            pytest.skip("ffmpeg with libx264 is not on PATH")
        monkeypatch.setattr(encoder.sys, "platform", "linux")
        encoder._reset_for_tests()
        real = encoder.cv2.VideoWriter

        class Refused:
            def __init__(self, *args, **kwargs):
                pass

            def isOpened(self):  # noqa: N802
                return False

            def release(self):
                pass

        def fake(path, backend, fourcc, *rest):
            if fourcc == encoder.cv2.VideoWriter_fourcc(*"avc1"):
                return Refused()
            return real(path, backend, fourcc, *rest)

        monkeypatch.setattr(encoder.cv2, "VideoWriter", fake)
        try:
            writer, chosen = encoder.open_writer(tmp_path / "c.mp4", 15, 64, 64)
            assert chosen is encoder.PIPE_X264
            writer.release()
        finally:
            encoder._reset_for_tests()


# ---------------------------------------------------------------------------
# US5: memory on System Health
# ---------------------------------------------------------------------------

class TestMemoryReading:
    def test_health_carries_whole_megabytes(self, bare_live_store):
        health = bare_live_store.health()
        assert isinstance(health.memory_used_mb, int)
        assert isinstance(health.memory_total_mb, int)
        assert 0 < health.memory_used_mb <= health.memory_total_mb

    def test_it_is_absent_not_zero_when_unreadable(self, monkeypatch, bare_live_store):
        import psutil

        def refuse():
            raise OSError("no /proc")

        monkeypatch.setattr(psutil, "virtual_memory", refuse)
        health = bare_live_store.health()
        assert health.memory_used_mb is None and health.memory_total_mb is None

    def test_it_crosses_the_wire_in_camel_case(self, bare_live_store, authed):
        app_module.set_store(bare_live_store)
        body = authed(create_app(), "it").get("/system/health").json()
        assert isinstance(body["memoryUsedMb"], int)
        assert isinstance(body["memoryTotalMb"], int)


# ---------------------------------------------------------------------------
# US5: the Ubuntu launcher and shortcut scripts
# ---------------------------------------------------------------------------

class TestLinuxScripts:
    NAMES = ["launch.sh", "tools/install-shortcut.sh"]

    @pytest.mark.parametrize("name", NAMES)
    def test_shell_syntax(self, name):
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("no bash on this machine")
        path = vgconfig.REPO_DIR / name
        done = subprocess.run([bash, "-n", str(path)], capture_output=True)
        assert done.returncode == 0, done.stderr.decode()

    @pytest.mark.parametrize("name", NAMES)
    def test_lf_endings_or_bash_cannot_run_it(self, name):
        assert b"\r\n" not in (vgconfig.REPO_DIR / name).read_bytes()

    def test_the_launcher_serves_the_console_from_the_engine(self):
        text = (vgconfig.REPO_DIR / "launch.sh").read_text()
        assert "VG_CONSOLE_DIR" in text and "pdeathsig" in text
        assert "--mock" in text and "--clip" in text and "--no-browser" in text

    def test_the_icon_is_in_assets(self):
        assert (vgconfig.REPO_DIR / "assets" / "visionguard.png").is_file()
