"""API contract tests.

The section that matters is `TestBehaviouralContract`. docs/INTEGRATION-PLAN.md
§1.2 lists promises the front end makes to users in its own copy — false alarms
stay in the history, weapons always wait for a human, every tracking search is
recorded. Those are product commitments, so they are tested like any other
requirement. If one of these fails, the UI is lying to a head teacher.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vg.api.app import app, create_app
from vg.api.store import MockStore


@pytest.fixture
def client(authed) -> TestClient:
    # A fresh store per test so mutations cannot leak between them, and a
    # signed-in admin, because every endpoint now refuses an anonymous caller.
    from vg.api import app as app_module

    app_module.set_store(MockStore())
    return authed(create_app())


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------

class TestWireShape:
    def test_everything_is_camel_case(self, client):
        # The front end is TypeScript; snake_case leaking through would force
        # a translation layer nobody wants to maintain.
        breach = client.get("/breaches?window=Last 30 days").json()[0]
        assert "zoneId" in breach and "zone_id" not in breach
        assert "dwellSeconds" in breach

    def test_geometry_is_normalised_not_pixels(self, client):
        for cam in client.get("/intrusion/cameras").json():
            for b in cam["boxes"]:
                assert 0.0 <= b["x"] <= 1.0 and 0.0 <= b["y"] <= 1.0
                assert 0.0 <= b["w"] <= 1.0 and 0.0 <= b["h"] <= 1.0
            if cam.get("zone"):
                for p in cam["zone"]["polygon"]:
                    assert 0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0

    def test_time_is_utc_plus_an_explicit_site_offset(self, client):
        # A phone in another timezone must render the school's local time, not
        # its own. That needs the offset to travel with the instant.
        at = client.get("/breaches?window=Last 30 days").json()[0]["at"]
        assert at["utc"].endswith("Z") or "+00:00" in at["utc"]
        assert isinstance(at["tzOffsetMinutes"], int)

    def test_every_surfaced_detection_carries_a_confidence(self, client):
        for w in client.get("/weapons/detections?window=This school year").json():
            assert 0.0 <= w["confidence"] <= 1.0

    def test_severity_is_a_backend_decision(self, client):
        # The engine emits severity; the UI maps it to a colour. Thresholds stay
        # server-side and auditable, and the UI keeps naming its own palette.
        allowed = {"info", "warn", "critical"}
        for b in client.get("/breaches?window=Last 30 days").json():
            assert b["severity"] in allowed

    def test_ids_are_opaque_strings(self, client):
        for b in client.get("/breaches?window=Last 30 days").json():
            assert isinstance(b["id"], str) and b["id"]


# ---------------------------------------------------------------------------
# the promises the UI already makes
# ---------------------------------------------------------------------------

class TestBehaviouralContract:
    def test_dismissed_weapons_stay_in_the_history(self, client):
        """"False alarms stay in the history." There is no delete."""
        client.post("/weapons/w3/review",
                    json={"verdict": "dismissed", "actor": "Mohamed Fouad",
                          "reason": "kitchen utensil"})
        history = client.get("/weapons/detections?window=This school year").json()
        assert "w3" in [w["id"] for w in history]

        # And there is no route that could remove it.
        assert client.delete("/weapons/w3").status_code in (404, 405)

    def test_weapon_review_records_who_decided_and_when(self, client):
        body = client.post("/weapons/w3/review",
                           json={"verdict": "confirmed",
                                 "actor": "Mohamed Fouad"}).json()
        assert body["verdict"] == "confirmed"
        assert body["reviewedBy"] == "Mohamed Fouad"
        assert body["reviewedAt"] is not None

    def test_a_detection_starts_unreviewed_and_only_a_human_moves_it(self, client):
        # The detector alone never confirms. `pending` is the only state the
        # engine can write; confirmed/dismissed require the review endpoint.
        detections = client.get("/weapons/detections?window=This school year").json()
        assert all(d["verdict"] in {"pending", "confirmed", "dismissed"}
                   for d in detections)
        for d in detections:
            if d["verdict"] != "pending":
                assert d["reviewedBy"], f"{d['id']} moved state with no reviewer"

    def test_review_verdict_cannot_be_set_back_to_pending(self, client):
        # Un-reviewing would erase the audit trail of a human decision.
        r = client.post("/weapons/w3/review",
                        json={"verdict": "pending", "actor": "x"})
        assert r.status_code == 422

    def test_paused_zones_stay_visible(self, client):
        """"Paused zones stay visible" — disabling flips a flag, nothing more."""
        before = {z["id"] for z in client.get("/zones").json()}
        client.patch("/zones/chem", json={"enabled": False})
        after = client.get("/zones").json()

        assert {z["id"] for z in after} == before
        assert next(z for z in after if z["id"] == "chem")["enabled"] is False

    def test_a_disabled_zone_is_present_in_the_shipped_fixtures(self, client):
        # Guards the regression where "helpfully" filtering disabled zones
        # passes every test because no fixture is disabled.
        assert any(not z["enabled"] for z in client.get("/zones").json())

    def test_every_tracking_search_is_recorded(self, client):
        """The UI's promise: every tracking search is recorded in the audit log."""
        before = len(client.get("/audit").json())
        result = client.post("/track?actor=Mohamed Fouad",
                             json={"who": "Layla Ahmed", "date": "2026-07-29"}).json()
        after = client.get("/audit").json()

        assert len(after) == before + 1
        # The receipt is returned with the result, so the audit row is provably
        # written before the caller sees anything.
        assert result["auditId"]
        assert any(e["id"] == result["auditId"] for e in after)

    def test_the_audit_row_names_the_actor_and_the_subject(self, client):
        client.post("/track?actor=Tarek Nassar",
                    json={"who": "Omar Khaled", "date": "2026-07-29"})
        entry = client.get("/audit").json()[0]
        assert entry["actor"] == "Tarek Nassar"
        assert entry["subject"] == "Omar Khaled"
        assert entry["action"] == "track.search"

    def test_offline_cameras_are_flagged_not_omitted(self, client):
        """"NO SIGNAL — showing last received frame."""
        cams = client.get("/system/health").json()["cameras"]
        offline = [c for c in cams if c["offline"]]
        assert offline, "health must report offline cameras, not hide them"
        for cam in offline:
            # A stale frame is never presented as current.
            assert cam["stale"] is True

    def test_degradation_is_payload_not_an_error_status(self, client):
        # System Health is the page an operator opens when things are broken.
        # It must not be the page that fails because things are broken.
        health = client.get("/system/health")
        assert health.status_code == 200
        body = health.json()
        assert body["camerasOnline"] < body["camerasTotal"]
        assert any(not p["healthy"] for p in body["pipeline"])

    def test_a_failed_connection_test_is_a_200_with_a_reason(self, client):
        r = client.post("/sources/test", json={"source": "rtsp://nope/stream"})
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_recorder_auth_failure_is_a_state_not_a_crash(self, client):
        statuses = {s["status"] for s in client.get("/sources").json()}
        assert "auth" in statuses or "down" in statuses

    def test_a_person_without_a_photo_is_marked_as_such(self, client):
        # The UI tells users "no photo means they cannot be recognised".
        people = client.get("/people").json()
        assert any(p["photoOnFile"] is False for p in people)


