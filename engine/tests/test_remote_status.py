"""Remote access on System Health (spec 020, US6, P10-FR-122; T040).

The row says one of: not set up, connected (with the workstation's NetBird
address), or not connected with the reason - and "cannot read the NetBird
client" when it is there but will not answer. Every state says when it was
checked. A connected workstation whose address is not on the site certificate
warns, because every remote device would see a certificate warning.

The client is read on a background thread; System Health only reads the last
answer, so a slow or broken client never holds up a request (rule 7: the page
stays a 200). Canned outputs below are from NetBird 0.81.2's `status --json`.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from vg import config as vgconfig
from vg.api.live import LiveStore
from vg.ingest.registry import CameraRegistry
from vg.remote import status as remote_status

NOW = datetime(2026, 10, 20, 9, 5, 12, tzinfo=timezone.utc)
CLIENT = Path(r"C:\Program Files\NetBird\netbird.exe")

CONNECTED = {
    "peers": {"total": 2, "connected": 1, "details": []},
    "cliVersion": "0.81.2", "daemonVersion": "0.81.2", "daemonStatus": "Connected",
    "management": {"url": "https://api.netbird.io:443", "connected": True, "error": ""},
    "signal": {"url": "https://signal.netbird.io:443", "connected": True, "error": ""},
    "netbirdIp": "100.81.4.7/16", "fqdn": "workstation.netbird.cloud",
    "usesKernelInterface": False,
}
MANAGEMENT_DOWN = {
    **CONNECTED, "daemonStatus": "Connecting",
    "management": {"url": "https://api.netbird.io:443", "connected": False,
                   "error": "context deadline exceeded"},
}
PLAIN_CONNECTED = """Daemon version: 0.81.2
CLI version: 0.81.2
Management: Connected
Signal: Connected
Relays: 2/2 Available
FQDN: workstation.netbird.cloud
NetBird IP: 100.81.4.7/16
Interface type: Userspace
Peers count: 1/2 Connected
"""


def answers(stdout="", stderr="", code=0, raises=None):
    """A stand-in for subprocess.run that answers as the client would."""
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, code, stdout, stderr)
    run.calls = calls
    return run


def read(run, client=CLIENT):
    return remote_status.read_status(client=client, run=run, now=lambda: NOW)


class TestReadingTheClient:
    def test_not_installed_is_not_set_up(self):
        got = remote_status.read_status(client=None, run=answers(), now=lambda: NOW)
        assert (got.state, got.checked_at) == ("not_set_up", NOW)

    def test_connected_gives_the_address(self):
        got = read(answers(json.dumps(CONNECTED)))
        assert (got.state, got.address) == ("connected", "100.81.4.7")

    def test_management_down_is_not_connected_with_its_reason(self):
        got = read(answers(json.dumps(MANAGEMENT_DOWN)))
        assert got.state == "not_connected"
        assert "context deadline exceeded" in got.reason

    def test_a_device_that_needs_a_new_key_says_so(self):
        needs = {**MANAGEMENT_DOWN, "daemonStatus": "NeedsLogin",
                 "management": {"url": "", "connected": False, "error": ""}}
        got = read(answers(json.dumps(needs)))
        assert got.state == "not_connected" and "NeedsLogin" in got.reason

    def test_a_client_that_will_not_answer_cannot_be_read(self):
        got = read(answers(raises=subprocess.TimeoutExpired("netbird", 3)))
        assert got.state == "unreadable" and "3 seconds" in got.reason

    def test_a_client_that_cannot_be_run_cannot_be_read(self):
        got = read(answers(raises=PermissionError("Access is denied")))
        assert got.state == "unreadable" and "Access is denied" in got.reason

    def test_a_stopped_background_service_cannot_be_read(self):
        got = read(answers(stderr="Error: unable to get daemon status: rpc error: "
                                  "code = Unavailable desc = connection refused\n", code=1))
        assert got.state == "unreadable" and "connection refused" in got.reason

    def test_plain_text_is_read_when_json_is_not_there(self):
        got = read(answers(PLAIN_CONNECTED))
        assert (got.state, got.address) == ("connected", "100.81.4.7")

    def test_plain_text_disconnected(self):
        text = PLAIN_CONNECTED.replace("Management: Connected",
                                       "Management: Disconnected, reason: no internet")
        got = read(answers(text))
        assert got.state == "not_connected" and "no internet" in got.reason

    def test_it_asks_for_json_with_a_three_second_limit(self):
        run = answers(json.dumps(CONNECTED))
        read(run)
        [(argv, kwargs)] = run.calls
        assert argv == [str(CLIENT), "status", "--json"]
        assert kwargs["timeout"] == 3


class TestTheBackgroundReader:
    def test_it_reads_at_once_and_then_every_interval(self):
        seen = []

        def reader():
            seen.append(time.monotonic())
            return remote_status.RemoteStatus("connected", NOW, "100.81.4.7")
        background = remote_status.StatusReader(read=reader, interval=0.05)
        background.start()
        try:
            deadline = time.monotonic() + 2
            while len(seen) < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            background.stop()
        assert len(seen) >= 3
        assert background.latest.state == "connected"

    def test_nothing_read_yet_is_none(self):
        assert remote_status.StatusReader(read=lambda: None).latest is None

    def test_a_reader_that_raises_is_unreadable_not_a_dead_thread(self):
        def broken():
            raise RuntimeError("boom")
        background = remote_status.StatusReader(read=broken, interval=0.05)
        background.start()
        try:
            deadline = time.monotonic() + 2
            while background.latest is None and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            background.stop()
        assert background.latest.state == "unreadable" and "boom" in background.latest.reason


# --- the System Health row ------------------------------------------------------

class Fixed:
    def __init__(self, latest):
        self.latest = latest


def row(latest, names=("192.168.1.5", "100.81.4.7", "127.0.0.1", "localhost")):
    cfg = vgconfig.load()
    cfg = replace(cfg, timezone="Africa/Cairo",
                  tls=vgconfig.TlsConfig(names=tuple(names)) if names is not None else None)
    store = LiveStore(config=cfg, registry=CameraRegistry([]))
    store.remote_status = Fixed(latest) if latest != "absent" else None
    [stage] = [p for p in store.health().pipeline if p.key == "remote_access"]
    return stage


class TestTheRow:
    def test_connected(self):
        stage = row(remote_status.RemoteStatus("connected", NOW, "100.81.4.7"))
        assert stage.healthy and stage.severity.value == "info"
        assert stage.detail == "Connected as 100.81.4.7. Checked 12:05:12."   # Cairo, +3

    def test_connected_but_not_on_the_certificate_warns(self):
        stage = row(remote_status.RemoteStatus("connected", NOW, "100.81.4.7"),
                    names=("192.168.1.5", "127.0.0.1"))
        assert not stage.healthy and stage.severity.value == "warn"
        assert "not on the site certificate" in stage.detail
        assert "Checked 12:05:12." in stage.detail

    def test_not_set_up_is_not_a_fault(self):
        stage = row(remote_status.RemoteStatus("not_set_up", NOW))
        assert stage.healthy
        assert stage.detail.startswith("Not set up - NetBird is not installed")

    def test_not_connected_gives_the_reason(self):
        stage = row(remote_status.RemoteStatus("not_connected", NOW, None, "no internet"))
        assert not stage.healthy and stage.severity.value == "warn"
        assert stage.detail == "Not connected - no internet. Checked 12:05:12."

    def test_unreadable_says_so_and_why(self):
        stage = row(remote_status.RemoteStatus("unreadable", NOW, None, "Access is denied"))
        assert not stage.healthy
        assert stage.detail == ("Not connected - cannot read the NetBird client: "
                                "Access is denied. Checked 12:05:12.")

    def test_before_the_first_check(self):
        stage = row(None)
        assert stage.healthy and stage.detail == "Checking now."

    def test_no_reader_at_all(self):
        stage = row("absent")
        assert stage.healthy and stage.detail.startswith("Not checked")

    def test_health_never_runs_the_client_itself(self, monkeypatch):
        def no(*a, **k):
            raise AssertionError("health() ran a program")
        monkeypatch.setattr(subprocess, "run", no)
        monkeypatch.setattr(subprocess, "Popen", no)
        row(remote_status.RemoteStatus("connected", NOW, "100.81.4.7"))


def test_system_health_is_200_whatever_the_client(authed, user_store):
    from vg.api import app as app_module
    from vg.api.store import MockStore

    cfg = vgconfig.load()
    store = LiveStore(config=cfg, registry=CameraRegistry([]))
    store.remote_status = Fixed(remote_status.RemoteStatus(
        "unreadable", NOW, None, "the client crashed"))
    app_module.set_store(store)
    try:
        answer = authed(app_module.create_app()).get("/system/health")
    finally:
        app_module.set_store(MockStore())
    assert answer.status_code == 200
    [stage] = [p for p in answer.json()["pipeline"] if p["key"] == "remote_access"]
    assert "the client crashed" in stage["detail"]