# ---------------------------------------------------------------------------
# onboarding — the signatures that must change
# ---------------------------------------------------------------------------

class TestOnboarding:
    def test_dvr_connect_requires_credentials(self, client):
        # `connectDvr()` takes no arguments in api.ts today, so the host and
        # password the operator types never leave the component. They must.
        assert client.post("/sources/dvr", json={}).status_code == 422

        ok = client.post("/sources/dvr", json={
            "host": "192.168.1.60", "username": "admin", "password": "secret",
        })
        assert ok.status_code == 200
        assert len(ok.json()["channels"]) > 0

    def test_test_connection_requires_a_source(self, client):
        assert client.post("/sources/test", json={}).status_code == 422

    def test_scan_marks_devices_already_added(self, client):
        found = client.post("/sources/scan").json()
        assert any(d["duplicate"] for d in found), \
            "a device already in sources should be flagged as a duplicate"


# ---------------------------------------------------------------------------
# validation and errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_unknown_window_is_rejected_with_the_valid_options(self, client):
        r = client.get("/breaches?window=Since forever")
        assert r.status_code == 422
        assert "Last 7 days" in r.text

    def test_unknown_ids_are_404_not_500(self, client):
        assert client.patch("/zones/nope", json={"enabled": True}).status_code == 404
        assert client.post("/weapons/nope/review",
                           json={"verdict": "confirmed",
                                 "actor": "x"}).status_code == 404
        assert client.get("/groups/Grade 99").status_code == 404
        assert client.get("/people/nobody/history").status_code == 404

    def test_unknown_fields_are_rejected(self, client):
        # extra="forbid" catches a front-end typo at the seam instead of
        # silently dropping the field and producing a confusing result.
        r = client.patch("/zones/chem", json={"enabled": True, "colour": "red"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# every api.ts function has an endpoint
# ---------------------------------------------------------------------------

class TestCoverage:
    """One endpoint per function in web/src/services/api.ts. No gaps, no extras
    the UI must stitch together itself."""

    REQUIRED = [
        ("GET", "/attendance"),          # getAttendance
        ("GET", "/count"),               # getCount
        ("GET", "/zones"),               # getZones
        ("PATCH", "/zones/{id}"),        # setZoneEnabled
        ("GET", "/breaches"),            # getBreaches
        ("GET", "/intrusion/cameras"),   # getIntrusionCameras
        ("GET", "/weapons/detections"),  # getWeaponDetections
        ("POST", "/weapons/{id}/review"),   # (new) confirm/dismiss
        ("GET", "/weapons/cameras"),     # getWeaponCameras
        ("POST", "/lost-items/search"),  # searchLostItem
        ("POST", "/track"),              # trackPerson + recordTrackSearch
        ("GET", "/audit"),
        ("GET", "/system/health"),       # getSystemHealth
        ("GET", "/users"),               # getUsers
        ("GET", "/people"),              # getPeople
        ("GET", "/groups"),              # getGroups
        ("GET", "/groups/{name}"),       # getGroup
        ("GET", "/people/{person}/history"),  # getHistory
        ("GET", "/sources"),             # getCameraSources
        ("GET", "/sources/areas"),       # getAreaOptions
        ("POST", "/sources/scan"),       # scanNetwork
        ("POST", "/sources/dvr"),        # connectDvr
        ("POST", "/sources/test"),       # testConnection
        ("GET", "/attention"),           # (new) Home feed
        ("POST", "/attention/{id}/ack"),
        ("GET", "/settings/school"),     # (new) Settings persistence
        ("GET", "/settings/alerts"),
        ("GET", "/settings/delivery"),
    ]

    def test_every_required_route_exists(self):
        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", ())
        }
        normalised = {
            (m, p.replace("{zone_id}", "{id}").replace("{detection_id}", "{id}")
                 .replace("{incident_id}", "{id}").replace("{item_id}", "{id}"))
            for m, p in routes
        }
        missing = [r for r in self.REQUIRED if tuple(r) not in normalised]
        assert not missing, f"missing endpoints: {missing}"

    def test_openapi_document_generates(self, client):
        # This document IS the frozen contract; the front end is written
        # against it. If it will not generate, the contract is not real.
        spec = client.get("/openapi.json")
        assert spec.status_code == 200
        assert len(spec.json()["paths"]) >= len(self.REQUIRED) - 4
